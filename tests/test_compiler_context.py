"""Unit tests for MemoryContextCompiler and inline temporal resolution."""

from __future__ import annotations

from datetime import UTC, date, datetime

from mnemosyne.compiler_context import (
    MemoryContextCompiler,
    resolve_inline_temporal_expressions,
    sanitize_sessions,
)


def test_resolve_inline_temporal_expressions_relative_and_explicit():
    anchor = date(2025, 5, 14)  # Wednesday
    query_d = date(2025, 6, 1)

    text = (
        "Synthetic fixture: calibrated spectrometer last Thursday, rotated keys three weeks ago, "
        "scheduled maintenance on 5/2, and queued benchmark in two weeks."
    )
    anchors = resolve_inline_temporal_expressions(
        text,
        session_index=1,
        turn_index=0,
        speaker="user",
        anchor_date=anchor,
        query_date=query_d,
    )
    by_date = {a.resolved_date: a for a in anchors}
    # Preceding Thursday before Wednesday 2025-05-14 is 2025-05-08
    assert date(2025, 5, 8) in by_date
    assert by_date[date(2025, 5, 8)].days_to_query_date == 24
    # Three weeks before 2025-05-14 is 2025-04-23
    assert date(2025, 4, 23) in by_date
    # Explicit "on 5/2" -> 2025-05-02
    assert date(2025, 5, 2) in by_date
    # "in two weeks" -> 2025-05-28
    assert date(2025, 5, 28) in by_date


def test_sanitize_sessions_strips_oracle_fields():
    raw_sessions = [
        [
            {"role": "user", "content": "Hello", "has_answer": True, "secret_label": "gold"},
            {"role": "assistant", "content": "Hi there", "has_answer": False},
        ]
    ]
    clean = sanitize_sessions(
        raw_sessions,
        ["2025/05/14 (Wed) 10:00"],
        [datetime(2025, 5, 14, 10, 0, tzinfo=UTC)],
    )
    assert len(clean) == 1
    assert clean[0].turns == (("user", "Hello"), ("assistant", "Hi there"))


def test_user_only_channel_rescues_diluted_side_remark_and_flags_premise():
    filler_assistant = " ".join(["Synthetic compiler pipeline documentation."] * 350)
    raw_sessions = [
        [
            {"role": "user", "content": "Inspect module alpha. Side note: registered telemetry beacon Quasar7 yesterday."},
            {"role": "assistant", "content": filler_assistant},
        ],
        [
            {"role": "user", "content": "Explain synthetic module beta configuration."},
            {"role": "assistant", "content": "Module beta uses static configuration."},
        ],
        [
            {"role": "user", "content": "Working as Principal Kernel Architect at SyntheticCorp."},
            {"role": "assistant", "content": "Noted Principal Kernel Architect assignment."},
        ],
    ]
    dates = [
        "2025/05/10 (Sat) 09:00",
        "2025/05/12 (Mon) 11:00",
        "2025/05/15 (Thu) 14:00",
    ]
    ts = [
        datetime(2025, 5, 10, 9, 0, tzinfo=UTC),
        datetime(2025, 5, 12, 11, 0, tzinfo=UTC),
        datetime(2025, 5, 15, 14, 0, tzinfo=UTC),
    ]
    sessions = sanitize_sessions(raw_sessions, dates, ts)
    compiler = MemoryContextCompiler(core_top_k=2, extended_max_extra=1)

    plan = compiler.compile_memory(
        "When did I register telemetry beacon Quasar7?",
        "2025/05/20 (Tue) 12:00",
        datetime(2025, 5, 20, 12, 0, tzinfo=UTC),
        sessions,
    )
    assert plan.ranked_session_indices[0] == 0
    assert "2025-05-09" in plan.compiled_history_text
    assert "11 days before Current Date" in plan.compiled_history_text

    plan_mismatch = compiler.compile_memory(
        "What systems do I oversee in my position as Chief Firmware Officer?",
        "2025/05/20 (Tue) 12:00",
        datetime(2025, 5, 20, 12, 0, tzinfo=UTC),
        sessions,
    )
    assert plan_mismatch.premise_alert is not None
    assert "Chief Firmware Officer" in plan_mismatch.premise_alert
    assert "Principal Kernel Architect" in plan_mismatch.premise_alert


def test_compiler_handles_multi_facet_comparison_queries():
    raw_sessions = [
        [
            {"role": "user", "content": "Completed benchmark 'ZetaKernel' in 48 seconds."},
            {"role": "assistant", "content": "Recorded ZetaKernel timing."},
        ],
        [
            {"role": "user", "content": "Completed benchmark 'OmegaKernel' in 54 seconds."},
            {"role": "assistant", "content": "Recorded OmegaKernel timing."},
        ],
    ]
    sessions = sanitize_sessions(
        raw_sessions,
        ["2025/05/01 (Thu) 08:00", "2025/05/08 (Thu) 08:00"],
        [datetime(2025, 5, 1, 8, 0, tzinfo=UTC), datetime(2025, 5, 8, 8, 0, tzinfo=UTC)],
    )
    compiler = MemoryContextCompiler(core_top_k=2, extended_max_extra=0)
    plan = compiler.compile_memory(
        "Was 'ZetaKernel' or 'OmegaKernel' faster?",
        "2025/05/10 (Sat) 09:00",
        datetime(2025, 5, 10, 9, 0, tzinfo=UTC),
        sessions,
    )
    assert set(plan.core_session_indices) == {0, 1}
    assert "48 seconds" in plan.compiled_history_text
    assert "54 seconds" in plan.compiled_history_text
