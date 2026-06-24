"""§31 RAIL 1 — max_supersession_rate = 0.05 (<=5% of active facts superseded per pass).

Two enforcement surfaces matter:

1. Parametric metrics gate (ENFORCED): ``ParametricInvariantRails`` rejects a
   self-reported ``supersession_rate`` > 0.05. Covered by
   test_parametric_rail_gate.py.

2. Live consolidation pass (ENFORCED): candidate assertions promoted through
   ``ConsolidationWorker.run_queue_payload`` are checked against a per-pass
   active-fact denominator before the promotion branch can merge to ``main``.

This file drives surface (2): it builds an active set and then submits a
consolidation batch of strictly-more-trusted candidates that would supersede 100%
of it, and asserts the system clamps the supersession rate to <= 5%.
"""

from __future__ import annotations

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.gate import RegressionCase
from mnemosyne.security import TrustTier

from .conftest import (
    active_assertions,
    add_evidence,
    fresh_engine,
    make_assertion,
    minutes_ago,
)

ACTIVE_COUNT = 40  # 5% of 40 == 2 facts allowed per pass
MAX_RATE = 0.05


def _seed_active_population(engine, n: int = ACTIVE_COUNT):
    """Seed `n` distinct active facts at a middling trust tier so a more-trusted
    correction batch can attempt to supersede them."""

    for i in range(n):
        cid = add_evidence(engine, content=f"fact {i} value alpha", trust_tier=int(TrustTier.NORMAL))
        engine.upsert_assertion(
            make_assertion(
                subject=f"entity-{i}",
                predicate="value_is",
                obj="alpha",
                trust_tier=int(TrustTier.NORMAL),
                source_cids=[cid],
                confidence=0.7,
                valid_from=minutes_ago(120),
            )
        )
    assert len(active_assertions(engine)) == n


class _MassSupersessionExtractor:
    def __init__(self, n: int):
        self.n = n

    def extract(self, tenant_id, payload, evidence):
        return {
            "candidates": [
                {
                    "signature": f"entity-{i} value_is",
                    "query": f"entity-{i}",
                    "candidate_subject": f"entity-{i}",
                    "candidate_predicate": "value_is",
                    "candidate_object": "beta",
                    "confidence": 0.7,
                    "trust_tier": int(TrustTier.DIRECT_USER),
                }
                for i in range(self.n)
            ],
            "details": {"provider": "test_mass_supersession_extractor"},
        }


def test_mass_supersession_pass_is_clamped_to_five_percent():
    engine = fresh_engine()
    _seed_active_population(engine)
    before = {a.id for a in active_assertions(engine)}
    source_cids = [
        add_evidence(engine, content=f"fact {i} value beta", trust_tier=int(TrustTier.DIRECT_USER))
        for i in range(ACTIVE_COUNT)
    ]
    worker = ConsolidationWorker(
        engine,
        gate_cases=[
            RegressionCase(
                id="candidate-beta-smoke",
                signature="entity value_is",
                query="entity beta",
                expected_substring="beta",
                tier="smoke",
            )
        ],
        candidate_extractor=_MassSupersessionExtractor(ACTIVE_COUNT),
    )

    result = worker.run_queue_payload(
        {
            "tenant_id": "tenant-rails",
            "branch": "main",
            "source_evidence_cids": source_cids,
            "passes": ["extractor", "resolver", "belief_reviser", "promotion_gate"],
        }
    )

    after = {a.id for a in active_assertions(engine)}
    superseded = len(before - after)
    allowed = int(ACTIVE_COUNT * MAX_RATE)  # == 2
    assert superseded <= allowed, (
        f"single pass superseded {superseded}/{ACTIVE_COUNT} active facts; "
        f"max_supersession_rate=0.05 allows at most {allowed}"
    )
    rails = next(item for item in result.pass_results if item["name"] == "mutation_rails")["details"]
    assert rails["supersessions_used"] == superseded
    assert any(item["rail"] == "max_supersession_rate" for item in rails["violations"])


def test_supersession_rate_metric_gate_is_the_only_current_enforcement():
    """Pins the parametric metrics gate in addition to live-pass enforcement."""

    from mnemosyne.parametric import ParametricArtifact, ParametricInvariantRails

    rails = ParametricInvariantRails()
    over = ParametricArtifact(
        tenant_id="tenant-rails",
        source_ids=["x"],
        adapter_kind="local-shadow-adapter",
        metrics={"supersession_rate": 0.06},
    )
    with pytest.raises(ValueError, match="supersession_rate exceeds 0.05"):
        rails.proposal_report(over, provider={})
