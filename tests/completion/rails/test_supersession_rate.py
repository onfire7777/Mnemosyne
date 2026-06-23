"""§31 RAIL 1 — max_supersession_rate = 0.05 (<=5% of active facts superseded per pass).

Two enforcement surfaces matter:

1. Parametric metrics gate (ENFORCED): ``ParametricInvariantRails`` rejects a
   self-reported ``supersession_rate`` > 0.05. Covered by
   test_parametric_rail_gate.py.

2. Live belief-revision pass (GAP): a batch of incoming assertions that
   supersedes far more than 5% of the active set is applied by
   ``LocalMemoryEngine.upsert_assertion`` with NO per-pass rate ceiling. There is
   no batch/"pass" abstraction in engine.py that counts supersessions against the
   active-fact denominator and clamps/refuses once 5% is exceeded.

This file drives surface (2): it builds an active set and then submits a batch of
strictly-more-trusted corrections that supersede 100% of it, and asserts the
system clamps the supersession rate to <= 5%. That assertion fails today, so the
breach test is xfail(strict) until Codex adds a pass-level supersession-rate rail
to the engine write path.
"""

from __future__ import annotations

import pytest

from mnemosyne.security import TrustTier

from .conftest import (
    active_assertions,
    add_evidence,
    fresh_engine,
    make_assertion,
    minutes_ago,
    utcnow,
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


def _apply_supersession_batch(engine, n: int) -> int:
    """Apply `n` strictly-more-trusted conflicting corrections (each legitimately
    supersedes its target under monotonic_trust). Returns how many active facts
    ended up superseded in this single pass."""

    before = {a.id for a in active_assertions(engine)}
    for i in range(n):
        cid = add_evidence(engine, content=f"fact {i} value beta", trust_tier=int(TrustTier.DIRECT_USER))
        engine.upsert_assertion(
            make_assertion(
                subject=f"entity-{i}",
                predicate="value_is",
                obj="beta",
                trust_tier=int(TrustTier.DIRECT_USER),  # more trusted => legal supersede
                source_cids=[cid],
                confidence=0.7,
                valid_from=utcnow(),
            )
        )
    after = {a.id for a in active_assertions(engine)}
    superseded = before - after
    return len(superseded)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RAIL 1 NOT ENFORCED ON LIVE PASS. Missing enforcement point: "
        "LocalMemoryEngine.upsert_assertion (engine.py:397) applies supersessions "
        "one-by-one with no pass-level rate ceiling against the active-fact "
        "denominator. max_supersession_rate=0.05 is only checked on self-reported "
        "metrics in ParametricInvariantRails._check_rate (parametric.py:127). Codex "
        "must add a batch/pass guard to the engine write path that clamps or refuses "
        "once supersessions exceed 5% of the active set in a single pass."
    ),
)
def test_mass_supersession_pass_is_clamped_to_five_percent():
    engine = fresh_engine()
    _seed_active_population(engine)

    # Adversary submits corrections that would supersede every active fact.
    superseded = _apply_supersession_batch(engine, ACTIVE_COUNT)

    allowed = int(ACTIVE_COUNT * MAX_RATE)  # == 2
    assert superseded <= allowed, (
        f"single pass superseded {superseded}/{ACTIVE_COUNT} active facts; "
        f"max_supersession_rate=0.05 allows at most {allowed}"
    )


def test_supersession_rate_metric_gate_is_the_only_current_enforcement():
    """Documents the enforcement that DOES exist: the parametric metrics gate.
    Kept green so the suite records that the rail is partially enforced (and to
    pin the 0.05 bound), while the live-pass gap above stays xfail."""

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
