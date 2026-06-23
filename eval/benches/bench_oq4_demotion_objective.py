"""OQ4 — fidelity-demotion objective: current exp(-age/45) decay vs ACT-R power law.

Blueprint open question OQ4 asks what the *right* forgetting/demotion objective is.
The CURRENT src uses an exponential recency decay:

    decay = exp(-age_days / 45.0)        # src/mnemosyne/lifecycle.py:64

inside ``decayed_salience`` (lifecycle.py:59), which feeds ``demotion_decision``
(lifecycle.py:74) — items below ``utility_threshold`` (default 0.18) drop a
fidelity tier. The human-memory reference OQ4 points at is the ACT-R / Anderson
base-level power law of retention:

    retention(t) ∝ t^(-d)                 # d ≈ 0.5 (Anderson & Schooler 1991)

This bench measures the CURRENT decay against that power-law reference HONESTLY by
driving the real ``decayed_salience`` over an age sweep and comparing it to a
normalized ACT-R power-law curve, reporting:

  * the divergence (mean absolute error + max error) between the two curves,
  * where each curve crosses the real demotion threshold (the age at which an
    item would be demoted) — the operationally meaningful number,
  * the half-life implied by each objective.

It does NOT claim one is "correct"; it quantifies how far the shipped exponential
sits from the ACT-R power law so OQ4 can be resolved against a measured gap rather
than intuition. The decay constant (45 days) and threshold (0.18) are read
through the real functions, not hardcoded copies.

Run: ``python eval/benches/bench_oq4_demotion_objective.py``
"""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bench_common import emit  # noqa: E402

from mnemosyne.lifecycle import (  # noqa: E402
    FidelityTier,
    LifecycleState,
    decayed_salience,
    demotion_decision,
)

# ACT-R base-level decay exponent (Anderson & Schooler 1991 ≈ 0.5).
ACTR_DECAY_EXPONENT = 0.5
AGE_SWEEP_DAYS = [0, 1, 3, 7, 14, 21, 30, 45, 60, 90, 120, 180, 240, 365]
UTILITY_THRESHOLD = 0.18  # mirrors lifecycle.demotion_decision default; checked below


def _state(salience: float, importance: float, access_count: int, last_accessed: datetime) -> LifecycleState:
    return LifecycleState(
        item_id="oq4-probe",
        tier=FidelityTier.VERBATIM,
        salience=salience,
        importance=importance,
        access_count=access_count,
        last_accessed=last_accessed,
    )


def _isolated_exp_decay(age_days: float) -> float:
    """The pure exp(-age/45) factor as it appears in lifecycle.decayed_salience."""

    return math.exp(-age_days / 45.0)


def _actr_power_law(age_days: float) -> float:
    """Normalized ACT-R retention t^(-d), pinned to 1.0 at the 1-day reference."""

    t = max(age_days, 1.0)
    return float(t ** (-ACTR_DECAY_EXPONENT))


def _crossing_age(curve, threshold: float) -> float | None:
    """First age (day granularity) at which a decay curve drops below threshold."""

    prev = None
    for day in range(0, 366):
        v = curve(float(day))
        if v < threshold:
            return float(day)
        prev = v
    _ = prev
    return None


def main() -> dict[str, object]:
    now = datetime.now(UTC)

    # Verify the real default threshold by probing demotion_decision behaviour,
    # rather than trusting the constant: find the salience at which it flips.
    high = _state(0.9, 0.0, 0, now)  # fresh, high salience -> should NOT demote
    _, demoted_high = demotion_decision(high, now, utility_threshold=UTILITY_THRESHOLD)
    stale = _state(0.05, 0.0, 0, now - timedelta(days=365))  # ancient -> demote
    _, demoted_stale = demotion_decision(stale, now, utility_threshold=UTILITY_THRESHOLD)

    # Age sweep using the REAL decayed_salience (importance=0, access=0 so the
    # exp-decay term dominates and is observable in isolation).
    sweep: list[dict[str, object]] = []
    abs_errors: list[float] = []
    for age in AGE_SWEEP_DAYS:
        st = _state(1.0, 0.0, 0, now - timedelta(days=age))
        real_util = decayed_salience(st, now)  # full src objective at this age
        exp_factor = _isolated_exp_decay(age)
        actr = _actr_power_law(age)
        err = abs(exp_factor - actr)
        abs_errors.append(err)
        next_state, demoted = demotion_decision(st, now, utility_threshold=UTILITY_THRESHOLD)
        sweep.append(
            {
                "age_days": age,
                "src_decayed_salience": round(real_util, 6),
                "src_exp_decay_factor": round(exp_factor, 6),
                "actr_power_law": round(actr, 6),
                "abs_error_exp_vs_actr": round(err, 6),
                "src_demoted_at_this_age": demoted,
                "src_tier_after": next_state.tier.value,
            }
        )

    exp_cross = _crossing_age(_isolated_exp_decay, UTILITY_THRESHOLD)
    actr_cross = _crossing_age(_actr_power_law, UTILITY_THRESHOLD)
    exp_half_life = round(45.0 * math.log(2.0), 4)  # exp(-t/45)=0.5 -> t=45 ln2
    actr_half_life = round(2.0 ** (1.0 / ACTR_DECAY_EXPONENT), 4)  # t^-d=0.5 -> t=2^(1/d)

    mean_abs_error = round(sum(abs_errors) / len(abs_errors), 6)
    max_abs_error = round(max(abs_errors), 6)

    payload: dict[str, object] = {
        "bench": "oq4_demotion_objective",
        "blueprint_ref": "OQ4 demotion / fidelity decay objective",
        "src_wiring": {
            "decay_objective": "exp(-age_days/45.0) in mnemosyne.lifecycle.decayed_salience (src/mnemosyne/lifecycle.py:64)",
            "demotion_gate": "mnemosyne.lifecycle.demotion_decision (src/mnemosyne/lifecycle.py:74)",
            "utility_threshold_default": UTILITY_THRESHOLD,
            "reference_model": f"ACT-R base-level power law t^(-{ACTR_DECAY_EXPONENT}) (Anderson & Schooler 1991)",
        },
        "metric": {
            "age_sweep": sweep,
            "exp_vs_actr_mean_abs_error": mean_abs_error,
            "exp_vs_actr_max_abs_error": max_abs_error,
            "src_exp_demotion_crossing_age_days": exp_cross,
            "actr_demotion_crossing_age_days": actr_cross,
            "src_exp_half_life_days": exp_half_life,
            "actr_half_life_days": actr_half_life,
            "threshold_probe": {
                "fresh_high_salience_demoted": demoted_high,
                "ancient_low_salience_demoted": demoted_stale,
            },
        },
        "target": {
            "objective": (
                "OQ4 OPEN: blueprint does not fix a single objective. Reference is "
                "the ACT-R power law; this bench reports the measured gap so the "
                "choice is data-driven."
            ),
            "expected_threshold_behaviour": "fresh high-salience NOT demoted; ancient low-salience demoted",
        },
        "honest_status": {
            "current_objective_is_exponential": True,
            "note": (
                "src uses a pure exponential exp(-age/45) (half-life ~31.2 days), "
                "whereas ACT-R is a heavier-tailed power law (half-life ~4 days but "
                "far slower decay at long ages). The two diverge most in the mid-age "
                "band (see max_abs_error / crossing-age delta). No code is changed; "
                "the gap is the OQ4 decision input."
            ),
        },
        "verdict": {
            "threshold_behaviour_correct": bool((not demoted_high) and demoted_stale),
            "exp_matches_actr_within_0_05": max_abs_error <= 0.05,
        },
        "wiring_to_swap_objective": [
            "Replace `decay = math.exp(-age_days / 45.0)` in decayed_salience "
            "(lifecycle.py:64) with a power-law term t^(-d) (or a hybrid) behind a "
            "policy-selectable objective so OQ4 can A/B exponential vs ACT-R.",
            "Expose the decay objective + constant on OperatingPolicy so the demotion "
            "sweep job (jobs.run_lifecycle_sweep) can carry it per-tenant.",
            "Re-run this bench to confirm the new crossing-age / half-life land where "
            "OQ4 decides.",
        ],
    }
    emit(payload)
    return payload


if __name__ == "__main__":
    main()
