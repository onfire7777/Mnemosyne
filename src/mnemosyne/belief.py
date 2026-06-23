"""Truth-maintenance and AGM-style belief revision."""

from __future__ import annotations

import copy
import json
from collections import defaultdict, deque
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Assertion, BeliefRevisionReport, Contradiction, Justification, parse_dt, utc_now

# AGM theory-change operation for each belief-core classification.
# ADD/UPDATE add a belief consistent with the current set (expansion);
# SUPERSEDE replaces a contradicted belief under minimal change (revision);
# CONTEST retains a competing hypothesis without forcing a single conclusion;
# NOOP leaves the belief set unchanged.
AGM_OPERATIONS: dict[str, str] = {
    "ADD": "expansion",
    "UPDATE": "expansion",
    "NOOP": "none",
    "SUPERSEDE": "revision",
    "CONTEST": "expansion",
}


def agm_operation(classification: str) -> str:
    """Map a belief-core classification (ADD/UPDATE/...) to its AGM operation."""
    return AGM_OPERATIONS.get(classification, "expansion")


class BeliefRevisionCore:
    """Truth-maintenance + AGM-style belief revision over the engine's store.

    Maintains "current truth" under contradiction: new assertions are
    classified and applied with minimal change (ADD/UPDATE/NOOP/SUPERSEDE/
    CONTEST), justifications and contradictions are recorded, dependent beliefs
    cascade-invalidate when their support is retracted, and contested facts are
    retained as competing hypotheses with normalised probabilities (FR-10).
    """

    def __init__(self, engine: LocalMemoryEngine):
        self.engine = engine

    def classify(self, assertion: Assertion, branch: str = "main") -> str:
        """Classify an incoming assertion against current peers on ``branch``.

        Returns one of ``ADD`` (no peer), ``UPDATE`` (same object, stronger
        confidence or new evidence), ``NOOP`` (same object, nothing new),
        ``SUPERSEDE`` (different object, strictly newer valid time), or
        ``CONTEST`` (different object, not newer) — the AGM minimal-change rule.
        """
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
        # Trust-based supersession: a strictly more-trusted assertion (lower tier
        # number; tier 0 = direct user) supersedes a less-trusted conflicting
        # peer regardless of valid time — the belief-core analogue of the
        # engine's trust supersession, so a tier-0 user correction wins the same
        # turn instead of being recorded as merely contested.
        most_trusted_peer = min(peers, key=lambda item: item.trust_tier)
        if assertion.trust_tier < most_trusted_peer.trust_tier:
            return "SUPERSEDE"
        newest = max(peers, key=lambda item: item.valid_from)
        if assertion.valid_from > newest.valid_from:
            return "SUPERSEDE"
        return "CONTEST"

    def revise(self, assertion: Assertion, branch: str = "main", rule: str | None = None) -> BeliefRevisionReport:
        """Apply an assertion through the belief core and record its provenance.

        Upserts the assertion, attaches a supporting :class:`Justification`, and
        opens contradictions against differing peers on SUPERSEDE/CONTEST.
        Returns a :class:`BeliefRevisionReport` with the operation, new
        assertion/justification ids, the affected assertion ids, and any opened
        contradiction ids.
        """
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

    def apply_tier0_correction(self, assertion: Assertion, branch: str = "main") -> BeliefRevisionReport:
        """Apply a tier-0 (direct-user) correction as an immediate supersession.

        The belief-core entry point for the human-correction hot path
        (§20.7/§30.2): the ingestion layer detects a tier-0 user correction and
        calls this to apply it synchronously through the belief core — bypassing
        the asynchronous consolidation candidate gate — while still recording a
        justification for provenance. The correction is forced to trust tier 0
        (highest trust) and ``active``, so it supersedes any conflicting
        lower-trust memory in the same turn regardless of valid time. Returns the
        :class:`BeliefRevisionReport` (operation ``SUPERSEDE`` when it overrides a
        conflicting peer).

        This is the CC-BC side of the tier-0 correction seam shared with the
        ingestion lane, which owns detecting ``is_tier0_user_correction``; this
        method owns the belief-state effect and never mutates the caller's input.
        """
        correction = copy.deepcopy(assertion)
        correction.trust_tier = 0
        correction.status = "active"
        return self.revise(correction, branch=branch, rule="tier0_user_correction")

    def add_derived_belief(
        self,
        assertion: Assertion,
        dependency_ids: list[str],
        branch: str = "main",
        rule: str = "derived",
    ) -> BeliefRevisionReport:
        """Revise a derived belief and link it to the beliefs it depends on.

        Behaves like :meth:`revise` but records ``dependency_ids`` on the new
        justification so that :meth:`cascade_invalidate` can retract this belief
        when any of its supports is retracted.
        """
        report = self.revise(assertion, branch=branch, rule=rule)
        if report.justification_id:
            justification = self.engine.justifications[report.justification_id]
            justification.dependency_ids = list(dependency_ids)
            self.engine._persist()
        return report

    def cascade_invalidate(self, tenant_id: str, assertion_id: str, reason: str = "dependency invalidated") -> list[str]:
        """Retract an assertion and every belief transitively derived from it.

        Walks the justification dependency graph breadth-first from
        ``assertion_id``, marking each reachable assertion ``retracted`` with the
        given ``reason``, then audits and persists. Returns the list of
        invalidated assertion ids (including the root).
        """
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
        """Return competing hypotheses for a subject/predicate with probabilities.

        Keeps multiple live hypotheses instead of forcing a single answer:
        returns the active/contested alternatives ordered by confidence
        (descending), each annotated with a confidence-normalised probability so
        the set sums to 1.0 (the multi-hypothesis side of I8).
        """
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

    def atms_label(self, tenant_id: str, assertion_id: str, branch: str = "main") -> str:
        """Return the ATMS belief label for an assertion: ``"in"`` or ``"out"``.

        An assumption-based truth-maintenance label: an assertion is ``"in"``
        (currently believed) when it is active/contested and either has no
        derivation (a directly asserted premise) or has at least one
        justification whose dependencies are not themselves retracted. It is
        ``"out"`` when retracted/superseded, missing, or every justification is
        undermined by a retracted dependency.
        """
        target: Assertion | None = None
        for item in self.engine.assertions.values():
            if item.tenant_id == tenant_id and item.id == assertion_id and item.branch == branch:
                target = item
                break
        if target is None or target.status not in {"active", "contested"}:
            return "out"
        status_by_id = {
            item.id: item.status
            for item in self.engine.assertions.values()
            if item.tenant_id == tenant_id
        }
        justifications = [
            justification
            for justification in self.engine.justifications.values()
            if justification.tenant_id == tenant_id and justification.assertion_id == assertion_id
        ]
        if not justifications:
            return "in"
        for justification in justifications:
            if all(status_by_id.get(dep) != "retracted" for dep in justification.dependency_ids):
                return "in"
        return "out"


def assertion_from_case(row: Mapping[str, Any], *, tenant_id: str, user_id: str | None, branch: str) -> Assertion:
    valid_from = parse_dt(row.get("valid_from")) or utc_now()
    return Assertion(
        tenant_id=str(row.get("tenant_id") or tenant_id),
        user_id=row.get("user_id") or user_id,
        subject=str(row["subject"]),
        predicate=str(row["predicate"]),
        object=str(row["object"]),
        branch=str(row.get("branch") or branch),
        scope=dict(row.get("scope") or {}),
        confidence=float(row.get("confidence", 0.7)),
        valid_from=valid_from,
        status=str(row.get("status", "active")),
        source_evidence_cids=[str(item) for item in row.get("source_evidence_cids", [])],
        trust_tier=int(row.get("trust_tier", 0)),
        sensitivity=int(row.get("sensitivity", 0)),
        access_policy=dict(row.get("access_policy") or {"tenant": tenant_id}),
    )


def belief_revision_fingerprint(cases: list[Mapping[str, Any]]) -> str:
    encoded = json.dumps(cases, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def validate_belief_revision_cases(
    cases: list[Mapping[str, Any]],
    *,
    min_cases: int = 1,
    required_case_ids: list[str] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    required_ids = list(required_case_ids or [])
    seen_case_ids: set[str] = set()
    if len(cases) < min_cases:
        findings.append(
            {
                "code": "insufficient_cases",
                "message": f"case count {len(cases)} is below required minimum {min_cases}",
            }
        )
    for index, raw in enumerate(cases, start=1):
        case_id = str(raw.get("id") or f"case-{index}")
        seen_case_ids.add(case_id)
        try:
            result = _evaluate_belief_revision_case(case_id, raw)
        except (KeyError, TypeError, ValueError) as exc:
            result = {
                "id": case_id,
                "ok": False,
                "operation_by_ref": {},
                "assertions": {},
                "contradictions": [],
                "invalidated": [],
                "contested": [],
                "findings": [{"code": "invalid_case", "message": str(exc), "case_id": case_id}],
            }
        results.append(result)
        findings.extend(result["findings"])
    for case_id in required_ids:
        if case_id not in seen_case_ids:
            findings.append({"code": "missing_required_case", "message": f"required case {case_id} is missing"})
    return {
        "ok": not findings,
        "fingerprint": belief_revision_fingerprint(cases),
        "summary": {
            "cases": len(cases),
            "passed": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
            "required_case_ids": required_ids,
        },
        "results": results,
        "findings": findings,
    }


def _evaluate_belief_revision_case(case_id: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    tenant_id = str(raw.get("tenant_id") or f"tenant-{case_id}")
    user_id = str(raw.get("user_id") or "belief-check")
    branch = str(raw.get("branch") or "main")
    engine = LocalMemoryEngine()
    core = BeliefRevisionCore(engine)
    refs: dict[str, str] = {}
    operation_by_ref: dict[str, str] = {}
    case_findings: list[dict[str, Any]] = []
    assertions_raw = raw.get("assertions")
    if not isinstance(assertions_raw, list) or not assertions_raw:
        raise ValueError("belief revision case requires non-empty assertions array")
    for op_index, assertion_raw in enumerate(assertions_raw, start=1):
        if not isinstance(assertion_raw, Mapping):
            raise ValueError(f"assertion {op_index} must be an object")
        ref = str(assertion_raw.get("ref") or f"assertion-{op_index}")
        assertion = assertion_from_case(assertion_raw, tenant_id=tenant_id, user_id=user_id, branch=branch)
        dependencies = assertion_raw.get("dependencies", [])
        if dependencies:
            if not isinstance(dependencies, list):
                raise ValueError(f"{ref} dependencies must be an array")
            dependency_ids = [refs[str(item)] for item in dependencies]
            report = core.add_derived_belief(
                assertion,
                dependency_ids=dependency_ids,
                branch=branch,
                rule=str(assertion_raw.get("rule") or "derived"),
            )
        else:
            report = core.revise(assertion, branch=branch, rule=assertion_raw.get("rule"))
        refs[ref] = report.assertion_id
        operation_by_ref[ref] = report.operation

    invalidated: list[str] = []
    cascade = raw.get("cascade")
    if isinstance(cascade, Mapping):
        target_ref = str(cascade["assertion_ref"])
        invalidated_ids = core.cascade_invalidate(
            tenant_id,
            refs[target_ref],
            reason=str(cascade.get("reason") or "belief-check cascade"),
        )
        inverse_refs = {assertion_id: ref for ref, assertion_id in refs.items()}
        invalidated = [inverse_refs[item] for item in invalidated_ids if item in inverse_refs]

    exported = engine.export_tenant(tenant_id)
    assertion_by_id = {item["id"]: item for item in exported["assertions"]}
    assertions_by_ref = {
        ref: {
            "id": assertion_id,
            "status": assertion_by_id[assertion_id]["status"],
            "object": assertion_by_id[assertion_id]["object"],
            "superseded_by": _ref_for_assertion_id(refs, assertion_by_id[assertion_id].get("superseded_by")),
            "hypothesis_prob": assertion_by_id[assertion_id].get("calibration", {}).get("hypothesis_prob"),
        }
        for ref, assertion_id in refs.items()
    }
    contested_report: list[dict[str, object]] = []
    contested = raw.get("contested")
    if isinstance(contested, Mapping):
        contested_report = core.contested_hypotheses(
            tenant_id,
            str(contested["subject"]),
            str(contested["predicate"]),
            branch=branch,
        )

    expected = raw.get("expected", {})
    if not isinstance(expected, Mapping):
        raise ValueError("expected must be an object when provided")
    _compare_mapping_expectations(case_findings, case_id, operation_by_ref, expected.get("operations"), "operations")
    _compare_mapping_expectations(
        case_findings,
        case_id,
        {ref: item["status"] for ref, item in assertions_by_ref.items()},
        expected.get("statuses"),
        "statuses",
    )
    _compare_mapping_expectations(
        case_findings,
        case_id,
        {ref: item["superseded_by"] for ref, item in assertions_by_ref.items()},
        expected.get("superseded_by"),
        "superseded_by",
    )
    expected_invalidated = expected.get("invalidated")
    if expected_invalidated is not None and sorted(str(item) for item in expected_invalidated) != sorted(invalidated):
        case_findings.append(
            {
                "code": "expectation_mismatch",
                "case_id": case_id,
                "field": "invalidated",
                "expected": sorted(str(item) for item in expected_invalidated),
                "actual": sorted(invalidated),
            }
        )
    min_contradictions = int(expected.get("min_contradictions", 0) or 0)
    contradictions = [item for item in exported["contradictions"] if item["status"] == "open"]
    if len(contradictions) < min_contradictions:
        case_findings.append(
            {
                "code": "expectation_mismatch",
                "case_id": case_id,
                "field": "min_contradictions",
                "expected": min_contradictions,
                "actual": len(contradictions),
            }
        )
    contested_expected = expected.get("contested")
    if isinstance(contested_expected, Mapping):
        actual_objects = sorted(str(item["object"]) for item in contested_report)
        expected_objects = sorted(str(item) for item in contested_expected.get("objects", []))
        if expected_objects and actual_objects != expected_objects:
            case_findings.append(
                {
                    "code": "expectation_mismatch",
                    "case_id": case_id,
                    "field": "contested.objects",
                    "expected": expected_objects,
                    "actual": actual_objects,
                }
            )
        if contested_expected.get("probability_sum") is not None:
            actual_sum = round(sum(float(item["probability"]) for item in contested_report), 6)
            expected_sum = round(float(contested_expected["probability_sum"]), 6)
            if actual_sum != expected_sum:
                case_findings.append(
                    {
                        "code": "expectation_mismatch",
                        "case_id": case_id,
                        "field": "contested.probability_sum",
                        "expected": expected_sum,
                        "actual": actual_sum,
                    }
                )
    return {
        "id": case_id,
        "ok": not case_findings,
        "operation_by_ref": operation_by_ref,
        "assertions": assertions_by_ref,
        "contradictions": contradictions,
        "invalidated": invalidated,
        "contested": contested_report,
        "findings": case_findings,
    }


def _ref_for_assertion_id(refs: Mapping[str, str], assertion_id: str | None) -> str | None:
    if assertion_id is None:
        return None
    for ref, stored_id in refs.items():
        if stored_id == assertion_id:
            return ref
    return assertion_id


def _compare_mapping_expectations(
    findings: list[dict[str, Any]],
    case_id: str,
    actual: Mapping[str, Any],
    expected: Any,
    field: str,
) -> None:
    if expected is None:
        return
    if not isinstance(expected, Mapping):
        findings.append({"code": "invalid_expected", "case_id": case_id, "field": field, "message": "expected object"})
        return
    for key, expected_value in expected.items():
        actual_value = actual.get(str(key))
        if actual_value != expected_value:
            findings.append(
                {
                    "code": "expectation_mismatch",
                    "case_id": case_id,
                    "field": f"{field}.{key}",
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
