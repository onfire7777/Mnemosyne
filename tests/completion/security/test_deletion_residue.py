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
from mnemosyne.sqlite_engine import SqliteEngine

CANARY = "w2-delete-canary-7f37"
TENANT = "tenant-delete-a"
OTHER_TENANT = "tenant-delete-b"
USER = "user-delete-a"
OTHER_USER = "user-delete-b"
OPERATION_ID = "00000000-0000-4000-8000-000000000025"
SCHEMA = "mnemosyne.deletion_manifest.v1"


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
    rows: list[dict[str, Any]] = field(default_factory=list)
    delete_calls: list[tuple[str, str]] = field(default_factory=list)

    def delete(self, tenant: str, source_ref: str) -> dict[str, Any]:
        self.delete_calls.append((tenant, source_ref))
        if not self.available:
            raise ConnectionError(f"{self.name} unavailable")
        if self.fail_delete:
            raise OSError(f"{self.name} delete failed")
        before = len(self.rows)
        self.rows = [
            row
            for row in self.rows
            if not (row.get("tenant_id") == tenant and row.get("source_ref") == source_ref)
        ]
        return {"deleted": before - len(self.rows)}


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
        session_id="session-delete",
        user_id=USER,
        agent_id="agent-delete",
        kind="task_context",
        task_id="task-delete",
        content=CANARY,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
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
    _assert_absent(world.engine.export_tenant(TENANT), CANARY, world.source_ref)
    assert _surface(manifest, "source_evidence")["verified_removed"] is True


def test_r02_sqlite_delete_removes_row_fts_pointer_metadata_and_vector(tmp_path: Path) -> None:
    engine = SqliteEngine(tmp_path)
    source_ref = engine.append_evidence(_evidence())
    world = FakeWorld(engine=engine, source_ref=source_ref)  # type: ignore[arg-type]
    manifest = _delete(world)
    conn = engine._connect(TENANT)
    assert conn.execute("SELECT 1 FROM evidence WHERE cid = ?", (source_ref,)).fetchone() is None
    assert conn.execute("SELECT 1 FROM evidence_fts WHERE evidence_fts MATCH ?", (CANARY,)).fetchone() is None
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
    _assert_absent(exported, CANARY, feature_ref)
    assert "feature survivor" in "\n".join(_strings(exported))
    assert manifest["branch_scope"] == "all"


def test_r05_mixed_source_derived_content_is_recomputed() -> None:
    world = _world()
    survivor = world.engine.append_evidence(_evidence(content="independent fact"))
    derived_evidence = _evidence(content=f"{CANARY} plus independent fact")
    derived_evidence.metadata["source_evidence_cids"] = [world.source_ref, survivor]
    derived = world.engine.append_evidence(derived_evidence)
    _delete(world)
    retained = world.engine.get_evidence(TENANT, derived)
    assert retained is not None
    assert "independent fact" in retained.content
    _assert_absent(retained.__dict__, CANARY, world.source_ref)


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
    _assert_absent(world.engine.export_tenant(TENANT), CANARY, world.source_ref)


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
    world.process_cache["graph-ppr"] = {"tenant_id": TENANT, "value": CANARY}
    _delete(world)
    _assert_absent(world.engine.export_tenant(TENANT), CANARY, world.source_ref)
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
    _assert_absent(world.engine.export_tenant(TENANT), CANARY, world.source_ref)


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
    world.process_cache["workspace"] = {"broadcast": CANARY, "source_ref": world.source_ref}
    _delete(world)
    assert world.engine.get_working(TENANT, "session-delete", "working-delete") is None
    _assert_absent(world.process_cache, CANARY, world.source_ref)


@pytest.mark.parametrize("cache", ["prefetch", "candidate", "projection", "mcp_bundle"])
def test_r14_process_caches_are_synchronously_invalidated(cache: str) -> None:
    world = _world()
    world.process_cache[cache] = {"tenant_id": TENANT, "source_ref": world.source_ref, "hit": CANARY}
    manifest = _delete(world)
    _assert_absent(world.process_cache, CANARY, world.source_ref)
    assert _surface(manifest, cache)["action"] == "invalidated"


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


@pytest.mark.parametrize("failure", ["journal", "object_storage", "manifest_store"])
def test_r20_boundary_failure_recovers_before_success_manifest(failure: str) -> None:
    world = _world()
    successful = FakeStore(
        "procedures",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "body": CANARY}],
    )
    failing = FakeStore(
        failure,
        fail_delete=True,
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "body": CANARY}],
    )
    world.stores["procedures"] = successful
    world.stores[failure] = failing
    before = copy.deepcopy(successful.rows)

    incomplete = _delete(world)

    assert incomplete["summary"]["complete"] is False
    assert incomplete["fence"]["durable"] is False
    assert world.engine.get_evidence(TENANT, world.source_ref) is not None
    assert successful.rows == before

    failing.fail_delete = False
    complete = _delete(world)
    _assert_complete(complete)
    assert world.engine.get_evidence(TENANT, world.source_ref) is None
    assert successful.rows == []
    assert failing.rows == []


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
                fence_generation=restore_generation,
            )
    assert world.engine.retrieve(CANARY, TENANT).hits == []


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
        coordinator.append_evidence(_evidence(), fence_generation=stale_generation)
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


def _valid_manifest() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "operation_id": OPERATION_ID,
        "request_id": "request-25",
        "requested_at": "2026-07-18T00:00:00Z",
        "completed_at": "2026-07-18T00:00:01Z",
        "mode": "hard_delete_legal",
        "requested_by_role": "legal",
        "reason": "synthetic",
        "tenant_ref": "opaque:tenant",
        "user_scope": "all",
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
                "store": "local",
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


def test_r25_coordinator_persists_signed_complete_multi_surface_manifest(tmp_path: Path) -> None:
    private_key = tmp_path / "collector.key.pem"
    public_key = tmp_path / "collector.pub.pem"
    manifest_path = tmp_path / "deletion-manifest.json"
    generate_collector_keypair(private_key, public_key)
    world = _world()
    world.stores["queue"] = FakeStore(
        "queue",
        rows=[{"tenant_id": TENANT, "source_ref": world.source_ref, "payload": CANARY}],
    )
    object_pointer = f"s3_encrypted://{TENANT}/{world.source_ref}"
    world.object_keys[object_pointer] = b"wrapped-data-key"

    manifest = _delete(
        world,
        manifest_path=str(manifest_path),
        signing_private_key_path=str(private_key),
    )

    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    assert verify_evidence_manifest_signature(manifest_path, public_key)["verified"] is True
    discovered_surfaces = {row["surface"] for row in manifest["surfaces"]}
    assert {"source_evidence", "queue", "object_storage"} <= discovered_surfaces
    assert all(row["verified_removed"] is True for row in manifest["surfaces"])
    verifier = importlib.import_module("mnemosyne.deletion_manifest")
    assert verifier.verify_deletion_manifest(manifest) == {"complete": True, "errors": []}
