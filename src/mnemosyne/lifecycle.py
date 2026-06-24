"""Fidelity-tiered forgetting and salience management."""

from __future__ import annotations

import math
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Any
from collections.abc import Mapping


class FidelityTier(str, Enum):
    VERBATIM = "verbatim"
    EXTRACTIVE_SUMMARY = "extractive_summary"
    ABSTRACTIVE_GIST = "abstractive_gist"
    STATISTICAL_TRACE = "statistical_trace"


FIDELITY_ORDER = [
    FidelityTier.VERBATIM,
    FidelityTier.EXTRACTIVE_SUMMARY,
    FidelityTier.ABSTRACTIVE_GIST,
    FidelityTier.STATISTICAL_TRACE,
]


@dataclass(slots=True)
class LifecycleState:
    item_id: str
    tier: FidelityTier
    salience: float
    importance: float
    access_count: int
    last_accessed: datetime | None
    must_keep: bool = False
    successful_rehearsals: int = 0
    next_rehearsal_at: datetime | None = None
    last_rehearsed_at: datetime | None = None
    confabulation_risk: bool = False
    protected: bool = False
    verbatim_pointer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tier"] = self.tier.value
        data["last_accessed"] = self.last_accessed.astimezone(UTC).isoformat() if self.last_accessed else None
        data["next_rehearsal_at"] = (
            self.next_rehearsal_at.astimezone(UTC).isoformat() if self.next_rehearsal_at else None
        )
        data["last_rehearsed_at"] = (
            self.last_rehearsed_at.astimezone(UTC).isoformat() if self.last_rehearsed_at else None
        )
        data["rehearsal_interval_days"] = next_rehearsal_days(self.successful_rehearsals)
        return data


def decayed_salience(state: LifecycleState, now: datetime, *, actr_decay: float = 0.0) -> float:
    """Estimate a memory's current utility from recency, importance and use.

    With ``actr_decay == 0.0`` this preserves the legacy exponential recency
    decay. Positive values switch the recency term to the ACT-R power-law
    ``(1 + age_days) ** -d`` used by the blueprint's forgetting model.
    """
    if state.last_accessed is None:
        age_days = 30.0
    else:
        age_days = max((now.astimezone(UTC) - state.last_accessed.astimezone(UTC)).total_seconds() / 86400.0, 0.0)
    if actr_decay > 0.0:
        decay = (1.0 + age_days) ** (-actr_decay)
    else:
        decay = math.exp(-age_days / 45.0)
    access_boost = min(math.log1p(state.access_count) / 6.0, 0.35)
    return max(0.0, min(1.0, state.salience * decay + state.importance * 0.35 + access_boost))


def next_fidelity_tier(current: FidelityTier) -> FidelityTier:
    """Return the next-lower fidelity tier, saturating at statistical trace.

    Follows the blueprint's graduated forgetting order
    verbatim -> extractive summary -> abstractive gist -> statistical trace.
    """
    index = FIDELITY_ORDER.index(current)
    return FIDELITY_ORDER[min(index + 1, len(FIDELITY_ORDER) - 1)]


def demotion_decision(
    state: LifecycleState,
    now: datetime,
    utility_threshold: float = 0.18,
    *,
    actr_decay: float = 0.0,
) -> tuple[LifecycleState, bool]:
    """Apply graduated forgetting to one memory and report whether it demoted.

    Protected memories are never demoted. Otherwise the item keeps its tier
    while its predicted utility stays above ``utility_threshold``; once utility
    drops below it the item falls one fidelity tier (and is flagged
    ``confabulation_risk`` on the gist/statistical-trace tiers per fuzzy-trace
    theory). ``actr_decay`` is forwarded to :func:`decayed_salience`, defaulting
    to the legacy exponential path. Returns ``(updated_state, demoted)``.
    """
    if state.protected:
        return state, False
    utility = decayed_salience(state, now, actr_decay=actr_decay)
    # I7: must-keep memories are never demoted even when their decayed utility
    # falls below the threshold (e.g. when not yet due for rehearsal); they keep
    # their fidelity tier while their salience estimate is refreshed.
    if state.must_keep or utility > utility_threshold or state.tier == FidelityTier.STATISTICAL_TRACE:
        updated = LifecycleState(
            item_id=state.item_id,
            tier=state.tier,
            salience=utility,
            importance=state.importance,
            access_count=state.access_count,
            last_accessed=state.last_accessed,
            must_keep=state.must_keep,
            successful_rehearsals=state.successful_rehearsals,
            next_rehearsal_at=state.next_rehearsal_at,
            last_rehearsed_at=state.last_rehearsed_at,
            confabulation_risk=state.confabulation_risk,
            protected=state.protected,
            verbatim_pointer=state.verbatim_pointer,
        )
        return updated, False
    new_tier = next_fidelity_tier(state.tier)
    updated = LifecycleState(
        item_id=state.item_id,
        tier=new_tier,
        salience=utility,
        importance=state.importance,
        access_count=state.access_count,
        last_accessed=state.last_accessed,
        must_keep=state.must_keep,
        successful_rehearsals=state.successful_rehearsals,
        next_rehearsal_at=state.next_rehearsal_at,
        last_rehearsed_at=state.last_rehearsed_at,
        confabulation_risk=new_tier in {FidelityTier.ABSTRACTIVE_GIST, FidelityTier.STATISTICAL_TRACE},
        protected=state.protected,
        # I7/§25: keep the pointer to the verbatim original so a demoted gist can
        # be reconstructed from raw evidence (the documented confabulation guard).
        verbatim_pointer=state.verbatim_pointer,
    )
    return updated, True


def sole_support_requires_abstention(supporting_states: list[LifecycleState]) -> bool:
    """Return ``True`` when a claim rests solely on a confabulation-risky trace.

    Implements the fuzzy-trace confabulation guard: if the only support for a
    claim is a single low-fidelity (gist or statistical-trace) memory flagged
    ``confabulation_risk``, the system should abstain rather than answer from a
    trace that may have drifted away from the verbatim original.
    """
    if len(supporting_states) != 1:
        return False
    only = supporting_states[0]
    return only.tier in {FidelityTier.ABSTRACTIVE_GIST, FidelityTier.STATISTICAL_TRACE} and only.confabulation_risk


def parse_lifecycle_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def lifecycle_state_from_dict(row: Mapping[str, Any]) -> LifecycleState:
    return LifecycleState(
        item_id=str(row["item_id"]),
        tier=FidelityTier(str(row.get("tier", FidelityTier.VERBATIM.value))),
        salience=float(row.get("salience", 0.5)),
        importance=float(row.get("importance", 0.5)),
        access_count=int(row.get("access_count", 0)),
        last_accessed=parse_lifecycle_datetime(row.get("last_accessed")),
        must_keep=bool(row.get("must_keep", False)),
        successful_rehearsals=int(row.get("successful_rehearsals", 0)),
        next_rehearsal_at=parse_lifecycle_datetime(row.get("next_rehearsal_at")),
        last_rehearsed_at=parse_lifecycle_datetime(row.get("last_rehearsed_at")),
        confabulation_risk=bool(row.get("confabulation_risk", False)),
        protected=bool(row.get("protected", False)),
        verbatim_pointer=(str(row["verbatim_pointer"]) if row.get("verbatim_pointer") is not None else None),
    )


def forgetting_policy_fingerprint(cases: list[Mapping[str, Any]], *, utility_threshold: float) -> str:
    canonical = {
        "cases": cases,
        "utility_threshold": utility_threshold,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def validate_forgetting_policy_cases(
    cases: list[Mapping[str, Any]],
    *,
    now: datetime,
    utility_threshold: float = 0.18,
    min_cases: int = 1,
    required_case_ids: list[str] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    required = sorted(set(required_case_ids or []))
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
        expected = raw.get("expected", {})
        if not isinstance(expected, Mapping):
            findings.append({"code": "invalid_expected", "message": f"{case_id} expected must be an object"})
            continue
        try:
            result = _evaluate_forgetting_policy_case(
                case_id,
                raw,
                expected=expected,
                now=now,
                utility_threshold=utility_threshold,
            )
        except (KeyError, TypeError, ValueError) as exc:
            findings.append({"code": "invalid_case", "message": f"{case_id} denied: {exc}"})
            continue
        results.append(result)
        if not result["ok"]:
            findings.extend(result["findings"])
    for case_id in required:
        if case_id not in seen_case_ids:
            findings.append({"code": "missing_required_case", "message": f"required case {case_id} is missing"})
    return {
        "ok": not findings,
        "fingerprint": forgetting_policy_fingerprint(cases, utility_threshold=utility_threshold),
        "summary": {
            "cases": len(cases),
            "passed": sum(1 for item in results if item["ok"]),
            "failed": sum(1 for item in results if not item["ok"]),
            "required_case_ids": required,
        },
        "results": results,
        "findings": findings,
    }


def _evaluate_forgetting_policy_case(
    case_id: str,
    raw: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    now: datetime,
    utility_threshold: float,
) -> dict[str, Any]:
    if "supporting_states" in raw:
        supporting_states_raw = raw["supporting_states"]
        if not isinstance(supporting_states_raw, list):
            raise ValueError("supporting_states must be an array")
        supporting_states = [lifecycle_state_from_dict(item) for item in supporting_states_raw]
        actual: dict[str, Any] = {
            "abstention_required": sole_support_requires_abstention(supporting_states),
            "supporting_state_count": len(supporting_states),
        }
    else:
        state_raw = raw.get("state")
        if not isinstance(state_raw, Mapping):
            raise ValueError("state must be an object")
        state = lifecycle_state_from_dict(state_raw)
        rehearsed_state, rehearsed = apply_rehearsal_schedule(state, now)
        next_state, demoted = demotion_decision(rehearsed_state, now, utility_threshold=utility_threshold)
        actual = {
            "tier": next_state.tier.value,
            "demoted": demoted,
            "rehearsed": rehearsed,
            "abstention_required": sole_support_requires_abstention([next_state]),
            "state": next_state.to_dict(),
        }
    findings: list[dict[str, Any]] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(str(key))
        if actual_value != expected_value:
            findings.append(
                {
                    "code": "expectation_mismatch",
                    "case_id": case_id,
                    "field": str(key),
                    "expected": expected_value,
                    "actual": actual_value,
                    "message": f"{case_id} expected {key}={expected_value!r} but got {actual_value!r}",
                }
            )
    return {
        "id": case_id,
        "ok": not findings,
        "actual": actual,
        "expected": dict(expected),
        "findings": findings,
    }


def next_rehearsal_days(successful_rehearsals: int) -> int:
    """Return the spaced-repetition interval (days) for the next rehearsal.

    Intervals expand with each successful rehearsal (1, 3, 7, 14, 30, 60, 120,
    240 days), saturating at the final interval.
    """
    intervals = [1, 3, 7, 14, 30, 60, 120, 240]
    index = min(max(successful_rehearsals, 0), len(intervals) - 1)
    return intervals[index]


def rehearsal_due(state: LifecycleState, now: datetime) -> bool:
    """Return whether a must-keep/protected memory is due for rehearsal now."""
    if not (state.must_keep or state.protected):
        return False
    if state.next_rehearsal_at is None:
        return True
    return state.next_rehearsal_at <= now


def apply_rehearsal_schedule(state: LifecycleState, now: datetime) -> tuple[LifecycleState, bool]:
    """Rehearse a due must-keep/protected memory before any demotion runs.

    When the item is due, this records the rehearsal (advancing the
    spaced-repetition interval, boosting salience, and stamping access/rehearsal
    times) so that durable memories survive the forgetting sweep. Returns
    ``(updated_state, rehearsed)``; ordinary memories pass through unchanged.
    """
    if not (state.must_keep or state.protected):
        return state, False
    if not rehearsal_due(state, now):
        return state, False
    successful_rehearsals = max(state.successful_rehearsals, 0) + 1
    interval_days = next_rehearsal_days(successful_rehearsals)
    salience_boost = min(1.0, state.salience + 0.2 + state.importance * 0.2)
    return (
        LifecycleState(
            item_id=state.item_id,
            tier=state.tier,
            salience=max(state.salience, salience_boost),
            importance=state.importance,
            access_count=state.access_count + 1,
            last_accessed=now,
            must_keep=state.must_keep,
            successful_rehearsals=successful_rehearsals,
            next_rehearsal_at=now + timedelta(days=interval_days),
            last_rehearsed_at=now,
            confabulation_risk=state.confabulation_risk,
            protected=state.protected,
            verbatim_pointer=state.verbatim_pointer,
        ),
        True,
    )
