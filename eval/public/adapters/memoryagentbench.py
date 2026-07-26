"""Deterministic MemoryAgentBench scoring and submission-envelope contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping


COMPETENCIES = (
    "retrieval",
    "test_time_learning",
    "long_range_understanding",
    "conflict_resolution",
)


class MemoryAgentBenchError(ValueError):
    """Raised when scored cases do not satisfy the canonical contract."""


def build_submission(
    cases: object,
    *,
    dataset_revision: object,
    protocol_id: object,
) -> dict[str, object]:
    """Build the canonical upstream submission envelope."""
    if not isinstance(dataset_revision, str) or re.fullmatch(
        r"[0-9a-f]{40}", dataset_revision
    ) is None:
        raise MemoryAgentBenchError("dataset_revision must be a lowercase 40-hex pin")
    if (
        not isinstance(protocol_id, str)
        or not protocol_id
        or protocol_id != protocol_id.strip()
    ):
        raise MemoryAgentBenchError("protocol_id must be a canonical non-empty string")

    return {
        "schema_version": 1,
        "dataset_revision": dataset_revision,
        "protocol_id": protocol_id,
        **score_cases(cases),
    }


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
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id != case_id.strip()
            or case_id in seen_ids
        ):
            raise MemoryAgentBenchError("case_id must be a unique non-empty string")
        if competency not in COMPETENCIES:
            raise MemoryAgentBenchError("competency is not canonical")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0 <= score <= 1
            or not math.isfinite(score)
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
