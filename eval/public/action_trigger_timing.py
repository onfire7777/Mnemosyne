"""Development scoring for independently specified trigger eligibility windows.

Gold eligibility comes from the frozen workload, never from candidate firings.
This scorer does not infer whether an event/condition/dependency became true.
"""

from collections import Counter
from bisect import bisect_left

from eval.public.action_timing import _closed, _key, _time, collect_action_ticks

TRIGGER_TYPES = frozenset(
    {"exact_time", "time_window", "event", "condition", "dependency_completion"}
)


def _before_end(at, end, inclusive):
    return end is None or at < end or (inclusive and at == end)


def _metrics(tp, fp, fn):
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def score_trigger_windows(expected, ticks):
    """Score one isolated case, retaining invalid and duplicate firings.

    Eligibility is a list of windows with explicit end inclusion, truncated at
    cancelled_at. Disjoint windows model transient event/condition signals. Missing output is a false negative only if a tick visited
    this interval. Lateness measures time from eligibility, including any delay
    imposed by the workload's polling schedule. No admission/ranking is implied.
    """
    if not isinstance(expected, list) or len(expected) > 10000:
        raise ValueError("expected occurrences must be a bounded list")
    schedule = {}
    total_windows = 0
    for row in expected:
        _closed(row, "action_id occurrence trigger_type due_at windows cancelled_at")
        key = _key(row)
        if (
            key in schedule
            or not isinstance(row["trigger_type"], str)
            or row["trigger_type"] not in TRIGGER_TYPES
        ):
            raise ValueError("duplicate occurrence or unsupported trigger type")
        due = _time(row["due_at"])
        cancelled = (
            _time(row["cancelled_at"]) if row["cancelled_at"] is not None else None
        )
        if not isinstance(row["windows"], list) or len(row["windows"]) > 100:
            raise ValueError("eligibility windows must be a bounded list")
        total_windows += len(row["windows"])
        if total_windows > 10000:
            raise ValueError("too many eligibility windows")
        windows = []
        for window in row["windows"]:
            _closed(window, "start end end_inclusive")
            inclusive = window["end_inclusive"]
            if type(inclusive) is not bool:
                raise ValueError("window end_inclusive must be a boolean")
            start = _time(window["start"])
            end = _time(window["end"]) if window["end"] is not None else None
            if start < due or (
                end is not None and (end < start or (end == start and not inclusive))
            ):
                raise ValueError("invalid eligibility window bounds")
            if windows and (
                windows[-1][1] is None
                or start < windows[-1][1]
                or (start == windows[-1][1] and windows[-1][2])
            ):
                raise ValueError("windows must be ordered and disjoint")
            if row["trigger_type"] == "time_window" and (end is None or inclusive):
                raise ValueError(
                    "time-window expectations require finite exclusive ends"
                )
            windows.append((start, end, inclusive))
        schedule[key] = {
            **row,
            "due_at": due,
            "windows": windows,
            "cancelled_at": cancelled,
        }
    observed, horizon, wall_ms, tick_times = collect_action_ticks(
        ticks, allowed_trigger_types=TRIGGER_TYPES
    )
    counts = {kind: Counter() for kind in TRIGGER_TYPES}
    rows, offsets, invalid, unexpected = [], [], [], []
    due_drift = 0
    for key, row in sorted(schedule.items()):

        def reason(at):
            if row["cancelled_at"] is not None and at >= row["cancelled_at"]:
                return "cancelled"
            if not row["windows"]:
                return "not-eligible"
            if at < row["windows"][0][0]:
                return "early"
            if any(
                start <= at and _before_end(at, end, inclusive)
                for start, end, inclusive in row["windows"]
            ):
                return None
            _, last_end, inclusive = row["windows"][-1]
            return "inactive" if _before_end(at, last_end, inclusive) else "expired"

        def visited(start, end, inclusive):
            index = bisect_left(tick_times, start)
            return (
                index < len(tick_times)
                and _before_end(tick_times[index], end, inclusive)
                and (
                    row["cancelled_at"] is None
                    or tick_times[index] < row["cancelled_at"]
                )
            )

        opportunity = any(visited(*window) for window in row["windows"])
        firings = observed.get(key, [])
        valid = []
        for firing in firings:
            issue = (
                "wrong-trigger-type"
                if firing["trigger_type"] != row["trigger_type"]
                else reason(_time(firing["evaluated_at"]))
            )
            if issue is None:
                valid.append(firing)
            else:
                invalid.append({"reason": issue, "observation": firing})
            due_drift += int(_time(firing["due_at"]) != row["due_at"])
        tp = int(bool(valid))
        fp = len(firings) - tp
        fn = int(opportunity and not valid)
        counts[row["trigger_type"]].update(tp=tp, fp=fp, fn=fn)
        offset = (
            (_time(valid[0]["evaluated_at"]) - row["windows"][0][0]).total_seconds()
            if valid
            else None
        )
        if offset is not None:
            offsets.append(offset)
        rows.append(
            {
                "action_id": key[0],
                "occurrence": key[1],
                "trigger_type": row["trigger_type"],
                "observed_opportunity": opportunity,
                **_metrics(tp, fp, fn),
                "lateness_seconds": offset,
                "observations": firings,
            }
        )
    for key, firings in observed.items():
        if key not in schedule:
            unexpected.extend(firings)
            for firing in firings:
                counts[firing["trigger_type"]]["fp"] += 1
    totals = sum(counts.values(), Counter())
    return {
        "schema": "m12-trigger-window-diagnostic/v1",
        "track": "DEVELOPMENT",
        "publishable": False,
        "metrics": _metrics(totals["tp"], totals["fp"], totals["fn"]),
        "by_trigger": {
            kind: _metrics(value["tp"], value["fp"], value["fn"])
            for kind, value in sorted(counts.items())
        },
        "rows": rows,
        "invalid_observations": invalid,
        "unexpected_observations": unexpected,
        "duplicate_observations": sum(
            max(0, len(values) - 1) for values in observed.values()
        ),
        "reported_due_drift_observations": due_drift,
        "eligible_opportunities": sum(row["observed_opportunity"] for row in rows),
        "no_observed_opportunity": sum(not row["observed_opportunity"] for row in rows),
        "lateness_observed_denominator": len(offsets),
        "mean_lateness_seconds": sum(offsets) / len(offsets) if offsets else None,
        "max_lateness_seconds": max(offsets) if offsets else None,
        "evaluation_command_wall_ms": wall_ms,
        "horizon": horizon.isoformat() if horizon else None,
        "cost_usd": None,
        "cost_status": "not-measured",
        "workload_completeness_verified": False,
        "uncertainty": "not-estimated; descriptive finite observations only",
    }
