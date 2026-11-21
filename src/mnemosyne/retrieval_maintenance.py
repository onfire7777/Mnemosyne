"""Repair missing source and projection vectors outside the interactive retrieval deadline."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from urllib.error import HTTPError, URLError

from mnemosyne.access_policy import (
    VECTOR_PARTITION_PUBLIC, may_embed_item, may_read_item, vector_partition_for_item,
)
from mnemosyne.models import Assertion, parse_dt
from mnemosyne.retrieval import (
    HashingEmbeddingProvider, evidence_current_for_context, projection_sources_readable,
)


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


def _record_evidence_retry(engine, tenant_id, source, clock, error) -> None:
    attempts = _retry(source)[0] + 1
    engine.update_evidence_metadata(
        tenant_id,
        source.cid,
        {
            "retrieval_index_retry": {
                "attempts": attempts,
                "after": (clock + timedelta(seconds=min(86400, 60 * 2 ** min(attempts, 10)))).isoformat(),
                "error": type(error).__name__,
            }
        },
        actor="retrieval-maintenance",
        source="configured-embedding-provider",
    )


def _embed_text_for_partition(provider: Any, text: str, partition: str, *, force_sensitive: bool = False) -> list[float] | None:
    if not force_sensitive and partition == VECTOR_PARTITION_PUBLIC:
        embed = getattr(provider, "embed", None)
        return list(embed(text)) if callable(embed) else None
    if type(provider) is HashingEmbeddingProvider:
        from mnemosyne.text import _hashing_embedding_pure
        return list(_hashing_embedding_pure(text, provider.dims))
    embed_sensitive = getattr(provider, "embed_sensitive", None)
    return list(embed_sensitive(text)) if callable(embed_sensitive) else None


def _evidence_candidates(engine, tenant_id: str, user_id: str, targets: dict[str, list[dict[str, Any]]] | None) -> list[str]:
    if targets is not None:
        return [
            row["cid"]
            for row in targets.get("evidence", [])
            if row.get("cid")
            and ("user_id" not in row or row.get("user_id") == user_id)
            and row.get("branch", "main") == "main"
        ]
    evidence_map = getattr(engine, "evidence", None)
    if isinstance(evidence_map, dict):
        return [
            item.cid
            for item in evidence_map.values()
            if getattr(item, "tenant_id", None) == tenant_id
            and getattr(item, "user_id", None) == user_id
            and getattr(item, "branch", "main") == "main"
            and not getattr(item, "embedding", None)
        ]
    return [
        row["cid"]
        for row in engine.export_tenant(tenant_id).get("evidence", [])
        if row.get("user_id") == user_id and row.get("branch", "main") == "main" and row.get("cid")
    ]


def _target_text(kind: str, row: dict[str, Any]) -> str:
    text = str(row.get("text") or "").strip()
    if text:
        return text
    if kind == "assertions":
        return f"{row.get('subject', '')} {row.get('predicate', '')} {row.get('object', '')}".strip()
    if kind == "observations":
        return str(row.get("content") or row.get("statement") or "").strip()
    if kind == "preferences":
        return str(row.get("statement") or "").strip()
    if kind == "knowledge_pages":
        return f"{row.get('title', '')}\n{row.get('content_markdown', '')}".strip()
    return ""


def _resolve_target_owner_and_sources(
    engine: Any,
    tenant_id: str,
    kind: str,
    item_id: str,
    row: dict[str, Any],
) -> tuple[str | None, list[str]]:
    owner = row.get("user_id") if "user_id" in row else None
    source_cids = row.get("source_evidence_cids") if "source_evidence_cids" in row else None
    if owner is not None and source_cids is not None:
        return owner, [cid for cid in (source_cids or []) if isinstance(cid, str) and cid]
    if kind == "assertions" and hasattr(engine, "assertions") and hasattr(engine, "_branch_key"):
        obj = engine.assertions.get(engine._branch_key(tenant_id, "main", item_id))
        if obj is not None:
            owner = owner if owner is not None else getattr(obj, "user_id", None)
            source_cids = source_cids if source_cids is not None else getattr(obj, "source_evidence_cids", [])
    elif kind == "observations" and isinstance(getattr(engine, "observations", None), dict):
        obj = engine.observations.get((tenant_id, item_id, "main"))
        if isinstance(obj, dict):
            owner = owner if owner is not None else obj.get("user_id")
            source_cids = source_cids if source_cids is not None else obj.get("source_evidence_cids", [])
    elif kind == "preferences" and isinstance(getattr(engine, "preferences", None), dict):
        obj = engine.preferences.get(item_id)
        if obj is not None:
            owner = owner if owner is not None else getattr(obj, "user_id", None)
            source_cids = source_cids if source_cids is not None else getattr(obj, "source_evidence_cids", [])
    elif kind == "knowledge_pages" and callable(getattr(engine, "knowledge_page_get", None)):
        obj = engine.knowledge_page_get(tenant_id, item_id, "main", validate_custody=False)
        if obj is not None:
            owner = owner if owner is not None else getattr(obj, "user_id", None)
            source_cids = source_cids if source_cids is not None else getattr(obj, "source_evidence_cids", [])
    return owner, [cid for cid in (source_cids or []) if isinstance(cid, str) and cid]


def _embed_structured_targets(
    engine: Any,
    provider: Any,
    tenant_id: str,
    user_id: str,
    filt: dict[str, Any],
    *,
    kind: str,
    rows: list[dict[str, Any]],
    setter_name: str,
    pass_branch: bool,
    limit: int,
    report: dict[str, Any],
    force_sensitive: bool = False,
) -> bool:
    """Embed bounded active structured targets (assertions/observations/preferences/knowledge_pages).

    Returns ``True`` if the provider became globally unavailable so remaining
    target kinds abort early this tick.
    """
    setter = getattr(engine, setter_name, None)
    if not callable(setter) or not rows:
        return False

    eligible: list[tuple[str, str, list[str], str]] = []
    for row in rows:
        if len(eligible) >= limit:
            break
        if pass_branch and row.get("branch", "main") != "main":
            continue
        item_id = row.get("id") or row.get("observation_id") or row.get("page_id")
        text = _target_text(kind, row)
        if not item_id or not text:
            continue
        owner, source_cids = _resolve_target_owner_and_sources(engine, tenant_id, kind, item_id, row)
        if owner != user_id:
            continue
        sensitivity = int(row.get("sensitivity", 0) or 0)
        access_policy = row.get("access_policy") if isinstance(row.get("access_policy"), dict) else {}
        status = str(row.get("status") or "active")
        if not may_embed_item(sensitivity=sensitivity, access_policy=access_policy, erased=False):
            continue
        decision = may_read_item(
            item_tenant_id=tenant_id,
            sensitivity=sensitivity,
            access_policy=access_policy,
            context=filt,
            policy_max_sensitivity=engine.policy.max_sensitivity,
            status=status,
            erased=False,
        )
        if not decision.allowed or decision.redacted:
            continue
        if source_cids and not projection_sources_readable(
            engine, source_cids, tenant_id=tenant_id, branch="main", filt=filt, policy=engine.policy,
        ):
            continue
        partition = vector_partition_for_item(sensitivity=sensitivity, access_policy=access_policy)
        eligible.append((item_id, text, source_cids, partition))

    if not eligible:
        return False

    counter_key = f"{kind}_indexed"
    public_items = [item for item in eligible if not force_sensitive and item[3] == VECTOR_PARTITION_PUBLIC]
    private_items = [item for item in eligible if force_sensitive or item[3] != VECTOR_PARTITION_PUBLIC]

    def persist_vector(item_id: str, source_cids: list[str], vector: list[float]) -> None:
        if source_cids and not projection_sources_readable(
            engine, source_cids, tenant_id=tenant_id, branch="main", filt=filt, policy=engine.policy,
        ):
            return
        wrote = (
            setter(tenant_id, item_id, vector, branch="main")
            if pass_branch
            else setter(tenant_id, item_id, vector)
        )
        if wrote is not False:
            report[counter_key] += 1

    embed_many = getattr(provider, "embed_many", None)
    if len(public_items) > 1 and callable(embed_many):
        try:
            vectors = list(embed_many([text for _, text, _, _ in public_items]))
            if len(vectors) != len(public_items):
                raise ValueError("embed_many returned mismatched vector count")
            for (item_id, _, source_cids, _), vector in zip(public_items, vectors):
                persist_vector(item_id, source_cids, list(vector))
            public_items = []
        except Exception as error:
            if _provider_unavailable(error):
                report["errors"].append({"kind": kind, "id": public_items[0][0], "error": type(error).__name__})
                return True
            # Fall back to per-item embedding so one bad record does not starve the rest.

    for item_id, text, source_cids, partition in [*public_items, *private_items]:
        try:
            vector = _embed_text_for_partition(provider, text, partition, force_sensitive=force_sensitive)
            if vector is None:
                continue
            persist_vector(item_id, source_cids, vector)
        except Exception as error:
            report["errors"].append({"kind": kind, "id": item_id, "error": type(error).__name__})
            if _provider_unavailable(error):
                return True
    return False


def _deduplicate_active_assertions(
    engine: Any,
    tenant_id: str,
    user_id: str,
    *,
    branch: str = "main",
    clock: datetime,
    max_retire: int = 32,
) -> int:
    """Supersede exact-duplicate active assertions for a user, keeping the newest copy."""
    batch_fn = getattr(engine, "knowledge_source_batch", None)
    upsert_fn = getattr(engine, "upsert_assertion", None)
    if not callable(batch_fn) or not callable(upsert_fn):
        return 0

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    after = ""
    while True:
        chunk = batch_fn(tenant_id, branch, collection="assertions", after=after, limit=4096)
        for row in chunk:
            if (
                row.get("user_id") != user_id
                or row.get("status") != "active"
                or row.get("superseded_by")
                or row.get("valid_to")
                or row.get("expired_at")
            ):
                continue
            key = (
                row.get("subject", ""),
                row.get("predicate", ""),
                row.get("object", ""),
                json.dumps(row.get("scope") or {}, sort_keys=True),
                int(row.get("trust_tier", 0) or 0),
                int(row.get("sensitivity", 0) or 0),
                json.dumps(row.get("access_policy") or {}, sort_keys=True),
            )
            groups.setdefault(key, []).append(row)
        if len(chunk) < 4096:
            break
        after = chunk[-1]["id"]

    retired_count = 0
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    for rows in groups.values():
        if len(rows) <= 1 or retired_count >= max_retire:
            continue
        rows.sort(
            key=lambda r: (parse_dt(r.get("valid_from")) or epoch, str(r.get("transaction_time") or ""), r["id"]),
            reverse=True,
        )
        keeper = rows[0]
        keeper_from = parse_dt(keeper.get("valid_from")) or clock
        for dup in rows[1:]:
            if retired_count >= max_retire:
                break
            dup_from = parse_dt(dup.get("valid_from")) or clock
            valid_to = max(keeper_from, dup_from + timedelta(microseconds=1))
            retired = {
                **dup,
                "status": "superseded",
                "valid_to": valid_to.isoformat(),
                "superseded_by": keeper["id"],
            }
            try:
                upsert_fn(Assertion.from_dict(retired), branch=branch)
                retired_count += 1
            except Exception:
                continue
    return retired_count


def maintain_retrieval_index(engine, tenant_id, user_id, *, limit=16):
    """Index a bounded batch with the configured model and fresh source custody.

    Existing vectors are never replaced or mixed with a fallback model. Private
    sources bypass shared provider caches. Failures remain retryable next tick.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    filt = {"tenant_id": tenant_id, "user_id": user_id, "principal": user_id,
            "role": "reader", "max_trust_tier": engine.policy.max_trust_tier}
    report: dict[str, Any] = {
        "indexed": 0,
        "pending": 0,
        "deferred": 0,
        "errors": [],
        "assertions_indexed": 0,
        "observations_indexed": 0,
        "preferences_indexed": 0,
        "knowledge_pages_indexed": 0,
        "deduplicated_assertions": 0,
    }
    clock = datetime.now(UTC)

    list_targets = getattr(engine, "list_unembedded_targets", None)
    targets = (
        list_targets(tenant_id, branch="main", limit=max(limit * 4, 128))
        if callable(list_targets)
        else None
    )

    pending = []
    for cid in _evidence_candidates(engine, tenant_id, user_id, targets):
        source = engine.get_evidence(tenant_id, cid)
        if source is None or source.user_id != user_id or source.embedding or source.modality != "text" or not source.content:
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
    provider_down = False

    def persist_evidence(source, vector: list[float]) -> None:
        # Recheck after provider I/O; erased/expired sources never reappear.
        current = engine.get_evidence(tenant_id, source.cid)
        if current is None or current.embedding or not evidence_current_for_context(current, filt) or not projection_sources_readable(
            engine, [source.cid], tenant_id=tenant_id, branch="main", filt=filt, policy=engine.policy,
        ):
            return
        if engine.set_evidence_embedding(
            tenant_id, source.cid, vector,
            actor="retrieval-maintenance", source="configured-embedding-provider", only_if_missing=True,
        ):
            report["indexed"] += 1

    batch = pending[:limit]
    public_batch = [
        source for source in batch
        if vector_partition_for_item(sensitivity=source.sensitivity, access_policy=source.access_policy) == VECTOR_PARTITION_PUBLIC
    ]
    private_batch = [
        source for source in batch
        if vector_partition_for_item(sensitivity=source.sensitivity, access_policy=source.access_policy) != VECTOR_PARTITION_PUBLIC
    ]

    embed_many = getattr(provider, "embed_many", None)
    if len(public_batch) > 1 and callable(embed_many):
        try:
            vectors = list(embed_many([source.content for source in public_batch]))
            if len(vectors) != len(public_batch):
                raise ValueError("embed_many returned mismatched vector count")
            for source, vector in zip(public_batch, vectors):
                persist_evidence(source, list(vector))
            public_batch = []
        except Exception as error:
            if _provider_unavailable(error):
                first_source = public_batch[0]
                report["errors"].append({"cid": first_source.cid, "error": type(error).__name__})
                _record_evidence_retry(engine, tenant_id, first_source, clock, error)
                provider_down = True
                public_batch = []
            # Otherwise fall back to per-item embedding to isolate a single bad input.

    if not provider_down:
        for source in [*public_batch, *private_batch]:
            try:
                partition = vector_partition_for_item(sensitivity=source.sensitivity, access_policy=source.access_policy)
                embed = provider.embed if partition == VECTOR_PARTITION_PUBLIC else getattr(provider, "embed_sensitive", None)
                if embed is None:
                    continue
                vector = embed(source.content)
                persist_evidence(source, list(vector))
            except Exception as error:
                report["errors"].append({"cid": source.cid, "error": type(error).__name__})
                _record_evidence_retry(engine, tenant_id, source, clock, error)
                if _provider_unavailable(error):
                    provider_down = True
                    break  # A provider outage is global; malformed input is not.

    report["pending"] -= report["indexed"]

    if not provider_down and targets is not None:
        for kind, setter_name, pass_branch, force_sensitive in (
            ("assertions", "set_assertion_embedding", True, False),
            ("observations", "set_observation_embedding", True, False),
            ("preferences", "set_preference_embedding", False, False),
            ("knowledge_pages", "set_knowledge_page_embedding", True, True),
        ):
            if _embed_structured_targets(
                engine, provider, tenant_id, user_id, filt,
                kind=kind,
                rows=targets.get(kind, []),
                setter_name=setter_name,
                pass_branch=pass_branch,
                limit=limit,
                report=report,
                force_sensitive=force_sensitive,
            ):
                break

    report["deduplicated_assertions"] = _deduplicate_active_assertions(
        engine, tenant_id, user_id, branch="main", clock=clock,
    )
    return report
