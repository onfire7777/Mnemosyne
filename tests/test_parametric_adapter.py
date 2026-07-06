"""Unit tests for the pure-Python parametric-tier memory adapter (B9, no-GPU)."""

from __future__ import annotations

import math

from mnemosyne import parametric_adapter as pa


def _separable_dataset() -> tuple[list[list[float]], list[int]]:
    """Two linearly separable clusters in 8-D (deterministic)."""
    features: list[list[float]] = []
    labels: list[int] = []
    for i in range(20):
        base = 1.0 + (i % 5) * 0.05
        features.append([base, base + 0.1, 0.2, -0.1, 0.05, 0.0, 0.3, base * 0.5])
        labels.append(1)
    for i in range(20):
        base = -1.0 - (i % 5) * 0.05
        features.append([base, base - 0.1, -0.2, 0.1, -0.05, 0.0, -0.3, base * 0.5])
        labels.append(0)
    return features, labels


def test_train_and_evaluate_separable() -> None:
    feats, labels = _separable_dataset()
    adapter = pa.train_logistic_adapter(feats, labels, l2=0.5, epochs=200, lr=0.5)
    result = pa.evaluate(adapter, feats, labels)
    assert result["accuracy"] == 1.0
    assert adapter["adapter_kind"] == pa.ADAPTER_KIND
    assert adapter["dims"] == 8


def test_training_is_deterministic() -> None:
    feats, labels = _separable_dataset()
    a1 = pa.serialize(pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=50, lr=0.3, backend="pure-python"))
    a2 = pa.serialize(pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=50, lr=0.3, backend="pure-python"))
    assert a1 == a2
    assert len(pa.sha256_hex(a1)) == 64


def test_serialize_roundtrip_preserves_scores() -> None:
    feats, labels = _separable_dataset()
    adapter = pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=80, lr=0.4, backend="pure-python")
    blob = pa.serialize(adapter)
    restored = pa.deserialize(blob)
    for row in feats:
        assert math.isclose(pa.score(adapter, row), pa.score(restored, row), rel_tol=0, abs_tol=0.0)


def test_backend_resolution_and_capabilities() -> None:
    assert pa.resolve_backend("pure-python") == "pure-python"
    assert pa.resolve_backend("auto") in pa._VALID_BACKENDS
    assert pa.resolve_backend("auto", env={"MNEMOSYNE_PARAMETRIC_BACKEND": "pure-python"}) == "pure-python"
    caps = pa.capabilities()
    assert set(caps) == {"numpy", "torch", "device", "auto_backend"}
    # pure-python is always a valid floor even with no accelerator installed.
    adapter = pa.train_logistic_adapter(*_separable_dataset(), epochs=30, backend="pure-python")
    assert adapter["training_backend"]["backend"] == "pure-python"


def test_numpy_backend_agrees_with_pure_python() -> None:
    if not pa.has_numpy():
        import pytest

        pytest.skip("numpy not installed")
    feats, labels = _separable_dataset()
    ref = pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=200, lr=0.5, backend="pure-python")
    npy = pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=200, lr=0.5, backend="numpy")
    # Same objective + same init/steps -> predictions and scores must match.
    for row in feats:
        assert math.isclose(pa.score(ref, row), pa.score(npy, row), rel_tol=1e-9, abs_tol=1e-9)
    assert npy["training_backend"]["backend"] == "numpy"


def test_torch_backend_trains_on_available_device() -> None:
    if not pa.has_torch():
        import pytest

        pytest.skip("torch not installed")
    feats, labels = _separable_dataset()
    # auto device picks the best accelerator (cuda > mps > cpu); GPU dtypes
    # (float32 on MPS/CUDA) must train without error and still converge.
    adapter = pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=200, lr=0.5, backend="torch", device="auto")
    assert adapter["training_backend"]["backend"] == "torch"
    assert pa.evaluate(adapter, feats, labels)["accuracy"] == 1.0
    # a torch-trained adapter serves through the identical stdlib scoring path
    blob = pa.serialize(adapter)
    restored = pa.deserialize(blob)
    assert pa.predict(restored, feats[0]) == labels[0]


def test_gate_margin_over_baseline_is_positive() -> None:
    feats, labels = _separable_dataset()
    adapter = pa.train_logistic_adapter(feats, labels, l2=0.5, epochs=200, lr=0.5)
    baseline = pa.majority_baseline(labels)
    adapter_acc = pa.evaluate(adapter, feats, labels)["accuracy"]
    baseline_acc = pa.baseline_accuracy(baseline, labels)
    assert adapter_acc - baseline_acc > 0.01


def test_score_bounds() -> None:
    feats, labels = _separable_dataset()
    adapter = pa.train_logistic_adapter(feats, labels, l2=1.0, epochs=50, lr=0.3)
    for row in feats:
        p = pa.score(adapter, row)
        assert 0.0 <= p <= 1.0
