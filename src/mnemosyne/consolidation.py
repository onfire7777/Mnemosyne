"""Warm-loop consolidation worker."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.models import Assertion, Evidence
from mnemosyne.security import SecurityPolicy, TrustTier

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
    trust_tier: int = int(TrustTier.NORMAL)
    sensitivity: int = 0
    access_policy: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PassResult:
    name: str
    status: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConsolidationRunResult:
    tenant_id: str
    branch: str
    source_evidence_cids: list[str]
    passes_run: list[str]
    pass_results: list[dict[str, Any]]
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

        evidence, missing = self._load_evidence(tenant_id, source_evidence_cids, branch)
        evidence_seen = len(evidence)
        passes_run = [str(name) for name in payload.get("passes") or DEFAULT_CONSOLIDATION_PASSES]
        pass_results: list[PassResult] = [
            PassResult(
                "replayer",
                "complete",
                {"selected_cids": [item.cid for item in evidence if item.cid], "missing_cids": missing},
            )
        ]
        candidate_results: list[dict[str, Any]] = []
        skipped: list[str] = list(missing)

        if self._contains_no_write_data(evidence, payload):
            skipped.append("source_marked_data_only")
            pass_results.append(PassResult("extractor", "skipped", {"reason": "source_marked_data_only"}))
        else:
            candidates = self._candidate_payloads(payload, evidence)
            if candidates:
                pass_results.append(PassResult("extractor", "complete", {"candidate_count": len(candidates)}))
                pass_results.append(PassResult("resolver", "complete", {"strategy": "deterministic_text_pattern"}))
                for candidate in candidates:
                    result = self.run_job(
                        ConsolidationJob(
                            tenant_id=tenant_id,
                            signature=str(candidate["signature"]),
                            query=str(candidate["query"]),
                            candidate_subject=str(candidate["candidate_subject"]),
                            candidate_predicate=str(candidate["candidate_predicate"]),
                            candidate_object=str(candidate["candidate_object"]),
                            source_evidence_cids=source_evidence_cids,
                            confidence=float(candidate.get("confidence", payload.get("confidence", 0.72))),
                            trust_tier=int(candidate.get("trust_tier", payload.get("trust_tier", TrustTier.NORMAL))),
                            sensitivity=int(candidate.get("sensitivity", payload.get("sensitivity", 0))),
                            access_policy=candidate.get("access_policy") or payload.get("access_policy"),
                        )
                    )
                    candidate_results.append(result.to_dict())
                pass_results.append(PassResult("belief_reviser", "complete", {"candidate_count": len(candidates)}))
            else:
                skipped.append("candidate_extraction_not_configured")
                pass_results.append(PassResult("extractor", "skipped", {"reason": "no_deterministic_candidate"}))
                pass_results.append(PassResult("resolver", "skipped", {"reason": "no_candidates"}))
                pass_results.append(PassResult("belief_reviser", "skipped", {"reason": "no_candidates"}))

        for pass_name in passes_run:
            if pass_name in {"replayer", "extractor", "resolver", "belief_reviser"}:
                continue
            if pass_name == "promotion_gate" and candidate_results:
                promoted = sum(1 for item in candidate_results if item.get("promoted"))
                pass_results.append(PassResult(pass_name, "complete", {"promoted": promoted, "evaluated": len(candidate_results)}))
                continue
            skipped_name = f"{pass_name}_not_implemented"
            skipped.append(skipped_name)
            pass_results.append(PassResult(pass_name, "skipped", {"reason": "not_implemented"}))

        return ConsolidationRunResult(
            tenant_id=tenant_id,
            branch=branch,
            source_evidence_cids=source_evidence_cids,
            passes_run=passes_run,
            pass_results=[item.to_dict() for item in pass_results],
            evidence_seen=evidence_seen,
            candidate_results=candidate_results,
            skipped=skipped,
        )

    def _load_evidence(self, tenant_id: str, source_evidence_cids: list[str], branch: str) -> tuple[list[Evidence], list[str]]:
        get_evidence = getattr(self.engine, "get_evidence", None)
        if not callable(get_evidence):
            return [], ["engine_get_evidence_unavailable"]
        evidence: list[Evidence] = []
        missing: list[str] = []
        for cid in source_evidence_cids:
            item = get_evidence(tenant_id, cid, branch)
            if item is None:
                missing.append(cid)
            else:
                evidence.append(item)
        return evidence, missing

    def _candidate_payloads(self, payload: dict[str, Any], evidence: list[Evidence]) -> list[dict[str, Any]]:
        required_candidate_fields = {
            "signature",
            "query",
            "candidate_subject",
            "candidate_predicate",
            "candidate_object",
        }
        if required_candidate_fields <= set(payload):
            return [dict(payload)]
        candidates: list[dict[str, Any]] = []
        for item in evidence:
            fact = _extract_simple_fact(item.content)
            if not fact:
                continue
            subject, predicate, object_value = fact
            signature = f"{subject} {predicate} {object_value}".lower()
            candidates.append(
                {
                    "signature": signature,
                    "query": subject,
                    "candidate_subject": subject,
                    "candidate_predicate": predicate,
                    "candidate_object": object_value,
                    "trust_tier": item.trust_tier,
                    "sensitivity": item.sensitivity,
                    "access_policy": item.access_policy,
                }
            )
        return candidates

    @staticmethod
    def _contains_no_write_data(evidence: list[Evidence], payload: dict[str, Any]) -> bool:
        payload_tags = set(str(tag) for tag in payload.get("capability_tags", []))
        evidence_tags = {str(tag) for item in evidence for tag in item.capability_tags}
        tags = payload_tags | evidence_tags
        if tags & {"data-only", "no-write-authority", "sanitize-as-data", "quarantined"}:
            return True
        trust_values = [int(payload.get("trust_tier", TrustTier.NORMAL)), *(item.trust_tier for item in evidence)]
        return any(value >= int(TrustTier.UNTRUSTED_EXTERNAL) for value in trust_values)

    def run_job(self, job: ConsolidationJob) -> GateResult:
        decision = self.security.authorize_write(
            operation="promote_candidate",
            role="consolidator",
            source_trust_tier=job.trust_tier,
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
                    trust_tier=job.trust_tier,
                    sensitivity=job.sensitivity,
                    access_policy=job.access_policy or {"tenant": job.tenant_id},
                ),
                branch=branch,
            )

        return self.gate.evaluate(job.tenant_id, candidate, apply)


def _extract_simple_fact(text: str) -> tuple[str, str, str] | None:
    first_sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    match = re.match(
        r"^(?:the\s+)?(?P<subject>[A-Za-z][A-Za-z0-9 _'/-]{1,80})\s+"
        r"(?P<predicate>is|are|was|were)\s+"
        r"(?P<object>[^.!?]{1,160})[.!?]?$",
        first_sentence,
    )
    if not match:
        return None
    subject = match.group("subject").strip()
    predicate = match.group("predicate").strip()
    object_value = match.group("object").strip()
    if not subject or not object_value:
        return None
    return subject, predicate, object_value
