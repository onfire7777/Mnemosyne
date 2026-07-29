"""Versioned, deterministic scoring profiles for public benchmarks."""

from __future__ import annotations

import json
import math
import random
import string
import unicodedata
from collections import Counter
from dataclasses import asdict
from typing import Any

from eval.harness.metrics import wilson_interval
from eval.public.adapters.pm_bench_triggerbench import recompute_metrics
from eval.public.adapters.working_memory_action_probe import score as score_working_action

BOOTSTRAP_ITERATIONS = 2_000
BOOTSTRAP_SEED = 1_234


class ScoringError(ValueError):
    """Labels, traces, or scoring metadata violated the profile contract."""


def score_profile(profile: str, labels: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    if profile == "wmbs-m01-v1":
        return _score_wmbs_m01(labels, traces)
    if profile == "wmbs-m10-v1":
        return _score_wmbs_m10(labels, traces)
    if profile in {"pm-bench-action-v1", "triggerbench-action-v1"}:
        return _score_pm_action(profile, labels, traces)
    if profile == "working-memory-action-v1":
        return _score_working_action(labels, traces)
    pairs = _bind(labels, traces)
    if profile == "longmemeval-retrieval-v1":
        _require_family(traces, "deterministic-retrieval")
        recall, ndcg = [], []
        for label, trace in pairs:
            gold = _unique_strings(label.get("gold_references"), "gold references")
            ranked = _ranked_strings(trace.get("ranked_retrieved_hits"))[:5]
            recall.append(len(set(ranked) & set(gold)) / len(gold))
            dcg = sum(1 / math.log2(rank + 1) for rank, item in enumerate(ranked, 1) if item in set(gold))
            ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(5, len(gold)) + 1))
            ndcg.append(dcg / ideal)
        values = {"recall_at_5": recall, "ndcg_at_5": ndcg}
        return _fractional_result(profile, "deterministic-retrieval", values)
    if profile == "hipporag-retrieval-v1":
        _require_family(traces, "deterministic-retrieval")
        by_k: dict[str, list[float]] = {"recall_at_2": [], "recall_at_5": []}
        for label, trace in pairs:
            gold = _unique_strings(label.get("gold_references"), "gold references")
            ranked = _ranked_strings(trace.get("ranked_retrieved_hits"))
            for k in (2, 5):
                by_k[f"recall_at_{k}"].append(len(set(ranked[:k]) & set(gold)) / len(gold))
        return _fractional_result(profile, "deterministic-retrieval", by_k)
    if profile == "qa-em-f1-v1":
        _require_family(traces, "qa")
        exact, f1 = [], []
        for label, trace in pairs:
            answers = _unique_strings(label.get("answers"), "answer aliases")
            prediction = trace.get("answer")
            if not isinstance(prediction, str):
                raise ScoringError("QA answer must be a string")
            exact.append(float(any(normalize_answer(prediction) == normalize_answer(answer) for answer in answers)))
            f1.append(max(_token_f1(prediction, answer) for answer in answers))
        em_successes = sum(int(value) for value in exact)
        em_interval = wilson_interval(em_successes, len(exact)).as_dict()
        return {
            "family": "qa",
            "profile": profile,
            "profile_version": 1,
            "total": len(pairs),
            "trace_count": len(pairs),
            "metrics": {"exact_match": _mean(exact), "token_f1": _mean(f1)},
            "intervals": {
                "exact_match": _wilson_projection(em_interval),
                "token_f1": _bootstrap(f1),
            },
        }
    raise ScoringError(f"unknown scoring profile: {profile}")


def _score_wmbs_m01(
    labels: list[dict[str, Any]], traces: list[dict[str, Any]]
) -> dict[str, Any]:
    from eval.public import wmbs_m01 as m01

    if (
        len(labels) != 1
        or len(traces) != 1
        or labels[0].get("case_id") != m01.MODULE_ID
        or traces[0].get("case_id") != m01.MODULE_ID
    ):
        raise ScoringError("M01 requires one trace bound to the M01 fixture")
    fixture = labels[0].get("fixture")
    if not isinstance(fixture, dict):
        raise ScoringError("M01 scoring fixture is missing")
    trace = traces[0]
    expected_fields = {
        "case_id",
        "clean_run_payloads",
        "exported_rows",
        "receipts",
        "restart_replay_payload",
        "scoring_family",
        "stored_projection",
    }
    unknown = set(trace) - expected_fields
    if unknown:
        raise ScoringError(f"unknown M01 trace fields: {sorted(unknown)}")
    missing = expected_fields - set(trace)
    if missing:
        raise ScoringError(f"missing M01 trace fields: {sorted(missing)}")
    measured = {
        "capture": m01.score_capture(
            fixture, trace.get("receipts"), trace.get("exported_rows")
        ),
        "canonical_replay_equality": m01.score_canonical_replay_equality(
            fixture,
            trace.get("clean_run_payloads"),
            trace.get("restart_replay_payload"),
        ),
        "provenance_retention": m01.score_provenance_retention(
            fixture, trace.get("stored_projection")
        ),
    }
    return json.loads(
        json.dumps(
            {
                "family": "whole-memory-development",
                "finite_corpus_only": True,
                "interval": {"method": "descriptive"},
                "metrics": measured,
                "passed": all(row["passed"] for row in measured.values()),
                "profile": "wmbs-m01-v1",
                "profile_version": 1,
                "total": 1,
                "trace_count": 1,
            },
            allow_nan=False,
        )
    )


def _score_wmbs_m10(
    labels: list[dict[str, Any]], traces: list[dict[str, Any]]
) -> dict[str, Any]:
    from eval.public import wmbs_m10 as m10

    def index(rows: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for row in rows:
            case_id = row.get("case_id")
            if not isinstance(case_id, str) or not case_id or case_id in indexed:
                raise ScoringError(f"duplicate or missing M10 {kind} case ID")
            indexed[case_id] = row
        return indexed

    expected, observed = index(labels, "label"), index(traces, "trace")
    if not expected or set(expected) != set(observed):
        raise ScoringError("M10 labels and traces do not match")
    cases = [m10.Case.from_dict(expected[key]["case"]) for key in sorted(expected)]
    records = [
        m10.AnswerEnvelope.from_dict(
            {
                field: value
                for field, value in observed[key].items()
                if field not in {"case_id", "scoring_family"}
            }
        )
        for key in sorted(expected)
    ]
    artifacts = [expected[key].get("calibration_artifact") for key in sorted(expected)]
    if not artifacts or any(artifact != artifacts[0] for artifact in artifacts[1:]):
        raise ScoringError("M10 labels do not share one calibration artifact")
    artifact = artifacts[0]
    if not isinstance(artifact, dict):
        raise ScoringError("M10 calibration artifact is missing")
    m10.verify_calibration_artifact(artifact)
    report = asdict(m10.score_records(cases, records))
    floor = artifact["useful_coverage_floor"]
    return {
        "family": "whole-memory-development",
        "finite_corpus_disclosure": m10.FINITE_CORPUS_DISCLOSURE,
        "interval": {"method": "descriptive"},
        "metrics": report,
        "meets_useful_coverage_floor": report["useful_coverage"] >= floor,
        "profile": "wmbs-m10-v1",
        "profile_version": 1,
        "total": len(cases),
        "trace_count": len(records),
        "useful_coverage_floor": floor,
    }


def _score_pm_action(
    profile: str,
    labels: list[dict[str, Any]],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    pairs = _bind_action(labels, traces, ("case_id", "step_id"))
    benchmark_name = "pm-bench" if profile == "pm-bench-action-v1" else "triggerbench"
    operating_points = {
        (
            label.get("operating_point_id"),
            _frozen_json(label.get("operating_point_config")),
        )
        for label, _ in pairs
    }
    if len(operating_points) != 1:
        raise ScoringError("action labels must declare one exact operating point")
    operating_point_id, frozen_config = operating_points.pop()
    merged: list[dict[str, Any]] = []
    for label, trace in pairs:
        if trace.get("category") != label.get("category"):
            raise ScoringError("action trace category does not match scoring custody")
        if trace.get("operating_point_id") != label.get("operating_point_id"):
            raise ScoringError("action trace operating point does not match scoring custody")
        expected = label.get("expected_due_action_ids")
        if not isinstance(expected, list) or any(
            not isinstance(value, str) or not value for value in expected
        ):
            raise ScoringError("action gold must be a string list")
        if "expected_due_action_ids" in trace and trace["expected_due_action_ids"] != expected:
            raise ScoringError("trace action gold does not match scoring custody")
        merged.append({**trace, "expected_due_action_ids": list(expected)})
    measured = recompute_metrics(
        merged,
        {
            "benchmark": benchmark_name,
            "operating_point_id": operating_point_id,
            "operating_point_config": json.loads(frozen_config),
        },
    )
    successes = sum(
        set(row["acted_action_ids"]) == set(row["expected_due_action_ids"])
        for row in merged
    )
    measured.update(
        family="deterministic-action",
        profile=profile,
        profile_version=1,
        total=len(merged),
        trace_count=len(merged),
        interval=_wilson_projection(wilson_interval(successes, len(merged)).as_dict()),
    )
    return measured


def _score_working_action(
    labels: list[dict[str, Any]], traces: list[dict[str, Any]]
) -> dict[str, Any]:
    pairs = _bind_action(labels, traces, ("case_id",))
    seeds = {label.get("seed") for label, _ in pairs}
    if len(seeds) != 1 or isinstance(next(iter(seeds)), bool) or not isinstance(next(iter(seeds)), int):
        raise ScoringError("working-action labels must declare one integer seed")
    seed = seeds.pop()
    measured = score_working_action(
        [
            {
                "case_id": label["case_id"],
                "expected_action_id": label.get("expected_action_id"),
                "expected_abstain": label.get("expected_abstain"),
            }
            for label, _ in pairs
        ],
        [trace for _, trace in pairs],
        seed=seed,
    )
    if any(trace.get("category") != label.get("category") for label, trace in pairs):
        raise ScoringError("working-action category does not match scoring custody")
    bootstrap = measured["bootstrap_macro_accuracy"]
    measured.update(
        family="deterministic-action",
        profile="working-memory-action-v1",
        profile_version=1,
        total=len(pairs),
        interval={
            "confidence": 0.95,
            "high": bootstrap["ci95"][1],
            "low": bootstrap["ci95"][0],
            "method": "bootstrap",
            "iterations": bootstrap["samples"],
            "seed": bootstrap["seed"],
        },
    )
    return measured


def _bind_action(
    labels: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    def index(rows: list[dict[str, Any]], kind: str) -> dict[tuple[str, ...], dict[str, Any]]:
        result: dict[tuple[str, ...], dict[str, Any]] = {}
        for row in rows:
            identifier = tuple(row.get(key) for key in keys)
            if any(not isinstance(value, str) or not value for value in identifier) or identifier in result:
                raise ScoringError(f"duplicate or missing {kind} action ID")
            result[identifier] = row
        return result

    _require_family(traces, "deterministic-action")
    gold, observed = index(labels, "label"), index(traces, "trace")
    if not gold or set(gold) != set(observed):
        raise ScoringError("label and trace actions do not match")
    return [(gold[key], observed[key]) for key in sorted(gold)]


def _frozen_json(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        raise ScoringError("operating point config must be a non-empty object")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalize_answer(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = "".join(" " if char in string.punctuation or unicodedata.category(char).startswith("P") else char for char in normalized)
    return " ".join(token for token in normalized.split() if token not in {"a", "an", "the"})


def _fractional_result(profile: str, family: str, values: dict[str, list[float]]) -> dict[str, Any]:
    intervals = {name: _bootstrap(items) for name, items in values.items()}
    first = next(iter(intervals.values()))
    return {
        "family": family,
        "profile": profile,
        "profile_version": 1,
        "total": len(next(iter(values.values()))),
        "trace_count": len(next(iter(values.values()))),
        "metrics": {name: _mean(items) for name, items in values.items()},
        "interval": first,
        "intervals": intervals,
    }


def _bind(labels: list[dict[str, Any]], traces: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    def index(rows: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            identifier = row.get("question_id")
            if not isinstance(identifier, str) or not identifier or identifier in result:
                raise ScoringError(f"duplicate or missing {kind} question ID")
            result[identifier] = row
        return result

    gold, observed = index(labels, "label"), index(traces, "trace")
    if not gold or set(gold) != set(observed):
        raise ScoringError("label and trace questions do not match")
    return [(gold[key], observed[key]) for key in sorted(gold)]


def _unique_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ScoringError(f"{label} must be a non-empty string list")
    return list(dict.fromkeys(value))


def _ranked_strings(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ScoringError("ranked hits must be a non-empty string list")
    if len(value) != len(set(value)):
        raise ScoringError("ranked hits contain duplicate IDs")
    return value


def _require_family(traces: list[dict[str, Any]], family: str) -> None:
    declared = {trace.get("scoring_family") for trace in traces}
    if declared != {family}:
        raise ScoringError("trace metric family does not match scoring profile family")


def _token_f1(prediction: str, answer: str) -> float:
    predicted, expected = normalize_answer(prediction).split(), normalize_answer(answer).split()
    overlap = sum((Counter(predicted) & Counter(expected)).values())
    if not predicted or not expected:
        return float(predicted == expected)
    if not overlap:
        return 0.0
    precision, recall = overlap / len(predicted), overlap / len(expected)
    return 2 * precision * recall / (precision + recall)


def _bootstrap(values: list[float]) -> dict[str, Any]:
    if not values:
        raise ScoringError("cannot bootstrap an empty sample")
    rng = random.Random(BOOTSTRAP_SEED)
    samples = sorted(_mean([values[rng.randrange(len(values))] for _ in values]) for _ in range(BOOTSTRAP_ITERATIONS))
    return {
        "confidence": 0.95,
        "high": samples[math.ceil(0.975 * len(samples)) - 1],
        "low": samples[math.floor(0.025 * len(samples))],
        "method": "bootstrap",
        "iterations": BOOTSTRAP_ITERATIONS,
        "seed": BOOTSTRAP_SEED,
    }


def _wilson_projection(interval: dict[str, Any]) -> dict[str, Any]:
    return {"confidence": 0.95, "high": interval["ci_high"], "low": interval["ci_low"], "method": "wilson"}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
