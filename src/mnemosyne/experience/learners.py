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
        learner._weights[task] = dict(previous)
    proposed = learner.record_outcome(task, rewards)
    day = datetime.now(UTC).date().isoformat()
    daily = policy.setdefault("route_daily", {}).setdefault(
        task, {"day": day, "weights": dict(previous)}
    )
    if daily["day"] != day:
        daily.update(day=day, weights=dict(previous))
    default = 1 / len(proposed)
    policy["routes"][task] = {
        route: max(
            0.05,
            min(
                0.65,
                daily["weights"].get(route, default) + 0.1,
                max(daily["weights"].get(route, default) - 0.1, weight),
            ),
        )
        for route, weight in proposed.items()
    }
