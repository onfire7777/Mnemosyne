"""Suite ignition: the shadow-until-N promotion gate (blueprint §33 / §17 P1).

The blueprint's cold-start fix: ship a seed suite (curated + synthetic) and keep
candidates in **shadow mode** — logged vs. real outcomes but NOT promoted — until
the private suite reaches ignition size **N**. "Active" promotion switches on at N.

N is a blueprint-tagged open question (§17 P1). We make it an explicit, tunable
parameter with a documented default and persist suite growth across runs so the
gate is auditable. The gate state lives in ``eval/reports/suite_state.json``.

Mode semantics:
  * ``SHADOW``  — suite_size < N. Candidates are evaluated and logged, never
    promoted. SLO verdicts are recorded as advisory only.
  * ``ACTIVE``  — suite_size >= N. Verdicts are binding; a regression blocks
    promotion (this is where the harness becomes the promotion gate).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Default ignition size. The blueprint leaves N open (§17 P1); we choose a small
# but non-trivial default so the seed + synthetic suite can realistically ignite,
# and document the trade-off: too low → noisy promotions; too high → suite never
# ignites. Override with --ignition-n.
DEFAULT_IGNITION_N = 40


@dataclass(slots=True)
class IgnitionState:
    ignition_n: int
    suite_size: int
    mode: str  # "SHADOW" | "ACTIVE"
    updated_at: str
    history: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_suite_size(
    *,
    curated_cases: int,
    synthetic_cases: int,
    belief_cases: int,
    poison_cases: int,
    mandatory_classes: int,
) -> int:
    """Total protected-case count contributing to ignition.

    Every confirmed case across every tier counts toward N: curated retrieval
    queries, synthetic retrieval queries, belief-revision cases, poison/attack
    cases, and the mandatory test classes.
    """
    return curated_cases + synthetic_cases + belief_cases + poison_cases + mandatory_classes


def evaluate_ignition(
    suite_size: int,
    ignition_n: int,
    *,
    state_path: Path | None = None,
    note: str = "",
) -> IgnitionState:
    mode = "ACTIVE" if suite_size >= ignition_n else "SHADOW"
    now = datetime.now(timezone.utc).isoformat()
    history: list[dict[str, Any]] = []
    if state_path and state_path.exists():
        try:
            prior = json.loads(state_path.read_text())
            history = list(prior.get("history", []))
        except (json.JSONDecodeError, OSError):
            history = []
    history.append({"at": now, "suite_size": suite_size, "ignition_n": ignition_n, "mode": mode, "note": note})
    state = IgnitionState(
        ignition_n=ignition_n,
        suite_size=suite_size,
        mode=mode,
        updated_at=now,
        history=history[-50:],  # keep last 50 transitions
    )
    if state_path:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state.as_dict(), indent=2))
    return state
