"""Warm-loop consolidation worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.models import Assertion
from mnemosyne.security import SecurityPolicy

CONSOLIDATE_EVIDENCE_JOB = "consolidate_evidence"
DEFAULT_CONSOLIDATION_PASSES = [
    "replayer",
    "extractor",
    "resolver",
    "belief_reviser",
    "skill_inducer",
    "lesson_distiller",
    "summarizer",
    "forgetter",
    "embedder",
    "promotion_gate",
    "user_model_updater",
]


@dataclass(slots=True)
class ConsolidationJob:
    tenant_id: str
    signature: str
    query: str
    candidate_subject: str
    candidate_predicate: str
    candidate_object: str
    source_evidence_cids: list[str]
    confidence: float = 0.72

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConsolidationRunResult:
    tenant_id: str
    branch: str
    source_evidence_cids: list[str]
    passes_run: list[str]
    evidence_seen: int
    candidate_results: list[dict[str, Any]]
    skipped: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConsolidationWorker:
    def __init__(self, engine: LocalMemoryEngine, gate_cases: list[RegressionCase], security: SecurityPolicy | None = None):
        self.engine = engine
        self.security = security or SecurityPolicy()
        self.gate = PromotionGate(engine, gate_cases)

    def run_queue_payload(self, payload: dict[str, Any]) -> ConsolidationRunResult:
        decision = self.security.authorize_write(
            operation="run_consolidation_passes",
            role="consolidator",
            source_trust_tier=0,
            destructive=False,
            target_sink="memory",
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        tenant_id = str(payload["tenant_id"])
        branch = str(payload.get("branch", "main"))
        source_evidence_cids = [str(cid) for cid in payload.get("source_evidence_cids", [])]
        if not source_evidence_cids:
            raise ValueError("consolidation payload requires source_evidence_cids")

        get_evidence = getattr(self.engine, "get_evidence", None)
        evidence_seen = 0
        missing: list[str] = []
        if callable(get_evidence):
            for cid in source_evidence_cids:
                if get_evidence(tenant_id, cid, branch) is None:
                    missing.append(cid)
                else:
                    evidence_seen += 1

        passes_run = [str(name) for name in payload.get("passes") or DEFAULT_CONSOLIDATION_PASSES]
        candidate_results: list[dict[str, Any]] = []
        required_candidate_fields = {
            "signature",
            "query",
            "candidate_subject",
            "candidate_predicate",
            "candidate_object",
        }
        if required_candidate_fields <= set(payload):
            result = self.run_job(
                ConsolidationJob(
                    tenant_id=tenant_id,
                    signature=str(payload["signature"]),
                    query=str(payload["query"]),
                    candidate_subject=str(payload["candidate_subject"]),
                    candidate_predicate=str(payload["candidate_predicate"]),
                    candidate_object=str(payload["candidate_object"]),
                    source_evidence_cids=source_evidence_cids,
                    confidence=float(payload.get("confidence", 0.72)),
                )
            )
            candidate_results.append(result.to_dict())
        else:
            missing.append("candidate_extraction_not_configured")

        return ConsolidationRunResult(
            tenant_id=tenant_id,
            branch=branch,
            source_evidence_cids=source_evidence_cids,
            passes_run=passes_run,
            evidence_seen=evidence_seen,
            candidate_results=candidate_results,
            skipped=missing,
        )

    def run_job(self, job: ConsolidationJob) -> GateResult:
        decision = self.security.authorize_write(
            operation="promote_candidate",
            role="consolidator",
            source_trust_tier=0,
            destructive=False,
            target_sink="memory",
        )
        if not decision.allowed:
            return GateResult(
                candidate_id=f"candidate-{job.signature}",
                promoted=False,
                protected_regressions=[],
                failed_cases=[decision.reason],
                passed_cases=[],
                margin=0.0,
                rollback_branch=None,
            )
        candidate = Candidate(
            id=f"candidate-{job.signature}",
            kind="fact",
            signature=job.signature,
            description=f"{job.candidate_subject} {job.candidate_predicate} {job.candidate_object}",
            branch=f"canary-{job.signature}",
            source_evidence_cids=job.source_evidence_cids,
        )

        def apply(engine: LocalMemoryEngine, branch: str) -> None:
            engine.upsert_assertion(
                Assertion(
                    tenant_id=job.tenant_id,
                    subject=job.candidate_subject,
                    predicate=job.candidate_predicate,
                    object=job.candidate_object,
                    confidence=job.confidence,
                    source_evidence_cids=job.source_evidence_cids,
                    status="active",
                    trust_tier=0,
                    access_policy={"tenant": job.tenant_id},
                ),
                branch=branch,
            )

        return self.gate.evaluate(job.tenant_id, candidate, apply)
