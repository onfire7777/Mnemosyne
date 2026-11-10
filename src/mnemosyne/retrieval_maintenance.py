"""Repair missing source vectors outside the interactive retrieval deadline."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

from mnemosyne.access_policy import (
    VECTOR_PARTITION_PUBLIC, may_embed_item, may_read_item, vector_partition_for_item,
)
from mnemosyne.retrieval import evidence_current_for_context, projection_sources_readable


def _retry(source):
    value = source.metadata.get("retrieval_index_retry")
    if not isinstance(value, dict):
        return 0, None
    count = value.get("attempts", 0)
    count = max(0, min(count, 100)) if type(count) is int else 0
    try:
        after = datetime.fromisoformat(value["after"])
        after = after.astimezone(UTC) if after.tzinfo else after.replace(tzinfo=UTC)
    except (KeyError, TypeError, ValueError, OverflowError):
        after = None
    return count, after


def _provider_unavailable(error):
    # HTTP adapters wrap status failures in ValueError subclasses as well as
    # urllib errors; preserve the status distinction without parsing messages.
    code = getattr(error, "code", None)
    if isinstance(error, HTTPError) or type(code) is int:
        return code in {401, 403, 404, 408, 429} or code >= 500
    return isinstance(error, (TimeoutError, ConnectionError, URLError))


def maintain_retrieval_index(engine, tenant_id, user_id, *, limit=16):
    """Index a bounded batch with the configured model and fresh source custody.

    Existing vectors are never replaced or mixed with a fallback model. Private
    sources bypass shared provider caches. Failures remain retryable next tick.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    filt = {"tenant_id": tenant_id, "user_id": user_id, "principal": user_id,
            "role": "reader", "max_trust_tier": engine.policy.max_trust_tier}
    report = {"indexed": 0, "pending": 0, "deferred": 0, "errors": []}
    clock = datetime.now(UTC)
    pending = []
    for row in engine.export_tenant(tenant_id).get("evidence", []):
        if row.get("user_id") != user_id or row.get("branch", "main") != "main":
            continue
        source = engine.get_evidence(tenant_id, row["cid"])
        if source is None or source.embedding or source.modality != "text" or not source.content:
            continue
        if source.source_type == "learning_tool_result" or source.metadata.get("quarantine_reason"):
            continue
        if not evidence_current_for_context(source, filt) or not may_embed_item(
            sensitivity=source.sensitivity, access_policy=source.access_policy, erased=source.erased,
        ):
            continue
        decision = may_read_item(item_tenant_id=tenant_id, sensitivity=source.sensitivity,
            access_policy=source.access_policy, context=filt,
            policy_max_sensitivity=engine.policy.max_sensitivity, erased=source.erased)
        if not decision.allowed or decision.redacted or not projection_sources_readable(
            engine, [source.cid], tenant_id=tenant_id, branch="main", filt=filt, policy=engine.policy,
        ):
            continue
        report["pending"] += 1
        attempts, after = _retry(source)
        if after is not None and after > clock:
            report["deferred"] += 1
            continue
        pending.append(source)
    # Never let a batch of permanently invalid newest records monopolize
    # every tick. Unattempted records get a turn before retried failures.
    pending.sort(key=lambda source: (_retry(source)[0], -source.created_at.timestamp(), source.cid))
    provider = engine.adapters.embedding
    for source in pending[:limit]:
        try:
            partition = vector_partition_for_item(sensitivity=source.sensitivity, access_policy=source.access_policy)
            embed = provider.embed if partition == VECTOR_PARTITION_PUBLIC else getattr(provider, "embed_sensitive", None)
            if embed is None:
                continue
            vector = embed(source.content)
            # Recheck after provider I/O; erased/expired sources never reappear.
            current = engine.get_evidence(tenant_id, source.cid)
            if current is None or current.embedding or not evidence_current_for_context(current, filt) or not projection_sources_readable(
                engine, [source.cid], tenant_id=tenant_id, branch="main", filt=filt, policy=engine.policy,
            ):
                continue
            if engine.set_evidence_embedding(tenant_id, source.cid, vector,
                actor="retrieval-maintenance", source="configured-embedding-provider", only_if_missing=True):
                report["indexed"] += 1
        except Exception as error:
            report["errors"].append({"cid": source.cid, "error": type(error).__name__})
            attempts = _retry(source)[0] + 1
            engine.update_evidence_metadata(tenant_id, source.cid, {"retrieval_index_retry": {
                "attempts": attempts, "after": (clock + timedelta(seconds=min(86400, 60 * 2 ** min(attempts, 10)))).isoformat(),
                "error": type(error).__name__,
            }}, actor="retrieval-maintenance", source="configured-embedding-provider")
            if _provider_unavailable(error):
                break  # A provider outage is global; malformed input is not.
    report["pending"] -= report["indexed"]
    return report
