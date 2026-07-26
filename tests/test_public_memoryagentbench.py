from __future__ import annotations

import math

import pytest

from eval.public.adapters.memoryagentbench import MemoryAgentBenchError, score_cases


def _case(case_id: str, competency: str, score: float) -> dict[str, object]:
    return {"case_id": case_id, "competency": competency, "score": score}


def test_score_cases_reports_each_competency_separately_in_canonical_order() -> None:
    result = score_cases(
        [
            _case("conflict-1", "conflict_resolution", 0.25),
            _case("retrieval-1", "retrieval", 1.0),
            _case("learning-1", "test_time_learning", 0.5),
            _case("range-1", "long_range_understanding", 0.75),
            _case("retrieval-2", "retrieval", 0.0),
        ]
    )

    assert result == {
        "competencies": {
            "retrieval": {"count": 2, "mean": 0.5},
            "test_time_learning": {"count": 1, "mean": 0.5},
            "long_range_understanding": {"count": 1, "mean": 0.75},
            "conflict_resolution": {"count": 1, "mean": 0.25},
        }
    }
    assert not ({"overall", "composite", "mean", "score"} & result.keys())


def test_score_cases_is_deterministic_for_equivalent_input_orderings() -> None:
    cases = [
        _case("retrieval-1", "retrieval", 0.2),
        _case("retrieval-2", "retrieval", 0.4),
        _case("learning-1", "test_time_learning", 0.6),
        _case("range-1", "long_range_understanding", 0.8),
        _case("conflict-1", "conflict_resolution", 1.0),
    ]

    assert score_cases(cases) == score_cases(reversed(cases))


@pytest.mark.parametrize(
    "cases",
    [
        [],
        [_case("", "retrieval", 0.5)],
        [_case("retrieval-1", "unknown", 0.5)],
        [_case("retrieval-1", "retrieval", True)],
        [_case("retrieval-1", "retrieval", math.nan)],
        [_case("retrieval-1", "retrieval", math.inf)],
        [_case("retrieval-1", "retrieval", -0.01)],
        [_case("retrieval-1", "retrieval", 1.01)],
        [{"case_id": "retrieval-1", "competency": "retrieval"}],
        [
            _case("same-id", "retrieval", 0.5),
            _case("same-id", "test_time_learning", 0.5),
        ],
    ],
)
def test_score_cases_fails_closed_for_invalid_cases(
    cases: list[dict[str, object]],
) -> None:
    with pytest.raises(MemoryAgentBenchError):
        score_cases(cases)


def test_score_cases_requires_non_empty_coverage_for_all_four_competencies() -> None:
    with pytest.raises(MemoryAgentBenchError):
        score_cases(
            [
                _case("retrieval-1", "retrieval", 0.5),
                _case("learning-1", "test_time_learning", 0.5),
                _case("range-1", "long_range_understanding", 0.5),
            ]
        )


@pytest.mark.parametrize(
    "cases",
    [
        None,
        "not-a-case-sequence",
        {"case_id": "retrieval-1", "competency": "retrieval", "score": 0.5},
        [object()],
        [
            {
                "case_id": "retrieval-1",
                "competency": "retrieval",
                "score": 0.5,
                "extra": "not canonical",
            }
        ],
    ],
)
def test_score_cases_rejects_non_canonical_input(cases: object) -> None:
    with pytest.raises(MemoryAgentBenchError):
        score_cases(cases)
