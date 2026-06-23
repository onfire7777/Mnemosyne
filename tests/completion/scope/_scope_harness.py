"""Dependency-free check framework shared by the FR-20/FR-21 scope checks.

Why hand-rolled instead of pytest: the ready eval venv (``.venv-eval``) carries
torch + sentence-transformers but NOT pytest, and the task requires a harness
that runs honestly under that venv. So the scope checks are plain callables
collected here; ``run_scope_conformance.py`` drives them with stdlib only, and
``test_scope_conformance.py`` re-exposes the same callables to pytest.

A "check" is a zero-arg callable that raises ``AssertionError`` (or any
exception) on failure and returns an optional human note string on success.
``Bar`` records which blueprint bar a check holds, so the report can show that
the *limited* v1 bar — not full P2 — is what is being measured.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Check:
    fr: str  # "FR-20" | "FR-21"
    name: str
    bar: str  # one-line statement of the *limited* v1 bar this holds
    fn: Callable[[], str | None]


@dataclass
class CheckResult:
    check: Check
    passed: bool
    note: str = ""
    error: str = ""


@dataclass
class SuiteReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def all_pass(self) -> bool:
        return self.total > 0 and self.passed == self.total

    def by_fr(self, fr: str) -> list[CheckResult]:
        return [r for r in self.results if r.check.fr == fr]


def run_checks(checks: list[Check]) -> SuiteReport:
    report = SuiteReport()
    for check in checks:
        try:
            note = check.fn() or ""
            report.results.append(CheckResult(check, True, note=note))
        except Exception as exc:  # noqa: BLE001 - honest capture of any failure
            tb = traceback.format_exc(limit=4).strip()
            report.results.append(
                CheckResult(check, False, error=f"{type(exc).__name__}: {exc}\n{tb}")
            )
    return report
