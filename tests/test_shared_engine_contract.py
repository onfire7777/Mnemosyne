from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.calibration import CalibrationSet
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence, Preference, Relation
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.privacy import ErasureMode


def _live_dsn() -> str | None:
    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


@pytest.fixture(params=["local", "postgres"])
def engine_bundle(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, str, str]:
    tenant = f"tenant-shared-{request.param}-{uuid4()}"
    user = f"user-shared-{request.param}"
    if request.param == "local":
        return LocalMemoryEngine(), tenant, user
    dsn = _live_dsn()
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    pytest.importorskip("psycopg")
    return PostgresEngine(dsn), tenant, user


def test_shared_engine_contract_retrieves_and_exports_evidence(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Shared engine contract stores the orchid retrieval fact.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    recalled = engine.get_evidence(tenant, cid)
    retrieved = engine.retrieve("orchid retrieval fact", tenant)
    exported = engine.export_tenant(tenant)

    assert recalled is not None
    assert recalled.content == "Shared engine contract stores the orchid retrieval fact."
    assert any(hit.id == cid for hit in retrieved.hits)
    assert any(item["cid"] == cid for item in exported["evidence"])


def test_shared_engine_contract_explain_reports_channels_rails_and_provenance(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Shared explain contract records sapphire provenance and retrieval rails.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    explained = engine.explain("sapphire provenance retrieval rails", tenant)
    explain = explained["explain"]

    assert explained["abstained"] is False
    assert explained["confidence"] > 0
    assert explain["channels"]
    assert sum(int(value) for value in explain["channels"].values()) >= 1
    assert explain["rails"]["tenant_isolation_required"] is True
    assert explain["rails"]["retrieved_text_is_data_not_instruction"] is True
    assert any(hit["id"] == cid and cid in hit["provenance"] for hit in explained["hits"])


def test_shared_engine_contract_retrieval_records_assertion_access_and_activation(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(engine, tenant, user, "Shared activation evidence backs retrieval telemetry.")
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="Shared activation",
            predicate="requires",
            object="read telemetry",
            confidence=0.95,
            source_evidence_cids=[cid],
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    before = _exported_assertion(engine, tenant, assertion_id)

    result = engine.retrieve("Shared activation requires read telemetry", tenant)
    after = _exported_assertion(engine, tenant, assertion_id)
    assertion_hit = next(hit for hit in result.hits if hit.kind == "assertion" and hit.id == assertion_id)

    assert before["access_count"] == 0
    assert after["access_count"] == 1
    assert after["last_accessed"]
    assert assertion_hit.metadata["activation"]["score"] > 0
    assert result.explain["activation"]["applied"] is True
    assert result.explain["read_marks"]["assertions"] >= 1


def test_shared_engine_contract_retrieval_uses_conformal_calibration(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    engine.set_calibration(
        CalibrationSet(
            tenant_id=tenant,
            memory_type="fact",
            scores=[0.95],
            target_coverage=0.9,
        )
    )
    _append_evidence(engine, tenant, user, "Shared calibrated abstention contract should retrieve evidence.")

    result = engine.retrieve("calibrated abstention contract", tenant)
    exported = engine.export_tenant(tenant)

    assert result.hits
    assert result.abstained is True
    assert result.uncertainty_note
    assert result.explain["calibration"]["source"] == "conformal"
    assert result.explain["calibration"]["threshold"] == 0.95
    assert result.explain["semantic_entropy"] >= 0.0
    assert exported["calibrations"][0]["memory_type"] == "fact"


def test_shared_engine_contract_direct_search_primitives(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(
        engine,
        tenant,
        user,
        "Shared primitive search contract stores the garnet needle evidence.",
    )
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="Shared primitive search",
            predicate="finds",
            object="garnet needle",
            confidence=0.92,
            source_evidence_cids=[cid],
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="shared primitive seed",
            predicate="points_to",
            target="primitive target",
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )
    filt = {"tenant_id": tenant, "branch": "main", "max_trust_tier": 3, "max_sensitivity": 2}

    lexical = engine.lexical_search("garnet needle", 10, filt)
    dense = engine.vector_search("garnet needle", 10, filt)
    graph = engine.graph_ppr(["shared primitive seed"], 5, tenant_id=tenant, branch="main")

    assert {cid, assertion_id} & {hit.id for hit in lexical}
    assert {cid, assertion_id} & {hit.id for hit in dense}
    assert relation_id in {hit.id for hit in graph}
    assert all(hit.tenant_id == tenant for hit in [*lexical, *dense, *graph])
    assert all(hit.branch == "main" for hit in [*lexical, *dense, *graph])


def test_shared_engine_contract_registers_entity_registry(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(engine, tenant, user, "Shared entity registry evidence.")

    entity = engine.register_entity(
        tenant,
        "shared-entity",
        alias="Shared Entity",
        summary="Shared Entity has durable registry state.",
        source_evidence_cids=[cid],
        access_policy={"tenant": tenant},
    )
    exported = engine.export_tenant(tenant)["entities"]

    assert entity["canonical"] == "shared-entity"
    assert "Shared Entity" in entity["aliases"]
    assert exported[0]["canonical"] == "shared-entity"
    assert exported[0]["source_evidence_cids"] == [cid]
    assert exported[0]["access_policy"]["tenant"] == tenant


def test_shared_engine_contract_branches_and_discards(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    _branch(engine, "candidate", tenant)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Candidate branch shared contract fact.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch="candidate",
    )

    assert engine.get_evidence(tenant, cid, branch="candidate") is not None
    assert engine.get_evidence(tenant, cid, branch="main") is None

    _discard(engine, "candidate", tenant)

    assert engine.get_evidence(tenant, cid, branch="candidate") is None


def test_shared_engine_contract_bitemporal_assertion_as_of(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    now = datetime.now(UTC)
    first_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Shared bitemporal preference starts as alpha.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    second_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Shared bitemporal preference changes to beta.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    subject = f"shared-user-{uuid4()}"
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=subject,
            predicate="prefers",
            object="alpha",
            confidence=0.9,
            valid_from=now,
            source_evidence_cids=[first_cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=subject,
            predicate="prefers",
            object="beta",
            confidence=0.92,
            valid_from=now + timedelta(minutes=5),
            source_evidence_cids=[second_cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    past = engine.as_of(subject, "prefers", now + timedelta(minutes=1), tenant_id=tenant)
    current = engine.as_of(subject, "prefers", now + timedelta(minutes=10), tenant_id=tenant)

    assert [item.object for item in past] == ["alpha"]
    assert [item.object for item in current] == ["beta"]


def test_shared_engine_contract_exports_relations_and_preferences(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(
        engine,
        tenant,
        user,
        "Shared graph contract links source alpha to target beta.",
    )
    relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="shared source alpha",
            predicate="connects_to",
            target="shared target beta",
            confidence=0.91,
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        )
    )
    preference_id = engine.add_preference(
        Preference(
            tenant_id=tenant,
            user_id=user,
            category="workflow",
            statement="Prefer shared contract parity checks.",
            explicit=True,
            confidence=0.94,
            source_evidence_cids=[cid],
        )
    )

    exported = engine.export_tenant(tenant)

    assert any(item["id"] == relation_id and item["source_evidence_cids"] == [cid] for item in exported["relations"])
    assert any(item["id"] == preference_id and item["source_evidence_cids"] == [cid] for item in exported["preferences"])


def test_shared_engine_contract_correct_adds_evidence_backed_assertion(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    subject = f"shared correction subject {uuid4()}"

    assertion_id = engine.correct(
        tenant,
        user,
        subject,
        "prefers",
        "corrected answer",
        "Shared correction contract evidence.",
    )
    exported = engine.export_tenant(tenant)
    assertion = next(item for item in exported["assertions"] if item["id"] == assertion_id)
    correction_evidence = [
        item
        for item in exported["evidence"]
        if item["source_type"] == "correction" and item["content"] == "Shared correction contract evidence."
    ]

    assert assertion["status"] == "active"
    assert assertion["object"] == "corrected answer"
    assert assertion["source_evidence_cids"] == [correction_evidence[0]["cid"]]


def test_shared_engine_contract_forget_propagates_projection_erasure(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    erased_cid = _append_evidence(engine, tenant, user, "Shared erasure source that must be removed.")
    surviving_cid = _append_evidence(engine, tenant, user, "Shared erasure source that must survive.")
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=f"shared erasure subject {uuid4()}",
            predicate="keeps",
            object="surviving source only",
            confidence=0.9,
            source_evidence_cids=[erased_cid, surviving_cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    preference_id = engine.add_preference(
        Preference(
            tenant_id=tenant,
            user_id=user,
            category="workflow",
            statement="Forget propagation retracts unbacked preferences.",
            explicit=True,
            source_evidence_cids=[erased_cid],
        )
    )
    relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="shared erasure source",
            predicate="supports",
            target="shared erasure target",
            source_evidence_cids=[erased_cid],
            access_policy={"tenant": tenant},
        )
    )
    entity_canonical = f"shared-erasure-entity-{uuid4()}"
    engine.register_entity(
        tenant,
        entity_canonical,
        alias="Shared Erasure Entity",
        source_evidence_cids=[erased_cid, surviving_cid],
        access_policy={"tenant": tenant},
    )

    result = engine.forget(tenant, erased_cid, requested_by=user, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    exported = engine.export_tenant(tenant)
    assertion = next(item for item in exported["assertions"] if item["id"] == assertion_id)
    preference = next(item for item in exported["preferences"] if item["id"] == preference_id)
    relation = next(item for item in exported["relations"] if item["id"] == relation_id)
    entity = next(item for item in exported["entities"] if item["canonical"] == entity_canonical)

    assert result["erased"] is True
    assert assertion["source_evidence_cids"] == [surviving_cid]
    assert assertion_id in result["propagated"]["trimmed_assertions"]
    assert preference["status"] == "retracted"
    assert preference["source_evidence_cids"] == []
    assert preference_id in result["propagated"]["retracted_preferences"]
    assert relation["valid_to"] is not None
    assert relation["source_evidence_cids"] == []
    assert relation_id in result["propagated"]["expired_relations"]
    assert entity["source_evidence_cids"] == [surviving_cid]
    assert entity_canonical in result["propagated"]["trimmed_entities"]
    assert all(item["cid"] != erased_cid for item in exported["evidence"])

    removal = engine.forget(tenant, surviving_cid, requested_by=user, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    exported_after_removal = engine.export_tenant(tenant)

    assert entity_canonical in removal["propagated"]["removed_entities"]
    assert all(item["canonical"] != entity_canonical for item in exported_after_removal["entities"])


def test_shared_engine_contract_retrieval_filters_trust_sensitivity_and_quarantine(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    trusted_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Shared filter contract keeps trusted visible evidence.",
        trust_tier=0,
        sensitivity=0,
    )
    low_trust_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Shared filter contract hides low trust evidence.",
        trust_tier=5,
        sensitivity=0,
    )
    sensitive_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Shared filter contract hides sensitive evidence.",
        trust_tier=0,
        sensitivity=5,
    )
    quarantined_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Shared filter contract hides quarantined evidence.",
        trust_tier=0,
        sensitivity=0,
        metadata={"quarantine_reason": "untrusted-manifest"},
    )

    filtered = engine.retrieve(
        "Shared filter contract evidence",
        tenant,
        filt={"max_trust_tier": 3, "max_sensitivity": 2},
    )
    include_quarantined = engine.retrieve(
        "Shared filter contract quarantined evidence",
        tenant,
        filt={"max_trust_tier": 3, "max_sensitivity": 2, "include_quarantined": True},
    )

    filtered_ids = {hit.id for hit in filtered.hits}
    quarantine_ids = {hit.id for hit in include_quarantined.hits}
    assert trusted_cid in filtered_ids
    assert low_trust_cid not in filtered_ids
    assert sensitive_cid not in filtered_ids
    assert quarantined_cid not in filtered_ids
    assert quarantined_cid in quarantine_ids


def test_shared_engine_contract_merges_branch_evidence_assertions_and_relations(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    branch = f"shared-merge-{uuid4()}"
    _branch(engine, branch, tenant)
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="shared-contract",
            content="Shared merge contract moves branch-only evidence.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=f"shared merge subject {uuid4()}",
            predicate="moves",
            object="branch projection",
            confidence=0.9,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )
    relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="shared merge source",
            predicate="moves_to",
            target="shared merge target",
            branch=branch,
            source_evidence_cids=[cid],
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )

    before = engine.retrieve("Shared merge contract branch-only evidence", tenant)
    report = _merge(engine, branch, tenant)
    after = engine.retrieve("Shared merge contract branch-only evidence", tenant)
    exported = engine.export_tenant(tenant)

    assert cid not in {hit.id for hit in before.hits}
    assert cid in {hit.id for hit in after.hits}
    assert report.evidence_added >= 1
    assert report.assertions_added >= 1
    assert report.relations_added >= 1
    assert any(item["cid"] == cid and item["branch"] == "main" for item in exported["evidence"])
    assert any(item["id"] == assertion_id and item["branch"] == "main" for item in exported["assertions"])
    assert any(item["id"] == relation_id and item["branch"] == "main" for item in exported["relations"])


def test_shared_engine_contract_deep_graph_respects_tenant_and_branch(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    other_tenant = f"{tenant}-other"
    branch = f"shared-graph-{uuid4()}"
    main_cid = _append_evidence(engine, tenant, user, "Shared graph isolation main evidence.")
    other_cid = _append_evidence(engine, other_tenant, user, "Shared graph isolation other tenant evidence.")
    _branch(engine, branch, tenant)
    branch_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="shared-contract",
            content="Shared graph isolation branch evidence.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )
    main_relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="shared graph seed",
            predicate="links",
            target="main-only target",
            source_evidence_cids=[main_cid],
            access_policy={"tenant": tenant},
        )
    )
    other_relation_id = engine.add_relation(
        Relation(
            tenant_id=other_tenant,
            source="shared graph seed",
            predicate="links",
            target="other-tenant target",
            source_evidence_cids=[other_cid],
            access_policy={"tenant": other_tenant},
        )
    )
    branch_relation_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source="shared graph seed",
            predicate="links",
            target="branch-only target",
            branch=branch,
            source_evidence_cids=[branch_cid],
            access_policy={"tenant": tenant},
        ),
        branch=branch,
    )

    main = engine.deep_search("shared graph seed", tenant)
    branch_result = engine.deep_search("shared graph seed", tenant, branch=branch)

    assert main_relation_id in {hit.id for hit in main.hits}
    assert other_relation_id not in {hit.id for hit in main.hits}
    assert branch_relation_id not in {hit.id for hit in main.hits}
    assert branch_relation_id in {hit.id for hit in branch_result.hits}


def test_shared_engine_contract_hard_delete_records_audit_and_deletion_log(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(engine, tenant, user, "Shared hard-delete contract evidence.")

    result = engine.forget(tenant, cid, requested_by=user, erasure_mode=ErasureMode.HARD_DELETE_LEGAL)
    exported = engine.export_tenant(tenant)

    assert result["erased"] is True
    assert result["erasure_mode"] == "hard_delete_legal"
    assert engine.get_evidence(tenant, cid) is None
    assert all(item["cid"] != cid for item in exported["evidence"])
    assert any(
        item["evidence_cid"] == cid
        and (item.get("erasure_mode") or item.get("propagated", {}).get("erasure_mode")) == "hard_delete_legal"
        for item in exported["deletion_log"]
    )
    assert any(item["op"] == "forget" and item["target_id"] == cid for item in exported["audit_log"])


def _append_evidence(
    engine: Any,
    tenant: str,
    user: str,
    content: str,
    *,
    trust_tier: int = 0,
    sensitivity: int = 0,
    metadata: dict[str, Any] | None = None,
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="shared-contract",
            content=content,
            metadata=metadata or {},
            trust_tier=trust_tier,
            sensitivity=sensitivity,
            access_policy={"tenant": tenant},
        )
    )


def _exported_assertion(engine: Any, tenant: str, assertion_id: str) -> dict[str, Any]:
    for assertion in engine.export_tenant(tenant)["assertions"]:
        if assertion["id"] == assertion_id:
            return assertion
    raise AssertionError(f"missing exported assertion {assertion_id}")


def _branch(engine: Any, name: str, tenant: str) -> None:
    try:
        engine.branch(name, tenant_id=tenant)
    except TypeError:
        engine.branch(name)


def _merge(engine: Any, name: str, tenant: str) -> Any:
    try:
        return engine.merge(name, tenant_id=tenant)
    except TypeError:
        return engine.merge(name)


def _discard(engine: Any, name: str, tenant: str) -> None:
    try:
        engine.discard(name, tenant_id=tenant)
    except TypeError:
        engine.discard(name)
