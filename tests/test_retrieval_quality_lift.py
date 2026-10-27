"""Unit tests for retrieval quality lift, temporal reasoning, and recency ranking.

Verifies:
1. rank_passages recency weighting boosts recent sessions over stale sessions.
2. rank_passages currency query boost prioritizes latest session on currency cues.
3. query_time_window avoids false calendar-day windows on between-event queries.
4. query_time_window avoids false monthly windows on target-date questions.
5. query_time_window correctly parses 'N weeks ago' into the corresponding calendar week.
6. schema_fast_path_rerank applies currency schema support to recent hits on currency queries.
"""

from datetime import UTC, datetime

from mnemosyne.models import Hit
from mnemosyne.policy import OperatingPolicy
from mnemosyne.passages import rank_passages
from mnemosyne.retrieval import (
    _current_currency_hit_id,
    query_time_window,
    schema_fast_path_rerank,
)


def _make_passage_hit(
    hit_id: str,
    text: str,
    created_at: str,
    score: float = 0.0,
) -> Hit:
    return Hit(
        id=hit_id,
        kind="evidence",
        tenant_id="tenant-test",
        branch="main",
        text=text,
        score=score,
        channel="evidence",
        metadata={
            "source_type": "session",
            "_candidate_created_at": created_at,
        },
    )


def test_rank_passages_recency_decay_boosts_recent_session() -> None:
    older_text = "I play tennis three times a week at the local park with John and Sarah."
    newer_text = "I play tennis once a month at the local park due to a busy schedule."

    # Both passages talk about playing tennis at the local park
    older_hit = _make_passage_hit(
        "sess_old",
        older_text,
        "2023-01-10T10:00:00+00:00",
    )
    newer_hit = _make_passage_hit(
        "sess_new",
        newer_text,
        "2023-06-15T10:00:00+00:00",
    )

    owner = object()
    query = "How often do I play tennis at the local park?"
    ranked = rank_passages(owner, query, [older_hit, newer_hit], k=2)

    assert len(ranked) == 2
    assert ranked[0].id == "sess_new"
    assert ranked[0].score > ranked[1].score


def test_rank_passages_currency_cue_boosts_latest() -> None:
    p1 = _make_passage_hit(
        "cand_1",
        "We have four dozen eggs stocked up in our refrigerator for the weekend bake.",
        "2023-03-01T12:00:00+00:00",
    )
    p2 = _make_passage_hit(
        "cand_2",
        "We have two dozen eggs stocked up in our refrigerator currently.",
        "2023-05-20T12:00:00+00:00",
    )

    owner = object()
    query = "How many dozen eggs do we currently have stocked up in our refrigerator?"
    ranked = rank_passages(owner, query, [p1, p2], k=2)

    assert len(ranked) == 2
    assert ranked[0].id == "cand_2"
    assert ranked[0].score > ranked[1].score


def test_query_time_window_between_events_returns_none() -> None:
    query = "How many days had passed between the Sunday mass at St. Mary's Church and the Ash Wednesday service at the cathedral?"
    local_now = datetime(2023, 7, 1, 12, 0, 0, tzinfo=UTC)
    window = query_time_window(query, local_now)
    assert window is None


def test_query_time_window_what_was_the_date_returns_none() -> None:
    query = "What was the date on which I attended the first BBQ event in June?"
    local_now = datetime(2023, 7, 1, 12, 0, 0, tzinfo=UTC)
    window = query_time_window(query, local_now)
    assert window is None


def test_query_time_window_n_weeks_ago_parses_calendar_week() -> None:
    query = "I mentioned participating in a sports event two weeks ago. What was the event?"
    # Saturday July 1, 2023
    local_now = datetime(2023, 7, 1, 12, 0, 0, tzinfo=UTC)
    window = query_time_window(query, local_now, query_timezone="UTC")

    assert window is not None
    assert "two weeks ago" in window.label
    assert window.axis == "source"
    # Target date 2 weeks ago: Saturday June 17, 2023
    # Window spans Monday June 12 to Monday June 19
    assert window.start.astimezone(UTC) == datetime(2023, 6, 12, 0, 0, 0, tzinfo=UTC)
    assert window.end.astimezone(UTC) == datetime(2023, 6, 19, 0, 0, 0, tzinfo=UTC)


def test_current_currency_hit_id_identifies_latest_match() -> None:
    h1 = _make_passage_hit("h1", "Company update on Rachel", "2023-05-20T10:00:00+00:00", score=10.0)
    h2 = _make_passage_hit("h2", "Company update on Rachel", "2023-05-25T14:00:00+00:00", score=9.8)
    h3 = _make_passage_hit("h3", "Irrelevant unrelated text", "2023-05-26T10:00:00+00:00", score=1.5)

    latest_id = _current_currency_hit_id(
        "What company is Rachel currently working at?",
        [h1, h2, h3],
    )
    assert latest_id == "h2"


def test_schema_fast_path_rerank_applies_currency_boost() -> None:
    h1 = _make_passage_hit("h1", "Company update on Rachel", "2023-05-20T10:00:00+00:00", score=10.0)
    h2 = _make_passage_hit("h2", "Company update on Rachel", "2023-05-25T14:00:00+00:00", score=9.8)

    policy = OperatingPolicy()
    reranked, explain = schema_fast_path_rerank(
        "What company is Rachel currently working at?",
        [h1, h2],
        policy,
    )

    assert explain["applied"] is True
    assert "current currency schema support" in explain["reasons"].values()
    assert reranked[0].id == "h2"
    assert "schema" in reranked[0].channel
