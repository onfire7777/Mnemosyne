"""Route updates reuse the existing learner inside immutable daily bounds."""

from __future__ import annotations

from datetime import UTC, datetime
from mnemosyne.self_optimization import AdaptiveRouteWeighter


def update_routes(state: dict, task: str, rewards: dict[str, float]) -> None:
    if not rewards:
        return
    policy = state["policy"]
    previous = policy.setdefault("routes", {}).get(task, {})
    learner = AdaptiveRouteWeighter()
    if previous:
        learner.restore_weights(task, previous)
    day = datetime.now(UTC).date().isoformat()
    daily = policy.setdefault("route_daily", {}).setdefault(
        task, {"day": day, "weights": dict(previous)}
    )
    if daily["day"] != day:
        daily.update(day=day, weights=dict(previous))
    policy["routes"][task] = learner.record_outcome(
        task, rewards, reference_weights=daily["weights"], max_change=0.1
    )
