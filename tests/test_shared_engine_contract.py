from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne.calibration import CalibrationSet
from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB, ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.jobs import PROJECTION_RECOMPUTE_JOB, RuntimeJobHandlers
from mnemosyne.models import Assertion, Contradiction, Evidence, Justification, Preference, Relation
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.privacy import ErasureMode
from mnemosyne.queue import InProcessQueue
from mnemosyne.text import hashing_embedding


def _live_dsn() -> str | None:
    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


class _RotatingSummarizer:
    strategy = "test_rotating_summary_refresh"

    def __init__(self, summaries: list[str]):
        self.summaries = list(summaries)
        self.calls = 0

    def summarize(self, tenant_id: str, evidence: list[Evidence]) -> dict[str, Any] | None:
        if not evidence:
            return None
        summary = self.summaries[self.calls]
        self.calls += 1
        return {
            "strategy": self.strategy,
            "evidence_count": len(evidence),
            "summary": summary,
            "source_cids": [item.cid for item in evidence if item.cid],
        }


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


def test_shared_engine_contract_updates_evidence_embedding(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="tool",
            source_type="embedding-contract",
            content="",
            content_pointer="objects/shared/embedding-contract.txt",
            trust_tier=1,
            access_policy={"tenant": tenant},
        )
    )
    dims = int(getattr(getattr(getattr(engine, "adapters", None), "embedding", None), "dims", 256))
    vector = hashing_embedding("shared embedding contract", dims=dims)

    updated = engine.set_evidence_embedding(tenant, cid, vector)
    recalled = engine.get_evidence(tenant, cid)
    exported = next(item for item in engine.export_tenant(tenant)["evidence"] if item["cid"] == cid)

    assert updated is True
    assert recalled is not None
    assert recalled.embedding is not None
    assert len(recalled.embedding) == len(vector)
    assert all(abs(left - right) < 0.000001 for left, right in zip(recalled.embedding, vector))
    assert exported["embedding"] is not None
    assert len(exported["embedding"]) == len(vector)


def test_shared_engine_contract_updates_evidence_metadata(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="metadata-contract",
            content="Shared metadata update contract.",
            metadata={"existing": "kept"},
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    updated = engine.update_evidence_metadata(
        tenant,
        cid,
        {"lifecycle": {"tier": "abstractive_gist", "salience": 0.05}},
    )
    recalled = engine.get_evidence(tenant, cid)
    exported = next(item for item in engine.export_tenant(tenant)["evidence"] if item["cid"] == cid)
    audit = [item for item in engine.export_tenant(tenant)["audit_log"] if item["op"] == "update_evidence_metadata"]

    assert updated is True
    assert recalled is not None
    assert recalled.metadata["existing"] == "kept"
    assert recalled.metadata["lifecycle"]["tier"] == "abstractive_gist"
    assert exported["metadata"]["lifecycle"]["salience"] == 0.05
    assert audit
    assert audit[-1]["source"] == "metadata_update"
    assert audit[-1]["diff"]["patch"]["lifecycle"]["tier"] == "abstractive_gist"


def test_shared_engine_contract_preserves_lossless_evidence_envelope(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    provenance = {
        "manifest_id": "urn:mnemosyne:test-manifest",
        "issuer": "shared-contract-verifier",
        "asset_hash": "sha256:" + "a" * 64,
        "valid": True,
    }
    access_policy = {"tenant": tenant, "residency": "us", "purpose": "shared-contract"}
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="tool",
            source_type="c2pa-asset",
            source_identity="camera:shared-contract",
            session_id="session-shared-envelope",
            content="Lossless evidence envelope should survive storage round trips.",
            metadata={"ocr_text": "envelope orchid", "labels": ["lossless", "shared"]},
            content_pointer="objects/tenant/shared-envelope.bin",
            modality="image",
            signed_provenance=provenance,
            trust_tier=1,
            capability_tags=["signed-provenance", "derived-text"],
            sensitivity=2,
            access_policy=access_policy,
        )
    )

    recalled = engine.get_evidence(tenant, cid)
    exported = next(item for item in engine.export_tenant(tenant)["evidence"] if item["cid"] == cid)

    assert recalled is not None
    for record in (recalled.to_dict(), exported):
        assert record["actor"] == "tool"
        assert record["source_type"] == "c2pa-asset"
        assert record["source_identity"] == "camera:shared-contract"
        assert record["session_id"] == "session-shared-envelope"
        assert record["metadata"]["ocr_text"] == "envelope orchid"
        assert record["content_pointer"] == "objects/tenant/shared-envelope.bin"
        assert record["modality"] == "image"
        assert record["signed_provenance"] == provenance
        assert record["trust_tier"] == 1
        assert record["capability_tags"] == ["signed-provenance", "derived-text"]
        assert record["sensitivity"] == 2
        assert record["access_policy"] == access_policy


def test_shared_engine_contract_evidence_cids_are_immutable(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    content = "Duplicate content-addressed evidence should not mutate its envelope."
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="immutable-source",
            source_identity="first-source",
            session_id="first-session",
            content=content,
            metadata={"version": "first"},
            content_pointer="objects/shared/immutable.txt",
            trust_tier=0,
            capability_tags=["first"],
            sensitivity=0,
            signed_provenance={"issuer": "first"},
            access_policy={"tenant": tenant, "version": "first"},
        )
    )

    duplicate_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=f"{user}-mutator",
            actor="tool",
            source_type="immutable-source",
            source_identity="second-source",
            session_id="second-session",
            content=content,
            metadata={"version": "second"},
            content_pointer="objects/shared/immutable.txt",
            trust_tier=5,
            capability_tags=["second"],
            sensitivity=4,
            signed_provenance={"issuer": "second"},
            access_policy={"tenant": tenant, "version": "second"},
        )
    )

    recalled = engine.get_evidence(tenant, cid)
    exported = next(item for item in engine.export_tenant(tenant)["evidence"] if item["cid"] == cid)

    assert duplicate_cid == cid
    assert recalled is not None
    for record in (recalled.to_dict(), exported):
        assert record["user_id"] == user
        assert record["actor"] == "user"
        assert record["source_identity"] == "first-source"
        assert record["session_id"] == "first-session"
        assert record["metadata"]["version"] == "first"
        assert record["trust_tier"] == 0
        assert record["capability_tags"] == ["first"]
        assert record["sensitivity"] == 0
        assert record["signed_provenance"] == {"issuer": "first"}
        assert record["access_policy"]["version"] == "first"


def test_shared_engine_contract_exports_all_and_json(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(engine, tenant, user, "Shared export-all contract evidence.")
    erased_cid = _append_evidence(engine, tenant, user, "Shared export-all erased evidence must stay hidden.")
    engine.forget(tenant, erased_cid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE.value)
    engine.set_calibration(
        CalibrationSet(
            tenant_id=tenant,
            memory_type="fact",
            scores=[0.91],
            target_coverage=0.9,
        )
    )
    entity = engine.register_entity(
        tenant,
        "shared-export-entity",
        alias="Shared Export Entity",
        summary="Shared export-all includes entity registry rows.",
        source_evidence_cids=[cid],
        access_policy={"tenant": tenant},
    )

    exported = engine.export_all()
    parsed = json.loads(engine.to_json())
    expected_keys = {
        "policy",
        "branches",
        "evidence",
        "assertions",
        "relations",
        "preferences",
        "justifications",
        "contradictions",
        "calibrations",
        "entities",
        "audit_log",
        "deletion_log",
        "merge_log",
        "tenants",
    }

    assert expected_keys <= set(exported)
    assert expected_keys <= set(parsed)
    assert exported["policy"]["top_k"] == parsed["policy"]["top_k"]
    assert any(item["cid"] == cid and item["tenant_id"] == tenant for item in exported["evidence"])
    assert any(item["cid"] == cid and item["tenant_id"] == tenant for item in parsed["evidence"])
    assert all(item["cid"] != erased_cid for item in exported["evidence"])
    assert all(item["cid"] != erased_cid for item in parsed["evidence"])
    assert any(item["name"] == "main" and item["tenant_id"] == tenant for item in exported["branches"])
    assert any(item["memory_type"] == "fact" and item["tenant_id"] == tenant for item in exported["calibrations"])
    assert any(item["memory_type"] == "fact" and item["tenant_id"] == tenant for item in parsed["calibrations"])
    assert any(item["canonical"] == entity["canonical"] and item["tenant_id"] == tenant for item in exported["entities"])
    assert any(item["canonical"] == entity["canonical"] and item["tenant_id"] == tenant for item in parsed["entities"])
    assert all(item["tenant_id"] != "*" for item in exported["tenants"])
    tenant_export = next(item for item in exported["tenants"] if item["tenant_id"] == tenant)
    assert any(item["cid"] == cid for item in tenant_export["evidence"])
    assert all(item["cid"] != erased_cid for item in tenant_export["evidence"])
    assert any(item["canonical"] == entity["canonical"] for item in tenant_export["entities"])


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


def test_shared_engine_contract_higher_trust_assertion_overrides_newer_machine_conflicts(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    subject = f"shared source truth subject {uuid4()}"
    machine_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Machine-generated assertion about source truth.",
        trust_tier=3,
    )
    machine_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=subject,
            predicate="prefers",
            object="machine guess",
            confidence=0.72,
            valid_from=datetime(2026, 6, 21, tzinfo=UTC),
            source_evidence_cids=[machine_cid],
            status="active",
            trust_tier=3,
            access_policy={"tenant": tenant},
        )
    )
    human_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Committed Markdown/git source truth assertion.",
        trust_tier=0,
    )
    human_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=subject,
            predicate="prefers",
            object="human-authored markdown",
            confidence=0.99,
            valid_from=datetime(2026, 6, 20, tzinfo=UTC),
            source_evidence_cids=[human_cid],
            status="active",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    later_machine_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=subject,
            predicate="prefers",
            object="newer machine guess",
            confidence=0.99,
            valid_from=datetime(2026, 6, 22, tzinfo=UTC),
            source_evidence_cids=[machine_cid],
            status="active",
            trust_tier=3,
            access_policy={"tenant": tenant},
        )
    )
    machine = _exported_assertion(engine, tenant, machine_id)
    human = _exported_assertion(engine, tenant, human_id)
    later_machine = _exported_assertion(engine, tenant, later_machine_id)

    assert human["status"] == "active"
    assert human["object"] == "human-authored markdown"
    assert machine["status"] == "superseded"
    assert machine["superseded_by"] == human_id
    assert later_machine["status"] == "superseded"
    assert later_machine["superseded_by"] == human_id


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


def test_shared_engine_contract_abstains_when_only_gist_support_is_retrieved(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="system",
            source_type="consolidation-summary",
            source_identity="consolidation-summary:gist-only-contract",
            content="Gist-only contract memory says deployment evidence requires original source inspection.",
            metadata={
                "summary": {
                    "kind": "abstractive_gist",
                    "source_evidence_cids": ["source-cid-for-gist-contract"],
                }
            },
            trust_tier=2,
            capability_tags=["consolidation-gist", "derived-summary"],
            access_policy={"tenant": tenant},
        )
    )

    result = engine.retrieve("gist-only contract deployment evidence", tenant)

    assert result.hits
    assert result.hits[0].id == cid
    assert result.abstained is True
    assert result.uncertainty_note == "Only gist-tier memory support was retrieved; inspect source evidence before answering."
    assert result.explain["gist_support"]["applied"] is True
    assert result.explain["gist_support"]["gist_hit_ids"] == [cid]


def test_shared_engine_contract_deep_search_abstains_on_summary_derived_graph_support(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    raw_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            source_identity="chat:deep-gist-derived-graph",
            content="Deep retrieval graph abstention requires original source inspection for generated summaries.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    summary_run = ConsolidationWorker(engine, gate_cases=[]).run_queue_payload(
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": [raw_cid],
            "passes": ["summarizer"],
        }
    )
    summary = next(item for item in summary_run.pass_results if item["name"] == "summarizer")["details"]

    result = engine.deep_search(raw_cid, tenant, filt={"min_trust_tier": 2})
    relation_hit = next(hit for hit in result.hits if hit.kind == "relation")

    assert result.hits
    assert any(hit.id == summary["summary_cid"] for hit in result.hits)
    assert relation_hit.metadata["predicate"] == "summary-derived-gist"
    assert relation_hit.metadata["source"] == raw_cid
    assert relation_hit.metadata["target"] == summary["summary_cid"]
    assert raw_cid in relation_hit.metadata["source_evidence_cids"]
    assert result.abstained is True
    assert result.uncertainty_note == "Only gist-tier memory support was retrieved; inspect source evidence before answering."
    assert result.explain["gist_support"]["applied"] is True
    assert set(result.explain["gist_support"]["gist_hit_ids"]) == {summary["summary_cid"], relation_hit.id}


def test_shared_engine_contract_abstains_on_trace_or_confabulation_risk_support(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    risk_tenant = f"{tenant}-risk"
    trace_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="system",
            source_type="statistical-trace",
            source_identity="statistical-trace:contract-alpha",
            content="Statistical trace contract alpha support requires source inspection.",
            metadata={"lifecycle": {"tier": "statistical_trace"}},
            trust_tier=2,
            capability_tags=["statistical-trace"],
            access_policy={"tenant": tenant},
        )
    )
    risk_cid = engine.append_evidence(
        Evidence(
            tenant_id=risk_tenant,
            user_id=user,
            actor="system",
            source_type="analysis-summary",
            source_identity="analysis-summary:contract-beta",
            content="Confabulation risk contract beta support requires source inspection.",
            metadata={"summary": {"kind": "extractive_summary", "confabulation_risk": True}},
            trust_tier=2,
            capability_tags=["derived-summary"],
            access_policy={"tenant": risk_tenant},
        )
    )

    trace_result = engine.retrieve("statistical trace contract alpha", tenant)
    risk_result = engine.retrieve("confabulation risk contract beta", risk_tenant)

    assert trace_result.hits[0].id == trace_cid
    assert trace_result.abstained is True
    assert trace_result.explain["gist_support"]["applied"] is True
    assert trace_result.explain["gist_support"]["gist_hit_ids"] == [trace_cid]
    assert risk_result.hits[0].id == risk_cid
    assert risk_result.abstained is True
    assert risk_result.explain["gist_support"]["applied"] is True
    assert risk_result.explain["gist_support"]["gist_hit_ids"] == [risk_cid]


def test_shared_engine_contract_summary_refresh_retires_superseded_gist(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    source_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Shared summary refresh source discusses durable consolidated memory.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    worker = ConsolidationWorker(
        engine,
        gate_cases=[],
        summarizer=_RotatingSummarizer(["obsolete amber synopsis", "current amber synopsis"]),
    )

    first = worker.run_queue_payload(
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": [source_cid],
            "passes": ["summarizer"],
        }
    )
    first_summary = next(item for item in first.pass_results if item["name"] == "summarizer")["details"]
    first_cid = first_summary["summary_cid"]
    second = worker.run_queue_payload(
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": [source_cid],
            "passes": ["summarizer"],
        }
    )
    second_summary = next(item for item in second.pass_results if item["name"] == "summarizer")["details"]
    second_cid = second_summary["summary_cid"]
    exported = engine.export_tenant(tenant)
    first_evidence = next(item for item in exported["evidence"] if item["cid"] == first_cid)
    second_evidence = next(item for item in exported["evidence"] if item["cid"] == second_cid)

    assert first_cid != second_cid
    assert second_summary["retired_summary_cids"] == [first_cid]
    assert first_evidence["metadata"]["summary"]["status"] == "retired"
    assert first_evidence["metadata"]["summary"]["superseded_by"] == second_cid
    assert first_evidence["metadata"]["summary"]["retired_by"] == "consolidation.summarizer"
    assert second_evidence["metadata"]["summary"]["status"] == "active"
    assert second_evidence["metadata"]["summary"]["source_fingerprint"] == second_summary["source_fingerprint"]

    stale_retrieval = engine.retrieve("obsolete amber synopsis", tenant)
    active_retrieval = engine.retrieve("current amber synopsis", tenant)

    assert first_cid not in {hit.id for hit in stale_retrieval.hits}
    assert second_cid in {hit.id for hit in active_retrieval.hits}


def test_shared_engine_contract_builds_raptor_summary_hierarchy(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    source_cids = [
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="chat",
                content=f"Raptor hierarchy source {index} preserves raw evidence provenance.",
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        for index in range(4)
    ]
    worker = ConsolidationWorker(engine, gate_cases=[])

    run = worker.run_queue_payload(
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": source_cids,
            "passes": ["summarizer"],
            "raptor_cluster_size": 2,
            "raptor_max_levels": 2,
        }
    )
    details = next(item for item in run.pass_results if item["name"] == "summarizer")["details"]
    hierarchy = details["hierarchy"]
    leaf_cids = hierarchy["levels"][0]["summary_cids"]
    root_cid = hierarchy["root_summary_cid"]
    exported = engine.export_tenant(tenant)
    summaries = {
        item["cid"]: item
        for item in exported["evidence"]
        if item["source_type"] == "consolidation-summary"
    }
    relation_edges = {
        (item["source"], item["target"])
        for item in exported["relations"]
        if item["predicate"] == "summary-derived-gist"
    }

    assert details["materialized"] is True
    assert hierarchy["enabled"] is True
    assert hierarchy["source_evidence_cids"] == source_cids
    assert [level["summary_count"] for level in hierarchy["levels"]] == [2, 1]
    assert len(leaf_cids) == 2
    assert root_cid == details["summary_cid"]
    assert set(summaries) == {*leaf_cids, root_cid}

    first_leaf_meta = summaries[leaf_cids[0]]["metadata"]["summary"]
    second_leaf_meta = summaries[leaf_cids[1]]["metadata"]["summary"]
    root_meta = summaries[root_cid]["metadata"]["summary"]

    assert first_leaf_meta["raptor_level"] == 1
    assert second_leaf_meta["raptor_level"] == 1
    assert root_meta["raptor_level"] == 2
    assert first_leaf_meta["source_evidence_cids"] == source_cids[:2]
    assert second_leaf_meta["source_evidence_cids"] == source_cids[2:]
    assert root_meta["source_evidence_cids"] == source_cids
    assert root_meta["source_summary_cids"] == leaf_cids
    assert root_meta["child_summary_cids"] == leaf_cids
    assert root_meta["confabulation_risk"] is True

    for leaf_cid in leaf_cids:
        leaf_sources = summaries[leaf_cid]["metadata"]["summary"]["source_evidence_cids"]
        assert all((source_cid, leaf_cid) in relation_edges for source_cid in leaf_sources)
        assert (leaf_cid, root_cid) in relation_edges

    root_retrieval = engine.retrieve(leaf_cids[0], tenant)
    root_hit = next(hit for hit in root_retrieval.hits if hit.id == root_cid)

    assert root_hit.metadata["summary"]["raptor_level"] == 2
    assert root_hit.metadata["summary"]["source_evidence_cids"] == source_cids
    assert root_hit.metadata["summary"]["source_summary_cids"] == leaf_cids
    assert root_retrieval.abstained is True
    assert root_cid in root_retrieval.explain["gist_support"]["gist_hit_ids"]


def test_shared_engine_contract_raptor_projection_recompute_refreshes_leaf_and_root(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    source_cids = [
        engine.append_evidence(
            Evidence(
                tenant_id=tenant,
                user_id=user,
                actor="user",
                source_type="chat",
                content=f"Raptor recompute source {index} participates in summary refresh.",
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        for index in range(4)
    ]
    run = ConsolidationWorker(engine, gate_cases=[]).run_queue_payload(
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": source_cids,
            "passes": ["summarizer"],
            "raptor_cluster_size": 2,
            "raptor_max_levels": 2,
        }
    )
    details = next(item for item in run.pass_results if item["name"] == "summarizer")["details"]
    leaf_cids = details["hierarchy"]["levels"][0]["summary_cids"]
    root_cid = details["hierarchy"]["root_summary_cid"]
    exported = engine.export_tenant(tenant)
    relation_ids = {
        (item["source"], item["target"]): item["id"]
        for item in exported["relations"]
        if item["predicate"] == "summary-derived-gist"
    }
    changed_raw_cid = source_cids[0]
    changed_leaf_cid = leaf_cids[0]
    required_relation_ids = {
        relation_ids[(changed_raw_cid, changed_leaf_cid)],
        relation_ids[(changed_leaf_cid, root_cid)],
    }
    queue = InProcessQueue()
    handlers = RuntimeJobHandlers(engine, queue)

    recompute = handlers.run_projection_recompute(
        {
            "tenant_id": tenant,
            "user_id": user,
            "branch": "main",
            "changed_evidence_cids": [changed_raw_cid],
            "passes": ["summarizer"],
        }
    )
    jobs = list(queue.jobs.values())

    assert recompute.kind == PROJECTION_RECOMPUTE_JOB
    assert {changed_raw_cid, changed_leaf_cid, root_cid}.issubset(recompute.details["affected_evidence_cids"])
    assert required_relation_ids.issubset(recompute.details["affected_projections"]["relations"])
    assert recompute.details["queued_consolidation_jobs"] == [jobs[0].id]
    assert len(jobs) == 1
    assert jobs[0].kind == CONSOLIDATE_EVIDENCE_JOB
    assert jobs[0].payload["source_evidence_cids"] == [changed_raw_cid]
    assert jobs[0].payload["passes"] == ["summarizer"]
    assert jobs[0].payload["trigger"] == PROJECTION_RECOMPUTE_JOB


def test_shared_engine_contract_forget_source_invalidates_summary_gist(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    source_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="chat",
            content="Shared derived forget source should not survive inside a gist.",
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    worker = ConsolidationWorker(
        engine,
        gate_cases=[],
        summarizer=_RotatingSummarizer(["derived forget amber synopsis"]),
    )

    run = worker.run_queue_payload(
        {
            "tenant_id": tenant,
            "branch": "main",
            "source_evidence_cids": [source_cid],
            "passes": ["summarizer"],
        }
    )
    summary = next(item for item in run.pass_results if item["name"] == "summarizer")["details"]
    summary_cid = summary["summary_cid"]
    relation_ids = set(summary["derived_relation_ids"])

    result = engine.forget(tenant, source_cid)
    exported = engine.export_tenant(tenant)
    retrieval = engine.retrieve("derived forget amber synopsis", tenant)

    assert result["erased"] is True
    assert summary_cid in result["propagated"]["erased_derived_evidence"]
    assert summary_cid not in {hit.id for hit in retrieval.hits}
    assert all(
        item["id"] not in relation_ids or item.get("valid_to") is not None
        for item in exported["relations"]
    )


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


def test_shared_engine_contract_direct_primitives_honor_k_limit(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cids = [
        _append_evidence(
            engine,
            tenant,
            user,
            f"Shared primitive budget cap evidence {idx} repeats the jasper needle phrase.",
        )
        for idx in range(3)
    ]
    assertion_ids = [
        engine.upsert_assertion(
            Assertion(
                tenant_id=tenant,
                user_id=user,
                subject=f"shared primitive budget subject {idx}",
                predicate="mentions",
                object="jasper needle",
                confidence=0.9,
                source_evidence_cids=[cids[idx]],
                trust_tier=0,
                access_policy={"tenant": tenant},
            )
        )
        for idx in range(3)
    ]
    relation_ids = [
        engine.add_relation(
            Relation(
                tenant_id=tenant,
                source="shared primitive budget seed",
                predicate=f"points_to_{idx}",
                target=f"primitive budget target {idx}",
                source_evidence_cids=[cids[idx]],
                access_policy={"tenant": tenant},
            )
        )
        for idx in range(3)
    ]
    filt = {"tenant_id": tenant, "branch": "main", "max_trust_tier": 3, "max_sensitivity": 2}

    lexical = engine.lexical_search("jasper needle", 1, filt)
    dense = engine.vector_search("jasper needle", 1, filt)
    graph = engine.graph_ppr(["shared primitive budget seed"], 1, tenant_id=tenant, branch="main")

    assert len(lexical) == 1
    assert len(dense) == 1
    assert len(graph) == 1
    assert lexical[0].id in {*cids, *assertion_ids}
    assert dense[0].id in {*cids, *assertion_ids}
    assert graph[0].id in relation_ids
    assert lexical[0].tenant_id == dense[0].tenant_id == graph[0].tenant_id == tenant
    assert lexical[0].branch == dense[0].branch == graph[0].branch == "main"
    assert lexical[0].channel in {"lexical", "postgres_fts"}
    assert dense[0].channel in {"dense_hash", "postgres_pgvector"}
    assert graph[0].channel in {"graph_ppr", "postgres_graph_ppr"}


def test_shared_engine_contract_graph_ppr_skips_expired_relations_by_default(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, _user = engine_bundle
    now = datetime.now(UTC)
    expired_from = now - timedelta(days=3)
    expired_to = now - timedelta(days=2)
    active_from = now - timedelta(days=1)
    seed = f"temporal seed {uuid4()}"
    expired_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source=seed,
            predicate="expired_edge",
            target="expired graph target",
            valid_from=expired_from,
            valid_to=expired_to,
            access_policy={"tenant": tenant},
        )
    )
    active_id = engine.add_relation(
        Relation(
            tenant_id=tenant,
            source=seed,
            predicate="active_edge",
            target="active graph target",
            valid_from=active_from,
            access_policy={"tenant": tenant},
        )
    )

    current_graph = engine.graph_ppr([seed], 10, tenant_id=tenant, branch="main")
    historical_graph = engine.graph_ppr([seed], 10, as_of=expired_from + timedelta(hours=1), tenant_id=tenant, branch="main")

    assert active_id in {hit.id for hit in current_graph}
    assert expired_id not in {hit.id for hit in current_graph}
    assert expired_id in {hit.id for hit in historical_graph}
    assert active_id not in {hit.id for hit in historical_graph}


def test_shared_engine_contract_justifications_and_contradictions(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    cid = _append_evidence(engine, tenant, user, "Shared justification evidence supports conflict tracking.")
    first_assertion = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="Shared conflict subject",
            predicate="has_answer",
            object="alpha",
            confidence=0.7,
            source_evidence_cids=[cid],
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    second_assertion = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="Shared conflict subject",
            predicate="has_answer",
            object="beta",
            confidence=0.6,
            source_evidence_cids=[cid],
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )

    justification_id = engine.add_justification(
        Justification(
            tenant_id=tenant,
            assertion_id=first_assertion,
            evidence_cids=[cid],
            rule="shared-support-rule",
            dependency_ids=[second_assertion],
            kind="support",
            label={"contract": "shared"},
            hypothesis_prob=0.7,
        )
    )
    contradiction_id = engine.add_contradiction(Contradiction(tenant_id=tenant, a=first_assertion, b=second_assertion))
    duplicate_id = engine.add_contradiction(Contradiction(tenant_id=tenant, a=second_assertion, b=first_assertion))
    exported = engine.export_tenant(tenant)
    justification = next(item for item in exported["justifications"] if item["id"] == justification_id)
    contradiction = next(item for item in exported["contradictions"] if item["id"] == contradiction_id)

    assert duplicate_id == contradiction_id
    assert justification["assertion_id"] == first_assertion
    assert justification["evidence_cids"] == [cid]
    assert justification["dependency_ids"] == [second_assertion]
    assert justification["label"] == {"contract": "shared"}
    assert justification["hypothesis_prob"] == 0.7
    assert contradiction["a"] == first_assertion
    assert contradiction["b"] == second_assertion
    assert contradiction["status"] == "open"


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


def test_shared_engine_contract_branch_names_are_tenant_scoped(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    other_tenant = f"{tenant}-other"
    other_user = f"{user}-other"
    branch = f"shared-tenant-branch-{uuid4()}"
    tenant_cid = _append_evidence(engine, tenant, user, "Tenant one branch snapshot should be isolated.")
    _branch(engine, branch, tenant)
    other_cid = _append_evidence(engine, other_tenant, other_user, "Tenant two branch snapshot should be isolated.")
    _branch(engine, branch, other_tenant)

    assert engine.get_evidence(tenant, tenant_cid, branch=branch) is not None
    assert engine.get_evidence(other_tenant, other_cid, branch=branch) is not None
    branches = engine.export_all()["branches"]
    assert any(item["tenant_id"] == tenant and item["name"] == branch for item in branches)
    assert any(item["tenant_id"] == other_tenant and item["name"] == branch for item in branches)

    _discard(engine, branch, tenant)

    branches_after_discard = engine.export_all()["branches"]
    assert engine.get_evidence(tenant, tenant_cid, branch=branch) is None
    assert engine.get_evidence(other_tenant, other_cid, branch=branch) is not None
    assert not any(item["tenant_id"] == tenant and item["name"] == branch for item in branches_after_discard)
    assert any(item["tenant_id"] == other_tenant and item["name"] == branch for item in branches_after_discard)


def test_shared_engine_contract_branch_inherits_explicit_source_branch(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    source_branch = f"shared-source-branch-{uuid4()}"
    child_branch = f"shared-child-branch-{uuid4()}"
    main_cid = _append_evidence(engine, tenant, user, "Main evidence should flow into explicit source branch children.")
    _branch(engine, source_branch, tenant)
    source_only_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Source branch evidence should flow only through explicit source branch inheritance.",
        branch=source_branch,
    )
    assertion_subject = f"source branch assertion {uuid4()}"
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            branch=source_branch,
            subject=assertion_subject,
            predicate="stays_on",
            object="explicit source branch",
            source_evidence_cids=[source_only_cid],
            trust_tier=0,
            access_policy={"tenant": tenant},
            status="active",
        ),
        branch=source_branch,
    )
    engine.add_relation(
        Relation(
            tenant_id=tenant,
            branch=source_branch,
            source="explicit source branch seed",
            predicate="inherits_to",
            target="explicit source branch child",
            source_evidence_cids=[source_only_cid],
            access_policy={"tenant": tenant},
        ),
        branch=source_branch,
    )

    _branch(engine, child_branch, tenant, frm=source_branch)
    branches = engine.export_all()["branches"]
    exported = engine.export_tenant(tenant)

    assert engine.get_evidence(tenant, main_cid, branch=child_branch) is not None
    assert engine.get_evidence(tenant, source_only_cid, branch=child_branch) is not None
    assert engine.get_evidence(tenant, source_only_cid, branch="main") is None
    assert any(
        item["subject"] == assertion_subject
        and item["predicate"] == "stays_on"
        and item["object"] == "explicit source branch"
        and item["branch"] == child_branch
        and item["source_evidence_cids"] == [source_only_cid]
        for item in exported["assertions"]
    )
    assert not any(
        item["subject"] == assertion_subject and item["branch"] == "main"
        for item in exported["assertions"]
    )
    assert any(
        item["source"] == "explicit source branch seed"
        and item["predicate"] == "inherits_to"
        and item["target"] == "explicit source branch child"
        and item["branch"] == child_branch
        and item["source_evidence_cids"] == [source_only_cid]
        for item in exported["relations"]
    )
    assert not any(
        item["source"] == "explicit source branch seed" and item["branch"] == "main"
        for item in exported["relations"]
    )
    assert any(
        item["tenant_id"] == tenant
        and item["name"] == child_branch
        and item.get("from_branch") == source_branch
        for item in branches
    )


def test_shared_engine_contract_discard_prunes_branch_tms_rows(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    branch = f"shared-discard-tms-{uuid4()}"
    _branch(engine, branch, tenant)
    cid = _append_evidence(
        engine,
        tenant,
        user,
        "Branch discard should prune abandoned TMS rows.",
        branch=branch,
    )
    first_assertion = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            branch=branch,
            subject=f"discarded branch first {uuid4()}",
            predicate="is",
            object="temporary",
            source_evidence_cids=[cid],
            status="active",
        ),
        branch=branch,
    )
    second_assertion = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            branch=branch,
            subject=f"discarded branch second {uuid4()}",
            predicate="is",
            object="temporary",
            source_evidence_cids=[cid],
            status="active",
        ),
        branch=branch,
    )
    justification_id = engine.add_justification(
        Justification(
            tenant_id=tenant,
            assertion_id=first_assertion,
            evidence_cids=[cid],
            dependency_ids=[second_assertion],
            rule="shared discard branch tms",
        )
    )
    contradiction_id = engine.add_contradiction(
        Contradiction(tenant_id=tenant, a=first_assertion, b=second_assertion)
    )

    before = engine.export_tenant(tenant)
    assert any(item["id"] == justification_id for item in before["justifications"])
    assert any(item["id"] == contradiction_id for item in before["contradictions"])

    _discard(engine, branch, tenant)
    exported = engine.export_tenant(tenant)

    assert engine.get_evidence(tenant, cid, branch=branch) is None
    assert all(item["id"] not in {first_assertion, second_assertion} for item in exported["assertions"])
    assert all(item["id"] != justification_id for item in exported["justifications"])
    assert all(item["id"] != contradiction_id for item in exported["contradictions"])


def test_shared_engine_contract_discard_prunes_orphaned_tms_dependencies(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    main_cid = _append_evidence(engine, tenant, user, "Main assertion survives discarded dependency branch.")
    main_assertion = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject=f"surviving main assertion {uuid4()}",
            predicate="is",
            object="durable",
            source_evidence_cids=[main_cid],
            status="active",
        )
    )
    branch = f"shared-discard-dependency-{uuid4()}"
    _branch(engine, branch, tenant)
    branch_cid = _append_evidence(
        engine,
        tenant,
        user,
        "Branch dependency should be pruned from surviving TMS rows.",
        branch=branch,
    )
    dependency_assertion = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            branch=branch,
            subject=f"discarded dependency assertion {uuid4()}",
            predicate="is",
            object="temporary",
            source_evidence_cids=[branch_cid],
            status="active",
        ),
        branch=branch,
    )
    justification_id = engine.add_justification(
        Justification(
            tenant_id=tenant,
            assertion_id=main_assertion,
            evidence_cids=[main_cid],
            dependency_ids=[dependency_assertion],
            rule="shared discard orphan dependency",
        )
    )
    contradiction_id = engine.add_contradiction(
        Contradiction(tenant_id=tenant, a=main_assertion, b=dependency_assertion)
    )

    _discard(engine, branch, tenant)
    exported = engine.export_tenant(tenant)

    assert any(item["id"] == main_assertion and item["branch"] == "main" for item in exported["assertions"])
    assert all(item["id"] != dependency_assertion for item in exported["assertions"])
    assert all(item["id"] != justification_id for item in exported["justifications"])
    assert all(item["id"] != contradiction_id for item in exported["contradictions"])


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


def test_shared_engine_contract_tombstoned_evidence_cannot_be_replayed(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    evidence = Evidence(
        tenant_id=tenant,
        user_id=user,
        actor="user",
        source_type="shared-replay",
        content="Tombstoned evidence replay must remain forgotten.",
        content_pointer="objects/shared/replay.txt",
        metadata={"case": "tombstone-replay"},
        access_policy={"tenant": tenant},
    )
    cid = engine.append_evidence(evidence)

    result = engine.forget(tenant, cid, requested_by=user, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    replay_cid = engine.append_evidence(evidence)
    exported = engine.export_tenant(tenant)

    assert result["erased"] is True
    assert replay_cid == cid
    assert engine.get_evidence(tenant, cid) is None
    assert all(item["cid"] != cid for item in exported["evidence"])


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
    exported_all = engine.export_all()

    assert cid not in {hit.id for hit in before.hits}
    assert cid in {hit.id for hit in after.hits}
    assert report.evidence_added >= 1
    assert report.assertions_added >= 1
    assert report.relations_added >= 1
    assert any(item["cid"] == cid and item["branch"] == "main" for item in exported["evidence"])
    assert any(item["id"] == assertion_id and item["branch"] == "main" for item in exported["assertions"])
    assert any(item["id"] == relation_id and item["branch"] == "main" for item in exported["relations"])
    assert any(
        item["from_branch"] == branch
        and item["into_branch"] == "main"
        and item["evidence_added"] >= 1
        and item["assertions_added"] >= 1
        and item["relations_added"] >= 1
        for item in exported_all["merge_log"]
    )


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


def test_shared_audit_log_records_actor_source_tier_and_diff_for_every_write(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="tool",
            source_type="workflow-log",
            source_identity="git:memory-source-truth.md",
            content="Shared audit contract records source tier and diff.",
            trust_tier=2,
            capability_tags=["tool-import", "signed"],
            access_policy={"tenant": tenant},
        )
    )
    assertion_id = engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="audit contract",
            predicate="records",
            object="source tier and diff",
            confidence=0.91,
            source_evidence_cids=[cid],
            status="active",
            trust_tier=2,
            access_policy={"tenant": tenant},
        )
    )
    preference_id = engine.add_preference(
        Preference(
            tenant_id=tenant,
            user_id=user,
            category="workflow",
            statement="Audit writes must retain source tier and diff metadata.",
            explicit=True,
            source_evidence_cids=[cid],
        )
    )

    engine.forget(tenant, cid, requested_by=user, erasure_mode=ErasureMode.HARD_DELETE_LEGAL)
    audit_log = engine.export_tenant(tenant)["audit_log"]

    assert audit_log
    for item in audit_log:
        assert "actor" in item
        assert "source" in item
        assert "trust_tier" in item
        assert "capability_tags" in item
        assert isinstance(item["diff"], dict)

    evidence_audit = next(item for item in audit_log if item["op"] == "append_evidence" and item["target_id"] == cid)
    assert evidence_audit["actor"] == "tool"
    assert evidence_audit["source"] == "workflow-log"
    assert evidence_audit["trust_tier"] == 2
    assert sorted(evidence_audit["capability_tags"]) == ["signed", "tool-import"]
    assert evidence_audit["diff"]["source_identity"] == "git:memory-source-truth.md"

    assertion_audit = next(item for item in audit_log if item["op"] == "upsert_assertion" and item["target_id"] == assertion_id)
    assert assertion_audit["source"] == "assertion"
    assert assertion_audit["trust_tier"] == 2
    assert assertion_audit["diff"]["source_evidence_cids"] == [cid]

    preference_audit = next(item for item in audit_log if item["op"] == "add_preference" and item["target_id"] == preference_id)
    assert preference_audit["source"] == "preference"
    assert preference_audit["trust_tier"] == 0
    assert preference_audit["diff"]["source_evidence_cids"] == [cid]

    forget_audit = next(item for item in audit_log if item["op"] == "forget" and item["target_id"] == cid)
    assert forget_audit["actor"] == user
    assert forget_audit["source"] == "workflow-log"
    assert forget_audit["trust_tier"] == 2
    assert sorted(forget_audit["capability_tags"]) == ["signed", "tool-import"]


def _append_evidence(
    engine: Any,
    tenant: str,
    user: str,
    content: str,
    *,
    trust_tier: int = 0,
    sensitivity: int = 0,
    metadata: dict[str, Any] | None = None,
    branch: str = "main",
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
        ),
        branch=branch,
    )


def _exported_assertion(engine: Any, tenant: str, assertion_id: str) -> dict[str, Any]:
    for assertion in engine.export_tenant(tenant)["assertions"]:
        if assertion["id"] == assertion_id:
            return assertion
    raise AssertionError(f"missing exported assertion {assertion_id}")


def _branch(engine: Any, name: str, tenant: str, *, frm: str = "main") -> None:
    try:
        engine.branch(name, frm=frm, tenant_id=tenant)
    except TypeError:
        engine.branch(name, frm=frm)


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
