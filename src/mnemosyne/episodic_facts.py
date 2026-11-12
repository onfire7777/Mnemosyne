"""Deterministic offline episodic-to-semantic fact and milestone indexing.

Extracts structured Assertions and Relations from conversational dialogue and
episodic narrative across 4 primary fact families:
1. Residence & Location (living, moving, residing, apartment/home purchases)
2. Family & Pets (children, spouse, parents, siblings, pets and breeds)
3. Expenses & Counts (expenditures, purchases, item counts)
4. Dated Milestones (graduations, education, career, life milestones)

All extracted facts preserve:
- source_evidence_cids: evidence IDs for cryptographic provenance and trust derivation.
- valid_from: explicit event timestamp or evidence creation time.
- trust_tier: inherited from source evidence or caller context.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from mnemosyne.models import Assertion, Relation, parse_dt, utc_now
from mnemosyne.security import TrustTier


class IsoDateTime(str):
    """Dual str/datetime representation for occurrence interval endpoints in qualifiers."""

    def __new__(cls, dt: datetime) -> "IsoDateTime":
        aware = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        obj = super().__new__(cls, aware.isoformat())
        obj._dt = aware  # type: ignore[attr-defined]
        return obj

    def __reduce__(self) -> tuple[Any, tuple[datetime]]:
        return (IsoDateTime, (self._dt,))  # type: ignore[attr-defined]

    @property
    def year(self) -> int:
        return self._dt.year  # type: ignore[attr-defined]

    @property
    def month(self) -> int:
        return self._dt.month  # type: ignore[attr-defined]

    @property
    def day(self) -> int:
        return self._dt.day  # type: ignore[attr-defined]

    @property
    def hour(self) -> int:
        return self._dt.hour  # type: ignore[attr-defined]

    @property
    def minute(self) -> int:
        return self._dt.minute  # type: ignore[attr-defined]

    @property
    def second(self) -> int:
        return self._dt.second  # type: ignore[attr-defined]

    @property
    def tzinfo(self) -> Any:
        return self._dt.tzinfo  # type: ignore[attr-defined]

    def isoformat(self, *args: Any, **kwargs: Any) -> str:
        return self._dt.isoformat(*args, **kwargs)  # type: ignore[attr-defined]

    def date(self) -> Any:
        return self._dt.date()  # type: ignore[attr-defined]

    def timestamp(self) -> float:
        return self._dt.timestamp()  # type: ignore[attr-defined]

    def replace(self, *args: Any, **kwargs: Any) -> datetime:
        return self._dt.replace(*args, **kwargs)  # type: ignore[attr-defined]

    def astimezone(self, tz: Any = UTC) -> datetime:
        return self._dt.astimezone(tz)  # type: ignore[attr-defined]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, datetime):
            o = other.astimezone(UTC) if other.tzinfo else other.replace(tzinfo=UTC)
            return bool(self._dt == o)  # type: ignore[attr-defined]
        if isinstance(other, str):
            return super().__eq__(other) or (
                len(other) == 10 and str(self)[:10] == other
            )
        return False

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()

    def __lt__(self, other: object) -> bool:
        if isinstance(other, datetime):
            o = other.astimezone(UTC) if other.tzinfo else other.replace(tzinfo=UTC)
            return bool(self._dt < o)  # type: ignore[attr-defined]
        return super().__lt__(str(other))

    def __le__(self, other: object) -> bool:
        return self == other or self < other

    def __gt__(self, other: object) -> bool:
        if isinstance(other, datetime):
            o = other.astimezone(UTC) if other.tzinfo else other.replace(tzinfo=UTC)
            return bool(self._dt > o)  # type: ignore[attr-defined]
        return super().__gt__(str(other))

    def __ge__(self, other: object) -> bool:
        return self == other or self > other


if not hasattr(Assertion, "qualifiers"):
    _orig_assertion_init = Assertion.__init__

    def _assertion_init_with_qualifiers(
        self: Assertion,
        *args: Any,
        qualifiers: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        _orig_assertion_init(self, *args, **kwargs)
        if qualifiers is not None:
            self.calibration["qualifiers"] = dict(qualifiers)

    def _get_assertion_qualifiers(self: Assertion) -> dict[str, Any]:
        q = self.calibration.get("qualifiers")
        if not isinstance(q, dict):
            q = {}
            self.calibration["qualifiers"] = q
        return q

    def _set_assertion_qualifiers(self: Assertion, value: dict[str, Any]) -> None:
        self.calibration["qualifiers"] = dict(value or {})

    Assertion.__init__ = _assertion_init_with_qualifiers  # type: ignore[method-assign]
    Assertion.qualifiers = property(
        _get_assertion_qualifiers, _set_assertion_qualifiers
    )  # type: ignore[attr-defined]

MONTH_MAP: dict[str, int] = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

WORD_TO_NUM: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


@dataclass(slots=True)
class ExtractedFacts:
    """Container for assertions and relations extracted from episodic text."""

    assertions: list[Assertion] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)

    def __iter__(self):
        yield self.assertions
        yield self.relations

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> list[Any]:
        if index == 0:
            return self.assertions
        elif index == 1:
            return self.relations
        raise IndexError(
            "ExtractedFacts index out of range (0=assertions, 1=relations)"
        )

    @property
    def all_items(self) -> list[Assertion | Relation]:
        return list(self.assertions) + list(self.relations)


@dataclass(frozen=True, slots=True)
class DistilledFact:
    fact_id: str
    speaker_role: str
    category: str
    subject: str
    predicate: str
    value: Any
    valid_from: datetime | None
    valid_to: datetime | None
    is_current: bool
    scope: dict[str, Any] = field(default_factory=dict)


def _to_utc(dt: datetime | None) -> datetime:
    """Normalize datetime to UTC. If None, returns datetime.min with UTC tzinfo. If naive, assumes UTC."""
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _to_utc_opt(dt: datetime | None) -> datetime | None:
    """Normalize datetime to UTC, preserving None. If naive, assumes UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    value: Any
    valid_from: datetime
    valid_to: datetime | None
    status: str  # "CURRENT" or "SUPERSEDED"
    evidence_cids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityAttributeTrajectory:
    entity: str
    attribute: str
    steps: tuple[TrajectoryStep, ...]  # chronologically sorted
    current_value: Any

    @property
    def current(self) -> TrajectoryStep | None:
        for s in reversed(self.steps):
            if s.status == "CURRENT":
                return s
        return None

    def as_of(self, dt: datetime) -> TrajectoryStep | None:
        aware_dt = _to_utc(dt)
        for s in self.steps:
            vf = _to_utc(s.valid_from)
            vt = _to_utc_opt(s.valid_to)
            if vf <= aware_dt and (vt is None or aware_dt < vt):
                return s
        return None

    def format_trajectory(self) -> str:
        parts: list[str] = []
        for s in self.steps:
            date_str = s.valid_from.strftime("%Y-%m-%d") if s.valid_from else ""
            if date_str:
                parts.append(
                    f"{s.value} ({date_str}{', CURRENT' if s.status == 'CURRENT' else ''})"
                )
            else:
                parts.append(
                    f"{s.value}{' (CURRENT)' if s.status == 'CURRENT' else ''}"
                )
        return " -> ".join(parts)


@dataclass(frozen=True, slots=True)
class EpisodicUserDigest:
    facts: tuple[DistilledFact, ...]
    trajectories: tuple[EntityAttributeTrajectory, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.facts, tuple):
            object.__setattr__(self, "facts", tuple(self.facts))
        if not isinstance(self.trajectories, tuple):
            object.__setattr__(self, "trajectories", tuple(self.trajectories))

    def render_markdown(self) -> str:
        lines: list[str] = [
            "=== EPISODIC USER-FACT & STATE DIGEST (AUTHORITATIVE USER STATEMENTS) ===",
            "NOTE: The facts below were authored by the user (speaker_role='user') and represent true state.",
            "They supersede any assistant suggestions, hypotheticals, or speculation.",
            "",
            "## Current State & Facts:",
        ]
        current_facts = [f for f in self.facts if f.is_current]
        if current_facts:
            residences = [f for f in current_facts if f.category == "residence"]
            for f in residences:
                lines.append(f"- Residence: {f.value} [CURRENT]")
            family_pets = [f for f in current_facts if f.category == "family_pet"]
            for f in family_pets:
                lines.append(f"- Family/Pet ({f.predicate}): {f.value} [CURRENT]")
            milestones = [
                f for f in current_facts if f.category in {"education", "milestone"}
            ]
            for f in milestones:
                lines.append(f"- Milestone ({f.predicate}): {f.value} [CURRENT]")
            counts = [f for f in current_facts if f.category == "count"]
            for f in counts:
                lines.append(f"- Quantity/Possession: {f.value} [CURRENT]")
            expenses = [f for f in current_facts if f.category == "expense"]
            for f in expenses:
                lines.append(f"- Expense: {f.value} [CURRENT]")
            durations = [f for f in current_facts if f.category == "duration"]
            for f in durations:
                lines.append(f"- Duration: {f.value} [CURRENT]")
            others = [
                f
                for f in current_facts
                if f.category
                not in {
                    "residence",
                    "family_pet",
                    "education",
                    "milestone",
                    "count",
                    "expense",
                    "duration",
                }
            ]
            for f in others:
                lines.append(f"- {f.predicate}: {f.value} [CURRENT]")
        else:
            lines.append("- (No active user facts recorded)")

        if self.trajectories:
            lines.append("\n## Chronological State Trajectories:")
            for traj in self.trajectories:
                if len(traj.steps) > 1:
                    lines.append(
                        f"- {traj.entity}.{traj.attribute}: {traj.format_trajectory()}"
                    )
                elif len(traj.steps) == 1:
                    if traj.steps[0].status == "CURRENT":
                        lines.append(
                            f"- {traj.entity}.{traj.attribute}: {traj.steps[0].value} (CURRENT)"
                        )
                    else:
                        lines.append(
                            f"- {traj.entity}.{traj.attribute}: {traj.format_trajectory()}"
                        )

        lines.append(
            "========================================================================"
        )
        return "\n".join(lines)


_INACTIVE_ASSERTION_STATUSES = {
    "superseded",
    "retracted",
    "quarantined",
    "contested",
    "expired",
    "archived",
}


def _is_hypothetical_assertion(a: Assertion) -> bool:
    return bool(
        a.qualifiers.get("is_hypothetical")
        or a.qualifiers.get("hypothetical")
        or a.scope.get("is_hypothetical")
        or a.scope.get("hypothetical")
    )


def build_attribute_trajectory(
    assertions: Sequence[Assertion],
    entity: str,
    attribute: str,
) -> EntityAttributeTrajectory:
    """Build a chronological state-evolution trajectory for an entity's attribute (t1 -> t2 -> t3).

    Orders transitions chronologically and explicitly tags the latest valid state as (CURRENT).
    """
    ent_low = entity.strip().lower()
    attr_low = attribute.strip().lower()

    def _matches_pred(p: str) -> bool:
        pl = p.strip().lower()
        if attr_low in {"residence", "lives_in", "lived_in"}:
            return pl in {"residence", "lives_in", "lived_in"}
        if attr_low in {"education", "graduated_from"}:
            return pl in {"education", "graduated_from"}
        if attr_low in {"works_at", "employed_by"}:
            return pl in {"works_at", "employed_by"}
        return pl == attr_low

    matching = [
        a
        for a in assertions
        if a.subject.strip().lower() == ent_low
        and _matches_pred(a.predicate)
        and not _is_hypothetical_assertion(a)
    ]
    if not matching:
        return EntityAttributeTrajectory(
            entity=entity,
            attribute=attribute,
            steps=(),
            current_value=None,
        )

    sorted_assertions = sorted(
        matching,
        key=lambda a: (
            _to_utc(a.valid_from),
            _to_utc(
                getattr(a, "transaction_time", None) or getattr(a, "created_at", None)
            ),
        ),
    )

    steps: list[TrajectoryStep] = []
    n = len(sorted_assertions)
    now_utc = utc_now()

    # Find the latest active and unexpired assertion
    latest_active_idx: int | None = None
    for i in reversed(range(n)):
        a_cand = sorted_assertions[i]
        cand_status = getattr(a_cand, "status", "active") or "active"
        cand_vt_opt = _to_utc_opt(a_cand.valid_to)
        cand_expired = cand_vt_opt is not None and cand_vt_opt < now_utc
        if cand_status not in _INACTIVE_ASSERTION_STATUSES and not cand_expired:
            latest_active_idx = i
            break

    for i, a in enumerate(sorted_assertions):
        is_last = i == n - 1
        vf = (
            _to_utc(a.valid_from)
            if a.valid_from is not None
            else datetime.min.replace(tzinfo=UTC)
        )
        a_status = getattr(a, "status", "active") or "active"

        if i == latest_active_idx:
            status = "CURRENT"
            vt = a.valid_to
        else:
            if a_status in {"retracted", "quarantined", "contested"}:
                status = a_status.upper()
            else:
                status = "SUPERSEDED"
            next_vf = sorted_assertions[i + 1].valid_from or vf if not is_last else None
            vt = a.valid_to if a.valid_to is not None else next_vf

        cids = tuple(str(c) for c in (a.source_evidence_cids or ()))
        steps.append(
            TrajectoryStep(
                value=a.object,
                valid_from=vf,
                valid_to=vt,
                status=status,
                evidence_cids=cids,
            )
        )

    current_val = (
        steps[latest_active_idx].value if latest_active_idx is not None else None
    )
    return EntityAttributeTrajectory(
        entity=entity,
        attribute=attribute,
        steps=tuple(steps),
        current_value=current_val,
    )


def _canonical_attribute(attr: str) -> str:
    al = attr.strip().lower()
    if al in {"residence", "lives_in", "lived_in"}:
        return "residence"
    if al in {"education", "graduated_from"}:
        return "education"
    if al in {"works_at", "employed_by"}:
        return "works_at"
    return al


def build_attribute_trajectories(
    assertions: Sequence[Assertion],
) -> tuple[EntityAttributeTrajectory, ...]:
    """Group assertions by entity and canonical attribute and construct trajectories."""
    groups: dict[tuple[str, str], list[Assertion]] = {}
    for a in assertions:
        if _is_hypothetical_assertion(a):
            continue
        subj = a.subject.strip().lower()
        canonical_p = _canonical_attribute(a.predicate)
        key = (subj, canonical_p)
        groups.setdefault(key, []).append(a)

    trajectories: list[EntityAttributeTrajectory] = []
    for (subj, pred), group in groups.items():
        if len(group) > 1 or (
            group
            and any(
                getattr(a, "status", None) in {"superseded", "retracted", "quarantined"}
                for a in group
            )
        ):
            trajectories.append(build_attribute_trajectory(group, subj, pred))
    return tuple(trajectories)


def build_episodic_user_digest(
    facts: Sequence[Assertion] | ExtractedFacts,
    *,
    as_of: datetime | None = None,
) -> EpisodicUserDigest:
    """Build a high-signal episodic user-fact and state digest from extracted assertions.

    Filters exclusively for user-authored statements (speaker_role="user") and verified user attributes,
    grouping current states, quantities, prices, durations, and active entities above raw dialogue.
    """
    if isinstance(facts, ExtractedFacts):
        raw_assertions = facts.assertions
    elif hasattr(facts, "assertions"):
        raw_assertions = getattr(facts, "assertions", [])
    else:
        raw_assertions = list(facts)

    filtered_assertions: list[Assertion] = []
    for a in raw_assertions:
        s_role = str(a.qualifiers.get("speaker_role") or "user").strip().lower()
        if s_role in {"assistant", "agent", "bot", "ai", "model"}:
            continue
        if a.qualifiers.get("epistemic_class") == "agent_experience":
            continue
        if a.subject.strip().lower() in {"assistant", "agent", "bot", "ai", "model"}:
            continue
        if (
            a.qualifiers.get("is_hypothetical")
            or a.qualifiers.get("hypothetical")
            or a.scope.get("is_hypothetical")
            or a.scope.get("hypothetical")
        ):
            continue
        filtered_assertions.append(a)

    sorted_assertions = sorted(
        filtered_assertions,
        key=lambda a: (
            _to_utc(a.valid_from),
            _to_utc(
                getattr(a, "transaction_time", None) or getattr(a, "created_at", None)
            ),
        ),
    )

    latest_single_value: dict[tuple[str, str], Assertion] = {}
    for a in sorted_assertions:
        cat_key = a.predicate.lower()
        if cat_key in {"residence", "lives_in"}:
            latest_single_value[(a.subject.lower(), "residence")] = a

    latest_single_value_as_of: dict[tuple[str, str], Assertion] = {}
    if as_of is not None:
        aware_as_of = _to_utc(as_of)
        for a in sorted_assertions:
            cat_key = a.predicate.lower()
            if cat_key in {"residence", "lives_in"}:
                vf = _to_utc(a.valid_from)
                vt = _to_utc_opt(a.valid_to)
                if (
                    vf <= aware_as_of
                    and (vt is None or aware_as_of < vt)
                    and (
                        getattr(a, "status", "active")
                        not in _INACTIVE_ASSERTION_STATUSES
                        or (vt is not None and aware_as_of < vt)
                    )
                ):
                    latest_single_value_as_of[(a.subject.lower(), "residence")] = a

    distilled: list[DistilledFact] = []
    for a in sorted_assertions:
        pred_low = a.predicate.lower()
        is_single = pred_low in {"residence", "lives_in"}
        if as_of is not None:
            aware_as_of = _to_utc(as_of)
            vf = _to_utc(a.valid_from)
            vt = _to_utc_opt(a.valid_to)
            in_window = (
                (vf <= aware_as_of)
                and (vt is None or aware_as_of < vt)
                and (
                    getattr(a, "status", "active") not in _INACTIVE_ASSERTION_STATUSES
                    or (vt is not None and aware_as_of < vt)
                )
            )
            if is_single:
                latest = latest_single_value_as_of.get((a.subject.lower(), "residence"))
                is_curr = in_window and (a is latest)
            else:
                is_curr = in_window
        elif is_single:
            latest = latest_single_value.get((a.subject.lower(), "residence"))
            is_curr = (
                (a is latest)
                and (getattr(a, "status", "active") not in _INACTIVE_ASSERTION_STATUSES)
                and (a.valid_to is None)
            )
        else:
            is_curr = (
                getattr(a, "status", "active") not in _INACTIVE_ASSERTION_STATUSES
            ) and (a.valid_to is None)

        if pred_low in {"residence", "lives_in"}:
            cat = "residence"
        elif pred_low in {"has_family", "has_pet", "breed"} or pred_low.startswith(
            "has_"
        ):
            cat = "family_pet"
        elif pred_low in {"expense", "spent_on"}:
            cat = "expense"
        elif pred_low in {"count", "owns"}:
            cat = "count"
        elif (
            pred_low in {"duration", "for_duration", "stayed_for"}
            or "duration" in a.scope
        ):
            cat = "duration"
        elif pred_low in {"education", "graduated_from"}:
            cat = "education"
        elif pred_low in {"milestone", "works_at", "employed_by", "married_to"}:
            cat = "milestone"
        else:
            cat = a.scope.get("category") or "user_state"

        distilled.append(
            DistilledFact(
                fact_id=a.id,
                speaker_role=str(a.qualifiers.get("speaker_role") or "user"),
                category=cat,
                subject=a.subject,
                predicate=a.predicate,
                value=a.object,
                valid_from=a.valid_from,
                valid_to=a.valid_to,
                is_current=is_curr,
                scope=dict(a.scope or {}),
            )
        )

    trajectories = build_attribute_trajectories(filtered_assertions)
    return EpisodicUserDigest(facts=tuple(distilled), trajectories=trajectories)


def parse_explicit_date(date_str: str | None) -> datetime | None:
    """Parse an explicit date, month+year, or 4-digit year into a UTC datetime."""
    if not date_str:
        return None
    cleaned = date_str.strip().strip(",.;")
    if not cleaned:
        return None

    # 1. Full date: Month Day, Year (e.g. "May 4, 2018", "June 15 2020", "October 12, 2015")
    m_full = re.search(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_full:
        month_name = m_full.group(1).lower()
        day = int(m_full.group(2))
        year = int(m_full.group(3))
        month = MONTH_MAP.get(month_name, 1)
        try:
            return datetime(year, month, day, 0, 0, 0, tzinfo=UTC)
        except ValueError:
            pass

    # 2. ISO date: YYYY-MM-DD
    m_iso = re.search(r"\b(19\d\d|20\d\d)-(\d{2})-(\d{2})\b", cleaned)
    if m_iso:
        try:
            return datetime(
                int(m_iso.group(1)),
                int(m_iso.group(2)),
                int(m_iso.group(3)),
                0,
                0,
                0,
                tzinfo=UTC,
            )
        except ValueError:
            pass

    # 3. Month and Year: (e.g. "May 2018", "August 2023")
    m_my = re.search(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_my:
        month_name = m_my.group(1).lower()
        year = int(m_my.group(2))
        month = MONTH_MAP.get(month_name, 1)
        return datetime(year, month, 1, 0, 0, 0, tzinfo=UTC)

    # 4. 4-digit Year: (e.g. "2021", "2024")
    m_yr = re.search(r"\b(19\d\d|20\d\d)\b", cleaned)
    if m_yr:
        year = int(m_yr.group(1))
        return datetime(year, 1, 1, 0, 0, 0, tzinfo=UTC)

    return None


def _clean_location(loc: str) -> str:
    cleaned = loc.strip().strip(",.;!? ")
    # Strip trailing "in 2024" or "now" or "today" or "recently"
    cleaned = re.sub(
        r"(?i)\s+(?:in\s+\d{4}|now|today|recently|currently|with\s+.*|and\s+.*)$",
        "",
        cleaned,
    )
    return cleaned.strip()


def classify_epistemic_fact(text: str, speaker_role: str = "user") -> str:
    """Classify an episodic statement into one of four biomimetic epistemic classes:
    - 'world_fact': objective external statements without personal/agent experiential framing
    - 'agent_experience': assistant/agent actions, tool executions, or assistant-attributed experiences
    - 'user_experience': first-person user experiences, preferences, possessions, or personal states
    - 'observation': sensory/observational statements ('I noticed', 'It seems', 'Observed that', etc.)
    """
    raw_role = (speaker_role or "user").strip().lower()
    cleaned = (text or "").strip()

    # Check inline speaker prefix if present
    m_prefix = re.match(
        r"(?i)^(assistant|agent|bot|ai|model|user|human|observer|observation|sensor|monitor)\s*:\s*(.*)$",
        cleaned,
    )
    if m_prefix:
        prefix_role = m_prefix.group(1).lower()
        cleaned = m_prefix.group(2).strip()
        if prefix_role in {"assistant", "agent", "bot", "ai", "model"}:
            raw_role = "assistant"
        elif prefix_role in {"observer", "observation", "sensor", "monitor"}:
            raw_role = "observation"
        elif prefix_role in {"user", "human"}:
            raw_role = "user"

    if raw_role in {"observer", "observation", "sensor", "monitor"}:
        return "observation"

    # Explicit observational markers
    if re.search(
        r"(?i)\b(?:(?:i|we)\s+(?:noticed|observed|saw|spotted|witnessed|overheard|detected|heard)|"
        r"(?:it\s+)?(?:seem(?:s|ed)?|appear(?:s|ed)?|look(?:s|ed)?\s+like|sound(?:s|ed)?\s+like)\b|"
        r"(?:observed|noticed|detected|witnessed)\s+that\b|"
        r"^observed\b|^observation\b|^apparently\b)",
        cleaned,
    ):
        return "observation"

    if raw_role in {"assistant", "agent", "bot", "ai", "model"}:
        return "agent_experience"

    # Explicit assistant/agent references in text
    if re.search(
        r"(?i)\b(?:the\s+(?:assistant|agent|bot|ai)|(?:assistant|agent)\s+(?:recommended|suggested|executed|ran|generated|retrieved|searched|found|updated|deployed|created|fixed|checked))\b",
        cleaned,
    ):
        return "agent_experience"

    # First-person user experiences, preferences, family, possessions, or actions
    if re.search(
        r"(?i)\b(?:i|i'm|i've|i'd|i'll|me|my|mine|myself|we|we're|we've|we'd|we'll|us|our|ours|ourselves)\b",
        cleaned,
    ):
        return "user_experience"

    return "world_fact"


def _end_of_month_dt(year: int, month: int) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, 23, 59, 59, tzinfo=UTC)


def _parse_number_token(token: str) -> int:
    t = token.strip().lower()
    if t in {"a", "an"}:
        return 1
    if t.isdigit():
        return int(t)
    return WORD_TO_NUM.get(t, 1)


def parse_relative_or_prose_date(
    text: str,
    reference_time: datetime | None = None,
) -> tuple[datetime | None, datetime | None, str]:
    """Resolve explicit, quarter, part-of-year, seasonal, and relative date expressions.

    Returns (occurrence_start, occurrence_end, temporal_precision) where temporal_precision
    is one of 'day', 'week', 'month', 'quarter', 'season', 'year', or 'none'.
    """
    if not text or not text.strip():
        return None, None, "none"
    cleaned = text.strip()
    ref = (
        reference_time.astimezone(UTC)
        if (reference_time is not None and reference_time.tzinfo is not None)
        else (
            reference_time.replace(tzinfo=UTC)
            if reference_time is not None
            else utc_now()
        )
    )

    # 1. Relative offset from an explicit date: "N days/weeks/months/years after/before <explicit date>"
    m_rel_explicit = re.search(
        r"(?i)\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(day|week|month|year)s?\s+(after|before|following|prior\s+to)\s+([A-Za-z0-9,.\s-]+)",
        cleaned,
    )
    if m_rel_explicit:
        n = _parse_number_token(m_rel_explicit.group(1))
        unit = m_rel_explicit.group(2).lower()
        direction = (
            -1 if m_rel_explicit.group(3).lower().startswith(("before", "prior")) else 1
        )
        anchor = parse_explicit_date(m_rel_explicit.group(4))
        if anchor is not None:
            if unit == "day":
                dt = anchor + timedelta(days=direction * n)
                return (
                    datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=UTC),
                    datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
                    "day",
                )
            if unit == "week":
                dt = anchor + timedelta(days=7 * direction * n)
                return (
                    datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=UTC),
                    datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
                    "day",
                )
            if unit == "month":
                total_m = (anchor.year * 12 + (anchor.month - 1)) + direction * n
                y, m0 = divmod(total_m, 12)
                m_val = m0 + 1
                day = min(anchor.day, calendar.monthrange(y, m_val)[1])
                start_dt = datetime(y, m_val, day, 0, 0, 0, tzinfo=UTC)
                return start_dt, _end_of_month_dt(y, m_val), "month"
            if unit == "year":
                y = anchor.year + direction * n
                return (
                    datetime(y, 1, 1, 0, 0, 0, tzinfo=UTC),
                    datetime(y, 12, 31, 23, 59, 59, tzinfo=UTC),
                    "year",
                )

    # 2. Quarter expressions: "Q1 2024", "in Q3 2023", "2024 Q2"
    m_quarter = re.search(
        r"(?i)\bQ([1-4])\s*(?:of\s+)?(19\d\d|20\d\d)\b|\b(19\d\d|20\d\d)\s*[-/]?\s*Q([1-4])\b",
        cleaned,
    )
    if m_quarter:
        q = int(m_quarter.group(1) or m_quarter.group(4))
        y = int(m_quarter.group(2) or m_quarter.group(3))
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        return (
            datetime(y, start_month, 1, 0, 0, 0, tzinfo=UTC),
            _end_of_month_dt(y, end_month),
            "quarter",
        )

    # 3. Part-of-year expressions: "early 2023", "mid 2022", "late 2024" -> 4-month interval, precision "season"
    m_part = re.search(
        r"(?i)\b(early|mid|middle\s+of|late|beginning\s+of|end\s+of)[\s-]+(?:of\s+)?(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_part:
        part = m_part.group(1).lower()
        y = int(m_part.group(2))
        if part.startswith(("early", "begin")):
            return (
                datetime(y, 1, 1, 0, 0, 0, tzinfo=UTC),
                _end_of_month_dt(y, 4),
                "season",
            )
        if part.startswith("mid"):
            return (
                datetime(y, 5, 1, 0, 0, 0, tzinfo=UTC),
                _end_of_month_dt(y, 8),
                "season",
            )
        return datetime(y, 9, 1, 0, 0, 0, tzinfo=UTC), _end_of_month_dt(y, 12), "season"

    # 4. Seasonal expressions with explicit year: "summer 2022", "winter 2023", "spring of 2021", "fall 2020"
    m_season_yr = re.search(
        r"(?i)\b(spring|summer|fall|autumn|winter)\s+(?:of\s+)?(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_season_yr:
        season = m_season_yr.group(1).lower()
        y = int(m_season_yr.group(2))
        return _season_interval(season, y)

    # 5. Relative seasonal expressions: "last summer", "last spring", "last fall", "last winter", "this summer"
    m_rel_season = re.search(
        r"(?i)\b(last|this|previous)\s+(spring|summer|fall|autumn|winter)\b",
        cleaned,
    )
    if m_rel_season:
        mod = m_rel_season.group(1).lower()
        season = m_rel_season.group(2).lower()
        y = ref.year - 1 if mod in {"last", "previous"} else ref.year
        return _season_interval(season, y)

    # 6. Relative offsets to reference_time: "N days/weeks/months/years ago"
    m_ago = re.search(
        r"(?i)\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(day|week|month|year)s?\s+ago\b",
        cleaned,
    )
    if m_ago:
        n = _parse_number_token(m_ago.group(1))
        unit = m_ago.group(2).lower()
        if unit == "day":
            dt = ref - timedelta(days=n)
            return (
                datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=UTC),
                datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
                "day",
            )
        if unit == "week":
            dt = ref - timedelta(days=7 * n)
            return (
                datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=UTC),
                datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
                "day",
            )
        if unit == "month":
            total_m = (ref.year * 12 + (ref.month - 1)) - n
            y, m0 = divmod(total_m, 12)
            m_val = m0 + 1
            return (
                datetime(y, m_val, 1, 0, 0, 0, tzinfo=UTC),
                _end_of_month_dt(y, m_val),
                "month",
            )
        if unit == "year":
            y = ref.year - n
            return (
                datetime(y, 1, 1, 0, 0, 0, tzinfo=UTC),
                datetime(y, 12, 31, 23, 59, 59, tzinfo=UTC),
                "year",
            )

    # 7. "last month", "last year", "yesterday", "today"
    if re.search(r"(?i)\blast\s+month\b", cleaned):
        total_m = (ref.year * 12 + (ref.month - 1)) - 1
        y, m0 = divmod(total_m, 12)
        m_val = m0 + 1
        return (
            datetime(y, m_val, 1, 0, 0, 0, tzinfo=UTC),
            _end_of_month_dt(y, m_val),
            "month",
        )
    if re.search(r"(?i)\blast\s+year\b", cleaned):
        y = ref.year - 1
        return (
            datetime(y, 1, 1, 0, 0, 0, tzinfo=UTC),
            datetime(y, 12, 31, 23, 59, 59, tzinfo=UTC),
            "year",
        )
    if re.search(r"(?i)\byesterday\b", cleaned):
        dt = ref - timedelta(days=1)
        return (
            datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=UTC),
            datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
            "day",
        )

    # 8. Explicit dates via parse_explicit_date (precision "day", "month", or "year")
    m_full = re.search(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_full:
        dt = parse_explicit_date(m_full.group(0))
        if dt is not None:
            return (
                dt,
                datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
                "day",
            )

    m_iso = re.search(r"\b(19\d\d|20\d\d)-(\d{2})-(\d{2})\b", cleaned)
    if m_iso:
        dt = parse_explicit_date(m_iso.group(0))
        if dt is not None:
            return (
                dt,
                datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=UTC),
                "day",
            )

    m_my = re.search(
        r"(?i)\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+(19\d\d|20\d\d)\b",
        cleaned,
    )
    if m_my:
        dt = parse_explicit_date(m_my.group(0))
        if dt is not None:
            return dt, _end_of_month_dt(dt.year, dt.month), "month"

    m_yr = re.search(r"\b(19\d\d|20\d\d)\b", cleaned)
    if m_yr:
        dt = parse_explicit_date(m_yr.group(0))
        if dt is not None:
            return dt, datetime(dt.year, 12, 31, 23, 59, 59, tzinfo=UTC), "year"

    return None, None, "none"


def _season_interval(season: str, year: int) -> tuple[datetime, datetime, str]:
    s = season.lower()
    if s == "spring":
        return (
            datetime(year, 3, 1, 0, 0, 0, tzinfo=UTC),
            _end_of_month_dt(year, 5),
            "season",
        )
    if s == "summer":
        return (
            datetime(year, 6, 1, 0, 0, 0, tzinfo=UTC),
            _end_of_month_dt(year, 8),
            "season",
        )
    if s in {"fall", "autumn"}:
        return (
            datetime(year, 9, 1, 0, 0, 0, tzinfo=UTC),
            _end_of_month_dt(year, 11),
            "season",
        )
    # winter: Dec 1 to Dec 31 of that year (keeps both start and end in `year`)
    return (
        datetime(year, 12, 1, 0, 0, 0, tzinfo=UTC),
        _end_of_month_dt(year, 12),
        "season",
    )


class OpenDomainFacts(list[Assertion]):
    """List of Assertion objects that also exposes .assertions and .relations like ExtractedFacts."""

    def __init__(
        self, assertions: Sequence[Assertion] = (), relations: Sequence[Relation] = ()
    ) -> None:
        super().__init__(assertions)
        self.relations: list[Relation] = list(relations)

    @property
    def assertions(self) -> list[Assertion]:
        return list(self)

    @property
    def all_items(self) -> list[Assertion | Relation]:
        return list(self) + list(self.relations)


_OPEN_DOMAIN_STOP_SUBJECTS = frozenset(
    {
        "what",
        "who",
        "when",
        "where",
        "why",
        "how",
        "which",
        "there",
        "here",
        "it",
        "this",
        "that",
        "these",
        "those",
        "hello",
        "hi",
        "hey",
        "thanks",
        "thank",
        "please",
        "okay",
        "ok",
        "yes",
        "no",
    }
)


def split_episodic_clauses(text: str) -> list[str]:
    """Split independent coordinated claims, retaining the explicit speaker.

    Noun conjunctions ("coffee and tea") stay intact. An omitted subject is
    inherited only before a recognizable verb, never from arbitrary prose.
    """
    clauses: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|[;\n]+", text or ""):
        speaker = re.match(r"(?i)^\s*(I|We)\b", sentence)
        parts = re.split(
            r"(?i)\s+(?:and|but)\s+(?=(?:I|we|my|our)\b|"
            r"(?:work|works|worked|live|lived|reside|resided|like|love|prefer|hate|"
            r"own|use|have|am|was|speak|study|studied|graduated|moved|decided)\b)",
            sentence,
        )
        for index, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if index and speaker and not re.match(r"(?i)^(I|we|my|our)\b", part):
                part = speaker.group(1) + " " + part
            clauses.append(part)
    return clauses


def _historical_state_window(text: str, reference_time: datetime):
    """Return only an attested past-state window, never an inferred move date."""
    past = re.search(
        r"(?i)\b(?:I|we)\s+(?:used\s+to\s+|did\s+(?:not\s+)?|was\b|were\b|lived\b|resided\b|"
        r"worked\b|liked\b|preferred\b|owned\b|spoke\b)", text,
    ) or re.search(r"(?i)\b(?:my|our)\s+[^.!?]+?\s+(?:was|were)\b", text)
    if not past:
        return None
    start, end, precision = parse_relative_or_prose_date(text, reference_time=reference_time)
    # A date following 'since' asserts a start, not a closing boundary. Bare
    # past tense likewise supplies no known end; store that uncertainty.
    bounded = bool(re.search(r"(?i)\b(?:in|on|during)\s+|\b(?:last|ago|yesterday)\b", text))
    if not bounded or re.search(r"(?i)\bsince\b", text):
        end = None
    return start, end + timedelta(seconds=1) if end is not None else None, precision


def _apply_historical_state_window(
    text: str, assertions: list[Assertion], relations: list[Relation], reference_time: datetime,
) -> None:
    from mnemosyne.assertion_semantics import assertion_predicate_key

    window = _historical_state_window(text, reference_time)
    if window is None:
        return
    past_start, past_end, precision = window
    state_predicates = {"residence", "work_at", "work_for", "is_a", "name", "like", "prefer", "own", "speak"}
    historical = [a for a in assertions if assertion_predicate_key(a.predicate)[0] in state_predicates]
    for assertion in historical:
        assertion.scope["temporal_context"] = "historical"
        assertion.qualifiers.update({
            "temporal_context": "historical", "current_state": "unknown",
            "validity_semantics": "attested_interval", "end_known": past_end is not None,
        })
        if past_start is not None:
            assertion.valid_from = past_start
        else:
            assertion.qualifiers["start_known"] = False
        assertion.valid_to = past_end
        assertion.status = "superseded"
    if historical:
        historical_keys = {(a.subject, a.object) for a in historical}
        for relation in list(relations):
            if (relation.source, relation.target) not in historical_keys:
                continue
            if past_end is None:
                # Relations have no historical/unknown-time state. Do not
                # turn a historical statement with unknown end into a live edge.
                relations.remove(relation)
            else:
                relation.valid_from = past_start or relation.valid_from
                relation.valid_to = past_end


def _strip_temporal_affixes(clause: str) -> str:
    s = clause.strip().strip(",.;!")
    # Strip leading temporal phrase followed by comma
    s = re.sub(
        r"(?i)^(?:(?:in|on|during|around|by|since|from|after|before)\s+"
        r"(?:Q[1-4]\s+\d{4}|(?:early|mid|late|spring|summer|fall|autumn|winter)\s+(?:of\s+)?\d{4}|"
        r"last\s+(?:spring|summer|fall|autumn|winter|month|year|week)|"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)[a-z.,\s0-9]*?\d{4}|\d{4}(?:-\d{2}-\d{2})?)|"
        r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(?:day|week|month|year)s?\s+(?:ago|after\s+[^,]+|before\s+[^,]+)|"
        r"yesterday|today|last\s+(?:month|year|week|spring|summer|fall|autumn|winter))\s*,\s*",
        "",
        s,
    )
    # Strip trailing temporal modifier
    s = re.sub(
        r"(?i)\s+(?:in\s+Q[1-4]\s+\d{4}|"
        r"in\s+(?:early|mid|late|spring|summer|fall|autumn|winter)\s+(?:of\s+)?\d{4}|"
        r"last\s+(?:spring|summer|fall|autumn|winter|month|year|week)|"
        r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(?:day|week|month|year)s?\s+(?:ago|after\s+[A-Za-z0-9,\s-]+|before\s+[A-Za-z0-9,\s-]+)|"
        r"(?:in|on|since)\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)[a-z.,\s0-9]*?\d{4}|"
        r"(?:in|on|since)\s+\d{4}(?:-\d{2}-\d{2})?)$",
        "",
        s,
    )
    return s.strip().strip(",.;!")


_HYPOTHETICAL_PATTERN = re.compile(
    r"(?i)\b(?:suppose|imagine|hypothetically|what if|let's say|assuming|consider a scenario)\b"
)
_LEADING_HYPOTHETICAL_RE = re.compile(
    r"(?i)^\s*(?:suppose(?:\s+that|\s*,\s*|\s+)|"
    r"imagine(?:\s+that|\s*,\s*|\s+)|"
    r"hypothetically(?:\s*,\s*|\s+)|"
    r"what\s+if\s+|"
    r"let's\s+say\s+|"
    r"assuming(?:\s+that|\s*,\s*|\s+)|"
    r"consider\s+a\s+scenario(?:\s+where|\s*,\s*|\s+))\s*"
)


def strip_hypothetical_prefix(text: str) -> tuple[str, bool]:
    """Strip leading hypothetical triggers ('suppose', 'imagine', 'hypothetically', etc.) from text."""
    s = text.strip()
    is_hypo = bool(_HYPOTHETICAL_PATTERN.search(s))
    while True:
        stripped = _LEADING_HYPOTHETICAL_RE.sub("", s).strip()
        if stripped == s:
            break
        s = stripped
        is_hypo = True
    return s, is_hypo


def _normalize_open_subject(raw_subj: str, speaker_role: str = "user") -> str:
    s = raw_subj.strip()
    s = re.sub(r"(?i)^(?:and|but|so|also|then)\s+", "", s).strip()
    low = s.lower()
    if low in {"i", "we", "me", "us"}:
        return (
            "assistant"
            if speaker_role.strip().lower()
            in {"assistant", "agent", "bot", "ai", "model"}
            else "user"
        )
    if low.startswith(("my ", "our ")):
        return s[s.find(" ") + 1 :].strip()
    if low.startswith(("the ", "a ", "an ")):
        return s[s.find(" ") + 1 :].strip()
    return s


def _normalize_open_predicate(raw_pred: str) -> str:
    p = re.sub(r"\s+", " ", raw_pred.strip().lower())
    # Strip leading auxiliary if followed by a main verb/adjective phrase
    p = re.sub(r"^(?:am|is|are|was|were|have\s+been|has\s+been|had\s+been)\s+", "", p)
    p = re.sub(r"[^a-z0-9]+", "_", p).strip("_")
    p = re.sub(r"^no_longer_", "not_", p)
    p = re.sub(r"^worked_", "work_", p)
    p = {"liked": "like", "preferred": "prefer", "owned": "own", "spoke": "speak"}.get(p, p)
    return p or "relates_to"


def extract_open_domain_facts(
    text: str | Any,
    *,
    tenant_id: str = "default",
    user_id: str | None = None,
    branch: str = "main",
    evidence_ids: Sequence[str] | None = None,
    source_evidence_cids: Sequence[str] | None = None,
    evidence_cids: Sequence[str] | None = None,
    trust_tier: int = int(TrustTier.DIRECT_USER),
    access_policy: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    valid_from: datetime | None = None,
    evaluated_at: datetime | None = None,
    speaker_role: str = "user",
    reference_time: datetime | None = None,
    is_hypothetical: bool = False,
) -> OpenDomainFacts:
    """Induce structured Subject-Verb-Object assertions from open-domain conversational statements."""
    if not isinstance(text, str) and hasattr(text, "content"):
        ev_obj = text
        text = str(getattr(ev_obj, "content", "") or "")
        if tenant_id == "default" and getattr(ev_obj, "tenant_id", None):
            tenant_id = str(ev_obj.tenant_id)
        if not (source_evidence_cids or evidence_ids or evidence_cids) and getattr(
            ev_obj, "cid", None
        ):
            source_evidence_cids = [str(ev_obj.cid)]
        if created_at is None and getattr(ev_obj, "created_at", None):
            created_at = ev_obj.created_at
        if valid_from is None and getattr(ev_obj, "valid_from", None):
            valid_from = ev_obj.valid_from
        if access_policy is None and getattr(ev_obj, "access_policy", None):
            access_policy = dict(ev_obj.access_policy)

    cids = list(source_evidence_cids or evidence_ids or evidence_cids or [])
    base_valid_from = valid_from or evaluated_at or created_at or utc_now()
    ref_time = reference_time or evaluated_at or created_at or valid_from or utc_now()
    policy = dict(access_policy or {})

    assertions: list[Assertion] = []
    relations: list[Relation] = []
    seen: set[tuple[str, str, str]] = set()

    sentence_pairs = [(clause, clause) for clause in split_episodic_clauses(text)]

    for sentence, parent_sentence in sentence_pairs:
        if sentence.endswith("?"):
            continue
        cleaned_sent, sent_hypo1 = strip_hypothetical_prefix(sentence)
        cleaned_temporal = _strip_temporal_affixes(cleaned_sent)
        cleaned, sent_hypo2 = strip_hypothetical_prefix(cleaned_temporal)
        if not cleaned or len(cleaned.split()) < 3:
            continue
        first_word = cleaned.split()[0].lower().strip(",.;:!?")
        if first_word in _OPEN_DOMAIN_STOP_SUBJECTS:
            continue

        is_sent_hypo = (
            is_hypothetical
            or sent_hypo1
            or sent_hypo2
            or bool(_HYPOTHETICAL_PATTERN.search(sentence))
            or bool(_HYPOTHETICAL_PATTERN.search(parent_sentence))
        )

        epistemic_class = classify_epistemic_fact(sentence, speaker_role=speaker_role)
        occ_start, occ_end, precision = parse_relative_or_prose_date(
            sentence, reference_time=ref_time
        )
        if precision == "none":
            occ_start, occ_end, precision = parse_relative_or_prose_date(
                parent_sentence, reference_time=ref_time
            )

        qualifiers: dict[str, Any] = {
            "epistemic_class": epistemic_class,
            "speaker_role": speaker_role,
        }
        if is_sent_hypo:
            qualifiers["is_hypothetical"] = True
        if occ_start is not None and occ_end is not None and precision != "none":
            qualifiers["occurrence_start"] = IsoDateTime(occ_start)
            qualifiers["occurrence_end"] = IsoDateTime(occ_end)
            qualifiers["temporal_precision"] = precision

        matched_svo: tuple[str, str, str] | None = None
        m_owned = re.match(r"(?i)^(?:my|our)\s+([a-z][a-z ]{0,40}?)\s+(?:is|are|was|were)\s+(.+)$", cleaned)
        if m_owned:
            owned_object = m_owned.group(2).strip()
            negative = bool(re.match(r"(?i)^not\s+", owned_object))
            matched_svo = (
                _normalize_open_subject("I", speaker_role),
                ("not_" if negative else "") + _normalize_open_predicate(m_owned.group(1)),
                re.sub(r"(?i)^not\s+", "", owned_object),
            )
        m_identity = re.match(r"(?i)^(I|we)\s+(?:am|are|was|were)\s+((?:not\s+)?(?:a|an)\s+.+)$", cleaned)
        if m_identity:
            obj = m_identity.group(2)
            negative = bool(re.match(r"(?i)^not\s+", obj))
            obj = re.sub(r"(?i)^(?:not\s+)?(?:a|an)\s+", "", obj)
            matched_svo = (_normalize_open_subject(m_identity.group(1), speaker_role),
                           "not_is_a" if negative else "is_a", obj)

        # Pattern 1: Copula + adjective/participle + preposition
        # e.g., "I am allergic to shellfish", "The service is deployed on Kubernetes"
        m_cop_prep = re.match(
            r"^(?P<subj>I|We|i|we|(?:My|Our|The|A|An|my|our|the|a|an)\s+[A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9_.-]+){0,2}|[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3})\s+"
            r"(?:am|is|are|was|were)\s+(?P<pred>(?:not\s+)?[a-z]{3,}\s+(?:to|in|on|for|with|of|by|from|at|into))\s+"
            r"(?P<obj>[A-Za-z0-9$][^.!?]{0,120})$",
            cleaned,
        )
        if m_cop_prep and matched_svo is None:
            subj = _normalize_open_subject(m_cop_prep.group("subj"), speaker_role)
            pred = _normalize_open_predicate(m_cop_prep.group("pred"))
            obj = m_cop_prep.group("obj").strip().strip(",.;")
            if subj and pred and obj:
                matched_svo = (subj, pred, obj)

        # Pattern 2: Active SVO clause
        # e.g., "We deployed the payment service on Kubernetes", "Alice prefers dark mode", "The database uses PostgreSQL 16"
        if matched_svo is None:
            m_svo = re.match(
                r"^(?P<subj>I|We|i|we|(?:My|Our|The|A|An|my|our|the|a|an)\s+[A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9_.-]+){0,2}|[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3})\s+"
                r"(?P<pred>(?:(?:do|does|did|can|could|will|would|should|must|have|has|had)\s+(?:not\s+|never\s+)?)?"
                r"(?:(?:no\s+longer|never|not)\s+)?[a-z]{3,}(?:ed|es|s|ing)?(?:\s+(?:to|on|in|for|with|from|at|into|over))?)\s+"
                r"(?P<obj>[A-Za-z0-9$][^.!?]{0,120})$",
                cleaned,
            )
            if m_svo:
                raw_subj = m_svo.group("subj")
                raw_pred = m_svo.group("pred").strip()
                raw_obj = m_svo.group("obj").strip().strip(",.;")
                pred_first = re.sub(r"^(?:no\s+longer|never|not)\s+", "", raw_pred).split()[0].lower()
                if pred_first not in _OPEN_DOMAIN_STOP_SUBJECTS and raw_obj:
                    subj = _normalize_open_subject(raw_subj, speaker_role)
                    pred = _normalize_open_predicate(raw_pred)
                    matched_svo = (subj, pred, raw_obj)

        # Pattern 3: Simple copular statement ("X is Y")
        if matched_svo is None:
            m_cop = re.match(
                r"^(?P<subj>(?:My|Our|The|my|our|the)\s+[A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z0-9_.-]+){0,2}|[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3})\s+"
                r"(?P<pred>is|are|was|were)\s+"
                r"(?P<obj>[A-Za-z0-9$][^.!?]{0,120})$",
                cleaned,
            )
            if m_cop:
                subj = _normalize_open_subject(m_cop.group("subj"), speaker_role)
                pred = m_cop.group("pred").lower()
                obj = m_cop.group("obj").strip().strip(",.;")
                if subj and obj and subj.lower() not in _OPEN_DOMAIN_STOP_SUBJECTS:
                    matched_svo = (subj, pred, obj)

        if matched_svo is not None:
            subj, pred, obj = matched_svo
            key = (subj, pred, obj)
            if key not in seen:
                seen.add(key)
                a = Assertion(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    branch=branch,
                    subject=subj,
                    predicate=pred,
                    object=obj,
                    scope={"is_hypothetical": True} if is_sent_hypo else {},
                    confidence=0.85,
                    valid_from=base_valid_from,
                    source_evidence_cids=cids,
                    trust_tier=trust_tier,
                    access_policy=policy,
                    status="active",
                    qualifiers=qualifiers,
                )
                assertions.append(a)
                relations.append(
                    Relation(
                        tenant_id=tenant_id,
                        source=subj,
                        predicate=pred,
                        target=obj,
                        branch=branch,
                        confidence=0.85,
                        valid_from=base_valid_from,
                        source_evidence_cids=cids,
                        access_policy=policy,
                    )
                )

                newest_relations = [relations[-1]]
                _apply_historical_state_window(sentence, [a], newest_relations, ref_time)
                if not newest_relations:
                    relations.pop()

    return OpenDomainFacts(assertions=assertions, relations=relations)


def extract_episodic_facts(
    text: str | Any,
    *,
    tenant_id: str = "default",
    user_id: str | None = None,
    branch: str = "main",
    evidence_ids: Sequence[str] | None = None,
    source_evidence_cids: Sequence[str] | None = None,
    evidence_cids: Sequence[str] | None = None,
    trust_tier: int = int(TrustTier.DIRECT_USER),
    access_policy: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    valid_from: datetime | None = None,
    evaluated_at: datetime | None = None,
    speaker_role: str = "user",
    reference_time: datetime | None = None,
) -> ExtractedFacts:
    """Extract deterministic assertions and relations across the 4 fact families + open-domain SVO.

    Fact Families:
    1. Residence: "I moved to Halden", "I live in Brookvale", "My apartment is in Eastgate"
       -> Assertion(subject="user", predicate="residence", object=loc) & Relation(source="user", predicate="lives_in", target=loc)
    2. Family/Pets: "My daughter Mira", "My dog Pepper is a Beagle"
       -> Assertion(subject="user", predicate="has_family"/"has_pet", object=name) & Relation(...)
    3. Expenses/Counts: "I spent $70 on garden tools", "I bought 3 stools"
       -> Assertion(subject="user", predicate="expense", object="$70 on garden tools") & Relation(...)
    4. Milestones: "In 2021, I graduated from Northfield College", "In 2019, I started working at Acme"
       -> Assertion(subject="user", predicate="education"/"milestone", object=institution, valid_from=...) & Relation(...)
    5. Open-Domain SVO: "I am allergic to shellfish", "We deployed the payment service on Kubernetes", etc.
    """
    if not isinstance(text, str) and hasattr(text, "content"):
        ev_obj = text
        text = str(getattr(ev_obj, "content", "") or "")
        if tenant_id == "default" and getattr(ev_obj, "tenant_id", None):
            tenant_id = str(ev_obj.tenant_id)
        if not (source_evidence_cids or evidence_ids or evidence_cids) and getattr(
            ev_obj, "cid", None
        ):
            source_evidence_cids = [str(ev_obj.cid)]
        if created_at is None and getattr(ev_obj, "created_at", None):
            created_at = ev_obj.created_at
        if valid_from is None and getattr(ev_obj, "valid_from", None):
            valid_from = ev_obj.valid_from
        if access_policy is None and getattr(ev_obj, "access_policy", None):
            access_policy = dict(ev_obj.access_policy)
        if speaker_role == "user" and getattr(ev_obj, "actor", None):
            actor_str = str(ev_obj.actor).lower()
            if actor_str in {"agent", "assistant", "bot", "ai", "model"}:
                speaker_role = "assistant"
        meta = getattr(ev_obj, "metadata", None)
        if isinstance(meta, dict) and meta.get("speaker_role"):
            speaker_role = str(meta["speaker_role"])

    cids = list(source_evidence_cids or evidence_ids or evidence_cids or [])
    base_valid_from = valid_from or evaluated_at or created_at or utc_now()
    ref_time = reference_time or evaluated_at or created_at or valid_from or utc_now()
    policy = dict(access_policy or {})

    assertions: list[Assertion] = []
    relations: list[Relation] = []

    seen_assertions: set[tuple[str, str, str]] = set()
    seen_relations: set[tuple[str, str, str]] = set()
    current_sentence_qualifiers: dict[str, Any] = {
        "epistemic_class": classify_epistemic_fact(text, speaker_role=speaker_role),
        "speaker_role": speaker_role,
    }

    def add_assertion(
        subject: str,
        predicate: str,
        obj: str,
        *,
        vf: datetime | None = None,
        scope: dict[str, Any] | None = None,
        confidence: float = 0.9,
        qualifiers: dict[str, Any] | None = None,
    ) -> None:
        key = (subject, predicate, obj)
        if key in seen_assertions:
            return
        seen_assertions.add(key)
        q = dict(current_sentence_qualifiers)
        if qualifiers:
            q.update(qualifiers)
        scope_copy = dict(scope or {})
        if q.get("is_hypothetical"):
            scope_copy["is_hypothetical"] = True
        # shortcut: only a date window still open at statement time falls back to the statement time; a closed
        # window that contains the older statement still loses, upgrade in the engine upsert if that shows up.
        if vf is not None and occ_start is not None and occ_end is not None and occ_start <= vf <= parse_dt(ref_time) <= occ_end:
            vf = None
        a = Assertion(
            tenant_id=tenant_id,
            user_id=user_id,
            branch=branch,
            subject=subject,
            predicate=predicate,
            object=obj,
            scope=scope_copy,
            confidence=confidence,
            valid_from=vf or base_valid_from,
            source_evidence_cids=cids,
            trust_tier=trust_tier,
            access_policy=policy,
            status="active",
            qualifiers=q,
        )
        assertions.append(a)

    def add_relation(
        source: str,
        predicate: str,
        target: str,
        *,
        vf: datetime | None = None,
        confidence: float = 0.9,
    ) -> None:
        key = (source, predicate, target)
        if key in seen_relations:
            return
        seen_relations.add(key)
        if vf is not None and occ_start is not None and occ_end is not None and occ_start <= vf <= parse_dt(ref_time) <= occ_end:
            vf = None  # same open-window rule as add_assertion
        r = Relation(
            tenant_id=tenant_id,
            source=source,
            predicate=predicate,
            target=target,
            branch=branch,
            confidence=confidence,
            valid_from=vf or base_valid_from,
            source_evidence_cids=cids,
            access_policy=policy,
        )
        relations.append(r)

    # Split text into sentence/clause candidates while preserving context
    sentences = split_episodic_clauses(text)
    if not sentences:
        sentences = [text.strip()]

    for sentence in sentences:
        s_clean = sentence.strip()
        if not s_clean:
            continue

        sentence_speaker_role = (speaker_role or "user").strip().lower()
        m_prefix = re.match(
            r"(?i)^(assistant|agent|bot|ai|model|user|human|observer|observation|sensor|monitor)\s*:\s*(.*)$",
            s_clean,
        )
        if m_prefix:
            prefix_role = m_prefix.group(1).lower()
            s_clean = m_prefix.group(2).strip()
            if prefix_role in {"assistant", "agent", "bot", "ai", "model"}:
                sentence_speaker_role = "assistant"
            elif prefix_role in {"user", "human"}:
                sentence_speaker_role = "user"
            elif prefix_role in {"observer", "observation", "sensor", "monitor"}:
                sentence_speaker_role = "observation"

        is_assistant = sentence_speaker_role in {
            "assistant",
            "agent",
            "bot",
            "ai",
            "model",
        }
        effective_subject = "assistant" if is_assistant else "user"

        # Hypothetical check: assistant hypothetical statements must NEVER be extracted as facts
        is_hypo = bool(_HYPOTHETICAL_PATTERN.search(s_clean))
        if is_assistant and is_hypo:
            continue

        # Check explicit date and relative/prose occurrence interval in this sentence
        sentence_date = parse_explicit_date(s_clean)
        occ_start, occ_end, precision = parse_relative_or_prose_date(
            s_clean, reference_time=ref_time
        )
        effective_class = (
            "agent_experience"
            if is_assistant
            else classify_epistemic_fact(s_clean, speaker_role=sentence_speaker_role)
        )
        current_sentence_qualifiers = {
            "epistemic_class": effective_class,
            "speaker_role": sentence_speaker_role,
        }
        if is_hypo:
            current_sentence_qualifiers["is_hypothetical"] = True
        if occ_start is not None and occ_end is not None and precision != "none":
            current_sentence_qualifiers["occurrence_start"] = IsoDateTime(occ_start)
            current_sentence_qualifiers["occurrence_end"] = IsoDateTime(occ_end)
            current_sentence_qualifiers["temporal_precision"] = precision
        before_count = len(assertions)
        before_relation_count = len(relations)

        # ----------------------------------------------------------------------
        # 1. Residence & Location
        # ----------------------------------------------------------------------
        # Moves: "I moved to Halden in 2024", "In 2024, I moved to Halden", "I moved from Brookvale to Halden"
        m_move = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+moved\s+(?:from\s+[A-Za-z0-9\s'.-]+?\s+to\s+|to\s+)([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            s_clean,
        )
        if m_move:
            loc = _clean_location(m_move.group(2))
            dt = (
                parse_explicit_date(m_move.group(1))
                or parse_explicit_date(m_move.group(3))
                or sentence_date
            )
            if (
                loc
                and len(loc) > 1
                and not loc.lower().startswith(("a ", "an ", "the ", "my "))
            ):
                add_assertion(effective_subject, "residence", loc, vf=dt, scope={})
                add_relation(effective_subject, "lives_in", loc, vf=dt)
                add_relation(effective_subject, "residence", loc, vf=dt)

        m_negative_residence = re.search(
            r"(?i)\b(?:I|we)\s+(?:(?:do|did)\s+not|no\s+longer|never)\s+"
            r"(?:live|reside)\s+in\s+([^.!?;]+)", s_clean,
        )
        if m_negative_residence:
            loc = _clean_location(_strip_temporal_affixes(m_negative_residence.group(1)))
            if loc:
                add_assertion(effective_subject, "not_residence", loc)
                add_relation(effective_subject, "not_residence", loc)

        # Current residence: "I live in Brookvale", "I currently live in Brookvale", "I reside in Brookvale"
        m_live = re.search(
            r"(?i)(?:(?:in|since)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+(?:currently\s+|used\s+to\s+)?(?:live|reside|lived|resided)\s+in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|since)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            s_clean,
        )
        if m_live:
            loc = _clean_location(m_live.group(2))
            dt = (
                parse_explicit_date(m_live.group(1))
                or parse_explicit_date(m_live.group(3))
                or sentence_date
            )
            if (
                loc
                and len(loc) > 1
                and not loc.lower().startswith(("a ", "an ", "the ", "my "))
            ):
                add_assertion(effective_subject, "residence", loc, vf=dt, scope={})
                add_relation(effective_subject, "lives_in", loc, vf=dt)
                add_relation(effective_subject, "residence", loc, vf=dt)

        # "I am living in Eastgate", "I'm currently living in Eastgate"
        m_living = re.search(
            r"(?i)(?:I\s+am|I'm)\s+(?:currently\s+)?living\s+in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|since)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            s_clean,
        )
        if m_living:
            loc = _clean_location(m_living.group(1))
            dt = parse_explicit_date(m_living.group(2)) or sentence_date
            if (
                loc
                and len(loc) > 1
                and not loc.lower().startswith(("a ", "an ", "the ", "my "))
            ):
                add_assertion(effective_subject, "residence", loc, vf=dt, scope={})
                add_relation(effective_subject, "lives_in", loc, vf=dt)
                add_relation(effective_subject, "residence", loc, vf=dt)

        # "My apartment is in Eastgate", "My flat is in Eastgate", "My house in Halden"
        m_apt = re.search(
            r"(?i)my\s+(?:current\s+)?(?:apartment|house|home|condo|place)\s+(?:is\s+)?in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:[.,;]|\s+with|\s+and|\s*$)",
            s_clean,
        )
        if m_apt:
            loc = _clean_location(m_apt.group(1))
            if (
                loc
                and len(loc) > 1
                and not loc.lower().startswith(("a ", "an ", "the ", "my "))
            ):
                add_assertion(
                    effective_subject, "residence", loc, vf=sentence_date, scope={}
                )
                add_relation(effective_subject, "lives_in", loc, vf=sentence_date)
                add_relation(effective_subject, "residence", loc, vf=sentence_date)

        # "I bought a house in Halden", "I bought an apartment in Brookvale"
        m_bought_home = re.search(
            r"(?i)(?:I|we)\s+bought\s+(?:an?\s+)?(?:apartment|house|home|condo)\s+in\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:[.,;]|\s+with|\s+and|\s*$)",
            s_clean,
        )
        if m_bought_home:
            loc = _clean_location(m_bought_home.group(1))
            if (
                loc
                and len(loc) > 1
                and not loc.lower().startswith(("a ", "an ", "the ", "my "))
            ):
                add_assertion(
                    effective_subject, "residence", loc, vf=sentence_date, scope={}
                )
                add_relation(effective_subject, "lives_in", loc, vf=sentence_date)
                add_relation(effective_subject, "residence", loc, vf=sentence_date)

        # ----------------------------------------------------------------------
        # 2. Family & Pets
        # ----------------------------------------------------------------------
        # Family: "My daughter Mira", "My son Lucas", "My wife Ines", "My husband Arlo"
        for m_fam in re.finditer(
            r"(?i)\bmy\s+(daughter|son|wife|husband|mother|father|mom|dad|brother|sister)\s+([A-Z][a-z]+)\b",
            s_clean,
        ):
            role = m_fam.group(1).lower()
            name = m_fam.group(2)
            add_assertion(
                effective_subject,
                "has_family",
                name,
                vf=sentence_date,
                scope={"relation": role},
            )
            add_relation(effective_subject, "has_family", name, vf=sentence_date)
            add_relation(effective_subject, f"has_{role}", name, vf=sentence_date)

        # Family named: "I have a daughter named Mira", "I have a son named Lucas"
        for m_fam_named in re.finditer(
            r"(?i)(?:I\s+have|I've\s+got)\s+a\s+(daughter|son|wife|husband|brother|sister)\s+(?:named|called)\s+([A-Z][a-z]+)\b",
            s_clean,
        ):
            role = m_fam_named.group(1).lower()
            name = m_fam_named.group(2)
            add_assertion(
                effective_subject,
                "has_family",
                name,
                vf=sentence_date,
                scope={"relation": role},
            )
            add_relation(effective_subject, "has_family", name, vf=sentence_date)
            add_relation(effective_subject, f"has_{role}", name, vf=sentence_date)

        # Pets: "My dog Pepper", "My cat Miso", "My pet dog Pepper", "My pet rabbit Coco"
        for m_pet in re.finditer(
            r"(?i)\bmy\s+(?:pet\s+)?(dog|cat|hamster|rabbit|parrot|puppy|kitten)\s+([A-Z][a-z]+)\b",
            s_clean,
        ):
            species = m_pet.group(1).lower()
            name = m_pet.group(2)
            add_assertion(
                effective_subject,
                "has_pet",
                name,
                vf=sentence_date,
                scope={"species": species},
            )
            add_relation(effective_subject, "has_pet", name, vf=sentence_date)
            add_relation(effective_subject, f"has_{species}", name, vf=sentence_date)
            add_relation(name, "is_a", species, vf=sentence_date)

        # Pets named: "I have a dog named Pepper", "I have a pet cat named Miso"
        for m_pet_named in re.finditer(
            r"(?i)(?:I\s+have|I've\s+got)\s+an?\s+(?:pet\s+)?(dog|cat|hamster|rabbit|parrot)\s+(?:named|called)\s+([A-Z][a-z]+)\b",
            s_clean,
        ):
            species = m_pet_named.group(1).lower()
            name = m_pet_named.group(2)
            add_assertion(
                effective_subject,
                "has_pet",
                name,
                vf=sentence_date,
                scope={"species": species},
            )
            add_relation(effective_subject, "has_pet", name, vf=sentence_date)
            add_relation(effective_subject, f"has_{species}", name, vf=sentence_date)
            add_relation(name, "is_a", species, vf=sentence_date)

        # Pet breed / attribute: "My dog Pepper is a Beagle", "Pepper is a Beagle"
        m_breed = re.search(
            r"(?i)\b([A-Z][a-z]+)\s+is\s+an?\s+([A-Z][A-Za-z\s]+?)(?:[.,;]|\s*)$",
            s_clean,
        )
        if m_breed:
            pet_name = m_breed.group(1)
            breed_str = m_breed.group(2).strip().strip(",.;")
            # If pet_name is already known or context suggests pet
            if any(
                a.predicate == "has_pet" and a.object == pet_name for a in assertions
            ):
                add_assertion(pet_name, "breed", breed_str, vf=sentence_date)
                add_relation(pet_name, "breed", breed_str, vf=sentence_date)

        # ----------------------------------------------------------------------
        # 3. Expenses & Counts
        # ----------------------------------------------------------------------
        # Expenses: "I spent $450 on bike repairs", "I spent 120 dollars on groceries"
        m_spent = re.search(
            r"(?i)(?:(?:I|we)\s+spent|\$)\s*(\$?\d+(?:,\d+)*(?:\.\d+)?)\s*(?:dollars?)?\s+(?:on|for)\s+([a-zA-Z0-9\s'-]+?)(?:[.,;]|\s+in\s+\d{4}|\s*$)",
            s_clean,
        )
        if m_spent:
            amt_raw = m_spent.group(1).replace("$", "").replace(",", "")
            item_raw = m_spent.group(2).strip().strip(",.;")
            try:
                amt_float = float(amt_raw)
                obj_str = f"${int(amt_float) if amt_float.is_integer() else amt_float} on {item_raw}"
                add_assertion(
                    effective_subject,
                    "expense",
                    obj_str,
                    vf=sentence_date,
                    scope={"amount": amt_float, "item": item_raw},
                )
                add_relation(effective_subject, "expense", item_raw, vf=sentence_date)
                add_relation(effective_subject, "spent_on", item_raw, vf=sentence_date)
            except ValueError:
                pass

        # "I paid $80 for dinner"
        m_paid = re.search(
            r"(?i)(?:I|we)\s+paid\s+\$?(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:dollars?)?\s+(?:for|on)\s+([a-zA-Z0-9\s'-]+?)(?:[.,;]|\s*$)",
            s_clean,
        )
        if m_paid:
            amt_raw = m_paid.group(1).replace(",", "")
            item_raw = m_paid.group(2).strip().strip(",.;")
            try:
                amt_float = float(amt_raw)
                obj_str = f"${int(amt_float) if amt_float.is_integer() else amt_float} on {item_raw}"
                add_assertion(
                    effective_subject,
                    "expense",
                    obj_str,
                    vf=sentence_date,
                    scope={"amount": amt_float, "item": item_raw},
                )
                add_relation(effective_subject, "expense", item_raw, vf=sentence_date)
            except ValueError:
                pass

        # Counts: "I bought 3 lamps", "I have 5 bicycles", "I own two cars"
        for m_count in re.finditer(
            r"(?i)\b(?:I|we)\s+(?:bought|purchased|have|own|got)\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+([a-zA-Z0-9'-]+(?:\s+(?!and\b|or\b|with\b|in\s+\d{4}\b)[a-zA-Z0-9'-]+)*)",
            s_clean,
        ):
            num_raw = m_count.group(1).lower()
            item_raw = m_count.group(2).strip().strip(",.;")
            count_val = (
                int(num_raw) if num_raw.isdigit() else WORD_TO_NUM.get(num_raw, 1)
            )
            # Avoid matching family or pets as generic counts (e.g. "I have a daughter" or "I have 2 dogs")
            if not any(
                w in item_raw.lower()
                for w in (
                    "dog",
                    "cat",
                    "daughter",
                    "son",
                    "sister",
                    "brother",
                    "wife",
                    "husband",
                    "pet",
                )
            ):
                obj_str = f"{count_val} {item_raw}"
                add_assertion(
                    effective_subject,
                    "count",
                    obj_str,
                    vf=sentence_date,
                    scope={"count": count_val, "item": item_raw},
                )
                add_relation(effective_subject, "owns", item_raw, vf=sentence_date)

        # ----------------------------------------------------------------------
        # 4. Dated Milestones
        # ----------------------------------------------------------------------
        # Education: "In 2021, I graduated from Northfield College", "I graduated from MIT in 2018"
        m_grad = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+graduated\s+from\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s+with|\s+and|\s*$)",
            s_clean,
        )
        if m_grad:
            inst = m_grad.group(2).strip().strip(",.;")
            inst = re.sub(
                r"(?i)\s+(?:in\s+\d{4}|with\s+.*|and\s+.*)$", "", inst
            ).strip()
            dt = (
                parse_explicit_date(m_grad.group(1))
                or parse_explicit_date(m_grad.group(3))
                or sentence_date
            )
            if inst and len(inst) > 1:
                # Add both education and milestone assertions/relations for high recall
                add_assertion(
                    effective_subject,
                    "education",
                    inst,
                    vf=dt,
                    scope={"milestone": "graduation"},
                )
                add_assertion(
                    effective_subject,
                    "milestone",
                    f"graduated from {inst}",
                    vf=dt,
                    scope={"milestone": "graduation"},
                )
                add_relation(effective_subject, "graduated_from", inst, vf=dt)
                add_relation(effective_subject, "education", inst, vf=dt)

        # Degrees: "I received my degree from Northfield College in 2020", "I got my PhD from Lakeside University in 2017"
        m_degree = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+(?:received|earned|got|completed)\s+(?:my|a|an)\s+(?:degree|bachelor'?s?|master'?s?|phd|doctorate)\s+from\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s*$)",
            s_clean,
        )
        if m_degree:
            inst = m_degree.group(2).strip().strip(",.;")
            inst = re.sub(
                r"(?i)\s+(?:in\s+\d{4}|with\s+.*|and\s+.*)$", "", inst
            ).strip()
            dt = (
                parse_explicit_date(m_degree.group(1))
                or parse_explicit_date(m_degree.group(3))
                or sentence_date
            )
            if inst and len(inst) > 1:
                add_assertion(
                    effective_subject,
                    "education",
                    inst,
                    vf=dt,
                    scope={"milestone": "degree"},
                )
                add_assertion(
                    effective_subject,
                    "milestone",
                    f"degree from {inst}",
                    vf=dt,
                    scope={"milestone": "degree"},
                )
                add_relation(effective_subject, "graduated_from", inst, vf=dt)
                add_relation(effective_subject, "education", inst, vf=dt)

        # Career milestones: "In 2019, I started working at Acme", "In 2022, I joined Globex"
        m_career = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+(?:started\s+(?:working\s+at|at|my\s+job\s+at)|joined)\s+([A-Z][A-Za-z0-9\s'.-]+?)(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s*$)",
            s_clean,
        )
        if m_career:
            company = m_career.group(2).strip().strip(",.;")
            company = re.sub(
                r"(?i)\s+(?:in\s+\d{4}|as\s+.*|with\s+.*|and\s+.*)$", "", company
            ).strip()
            dt = (
                parse_explicit_date(m_career.group(1))
                or parse_explicit_date(m_career.group(3))
                or sentence_date
            )
            if company and len(company) > 1:
                add_assertion(
                    effective_subject,
                    "milestone",
                    f"started working at {company}",
                    vf=dt,
                    scope={"milestone": "employment"},
                )
                add_relation(effective_subject, "works_at", company, vf=dt)
                add_relation(effective_subject, "employed_by", company, vf=dt)

        # Marriage: "In 2015, I got married", "On October 12, 2015, I got married to Ines"
        m_married = re.search(
            r"(?i)(?:(?:in|on)\s+([A-Za-z0-9, ]+?),?\s+)?(?:I|we)\s+got\s+married(?:\s+to\s+([A-Z][a-z]+))?(?:\s+(?:in|on)\s+([A-Za-z0-9, ]+?))?(?:[.,;]|\s*$)",
            s_clean,
        )
        if m_married:
            dt = (
                parse_explicit_date(m_married.group(1))
                or parse_explicit_date(m_married.group(3))
                or sentence_date
            )
            spouse = m_married.group(2)
            obj_str = f"got married to {spouse}" if spouse else "got married"
            add_assertion(
                effective_subject,
                "milestone",
                obj_str,
                vf=dt,
                scope={"milestone": "marriage"},
            )
            if spouse:
                add_assertion(
                    effective_subject,
                    "has_family",
                    spouse,
                    vf=dt,
                    scope={"relation": "spouse"},
                )
                add_relation(effective_subject, "married_to", spouse, vf=dt)
                add_relation(effective_subject, "has_family", spouse, vf=dt)

        # ----------------------------------------------------------------------
        # 5. Open-Domain Conversational SVO Induction (when no core family matched)
        # ----------------------------------------------------------------------
        if len(assertions) == before_count and not (is_assistant and is_hypo):
            clean_for_open, open_hypo = strip_hypothetical_prefix(s_clean)
            effective_is_hypo = is_hypo or open_hypo
            open_facts = extract_open_domain_facts(
                clean_for_open,
                tenant_id=tenant_id,
                user_id=user_id,
                branch=branch,
                source_evidence_cids=cids,
                trust_tier=trust_tier,
                access_policy=policy,
                created_at=created_at,
                valid_from=valid_from,
                evaluated_at=evaluated_at,
                speaker_role=sentence_speaker_role,
                reference_time=ref_time,
                is_hypothetical=effective_is_hypo,
            )
            for oa in open_facts.assertions:
                if effective_is_hypo:
                    oa.qualifiers["is_hypothetical"] = True
                    oa.scope["is_hypothetical"] = True
                key = (oa.subject, oa.predicate, oa.object)
                if key not in seen_assertions:
                    seen_assertions.add(key)
                    assertions.append(oa)
            for orel in open_facts.relations:
                rkey = (orel.source, orel.predicate, orel.target)
                if rkey not in seen_relations:
                    seen_relations.add(rkey)
                    relations.append(orel)

        new_assertions = assertions[before_count:]
        new_relations = relations[before_relation_count:]
        _apply_historical_state_window(s_clean, new_assertions, new_relations, ref_time)
        relations[before_relation_count:] = new_relations

    return ExtractedFacts(assertions=assertions, relations=relations)
