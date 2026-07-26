"""Deterministic, competency-separated MemoryAgentBench scoring."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


COMPETENCIES = (
    "retrieval",
    "test_time_learning",
    "long_range_understanding",
    "conflict_resolution",
)


class MemoryAgentBenchError(ValueError):
    """Raised when scored cases do not satisfy the canonical contract."""


def score_cases(cases: object) -> dict[str, object]:
    """Validate and aggregate scored cases without producing an overall score."""
    if isinstance(cases, (str, bytes, Mapping)) or not isinstance(cases, Iterable):
        raise MemoryAgentBenchError("cases must be an iterable of case objects")

    scores: dict[str, list[tuple[str, float]]] = {
        competency: [] for competency in COMPETENCIES
    }
    seen_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "case_id",
            "competency",
            "score",
        }:
            raise MemoryAgentBenchError("each case must use the canonical fields")
        case_id = case["case_id"]
        competency = case["competency"]
        score = case["score"]
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen_ids:
            raise MemoryAgentBenchError("case_id must be a unique non-empty string")
        if competency not in COMPETENCIES:
            raise MemoryAgentBenchError("competency is not canonical")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise MemoryAgentBenchError("score must be finite and between 0 and 1")
        seen_ids.add(case_id)
        scores[competency].append((case_id, float(score)))

    if any(not values for values in scores.values()):
        raise MemoryAgentBenchError("all competencies require non-empty coverage")

    return {
        "competencies": {
            competency: {
                "count": len(values),
                "mean": math.fsum(
                    score for _, score in sorted(values, key=lambda item: item[0])
                )
                / len(values),
            }
            for competency, values in scores.items()
        }
    }
