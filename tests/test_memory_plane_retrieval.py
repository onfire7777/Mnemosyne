from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mnemosyne import pipeline as pipeline_mod
from mnemosyne import retrieval as retrieval_mod
from mnemosyne.engine import Intention, LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.retrieval import prospective_memory_hits, working_memory_route_hits
from mnemosyne.sqlite_engine import SqliteEngine


TENANT = "tenant-memory-planes"
USER = "user-memory-planes"
AGENT = "agent-memory-planes"
SESSION = "session-memory-planes"
NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _engine() -> LocalMemoryEngine:
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="test",
            session_id=SESSION,
            content="Submit the Helios release review today.",
            access_policy={"tenant": TENANT},
        )
    )
    engine.schedule_intention(
        Intention(
            intention_id="shared-id",
            tenant_id=TENANT,
            user_id=USER,
            agent_id=AGENT,
            trigger_type="exact_time",
            trigger_expression={"at": (NOW - timedelta(minutes=1)).isoformat()},
            action={"summary": "Submit the Helios release review today."},
            due_at=NOW - timedelta(minutes=1),
            evidence_ids=[cid],
        )
    )
    return engine


def _working_item(**overrides: object) -> SimpleNamespace:
    values = {
        "item_id": "shared-id",
        "tenant_id": TENANT,
        "session_id": SESSION,
        "user_id": USER,
        "agent_id": AGENT,
        "kind": "active_goal",
        "task_id": "task-1",
        "content": "Review the Helios release submission today.",
        "created_at": NOW - timedelta(minutes=10),
        "expires_at": NOW + timedelta(minutes=10),
        "evidence_ids": ["cid-working"],
        "trust_tier": 1,
        "sensitivity": 0,
        "status": "active",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _install_working(monkeypatch: pytest.MonkeyPatch, engine: LocalMemoryEngine, items: list[object]) -> None:
    def list_working(
        self: LocalMemoryEngine, tenant_id: str, session_id: str, *, as_of: datetime
    ) -> list[object]:
        assert self is engine
        assert tenant_id == TENANT
        assert session_id == SESSION
        assert as_of == NOW
        return items

    monkeypatch.setattr(LocalMemoryEngine, "list_working", list_working, raising=False)


def _filter() -> dict[str, object]:
    return {
        "as_of": NOW,
        "user_id": USER,
        "agent_id": AGENT,
        "role": "agent",
        "prospective_owner": {"user_id": USER, "agent_id": AGENT},
        "working_session_id": SESSION,
    }


def _working_hits(
    engine: LocalMemoryEngine,
    query: str,
    limit: int,
    filt: dict[str, object],
) -> list[object]:
    session_id = filt.get("working_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return []
    items = engine.list_working(TENANT, session_id, as_of=NOW)
    return working_memory_route_hits(
        items,
        query=query,
        tenant_id=TENANT,
        session_id=session_id,
        evaluated_at=NOW,
        branch="main",
        limit=limit,
        access_context={"tenant_id": TENANT, **filt},
        policy_max_sensitivity=engine.policy.max_sensitivity,
        max_trust_tier=engine.policy.max_trust_tier,
    )


def test_plane_helpers_require_explicit_owner_and_session_context() -> None:
    engine = _engine()
    base = {"tenant_id": TENANT, "branch": "main"}
    assert prospective_memory_hits(engine, "Helios", 8, base, as_of=NOW) == []
    assert _working_hits(engine, "Helios", 8, base) == []


def test_plane_helpers_preserve_shape_provenance_and_collision_free_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    _install_working(monkeypatch, engine, [_working_item()])
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}

    prospective = prospective_memory_hits(engine, "Helios review", 8, filt, as_of=NOW)
    working = _working_hits(engine, "Helios review", 8, filt)

    assert prospective[0].kind == "intention"
    assert working[0].kind == "working"
    assert prospective[0].channel == "prospective_memory"
    assert working[0].channel == "working_memory"
    assert prospective[0].id == working[0].id == "shared-id"
    assert prospective[0].metadata["memory_plane"] == "prospective_memory"
    assert prospective[0].metadata["intention_id"] == "shared-id"
    assert working[0].metadata["memory_plane"] == "working_memory"
    assert working[0].metadata["working_memory_id"] == "shared-id"
    assert prospective[0].provenance
    assert working[0].provenance == ["cid-working"]


def test_prospective_owner_selector_must_match_access_principal() -> None:
    engine = _engine()
    filt = {"tenant_id": TENANT, "branch": "main", **_filter(), "user_id": "attacker"}
    assert prospective_memory_hits(engine, "Helios", 8, filt, as_of=NOW) == []


def test_prospective_provenance_is_hydrated_and_access_checked() -> None:
    engine = _engine()
    intention = engine.list_intentions(TENANT)[0]
    cid = intention.evidence_ids[0]
    evidence = engine.get_evidence(TENANT, cid)
    assert evidence is not None
    evidence.access_policy = {"tenant": TENANT, "restricted": True}
    engine.evidence[engine._evidence_key(TENANT, "main", cid)] = evidence
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}
    assert prospective_memory_hits(engine, "Helios", 8, filt, as_of=NOW) == []


def test_prospective_provenance_preserves_trust_and_capability_rails() -> None:
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}
    for mutate in (
        lambda evidence, engine: setattr(
            evidence, "trust_tier", engine.policy.max_trust_tier + 1
        ),
        lambda evidence, _engine: evidence.access_policy.update(
            {"require_capabilities": ["release-approver"]}
        ),
    ):
        engine = _engine()
        cid = engine.list_intentions(TENANT)[0].evidence_ids[0]
        evidence = engine.get_evidence(TENANT, cid)
        assert evidence is not None
        mutate(evidence, engine)
        engine.evidence[engine._evidence_key(TENANT, "main", cid)] = evidence
        assert prospective_memory_hits(engine, "Helios", 8, filt, as_of=NOW) == []


def test_prospective_action_applies_originating_evidence_redactions() -> None:
    engine = _engine()
    intention = engine.list_intentions(TENANT)[0]
    intention.action = {"summary": "Submit secret launch details."}
    engine.intentions[(TENANT, intention.intention_id)] = intention
    cid = intention.evidence_ids[0]
    evidence = engine.get_evidence(TENANT, cid)
    assert evidence is not None
    evidence.access_policy = {
        "tenant": TENANT,
        "redact_fields": ["summary"],
        "min_role_for_raw": "operator",
    }
    engine.evidence[engine._evidence_key(TENANT, "main", cid)] = evidence
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}
    hits = prospective_memory_hits(engine, "launch", 8, filt, as_of=NOW)
    assert len(hits) == 1
    assert "secret launch details" not in hits[0].text
    assert "[REDACTED:summary]" in hits[0].text


def test_prospective_uses_worst_source_trust_and_omits_empty_privacy_rows() -> None:
    engine = _engine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="tool",
            source_type="test",
            content="Second provenance source.",
            trust_tier=2,
            access_policy={"tenant": TENANT},
        )
    )
    intention = engine.list_intentions(TENANT)[0]
    intention.evidence_ids.append(cid)
    engine.intentions[(TENANT, intention.intention_id)] = intention
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}

    hit = prospective_memory_hits(engine, "Helios", 8, filt, as_of=NOW)[0]

    assert hit.trust_tier == 2
    assert hit.metadata["privacy"] == []


def test_prospective_fails_closed_if_redaction_produces_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    monkeypatch.setattr(retrieval_mod, "apply_text_redactions", lambda *args: ("", {}))
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}
    assert prospective_memory_hits(engine, "Helios", 8, filt, as_of=NOW) == []


@pytest.mark.parametrize("backend", [LocalMemoryEngine, SqliteEngine, PostgresEngine])
def test_all_finalized_backends_expose_prospective_read_protocol(backend: type[object]) -> None:
    assert callable(getattr(backend, "list_intentions", None))
    assert callable(getattr(backend, "get_evidence", None))


def test_owner_session_due_and_ttl_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    future = copy.deepcopy(engine.list_intentions(TENANT)[0])
    future.intention_id = "future"
    future.due_at = NOW + timedelta(minutes=1)
    future.trigger_expression = {"at": future.due_at.isoformat()}
    other_owner = copy.deepcopy(engine.list_intentions(TENANT)[0])
    other_owner.intention_id = "other-owner"
    other_owner.user_id = "other-user"
    monkeypatch.setattr(engine, "list_intentions", lambda tenant_id: [future, other_owner])
    _install_working(
        monkeypatch,
        engine,
        [
            _working_item(item_id="expired", expires_at=NOW),
            _working_item(item_id="future", created_at=NOW + timedelta(seconds=1)),
            _working_item(item_id="other-session", session_id="other-session"),
        ],
    )
    filt = {"tenant_id": TENANT, "branch": "main", **_filter()}

    assert prospective_memory_hits(engine, "Helios", 8, filt, as_of=NOW) == []
    assert _working_hits(engine, "Helios", 8, filt) == []


@pytest.mark.parametrize("parallel", ["0", "1"])
def test_pipeline_runs_five_routes_in_stable_order_and_sanitizes_plane_text(
    monkeypatch: pytest.MonkeyPatch, parallel: str
) -> None:
    engine = _engine()
    _install_working(monkeypatch, engine, [_working_item()])
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", parallel)
    seen: list[list[str]] = []
    original = LocalMemoryEngine._rrf

    def recording_rrf(self: LocalMemoryEngine, routes: list[list[object]], k: int) -> list[object]:
        seen.append([route[0].channel if route else "empty" for route in routes])
        return original(self, routes, k)

    monkeypatch.setattr(LocalMemoryEngine, "_rrf", recording_rrf)
    result = engine.retrieve("Helios release review", TENANT, filt=_filter(), record_access=False)

    assert seen == [["dense_hash", "lexical", "empty", "prospective_memory", "working_memory"]]
    assert list(result.explain["channels"])[-2:] == ["prospective_memory", "working_memory"]
    assert [row["channel"] for row in result.explain["routes"]] == [
        "dense_hash",
        "lexical",
        "graph_ppr",
        "prospective_memory",
        "working_memory",
    ]
    plane_hits = [hit for hit in result.hits if hit.metadata.get("memory_plane")]
    assert plane_hits
    assert all("retrieved_text" in hit.metadata for hit in plane_hits)
    assert result.used_tokens <= result.token_budget


def test_pipeline_reports_stable_routes_without_widening_legacy_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()

    result = engine.retrieve("unmatched", TENANT, filt={}, record_access=False)

    assert "prospective_memory" not in result.explain["channels"]
    assert "working_memory" not in result.explain["channels"]
    assert "routes" not in result.explain

    intention = engine.list_intentions(TENANT)[0]
    intention.due_at = NOW + timedelta(minutes=1)
    engine.intentions[(TENANT, intention.intention_id)] = intention
    _install_working(monkeypatch, engine, [])
    requested_empty = engine.retrieve("unmatched", TENANT, filt=_filter(), record_access=False)
    assert requested_empty.explain["channels"]["prospective_memory"] == 0
    assert requested_empty.explain["channels"]["working_memory"] == 0
    assert requested_empty.explain["routes"][-2:] == [
        {"channel": "prospective_memory", "count": 0, "requested": True},
        {"channel": "working_memory", "count": 0, "requested": True},
    ]


def test_pipeline_uses_one_instant_and_prefers_working_session_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    _install_working(monkeypatch, engine, [_working_item()])
    monkeypatch.setattr(pipeline_mod, "utc_now", lambda: NOW)
    filt = {
        **_filter(),
        "session_id": "durable-evidence-session",
    }
    filt.pop("as_of")

    result = engine.retrieve("Helios", TENANT, filt=filt, record_access=False)

    assert result.explain["working_memory"]["evaluated_at"] == NOW.isoformat()
    assert result.explain["channels"]["working_memory"] == 1

    conflicting = {
        **filt,
        "as_of": NOW,
        "working_evaluated_at": NOW + timedelta(days=1),
    }
    result = engine.retrieve("Helios", TENANT, filt=conflicting, record_access=False)
    assert result.explain["working_memory"]["evaluated_at"] == NOW.isoformat()


def test_serial_parallel_results_are_byte_identical(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    _install_working(monkeypatch, engine, [_working_item()])
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "0")
    serial = engine.retrieve("Helios release review", TENANT, filt=_filter(), record_access=False)
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "1")
    parallel = engine.retrieve("Helios release review", TENANT, filt=_filter(), record_access=False)
    assert serial.to_dict() == parallel.to_dict()


def test_plane_hits_share_the_common_budget_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    _install_working(monkeypatch, engine, [_working_item()])
    candidates: list[str] = []

    def recording_fit_budget(hits: list[object], budget: int) -> tuple[list[object], int]:
        candidates.extend(hit.id for hit in hits)
        return [], 0

    monkeypatch.setattr(LocalMemoryEngine, "_fit_budget", staticmethod(recording_fit_budget))
    result = engine.retrieve("Helios release review", TENANT, filt=_filter(), record_access=False)

    assert candidates.count("shared-id") == 2
    assert not any(hit.metadata.get("memory_plane") for hit in result.hits)


def test_plane_reads_are_non_mutating(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine()
    item = _working_item()
    _install_working(monkeypatch, engine, [item])
    intentions_before = engine.list_intentions(TENANT)
    working_before = copy.deepcopy(item.__dict__)

    engine.retrieve("Helios release review", TENANT, filt=_filter(), record_access=False)

    assert engine.list_intentions(TENANT) == intentions_before
    assert item.__dict__ == working_before
    assert engine.list_intentions(TENANT)[0].status == "scheduled"


def test_volatile_routes_reuse_cache_at_same_evaluation_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    _install_working(monkeypatch, engine, [_working_item()])
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "4")
    monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", "0")
    pipeline_mod._RESULT_CACHE.clear()
    calls = 0
    original = LocalMemoryEngine.vector_search

    def counting_vector(self: LocalMemoryEngine, *args: object, **kwargs: object) -> list[object]:
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(LocalMemoryEngine, "vector_search", counting_vector)
    engine.retrieve("Helios", TENANT, filt=_filter(), record_access=False)
    engine.retrieve("Helios", TENANT, filt=_filter(), record_access=False)

    assert calls == 1
    assert len(pipeline_mod._RESULT_CACHE) == 1


def test_working_route_exceptions_are_fail_soft_in_serial_and_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()

    def broken(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("working route failed")

    monkeypatch.setattr(LocalMemoryEngine, "list_working", broken, raising=False)
    for parallel in ("0", "1"):
        monkeypatch.setenv("MNEMOSYNE_PARALLEL_CHANNELS", parallel)
        result = engine.retrieve("Helios", TENANT, filt=_filter(), record_access=False)
        assert result.explain["working_memory"]["status"] == "unavailable"
        assert result.explain["working_memory"]["reason"] == "working_store_error"
        assert result.explain["working_memory"]["error_type"] == "RuntimeError"
        assert all(hit.kind != "working" for hit in result.hits)
