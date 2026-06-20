from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

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

    result = engine.forget(tenant, erased_cid, requested_by=user, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    exported = engine.export_tenant(tenant)
    assertion = next(item for item in exported["assertions"] if item["id"] == assertion_id)
    preference = next(item for item in exported["preferences"] if item["id"] == preference_id)
    relation = next(item for item in exported["relations"] if item["id"] == relation_id)

    assert result["erased"] is True
    assert assertion["source_evidence_cids"] == [surviving_cid]
    assert assertion_id in result["propagated"]["trimmed_assertions"]
    assert preference["status"] == "retracted"
    assert preference["source_evidence_cids"] == []
    assert preference_id in result["propagated"]["retracted_preferences"]
    assert relation["valid_to"] is not None
    assert relation["source_evidence_cids"] == []
    assert relation_id in result["propagated"]["expired_relations"]
    assert all(item["cid"] != erased_cid for item in exported["evidence"])


def _append_evidence(engine: Any, tenant: str, user: str, content: str) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="shared-contract",
            content=content,
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )


def _branch(engine: Any, name: str, tenant: str) -> None:
    try:
        engine.branch(name, tenant_id=tenant)
    except TypeError:
        engine.branch(name)


def _discard(engine: Any, name: str, tenant: str) -> None:
    try:
        engine.discard(name, tenant_id=tenant)
    except TypeError:
        engine.discard(name)
