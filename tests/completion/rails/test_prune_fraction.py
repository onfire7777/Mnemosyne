"""§31 RAIL 3 — max_prune_fraction_per_pass = 0.02 (<=2% pruned per pass).

"Prune" in the lifecycle model is a fidelity *demotion* (verbatim ->
extractive_summary -> abstractive_gist -> statistical_trace) performed by the
consolidation forgetter. The rail caps how much of a pass's working set may be
pruned/demoted in a single consolidation pass at 2%.

Two enforcement surfaces:

1. Parametric metrics gate (ENFORCED): ``ParametricInvariantRails`` rejects a
   self-reported ``prune_fraction`` > 0.02. Covered by test_parametric_rail_gate.py.

2. Live consolidation pass (ENFORCED): ``ConsolidationWorker._run_forgetter``
   counts lifecycle demotions against a per-pass mutation rail budget and
   defers additional low-utility items once the 2% budget is exhausted.

This file drives surface (2) end-to-end through ``run_queue_payload`` and asserts
the demoted fraction is clamped to <= 0.02.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.models import Evidence

from .conftest import TENANT, USER, fresh_engine

PASS_SIZE = 50
MAX_PRUNE_FRACTION = 0.02


def _seed_stale_working_set(engine, n: int = PASS_SIZE) -> list[str]:
    """Seed `n` evidence rows that all decay below the utility threshold, so the
    forgetter would demote every one of them absent a fraction cap."""

    stale = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    cids: list[str] = []
    for i in range(n):
        cid = engine.append_evidence(
            Evidence(
                tenant_id=TENANT,
                user_id=USER,
                actor="user",
                source_type="episode",
                content=f"ephemeral low-utility note {i}",
                trust_tier=0,
                access_policy={"tenant": TENANT},
                metadata={
                    "lifecycle": {
                        "tier": "verbatim",
                        "salience": 0.01,
                        "importance": 0.0,
                        "access_count": 0,
                        "last_accessed": stale,
                    }
                },
            )
        )
        cids.append(cid)
    return cids


def _run_forgetter_pass(engine, cids: list[str]) -> dict:
    worker = ConsolidationWorker(engine, gate_cases=[])
    result = worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "branch": "main",
            "source_evidence_cids": cids,
            "passes": ["forgetter"],
            "utility_threshold": 0.18,
            "now": datetime.now(UTC).isoformat(),
        }
    )
    for entry in result.pass_results:
        if entry["name"] == "forgetter":
            return entry["details"]
    raise AssertionError("forgetter pass did not run")


def test_forgetter_pass_is_clamped_to_two_percent():
    engine = fresh_engine()
    cids = _seed_stale_working_set(engine)

    details = _run_forgetter_pass(engine, cids)

    evaluated = int(details["evaluated"])
    demoted = int(details["demoted"])
    assert evaluated == PASS_SIZE
    allowed = int(PASS_SIZE * MAX_PRUNE_FRACTION) or 1  # 2% of 50 == 1
    assert demoted <= allowed, (
        f"forgetter demoted {demoted}/{evaluated} in one pass; "
        f"max_prune_fraction_per_pass=0.02 allows at most {allowed}"
    )
    assert details["rail_budget"]["prunes_used"] == demoted
    assert details["rail_budget"]["violations"]


def test_prune_fraction_metric_gate_is_the_only_current_enforcement():
    """Pins the parametric metrics gate in addition to live-pass enforcement."""

    from mnemosyne.parametric import ParametricArtifact, ParametricInvariantRails

    rails = ParametricInvariantRails()
    over = ParametricArtifact(
        tenant_id="tenant-rails",
        source_ids=["x"],
        adapter_kind="local-shadow-adapter",
        metrics={"prune_fraction": 0.03},
    )
    with pytest.raises(ValueError, match="prune_fraction exceeds 0.02"):
        rails.proposal_report(over, provider={})
