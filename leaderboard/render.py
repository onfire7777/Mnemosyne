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

from leaderboard.explainers import systems_body
from leaderboard.comparisons import comparisons_body
from leaderboard.catalog import benchmarks_body, coverage_body, load_catalog
from leaderboard.validate import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_V2,
    _validate_records,
    validate_record,
    verify_result_digests,
)

NETWORK_IO = False
TELEMETRY = False


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
    versions = {record.get("schema_version") for record in validated}
    if SCHEMA_VERSION in versions and SCHEMA_VERSION_V2 in versions:
        raise RenderError("mixed result schema versions")
    return sorted(validated, key=lambda record: record["record_id"])


def _load_traces_from_bytes(raw: bytes, source: Path) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise RenderError(f"cannot read input: {source}") from exc
    traces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        trace = _load_json(line, source)
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


def _load_traces(path: Path) -> list[dict[str, Any]]:
    return _load_traces_from_bytes(_read(path).encode("utf-8"), path)


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


def _page(title: str, body: str, root: str = "") -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_escape(title)} · OpenMemBench</title>"
        "<style>"
        ":root{color-scheme:light;--ink:#0c1938;--muted:#59667c;--line:#cbd3df}"
        "*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);"
        "font:20px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
        "body>header,main,body>footer{max-width:1440px;margin:auto;padding:0 64px}"
        "body>header{display:flex;align-items:center;justify-content:space-between;"
        "gap:24px;padding-top:16px;padding-bottom:18px;border-bottom:1px solid var(--line)}"
        "a{color:#005bd3;text-underline-offset:4px}a:focus-visible{outline:3px solid #005bd3;"
        "outline-offset:5px}.brand{font:32px Georgia,serif;color:var(--ink);text-decoration:none}"
        "nav{display:flex;flex-wrap:wrap;gap:16px 28px}nav a{text-decoration:none}main{padding-top:48px;"
        "padding-bottom:40px}h1,h2{font-family:Georgia,serif;letter-spacing:-.025em;line-height:1.15}"
        "h1{font-size:56px;font-weight:500;margin:4px 0 14px}h2{font-size:36px;font-weight:500;margin:0 0 24px}"
        "p{margin:0 0 24px}.intro{font-size:28px;color:var(--muted);margin-bottom:48px}"
        ".table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:18px}"
        "th,td{text-align:left;border:1px solid var(--line);padding:18px;vertical-align:top}"
        "th{font-weight:500;background:#f7f9fc}th:first-child{width:21%}"
        ".empty{text-align:center;padding:66px 24px}.empty p:last-child{margin:0;"
        "color:var(--muted);font-size:17px}.overview{display:grid;grid-template-columns:1fr 1fr;"
        "gap:72px;border-top:1px solid var(--line);margin-top:40px;padding-top:38px}"
        ".overview h2{font-size:32px}.overview p,small{color:var(--muted)}small{display:block;"
        "font-size:15px}body>footer{border-top:1px solid var(--line);padding-top:16px;"
        "padding-bottom:24px;font-size:16px;color:var(--muted)}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere;padding:20px;background:#f7f9fc;font-size:15px}"
        "li{overflow-wrap:anywhere}.prose{max-width:880px}.prose h2{margin-top:36px}"
        ".section-heading{margin-top:48px}.scope-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}"
        ".scope-card{border:1px solid var(--line);padding:24px}.scope-card h3{margin:0 0 12px;font-size:22px}"
        ".scope-card p{margin:0}.scope-card:target{outline:3px solid #005bd3;outline-offset:3px}"
        ".capability-map th:first-child{width:65%}"
        "@media(max-width:700px){body{font-size:17px}body>header,main,body>footer{padding-left:20px;"
        "padding-right:20px}.brand{font-size:25px}nav{gap:18px;font-size:16px}"
        "body>header{align-items:flex-start;flex-direction:column;gap:12px}.scope-grid{grid-template-columns:1fr}"
        "main{padding-top:32px}h1{font-size:39px}.intro{font-size:21px;margin-bottom:34px}"
        "h2{font-size:29px}.overview{grid-template-columns:1fr;gap:24px}.overview h2{font-size:28px}"
        "th,td{padding:12px}table{min-width:540px}.empty{padding:40px 18px}"
        ".empty-results{min-width:0}.empty-results thead{display:none}}"
        "</style></head><body>\n"
        f'<header><a class="brand" href="{root}index.html">OpenMemBench</a>'
        f'<nav aria-label="Main"><a href="{root}index.html">Results</a>'
        f'<a href="{root}benchmarks.html">Benchmarks</a><a href="{root}coverage.html">Coverage</a>'
        f'<a href="{root}systems.html">Systems</a>'
        f'<a href="{root}methods.html">Methods</a></nav></header>'
        f"<main>{body}</main>\n"
        "<footer>Open, operator-run. Mnemosyne is the operator entry.</footer>"
        "</body></html>\n"
    )


def _interval(metric: dict[str, Any]) -> str:
    interval = metric.get("confidence_interval")
    if interval is None:
        return "<small>Interval not supplied</small>"
    return (
        f"<small>Interval: {_escape(interval['low'])} to "
        f"{_escape(interval['high'])}</small>"
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
        + _interval(metric)
        + "</li>"
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
    details = (
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
    if record.get("schema_version") != SCHEMA_VERSION_V2:
        return details
    gates = "".join(
        "<li>"
        f"{_escape(gate['name'])}: {_escape(gate['status'])}"
        "</li>"
        for gate in record.get("safety_gates", [])
        if isinstance(gate, dict)
    )
    return (
        details
        + f"<p>Track kind: {_escape(record['track_kind'])}</p>"
        + f"<p>Admission: {_escape(record['admission_state'])}</p>"
        + f"<p>Evidence: {_escape(record['evidence_level'])}</p>"
        + f"<p>Module: {_escape(record['module_id'])}</p>"
        + f"<p>Capability: {_escape(record['capability'])}</p>"
        + f"<p>Custody: {_escape(record['custody'])}</p>"
        + f"<p>Signer role: {_escape(record['signer_role'])}</p>"
        + f"<p>Trace: {_escape(record['trace_id'])}</p>"
        + f"<h2>Safety gates</h2><ul>{gates}</ul>"
    )


def _export_json(value: object) -> str:
    # Preserve record array order for its canonical identity while preventing
    # literal markup in generated JSON. Bound raw artifacts are never rewritten.
    return json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    ).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e") + "\n"


def _render_pages(
    records: list[dict[str, Any]],
    traces: dict[str, list[dict[str, Any]]],
) -> dict[Path, str]:
    pages: dict[Path, str] = {}
    pages[Path("data/results.json")] = _export_json(records)
    index_items: list[str] = []
    for record in records:
        record_id = record["record_id"]
        record_digest = _digest(record_id)
        pages[Path("data") / record_digest / "result.json"] = _export_json(record)
        downloads = (
            '<h2>Download evidence</h2><ul>'
            f'<li><a href="../data/{record_digest}/result.json" download>Result record (JSON)</a></li>'
        )
        if record.get("schema_version") == SCHEMA_VERSION_V2:
            downloads += "".join(
                f'<li><a href="../data/{record_digest}/{filename}" download>{label}</a></li>'
                for filename, label in (
                    ("build.json", "Build (JSON)"),
                    ("config.json", "Configuration (JSON)"),
                    ("bundle-manifest.json", "Bundle manifest (JSON)"),
                    ("traces.jsonl", "Raw traces (JSONL)"),
                )
            )
        downloads += "</ul>"
        for metric in sorted(record["metrics"], key=lambda value: json.dumps(value, sort_keys=True)):
            index_items.append(
                f"<tr><td>{_escape(record['system'])}"
                f"<small>{_escape(record['track'])}</small></td>"
                f"<td>{_escape(record['benchmark'])}<small>"
                f"{_escape(record['benchmark_version'])}</small></td>"
                f"<td>{_escape(metric['name'])}<small>{_escape(metric['family'])}</small></td>"
                f"<td>{_escape(metric['value'])} {_escape(metric['unit'])}{_interval(metric)}</td>"
                f'<td><a href="results/{record_digest}.html">View run</a>'
                f"<small>{_escape(record_id)}</small>"
                f"<small>{_escape(record['publication']['label'])}; "
                f"{'publishable' if record['publication']['publishable'] else 'not publishable'}</small>"
                f"<small>Operator: {_escape(record['operator_entry']['operator'])}</small>"
                f"<details><summary>Run disclosures</summary>{_record_details(record)}</details>"
                "</td></tr>"
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
            family = trace.get("scoring_family")
            if family == "deterministic-retrieval":
                answer_label = "Retrieval output (not a generated answer)"
            elif family == "qa":
                answer_label = "Final answer"
            else:
                answer_label = "Recorded output"
            evidence = "".join(
                f"<h2>{label}</h2><pre>{_escape(trace[field])}</pre>"
                for field, label in (
                    ("stored_records", "Stored context/evidence"),
                    ("ranked_retrieved_hits", "Retrieved context/evidence"),
                    (
                        "authorized_retrieval_hops",
                        "Retrieved context/evidence: authorized_retrieval_hops",
                    ),
                    ("answer", answer_label),
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
                root="../../",
            )
        pages[Path("results") / f"{record_digest}.html"] = _page(
            f"Result {record_id}",
            f"<h1>Result {_escape(record_id)}</h1>"
            '<p><a href="../index.html">Leaderboard</a></p>'
            f"{_record_details(record)}"
            f"{downloads}"
            f"<h2>Disclosed traces</h2><ul>{''.join(trace_items)}</ul>",
            root="../",
        )
    empty = (
        '<tr><td colspan="5" class="empty"><p>No verified results published yet.</p>'
        '<p>Development tests are not benchmark rankings. Real results appear here '
        'only with reproducible evidence.</p></td></tr>'
    )
    overview = (
        '<section class="overview"><div><h2>Retrieval is not answer quality</h2>'
        '<p>Recall measures whether useful evidence was found. Answer quality measures '
        'whether the response was correct. We report them separately.</p>'
        '<a href="methods.html">Read the methods</a></div>'
        '<div><h2>Follow the evidence</h2><p>Every published run links its configuration, '
        'uncertainty and question-level traces. Missing measurements stay missing.</p></div></section>'
    )
    pages[Path("index.html")] = _page(
        "Leaderboard",
        '<h1>Memory benchmarks, with evidence.</h1>'
        '<p class="intro">Compare measured results. Inspect the traces behind every number.</p>'
        '<p><a href="benchmarks.html">Explore benchmark families</a> · '
        '<a href="coverage.html">See the whole-memory coverage map</a></p>'
        '<section aria-labelledby="results-heading"><h2 id="results-heading">Results</h2>'
        '<div class="table-scroll" role="region" aria-label="Benchmark results" tabindex="0">'
        f'<table class="{"" if index_items else "empty-results"}"><thead><tr>'
        '<th scope="col">System</th><th scope="col">Benchmark</th><th scope="col">Metric</th>'
        '<th scope="col">Result</th><th scope="col">Evidence</th></tr></thead><tbody>'
        + ("".join(index_items) or empty)
        + '</tbody></table></div><p><a href="data/results.json" download>'
        'Download result data (JSON)</a></p></section>' + overview,
    )
    pages[Path("methods.html")] = _page(
        "Methods",
        '<article class="prose"><h1>How to read the evidence</h1>'
        '<p class="intro">A score is useful only when you can inspect how it was produced.</p>'
        '<h2>Retrieval is not answer quality</h2><p>Retrieval recall measures how much '
        'relevant evidence a system found within a stated result limit. It does not show '
        'that a generated answer was correct. Answer quality, security, calibration, '
        'latency and cost are separate metric families.</p>'
        '<h2>Compare like with like</h2><p>Compare runs only when their dataset version, '
        'split, protocol, model and resource budgets support that comparison. An interval '
        'shows the uncertainty supplied by the run; its confidence level is not inferred. '
        'Missing intervals and missing measurements are not zero. This site does not '
        'calculate a universal winner across different tasks.</p>'
        '<h2>Inspect a run</h2><p>Open a result to inspect its build and configuration '
        'digests, publication status and individual question traces. Trace pages show '
        'only stored evidence, retrieved evidence and answers actually disclosed in '
        'the source. Development results are not public benchmark rankings.</p>'
        '<h2>Publication requires more than rendering</h2><p>A local preview may contain '
        'non-publishable development records. Rendering does not approve publication. '
        'Public release requires the signed ledger, registered experiment, reproducible '
        'bundle, permitted assets and governance evidence to pass the separate release gates.</p>'
        '<h2>Who operates this site</h2><p>Mnemosyne is the operator entry. The project '
        'must run supported competitors under the same disclosed protocol, retain failed '
        'attempts, and explain missing systems. Operator-run does not mean independent '
        'or neutral evaluation.</p>'
        '<p><a href="systems.html">Explore memory system architectures</a></p></article>',
    )
    pages[Path("systems.html")] = _page("Memory systems", systems_body())
    pages[Path("comparisons.html")] = _page("Capabilities and benchmark coverage", comparisons_body())
    catalog = load_catalog()
    pages[Path("benchmarks.html")] = _page("Benchmark catalog", benchmarks_body(catalog))
    pages[Path("coverage.html")] = _page("Whole-memory coverage", coverage_body(catalog))
    pages[Path("data/catalog.json")] = _export_json(catalog)
    return pages


def _publish(pages: dict[Path, str | bytes], destination: Path) -> None:
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
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
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
                        try:
                            if destination.is_symlink() or destination.is_file():
                                destination.unlink(missing_ok=True)
                            elif destination.exists():
                                shutil.rmtree(destination)
                        except OSError as cleanup_error:
                            raise RenderError(
                                "failed to remove partial site at: "
                                f"{destination}; backup preserved at: {backup}"
                            ) from cleanup_error
                        if destination.exists():
                            raise RenderError(
                                "partial site remains at: "
                                f"{destination}; backup preserved at: {backup}"
                            )
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


def _verify_v2_artifacts(
    records: list[dict[str, Any]],
    traces: dict[str, str | Path],
    artifacts: dict[str, dict[str, str | Path]] | None,
) -> dict[str, dict[str, bytes]]:
    bound = artifacts or {}
    snapshots: dict[str, dict[str, bytes]] = {}
    for record in records:
        if record.get("schema_version") != SCHEMA_VERSION_V2:
            continue
        record_id = str(record["record_id"])
        files = bound.get(record_id)
        if not isinstance(files, dict):
            raise RenderError(f"missing artifact source: {record_id}")
        for name in ("build", "config", "bundle"):
            if name in files and "://" in str(files[name]):
                raise RenderError(f"local artifact required: {name}")
        if "://" in str(traces[record_id]):
            raise RenderError("local artifact required: traces")
        try:
            payloads = {
                "build.json": Path(files["build"]).read_bytes(),
                "config.json": Path(files["config"]).read_bytes(),
                "bundle-manifest.json": Path(files["bundle"]).read_bytes(),
                "traces.jsonl": Path(traces[record_id]).read_bytes(),
            }
        except (KeyError, OSError) as exc:
            raise RenderError(f"missing artifact source: {record_id}") from exc
        errors = verify_result_digests(record, payloads)
        if errors:
            raise RenderError("digest mismatch: " + ", ".join(errors))
        snapshots[record_id] = payloads
    return snapshots


def render_site(
    results: str | Path,
    traces: dict[str, str | Path],
    destination: str | Path,
    artifacts: dict[str, dict[str, str | Path]] | None = None,
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
    verified_artifacts = _verify_v2_artifacts(records, traces, artifacts)
    loaded_traces = {
        record_id: (
            _load_traces_from_bytes(verified_artifacts[record_id]["traces.jsonl"], Path(traces[record_id]))
            if record_id in verified_artifacts
            else _load_traces(Path(traces[record_id]))
        )
        for record_id in sorted(record_ids)
    }
    pages: dict[Path, str | bytes] = dict(_render_pages(records, loaded_traces))
    for record_id, payloads in verified_artifacts.items():
        for name, content in payloads.items():
            pages[Path("data") / _digest(record_id) / name] = content
    _publish(pages, Path(destination))


def main(argv: list[str] | None = None) -> int:
    """Render RESULTS with RECORD_ID=TRACES mappings into DESTINATION."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        print(
            "usage: render.py RESULTS DESTINATION [RECORD_ID=TRACES ...]",
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
