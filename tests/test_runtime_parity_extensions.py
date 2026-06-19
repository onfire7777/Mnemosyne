from __future__ import annotations

from hashlib import sha256

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import GateResult, RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.learning import Lesson, Procedure
from mnemosyne.models import Evidence
from mnemosyne.parametric import ParametricTier
from mnemosyne.prefetch import AnticipatoryPrefetcher, PrefetchCandidate
from mnemosyne.provenance import SignedProvenanceVerifier
from mnemosyne.queue import InProcessQueue, QueueWorker
from mnemosyne.storage import LocalObjectStore


TENANT = "tenant-runtime-extensions"
USER = "user-runtime-extensions"


def test_local_object_store_addresses_bytes_and_blocks_bad_uris(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    first = store.put_bytes(b"image-bytes", TENANT, kind="image", media_type="image/png")
    second = store.put_bytes(b"image-bytes", TENANT, kind="image", media_type="image/png")

    assert first.cid == second.cid
    assert store.exists(first.uri)
    assert store.read_bytes(first.uri) == b"image-bytes"

    try:
        store.read_bytes("file:///etc/passwd")
    except ValueError as exc:
        assert "unsupported object uri" in str(exc)
    else:
        raise AssertionError("unsafe URI should be rejected")


def test_signed_provenance_verifier_quarantines_digest_mismatch() -> None:
    verifier = SignedProvenanceVerifier()
    payload = b"trusted payload"
    valid = verifier.verify(payload, {"sha256": sha256(payload).hexdigest(), "issuer": "camera", "signature": "sig"})
    invalid = verifier.verify(payload, {"sha256": sha256(b"other").hexdigest(), "issuer": "camera", "signature": "sig"})

    assert valid.valid is True
    assert valid.trusted is True
    assert valid.trust_delta == 1
    assert invalid.quarantine is True
    assert invalid.trust_delta < 0


def test_ingestion_pipeline_externalizes_multimodal_bytes_and_quarantines_bad_provenance(tmp_path) -> None:
    engine = LocalMemoryEngine()
    pipeline = IngestionPipeline(engine, LocalObjectStore(tmp_path / "objects"))
    result = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="external",
            source_type="camera",
            data=b"not-the-manifest-bytes",
            modality="image",
            media_type="image/png",
            metadata={"alt_text": "A whiteboard architecture diagram."},
            signed_provenance={"sha256": sha256(b"different").hexdigest(), "issuer": "camera", "signature": "sig"},
            trust_tier=3,
        )
    )
    evidence = engine.get_evidence(TENANT, result.cid)

    assert result.content_pointer is not None
    assert result.resource is not None
    assert result.quarantined is True
    assert result.trust_tier == 0
    assert evidence is not None
    assert evidence.modality == "image"
    assert evidence.content == "A whiteboard architecture diagram."
    assert evidence.metadata["quarantine_reason"] == "signed provenance digest mismatch"


def test_externalized_binary_evidence_cid_includes_object_pointer(tmp_path) -> None:
    engine = LocalMemoryEngine()
    pipeline = IngestionPipeline(engine, LocalObjectStore(tmp_path / "objects"))
    first = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="upload",
            data=b"first",
            modality="binary",
            media_type="application/octet-stream",
        )
    )
    second = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="upload",
            data=b"second",
            modality="binary",
            media_type="application/octet-stream",
        )
    )

    assert first.cid != second.cid
    assert len(engine.evidence) == 2


def test_in_process_queue_retries_and_completes_jobs() -> None:
    queue = InProcessQueue()
    attempts = {"count": 0}

    def flaky(payload):
        attempts["count"] += payload["increment"]
        if attempts["count"] == 1:
            raise RuntimeError("transient")

    worker = QueueWorker(queue, {"consolidate": flaky})
    job = queue.enqueue("consolidate", {"increment": 1}, max_attempts=2)

    first = worker.run_once("consolidate")
    second = worker.run_once("consolidate")

    assert first is job
    assert second is job
    assert job.status == "complete"
    assert job.attempts == 2
    assert queue.snapshot()["complete"] == 1


def test_prefetch_gate_warms_only_predictable_safe_queries() -> None:
    engine = LocalMemoryEngine()
    engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="seed",
            content="The predictable next task uses Postgres retrieval.",
            trust_tier=3,
            access_policy={"tenant": TENANT},
        )
    )
    prefetcher = AnticipatoryPrefetcher(engine)
    results = prefetcher.prefetch(
        TENANT,
        [
            PrefetchCandidate("predictable next task", 0.9, "recent task sequence"),
            PrefetchCandidate("network call", 0.99, "unsafe", {"requires_network": True}),
            PrefetchCandidate("low confidence", 0.2, "weak signal"),
        ],
    )

    assert [item.executed for item in results] == [True, False, False]
    assert prefetcher.get_warmed(TENANT, "predictable next task") is not None


def test_parametric_tier_requires_validated_sources_and_protected_gate() -> None:
    tier = ParametricTier()
    active_lesson = Lesson(
        tenant_id=TENANT,
        lesson_type="corrective",
        failure_signature="retry-safe-tool",
        content="Retry safe tool calls after transient failures.",
        status="active",
    )
    active_procedure = Procedure(
        tenant_id=TENANT,
        kind="checklist",
        name="Retry procedure",
        body="Verify idempotency before retrying.",
        signature={"failure_signature": "retry-safe-tool"},
        status="validated",
    )
    artifact = tier.propose_from_lessons(TENANT, [active_lesson], [active_procedure])
    gate = GateResult(
        candidate_id="candidate",
        promoted=True,
        protected_regressions=[],
        failed_cases=[],
        passed_cases=["protected"],
        margin=0.99,
        rollback_branch=None,
    )
    protected = [RegressionCase("protected", "retry", "retry", "idempotency", protected=True)]

    decision = tier.evaluate(artifact, gate, protected)

    assert artifact.source_ids == [active_lesson.id, active_procedure.id]
    assert decision.promoted is True
    assert artifact.status == "promoted"
