"""Promotion gate, protected regression cases, and branch rollback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

from mnemosyne.engine import LocalMemoryEngine

CaseTier = Literal["smoke", "core", "archive"]
CaseOrigin = Literal["curated", "genuine", "synthetic"]


@dataclass(slots=True)
class RegressionCase:
    id: str
    signature: str
    query: str
    expected_substring: str
    tier: CaseTier = "smoke"
    protected: bool = False
    origin: CaseOrigin = "curated"
    mode: Literal["shadow", "active"] = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegressionCase":
        return cls(**dict(data))


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
class CounterfactualVerdict:
    """Verdict from a counterfactual-replay hook (§30.6).

    Produced by the CC-LS counterfactual-replay scorer: replaying a historical
    session against the candidate predicts whether the change actually lifts task
    success. ``passed`` False vetoes promotion even when the point-check
    regression suite is green.
    """

    passed: bool
    predicted_lift: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# A counterfactual-replay hook receives the gate decision context and returns a
# verdict. Owned/implemented by CC-LS; the gate only provides the seam.
CounterfactualHook = Callable[[str, "Candidate", LocalMemoryEngine, list[str], list[str]], CounterfactualVerdict]


@dataclass(slots=True)
class GateResult:
    candidate_id: str
    promoted: bool
    protected_regressions: list[str]
    failed_cases: list[str]
    passed_cases: list[str]
    margin: float
    rollback_branch: str | None
    counterfactual: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


IGNITION_N_ACTIVE = 30
IGNITION_MIN_CURATED = 20
IGNITION_MIN_GENUINE = 5


@dataclass(slots=True)
class IgnitionStatus:
    """Suite-ignition readiness for the OQ5 shadow-to-active promotion flip."""

    mode: Literal["SHADOW", "ACTIVE"]
    ready: bool
    n_active: int
    n_active_target: int
    counts: dict[str, int]
    blocking_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromotionGate:
    def __init__(
        self,
        engine: LocalMemoryEngine,
        cases: list[RegressionCase],
        noise_margin: float = 0.01,
        counterfactual_hook: CounterfactualHook | None = None,
        require_ignition: bool = False,
    ):
        self.engine = engine
        self.cases = cases
        self.noise_margin = noise_margin
        # Optional §30.6 seam: when set, a counterfactual-replay verdict can veto an
        # otherwise-promotable candidate. Default ``None`` preserves prior behaviour.
        self.counterfactual_hook = counterfactual_hook
        self.require_ignition = require_ignition

    def relevant_cases(self, candidate: Candidate) -> list[RegressionCase]:
        signature_terms = set(candidate.signature.lower().split())
        relevant = []
        for case in self.cases:
            case_terms = set((case.signature + " " + case.query).lower().split())
            if signature_terms & case_terms or case.protected or case.tier == "smoke":
                relevant.append(case)
        return relevant

    def ignition_status(self) -> IgnitionStatus:
        """Return the private-suite readiness gate for OQ5 cold-loop promotion."""

        counts = {"curated": 0, "genuine": 0, "synthetic": 0}
        protected_present = False
        for case in self.cases:
            origin = getattr(case, "origin", "curated")
            if origin not in counts:
                origin = "curated"
            if getattr(case, "mode", "active") != "active":
                continue
            counts[origin] += 1
            if origin != "synthetic" and case.protected:
                protected_present = True
        n_active = counts["curated"] + counts["genuine"]
        blocking: list[str] = []
        if counts["curated"] < IGNITION_MIN_CURATED:
            blocking.append(f"curated {counts['curated']} < required {IGNITION_MIN_CURATED}")
        if counts["genuine"] < IGNITION_MIN_GENUINE:
            blocking.append(f"genuine {counts['genuine']} < required {IGNITION_MIN_GENUINE}")
        if n_active < IGNITION_N_ACTIVE:
            blocking.append(f"N_active {n_active} < target {IGNITION_N_ACTIVE}")
        if not protected_present:
            blocking.append("no protected active curated/genuine case present")
        ready = not blocking
        return IgnitionStatus(
            mode="ACTIVE" if ready else "SHADOW",
            ready=ready,
            n_active=n_active,
            n_active_target=IGNITION_N_ACTIVE,
            counts=counts,
            blocking_reasons=blocking,
        )

    def evaluate(
        self,
        tenant_id: str,
        candidate: Candidate,
        apply_candidate: Callable[[LocalMemoryEngine, str], None],
        pre_merge_check: Callable[[LocalMemoryEngine, str], str | None] | None = None,
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
        counterfactual: dict[str, Any] | None = None
        if self.counterfactual_hook is not None:
            verdict = self.counterfactual_hook(tenant_id, candidate, self.engine, passed, failed)
            counterfactual = verdict.to_dict()
            # Replay-fidelity term consumed by the cold-loop counterfactual rail.
            counterfactual["replay_predicted_lift"] = verdict.predicted_lift
            # Counterfactual replay can veto an otherwise-promotable candidate, but
            # never rescues one the regression suite already failed.
            if promoted and not verdict.passed:
                promoted = False
        if promoted and pre_merge_check is not None:
            rail_violation = pre_merge_check(self.engine, branch)
            if rail_violation:
                failed.append(rail_violation)
                protected_regressions.append(rail_violation)
                promoted = False
        if promoted and self.require_ignition:
            ignition = self.ignition_status()
            if not ignition.ready:
                failed.append("ignition_not_ready: " + "; ".join(ignition.blocking_reasons))
                promoted = False
        rollback_branch = None
        if promoted:
            self._merge(branch, tenant_id)
        else:
            rollback_branch = branch
            self._discard(branch, tenant_id)
        return GateResult(candidate.id, promoted, protected_regressions, failed, passed, margin, rollback_branch, counterfactual)

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
