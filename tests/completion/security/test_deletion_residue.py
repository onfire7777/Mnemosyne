"""RED contract for fail-closed, cross-plane deletion (W2 D1, R01-R25).

These tests are deliberately synthetic-only.  They describe the observable
contract of the deletion coordinator without requiring PostgreSQL, an object
service, KMS, a replica, or a backup service.  Existing green erasure behavior
is exercised directly where it exists; missing orchestration remains literal
RED evidence for the repair DAG.
"""

from __future__ import annotations

import copy
import hashlib
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
from mnemosyne.models import Assertion, Evidence, MergeReport, Relation
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
        return [str(key) for key in value] + [
            item for nested in value.values() for item in _strings(nested)
        ]
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
        if self.delete_fault == "crash_after_commit":
            self.delete_fault = None
            raise SystemExit(f"{self.name} crashed after commit")
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
    other_ref = engine.append_evidence(_evidence(OTHER_TENANT, user=OTHER_USER))
    other_before = copy.deepcopy(engine.export_tenant(OTHER_TENANT))
    world = FakeWorld(engine=engine, source_ref=source_ref)  # type: ignore[arg-type]
    manifest = _delete(world)
    assert engine.export_tenant(OTHER_TENANT) == other_before
    assert engine.get_evidence(OTHER_TENANT, other_ref) is not None
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


def test_r06_assertion_calibration_is_scrubbed() -> None:
    world = _world()
    assertion = Assertion(
        tenant_id=TENANT,
        user_id=USER,
        subject="calibration-subject",
        predicate="is",
        object="secret",
        confidence=1.0,
        source_evidence_cids=[world.source_ref],
        calibration={"note": CANARY, "pair": (CANARY, "kept-sample")},
    )
    world.engine.upsert_assertion(assertion)
    _delete(world)
    stored = next(iter(world.engine.assertions.values()))
    _assert_absent(stored.calibration, CANARY, world.source_ref)
    assert stored.calibration["pair"][1] == "kept-sample"


def test_r21_scrubbed_key_collision_never_drops_audit_data() -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    world = _world()
    metadata_key = "colliding-metadata-key"
    evidence = _evidence(content="ordinary payload")
    evidence.metadata = {metadata_key: "safe"}
    source_ref = world.engine.append_evidence(evidence)
    occupied = deletion._opaque("retained-audit-key", metadata_key)
    world.engine.audit_log.append(
        {
            "id": "audit-collision-r21",
            "tenant_id": TENANT,
            "details": {metadata_key: "first", occupied: "second"},
        }
    )
    _delete(world, source_refs=[source_ref])
    retained = next(row for row in world.engine.audit_log if row["id"] == "audit-collision-r21")
    assert len(retained["details"]) == 2
    assert set(retained["details"].values()) == {"first", "second"}
    assert metadata_key not in retained["details"]


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
    assert next(row for row in manifest["surfaces"] if row["surface_type"] == "cache")[
        "action"
    ] == "invalidated"


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
    canary_digest = hashlib.sha256(CANARY.encode()).hexdigest()
    world.engine.audit_log.append(
        {
            "id": "audit-r21",
            "tenant_id": TENANT,
            "op": "remember",
            "target_id": world.source_ref,
            "details": {
                "content": CANARY,
                "source_ref": world.source_ref,
                "digest": canary_digest,
                f"{CANARY}:{world.source_ref}": "sensitive-key",
            },
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
    _assert_absent(manifest, CANARY, world.source_ref, canary_digest)
    _assert_absent(retained["audit_log"], CANARY, world.source_ref, canary_digest)
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


def test_request_validation_canonicalizes_uuid_before_deletion() -> None:
    world = _world()
    manifest = _delete(world, operation_id=f"{{{OPERATION_ID.upper()}}}")
    assert manifest["operation_id"] == OPERATION_ID
    assert manifest["request_id"] == OPERATION_ID
    replay = _delete(world, operation_id=OPERATION_ID)
    assert replay == manifest
    durable_manifest = copy.deepcopy(manifest)
    durable_manifest["fence"]["durable"] = True
    assert importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(durable_manifest) == {
        "complete": True,
        "errors": [],
    }


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
    assert _surface(complete, "remote")["error_code"] is None
    durable = copy.deepcopy(complete)
    durable["fence"]["durable"] = True
    assert importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(durable) == {
        "complete": True,
        "errors": [],
    }


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
    colliding = [
        (row["surface_type"], row["surface"])
        for row in manifest["surfaces"]
        if row["surface_type"] == "cache" or row["surface"] == "cache:shared"
    ]
    assert [pair for pair in colliding if pair[0] == "store"] == [("store", "cache:shared")]
    cache_pairs = [pair for pair in colliding if pair[0] == "cache"]
    assert len(cache_pairs) == 1
    assert cache_pairs[0][1].startswith("cache:opaque:")
    durable_manifest = copy.deepcopy(manifest)
    durable_manifest["fence"]["durable"] = True
    assert importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(durable_manifest) == {
        "complete": True,
        "errors": [],
    }


def test_engine_crash_after_commit_resumes_by_probe_without_repeating_forget(tmp_path: Path) -> None:
    class CrashAfterCommitEngine(LocalMemoryEngine):
        def __init__(self) -> None:
            super().__init__()
            self.forget_calls = 0
            self.crash_after_commit = True

        def forget(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            result = super().forget(*args, **kwargs)
            self.forget_calls += 1
            if self.crash_after_commit:
                self.crash_after_commit = False
                raise SystemExit("synthetic crash after engine commit")
            return result

    engine = CrashAfterCommitEngine()
    world = FakeWorld(engine=engine, source_ref=engine.append_evidence(_evidence()))
    ledger = importlib.import_module("mnemosyne.deletion").SQLiteDeletionLedger(tmp_path / "deletion.db")
    coordinator = _coordinator_type()(
        engine=engine,
        session_identity=SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=int(TrustTier.DIRECT_USER),
            session_id="verified-delete-session",
        ),
        security_policy=SecurityPolicy(),
        ledger=ledger,
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

    with pytest.raises(SystemExit, match="synthetic crash"):
        coordinator.delete(**request)

    restarted_ledger = importlib.import_module("mnemosyne.deletion").SQLiteDeletionLedger(
        tmp_path / "deletion.db"
    )
    restarted_coordinator = _coordinator_type()(
        engine=engine,
        session_identity=SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=int(TrustTier.DIRECT_USER),
            session_id="verified-delete-session",
        ),
        security_policy=SecurityPolicy(),
        ledger=restarted_ledger,
    )
    manifest = restarted_coordinator.delete(**request)
    _assert_complete(manifest)
    assert engine.forget_calls == 1
    # The crash window must not leave residue in retained history or the journal.
    _assert_absent(world.engine.export_tenant(TENANT), CANARY, world.source_ref)
    journal_bytes = (tmp_path / "deletion.db").read_bytes()
    for suffix in ("-wal", "-shm"):
        sidecar = tmp_path / f"deletion.db{suffix}"
        if sidecar.exists():
            journal_bytes += sidecar.read_bytes()
    for needle in (CANARY, world.source_ref, TENANT, USER):
        assert needle.encode() not in journal_bytes
    assert importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest) == {
        "complete": True,
        "errors": [],
    }


def test_store_crash_after_commit_resumes_by_probe_without_repeating_delete(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    world = _world()
    remote = FakeStore(
        "remote",
        delete_fault="crash_after_commit",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.stores["remote"] = remote
    world.process_cache["prefetch"] = {
        "tenant_id": TENANT,
        "source_ref": world.source_ref,
        "hit": CANARY,
    }
    journal_path = tmp_path / "deletion-journal.sqlite"
    identity = SessionIdentity(
        tenant_id=TENANT,
        user_id=USER,
        role="operator",
        source_trust_tier=int(TrustTier.DIRECT_USER),
        session_id="verified-delete-session",
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

    with pytest.raises(SystemExit, match="crashed after commit"):
        deletion.DeletionCoordinator(
            engine=world.engine,
            stores=world.stores,
            process_cache=world.process_cache,
            session_identity=identity,
            ledger=deletion.SQLiteDeletionLedger(journal_path),
        ).delete(**request)

    manifest = deletion.DeletionCoordinator(
        engine=world.engine,
        stores=world.stores,
        process_cache=world.process_cache,
        session_identity=identity,
        ledger=deletion.SQLiteDeletionLedger(journal_path),
    ).delete(**request)

    _assert_complete(manifest)
    assert remote.delete_calls == [(TENANT, world.source_ref)]
    assert _surface(manifest, "remote")["attempts"] == 1
    assert world.engine.get_evidence(TENANT, world.source_ref) is None
    # The cache surface persisted before the crash resumes under the same
    # ledger-keyed name instead of duplicating.
    cache_rows = [row for row in manifest["surfaces"] if row["surface_type"] == "cache"]
    assert len(cache_rows) == 1
    assert cache_rows[0]["verified_removed"] is True
    _assert_absent(manifest, CANARY, world.source_ref)


def test_cache_crash_after_invalidation_resumes_without_probe_failure(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")

    class CrashingCache(dict):
        def __init__(self) -> None:
            super().__init__()
            self.crash = True

        def __delitem__(self, key: str) -> None:
            super().__delitem__(key)
            if self.crash:
                self.crash = False
                raise SystemExit("synthetic crash after cache invalidation")

    world = _world()
    cache = CrashingCache()
    cache["prefetch"] = {"tenant_id": TENANT, "source_ref": world.source_ref, "hit": CANARY}
    journal_path = tmp_path / "deletion-journal.sqlite"
    identity = SessionIdentity(
        tenant_id=TENANT,
        user_id=USER,
        role="operator",
        source_trust_tier=int(TrustTier.DIRECT_USER),
        session_id="verified-delete-session",
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

    with pytest.raises(SystemExit, match="cache invalidation"):
        deletion.DeletionCoordinator(
            engine=world.engine,
            process_cache=cache,
            session_identity=identity,
            ledger=deletion.SQLiteDeletionLedger(journal_path),
        ).delete(**request)
    assert "prefetch" not in cache

    manifest = deletion.DeletionCoordinator(
        engine=world.engine,
        process_cache=cache,
        session_identity=identity,
        ledger=deletion.SQLiteDeletionLedger(journal_path),
    ).delete(**request)

    _assert_complete(manifest)
    cache_rows = [row for row in manifest["surfaces"] if row["surface_type"] == "cache"]
    assert len(cache_rows) == 1
    assert cache_rows[0]["action"] == "invalidated"
    assert cache_rows[0]["attempts"] == 2
    assert world.engine.get_evidence(TENANT, world.source_ref) is None


def test_sqlite_ledger_replay_conflict_generation_and_checkpoint_cas(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    ledger = deletion.SQLiteDeletionLedger(tmp_path / "ledger.sqlite")
    record = ledger.begin(OPERATION_ID, "fingerprint-a", TENANT)
    assert ledger.current_generation(TENANT) == 1
    assert ledger.current_generation(OTHER_TENANT) == 0
    with pytest.raises(ValueError, match="replay conflicts"):
        ledger.begin(OPERATION_ID, "fingerprint-b", TENANT)
    stale = deletion.SQLiteDeletionLedger(tmp_path / "ledger.sqlite").begin(
        OPERATION_ID, "fingerprint-a", TENANT
    )
    ledger.checkpoint(record)
    with pytest.raises(RuntimeError, match="checkpoint conflict"):
        ledger.checkpoint(stale)


def test_concurrent_durable_ledgers_serialize_same_request(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    world = _world()
    remote = FakeStore(
        "remote",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    world.stores["remote"] = remote
    journal_path = tmp_path / "deletion-journal.sqlite"
    identity = SessionIdentity(
        tenant_id=TENANT,
        user_id=USER,
        role="operator",
        source_trust_tier=int(TrustTier.DIRECT_USER),
        session_id="verified-delete-session",
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

    def run(_: int) -> dict[str, Any]:
        return deletion.DeletionCoordinator(
            engine=world.engine,
            stores=world.stores,
            session_identity=identity,
            ledger=deletion.SQLiteDeletionLedger(journal_path),
        ).delete(**request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, range(2)))
    assert outcomes[0] == outcomes[1]
    assert remote.delete_calls == [(TENANT, world.source_ref)]


def test_store_named_object_storage_without_object_keys_does_not_crash() -> None:
    world = _world()
    world.stores["object_storage"] = FakeStore(
        "object_storage",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    manifest = _delete(world)
    _assert_complete(manifest)
    assert world.stores["object_storage"].rows == []
    assert _surface(manifest, "object_storage")["surface_type"] == "store"


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
    opaque = "opaque:" + "0" * 64
    return {
        "schema": SCHEMA,
        "operation_id": OPERATION_ID,
        "request_id": OPERATION_ID,
        "requested_at": "2026-07-18T00:00:00Z",
        "completed_at": "2026-07-18T00:00:01Z",
        "mode": "hard_delete_legal",
        "requested_by_role": "legal",
        "reason": opaque,
        "tenant_ref": opaque,
        "user_scope": opaque,
        "branch_scope": "all",
        "source_refs": [opaque],
        "policy": {
            "version": "w2",
            "required_surfaces": [{"surface_type": "engine", "surface": "source_evidence"}],
        },
        "fence": {"generation": 1, "ledger_position": 1, "durable": True},
        "surfaces": [
            {
                "surface": "source_evidence",
                "surface_type": "engine",
                "backend": "local",
                "tenant_ref": opaque,
                "object_ref": opaque,
                "action": "deleted",
                "precondition_present": True,
                "attempted_at": "2026-07-18T00:00:00Z",
                "verified_at": "2026-07-18T00:00:01Z",
                "verification_method": "direct_and_public_probe",
                "state": "verified",
                "attempts": 1,
                "checkpoint": "local:1",
                "verified_removed": True,
                "residue_probe": 0,
                "durability_checkpoint": "local:1",
                "error_code": None,
            }
        ],
        "stores": [
            {
                "store": "source_evidence",
                "surface_type": "engine",
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
        lambda manifest: manifest.update(operation_id={"unexpected": "object"}),
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.pop("operation_id"),
        lambda manifest: manifest.update(request_id="different-request"),
        lambda manifest: manifest.pop("completed_at"),
        lambda manifest: manifest.update(completed_at="2026-07-18T00:00:01"),
        lambda manifest: manifest.update(mode="soft_delete"),
        lambda manifest: manifest.update(requested_by_role="operator"),
        lambda manifest: manifest["policy"].pop("version"),
        lambda manifest: manifest["surfaces"][0].update(action="retained"),
        lambda manifest: manifest["surfaces"][0].update(state="failed"),
        lambda manifest: manifest["surfaces"][0].update(precondition_present=False),
        lambda manifest: manifest["surfaces"][0].update(verification_method="none"),
        lambda manifest: manifest["surfaces"][0].pop("attempted_at"),
        lambda manifest: manifest["surfaces"][0].pop("verified_at"),
        lambda manifest: manifest["surfaces"][0].update(
            attempted_at="2026-07-18T00:00:01Z",
            verified_at="2026-07-18T00:00:00Z",
        ),
        lambda manifest: manifest["surfaces"][0].update(
            attempted_at="2026-07-18T00:00:02Z",
            verified_at="2026-07-18T00:00:03Z",
        ),
        lambda manifest: manifest.update(tenant_ref="opaque:tenant-direct"),
        lambda manifest: manifest.update(source_refs=["opaque:" + "A" * 64]),
        lambda manifest: manifest.update(schema="mnemosyne.deletion_manifest.v0"),
        lambda manifest: manifest.update(branch_scope="feature"),
        lambda manifest: manifest["fence"].update(durable=False),
        lambda manifest: manifest["surfaces"][0].update(residue_probe=1),
        lambda manifest: manifest["surfaces"][0].update(verified_removed=False),
        lambda manifest: manifest["surfaces"][0].update(attempts=0),
        lambda manifest: manifest["surfaces"][0].update(attempts=True),
        lambda manifest: manifest["surfaces"][0].update(durability_checkpoint="local:2"),
        lambda manifest: manifest["stores"][0].update(visited=0),
        lambda manifest: manifest["stores"][0].update(discovered=0),
        lambda manifest: manifest["stores"][0].update(expected=True),
        lambda manifest: manifest["surfaces"].append(copy.deepcopy(manifest["surfaces"][0])),
        lambda manifest: manifest["retention_exceptions"].append(
            {"surface": "backups", "restore_block_fence": 1, "deadline": "2026-08-17T00:00:00Z"}
        ),
    ],
)
def test_r25_semantic_verifier_requires_identity_policy_and_receipt_semantics(
    mutate: Callable[[dict[str, Any]], Any],
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)
    result = importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest)
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["fence"].update(generation=True, ledger_position=True),
        lambda manifest: manifest["surfaces"][0].update(surface=[]),
        lambda manifest: manifest["stores"][0].update(store={}),
        lambda manifest: manifest["policy"].update(required_surfaces=[[]]),
    ],
)
def test_r25_semantic_verifier_fails_closed_for_malformed_names_and_fences(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)
    result = importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert result["errors"]


@pytest.mark.parametrize("label", ["user@example.com", "tenant/customer-123"])
def test_r25_signed_manifest_rejects_identifier_bearing_surface_labels(
    tmp_path: Path, label: str
) -> None:
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    generate_collector_keypair(private_key, public_key)
    manifest = _valid_manifest()
    manifest["surfaces"][0]["surface"] = label
    manifest["stores"][0]["store"] = label
    manifest["policy"]["required_surfaces"][0]["surface"] = label
    manifest_path = tmp_path / "deletion-manifest.json"

    with pytest.raises(ValueError, match="semantically incomplete"):
        verifier.write_signed_deletion_manifest(manifest, manifest_path, private_key)

    assert not manifest_path.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["surfaces"][0].update(
            checkpoint="direct-user-identifier",
            durability_checkpoint="direct-user-identifier",
        ),
        lambda manifest: manifest["stores"][0].update(checkpoint="direct-user-identifier"),
        lambda manifest: manifest["surfaces"][0].update(backend="direct-user-identifier"),
    ],
)
def test_r25_semantic_verifier_rejects_custody_in_receipt_tokens(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)
    result = importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert result["errors"]


@pytest.mark.parametrize("field", ["Payload", "extra"])
def test_r25_semantic_verifier_rejects_unknown_custody_fields(field: str) -> None:
    manifest = _valid_manifest()
    manifest[field] = "direct-user-identifier"
    result = importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert result["errors"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["surfaces"][0].update(surface_type="user-jake@example-corp"),
        lambda manifest: manifest["stores"][0].update(surface_type="user-jake@example-corp"),
        lambda manifest: manifest["policy"]["required_surfaces"][0].update(
            surface_type="user-jake@example-corp"
        ),
    ],
)
def test_r25_verifier_rejects_identifier_bearing_surface_types(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], Any]
) -> None:
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    generate_collector_keypair(private_key, public_key)
    manifest = _valid_manifest()
    mutate(manifest)
    result = verifier.verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert any("safe deletion vocabulary" in error for error in result["errors"])
    manifest_path = tmp_path / "deletion-manifest.json"
    with pytest.raises(ValueError, match="semantically incomplete"):
        verifier.write_signed_deletion_manifest(manifest, manifest_path, private_key)
    assert not manifest_path.exists()


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda m: m["surfaces"][0].update(surface=f"{CANARY}-surface"), "canary material"),
        (lambda m: m["surfaces"][0].update(surface="s3://bucket/evidence"), "source URI"),
        (
            lambda m: m["surfaces"][0].update(checkpoint="a" * 64, durability_checkpoint="a" * 64),
            "direct hash",
        ),
        (
            lambda m: m["policy"]["required_surfaces"][0].update(tenant_id="tenant-direct"),
            "forbidden direct-custody field",
        ),
    ],
)
def test_r25_custody_scan_rejects_direct_material(
    mutate: Callable[[dict[str, Any]], Any], expected_error: str
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)
    result = importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert any(expected_error in error for error in result["errors"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["policy"]["required_surfaces"][0].update(note="user-jake@example-corp"),
        lambda m: m["policy"]["required_surfaces"][0].update({CANARY: "x"}),
        lambda m: m["policy"]["required_surfaces"][0].pop("surface_type"),
    ],
)
def test_r25_verifier_rejects_custody_in_required_surface_rows(
    mutate: Callable[[dict[str, Any]], Any],
) -> None:
    manifest = _valid_manifest()
    mutate(manifest)
    result = importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert result["errors"]


def test_r25_verifier_fails_closed_for_non_object_manifests() -> None:
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    for manifest in (None, "manifest", 7, ["surfaces"]):
        result = verifier.verify_deletion_manifest(manifest)
        assert result == {"complete": False, "errors": ["manifest must be an object"]}


def test_r25_verifier_fails_closed_for_hostile_nesting_depth() -> None:
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    manifest = _valid_manifest()
    hostile: dict[str, Any] = {"deep": "leaf"}
    for _ in range(3000):
        hostile = {"deep": hostile}
    manifest["summary"] = hostile
    result = verifier.verify_deletion_manifest(manifest)
    assert result["complete"] is False
    assert any("custody scan" in error for error in result["errors"])


def test_r25_signed_verification_fails_closed_on_tamper_and_malformed_bytes(tmp_path: Path) -> None:
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    generate_collector_keypair(private_key, public_key)
    manifest = _valid_manifest()
    manifest_path = tmp_path / "deletion-manifest.json"
    verifier.write_signed_deletion_manifest(manifest, manifest_path, private_key)

    # Semantically complete but tampered after signing: only the signature fails.
    tampered = dict(manifest, reason="opaque:" + "1" * 64)
    manifest_path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = verifier.verify_signed_deletion_manifest(manifest_path, public_key)
    assert result["complete"] is False
    assert any("signature" in error for error in result["errors"])

    manifest_path.write_text("not-json", encoding="utf-8")
    result = verifier.verify_signed_deletion_manifest(manifest_path, public_key)
    assert result["complete"] is False
    assert result["errors"]

    # Hostile nesting must fail closed at parse time, not crash the verifier.
    manifest_path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    result = verifier.verify_signed_deletion_manifest(manifest_path, public_key)
    assert result["complete"] is False
    assert result["errors"]


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


def test_r23_durable_journal_never_persists_sensitive_cache_key(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    world = _world()
    cache_key = f"{CANARY}:{world.source_ref}"
    world.process_cache[cache_key] = {
        "tenant_id": TENANT,
        "source_ref": world.source_ref,
        "payload": CANARY,
    }
    journal_path = tmp_path / "deletion-journal.sqlite"
    coordinator = deletion.DeletionCoordinator(
        engine=world.engine,
        process_cache=world.process_cache,
        session_identity=SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=int(TrustTier.DIRECT_USER),
            session_id="verified-delete-session",
        ),
        ledger=deletion.SQLiteDeletionLedger(journal_path),
    )
    manifest = coordinator.delete(
        schema=SCHEMA,
        operation_id=OPERATION_ID,
        tenant_id=TENANT,
        user_id=USER,
        source_refs=[world.source_ref],
        branch_scope="all",
        mode="hard_delete_legal",
        requested_by_role="legal",
        reason="synthetic W2 contract",
    )
    journal_bytes = journal_path.read_bytes()
    for suffix in ("-wal", "-shm"):
        sidecar = journal_path.with_name(journal_path.name + suffix)
        if sidecar.exists():
            journal_bytes += sidecar.read_bytes()
    for needle in (cache_key, CANARY, world.source_ref, TENANT, USER):
        assert needle.encode() not in journal_bytes
    # An unkeyed digest of the cache key would be a dictionary-attack oracle; the
    # persisted surface name must be keyed by the ledger instead.
    unkeyed_digest = hashlib.sha256(f"cache-surface\0{cache_key}".encode()).hexdigest()
    assert unkeyed_digest.encode() not in journal_bytes
    assert unkeyed_digest not in json.dumps(manifest)
    _assert_absent(manifest, CANARY, world.source_ref)


def test_r23_durable_journal_never_persists_sensitive_store_name(tmp_path: Path) -> None:
    deletion = importlib.import_module("mnemosyne.deletion")
    world = _world()
    store_name = f"user-{CANARY}@example.com"
    world.stores[store_name] = FakeStore(
        store_name,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )
    journal_path = tmp_path / "deletion-journal.sqlite"
    coordinator = deletion.DeletionCoordinator(
        engine=world.engine,
        stores=world.stores,
        session_identity=SessionIdentity(
            tenant_id=TENANT,
            user_id=USER,
            role="operator",
            source_trust_tier=int(TrustTier.DIRECT_USER),
            session_id="verified-delete-session",
        ),
        ledger=deletion.SQLiteDeletionLedger(journal_path),
    )
    manifest = coordinator.delete(
        schema=SCHEMA,
        operation_id=OPERATION_ID,
        tenant_id=TENANT,
        user_id=USER,
        source_refs=[world.source_ref],
        branch_scope="all",
        mode="hard_delete_legal",
        requested_by_role="legal",
        reason="synthetic W2 contract",
    )
    _assert_complete(manifest)
    journal_bytes = journal_path.read_bytes()
    for suffix in ("-wal", "-shm"):
        sidecar = journal_path.with_name(journal_path.name + suffix)
        if sidecar.exists():
            journal_bytes += sidecar.read_bytes()
    for needle in (store_name, CANARY, world.source_ref, TENANT, USER):
        assert needle.encode() not in journal_bytes
    # An unkeyed digest of the store name would be a dictionary-attack oracle.
    unkeyed_digest = hashlib.sha256(f"store-surface\0{store_name}".encode()).hexdigest()
    assert unkeyed_digest.encode() not in journal_bytes
    _assert_absent(manifest, store_name)


def test_r21_retained_history_preserves_unrelated_schema_keys_and_short_values() -> None:
    world = _world()
    evidence = _evidence(content="ordinary payload")
    evidence.metadata = {"reality_class": "shared-taxonomy", "private-key-r21": "sv7"}
    source_ref = world.engine.append_evidence(evidence)
    world.engine.audit_log.append(
        {
            "id": "audit-schema-r21",
            "tenant_id": TENANT,
            "source_type": "source_type",
            "reality_class": "source_type-adjacent",
            "private-key-r21": "kept-value",
            "short_exact": "sv7",
            "short_context": "prefix sv7 suffix",
        }
    )
    _delete(world, source_refs=[source_ref])
    retained = next(row for row in world.engine.audit_log if row["id"] == "audit-schema-r21")
    # Schema keys shared with deleted metadata survive; ad-hoc deleted metadata
    # keys are opaqued.
    assert retained["source_type"] == "source_type"
    assert retained["reality_class"] == "source_type-adjacent"
    assert "private-key-r21" not in retained
    assert "kept-value" in retained.values()
    # Short (<8 char) sensitive values scrub only on exact match, never as substrings.
    assert retained["short_exact"].startswith("opaque:")
    assert retained["short_context"] == "prefix sv7 suffix"


def test_r21_retained_history_scrubs_deleted_metadata_keys() -> None:
    world = _world()
    metadata_key = "private-metadata-key-unique"
    evidence = _evidence(content="ordinary payload")
    evidence.metadata = {metadata_key: "safe"}
    source_ref = world.engine.append_evidence(evidence)
    world.engine.audit_log.append(
        {
            "id": "audit-metadata-key-r21",
            "tenant_id": TENANT,
            "details": {metadata_key: "safe"},
        }
    )

    _delete(world, source_refs=[source_ref])

    retained = next(
        row for row in world.engine.audit_log if row["id"] == "audit-metadata-key-r21"
    )
    _assert_absent(retained, metadata_key)
    assert retained["details"]


def test_r21_merge_log_and_wildcard_audit_history_is_scrubbed() -> None:
    world = _world()
    # Real merge rows are MergeReport.to_dict() and embed no tenant_id; merges
    # audited without a tenant use the "*" wildcard. Neither may keep payload.
    world.engine.merge_log.append(
        MergeReport(
            from_branch=f"branch-{CANARY}",
            into_branch="main",
            evidence_added=1,
            assertions_added=0,
            assertions_merged=0,
            relations_added=0,
            conflicts=[{"detail": CANARY, "source_ref": world.source_ref}],
        ).to_dict()
    )
    world.engine.audit_log.append(
        {
            "id": "audit-merge-wildcard",
            "tenant_id": "*",
            "op": "merge",
            "target_id": f"branch-{CANARY}",
            "details": {"content": CANARY, "source_ref": world.source_ref},
        }
    )
    other_audit = {
        "id": "audit-other-tenant",
        "tenant_id": OTHER_TENANT,
        "op": "remember",
        "details": {"content": CANARY},
    }
    world.engine.audit_log.append(copy.deepcopy(other_audit))

    _delete(world)

    _assert_absent(world.engine.merge_log, CANARY, world.source_ref)
    assert world.engine.merge_log[0]["evidence_added"] == 1
    scrubbed_wildcard = next(
        row for row in world.engine.audit_log if row.get("id") == "audit-merge-wildcard"
    )
    _assert_absent(scrubbed_wildcard, CANARY, world.source_ref)
    assert scrubbed_wildcard["op"] == "merge"
    # Rows attributed to another tenant stay byte-identical.
    assert other_audit in world.engine.audit_log
    _assert_absent(world.engine.export_tenant(TENANT)["merge_log"], CANARY, world.source_ref)


def test_r21_sqlite_merge_log_rows_are_scrubbed(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path)
    source_ref = engine.append_evidence(_evidence())
    conn = engine._connect(TENANT)
    with engine._lock, conn:
        conn.execute(
            "INSERT INTO merge_log(tenant_id, record) VALUES (?, ?)",
            (
                TENANT,
                json.dumps(
                    MergeReport(
                        from_branch=f"branch-{CANARY}",
                        into_branch="main",
                        evidence_added=1,
                        assertions_added=0,
                        assertions_merged=0,
                        relations_added=0,
                        conflicts=[{"detail": CANARY, "source_ref": source_ref}],
                    ).to_dict(),
                    sort_keys=True,
                ),
            ),
        )
    world = FakeWorld(engine=engine, source_ref=source_ref)  # type: ignore[arg-type]

    manifest = _delete(world)

    _assert_complete(manifest)
    rows = [
        json.loads(row["record"])
        for row in conn.execute("SELECT record FROM merge_log").fetchall()
    ]
    assert rows and rows[0]["evidence_added"] == 1
    _assert_absent(rows, CANARY, source_ref)


def test_r25_coordinator_opaques_identifier_bearing_store_labels() -> None:
    world = _world()
    unsafe_label = "user@example.com"
    world.stores[unsafe_label] = FakeStore(
        unsafe_label,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref}],
    )

    manifest = _delete(world)

    _assert_absent(manifest, unsafe_label)
    store = next(row for row in manifest["stores"] if row["store"].startswith("opaque:"))
    assert store["store"] == _surface(manifest, store["store"])["surface"]
    manifest["fence"]["durable"] = True
    assert importlib.import_module("mnemosyne.deletion_manifest").verify_deletion_manifest(
        manifest
    ) == {"complete": True, "errors": []}


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
