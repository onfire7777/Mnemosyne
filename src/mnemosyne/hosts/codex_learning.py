"""Advance a local host's learning when its verified inputs change."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


def _fingerprint(facade, runtime, tenant):
    state = runtime.writer.read(tenant)
    status = runtime.status(tenant)
    payload = {
        "pipeline_version": 4,
        "trainer": type(getattr(facade.tools.parametric, "trainer", None)).__qualname__,
        "trainer_configuration": getattr(getattr(facade.tools.parametric, "trainer", None),
                                         "configuration_fingerprint", lambda: None)(),
        "episodes": [
            row for _, row in sorted(state["episodes"].items())
            if row["status"] == "resolved"
        ],
        "artifacts": state["artifacts"],
        "modes": status["modes"],
        "enabled": status["enabled"],
        "frozen": status["frozen"],
        "pending_reviews": [
            [key, row.get("status"), row.get("next_review_at"), row.get("lease_until")]
            for key, row in sorted(state["policy"].get("hypotheses", {}).items())
            if row.get("status") not in {"verified", "rejected"}
        ],
        "protected_cases": [
            case.to_dict() for case in sorted(
                facade.runtime_state.load_gate_cases(), key=lambda case: case.id
            )
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def advance(facade, tenant, state_path):
    """Consolidate and propose eligible training without creating outcome labels.

    The caller owns the host lock. A failed pass leaves the previous checkpoint
    intact so the next worker can retry it.
    """
    state_path = Path(state_path)
    runtime = facade.tools._learning_runtime()
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    if previous.get("fingerprint") == _fingerprint(facade, runtime, tenant) and (
        not previous.get("retry_after") or time.time() < previous["retry_after"]
    ):
        return previous
    state = runtime.writer.read(tenant)
    report = {
        "resolved_episodes": sum(
            row["status"] == "resolved" for row in state["episodes"].values()
        ),
        "consolidation": runtime.consolidate(tenant),
    }
    facade.tools.learning.load_native([tenant])
    lessons = list(facade.tools.learning.lessons.values())
    procedures = list(facade.tools.learning.procedures.values())
    tier = facade.tools.parametric
    eligible = [item for item in lessons if tier._eligible_source(item, tenant, {"active"})]
    eligible += [
        item for item in procedures
        if tier._eligible_source(item, tenant, {"active", "validated"})
    ]
    report["eligible_training_sources"] = len(eligible)
    retryable = False
    status = runtime.status(tenant)
    if not status["enabled"] or status["frozen"]:
        report["training"] = {"status": "paused"}
    elif eligible:
        try:
            artifact = tier.propose_from_lessons(tenant, lessons, procedures)
            cases = [case for case in facade.runtime_state.load_gate_cases()
                     if case.protected and case.mode == "active"]
            decision = tier.evaluate_measured(artifact, cases)
            report["training"] = {
                "status": artifact.status,
                "artifact_id": artifact.id,
                "metrics": artifact.metrics,
                "activation": decision.reason,
                "promoted": decision.promoted,
            }
            if not decision.promoted:
                # Protected memory or evaluator availability can change without
                # a new episode. Retry conservatively without a training loop.
                report["retry_after"] = time.time() + 300
        except ValueError as error:
            report["training"] = {"status": "waiting_for_evidence", "reason": str(error)}
            retryable = True
    else:
        report["training"] = {"status": "waiting_for_validated_sources"}
    from datetime import datetime
    # The worker must wake queued/leased reviews even if no new task finishes.
    # Previously a matching episode fingerprint could strand them indefinitely.
    pending = runtime.writer.read(tenant)["policy"].get("hypotheses", {}).values()
    review_times = []
    for row in pending:
        if row.get("status") in {"verified", "rejected"}:
            continue
        if row.get("review_complete") and row.get("prediction_candidate_status"):
            continue
        if row.get("review_complete"):
            review_times.append(time.time() + 60)
            continue
        due = row.get("lease_until") if row.get("status") == "running" else row.get("next_review_at")
        try:
            review_times.append(datetime.fromisoformat(due).timestamp() if due else time.time() + 60)
        except (TypeError, ValueError):
            review_times.append(time.time() + 60)
    if review_times:
        report["retry_after"] = min(report.get("retry_after", float("inf")), max(time.time() + 60, min(review_times)))
    # Trainer validation errors may also describe a temporary provider failure.
    # Preserve the diagnostic but let the next worker tick retry the inputs.
    report["fingerprint"] = None if retryable else _fingerprint(facade, runtime, tenant)
    temporary = state_path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        temporary.chmod(0o600)
        json.dump(report, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(state_path)
    return report
