"""Spaced testing advances only for new external, served-revision outcomes."""

from __future__ import annotations

from datetime import datetime, timedelta
from mnemosyne.lifecycle import next_rehearsal_days
from .candidates import verification_request_id, EXCLUDED_SOURCES
from .signals import reward, tool_signals, verified_target_outcome


def revalidate(
    runtime, tenant: str, state: dict, artifact: dict, timestamp: datetime
) -> None:
    if artifact.get("pinned") or artifact.get("locked"):
        return
    if timestamp < datetime.fromisoformat(artifact["next_revalidation_at"]):
        return
    if not runtime._sources_live(
        tenant, artifact.get("source_cids", []), artifact.get("user_id")
    ):
        artifact.update(state="demoted", revalidation_reason="source_unavailable")
        return
    seen = set(artifact.get("revalidation_episode_ids", []))
    tests = []
    for episode in state["episodes"].values():
        if (
            episode["id"] in seen
            or episode["status"] != "resolved"
            or episode["created_at"] <= artifact["created_at"]
        ):
            continue
        checks = [signal for signal in episode.get("signals", [])
                  if signal["kind"] in {"tests", "verifier"}]
        if not checks:
            continue
        served = [
            item
            for rid in episode["receipt_ids"]
            for item in state["receipts"].get(rid, {}).get("items", [])
        ]
        # A request annotation is not a result. Grade only the external check
        # carrying this exact request and tested revision, not a nearby verdict.
        requested_checks = tool_signals([
            event for event in episode.get("tool_events", [])
            if event.get("source") not in EXCLUDED_SOURCES
            and event.get("revalidation_request_id")
            == verification_request_id(artifact)
            and event.get("tested_steps") == artifact["steps"]
            and (not event.get("target_ids") or artifact["id"] in event["target_ids"])
        ])
        requested_value = reward(
            [item for item in requested_checks if item["kind"] in {"tests", "verifier"}],
            include_diagnostics=True,
        )
        values = [] if requested_value is None else [requested_value]
        target = episode.get("target_outcomes", {}).get(artifact["id"])
        if target is not None and any(
            item["item_id"] == artifact["id"]
            and item["revision"] == artifact["revision"]
            for item in served
        ):
            # Old attribution bugs and ratings accompanied by unrelated tests
            # are not retention evidence. Require the retained target result
            # to be independently reproducible for this exact served revision.
            checked_value = verified_target_outcome(artifact, {**episode, "signals": checks})
            if checked_value is not None and checked_value == target["value"]:
                values.append(checked_value)
        if values:
            tests.append((episode["id"], min(values)))
    if not tests:
        artifact["revalidation_pending"] = True
        return
    artifact["revalidation_episode_ids"] = sorted(seen | {identifier for identifier, _ in tests})
    artifact["revalidation_pending"] = False
    explanation_ok = artifact.get("explanation_sources") == artifact.get(
        "source_episode_ids"
    )
    for quote in artifact.get("source_quotes", []):
        source = runtime.engine.get_evidence(tenant, quote["cid"])
        explanation_ok = (
            explanation_ok and source is not None and quote["quote"] in source.content
        )
    if any(value <= 0 for _, value in tests) or not explanation_ok:
        artifact.update(
            state="demoted" if explanation_ok else "labile",
            revalidation_reason="external_test_failed"
            if explanation_ok
            else "explanation_mismatch",
        )
        if not explanation_ok:
            artifact["labile_until"] = (timestamp + timedelta(hours=3)).isoformat()
        return
    artifact["revalidation_step"] = artifact.get("revalidation_step", 0) + 1
    artifact["next_revalidation_at"] = (
        timestamp + timedelta(days=next_rehearsal_days(artifact["revalidation_step"]))
    ).isoformat()
