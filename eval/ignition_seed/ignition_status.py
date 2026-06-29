"""OQ5 ignition-status reporter (blueprint FR-14 / FR-17, §17 P1 decision).

Answers the single keystone question the OQ5 decision turns into a switch:

    *Is the private regression suite big enough (N_active >= 30 curated+genuine)
    to flip the promotion gate from SHADOW (log-only, never merge) to ACTIVE
    (verdicts bind, a regression blocks promotion)?*

This module computes that readiness from the seed set produced by ``loader.py``.
It mirrors the production ``PromotionGate.ignition_status`` counting rules in
``src/mnemosyne/gate.py`` so the seed report remains a readable oracle for that
runtime wiring.

Counting rules (OQ5 decision, verbatim intent):
  * ``N_active`` counts ONLY ``curated`` + ``genuine`` cases.
  * ``synthetic`` NEVER counts toward ignition, and the synthetic contribution is
    capped at ``2 x curated`` (a guard so an auto-generator cannot dilute the suite).
  * The flip fires at ``N_active >= 30`` with the documented slice floors:
    ``>= 20`` curated, ``>= 5`` genuine, and at least one protected case present.
  * Below the floor the gate is ``SHADOW``; at/above it is ``ACTIVE``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .loader import N_ACTIVE, LoadedCase, load_seed_cases

# Slice floors from the OQ5 decision memo (SECTION-17-OPEN-QUESTIONS.md, OQ5).
MIN_CURATED = 20
MIN_GENUINE = 5
SYNTHETIC_CAP_MULTIPLE = 2  # synthetic accepted <= 2x curated (never counted)


@dataclass(slots=True)
class IgnitionStatus:
    """Machine-readable readiness verdict for the OQ5 shadow->active flip."""

    mode: str  # "SHADOW" | "ACTIVE"
    ready: bool
    n_active: int  # curated + genuine
    n_active_target: int
    counts: dict[str, int]  # per-origin raw counts
    protected_active: int
    protected_synthetic: int
    tiers_present: list[str]
    synthetic_cap: int
    synthetic_within_cap: bool
    slice_floors_met: dict[str, bool]
    blocking_reasons: list[str]
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_ignition_status(
    cases: list[LoadedCase] | None = None,
    *,
    n_active_target: int = N_ACTIVE,
    cases_path: str | Path | None = None,
) -> IgnitionStatus:
    """Compute SHADOW/ACTIVE readiness from the seed set.

    This is the function ``PromotionGate.ignition_status`` should delegate to (or
    replicate) once ``origin`` lives on ``RegressionCase`` in ``src``.
    """
    if cases is None:
        cases = load_seed_cases(cases_path)

    counts = {"curated": 0, "genuine": 0, "synthetic": 0}
    protected_active = 0
    protected_synthetic = 0
    tiers: set[str] = set()
    for lc in cases:
        counts[lc.origin] += 1
        tiers.add(lc.case.tier)
        if lc.case.protected:
            if lc.counts_toward_active:
                protected_active += 1
            else:
                protected_synthetic += 1

    n_active = counts["curated"] + counts["genuine"]
    synthetic_cap = SYNTHETIC_CAP_MULTIPLE * counts["curated"]
    synthetic_within_cap = counts["synthetic"] <= synthetic_cap

    slice_floors_met = {
        "curated": counts["curated"] >= MIN_CURATED,
        "genuine": counts["genuine"] >= MIN_GENUINE,
        "n_active": n_active >= n_active_target,
        "protected_present": (protected_active + protected_synthetic) > 0,
    }

    blocking: list[str] = []
    if counts["curated"] < MIN_CURATED:
        blocking.append(f"curated {counts['curated']} < required {MIN_CURATED}")
    if counts["genuine"] < MIN_GENUINE:
        blocking.append(f"genuine {counts['genuine']} < required {MIN_GENUINE}")
    if n_active < n_active_target:
        blocking.append(f"N_active {n_active} < target {n_active_target}")
    if (protected_active + protected_synthetic) == 0:
        blocking.append("no protected case present")

    ready = not blocking
    mode = "ACTIVE" if ready else "SHADOW"

    return IgnitionStatus(
        mode=mode,
        ready=ready,
        n_active=n_active,
        n_active_target=n_active_target,
        counts=counts,
        protected_active=protected_active,
        protected_synthetic=protected_synthetic,
        tiers_present=sorted(tiers),
        synthetic_cap=synthetic_cap,
        synthetic_within_cap=synthetic_within_cap,
        slice_floors_met=slice_floors_met,
        blocking_reasons=blocking,
    )


def render_markdown(status: IgnitionStatus) -> str:
    """Human-readable readiness scorecard."""
    c = status.counts
    lines: list[str] = []
    lines.append("# OQ5 Suite-Ignition Readiness")
    lines.append("")
    lines.append(f"- **Generated:** {status.generated_at}")
    lines.append(f"- **Mode:** **{status.mode}** "
                 f"({'verdicts BIND — regressions block promotion' if status.mode == 'ACTIVE' else 'log-only — never merges'})")
    lines.append(f"- **N_active:** {status.n_active} / {status.n_active_target} "
                 f"(curated + genuine; synthetic excluded)")
    lines.append("")
    lines.append("| Origin | Count | Counts toward N_active? |")
    lines.append("|---|---|---|")
    lines.append(f"| curated | {c['curated']} | yes |")
    lines.append(f"| genuine | {c['genuine']} | yes |")
    lines.append(f"| synthetic | {c['synthetic']} | **no** (cap {status.synthetic_cap}, "
                 f"{'within cap' if status.synthetic_within_cap else 'OVER CAP'}) |")
    lines.append("")
    lines.append("## Slice floors (OQ5)")
    lines.append("")
    lines.append("| Floor | Met |")
    lines.append("|---|---|")
    floors = status.slice_floors_met
    lines.append(f"| curated >= {MIN_CURATED} | {'PASS' if floors['curated'] else 'FAIL'} |")
    lines.append(f"| genuine >= {MIN_GENUINE} | {'PASS' if floors['genuine'] else 'FAIL'} |")
    lines.append(f"| N_active >= {status.n_active_target} | {'PASS' if floors['n_active'] else 'FAIL'} |")
    lines.append(f"| protected tier present | {'PASS' if floors['protected_present'] else 'FAIL'} |")
    lines.append("")
    lines.append(f"- **Protected cases:** {status.protected_active} active + "
                 f"{status.protected_synthetic} synthetic")
    lines.append(f"- **Tiers present:** {', '.join(status.tiers_present)}")
    if status.blocking_reasons:
        lines.append("")
        lines.append("## Blocking (still SHADOW)")
        lines.append("")
        for r in status.blocking_reasons:
            lines.append(f"- {r}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: print the readiness report. ``--json`` for machine output."""
    import argparse

    parser = argparse.ArgumentParser(description="OQ5 suite-ignition readiness reporter")
    parser.add_argument("--cases", default=None, help="path to cases.json (default: bundled seed)")
    parser.add_argument("--n-active", type=int, default=N_ACTIVE, help="ignition threshold (default 30)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    args = parser.parse_args(argv)

    status = compute_ignition_status(n_active_target=args.n_active, cases_path=args.cases)
    if args.json:
        print(json.dumps(status.as_dict(), indent=2))
    else:
        print(render_markdown(status))
    # Exit non-zero in SHADOW so CI can gate on readiness if desired.
    return 0 if status.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
