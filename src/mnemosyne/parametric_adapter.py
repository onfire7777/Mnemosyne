"""Device-adaptive parametric-tier memory adapter (self-hosted, CPU/GPU).

The concrete, portable instantiation of the blueprint's parametric tier (see
:class:`mnemosyne.parametric.ParametricTier`, whose docstring states "Mnemosyne
is not a foundation-model trainer"). The adapter is a small L2-regularized
logistic-regression scoring head learned over dense embeddings of already
validated memory items -- test-time training over the memory, not a
foundation-model LoRA.

No-compromise portability by capability tiering. Training runs on the best
backend available, and *every* backend optimises the identical objective to the
identical artifact schema, so the trained adapter is byte-portable and serving
is uniform regardless of where it was trained:

  * ``pure-python`` -- zero-dependency floor. Always available, trains in
    milliseconds on the least powerful machine. Deterministic reference.
  * ``numpy``       -- vectorised CPU. Same objective, ~10-100x faster on wide
    embeddings; auto-selected when numpy is importable.
  * ``torch``       -- CPU or GPU (CUDA / Apple MPS). Same objective, scales to
    large memory corpora and wider adapters; auto-selected when torch is
    importable, preferring an available accelerator.

Selection order: explicit ``backend=`` arg -> ``MNEMOSYNE_PARAMETRIC_BACKEND``
env -> best detected. Device: explicit ``device=`` -> ``MNEMOSYNE_PARAMETRIC_DEVICE``
env -> best detected (cuda > mps > cpu). Scoring/serving is always the tiny
stdlib dot-product path, so a GPU-trained adapter serves on a CPU-only host
unchanged.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from typing import Any, Sequence

ADAPTER_KIND = "linear-logistic-memory-adapter/v1"
ADAPTER_SCHEMA = "mnemosyne.parametric_adapter/v1"

_VALID_BACKENDS = ("pure-python", "numpy", "torch")


# --------------------------------------------------------------------------- #
# Capability detection + backend/device resolution
# --------------------------------------------------------------------------- #
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def has_numpy() -> bool:
    return _has_module("numpy")


def has_torch() -> bool:
    return _has_module("torch")


def detect_device(preferred: str = "auto") -> str:
    """Resolve a torch device string: cuda > mps > cpu (or an explicit choice)."""
    preferred = (preferred or "auto").strip().lower()
    if preferred not in ("", "auto"):
        return preferred
    if not has_torch():
        return "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001 - never let detection crash training
        return "cpu"
    return "cpu"


def resolve_backend(backend: str = "auto", *, env: dict[str, str] | None = None) -> str:
    """Resolve the training backend: explicit arg -> env -> best available."""
    env = os.environ if env is None else env
    choice = (backend or "auto").strip().lower()
    if choice in ("", "auto"):
        choice = (env.get("MNEMOSYNE_PARAMETRIC_BACKEND", "") or "auto").strip().lower()
    if choice in ("", "auto"):
        if has_torch():
            return "torch"
        if has_numpy():
            return "numpy"
        return "pure-python"
    if choice not in _VALID_BACKENDS:
        raise ValueError(f"unknown parametric backend {choice!r}; valid: {_VALID_BACKENDS}")
    if choice == "torch" and not has_torch():
        raise ValueError("backend 'torch' requested but torch is not installed")
    if choice == "numpy" and not has_numpy():
        raise ValueError("backend 'numpy' requested but numpy is not installed")
    return choice


def capabilities() -> dict[str, Any]:
    """Report the machine's parametric-training capabilities (for diagnostics)."""
    return {
        "numpy": has_numpy(),
        "torch": has_torch(),
        "device": detect_device("auto"),
        "auto_backend": resolve_backend("auto"),
    }


# --------------------------------------------------------------------------- #
# Shared math (standardisation) -- identical across backends
# --------------------------------------------------------------------------- #
def _sigmoid(z: float) -> float:
    if z <= -60.0:
        return 0.0
    if z >= 60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _standardize_fit(features: Sequence[Sequence[float]]) -> tuple[list[float], list[float]]:
    if not features:
        raise ValueError("cannot standardize an empty feature matrix")
    dims = len(features[0])
    n = len(features)
    mean = [0.0] * dims
    for row in features:
        if len(row) != dims:
            raise ValueError("feature rows must share a fixed dimensionality")
        for j, v in enumerate(row):
            mean[j] += v
    mean = [m / n for m in mean]
    var = [0.0] * dims
    for row in features:
        for j, v in enumerate(row):
            d = v - mean[j]
            var[j] += d * d
    inv_std = [1.0 / math.sqrt(var[j] / n + 1e-6) for j in range(dims)]
    return mean, inv_std


def _apply_standardize(row: Sequence[float], mean: Sequence[float], inv_std: Sequence[float]) -> list[float]:
    return [(row[j] - mean[j]) * inv_std[j] for j in range(len(mean))]


# --------------------------------------------------------------------------- #
# Backend training kernels -- same L2-logistic objective, same result
# --------------------------------------------------------------------------- #
def _train_pure_python(std_rows, labels, *, l2, epochs, lr):
    dims = len(std_rows[0])
    weights = [0.0] * dims
    bias = 0.0
    n = len(std_rows)
    for _ in range(epochs):
        grad_w = [0.0] * dims
        grad_b = 0.0
        for row, y in zip(std_rows, labels):
            z = bias
            for j in range(dims):
                z += weights[j] * row[j]
            err = _sigmoid(z) - float(y)
            grad_b += err
            for j in range(dims):
                grad_w[j] += err * row[j]
        bias -= lr * (grad_b / n)
        for j in range(dims):
            weights[j] -= lr * (grad_w[j] / n + l2 * weights[j] / n)
    return weights, bias


def _train_numpy(std_rows, labels, *, l2, epochs, lr):
    import numpy as np

    x = np.asarray(std_rows, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    n, dims = x.shape
    weights = np.zeros(dims, dtype=np.float64)
    bias = 0.0
    for _ in range(epochs):
        z = x @ weights + bias
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))
        err = p - y
        grad_w = x.T @ err / n + l2 * weights / n
        grad_b = float(err.sum() / n)
        weights -= lr * grad_w
        bias -= lr * grad_b
    return weights.tolist(), float(bias)


def _train_torch(std_rows, labels, *, l2, epochs, lr, device):
    import torch

    dev = torch.device(device)
    # CPU keeps float64 for parity with the pure-Python/numpy reference; GPU
    # accelerators (Apple MPS rejects float64, CUDA is far faster in float32)
    # train in float32 -- same objective, GPU-native precision.
    dtype = torch.float64 if dev.type == "cpu" else torch.float32
    x = torch.tensor(std_rows, dtype=dtype, device=dev)
    y = torch.tensor(labels, dtype=dtype, device=dev)
    n, dims = x.shape
    weights = torch.zeros(dims, dtype=dtype, device=dev)
    bias = torch.zeros((), dtype=dtype, device=dev)
    for _ in range(epochs):
        z = torch.clamp(x @ weights + bias, -60.0, 60.0)
        p = torch.sigmoid(z)
        err = p - y
        grad_w = x.t() @ err / n + l2 * weights / n
        grad_b = err.sum() / n
        weights -= lr * grad_w
        bias -= lr * grad_b
    return weights.detach().cpu().tolist(), float(bias.detach().cpu())


def train_logistic_adapter(
    features: Sequence[Sequence[float]],
    labels: Sequence[int],
    *,
    l2: float = 1.0,
    epochs: int = 300,
    lr: float = 0.5,
    adapter_kind: str = ADAPTER_KIND,
    backend: str = "auto",
    device: str = "auto",
) -> dict[str, Any]:
    """Fit the adapter on the best available backend; return a portable artifact.

    Every backend optimises the same standardised L2-logistic objective, so the
    resulting adapter dict (weights/bias + standardisation) means the same thing
    and is scored identically everywhere. ``training_backend`` records where it
    ran for provenance.
    """
    if len(features) != len(labels):
        raise ValueError("features and labels must be the same length")
    if not features:
        raise ValueError("cannot train on an empty feature matrix")
    dims = len(features[0])
    mean, inv_std = _standardize_fit(features)
    std_rows = [_apply_standardize(row, mean, inv_std) for row in features]

    resolved = resolve_backend(backend)
    used_device = "cpu"
    if resolved == "torch":
        used_device = detect_device(device)
        weights, bias = _train_torch(std_rows, [float(v) for v in labels], l2=l2, epochs=epochs, lr=lr, device=used_device)
    elif resolved == "numpy":
        weights, bias = _train_numpy(std_rows, [float(v) for v in labels], l2=l2, epochs=epochs, lr=lr)
    else:
        weights, bias = _train_pure_python(std_rows, [float(v) for v in labels], l2=l2, epochs=epochs, lr=lr)

    return {
        "schema": ADAPTER_SCHEMA,
        "adapter_kind": adapter_kind,
        "dims": dims,
        "weights": weights,
        "bias": bias,
        "feature_mean": list(mean),
        "feature_inv_std": list(inv_std),
        "hyperparams": {"l2": l2, "epochs": epochs, "lr": lr},
        "train_size": len(std_rows),
        "training_backend": {"backend": resolved, "device": used_device},
    }


# --------------------------------------------------------------------------- #
# Scoring / serving -- always stdlib, device-free, portable
# --------------------------------------------------------------------------- #
def score(adapter: dict[str, Any], feature: Sequence[float]) -> float:
    """Return P(class=1) for ``feature`` under ``adapter`` (stdlib, portable)."""
    mean = adapter["feature_mean"]
    inv_std = adapter["feature_inv_std"]
    weights = adapter["weights"]
    if len(feature) != len(weights):
        raise ValueError("feature dimensionality does not match adapter")
    z = float(adapter["bias"])
    for j in range(len(weights)):
        z += weights[j] * ((feature[j] - mean[j]) * inv_std[j])
    return _sigmoid(z)


def predict(adapter: dict[str, Any], feature: Sequence[float], *, threshold: float = 0.5) -> int:
    return 1 if score(adapter, feature) >= threshold else 0


def evaluate(adapter: dict[str, Any], features: Sequence[Sequence[float]], labels: Sequence[int]) -> dict[str, Any]:
    correct = sum(1 for row, y in zip(features, labels) if predict(adapter, row) == int(y))
    n = len(labels)
    return {"n": n, "correct": correct, "accuracy": (correct / n) if n else 0.0}


def majority_baseline(labels: Sequence[int]) -> int:
    ones = sum(1 for y in labels if int(y) == 1)
    return 1 if ones * 2 >= len(labels) else 0


def baseline_accuracy(baseline_label: int, labels: Sequence[int]) -> float:
    n = len(labels)
    if not n:
        return 0.0
    return sum(1 for y in labels if int(y) == baseline_label) / n


def serialize(adapter: dict[str, Any]) -> bytes:
    return json.dumps(adapter, sort_keys=True, separators=(",", ":")).encode("utf-8")


def deserialize(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
