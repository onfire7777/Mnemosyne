"""Advance a local host's learning when its verified inputs change."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


def learning_progress(state):
    """Describe observed learning evidence without equating enablement with learning."""
    episodes = [row for row in state.get("episodes", {}).values()
                if row.get("status") != "erased"]
    resolved = [row for row in episodes if row.get("status") == "resolved"]
    applied = [row for row in resolved if any(row.get(key) for key in
               ("cited_cids", "used_lessons", "used_skills"))]
    verified = [row for row in applied if row.get("target_outcomes")]
    trials = [row for row in state.get("stats", {}).values()
              if row.get("randomized_served_n") or row.get("randomized_control_n")]
    if not resolved:
        stage = "awaiting_task_outcomes"
    elif not applied:
        stage = "awaiting_memory_use"
    elif not verified:
        stage = "awaiting_target_verification"
    elif not state.get("credit"):
        stage = "collecting_controlled_evidence"
    else:
        stage = "learning_from_verified_use"
    return {
        "stage": stage,
        "captured_episodes": len(episodes),
        "resolved_episodes": len(resolved),
        "applied_memory_episodes": len(applied),
        "verified_memory_episodes": len(verified),
        "credit_rows": len(state.get("credit", {})),
        "controlled_served_trials": sum(row.get("randomized_served_n", 0) for row in trials),
        "controlled_withheld_trials": sum(row.get("randomized_control_n", 0) for row in trials),
    }


def _fingerprint(facade, runtime, tenant):
    state = runtime.writer.read(tenant)
    status = runtime.status(tenant)
    payload = {
        "pipeline_version": 5,
        "trainer": type(getattr(facade.tools.parametric, "trainer", None)).__qualname__,
        "trainer_configuration": getattr(getattr(facade.tools.parametric, "trainer", None),
                                         "configuration_fingerprint", lambda: None)(),
        "episodes": [
            row for _, row in sorted(state["episodes"].items())
            if row["status"] == "resolved"
        ],
        # An authentic failed attempt can be useful before its enclosing task
        # resolves, or after that task recovers. Do not strand these snapshots
        # behind a fingerprint that only observes finalized task rewards.
        "captured_experiments": [
            [key, row.get("status"), row.get("source_cids", []),
             [event for event in row.get("tool_events", [])
              if event.get("experiment_environment")]]
            for key, row in sorted(state["episodes"].items())
            if row.get("status") != "erased" and any(
                event.get("experiment_environment") for event in row.get("tool_events", []))
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
        "environment_reviews": [
            [key, row.get("environment_cohort"), row.get("review_complete"),
             row.get("status"), row.get("environment_result")]
            for key, row in sorted(state["policy"].get("hypotheses", {}).items())
            if row.get("environment_cohort")
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
    state = runtime.writer.read(tenant)
    from mnemosyne.experience.signals import OUTCOME_VERSION
    migration = None
    if callable(getattr(runtime, "reprocess_outcomes", None)) and any(
        row.get("status") in {"resolved", "unknown"}
        and row.get("outcome_version", 1) < OUTCOME_VERSION
        for row in state["episodes"].values()
    ):
        migration = runtime.reprocess_outcomes(tenant)
        state = runtime.writer.read(tenant)
    if previous.get("fingerprint") == _fingerprint(facade, runtime, tenant) and (
        not previous.get("retry_after") or time.time() < previous["retry_after"]
    ):
        return {**previous, "progress": learning_progress(state)}
    report = {
        "resolved_episodes": sum(
            row["status"] == "resolved" for row in state["episodes"].values()
        ),
        "consolidation": runtime.consolidate(tenant),
    }
    if migration is not None:
        report["outcome_repair"] = {"reprocessed": migration.get("reprocessed", 0)}
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
    from mnemosyne.experience.environment_experiments import environment_retry_at
    retry_at = environment_retry_at(runtime.writer.read(tenant))
    if retry_at is not None and runtime._enabled(runtime.writer.read(tenant), "dreamer"):
        # A provider timeout or empty proposal is not proof that a captured
        # failure is unlearnable. Retry with the recorded bounded backoff,
        # without fabricating another task outcome.
        report["retry_after"] = min(report.get("retry_after", float("inf")),
                                    max(time.time() + 300, retry_at))
    # Trainer validation errors may also describe a temporary provider failure.
    # Preserve the diagnostic but let the next worker tick retry the inputs.
    report["fingerprint"] = None if retryable else _fingerprint(facade, runtime, tenant)
    report["progress"] = learning_progress(runtime.writer.read(tenant))
    temporary = state_path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        temporary.chmod(0o600)
        json.dump(report, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(state_path)
    return report
