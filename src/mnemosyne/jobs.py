"""Runtime job handlers for local queue-backed memory maintenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.consolidation import CONSOLIDATE_EVIDENCE_JOB, ConsolidationWorker
from mnemosyne.eval import run_seed_suite
from mnemosyne.lifecycle import FidelityTier, LifecycleState, demotion_decision
from mnemosyne.observability import MetricsRegistry
from mnemosyne.queue import InProcessQueue

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
    ):
        self.engine = engine
        self.queue = queue
        self.metrics = metrics or MetricsRegistry()
        self.consolidator = ConsolidationWorker(engine, gate_cases=[])

    def handlers(self) -> dict[str, Any]:
        return {
            CONSOLIDATE_EVIDENCE_JOB: self.consolidator.run_queue_payload,
            CALIBRATE_JOB: self.run_calibration,
            LIFECYCLE_SWEEP_JOB: self.run_lifecycle_sweep,
            EVAL_SUITE_JOB: self.run_eval_suite,
            OBSERVABILITY_SNAPSHOT_JOB: self.run_observability_snapshot,
        }

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
