"""Persistent semantic identity stays scoped, evidenced and replayable."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.memory_formation import project_direct_user_memory, preview_direct_user_memory, reproject_direct_user_memory
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "store")
    yield store
    store.close()


def capture(engine, text, *, hour=0, user="alice", session="one", workspace="/work/project", policy=None, **options):
    cid = engine.append_evidence(Evidence(
        tenant_id="t", user_id=user, actor="user", source_type="chat", content=text,
        created_at=datetime(2026, 11, 9, tzinfo=UTC) + timedelta(hours=hour),
        document_segment_id=sha256(repr((text, hour, user, session, workspace)).encode()).hexdigest(),
        session_id=session, trust_tier=1, metadata={"workspace": workspace} if workspace else {},
        access_policy={"tenant": "t", "allow_principals": [user], **(policy or {})},
    ))
    return cid, project_direct_user_memory(engine, "t", cid, **options)


def rows(engine):
    return engine.export_tenant("t")["assertions"]


def test_neutral_intervening_turn_and_long_gap_preserve_focus(engine):
    intro, _ = capture(engine, "My deployment server is Atlas.")
    capture(engine, "continue", hour=1)
    current, result = capture(engine, "It runs Debian.", hour=30)
    fact = next(row for row in rows(engine) if row["predicate"] == "runs")
    assert fact["subject"] == "Atlas"
    assert set(fact["source_evidence_cids"]) == {intro, current}
    assert result["rejected_proposals"] == []


def test_cross_session_role_and_explicit_scope_focus_persist(engine):
    intro, _ = capture(engine, "My deployment server is Atlas.")
    current, result = capture(engine, "The deployment server runs Debian.", hour=30, session="two")
    fact = next(row for row in rows(engine) if row["id"] in result["assertion_ids"])
    assert fact["subject"] == "Atlas"
    assert set(fact["source_evidence_cids"]) == {intro, current}
    _, result = capture(engine, "It hosts our dashboard.", hour=40, session="three")
    fact = next(row for row in rows(engine) if row["id"] in result["assertion_ids"])
    assert fact["subject"] == "Atlas"
    assert len(fact["source_evidence_cids"]) == 3  # identity plus the explicit focus-setting source


def test_named_alias_updates_the_original_entity_without_cross_scope_conflicts(engine):
    intro, _ = capture(engine, "My deployment server is Atlas. It runs Debian.")
    capture(engine, "My deployment server is Atlas. It runs Ubuntu.", workspace="/work/other")
    rename, result = capture(engine, "I renamed Atlas to Orion.", hour=1)
    assert result["unresolved"] == []
    current, result = capture(engine, "Orion runs Fedora.", hour=30, session="two")
    fact = next(row for row in rows(engine) if row["id"] in result["assertion_ids"])
    assert (fact["subject"], fact["object"]) == ("Atlas", "Fedora")
    assert set(fact["source_evidence_cids"]) == {intro, rename, current}
    assert fact["calibration"]["source_quote"] == "Orion runs Fedora."
    assert {(row["object"], str(row["scope"])) for row in rows(engine) if row["predicate"] == "runs" and row["status"] == "active"} == {
        ("Fedora", str({"entity_scope": {"workspace": "/work/project"}})),
        ("Ubuntu", str({"entity_scope": {"workspace": "/work/other"}})),
    }


def test_unknown_project_and_ambiguous_role_never_pick_a_name(engine):
    capture(engine, "I have two servers: Atlas and Borealis.")
    _, ambiguous = capture(engine, "The server runs Debian.", hour=1)
    assert ambiguous["count"] == 0
    assert ambiguous["rejected_proposals"][0]["reason"] == "ambiguous_entity_reference"
    _, other = capture(engine, "The server runs Debian.", hour=2, workspace="/work/unknown")
    assert other["count"] == 0
    _, other_user = capture(engine, "It runs Debian.", hour=2, user="bob")
    assert other_user["count"] == 0


def test_conflicting_alias_does_not_unify_distinct_entities(engine):
    capture(engine, "I have two servers: Atlas and Borealis.")
    _, result = capture(engine, "I renamed Borealis to Atlas.", hour=1)
    assert not [row for row in rows(engine) if row["predicate"] == "entity_alias"]
    assert result["rejected_proposals"][0]["reason"] == "ambiguous_or_unknown_rename"


def test_unrelated_turn_remains_a_focus_boundary_in_preview(engine):
    capture(engine, "My server is Atlas.")
    capture(engine, "Please implement the memory audit.", hour=1)
    cid, result = capture(engine, "It runs Debian.", hour=2)
    assert result["count"] == 0
    assert preview_direct_user_memory(engine, "t", cid)["assertions"] == []


def test_replay_excludes_self_future_and_future_rename_sources(engine):
    intro, _ = capture(engine, "My server is Atlas.")
    cid, result = capture(engine, "It runs Debian.", hour=1)
    original = next(row for row in rows(engine) if row["id"] in result["assertion_ids"])
    capture(engine, "It hosts our dashboard.", hour=2)
    capture(engine, "I renamed Atlas to Orion.", hour=3)
    before = deepcopy(engine.export_tenant("t"))
    [replayed] = preview_direct_user_memory(engine, "t", cid)["assertions"]
    assert replayed["id"] == original["id"]
    assert set(replayed["source_evidence_cids"]) == {intro, cid}
    assert replayed["calibration"]["source_spans"] == original["calibration"]["source_spans"]
    assert engine.export_tenant("t") == before


def test_erased_identity_cannot_resolve_a_later_pronoun(engine):
    intro, _ = capture(engine, "My server is Atlas.")
    capture(engine, "It runs Debian.", hour=1)
    engine.forget("t", intro)
    _, result = capture(engine, "It hosts our dashboard.", hour=2)
    assert result["count"] == 0
    assert not [row for row in rows(engine) if row["status"] == "active" and row["subject"] == "Atlas"]


def test_identity_expiry_and_denial_are_rechecked(engine, monkeypatch):
    import mnemosyne.memory_formation as formation
    intro, _ = capture(engine, "My server is Atlas.", policy={"expires_at": "2999-01-01T00:00:00Z"})
    monkeypatch.setattr(formation, "utc_now", lambda: datetime(3000, 1, 1, tzinfo=UTC))
    _, result = capture(engine, "It runs Debian.", hour=1)
    assert result["count"] == 0


def test_apposition_and_causal_move_reach_the_proposer_without_inventing_a_schedule(engine):
    calls = []
    def proposer(payload):
        calls.append(payload)
        return {"claims": []}
    first, _ = capture(engine, "My deployment server, Atlas, runs Debian.", semantic_proposer=proposer)
    second, result = capture(engine, "We moved the deployment service to Atlas because Borealis was too slow.", hour=1, semantic_proposer=proposer)
    assert [call["clauses"][0]["cid"] for call in calls] == [first, second]
    assert result["unresolved"] == []
    assert engine.list_intentions("t") == []
    assert any(row["subject"] == "Atlas" and row["predicate"] == "runs" and row["object"] == "Debian" for row in rows(engine))
    assert any(row["predicate"] == "moved_to" and row["object"] == "Atlas" for row in rows(engine))
    reason = next(row for row in rows(engine) if row["predicate"] == "move_reason")
    assert reason["object"] == "Borealis was too slow"
    assert reason["calibration"]["event_time"]["status"] == "unspecified"


def _proposer(payload):
    span = payload["clauses"][0]
    return {"claims": [{"span": span, "subject": "API", "predicate": "authenticates_with", "object": "signed tokens",
                        "subject_quote": "Our API", "predicate_quote": "authenticates requests using", "object_quote": "signed tokens",
                        "epistemic_class": "inferred_proposal"}]}


def _reviewer(payload):
    return {"entailed": True, "preserves_negation": True, "preserves_time": True,
            "preserves_attribution": True, "no_added_detail": True,
            "support_spans": payload["source_spans"], "reason": "The authentication mechanism is explicit."}


def test_nonliteral_proposal_requires_a_separate_entailment_review(engine):
    cid, result = capture(engine, "Our API authenticates requests using signed tokens.", semantic_proposer=_proposer)
    assert result["pending_reviews"][0]["reason"] == "reviewer_unavailable"
    [pending] = rows(engine)
    assert pending["status"] == "quarantined"
    assert pending["calibration"]["entailment_review"]["reason"] == "reviewer_unavailable"
    result = reproject_direct_user_memory(engine, "t", cid, semantic_proposer=_proposer, semantic_reviewer=_reviewer)
    assert result["applied"]
    active = [row for row in rows(engine) if row["status"] == "active"]
    assert len(active) == 1
    assert active[0]["predicate"] == "authenticates_with"
    assert active[0]["calibration"]["proposal_validation"] == "independent_entailment_review"
    assert active[0]["source_evidence_cids"] == [cid]


def test_failed_review_is_reported_and_ordinary_projection_retry_admits_claim(engine):
    def unavailable(payload):
        raise TimeoutError("temporary failure")

    cid, first = capture(engine, "Our API authenticates requests using signed tokens.",
                         semantic_proposer=_proposer, semantic_reviewer=unavailable)
    assert first["pending_reviews"] == [{"reason": "review_failed", "method": "requires_entailment_review",
                                        "error_type": "TimeoutError"}]
    assert all(row["status"] == "quarantined" for row in rows(engine))
    second = project_direct_user_memory(engine, "t", cid, semantic_proposer=_proposer,
                                       semantic_reviewer=_reviewer)
    assert second["pending_reviews"] == []
    active = [row for row in rows(engine) if row["status"] == "active"]
    assert len(active) == 1
    assert active[0]["id"] in second["assertion_ids"]
    assert active[0]["source_evidence_cids"] == [cid]
    assert active[0]["calibration"]["entailment_review"]["entailed"] is True
    again = project_direct_user_memory(engine, "t", cid, semantic_proposer=_proposer,
                                      semantic_reviewer=_reviewer)
    assert again["created_count"] == 0
    assert again["assertion_ids"] == second["assertion_ids"]


@pytest.mark.parametrize("fault", ["false", "missing_check", "wrong_span", "invented_object", "negation"])
def test_reviewer_cannot_bypass_mechanical_claim_guards(engine, fault):
    def proposer(payload):
        result = _proposer(payload)
        if fault == "invented_object":
            result["claims"][0]["object"] = "passwords"
        return result
    def reviewer(payload):
        result = _reviewer(payload)
        if fault == "false":
            result["entailed"] = False
        if fault == "missing_check":
            result.pop("preserves_time")
        if fault == "wrong_span":
            result["support_spans"] = []
        return result
    text = "Our API authenticates requests using signed tokens."
    if fault == "negation":
        text = "Our API does not authenticate requests using signed tokens."
    capture(engine, text, semantic_proposer=proposer, semantic_reviewer=reviewer)
    assert not [row for row in rows(engine) if row["status"] == "active"]


def test_sqlite_reopen_preserves_named_alias_identity(tmp_path):
    path = tmp_path / "persistent"
    store = SqliteEngine(path)
    intro, _ = capture(store, "My server is Atlas.")
    rename, _ = capture(store, "I renamed Atlas to Orion.", hour=1)
    store.close()
    store = SqliteEngine(path)
    try:
        current, result = capture(store, "Orion runs Debian.", hour=30, session="new")
        [fact] = [row for row in rows(store) if row["id"] in result["assertion_ids"]]
        assert fact["subject"] == "Atlas"
        assert set(fact["source_evidence_cids"]) == {intro, rename, current}
    finally:
        store.close()


def test_alias_negation_withdraws_only_the_requested_name(engine):
    capture(engine, "My server is Atlas.")
    capture(engine, "I renamed Atlas to Orion.", hour=1)
    capture(engine, "Atlas is no longer called Orion.", hour=2)
    from mnemosyne.memory_formation import _semantic_context
    cid, _ = capture(engine, "continue", hour=3)
    context = _semantic_context(engine, engine.get_evidence("t", cid), engine.export_tenant("t"))
    assert "Orion" not in context["aliases"]
    assert context["aliases"]["Atlas"] == "Atlas"
    assert next(row for row in rows(engine) if row["predicate"] == "entity_alias")["status"] == "superseded"


def test_alias_contracted_negative_preserves_the_actual_predicate(engine):
    capture(engine, "My server is Atlas.")
    capture(engine, "I renamed Atlas to Orion.", hour=1)
    _, result = capture(engine, "Orion doesn’t use Redis.", hour=2)
    [fact] = [row for row in rows(engine) if row["id"] in result["assertion_ids"]]
    assert (fact["subject"], fact["predicate"], fact["object"]) == ("Atlas", "does_not_use", "Redis")
    assert fact["calibration"]["source_quote"] == "Orion doesn’t use Redis."


def test_owned_role_uses_one_canonical_scoped_projection(engine):
    capture(engine, "My deployment server is Atlas.")
    _, result = capture(engine, "My deployment server uses NATS.", hour=1)
    [fact] = [row for row in rows(engine) if row["id"] in result["assertion_ids"]]
    assert (fact["subject"], fact["predicate"], fact["object"]) == ("Atlas", "uses", "NATS")
    assert fact["scope"] == {"entity_scope": {"workspace": "/work/project"}}


def test_pronoun_retains_the_evidence_that_disambiguated_two_entities(engine):
    intro, _ = capture(engine, "I have two servers: Atlas and Borealis.")
    focus, _ = capture(engine, "Atlas runs Debian.", hour=1)
    current, result = capture(engine, "It uses NATS.", hour=2)
    [fact] = [row for row in rows(engine) if row["id"] in result["assertion_ids"]]
    assert set(fact["source_evidence_cids"]) == {intro, focus, current}
    engine.forget("t", focus)
    assert not [row for row in rows(engine) if row["id"] == fact["id"] and row["status"] == "active"]
