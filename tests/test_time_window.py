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
