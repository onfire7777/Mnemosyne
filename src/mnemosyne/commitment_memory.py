"""Source-backed commitments with explicit date precision and lifecycle.

Intentions remain data-only prospective records. A due/fired intention is never
evidence that its real-world task was completed. Cancellation and completion
require a later, matching user statement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mnemosyne.models import Assertion, parse_dt
from mnemosyne.semantic_memory import semantic_metadata, source_spans

_WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
_DAY_WORD = r"(?:the day after tomorrow|tomorrow|today|in \d+ days?|(?:next|this|on|coming) (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\d{4}-\d{2}-\d{2})"
_TEMPORAL = re.compile(r"(?:\b(?:by|until|to|on)\s+)?\b" + _DAY_WORD + r"\b(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?", re.I)
_UNCERTAIN = re.compile(r"\b(?:if|maybe|perhaps|might|could|would|may|probably|think|guess|suppose|imagine)\b", re.I)


def resolve_commitment_time(text: str, observed_at: datetime, timezone: str | None = None) -> dict:
    """Resolve a date/window, preserving uncertainty instead of inventing time."""
    match = _TEMPORAL.search(text)
    result = {"wording": match[0] if match else "", "status": "unknown",
              "precision": "unknown", "timezone": timezone, "observed_at": observed_at.isoformat()}
    if match is None:
        return result
    try:
        zone = ZoneInfo(timezone) if timezone else None
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        result.update(status="ambiguous", reason="unknown_timezone")
        return result
    wording = match[0].lower()
    explicit = re.search(r"\d{4}-\d{2}-\d{2}", wording)
    day = None
    if explicit:
        try:
            day = date.fromisoformat(explicit[0])
        except ValueError:
            result.update(status="ambiguous", reason="invalid_date")
            return result
    elif zone is None:
        result.update(status="ambiguous", reason="timezone_required")
        return result
    else:
        today = observed_at.astimezone(zone).date()
        if "day after tomorrow" in wording:
            day = today + timedelta(days=2)
        elif "tomorrow" in wording:
            day = today + timedelta(days=1)
        elif "today" in wording:
            day = today
        elif offset := re.search(r"in (\d+) days?", wording):
            if int(offset[1]) > 36525:
                result.update(status="ambiguous", reason="date_out_of_range")
                return result
            day = today + timedelta(days=int(offset[1]))
        else:
            weekday = next((i for i, name in enumerate(_WEEKDAYS) if name in wording), None)
            if weekday is not None:
                next_day = today + timedelta(days=(weekday - today.weekday()) % 7)
                if next_day == today and not re.search(r"\bthis\b", wording):
                    next_day += timedelta(days=7)
                # "Next Friday" can mean this coming Friday or the following
                # week. Bare weekdays also lack an explicit week reference.
                if re.search(r"\b(?:this|coming)\b", wording):
                    day = next_day
                else:
                    result.update(status="ambiguous", precision="day", reason="weekday_reference_ambiguous",
                                  candidate_dates=[next_day.isoformat(), (next_day + timedelta(days=7)).isoformat()])
                    return result
    if day is None:
        return result
    result.update(date=day.isoformat(), precision="day")
    if zone is None:
        result.update(status="ambiguous", reason="timezone_required")
        return result
    start = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    clock = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", wording)
    if clock:
        hour, minute = int(clock[1]), int(clock[2] or 0)
        if minute > 59 or hour > (12 if clock[3] else 23) or clock[3] and hour == 0:
            result.update(status="ambiguous", reason="invalid_time")
            return result
        if not clock[3] and clock[2] is None and hour <= 12:
            result.update(status="ambiguous", reason="meridiem_required")
            return result
        if clock[3]:
            hour = hour % 12 + (12 if clock[3] == "pm" else 0)
        start = datetime.combine(day, time(hour, minute), zone)
        if start.replace(fold=0).utcoffset() != start.replace(fold=1).utcoffset() or start.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != start.replace(tzinfo=None):
            result.update(status="ambiguous", reason="daylight_saving_transition")
            return result
        end = start
        result["precision"] = "instant"
    result.update(status="resolved", start=start.astimezone(UTC).isoformat(), end=end.astimezone(UTC).isoformat())
    return result


def _action_key(action: str) -> str:
    text = action.casefold()
    text = re.sub(r"\b(?:my|our|the|a|an|with|to)\b", " ", text)
    for word, normalized in {"meeting": "meet", "met": "meet", "calling": "call", "called": "call", "launching": "launch", "launched": "launch"}.items():
        text = re.sub(r"\b" + word + r"\b", normalized, text)
    return " ".join(re.findall(r"[\w-]+", text))


def commitment_changes(source, clauses: list[str], timezone: str | None = None) -> list[dict]:
    changes = []
    for span in source_spans(source, clauses):
        text = span.quote.strip().rstrip(".! ")
        if _UNCERTAIN.search(text):
            continue
        kind, action = "pending", None
        if m := re.fullmatch(r"(?:I|We)\s+(?:cancel(?:led|ed)?|called off|no longer plan to)\s+(.+)", text, re.I):
            kind, action = "cancelled", m[1]
        elif m := re.fullmatch(r"(?:I|We)\s+(?:completed|finished)\s+(.+)", text, re.I):
            kind, action = "completed", m[1]
        elif m := re.fullmatch(r"(?:I|We)\s+(met|called|launched)\s+(.+)", text, re.I):
            kind, action = "completed", m[1] + " " + m[2]
        elif m := re.fullmatch(r"(?:I|We)\s+(?:(?:decided to|will)\s+)?(?:reschedul(?:e|ed)|postpon(?:e|ed)|mov(?:e|ed))\s+(.+)", text, re.I):
            kind, action = "rescheduled", m[1]
        elif m := re.fullmatch(r"(?:I|We)\s+(?:(?:plan|intend|committed|commit|promised|promise|decided)\s+to|will|am going to|are going to)\s+(.+)", text, re.I):
            action = m[1]
        elif m := re.fullmatch(r"(?:Remind me to)\s+(.+)", text, re.I):
            action = m[1]
        elif m := re.fullmatch(r"(?:(?:I|We)\s+)?((?:meet|call|visit|pay|submit|finish|launch)\s+.+)", text, re.I):
            if _TEMPORAL.search(m[1]):
                action = m[1]
        elif m := re.fullmatch(r"(?:I|We)\s+have\s+(?:a\s+)?((?:meeting|call|appointment)\s+.+)", text, re.I):
            if _TEMPORAL.search(m[1]):
                action = m[1]
        if action is None:
            continue
        temporal_matches = list(_TEMPORAL.finditer(action))
        temporal_text = action
        previous_temporal = None
        if kind == "rescheduled" and len(temporal_matches) > 1:
            # "from tomorrow to Friday" describes two dates; never schedule
            # the replacement on the old date simply because it came first.
            previous_temporal = resolve_commitment_time(temporal_matches[0][0], source.created_at, timezone)
            temporal_text = temporal_matches[-1][0]
        temporal = resolve_commitment_time(temporal_text, source.created_at, timezone)
        if kind != "rescheduled" and len(temporal_matches) > 1:
            temporal.update(status="ambiguous", reason="multiple_event_dates")
        action = _TEMPORAL.sub("", action).strip(" ,.;")
        action = re.sub(r"\s+from\s*$", "", action).strip()
        # A statement of an undated decision is retained by the semantic fact
        # path. It becomes prospective memory only for an explicit future act.
        if kind == "pending" and not temporal["wording"] and re.match(r"(?:I|We) decided to\b", text, re.I):
            continue
        if not action or len(action) > 500:
            continue
        changes.append({"state": kind, "action": action, "action_key": _action_key(action), "span": span,
                        "event_time": temporal, "previous_event_time": previous_temporal})
    return changes


def commitment_display_status(intention, *, now: datetime) -> str:
    """Distinguish a reminder firing/overdue date from actual task completion."""
    state = intention.action.get("commitment_state")
    if state in {"completed", "cancelled", "rescheduled"}:
        return state
    if intention.status == "cancelled":
        return "cancelled"
    temporal = intention.action.get("event_time", {})
    end = parse_dt(temporal.get("end")) or intention.due_at
    return "overdue" if now >= end else "pending"


def project_commitment_memory(engine, source, policy: dict, clauses: list[str], *, timezone=None, agent_id="codex", session_id=None) -> dict:
    """Project state through ordinary assertion/intention writers, idempotently.

    A reschedule creates an immutable, newly sourced intention and cancels its
    predecessor. This preserves custody without mutating an old intention's
    source set or treating a reminder's fired status as real task completion.
    """
    from mnemosyne.engine import Intention, intention_revision
    report = {"assertion_ids": [], "intention_ids": [], "created_count": 0, "unresolved": []}
    if source.branch != "main":
        # Prospective storage currently has no branch column. Do not leak
        # speculative branch commitments into the live main schedule.
        return report
    timezone = timezone or source.metadata.get("timezone") or source.metadata.get("time_zone")
    changes = commitment_changes(source, clauses, timezone)

    def cancel_predecessor(previous, identifier):
        if previous is None:
            return
        old_id = previous.get("calibration", {}).get("intention_id")
        old = next((item for item in engine.list_intentions(source.tenant_id) if item.intention_id == old_id), None)
        if old is not None and old.status == "scheduled":
            engine.cancel_intention(source.tenant_id, old.intention_id, cancelled_by=source.user_id,
                                    session_id=old.session_id or session_id or "memory-projection",
                                    expected_revision=intention_revision(old),
                                    idempotency_key="commitment:" + identifier)

    for change in changes:
        span = change["span"]
        identifier = str(uuid5(NAMESPACE_URL, json.dumps(["commitment-state-v1", source.tenant_id, source.user_id, source.cid, span.start, change["state"]])))
        snapshot = engine.export_tenant(source.tenant_id)
        prior = next((row for row in snapshot["assertions"] if row["id"] == identifier), None)
        if prior is not None:
            previous_id = prior.get("calibration", {}).get("previous_assertion_id")
            previous = next((row for row in snapshot["assertions"] if row["id"] == previous_id), None)
            # A retry completes an interrupted state-write/cancel sequence.
            cancel_predecessor(previous, identifier)
            report["assertion_ids"].append(identifier)
            if prior.get("calibration", {}).get("intention_id"):
                report["intention_ids"].append(prior["calibration"]["intention_id"])
            continue
        candidates = [row for row in snapshot["assertions"] if row.get("user_id") == source.user_id
                      and row.get("branch", "main") == "main" and row["status"] == "active"
                      and row["predicate"] == "commitment_state"
                      and row.get("calibration", {}).get("commitment_state") == "pending"
                      and row.get("calibration", {}).get("action_key") == change["action_key"]]
        is_change = change["state"] != "pending"
        selector = change["previous_event_time"] if change["state"] == "rescheduled" else change["event_time"]
        if is_change and len(candidates) > 1 and selector and selector.get("date"):
            candidates = [row for row in candidates if row["calibration"].get("event_time", {}).get("date") == selector["date"]]
        if is_change and len(candidates) != 1:
            report["unresolved"].append({"source_span": span.to_dict(), "reason": "ambiguous_commitment_target" if candidates else "missing_commitment_target", "action": change["action"]})
            continue
        previous = candidates[0] if is_change else None
        commitment_id = previous["scope"]["commitment_id"] if previous else hashlib.sha256(identifier.encode()).hexdigest()[:24]
        state = "pending" if change["state"] == "rescheduled" else change["state"]
        temporal = change["event_time"]
        intention_id = None
        if state == "pending" and temporal["status"] == "resolved":
            intention_id = str(uuid5(NAMESPACE_URL, "commitment-intention-v1:" + identifier))
            start = parse_dt(temporal["start"])
            trigger = {"at": temporal["start"]} if temporal["precision"] == "instant" else {"start": temporal["start"], "end": temporal["end"]}
            intention = Intention(
                intention_id=intention_id, tenant_id=source.tenant_id, user_id=source.user_id,
                agent_id=agent_id, session_id=None,
                trigger_type="exact_time" if temporal["precision"] == "instant" else "time_window",
                trigger_expression=trigger, due_at=start, evidence_ids=[source.cid],
                action={"type": "memory_commitment", "text": change["action"], "commitment_id": commitment_id,
                        "commitment_state": "pending", "action_key": change["action_key"],
                        "event_time": temporal, "source_spans": [span.to_dict()],
                        "derivation_version": "semantic-memory-v1", "notifications": False},
            )
            existing = {item.intention_id for item in engine.list_intentions(source.tenant_id)}
            engine.schedule_intention(intention, idempotent=True)
            report["created_count"] += int(intention_id not in existing)
            report["intention_ids"].append(intention_id)
        elif state == "pending":
            report["unresolved"].append({"source_span": span.to_dict(), "reason": temporal.get("reason", "date_unspecified"), "action": change["action"]})
        metadata = semantic_metadata(source, span, commitment_id=commitment_id, commitment_state=state,
                                     transition=change["state"], action=change["action"], action_key=change["action_key"],
                                     event_time=temporal, intention_id=intention_id,
                                     previous_assertion_id=previous["id"] if previous else None)
        date_text = temporal.get("date") or temporal.get("wording")
        obj = f"{state}: {change['action']}" + (f" ({date_text})" if date_text else "")
        fact = Assertion(tenant_id=source.tenant_id, user_id=source.user_id, branch="main",
                         subject="user", predicate="commitment_state", object=obj,
                         scope={"commitment_id": commitment_id}, calibration=metadata,
                         valid_from=source.created_at, source_evidence_cids=[source.cid],
                         status="active", trust_tier=source.trust_tier, access_policy=dict(policy), id=identifier)
        engine.upsert_assertion(fact)
        report["created_count"] += 1
        report["assertion_ids"].append(identifier)
        cancel_predecessor(previous, identifier)
    return report
