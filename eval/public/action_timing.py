"""Descriptive exact-time timing diagnostics for one isolated action case.

The caller supplies the frozen occurrence schedule, including occurrences
cancelled before they were due. No schedule or threshold is inferred from the
system's answers. This is not the registered PM-Bench/TriggerBench scorer.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime
import math


def _time(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _key(row):
    if not isinstance(row.get("action_id"), str) or not row["action_id"].strip():
        raise ValueError("action_id must be nonempty")
    if type(row.get("occurrence")) is not int or row["occurrence"] < 0:
        raise ValueError("occurrence must be a nonnegative integer")
    return row["action_id"], row["occurrence"]


def _closed(row, fields):
    if not isinstance(row, dict) or set(row) != set(fields.split()):
        raise ValueError("timing record has missing or unknown fields")


def score_exact_time(expected, ticks):
    """Score captured ticks against explicit exact-time occurrence expectations.

    Lateness is max(0, first firing's virtual evaluation time - expected due).
    Missing/future occurrences have no lateness value. Early firing, duplicate
    observations, cancellation violations and reported due-date drift remain
    separate findings. Command duration is wall time, never virtual lateness.
    """
    if any(not isinstance(rows, list) or len(rows) > 10000 for rows in (expected, ticks)):
        raise ValueError("expected occurrences and ticks must be bounded lists")
    schedule = {}
    for row in expected:
        _closed(row, "action_id occurrence due_at cancelled")
        key = _key(row)
        if key in schedule or type(row["cancelled"]) is not bool:
            raise ValueError("duplicate occurrence or invalid cancellation flag")
        schedule[key] = {**row, "due": _time(row["due_at"])}
    observed = defaultdict(list)
    horizon = None
    wall_ms = 0.0
    observation_count = 0
    for tick in ticks:
        _closed(tick, "action_ids queried_channels evaluated_at evaluation_wall_ms firing_observations")
        now = _time(tick["evaluated_at"])
        if horizon is not None and now < horizon:
            raise ValueError("tick clock must not move backwards")
        horizon = now
        duration = tick["evaluation_wall_ms"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 86400000:
            raise ValueError("invalid command wall duration")
        wall_ms += duration
        firings = tick["firing_observations"]
        if not isinstance(firings, list) or len(firings) > 10000:
            raise ValueError("firings must be a bounded list")
        observation_count += len(firings)
        if observation_count > 10000:
            raise ValueError("too many firing observations")
        for field in ("action_ids", "queried_channels"):
            if not isinstance(tick[field], list) or any(not isinstance(v, str) for v in tick[field]):
                raise ValueError("action IDs and channels must be string lists")
        action_ids = []
        for firing in firings:
            _closed(firing, "action_id intention_id occurrence trigger_type due_at evaluated_at provider_evaluated_at")
            key = _key(firing)
            if firing["trigger_type"] != "exact_time":
                raise ValueError("this diagnostic supports only exact-time triggers")
            if not isinstance(firing["intention_id"], str) or not firing["intention_id"].strip():
                raise ValueError("missing intention identity")
            if _time(firing["evaluated_at"]) != now:
                raise ValueError("firing clock does not match its tick")
            if firing["provider_evaluated_at"] is not None and _time(firing["provider_evaluated_at"]) != now:
                raise ValueError("provider evaluation clock does not match its tick")
            _time(firing["due_at"])
            observed[key].append(dict(firing))
            action_ids.append(firing["action_id"])
        if Counter(action_ids) != Counter(tick["action_ids"]):
            raise ValueError("firing observations do not match returned action IDs")
    rows = []
    lateness = []
    due_drift = 0
    for key, row in sorted(schedule.items()):
        firings = observed.get(key, [])
        offset = None
        if row["cancelled"]:
            status = "cancelled-fired" if firings else "cancelled-unfired"
        elif firings:
            offset = (_time(firings[0]["evaluated_at"]) - row["due"]).total_seconds()
            status = "early" if offset < 0 else "late" if offset > 0 else "on-time"
            lateness.append(max(0, offset))
        else:
            status = "missed" if horizon is not None and row["due"] <= horizon else "pending"
        due_drift += sum(_time(f["due_at"]) != row["due"] for f in firings)
        rows.append({
            "action_id": key[0], "occurrence": key[1], "status": status,
            "signed_offset_seconds": offset,
            "observations": firings,
        })
    statuses = Counter(row["status"] for row in rows)
    return {
        "schema": "m12-exact-time-diagnostic/v1",
        "track": "DEVELOPMENT", "publishable": False,
        "rows": rows,
        "expected_occurrences": len(schedule),
        "status_counts": {name: statuses[name] for name in (
            "early", "on-time", "late", "missed", "pending", "cancelled-fired", "cancelled-unfired",
        )},
        "duplicate_observations": sum(max(0, len(values) - 1) for values in observed.values()),
        "unexpected_observations": [f for key, values in observed.items() if key not in schedule for f in values],
        "reported_due_drift_observations": due_drift,
        "lateness_observed_denominator": len(lateness),
        "mean_lateness_seconds": sum(lateness) / len(lateness) if lateness else None,
        "max_lateness_seconds": max(lateness) if lateness else None,
        "evaluation_command_wall_ms": wall_ms,
        "cost_usd": None,
        "cost_status": "not-measured",
        "uncertainty": "not-estimated; descriptive finite observations only",
    }
