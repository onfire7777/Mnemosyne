"""Warm-loop consolidation worker."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Protocol, Sequence

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
    entity_key: str | None = None

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
        entity_resolver: "EntityResolver | None" = None,
        candidate_extractor: "CandidateExtractor | None" = None,
        summarizer: "EvidenceSummarizer | None" = None,
    ):
        self.engine = engine
        self.security = security or SecurityPolicy()
        self.gate = PromotionGate(engine, gate_cases)
        self.learning = learning
        self.entity_resolver = entity_resolver or DeterministicEntityResolver()
        self.candidate_extractor = candidate_extractor or DeterministicCandidateExtractor()
        self.summarizer = summarizer or DeterministicEvidenceSummarizer()

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
        replay_rows = self._prioritize_replay(evidence, payload)
        evidence = [row["evidence"] for row in replay_rows]
        evidence_seen = len(evidence)
        passes_run = [str(name) for name in payload.get("passes") or DEFAULT_CONSOLIDATION_PASSES]
        pass_results: list[PassResult] = [
            PassResult(
                "replayer",
                "complete",
                {
                    "formula": "importance*novelty*surprise*reward",
                    "selected_cids": [item.cid for item in evidence if item.cid],
                    "missing_cids": missing,
                    "scores": [
                        {
                            "cid": row["cid"],
                            "score": row["score"],
                            "importance": row["importance"],
                            "novelty": row["novelty"],
                            "surprise": row["surprise"],
                            "reward": row["reward"],
                        }
                        for row in replay_rows
                    ],
                },
            )
        ]
        candidate_results: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        skipped: list[str] = list(missing)

        if self._contains_no_write_data(evidence, payload):
            skipped.append("source_marked_data_only")
            pass_results.append(PassResult("extractor", "skipped", {"reason": "source_marked_data_only"}))
        else:
            extractor_result = self.candidate_extractor.extract(tenant_id, payload, evidence)
            candidates = extractor_result["candidates"]
            if candidates:
                extractor_details = dict(extractor_result["details"])
                extractor_details["candidate_count"] = len(candidates)
                pass_results.append(PassResult("extractor", "complete", extractor_details))
                resolver_result = self.entity_resolver.resolve(tenant_id, candidates)
                candidates = resolver_result["candidates"]
                pass_results.append(
                    PassResult(
                        "resolver",
                        "complete",
                        resolver_result["details"],
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
                            entity_key=str(candidate.get("entity_key") or "") or None,
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
                summary = self.summarizer.summarize(tenant_id, evidence)
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

    def _prioritize_replay(self, evidence: list[Evidence], payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(evidence):
            factors = {
                "importance": self._replay_factor(item, payload, "importance"),
                "novelty": self._replay_factor(item, payload, "novelty"),
                "surprise": self._replay_factor(item, payload, "surprise"),
                "reward": self._replay_factor(item, payload, "reward"),
            }
            score = 1.0
            for value in factors.values():
                score *= value
            rows.append(
                {
                    "evidence": item,
                    "cid": item.cid,
                    "score": round(score, 6),
                    "index": index,
                    **factors,
                }
            )
        return sorted(rows, key=lambda row: (row["score"], -row["index"]), reverse=True)

    @staticmethod
    def _replay_factor(item: Evidence, payload: dict[str, Any], name: str) -> float:
        cid_scores = {}
        replay_scores = payload.get("replay_scores")
        if isinstance(replay_scores, dict) and item.cid:
            raw_scores = replay_scores.get(item.cid)
            if isinstance(raw_scores, dict):
                cid_scores = raw_scores
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        consolidation = metadata.get("consolidation")
        if not isinstance(consolidation, dict):
            consolidation = {}
        raw = cid_scores.get(name, consolidation.get(name, metadata.get(name, 1.0)))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 1.0
        return round(value, 6)

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
            entity_key = job.entity_key or _entity_key(job.candidate_subject)
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


class CandidateExtractor(Protocol):
    strategy: str

    def extract(self, tenant_id: str, payload: dict[str, Any], evidence: Sequence[Evidence]) -> dict[str, Any]: ...


class DeterministicCandidateExtractor:
    strategy = "deterministic_fact_extractor"

    def extract(self, tenant_id: str, payload: dict[str, Any], evidence: Sequence[Evidence]) -> dict[str, Any]:
        candidates = _deterministic_candidates(payload, evidence)
        return {
            "candidates": candidates,
            "details": {
                "strategy": self.strategy,
                "evidence_count": len(evidence),
            },
        }


class CommandCandidateExtractor:
    """Shell-free candidate extractor adapter for model-backed consolidation."""

    strategy = "command_candidate_extractor"

    def __init__(self, command: str | Sequence[str], *, timeout_seconds: float = 30.0):
        self.command = _command_argv(command)
        self.timeout_seconds = timeout_seconds

    def extract(self, tenant_id: str, payload: dict[str, Any], evidence: Sequence[Evidence]) -> dict[str, Any]:
        parsed = _run_json_command(
            self.command,
            {
                "tenant_id": tenant_id,
                "payload": payload,
                "evidence": [item.to_dict() for item in evidence],
            },
            timeout_seconds=self.timeout_seconds,
            provider_name="candidate extractor",
        )
        rows = parsed.get("candidates")
        if not isinstance(rows, list):
            raise ValueError("candidate extractor response requires candidates array")
        candidates = [_normalize_candidate(row, evidence, payload) for row in rows]
        metadata = parsed.get("metadata", {})
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("candidate extractor metadata must be a JSON object")
        return {
            "candidates": candidates,
            "details": {
                "strategy": self.strategy,
                "evidence_count": len(evidence),
                "metadata": metadata or {},
            },
        }


class EvidenceSummarizer(Protocol):
    strategy: str

    def summarize(self, tenant_id: str, evidence: Sequence[Evidence]) -> dict[str, Any] | None: ...


class DeterministicEvidenceSummarizer:
    strategy = "deterministic_first_sentence"

    def summarize(self, tenant_id: str, evidence: Sequence[Evidence]) -> dict[str, Any] | None:
        if not evidence:
            return None
        combined = " ".join(item.content.strip() for item in evidence if item.content.strip())
        first_sentence = re.split(r"(?<=[.!?])\s+", combined.strip())[0] if combined.strip() else ""
        tokens = first_sentence.split()
        summary = " ".join(tokens[:32])
        return {
            "strategy": self.strategy,
            "evidence_count": len(evidence),
            "summary": summary,
            "source_cids": [item.cid for item in evidence if item.cid],
        }


class CommandEvidenceSummarizer:
    """Shell-free summarizer adapter for model-backed consolidation."""

    strategy = "command_evidence_summarizer"

    def __init__(self, command: str | Sequence[str], *, timeout_seconds: float = 30.0):
        self.command = _command_argv(command)
        self.timeout_seconds = timeout_seconds

    def summarize(self, tenant_id: str, evidence: Sequence[Evidence]) -> dict[str, Any] | None:
        if not evidence:
            return None
        parsed = _run_json_command(
            self.command,
            {
                "tenant_id": tenant_id,
                "evidence": [item.to_dict() for item in evidence],
            },
            timeout_seconds=self.timeout_seconds,
            provider_name="evidence summarizer",
        )
        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            raise ValueError("evidence summarizer response requires non-empty summary")
        metadata = parsed.get("metadata", {})
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("evidence summarizer metadata must be a JSON object")
        return {
            "strategy": self.strategy,
            "evidence_count": len(evidence),
            "summary": summary,
            "source_cids": [item.cid for item in evidence if item.cid],
            "metadata": metadata or {},
        }


class EntityResolver(Protocol):
    strategy: str

    def resolve(self, tenant_id: str, candidates: Sequence[dict[str, Any]]) -> dict[str, Any]: ...


class DeterministicEntityResolver:
    strategy = "deterministic_entity_key"

    def resolve(self, tenant_id: str, candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
        resolved = []
        for candidate in candidates:
            item = dict(candidate)
            item["entity_key"] = str(item.get("entity_key") or _entity_key(str(item["candidate_subject"])))
            resolved.append(item)
        return {
            "candidates": resolved,
            "details": {
                "strategy": self.strategy,
                "resolved_entities": _resolved_entities(resolved),
            },
        }


class CommandEntityResolver:
    """Shell-free entity resolver adapter for production resolver services."""

    strategy = "command_entity_resolver"

    def __init__(self, command: str | Sequence[str], *, timeout_seconds: float = 30.0):
        self.command = _command_argv(command)
        self.timeout_seconds = timeout_seconds

    def resolve(self, tenant_id: str, candidates: Sequence[dict[str, Any]]) -> dict[str, Any]:
        payload = {"tenant_id": tenant_id, "candidates": [dict(candidate) for candidate in candidates]}
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("entity resolver timed out") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[:512]
            suffix = f": {detail}" if detail else ""
            raise ValueError(f"entity resolver failed{suffix}")
        try:
            parsed = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("entity resolver response must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("entity resolver response must be a JSON object")
        return _apply_resolver_response(candidates, parsed)


def _deterministic_candidates(payload: dict[str, Any], evidence: Sequence[Evidence]) -> list[dict[str, Any]]:
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


def _normalize_candidate(row: Any, evidence: Sequence[Evidence], payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("candidate extractor candidates must be JSON objects")
    required = ["signature", "query", "candidate_subject", "candidate_predicate", "candidate_object"]
    candidate = {key: str(row.get(key) or "").strip() for key in required}
    missing = [key for key, value in candidate.items() if not value]
    if missing:
        raise ValueError(f"candidate extractor candidate missing fields: {', '.join(missing)}")
    candidate["confidence"] = float(row.get("confidence", payload.get("confidence", 0.72)))
    candidate["trust_tier"] = int(row.get("trust_tier", payload.get("trust_tier", _max_evidence_trust(evidence))))
    candidate["sensitivity"] = int(row.get("sensitivity", payload.get("sensitivity", _max_evidence_sensitivity(evidence))))
    candidate["access_policy"] = row.get("access_policy") or payload.get("access_policy") or _first_access_policy(evidence)
    entity_key = str(row.get("entity_key") or row.get("entityKey") or "").strip()
    if entity_key:
        candidate["entity_key"] = entity_key
    return candidate


def _max_evidence_trust(evidence: Sequence[Evidence]) -> int:
    if not evidence:
        return int(TrustTier.NORMAL)
    return max(int(item.trust_tier) for item in evidence)


def _max_evidence_sensitivity(evidence: Sequence[Evidence]) -> int:
    if not evidence:
        return 0
    return max(int(item.sensitivity) for item in evidence)


def _first_access_policy(evidence: Sequence[Evidence]) -> dict[str, Any] | None:
    for item in evidence:
        if item.access_policy:
            return dict(item.access_policy)
    return None


def _run_json_command(
    command: Sequence[str],
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    provider_name: str,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"{provider_name} timed out") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[:512]
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"{provider_name} failed{suffix}")
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{provider_name} response must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{provider_name} response must be a JSON object")
    return parsed


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


def _apply_resolver_response(candidates: Sequence[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    by_signature = {str(candidate["signature"]): dict(candidate) for candidate in candidates}
    candidate_rows = response.get("candidates")
    if not isinstance(candidate_rows, list):
        raise ValueError("entity resolver response requires candidates array")
    seen_signatures: set[str] = set()
    for row in candidate_rows:
        if not isinstance(row, dict):
            raise ValueError("entity resolver candidates must be JSON objects")
        signature = str(row.get("signature", ""))
        if signature not in by_signature:
            raise ValueError(f"entity resolver returned unknown candidate signature {signature!r}")
        if signature in seen_signatures:
            raise ValueError(f"entity resolver returned duplicate candidate signature {signature!r}")
        entity_key = str(row.get("entity_key") or row.get("entityKey") or "").strip()
        if not entity_key:
            raise ValueError("entity resolver candidate mapping requires entity_key")
        by_signature[signature]["entity_key"] = entity_key
        seen_signatures.add(signature)
    missing_signatures = sorted(set(by_signature) - seen_signatures)
    if missing_signatures:
        raise ValueError(f"entity resolver did not resolve candidate signatures: {', '.join(missing_signatures)}")

    resolved = list(by_signature.values())

    entities = response.get("entities")
    if entities is None:
        entities = _resolved_entities(resolved)
    if not isinstance(entities, list):
        raise ValueError("entity resolver entities must be an array")
    normalized_entities = [_normalize_entity(row) for row in entities]
    return {
        "candidates": resolved,
        "details": {
            "strategy": "command_entity_resolver",
            "resolved_entities": normalized_entities,
        },
    }


def _normalize_entity(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("entity resolver entity rows must be JSON objects")
    key = str(row.get("key") or row.get("entity_key") or row.get("entityKey") or "").strip()
    if not key:
        raise ValueError("entity resolver entity requires key")
    label = str(row.get("label") or key)
    aliases = row.get("aliases", [])
    signatures = row.get("candidate_signatures", row.get("candidateSignatures", []))
    if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
        raise ValueError("entity resolver entity aliases must be strings")
    if not isinstance(signatures, list) or not all(isinstance(item, str) for item in signatures):
        raise ValueError("entity resolver entity candidate_signatures must be strings")
    return {
        "key": key,
        "label": label,
        "aliases": aliases,
        "candidate_signatures": signatures,
    }


def _command_argv(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        argv = shlex.split(command)
    else:
        argv = [str(item) for item in command]
    if not argv:
        raise ValueError("entity resolver command cannot be empty")
    return argv
