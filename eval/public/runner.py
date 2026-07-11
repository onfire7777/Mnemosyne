"""Registry-driven public benchmark runner using only the CLI subprocess seam."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from eval.harness.cli_driver import MnemoCLI
from eval.public.adapters import hipporag_multihop, longmemeval, smoke
from eval.public.assets import AssetSpec, load_asset_set
from eval.public.bundle import write_bundle

ROOT = Path(__file__).parent
_HEX = set("0123456789abcdef")
_ADAPTERS = {
    "hipporag-multihop": hipporag_multihop.run,
    "longmemeval": longmemeval.run,
    "smoke": smoke.run,
}
_NORMALIZERS = {
    "hipporag-multihop": hipporag_multihop.normalize,
    "longmemeval": longmemeval.normalize,
}
_PROFILE_CONTRACTS = {
    "smoke-hit-at-k-v1": ("deterministic-retrieval", "wilson"),
    "longmemeval-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
    "hipporag-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
}


def load_registry() -> dict[str, dict[str, Any]]:
    registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    for name, suite in registry.items():
        revision, digest = suite.get("revision", ""), suite.get("dataset_sha256", "")
        if len(revision) != 40 or set(revision) - _HEX:
            raise ValueError(f"{name}: revision must be an exact 40-hex pin")
        if len(digest) != 64 or set(digest) - _HEX:
            raise ValueError(f"{name}: dataset_sha256 must be exact")
        contract = _PROFILE_CONTRACTS.get(suite.get("scoring_profile"))
        if contract != (suite.get("family"), suite.get("interval_method")):
            raise ValueError(
                f"{name}: invalid scoring profile, family, or interval method"
            )
    return registry


def run_public_suite(
    suite_name: str,
    out_dir: Path | str,
    *,
    benchmark_override: dict[str, Any] | None = None,
    dataset_dir: Path | str | None = None,
) -> dict[str, Any]:
    registry = load_registry()
    if suite_name not in registry:
        raise ValueError(f"unknown public suite: {suite_name}")
    suite = registry[suite_name]
    if dataset_dir is not None and suite_name == "smoke":
        raise ValueError("smoke does not accept --dataset-dir")
    try:
        adapter = _ADAPTERS[suite["adapter"]]
    except KeyError as exc:
        raise ValueError(f"{suite_name}: unsupported adapter") from exc
    if benchmark_override is not None:
        adapter_input = benchmark_override
    elif "assets" in suite:
        if dataset_dir is None:
            raise ValueError(f"{suite_name}: --dataset-dir is required")
        specs = [AssetSpec(**item) for item in suite["assets"]]
        raw_input = {"assets": load_asset_set(dataset_dir, specs)}
        try:
            adapter_input = _NORMALIZERS[suite["adapter"]](raw_input)
        except KeyError as exc:
            raise ValueError(
                f"{suite_name}: asset adapter has no preflight normalizer"
            ) from exc
    else:
        fixture_bytes = (ROOT / suite["fixture"]).read_bytes()
        adapter_input = json.loads(fixture_bytes)
    if hashlib.sha256(_canonical(adapter_input)).hexdigest() != suite["dataset_sha256"]:
        raise ValueError(
            f"{suite_name}: normalized benchmark digest does not match registry"
        )
    allowed_env = {
        key: os.environ[key]
        for key in ("LANG", "LC_ALL", "PATH", "TMPDIR")
        if key in os.environ
    }
    with tempfile.TemporaryDirectory(prefix="mneme-public-") as temp:
        cli = MnemoCLI(store=str(Path(temp) / "store.json"), env=allowed_env)
        with patch.dict(os.environ, allowed_env, clear=True):
            result = adapter(adapter_input, cli)
    if len(result) == 2:
        traces, measured = result
        benchmark = adapter_input
    elif len(result) == 3:
        benchmark, traces, measured = result
    else:
        raise ValueError(
            "public adapter must return (traces, metrics) or (benchmark, traces, metrics)"
        )
    if hashlib.sha256(_canonical(benchmark)).hexdigest() != suite["dataset_sha256"]:
        raise ValueError(
            f"{suite_name}: normalized benchmark digest does not match registry"
        )
    if (
        measured.get("family") != suite["family"]
        or measured.get("profile", suite["scoring_profile"]) != suite["scoring_profile"]
        or measured.get("interval", {}).get("method") != suite["interval_method"]
    ):
        raise ValueError("scoring profile, family, or interval metadata mismatch")
    metadata = {**suite, "suite": suite_name}
    write_bundle(
        Path(out_dir),
        benchmark=benchmark,
        metadata=metadata,
        metrics=measured,
        traces=traces,
    )
    return {
        "bundle": str(Path(out_dir).resolve()),
        "independent_external_reproduction": False,
        "pbpp_headline_eligible": False,
        "publishable": False,
        "suite": suite_name,
        "system_seam": "public-cli-subprocess",
    }


def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
