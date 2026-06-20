from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.postgres_engine import PostgresEngine


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
