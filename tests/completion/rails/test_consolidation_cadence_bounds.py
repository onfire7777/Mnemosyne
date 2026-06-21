"""§31 RAIL 7 — consolidation_cadence_bounds = [5_steps, 24h].

Rail: consolidation passes must run no more often than every 5 steps (lower
bound) and at least every 24h (upper bound). This bounds both runaway
self-editing (too frequent) and staleness (too infrequent).

Enforcement point that DOES exist (partial / proxy):
- ``validate_policy_ops_bundle`` (self_optimization.py:443-462) enforces a
  cadence *window* in HOURS (>= ``min_cadence_window_hours``, default 1.0) and a
  ``max_updates_per_day`` ceiling. This bounds the *policy-ops* cadence, and is
  the closest existing analogue to the rail.

Gaps vs the literal §31 bound:
- The check is parameterised in hours with a default lower bound of 1.0h, not the
  blueprint's "5 steps" step-count lower bound nor the explicit 24h upper bound.
- It guards the policy-optimization bundle, NOT the consolidation worker. Nothing
  in ``ConsolidationWorker.run_queue_payload`` (consolidation.py:135) records a
  step counter / last-run timestamp or refuses a pass that fires before 5 steps
  have elapsed or forces one after 24h. ``run_queue_payload`` will happily run an
  arbitrary number of back-to-back passes.

So: the policy-ops cadence guard is tested green (it is real), and the missing
structural [5_steps, 24h] bound on the consolidation worker is xfail(strict).
"""

from __future__ import annotations

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.self_optimization import validate_policy_ops_bundle

from .conftest import TENANT, USER, fresh_engine

from mnemosyne.models import Evidence


def _bundle_with_cadence(window_hours: float, updates_per_day: int) -> dict:
    weights = {"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10}
    variant = {
        "id": "v1",
        "activation_weights": dict(weights),
        "abstention_threshold": 0.4,
        "top_k": 8,
        "shadow_mode": True,
    }
    return {
        "tenant_id": TENANT,
        "metric": "retrieval_quality",
        "variants": [variant, {**variant, "id": "v2"}],
        "outcomes": [
            {"variant_id": "v1", "reward": 0.9, "reward_source": "external_eval"},
            {"variant_id": "v2", "reward": 0.5, "reward_source": "external_eval"},
            {"variant_id": "v1", "reward": 0.8, "reward_source": "external_eval"},
        ],
        "tripwires": [{"id": "t1", "diversity": 0.5, "proxy_score": 0.6, "true_score": 0.6}],
        "cadence": {"window_hours": window_hours, "max_updates_per_day": updates_per_day},
        "promotion": {"mode": "shadow", "production_mutation": False},
    }


# --- Surface A: policy-ops cadence guard (ENFORCED proxy) ----------------------

def test_policy_ops_rejects_cadence_window_too_short():
    report = validate_policy_ops_bundle(_bundle_with_cadence(window_hours=0.25, updates_per_day=2))
    codes = {f["code"] for f in report["findings"]}
    assert "cadence_window_too_short" in codes
    assert report["ok"] is False


def test_policy_ops_rejects_too_many_updates_per_day():
    report = validate_policy_ops_bundle(_bundle_with_cadence(window_hours=2.0, updates_per_day=999))
    codes = {f["code"] for f in report["findings"]}
    assert "cadence_updates_too_frequent" in codes


def test_policy_ops_accepts_cadence_within_bounds():
    report = validate_policy_ops_bundle(_bundle_with_cadence(window_hours=6.0, updates_per_day=2))
    codes = {f["code"] for f in report["findings"]}
    assert "cadence_window_too_short" not in codes
    assert "cadence_updates_too_frequent" not in codes


# --- Surface B: MISSING structural [5_steps, 24h] bound on the worker (gap) ----

def _run_one_pass(worker: ConsolidationWorker, cid: str):
    return worker.run_queue_payload(
        {
            "tenant_id": TENANT,
            "branch": "main",
            "source_evidence_cids": [cid],
            "passes": ["summarizer"],
        }
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RAIL 7 NOT STRUCTURALLY ENFORCED ON THE WORKER. Missing enforcement point: "
        "ConsolidationWorker.run_queue_payload (consolidation.py:135) keeps no step "
        "counter or last-run timestamp and never refuses a pass that fires before the "
        "5-step lower bound. The only cadence guard is validate_policy_ops_bundle "
        "(self_optimization.py:443) which bounds the policy-ops bundle in HOURS "
        "(default >=1.0h), not the literal §31 [5_steps, 24h] window, and does not "
        "gate the consolidation worker. Codex must give the worker a per-tenant "
        "cadence governor that refuses sub-5-step re-runs (and flags >24h staleness)."
    ),
)
def test_back_to_back_consolidation_passes_are_rate_limited_to_five_steps():
    engine = fresh_engine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="episode",
            content="A recurring workflow that should consolidate on a bounded cadence.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    worker = ConsolidationWorker(engine, gate_cases=[])

    # First pass is allowed.
    _run_one_pass(worker, cid)

    # Immediately firing a second pass (0 steps elapsed) breaches the 5-step
    # lower bound and must be refused by a cadence governor.
    refused = False
    try:
        _run_one_pass(worker, cid)
    except (ValueError, PermissionError, RuntimeError):
        refused = True
    assert refused, "a consolidation pass fired before the 5-step lower bound must be refused"
