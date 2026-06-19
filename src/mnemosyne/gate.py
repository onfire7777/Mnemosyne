"""Promotion gate, protected regression cases, and branch rollback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from mnemosyne.engine import LocalMemoryEngine

CaseTier = Literal["smoke", "core", "archive"]


@dataclass(slots=True)
class RegressionCase:
    id: str
    signature: str
    query: str
    expected_substring: str
    tier: CaseTier = "smoke"
    protected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Candidate:
    id: str
    kind: Literal["lesson", "procedure", "policy", "preference", "fact"]
    signature: str
    description: str
    branch: str
    source_evidence_cids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GateResult:
    candidate_id: str
    promoted: bool
    protected_regressions: list[str]
    failed_cases: list[str]
    passed_cases: list[str]
    margin: float
    rollback_branch: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromotionGate:
    def __init__(self, engine: LocalMemoryEngine, cases: list[RegressionCase], noise_margin: float = 0.01):
        self.engine = engine
        self.cases = cases
        self.noise_margin = noise_margin

    def relevant_cases(self, candidate: Candidate) -> list[RegressionCase]:
        signature_terms = set(candidate.signature.lower().split())
        relevant = []
        for case in self.cases:
            case_terms = set((case.signature + " " + case.query).lower().split())
            if signature_terms & case_terms or case.protected or case.tier == "smoke":
                relevant.append(case)
        return relevant

    def evaluate(
        self,
        tenant_id: str,
        candidate: Candidate,
        apply_candidate: Callable[[LocalMemoryEngine, str], None],
    ) -> GateResult:
        branch = candidate.branch
        self._reset_branch(branch, tenant_id)
        self._branch(branch, tenant_id)
        apply_candidate(self.engine, branch)
        passed: list[str] = []
        failed: list[str] = []
        protected_regressions: list[str] = []
        for case in self.relevant_cases(candidate):
            result = self.engine.retrieve(case.query, tenant_id=tenant_id, branch=branch, deep=case.tier != "smoke")
            rendered = "\n".join(hit.text for hit in result.hits)
            ok = case.expected_substring.lower() in rendered.lower() and not result.abstained
            if ok:
                passed.append(case.id)
            else:
                failed.append(case.id)
                if case.protected:
                    protected_regressions.append(case.id)
        total = max(len(passed) + len(failed), 1)
        margin = len(passed) / total - self.noise_margin
        promoted = not protected_regressions and not failed and margin > 0
        rollback_branch = None
        if promoted:
            self._merge(branch, tenant_id)
        else:
            rollback_branch = branch
            self._discard(branch, tenant_id)
        return GateResult(candidate.id, promoted, protected_regressions, failed, passed, margin, rollback_branch)

    def _reset_branch(self, branch: str, tenant_id: str) -> None:
        branches = getattr(self.engine, "branches", None)
        if isinstance(branches, dict):
            if branch in branches:
                self._discard(branch, tenant_id)
            return
        self._discard(branch, tenant_id)

    def _branch(self, branch: str, tenant_id: str) -> None:
        try:
            self.engine.branch(branch, frm="main", kind="canary", tenant_id=tenant_id)
        except TypeError:
            self.engine.branch(branch, frm="main", kind="canary")

    def _merge(self, branch: str, tenant_id: str) -> None:
        try:
            self.engine.merge(branch, into="main", tenant_id=tenant_id)
        except TypeError:
            self.engine.merge(branch, into="main")

    def _discard(self, branch: str, tenant_id: str) -> None:
        try:
            self.engine.discard(branch, tenant_id=tenant_id)
        except TypeError:
            self.engine.discard(branch)
