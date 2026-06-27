"""G0 unified-substrate cascade and observability fixture.

This is the pre-owner-checkpoint slice of Phase 7 P5: it proves Standing is
observable/replayable and that erasure/dependency cascades reach self-derived
content. It deliberately does not remove `shadow_only` or `enabled` toggles.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mnemosyne.belief import BeliefRevisionCore
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, Evidence
from mnemosyne.privacy import ErasureMode


def run_unified_substrate_eval() -> dict[str, Any]:
    """Return deterministic H8/H12 pre-checkpoint metrics."""

    tenant = "g0-unified-substrate"
    engine = LocalMemoryEngine()
    source_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="eval",
            actor="g0",
            source_type="operator_note",
            source_identity="g0:source",
            content="Unified substrate source evidence.",
            metadata={"reality_class": "grounded", "confidence": 1.0},
            trust_tier=0,
            access_policy={"tenant": tenant},
        )
    )
    derived_cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id="eval",
            actor="g0",
            source_type="workspace-reflection",
            source_identity="g0:self-derivation",
            content="Self-derived reflection from unified substrate source evidence.",
            metadata={"reality_class": "self_generated", "source_evidence_cids": [source_cid]},
            trust_tier=5,
            access_policy={"tenant": tenant},
        )
    )
    retrieval = engine.retrieve("unified substrate source evidence", tenant)
    trace = next(
        (
            hit.metadata.get("standing_observability")
            for hit in retrieval.hits
            if hit.id == source_cid and isinstance(hit.metadata.get("standing_observability"), dict)
        ),
        {},
    )
    forget = engine.forget(tenant, source_cid, erasure_mode=ErasureMode.TOMBSTONE_RECOMPUTE)
    cascade = forget["propagated"].get("standing_cascade", {})
    erased_self = [
        action
        for action in cascade.get("self_derivation_actions", [])
        if action.get("cid") == derived_cid and action.get("action") == "erased_self_derivation"
    ]

    core = BeliefRevisionCore(engine)
    root = core.revise(_assertion(tenant, "root"))
    child = core.add_derived_belief(_assertion(tenant, "derived"), dependency_ids=[root.assertion_id])
    invalidated = core.cascade_invalidate(tenant, root.assertion_id, reason="g0 dependency contradicted")
    child_row = engine.assertions[engine._branch_key(tenant, "main", child.assertion_id)]
    belief_cascade = child_row.calibration.get("standing_cascade", {})

    metrics = {
        "standing_observability_trace_contract": _contract(
            trace.get("schema_version") == "standing.observability.v1"
            and trace.get("replayable") is True
            and trace.get("h12_observability") is True
            and source_cid in set(trace.get("source_evidence_cids") or [])
        ),
        "standing_erasure_cascade_contract": _contract(
            cascade.get("schema_version") == "standing.erasure-cascade.v1"
            and cascade.get("h8_cascade_to_self_derivations") is True
            and cascade.get("h12_observable_replayable_reversible") is True
            and bool(erased_self)
        ),
        "belief_standing_cascade_contract": _contract(
            root.assertion_id in invalidated
            and child.assertion_id in invalidated
            and belief_cascade.get("schema_version") == "standing.belief-cascade.v1"
            and belief_cascade.get("standing_recomputed_on_read") is True
            and belief_cascade.get("h12_observable_replayable_reversible") is True
        ),
    }
    return {
        "schema_version": "g0.unified_substrate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "definition": (
            "Pre-checkpoint Phase 7 P5 fixture proving Standing observability "
            "and cascade/replay contracts before operational toggle retirement."
        ),
        "measurement_scope": "deterministic local fixture, not production operator evidence",
        "metrics": metrics,
        "standing_observability": trace,
        "standing_cascade": cascade,
        "belief_cascade": belief_cascade,
        "passed": all(value == 1.0 for value in metrics.values()),
    }


def _assertion(tenant_id: str, object_value: str) -> Assertion:
    return Assertion(
        tenant_id=tenant_id,
        user_id="eval",
        subject="unified-substrate",
        predicate="cascade",
        object=object_value,
        confidence=0.9,
        source_evidence_cids=[],
        trust_tier=0,
        access_policy={"tenant": tenant_id},
    )


def _contract(ok: bool) -> float:
    return 1.0 if ok else 0.0
