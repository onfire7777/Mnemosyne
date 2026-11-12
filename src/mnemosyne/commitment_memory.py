"""Source-backed commitments with explicit date precision and lifecycle.

Intentions remain data-only prospective records. A due/fired intention is never
evidence that its real-world task was completed. Cancellation and completion
require a later, matching user statement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
import calendar
import hashlib
import json
import re
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mnemosyne.models import Assertion, parse_dt
from mnemosyne.semantic_memory import semantic_metadata, source_spans

_WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
_NUMBER_WORDS = {word: index for index, word in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_NUMBER_WORDS.update({"a": 1, "an": 1, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90})
_NUMBER = r"(?:\d+|(?:" + "|".join(_NUMBER_WORDS) + r")(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?)"
_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
_DAY_WORD = (r"(?:the day after tomorrow|tomorrow|today|yesterday|in " + _NUMBER + r" (?:minutes?|hours?|days?|weeks?|months?|years?)|"
             r"(?:next|this|on|coming) (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|"
             r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\d{4}-\d{2}-\d{2}|"
             + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"(?:\s+\d{4})?)")
_TEMPORAL = re.compile(r"(?:\b(?:by|until|to|on)\s+)?\b" + _DAY_WORD + r"\b(?:\s+at\s+(?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?", re.I)
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
    named = re.search(r"(" + _MONTH + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", wording, re.I)
    reverse_named = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTH + r")(?:\s+(\d{4}))?", wording, re.I)
    day = None
    if explicit:
        try:
            day = date.fromisoformat(explicit[0])
        except ValueError:
            result.update(status="ambiguous", reason="invalid_date")
            return result
    elif named or reverse_named:
        month_text, day_text, year_text = named.groups() if named else (reverse_named[2], reverse_named[1], reverse_named[3])
        if year_text is None:
            result.update(status="ambiguous", reason="year_required")
            return result
        month = next(i for i in range(1, 13) if calendar.month_name[i].lower().startswith(month_text[:3].lower()))
        try:
            day = date(int(year_text), month, int(day_text))
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
        elif "yesterday" in wording:
            day = today - timedelta(days=1)
        elif offset := re.search(r"in (" + _NUMBER + r") (minute|hour|day|week|month|year)s?", wording):
            amount = int(offset[1]) if offset[1].isdigit() else sum(_NUMBER_WORDS[word] for word in re.split(r"[- ]", offset[1]))
            if amount > 36525:
                result.update(status="ambiguous", reason="date_out_of_range")
                return result
            unit = offset[2]
            if unit in {"minute", "hour"}:
                start = observed_at.astimezone(UTC) + timedelta(seconds=amount * (60 if unit == "minute" else 3600))
                result.update(status="resolved", precision="instant", date=start.astimezone(zone).date().isoformat(),
                              start=start.isoformat(), end=start.isoformat())
                return result
            try:
                if unit in {"month", "year"}:
                    months = today.year * 12 + today.month - 1 + amount * (12 if unit == "year" else 1)
                    year, month0 = divmod(months, 12)
                    # Month/year arithmetic preserves calendar meaning. An
                    # impossible date is surfaced rather than silently moved.
                    day = date(year, month0 + 1, today.day)
                else:
                    day = today + timedelta(days=amount * (7 if unit == "week" else 1))
            except (ValueError, OverflowError):
                result.update(status="ambiguous", reason="invalid_relative_date")
                return result
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
    clock_word = re.search(r"\bat\s+(noon|midnight)\b", wording)
    if clock_word:
        wording = wording[:clock_word.start()] + ("at 12:00pm" if clock_word[1] == "noon" else "at 12:00am")
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


_PAST_VERBS = {
    "met": "meet", "paid": "pay", "sent": "send", "wrote": "write", "written": "write",
    "bought": "buy", "brought": "bring", "made": "make", "done": "do", "did": "do",
    "read": "read", "ran": "run", "built": "build", "took": "take", "taken": "take",
    "went": "go", "gone": "go", "gave": "give", "given": "give", "spoke": "speak",
    "spoken": "speak", "chose": "choose", "chosen": "choose", "found": "find",
    "flew": "fly", "flown": "fly", "drove": "drive", "driven": "drive", "held": "hold",
    "left": "leave", "kept": "keep", "set": "set", "put": "put", "got": "get",
    "gotten": "get", "sold": "sell", "taught": "teach", "told": "tell",
}


def _action_verb(word: str) -> str:
    """Inflection-normalize a verb, leaving the action's objects untouched."""
    word = _PAST_VERBS.get(word, word)
    if word.endswith("ied"):
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 5:
        word = word[:-3]
        if len(word) > 2 and word[-1] == word[-2] and word[-1] not in "lsz":
            word = word[:-1]
    elif word.endswith("ed") and len(word) > 4:
        word = word[:-2]
        if len(word) > 2 and word[-1] == word[-2] and word[-1] not in "lsz":
            word = word[:-1]
    # The base and its -ed/-ing variants share a stem even for silent-e verbs.
    return word[:-1] if word.endswith("e") and not word.endswith("ee") else word


def _action_key(action: str) -> str:
    text = action.casefold()
    text = re.sub(r"\b(?:my|our|the|a|an|with|to)\b", " ", text)
    words = re.findall(r"[\w-]+", text)
    if len(words) > 1 and words[0] in {"finish", "complete"}:
        del words[0]  # "I finished X" is parsed as bare "X"
    if words:
        words[0] = _action_verb(words[0])
    return " ".join(words)


def commitment_changes(source, clauses: list[str], timezone: str | None = None) -> list[dict]:
    changes = []
    for span in source_spans(source, clauses):
        text = span.quote.strip().rstrip(".! ")
        text = re.sub(r"\b(I|We)['’]ve\b", r"\1 have", text, flags=re.I)
        if _UNCERTAIN.search(_TEMPORAL.sub("", text)):  # the month "May" is not the modal "may"
            continue
        kind, action = "pending", None
        if m := re.fullmatch(r"(?:I|We)\s+(?:cancel(?:led|ed)?|called off|no longer plan to)\s+(.+)", text, re.I):
            kind, action = "cancelled", m[1]
        elif m := re.fullmatch(r"(?:I|We)\s+(?:(?:have|had)\s+)?(?:already\s+|just\s+)?(?:completed|finished)\s+(.+)", text, re.I):
            kind, action = "completed", m[1]
        elif m := re.fullmatch(r"(?:I|We)\s+(?:(?:have|had)\s+)?(?:already\s+|just\s+)?(" + "|".join(_PAST_VERBS) + r"|[a-z]+ed)\s+(.+)", text, re.I):
            # Rescheduling/cancellation is handled as a transition below.
            if (m[1].lower() in {"rescheduled", "postponed", "moved", "cancelled", "canceled", "decided", "promised", "committed"}
                    or m[1].lower() in {"read", "set", "put"} and not re.search(r"\b(?:have|had|already|just|yesterday)\b", text, re.I)):
                m = None
            else:
                kind, action = "completed", m[1] + " " + m[2]
        if action is not None:
            pass
        elif m := re.fullmatch(r"(?:I|We)\s+(?:(?:decided to|will)\s+)?(?:reschedul(?:e|ed)|postpon(?:e|ed)|mov(?:e|ed))\s+(.+)", text, re.I):
            # Moving an asset to a host is a relocation, not a calendar edit.
            # "move" denotes rescheduling only for an explicit scheduled event.
            if re.search(r"\bmov(?:e|ed)\b", m[0], re.I) and not re.search(
                r"\b(?:meeting|appointment|call|deadline|booking|session|interview|visit|presentation|reservation|schedule)\b", m[1], re.I,
            ):
                continue
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


def _commitment_readable(engine, source, row) -> bool:
    from mnemosyne.retrieval import projection_sources_readable
    return bool(row.get("source_evidence_cids")) and projection_sources_readable(
        engine, row["source_evidence_cids"], tenant_id=source.tenant_id, branch=source.branch,
        filt={"tenant_id": source.tenant_id, "user_id": source.user_id, "principal": source.user_id},
        policy=engine.policy,
    )


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
                      and _action_key(row.get("calibration", {}).get("action", "")) == change["action_key"]
                      and (parse_dt(row.get("valid_from")) or source.created_at) <= source.created_at
                      and _commitment_readable(engine, source, row)]
        is_change = change["state"] != "pending"
        selector = change["previous_event_time"] if change["state"] == "rescheduled" else change["event_time"]
        if is_change and len(candidates) > 1 and selector and selector.get("date"):
            candidates = [row for row in candidates if row["calibration"].get("event_time", {}).get("date") == selector["date"]]
        if is_change and not candidates and change["state"] == "completed":
            continue  # An ordinary past-tense fact does not invent a prior commitment.
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
