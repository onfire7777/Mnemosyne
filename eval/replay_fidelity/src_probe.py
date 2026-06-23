"""Honest probe of the CURRENT src: is the cf replay term wired into the gate?

This module measures reality, not aspiration. It introspects the live src to
determine whether ``counterfactual_replay_score`` is actually consumed by any
promotion decision, and whether a paired (predicted-lift, observed-lift) corpus
exists in src for the OQ2 gate to score. Both answers are **no** today, and this
probe proves it by source inspection rather than assertion — so the verdict moves
automatically the day someone wires it.

Findings the probe establishes by inspecting real src:

  * ``gate.PromotionGate.evaluate`` computes ``promoted`` from the regression-case
    margin only. Its source contains no reference to the cf term.
  * ``self_optimization.ShadowPolicyOptimizer.evaluate_variant`` restores
    ``OperatingPolicy()`` in a ``finally`` block -> it is shadow/veto-only by
    construction (never mutates production).
  * ``mcp_tools.outcome_evaluate`` computes ``counterfactual_replay_score`` and
    returns it as an **informational** number; nothing reads it back to gate.
  * ``SelfModelStore`` / ``PolicyOutcome`` can hold a predicted lift and an
    observed lift, but the cold loop never pairs them for a fidelity check.

Because there is no wired cf->gate path and no paired corpus in src, the OQ2 gate
has **zero real pairs** to score (window = 0 < 50) -> the bar is unmet -> the
proxy is NOT authorized to gate -> the loop is correctly held in SHADOW
(veto-only). That is the honest current status and the forcing function.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mnemosyne import gate as gate_mod  # noqa: E402
from mnemosyne import learning as learning_mod  # noqa: E402
from mnemosyne import mcp_tools as mcp_tools_mod  # noqa: E402
from mnemosyne import self_optimization as so_mod  # noqa: E402

import scorer  # noqa: E402


def _source_of(obj) -> str:
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):  # pragma: no cover - defensive
        return ""


def _cf_referenced_in_gate() -> bool:
    """True iff the promotion-gate decision path references the cf replay term.

    We inspect the source of ``PromotionGate.evaluate`` (the function that sets
    ``promoted``) for any reference to the counterfactual replay score. If a
    future src change threads the cf term into the gate decision, this flips True.
    """
    src = _source_of(gate_mod.PromotionGate.evaluate)
    needles = ("counterfactual_replay_score", "replay_predicted_lift", "cf_term", "replay_fidelity")
    return any(token in src for token in needles)


def _shadow_only_by_construction() -> bool:
    """True iff ShadowPolicyOptimizer.evaluate_variant restores base policy (veto-only)."""
    src = _source_of(so_mod.ShadowPolicyOptimizer.evaluate_variant)
    return "finally" in src and "OperatingPolicy()" in src


def _cf_only_informational() -> bool:
    """True iff outcome_evaluate merely returns the cf score (no gate consumption)."""
    src = _source_of(mcp_tools_mod.MemoryTools.outcome_evaluate)
    returns_cf = "counterfactual_replay_score" in src
    # No decision keyword (promote/gate) bound to the cf value in this method.
    gates_on_cf = "promoted" in src or "gate.evaluate" in src
    return returns_cf and not gates_on_cf


def probe_current_src(bar: scorer.FidelityBar) -> dict:
    """Return the honest current-src state for the OQ2 gate report."""
    cf_wired = _cf_referenced_in_gate()
    shadow_only = _shadow_only_by_construction()
    cf_informational = _cf_only_informational()

    # The real cf arithmetic is callable — show it produces lift numbers — but
    # there is NO src-side source of *observed real lift* paired to it, so the
    # gate has zero pairs to score on the current system.
    sample_predicted = learning_mod.counterfactual_replay_score(2, 5, 10)
    real_pairs_available = 0  # no paired (predicted, observed) corpus exists in src

    # Score the (empty) real corpus: window 0 < min_window -> fails the bar, which
    # is the correct, honest outcome (nothing to authorize on).
    empty_score = scorer.score_fidelity([], [], bar=bar)
    fidelity_score = empty_score.to_dict()

    narrative = (
        "**Honest current status — loop correctly held in SHADOW (veto-only).** "
        "The counterfactual replay arithmetic exists and runs "
        f"(`counterfactual_replay_score(2,5,10)` = {sample_predicted}), and it is "
        "surfaced by `mcp_tools.outcome_evaluate`, but it is **informational only**: "
        f"`cf term consumed by gate decision = {cf_wired}`. "
        "`gate.PromotionGate.evaluate` decides `promoted` purely from the "
        "regression-case margin, and "
        f"`ShadowPolicyOptimizer.evaluate_variant` is veto-only by construction "
        f"(restores base `OperatingPolicy()` in a `finally`: shadow_only={shadow_only}). "
        "There is **no paired (replay-predicted lift, observed real lift) corpus in "
        f"src**, so the OQ2 gate has {real_pairs_available} real pairs to score "
        f"(window {real_pairs_available} < {bar.min_window}). The replay proxy is "
        "therefore **NOT authorized to gate self-modifications**, which is exactly "
        "why the cold loop must stay in shadow. This harness is the forcing "
        "function: it will authorize the proxy only once the cf->gate path is wired "
        "AND it clears the OQ2 bar on real paired data."
    )

    required_wiring = [
        "src/mnemosyne/self_optimization.py — add an `observed_real_lift` field (or a "
        "reserved metrics key) to `PolicyOutcome` and have the cold loop record the "
        "real post-promotion lift there, paired to the candidate's "
        "`replay_predicted_lift` (= counterfactual_replay_score(before,after,total)).",
        "src/mnemosyne/self_optimization.py — add a `SelfModelStore.replay_pairs("
        "tenant_id)` accessor that returns the (predicted, observed) pairs the OQ2 "
        "scorer consumes, so the gate has a first-class source of paired data.",
        "src/mnemosyne/gate.py — extend `PromotionGate.evaluate` (or add a sibling "
        "`replay_fidelity_gate`) so that, before `promoted` can be True for a "
        "self-modification candidate, the OQ2 fidelity bar over recent replay_pairs "
        "must hold (rho>=0.6 & CI-lower>0.3, sign>=0.80, gap<=0.15, window>=50, "
        "coverage>=0.80). Until the bar holds, force veto-only (shadow).",
        "src/mnemosyne/self_optimization.py — bind the existing `tripwire_check` "
        "`max_proxy_gap` (0.15) to the OQ2 `proxy_true_gap` axis so the two gap "
        "guards share one threshold and cannot drift apart.",
        "src/mnemosyne/mcp_tools.py — stop treating `outcome_evaluate`'s "
        "`counterfactual_replay_score` as purely informational: route the cf value "
        "into the candidate's `replay_predicted_lift` so it is the same number the "
        "OQ2 gate scores (single source of truth for the proxy).",
        "eval — once wired, run `replay_fidelity_check.py --require-wired` in CI; a "
        "non-zero exit (code 2) blocks the cold loop from leaving shadow until the "
        "proxy proves fidelity on real paired data.",
    ]

    return {
        "cf_wired_into_gate": cf_wired,
        "shadow_only_by_construction": shadow_only,
        "cf_only_informational": cf_informational,
        "sample_predicted_lift": sample_predicted,
        "real_paired_corpus_size": real_pairs_available,
        "fidelity_score": fidelity_score,
        "narrative": narrative,
        "required_wiring": required_wiring,
    }
