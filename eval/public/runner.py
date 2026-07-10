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
from eval.public.adapters import smoke
from eval.public.bundle import write_bundle

ROOT = Path(__file__).parent
_HEX = set("0123456789abcdef")
_ADAPTERS = {"smoke": smoke.run}


def load_registry() -> dict[str, dict[str, Any]]:
    registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    for name, suite in registry.items():
        revision, digest = suite.get("revision", ""), suite.get("dataset_sha256", "")
        if len(revision) != 40 or set(revision) - _HEX:
            raise ValueError(f"{name}: revision must be an exact 40-hex pin")
        if len(digest) != 64 or set(digest) - _HEX:
            raise ValueError(f"{name}: dataset_sha256 must be exact")
        required = {"deterministic-retrieval": "wilson", "qa": "bootstrap"}.get(suite.get("family"))
        if required is None or suite.get("interval_method") != required:
            raise ValueError(f"{name}: invalid metric family or interval method")
    return registry


def run_public_suite(suite_name: str, out_dir: Path | str, *, benchmark_override: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = load_registry()
    if suite_name not in registry:
        raise ValueError(f"unknown public suite: {suite_name}")
    suite = registry[suite_name]
    try:
        adapter = _ADAPTERS[suite["adapter"]]
    except KeyError as exc:
        raise ValueError(f"{suite_name}: unsupported adapter") from exc
    fixture_bytes = (ROOT / suite["fixture"]).read_bytes()
    fixture_data = json.loads(fixture_bytes)
    if hashlib.sha256(_canonical(fixture_data)).hexdigest() != suite["dataset_sha256"]:
        raise ValueError(f"{suite_name}: fixture digest does not match registry")
    benchmark = benchmark_override or fixture_data
    custody_sha = suite["dataset_sha256"] if benchmark_override is None else hashlib.sha256(_canonical(benchmark)).hexdigest()
    allowed_env = {key: os.environ[key] for key in ("LANG", "LC_ALL", "PATH", "TMPDIR") if key in os.environ}
    with tempfile.TemporaryDirectory(prefix="mneme-public-") as temp:
        cli = MnemoCLI(store=str(Path(temp) / "store.json"), env=allowed_env)
        with patch.dict(os.environ, allowed_env, clear=True):
            traces, measured = adapter(benchmark, cli)
    if measured["family"] != suite["family"] or measured["interval"]["method"] != suite["interval_method"]:
        raise ValueError("metric family or interval metadata mismatch")
    metadata = {**suite, "dataset_sha256": custody_sha, "suite": suite_name}
    write_bundle(Path(out_dir), benchmark=benchmark, metadata=metadata, metrics=measured, traces=traces)
    return {"bundle": str(Path(out_dir).resolve()), "independent_external_reproduction": False, "pbpp_headline_eligible": False, "publishable": False, "suite": suite_name, "system_seam": "public-cli-subprocess"}


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
