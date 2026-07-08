"""Hardware capability probe, tier mapping, and advisory env recommendations.

Generalizes the ``parametric_adapter.py`` capability pattern (pure-python ->
numpy -> torch cpu/cuda/mps) into a machine-wide probe that self-describes
what the host can do and maps it to a declared profile tier:

  * ``floor``       -- < 9 GiB RAM or no ``mnemosyne_native`` extension.
  * ``standard``    -- CPU-only host with >= 9 GiB RAM and native kernels.
  * ``accelerated`` -- a torch accelerator (CUDA or Apple MPS) is available.
  * ``frontier``    -- never detected; explicit ``MNEMOSYNE_CAPABILITY_TIER=frontier`` only.

Advisory-first, no silent behavior change: :func:`recommended_env` returns
RECOMMENDATIONS keyed to knobs that already exist elsewhere in the codebase
(``MNEMOSYNE_PARAMETRIC_BACKEND``/``MNEMOSYNE_PARAMETRIC_DEVICE`` from
``parametric_adapter.py``, ``MNEMOSYNE_EMBED_BATCH_SIZE`` from
``consolidation.py``, ``MNEMOSYNE_PARALLEL_CHANNELS`` from ``pipeline.py``,
plus an ``OLLAMA_MODEL`` suggestion for the production role-LLM stack). It
deliberately recommends nothing for rerank width or PPR iteration count —
``rerank_width`` is an ``OperatingPolicy`` tunable (not env-configurable) and
no PPR-iteration env knob exists, so there is nothing to key a recommendation to.

The only mutating entry point, :func:`apply`, is reached at runtime solely via
:func:`maybe_autotune`, which is a strict no-op unless the operator opted in
with ``MNEMOSYNE_CAPABILITY_AUTOTUNE=1`` — and even then it fills env defaults
ONLY for keys the operator has not set. Both env vars are registered in
CONFIG-DRIFT-CHECKS.md.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import subprocess
import sys
from typing import Any, MutableMapping

TIERS = ("floor", "standard", "accelerated", "frontier")

#: Explicit tier override; always wins over detection. Registered in
#: CONFIG-DRIFT-CHECKS.md. ``frontier`` is reachable only through this env.
TIER_ENV = "MNEMOSYNE_CAPABILITY_TIER"

#: Default-OFF opt-in for :func:`maybe_autotune`. Registered in
#: CONFIG-DRIFT-CHECKS.md.
AUTOTUNE_ENV = "MNEMOSYNE_CAPABILITY_AUTOTUNE"

#: Below this much total RAM (GiB) the host maps to the ``floor`` tier.
FLOOR_MAX_RAM_GB = 9.0

#: Presence of any of these (pre-existing) env vars marks an accelerated /
#: hosted LLM endpoint as configured. Read-only presence probe — values are
#: never read or echoed here.
_HOSTED_LLM_ENV_VARS = (
    "OLLAMA_HOST",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "MNEMOSYNE_EMBEDDING_URL",
    "MNEMOSYNE_RERANKER_URL",
)

_TRUTHY = {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Probing (stdlib-first; torch probe is import-guarded)
# --------------------------------------------------------------------------- #
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def total_ram_bytes() -> int | None:
    """Total physical RAM in bytes, or None when it cannot be determined.

    Darwin needs the sysctl route: ``os.sysconf('SC_PHYS_PAGES')`` is not a
    reliable phys-pages source there, while ``hw.memsize`` is authoritative.
    """
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            return int(out)
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return int(pages) * int(page_size)
    except Exception:  # noqa: BLE001 - a probe must never crash the caller
        return None
    return None


def _torch_accelerators() -> dict[str, bool]:
    facts = {"torch": False, "cuda": False, "mps": False}
    if not _has_module("torch"):
        return facts
    facts["torch"] = True
    try:
        import torch

        facts["cuda"] = bool(torch.cuda.is_available())
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        facts["mps"] = bool(mps is not None and mps.is_available())
    except Exception:  # noqa: BLE001 - a probe must never crash the caller
        pass
    return facts


def probe(env: MutableMapping[str, str] | None = None) -> dict[str, Any]:
    """Gather host capability facts. Read-only; never raises."""
    env = os.environ if env is None else env
    ram_bytes = total_ram_bytes()
    ram_gb = round(ram_bytes / 1024**3, 2) if ram_bytes is not None else None
    hosted_vars = [name for name in _HOSTED_LLM_ENV_VARS if env.get(name)]
    facts: dict[str, Any] = {
        "platform": sys.platform,
        "machine": platform.machine(),
        "apple_silicon": sys.platform == "darwin" and platform.machine() == "arm64",
        "cpu_count": os.cpu_count(),
        "total_ram_bytes": ram_bytes,
        "total_ram_gb": ram_gb,
        "numpy": _has_module("numpy"),
        "native": _has_module("mnemosyne_native"),
        "pure_forced": env.get("MNEMOSYNE_PURE") == "1",
        "hosted_llm_env_present": bool(hosted_vars),
        "hosted_llm_env_vars": hosted_vars,
    }
    facts.update(_torch_accelerators())
    return facts


# --------------------------------------------------------------------------- #
# Tier mapping
# --------------------------------------------------------------------------- #
def _detected_tier(facts: dict[str, Any]) -> str:
    ram_gb = facts.get("total_ram_gb")
    # Unknown RAM maps conservatively to the floor tier.
    if not facts.get("native") or ram_gb is None or ram_gb < FLOOR_MAX_RAM_GB:
        return "floor"
    if facts.get("cuda") or facts.get("mps"):
        return "accelerated"
    return "standard"


def resolve_tier(
    facts: dict[str, Any] | None = None,
    env: MutableMapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve (tier, source); source is ``"env"`` or ``"detected"``.

    ``MNEMOSYNE_CAPABILITY_TIER`` always wins when it names a valid tier; an
    unrecognized value is ignored (the probe stays advisory and non-fatal) and
    detection applies.
    """
    env = os.environ if env is None else env
    override = (env.get(TIER_ENV) or "").strip().lower()
    if override in TIERS:
        return override, "env"
    if facts is None:
        facts = probe(env=env)
    return _detected_tier(facts), "detected"


# --------------------------------------------------------------------------- #
# Recommendations (advisory only) + opt-in autotune
# --------------------------------------------------------------------------- #
def recommended_env(tier: str, facts: dict[str, Any] | None = None) -> dict[str, str]:
    """Recommended env values for ``tier`` — recommendations ONLY, never applied here.

    Every key is a knob that already exists elsewhere; values are clamped to
    what the probed host can actually run (never recommend ``torch``/``numpy``
    backends that would make ``parametric_adapter.resolve_backend`` raise).
    """
    if tier not in TIERS:
        raise ValueError(f"unknown capability tier {tier!r}; valid: {TIERS}")
    if facts is None:
        facts = probe()
    wants_parallel = tier != "floor"
    wants_accel = tier in ("accelerated", "frontier")
    if wants_accel and facts.get("torch"):
        backend = "torch"
    elif tier != "floor" and facts.get("numpy"):
        backend = "numpy"
    else:
        backend = "pure-python"
    if backend == "torch" and facts.get("cuda"):
        device = "cuda"
    elif backend == "torch" and facts.get("mps"):
        device = "mps"
    else:
        device = "cpu"
    batch = {"floor": "8", "standard": "32", "accelerated": "64", "frontier": "128"}[tier]
    return {
        "MNEMOSYNE_PARAMETRIC_BACKEND": backend,
        "MNEMOSYNE_PARAMETRIC_DEVICE": device,
        "MNEMOSYNE_EMBED_BATCH_SIZE": batch,
        "MNEMOSYNE_PARALLEL_CHANNELS": "1" if wants_parallel else "0",
        "OLLAMA_MODEL": "qwen3:4b" if wants_accel else "qwen3:0.6b",
    }


def autotune_enabled(env: MutableMapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return (env.get(AUTOTUNE_ENV) or "").strip().lower() in _TRUTHY


def apply(
    env: MutableMapping[str, str] | None = None,
    *,
    facts: dict[str, Any] | None = None,
    tier: str | None = None,
) -> dict[str, str]:
    """Fill env defaults from :func:`recommended_env`; return what was set.

    Only keys NOT already present in ``env`` are filled — an operator-set
    value (even an empty one) is never overwritten (precedence: human wins).
    """
    env = os.environ if env is None else env
    if tier is None:
        tier, _ = resolve_tier(facts=facts, env=env)
    applied: dict[str, str] = {}
    for key, value in recommended_env(tier, facts=facts).items():
        if key not in env:
            env[key] = value
            applied[key] = value
    return applied


def maybe_autotune(env: MutableMapping[str, str] | None = None) -> dict[str, str]:
    """Early startup hook: strict no-op unless ``MNEMOSYNE_CAPABILITY_AUTOTUNE=1``."""
    env = os.environ if env is None else env
    if not autotune_enabled(env):
        return {}
    try:
        return apply(env)
    except Exception:  # noqa: BLE001 - opt-in tuning must never break startup
        return {}
