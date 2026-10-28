from __future__ import annotations

from datetime import UTC, datetime

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, parse_dt
from mnemosyne.retrieval import query_time_window


NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
NOW_STR = "2026-10-15T12:00:00Z"


def test_rolling_relative_time_windows() -> None:
    # 1. "in the past 3 days" (event axis for activities)
    w1 = query_time_window("What did I eat in the past 3 days?", now=NOW, query_timezone="UTC")
    assert w1 is not None
    assert w1.axis == "event"
    assert w1.start == datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
    assert w1.end == NOW

    # Speech query uses source axis
    w1_source = query_time_window("What did I say in the past 3 days?", now=NOW, query_timezone="UTC")
    assert w1_source is not None
    assert w1_source.axis == "source"

    # 2. "in the past three months"
    w2 = query_time_window("Where did I travel in the past three months?", now=NOW, query_timezone="UTC")
    assert w2 is not None
    assert w2.start == datetime(2026, 7, 17, 0, 0, tzinfo=UTC)
    assert w2.end == NOW

    # 3. "during the last 2 weeks"
    w3 = query_time_window("What books did I read during the last 2 weeks?", now=NOW, query_timezone="UTC")
    assert w3 is not None
    assert w3.start == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert w3.end == NOW

    # 4. "during the past year"
    w4 = query_time_window("What projects did I launch during the past year?", now=NOW, query_timezone="UTC")
    assert w4 is not None
    assert w4.start == datetime(2025, 10, 15, 0, 0, tzinfo=UTC)
    assert w4.end == NOW

    # 5. "since the start of the year"
    w5 = query_time_window("How many miles did I run since the start of the year?", now=NOW, query_timezone="UTC")
    assert w5 is not None
    assert w5.start == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    assert w5.end == NOW


def test_source_time_fallback_for_non_happen_event_queries() -> None:
    engine = LocalMemoryEngine()
    try:
        # Passage without explicit event_start, but created in May 2026
        engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I finished reading Neuromancer and loved the ending.",
                created_at=parse_dt("2026-05-15T14:00:00Z"),
                metadata={},
            )
        )
        # Non-happen event query: falls back to created_at
        res = engine.retrieve(
            "What did I read in May 2026?",
            tenant_id="t1",
            record_access=False,
            filt={"query_mode": "passages", "evaluated_at": NOW_STR},
        )
        assert len(res.hits) == 1
        assert "Neuromancer" in res.hits[0].text
    finally:
        engine.close()


def test_bare_happen_does_not_fall_back_to_created_at() -> None:
    engine = LocalMemoryEngine()
    try:
        # Passage without event_start, created in May 2026
        engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I recorded some casual notes about my week.",
                created_at=parse_dt("2026-05-15T14:00:00Z"),
                metadata={},
            )
        )
        # Bare happen query: should NOT fall back to created_at
        res = engine.retrieve(
            "What happened in May 2026?",
            tenant_id="t1",
            record_access=False,
            filt={"query_mode": "passages", "evaluated_at": NOW_STR},
        )
        assert len(res.hits) == 0
    finally:
        engine.close()


def test_soft_temporal_fallback_when_hard_window_empty() -> None:
    engine = LocalMemoryEngine()
    try:
        # Conference event occurred on June 3, 2026 (outside May 2026)
        c_id = engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I attended the PyCon AI Conference keynote in Pittsburgh.",
                created_at=parse_dt("2026-06-03T18:00:00Z"),
                metadata={
                    "event_start": "2026-06-03T09:00:00Z",
                    "event_end": "2026-06-03T17:00:00Z",
                },
            )
        )
        # Query specifies May 2026; 0 hits inside hard window
        res = engine.retrieve(
            "What conference did I attend in May 2026?",
            tenant_id="t1",
            record_access=False,
            filt={"query_mode": "passages", "evaluated_at": NOW_STR},
        )
        assert len(res.hits) == 1
        assert res.hits[0].id == c_id
        assert res.explain.get("time_window", {}).get("fallback") == "soft_temporal_proximity"
    finally:
        engine.close()


def test_sequence_chronological_ordering_without_window() -> None:
    engine = LocalMemoryEngine()
    try:
        h1 = engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I visited the Louvre museum.",
                created_at=parse_dt("2025-01-10T10:00:00Z"),
                metadata={"event_start": "2025-01-10T10:00:00Z"},
            )
        )
        h2 = engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I visited the Prado museum.",
                created_at=parse_dt("2025-06-20T10:00:00Z"),
                metadata={"event_start": "2025-06-20T10:00:00Z"},
            )
        )
        h3 = engine.append_evidence(
            Evidence(
                tenant_id="t1",
                branch="main",
                user_id="u",
                actor="user",
                source_type="conversation",
                content="I visited the Uffizi museum.",
                created_at=parse_dt("2024-11-05T10:00:00Z"),
                metadata={"event_start": "2024-11-05T10:00:00Z"},
            )
        )

        # Earliest to latest
        res_earliest = engine.retrieve(
            "order of the museums I visited from earliest to latest",
            tenant_id="t1",
            record_access=False,
            filt={"query_mode": "passages", "evaluated_at": NOW_STR},
        )
        assert [h.id for h in res_earliest.hits[:3]] == [h3, h1, h2]

        # Latest to earliest
        res_latest = engine.retrieve(
            "order of the museums I visited from latest to earliest",
            tenant_id="t1",
            record_access=False,
            filt={"query_mode": "passages", "evaluated_at": NOW_STR},
        )
        assert [h.id for h in res_latest.hits[:3]] == [h2, h1, h3]
    finally:
        engine.close()
