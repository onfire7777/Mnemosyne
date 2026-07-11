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
    candidate_manifest_path: Path | str | None = None,
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
        build = {
            "environment_contract": "uv run --locked",
            "system_seam": "public-cli-subprocess",
            "version": 1,
        }
        if metadata["family"] == "qa":
            build["candidate_git_sha"] = _git_sha()
        _write_json(
            temp / "build.json",
            build,
        )
        _write_json(
            temp / "config.json",
            {
                "family": metadata["family"],
                "interval_method": metadata["interval_method"],
                **({"interval_methods": metadata.get("interval_methods")} if metadata["family"] == "qa" else {}),
                "scoring_profile": metadata.get("scoring_profile", "smoke-hit-at-k-v1"),
                "suite": metadata["suite"],
            },
        )
        if metadata["family"] == "qa":
            custody = metadata.get("reader_custody")
            if not isinstance(custody, dict):
                raise BundleError("QA bundle requires reader custody")
            _write_json(
                temp / "judge.json",
                {
                    "custody": custody,
                    "judge": "benchmark-owned-qa-em-f1-v1",
                    "reader": custody.get("reader", {}).get("name"),
                },
            )
            if candidate_manifest_path is None:
                raise BundleError("QA bundle requires an external candidate manifest path")
            source = Path(candidate_manifest_path)
            _reject_symlink_path(source)
            if not source.is_file():
                raise BundleError("candidate manifest path must be a real file")
            candidate_raw = source.read_bytes()
            candidate = _parse_json(candidate_raw.decode("utf-8"), "candidate manifest")
            from eval.public.runner import validate_candidate_manifest

            try:
                validate_candidate_manifest(candidate, expected_git_sha=build["candidate_git_sha"])
            except ValueError as exc:
                raise BundleError("candidate manifest does not bind bundle-producing git SHA") from exc
            if candidate_raw != _canonical(candidate):
                raise BundleError("candidate manifest bytes must be canonical")
            (temp / "candidate-manifest.json").write_bytes(candidate_raw)
        else:
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
        required = REQUIRED + (("candidate-manifest.json",) if metadata["family"] == "qa" else ())
        _write_json(
            temp / "bundle-manifest.json",
            {"files": {name: _digest(temp / name) for name in required}, "version": 1},
        )
        temp.rename(destination)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def verify_bundle(bundle: Path | str) -> dict[str, Any]:
    root = Path(bundle)
    if not root.is_dir() or root.is_symlink():
        raise BundleError("bundle must be a real directory, not a link")
    actual = {entry.name for entry in root.iterdir()}
    payload_files = REQUIRED + (("candidate-manifest.json",) if "candidate-manifest.json" in actual else ())
    expected = {*payload_files, "bundle-manifest.json"}
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
    if set(manifest.get("files", {})) != set(payload_files):
        raise BundleError("manifest inventory mismatch")
    for name, expected_digest in manifest["files"].items():
        if _digest(root / name) != expected_digest:
            raise BundleError(f"digest mismatch: {name}")
    benchmark, config, measured, build = (
        _load_json(root / "benchmark.json"),
        _load_json(root / "config.json"),
        _load_json(root / "metrics.json"),
        _load_json(root / "build.json"),
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
        "qa-em-f1-v1": ("qa", "bootstrap"),
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
    if (family == "qa") != ("candidate-manifest.json" in actual):
        raise BundleError("QA candidate manifest inventory mismatch")
    if allowed_profile != (family, method):
        raise BundleError("wrong interval-family metadata")
    metadata = benchmark.get("metadata", {})
    if hashlib.sha256(_canonical(benchmark.get("data"))).hexdigest() != metadata.get(
        "dataset_sha256"
    ):
        raise BundleError("benchmark custody digest mismatch")
    _verify_registry_anchor(metadata)
    expected_config = {
        "family": metadata.get("family"),
        "interval_method": metadata.get("interval_method"),
        "scoring_profile": metadata.get("scoring_profile"),
        "suite": metadata.get("suite"),
    }
    if family == "qa":
        expected_config["interval_methods"] = metadata.get("interval_methods")
    if config != expected_config:
        raise BundleError("bundle config does not match canonical registry metadata")
    if measured.get("family") != family:
        raise BundleError("metrics/config family mismatch")
    if family == "qa":
        _verify_qa_custody(metadata, judge, benchmark.get("data"), traces, root / "candidate-manifest.json", measured, build)
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
            candidate_manifest_path=(Path(source) / "candidate-manifest.json") if custody["metadata"]["family"] == "qa" else None,
        )
        verify_bundle(destination)
        for name in _manifest_files(Path(source)):
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
    source_files = _manifest_files(source_root)
    if source_files != _manifest_files(reproduced_root):
        raise BundleError("source and reproduced bundle inventory mismatch")
    for name in source_files:
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
    source_files = _manifest_files(source)
    if source_files != _manifest_files(reproduced):
        raise BundleError("reported reproduction inventory mismatch")
    for name in source_files:
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
            "matched_files": list(_manifest_files(source)),
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


def _verify_qa_custody(
    metadata: dict[str, Any],
    judge: dict[str, Any],
    benchmark: Any,
    traces: list[dict[str, Any]],
    candidate_path: Path,
    measured: dict[str, Any],
    build: dict[str, Any],
) -> None:
    from eval.public.runner import load_qa_protocol, qa_protocol_digests, require_clean_candidate_checkout, validate_candidate_manifest

    protocol = load_qa_protocol()
    custody = metadata.get("reader_custody")
    if not isinstance(custody, dict) or judge.get("custody") != custody:
        raise BundleError("QA reader custody mismatch")
    if custody.get("protocol_version") != protocol["version"]:
        raise BundleError("QA protocol version mismatch")
    reader = custody.get("reader")
    if not isinstance(reader, dict) or set(reader) != {"model_content_sha256", "model_revision", "name", "provider", "selector"}:
        raise BundleError("QA reader model custody is incomplete")
    expected_reader = {"model_revision": protocol["model"]["selector"], "name": "grounded-reader", "provider": protocol["model"]["provider"], "selector": protocol["model"]["selector"]}
    if any(reader.get(key) != value for key, value in expected_reader.items()):
        raise BundleError("QA reader provider and selector must match preregistration")
    _require_sha256(reader.get("model_content_sha256"), "reader model content")
    prompt = custody.get("prompt")
    if not isinstance(prompt, dict) or set(prompt) != {"serializer_sha256", "template_sha256"}:
        raise BundleError("QA prompt custody is incomplete")
    _require_sha256(prompt.get("template_sha256"), "prompt template")
    _require_sha256(prompt.get("serializer_sha256"), "evidence serializer")
    expected_digests = qa_protocol_digests(protocol)
    if prompt != {
        "serializer_sha256": expected_digests["serializer_sha256"],
        "template_sha256": expected_digests["prompt_sha256"],
    }:
        raise BundleError("QA prompt custody does not match preregistration")
    if custody.get("decoding") != protocol["decoding"]:
        raise BundleError("QA decoding config does not match preregistration")
    if custody.get("evidence_budget") != protocol["evidence_budget"]:
        raise BundleError("QA evidence budget does not match preregistration")
    if custody.get("abstention") != protocol["abstention"]:
        raise BundleError("QA abstention rule does not match preregistration")
    if custody.get("split_role") not in {"frozen-internal", "held-out-test", "held-out-validation"}:
        raise BundleError("QA split declaration may not be development")
    if custody.get("transport_retries") != protocol["held_out_policy"]["transport_retries"]:
        raise BundleError("QA transport retry count does not match preregistration")
    _require_sha256(custody.get("candidate_manifest_sha256"), "candidate manifest")
    candidate = _load_json(candidate_path)
    if not isinstance(build.get("candidate_git_sha"), str):
        raise BundleError("QA build git SHA is missing")
    if build["candidate_git_sha"] != _git_sha():
        raise BundleError("QA build git SHA does not match the verifying checkout")
    try:
        require_clean_candidate_checkout(build["candidate_git_sha"])
    except ValueError as exc:
        raise BundleError("QA candidate checkout is not clean") from exc
    try:
        validate_candidate_manifest(candidate, expected_git_sha=build["candidate_git_sha"])
    except ValueError as exc:
        raise BundleError("embedded candidate manifest schema mismatch") from exc
    if candidate.get("git_sha") != custody.get("candidate_git_sha"):
        raise BundleError("candidate, build, and custody git SHA mismatch")
    if _digest(candidate_path) != custody["candidate_manifest_sha256"]:
        raise BundleError("embedded candidate manifest digest mismatch")
    if candidate.get("model_content_sha256") != reader["model_content_sha256"]:
        raise BundleError("candidate manifest model digest mismatch")
    if metadata.get("interval_methods") != protocol["interval_methods"]:
        raise BundleError("QA mixed interval declaration mismatch")
    intervals = measured.get("intervals", {})
    if {key: value.get("method") for key, value in intervals.items()} != protocol["interval_methods"]:
        raise BundleError("QA mixed interval metadata mismatch")
    labels = _scoring_labels(benchmark)
    if any(not isinstance(label.get("answers"), list) or not label["answers"] for label in labels):
        raise BundleError("QA benchmark answer labels are missing")
    for trace in traces:
        if any(key in trace for key in ("score", "exact_match", "token_f1")):
            raise BundleError("reader traces may not self-score")
        answer, claims, abstained = trace.get("answer"), trace.get("claims"), trace.get("abstained")
        if "authorized_evidence_cids" in trace:
            raise BundleError("QA trace may not self-attest an authorized CID list")
        authorized = _authorized_cids_from_hops(
            trace.get("authorized_retrieval_hops"),
            benchmark,
            protocol["evidence_budget"],
        )
        expected_fingerprint = hashlib.sha256(_canonical(sorted(authorized))).hexdigest()
        if trace.get("authorized_evidence_fingerprint") != expected_fingerprint:
            raise BundleError("QA authorized evidence fingerprint mismatch")
        if abstained is True:
            if answer != "" or claims != []:
                raise BundleError("QA abstention must use the canonical empty output")
            continue
        if abstained is not False or not isinstance(answer, str) or not answer or not isinstance(claims, list) or not claims:
            raise BundleError("non-abstained QA output requires answer and claims")
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) != {"evidence_cids", "text"}:
                raise BundleError("QA claim schema is invalid")
            if not isinstance(claim["text"], str) or not claim["text"].strip() or not isinstance(claim["evidence_cids"], list) or not claim["evidence_cids"]:
                raise BundleError("every QA claim requires citations")
            if any(not isinstance(cid, str) or not cid for cid in claim["evidence_cids"]):
                raise BundleError("every QA claim requires valid citations")
            if len(claim["evidence_cids"]) != len(set(claim["evidence_cids"])) or not set(claim["evidence_cids"]) <= set(authorized):
                raise BundleError("QA claim citations must be a unique authorized subset")
        rendered = "\n".join(claim["text"].strip() for claim in claims)
        if answer != rendered:
            raise BundleError("QA answer must render deterministically from ordered claims")


def _authorized_cids_from_hops(
    value: Any,
    benchmark: Any,
    evidence_budget: Any,
) -> list[str]:
    if (
        not isinstance(evidence_budget, dict)
        or set(evidence_budget)
        != {"max_characters", "max_hops", "max_records"}
        or any(
            not isinstance(evidence_budget.get(key), int)
            or isinstance(evidence_budget[key], bool)
            or evidence_budget[key] <= 0
            for key in evidence_budget
        )
    ):
        raise BundleError("QA evidence budget is invalid")
    if not isinstance(benchmark, dict) or not isinstance(benchmark.get("corpus"), list):
        raise BundleError("QA benchmark corpus is missing")
    anchored: dict[str, dict[str, Any]] = {}
    for record in benchmark["corpus"]:
        if not isinstance(record, dict) or set(record) < {"capture", "content", "doc_id", "source_identity"}:
            raise BundleError("QA benchmark corpus custody is incomplete")
        if record["capture"].get("content") != record["content"] or record["capture"].get("source_identity") != record["source_identity"]:
            raise BundleError("QA benchmark capture mapping is inconsistent")
        anchored[record["doc_id"]] = record["capture"]
    if not isinstance(value, list) or not value:
        raise BundleError("QA trace requires retained authorized retrieval hops")
    if len(value) > evidence_budget["max_hops"]:
        raise BundleError("QA authorized retrieval exceeds the hop budget")
    hops: set[int] = set()
    cids: list[str] = []
    content_characters = 0
    for hop in value:
        if (
            not isinstance(hop, dict)
            or set(hop) != {"hop", "rows"}
            or not isinstance(hop["hop"], int)
            or isinstance(hop["hop"], bool)
            or hop["hop"] < 0
            or hop["hop"] in hops
        ):
            raise BundleError("QA authorized retrieval hop schema is invalid")
        hops.add(hop["hop"])
        if not isinstance(hop["rows"], list):
            raise BundleError("QA authorized retrieval rows are invalid")
        for row in hop["rows"]:
            if not isinstance(row, dict) or set(row) != {"capture", "cid"}:
                raise BundleError("QA authorized retrieval row schema is invalid")
            if not isinstance(row.get("cid"), str) or not row["cid"] or not isinstance(row.get("capture"), dict):
                raise BundleError("QA authorized retrieval provenance is invalid")
            recomputed = _engine_evidence_cid(row["capture"])
            if row["cid"] != recomputed or anchored.get(row["cid"]) != row["capture"]:
                raise BundleError("QA authorized retrieval row does not match anchored corpus custody")
            cids.append(row["cid"])
            content_characters += len(row["capture"]["content"])
            if len(cids) > evidence_budget["max_records"]:
                raise BundleError("QA authorized retrieval exceeds the record budget")
            if content_characters > evidence_budget["max_characters"]:
                raise BundleError("QA authorized retrieval exceeds the character budget")
    if [hop["hop"] for hop in value] != list(range(len(value))):
        raise BundleError("QA authorized retrieval hops must be ordered and contiguous")
    if len(cids) != len(set(cids)):
        raise BundleError("QA authorized retrieval rows contain duplicate CIDs")
    return cids


def _engine_evidence_cid(capture: dict[str, Any]) -> str:
    from mnemosyne.ids import evidence_cid

    required = {"actor", "content", "content_pointer", "modality", "sensitivity", "source_identity", "source_type", "tenant_id", "user_id"}
    if set(capture) != required:
        raise BundleError("QA capture envelope schema is incomplete")
    if not all(isinstance(capture.get(key), str) and capture[key] for key in ("actor", "content", "modality", "source_identity", "source_type", "tenant_id", "user_id")):
        raise BundleError("QA capture envelope values are invalid")
    if capture["content_pointer"] is not None or not isinstance(capture["sensitivity"], int) or isinstance(capture["sensitivity"], bool):
        raise BundleError("QA capture envelope values are invalid")
    return evidence_cid(
        capture["content"], tenant_id=capture["tenant_id"], user_id=capture["user_id"],
        source_type=capture["source_type"], content_pointer=capture["content_pointer"],
        modality=capture["modality"], sensitivity=capture["sensitivity"],
    )


def _manifest_files(root: Path) -> tuple[str, ...]:
    manifest = _load_json(root / "bundle-manifest.json")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise BundleError("manifest inventory mismatch")
    return tuple(sorted(files))


def _reject_symlink_path(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path.cwd()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current /= part
        if current.is_symlink():
            raise BundleError("candidate manifest path components must not be symlinks")


def _require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise BundleError(f"QA {label} digest must be exact SHA-256")


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
        "qa_protocol_version",
        "interval_methods",
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
