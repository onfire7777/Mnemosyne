"""Project causally supported item utility into the existing lifecycle sweep."""

from dataclasses import replace
from datetime import datetime

from .runtime import stat_key


def outcome_lifecycle(state, item_id: str, learning: dict):
    rows = []
    for credit in learning["credit"].values():
        if credit["target_kind"] == "item" and credit["target_id"] == item_id:
            key = stat_key("item", item_id, credit["revision"], credit["task_class"])
            if key in learning["stats"]:
                rows.append(learning["stats"][key])
    if not rows:
        return state
    latest = max(rows, key=lambda row: row.get("last_outcome_at", ""))
    weighted = sum((row.get("utility", 1.0) - 1.0) * row.get("n", 0) for row in rows)
    observations = sum(row.get("n", 0) for row in rows)
    utility = max(-1.0, min(1.0, weighted / max(1, observations) / 0.2))
    return replace(
        state,
        outcome_utility=utility,
        last_outcome_at=datetime.fromisoformat(latest["last_outcome_at"]),
    )
