"""Spaced testing advances only for new external, served-revision outcomes."""

from __future__ import annotations

from datetime import datetime, timedelta
from mnemosyne.lifecycle import next_rehearsal_days
from .candidates import verification_request_id, EXCLUDED_SOURCES


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
        if not any(
            signal["kind"] in {"tests", "verifier"}
            for signal in episode.get("signals", [])
        ):
            continue
        served = [
            item
            for rid in episode["receipt_ids"]
            for item in state["receipts"].get(rid, {}).get("items", [])
        ]
        requested_test = any(
            event.get("source") not in EXCLUDED_SOURCES
            and event.get("revalidation_request_id")
            == verification_request_id(artifact)
            and event.get("tested_steps") == artifact["steps"]
            for event in episode.get("tool_events", [])
        )
        if requested_test or any(
            item["item_id"] == artifact["id"]
            and item["revision"] == artifact["revision"]
            for item in served
        ):
            tests.append(episode)
    if not tests:
        artifact["revalidation_pending"] = True
        return
    artifact["revalidation_episode_ids"] = sorted(seen | {row["id"] for row in tests})
    artifact["revalidation_pending"] = False
    explanation_ok = artifact.get("explanation_sources") == artifact.get(
        "source_episode_ids"
    )
    for quote in artifact.get("source_quotes", []):
        source = runtime.engine.get_evidence(tenant, quote["cid"])
        explanation_ok = (
            explanation_ok and source is not None and quote["quote"] in source.content
        )
    if any(row["reward"] <= 0 for row in tests) or not explanation_ok:
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
