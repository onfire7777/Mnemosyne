"""RED contract for fail-closed, cross-plane deletion (W2 D1, R01-R25).

These tests are deliberately synthetic-only.  They describe the observable
contract of the deletion coordinator without requiring PostgreSQL, an object
service, KMS, a replica, or a backup service.  Existing green erasure behavior
is exercised directly where it exists; missing orchestration remains literal
RED evidence for the repair DAG.
"""

from __future__ import annotations

import copy
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pytest

from mnemosyne.engine import LocalMemoryEngine, WorkingMemoryItem
from mnemosyne.evidence_signing import (
    generate_collector_keypair,
    sign_evidence_manifest,
    verify_evidence_manifest_signature,
)
from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.security import SecurityPolicy, SessionIdentity, TrustTier
from mnemosyne.sqlite_engine import SqliteEngine

CANARY = "w2-delete-canary-7f37"
TENANT = "tenant-delete-a"
OTHER_TENANT = "tenant-delete-b"
USER = "user-delete-a"
OTHER_USER = "user-delete-b"
OPERATION_ID = "00000000-0000-4000-8000-000000000025"
SCHEMA = "mnemosyne.deletion_manifest.v1"
AS_OF = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _evidence(tenant: str = TENANT, *, user: str = USER, content: str = CANARY) -> Evidence:
    return Evidence(
        tenant_id=tenant,
        user_id=user,
        actor="user",
        source_type="chat",
        source_identity=f"source-{CANARY}",
        session_id=f"session-{CANARY}",
        content=content,
        content_pointer=f"object://{tenant}/{CANARY}",
        embedding=[0.125, 0.25],
        metadata={"secret": CANARY},
        access_policy={"tenant": tenant},
    )


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _strings(nested)]
    if isinstance(value, (list, tuple, set)):
        return [item for nested in value for item in _strings(nested)]
    return []


def _assert_absent(value: Any, *needles: str) -> None:
    text = "\n".join(_strings(value))
    for needle in needles:
        assert needle not in text


@dataclass
class FakeStore:
    name: str
    available: bool = True
    fail_delete: bool = False
    delete_fault: str | None = None
    probe_fault: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    delete_calls: list[tuple[str, str]] = field(default_factory=list)
    probe_calls: list[tuple[str, str]] = field(default_factory=list)

    def delete(self, tenant: str, source_ref: str) -> dict[str, Any]:
        self.delete_calls.append((tenant, source_ref))
        if not self.available:
            raise ConnectionError(f"{self.name} unavailable")
        if self.fail_delete or self.delete_fault == "before_commit":
            raise OSError(f"{self.name} delete failed")
        before = len(self.rows)
        self.rows = [
            row
            for row in self.rows
            if not (row.get("tenant_id") == tenant and row.get("source_ref") == source_ref)
        ]
        if self.delete_fault == "timeout_after_commit":
            self.delete_fault = None
            raise TimeoutError(f"{self.name} timed out after commit")
        return {"deleted": before - len(self.rows)}

    def probe(self, tenant: str, source_ref: str) -> bool:
        self.probe_calls.append((tenant, source_ref))
        if self.probe_fault == "raise":
            raise OSError(f"{self.name} probe failed")
        if self.probe_fault == "residue":
            return True
        return any(
            row.get("tenant_id") == tenant and row.get("source_ref") == source_ref
            for row in self.rows
        )


@dataclass
class FakeWorld:
    engine: LocalMemoryEngine
    source_ref: str
    stores: dict[str, FakeStore] = field(default_factory=dict)
    process_cache: dict[str, Any] = field(default_factory=dict)
    object_keys: dict[str, bytes | None] = field(default_factory=dict)
    backup_snapshots: list[dict[str, Any]] = field(default_factory=list)
    deletion_fence: int = 0


def _world() -> FakeWorld:
    engine = LocalMemoryEngine()
    source_ref = engine.append_evidence(_evidence())
    return FakeWorld(engine=engine, source_ref=source_ref)


def _working(source_ref: str) -> WorkingMemoryItem:
    return WorkingMemoryItem(
        item_id="working-delete",
        tenant_id=TENANT,
        session_id=f"session-{CANARY}",
        user_id=USER,
        agent_id="agent-delete",
        kind="current_plan",
        task_id="task-delete",
        content=CANARY,
        created_at=AS_OF,
        expires_at=AS_OF + timedelta(hours=1),
        evidence_ids=[source_ref],
        access_policy={"tenant": TENANT},
    )


def _coordinator_type() -> type[Any]:
    """Load the production contract lazily so every missing surface collects."""
    module = importlib.import_module("mnemosyne.deletion")
    return module.DeletionCoordinator


def _coordinator(world: FakeWorld) -> Any:
    return _coordinator_type()(
        engine=world.engine,
        stores=world.stores,
        process_cache=world.process_cache,
        object_keys=world.object_keys,
        backup_snapshots=world.backup_snapshots,
        session_identity=SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=int(TrustTier.DIRECT_USER),
            session_id="verified-delete-session",
        ),
        security_policy=SecurityPolicy(),
    )


def _delete(world: FakeWorld, **overrides: Any) -> dict[str, Any]:
    coordinator = _coordinator(world)
    request = {
        "schema": SCHEMA,
        "operation_id": OPERATION_ID,
        "tenant_id": TENANT,
        "user_id": USER,
        "source_refs": [world.source_ref],
        "branch_scope": "all",
        "mode": "hard_delete_legal",
        "requested_by_role": "legal",
        "reason": "synthetic W2 contract",
    }
    request.update(overrides)
    return coordinator.delete(**request)


def _surface(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in manifest["surfaces"] if row["surface"] == name)


def _assert_complete(manifest: dict[str, Any]) -> None:
    summary = manifest["summary"]
    assert manifest["schema"] == SCHEMA
    assert summary == {
        **summary,
        "cascade_percent": 100,
        "recoverable_residue_count": 0,
        "cross_tenant_mutations": 0,
        "unavailable": 0,
        "failed": 0,
        "complete": True,
    }


def test_r01_local_legal_delete_removes_payload_and_direct_identifiers() -> None:
    world = _world()
    manifest = _delete(world)
    assert world.engine.get_evidence(TENANT, world.source_ref) is None
    _assert_absent(world.engine.export_tenant(TENANT), world.source_ref)
    assert _surface(manifest, "source_evidence")["verified_removed"] is True


def test_r02_sqlite_delete_removes_row_fts_pointer_metadata_and_vector(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path)
    source_ref = engine.append_evidence(_evidence())
    world = FakeWorld(engine=engine, source_ref=source_ref)  # type: ignore[arg-type]
    manifest = _delete(world)
    conn = engine._connect(TENANT)
    assert conn.execute("SELECT 1 FROM evidence WHERE cid = ?", (source_ref,)).fetchone() is None
    assert (
        conn.execute(
            "SELECT 1 FROM evidence_fts WHERE evidence_fts MATCH ?",
            (f'"{CANARY}"',),
        ).fetchone()
        is None
    )
    _assert_absent(engine.export_tenant(TENANT), CANARY, source_ref)
    assert _surface(manifest, "sqlite")["verified_removed"] is True


def test_r03_unavailable_postgres_is_explicitly_incomplete() -> None:
    world = _world()
    world.stores["postgres"] = FakeStore("postgres", available=False)
    manifest = _delete(world)
    assert _surface(manifest, "postgres")["error_code"] == "store_unavailable"
    assert manifest["summary"]["unavailable"] == 1
    assert manifest["summary"]["complete"] is False


def test_r03_available_postgres_removes_row_metadata_vector_and_index() -> None:
    world = _world()
    postgres = FakeStore(
        "postgres",
        rows=[
            {
                "tenant_id": TENANT,
                "source_ref": world.source_ref,
                "content": CANARY,
                "metadata": {"secret": CANARY},
                "embedding": [0.125, 0.25],
                "lexical_index": CANARY,
            }
        ],
    )
    world.stores["postgres"] = postgres
    manifest = _delete(world)
    assert postgres.delete_calls == [(TENANT, world.source_ref)]
    assert postgres.rows == []
    postgres_surface = _surface(manifest, "postgres")
    assert postgres_surface["verified_removed"] is True
    assert postgres_surface["checkpoint"]
    _assert_complete(manifest)


def test_r04_legal_delete_cascades_to_every_branch() -> None:
    world = _world()
    branch_refs: dict[str, str] = {"main": world.source_ref}
    for branch in ("feature", "release"):
        world.engine.branch(branch, tenant_id=TENANT)
        branch_refs[branch] = world.engine.append_evidence(_evidence(), branch=branch)

    feature_ref = branch_refs["feature"]
    survivor = world.engine.append_evidence(_evidence(content="feature survivor"), branch="feature")
    derived_evidence = _evidence(content=f"{CANARY} plus feature survivor")
    derived_evidence.metadata["source_evidence_cids"] = [feature_ref, survivor]
    world.engine.append_evidence(derived_evidence, branch="feature")
    world.engine.upsert_assertion(
        Assertion(
            tenant_id=TENANT,
            user_id=USER,
            subject=CANARY,
            predicate="is",
            object="feature projection",
            confidence=1.0,
            source_evidence_cids=[feature_ref],
        ),
        branch="feature",
    )
    world.engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source=CANARY,
            predicate="projects",
            target="feature graph",
            source_evidence_cids=[feature_ref],
        ),
        branch="feature",
    )
    manifest = _delete(world)
    for branch, source_ref in branch_refs.items():
        assert world.engine.get_evidence(TENANT, source_ref, branch=branch) is None
    exported = world.engine.export_tenant(TENANT)
    _assert_absent(exported, feature_ref)
    assert "feature survivor" in "\n".join(_strings(exported))
    assert manifest["branch_scope"] == "all"


def test_r05_mixed_source_derived_content_is_recomputed() -> None:
    world = _world()
    survivor = world.engine.append_evidence(_evidence(content="independent fact"))
    unrelated = world.engine.append_evidence(
        Evidence.from_dict(_evidence(content=f"unrelated literal {CANARY}").to_dict())
    )
    derived_evidence = _evidence(content=f"{CANARY} plus independent fact")
    derived_evidence.metadata["source_evidence_cids"] = [world.source_ref, survivor]
    derived = world.engine.append_evidence(derived_evidence)
    _delete(world)
    assert world.engine.get_evidence(TENANT, derived) is None
    assert world.engine.get_evidence(TENANT, survivor) is not None
    assert world.engine.get_evidence(TENANT, unrelated) is not None
    assert world.engine.get_evidence(TENANT, unrelated).content == f"unrelated literal {CANARY}"


def test_r05_unrelated_same_tenant_records_remain_byte_identical() -> None:
    world = _world()
    unrelated = world.engine.append_evidence(_evidence(content=f"literal survivor {CANARY}"))
    unrelated_before = json.dumps(
        world.engine.get_evidence(TENANT, unrelated).to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    survivor_row = {
        "tenant_id": TENANT,
        "source_ref": unrelated,
        "payload": {"literal": CANARY, "bytes": "00ff"},
    }
    world.stores["queue"] = FakeStore(
        "queue",
        rows=[
            {"tenant_id": TENANT, "source_ref": world.source_ref, "payload": CANARY},
            copy.deepcopy(survivor_row),
        ],
    )

    _delete(world)

    unrelated_after = json.dumps(
        world.engine.get_evidence(TENANT, unrelated).to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert unrelated_after == unrelated_before
    assert world.stores["queue"].rows == [survivor_row]


def test_r06_assertion_history_and_vectors_are_scrubbed() -> None:
    world = _world()
    assertion = Assertion(
        tenant_id=TENANT,
        user_id=USER,
        subject=CANARY,
        predicate="is",
        object="secret",
        confidence=1.0,
        source_evidence_cids=[world.source_ref],
    )
    world.engine.upsert_assertion(assertion)
    _delete(world)
    stored = next(iter(world.engine.assertions.values()))
    assert stored.status == "retracted"
    assert stored.source_evidence_cids == []


def test_r07_runtime_user_model_cannot_resurrect_deleted_value() -> None:
    world = _world()
    world.stores["runtime_state"] = FakeStore(
        "runtime_state",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "user_model": CANARY}],
    )
    manifest = _delete(world)
    assert world.stores["runtime_state"].rows == []
    assert _surface(manifest, "runtime_user_model")["verified_removed"] is True


def test_r08_relations_graph_cache_and_aliases_are_scrubbed_all_branches() -> None:
    world = _world()
    world.engine.add_relation(
        Relation(
            tenant_id=TENANT,
            source=CANARY,
            predicate="reveals",
            target="secret",
            source_evidence_cids=[world.source_ref],
        )
    )
    world.process_cache["graph-ppr"] = {
        "tenant_id": TENANT,
        "source_ref": world.source_ref,
        "value": CANARY,
    }
    _delete(world)
    stored = next(iter(world.engine.relations.values()))
    assert stored.valid_to is not None
    assert stored.source_evidence_cids == []
    _assert_absent(world.process_cache, CANARY)


def test_r09_entity_summary_aliases_and_vectors_are_recomputed() -> None:
    world = _world()
    world.engine.register_entity(
        TENANT,
        CANARY,
        source_evidence_cids=[world.source_ref],
        access_policy={"tenant": TENANT},
    )
    _delete(world)
    assert not any(
        row.get("tenant_id") == TENANT and world.source_ref in row.get("source_evidence_cids", [])
        for row in world.engine.entities.values()
    )


@pytest.mark.parametrize("surface", ["justifications", "contradictions"])
def test_r10_justification_and_contradiction_records_are_scrubbed(surface: str) -> None:
    world = _world()
    world.stores[surface] = FakeStore(
        surface,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "text": CANARY}],
    )
    _delete(world)
    assert world.stores[surface].rows == []


@pytest.mark.parametrize("surface", ["procedures", "lessons", "trajectories"])
def test_r11_learned_artifacts_are_provenance_linked_and_removed(surface: str) -> None:
    world = _world()
    world.stores[surface] = FakeStore(
        surface,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "body": CANARY}],
    )
    manifest = _delete(world)
    assert world.stores[surface].rows == []
    assert _surface(manifest, surface)["verified_removed"] is True


def test_r12_all_prospective_intention_states_are_cancelled_and_scrubbed() -> None:
    world = _world()
    world.stores["intentions"] = FakeStore(
        "intentions",
        rows=[
            {"tenant_id": TENANT, "source_ref": world.source_ref, "status": state, "trigger": CANARY}
            for state in ("scheduled", "cancelled", "fired")
        ],
    )
    _delete(world)
    assert world.stores["intentions"].rows == []


def test_r13_working_and_workspace_contexts_cannot_recall_or_broadcast() -> None:
    world = _world()
    world.engine.put_working(_working(world.source_ref))
    world.process_cache["workspace"] = {
        "tenant_id": TENANT,
        "broadcast": CANARY,
        "source_ref": world.source_ref,
    }
    _delete(world)
    assert (
        world.engine.get_working(
            TENANT,
            f"session-{CANARY}",
            "working-delete",
            as_of=AS_OF,
        )
        is None
    )
    _assert_absent(world.process_cache, CANARY, world.source_ref)


@pytest.mark.parametrize("cache", ["prefetch", "candidate", "projection", "mcp_bundle"])
def test_r14_process_caches_are_synchronously_invalidated(cache: str) -> None:
    world = _world()
    world.process_cache[cache] = {"tenant_id": TENANT, "source_ref": world.source_ref, "hit": CANARY}
    manifest = _delete(world)
    _assert_absent(world.process_cache, CANARY, world.source_ref)
    assert _surface(manifest, f"cache:{cache}")["action"] == "invalidated"


def test_r15_provider_purge_failure_never_reports_success() -> None:
    world = _world()
    world.stores["embedding_provider"] = FakeStore("embedding_provider", fail_delete=True)
    manifest = _delete(world)
    assert _surface(manifest, "embedding_provider")["error_code"] == "delete_failed"
    assert manifest["summary"]["complete"] is False


def test_r16_lexical_index_has_zero_active_or_historical_hits() -> None:
    world = _world()
    world.stores["lexical_index"] = FakeStore(
        "lexical_index",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "lexeme": CANARY}],
    )
    _delete(world)
    assert world.stores["lexical_index"].rows == []


@pytest.mark.parametrize("status", ["queued", "running", "retry", "complete", "dead"])
def test_r17_queue_payload_result_and_error_are_scrubbed(status: str) -> None:
    world = _world()
    world.stores["queue"] = FakeStore(
        "queue",
        rows=[
            {
                "tenant_id": TENANT,
                "source_ref": world.source_ref,
                "status": status,
                "payload": CANARY,
                "result": CANARY,
                "error": CANARY,
            }
        ],
    )
    _delete(world)
    assert world.stores["queue"].rows == []


@pytest.mark.parametrize("object_backend", ["local_encrypted", "s3_encrypted"])
def test_r18_every_object_key_is_crypto_shredded(object_backend: str) -> None:
    world = _world()
    pointer = f"{object_backend}://{TENANT}/{world.source_ref}"
    world.object_keys[pointer] = b"synthetic-key"
    manifest = _delete(world)
    assert world.object_keys[pointer] is None
    assert _surface(manifest, "object_storage")["action"] == "crypto_shredded"


def test_r18_unencrypted_or_unavailable_kms_forces_incomplete() -> None:
    world = _world()
    world.stores["kms"] = FakeStore("kms", available=False)
    world.object_keys[f"plain://{TENANT}/{world.source_ref}"] = b"not-shreddable"
    manifest = _delete(world)
    assert manifest["summary"]["complete"] is False
    assert _surface(manifest, "object_storage")["verified_removed"] is False


def test_r19_resource_uri_and_hash_confirmation_oracle_is_removed() -> None:
    world = _world()
    world.stores["resources"] = FakeStore(
        "resources",
        rows=[
            {
                "tenant_id": TENANT,
                "source_ref": world.source_ref,
                "uri": f"https://example.invalid/{CANARY}",
                "hash": CANARY,
            }
        ],
    )
    _delete(world)
    assert world.stores["resources"].rows == []


def test_r20_verified_boundary_deletion_is_forward_only_and_retry_resumes() -> None:
    world = _world()
    journal = FakeStore(
        "journal",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "body": CANARY}],
    )
    manifest_store = FakeStore(
        "manifest_store",
        delete_fault="before_commit",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "body": CANARY}],
    )
    world.stores.update(journal=journal, manifest_store=manifest_store)

    incomplete = _delete(world)

    assert incomplete["summary"]["complete"] is False
    assert incomplete["fence"]["durable"] is False
    assert journal.rows == []
    assert _surface(incomplete, "journal")["verified_removed"] is True
    assert _surface(incomplete, "manifest_store")["verified_removed"] is False
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None

    manifest_store.delete_fault = None
    complete = _delete(world)
    _assert_complete(complete)
    assert journal.delete_calls == [(TENANT, world.source_ref)]
    assert world.engine.get_evidence(TENANT, world.source_ref) is None
    assert manifest_store.rows == []


def test_r21_retained_audit_history_contains_only_opaque_refs() -> None:
    world = _world()
    world.engine.audit_log.append(
        {
            "id": "audit-r21",
            "tenant_id": TENANT,
            "op": "remember",
            "target_id": world.source_ref,
            "details": {"content": CANARY, "source_ref": world.source_ref},
        }
    )
    world.engine.deletion_log.append(
        {
            "id": "deletion-r21",
            "tenant_id": TENANT,
            "evidence_cid": world.source_ref,
            "reason": CANARY,
        }
    )
    manifest = _delete(world)
    retained = world.engine.export_tenant(TENANT)
    _assert_absent(manifest, CANARY, world.source_ref)
    _assert_absent(retained["audit_log"], CANARY, world.source_ref)
    _assert_absent(retained["deletion_log"], CANARY, world.source_ref)
    assert any(row["id"] == "audit-r21" and row["op"] == "remember" for row in retained["audit_log"])
    assert any(row["id"] == "deletion-r21" for row in retained["deletion_log"])
    assert manifest["source_refs"]
    assert all(ref.startswith("opaque:") for ref in manifest["source_refs"])


@pytest.mark.parametrize("available,immutable", [(True, False), (False, False), (True, True)])
def test_r22_backup_retention_and_restore_are_reported_honestly(available: bool, immutable: bool) -> None:
    world = _world()
    world.backup_snapshots.append(
        {
            "tenant_id": TENANT,
            "source_ref": world.source_ref,
            "payload": CANARY,
            "available": available,
            "immutable": immutable,
        }
    )
    manifest = _delete(world)
    if available and not immutable:
        _assert_complete(manifest)
        assert world.backup_snapshots == []
        return

    exception = manifest["retention_exceptions"][0]
    fence_generation = manifest["fence"]["generation"]
    assert exception["restore_block_fence"] >= fence_generation
    assert exception["deadline"]
    assert manifest["summary"]["complete"] is False

    coordinator = _coordinator(world)
    for restore_generation in (fence_generation - 1, fence_generation):
        with pytest.raises(PermissionError, match="deletion fence"):
            coordinator.restore_backup(
                tenant_id=TENANT,
                snapshot={"tenant_id": TENANT, "payload": CANARY},
                capability=restore_generation,
            )
    assert world.engine.retrieve(CANARY, TENANT).hits


def test_r23_replay_returns_same_outcome_and_partial_retry_resumes() -> None:
    world = _world()
    provider = FakeStore(
        "embedding_provider",
        fail_delete=True,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "vector": CANARY}],
    )
    world.stores["embedding_provider"] = provider

    incomplete = _delete(world)
    assert incomplete["summary"]["complete"] is False
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None

    provider.fail_delete = False
    complete = _delete(world)
    replay = _delete(world)
    _assert_complete(complete)
    assert replay == complete
    assert complete["operation_id"] == OPERATION_ID
    assert provider.rows == []
    assert len(provider.delete_calls) == 2


def test_r23_deletion_fence_blocks_racing_resurrection() -> None:
    world = _world()
    manifest = _delete(world)
    stale_generation = manifest["fence"]["generation"] - 1
    coordinator = _coordinator(world)
    with pytest.raises(PermissionError, match="deletion fence"):
        coordinator.append_evidence(_evidence(), capability=stale_generation)
    assert world.engine.retrieve(CANARY, TENANT).hits == []


def test_r24_identical_cross_tenant_canary_is_not_mutated() -> None:
    world = _world()
    other_ref = world.engine.append_evidence(_evidence(OTHER_TENANT, user=OTHER_USER))
    world.stores["queue"] = FakeStore(
        "queue",
        rows=[
            {"tenant_id": TENANT, "source_ref": world.source_ref, "payload": CANARY},
            {"tenant_id": OTHER_TENANT, "source_ref": world.source_ref, "payload": CANARY},
        ],
    )
    world.process_cache["other-tenant"] = {
        "tenant_id": OTHER_TENANT,
        "source_ref": world.source_ref,
        "payload": CANARY,
    }
    other_pointer = f"s3_encrypted://{OTHER_TENANT}/{world.source_ref}"
    world.object_keys[other_pointer] = b"other-tenant-key"
    world.backup_snapshots.append(
        {"tenant_id": OTHER_TENANT, "source_ref": world.source_ref, "payload": CANARY}
    )
    other_before = copy.deepcopy(world.engine.export_tenant(OTHER_TENANT))
    store_before = copy.deepcopy(world.stores["queue"].rows[1])
    cache_before = copy.deepcopy(world.process_cache["other-tenant"])
    backups_before = copy.deepcopy(world.backup_snapshots)
    manifest = _delete(world)
    assert world.engine.export_tenant(OTHER_TENANT) == other_before
    assert world.engine.get_evidence(OTHER_TENANT, other_ref) is not None
    assert world.stores["queue"].rows == [store_before]
    assert world.process_cache["other-tenant"] == cache_before
    assert world.object_keys[other_pointer] == b"other-tenant-key"
    assert world.backup_snapshots == backups_before
    assert manifest["summary"]["cross_tenant_mutations"] == 0
    target_recall = world.engine.retrieve(CANARY, TENANT)
    other_recall = world.engine.retrieve(CANARY, OTHER_TENANT)
    assert target_recall.hits == []
    assert all(hit.tenant_id == OTHER_TENANT for hit in other_recall.hits)
    assert any(hit.id == other_ref for hit in other_recall.hits)


def test_delete_requires_verified_destructive_identity_before_effects() -> None:
    world = _world()
    coordinator = _coordinator_type()(
        engine=world.engine,
        stores=world.stores,
        process_cache=world.process_cache,
        object_keys=world.object_keys,
        backup_snapshots=world.backup_snapshots,
    )
    request = {
        "schema": SCHEMA,
        "operation_id": OPERATION_ID,
        "tenant_id": TENANT,
        "user_id": USER,
        "source_refs": [world.source_ref],
        "branch_scope": "all",
        "mode": "hard_delete_legal",
        "requested_by_role": "legal",
        "reason": "synthetic W2 contract",
    }
    with pytest.raises(PermissionError, match="verified session identity"):
        coordinator.delete(**request)
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("operation_id", "not-a-uuid", "UUID"),
        ("source_refs", [], "nonempty"),
        ("source_refs", ["same", "same"], "deduplicated"),
        ("schema", "wrong", "schema"),
        ("mode", "soft", "mode"),
        ("user_id", OTHER_USER, "user ownership"),
        ("branch_scope", "feature", "main or all"),
    ],
)
def test_request_validation_rejects_before_effects(field: str, value: Any, error: str) -> None:
    world = _world()
    with pytest.raises((PermissionError, ValueError), match=error):
        _delete(world, **{field: value})
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None


def test_replay_conflict_covers_every_authoritative_request_dimension() -> None:
    world = _world()
    first = _delete(world)
    assert first["summary"]["complete"] is True
    for request_field, value in (
        ("tenant_id", OTHER_TENANT),
        ("user_id", OTHER_USER),
        ("source_refs", ["different-source"]),
        ("branch_scope", "main"),
        ("mode", "different-mode"),
    ):
        with pytest.raises((PermissionError, ValueError), match="conflict|ownership|mode"):
            _delete(world, **{request_field: value})


def test_unprobed_store_remains_incomplete() -> None:
    class DeleteOnlyStore:
        def delete(self, tenant: str, source_ref: str) -> dict[str, int]:
            return {"deleted": 1}

    world = _world()
    world.stores["remote"] = DeleteOnlyStore()  # type: ignore[assignment]
    manifest = _delete(world)
    assert _surface(manifest, "remote")["error_code"] == "probe_failed"
    assert manifest["summary"]["complete"] is False
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None


@pytest.mark.parametrize("probe_fault", ["raise", "residue"])
def test_probe_failure_never_treats_delete_return_as_verified_absence(probe_fault: str) -> None:
    world = _world()
    remote = FakeStore(
        "remote",
        probe_fault=probe_fault,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.stores["remote"] = remote

    manifest = _delete(world)

    assert remote.rows == []
    assert remote.probe_calls == [(TENANT, world.source_ref)]
    assert _surface(manifest, "remote")["verified_removed"] is False
    assert manifest["summary"]["complete"] is False
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None


def test_timeout_after_commit_converges_on_retry_without_early_engine_delete() -> None:
    world = _world()
    remote = FakeStore(
        "remote",
        delete_fault="timeout_after_commit",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.stores["remote"] = remote

    complete = _delete(world)

    _assert_complete(complete)
    assert remote.rows == []
    assert remote.delete_calls == [(TENANT, world.source_ref)]
    assert remote.probe_calls == [(TENANT, world.source_ref)]
    assert world.engine.get_evidence(TENANT, world.source_ref) is None


def test_timeout_after_commit_retry_probes_before_repeating_delete() -> None:
    world = _world()
    remote = FakeStore(
        "remote",
        delete_fault="timeout_after_commit",
        probe_fault="raise",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.stores["remote"] = remote

    incomplete = _delete(world)

    assert incomplete["summary"]["complete"] is False
    assert remote.delete_calls == [(TENANT, world.source_ref)]
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None

    remote.probe_fault = None
    complete = _delete(world)

    _assert_complete(complete)
    assert remote.delete_calls == [(TENANT, world.source_ref)]
    assert remote.probe_calls == [
        (TENANT, world.source_ref),
        (TENANT, world.source_ref),
    ]
    assert world.engine.get_evidence(TENANT, world.source_ref) is None


def test_multi_ref_timeout_recovery_never_repeats_committed_delete() -> None:
    world = _world()
    second_ref = world.engine.append_evidence(_evidence(content=f"{CANARY}-second"))
    refs = [world.source_ref, second_ref]
    remote = FakeStore(
        "remote",
        delete_fault="timeout_after_commit",
        probe_fault="raise",
        rows=[{"tenant_id": TENANT, "source_ref": ref} for ref in refs],
    )
    world.stores["remote"] = remote

    incomplete = _delete(world, source_refs=refs)

    assert incomplete["summary"]["complete"] is False
    assert remote.delete_calls == [(TENANT, world.source_ref)]
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None
    assert world.engine.get_evidence(TENANT, second_ref) is not None

    remote.probe_fault = None
    complete = _delete(world, source_refs=refs)

    _assert_complete(complete)
    assert remote.delete_calls == [(TENANT, world.source_ref), (TENANT, second_ref)]
    assert world.engine.get_evidence(TENANT, world.source_ref) is None
    assert world.engine.get_evidence(TENANT, second_ref) is None


def test_r14_cache_name_collision_cannot_hide_store_residue() -> None:
    world = _world()
    world.stores["cache:shared"] = FakeStore(
        "cache:shared",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.process_cache["shared"] = {
        "tenant_id": TENANT,
        "source_ref": world.source_ref,
        "payload": CANARY,
    }

    manifest = _delete(world)

    _assert_complete(manifest)
    assert world.stores["cache:shared"].delete_calls == [(TENANT, world.source_ref)]
    assert "shared" not in world.process_cache
    assert [
        (row["surface_type"], row["surface"])
        for row in manifest["surfaces"]
        if row["surface"] == "cache:shared"
    ] == [("store", "cache:shared"), ("cache", "cache:shared")]


def test_r18_object_deletion_does_not_match_source_ref_prefixes() -> None:
    world = _world()
    target = f"s3_encrypted://{TENANT}/{world.source_ref}"
    unrelated = f"s3_encrypted://{TENANT}/{world.source_ref}-unrelated"
    world.object_keys.update({target: b"target-key", unrelated: b"unrelated-key"})

    _assert_complete(_delete(world))

    assert world.object_keys[target] is None
    assert world.object_keys[unrelated] == b"unrelated-key"


@pytest.mark.parametrize("surface", ["manifest_store", "remote"])
@pytest.mark.parametrize(
    ("fault_field", "fault_value"),
    [
        ("delete_fault", "before_commit"),
        ("delete_fault", "timeout_after_commit"),
        ("probe_fault", "raise"),
        ("probe_fault", "residue"),
    ],
)
def test_each_store_transition_failure_is_recorded_and_resumable(
    surface: str,
    fault_field: str,
    fault_value: str,
) -> None:
    """Synthetic faults are contract tests, not production deletion evidence."""
    world = _world()
    journal = FakeStore(
        "journal",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "payload": CANARY}],
    )
    target = FakeStore(
        surface,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "payload": CANARY}],
    )
    setattr(target, fault_field, fault_value)
    world.stores.update(journal=journal)
    world.stores[surface] = target

    incomplete = _delete(world)

    receipt = _surface(incomplete, surface)
    if fault_field == "delete_fault" and fault_value == "timeout_after_commit":
        _assert_complete(incomplete)
        assert receipt["state"] == "verified"
        assert receipt["attempts"] == 1
        assert target.delete_calls == [(TENANT, world.source_ref)]
        return
    assert receipt["state"] == "failed"
    assert receipt["verified_removed"] is False
    assert receipt["attempts"] == 1
    assert incomplete["summary"]["complete"] is False
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None

    target.delete_fault = None
    target.probe_fault = None
    complete = _delete(world)

    _assert_complete(complete)
    expected_attempts = 2 if fault_field == "delete_fault" else 1
    assert _surface(complete, surface)["attempts"] == expected_attempts
    assert journal.delete_calls == [(TENANT, world.source_ref)]
    assert world.engine.get_evidence(TENANT, world.source_ref) is None


def test_concurrent_same_request_is_serialized_by_shared_ledger() -> None:
    world = _world()
    remote = FakeStore(
        "remote",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.stores["remote"] = remote
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: _delete(world), range(2)))
    assert outcomes[0] == outcomes[1]
    assert remote.delete_calls == [(TENANT, world.source_ref)]


def test_forged_generation_cannot_authorize_resurrection() -> None:
    world = _world()
    manifest = _delete(world)
    coordinator = _coordinator(world)
    with pytest.raises(PermissionError, match="capability"):
        coordinator.append_evidence(
            _evidence(),
            capability=manifest["fence"]["generation"],
        )


def test_import_has_no_engine_monkeypatch_side_effect() -> None:
    append_before = LocalMemoryEngine.append_evidence
    forget_before = LocalMemoryEngine.forget
    importlib.reload(importlib.import_module("mnemosyne.deletion"))
    assert LocalMemoryEngine.append_evidence is append_before
    assert LocalMemoryEngine.forget is forget_before


def _valid_manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "operation_id": OPERATION_ID,
        "request_id": "request-25",
        "requested_at": "2026-07-18T00:00:00Z",
        "completed_at": "2026-07-18T00:00:01Z",
        "mode": "hard_delete_legal",
        "requested_by_role": "legal",
        "reason": "opaque:reason",
        "tenant_ref": "opaque:tenant",
        "user_scope": "opaque:user",
        "branch_scope": "all",
        "source_refs": ["opaque:source"],
        "policy": {"version": "w2", "required_surfaces": ["source_evidence"]},
        "fence": {"generation": 1, "ledger_position": 1, "durable": True},
        "surfaces": [
            {
                "surface": "source_evidence",
                "backend": "local",
                "tenant_ref": "opaque:tenant",
                "object_ref": "opaque:source",
                "action": "deleted",
                "precondition_present": True,
                "attempted_at": "2026-07-18T00:00:00Z",
                "verified_at": "2026-07-18T00:00:01Z",
                "verification_method": "direct_and_public_probe",
                "verified_removed": True,
                "residue_probe": 0,
                "durability_checkpoint": "local:1",
                "error_code": None,
            }
        ],
        "stores": [
            {
                "store": "source_evidence",
                "expected": 1,
                "discovered": 1,
                "visited": 1,
                "available": True,
                "checkpoint": "local:1",
            }
        ],
        "retention_exceptions": [],
        "summary": {
            "expected": 1,
            "visited": 1,
            "verified": 1,
            "failed": 0,
            "unavailable": 0,
            "cascade_percent": 100,
            "recoverable_residue_count": 0,
            "cross_tenant_mutations": 0,
            "complete": True,
        },
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["surfaces"].clear(),
        lambda manifest: manifest["stores"][0].update(available=False),
        lambda manifest: manifest["summary"].update(recoverable_residue_count=1),
        lambda manifest: manifest["summary"].update(cross_tenant_mutations=1),
        lambda manifest: manifest["summary"].update(complete=True, failed=1),
    ],
)
def test_r25_semantic_verifier_rejects_signed_but_incomplete_manifest(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None]
) -> None:
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    generate_collector_keypair(private_key, public_key)
    manifest = _valid_manifest()
    mutate(manifest)
    manifest_path = tmp_path / "deletion-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    sign_evidence_manifest(manifest_path, private_key)
    assert verify_evidence_manifest_signature(manifest_path, public_key)["verified"] is True
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    result = verifier.verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert result["errors"]


def test_r25_complete_manifest_is_signed_then_semantically_verified(tmp_path: Path) -> None:
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    generate_collector_keypair(private_key, public_key)
    manifest = _valid_manifest()
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    semantic = verifier.verify_deletion_manifest(manifest)
    assert semantic == {"complete": True, "errors": []}
    manifest_path = tmp_path / "deletion-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    sign_evidence_manifest(manifest_path, private_key)
    verified = verify_evidence_manifest_signature(manifest_path, public_key)
    assert verified["verified"] is True
    _assert_complete(manifest)


def test_r23_durable_journal_replays_after_coordinator_restart(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    world = _world()
    request = {
        "schema": SCHEMA,
        "operation_id": OPERATION_ID,
        "tenant_id": TENANT,
        "user_id": USER,
        "source_refs": [world.source_ref],
        "branch_scope": "all",
        "mode": "hard_delete_legal",
        "requested_by_role": "legal",
        "reason": "synthetic W2 contract",
    }
    journal_path = tmp_path / "deletion-journal.sqlite"
    identity = SessionIdentity(
        tenant_id=TENANT,
        user_id=USER,
        role="operator",
        source_trust_tier=int(TrustTier.DIRECT_USER),
        session_id="verified-delete-session",
    )
    first = deletion.DeletionCoordinator(
        engine=world.engine,
        session_identity=identity,
        ledger=deletion.SQLiteDeletionLedger(journal_path),
    ).delete(**request)
    replay = deletion.DeletionCoordinator(
        engine=world.engine,
        session_identity=identity,
        ledger=deletion.SQLiteDeletionLedger(journal_path),
    ).delete(**request)
    assert replay == first
    assert replay["fence"]["durable"] is True
    assert importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(replay) == {
        "complete": True,
        "errors": [],
    }


def test_r25_signed_deletion_manifest_helper_requires_semantic_completeness(tmp_path: Path) -> None:
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    generate_collector_keypair(private_key, public_key)
    manifest = _valid_manifest()
    manifest_path = tmp_path / "deletion-manifest.json"
    verifier.write_signed_deletion_manifest(manifest, manifest_path, private_key)
    result = verifier.verify_signed_deletion_manifest(manifest_path, public_key)
    assert result["complete"] is True
    manifest["summary"]["complete"] = False
    with pytest.raises(ValueError, match="semantically incomplete"):
        verifier.write_signed_deletion_manifest(manifest, manifest_path, private_key)
