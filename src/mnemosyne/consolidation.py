"""Warm-loop consolidation worker."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol, Sequence

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.gate import Candidate, GateResult, PromotionGate, RegressionCase
from mnemosyne.learning import Lesson, Procedure
from mnemosyne.lifecycle import FidelityTier, LifecycleState, apply_rehearsal_schedule, demotion_decision
from mnemosyne.models import Assertion, Evidence, Relation
from mnemosyne.retrieval import is_retired_summary_metadata
from mnemosyne.security import SecurityPolicy, TrustTier
from mnemosyne.text import hashing_embedding
from mnemosyne.user_model import LatentUserProfile, UserModel

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


def _summary_source_fingerprint(source_cids: Sequence[str], *, level: int = 1) -> str:
    normalized = sorted(str(cid) for cid in source_cids)
    payload = {"raptor_level": level, "source_evidence_cids": normalized}
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _positive_int(value: object, *, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


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
    role_pipeline: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ROLE_NAMES = {
    "replayer": "replay_prioritizer",
    "extractor": "candidate_extractor",
    "resolver": "entity_resolver",
    "belief_reviser": "belief_reviser",
    "lesson_distiller": "lesson_distiller",
    "skill_inducer": "skill_inducer",
    "summarizer": "evidence_summarizer",
    "forgetter": "lifecycle_forgetter",
    "embedder": "evidence_embedder",
    "promotion_gate": "promotion_gate",
    "user_model_updater": "user_model_updater",
}


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
        user_model: UserModel | None = None,
    ):
        self.engine = engine
        self.security = security or SecurityPolicy()
        self.gate = PromotionGate(engine, gate_cases)
        self.learning = learning
        self.entity_resolver = entity_resolver or DeterministicEntityResolver()
        self.candidate_extractor = candidate_extractor or DeterministicCandidateExtractor()
        self.summarizer = summarizer or DeterministicEvidenceSummarizer()
        self.user_model = user_model

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
                summary = self._run_summarizer_pass(tenant_id, branch, evidence, payload)
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
            if pass_name == "forgetter":
                forgetter_result = self._run_forgetter(tenant_id, branch, payload, evidence)
                status = "complete" if forgetter_result["backend_supported"] else "skipped"
                if status == "skipped":
                    skipped.append("forgetter_backend_unavailable")
                    forgetter_result["reason"] = "engine_update_evidence_metadata_unavailable"
                pass_results.append(PassResult(pass_name, status, forgetter_result))
                continue
            if pass_name == "user_model_updater":
                user_model_result = self._update_user_model(tenant_id, payload, evidence, candidates)
                status = "complete" if user_model_result["updated"] else "skipped"
                if status == "skipped":
                    skipped.append("user_model_updater_unavailable")
                    user_model_result["reason"] = "no_user_model_or_user"
                pass_results.append(PassResult(pass_name, status, user_model_result))
                continue
            if pass_name == "embedder":
                embedder_result = self._embed_evidence(tenant_id, branch, evidence)
                status = "complete" if embedder_result["backend_supported"] else "skipped"
                if status == "skipped":
                    skipped.append("embedder_backend_unavailable")
                    embedder_result["reason"] = "engine_set_evidence_embedding_unavailable"
                pass_results.append(PassResult(pass_name, status, embedder_result))
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
            role_pipeline=self._role_pipeline_report(pass_results),
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

    def _role_pipeline_report(self, pass_results: list[PassResult]) -> dict[str, Any]:
        roles = []
        for item in pass_results:
            provider = self._role_provider(item.name)
            provider_type = "model_adapter" if provider.startswith("command_") else "deterministic_or_local"
            roles.append(
                {
                    "pass": item.name,
                    "role": ROLE_NAMES.get(item.name, item.name),
                    "provider": provider,
                    "provider_type": provider_type,
                    "status": item.status,
                }
            )
        return {
            "owner_role": "consolidator",
            "write_authorized": True,
            "roles": roles,
            "role_count": len(roles),
            "model_backed_roles": [item["role"] for item in roles if item["provider_type"] == "model_adapter"],
        }

    def _role_provider(self, pass_name: str) -> str:
        if pass_name == "extractor":
            return str(getattr(self.candidate_extractor, "strategy", self.candidate_extractor.__class__.__name__))
        if pass_name == "resolver":
            return str(getattr(self.entity_resolver, "strategy", self.entity_resolver.__class__.__name__))
        if pass_name == "summarizer":
            return str(getattr(self.summarizer, "strategy", self.summarizer.__class__.__name__))
        return {
            "replayer": "deterministic_priority_replay",
            "belief_reviser": "promotion_gate",
            "lesson_distiller": "deterministic_lesson_distiller",
            "skill_inducer": "deterministic_skill_inducer",
            "forgetter": "fidelity_lifecycle_policy",
            "embedder": "deterministic_hashing_embedding",
            "promotion_gate": "protected_regression_gate",
            "user_model_updater": "latent_user_model_updater",
        }.get(pass_name, "local_pass")

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

    def _update_user_model(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        evidence: list[Evidence],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.user_model is None:
            return {"updated": False}
        user_id = str(payload.get("user_id") or "")
        if not user_id and evidence:
            user_id = evidence[0].user_id
        if not user_id:
            return {"updated": False}
        selected_cids = [item.cid for item in evidence if item.cid]
        candidate_statements = [
            f"{item['candidate_subject']} {item['candidate_predicate']} {item['candidate_object']}"
            for item in candidates
        ]
        evidence_preview = " ".join(item.content.strip() for item in evidence if item.content).strip()
        if len(evidence_preview) > 240:
            evidence_preview = evidence_preview[:237].rstrip() + "..."
        summary_parts = [
            f"Consolidated {len(evidence)} prioritized evidence item(s)",
            f"source_cids={','.join(selected_cids)}" if selected_cids else "source_cids=none",
        ]
        if candidate_statements:
            summary_parts.append("candidates=" + "; ".join(candidate_statements[:3]))
        if evidence_preview:
            summary_parts.append("evidence=" + evidence_preview)
        summary = " | ".join(summary_parts)
        self.user_model.set_latent_profile(
            LatentUserProfile(
                tenant_id=tenant_id,
                user_id=user_id,
                embedding=hashing_embedding(summary),
                summary=summary,
            )
        )
        return {
            "updated": True,
            "user_id": user_id,
            "source_cids": selected_cids,
            "candidate_count": len(candidates),
            "summary": summary,
        }

    def _run_summarizer_pass(
        self,
        tenant_id: str,
        branch: str,
        evidence: list[Evidence],
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not evidence:
            return None
        cluster_size = _positive_int(payload.get("raptor_cluster_size"), default=4)
        max_levels = _positive_int(payload.get("raptor_max_levels"), default=2)
        if max_levels <= 1 or len(evidence) <= cluster_size:
            summary = self.summarizer.summarize(tenant_id, evidence)
            if not summary:
                return None
            return self._materialize_summary(tenant_id, branch, summary, evidence, raptor_level=1)
        return self._materialize_summary_hierarchy(
            tenant_id,
            branch,
            evidence,
            cluster_size=cluster_size,
            max_levels=max_levels,
        )

    def _materialize_summary_hierarchy(
        self,
        tenant_id: str,
        branch: str,
        evidence: list[Evidence],
        *,
        cluster_size: int,
        max_levels: int,
    ) -> dict[str, Any] | None:
        get_evidence = getattr(self.engine, "get_evidence", None)
        if not callable(get_evidence):
            summary = self.summarizer.summarize(tenant_id, evidence)
            if not summary:
                return None
            return self._materialize_summary(tenant_id, branch, summary, evidence, raptor_level=1)

        raw_source_cids = self._summary_transitive_source_cids(evidence)
        current = list(evidence)
        all_results: list[dict[str, Any]] = []
        levels: list[dict[str, Any]] = []
        all_relation_ids: list[str] = []

        for level in range(1, max_levels + 1):
            if len(current) <= 1 and level > 1:
                break
            clusters = [current] if level == max_levels or len(current) <= cluster_size else self._cluster_evidence(current, cluster_size)
            next_level: list[Evidence] = []
            level_summary_cids: list[str] = []
            for cluster in clusters:
                if not cluster:
                    continue
                summary = self.summarizer.summarize(tenant_id, cluster)
                if not summary:
                    continue
                if level > 1:
                    child_summary_cids = [item.cid for item in cluster if item.cid]
                    summary = {
                        **summary,
                        "source_cids": self._summary_transitive_source_cids(cluster),
                        "source_summary_cids": child_summary_cids,
                        "relation_source_cids": child_summary_cids,
                    }
                result = self._materialize_summary(tenant_id, branch, summary, cluster, raptor_level=level)
                if not result.get("materialized") or not result.get("summary_cid"):
                    continue
                summary_cid = str(result["summary_cid"])
                materialized = get_evidence(tenant_id, summary_cid, branch)
                if materialized is not None:
                    next_level.append(materialized)
                level_summary_cids.append(summary_cid)
                all_relation_ids.extend(str(item) for item in result.get("derived_relation_ids", []))
                all_results.append(result)

            if not level_summary_cids:
                break
            levels.append({"level": level, "summary_cids": level_summary_cids, "summary_count": len(level_summary_cids)})
            current = next_level
            if len(current) <= 1:
                break

        if not all_results:
            return None
        root = dict(all_results[-1])
        leaf_summary_cids = list(levels[0]["summary_cids"]) if levels else [str(root["summary_cid"])]
        root["derived_relation_ids"] = all_relation_ids
        root["hierarchy"] = {
            "enabled": len(levels) > 1,
            "strategy": "deterministic_raptor_tree",
            "cluster_size": cluster_size,
            "max_levels": max_levels,
            "levels": levels,
            "leaf_summary_cids": leaf_summary_cids,
            "root_summary_cid": root.get("summary_cid"),
            "summary_cids": [str(result["summary_cid"]) for result in all_results if result.get("summary_cid")],
            "source_evidence_cids": raw_source_cids,
        }
        return root

    @staticmethod
    def _cluster_evidence(evidence: list[Evidence], cluster_size: int) -> list[list[Evidence]]:
        clusters = [evidence[index : index + cluster_size] for index in range(0, len(evidence), cluster_size)]
        if len(clusters) > 1 and len(clusters[-1]) == 1:
            clusters[-2].extend(clusters.pop())
        return clusters

    @staticmethod
    def _summary_transitive_source_cids(evidence: Sequence[Evidence]) -> list[str]:
        source_cids: list[str] = []

        def add(values: object) -> None:
            if not isinstance(values, list):
                return
            for value in values:
                cid = str(value)
                if cid and cid not in source_cids:
                    source_cids.append(cid)

        for item in evidence:
            metadata = item.metadata if isinstance(item.metadata, dict) else {}
            summary = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
            add(summary.get("source_evidence_cids") if isinstance(summary, dict) else None)
            add(metadata.get("source_evidence_cids"))
            if item.cid and not (isinstance(summary, dict) and summary.get("source_evidence_cids")) and not metadata.get("source_evidence_cids") and item.cid not in source_cids:
                source_cids.append(item.cid)
        return source_cids

    def _materialize_summary(
        self,
        tenant_id: str,
        branch: str,
        summary: dict[str, Any],
        evidence: list[Evidence],
        *,
        raptor_level: int = 1,
    ) -> dict[str, Any]:
        append_evidence = getattr(self.engine, "append_evidence", None)
        add_relation = getattr(self.engine, "add_relation", None)
        source_cids = [str(cid) for cid in summary.get("source_cids") or [item.cid for item in evidence if item.cid]]
        relation_source_cids = [str(cid) for cid in summary.get("relation_source_cids") or [item.cid for item in evidence if item.cid]]
        source_summary_cids = [str(cid) for cid in summary.get("source_summary_cids") or []]
        summary_text = str(summary.get("summary") or "").strip()
        if not callable(append_evidence) or not callable(add_relation) or not source_cids or not summary_text:
            return {**summary, "materialized": False}
        source_trust = max((int(item.trust_tier) for item in evidence), default=int(TrustTier.NORMAL))
        trust_tier = max(source_trust, int(TrustTier.AUTHENTICATED))
        source_identity = "consolidation-summary:" + sha256(
            json.dumps(
                {
                    "tenant_id": tenant_id,
                    "branch": branch,
                    "source_cids": source_cids,
                    "source_summary_cids": source_summary_cids,
                    "summary": summary_text,
                    "strategy": summary.get("strategy"),
                    "raptor_level": raptor_level,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        content_lines = ["Source evidence CIDs: " + ", ".join(source_cids)]
        if source_summary_cids:
            content_lines.append("Source summary CIDs: " + ", ".join(source_summary_cids))
        content = "\n".join(content_lines) + "\n\n" + summary_text
        first = evidence[0]
        generated_at = datetime.now(UTC).isoformat()
        source_fingerprint = _summary_source_fingerprint(source_cids, level=raptor_level)
        summary_metadata = {
            "kind": "abstractive_gist",
            "strategy": summary.get("strategy"),
            "status": "active",
            "generated_at": generated_at,
            "source_fingerprint": source_fingerprint,
            "confabulation_risk": True,
            "source_evidence_cids": source_cids,
            "raptor_level": raptor_level,
            "source_count": len(source_cids),
        }
        if source_summary_cids:
            summary_metadata["source_summary_cids"] = source_summary_cids
            summary_metadata["child_summary_cids"] = source_summary_cids
        summary_cid = append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=first.user_id,
                actor="system",
                source_type="consolidation-summary",
                source_identity=source_identity,
                content=content,
                modality="text",
                metadata={
                    "summary": summary_metadata,
                    "source_evidence_cids": source_cids,
                    **({"source_summary_cids": source_summary_cids} if source_summary_cids else {}),
                },
                trust_tier=trust_tier,
                capability_tags=["derived-summary", "consolidation-gist", "source:consolidation"],
                sensitivity=max((int(item.sensitivity) for item in evidence), default=0),
                access_policy=dict(first.access_policy or {"tenant": tenant_id}),
            ),
            branch=branch,
        )
        retired_summary_cids = self._retire_superseded_summaries(
            tenant_id,
            branch,
            source_cids,
            summary_cid,
            generated_at=generated_at,
            raptor_level=raptor_level,
        )
        relation_ids: list[str] = []
        for source_cid in relation_source_cids:
            relation_ids.append(
                add_relation(
                    Relation(
                        tenant_id=tenant_id,
                        source=source_cid,
                        predicate="summary-derived-gist",
                        target=summary_cid,
                        confidence=0.92,
                        source_evidence_cids=[source_cid, summary_cid],
                        access_policy=dict(first.access_policy or {"tenant": tenant_id}),
                    ),
                    branch=branch,
                )
            )
        return {
            **summary,
            "materialized": True,
            "summary_cid": summary_cid,
            "derived_relation_ids": relation_ids,
            "retired_summary_cids": retired_summary_cids,
            "source_fingerprint": source_fingerprint,
            "fidelity": "abstractive_gist",
            "trust_tier": trust_tier,
            "raptor_level": raptor_level,
            **({"source_summary_cids": source_summary_cids} if source_summary_cids else {}),
        }

    def _retire_superseded_summaries(
        self,
        tenant_id: str,
        branch: str,
        source_cids: list[str],
        new_summary_cid: str,
        *,
        generated_at: str,
        raptor_level: int = 1,
    ) -> list[str]:
        export_tenant = getattr(self.engine, "export_tenant", None)
        update_metadata = getattr(self.engine, "update_evidence_metadata", None)
        if not callable(export_tenant) or not callable(update_metadata):
            return []
        source_fingerprint = _summary_source_fingerprint(source_cids, level=raptor_level)
        try:
            snapshot = export_tenant(tenant_id)
        except Exception:
            return []
        retired: list[str] = []
        for row in snapshot.get("evidence", []):
            if not isinstance(row, dict):
                continue
            cid = str(row.get("cid") or "")
            if not cid or cid == new_summary_cid:
                continue
            if row.get("branch", branch) != branch or row.get("source_type") != "consolidation-summary":
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if is_retired_summary_metadata(metadata):
                continue
            summary_meta = metadata.get("summary") if isinstance(metadata.get("summary"), dict) else {}
            existing_level = _positive_int(summary_meta.get("raptor_level"), default=1)
            existing_sources = summary_meta.get("source_evidence_cids") or metadata.get("source_evidence_cids") or []
            existing_fingerprint = str(summary_meta.get("source_fingerprint") or "")
            if existing_fingerprint:
                if existing_fingerprint != source_fingerprint:
                    continue
            elif _summary_source_fingerprint([str(item) for item in existing_sources], level=existing_level) != source_fingerprint:
                continue
            retired_summary = {
                **summary_meta,
                "status": "retired",
                "retired_at": generated_at,
                "retired_by": "consolidation.summarizer",
                "superseded_by": new_summary_cid,
            }
            if update_metadata(
                tenant_id,
                cid,
                {"summary": retired_summary},
                branch=branch,
                actor="consolidation",
                source="summary_refresh",
            ):
                retired.append(cid)
        return retired

    def _embed_evidence(self, tenant_id: str, branch: str, evidence: list[Evidence]) -> dict[str, Any]:
        set_embedding = getattr(self.engine, "set_evidence_embedding", None)
        if not callable(set_embedding):
            return {"backend_supported": False, "evaluated": len(evidence), "embedded": 0, "already_embedded": 0}
        embedded_cids: list[str] = []
        failed_cids: list[str] = []
        already_embedded = 0
        dims = self._embedding_dims()
        for item in evidence:
            if not item.cid:
                continue
            if item.embedding is not None:
                already_embedded += 1
                continue
            vector = hashing_embedding(item.content, dims=dims)
            updated = bool(
                set_embedding(
                    tenant_id,
                    item.cid,
                    vector,
                    branch=branch,
                    actor="consolidation",
                    source="embedder",
                )
            )
            if updated:
                item.embedding = vector
                embedded_cids.append(item.cid)
            else:
                failed_cids.append(item.cid)
        return {
            "backend_supported": True,
            "provider": "deterministic-hashing",
            "embedding_dims": dims,
            "evaluated": len(evidence),
            "embedded": len(embedded_cids),
            "already_embedded": already_embedded,
            "embedded_cids": embedded_cids,
            "failed_cids": failed_cids,
        }

    def _embedding_dims(self) -> int:
        adapters = getattr(self.engine, "adapters", None)
        embedding = getattr(adapters, "embedding", None)
        dims = getattr(embedding, "dims", 256)
        try:
            value = int(dims)
        except (TypeError, ValueError):
            value = 256
        return max(value, 1)

    def _run_forgetter(
        self,
        tenant_id: str,
        branch: str,
        payload: dict[str, Any],
        evidence: list[Evidence],
    ) -> dict[str, Any]:
        update_metadata = getattr(self.engine, "update_evidence_metadata", None)
        if not callable(update_metadata):
            return {"backend_supported": False, "evaluated": len(evidence), "demoted": 0}
        now = self._parse_datetime(payload.get("now")) or datetime.now(UTC)
        threshold = float(payload.get("utility_threshold", 0.18))
        evaluated: list[dict[str, Any]] = []
        demoted_cids: list[str] = []
        failed_cids: list[str] = []
        for item in evidence:
            if not item.cid:
                continue
            lifecycle = item.metadata.get("lifecycle") if isinstance(item.metadata, dict) else None
            state = self._lifecycle_state(item, lifecycle)
            scheduled_state, rehearsed = apply_rehearsal_schedule(state, now)
            next_state, changed = demotion_decision(scheduled_state, now, utility_threshold=threshold)
            payload_patch = {
                "lifecycle": {
                    **next_state.to_dict(),
                    "updated_by": "consolidation.forgetter",
                    "utility_threshold": threshold,
                    "demoted": changed,
                    "rehearsed": rehearsed,
                }
            }
            updated = bool(
                update_metadata(
                    tenant_id,
                    item.cid,
                    payload_patch,
                    branch=branch,
                    actor="consolidation",
                    source="forgetter",
                )
            )
            if updated:
                item.metadata = {**item.metadata, **payload_patch}
                if changed:
                    demoted_cids.append(item.cid)
            else:
                failed_cids.append(item.cid)
            evaluated.append(
                {
                    "cid": item.cid,
                    "from_tier": state.tier.value,
                    "to_tier": next_state.tier.value,
                    "salience": next_state.salience,
                    "demoted": changed,
                    "rehearsed": rehearsed,
                    "successful_rehearsals": next_state.successful_rehearsals,
                    "next_rehearsal_at": (
                        next_state.next_rehearsal_at.astimezone(UTC).isoformat()
                        if next_state.next_rehearsal_at
                        else None
                    ),
                    "updated": updated,
                }
            )
        return {
            "backend_supported": True,
            "evaluated": len(evaluated),
            "demoted": len(demoted_cids),
            "demoted_cids": demoted_cids,
            "failed_cids": failed_cids,
            "states": evaluated,
        }

    @staticmethod
    def _lifecycle_state(item: Evidence, lifecycle: Any) -> LifecycleState:
        data = lifecycle if isinstance(lifecycle, dict) else {}
        tier_raw = str(data.get("tier") or FidelityTier.VERBATIM.value)
        try:
            tier = FidelityTier(tier_raw)
        except ValueError:
            tier = FidelityTier.VERBATIM
        return LifecycleState(
            item_id=item.cid or "",
            tier=tier,
            salience=ConsolidationWorker._safe_float(data.get("salience"), 0.1),
            importance=ConsolidationWorker._safe_float(
                data.get("importance", item.metadata.get("importance") if isinstance(item.metadata, dict) else None),
                0.1,
            ),
            access_count=int(ConsolidationWorker._safe_float(data.get("access_count"), 0.0)),
            last_accessed=ConsolidationWorker._parse_datetime(data.get("last_accessed")),
            must_keep=bool(data.get("must_keep", False)),
            successful_rehearsals=int(ConsolidationWorker._safe_float(data.get("successful_rehearsals"), 0.0)),
            next_rehearsal_at=ConsolidationWorker._parse_datetime(data.get("next_rehearsal_at")),
            last_rehearsed_at=ConsolidationWorker._parse_datetime(data.get("last_rehearsed_at")),
            confabulation_risk=bool(data.get("confabulation_risk", False)),
            protected=bool(data.get("protected", False)),
        )

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC)

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
