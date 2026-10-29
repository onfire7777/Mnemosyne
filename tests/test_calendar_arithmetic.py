"""Tests for calendar arithmetic pre-computation, CalendarDelta, and event timeline construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from mnemosyne.models import Hit
from mnemosyne.retrieval import (
    CalendarDelta,
    build_event_timeline,
    compute_calendar_delta,
)


def test_calendar_delta_same_day():
    """Verify delta computation for same-day target and reference."""
    ref = datetime(2023, 6, 15, 14, 0, tzinfo=UTC)
    tgt = datetime(2023, 6, 15, 9, 30, tzinfo=UTC)
    delta = compute_calendar_delta(ref, tgt)

    assert delta.delta_days == 0
    assert delta.delta_weeks == 0
    assert delta.delta_months == 0
    assert delta.delta_years == 0
    assert delta.is_past is True
    assert delta.formatted_relative == "today"


def test_calendar_delta_days_and_weeks():
    """Verify day and week relative intervals."""
    ref = datetime(2023, 5, 29, 12, 0, tzinfo=UTC)

    # 1 day ago
    d1 = compute_calendar_delta(ref, datetime(2023, 5, 28, 12, 0, tzinfo=UTC))
    assert d1.delta_days == 1
    assert d1.delta_weeks == 0
    assert d1.is_past is True
    assert d1.formatted_relative == "1 day ago"

    # 7 days ago -> 1 week
    d7 = compute_calendar_delta(ref, datetime(2023, 5, 22, 12, 0, tzinfo=UTC))
    assert d7.delta_days == 7
    assert d7.delta_weeks == 1
    assert d7.formatted_relative == "1 week ago"

    # 28 days ago -> 4 weeks
    d28 = compute_calendar_delta(ref, datetime(2023, 5, 1, 12, 0, tzinfo=UTC))
    assert d28.delta_days == 28
    assert d28.delta_weeks == 4
    assert d28.formatted_weeks_relative == "4 weeks ago"
    assert d28.formatted_days_relative == "28 days ago"


def test_calendar_delta_month_boundaries_and_leap_years():
    """Verify exact month calculation across differing month lengths and leap years."""
    # Jan 31 to Feb 28 in non-leap year (2023)
    ref_2023 = datetime(2023, 2, 28, 12, 0, tzinfo=UTC)
    tgt_2023 = datetime(2023, 1, 31, 12, 0, tzinfo=UTC)
    delta_non_leap = compute_calendar_delta(ref_2023, tgt_2023)
    assert delta_non_leap.delta_days == 28
    assert delta_non_leap.delta_months == 1
    assert delta_non_leap.delta_years == 0
    assert delta_non_leap.formatted_relative == "1 month ago"

    # Jan 31 to Feb 29 in leap year (2024)
    ref_2024 = datetime(2024, 2, 29, 12, 0, tzinfo=UTC)
    tgt_2024 = datetime(2024, 1, 31, 12, 0, tzinfo=UTC)
    delta_leap = compute_calendar_delta(ref_2024, tgt_2024)
    assert delta_leap.delta_days == 29
    assert delta_leap.delta_months == 1
    assert delta_leap.delta_years == 0

    # Leap day itself: 2024-02-29 to 2024-03-01
    d_leap_day = compute_calendar_delta(
        datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 2, 29, tzinfo=UTC)
    )
    assert d_leap_day.delta_days == 1
    assert d_leap_day.formatted_relative == "1 day ago"


def test_calendar_delta_years_and_future_dates():
    """Verify full year deltas and future date formatting."""
    ref = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
    tgt_past_year = datetime(2022, 6, 1, 12, 0, tzinfo=UTC)
    d_years = compute_calendar_delta(ref, tgt_past_year)

    assert d_years.delta_years == 2
    assert d_years.delta_months == 24
    assert d_years.is_past is True
    assert d_years.formatted_relative == "2 years ago"

    # Future date
    tgt_future = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
    d_future = compute_calendar_delta(ref, tgt_future)
    assert d_future.delta_days == 14
    assert d_future.delta_weeks == 2
    assert d_future.is_past is False
    assert d_future.formatted_relative == "in 2 weeks"


def test_calendar_delta_string_inputs():
    """Verify compute_calendar_delta parses ISO strings transparently."""
    ref_str = "2023-10-15T08:00:00Z"
    tgt_str = "2023-10-05T12:00:00Z"
    delta = compute_calendar_delta(ref_str, tgt_str)

    assert isinstance(delta, CalendarDelta)
    assert delta.delta_days == 10
    assert delta.delta_weeks == 1
    assert delta.is_past is True
    assert delta.formatted_relative == "1 week ago"


def test_build_event_timeline_chronological_ordering():
    """Verify build_event_timeline orders hits chronologically and computes inter-event deltas."""
    h_july = Hit(
        id="h_july",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Attended summer festival in July.",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2023-07-20T18:00:00Z"},
    )
    h_feb = Hit(
        id="h_feb",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Booked trip to Tokyo in February.",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2023-02-10T10:00:00Z"},
    )
    h_may = Hit(
        id="h_may",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Ran half marathon in May.",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2023-05-15T09:00:00Z"},
    )

    reference_date = "2023-08-01T00:00:00Z"
    timeline = build_event_timeline(
        [h_july, h_feb, h_may], reference_date=reference_date
    )

    # Must be sorted earliest to latest
    assert len(timeline) == 3
    assert timeline[0]["hit_id"] == "h_feb"
    assert timeline[1]["hit_id"] == "h_may"
    assert timeline[2]["hit_id"] == "h_july"

    # Consecutive event differences
    assert timeline[0]["days_since_previous"] is None
    # From Feb 10, 2023 to May 15, 2023: 18 days in Feb + 31 in Mar + 30 in Apr + 15 in May = 94 days
    assert timeline[1]["days_since_previous"] == 94
    # From May 15, 2023 to July 20, 2023: 16 in May + 30 in Jun + 20 in Jul = 66 days
    assert timeline[2]["days_since_previous"] == 66

    # Verify calendar_delta attached to hit metadata
    assert "calendar_delta" in h_feb.metadata
    assert h_feb.metadata["calendar_delta"]["delta_days"] > 100


def test_build_event_timeline_sunday_mass_to_ash_wednesday():
    """Verify exact days between Sunday Mass and Ash Wednesday as in benchmark questions."""
    h_sunday = Hit(
        id="sunday_mass",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Attended Sunday mass at St. Mary's.",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2024-02-11T10:00:00Z"},
    )
    h_ash = Hit(
        id="ash_wednesday",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Attended Ash Wednesday service at the cathedral.",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2024-02-14T19:00:00Z"},
    )

    timeline = build_event_timeline(
        [h_ash, h_sunday], reference_date="2024-02-20T00:00:00Z"
    )
    assert len(timeline) == 2
    assert timeline[0]["hit_id"] == "sunday_mass"
    assert timeline[1]["hit_id"] == "ash_wednesday"
    assert timeline[1]["days_since_previous"] == 3


def test_calendar_delta_cross_timezone_utc_normalization():
    """Verify timezone normalization prevents negative delta_days and inverted relative strings."""
    tz_est = timezone(timedelta(hours=-5))
    tgt = datetime(2024, 1, 2, 1, 0, tzinfo=UTC)
    ref = datetime(
        2024, 1, 1, 23, 0, tzinfo=tz_est
    )  # 2024-01-02 04:00 UTC (tgt is 3h in the past)

    delta = compute_calendar_delta(ref, tgt)
    assert delta.delta_days == 0
    assert delta.delta_weeks == 0
    assert delta.is_past is True
    assert delta.formatted_relative == "today"

    # Future direction
    delta_fut = compute_calendar_delta(tgt, ref)
    assert delta_fut.delta_days == 0
    assert delta_fut.delta_weeks == 0
    assert delta_fut.is_past is False
    assert delta_fut.formatted_relative == "today"


def test_calendar_delta_object_vs_string_parity():
    """Verify exact parity between datetime object and ISO string representation across timezones."""
    tz_est = timezone(timedelta(hours=-5))
    dt_obj = datetime(2023, 1, 1, 22, 0, tzinfo=tz_est)
    dt_str = "2023-01-01T22:00:00-05:00"
    ref = datetime(2023, 1, 10, 0, 0, tzinfo=UTC)

    d_obj = compute_calendar_delta(ref, dt_obj)
    d_str = compute_calendar_delta(ref, dt_str)

    assert d_obj.delta_days == 8
    assert d_str.delta_days == 8
    assert d_obj.delta_days == d_str.delta_days
    assert d_obj.formatted_relative == d_str.formatted_relative


def test_calendar_delta_leap_day_to_feb_28_alignment():
    """Verify leap day (Feb 29) to Feb 28 in non-leap year aligns to full years."""
    tgt = datetime(2024, 2, 29, tzinfo=UTC)

    # 1 year later (2025-02-28, non-leap)
    d1 = compute_calendar_delta(datetime(2025, 2, 28, tzinfo=UTC), tgt)
    assert d1.delta_years == 1
    assert d1.delta_months == 12
    assert d1.formatted_relative == "1 year ago"

    # 2 years later (2026-02-28, non-leap)
    d2 = compute_calendar_delta(datetime(2026, 2, 28, tzinfo=UTC), tgt)
    assert d2.delta_years == 2
    assert d2.delta_months == 24
    assert d2.formatted_relative == "2 years ago"

    # 3 years later (2027-02-28, non-leap)
    d3 = compute_calendar_delta(datetime(2027, 2, 28, tzinfo=UTC), tgt)
    assert d3.delta_years == 3
    assert d3.delta_months == 36
    assert d3.formatted_relative == "3 years ago"

    # 4 years across non-leap century: 1896-02-29 to 1900-02-28
    d_cent = compute_calendar_delta(
        datetime(1900, 2, 28, tzinfo=UTC), datetime(1896, 2, 29, tzinfo=UTC)
    )
    assert d_cent.delta_years == 4
    assert d_cent.delta_months == 48
    assert d_cent.formatted_relative == "4 years ago"

    # 1 year across leap century: 2000-02-29 to 2001-02-28
    d_cent_leap = compute_calendar_delta(
        datetime(2001, 2, 28, tzinfo=UTC), datetime(2000, 2, 29, tzinfo=UTC)
    )
    assert d_cent_leap.delta_years == 1
    assert d_cent_leap.delta_months == 12
    assert d_cent_leap.formatted_relative == "1 year ago"

    # Future direction: 2024-02-29 (ref) to 2025-02-28 (tgt)
    d_fut1 = compute_calendar_delta(tgt, datetime(2025, 2, 28, tzinfo=UTC))
    assert d_fut1.delta_years == 1
    assert d_fut1.delta_months == 12
    assert d_fut1.formatted_relative == "in 1 year"


def test_calendar_delta_graceful_invalid_date_strings():
    """Verify unparseable date strings fall back gracefully to utc_now instead of crashing."""
    d_invalid_tgt = compute_calendar_delta("2024-01-01", "invalid-date-string")
    assert isinstance(d_invalid_tgt, CalendarDelta)
    assert d_invalid_tgt.delta_days >= 0

    d_invalid_ref = compute_calendar_delta("invalid-ref-string", "2024-01-01")
    assert isinstance(d_invalid_ref, CalendarDelta)
    assert d_invalid_ref.delta_days >= 0


def test_build_event_timeline_invalid_reference_string():
    """Verify build_event_timeline handles invalid reference_date string without raising ValueError."""
    h = Hit(
        id="h_valid",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="A valid event.",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2024-05-01T12:00:00Z"},
    )
    timeline = build_event_timeline([h], reference_date="bad-ref-date")
    assert len(timeline) == 1
    assert timeline[0]["hit_id"] == "h_valid"


def test_build_event_timeline_mixed_timezones_monotonicity():
    """Verify chronological monotonicity and non-negative interval metrics across mixed timezones."""
    tz_est = timezone(timedelta(hours=-5))
    tz_jst = timezone(timedelta(hours=9))

    # Event 1: 2023-01-02 01:00 UTC
    # Event 2: 2023-01-01 22:00 EST -> 2023-01-02 03:00 UTC (occurs 2 hours AFTER Event 1)
    # Event 3: 2023-01-02 18:00 JST -> 2023-01-02 09:00 UTC (occurs 6 hours AFTER Event 2)
    h1 = Hit(
        id="e1",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Event 1",
        score=1.0,
        channel="evidence",
        metadata={"event_start": "2023-01-02T01:00:00Z"},
    )
    h2 = Hit(
        id="e2",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Event 2",
        score=1.0,
        channel="evidence",
        metadata={"event_start": datetime(2023, 1, 1, 22, 0, tzinfo=tz_est)},
    )
    h3 = Hit(
        id="e3",
        kind="evidence",
        tenant_id="t",
        branch="main",
        text="Event 3",
        score=1.0,
        channel="evidence",
        metadata={"event_start": datetime(2023, 1, 2, 18, 0, tzinfo=tz_jst)},
    )

    ref = datetime(2023, 1, 10, 0, 0, tzinfo=UTC)
    timeline = build_event_timeline([h3, h1, h2], reference_date=ref)

    assert len(timeline) == 3
    # Chronological sort order: e1 (01:00 UTC) -> e2 (03:00 UTC) -> e3 (09:00 UTC)
    assert [item["hit_id"] for item in timeline] == ["e1", "e2", "e3"]
    # days_since_previous must be non-negative
    assert timeline[0]["days_since_previous"] is None
    assert timeline[1]["days_since_previous"] == 0
    assert timeline[2]["days_since_previous"] == 0
    # delta_days_to_reference must be monotonically non-increasing (since later events are closer to reference)
    assert (
        timeline[0]["delta_days_to_reference"]
        >= timeline[1]["delta_days_to_reference"]
        >= timeline[2]["delta_days_to_reference"]
    )
