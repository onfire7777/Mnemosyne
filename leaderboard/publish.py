"""Publish active successful results from a verified signed ledger."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from leaderboard.ledger import LedgerError, verify_ledger
from leaderboard.render import RenderError, render_site


class PublicationError(ValueError):
    """Raised when signed ledger results cannot be published."""


def publish_site(
    ledger: str | Path,
    public_key: str | Path,
    traces: dict[str, str | Path],
    destination: str | Path,
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

    try:
        for result in results:
            record_id = str(result["record_id"])
            trace = traces.get(record_id)
            if trace is None:
                raise PublicationError(f"missing trace source: {record_id}")
            actual_digest = "sha256:" + hashlib.sha256(
                Path(trace).read_bytes()
            ).hexdigest()
            if actual_digest != result["trace_index_digest"]:
                raise PublicationError(f"trace digest mismatch: {record_id}")
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "results.json"
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
            render_site(result_path, traces, destination)
    except (OSError, RenderError, TypeError, ValueError) as exc:
        raise PublicationError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    """Publish LEDGER with RECORD_ID=TRACES mappings into DESTINATION."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 4:
        print(
            "usage: python -m leaderboard.publish "
            "LEDGER PUBLIC_KEY DESTINATION RECORD_ID=TRACES [...]",
            file=sys.stderr,
        )
        return 2
    mappings: dict[str, Path] = {}
    try:
        for item in args[3:]:
            record_id, separator, path = item.partition("=")
            if not separator or not record_id or not path or record_id in mappings:
                raise PublicationError(f"invalid trace mapping: {item}")
            mappings[record_id] = Path(path)
        publish_site(Path(args[0]), Path(args[1]), mappings, Path(args[2]))
    except PublicationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
