"""Render validated leaderboard records and public traces as static HTML."""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

from leaderboard.validate import _validate_records, validate_record


class RenderError(ValueError):
    """Raised when renderer input or publication fails closed."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RenderError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise RenderError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RenderError(f"non-finite JSON number: {value}")
    return parsed


def _load_json(raw: str, source: Path) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except RenderError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RenderError(f"invalid JSON: {source}") from exc


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RenderError(f"cannot read input: {path}") from exc


def _load_results(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(_read(path), path)
    records = payload if isinstance(payload, list) else [payload]
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        errors = validate_record(record)
        if errors:
            raise RenderError("result contract invalid: " + ", ".join(errors))
        record_id = record["record_id"]
        if record_id in seen:
            raise RenderError(f"duplicate result: {record_id}")
        seen.add(record_id)
        validated.append(record)
    collection_errors = _validate_records(records)
    if collection_errors:
        raise RenderError(
            "result contract invalid: " + ", ".join(collection_errors)
        )
    return sorted(validated, key=lambda record: record["record_id"])


def _load_traces(path: Path) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(_read(path).split("\n"), 1):
        if not raw.strip():
            continue
        trace = _load_json(raw, path)
        if not isinstance(trace, dict):
            raise RenderError(f"invalid JSON trace row at line {line_number}")
        question_id = trace.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise RenderError(f"trace question_id missing at line {line_number}")
        if question_id in seen:
            raise RenderError(f"duplicate question_id: {question_id}")
        seen.add(question_id)
        traces.append(trace)
    return sorted(traces, key=lambda trace: trace["question_id"])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _escape(value: object) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    if isinstance(value, bool):
        value = str(value).lower()
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{_escape(title)}</title></head><body>\n"
        f"{body}\n"
        "</body></html>\n"
    )


def _record_details(record: dict[str, Any]) -> str:
    publication = record["publication"]
    operator = record["operator_entry"]
    publishability = (
        "publishable" if publication["publishable"] else "not publishable"
    )
    metrics = "".join(
        "<li>"
        f"{_escape(metric['family'])}: {_escape(metric['name'])} = "
        f"{_escape(metric['value'])} {_escape(metric['unit'])}"
        "</li>"
        for metric in sorted(
            record["metrics"],
            key=lambda metric: (
                metric["family"],
                metric["name"],
                json.dumps(
                    metric, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ),
            ),
        )
    )
    immutable = "".join(
        f"<li>{_escape(field)}: {_escape(record[field])}</li>"
        for field in (
            "run_commit",
            "build_fingerprint",
            "config_digest",
            "bundle_digest",
            "trace_index_digest",
        )
    )
    return (
        f"<p>System: {_escape(record['system'])}</p>"
        f"<p>Track: {_escape(record['track'])}</p>"
        f"<p>Benchmark: {_escape(record['benchmark'])} "
        f"{_escape(record['benchmark_version'])}</p>"
        f"<p>Publication: {_escape(publication['label'])}; {publishability}</p>"
        f"<p>Operator: {_escape(operator['operator'])}; "
        f"disclosed: {_escape(operator['disclosed'])}</p>"
        f"<h2>Metrics</h2><ul>{metrics}</ul>"
        f"<h2>Immutable artifacts</h2><ul>{immutable}</ul>"
    )


def _render_pages(
    records: list[dict[str, Any]],
    traces: dict[str, list[dict[str, Any]]],
) -> dict[Path, str]:
    pages: dict[Path, str] = {}
    index_items: list[str] = []
    for record in records:
        record_id = record["record_id"]
        record_digest = _digest(record_id)
        index_items.append(
            "<li>"
            f"<a href=\"results/{record_digest}.html\">{_escape(record_id)}</a>"
            f"{_record_details(record)}"
            "</li>"
        )
        trace_items: list[str] = []
        for trace in traces[record_id]:
            question_id = trace["question_id"]
            question_digest = _digest(question_id)
            trace_items.append(
                "<li>"
                f'<a href="../traces/{record_digest}/{question_digest}.html">'
                f"{_escape(question_id)}</a>"
                "</li>"
            )
            evidence = "".join(
                f"<h2>{label}</h2><pre>{_escape(trace[field])}</pre>"
                for field, label in (
                    ("stored_records", "Stored context/evidence"),
                    ("ranked_retrieved_hits", "Retrieved context/evidence"),
                    (
                        "authorized_retrieval_hops",
                        "Retrieved context/evidence: authorized_retrieval_hops",
                    ),
                    ("answer", "Final answer"),
                )
                if field in trace
            )
            pages[
                Path("traces") / record_digest / f"{question_digest}.html"
            ] = _page(
                f"Trace {question_id}",
                f"<h1>Trace {_escape(question_id)}</h1>"
                f'<p><a href="../../results/{record_digest}.html">'
                "Back to result</a></p>"
                f"{evidence}",
            )
        pages[Path("results") / f"{record_digest}.html"] = _page(
            f"Result {record_id}",
            f"<h1>Result {_escape(record_id)}</h1>"
            '<p><a href="../index.html">Leaderboard</a></p>'
            f"{_record_details(record)}"
            f"<h2>Disclosed traces</h2><ul>{''.join(trace_items)}</ul>",
        )
    pages[Path("index.html")] = _page(
        "Leaderboard",
        "<h1>Leaderboard</h1><ul>" + "".join(index_items) + "</ul>",
    )
    return pages


def _publish(pages: dict[Path, str], destination: Path) -> None:
    destination = destination.absolute()
    temporary: Path | None = None
    backup: Path | None = None
    preserve_backup = False
    try:
        if destination.is_symlink():
            raise RenderError(f"destination may not be a symlink: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_mode = (
            stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o755
        )
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
        )
        temporary.chmod(destination_mode)
        backup = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}-backup-", dir=destination.parent
            )
        )
        backup.rmdir()
        for relative, content in sorted(pages.items(), key=lambda item: str(item[0])):
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except OSError:
            if backup.exists():
                try:
                    os.replace(backup, destination)
                except OSError:
                    try:
                        shutil.copytree(backup, destination)
                    except OSError as restore_error:
                        preserve_backup = True
                        raise RenderError(
                            f"failed to restore site; backup preserved at: {backup}"
                        ) from restore_error
            raise
        shutil.rmtree(backup, ignore_errors=True)
    except RenderError:
        raise
    except (OSError, UnicodeError) as exc:
        raise RenderError(f"failed to publish site: {destination}") from exc
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary)
        if (
            backup is not None
            and backup.exists()
            and destination.exists()
            and not preserve_backup
        ):
            shutil.rmtree(backup, ignore_errors=True)


def render_site(
    results: str | Path,
    traces: dict[str, str | Path],
    destination: str | Path,
) -> None:
    """Render a complete site, replacing the destination only after validation."""
    records = _load_results(Path(results))
    record_ids = {record["record_id"] for record in records}
    trace_ids = set(traces)
    missing = sorted(record_ids - trace_ids)
    if missing:
        raise RenderError("missing trace source: " + ", ".join(missing))
    unlinked = sorted(trace_ids - record_ids)
    if unlinked:
        raise RenderError("unlinked trace source: " + ", ".join(unlinked))
    loaded_traces = {
        record_id: _load_traces(Path(traces[record_id]))
        for record_id in sorted(record_ids)
    }
    _publish(_render_pages(records, loaded_traces), Path(destination))


def main(argv: list[str] | None = None) -> int:
    """Render RESULTS with RECORD_ID=TRACES mappings into DESTINATION."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3:
        print(
            "usage: render.py RESULTS DESTINATION RECORD_ID=TRACES [...]",
            file=sys.stderr,
        )
        return 2
    mappings: dict[str, Path] = {}
    try:
        for item in args[2:]:
            record_id, separator, path = item.partition("=")
            if not separator or not record_id or not path or record_id in mappings:
                raise RenderError(f"invalid trace mapping: {item}")
            mappings[record_id] = Path(path)
        render_site(Path(args[0]), mappings, Path(args[1]))
    except RenderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
