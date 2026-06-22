"""Loader for the OQ5 suite-ignition curated seed set (blueprint §33 / §17 P1).

Turns ``cases.json`` into ``RegressionCase``-shaped objects (``mnemosyne.gate``)
while preserving the per-case ``origin`` tag (``curated`` | ``genuine`` |
``synthetic``) that the OQ5 ignition counter depends on.

Forward-compatibility note (FR-14 reconciliation):
    The *current* ``RegressionCase`` dataclass has fields
    ``id, signature, query, expected_substring, tier, protected`` only -- it does
    NOT yet accept ``origin``/``mode`` (verified: ``from_dict`` raises TypeError on
    an extra ``origin`` key). The OQ5 decision requires Codex to add ``origin`` and
    ``mode`` to ``RegressionCase`` in ``src/mnemosyne/gate.py``.

    To remain loadable against BOTH the current and the future shape, this loader
    introspects the dataclass fields at runtime and only passes ``origin``/``mode``
    into the constructor when the dataclass actually declares them. Either way the
    ``origin`` is always returned alongside (see :class:`LoadedCase`) so the
    ignition reporter can count curated/genuine/synthetic without depending on the
    src change having landed.

SECURITY: every string in ``cases.json`` is inert data. Adversarial / poison
strings (e.g. "ignore all previous instructions ...") are intentional regression
*fixtures*, not directives -- they are loaded verbatim and never executed.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from mnemosyne.gate import RegressionCase

Origin = Literal["curated", "genuine", "synthetic"]
VALID_ORIGINS: frozenset[str] = frozenset({"curated", "genuine", "synthetic"})

# The OQ5 active-suite ignition threshold (§17 P1 decision): flip shadow->active
# at 30 curated+genuine cases. Synthetic NEVER counts and is capped at 2x curated.
N_ACTIVE: int = 30

DEFAULT_CASES_PATH = Path(__file__).resolve().parent / "cases.json"

# Fields the *installed* RegressionCase dataclass actually declares. Used to decide
# whether origin/mode can be passed into the constructor (future shape) or must be
# stripped first (current shape).
_RC_FIELDS: frozenset[str] = frozenset(f.name for f in dataclasses.fields(RegressionCase))


@dataclass(slots=True, frozen=True)
class LoadedCase:
    """A RegressionCase plus the OQ5 ``origin`` tag, kept together.

    ``case`` is always a real ``mnemosyne.gate.RegressionCase`` (the exact object
    ``PromotionGate`` consumes). ``origin`` is carried separately so the count is
    available even when the running ``RegressionCase`` does not yet store it.
    """

    case: RegressionCase
    origin: Origin

    @property
    def id(self) -> str:
        return self.case.id

    @property
    def counts_toward_active(self) -> bool:
        """Curated + genuine count toward N_active; synthetic never does."""
        return self.origin in ("curated", "genuine")


def _build_case(raw: dict[str, Any]) -> RegressionCase:
    """Construct a RegressionCase from a raw dict, tolerating origin/mode.

    Drops any key the installed dataclass does not declare (forward-compatible:
    once Codex adds origin/mode, those keys flow straight through).
    """
    payload = {k: v for k, v in raw.items() if k in _RC_FIELDS}
    return RegressionCase(**payload)


def load_seed_cases(path: str | Path | None = None) -> list[LoadedCase]:
    """Load and validate the OQ5 ignition seed set.

    Returns a list of :class:`LoadedCase`. Raises ``ValueError`` on a malformed
    dataset (missing/invalid origin, duplicate id) so a corrupt seed cannot
    silently understate the active count and force a spurious SHADOW verdict.
    """
    src = Path(path) if path is not None else DEFAULT_CASES_PATH
    data = json.loads(src.read_text())
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"{src}: 'cases' must be a non-empty list")

    seen: set[str] = set()
    loaded: list[LoadedCase] = []
    for i, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"{src}: case #{i} is not an object")
        origin = raw.get("origin")
        if origin not in VALID_ORIGINS:
            raise ValueError(
                f"{src}: case #{i} (id={raw.get('id')!r}) has invalid origin "
                f"{origin!r}; expected one of {sorted(VALID_ORIGINS)}"
            )
        case = _build_case(raw)
        if case.id in seen:
            raise ValueError(f"{src}: duplicate case id {case.id!r}")
        seen.add(case.id)
        loaded.append(LoadedCase(case=case, origin=origin))  # type: ignore[arg-type]
    return loaded


def regression_cases(path: str | Path | None = None) -> list[RegressionCase]:
    """Convenience: just the RegressionCase objects (what PromotionGate takes).

    Includes every origin -- the gate evaluates all cases; the SHADOW/ACTIVE
    *gating decision* is what excludes synthetic (see ignition_status).
    """
    return [lc.case for lc in load_seed_cases(path)]


def active_cases(path: str | Path | None = None) -> list[RegressionCase]:
    """RegressionCase objects that count toward N_active (curated + genuine)."""
    return [lc.case for lc in load_seed_cases(path) if lc.counts_toward_active]
