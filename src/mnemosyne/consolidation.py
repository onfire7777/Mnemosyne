"""Warm-loop consolidation worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.models import Assertion
from mnemosyne.security import SecurityPolicy


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


class ConsolidationWorker:
    def __init__(self, engine: LocalMemoryEngine, gate_cases: list[RegressionCase], security: SecurityPolicy | None = None):
        self.engine = engine
        self.security = security or SecurityPolicy()
        self.gate = PromotionGate(engine, gate_cases)

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
