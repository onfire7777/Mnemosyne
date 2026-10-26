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


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What did you tell me yesterday?", "assistant"),
        ("What did you say about my project yesterday?", "assistant"),
        ("Remind me what you suggested yesterday", "assistant"),
        ("What was the first thing I asked yesterday?", "user"),
        ("What did I first tell you yesterday?", "user"),
        ("What did you and I say yesterday?", None),
        ("What did I say and you reply yesterday?", None),
        ("What happened to my project yesterday?", None),
    ],
)
def test_speaker_tracks_the_speaking_subject_not_a_recipient_or_possessive(question, expected):
    from mnemosyne.pipeline import _asked_speaker

    assert _asked_speaker(question) == expected


def test_assistant_speaker_priority_does_not_promote_unrelated_tool_records():
    from datetime import UTC
    from types import SimpleNamespace
    from mnemosyne.models import Hit
    from mnemosyne.pipeline import _time_window_route
    from mnemosyne.retrieval import RetrievalAdapters

    candidates = [
        Hit(
            id=f"{index}-{actor}", kind="evidence", tenant_id=TENANT, branch="main",
            text="What did you say?", score=0, channel="source", metadata={"actor": actor},
        )
        for index, actor in enumerate(("tool", "user", "assistant"))
    ]
    ops = SimpleNamespace(
        passage_candidates=lambda _: candidates,
        evidence_created_at_many=lambda *args: {
            hit.id: datetime(2026, 10, 7, 12, tzinfo=UTC) for hit in candidates
        },
        adapters=RetrievalAdapters(),
    )
    window = query_time_window(
        "What did you say yesterday?", datetime(2026, 10, 8, 12, tzinfo=UTC), query_timezone="UTC",
    )
    assert window is not None
    hits, _ = _time_window_route(ops, window, {}, tenant_id=TENANT, branch="main", passage_graph=None)
    assert [hit.metadata["actor"] for hit in hits] == ["assistant", "tool", "user"]


@pytest.mark.parametrize(
    "instant,expected_start,expected_end,hours",
    [
        ("2026-03-09T12:00:00Z", "2026-03-08T00:00:00-05:00", "2026-03-09T00:00:00-04:00", 23),
        ("2026-11-02T12:00:00Z", "2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00", 25),
    ],
)
def test_implicit_machine_calendar_converts_each_dst_boundary(monkeypatch, instant, expected_start, expected_end, hours):
    import time
    from datetime import UTC
    from mnemosyne.models import parse_dt

    if not hasattr(time, "tzset"):
        pytest.skip("changing the process local calendar requires time.tzset")
    with monkeypatch.context() as local:
        local.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            window = query_time_window("What did I say yesterday?", parse_dt(instant))
            assert window is not None
            assert window.start.isoformat() == expected_start
            assert window.end.isoformat() == expected_end
            assert (window.end.astimezone(UTC) - window.start.astimezone(UTC)).total_seconds() == hours * 3600
        finally:
            # Restore the environment before refreshing libc's timezone state.
            local.undo()
            time.tzset()


@pytest.mark.parametrize("offset", ["-04:00", "-05:00"])
def test_implicit_current_week_preserves_evaluation_instant_in_repeated_hour(monkeypatch, offset):
    import time
    from datetime import UTC

    if not hasattr(time, "tzset"):
        pytest.skip("changing the process local calendar requires time.tzset")
    with monkeypatch.context() as local:
        local.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            now = datetime.fromisoformat(f"2026-11-01T01:30:00{offset}")
            window = query_time_window("What did I say this week?", now)
            assert window is not None
            assert window.end.astimezone(UTC) == now.astimezone(UTC)
        finally:
            local.undo()
            time.tzset()


@pytest.fixture(params=["local", "sqlite"])
def temporal_engine(request, tmp_path):
    from mnemosyne.sqlite_engine import SqliteEngine

    engine = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "temporal")
    yield engine
    close = getattr(engine, "close", None)
    if close:
        close()


def _append_fall_back_conversation(engine, *, minute, fold, content):
    from zoneinfo import ZoneInfo

    return engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id="u", actor="user", source_type="conversation", content=content,
        created_at=datetime(2026, 11, 1, 1, minute, tzinfo=ZoneInfo("America/New_York"), fold=fold),
        access_policy={"tenant": TENANT},
    ))


@pytest.mark.parametrize("position", ["first", "last"])
def test_first_last_orders_repeated_dst_hour_by_actual_instant(temporal_engine, position):
    earlier = _append_fall_back_conversation(
        temporal_engine, minute=50, fold=0, content="I asked the chronologically earlier question.",
    )
    later = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=1, content="I asked the chronologically later question.",
    )
    result = temporal_engine.retrieve(
        f"What was the {position} thing I asked yesterday?", tenant_id=TENANT, record_access=False,
        filt={"query_mode": "passages", "query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"},
    )
    assert [hit.id for hit in result.hits] == ([earlier, later] if position == "first" else [later, earlier])


def test_current_week_excludes_later_occurrence_of_repeated_dst_hour(temporal_engine):
    earlier = _append_fall_back_conversation(
        temporal_engine, minute=15, fold=0, content="I said this before the question was asked.",
    )
    _append_fall_back_conversation(
        temporal_engine, minute=15, fold=1, content="I said this after the question was asked.",
    )
    result = temporal_engine.retrieve(
        "What did I say this week?", tenant_id=TENANT, record_access=False,
        filt={"query_mode": "passages", "query_timezone": "America/New_York", "evaluated_at": "2026-11-01T01:30:00-04:00"},
    )
    assert [hit.id for hit in result.hits] == [earlier]


@pytest.mark.parametrize("position", ["first", "last"])
@pytest.mark.parametrize("route", ["passages", "default-with-graph", "default-without-graph"])
def test_explicit_chronology_bypasses_custom_reranker_before_top_k(temporal_engine, position, route):
    from dataclasses import replace

    class ReverseReranker:
        name = "reverse-test-reranker"

        def __init__(self):
            self.calls = 0

        def rerank(self, query, hits, k):
            self.calls += 1
            return list(reversed(hits))[:k]

    class LocalGraph:
        def rank(self, query, candidates, embedding, k):
            return list(candidates)[:k], {}

    reranker = ReverseReranker()
    temporal_engine.adapters = replace(
        temporal_engine.adapters, reranker=reranker,
        passage_graph=LocalGraph() if route == "default-with-graph" else None,
    )
    temporal_engine.policy = replace(temporal_engine.policy, top_k=1)
    earlier = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I asked the earlier question.",
    )
    later = _append_fall_back_conversation(
        temporal_engine, minute=50, fold=0, content="I asked the later question.",
    )
    filt = {"query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"}
    if route == "passages":
        filt["query_mode"] = "passages"
    result = temporal_engine.retrieve(
        f"What was the {position} thing I asked yesterday?", tenant_id=TENANT, record_access=False, filt=filt,
    )
    assert [hit.id for hit in result.hits] == ([earlier] if position == "first" else [later])
    assert reranker.calls == 0
    assert result.used_tokens <= result.token_budget
    temporal_engine.retrieve("What did I ask yesterday?", tenant_id=TENANT, record_access=False, filt=filt)
    assert reranker.calls == 1


def test_current_policy_schema_does_not_override_first_conversation(temporal_engine):
    from dataclasses import replace

    temporal_engine.policy = replace(temporal_engine.policy, top_k=1)
    earlier = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I said the current policy needs discussion.",
    )
    _append_fall_back_conversation(
        temporal_engine, minute=50, fold=0, content="I said the current policy was updated.",
    )
    result = temporal_engine.retrieve(
        "What was the first thing I said about the current policy yesterday?", tenant_id=TENANT, record_access=False,
        filt={"query_mode": "passages", "query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"},
    )
    assert [hit.id for hit in result.hits] == [earlier]
    assert result.explain["schema_fast_path"]["applied"] is False


def test_workspace_score_boost_preserves_explicit_chronology(temporal_engine):
    from dataclasses import replace

    temporal_engine.policy = replace(temporal_engine.policy, workspace_retrieval_advisory_enabled=True)
    earlier = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I asked the earlier question.",
    )
    later = _append_fall_back_conversation(
        temporal_engine, minute=50, fold=0, content="I asked the later question.",
    )
    result = temporal_engine.retrieve(
        "What was the first thing I asked yesterday?", tenant_id=TENANT, record_access=False,
        filt={
            "query_mode": "passages", "query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z",
            "apply_workspace_retrieval_advisory": True,
            "workspace_retrieval_advisory": {
                "version": "workspace-retrieval-advisory.v1", "source": "shadow_workspace_controller",
                "tenant_id": TENANT, "branch": "main", "shadow_only": True, "critical_path": False,
                "production_mutation": False, "advisory_only": True, "promotion_gate_required": True,
                "applied_to_ranking": False, "applied_to_mutation": False,
                "items": [{"cid": later, "priority": 1.0}],
            },
        },
    )
    assert [hit.id for hit in result.hits] == [earlier, later]
    advisory = result.explain["workspace_retrieval_advisory"]
    assert advisory["status"] == "applied"
    assert advisory["used_for_ranking"] is False
    assert advisory["ranking_preserved"] == "explicit_temporal_order"


def test_default_without_graph_reads_only_the_requested_window(temporal_engine):
    from datetime import UTC

    inside = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I asked about the workshop agenda.",
    )
    temporal_engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id="u", actor="user", source_type="conversation",
        content="I asked about the workshop location.", created_at=datetime(2026, 11, 2, 10, tzinfo=UTC),
    ))
    filt = {"query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"}
    result = temporal_engine.retrieve(
        "What did I ask about the workshop yesterday?", tenant_id=TENANT, record_access=False, filt=filt,
    )
    assert [hit.id for hit in result.hits] == [inside]
    assert result.explain["time_window"]["label"] == "yesterday"
    assert result.explain.get("source_only_local_fallback") is None
    assert "query_mode" not in filt


def test_default_without_graph_abstains_for_empty_window(temporal_engine):
    _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I asked about the workshop agenda.",
    )
    result = temporal_engine.retrieve(
        "What did I ask about the workshop yesterday?", tenant_id=TENANT, record_access=False,
        filt={"query_timezone": "America/New_York", "evaluated_at": "2026-11-04T12:00:00Z"},
    )
    assert result.hits == []
    assert result.abstained is True
    assert result.explain["time_window"]["passages"] == 0


def test_default_window_needs_no_embedding_channel_or_mmr_provider(temporal_engine, monkeypatch):
    from dataclasses import replace

    class NoEmbedding:
        name = "unavailable-test-embedding"
        dims = 8

        def embed(self, text):
            pytest.fail("a deterministic conversation window does not require embeddings")

    def forbidden(*args, **kwargs):
        pytest.fail("a conversation window must not call global channels or MMR")

    inside = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I said the workshop starts at nine.",
    )
    temporal_engine.adapters = replace(temporal_engine.adapters, embedding=NoEmbedding())
    for name in ("vector_search", "lexical_search", "graph_ppr", "_mmr"):
        monkeypatch.setattr(temporal_engine, name, forbidden)
    result = temporal_engine.retrieve(
        "What did I say yesterday?", tenant_id=TENANT, record_access=False,
        filt={"query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"},
    )
    assert [hit.id for hit in result.hits] == [inside]


def test_default_window_preserves_speaker_priority(temporal_engine):
    from datetime import UTC

    user = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I mentioned the workshop agenda.",
    )
    tool = temporal_engine.append_evidence(Evidence(
        tenant_id=TENANT, user_id="u", actor="tool", source_type="conversation",
        content="What did I say yesterday? Workshop agenda search results.",
        created_at=datetime(2026, 11, 1, 5, tzinfo=UTC),
    ))
    result = temporal_engine.retrieve(
        "What did I say about the workshop agenda yesterday?", tenant_id=TENANT, record_access=False,
        filt={"query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"},
    )
    assert [hit.id for hit in result.hits] == [user, tool]
    assert result.explain["time_window"]["speaker"] == "user"


def test_default_window_only_uses_authorized_passages(temporal_engine):
    from datetime import UTC

    public = _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I said the public workshop starts at nine.",
    )
    for tenant, policy, content in [
        (TENANT, {"allow_roles": ["operator"]}, "I said the private workshop starts at ten."),
        ("another-tenant", {}, "I said the other tenant's workshop starts at eleven."),
    ]:
        temporal_engine.append_evidence(Evidence(
            tenant_id=tenant, user_id="u", actor="user", source_type="conversation", content=content,
            access_policy={"tenant": tenant, **policy}, created_at=datetime(2026, 11, 1, 5, tzinfo=UTC),
        ))
    result = temporal_engine.retrieve(
        "What did I say about the workshop yesterday?", tenant_id=TENANT, record_access=False,
        filt={"role": "reader", "query_timezone": "America/New_York", "evaluated_at": "2026-11-02T12:00:00Z"},
    )
    assert [hit.id for hit in result.hits] == [public]


@pytest.mark.parametrize("mode", ["deep", "as_of", "global_sensemaking"])
def test_default_window_does_not_replace_explicit_read_semantics(temporal_engine, mode):
    _append_fall_back_conversation(
        temporal_engine, minute=10, fold=0, content="I said the workshop starts at nine.",
    )
    filt = {"query_timezone": "America/New_York", "evaluated_at": "2026-11-04T12:00:00Z"}
    if mode == "as_of":
        filt["as_of"] = "2026-11-04T12:00:00Z"
    elif mode == "global_sensemaking":
        filt["query_mode"] = mode
    result = temporal_engine.retrieve(
        "What did I say about the workshop yesterday?", tenant_id=TENANT, record_access=False,
        filt=filt, deep=mode == "deep",
    )
    assert "time_window" not in result.explain
    if mode == "global_sensemaking":
        assert result.explain["query_mode"] == mode
    else:
        assert result.hits


def test_temporal_freshness_preserves_requested_speaker_priority():
    engine = LocalMemoryEngine()
    when = TODAY - timedelta(days=1) + timedelta(hours=12)
    for actor, text in [('user', 'Please schedule launch.'), ('tool', 'You asked about launch launch launch.')]:
        engine.append_evidence(Evidence(tenant_id=TENANT, user_id='u', actor=actor, source_type='conversation',
                                      content=text, created_at=when))
    result = _ask(engine, 'What did I ask you yesterday about launch?')
    assert result.explain['time_window']['speaker'] == 'user'
    assert result.hits[0].metadata['actor'] == 'user'
