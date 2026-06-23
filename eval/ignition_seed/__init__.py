"""OQ5 suite-ignition curated seed set (blueprint §33 / §17 P1; FR-14, FR-17).

The completion-additive half of OQ5: a curated, trusted, held-out regression
corpus plus a genuine-style set and the permanent protected/attack tier, each
case tagged with an ``origin`` (``curated`` | ``genuine`` | ``synthetic``).

This is the exact data ``PromotionGate.ignition_status`` (to be wired by Codex in
``src/mnemosyne/gate.py``) consumes to decide whether the promotion gate runs in
SHADOW (log-only) or ACTIVE (binding) mode. ``N_active`` counts curated+genuine
only; synthetic never counts and is capped at 2x curated.

Public API:
  * ``load_seed_cases`` / ``regression_cases`` / ``active_cases`` (loader)
  * ``compute_ignition_status`` / ``IgnitionStatus`` (reporter)
  * ``N_ACTIVE`` (the threshold, = 30)
"""

from __future__ import annotations

from .ignition_status import (
    IgnitionStatus,
    compute_ignition_status,
    render_markdown,
)
from .loader import (
    DEFAULT_CASES_PATH,
    N_ACTIVE,
    LoadedCase,
    active_cases,
    load_seed_cases,
    regression_cases,
)

__all__ = [
    "DEFAULT_CASES_PATH",
    "IgnitionStatus",
    "LoadedCase",
    "N_ACTIVE",
    "active_cases",
    "compute_ignition_status",
    "load_seed_cases",
    "regression_cases",
    "render_markdown",
]
