"""Runtime job handlers for local queue-backed memory maintenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB, DEFAULT_CONSOLIDATION_PASSES, ConsolidationWorker, EntityResolver
from mnemosyne.eval import run_seed_suite
from mnemosyne.gate import RegressionCase
from mnemosyne.lifecycle import FidelityTier, LifecycleState, demotion_decision
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
        gate_cases: list[RegressionCase] | None = None,
        entity_resolver: EntityResolver | None = None,
    ):
        self.engine = engine
        self.queue = queue
        self.metrics = metrics or MetricsRegistry()
        self.object_store = object_store or LocalObjectStore(".mnemosyne/objects")
        self.media_extractor = media_extractor or MetadataMediaTextExtractor()
        self.learning = learning
        self.gate_cases = gate_cases or []
        self.consolidator = ConsolidationWorker(engine, gate_cases=self.gate_cases, learning=learning, entity_resolver=entity_resolver)

    def handlers(self) -> dict[str, Any]:
        return {
            CONSOLIDATE_EVIDENCE_JOB: self.consolidator.run_queue_payload,
            CALIBRATE_JOB: self.run_calibration,
            LIFECYCLE_SWEEP_JOB: self.run_lifecycle_sweep,
            EVAL_SUITE_JOB: self.run_eval_suite,
            OBSERVABILITY_SNAPSHOT_JOB: self.run_observability_snapshot,
            MEDIA_EXTRACT_JOB: self.run_media_extract,
        }

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
        for row in payload.get("states", []):
            state = _lifecycle_state_from_dict(row)
            next_state, changed = demotion_decision(state, now, utility_threshold=threshold)
            if changed:
                demoted += 1
            updated.append(next_state.to_dict())
        self.metrics.increment("lifecycle.sweeps")
        self.metrics.increment("lifecycle.demotions", demoted)
        self.metrics.gauge("lifecycle.demotions.latest", float(demoted))
        return RuntimeJobResult(
            LIFECYCLE_SWEEP_JOB,
            "complete",
            {"evaluated": len(updated), "demoted": demoted, "states": updated},
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
                "outcomes": [item.__dict__ for item in outcomes],
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
