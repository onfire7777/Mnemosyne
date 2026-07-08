"""Lane D (P5) capability tiering: probe fakes, tier mapping, env override,
opt-in autotune only-fills-unset semantics, and the read-only CLI surface."""

from __future__ import annotations

import json
from typing import Any

import pytest

from mnemosyne import capability
from mnemosyne.cli import main as cli_main


def _facts(**overrides: Any) -> dict[str, Any]:
    """A plausible probed-fact dict; tests force the axes they exercise."""
    base: dict[str, Any] = {
        "platform": "darwin",
        "machine": "arm64",
        "apple_silicon": True,
        "cpu_count": 8,
        "total_ram_bytes": 16 * 1024**3,
        "total_ram_gb": 16.0,
        "numpy": True,
        "native": True,
        "pure_forced": False,
        "hosted_llm_env_present": False,
        "hosted_llm_env_vars": [],
        "torch": False,
        "cuda": False,
        "mps": False,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Tier mapping under forced probe fakes
# --------------------------------------------------------------------------- #

def test_tier_floor_on_low_ram() -> None:
    tier, source = capability.resolve_tier(facts=_facts(total_ram_gb=8.0), env={})
    assert (tier, source) == ("floor", "detected")


def test_tier_floor_without_native() -> None:
    tier, _ = capability.resolve_tier(facts=_facts(native=False, mps=True, torch=True), env={})
    assert tier == "floor"


def test_tier_floor_on_unknown_ram() -> None:
    facts = _facts(total_ram_bytes=None, total_ram_gb=None)
    tier, _ = capability.resolve_tier(facts=facts, env={})
    assert tier == "floor"


def test_tier_standard_on_cpu_midsize_host() -> None:
    tier, _ = capability.resolve_tier(facts=_facts(), env={})
    assert tier == "standard"


@pytest.mark.parametrize("accel", ["mps", "cuda"])
def test_tier_accelerated_when_torch_accelerator_available(accel: str) -> None:
    facts = _facts(torch=True, **{accel: True})
    tier, _ = capability.resolve_tier(facts=facts, env={})
    assert tier == "accelerated"


def test_tier_frontier_is_never_detected() -> None:
    facts = _facts(torch=True, cuda=True, total_ram_gb=256.0, hosted_llm_env_present=True)
    tier, _ = capability.resolve_tier(facts=facts, env={})
    assert tier == "accelerated"


# --------------------------------------------------------------------------- #
# Env override precedence (MNEMOSYNE_CAPABILITY_TIER always wins)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tier", capability.TIERS)
def test_tier_env_override_always_wins(tier: str) -> None:
    env = {capability.TIER_ENV: tier}
    resolved, source = capability.resolve_tier(facts=_facts(), env=env)
    assert (resolved, source) == (tier, "env")


def test_tier_env_override_is_case_insensitive() -> None:
    env = {capability.TIER_ENV: " Frontier "}
    assert capability.resolve_tier(facts=_facts(), env=env) == ("frontier", "env")


def test_tier_env_invalid_value_falls_back_to_detection() -> None:
    env = {capability.TIER_ENV: "warp-speed"}
    assert capability.resolve_tier(facts=_facts(), env=env) == ("standard", "detected")


# --------------------------------------------------------------------------- #
# Recommendations: existing knobs only, clamped to the probed host
# --------------------------------------------------------------------------- #

_EXPECTED_KEYS = {
    "MNEMOSYNE_PARAMETRIC_BACKEND",
    "MNEMOSYNE_PARAMETRIC_DEVICE",
    "MNEMOSYNE_EMBED_BATCH_SIZE",
    "MNEMOSYNE_PARALLEL_CHANNELS",
    "OLLAMA_MODEL",
}


@pytest.mark.parametrize("tier", capability.TIERS)
def test_recommended_env_keys_are_exactly_the_existing_knobs(tier: str) -> None:
    rec = capability.recommended_env(tier, facts=_facts(torch=True, mps=True))
    assert set(rec) == _EXPECTED_KEYS
    assert all(isinstance(v, str) and v for v in rec.values())


def test_recommended_env_rejects_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown capability tier"):
        capability.recommended_env("hyperscale", facts=_facts())


def test_recommended_env_floor_is_conservative() -> None:
    rec = capability.recommended_env("floor", facts=_facts(torch=True, mps=True))
    assert rec["MNEMOSYNE_PARAMETRIC_BACKEND"] == "pure-python"
    assert rec["MNEMOSYNE_PARAMETRIC_DEVICE"] == "cpu"
    assert rec["MNEMOSYNE_PARALLEL_CHANNELS"] == "0"
    assert rec["OLLAMA_MODEL"] == "qwen3:0.6b"


def test_recommended_env_standard_enables_parallel_channels() -> None:
    rec = capability.recommended_env("standard", facts=_facts(torch=False, numpy=True))
    assert rec["MNEMOSYNE_PARAMETRIC_BACKEND"] == "numpy"
    assert rec["MNEMOSYNE_PARAMETRIC_DEVICE"] == "cpu"
    assert rec["MNEMOSYNE_PARALLEL_CHANNELS"] == "1"
    assert rec["OLLAMA_MODEL"] == "qwen3:0.6b"


def test_recommended_env_accelerated_prefers_cuda_over_mps() -> None:
    rec = capability.recommended_env("accelerated", facts=_facts(torch=True, cuda=True, mps=True))
    assert rec["MNEMOSYNE_PARAMETRIC_BACKEND"] == "torch"
    assert rec["MNEMOSYNE_PARAMETRIC_DEVICE"] == "cuda"
    assert rec["MNEMOSYNE_PARALLEL_CHANNELS"] == "1"
    assert rec["OLLAMA_MODEL"] == "qwen3:4b"


def test_recommended_env_never_recommends_missing_backends() -> None:
    # An accelerated/frontier tier on a host without torch must not recommend a
    # backend that would make parametric_adapter.resolve_backend raise.
    rec = capability.recommended_env("accelerated", facts=_facts(torch=False, numpy=True))
    assert rec["MNEMOSYNE_PARAMETRIC_BACKEND"] == "numpy"
    rec = capability.recommended_env("frontier", facts=_facts(torch=False, numpy=False))
    assert rec["MNEMOSYNE_PARAMETRIC_BACKEND"] == "pure-python"
    assert rec["MNEMOSYNE_PARAMETRIC_DEVICE"] == "cpu"


# --------------------------------------------------------------------------- #
# Opt-in autotune: only-fills-unset, default-off hook
# --------------------------------------------------------------------------- #

def test_apply_fills_only_unset_keys_and_reports_what_it_set() -> None:
    env: dict[str, str] = {"MNEMOSYNE_EMBED_BATCH_SIZE": "7"}
    applied = capability.apply(env, facts=_facts(), tier="standard")
    assert env["MNEMOSYNE_EMBED_BATCH_SIZE"] == "7"  # operator value untouched
    assert "MNEMOSYNE_EMBED_BATCH_SIZE" not in applied
    assert set(applied) == _EXPECTED_KEYS - {"MNEMOSYNE_EMBED_BATCH_SIZE"}
    assert env["MNEMOSYNE_PARAMETRIC_BACKEND"] == "numpy"


def test_apply_preserves_operator_empty_string() -> None:
    env = {"MNEMOSYNE_PARALLEL_CHANNELS": ""}
    capability.apply(env, facts=_facts(torch=True, mps=True), tier="accelerated")
    assert env["MNEMOSYNE_PARALLEL_CHANNELS"] == ""


def test_apply_honors_tier_env_override() -> None:
    env = {capability.TIER_ENV: "floor"}
    applied = capability.apply(env, facts=_facts(torch=True, cuda=True))
    assert applied["MNEMOSYNE_PARAMETRIC_BACKEND"] == "pure-python"


def test_maybe_autotune_is_noop_without_flag() -> None:
    env: dict[str, str] = {}
    assert capability.maybe_autotune(env) == {}
    assert env == {}


def test_maybe_autotune_flag_off_values_are_noops() -> None:
    for raw in ("0", "false", "", "off"):
        env = {capability.AUTOTUNE_ENV: raw}
        assert capability.maybe_autotune(env) == {}
        assert env == {capability.AUTOTUNE_ENV: raw}


def test_maybe_autotune_applies_when_flag_set() -> None:
    env = {capability.AUTOTUNE_ENV: "1", capability.TIER_ENV: "floor"}
    applied = capability.maybe_autotune(env)
    assert applied  # filled the unset recommendation keys
    assert env["MNEMOSYNE_PARAMETRIC_BACKEND"] == "pure-python"
    # flag + tier override themselves are never treated as fillable knobs
    assert env[capability.AUTOTUNE_ENV] == "1"


# --------------------------------------------------------------------------- #
# CLI surface (read-only)
# --------------------------------------------------------------------------- #

@pytest.fixture
def _quiet_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(capability.AUTOTUNE_ENV, raising=False)
    monkeypatch.delenv(capability.TIER_ENV, raising=False)


def test_cli_capability_json_shape(_quiet_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["capability", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["tier"] in capability.TIERS
    assert report["tier_source"] in {"env", "detected"}
    assert report["autotune_enabled"] is False
    assert set(report["recommended_env"]) == _EXPECTED_KEYS
    facts = report["facts"]
    for key in ("platform", "machine", "apple_silicon", "cpu_count", "numpy", "torch", "cuda", "mps", "native", "hosted_llm_env_present"):
        assert key in facts


def test_cli_capability_shell_output_is_sourceable(_quiet_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["capability"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines[0].startswith("# capability tier: ")
    exports = [line for line in lines if line.startswith("export ")]
    assert {line.split("=", 1)[0].removeprefix("export ") for line in exports} == _EXPECTED_KEYS
    assert all(line.startswith("#") or line.startswith("export ") for line in lines)


def test_cli_capability_respects_env_override(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv(capability.AUTOTUNE_ENV, raising=False)
    monkeypatch.setenv(capability.TIER_ENV, "frontier")
    assert cli_main(["capability", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tier"] == "frontier"
    assert report["tier_source"] == "env"
