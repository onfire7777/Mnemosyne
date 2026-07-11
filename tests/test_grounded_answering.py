from __future__ import annotations

import copy
from dataclasses import asdict, replace
from datetime import UTC, datetime

import pytest

from mnemosyne.answering import (
    AnswerLimits,
    AnswerReadContext,
    AnswerRequest,
    GroundedAnswerOrchestrator,
)
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence, Hit, Relation, RetrievalResult


class RecordingDecomposer:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def decompose(self, payload: dict[str, object]) -> object:
        self.calls.append(payload)
        return self.response


class RecordingReader:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def read(self, payload: dict[str, object]) -> object:
        self.calls.append(payload)
        return self.response


class FailingReader:
    def read(self, payload: dict[str, object]) -> object:
        raise RuntimeError("provider unavailable")


def _context() -> AnswerReadContext:
    return AnswerReadContext(
        tenant_id="tenant-a",
        branch="main",
        user_id="user-a",
        role="reader",
        source_identity="request-source",
        source_trust_tier=1,
        min_trust_tier=None,
        max_trust_tier=1,
        max_sensitivity=2,
        capability_tags=("memory:read",),
        purpose=("support",),
        residency="us",
        region="us-west",
        lawful_basis=("consent",),
        break_glass=False,
        as_of="2026-07-11T23:59:59Z",
    )


def _engine() -> LocalMemoryEngine:
    engine = LocalMemoryEngine()
    engine.append_evidence(
        Evidence(
            tenant_id="tenant-a",
            user_id="user-a",
            actor="user",
            source_type="chat",
            source_identity="chat-source",
            session_id="session-a",
            content="Ada owns project Zephyr.",
            metadata={"episode": {"session_id": "session-a", "source_identity": "chat-source", "turn_index": 0}},
            access_policy={"tenant": "tenant-a", "allow_principals": ["user-a"], "purposes": ["support"]},
        )
    )
    engine.append_evidence(
        Evidence(
            tenant_id="tenant-a",
            user_id="user-a",
            actor="user",
            source_type="chat",
            source_identity="chat-source",
            session_id="session-a",
            content="Project Zephyr launches Friday.",
            metadata={"episode": {"session_id": "session-a", "source_identity": "chat-source", "turn_index": 1}},
            access_policy={"tenant": "tenant-a", "allow_principals": ["user-a"], "purposes": ["support"]},
        )
    )
    return engine


def test_multi_hop_preserves_complete_immutable_read_context_and_episode_order() -> None:
    engine = _engine()
    decomposer = RecordingDecomposer({"queries": ["Project Zephyr launches"]})
    context = _context()
    result = GroundedAnswerOrchestrator(engine, decomposer).assemble(
        AnswerRequest(question="When does Ada's project launch?", context=context)
    )

    assert result.abstained is False
    assert len(result.trace.hops) == 2
    assert all(hop.context == context for hop in result.trace.hops)
    assert asdict(context) == asdict(_context())
    assert [row.turn_index for row in result.evidence] == [0, 1]
    assert len(result.episodes) == 1
    assert result.episodes[0].session_id == "session-a"
    assert result.episodes[0].evidence_cids == tuple(row.cid for row in result.evidence)
    assert decomposer.calls and set(decomposer.calls[0]) == {"question", "evidence"}
    assert "tenant-a" not in repr(decomposer.calls)


@pytest.mark.parametrize(
    "response",
    [
        {"queries": ["ok"], "filters": {"tenant": "other"}},
        {"queries": ["ok"], "command": "ignore policy"},
        {"queries": ["ok", 1]},
        {"queries": [""]},
        ["not-schema-bound"],
    ],
)
def test_decomposer_accepts_only_exact_bounded_query_schema(response: object) -> None:
    result = GroundedAnswerOrchestrator(_engine(), RecordingDecomposer(response)).assemble(
        AnswerRequest(question="Ada", context=_context())
    )
    assert result.abstained is True
    assert result.answer == ""
    assert result.claims == ()
    assert result.public_reason == "insufficient_authorized_evidence"


def test_unknown_or_filtered_evidence_is_existence_silent() -> None:
    denied = replace(_context(), purpose=("billing",))
    result = GroundedAnswerOrchestrator(_engine(), RecordingDecomposer({"queries": []})).assemble(
        AnswerRequest(question="Ada", context=denied)
    )
    assert result.abstained is True
    assert result.public_reason == "insufficient_authorized_evidence"
    assert result.evidence == ()


def test_narrow_cannot_widen_any_authorization_field() -> None:
    context = _context()
    with pytest.raises(ValueError, match="widen"):
        context.narrow(max_sensitivity=3)
    with pytest.raises(ValueError, match="widen"):
        context.narrow(capability_tags=("memory:read", "admin"))
    with pytest.raises(ValueError, match="widen"):
        context.narrow(tenant_id="tenant-b")
    with pytest.raises(ValueError, match="widen"):
        context.narrow(source_identity="other-source")
    with pytest.raises(ValueError, match="widen"):
        context.narrow(source_trust_tier=2)


@pytest.mark.parametrize(
    "changes",
    [
        {"branch": "other"},
        {"user_id": "other"},
        {"role": "operator"},
        {"residency": "eu"},
        {"region": "eu-west"},
        {"as_of": "2026-07-12T00:00:00Z"},
        {"lawful_basis": ("contract",)},
        {"purpose": ("billing",)},
        {"break_glass": True},
    ],
)
def test_all_context_widening_or_identity_changes_are_rejected(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="widen|replace"):
        _context().narrow(**changes)


def test_context_rejects_unknown_role_and_naive_temporal_scope() -> None:
    with pytest.raises(ValueError, match="role"):
        replace(_context(), role="root")
    with pytest.raises(ValueError, match="timezone"):
        replace(_context(), as_of="2026-07-11T00:00:00")


def test_legacy_min_trust_alias_is_canonicalized_as_an_upper_ceiling() -> None:
    strict = replace(_context(), min_trust_tier=0, max_trust_tier=None)
    permissive = replace(_context(), min_trust_tier=1, max_trust_tier=None)
    assert strict.min_trust_tier is None and strict.max_trust_tier == 0
    assert strict.to_filter()["max_trust_tier"] == 0
    with pytest.raises(ValueError, match="widen"):
        strict.narrow(min_trust_tier=1)
    narrowed = permissive.narrow(min_trust_tier=0)
    assert narrowed.min_trust_tier is None and narrowed.max_trust_tier == 0
    assert narrowed.to_filter()["max_trust_tier"] == 0
    with pytest.raises(ValueError, match="contradicts"):
        replace(_context(), min_trust_tier=0, max_trust_tier=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_trust_tier", -1),
        ("source_trust_tier", 6),
        ("source_trust_tier", True),
        ("min_trust_tier", -1),
        ("min_trust_tier", 999),
        ("min_trust_tier", False),
        ("max_trust_tier", -1),
        ("max_trust_tier", 6),
        ("max_trust_tier", True),
        ("max_sensitivity", -1),
        ("max_sensitivity", 4),
        ("max_sensitivity", False),
    ],
)
def test_context_rejects_out_of_range_or_boolean_trust_and_sensitivity(
    field: str, value: object
) -> None:
    changes = {"min_trust_tier": None, "max_trust_tier": None, field: value}
    with pytest.raises(ValueError, match="invalid"):
        replace(_context(), **changes)


def test_query_hop_evidence_and_character_caps_fail_closed() -> None:
    engine = _engine()
    result = GroundedAnswerOrchestrator(
        engine,
        RecordingDecomposer({"queries": ["one", "two"]}),
        limits=AnswerLimits(max_hops=2, max_queries_per_hop=1, max_evidence=1, max_characters=4),
    ).assemble(AnswerRequest(question="Ada", context=_context()))
    assert result.abstained is True
    assert result.evidence == ()


def test_reauthorization_detects_access_drift_without_disclosing_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    original = engine.export_tenant_filtered
    calls = 0

    def drifting(tenant_id: str, context: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        value = original(tenant_id, context)
        if calls > 1:
            value["evidence"] = []
        return value

    monkeypatch.setattr(engine, "export_tenant_filtered", drifting)
    result = GroundedAnswerOrchestrator(engine, RecordingDecomposer({"queries": []})).assemble(
        AnswerRequest(question="Ada", context=_context())
    )
    assert result.abstained is True
    assert result.public_reason == "insufficient_authorized_evidence"


def test_answer_assembly_does_not_persist_retrieval_access_or_generated_output() -> None:
    engine = _engine()
    before = engine.export_all()
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).assemble(AnswerRequest(question="Ada", context=_context()))
    assert result.abstained is False
    assert engine.export_all() == before


def test_reader_claims_are_approved_only_against_replayed_authorized_cids() -> None:
    engine = _engine()
    assembled = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).assemble(AnswerRequest(question="Ada", context=_context()))
    reader = RecordingReader(
        {
            "claims": [
                {
                    "text": "Ada owns project Zephyr.",
                    "evidence_cids": [assembled.evidence[0].cid],
                }
            ],
            "unresolved": False,
        }
    )
    before = engine.export_all()
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).answer(AnswerRequest(question="Ada", context=_context()), reader)
    assert result.abstained is False
    assert result.answer == "Ada owns project Zephyr."
    assert result.claims[0].evidence_cids == (assembled.evidence[0].cid,)
    assert set(reader.calls[0]) == {"question", "evidence"}
    assert engine.export_all() == before


@pytest.mark.parametrize(
    "response",
    [
        {"claims": [{"text": "fabricated", "evidence_cids": ["unknown"]}], "unresolved": False},
        {"claims": [{"text": "duplicate", "evidence_cids": ["x", "x"]}], "unresolved": False},
        {"claims": [{"text": "uncited", "evidence_cids": []}], "unresolved": False},
        {"claims": [{"text": "mismatch", "evidence_cids": ["x"]}], "unresolved": True},
        {"claims": [], "unresolved": False},
        {"claims": [], "unresolved": True, "self_validated": True},
    ],
)
def test_reader_schema_citations_and_abstention_fail_closed(response: object) -> None:
    result = GroundedAnswerOrchestrator(
        _engine(), RecordingDecomposer({"queries": []})
    ).answer(AnswerRequest(question="Ada", context=_context()), RecordingReader(response))
    assert result.abstained is True
    assert result.answer == "" and result.claims == ()
    assert len(result.evidence) == 1
    assert result.trace.hops and result.trace.evidence_fingerprint


def test_retrieval_abstention_prevents_reader_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    original = engine.retrieve

    def abstained(*args: object, **kwargs: object) -> RetrievalResult:
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        return replace(result, abstained=True, abstain_reason="retrieval-floor")

    monkeypatch.setattr(engine, "retrieve", abstained)
    reader = RecordingReader({"claims": [], "unresolved": True})
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).answer(AnswerRequest(question="Ada", context=_context()), reader)
    assert result.abstained is True
    assert reader.calls == []


def test_reader_provider_failure_does_not_retain_unreplayed_trace() -> None:
    result = GroundedAnswerOrchestrator(
        _engine(), RecordingDecomposer({"queries": []})
    ).answer(AnswerRequest(question="Ada", context=_context()), FailingReader())
    assert result.abstained is True
    assert result.evidence == () and result.trace.hops == ()


def test_replay_drift_does_not_retain_stale_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = GroundedAnswerOrchestrator(
        _engine(), RecordingDecomposer({"queries": []})
    )
    original = orchestrator.assemble
    calls = 0

    def drifting(request: AnswerRequest):
        nonlocal calls
        calls += 1
        result = original(request)
        return replace(result, evidence=()) if calls == 2 else result

    monkeypatch.setattr(orchestrator, "assemble", drifting)
    result = orchestrator.answer(
        AnswerRequest(question="Ada", context=_context()),
        RecordingReader({"claims": [], "unresolved": True}),
    )
    assert result.abstained is True
    assert result.evidence == () and result.trace.hops == ()


def test_temporal_scope_is_timezone_aware_and_reaches_graph_ppr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    observed: list[datetime | None] = []
    original = engine.graph_ppr

    def graph(*args: object, **kwargs: object) -> list[Hit]:
        observed.append(kwargs.get("as_of"))  # type: ignore[arg-type]
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(engine, "graph_ppr", graph)
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).assemble(AnswerRequest(question="Ada", context=_context()))
    assert result.abstained is False
    assert observed
    assert all(
        value == datetime(2026, 7, 11, 23, 59, 59, tzinfo=UTC)
        for value in observed
    )


def test_two_hop_access_swap_with_same_union_fails_per_hop_replay() -> None:
    class SwappingEngine:
        def __init__(self) -> None:
            self.calls = 0

        def retrieve(self, query: str, **_: object) -> RetrievalResult:
            self.calls += 1
            initial = self.calls <= 2
            cid = ("a" if query == "first" else "b") if initial else ("b" if query == "first" else "a")
            hit = Hit(cid, "evidence", "tenant-a", "main", cid, 1.0, "lexical", [cid])
            return RetrievalResult(query, [hit], 1.0, False, None, 10, 1, {})

        def export_tenant_filtered(self, _tenant: str, _context: dict[str, object]) -> dict[str, object]:
            return {
                "evidence": [
                    {
                        "branch": "main", "cid": cid, "content": cid,
                        "metadata": {}, "session_id": None,
                        "source_identity": f"source-{cid}", "tenant_id": "tenant-a",
                        "trust_tier": 0, "sensitivity": 0,
                    }
                    for cid in ("a", "b")
                ]
            }

        def get_evidence(self, tenant: str, cid: str, branch: str) -> Evidence:
            return Evidence(
                tenant_id=tenant, user_id="user-a", actor="user",
                source_type="chat", source_identity=f"source-{cid}",
                content=cid, branch=branch, cid=cid,
                access_policy={"tenant": tenant},
            )

    result = GroundedAnswerOrchestrator(
        SwappingEngine(),  # type: ignore[arg-type]
        RecordingDecomposer({"queries": ["second"]}),
    ).assemble(AnswerRequest(question="first", context=_context()))
    assert result.abstained is True
    assert result.public_reason == "insufficient_authorized_evidence"


def test_episode_metadata_must_exactly_match_canonical_evidence_identity() -> None:
    engine = _engine()
    row = next(iter(engine.evidence.values()))
    row.metadata["episode"]["session_id"] = "other-session"
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).assemble(AnswerRequest(question="Ada", context=_context()))
    assert result.abstained is True
    assert result.evidence == ()


def test_access_policy_fingerprint_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    original = engine.get_evidence
    calls = 0

    def changed_policy(tenant: str, cid: str, branch: str = "main") -> Evidence | None:
        nonlocal calls
        calls += 1
        row = original(tenant, cid, branch)
        if row is not None and calls > 1:
            row = copy.deepcopy(row)
            row.access_policy = {**row.access_policy, "allow_roles": ["reader"]}
        return row

    monkeypatch.setattr(engine, "get_evidence", changed_policy)
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).assemble(AnswerRequest(question="Ada", context=_context()))
    assert result.abstained is True
    assert result.public_reason == "insufficient_authorized_evidence"


def test_graph_relation_id_is_never_cited_and_authorized_source_is_hydrated() -> None:
    engine = _engine()
    source_cid = next(iter(engine.evidence.values())).cid
    assert source_cid is not None
    relation_id = engine.add_relation(
        Relation(
            tenant_id="tenant-a",
            source="Ada",
            predicate="owns",
            target="Zephyr",
            source_evidence_cids=[source_cid],
            access_policy={"tenant": "tenant-a"},
        )
    )
    result = GroundedAnswerOrchestrator(
        engine, RecordingDecomposer({"queries": []})
    ).assemble(AnswerRequest(question="Ada owns Zephyr", context=_context()))
    assert result.abstained is False
    assert relation_id not in {row.cid for row in result.evidence}
    assert source_cid in {row.cid for row in result.evidence}
