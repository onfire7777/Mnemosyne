"""Synthetic regressions that enter the bridge path and inspect its returned evidence."""
from __future__ import annotations

import sys
from datetime import UTC, datetime

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.policy import OperatingPolicy

QUERY = "Who leads Project Apollo's team?"
SEED = "Project Apollo is assigned to the Vega team."
ANSWER = "Vega team is led by Morgan."


def _append(engine, text, source_type="doc", **kwargs):
    values = dict(tenant_id="t", user_id="u", actor="user", source_type=source_type,
                  content=text, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    values.update(kwargs)
    return engine.append_evidence(Evidence(**values), values.get("branch", "main"))


@pytest.mark.parametrize("source_type", ["doc", "session:chat"])
@pytest.mark.parametrize("explicit", [False, True])
def test_bridge_returns_both_link_and_answer_with_two_hit_budget(source_type, explicit, monkeypatch):
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=2))
    _append(engine, SEED, source_type)
    _append(engine, ANSWER, source_type)
    _append(engine, "Project Apollo is operational.", source_type)
    query = "Project Apollo" if explicit else QUERY
    filt = {"multi_hop": True} if explicit else {}
    normal = engine.retrieve(query, "t", record_access=False, filt=filt)
    monkeypatch.setattr(sys, "argv", ["mneme", "--evaluation-read-only"])
    evaluation = engine.retrieve(query, "t", record_access=False, filt=filt)
    assert [(h.id, h.score) for h in normal.hits] == [(h.id, h.score) for h in evaluation.hits]
    assert [h.text for h in normal.hits] == [SEED, ANSWER]
    assert all(h.metadata["score_scale"] == "reciprocal_rank" for h in normal.hits)
    assert normal.explain["source_only_local_fallback"]["score_scale"] == "reciprocal_rank"
    assert normal.explain["bridge_expansion"]["applied"]


def test_real_bridge_route_preserves_tenant_branch_acl_and_sensitivity_boundaries():
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=8))
    engine.branch("private", "main", tenant_id="t")
    _append(engine, SEED)
    _append(engine, ANSWER)
    _append(engine, "Vega team private tenant secret.", tenant_id="other")
    _append(engine, "Vega team private branch secret.", branch="private")
    _append(engine, "Vega team private sensitive secret.", sensitivity=3)
    _append(engine, "Vega team private owner secret.", access_policy={"allow_principals": ["user:other"]})
    result = engine.retrieve(QUERY, "t", record_access=False, filt={"user_id": "u", "max_sensitivity": 0})
    assert result.explain["bridge_expansion"]["applied"]
    assert all("secret" not in h.text for h in result.hits)
    assert ANSWER in [h.text for h in result.hits]


def test_single_hit_budget_does_not_spend_calls_on_unreturnable_bridges(monkeypatch):
    engine = LocalMemoryEngine(policy=OperatingPolicy(top_k=1))
    _append(engine, SEED)
    _append(engine, ANSWER)
    original = engine.lexical_search
    calls = []
    def lexical(query, *args, **kwargs):
        calls.append(query)
        return original(query, *args, **kwargs)
    monkeypatch.setattr(engine, "lexical_search", lexical)
    result = engine.retrieve(QUERY, "t", record_access=False)
    assert "bridge_expansion" not in result.explain
    assert "Vega" not in calls


@pytest.mark.parametrize('backend', ['sqlite', 'postgres'])
def test_native_backend_bridge_and_timestamp_privacy(backend, tmp_path):
    import json
    import os
    from uuid import uuid4
    from mnemosyne.sqlite_engine import SqliteEngine
    from mnemosyne.postgres_engine import PostgresEngine

    if backend == 'postgres':
        dsn = os.environ.get('MNEMOSYNE_POSTGRES_DSN')
        if not dsn:
            pytest.skip('disposable PostgreSQL DSN not configured')
        engine = PostgresEngine(dsn, policy=OperatingPolicy(top_k=2))
    else:
        engine = SqliteEngine(tmp_path / 'bridge.sqlite', policy=OperatingPolicy(top_k=2))
    tenant = f'bridge-{uuid4().hex}'
    try:
        _append(engine, SEED, tenant_id=tenant)
        _append(engine, ANSWER, tenant_id=tenant)
        _append(engine, 'Project Apollo is operational.', tenant_id=tenant)
        result = engine.retrieve(QUERY, tenant, record_access=False)
        assert result.explain['bridge_expansion']['applied']
        assert [hit.text for hit in result.hits] == [SEED, ANSWER]
        private = f'private-{uuid4().hex}'
        _append(engine, 'launch code: Secret123', tenant_id=private,
                metadata={'event_start': 'Secret123'},
                access_policy={'redact_fields': ['code'], 'min_role_for_raw': 'operator'})
        hits = engine.lexical_search('launch', 5, {'tenant_id': private, 'query_mode': 'passages'})
        serialized = json.dumps([hit.to_dict() for hit in hits], allow_nan=False)
        assert hits and 'Secret123' not in serialized
    finally:
        if backend == 'postgres':
            engine.close_connections()
        else:
            engine.close()
