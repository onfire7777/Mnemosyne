"""Probe the current replay-fidelity wiring in src.

This module measures reality, not roadmap intent. The current system has a
counterfactual replay hook wired into ``PromotionGate`` through
``ShadowPolicyOptimizer``. That wiring is safe only if unproven replay fidelity
fails closed: the cold loop must remain shadow-only until real replay pairs meet
the OQ2 bar.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mnemosyne.engine import LocalMemoryEngine  # noqa: E402
from mnemosyne.gate import RegressionCase  # noqa: E402
from mnemosyne.models import Assertion, Evidence  # noqa: E402
from mnemosyne.self_optimization import (  # noqa: E402
    PolicyVariant,
    SelfModelStore,
    ShadowPolicyOptimizer,
)

import corpus  # noqa: E402
import scorer  # noqa: E402


def _source_of(obj) -> str:
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):  # pragma: no cover - defensive
        return ""


def _cf_referenced_in_gate() -> bool:
    src = _source_of(ShadowPolicyOptimizer.evaluate_variant)
    return "counterfactual_hook" in src and "default_counterfactual_hook" in src


def _shadow_only_by_construction() -> bool:
    src = _source_of(ShadowPolicyOptimizer.evaluate_variant)
    return "finally" in src and "OperatingPolicy()" in src


def _default_replay_fails_closed() -> dict:
    tenant = "tenant-replay-fidelity-probe"
    user = "user-replay-fidelity-probe"
    engine = LocalMemoryEngine()
    cid = engine.append_evidence(
        Evidence(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="probe",
            content="Replay fidelity probe must keep unproven promotion in shadow.",
            access_policy={"tenant": tenant},
        )
    )
    engine.upsert_assertion(
        Assertion(
            tenant_id=tenant,
            user_id=user,
            subject="Replay fidelity probe",
            predicate="requires",
            object="shadow promotion",
            confidence=0.95,
            source_evidence_cids=[cid],
            status="active",
            access_policy={"tenant": tenant},
        )
    )
    variant = PolicyVariant(
        id="probe-variant",
        activation_weights={"base_level": 0.35, "semantic": 0.35, "importance": 0.20, "recency": 0.10},
        abstention_threshold=0.45,
        top_k=8,
    )
    case = RegressionCase(
        id="probe-case",
        signature="policy retrieval activation confidence",
        query="replay fidelity probe",
        expected_substring="shadow promotion",
        protected=True,
    )
    optimizer = ShadowPolicyOptimizer(engine, [case], self_model=SelfModelStore())
    result = optimizer.evaluate_variant(tenant, variant)
    return {
        "promoted": result.promoted,
        "counterfactual": result.counterfactual,
        "passed_cases": list(result.passed_cases),
        "failed_cases": list(result.failed_cases),
    }


def probe_current_src(bar: scorer.FidelityBar) -> dict:
    cf_wired = _cf_referenced_in_gate()
    shadow_only = _shadow_only_by_construction()
    default_probe = _default_replay_fails_closed()
    default_counterfactual = default_probe.get("counterfactual") or {}
    default_fail_closed = default_probe["promoted"] is False and default_counterfactual.get("passed") is False

    sample_pairs = corpus.faithful_corpus()
    sample_score = scorer.score_fidelity(
        [pair.proxy for pair in sample_pairs],
        [pair.truth for pair in sample_pairs],
        bar=bar,
    )
    real_pairs_available = 0
    empty_score = scorer.score_fidelity([], [], bar=bar)

    narrative = (
        "**Current status — replay hook wired, promotion still shadow-only until proven.** "
        f"`ShadowPolicyOptimizer` attaches the default replay hook to promotion (`cf_wired={cf_wired}`), "
        f"and restores base policy after evaluation (`shadow_only={shadow_only}`). "
        "The default hook now fails closed when the replay-pair window is below the OQ2 bar: "
        f"default promotion result = {default_probe['promoted']}, reason = "
        f"`{default_counterfactual.get('reason')}`. "
        f"The src-side real replay-pair corpus available to the live cold loop is {real_pairs_available}; "
        f"window {real_pairs_available} < {bar.min_window}, so the proxy is not authorized to promote. "
        "The golden corpus still proves the scorer can authorize a faithful corpus once real pairs exist."
    )

    required_wiring = [
        "Populate real replay pairs in `SelfModelStore.record_replay_pair` from post-promotion outcomes.",
        "Run `replay_fidelity_check.py --require-wired` only after real pairs meet the OQ2 bar.",
        "Keep default promotion fail-closed while the real replay-pair window remains below the OQ2 minimum.",
    ]

    return {
        "cf_wired_into_gate": cf_wired,
        "shadow_only_by_construction": shadow_only,
        "default_replay_fails_closed": default_fail_closed,
        "default_promotion_probe": default_probe,
        "sample_faithful_score": sample_score.to_dict(),
        "real_paired_corpus_size": real_pairs_available,
        "fidelity_score": empty_score.to_dict(),
        "narrative": narrative,
        "required_wiring": required_wiring,
    }
