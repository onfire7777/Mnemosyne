"""Truth-maintenance and AGM-style belief revision."""

from __future__ import annotations

from collections import defaultdict, deque

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, BeliefRevisionReport, Contradiction, Justification


class BeliefRevisionCore:
    def __init__(self, engine: LocalMemoryEngine):
        self.engine = engine

    def classify(self, assertion: Assertion, branch: str = "main") -> str:
        peers = [
            item
            for item in self.engine.assertions.values()
            if item.tenant_id == assertion.tenant_id
            and item.branch == branch
            and item.subject == assertion.subject
            and item.predicate == assertion.predicate
            and item.scope == assertion.scope
            and item.status in {"active", "contested"}
        ]
        if not peers:
            return "ADD"
        same = [item for item in peers if item.object == assertion.object]
        if same:
            best = max(same, key=lambda item: item.confidence)
            if assertion.confidence > best.confidence or set(assertion.source_evidence_cids) - set(best.source_evidence_cids):
                return "UPDATE"
            return "NOOP"
        newest = max(peers, key=lambda item: item.valid_from)
        if assertion.valid_from > newest.valid_from:
            return "SUPERSEDE"
        return "CONTEST"

    def revise(self, assertion: Assertion, branch: str = "main", rule: str | None = None) -> BeliefRevisionReport:
        operation = self.classify(assertion, branch)
        before = {
            item.id: item
            for item in self.engine.assertions.values()
            if item.tenant_id == assertion.tenant_id
            and item.branch == branch
            and item.subject == assertion.subject
            and item.predicate == assertion.predicate
            and item.scope == assertion.scope
            and item.status in {"active", "contested"}
        }
        assertion_id = self.engine.upsert_assertion(assertion, branch=branch)
        after = self.engine.assertions[self.engine._branch_key(assertion.tenant_id, branch, assertion_id)]
        justification = Justification(
            tenant_id=assertion.tenant_id,
            assertion_id=assertion_id,
            evidence_cids=list(after.source_evidence_cids),
            rule=rule or operation,
            dependency_ids=[],
            kind="support",
            hypothesis_prob=after.calibration.get("hypothesis_prob"),
        )
        justification_id = self.engine.add_justification(justification)
        after.justification_id = justification_id
        contradictions: list[str] = []
        if operation in {"SUPERSEDE", "CONTEST"}:
            for peer in before.values():
                if peer.object != assertion.object:
                    contradictions.append(self.engine.add_contradiction(Contradiction(assertion.tenant_id, peer.id, assertion_id)))
        affected = sorted(
            item.id
            for item in self.engine.assertions.values()
            if item.tenant_id == assertion.tenant_id
            and item.branch == branch
            and item.subject == assertion.subject
            and item.predicate == assertion.predicate
        )
        self.engine._persist()
        return BeliefRevisionReport(operation, assertion_id, justification_id, affected, contradictions)

    def add_derived_belief(
        self,
        assertion: Assertion,
        dependency_ids: list[str],
        branch: str = "main",
        rule: str = "derived",
    ) -> BeliefRevisionReport:
        report = self.revise(assertion, branch=branch, rule=rule)
        if report.justification_id:
            justification = self.engine.justifications[report.justification_id]
            justification.dependency_ids = list(dependency_ids)
            self.engine._persist()
        return report

    def cascade_invalidate(self, tenant_id: str, assertion_id: str, reason: str = "dependency invalidated") -> list[str]:
        dependencies: dict[str, list[str]] = defaultdict(list)
        for justification in self.engine.justifications.values():
            if justification.tenant_id != tenant_id:
                continue
            for dependency in justification.dependency_ids:
                dependencies[dependency].append(justification.assertion_id)
        invalidated: list[str] = []
        queue: deque[str] = deque([assertion_id])
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            for key, assertion in self.engine.assertions.items():
                if assertion.tenant_id == tenant_id and assertion.id == current and assertion.status != "retracted":
                    assertion.status = "retracted"
                    assertion.calibration["invalidated_reason"] = reason
                    invalidated.append(current)
                    self.engine.assertions[key] = assertion
            for dependent in dependencies.get(current, []):
                queue.append(dependent)
        if invalidated:
            self.engine._audit(tenant_id, "belief-core", "cascade_invalidate", assertion_id, {"invalidated": invalidated, "reason": reason})
            self.engine._persist()
        return invalidated

    def contested_hypotheses(self, tenant_id: str, subject: str, predicate: str, branch: str = "main") -> list[dict[str, object]]:
        alternatives = [
            item
            for item in self.engine.assertions.values()
            if item.tenant_id == tenant_id
            and item.branch == branch
            and item.subject == subject
            and item.predicate == predicate
            and item.status in {"active", "contested"}
        ]
        total = sum(max(item.confidence, 0.01) for item in alternatives)
        if total <= 0:
            return []
        return [
            {
                "assertion_id": item.id,
                "object": item.object,
                "status": item.status,
                "probability": max(item.confidence, 0.01) / total,
                "source_evidence_cids": list(item.source_evidence_cids),
            }
            for item in sorted(alternatives, key=lambda row: row.confidence, reverse=True)
        ]

