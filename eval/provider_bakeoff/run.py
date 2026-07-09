#!/usr/bin/env python3
"""Provider bake-off evidence harness.

This is a measurement/evidence wrapper around the existing eval harness and
``mneme provider-check``. It never changes provider defaults.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_PROTOCOL = "mnemosyne-provider-bakeoff-report-v1"
DEFAULT_FIXTURE = Path(__file__).with_name("sidecar-local-smoke.json")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"failed to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return payload


def _resolve_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _finding(code: str, message: str, *, severity: str = "error") -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _command(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise SystemExit(f"{field} must be a non-empty list of strings")
    return list(value)


def _subprocess_env(cwd: Path) -> dict[str, str]:
    env = os.environ.copy()
    paths = [str(cwd / "src"), str(cwd)]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _run_command(command: list[str], *, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            env=_subprocess_env(cwd),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 6),
            "timed_out": True,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    return {
        "command": command,
        "returncode": proc.returncode,
        "duration_seconds": round(time.monotonic() - started, 6),
        "timed_out": False,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_provider_check(manifest: Path, *, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "mnemosyne.cli",
        "provider-check",
        "--provider-manifest",
        str(manifest),
    ]
    run = _run_command(command, cwd=cwd, timeout_seconds=timeout_seconds)
    payload: dict[str, Any] | None = None
    if run.get("stdout"):
        try:
            parsed = json.loads(str(run["stdout"]))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            payload = parsed
    return {
        "source": "provider_manifest",
        "manifest_path": str(manifest),
        "ok": bool(payload and payload.get("ok") is True and run["returncode"] == 0),
        "run": run,
        "report": payload,
    }


def _load_provider_check_report(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "source": "provider_check_report",
        "path": str(path),
        "ok": payload.get("ok") is True,
        "report": payload,
    }


def _matching_markdown_path(report_path: Path) -> Path:
    return report_path.with_suffix(".md")


def _metric_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    seen_suite_counts: dict[str, int] = {}
    for suite in report.get("slo_suites", []):
        if not isinstance(suite, dict):
            continue
        suite_name = str(suite.get("suite") or "unknown")
        seen_suite_counts[suite_name] = seen_suite_counts.get(suite_name, 0) + 1
        suite_label = suite_name
        if suite_name == "retrieval":
            suite_label = "retrieval.synthetic" if seen_suite_counts[suite_name] > 1 else "retrieval.curated"
        for verdict in suite.get("verdicts", []):
            if not isinstance(verdict, dict):
                continue
            name = str(verdict.get("name") or "unnamed")
            metric_id = f"{suite_label}:{name}"
            ci = verdict.get("ci")
            rows[metric_id] = {
                "suite": suite_label,
                "name": name,
                "value": verdict.get("value"),
                "target": verdict.get("target"),
                "op": verdict.get("op"),
                "pass": verdict.get("pass") is True,
                "ci_present": isinstance(ci, dict) and ci.get("ci_low") is not None and ci.get("ci_high") is not None,
                "ci": ci if isinstance(ci, dict) else None,
            }
    for item in report.get("mandatory_classes", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "unnamed")
        rows[f"mandatory:{name}"] = {
            "suite": "mandatory",
            "name": name,
            "pass": item.get("passed") is True,
            "protected": True,
        }
    return rows


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    metrics = _metric_rows(report)
    numeric_metrics = {
        key: value
        for key, value in metrics.items()
        if isinstance(value.get("value"), int | float) and not isinstance(value.get("value"), bool)
    }
    return {
        "meta": report.get("meta") if isinstance(report.get("meta"), dict) else {},
        "ignition": report.get("ignition") if isinstance(report.get("ignition"), dict) else {},
        "overall": report.get("overall") if isinstance(report.get("overall"), dict) else {},
        "metric_count": len(metrics),
        "numeric_metric_count": len(numeric_metrics),
        "confidence_intervals_present": bool(numeric_metrics)
        and all(item.get("ci_present") is True for item in numeric_metrics.values()),
        "metrics": metrics,
    }


def _load_arm_report(
    arm: dict[str, Any],
    *,
    fixture_base: Path,
    cwd: Path,
    execute: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    name = str(arm.get("name") or "")
    if not name:
        raise SystemExit("every bake-off arm requires a name")

    run: dict[str, Any] | None = None
    if execute:
        run = _run_command(_command(arm.get("command"), field=f"arms.{name}.command"), cwd=cwd, timeout_seconds=timeout_seconds)

    report_path = _resolve_path(str(arm.get("report") or ""), base=fixture_base)
    md_path = _matching_markdown_path(report_path)
    findings: list[dict[str, str]] = []
    report: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    if not report_path.exists():
        findings.append(_finding("report_missing", f"arm {name} is missing JSON report {report_path}"))
    else:
        report = _read_json(report_path)
        summary = _summarize_report(report)
    if not md_path.exists():
        findings.append(_finding("markdown_report_missing", f"arm {name} is missing Markdown report {md_path}"))
    if run and run.get("returncode") not in (0, None):
        findings.append(_finding("arm_command_failed", f"arm {name} command exited {run['returncode']}"))
    if run and run.get("timed_out"):
        findings.append(_finding("arm_command_timeout", f"arm {name} command timed out after {timeout_seconds}s"))

    return {
        "name": name,
        "kind": arm.get("kind"),
        "command": arm.get("command"),
        "report_path": str(report_path),
        "markdown_path": str(md_path),
        "report_found": report is not None,
        "markdown_found": md_path.exists(),
        "run": run,
        "summary": summary,
        "findings": findings,
    }


def _compare_arms(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_metrics = ((baseline.get("summary") or {}).get("metrics") or {})
    candidate_metrics = ((candidate.get("summary") or {}).get("metrics") or {})
    common = sorted(set(baseline_metrics).intersection(candidate_metrics))
    rows: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for metric_id in common:
        base = baseline_metrics[metric_id]
        cand = candidate_metrics[metric_id]
        delta = None
        if isinstance(base.get("value"), int | float) and isinstance(cand.get("value"), int | float):
            delta = cand["value"] - base["value"]
        row = {
            "metric": metric_id,
            "baseline_value": base.get("value"),
            "candidate_value": cand.get("value"),
            "delta": delta,
            "baseline_pass": base.get("pass") is True,
            "candidate_pass": cand.get("pass") is True,
        }
        rows.append(row)
        if row["baseline_pass"] and not row["candidate_pass"]:
            regressions.append(row)
    return {
        "baseline": baseline["name"],
        "candidate": candidate["name"],
        "common_metric_count": len(common),
        "metrics": rows,
        "regressions": regressions,
    }


def build_report(
    fixture_path: Path = DEFAULT_FIXTURE,
    *,
    output_path: Path | None = None,
    provider_check_report: Path | None = None,
    provider_manifest: Path | None = None,
    noise_notes: Path | None = None,
    execute_arms: bool = False,
    cwd: Path | None = None,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    cwd = (cwd or _repo_root()).resolve()
    fixture_path = fixture_path.resolve()
    fixture = _read_json(fixture_path)
    findings: list[dict[str, str]] = []
    if fixture.get("protocol") != "mnemosyne-provider-bakeoff-v1":
        findings.append(_finding("fixture_protocol_unsupported", "fixture protocol must be mnemosyne-provider-bakeoff-v1"))

    arms_payload = fixture.get("arms")
    if not isinstance(arms_payload, list) or not arms_payload:
        raise SystemExit("fixture must contain non-empty arms list")
    arms = [
        _load_arm_report(
            arm,
            fixture_base=fixture_path.parent,
            cwd=cwd,
            execute=execute_arms,
            timeout_seconds=timeout_seconds,
        )
        for arm in arms_payload
        if isinstance(arm, dict)
    ]
    for arm in arms:
        findings.extend(arm["findings"])

    baselines = [arm for arm in arms if arm.get("kind") == "baseline"]
    if len(baselines) != 1:
        findings.append(_finding("baseline_count_invalid", "fixture must contain exactly one baseline arm"))
        baseline = arms[0]
    else:
        baseline = baselines[0]
    comparisons = [_compare_arms(baseline, arm) for arm in arms if arm is not baseline]
    if any(comparison["regressions"] for comparison in comparisons):
        findings.append(_finding("candidate_regression", "one or more candidates regressed on a baseline-passing verdict"))

    provider_check: dict[str, Any]
    if provider_check_report and provider_manifest:
        raise SystemExit("--provider-check-report and --provider-manifest are mutually exclusive")
    if provider_check_report:
        provider_check = _load_provider_check_report(provider_check_report.resolve())
    elif provider_manifest:
        provider_check = _run_provider_check(provider_manifest.resolve(), cwd=cwd, timeout_seconds=timeout_seconds)
    else:
        provider_check = {"source": "missing", "ok": False, "report": None}
    if provider_check.get("ok") is not True:
        findings.append(_finding("provider_check_missing_or_failed", "provider-check evidence is missing or failed"))

    required = fixture.get("required_evidence") if isinstance(fixture.get("required_evidence"), list) else []
    evidence = {
        "baseline_report_json": any(arm["kind"] == "baseline" and arm["report_found"] for arm in arms),
        "candidate_report_json": any(arm["kind"] != "baseline" and arm["report_found"] for arm in arms),
        "baseline_report_markdown": any(arm["kind"] == "baseline" and arm["markdown_found"] for arm in arms),
        "candidate_report_markdown": any(arm["kind"] != "baseline" and arm["markdown_found"] for arm in arms),
        "provider_check_report": provider_check.get("ok") is True,
        "noise_or_rerun_notes": bool(noise_notes and noise_notes.exists()),
    }
    missing_evidence = [str(item) for item in required if evidence.get(str(item)) is not True]
    for item in missing_evidence:
        severity = "warning" if item == "noise_or_rerun_notes" else "error"
        findings.append(_finding("required_evidence_missing", f"missing required evidence: {item}", severity=severity))

    confidence_intervals_present = all(
        (arm.get("summary") or {}).get("confidence_intervals_present") is True
        for arm in arms
        if arm.get("report_found")
    )
    acceptance = fixture.get("acceptance") if isinstance(fixture.get("acceptance"), dict) else {}
    promotion_reasons: list[str] = []
    if fixture.get("promotion_allowed_from_smoke") is not True:
        promotion_reasons.append("fixture_does_not_allow_promotion")
    if missing_evidence:
        promotion_reasons.append("required_evidence_missing")
    if provider_check.get("ok") is not True:
        promotion_reasons.append("provider_check_missing_or_failed")
    if not confidence_intervals_present and acceptance.get("confidence_intervals_required", True):
        promotion_reasons.append("confidence_intervals_missing")
    if any(comparison["regressions"] for comparison in comparisons):
        promotion_reasons.append("candidate_regression")
    if acceptance.get("margin_must_exceed_run_to_run_noise", True) and not evidence["noise_or_rerun_notes"]:
        promotion_reasons.append("noise_evidence_missing")

    report = {
        "protocol": REPORT_PROTOCOL,
        "generated_at": datetime.now(UTC).isoformat(),
        "ok": not any(item["severity"] == "error" for item in findings),
        "fixture": {
            "path": str(fixture_path),
            "protocol": fixture.get("protocol"),
            "purpose": fixture.get("purpose"),
            "promotion_allowed_from_smoke": fixture.get("promotion_allowed_from_smoke") is True,
        },
        "acceptance": acceptance,
        "evidence": evidence,
        "missing_evidence": missing_evidence,
        "provider_check": provider_check,
        "arms": arms,
        "comparisons": comparisons,
        "promotion": {
            "allowed": not promotion_reasons,
            "eligible_for_human_review": not any(reason.endswith("missing_or_failed") for reason in promotion_reasons)
            and "candidate_regression" not in promotion_reasons,
            "reasons": promotion_reasons,
        },
        "findings": findings,
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or summarize Mnemosyne provider bake-off evidence.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider-check-report", type=Path)
    parser.add_argument("--provider-manifest", type=Path)
    parser.add_argument("--noise-notes", type=Path, help="Path to run-to-run noise notes or rerun report")
    parser.add_argument("--execute-arms", action="store_true", help="Run each arm command before reading reports")
    parser.add_argument("--cwd", type=Path, default=_repo_root())
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless the evidence report is ok")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        args.fixture,
        output_path=args.output,
        provider_check_report=args.provider_check_report,
        provider_manifest=args.provider_manifest,
        noise_notes=args.noise_notes,
        execute_arms=args.execute_arms,
        cwd=args.cwd,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
