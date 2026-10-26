"""Occurrence time and conversation time are distinct, authorized retrieval constraints."""

from datetime import UTC, datetime

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit, parse_dt
from mnemosyne.retrieval import hit_recency_for_unit, query_time_window
from mnemosyne.sqlite_engine import SqliteEngine


NOW = "2026-10-08T12:00:00Z"


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    value = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "memory.db")
    yield value
    value.close()


def add(engine, text, *, created="2026-10-08T09:00:00Z", start=None, end=None, metadata=None,
        tenant="events", branch="main", access=None, actor="user"):
    dates = dict(metadata or {})
    if start is not None:
        dates["event_start"] = start
    if end is not None:
        dates["event_end"] = end
    return engine.append_evidence(Evidence(
        tenant_id=tenant, branch=branch, user_id="u", actor=actor, source_type="conversation",
        content=text, created_at=parse_dt(created), metadata=dates, access_policy=access or {},
    ), branch=branch)


def ask(engine, query, **filters):
    return engine.retrieve(query, "events", record_access=False,
                           filt={"evaluated_at": NOW, "query_timezone": "UTC", **filters})


def test_event_and_source_queries_choose_different_authoritative_clocks(engine):
    actual = add(engine, "The workshop was at the harbor.", start="2026-10-07T10:00:00Z")
    mentioned = add(engine, "The workshop was at the museum.", created="2026-10-07T09:00:00Z",
                    start="2026-08-02T10:00:00Z")
    event = ask(engine, "What workshop happened yesterday?")
    source = ask(engine, "What did I say about the workshop yesterday?")
    assert [hit.id for hit in event.hits] == [actual]
    assert [hit.id for hit in source.hits] == [mentioned]
    assert event.explain["time_window"]["axis"] == "event"
    assert source.explain["time_window"]["axis"] == "source"


def test_event_interval_overlap_and_exclusive_boundaries(engine):
    overlap = add(engine, "A workshop spanning the day.", start="2026-10-06T12:00:00Z", end="2026-10-08T10:00:00Z")
    point = add(engine, "A workshop at the first instant.", start="2026-10-07T00:00:00Z")
    zero = add(engine, "A workshop with a precise instant.", start="2026-10-07T12:00:00Z", end="2026-10-07T12:00:00Z")
    add(engine, "A workshop ending before the day.", start="2026-10-06T12:00:00Z", end="2026-10-07T00:00:00Z")
    add(engine, "A workshop beginning next day.", start="2026-10-08T00:00:00Z")
    result = ask(engine, "What workshop happened yesterday?")
    assert {hit.id for hit in result.hits} == {overlap, point, zero}


@pytest.mark.parametrize("metadata", [{}, {"event_start": "invalid"}, {"event_end": "2026-10-07"},
    {"event_start": "2026-10-08", "event_end": "2026-10-06"},
    {"event_start": "2026-10-07", "event_end": "invalid"}])
def test_missing_or_invalid_event_time_does_not_borrow_recording_time(engine, metadata):
    add(engine, "A workshop was discussed.", created="2026-10-07T10:00:00Z", metadata=metadata)
    result = ask(engine, "What workshop happened yesterday?")
    assert result.hits == [] and result.abstained
    assert result.explain["time_window"]["axis"] == "event"


def test_occurrence_aliases_are_supported(engine):
    cid = add(engine, "A workshop at the coast.", metadata={"occurred_start": "2026-10-07T12:00:00Z"})
    assert [hit.id for hit in ask(engine, "What workshop happened yesterday?").hits] == [cid]


@pytest.mark.parametrize("query,clock", [("What did I say yesterday?", "source"),
    ("What happened yesterday?", "event"), ("What was the first thing I said yesterday?", "source"),
    ("What was the first event yesterday?", "event"), ("What messages did I send yesterday?", "source"),
    ("What did I message you yesterday?", "source")])
def test_date_only_recall_does_not_require_repeating_question_framing(engine, query, clock):
    cid = add(engine, "The workshop was at the museum.", created="2026-10-07T10:00:00Z",
              start="2026-10-07T11:00:00Z")
    result = ask(engine, query)
    assert [hit.id for hit in result.hits] == [cid]
    assert result.abstained is False
    assert result.explain["time_window"]["axis"] == clock
    assert result.explain["time_window"]["date_only"] is True


def test_temporal_presence_does_not_support_unrelated_topic(engine):
    add(engine, "The workshop was at the museum.", created="2026-10-07T10:00:00Z", start="2026-10-07T11:00:00Z")
    for query in ("What did I say about glaciers yesterday?", "What glacier expedition happened yesterday?"):
        result = ask(engine, query)
        assert result.abstained
        assert not result.explain["time_window"]["date_only"]
        assert result.explain["confidence"]["query_support"]["missing_terms"]


@pytest.mark.parametrize("position", ["first", "last"])
def test_event_order_uses_occurrence_time_across_repeated_dst_hour(engine, position):
    early = add(engine, "The workshop at the harbor.", created="2026-11-03T12:00:00Z", start="2026-11-01T01:50:00-04:00")
    late = add(engine, "The workshop at the museum.", created="2026-11-02T12:00:00Z", start="2026-11-01T01:10:00-05:00")
    result = ask(engine, f"What workshop happened {position} yesterday?", evaluated_at="2026-11-02T12:00:00Z",
                 query_timezone="America/New_York")
    assert [hit.id for hit in result.hits] == ([early, late] if position == "first" else [late, early])


def test_source_order_still_uses_recording_time_despite_reversed_event_times(engine):
    early = add(engine, "The workshop at the harbor.", created="2026-10-07T10:00:00Z", start="2026-10-07T15:00:00Z")
    late = add(engine, "The workshop at the museum.", created="2026-10-07T12:00:00Z", start="2026-10-07T09:00:00Z")
    result = ask(engine, "What did I first say about the workshop yesterday?")
    assert [hit.id for hit in result.hits] == [early, late]


def test_event_route_never_reads_hidden_event_dates(engine):
    public = add(engine, "A public workshop.", start="2026-10-07T10:00:00Z")
    add(engine, "An inaccessible workshop.", start="2026-10-07T10:00:00Z", access={"allow_roles": ["operator"]})
    add(engine, "Another tenant's workshop.", start="2026-10-07T10:00:00Z", tenant="another")
    engine.branch("other", tenant_id="events")
    add(engine, "Another branch's workshop.", start="2026-10-07T10:00:00Z", branch="other")
    add(engine, "workshop code: secret", start="2026-10-07T10:00:00Z", created="2026-10-07T12:00:00Z",
        access={"redact_fields": ["code"], "min_role_for_raw": "operator"})
    result = ask(engine, "What workshop happened yesterday?", role="reader")
    assert [hit.id for hit in result.hits] == [public]


@pytest.mark.parametrize("phrase,start,end", [
    ("in 2025", "2025-01-01", "2026-01-01"), ("last year", "2025-01-01", "2026-01-01"),
    ("last month", "2026-09-01", "2026-10-01"), ("on 2026-10-07", "2026-10-07", "2026-10-08"),
])
def test_common_historical_calendar_windows(phrase, start, end):
    window = query_time_window(f"What happened {phrase}?", parse_dt(NOW), query_timezone="UTC")
    assert window is not None
    assert (window.start, window.end) == (parse_dt(start), parse_dt(end))
    assert window.axis == "event"


def test_exact_iso_day_has_local_dst_boundaries():
    window = query_time_window("What did I say on 2026-03-08?", parse_dt(NOW), query_timezone="America/New_York")
    assert window is not None and window.axis == "source"
    assert window.start.isoformat() == "2026-03-08T00:00:00-05:00"
    assert window.end.isoformat() == "2026-03-09T00:00:00-04:00"
    assert (window.end.astimezone(UTC) - window.start.astimezone(UTC)).total_seconds() == 23 * 3600


@pytest.mark.parametrize("phrase", ["on 2026-02-30", "in 0000", "in 9999", "on 9999-12-31",
    "on 2026-10-07-extra", "on 2026-10-07-2026-10-09", "on 2026-10-07 or 2026-10-08",
    "on 2026-10-07-extra yesterday", "before 2026-10-07", "after 2026-10-07",
    "in 2024 and in 2025", "in August 2024 and in 2025"])
def test_invalid_or_unrepresentable_windows_fail_without_partial_date_fallback(phrase):
    assert query_time_window(f"What happened {phrase}?", datetime(2026, 10, 8, tzinfo=UTC), query_timezone="UTC") is None


def test_historical_year_selects_metadata_dates_not_recording_year(engine):
    event = add(engine, "A workshop on the coast.", start="2025-08-07T10:00:00Z")
    add(engine, "A workshop on the mountain.", created="2025-08-07T10:00:00Z", start="2024-08-07T10:00:00Z")
    result = ask(engine, "What workshop happened in 2025?")
    assert [hit.id for hit in result.hits] == [event]
    assert result.abstained is False


@pytest.mark.parametrize("mode", ["deep", "as_of", "global_sensemaking"])
def test_explicit_read_modes_are_not_replaced_by_event_window(engine, mode):
    add(engine, "A workshop on the coast.", start="2025-08-07T10:00:00Z")
    filters = {"evaluated_at": NOW, "query_timezone": "UTC"}
    if mode == "as_of":
        filters["as_of"] = NOW
    if mode == "global_sensemaking":
        filters["query_mode"] = mode
    result = engine.retrieve("What workshop happened yesterday?", "events", record_access=False,
                             filt=filters, deep=mode == "deep")
    assert "time_window" not in result.explain


@pytest.mark.parametrize("query,axis", [
    ("Tell me what happened yesterday", "event"),
    ("Can you tell me what I did in August 2026?", "event"),
    ("What happened at the talk yesterday?", "event"),
    ("What did I tell you yesterday?", "source"),
    ("What did Alice say yesterday?", "source"),
    ("What did the document created yesterday contain?", "source"),
])
def test_temporal_intent_ignores_request_framing(query, axis):
    window = query_time_window(query, parse_dt(NOW), query_timezone="UTC")
    assert window is not None and window.axis == axis


def test_date_only_speaker_match_is_required_for_temporal_score(engine):
    add(engine, "The workshop was at the museum.", created="2026-10-07T10:00:00Z", actor="assistant")
    result = ask(engine, "What did I say yesterday?")
    assert result.abstained
    assert all(hit.score == 0 for hit in result.hits)


def test_date_only_match_does_not_override_low_trust(engine):
    engine.append_evidence(Evidence(tenant_id="events", user_id="u", actor="user", source_type="conversation",
        content="The workshop was at the museum.", created_at=parse_dt("2026-10-07T12:00:00Z"), trust_tier=3))
    assert ask(engine, "What did I say yesterday?").abstained


def test_date_only_match_does_not_override_self_generated_evidence(engine):
    add(engine, "The workshop was at the museum.", created="2026-10-07T12:00:00Z",
        metadata={"reality_class": "self_generated"})
    assert ask(engine, "What did I say yesterday?").abstained


@pytest.mark.parametrize("start,end", [
    ("2026-10-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00"),
    ("2026-10-01T00:00:00-07:00", "2026-11-01T00:00:00-07:00"),
    ("2026-03-01T00:00:00-05:00", "2026-04-01T00:00:00-04:00"),
])
def test_direct_hit_coarse_calendar_recency_preserves_local_precision(start, end):
    hit = Hit(id="coarse", tenant_id="events", branch="main", kind="evidence", text="A monthly summary.",
              score=1.0, channel="source", metadata={"event_start": start, "event_end": end})
    now = parse_dt(start).replace(day=8)
    assert hit_recency_for_unit(hit, now) == 0.5


def test_direct_offset_trip_is_not_mistaken_for_a_coarse_calendar_period():
    hit = Hit(id="trip", tenant_id="events", branch="main", kind="evidence", text="A month-long trip.",
        score=1.0, channel="source", metadata={"event_start": "2026-10-02T00:00:00-07:00",
                                             "event_end": "2026-11-02T00:00:00-07:00"})
    assert hit_recency_for_unit(hit, parse_dt("2026-10-08T12:00:00Z")) > 0.5
