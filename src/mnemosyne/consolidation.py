"""Warm-loop consolidation worker."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.learning import Lesson, Procedure
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
    def __init__(
        self,
        engine: LocalMemoryEngine,
        gate_cases: list[RegressionCase],
        security: SecurityPolicy | None = None,
        learning: Any | None = None,
    ):
        self.engine = engine
        self.security = security or SecurityPolicy()
        self.gate = PromotionGate(engine, gate_cases)
        self.learning = learning

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
        candidates: list[dict[str, Any]] = []
        skipped: list[str] = list(missing)

        if self._contains_no_write_data(evidence, payload):
            skipped.append("source_marked_data_only")
            pass_results.append(PassResult("extractor", "skipped", {"reason": "source_marked_data_only"}))
        else:
            candidates = self._candidate_payloads(payload, evidence)
            if candidates:
                pass_results.append(PassResult("extractor", "complete", {"candidate_count": len(candidates)}))
                pass_results.append(
                    PassResult(
                        "resolver",
                        "complete",
                        {
                            "strategy": "deterministic_entity_key",
                            "resolved_entities": _resolved_entities(candidates),
                        },
                    )
                )
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
            if pass_name == "summarizer":
                summary = self._summarize_evidence(evidence)
                if summary:
                    pass_results.append(PassResult(pass_name, "complete", summary))
                else:
                    skipped.append("summarizer_no_evidence")
                    pass_results.append(PassResult(pass_name, "skipped", {"reason": "no_evidence"}))
                continue
            if pass_name == "lesson_distiller":
                lesson_result = self._distill_lessons(tenant_id, candidates)
                status = "complete" if lesson_result["lessons"] else "skipped"
                if status == "skipped":
                    skipped.append("lesson_distiller_no_candidates")
                    lesson_result["reason"] = "no_candidates_or_learning_store"
                pass_results.append(PassResult(pass_name, status, lesson_result))
                continue
            if pass_name == "skill_inducer":
                procedure_result = self._induce_procedures(tenant_id, candidates)
                status = "complete" if procedure_result["procedures"] else "skipped"
                if status == "skipped":
                    skipped.append("skill_inducer_no_candidates")
                    procedure_result["reason"] = "no_candidates_or_learning_store"
                pass_results.append(PassResult(pass_name, status, procedure_result))
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
            entity_label = _entity_label(subject)
            entity_key = _entity_key(entity_label)
            signature = f"{subject} {predicate} {object_value}".lower()
            candidates.append(
                {
                    "signature": signature,
                    "query": entity_label,
                    "candidate_subject": entity_label,
                    "candidate_predicate": predicate,
                    "candidate_object": object_value,
                    "entity_key": entity_key,
                    "trust_tier": item.trust_tier,
                    "sensitivity": item.sensitivity,
                    "access_policy": item.access_policy,
                }
            )
        return candidates

    @staticmethod
    def _summarize_evidence(evidence: list[Evidence]) -> dict[str, Any] | None:
        if not evidence:
            return None
        combined = " ".join(item.content.strip() for item in evidence if item.content.strip())
        first_sentence = re.split(r"(?<=[.!?])\s+", combined.strip())[0] if combined.strip() else ""
        tokens = first_sentence.split()
        summary = " ".join(tokens[:32])
        return {
            "evidence_count": len(evidence),
            "summary": summary,
            "source_cids": [item.cid for item in evidence if item.cid],
        }

    def _distill_lessons(self, tenant_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if self.learning is None or not candidates:
            return {"lessons": []}
        lesson_ids: list[str] = []
        created = 0
        for candidate in candidates:
            signature = f"consolidation:{candidate['signature']}"
            existing = next(
                (
                    item
                    for item in self.learning.lessons.values()
                    if item.tenant_id == tenant_id and item.failure_signature == signature
                ),
                None,
            )
            if existing:
                lesson_ids.append(existing.id)
                continue
            content = (
                f"Evidence supports `{candidate['candidate_subject']} "
                f"{candidate['candidate_predicate']} {candidate['candidate_object']}`; "
                f"resolve entity `{candidate.get('entity_key', candidate['candidate_subject'])}`, "
                "preserve source CIDs, and promote only through the gate."
            )
            lesson = Lesson(
                tenant_id=tenant_id,
                lesson_type="observed-pattern",
                failure_signature=signature,
                content=content,
                votes=1,
            )
            self.learning.lessons[lesson.id] = lesson
            lesson_ids.append(lesson.id)
            created += 1
        return {"lessons": lesson_ids, "created": created, "reused": len(lesson_ids) - created}

    def _induce_procedures(self, tenant_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if self.learning is None or not candidates:
            return {"procedures": []}
        procedure_ids: list[str] = []
        created = 0
        for candidate in candidates:
            signature = {
                "source": "consolidation",
                "candidate_signature": candidate["signature"],
                "entity_key": candidate.get("entity_key"),
            }
            existing = next(
                (
                    item
                    for item in self.learning.procedures.values()
                    if item.tenant_id == tenant_id and item.signature == signature
                ),
                None,
            )
            if existing:
                procedure_ids.append(existing.id)
                continue
            name = f"Consolidate {candidate['candidate_subject']}"
            body = (
                "1. Re-read source evidence CIDs\n"
                f"2. Verify `{candidate['candidate_subject']} "
                f"{candidate['candidate_predicate']} {candidate['candidate_object']}`\n"
                f"3. Resolve entity key `{candidate.get('entity_key', 'n/a')}`\n"
                "4. Check trust tier, sensitivity, and access policy\n"
                "5. Promote only through protected gate evaluation"
            )
            procedure = Procedure(
                tenant_id=tenant_id,
                kind="consolidation-checklist",
                name=name,
                body=body,
                signature=signature,
            )
            self.learning.procedures[procedure.id] = procedure
            procedure_ids.append(procedure.id)
            created += 1
        return {"procedures": procedure_ids, "created": created, "reused": len(procedure_ids) - created}

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

        result = self.gate.evaluate(job.tenant_id, candidate, apply)
        if result.promoted and hasattr(self.engine, "register_entity"):
            entity_key = _entity_key(job.candidate_subject)
            self.engine.register_entity(
                job.tenant_id,
                entity_key,
                alias=job.candidate_subject,
                summary=candidate.description,
                source_evidence_cids=job.source_evidence_cids,
                access_policy=job.access_policy or {"tenant": job.tenant_id},
            )
        return result


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


def _entity_label(subject: str) -> str:
    return re.sub(r"\s+", " ", subject.strip())


def _entity_key(subject: str) -> str:
    normalized = _entity_label(subject).lower()
    normalized = re.sub(r"^(the|a|an)\s+", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "unknown-entity"


def _resolved_entities(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = str(candidate.get("entity_key") or _entity_key(str(candidate["candidate_subject"])))
        entity = entities.setdefault(
            key,
            {
                "key": key,
                "label": str(candidate["candidate_subject"]),
                "aliases": [],
                "candidate_signatures": [],
            },
        )
        alias = str(candidate["candidate_subject"])
        if alias not in entity["aliases"]:
            entity["aliases"].append(alias)
        signature = str(candidate["signature"])
        if signature not in entity["candidate_signatures"]:
            entity["candidate_signatures"].append(signature)
    return list(entities.values())
