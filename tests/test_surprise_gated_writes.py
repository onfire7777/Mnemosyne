"""Surprise-gated write closure (task 15-01-04).

Surprise may change write priority. It must never raise write authority past
security, corroboration, regression, mutation-budget, erasure, or capability
checks. Held-out eval labels stay in the G0 helper and never enter ingestion.
"""

from __future__ import annotations

from typing import Any

from eval.g0.write_gating import (
    FAILURE_CLASSES,
    HELD_OUT_LABEL_KEYS,
    run_write_gating_eval,
)
from mnemosyne.consolidation import ConsolidationWorker, MutationRailBudget
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import RegressionCase
from mnemosyne.ingestion import IngestRequest, IngestionPipeline
from mnemosyne.models import Assertion, Evidence
from mnemosyne.queue import InProcessQueue
from mnemosyne.security import CapabilityDecision, SecurityPolicy, TrustTier


TENANT = "surprise-gate-tenant"
USER = "surprise-gate-user"
FACT_A = "The amber harbor beacon is cerulean."
FACT_B = "Independent note: amber harbor beacon is cerulean."


class _DenyPromoteSecurity(SecurityPolicy):
    def authorize_write(
        self,
        operation: str,
        role: str = "consolidator",
        source_trust_tier: int = 0,
        destructive: bool = False,
        target_sink: str | None = None,
        source_capability_tags: Any = None,
    ) -> CapabilityDecision:
        if operation == "promote_candidate":
            return CapabilityDecision(False, "security_denied", role, source_trust_tier, operation)
        return super().authorize_write(
            operation,
            role,
            source_trust_tier,
            destructive=destructive,
            target_sink=target_sink,
            source_capability_tags=source_capability_tags,
        )


def _passing_case() -> RegressionCase:
    return RegressionCase(
        id="case-cerulean",
        signature="amber harbor beacon",
        query="amber harbor beacon",
        expected_substring="cerulean",
        protected=True,
    )


def _worker(
    engine: LocalMemoryEngine,
    *,
    security: SecurityPolicy | None = None,
    max_supersession_rate: float | None = None,
    gate_cases: list[RegressionCase] | None = None,
) -> ConsolidationWorker:
    return ConsolidationWorker(
        engine,
        gate_cases if gate_cases is not None else [_passing_case()],
        consolidation_min_steps=0,
        security=security,
        max_supersession_rate=max_supersession_rate,
    )


def _ingest(
    engine: LocalMemoryEngine,
    content: str,
    *,
    actor: str = "user",
    source_type: str = "chat",
    metadata: dict[str, Any] | None = None,
    capability_tags: list[str] | None = None,
    queue: InProcessQueue | None = None,
) -> tuple[Any, InProcessQueue]:
    queue = queue or InProcessQueue()
    pipeline = IngestionPipeline(engine, queue=queue)
    result = pipeline.ingest(
        IngestRequest(
            tenant_id=TENANT,
            user_id=USER,
            actor=actor,
            source_type=source_type,
            content=content,
            metadata=dict(metadata or {}),
            capability_tags=list(capability_tags or []),
        )
    )
    return result, queue


def _append(
    engine: LocalMemoryEngine,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
    trust_tier: int = 0,
    capability_tags: list[str] | None = None,
    actor: str = "user",
    source_type: str = "chat",
) -> str:
    return engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor=actor,  # type: ignore[arg-type]
            source_type=source_type,
            content=content,
            metadata=dict(metadata or {}),
            trust_tier=trust_tier,
            capability_tags=list(capability_tags or []),
            access_policy={"tenant": TENANT},
        )
    )


def _promoted(run: Any) -> bool:
    return any(bool(item.get("promoted")) for item in run.candidate_results)


def _pass_details(run: Any, name: str) -> dict[str, Any]:
    for item in run.pass_results:
        if item["name"] == name:
            return item["details"]
    raise AssertionError(f"missing pass {name}")


def test_trusted_high_surprise_is_prioritized_but_does_not_grant_authority() -> None:
    engine = LocalMemoryEngine()
    low = _append(
        engine,
        "Low surprise archival harbor note is quiet.",
        metadata={"consolidation": {"importance": 0.5, "novelty": 0.5, "surprise": 0.1, "reward": 0.5}},
    )
    high = _append(
        engine,
        FACT_A,
        metadata={"consolidation": {"importance": 0.5, "novelty": 0.5, "surprise": 0.9, "reward": 0.5, "prediction_error": 0.9}},
    )
    corroborating = _append(
        engine,
        FACT_B,
        metadata={"consolidation": {"importance": 0.5, "novelty": 0.5, "surprise": 0.9, "reward": 0.5, "prediction_error": 0.9}},
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "branch": "main",
            "source_evidence_cids": [low, high, corroborating],
            "passes": ["replayer", "extractor", "resolver", "belief_reviser", "promotion_gate"],
            "prediction_error": {"score": 0.91, "gate": "promote_to_consolidation"},
            "replay_scores": {
                low: {"importance": 0.5, "novelty": 0.5, "surprise": 0.1, "reward": 0.5},
                high: {"importance": 0.5, "novelty": 0.5, "surprise": 0.9, "reward": 0.5},
                corroborating: {"importance": 0.5, "novelty": 0.5, "surprise": 0.9, "reward": 0.5},
            },
        }
    )
    replayer = _pass_details(run, "replayer")
    assert replayer["selected_cids"][0] in {high, corroborating}
    assert replayer["selected_cids"][-1] == low
    assert _pass_details(run, "prediction_error_gate")["gate"] == "promote_to_consolidation"
    assert _promoted(run) is True


def test_high_surprise_cannot_bypass_security() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(engine, FACT_A, metadata={"consolidation": {"prediction_error": 1.0}})
    cid_b = _append(engine, FACT_B, metadata={"consolidation": {"prediction_error": 1.0}})
    run = _worker(engine, security=_DenyPromoteSecurity()).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
        }
    )
    assert _promoted(run) is False
    assert any("security_denied" in str(item.get("failed_cases")) for item in run.candidate_results)


def test_high_surprise_cannot_bypass_corroboration() -> None:
    engine = LocalMemoryEngine()
    cid = _append(engine, FACT_A, metadata={"consolidation": {"prediction_error": 1.0}})
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid],
            "prediction_error": {"score": 1.0},
        }
    )
    assert _promoted(run) is False
    assert any(
        "fact_external_corroboration" in str(item.get("failed_cases")) for item in run.candidate_results
    )


def test_high_surprise_cannot_bypass_regression() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(engine, "The amber harbor beacon is scarlet.", metadata={"consolidation": {"prediction_error": 1.0}})
    cid_b = _append(
        engine,
        "Independent note: amber harbor beacon is scarlet.",
        metadata={"consolidation": {"prediction_error": 1.0}},
        source_type="note",
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
        }
    )
    assert _promoted(run) is False
    assert any(item.get("protected_regressions") for item in run.candidate_results)


def test_high_surprise_cannot_bypass_mutation_budget() -> None:
    engine = LocalMemoryEngine()
    for index in range(4):
        cid = _append(engine, f"Entity {index} value is alpha.")
        engine.upsert_assertion(
            Assertion(
                tenant_id=TENANT,
                subject=f"Entity {index}",
                predicate="value is",
                object="alpha",
                source_evidence_cids=[cid],
                status="active",
                trust_tier=int(TrustTier.NORMAL),
                access_policy={"tenant": TENANT},
            )
        )
    replacements = [
        _append(
            engine,
            f"Entity {index} value is beta.",
            metadata={"consolidation": {"prediction_error": 1.0}},
        )
        for index in range(4)
    ]
    before = {
        row["id"]
        for row in engine.export_tenant(TENANT)["assertions"]
        if row.get("status") == "active" and row.get("branch", "main") == "main"
    }
    run = _worker(engine, max_supersession_rate=0.0, gate_cases=[]).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": replacements,
            "prediction_error": {"score": 1.0},
            "passes": ["extractor", "resolver", "belief_reviser", "promotion_gate"],
        }
    )
    after = {
        row["id"]
        for row in engine.export_tenant(TENANT)["assertions"]
        if row.get("status") == "active" and row.get("branch", "main") == "main"
    }
    rails = _pass_details(run, "mutation_rails")
    assert len(before - after) == 0
    assert rails["supersessions_allowed"] == 0
    assert any(item["rail"] == "max_supersession_rate" for item in rails["violations"]) or not _promoted(run)


def test_high_surprise_cannot_bypass_erasure() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(engine, FACT_A, metadata={"consolidation": {"prediction_error": 1.0}})
    cid_b = _append(engine, FACT_B, metadata={"consolidation": {"prediction_error": 1.0}}, source_type="note")
    assert engine.forget(TENANT, cid_a, requested_by="operator")["erased"] is True
    assert engine.forget(TENANT, cid_b, requested_by="operator")["erased"] is True
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
        }
    )
    assert run.evidence_seen == 0
    assert _promoted(run) is False
    assert cid_a in run.skipped or cid_b in run.skipped


def test_high_surprise_cannot_bypass_capability() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(
        engine,
        FACT_A,
        metadata={"consolidation": {"prediction_error": 1.0}},
        capability_tags=["data-only", "no-write-authority"],
    )
    cid_b = _append(
        engine,
        FACT_B,
        metadata={"consolidation": {"prediction_error": 1.0}},
        capability_tags=["data-only", "no-write-authority"],
        source_type="note",
    )
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 1.0},
            "capability_tags": ["data-only", "no-write-authority"],
        }
    )
    assert "source_marked_data_only" in run.skipped
    assert _promoted(run) is False


def test_low_surprise_is_metadata_only() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(engine, FACT_A, metadata={"consolidation": {"prediction_error": 0.0}})
    cid_b = _append(engine, FACT_B, metadata={"consolidation": {"prediction_error": 0.0}}, source_type="note")
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": 0.0},
            "passes": ["replayer", "extractor", "resolver", "belief_reviser", "forgetter"],
        }
    )
    gate = _pass_details(run, "prediction_error_gate")
    assert gate["gate"] == "low_prediction_error_metadata_only"
    assert gate["score"] == 0.0
    assert "low_prediction_error_metadata_only" in run.skipped
    assert _promoted(run) is False
    by_pass = {item["name"]: item for item in run.pass_results}
    assert by_pass["extractor"]["status"] == "skipped"
    assert by_pass["forgetter"]["status"] in {"complete", "skipped"}


def test_malformed_surprise_never_raises_authority() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(engine, FACT_A)
    cid_b = _append(engine, FACT_B, source_type="note")
    run = _worker(engine).run_queue_payload(
        {
            "tenant_id": TENANT,
            "source_evidence_cids": [cid_a, cid_b],
            "prediction_error": {"score": "not-a-number"},
            "replay_scores": {
                cid_a: {"importance": 1.0, "novelty": 1.0, "surprise": "bad", "reward": 1.0},
                cid_b: {"importance": 1.0, "novelty": 1.0, "surprise": float("nan"), "reward": 1.0},
            },
        }
    )
    gate = _pass_details(run, "prediction_error_gate")
    assert gate["gate"] == "low_prediction_error_metadata_only"
    assert gate["score"] == 0.0
    assert _promoted(run) is False
    scores = {row["cid"]: row["surprise"] for row in _pass_details(run, "replayer")["scores"]}
    assert scores[cid_a] == 0.0
    assert scores[cid_b] == 0.0


def test_untrusted_surprise_never_raises_authority() -> None:
    engine = LocalMemoryEngine()
    result, queue = _ingest(
        engine,
        FACT_A,
        actor="external",
        source_type="web",
        metadata={"surprise": 1.0, "importance": 1.0, "novelty": 1.0, "reward": 1.0},
    )
    job = queue.lease("consolidate_evidence")
    ev = engine.get_evidence(TENANT, result.cid)
    assert ev is not None
    assert ev.trust_tier == int(TrustTier.UNTRUSTED_EXTERNAL)
    assert ev.metadata["write_priority"]["score"] <= ev.metadata["write_priority"]["trust_cap"]
    assert ev.metadata["write_priority"]["trust_cap"] == 0.2
    assert job is not None
    run = _worker(engine).run_queue_payload(job.payload)
    assert "source_marked_data_only" in run.skipped
    assert _promoted(run) is False


def test_client_injected_prediction_error_cannot_override_computed_signal() -> None:
    engine = LocalMemoryEngine()
    result, queue = _ingest(
        engine,
        "Novel surprise-gated write probe should compute its own prediction error.",
        metadata={
            "consolidation": {
                "prediction_error": 0.0,
                "prediction_error_gate": "low_prediction_error_metadata_only",
                "held_out_label": "should_write",
            },
            "should_write": True,
            "held_out_label": "should_write",
            "surprise": 1.0,
        },
    )
    ev = engine.get_evidence(TENANT, result.cid)
    job = queue.lease("consolidate_evidence")
    assert ev is not None
    assert job is not None
    computed = job.payload["prediction_error"]["score"]
    assert ev.metadata["consolidation"]["prediction_error"] == computed
    assert ev.metadata["consolidation"]["prediction_error_gate"] == job.payload["prediction_error"]["gate"]
    leaked = set(ev.metadata) & HELD_OUT_LABEL_KEYS
    leaked.update(set(ev.metadata.get("consolidation") or {}) & HELD_OUT_LABEL_KEYS)
    assert not leaked
    run = _worker(engine).run_queue_payload(job.payload)
    assert _pass_details(run, "prediction_error_gate")["score"] == computed


def test_replay_is_stable() -> None:
    engine = LocalMemoryEngine()
    cid_a = _append(
        engine,
        "Stable replay alpha note.",
        metadata={"consolidation": {"importance": 0.4, "novelty": 0.8, "surprise": 0.6, "reward": 0.5}},
    )
    cid_b = _append(
        engine,
        "Stable replay beta note.",
        metadata={"consolidation": {"importance": 0.7, "novelty": 0.3, "surprise": 0.9, "reward": 0.4}},
    )
    payload = {
        "tenant_id": TENANT,
        "source_evidence_cids": [cid_a, cid_b],
        "passes": ["replayer"],
        "prediction_error": {"score": 0.6},
        "replay_scores": {
            cid_a: {"importance": 0.4, "novelty": 0.8, "surprise": 0.6, "reward": 0.5},
            cid_b: {"importance": 0.7, "novelty": 0.3, "surprise": 0.9, "reward": 0.4},
        },
    }
    first = _worker(engine, gate_cases=[]).run_queue_payload(payload)
    second = _worker(engine, gate_cases=[]).run_queue_payload(payload)
    assert _pass_details(first, "replayer") == _pass_details(second, "replayer")
    assert first.to_dict()["pass_results"][0] == second.to_dict()["pass_results"][0]


def test_write_gating_eval_exposes_confusion_counts_without_leaking_labels() -> None:
    first = run_write_gating_eval()
    second = run_write_gating_eval()
    assert first["schema_version"] == "g0.write_gating.v1"
    assert first["metric"] == "write_precision_recall"
    confusion = first["confusion"]
    denominators = first["denominators"]
    assert set(confusion) == {"tp", "fp", "tn", "fn"}
    assert all(isinstance(confusion[key], int) and confusion[key] >= 0 for key in confusion)
    assert denominators["total"] == sum(confusion.values()) == first["total_cases"]
    assert denominators["precision"] == confusion["tp"] + confusion["fp"]
    assert denominators["recall"] == confusion["tp"] + confusion["fn"]
    assert denominators["positive"] == confusion["tp"] + confusion["fn"]
    assert denominators["negative"] == confusion["tn"] + confusion["fp"]
    assert set(first["failure_classes"]) == set(FAILURE_CLASSES)
    assert set(first["failure_classes"]) == {
        "security",
        "corroboration",
        "regression",
        "mutation_budget",
        "erasure",
        "capability",
        "low_surprise_metadata_only",
        "malformed_surprise",
        "untrusted_surprise",
    }
    assert first["passed"] is True
    assert first["precision"] == 1.0
    assert first["recall"] == 1.0
    assert {row["case_id"] for row in first["rows"]} == {row["case_id"] for row in second["rows"]}
    assert first["confusion"] == second["confusion"]
    assert first["failure_classes"] == second["failure_classes"]
    leaked = first.get("ingested_label_keys") or []
    assert leaked == []
    for row in first["rows"]:
        assert "held_out_label" not in (row.get("ingest_metadata") or {})
        assert row["failure_class"] in {None, *FAILURE_CLASSES}


def test_mutation_rail_budget_object_still_clamps_when_surprise_is_maxed() -> None:
    budget = MutationRailBudget(
        tenant_id=TENANT,
        branch="main",
        max_supersession_rate=0.0,
        max_prune_fraction_per_pass=0.0,
        active_fact_ids={"fact-a", "fact-b"},
        active_memory_cids={"cid-a", "cid-b"},
    )
    assert budget.supersessions_allowed == 0
    assert budget.try_consume_prune("cid-a", kind="test") is False
    assert budget.violations
