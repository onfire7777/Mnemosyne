"""§31 RAIL 7 — consolidation_cadence_bounds = [5_steps, 24h].

Rail: consolidation passes must run no more often than every 5 steps (lower
bound) and at least every 24h (upper bound). This bounds both runaway
self-editing (too frequent) and staleness (too infrequent).

Enforcement point that DOES exist (proxy):
- ``validate_policy_ops_bundle`` (self_optimization.py:443-462) enforces a
  cadence *window* in HOURS (>= ``min_cadence_window_hours``, default 1.0) and a
  ``max_updates_per_day`` ceiling. This bounds the *policy-ops* cadence, and is
  the closest existing analogue to the rail.

Live consolidation enforcement:
- ``ConsolidationWorker.run_queue_payload`` records a per-tenant pass step and
  timestamp, refuses reruns before five steps have elapsed, and lets stale tenants
  run once the 24h upper bound is crossed.

So: the policy-ops cadence guard remains tested as a proxy, and the structural
[5_steps, 24h] bound on the consolidation worker is tested directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


# --- Surface B: structural [5_steps, 24h] bound on the worker ------------------

def _run_one_pass(worker: ConsolidationWorker, cid: str, *, step: int | None = None, now: datetime | None = None):
    payload = {
        "tenant_id": TENANT,
        "branch": "main",
        "source_evidence_cids": [cid],
        "passes": ["summarizer"],
    }
    if step is not None:
        payload["consolidation_step"] = step
    if now is not None:
        payload["now"] = now.isoformat()
    return worker.run_queue_payload(payload)


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
    _run_one_pass(worker, cid, step=0)

    # Immediately firing a second pass (0 steps elapsed) breaches the 5-step
    # lower bound and must be refused by a cadence governor.
    refused = False
    try:
        _run_one_pass(worker, cid)
    except (ValueError, PermissionError, RuntimeError):
        refused = True
    assert refused, "a consolidation pass fired before the 5-step lower bound must be refused"


def test_stale_consolidation_pass_is_allowed_after_twenty_four_hours():
    engine = fresh_engine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=TENANT,
            user_id=USER,
            actor="user",
            source_type="episode",
            content="A stale workflow should consolidate even when the step count is low.",
            trust_tier=0,
            access_policy={"tenant": TENANT},
        )
    )
    worker = ConsolidationWorker(engine, gate_cases=[])
    first = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

    _run_one_pass(worker, cid, step=0, now=first)
    stale = _run_one_pass(worker, cid, step=1, now=first + timedelta(hours=25))

    assert next(item for item in stale.pass_results if item["name"] == "summarizer")["status"] == "complete"
