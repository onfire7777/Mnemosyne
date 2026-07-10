"""Canonical public benchmark bundle custody, verification, and reproduction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

REQUIRED = ("README.md", "benchmark.json", "build.json", "config.json", "judge.json", "metrics.json", "reproduce.sh", "traces.jsonl")
SECRET = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")


class BundleError(ValueError):
    """Bundle failed closed under the public custody contract."""


def write_bundle(destination: Path, *, benchmark: dict[str, Any], metadata: dict[str, Any], metrics: dict[str, Any], traces: list[dict[str, Any]]) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        _write_json(temp / "benchmark.json", {"data": benchmark, "metadata": metadata})
        _write_json(temp / "build.json", {"environment_contract": "uv run --locked", "system_seam": "public-cli-subprocess", "version": 1})
        _write_json(temp / "config.json", {"family": metadata["family"], "interval_method": metadata["interval_method"], "suite": metadata["suite"]})
        _write_json(temp / "judge.json", {"judge": None, "reader": None, "reason": "retrieval family"})
        _write_json(temp / "metrics.json", metrics)
        (temp / "traces.jsonl").write_bytes(b"".join(_canonical(trace) for trace in traces))
        (temp / "README.md").write_text("# PBPP development bundle\n\nThis smoke artifact is non-publishable, not headline eligible, and is not an independent external reproduction. Run `./reproduce.sh DEST`.\n", encoding="utf-8")
        (temp / "reproduce.sh").write_text("#!/bin/sh\nset -eu\ntest \"$#\" -eq 1 || { echo \"usage: $0 DEST\" >&2; exit 2; }\nuv run --locked mneme eval-public --reproduce-bundle \"$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\" --out-dir \"$1\"\n", encoding="utf-8")
        os.chmod(temp / "reproduce.sh", 0o755)
        _write_json(temp / "bundle-manifest.json", {"files": {name: _digest(temp / name) for name in REQUIRED}, "version": 1})
        temp.rename(destination)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def verify_bundle(bundle: Path | str) -> dict[str, Any]:
    root = Path(bundle)
    if not root.is_dir() or root.is_symlink():
        raise BundleError("bundle must be a real directory, not a link")
    actual, expected = {entry.name for entry in root.iterdir()}, {*REQUIRED, "bundle-manifest.json"}
    if actual != expected:
        raise BundleError("inventory mismatch")
    for entry in root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise BundleError(f"links and non-files are forbidden: {entry.name}")
        if entry.resolve().parent != root.resolve():
            raise BundleError(f"path escapes bundle: {entry.name}")
    raw = b"".join((root / name).read_bytes() for name in sorted(actual))
    if SECRET.search(raw.decode("utf-8", errors="replace")):
        raise BundleError("secret-like material detected")
    manifest = _load_json(root / "bundle-manifest.json")
    if set(manifest.get("files", {})) != set(REQUIRED):
        raise BundleError("manifest inventory mismatch")
    for name, expected_digest in manifest["files"].items():
        if _digest(root / name) != expected_digest:
            raise BundleError(f"digest mismatch: {name}")
    benchmark, config, measured = _load_json(root / "benchmark.json"), _load_json(root / "config.json"), _load_json(root / "metrics.json")
    judge = _load_json(root / "judge.json")
    traces = [_parse_json(line, "traces.jsonl") for line in (root / "traces.jsonl").read_text().splitlines()]
    question_ids = [trace.get("question_id") for trace in traces]
    if len(question_ids) != len(set(question_ids)) or None in question_ids:
        raise BundleError("duplicate or missing question IDs")
    if measured.get("trace_count") != len(traces) or measured.get("total") != len(traces):
        raise BundleError("trace/metric count drift")
    family, method = config.get("family"), measured.get("interval", {}).get("method")
    if (family, method) not in {("deterministic-retrieval", "wilson"), ("qa", "bootstrap")}:
        raise BundleError("wrong interval-family metadata")
    if any(trace.get("scoring_family") != family for trace in traces):
        raise BundleError("metric families may not be blended")
    if family == "deterministic-retrieval" and (judge.get("reader") is not None or judge.get("judge") is not None):
        raise BundleError("retrieval family must not declare a reader or judge")
    if family == "qa" and not all(isinstance(judge.get(key), str) and judge[key].strip() for key in ("reader", "judge")):
        raise BundleError("QA family must disclose its reader and judge")
    metadata = benchmark.get("metadata", {})
    if hashlib.sha256(_canonical(benchmark.get("data"))).hexdigest() != metadata.get("dataset_sha256"):
        raise BundleError("benchmark custody digest mismatch")
    if any(metadata.get(flag) is not False for flag in ("publishable", "pbpp_headline_eligible", "independent_external_reproduction")):
        raise BundleError("smoke publication flags must remain false")
    return {"family": family, "suite": metadata.get("suite"), "valid": True}


def reproduce_bundle(source: Path | str, destination: Path | str) -> dict[str, Any]:
    verify_bundle(source)
    custody = _load_json(Path(source) / "benchmark.json")
    from eval.public.runner import run_public_suite
    result = run_public_suite(custody["metadata"]["suite"], destination, benchmark_override=custody["data"])
    verify_bundle(destination)
    return result


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical(value))


def _canonical(value: Any) -> bytes:
    _reject_non_finite(value)
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _load_json(path: Path) -> Any:
    return _parse_json(path.read_text(encoding="utf-8"), path.name)


def _parse_json(raw: str, label: str) -> Any:
    try:
        value = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (json.JSONDecodeError, ValueError) as exc:
        raise BundleError(f"invalid JSON in {label}") from exc
    _reject_non_finite(value)
    return value


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise BundleError("non-finite number")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_non_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_non_finite(nested)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
