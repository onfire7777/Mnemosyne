"""Publish active successful results from a verified signed ledger."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

from leaderboard.ledger import LedgerError, verify_ledger
from leaderboard.readiness import ReadinessError, evaluate_result_v2
from leaderboard.render import RenderError, render_site
from leaderboard.validate import SCHEMA_VERSION, SCHEMA_VERSION_V2, verify_result_digests


class PublicationError(ValueError):
    """Raised when signed ledger results cannot be published."""


_ARTIFACT_KEYS = ("build", "config", "bundle")
_BINDING_MARK = re.compile(r",([^=,]+)=")
_USAGE = (
    "usage: python -m leaderboard.publish "
    "LEDGER PUBLIC_KEY DESTINATION "
    "RECORD_ID=TRACES[,build=BUILD,config=CONFIG,bundle=BUNDLE] [...]"
)


def _parse_record_mapping(
    item: str,
) -> tuple[str, Path, dict[str, Path] | None]:
    record_id, separator, rest = item.partition("=")
    if not separator or not record_id or not rest:
        raise PublicationError(f"invalid trace mapping: {item}")
    marks = list(_BINDING_MARK.finditer(rest))
    artifact_marks = [mark for mark in marks if mark.group(1) in _ARTIFACT_KEYS]
    if not artifact_marks:
        return record_id, Path(rest), None
    if any(mark.group(1) not in _ARTIFACT_KEYS for mark in marks):
        raise PublicationError(f"invalid artifact mapping: {item}")
    keys = [mark.group(1) for mark in artifact_marks]
    if len(keys) != len(set(keys)) or any(key not in keys for key in _ARTIFACT_KEYS):
        raise PublicationError(f"invalid artifact mapping: {item}")
    ordered = sorted(artifact_marks, key=lambda mark: mark.start())
    trace = rest[: ordered[0].start()]
    if not trace:
        raise PublicationError(f"invalid trace mapping: {item}")
    files: dict[str, Path] = {}
    for index, mark in enumerate(ordered):
        end = ordered[index + 1].start() if index + 1 < len(ordered) else len(rest)
        path = rest[mark.end() : end]
        if not path:
            raise PublicationError(f"invalid artifact mapping: {item}")
        files[mark.group(1)] = Path(path)
    return record_id, Path(trace), files


def publish_site(
    ledger: str | Path,
    public_key: str | Path,
    traces: dict[str, str | Path],
    destination: str | Path,
    artifacts: dict[str, dict[str, str | Path]] | None = None,
) -> None:
    """Verify LEDGER and publish its active successful results."""
    try:
        entries = verify_ledger(Path(ledger), Path(public_key))
    except LedgerError as exc:
        raise PublicationError(str(exc)) from exc

    superseded = {
        entry["supersedes"]
        for entry in entries
        if entry["status"] == "superseded"
    }
    results = [
        entry["result"]
        for entry in entries
        if entry["entry_id"] not in superseded
        and entry["status"] == "succeeded"
        and entry["result"] is not None
    ]
    if not results:
        raise PublicationError("ledger has no active successful result")

    record_ids = [str(result["record_id"]) for result in results]
    if len(record_ids) != len(set(record_ids)):
        raise PublicationError("ledger has a duplicate active result")
    unlinked = sorted(set(traces) - set(record_ids))
    if unlinked:
        raise PublicationError("unlinked trace source: " + ", ".join(unlinked))
    versions = {
        result.get("schema_version")
        for result in results
        if isinstance(result, dict)
    }
    if SCHEMA_VERSION in versions and SCHEMA_VERSION_V2 in versions:
        raise PublicationError("mixed result schema versions")

    try:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            verified_traces: dict[str, Path] = {}
            verified_artifacts: dict[str, dict[str, Path]] = {}
            bound = artifacts or {}
            for index, result in enumerate(results):
                record_id = str(result["record_id"])
                trace = traces.get(record_id)
                if trace is None:
                    raise PublicationError(f"missing trace source: {record_id}")
                trace_bytes = Path(trace).read_bytes()
                actual_digest = (
                    "sha256:" + hashlib.sha256(trace_bytes).hexdigest()
                )
                if actual_digest != result["trace_index_digest"]:
                    raise PublicationError(f"trace digest mismatch: {record_id}")
                verified_trace = temporary_path / f"trace-{index}.jsonl"
                verified_trace.write_bytes(trace_bytes)
                verified_traces[record_id] = verified_trace
                if result.get("schema_version") != SCHEMA_VERSION_V2:
                    continue
                files = bound.get(record_id)
                if not isinstance(files, dict):
                    raise PublicationError(f"missing artifact source: {record_id}")
                try:
                    build_bytes = Path(files["build"]).read_bytes()
                    config_bytes = Path(files["config"]).read_bytes()
                    bundle_bytes = Path(files["bundle"]).read_bytes()
                except (KeyError, OSError) as exc:
                    raise PublicationError(
                        f"missing artifact source: {record_id}"
                    ) from exc
                digest_errors = verify_result_digests(
                    result,
                    {
                        "build.json": build_bytes,
                        "config.json": config_bytes,
                        "bundle-manifest.json": bundle_bytes,
                        "traces.jsonl": trace_bytes,
                    },
                )
                if digest_errors:
                    raise PublicationError(
                        "digest mismatch: " + ", ".join(digest_errors)
                    )
                copied = {
                    "build": temporary_path / f"build-{index}.json",
                    "config": temporary_path / f"config-{index}.json",
                    "bundle": temporary_path / f"bundle-{index}.json",
                }
                copied["build"].write_bytes(build_bytes)
                copied["config"].write_bytes(config_bytes)
                copied["bundle"].write_bytes(bundle_bytes)
                verified_artifacts[record_id] = copied
                try:
                    readiness = evaluate_result_v2(result)
                except ReadinessError as exc:
                    raise PublicationError("result is not ready") from exc
                if readiness["ready"] is not True:
                    blocked = readiness["blocked_gates"]
                    raise PublicationError(
                        "result is not ready: "
                        + ", ".join(str(gate) for gate in blocked)
                    )

            result_path = temporary_path / "results.json"
            result_path.write_text(
                json.dumps(
                    results,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )
            if verified_artifacts:
                render_site(
                    result_path,
                    verified_traces,
                    destination,
                    verified_artifacts,
                )
            else:
                render_site(result_path, verified_traces, destination)
    except (OSError, RenderError, TypeError, ValueError) as exc:
        raise PublicationError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    """Publish LEDGER with RECORD_ID=TRACES mappings into DESTINATION."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 4:
        print(_USAGE, file=sys.stderr)
        return 2
    mappings: dict[str, Path] = {}
    artifacts: dict[str, dict[str, Path]] = {}
    try:
        for item in args[3:]:
            record_id, trace, files = _parse_record_mapping(item)
            if record_id in mappings:
                raise PublicationError(f"invalid trace mapping: {item}")
            mappings[record_id] = trace
            if files is not None:
                artifacts[record_id] = files
        publish_site(
            Path(args[0]),
            Path(args[1]),
            mappings,
            Path(args[2]),
            artifacts=artifacts or None,
        )
    except PublicationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
