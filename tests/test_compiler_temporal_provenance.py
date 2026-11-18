"""Synthetic regressions for temporal grounding and bounded evidence selection."""

from datetime import UTC, date, datetime

import pytest

from mnemosyne.compiler_context import (
    MemoryContextCompiler,
    resolve_inline_temporal_expressions,
    sanitize_sessions,
)
from mnemosyne.premise_verifier import PremiseConsistencyVerifier


def _sessions(*entries):
    timestamps = [
        datetime.fromisoformat(stamp).replace(tzinfo=UTC) for stamp, _ in entries
    ]
    return sanitize_sessions(
        [
            [{"role": role, "content": content} for role, content in turns]
            for _, turns in entries
        ],
        [stamp for stamp, _ in entries],
        timestamps,
    )


def _compile(question, sessions, at="2025-04-02", **kwargs):
    return MemoryContextCompiler(**kwargs).compile_memory(
        question, at, datetime.fromisoformat(at).replace(tzinfo=UTC), sessions
    )


def _resolve(text):
    return resolve_inline_temporal_expressions(
        text,
        session_index=1,
        turn_index=0,
        speaker="user",
        anchor_date=date(2025, 2, 20),
        query_date=date(2025, 3, 1),
    )


def test_promotion_does_not_conflict_with_earlier_role():
    sessions = _sessions(
        (
            "2025-01-02",
            [("user", "I started my role as Research Associate at Larch Labs.")],
        ),
        (
            "2025-04-01",
            [
                (
                    "user",
                    "I was promoted to Lab Director at Larch Labs. I lead six chemists.",
                )
            ],
        ),
    )
    plan = _compile("How many chemists do I lead in my role as Lab Director?", sessions)
    assert plan.premise_alert is None
    assert "six chemists" in plan.compiled_history_text


@pytest.mark.parametrize(
    "row",
    [
        {"content": "I was promoted to Field Botanist.", "speaker_role": "assistant"},
        {"content": "Assistant: I was promoted to Field Botanist."},
        {"content": "User: My sister was promoted to Field Botanist."},
        {"content": "User: I was not promoted to Field Botanist."},
        {"content": "User: I used to be working as Field Botanist."},
        {"content": "User: If I were promoted to Field Botanist, I would travel."},
        {
            "content": "I was promoted to Field Botanist.",
            "speaker_role": "user",
            "subject": "sister",
        },
    ],
)
def test_other_speakers_subjects_and_nonassertions_cannot_refute_user_role(row):
    result = PremiseConsistencyVerifier().verify(
        "What do I do in my role as Survey Coordinator?", evidence_rows=[row]
    )
    assert result.is_consistent


def test_future_sessions_cannot_supply_or_refute_query_time_evidence():
    sessions = _sessions(
        (
            "2025-02-01",
            [
                (
                    "user",
                    "I am working as Survey Coordinator. I supervise two volunteers.",
                )
            ],
        ),
        (
            "2025-05-01",
            [
                (
                    "user",
                    "I was promoted to Field Botanist. I supervise nine volunteers.",
                )
            ],
        ),
    )
    plan = _compile(
        "How many volunteers do I supervise in my role as Survey Coordinator?", sessions
    )
    assert plan.premise_alert is None
    assert set(plan.ranked_session_indices) == {0}
    assert "nine volunteers" not in plan.compiled_history_text
    assert "two volunteers" in plan.compiled_history_text


def _role_fact(title, *, subject="user", speaker="user", start=None, end=None):
    from mnemosyne.episodic_facts import DistilledFact

    return DistilledFact(
        fact_id=title,
        speaker_role=speaker,
        category="career",
        subject=subject,
        predicate="job_title",
        value=title,
        valid_from=start,
        valid_to=end,
        is_current=end is None,
    )


@pytest.mark.parametrize(
    "other",
    [
        _role_fact("Field Botanist", speaker="assistant"),
        _role_fact("Field Botanist", subject="sister"),
        _role_fact("Field Botanist"),  # concurrent, not an exclusive title
    ],
)
def test_structured_roles_do_not_use_first_different_fact(other):
    result = PremiseConsistencyVerifier().verify(
        "What do I do in my role as Survey Coordinator?",
        facts=[other, _role_fact("Survey Coordinator")],
    )
    assert result.is_consistent


def test_role_verification_uses_query_time_not_future_facts_or_rows():
    at = datetime(2025, 4, 2, tzinfo=UTC)
    result = PremiseConsistencyVerifier().verify(
        "What do I do in my role as Field Botanist?",
        facts=[
            _role_fact("Field Botanist", start=datetime(2025, 5, 1, tzinfo=UTC)),
            _role_fact(
                "Survey Coordinator",
                start=datetime(2025, 1, 1, tzinfo=UTC),
                end=datetime(2025, 5, 1, tzinfo=UTC),
            ),
        ],
        evidence_rows=[
            {
                "speaker_role": "user",
                "content": "I was promoted to Field Botanist.",
                "created_at": "2025-05-01T00:00:00Z",
            }
        ],
        evaluated_at=at,
    )
    assert result.abstention_recommended
    assert "Survey Coordinator" in result.clean_abstention_text


def test_event_relative_date_uses_explicit_event_not_session_date():
    text = "I signed the lease on 2025-02-03. Two days later I collected the keys."
    anchors = _resolve(text)
    later = next(a for a in anchors if a.expression == "Two days later")
    assert later.resolved_date == date(2025, 2, 5)
    assert "2025-02-03" in later.note


@pytest.mark.parametrize(
    ("text", "expression", "expected"),
    [
        (
            "I arrived on 2025-02-10. Two days before that I packed.",
            "Two days before that",
            date(2025, 2, 8),
        ),
        (
            "I arrived on 2025-02-10. Two days afterwards I unpacked.",
            "Two days afterwards",
            date(2025, 2, 12),
        ),
        (
            "I arrived on 2025-02-10. Two days later I unpacked. Three days later I left.",
            "Three days later",
            date(2025, 2, 15),
        ),
        ("I arrived yesterday. In two days I leave.", "In two days", date(2025, 2, 22)),
    ],
)
def test_event_relative_chains_and_deictic_offsets(text, expression, expected):
    anchors = _resolve(text)
    assert (
        next(a.resolved_date for a in anchors if a.expression == expression) == expected
    )


@pytest.mark.parametrize(
    "text",
    [
        "Two days later I collected the keys.",
        "I signed on 2025-02-03 or 2025-02-06. Two days later I collected the keys.",
        "I did not sign on 2025-02-03. Two days later I collected the keys.",
        "I signed on 2025-02-03. Afterwards I collected the keys. Two days later I moved.",
        "I signed on 02/03/2025. Two days later I collected the keys.",
    ],
)
def test_event_relative_ambiguous_antecedents_remain_unresolved(text):
    assert not any("later" in a.expression.lower() for a in _resolve(text))


@pytest.mark.parametrize(
    "text",
    [
        "I did not sign yesterday or on 2025-02-03.",
        "On 2025-02-03 I did not sign. Two days later I collected the keys.",
        "I signed on 2025-02-03. Two days later I did not collect the keys.",
    ],
)
def test_negated_dates_are_not_asserted_event_dates(text):
    anchors = _resolve(text)
    if text.startswith("I signed"):
        assert [a.expression for a in anchors] == ["2025-02-03"]
    else:
        assert not anchors


def test_ambiguous_numeric_dates_are_labeled_not_compiled_as_facts():
    anchors = _resolve("I signed on 5/2.")
    assert len(anchors) == 1  # legacy month/day candidate remains inspectable
    assert anchors[0].is_ambiguous
    assert "ambiguous" in anchors[0].note
    plan = _compile(
        "When did I sign?", _sessions(("2025-02-20", [("user", "I signed on 5/2.")]))
    )
    assert not plan.temporal_anchors
    assert "Event Date" not in plan.compiled_history_text


def test_explicit_year_and_source_ranges_survive_resolution():
    text = "I signed on 1999-12-31. Two days later I moved. I called yesterday, then called yesterday."
    anchors = _resolve(text)
    assert anchors[0].resolved_date == date(1999, 12, 31)
    assert anchors[1].resolved_date == date(2000, 1, 2)
    assert [a.expression for a in anchors].count("yesterday") == 2
    for anchor in anchors:
        assert text[anchor.source_start : anchor.source_end] == anchor.expression
        assert (anchor.session_index, anchor.turn_index, anchor.speaker) == (
            1,
            0,
            "user",
        )


def test_extended_session_limit_is_a_hard_cap_for_narrow_queries():
    sessions = _sessions(
        *[
            (
                f"2025-02-{day:02d}",
                [("user", f"The kiln glaze batch {day} used cobalt.")],
            )
            for day in range(1, 7)
        ]
    )
    compiler = MemoryContextCompiler(core_top_k=1, extended_max_extra=1)
    core, extra, chunks = compiler.select_compiled_turn_windows(
        "Which kiln glaze used cobalt?",
        sessions,
        list(range(6)),
        {},
        {i: 1.0 for i in range(6)},
    )
    assert len(core) == 1
    assert len(extra) == 1
    assert len(chunks) == 2


def test_bounded_selection_rescues_verbatim_matching_turns_across_sessions():
    sessions = _sessions(
        ("2025-02-01", [("user", "I maintain a kiln log.")]),
        (
            "2025-02-02",
            [
                ("user", "An unrelated essay. " * 2000),
                ("assistant", "Commentary. " * 2000),
                ("user", "Kiln cedar consumed 18 kWh."),
                ("assistant", "An estimate, not a measurement. " * 1000),
            ],
        ),
        (
            "2025-02-03",
            [
                ("user", "A garden journal. " * 2000),
                ("assistant", "Suggestions. " * 2000),
                ("user", "Kiln maple consumed 24 kWh."),
                ("assistant", "More commentary. " * 1000),
            ],
        ),
    )
    compiler = MemoryContextCompiler(
        core_top_k=1, extended_max_extra=2, extended_token_budget=100
    )
    core, extra, chunks = compiler.select_compiled_turn_windows(
        "How much energy did the kilns consume across runs?",
        sessions,
        [0, 1, 2],
        {1: [1], 2: [1]},
        {0: 1.0, 1: 0.9, 2: 0.8},
    )
    assert core == [0]
    assert extra == [1, 2]
    assert chunks[1] == [2]
    assert chunks[2] == [2]
    estimated_tokens = sum(
        sum(len(sessions[idx].turns[ti][1]) + 28 for ti in chunks[idx]) // 4 + 24
        for idx in extra
    )
    assert estimated_tokens <= compiler.extended_token_budget


@pytest.mark.parametrize(
    "question",
    [
        "What were my duties in my role as Research Associate?",
        "What was my remit in my role as Research Associate?",
        "Which responsibilities were assigned to me in my role as Research Associate?",
        "How large was the team in my role as Research Associate?",
        "What had I achieved in my role as Research Associate?",
        "How many chemists did I supervise in my role as Research Associate?",
    ],
)
def test_historical_role_phrasings_do_not_infer_conflict_from_current_title(question):
    content = "I am working as Lab Director."
    result = PremiseConsistencyVerifier().verify(
        question,
        evidence_rows=[
            {
                "speaker_role": "user",
                "content": content,
                "created_at": "2025-04-01T00:00:00Z",
            }
        ],
        evaluated_at=datetime(2025, 4, 2, tzinfo=UTC),
    )
    assert result.is_consistent
    assert not result.mismatches
    plan = _compile(question, _sessions(("2025-04-01", [("user", content)])))
    assert plan.premise_alert is None
    assert "[ALERT]" not in plan.compiled_history_text


@pytest.mark.parametrize(
    "question",
    [
        "What are my duties in my role as Research Associate?",
        "What is my remit in my role as Research Associate?",
        "Which responsibilities are assigned to me in my role as Research Associate?",
        "How large is the team in my role as Research Associate?",
        "How many chemists do I supervise in my role as Research Associate?",
    ],
)
def test_present_role_phrasings_still_check_current_title(question):
    plan = _compile(
        question,
        _sessions(("2025-04-01", [("user", "I am working as Lab Director.")])),
    )
    assert plan.premise_alert is not None
    assert "Research Associate" in plan.premise_alert
    assert "Lab Director" in plan.premise_alert


def test_current_role_cannot_refute_a_historical_role_question():
    result = PremiseConsistencyVerifier().verify(
        "How many volunteers did I supervise in my role as Survey Coordinator?",
        facts=[
            _role_fact("Survey Coordinator", end=datetime(2025, 3, 1, tzinfo=UTC)),
            _role_fact("Field Botanist", start=datetime(2025, 3, 1, tzinfo=UTC)),
        ],
        evaluated_at=datetime(2025, 4, 2, tzinfo=UTC),
    )
    assert result.is_consistent


@pytest.mark.parametrize(
    "suffix",
    [
        "Two days after the inspection I collected the keys.",
        "Two days prior to the inspection I collected the keys.",
        "Two days earlier than planned I collected the keys.",
    ],
)
def test_named_reference_is_not_rebound_to_a_different_event(suffix):
    anchors = _resolve("I signed on 2025-02-03. " + suffix)
    assert [a.expression for a in anchors] == ["2025-02-03"]


@pytest.mark.parametrize(
    "suffix",
    [
        "Two days after that inspection I collected the keys.",
        "Two days before that inspection I collected the keys.",
        "Two days after that electrical inspection I collected the keys.",
        "Two days before that Inspection, I collected the keys.",
        "I collected the keys two days after that inspection.",
        "I collected the keys two days before that inspection.",
    ],
)
def test_demonstrative_named_event_is_not_rebound_to_unrelated_date(suffix):
    text = "I signed on 2025-02-03. " + suffix
    anchors = _resolve(text)
    plan = _compile(
        "When did I collect the keys?",
        _sessions(("2025-02-20", [("user", text)])),
    )
    for resolved in (anchors, plan.temporal_anchors):
        assert [(a.expression, a.resolved_date) for a in resolved] == [
            ("2025-02-03", date(2025, 2, 3))
        ]
        for anchor in resolved:
            assert text[anchor.source_start : anchor.source_end] == anchor.expression
    assert "Event Date 2025-02-05" not in plan.compiled_history_text
    assert "Event Date 2025-02-01" not in plan.compiled_history_text
    assert suffix in plan.compiled_history_text


@pytest.mark.parametrize(
    ("suffix", "expression", "expected"),
    [
        (
            "Two days after that I collected the keys.",
            "Two days after that",
            date(2025, 2, 5),
        ),
        (
            "Two days after that, I collected the keys.",
            "Two days after that",
            date(2025, 2, 5),
        ),
        (
            "I collected the keys two days after that.",
            "two days after that",
            date(2025, 2, 5),
        ),
        (
            "Two days before that I collected the keys.",
            "Two days before that",
            date(2025, 2, 1),
        ),
    ],
)
def test_bare_demonstrative_reference_keeps_date_and_raw_source_offsets(
    suffix, expression, expected
):
    text = "  I signed on 2025-02-03.\n\t" + suffix
    anchors = _resolve(text)
    plan = _compile(
        "When did I collect the keys?",
        _sessions(("2025-02-20", [("user", text)])),
    )
    for resolved in (anchors, plan.temporal_anchors):
        assert [(a.expression, a.resolved_date) for a in resolved] == [
            ("2025-02-03", date(2025, 2, 3)),
            (expression, expected),
        ]
        for anchor in resolved:
            assert text[anchor.source_start : anchor.source_end] == anchor.expression
            assert (anchor.source_start, anchor.source_end) == (
                text.index(anchor.expression),
                text.index(anchor.expression) + len(anchor.expression),
            )
            assert (anchor.session_index, anchor.turn_index, anchor.speaker) == (
                1,
                0,
                "user",
            )
    assert f"Event Date {expected.isoformat()}" in plan.compiled_history_text


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("1999-12-31", date(1999, 12, 31)),
        ("2028-02-29", date(2028, 2, 29)),
        ("2/14/1999", date(1999, 2, 14)),
        ("February 14 1999", date(1999, 2, 14)),
    ],
)
def test_explicit_year_is_never_replaced_with_session_year(literal, expected):
    anchors = _resolve("I signed on " + literal + ".")
    assert len(anchors) == 1
    assert anchors[0].resolved_date == expected


@pytest.mark.parametrize("literal", ["2025-02-29", "2025-02-03-04", "2/14/20250"])
def test_invalid_date_tokens_are_not_partially_resolved(literal):
    assert not _resolve("I signed on " + literal + ".")


@pytest.mark.parametrize("question", [
    "When was I promoted to Engineering Director?",
    "When did I get my promotion to Engineering Director?",
])
def test_past_tense_promotion_premise_is_still_checked_against_recorded_promotions(question):
    result = PremiseConsistencyVerifier().verify(
        question,
        evidence_rows=[{"speaker_role": "user", "content": "I was promoted to Senior Engineer.",
                        "created_at": "2025-04-01T00:00:00Z"}],
        evaluated_at=datetime(2025, 4, 2, tzinfo=UTC),
    )
    assert not result.is_consistent
    assert result.abstention_recommended


def test_past_tense_promotion_matching_an_earlier_title_is_consistent():
    result = PremiseConsistencyVerifier().verify(
        "When was I promoted to Survey Coordinator?",
        facts=[
            _role_fact("Survey Coordinator", end=datetime(2025, 3, 1, tzinfo=UTC)),
            _role_fact("Field Botanist", start=datetime(2025, 3, 1, tzinfo=UTC)),
        ],
        evaluated_at=datetime(2025, 4, 2, tzinfo=UTC),
    )
    assert result.is_consistent


@pytest.mark.parametrize("text,expected", [
    ("The marathon on May 5 2000 runners finished.", date(2025, 5, 5)),
    ("We moved on May 5 2023.", date(2023, 5, 5)),
    ("We moved on May 5, 2023 and unpacked.", date(2023, 5, 5)),
    ("I started the job on March 3 and haven't looked back.", date(2025, 3, 3)),
])
def test_month_name_year_and_negation_scope(text, expected):
    anchors = resolve_inline_temporal_expressions(
        text, session_index=0, turn_index=0, speaker="user",
        anchor_date=date(2025, 6, 1), query_date=date(2025, 6, 2),
    )
    assert expected in {a.resolved_date for a in anchors}
