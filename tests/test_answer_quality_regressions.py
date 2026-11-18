"""Synthetic answer-path regressions; no providers or persistent stores."""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
from datetime import UTC, datetime

import pytest

from mnemosyne.answering import (
    AnswerLimits,
    AnswerReadContext,
    AnswerRequest,
    GroundedAnswerOrchestrator,
    adaptive_synthesize,
)
from mnemosyne.event_ledger import EventLedger
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence


class _SaffronDecomposer:
    def decompose(self, payload):
        return {"queries": ["Saffron"]}


class _UnresolvedReader:
    def read(self, payload):
        return {"claims": [], "unresolved": True}


def _engine_with(content, *, actor="user", created_at=None):
    engine = LocalMemoryEngine()
    engine.append_evidence(
        Evidence(
            tenant_id="synthetic",
            user_id="invented",
            actor=actor,
            source_type="chat",
            content=content,
            created_at=created_at or datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    return engine


def _orchestrator(engine):
    return GroundedAnswerOrchestrator(
        engine,
        _SaffronDecomposer(),
        limits=AnswerLimits(max_hops=1),
    )


def _request(question="Which port does Saffron launch use?"):
    return AnswerRequest(question, AnswerReadContext("synthetic"))


@pytest.mark.parametrize("fallback", [False, True])
def test_adaptive_fact_handoff_uses_the_strict_quote_proposal(fallback):
    content = "Saffron launch uses port 7421."
    engine = _engine_with(content)
    orchestrator = _orchestrator(engine)
    assert not orchestrator.assemble(_request()).abstained

    answer = orchestrator.answer(
        _request(),
        _UnresolvedReader() if fallback else None,
        adaptive_synthesis=fallback,
    )

    assert not answer.abstained, answer.failure_kind
    assert answer.failure_kind is None
    assert answer.answer == content
    assert answer.claims[0].text == content
    assert answer.claims[0].spans[0].start == 0
    assert answer.claims[0].spans[0].end == len(content)


def test_assistant_purchase_is_not_reassigned_after_canonical_hydration():
    engine = _engine_with("I bought a microscope for $240.", actor="assistant")
    orchestrator = _orchestrator(engine)
    rows = orchestrator._authorized_rows(_request().context, None)
    evidence = tuple(orchestrator._evidence(cid, row, 0) for cid, row in rows.items())
    assert evidence

    result = adaptive_synthesize("How much did I spend on microscope?", evidence)

    assert "You spent $240" not in result["answer"]
    assert not EventLedger().extract_from_evidence(evidence)
    assert evidence[0].actor == "assistant"


@pytest.mark.parametrize("speaker", [None, "unknown", "tool", "assistant"])
def test_ledger_never_defaults_unknown_attribution_to_user(speaker):
    row = {"cid": "unattributed", "content": "I bought a microscope for $240."}
    if speaker is not None:
        row["actor"] = speaker
    assert EventLedger().extract_from_evidence([row]) == []


def test_canonical_assistant_cannot_relabel_its_purchase_as_a_user_turn():
    row = {
        "cid": "assistant-quotation",
        "actor": "assistant",
        "speaker_role": "user",
        "content": "User: I bought a microscope for $240.",
    }
    assert EventLedger().extract_from_evidence([row]) == []


def test_canonical_timestamps_survive_evidence_serialization_and_timeline_order():
    rows = [
        {
            "cid": "later",
            "actor": "user",
            "content": "Saffron launch was completed.",
            "created_at": "2025-02-01T00:00:00+00:00",
        },
        {
            "cid": "earlier",
            "actor": "user",
            "content": "Saffron launch was planned.",
            "created_at": "2025-01-01T00:00:00+00:00",
        },
    ]
    evidence = [
        GroundedAnswerOrchestrator._evidence(row["cid"], row, 0) for row in rows
    ]
    result = adaptive_synthesize("Show the timeline of Saffron launch.", evidence)

    assert [event["cid"] for event in result["timeline_events"]] == ["earlier", "later"]
    assert [event["timestamp"] for event in result["timeline_events"]] == [
        rows[1]["created_at"],
        rows[0]["created_at"],
    ]
    assert asdict(evidence[0])["created_at"] == rows[0]["created_at"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor", "assistant"),
        ("created_at", "2025-02-01T00:00:00+00:00"),
    ],
)
def test_assembly_replay_detects_provenance_only_drift(monkeypatch, field, value):
    engine = _engine_with("Saffron launch uses port 7421.")
    export = engine.export_tenant_filtered
    calls = 0

    def changing_export(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = export(*args, **kwargs)
        if calls > 1:
            result["evidence"][0][field] = value
        return result

    monkeypatch.setattr(engine, "export_tenant_filtered", changing_export)
    result = _orchestrator(engine).assemble(_request())
    assert result.abstained
    assert result.failure_kind == "replay_drift"
    assert not result.evidence


@pytest.mark.parametrize(
    "question",
    [
        "How often did I attend workshops?",
        "How many observatories did I visit?",
        "How much did I spend on microscopes?",
    ],
)
def test_unrelated_evidence_is_not_a_count_or_a_proven_zero(question):
    result = adaptive_synthesize(
        question,
        [
            {
                "cid": "roof-repair",
                "actor": "user",
                "content": "I repaired the greenhouse roof.",
            }
        ],
    )
    assert result["abstained"]
    assert result["claims"] == []
    assert result["count"] is None
    assert result["cited_cids"] == []


def test_supported_cost_question_still_uses_matching_attributed_purchase():
    result = adaptive_synthesize(
        "How much did the microscope cost?",
        [
            {
                "cid": "user-purchase",
                "actor": "user",
                "content": "I bought a microscope for $240.",
            }
        ],
    )
    assert not result["abstained"]
    assert "$240.00" in result["answer"]
    assert result["count"] == 1


def test_assistant_only_purchase_cannot_prove_zero_user_purchases():
    result = adaptive_synthesize(
        "How much did I spend on microscope?",
        [
            {
                "cid": "assistant-purchase",
                "actor": "assistant",
                "content": "I bought a microscope for $240.",
            }
        ],
    )
    assert result["abstained"]
    assert result["count"] is None
    assert result["claims"] == []


@pytest.mark.parametrize(
    "prefix", ["", "Earlier maintenance notes. " * 700], ids=["beginning", "middle"]
)
def test_long_canonical_source_answers_from_bounded_exact_window(prefix):
    fact = "Saffron launch uses port 7421."
    content = prefix + fact + " More deployment notes." * 1100
    engine = _engine_with(content)
    orchestrator = _orchestrator(engine)
    retrieved = engine.retrieve(
        "Saffron", tenant_id="synthetic", deep=True, record_access=False
    )
    assert not retrieved.abstained
    assert fact in retrieved.hits[0].text
    assert (
        len(retrieved.hits[0].text) < orchestrator.limits.max_characters < len(content)
    )

    assembled = orchestrator.assemble(_request())
    assert not assembled.abstained, assembled.failure_kind
    assert (
        sum(len(row.content) for row in assembled.evidence)
        <= orchestrator.limits.max_characters
    )
    assert all(row.content in content for row in assembled.evidence)

    answer = orchestrator.answer(_request())
    assert not answer.abstained, answer.failure_kind
    assert fact in answer.answer
    assert "truncated for budget" not in answer.answer
    for claim in answer.claims:
        assert claim.text == " ".join(content[s.start : s.end] for s in claim.spans)
    if prefix:
        assert answer.claims[0].spans[0].start > 0


def test_premise_abstention_does_not_report_a_numeric_count():
    result = adaptive_synthesize(
        "How many gardeners do I lead in my new role as Regional Forester?",
        [
            {
                "cid": "role-change",
                "actor": "user",
                "speaker_role": "user",
                "content": "I was just promoted to Botanical Archivist at my company.",
            }
        ],
    )
    assert result["abstained"]
    assert result["premise_verification"]["abstention_recommended"]
    assert result["claims"] == []
    assert result["count"] is None


@pytest.mark.parametrize(
    "quote", ["Saffron launch uses port 7421.", "Unselected tail marker."]
)
def test_reader_only_sees_bounded_window_and_cannot_cite_unselected_tail(quote):
    fact = "Saffron launch uses port 7421."
    content = (
        "Earlier maintenance notes. " * 700
        + fact
        + " More deployment notes." * 1100
        + " Unselected tail marker."
    )
    engine = _engine_with(content)
    calls = []

    class Reader:
        def read(self, payload):
            calls.append(payload)
            row = payload["evidence"][0]
            assert len(row["content"]) <= 24000
            assert "Unselected tail marker." not in row["content"]
            return {
                "claims": [{"spans": [{"cid": row["cid"], "quote": quote}]}],
                "unresolved": False,
            }

    result = _orchestrator(engine).answer(_request(), Reader())
    assert calls
    if quote == fact:
        assert not result.abstained, result.failure_kind
        span = result.claims[0].spans[0]
        assert span.start == content.index(fact)
        assert content[span.start : span.end] == fact
        assert span.slice_sha256 == hashlib.sha256(fact.encode()).hexdigest()
    else:
        assert result.abstained
        assert result.failure_kind == "invalid_reader_proposal"
        assert not result.claims


def test_selected_window_cannot_use_unredacted_raw_content(monkeypatch):
    engine = _engine_with("Saffron launch uses port 7421.")
    export = engine.export_tenant_filtered

    def redacted_export(*args, **kwargs):
        result = export(*args, **kwargs)
        result["evidence"][0]["content"] = "Saffron launch uses port [REDACTED]."
        return result

    monkeypatch.setattr(engine, "export_tenant_filtered", redacted_export)
    result = _orchestrator(engine).assemble(_request())
    assert result.abstained
    assert not result.evidence


def test_window_replay_checks_the_unselected_canonical_tail(monkeypatch):
    engine = _engine_with(
        "Saffron launch uses port 7421." + " More deployment notes." * 1100
    )
    export = engine.export_tenant_filtered
    calls = 0

    def changed_tail(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = export(*args, **kwargs)
        if calls > 1:
            result["evidence"][0]["content"] += " Changed canonical tail."
        return result

    monkeypatch.setattr(engine, "export_tenant_filtered", changed_tail)
    result = _orchestrator(engine).assemble(_request())
    assert result.abstained
    assert result.failure_kind == "replay_drift"
    assert not result.evidence


def test_retrieved_window_must_resolve_to_authorized_canonical_text(monkeypatch):
    engine = _engine_with("Saffron launch uses port 7421.")
    retrieve = engine.retrieve

    def invented_window(*args, **kwargs):
        result = retrieve(*args, **kwargs)
        return replace(
            result,
            hits=[
                replace(hit, text="Saffron launch uses port 9001.")
                for hit in result.hits
            ],
        )

    monkeypatch.setattr(engine, "retrieve", invented_window)
    result = _orchestrator(engine).assemble(_request())
    assert result.abstained
    assert not result.evidence


def test_adaptive_window_spans_remain_source_relative():
    content = "Saffron launch uses port 7421."
    evidence = GroundedAnswerOrchestrator._evidence(
        "window",
        {
            "content": content,
            "content_start": 500,
            "actor": "user",
        },
        0,
    )
    result = adaptive_synthesize("Which port does Saffron launch use?", [evidence])
    span = result["claims"][0]["spans"][0]
    assert (span["start"], span["end"]) == (500, 500 + len(content))
    assert span["quote"] == content


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize(
    "question", ["How much did I spend on microscope?", "Compare microscope purchases."]
)
def test_default_multirow_answer_keeps_all_support_within_strict_limits(question, fallback):
    engine = LocalMemoryEngine()
    for month, color in enumerate(("blue", "red", "green", "yellow"), 1):
        engine.append_evidence(Evidence(
            tenant_id="synthetic", user_id="invented", actor="user", source_type="chat",
            content=f"I bought a {color} microscope for $240.",
            created_at=datetime(2025, month, 1, tzinfo=UTC),
        ))

    class Decomposer:
        def decompose(self, payload):
            return {"queries": ["microscope"]}

    orchestrator = GroundedAnswerOrchestrator(engine, Decomposer(), limits=AnswerLimits(max_hops=1))
    request = _request(question)
    assembled = orchestrator.assemble(request)
    assert len(assembled.evidence) == 4
    answer = orchestrator.answer(request, _UnresolvedReader() if fallback else None,
                                 adaptive_synthesis=fallback)
    assert not answer.abstained, answer.failure_kind
    assert answer.failure_kind is None
    assert {s.cid for c in answer.claims for s in c.spans} == {e.cid for e in assembled.evidence}
    for color in ("blue", "red", "green", "yellow"):
        assert color in answer.answer
    assert all(len(c.spans) <= 3 and len(c.text) <= 2000 for c in answer.claims)


@pytest.mark.parametrize("fallback", [False, True])
def test_default_answer_splits_medium_source_into_bounded_complete_quotes(fallback):
    content = "Saffron launch uses port 7421." + " Deployment notes." * 300
    engine = _engine_with(content)
    orchestrator = _orchestrator(engine)
    assembled = orchestrator.assemble(_request())
    assert not assembled.abstained
    assert len(assembled.evidence[0].content) > 2000
    answer = orchestrator.answer(_request(), _UnresolvedReader() if fallback else None,
                                 adaptive_synthesis=fallback)
    assert not answer.abstained, answer.failure_kind
    assert "Saffron launch uses port 7421." in answer.answer
    assert " ".join(answer.answer.split()) == " ".join(content.split())
    assert all(len(c.text) <= 2000 for c in answer.claims)
    for claim in answer.claims:
        for span in claim.spans:
            assert content[span.start:span.end] == claim.text
            assert hashlib.sha256(claim.text.encode()).hexdigest() == span.slice_sha256


@pytest.mark.parametrize("quote", ["Saffron launch uses port 7421.", "Unselected tail marker."])
def test_projection_reference_exposes_only_quote_matched_canonical_window(monkeypatch, quote):
    fact = "Saffron launch uses port 7421."
    content = "Earlier note. " * 7 + fact + " More deployment notes." * 300 + " Unselected tail marker."
    engine = _engine_with(content)
    retrieve = engine.retrieve

    def projection_only(*args, **kwargs):
        result = retrieve(*args, **kwargs)
        hit = result.hits[0]
        return replace(result, hits=[replace(
            hit, id="synthetic-relation", kind="relation", text=fact,
            provenance=[hit.id], metadata={"source_evidence_cids": [hit.id]},
        )])

    monkeypatch.setattr(engine, "retrieve", projection_only)
    calls = []

    class Reader:
        def read(self, payload):
            calls.append(payload)
            return {"claims": [{"spans": [{"cid": payload["evidence"][0]["cid"], "quote": quote}]}],
                    "unresolved": False}

    result = _orchestrator(engine).answer(_request(), Reader())
    assert calls
    assert calls[0]["evidence"][0]["content"] == fact
    if quote == fact:
        assert not result.abstained, result.failure_kind
        span = result.claims[0].spans[0]
        assert span.start == content.index(fact)
        assert content[span.start:span.end] == fact
    else:
        assert result.abstained
        assert result.failure_kind == "invalid_reader_proposal"
        assert not result.claims


def test_selected_transcript_window_retains_canonical_assistant_speaker():
    purchase = "I bought a microscope for $240."
    content = "User: Hello.\nAssistant: " + "Earlier commentary. " * 1400 + purchase + " Later commentary." * 1400
    engine = _engine_with(content)

    class Decomposer:
        def decompose(self, payload):
            return {"queries": ["microscope"]}

    orchestrator = GroundedAnswerOrchestrator(engine, Decomposer(), limits=AnswerLimits(max_hops=1))
    request = _request("How much did I spend on microscope?")
    full_rows = orchestrator._authorized_rows(request.context, None)
    assert EventLedger().extract_from_evidence(list(full_rows.values())) == []
    assembled = orchestrator.assemble(request)
    assert not assembled.abstained, assembled.failure_kind
    row = assembled.evidence[0]
    assert purchase in row.content and "Assistant:" not in row.content
    assert row.actor == "user"
    assert row.content_start > 0
    assert content[row.content_start:row.content_start + len(row.content)] == row.content
    assert EventLedger().extract_from_evidence(assembled.evidence) == []
    assert EventLedger().extract_from_evidence([asdict(row)]) == []
    result = adaptive_synthesize(request.question, assembled.evidence)
    assert result["abstained"] and result["count"] is None
    assert result["claims"] == []
    answer = orchestrator.answer(request)
    assert answer.abstained and answer.failure_kind is None
    assert not answer.claims


def test_external_reader_span_schema_stays_strict():
    with pytest.raises(ValueError, match="span schema"):
        GroundedAnswerOrchestrator._claims(
            {
                "claims": [
                    {"spans": [{"cid": "fact", "quote": "Saffron", "start": 0}]}
                ],
                "unresolved": False,
            },
            {"fact": "Saffron"},
        )


def test_paraphrased_projection_before_its_source_hit_does_not_abort_the_answer(monkeypatch):
    fact = "Saffron launch uses port 7421."
    content = "Earlier note. " * 7 + fact + " More deployment notes." * 300
    engine = _engine_with(content)
    retrieve = engine.retrieve

    def projection_first(*args, **kwargs):
        result = retrieve(*args, **kwargs)
        hit = result.hits[0]
        projection = replace(
            hit, id="synthetic-relation", kind="relation", text="Saffron launch port 7421",
            provenance=[hit.id], metadata={"source_evidence_cids": [hit.id]},
        )
        return replace(result, hits=[projection, *result.hits])

    monkeypatch.setattr(engine, "retrieve", projection_first)

    class Reader:
        def read(self, payload):
            return {"claims": [{"spans": [{"cid": payload["evidence"][0]["cid"], "quote": fact}]}],
                    "unresolved": False}

    result = _orchestrator(engine).answer(_request(), Reader())
    assert not result.abstained, result.failure_kind
    assert content[result.claims[0].spans[0].start:result.claims[0].spans[0].end] == fact


def test_paraphrased_projection_alone_withholds_its_source_instead_of_disclosing_it(monkeypatch):
    content = "Earlier note. " * 7 + "Saffron launch uses port 7421." + " More deployment notes." * 300
    engine = _engine_with(content)
    retrieve = engine.retrieve

    def projection_only(*args, **kwargs):
        result = retrieve(*args, **kwargs)
        hit = result.hits[0]
        return replace(result, hits=[replace(
            hit, id="synthetic-relation", kind="relation", text="Saffron launch port 7421",
            provenance=[hit.id], metadata={"source_evidence_cids": [hit.id]},
        )])

    monkeypatch.setattr(engine, "retrieve", projection_only)
    calls = []

    class Reader:
        def read(self, payload):
            calls.append(payload)
            return {"claims": [], "unresolved": True}

    result = _orchestrator(engine).answer(_request(), Reader())
    assert result.abstained
    assert result.failure_kind != "assembly_error"
    assert all(row["content"] != content for call in calls for row in call["evidence"])
