"""Restricted-role entity erasure must also remove its derived aliases."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine, _stable_uuid


@pytest.fixture
def entity_engine():
    pytest.importorskip("psycopg")
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    engine = PostgresEngine(dsn)
    try:
        yield engine
    finally:
        engine.close_connections()


def seed_entity(engine):
    tenant = f"entity-erasure-{uuid4().hex}"
    cid = engine.append_evidence(Evidence(
        tenant_id=tenant, user_id="owner", actor="user", source_type="document",
        content="A named entity derived from this removable source.",
    ))
    canonical = f"entity-{uuid4().hex}"
    engine.register_entity(
        tenant, canonical, alias="Removable Alias", source_evidence_cids=[cid],
        access_policy={"tenant": tenant},
    )
    return tenant, cid, canonical


def alias_count(engine, tenant):
    with engine.connect() as conn:
        with conn.cursor() as cur:
            engine._set_tenant(cur, _stable_uuid("tenant", tenant))
            cur.execute("SELECT count(*) FROM entity_aliases WHERE tenant_id = %s",
                        (_stable_uuid("tenant", tenant),))
            return cur.fetchone()[0]


@pytest.mark.parametrize("mode", ["tombstone_recompute", "hard_delete_legal"])
def test_entity_erasure_cascades_aliases_with_restricted_consolidator(entity_engine, mode):
    engine = entity_engine
    tenant, cid, canonical = seed_entity(engine)
    assert alias_count(engine, tenant) == 2  # canonical name and explicit alias
    result = engine.forget(tenant, cid, requested_by="legal", erasure_mode=mode)
    assert result["erased"] is True
    assert canonical in result["propagated"]["removed_entities"]
    assert engine.get_evidence(tenant, cid) is None
    assert all(row["canonical"] != canonical for row in engine.export_tenant(tenant)["entities"])
    assert alias_count(engine, tenant) == 0


def test_alias_owner_grant_stays_tenant_scoped_and_preserves_protected_tables(entity_engine):
    engine = entity_engine
    app_dsn = os.environ.get("MNEMOSYNE_POSTGRES_APP_DSN")
    if not app_dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_APP_DSN is not set")
    tenant, _, _ = seed_entity(engine)
    other_tenant, _, _ = seed_entity(engine)
    with engine._psycopg.connect(app_dsn) as conn:
        conn.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)",
                     (str(_stable_uuid("tenant", tenant)),))
        assert conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone() == (False, False)
        assert conn.execute("DELETE FROM entity_aliases WHERE tenant_id = %s",
                            (_stable_uuid("tenant", other_tenant),)).rowcount == 0
        assert conn.execute("DELETE FROM entity_aliases WHERE tenant_id = %s",
                            (_stable_uuid("tenant", tenant),)).rowcount == 2
        for table in ("entities", "evidence", "branches", "audit_log"):
            with pytest.raises(engine._psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(f"DELETE FROM {table} WHERE false")
    assert alias_count(engine, tenant) == 0
    assert alias_count(engine, other_tenant) == 2


def test_readonly_role_cannot_delete_aliases(entity_engine):
    engine = entity_engine
    readonly_dsn = os.environ.get("MNEMOSYNE_POSTGRES_READONLY_DSN")
    if not readonly_dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_READONLY_DSN is not set")
    tenant, _, _ = seed_entity(engine)
    with engine._psycopg.connect(readonly_dsn) as conn:
        conn.execute("SELECT set_config('mnemosyne.tenant_id', %s, true)",
                     (str(_stable_uuid("tenant", tenant)),))
        with pytest.raises(engine._psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("DELETE FROM entity_aliases WHERE tenant_id = %s",
                             (_stable_uuid("tenant", tenant),))
    assert alias_count(engine, tenant) == 2
