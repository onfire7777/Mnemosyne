"""Outcome-backed learning diagnostics and writer-contained monitor failures."""

from __future__ import annotations

from collections import defaultdict
import math

from .guards import LearningGuardError, validate
from .receipts import digest
from .stats import wilson_interval

CALIBRATION_MIN_EPISODES = 100
CALIBRATION_MAX_ERROR = 0.10
EXPLORATION_MIN_RECEIPTS = 100
EXPLORATION_FLOOR = 0.02
PROXY_MIN_EPISODES = 40
PROXY_MAX_GAP = 0.20


def _active_component(receipt: dict, component: str) -> bool:
    policy = receipt.get("effective_policy", {})
    return (
        policy.get("learning_enabled", True)
        and not policy.get("learning_frozen", False)
        and policy.get("learning_modes", {}).get(component, "active") == "active"
    )


def diagnostics(state: dict, *, source_lookup=None) -> list[dict]:
    """Return privacy-preserving defects; statistical monitors require enough data."""
    defects = []
    try:
        validate(state, state, "monitor", source_lookup=source_lookup)
    except LearningGuardError as error:
        defects.append({"class": error.code, "reason": str(error)})
    by_class = defaultdict(list)
    for episode in state["episodes"].values():
        if episode.get("status") == "resolved":
            by_class[episode["task_class"]].append(episode)
    for task, episodes in sorted(by_class.items()):
        predictions = [
            episode
            for episode in episodes
            if all(
                _active_component(
                    state["receipts"].get(receipt_id, {}), "metacognition"
                )
                for receipt_id in episode.get("receipt_ids", [])
            )
        ]
        if len(predictions) >= CALIBRATION_MIN_EPISODES:
            bins = defaultdict(list)
            for episode in predictions:
                bins[min(4, int(episode["prediction"] * 5))].append(episode)
            error = math.fsum(
                abs(
                    math.fsum(
                        row["prediction"] - (row["reward"] + 1) / 2 for row in rows
                    )
                )
                for rows in bins.values()
            ) / len(predictions)
            error_lower_bound = 0.0
            for rows in bins.values():
                predicted = math.fsum(row["prediction"] for row in rows) / len(rows)
                observed = math.fsum((row["reward"] + 1) / 2 for row in rows)
                interval = wilson_interval(observed, len(rows))
                distance = max(interval.low - predicted, predicted - interval.high, 0.0)
                error_lower_bound += len(rows) * distance / len(predictions)
            if error_lower_bound > CALIBRATION_MAX_ERROR:
                defects.append(
                    {
                        "class": "X5",
                        "reason": "success predictions exceed calibration tolerance",
                        "task_class": task,
                        "value": error,
                        "error_lower_bound": error_lower_bound,
                        "observations": len(predictions),
                    }
                )
        proxy = []
        for episode in episodes:
            acceptance = [
                row["value"]
                for row in episode.get("signals", [])
                if row["kind"] == "acceptance"
            ]
            verified = [
                row["value"]
                for row in episode.get("signals", [])
                if row["kind"] in {"verifier", "tests"}
            ]
            if acceptance and verified:
                proxy.append(
                    (sum(acceptance) / len(acceptance) - sum(verified) / len(verified))
                    / 2
                )
        if len(proxy) >= PROXY_MIN_EPISODES and sum(proxy) / len(proxy) > PROXY_MAX_GAP:
            defects.append(
                {
                    "class": "X7",
                    "reason": "acceptance reward diverges from verified outcomes",
                    "task_class": task,
                    "value": sum(proxy) / len(proxy),
                    "observations": len(proxy),
                }
            )
    decisions = defaultdict(list)
    for receipt in state["receipts"].values():
        # Legacy records without explicit assignment cannot establish exposure frequency.
        if (
            "exploration" in receipt
            and receipt.get("eligible_targets")
            and _active_component(receipt, "exploration")
        ):
            decisions[receipt["task_class"]].append(receipt)
    for task, receipts in sorted(decisions.items()):
        if len(receipts) < EXPLORATION_MIN_RECEIPTS:
            continue
        explored = sum(row["exploration"] is True for row in receipts)
        if wilson_interval(explored, len(receipts)).high < EXPLORATION_FLOOR:
            defects.append(
                {
                    "class": "X4",
                    "reason": "observed exploration is below its mandatory floor",
                    "task_class": task,
                    "observations": len(receipts),
                    "explored": explored,
                }
            )
    for artifact in state["artifacts"].values():
        if source_lookup is None:
            continue
        for quote in artifact.get("source_quotes", []):
            source = source_lookup(quote.get("cid"))
            if source is None or source.erased:
                continue  # The general live-provenance guard reports this case.
            expected = quote.get("source_hash")
            if expected is not None and expected != digest(source.content):
                defects.append(
                    {
                        "class": "X11",
                        "reason": "source content changed since quote admission",
                        "artifact_id": artifact["id"],
                    }
                )
    protected = state["policy"].get("protected_suite_results", [])
    if any(row.get("passed") is False for row in protected):
        defects.append({"class": "X18", "reason": "protected regression suite failed"})
    return defects


def run_monitors(writer, tenant_id: str) -> dict:
    """Run within LearningWriter so a detection freezes and audits atomically."""

    def lookup(cid):
        return writer.store.engine.get_evidence(tenant_id, cid)

    def inspect(state):
        failures = diagnostics(state, source_lookup=lookup)
        if failures:
            first = failures[0]
            raise LearningGuardError(first["class"], first["reason"])
        return {
            "checked": True,
            "defects": 0,
            "resolved_episodes": sum(
                row.get("status") == "resolved" for row in state["episodes"].values()
            ),
        }

    return writer.apply(tenant_id, "monitor", inspect)
