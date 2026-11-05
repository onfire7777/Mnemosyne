"""Fault-probe adapter; concrete corruptors are supplied only by test fixtures."""

from __future__ import annotations

from mnemosyne.experience.guards import LearningGuardError
from .families import verify_family


def run_injected_fault(writer, tenant, mutate, *, family, clean_evidence):
    """Observe real writer containment, then let the independent family reject it.

    This module imports no test corruptor and has no production execution path.
    The caller owns its isolated fixture and must provide the harmful mutation.
    """
    before = writer.read(tenant)
    caught = None
    try:
        writer.apply(tenant, "benchmark_fault_injection", mutate)
    except LearningGuardError as error:
        caught = error.code
    after = writer.read(tenant)
    new = [row for key, row in after["defects"].items() if key not in before["defects"]]
    evidence = {**clean_evidence, "guard_detections": len(new)}
    verdict = verify_family(family, evidence)
    unchanged = all(
        before[key] == after[key]
        for key in ("receipts", "episodes", "credit", "stats", "artifacts")
    )
    return {
        "caught_guard": caught,
        "recorded_guards": [row["class"] for row in new],
        "contained": unchanged and bool(after["policy"].get("frozen")),
        "family_rejected": not verdict.passed,
        "family_supported": verdict.supported,
        "evidence": evidence,
    }
