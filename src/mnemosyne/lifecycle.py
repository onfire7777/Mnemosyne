"""Fidelity-tiered forgetting and salience management."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any


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


def decayed_salience(state: LifecycleState, now: datetime) -> float:
    if state.last_accessed is None:
        age_days = 30.0
    else:
        age_days = max((now.astimezone(UTC) - state.last_accessed.astimezone(UTC)).total_seconds() / 86400.0, 0.0)
    decay = math.exp(-age_days / 45.0)
    access_boost = min(math.log1p(state.access_count) / 6.0, 0.35)
    return max(0.0, min(1.0, state.salience * decay + state.importance * 0.35 + access_boost))


def next_fidelity_tier(current: FidelityTier) -> FidelityTier:
    index = FIDELITY_ORDER.index(current)
    return FIDELITY_ORDER[min(index + 1, len(FIDELITY_ORDER) - 1)]


def demotion_decision(state: LifecycleState, now: datetime, utility_threshold: float = 0.18) -> tuple[LifecycleState, bool]:
    if state.protected:
        return state, False
    utility = decayed_salience(state, now)
    if utility > utility_threshold or state.tier == FidelityTier.STATISTICAL_TRACE:
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
    )
    return updated, True


def sole_support_requires_abstention(supporting_states: list[LifecycleState]) -> bool:
    if len(supporting_states) != 1:
        return False
    only = supporting_states[0]
    return only.tier in {FidelityTier.ABSTRACTIVE_GIST, FidelityTier.STATISTICAL_TRACE} and only.confabulation_risk


def next_rehearsal_days(successful_rehearsals: int) -> int:
    intervals = [1, 3, 7, 14, 30, 60, 120, 240]
    index = min(max(successful_rehearsals, 0), len(intervals) - 1)
    return intervals[index]


def rehearsal_due(state: LifecycleState, now: datetime) -> bool:
    if not (state.must_keep or state.protected):
        return False
    if state.next_rehearsal_at is None:
        return True
    return state.next_rehearsal_at <= now


def apply_rehearsal_schedule(state: LifecycleState, now: datetime) -> tuple[LifecycleState, bool]:
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
        ),
        True,
    )
