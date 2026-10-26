from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mnemosyne.models import Hit
from mnemosyne.retrieval import (
    QUERY_SUPPORT_STOPWORDS,
    _spans_calendar_period,
    compute_recency_decay,
    hit_recency_for_unit,
    query_support,
    similar_query_terms,
)


def _make_hit(
    id: str,
    text: str,
    score: float = 1.0,
    channel: str = "lexical",
    metadata: dict | None = None,
    trust_tier: int = 0,
) -> Hit:
    return Hit(
        id=id,
        kind="evidence",
        tenant_id="test-tenant",
        branch="main",
        text=text,
        score=score,
        channel=channel,
        trust_tier=trust_tier,
        metadata=metadata or {},
    )


def test_spans_calendar_period() -> None:
    # Exactly one month (March 2026: 31 days)
    start_march = datetime(2026, 3, 1, tzinfo=UTC)
    end_march = start_march + timedelta(days=31)
    assert _spans_calendar_period(start_march, end_march) is True

    # Exactly one non-leap year (365 days)
    start_year = datetime(2025, 1, 1, tzinfo=UTC)
    end_year = start_year + timedelta(days=365)
    assert _spans_calendar_period(start_year, end_year) is True

    # Leap year (2024: 366 days)
    start_leap = datetime(2024, 1, 1, tzinfo=UTC)
    end_leap = start_leap + timedelta(days=366)
    assert _spans_calendar_period(start_leap, end_leap) is True

    # 10 days (point event or short trip) -> False
    assert _spans_calendar_period(start_march, start_march + timedelta(days=10)) is False

    # Negative or zero span -> False
    assert _spans_calendar_period(start_march, start_march) is False
    assert _spans_calendar_period(end_march, start_march) is False


def test_compute_recency_decay() -> None:
    # Linear decay
    assert compute_recency_decay(0.0, function="linear", linear_window_days=60.0) == 1.0
    assert abs(compute_recency_decay(30.0, function="linear", linear_window_days=60.0) - 0.5) < 1e-6
    assert compute_recency_decay(60.0, function="linear", linear_window_days=60.0) == 0.1
    assert compute_recency_decay(100.0, function="linear", linear_window_days=60.0) == 0.1  # floor

    # Exponential decay
    assert compute_recency_decay(0.0, function="exponential", halflife_days=30.0) == 1.0
    assert abs(compute_recency_decay(30.0, function="exponential", halflife_days=30.0) - 0.5) < 1e-6
    assert abs(compute_recency_decay(60.0, function="exponential", halflife_days=30.0) - 0.25) < 1e-6

    # None function -> neutral 0.5
    assert compute_recency_decay(10.0, function="none") == 0.5


def test_hit_recency_for_unit() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)

    # Point event 10 days ago
    hit_point = _make_hit(
        id="h1", text="Point event",
        metadata={"created_at": (now - timedelta(days=10)).isoformat()},
    )
    recency = hit_recency_for_unit(hit_point, now=now, linear_window_days=60.0)
    assert recency > 0.8

    # Coarse calendar period: entire month of March (capped at neutral 0.5)
    start_march = datetime(2026, 3, 1, tzinfo=UTC)
    end_march = start_march + timedelta(days=31)
    hit_month = _make_hit(
        id="h2", text="Coarse monthly memory",
        metadata={"event_start": start_march.isoformat(), "event_end": end_march.isoformat()},
    )
    recency_month = hit_recency_for_unit(hit_month, now=now)
    assert recency_month <= 0.5

    # Missing timestamps -> neutral 0.5
    hit_empty = _make_hit(id="h3", text="No date")
    assert hit_recency_for_unit(hit_empty, now=now) == 0.5


def test_similar_query_terms_stemming_and_rejection() -> None:
    # Identical
    assert similar_query_terms("apple", "apple") is True

    # Valid inflectional suffixes: s, e, d, y, ed, es, ing
    assert similar_query_terms("cook", "cooked") is True
    assert similar_query_terms("cook", "cooks") is True
    assert similar_query_terms("bake", "bakes") is True
    assert similar_query_terms("park", "parks") is True

    # Rejection of false prefix matches (e.g., hamster vs hamstring, korea vs korean)
    assert similar_query_terms("hamster", "hamstring") is False
    assert similar_query_terms("korea", "korean") is False
    assert similar_query_terms("butter", "butterfly") is False


def test_query_support_stopwords_and_matching() -> None:
    # Question stopwords are ignored
    for sw in ["across", "ago", "between", "compare", "frequently", "instead", "number", "passed", "previously", "total", "typical"]:
        assert sw in QUERY_SUPPORT_STOPWORDS

    hit = _make_hit(id="h1", score=10.0, text="I visited Seattle in 2024 and bought coffee.")
    query = "How much total did I spend previously in Seattle?"
    supp = query_support(query, [hit])
    assert "seattle" in supp["matched_terms"]
    assert "total" not in supp["query_terms"]
    assert "previously" not in supp["query_terms"]


def test_month_length_interval_is_not_mistaken_for_calendar_precision():
    start = datetime(2026, 3, 15, tzinfo=UTC)
    assert not _spans_calendar_period(start, start + timedelta(days=31))
    month_start = datetime(2026, 3, 1, tzinfo=UTC)
    assert not _spans_calendar_period(month_start, month_start + timedelta(days=30))
    assert _spans_calendar_period(month_start, month_start + timedelta(days=31, seconds=-1))


def test_recency_invalid_inputs_do_not_invent_freshness():
    import pytest
    for invalid in (float('nan'), float('inf'), -float('inf')):
        assert compute_recency_decay(invalid) == 0.5
        assert compute_recency_decay(10, function='exponential', halflife_days=invalid) == 0.5
    with pytest.raises(ValueError):
        compute_recency_decay(1, function='typo')
    now = datetime(2026, 1, 1, tzinfo=UTC)
    future = _make_hit('future', 'planned event', metadata={'event_start': '2026-02-01'})
    assert hit_recency_for_unit(future, now) == 0.5
    assert hit_recency_for_unit(future, 'invalid') == 0.5


def test_parse_dt_normalizes_supported_types_and_rejects_lookalikes():
    import pytest
    from datetime import date, timezone
    from types import SimpleNamespace
    from mnemosyne.models import parse_dt
    expected = datetime(2026, 1, 1, tzinfo=UTC)
    assert parse_dt(date(2026, 1, 1)) == expected
    assert parse_dt(datetime(2026, 1, 1)) == expected
    assert parse_dt(datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2)))) == expected
    for invalid in (42, {}, SimpleNamespace(year=2026, month=1, day=1)):
        with pytest.raises(TypeError):
            parse_dt(invalid)
