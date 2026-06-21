"""Runtime job handlers for local queue-backed memory maintenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from mnemosyne.calibration import CalibrationSet, calibration_examples_from_rows, conformal_threshold, should_abstain, tune_calibration_set
from mnemosyne.consolidation import (
    CONSOLIDATE_EVIDENCE_JOB,
    DEFAULT_CONSOLIDATION_PASSES,
    CandidateExtractor,
    ConsolidationWorker,
    EntityResolver,
    EvidenceSummarizer,
)
from mnemosyne.eval import run_seed_suite
from mnemosyne.gate import RegressionCase
from mnemosyne.lifecycle import FidelityTier, LifecycleState, apply_rehearsal_schedule, demotion_decision
from mnemosyne.media import MEDIA_EXTRACT_JOB, MediaTextExtractor, MetadataMediaTextExtractor
from mnemosyne.models import Evidence, Relation
from mnemosyne.observability import MetricsRegistry
from mnemosyne.queue import InProcessQueue
from mnemosyne.security import TrustTier
from mnemosyne.storage import LocalObjectStore

CALIBRATE_JOB = "calibrate"
LIFECYCLE_SWEEP_JOB = "lifecycle_sweep"
EVAL_SUITE_JOB = "eval_suite"
OBSERVABILITY_SNAPSHOT_JOB = "observability_snapshot"
PROJECTION_RECOMPUTE_JOB = "projection_recompute"


@dataclass(slots=True)
class RuntimeJobResult:
    kind: str
    status: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeJobHandlers:
    def __init__(
        self,
        engine: Any,
        queue: InProcessQueue,
        metrics: MetricsRegistry | None = None,
        object_store: LocalObjectStore | None = None,
        media_extractor: MediaTextExtractor | None = None,
        learning: Any | None = None,
        user_model: Any | None = None,
        gate_cases: list[RegressionCase] | None = None,
        entity_resolver: EntityResolver | None = None,
        candidate_extractor: CandidateExtractor | None = None,
        summarizer: EvidenceSummarizer | None = None,
    ):
        self.engine = engine
        self.queue = queue
        self.metrics = metrics or MetricsRegistry()
        self.object_store = object_store or LocalObjectStore(".mnemosyne/objects")
        self.media_extractor = media_extractor or MetadataMediaTextExtractor()
        self.learning = learning
        self.gate_cases = gate_cases or []
        self.consolidator = ConsolidationWorker(
            engine,
            gate_cases=self.gate_cases,
            learning=learning,
            entity_resolver=entity_resolver,
            candidate_extractor=candidate_extractor,
            summarizer=summarizer,
            user_model=user_model,
        )

    def handlers(self) -> dict[str, Any]:
        return {
            CONSOLIDATE_EVIDENCE_JOB: self.consolidator.run_queue_payload,
            CALIBRATE_JOB: self.run_calibration,
            LIFECYCLE_SWEEP_JOB: self.run_lifecycle_sweep,
            EVAL_SUITE_JOB: self.run_eval_suite,
            OBSERVABILITY_SNAPSHOT_JOB: self.run_observability_snapshot,
            MEDIA_EXTRACT_JOB: self.run_media_extract,
            PROJECTION_RECOMPUTE_JOB: self.run_projection_recompute,
        }

    def run_projection_recompute(self, payload: dict[str, Any]) -> RuntimeJobResult:
        tenant_id = str(payload["tenant_id"])
        branch = str(payload.get("branch", "main"))
        changed_cids = _payload_cids(payload)
        if not changed_cids:
            raise ValueError("projection recompute requires changed evidence CIDs")
        snapshot = _tenant_snapshot(self.engine, tenant_id)
        affected_cids = _affected_evidence_cids(snapshot, tenant_id, branch, changed_cids)
        projections = _affected_projections(snapshot, tenant_id, branch, affected_cids)
        queued_jobs = []
        if bool(payload.get("enqueue_consolidation", True)):
            passes = [str(name) for name in payload.get("passes") or DEFAULT_CONSOLIDATION_PASSES]
            for cid in _surviving_evidence_cids(snapshot, tenant_id, branch, affected_cids):
                job = self.queue.enqueue(
                    CONSOLIDATE_EVIDENCE_JOB,
                    {
                        "tenant_id": tenant_id,
                        "user_id": str(payload.get("user_id", "system")),
                        "branch": branch,
                        "source_evidence_cids": [cid],
                        "trigger": PROJECTION_RECOMPUTE_JOB,
                        "passes": passes,
                    },
                )
                queued_jobs.append(job.id)
        self.metrics.increment("projection_recompute.completed")
        return RuntimeJobResult(
            PROJECTION_RECOMPUTE_JOB,
            "complete",
            {
                "tenant_id": tenant_id,
                "branch": branch,
                "changed_evidence_cids": changed_cids,
                "affected_evidence_cids": affected_cids,
                "affected_projection_counts": {key: len(value) for key, value in projections.items()},
                "affected_projections": projections,
                "queued_consolidation_jobs": queued_jobs,
            },
        )

    def run_media_extract(self, payload: dict[str, Any]) -> RuntimeJobResult:
        tenant_id = str(payload["tenant_id"])
        branch = str(payload.get("branch", "main"))
        source_cid = str(payload["source_evidence_cid"])
        source = _get_evidence(self.engine, tenant_id, source_cid, branch)
        content_pointer = str(payload.get("content_pointer") or getattr(source, "content_pointer", "") or "")
        if not content_pointer:
            self.metrics.increment("media_extract.skipped")
            return RuntimeJobResult(
                MEDIA_EXTRACT_JOB,
                "skipped",
                {"source_evidence_cid": source_cid, "reason": "missing_content_pointer"},
            )

        media_type = str(
            payload.get("media_type")
            or getattr(source, "metadata", {}).get("media_type", "application/octet-stream")
        )
        modality = str(payload.get("modality") or getattr(source, "modality", "binary"))
        metadata = dict(getattr(source, "metadata", {}) or {})
        metadata.update(payload.get("metadata", {}) or {})
        extracted = self.media_extractor.extract(
            self.object_store.read_bytes(content_pointer),
            media_type=media_type,
            modality=modality,
            metadata=metadata,
        )
        text = extracted.text.strip()
        if not text:
            self.metrics.increment("media_extract.empty")
            return RuntimeJobResult(
                MEDIA_EXTRACT_JOB,
                "skipped",
                {"source_evidence_cid": source_cid, "reason": "empty_extraction"},
            )

        source_trust = int(payload.get("source_trust_tier", getattr(source, "trust_tier", int(TrustTier.NORMAL))))
        trust_tier = max(source_trust, int(TrustTier.AUTHENTICATED))
        capability_tags = sorted(
            set(
                list(getattr(source, "capability_tags", []) or [])
                + list(payload.get("capability_tags", []) or [])
                + ["derived-from-media", "tool-authored", "source:media-extraction"]
            )
        )
        if trust_tier >= int(TrustTier.UNTRUSTED_EXTERNAL):
            capability_tags = sorted(set(capability_tags + ["data-only", "no-write-authority"]))

        derived_cid = self.engine.append_evidence(
            Evidence(
                tenant_id=tenant_id,
                user_id=str(payload.get("user_id") or getattr(source, "user_id", "system")),
                actor="tool",
                source_type="media-extraction",
                source_identity=str(payload.get("extractor_id", "media-extractor")),
                content=text,
                content_pointer=content_pointer,
                modality="text",
                metadata={
                    "source_evidence_cid": source_cid,
                    "source_content_pointer": content_pointer,
                    "source_modality": modality,
                    "media_type": media_type,
                    "derived_text_sources": extracted.sources,
                    "extraction": extracted.metadata,
                },
                trust_tier=trust_tier,
                capability_tags=capability_tags,
                sensitivity=int(payload.get("sensitivity", getattr(source, "sensitivity", 0))),
                access_policy=dict(getattr(source, "access_policy", {}) or {"tenant": tenant_id}),
            ),
            branch=branch,
        )
        relation_id = self.engine.add_relation(
            Relation(
                tenant_id=tenant_id,
                source=source_cid,
                predicate="media-derived-text",
                target=derived_cid,
                confidence=1.0,
                source_evidence_cids=[source_cid, derived_cid],
                access_policy=dict(getattr(source, "access_policy", {}) or {"tenant": tenant_id}),
            ),
            branch=branch,
        )
        self.queue.enqueue(
            CONSOLIDATE_EVIDENCE_JOB,
            {
                "tenant_id": tenant_id,
                "user_id": str(payload.get("user_id") or getattr(source, "user_id", "system")),
                "branch": branch,
                "source_evidence_cids": [derived_cid],
                "trigger": MEDIA_EXTRACT_JOB,
                "passes": list(DEFAULT_CONSOLIDATION_PASSES),
                "trust_tier": trust_tier,
                "sensitivity": int(payload.get("sensitivity", getattr(source, "sensitivity", 0))),
                "capability_tags": capability_tags,
                "modality": "text",
                "source_type": "media-extraction",
                "source_identity": str(payload.get("extractor_id", "media-extractor")),
            },
        )
        self.metrics.increment("media_extract.completed")
        return RuntimeJobResult(
            MEDIA_EXTRACT_JOB,
            "complete",
            {
                "source_evidence_cid": source_cid,
                "derived_cid": derived_cid,
                "relation_id": relation_id,
                "derived_text_sources": extracted.sources,
            },
        )

    def run_calibration(self, payload: dict[str, Any]) -> RuntimeJobResult:
        examples = payload.get("examples")
        if isinstance(examples, list):
            tuning = tune_calibration_set(
                tenant_id=str(payload["tenant_id"]),
                memory_type=str(payload.get("memory_type", "fact")),
                examples=calibration_examples_from_rows(examples),
                target_coverage=float(payload.get("target_coverage", 0.9)),
                min_examples=int(payload.get("min_examples", 20)),
                min_correct=int(payload.get("min_correct", 1)),
                min_incorrect=int(payload.get("min_incorrect", 1)),
                min_empirical_coverage=(
                    float(payload["min_empirical_coverage"])
                    if payload.get("min_empirical_coverage") is not None
                    else None
                ),
                max_false_accept_rate=float(payload.get("max_false_accept_rate", 0.1)),
                max_prediction_set_size=int(payload.get("max_prediction_set_size", 3)),
            )
            self.metrics.gauge(f"calibration.{tuning.calibration.memory_type}.threshold", tuning.threshold)
            self.metrics.increment("calibration.jobs")
            if tuning.metrics["abstention_rate"] > 0:
                self.metrics.increment("calibration.abstentions")
            if tuning.ok and hasattr(self.engine, "set_calibration"):
                self.engine.set_calibration(tuning.calibration)
            details = tuning.to_dict()
            details["applied"] = bool(tuning.ok)
            return RuntimeJobResult(
                CALIBRATE_JOB,
                "complete" if tuning.ok else "failed",
                details,
            )
        calibration = CalibrationSet(
            tenant_id=str(payload["tenant_id"]),
            memory_type=str(payload.get("memory_type", "fact")),
            scores=[float(score) for score in payload.get("scores", [])],
            target_coverage=float(payload.get("target_coverage", 0.9)),
        )
        threshold = conformal_threshold(calibration)
        confidence = float(payload.get("confidence", threshold))
        prediction_set_size = int(payload.get("prediction_set_size", 1))
        abstain = should_abstain(confidence, calibration, prediction_set_size=prediction_set_size)
        if hasattr(self.engine, "set_calibration"):
            self.engine.set_calibration(calibration)
        self.metrics.gauge(f"calibration.{calibration.memory_type}.threshold", threshold)
        self.metrics.increment("calibration.jobs")
        if abstain:
            self.metrics.increment("calibration.abstentions")
        return RuntimeJobResult(
            CALIBRATE_JOB,
            "complete",
            {
                "tenant_id": calibration.tenant_id,
                "memory_type": calibration.memory_type,
                "threshold": threshold,
                "confidence": confidence,
                "abstain": abstain,
            },
        )

    def run_lifecycle_sweep(self, payload: dict[str, Any]) -> RuntimeJobResult:
        now = _parse_dt(payload.get("now")) or datetime.now(UTC)
        threshold = float(payload.get("utility_threshold", 0.18))
        updated: list[dict[str, Any]] = []
        demoted = 0
        rehearsed = 0
        for row in payload.get("states", []):
            state = _lifecycle_state_from_dict(row)
            scheduled_state, did_rehearse = apply_rehearsal_schedule(state, now)
            next_state, changed = demotion_decision(scheduled_state, now, utility_threshold=threshold)
            if changed:
                demoted += 1
            if did_rehearse:
                rehearsed += 1
            state_payload = next_state.to_dict()
            state_payload["demoted"] = changed
            state_payload["rehearsed"] = did_rehearse
            updated.append(state_payload)
        self.metrics.increment("lifecycle.sweeps")
        self.metrics.increment("lifecycle.demotions", demoted)
        self.metrics.increment("lifecycle.rehearsals", rehearsed)
        self.metrics.gauge("lifecycle.demotions.latest", float(demoted))
        self.metrics.gauge("lifecycle.rehearsals.latest", float(rehearsed))
        return RuntimeJobResult(
            LIFECYCLE_SWEEP_JOB,
            "complete",
            {"evaluated": len(updated), "demoted": demoted, "rehearsed": rehearsed, "states": updated},
        )

    def run_eval_suite(self, payload: dict[str, Any]) -> RuntimeJobResult:
        outcomes = run_seed_suite()
        passed = sum(1 for item in outcomes if item.passed)
        failed = len(outcomes) - passed
        self.metrics.increment("eval.suites")
        self.metrics.increment("eval.cases.passed", passed)
        self.metrics.increment("eval.cases.failed", failed)
        return RuntimeJobResult(
            EVAL_SUITE_JOB,
            "complete",
            {
                "suite": str(payload.get("suite", "seed")),
                "passed": failed == 0,
                "outcomes": [asdict(item) for item in outcomes],
            },
        )

    def run_observability_snapshot(self, payload: dict[str, Any]) -> RuntimeJobResult:
        self.metrics.increment("observability.snapshots")
        return RuntimeJobResult(
            OBSERVABILITY_SNAPSHOT_JOB,
            "complete",
            {
                "queue": self.queue.snapshot(),
                "metrics": self.metrics.snapshot().to_dict(),
            },
        )


def _payload_cids(payload: dict[str, Any]) -> list[str]:
    raw = (
        payload.get("changed_evidence_cids")
        or payload.get("evidence_cids")
        or payload.get("source_evidence_cids")
        or payload.get("cid")
    )
    if isinstance(raw, str):
        values = [raw]
    else:
        values = list(raw or [])
    cids: list[str] = []
    seen: set[str] = set()
    for value in values:
        cid = str(value)
        if cid and cid not in seen:
            cids.append(cid)
            seen.add(cid)
    return cids


def _tenant_snapshot(engine: Any, tenant_id: str) -> dict[str, Any]:
    export_tenant = getattr(engine, "export_tenant", None)
    if not callable(export_tenant):
        raise RuntimeError("projection recompute requires an engine with export_tenant")
    snapshot = export_tenant(tenant_id)
    if not isinstance(snapshot, dict):
        raise RuntimeError("projection recompute export_tenant returned non-object snapshot")
    return snapshot


def _affected_evidence_cids(
    snapshot: dict[str, Any],
    tenant_id: str,
    branch: str,
    changed_cids: list[str],
) -> list[str]:
    affected = set(changed_cids)
    ordered = list(changed_cids)
    changed = True
    while changed:
        changed = False
        for row in snapshot.get("evidence", []):
            if not _matches_tenant_branch(row, tenant_id, branch):
                continue
            cid = str(row.get("cid", ""))
            metadata = row.get("metadata") or {}
            source_cids = _metadata_source_cids(metadata)
            if cid and source_cids.intersection(affected) and cid not in affected:
                affected.add(cid)
                ordered.append(cid)
                changed = True
        for row in snapshot.get("relations", []):
            if not _matches_tenant_branch(row, tenant_id, branch):
                continue
            if str(row.get("predicate", "")) not in {"media-derived-text", "summary-derived-gist"}:
                continue
            source = str(row.get("source", ""))
            target = str(row.get("target", ""))
            if source in affected and target and target not in affected:
                affected.add(target)
                ordered.append(target)
                changed = True
    return ordered


def _metadata_source_cids(metadata: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    single = metadata.get("source_evidence_cid")
    if single:
        sources.add(str(single))
    values = metadata.get("source_evidence_cids")
    if isinstance(values, list):
        sources.update(str(item) for item in values if item)
    summary = metadata.get("summary")
    if isinstance(summary, dict):
        summary_values = summary.get("source_evidence_cids")
        if isinstance(summary_values, list):
            sources.update(str(item) for item in summary_values if item)
    return sources


def _affected_projections(
    snapshot: dict[str, Any],
    tenant_id: str,
    branch: str,
    affected_cids: list[str],
) -> dict[str, list[str]]:
    affected = set(affected_cids)
    return {
        "assertions": _projection_ids(snapshot.get("assertions", []), tenant_id, branch, affected, "id"),
        "preferences": _projection_ids(snapshot.get("preferences", []), tenant_id, branch, affected, "id"),
        "relations": _projection_ids(snapshot.get("relations", []), tenant_id, branch, affected, "id"),
        "entities": _projection_ids(snapshot.get("entities", []), tenant_id, branch, affected, "canonical"),
    }


def _surviving_evidence_cids(
    snapshot: dict[str, Any],
    tenant_id: str,
    branch: str,
    affected_cids: list[str],
) -> list[str]:
    affected = set(affected_cids)
    surviving: list[str] = []
    for row in snapshot.get("evidence", []):
        if not _matches_tenant_branch(row, tenant_id, branch):
            continue
        cid = str(row.get("cid", ""))
        if (
            cid in affected
            and not bool(row.get("erased", False))
            and str(row.get("source_type", "")) != "consolidation-summary"
        ):
            surviving.append(cid)
    return surviving


def _projection_ids(
    rows: list[dict[str, Any]],
    tenant_id: str,
    branch: str,
    affected_cids: set[str],
    key_field: str,
) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not _matches_tenant_branch(row, tenant_id, branch):
            continue
        sources = {str(cid) for cid in row.get("source_evidence_cids", [])}
        if not sources.intersection(affected_cids):
            continue
        item_id = str(row.get(key_field) or row.get("id") or row.get("key") or "")
        if item_id:
            ids.append(item_id)
    return sorted(set(ids))


def _matches_tenant_branch(row: dict[str, Any], tenant_id: str, branch: str) -> bool:
    if row.get("tenant_id") not in {None, tenant_id}:
        return False
    if row.get("branch") not in {None, branch}:
        return False
    return True


def _parse_dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _lifecycle_state_from_dict(row: dict[str, Any]) -> LifecycleState:
    return LifecycleState(
        item_id=str(row["item_id"]),
        tier=FidelityTier(str(row.get("tier", FidelityTier.VERBATIM.value))),
        salience=float(row.get("salience", 0.5)),
        importance=float(row.get("importance", 0.5)),
        access_count=int(row.get("access_count", 0)),
        last_accessed=_parse_dt(row.get("last_accessed")),
        must_keep=bool(row.get("must_keep", False)),
        successful_rehearsals=int(row.get("successful_rehearsals", 0)),
        next_rehearsal_at=_parse_dt(row.get("next_rehearsal_at")),
        last_rehearsed_at=_parse_dt(row.get("last_rehearsed_at")),
        confabulation_risk=bool(row.get("confabulation_risk", False)),
        protected=bool(row.get("protected", False)),
    )


def _get_evidence(engine: Any, tenant_id: str, cid: str, branch: str) -> Any:
    get_evidence = getattr(engine, "get_evidence", None)
    if not callable(get_evidence):
        raise RuntimeError("media extraction requires an engine with get_evidence")
    try:
        evidence = get_evidence(tenant_id, cid, branch)
    except TypeError:
        evidence = get_evidence(tenant_id, cid)
    if evidence is None:
        raise RuntimeError(f"source evidence not found: {cid}")
    return evidence
