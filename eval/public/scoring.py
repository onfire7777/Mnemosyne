"""Versioned, deterministic scoring profiles for public benchmarks."""

from __future__ import annotations

import math
import random
import string
import unicodedata
from collections import Counter
from typing import Any

from eval.harness.metrics import wilson_interval

BOOTSTRAP_ITERATIONS = 2_000
BOOTSTRAP_SEED = 1_234


class ScoringError(ValueError):
    """Labels, traces, or scoring metadata violated the profile contract."""


def score_profile(profile: str, labels: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
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
