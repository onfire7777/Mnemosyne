"""G0 ablation gate.

The cognitive-architecture G0 spec requires every G1-G4 change to pre-register
the metric it is trying to improve, then ship only if that target improves by
the promised margin and no guardrail metric regresses. This module keeps that
policy independent from any one report producer: it consumes G0 report JSONs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class AblationDecision:
    """Machine-readable G0 gate result."""

    passed: bool
    change_id: str
    target_metric: str | None
    reasons: list[str]
    target_delta: float | None
    guardrail_results: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "g0.ablation-decision.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": self.passed,
            "change_id": self.change_id,
            "target_metric": self.target_metric,
            "target_delta": self.target_delta,
            "reasons": self.reasons,
            "guardrail_results": self.guardrail_results,
        }


def evaluate_ablation(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    preregistration: dict[str, Any],
) -> AblationDecision:
    """Evaluate the G0 target-up / guardrail-not-down rule.

    Required preregistration fields:
    - ``change_id``: stable identifier for the proposed change.
    - ``target_metric``: metric id expected to improve.
    - ``minimum_delta``: non-negative improvement margin.

    Optional fields:
    - ``direction``: ``increase`` or ``decrease``. Defaults to the target metric
      direction in the candidate report.
    - ``guardrail_metrics``: explicit guardrail ids. Defaults to every metric
      classified as a guardrail in either the baseline or candidate report.
    - ``guardrail_tolerances``: id -> allowed absolute regression amount.
    """

    change_id = str(preregistration.get("change_id") or "unregistered-change")
    target_id = preregistration.get("target_metric")
    reasons: list[str] = []
    guardrail_results: list[dict[str, Any]] = []

    if not target_id:
        reasons.append("missing preregistration.target_metric")
        return AblationDecision(False, change_id, None, reasons, None, guardrail_results)

    baseline = _metric_map(baseline_report)
    candidate = _metric_map(candidate_report)
    base_target = baseline.get(str(target_id))
    cand_target = candidate.get(str(target_id))
    if base_target is None or cand_target is None:
        reasons.append(f"target metric {target_id!r} missing from baseline or candidate")
        return AblationDecision(False, change_id, str(target_id), reasons, None, guardrail_results)
    if not _is_measured(base_target) or not _is_measured(cand_target):
        reasons.append(f"target metric {target_id!r} is not measured in both reports")
        return AblationDecision(False, change_id, str(target_id), reasons, None, guardrail_results)

    margin = float(preregistration.get("minimum_delta", 0.0))
    if margin < 0:
        reasons.append("minimum_delta must be non-negative")
        return AblationDecision(False, change_id, str(target_id), reasons, None, guardrail_results)

    direction = str(preregistration.get("direction") or cand_target.get("direction") or "")
    if direction not in {"increase", "decrease"}:
        reasons.append(f"target metric {target_id!r} has unsupported direction {direction!r}")
        return AblationDecision(False, change_id, str(target_id), reasons, None, guardrail_results)

    base_value = _metric_value(base_target)
    cand_value = _metric_value(cand_target)
    if base_value is None or cand_value is None:
        reasons.append(f"target metric {target_id!r} has a non-numeric value")
        return AblationDecision(False, change_id, str(target_id), reasons, None, guardrail_results)

    target_delta = cand_value - base_value
    target_pass = target_delta >= margin if direction == "increase" else target_delta <= -margin
    if not target_pass:
        op = ">=" if direction == "increase" else "<="
        required = margin if direction == "increase" else -margin
        reasons.append(
            f"target metric {target_id!r} delta {target_delta:.6g} did not meet {op} {required:.6g}"
        )

    guardrail_ids = preregistration.get("guardrail_metrics")
    if guardrail_ids is None:
        guardrail_ids = sorted(
            {
                metric_id
                for metric_id, metric in baseline.items()
                if metric.get("class") == "guardrail"
            }
            | {
                metric_id
                for metric_id, metric in candidate.items()
                if metric.get("class") == "guardrail"
            }
        )
    guardrail_tolerances = preregistration.get("guardrail_tolerances") or {}

    for guardrail_id in guardrail_ids:
        gid = str(guardrail_id)
        base_guard = baseline.get(gid)
        cand_guard = candidate.get(gid)
        result = {
            "metric": gid,
            "passed": False,
            "baseline": None,
            "candidate": None,
            "delta": None,
            "tolerance": float(guardrail_tolerances.get(gid, 0.0)),
            "reason": "",
        }
        if base_guard is None or cand_guard is None:
            result["reason"] = "missing from baseline or candidate"
            reasons.append(f"guardrail {gid!r} missing from baseline or candidate")
            guardrail_results.append(result)
            continue
        if not _is_measured(base_guard) or not _is_measured(cand_guard):
            result["reason"] = "not measured in both reports"
            reasons.append(f"guardrail {gid!r} is not measured in both reports")
            guardrail_results.append(result)
            continue
        base_guard_value = _metric_value(base_guard)
        cand_guard_value = _metric_value(cand_guard)
        if base_guard_value is None or cand_guard_value is None:
            result["reason"] = "non-numeric value"
            reasons.append(f"guardrail {gid!r} has a non-numeric value")
            guardrail_results.append(result)
            continue

        result["baseline"] = base_guard_value
        result["candidate"] = cand_guard_value
        result["delta"] = cand_guard_value - base_guard_value
        guard_direction = str(cand_guard.get("direction") or base_guard.get("direction") or "")
        tolerance = float(result["tolerance"])
        if guard_direction == "increase":
            passed = cand_guard_value + tolerance >= base_guard_value
        elif guard_direction == "decrease":
            passed = cand_guard_value <= base_guard_value + tolerance
        else:
            result["reason"] = f"unsupported guardrail direction {guard_direction!r}"
            reasons.append(f"guardrail {gid!r} has unsupported direction {guard_direction!r}")
            guardrail_results.append(result)
            continue
        result["passed"] = passed
        result["reason"] = "ok" if passed else "regressed beyond tolerance"
        if not passed:
            reasons.append(f"guardrail {gid!r} regressed beyond tolerance")
        guardrail_results.append(result)

    return AblationDecision(
        passed=not reasons,
        change_id=change_id,
        target_metric=str(target_id),
        reasons=reasons,
        target_delta=target_delta,
        guardrail_results=guardrail_results,
    )


def _metric_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = report.get("metrics") or []
    return {str(metric.get("id")): metric for metric in metrics if isinstance(metric, dict)}


def _is_measured(metric: dict[str, Any]) -> bool:
    return metric.get("status") == "measured"


def _metric_value(metric: dict[str, Any]) -> float | None:
    value = metric.get("value")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a preregistered G0 ablation gate")
    parser.add_argument("--baseline", required=True, type=Path, help="baseline G0 report JSON")
    parser.add_argument("--candidate", required=True, type=Path, help="candidate G0 report JSON")
    parser.add_argument("--prereg", required=True, type=Path, help="ablation preregistration JSON")
    parser.add_argument("--decision-log", type=Path, help="append the gate decision as JSONL")
    parser.add_argument("--print-json", action="store_true", help="print the full decision JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    decision = evaluate_ablation(
        _load_json(args.baseline),
        _load_json(args.candidate),
        _load_json(args.prereg),
    )
    decision_json = decision.as_dict()
    if args.decision_log:
        args.decision_log.parent.mkdir(parents=True, exist_ok=True)
        with args.decision_log.open("a") as fh:
            fh.write(json.dumps(decision_json, sort_keys=True) + "\n")
    if args.print_json:
        print(json.dumps(decision_json, indent=2, sort_keys=True))
    else:
        verdict = "PASS" if decision.passed else "FAIL"
        print(f"G0 ablation gate: {verdict} ({decision.change_id})")
        for reason in decision.reasons:
            print(f"- {reason}")
    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
