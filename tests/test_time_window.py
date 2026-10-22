"""Questions that name a time span ("what did I ask you yesterday?") read the memories made
inside it, in the asker's local time; a question without a past-tense cue never does."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.retrieval import query_time_window

# Thursday 8 October 2026, noon, in this machine's time zone.
NOW = datetime(2026, 10, 8, 12, 0).astimezone()
TODAY = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
TENANT = "time-tenant"


@pytest.mark.parametrize(
    ("question", "start_days", "start_hour", "span_hours", "label"),
    [
        ("What did I ask you yesterday?", -1, 0, 24, "yesterday"),
        ("What did we talk about the day before yesterday?", -2, 0, 24, "the day before yesterday"),
        ("What did I say last night?", -1, 18, 11, "last night"),
        ("What did I ask three days ago?", -3, 0, 24, "three days ago"),
        ("What did I mention on Tuesday?", -2, 0, 24, "tuesday"),
        ("What did I say last Thursday?", -7, 0, 24, "thursday"),
        ("What did we discuss yesterday morning?", -1, 5, 7, "yesterday morning"),
        ("What did I tell you this morning?", 0, 5, 7, "this morning"),
    ],
)
def test_a_question_naming_a_day_gets_that_span(question, start_days, start_hour, span_hours, label) -> None:
    window = query_time_window(question, NOW)
    assert window is not None
    start = TODAY + timedelta(days=start_days, hours=start_hour)
    assert (window.start, window.end) == (start, start + timedelta(hours=span_hours))
    assert window.label == label


def test_the_rest_of_the_question_drops_the_words_that_named_the_span() -> None:
    window = query_time_window("What did I ask you yesterday morning?", NOW)
    assert window is not None and window.rest == "what did i ask you"


def test_weeks_and_months() -> None:
    last_week = query_time_window("What did we talk about last week?", NOW)
    assert last_week is not None
    # Monday 28 September to Monday 5 October.
    assert (last_week.start, last_week.end) == (TODAY - timedelta(days=10), TODAY - timedelta(days=3))
    august = query_time_window("What did I say in August?", NOW)
    assert august is not None
    assert (august.start.year, august.start.month, august.start.day, august.end.month) == (2026, 8, 1, 9)
    december = query_time_window("What did I mention in December?", NOW)
    assert december is not None
    assert (december.start.year, december.start.month, december.end.year, december.end.month) == (2025, 12, 2026, 1)


@pytest.mark.parametrize(
    "question",
    [
        "I'm tired today",
        "what's the weather tonight",
        "remind me on Monday to call Anna",
        "What is my favourite colour?",
        "Where did I park the car?",
    ],
)
def test_no_span_without_a_past_tense_cue_and_a_time_phrase(question) -> None:
    assert query_time_window(question, NOW) is None


def _engine() -> LocalMemoryEngine:
    engine = LocalMemoryEngine()
    lines = {
        "I asked you to book a table at the Thai place.": TODAY - timedelta(days=1) + timedelta(hours=10),
        "We talked about the film Arrival.": TODAY - timedelta(days=1) + timedelta(hours=21),
        "I asked about the train timetable to Leeds.": TODAY + timedelta(hours=9),
        "I asked about the train timetable to York.": TODAY - timedelta(days=3) + timedelta(hours=9),
    }
    for text, moment in lines.items():
        engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id="u", actor="user", source_type="conversation", content=text,
            created_at=moment, access_policy={"tenant": TENANT},
        ))
    return engine


def _ask(engine: LocalMemoryEngine, question: str):
    return engine.retrieve(
        question, tenant_id=TENANT, record_access=False,
        filt={"query_mode": "passages", "role": "reader", "evaluated_at": NOW.isoformat()},
    )


def test_search_answers_from_the_memories_made_in_the_span() -> None:
    engine = _engine()
    result = _ask(engine, "What did I ask you yesterday?")
    texts = [hit.text for hit in result.hits]
    assert set(texts) == {"I asked you to book a table at the Thai place.", "We talked about the film Arrival."}
    assert result.explain["time_window"]["label"] == "yesterday"
    assert result.abstained is False
    night = _ask(engine, "What did we talk about last night?")
    assert [hit.text for hit in night.hits] == ["We talked about the film Arrival."]


def test_a_span_answer_that_misses_what_was_asked_about_abstains() -> None:
    result = _ask(_engine(), "What did I say about Leeds yesterday?")
    assert result.explain["time_window"]["label"] == "yesterday"
    assert "Leeds" not in " ".join(hit.text for hit in result.hits)
    assert result.abstained is True


def test_a_question_without_a_span_searches_all_of_memory() -> None:
    result = _ask(_engine(), "Which train timetable did I ask about?")
    texts = [hit.text for hit in result.hits]
    assert "I asked about the train timetable to Leeds." in texts and "I asked about the train timetable to York." in texts
    assert "time_window" not in result.explain


@pytest.mark.parametrize("year", [2024, 2026, 2027])
def test_explicit_month_year_does_not_silently_select_the_latest_month(year) -> None:
    window = query_time_window(f"What did I say in August {year}?", NOW)
    assert window is not None
    assert (window.start.year, window.start.month, window.end.year, window.end.month) == (year, 8, year, 9)
    assert window.label == f"august {year}"
    assert window.rest == "what did i say"


@pytest.mark.parametrize(
    "span",
    ["999999999999999999999 days ago", "9" * 5000 + " days ago", "in August 0000", "in August 10000"],
    ids=["timedelta-overflow", "integer-string-limit", "zero-year", "year-overflow"],
)
def test_unrepresentable_time_span_does_not_crash_search_or_guess_a_different_date(span) -> None:
    assert query_time_window(f"What did I say {span}?", NOW) is None


def test_search_uses_explicit_year_to_exclude_a_newer_conversation() -> None:
    engine = LocalMemoryEngine()
    for year, content in [(2024, "We discussed the original workshop."), (2026, "We discussed the replacement workshop.")]:
        engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id="u", actor="user", source_type="conversation", content=content,
            created_at=TODAY.replace(year=year, month=8, day=12), access_policy={"tenant": TENANT},
        ))
    result = _ask(engine, "What did we discuss in August 2024?")
    assert [hit.text for hit in result.hits] == ["We discussed the original workshop."]
    assert result.abstained is False


@pytest.mark.parametrize("zone,expected_day", [("Asia/Tokyo", 22), ("America/Los_Angeles", 21)])
def test_search_respects_caller_calendar_zone(zone, expected_day):
    from mnemosyne.mcp_tools import MemoryTools

    engine = LocalMemoryEngine()
    for day in (21, 22):
        engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id="u", actor="user", source_type="conversation",
            content=f"We discussed workshop {day}.",
            created_at=datetime.fromisoformat(f"2026-10-{day}T12:00:00+09:00"),
            access_policy={"tenant": TENANT},
        ))
    result = MemoryTools(engine).search(
        TENANT, "What did we discuss yesterday?", query_mode="passages",
        evaluated_at="2026-10-23T00:30:00+09:00", query_timezone=zone,
    )
    assert result["explain"]["time_window"]["start"].startswith(f"2026-10-{expected_day}")
    if zone == "Asia/Tokyo":
        assert [hit["text"] for hit in result["hits"]] == ["We discussed workshop 22."]


@pytest.mark.parametrize("instant,hours", [("2026-03-09T12:00:00Z", 23), ("2026-11-02T12:00:00Z", 25)])
def test_caller_zone_day_observes_dst(instant, hours):
    from datetime import UTC
    from mnemosyne.models import parse_dt

    window = query_time_window("What did I say yesterday?", parse_dt(instant), query_timezone="America/New_York")
    assert window is not None
    assert (window.end.astimezone(UTC) - window.start.astimezone(UTC)).total_seconds() == hours * 3600


@pytest.mark.parametrize("zone", ["", "Not/A_Zone", "../UTC", 123])
def test_invalid_caller_zone_fails_clearly(zone):
    from mnemosyne.mcp_tools import MemoryTools

    with pytest.raises(ValueError, match="query_timezone"):
        MemoryTools(LocalMemoryEngine()).search(TENANT, "hello", query_timezone=zone)
    with pytest.raises(ValueError, match="query_timezone"):
        LocalMemoryEngine().retrieve("hello", tenant_id=TENANT, filt={"query_timezone": zone})


def test_cli_query_timezone_parses_validates_and_reaches_search(monkeypatch, capsys):
    from mnemosyne import cli
    from types import SimpleNamespace

    parser = cli.build_parser()
    args = parser.parse_args(["search", "--tenant", TENANT, "--query", "What did I say yesterday?", "--query-timezone", "Asia/Tokyo"])
    seen = {}

    def search(**kwargs):
        seen.update(kwargs)
        return {"hits": []}

    monkeypatch.setattr(cli, "load_tools", lambda args: SimpleNamespace(search=search))
    cli.cmd_search(args)
    assert seen["query_timezone"] == "Asia/Tokyo"
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["search", "--tenant", TENANT, "--query", "hello", "--query-timezone", "Not/A_Zone"])
    assert exc.value.code == 2
    assert "query_timezone" in capsys.readouterr().err


def test_implicit_clock_time_windows_do_not_reuse_yesterdays_cache(monkeypatch):
    from mnemosyne import pipeline

    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "8")
    engine = LocalMemoryEngine()
    for day in (21, 22):
        engine.append_evidence(Evidence(
            tenant_id=TENANT, user_id="u", actor="user", source_type="conversation",
            content=f"We discussed workshop {day}.", created_at=TODAY.replace(day=day),
            access_policy={"tenant": TENANT},
        ))
    clock = [TODAY.replace(day=22, hour=12)]
    monkeypatch.setattr(pipeline, "utc_now", lambda: clock[0])
    filt = {"query_mode": "passages", "role": "reader"}
    first = engine.retrieve("What did we discuss yesterday?", tenant_id=TENANT, filt=filt, record_access=False)
    clock[0] = TODAY.replace(day=23, hour=12)
    second = engine.retrieve("What did we discuss yesterday?", tenant_id=TENANT, filt=filt, record_access=False)
    assert [hit.text for hit in first.hits] == ["We discussed workshop 21."]
    assert [hit.text for hit in second.hits] == ["We discussed workshop 22."]


def test_fixed_clock_cache_preserves_hits_and_separates_caller_zones(monkeypatch):
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "8")
    engine = LocalMemoryEngine()
    filt = {
        "query_mode": "passages", "role": "reader",
        "evaluated_at": "2026-10-23T00:30:00+09:00", "query_timezone": "Asia/Tokyo",
    }
    first = engine.retrieve("What did I say yesterday?", tenant_id=TENANT, filt=filt, record_access=False)
    second = engine.retrieve("What did I say yesterday?", tenant_id=TENANT, filt=filt, record_access=False)
    other = engine.retrieve(
        "What did I say yesterday?", tenant_id=TENANT,
        filt={**filt, "query_timezone": "America/Los_Angeles"}, record_access=False,
    )
    assert first.explain["retrieval_result_cache"]["hit"] is False
    assert second.explain["retrieval_result_cache"]["hit"] is True
    assert other.explain["retrieval_result_cache"]["hit"] is False
    assert first.explain["time_window"]["start"].startswith("2026-10-22")
    assert other.explain["time_window"]["start"].startswith("2026-10-21")


def test_missing_iana_data_has_actionable_validation_error(monkeypatch):
    from zoneinfo import ZoneInfoNotFoundError
    from mnemosyne import retrieval

    def missing(_name):
        raise ZoneInfoNotFoundError("no timezone data installed")

    monkeypatch.setattr(retrieval, "ZoneInfo", missing)
    with pytest.raises(ValueError, match="query_timezone.*timezone data.*tzdata"):
        retrieval.resolve_query_timezone("America/New_York")
    # Existing callers require no IANA data when no explicit zone is supplied.
    assert retrieval.resolve_query_timezone(None) is None
