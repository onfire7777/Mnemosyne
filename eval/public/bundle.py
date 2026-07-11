"""Canonical public benchmark bundle custody, verification, and reproduction."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED = (
    "README.md",
    "benchmark.json",
    "build.json",
    "config.json",
    "judge.json",
    "metrics.json",
    "reproduce.sh",
    "traces.jsonl",
)
SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"-----(?:BEGIN|END) [A-Z ]*PRIVATE KEY-----)"
)


class BundleError(ValueError):
    """Bundle failed closed under the public custody contract."""


def write_bundle(
    destination: Path,
    *,
    benchmark: dict[str, Any],
    metadata: dict[str, Any],
    metrics: dict[str, Any],
    traces: list[dict[str, Any]],
) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent)
    )
    try:
        _write_json(temp / "benchmark.json", {"data": benchmark, "metadata": metadata})
        _write_json(
            temp / "build.json",
            {
                "environment_contract": "uv run --locked",
                "system_seam": "public-cli-subprocess",
                "version": 1,
            },
        )
        _write_json(
            temp / "config.json",
            {
                "family": metadata["family"],
                "interval_method": metadata["interval_method"],
                "scoring_profile": metadata.get("scoring_profile", "smoke-hit-at-k-v1"),
                "suite": metadata["suite"],
            },
        )
        _write_json(
            temp / "judge.json",
            {"judge": None, "reader": None, "reason": "retrieval family"},
        )
        _write_json(temp / "metrics.json", metrics)
        (temp / "traces.jsonl").write_bytes(
            b"".join(_canonical(trace) for trace in traces)
        )
        (temp / "README.md").write_text(
            "# PBPP development bundle\n\nThis smoke artifact is non-publishable, not headline eligible, and is not an independent external reproduction. Run `./reproduce.sh DEST`.\n",
            encoding="utf-8",
        )
        (temp / "reproduce.sh").write_text(
            '#!/bin/sh\nset -eu\ntest "$#" -eq 1 || { echo "usage: $0 DEST" >&2; exit 2; }\nuv run --locked mneme eval-public --reproduce-bundle "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" --out-dir "$1"\n',
            encoding="utf-8",
        )
        os.chmod(temp / "reproduce.sh", 0o755)
        _write_json(
            temp / "bundle-manifest.json",
            {"files": {name: _digest(temp / name) for name in REQUIRED}, "version": 1},
        )
        temp.rename(destination)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def verify_bundle(bundle: Path | str) -> dict[str, Any]:
    root = Path(bundle)
    if not root.is_dir() or root.is_symlink():
        raise BundleError("bundle must be a real directory, not a link")
    actual, expected = (
        {entry.name for entry in root.iterdir()},
        {*REQUIRED, "bundle-manifest.json"},
    )
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
    benchmark, config, measured = (
        _load_json(root / "benchmark.json"),
        _load_json(root / "config.json"),
        _load_json(root / "metrics.json"),
    )
    judge = _load_json(root / "judge.json")
    traces = [
        _parse_json(line, "traces.jsonl")
        for line in (root / "traces.jsonl").read_text().splitlines()
    ]
    question_ids = [trace.get("question_id") for trace in traces]
    if len(question_ids) != len(set(question_ids)) or None in question_ids:
        raise BundleError("duplicate or missing question IDs")
    if measured.get("trace_count") != len(traces) or measured.get("total") != len(
        traces
    ):
        raise BundleError("trace/metric count drift")
    family, method, profile = (
        config.get("family"),
        config.get("interval_method"),
        config.get("scoring_profile"),
    )
    allowed_profile = {
        "smoke-hit-at-k-v1": ("deterministic-retrieval", "wilson"),
        "longmemeval-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
        "hipporag-retrieval-v1": ("deterministic-retrieval", "bootstrap"),
    }.get(profile)
    if any(trace.get("scoring_family") != family for trace in traces):
        raise BundleError("metric families may not be blended")
    if family == "deterministic-retrieval" and (
        judge.get("reader") is not None or judge.get("judge") is not None
    ):
        raise BundleError("retrieval family must not declare a reader or judge")
    if family == "qa" and not all(
        isinstance(judge.get(key), str) and judge[key].strip()
        for key in ("reader", "judge")
    ):
        raise BundleError("QA family must disclose its reader and judge")
    if allowed_profile != (family, method):
        raise BundleError("wrong interval-family metadata")
    metadata = benchmark.get("metadata", {})
    if hashlib.sha256(_canonical(benchmark.get("data"))).hexdigest() != metadata.get(
        "dataset_sha256"
    ):
        raise BundleError("benchmark custody digest mismatch")
    _verify_registry_anchor(metadata)
    if config != {
        "family": metadata.get("family"),
        "interval_method": metadata.get("interval_method"),
        "scoring_profile": metadata.get("scoring_profile"),
        "suite": metadata.get("suite"),
    }:
        raise BundleError("bundle config does not match canonical registry metadata")
    if measured.get("family") != family:
        raise BundleError("metrics/config family mismatch")
    if profile == "smoke-hit-at-k-v1":
        if measured.get("interval", {}).get("method") != method:
            raise BundleError("wrong interval-family metadata")
        _verify_metrics(family, benchmark.get("data"), measured, traces)
    else:
        from eval.public.scoring import ScoringError, score_profile

        try:
            expected_metrics = score_profile(
                profile, _scoring_labels(benchmark.get("data")), traces
            )
        except ScoringError as exc:
            raise BundleError(
                "generalized scoring profile recomputation failed"
            ) from exc
        if measured != expected_metrics:
            raise BundleError("metrics do not recompute from anchored scoring profile")
    if any(
        metadata.get(flag) is not False
        for flag in (
            "publishable",
            "pbpp_headline_eligible",
            "independent_external_reproduction",
        )
    ):
        raise BundleError("smoke publication flags must remain false")
    return {"family": family, "suite": metadata.get("suite"), "valid": True}


def reproduce_bundle(source: Path | str, destination: Path | str) -> dict[str, Any]:
    verify_bundle(source)
    custody = _load_json(Path(source) / "benchmark.json")
    from eval.public.runner import run_public_suite

    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite bundle: {destination}")
    try:
        result = run_public_suite(
            custody["metadata"]["suite"],
            destination,
            benchmark_override=custody["data"],
        )
        verify_bundle(destination)
        for name in REQUIRED:
            if (Path(source) / name).read_bytes() != (destination / name).read_bytes():
                raise BundleError(f"reproduction mismatch: {name}")
        return result
    except BaseException:
        if destination.is_dir():
            shutil.rmtree(destination)
        raise


def write_report(
    source: Path | str,
    reproduced: Path | str,
    report_output: Path | str,
    report_note: Path | str,
) -> dict[str, Any]:
    """Write a deterministic evidence report only for a matching reproduction."""
    source_root, reproduced_root = Path(source).resolve(), Path(reproduced).resolve()
    source_result, reproduced_result = (
        verify_bundle(source_root),
        verify_bundle(reproduced_root),
    )
    if source_result != reproduced_result:
        raise BundleError("source and reproduced bundle verification metadata mismatch")
    for name in REQUIRED:
        if (source_root / name).read_bytes() != (reproduced_root / name).read_bytes():
            raise BundleError(f"source and reproduced bundle mismatch: {name}")
    output, note = Path(report_output), Path(report_note)
    if output.exists() or note.exists():
        raise FileExistsError("refusing to overwrite report output or note")
    git_sha = _git_sha()
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence = _report_evidence(source_root, reproduced_root)
    report = {
        "bindings": {
            "reproduced_bundle_manifest_sha256": _digest(
                reproduced_root / "bundle-manifest.json"
            ),
            "source_bundle_manifest_sha256": _digest(
                source_root / "bundle-manifest.json"
            ),
            **{
                f"{name.replace('.', '_')}_sha256": _digest(source_root / name)
                for name in ("benchmark.json", "metrics.json", "traces.jsonl")
            },
        },
        "git_sha": git_sha,
        "generated_at": generated_at,
        "evidence": evidence,
        "command": [
            "mneme",
            "eval-public",
            "--write-report",
            str(source_root),
            "--reproduced-bundle",
            str(reproduced_root),
            "--report-output",
            str(output.resolve()),
            "--report-note",
            str(note.resolve()),
        ],
        "publication": {
            "independent_external_reproduction": False,
            "pbpp_headline_eligible": False,
            "publishable": False,
        },
        "reproduced_bundle": str(reproduced_root),
        "source_bundle": str(source_root),
        "suite": source_result["suite"],
        "version": 1,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    note.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output, _canonical(report))
    report_digest = _digest(output)
    markdown = _render_report_note(report, report_digest)
    try:
        _atomic_write(note, markdown)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return {
        "report": str(output.resolve()),
        "report_note": str(note.resolve()),
        "sha256": report_digest,
        "valid": True,
    }


def verify_report(report_path: Path | str, report_note: Path | str) -> dict[str, Any]:
    report_file, note_file = Path(report_path), Path(report_note)
    for path in (report_file, note_file):
        if path.is_symlink() or not path.is_file():
            raise BundleError("report and report note must be real files, not links")
    report = _load_json(report_file)
    if (
        set(report)
        != {
            "bindings",
            "command",
            "evidence",
            "generated_at",
            "git_sha",
            "publication",
            "reproduced_bundle",
            "source_bundle",
            "suite",
            "version",
        }
        or report["version"] != 1
    ):
        raise BundleError("invalid report schema")
    if len(report.get("git_sha", "")) != 40 or set(report["git_sha"]) - set(
        "0123456789abcdef"
    ):
        raise BundleError("invalid report git SHA")
    source, reproduced = (
        Path(report["source_bundle"]),
        Path(report["reproduced_bundle"]),
    )
    source_result, reproduced_result = verify_bundle(source), verify_bundle(reproduced)
    if source_result != reproduced_result or source_result["suite"] != report["suite"]:
        raise BundleError("report suite binding mismatch")
    expected = {
        "reproduced_bundle_manifest_sha256": _digest(
            reproduced / "bundle-manifest.json"
        ),
        "source_bundle_manifest_sha256": _digest(source / "bundle-manifest.json"),
        **{
            f"{name.replace('.', '_')}_sha256": _digest(source / name)
            for name in ("benchmark.json", "metrics.json", "traces.jsonl")
        },
    }
    if report.get("bindings") != expected:
        raise BundleError("report cryptographic binding mismatch")
    try:
        generated_at = datetime.fromisoformat(
            report["generated_at"].replace("Z", "+00:00")
        )
    except (AttributeError, ValueError) as exc:
        raise BundleError("invalid report UTC timestamp") from exc
    if not report["generated_at"].endswith("Z") or generated_at.tzinfo != UTC:
        raise BundleError("invalid report UTC timestamp")
    expected_command = [
        "mneme",
        "eval-public",
        "--write-report",
        str(source.resolve()),
        "--reproduced-bundle",
        str(reproduced.resolve()),
        "--report-output",
        str(report_file.resolve()),
        "--report-note",
        str(note_file.resolve()),
    ]
    if report.get("command") != expected_command:
        raise BundleError("report command provenance mismatch")
    if report.get("evidence") != _report_evidence(
        source.resolve(), reproduced.resolve()
    ):
        raise BundleError("report evidence projection mismatch")
    for name in REQUIRED:
        if (source / name).read_bytes() != (reproduced / name).read_bytes():
            raise BundleError(f"reported reproduction mismatch: {name}")
    if any(
        report.get("publication", {}).get(flag) is not False
        for flag in (
            "publishable",
            "pbpp_headline_eligible",
            "independent_external_reproduction",
        )
    ):
        raise BundleError("report publication flags must remain false")
    note_bytes = note_file.read_bytes()
    if note_bytes != _render_report_note(report, _digest(report_file)):
        raise BundleError("report note binding is not the exact canonical projection")
    note = note_bytes.decode("utf-8")
    for value in (
        _digest(report_file),
        expected["source_bundle_manifest_sha256"],
        expected["reproduced_bundle_manifest_sha256"],
        report["git_sha"],
    ):
        if f"`{value}`" not in note:
            raise BundleError("report note binding mismatch")
    for projection in (
        json.dumps(
            {
                "assets": report["evidence"]["assets"],
                "benchmark_metadata": report["evidence"]["benchmark_metadata"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        json.dumps(
            report["evidence"]["metrics"], sort_keys=True, separators=(",", ":")
        ),
        json.dumps(
            {
                "command": report["command"],
                "provenance": report["evidence"]["provenance"],
                "reproduction": report["evidence"]["reproduction"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        f"Eligible records: `{report['evidence']['counts']['eligible']}`",
        f"Excluded records: `{report['evidence']['counts']['excluded']}`",
        f"Generated at (UTC): `{report['generated_at']}`",
    ):
        if projection not in note:
            raise BundleError("report note evidence projection mismatch")
    return {
        "report": str(report_file.resolve()),
        "report_note": str(note_file.resolve()),
        "sha256": _digest(report_file),
        "valid": True,
    }


def _report_evidence(source: Path, reproduced: Path) -> dict[str, Any]:
    benchmark = _load_json(source / "benchmark.json")
    build = _load_json(source / "build.json")
    metrics = _load_json(source / "metrics.json")
    metadata = benchmark.get("metadata", {})
    data = benchmark.get("data", {})
    questions = data.get("questions", []) if isinstance(data, dict) else []
    trace_count = metrics.get("trace_count")
    eligible = metadata.get(
        "eligible_count", len(questions) if isinstance(questions, list) else trace_count
    )
    excluded = metadata.get("excluded_count", 0)
    if not isinstance(eligible, int) or isinstance(eligible, bool) or eligible < 0:
        raise BundleError("invalid eligible count metadata")
    if not isinstance(excluded, int) or isinstance(excluded, bool) or excluded < 0:
        raise BundleError("invalid excluded count metadata")
    assets = metadata.get("assets")
    if assets is None:
        assets = [
            {
                key: metadata.get(key)
                for key in ("dataset_sha256", "license", "revision", "split_role")
            }
        ]
    if not isinstance(assets, list) or not assets:
        raise BundleError("report requires benchmark asset metadata")
    return {
        "assets": assets,
        "benchmark_metadata": metadata,
        "counts": {"eligible": eligible, "excluded": excluded, "traces": trace_count},
        "metrics": metrics,
        "provenance": {
            "build": build,
            "source_bundle": str(source.resolve()),
            "system_seam": build.get("system_seam"),
        },
        "reproduction": {
            "matched_files": list(REQUIRED),
            "reproduced_bundle": str(reproduced.resolve()),
            "verified": True,
        },
    }


def _render_report_note(report: dict[str, Any], report_digest: str) -> bytes:
    evidence = report["evidence"]
    return (
        f"# Public evaluation report: {report['suite']}\n\n"
        "This report is non-publishable, not PBPP headline eligible, and is not an independent external reproduction.\n\n"
        f"- External report SHA-256: `{report_digest}`\n"
        f"- Source bundle manifest SHA-256: `{report['bindings']['source_bundle_manifest_sha256']}`\n"
        f"- Reproduced bundle manifest SHA-256: `{report['bindings']['reproduced_bundle_manifest_sha256']}`\n"
        f"- Git SHA: `{report['git_sha']}`\n"
        f"- Generated at (UTC): `{report['generated_at']}`\n\n"
        "## Assets and benchmark metadata\n\n"
        f"```json\n{json.dumps({'assets': evidence['assets'], 'benchmark_metadata': evidence['benchmark_metadata']}, sort_keys=True, separators=(',', ':'))}\n```\n\n"
        f"- Eligible records: `{evidence['counts']['eligible']}`\n"
        f"- Excluded records: `{evidence['counts']['excluded']}`\n\n"
        "## Metrics\n\n"
        f"```json\n{json.dumps(evidence['metrics'], sort_keys=True, separators=(',', ':'))}\n```\n\n"
        "## Reproduction and provenance\n\n"
        f"```json\n{json.dumps({'command': report['command'], 'provenance': evidence['provenance'], 'reproduction': evidence['reproduction']}, sort_keys=True, separators=(',', ':'))}\n```\n"
    ).encode()


def _scoring_labels(benchmark: Any) -> list[dict[str, Any]]:
    if not isinstance(benchmark, dict) or not isinstance(
        benchmark.get("questions"), list
    ):
        raise BundleError("scoring profile benchmark questions are missing")
    labels = []
    for question in benchmark["questions"]:
        if not isinstance(question, dict):
            raise BundleError("scoring profile question schema is invalid")
        label: dict[str, Any] = {"question_id": question.get("question_id")}
        present_golds = [
            question[key]
            for key in (
                "gold_references",
                "answer_session_ids",
                "gold_doc_ids",
                "gold_passage_ids",
            )
            if key in question
        ]
        if len(present_golds) > 1 and any(
            value != present_golds[0] for value in present_golds[1:]
        ):
            raise BundleError("conflicting benchmark gold fields")
        gold = question.get(
            "gold_references",
            question.get(
                "answer_session_ids",
                question.get("gold_doc_ids", question.get("gold_passage_ids")),
            ),
        )
        if gold is not None:
            label["gold_references"] = gold
        if "answers" in question:
            label["answers"] = question["answers"]
        labels.append(label)
    return labels


def _verify_registry_anchor(metadata: dict[str, Any]) -> None:
    from eval.public.runner import load_registry

    suite_name = metadata.get("suite")
    registry = load_registry()
    if suite_name not in registry:
        raise BundleError("suite has no canonical registry anchor")
    canonical = registry[suite_name]
    anchored = (
        "adapter",
        "dataset_sha256",
        "family",
        "independent_external_reproduction",
        "interval_method",
        "license",
        "pbpp_headline_eligible",
        "publishable",
        "revision",
        "split_role",
        "scoring_profile",
        "assets",
    )
    if any(metadata.get(key) != canonical.get(key) for key in anchored):
        raise BundleError("bundle metadata does not match canonical registry anchor")


def _verify_metrics(
    family: str,
    benchmark: Any,
    measured: dict[str, Any],
    traces: list[dict[str, Any]],
) -> None:
    if family != "deterministic-retrieval":
        return
    from eval.harness.metrics import wilson_interval

    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("k"), int):
        raise BundleError("retrieval benchmark is missing k")
    questions = benchmark.get("questions")
    corpus = benchmark.get("corpus")
    if not isinstance(questions, list) or not isinstance(corpus, list):
        raise BundleError("retrieval benchmark schema is invalid")
    gold_by_question = {
        question.get("question_id"): question.get("gold_doc_ids")
        for question in questions
    }
    doc_ids = {document.get("doc_id") for document in corpus}
    if (
        None in gold_by_question
        or None in doc_ids
        or set(gold_by_question) != {trace.get("question_id") for trace in traces}
    ):
        raise BundleError("traces do not match anchored benchmark questions")
    for trace in traces:
        question_id = trace["question_id"]
        if trace.get("gold_references") != gold_by_question[question_id]:
            raise BundleError("trace gold does not match anchored benchmark")
        stored = trace.get("stored_records")
        ranked = trace.get("ranked_retrieved_hits")
        if not isinstance(stored, list) or set(stored) != doc_ids:
            raise BundleError("stored records do not match anchored benchmark corpus")
        if not isinstance(ranked, list) or any(item not in doc_ids for item in ranked):
            raise BundleError("retrieved hit is outside anchored benchmark corpus")
        if trace.get("answer") is not None and trace.get("answer") not in doc_ids:
            raise BundleError("answer is outside anchored benchmark corpus")
    if measured.get("metric") != "hit_at_k":
        raise BundleError("deterministic retrieval metric must be hit_at_k")
    k = benchmark["k"]
    successes = sum(
        bool(
            set(trace["ranked_retrieved_hits"][:k])
            & set(gold_by_question[trace["question_id"]])
        )
        for trace in traces
    )
    expected = wilson_interval(successes, len(traces)).as_dict()
    interval = measured.get("interval", {})
    recomputed = {
        "family": family,
        "successes": successes,
        "total": len(traces),
        "trace_count": len(traces),
        "value": expected["point"],
        "interval": {
            "confidence": 0.95,
            "high": expected["ci_high"],
            "low": expected["ci_low"],
            "method": expected["ci_method"],
        },
    }
    for key, value in recomputed.items():
        if key == "interval":
            if any(
                interval.get(nested) != expected_value
                for nested, expected_value in value.items()
            ):
                raise BundleError("metrics do not recompute from traces")
        elif measured.get(key) != value:
            raise BundleError("metrics do not recompute from traces")


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical(value))


def _canonical(value: Any) -> bytes:
    _reject_non_finite(value)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _load_json(path: Path) -> Any:
    return _parse_json(path.read_text(encoding="utf-8"), path.name)


def _parse_json(raw: str, label: str) -> Any:
    try:
        value = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            object_pairs_hook=_unique_object,
        )
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


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = nested
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _git_sha() -> str:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    sha = result.stdout.strip()
    if len(sha) != 40 or set(sha) - set("0123456789abcdef"):
        raise BundleError("could not resolve an exact git SHA")
    return sha
