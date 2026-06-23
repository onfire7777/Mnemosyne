"""Pytest shim exposing the FR-20/FR-21 scope-conformance checks.

The real assertions live in ``fr20_multimodal.py`` / ``fr21_parametric.py`` as
dependency-free callables so they also run under ``.venv-eval`` (which has torch
+ sentence-transformers but no pytest) via ``run_scope_conformance.py``. This
module simply re-exposes each check to pytest so it participates in the normal
``tests/`` collection (run under ``.venv`` with ``pythonpath = ["src"]``).

Each check holds FR-20 (blueprint non-goal N5) and FR-21 (non-goal N2) to their
INTENTIONALLY-LIMITED v1 bar. A failure here means the substrate REGRESSED below
that limited bar — not that full P2 multimodal/LoRA is missing (that is correctly
deferred; see each module's ``REAL_DEPLOYMENT_VALIDATION``).
"""

from __future__ import annotations

import pytest

from . import fr20_multimodal, fr21_parametric
from ._scope_harness import Check

_ALL_CHECKS: list[Check] = list(fr20_multimodal.CHECKS) + list(fr21_parametric.CHECKS)


@pytest.mark.parametrize("check", _ALL_CHECKS, ids=lambda c: f"{c.fr}:{c.name}")
def test_scope_v1_bar(check: Check) -> None:
    """Each check raises on failure; a returned note is the human evidence string."""
    note = check.fn()
    # A passing check may return a human note; surface it for -v / -rA readers.
    if note:
        print(f"[{check.fr}:{check.name}] {note}")


def test_every_fr_has_a_deferred_validation_surface() -> None:
    """Both FRs must DOCUMENT what real-deployment validation is deferred (forcing fn)."""
    assert fr20_multimodal.REAL_DEPLOYMENT_VALIDATION, "FR-20 must document deferred validation"
    assert fr21_parametric.REAL_DEPLOYMENT_VALIDATION, "FR-21 must document deferred validation"
    # Sanity: each item is a non-trivial sentence, not a placeholder.
    for item in fr20_multimodal.REAL_DEPLOYMENT_VALIDATION + fr21_parametric.REAL_DEPLOYMENT_VALIDATION:
        assert isinstance(item, str) and len(item) > 40
