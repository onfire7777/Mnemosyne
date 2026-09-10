"""Retrieval adapter boundaries and local deterministic fallbacks."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Callable, Mapping, Protocol, Sequence

from mnemosyne.access_policy import apply_text_redactions, effective_max_sensitivity, may_read_item
from mnemosyne.command_line import split_command
from mnemosyne.evidence_redaction import redaction_findings
from mnemosyne.media_limits import DEFAULT_MAX_INGEST_BYTES, enforce_byte_limit, validate_byte_limit
from mnemosyne.models import Hit, parse_dt, utc_now
from mnemosyne.network_safety import safe_urlopen, validate_fetch_url
from mnemosyne.policy import OperatingPolicy
from mnemosyne.security import sanitize_retrieved_text, trust_weight
from mnemosyne.text import cosine, hashing_embedding, lexical_score, tokenize


QUERY_SUPPORT_THRESHOLD = 2.0 / 3.0
PROSPECTIVE_MEMORY_CHANNEL = "prospective_memory"
WORKING_MEMORY_CHANNEL = "working_memory"
GLOBAL_SENSEMAKING_MODE = "global_sensemaking"
GLOBAL_SENSEMAKING_CHANNEL = "global_sensemaking"
GLOBAL_SENSEMAKING_VERSION = "global-sensemaking.v1"
SUPPORTED_QUERY_MODES = frozenset({GLOBAL_SENSEMAKING_MODE})
WORKSPACE_BROADCAST_MAX_ITEMS = 4
WORKSPACE_BROADCAST_MAX_CONTENT_CHARS = 160
WORKSPACE_BROADCAST_FILTER_KEYS = ("workspace_broadcast", "workspace_focus")
WORKSPACE_RETRIEVAL_ADVISORY_VERSION = "workspace-retrieval-advisory.v1"
WORKSPACE_RETRIEVAL_ADVISORY_FILTER_KEYS = (
    "workspace_retrieval_advisory",
    "apply_workspace_retrieval_advisory",
    "workspace_retrieval_advisory_mode",
)
WORKSPACE_CONTROLLER_FILTER_KEYS = WORKSPACE_BROADCAST_FILTER_KEYS + WORKSPACE_RETRIEVAL_ADVISORY_FILTER_KEYS
WORKING_MEMORY_ROUTE_VERSION = "working-memory-route.v1"
WORKING_MEMORY_TASK_WEIGHT = 0.75
WORKING_MEMORY_RECENCY_WEIGHT = 0.25
HttpEmbeddingCacheKey = tuple[str, str, str, str, int, str, str]
_HTTP_EMBEDDING_CACHE: OrderedDict[HttpEmbeddingCacheKey, tuple[float, ...]] = OrderedDict()
_HTTP_EMBEDDING_CACHE_LOCK = RLock()


def _plane_value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _plane_relevance(query: str, text: str) -> float:
    query_terms = set(tokenize(query))
    if not query_terms:
        return 0.0
    return len(query_terms & set(tokenize(text))) / len(query_terms)


def prospective_memory_hits(
    ops: Any,
    query: str,
    k: int,
    filt: Mapping[str, Any],
    *,
    as_of: datetime,
) -> list[Hit]:
    """Return due intentions for an explicitly authorized owner, without firing them."""

    owner = filt.get("prospective_owner")
    if not isinstance(owner, Mapping):
        return []
    user_id = str(owner.get("user_id") or "").strip()
    agent_id = str(owner.get("agent_id") or "").strip()
    if not all(isinstance(value, str) and value.strip() for value in (user_id, agent_id)):
        return []
    # The selector is not authority by itself.  Bind it to the authenticated
    # retrieval principal so a caller cannot enumerate another owner's actions.
    if str(filt.get("user_id") or "").strip() != user_id:
        return []
    if str(filt.get("agent_id") or "").strip() != agent_id:
        return []
    tenant_id = str(filt["tenant_id"])
    branch = str(filt.get("branch", "main"))
    hits: list[Hit] = []
    for intention in ops.list_intentions(tenant_id):
        if _plane_value(intention, "user_id") != user_id:
            continue
        if _plane_value(intention, "agent_id") != agent_id:
            continue
        due_at = _plane_value(intention, "due_at")
        if not isinstance(due_at, datetime) or due_at.tzinfo is None:
            continue
        if _plane_value(intention, "status") != "scheduled" or due_at.astimezone(UTC) > as_of:
            continue
        raw_id = str(_plane_value(intention, "intention_id"))
        action = _plane_value(intention, "action", {})
        text = json.dumps(action, sort_keys=True, separators=(",", ":"), default=str)
        provenance = [str(cid) for cid in _plane_value(intention, "evidence_ids", [])]
        if not provenance:
            continue
        trust_tiers: list[int] = []
        sensitivities: list[int] = []
        capability_tags: set[str] = set()
        privacy: list[dict[str, Any]] = []
        allowed = True
        for cid in provenance:
            evidence = ops.get_evidence(tenant_id, cid, branch)
            if (
                evidence is None
                or evidence.tenant_id != tenant_id
                or evidence.user_id != user_id
                or evidence.branch != branch
                or evidence.trust_tier > ops.policy.max_trust_tier
            ):
                allowed = False
                break
            decision = may_read_item(
                item_tenant_id=evidence.tenant_id,
                sensitivity=evidence.sensitivity,
                access_policy=evidence.access_policy,
                context=filt,
                policy_max_sensitivity=ops.policy.max_sensitivity,
                erased=evidence.erased,
            )
            if not decision.allowed:
                allowed = False
                break
            text, redaction = apply_text_redactions(text, evidence.access_policy, decision)
            if not text:
                allowed = False
                break
            if redaction.get("redacted"):
                privacy.append(redaction)
            trust_tiers.append(evidence.trust_tier)
            sensitivities.append(evidence.sensitivity)
            capability_tags.update(str(tag) for tag in evidence.capability_tags if str(tag).strip())
        if not allowed:
            continue
        hits.append(
            Hit(
                id=raw_id,
                kind="intention",
                tenant_id=tenant_id,
                branch=branch,
                text=text,
                score=_plane_relevance(query, text),
                channel=PROSPECTIVE_MEMORY_CHANNEL,
                provenance=provenance,
                trust_tier=max(trust_tiers),
                sensitivity=max(sensitivities),
                metadata={
                    "memory_plane": PROSPECTIVE_MEMORY_CHANNEL,
                    "intention_id": raw_id,
                    "due_at": due_at.astimezone(UTC).isoformat(),
                    "capability_tags": sorted(capability_tags),
                    "privacy": privacy,
                },
            )
        )
    return sorted(hits, key=lambda hit: (-hit.score, hit.metadata["due_at"], hit.id))[:k]


QUERY_SUPPORT_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "answer",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "capital",
    "did",
    "do",
    "does",
    "drink",
    "fast",
    "for",
    "from",
    "happened",
    "how",
    "i",
    "in",
    "into",
    "is",
    "it",
    "its",
    "kind",
    "language",
    "level",
    "manually",
    "me",
    "memory",
    "my",
    "now",
    "of",
    "on",
    "or",
    "our",
    "own",
    "owned",
    "owns",
    "please",
    "prefer",
    "preferred",
    "prefers",
    "procedure",
    "produce",
    "relation",
    "should",
    "size",
    "style",
    "tell",
    "that",
    "the",
    "therefore",
    "these",
    "this",
    "those",
    "to",
    "travel",
    "type",
    "use",
    "used",
    "user",
    "uses",
    "using",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "whose",
    "why",
    "with",
    "you",
    "your",
}

_SCHEMA_NAME_RE = r"([A-Z][A-Za-z0-9_-]*)"
_ASSIGNED_PROJECT_RE = re.compile(
    rf"\b{_SCHEMA_NAME_RE}\s+is\s+assigned\s+to\s+project\s+{_SCHEMA_NAME_RE}\b",
    re.IGNORECASE,
)
_REPORTS_TO_RE = re.compile(rf"\b{_SCHEMA_NAME_RE}\s+reports\s+to\s+{_SCHEMA_NAME_RE}\b", re.IGNORECASE)
_PROJECT_DEADLINE_RE = re.compile(
    rf"\bproject\s+{_SCHEMA_NAME_RE}\s+has\s+a\s+delivery\s+deadline\b",
    re.IGNORECASE,
)
_PROJECT_LEAD_RE = re.compile(rf"\bproject\s+{_SCHEMA_NAME_RE}\s+is\s+led\s+by\s+{_SCHEMA_NAME_RE}\b", re.IGNORECASE)
_AS_OF_RE = re.compile(r"\bas\s+of\s+(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)

_TEMPORAL_SUBJECTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("primary_datacenter", ("primary", "datacenter")),
    ("release_cadence", ("release", "cadence")),
    ("on_call_tool", ("on-call", "tool")),
    ("default_cloud", ("default", "cloud")),
)


def workspace_broadcast_from_context(ctx: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return redacted shadow workspace broadcast metadata from route/retrieval context."""

    raw = None
    if isinstance(ctx, Mapping):
        for key in WORKSPACE_BROADCAST_FILTER_KEYS:
            if key in ctx:
                raw = ctx.get(key)
                break
    items = _workspace_broadcast_items(raw)
    return {
        "applied": bool(items),
        "source": "workspace_context",
        "shadow_only": True,
        "critical_path": False,
        "data_not_instructions": True,
        "used_for_control_flow": False,
        "used_for_ranking": False,
        "control_keys_stripped": True,
        "raw_content_present": False,
        "max_items": WORKSPACE_BROADCAST_MAX_ITEMS,
        "item_count": len(items),
        "items": items,
    }


def strip_workspace_broadcast_filter(filt: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove workspace-controller keys before adapter/search filters are evaluated."""

    clean = dict(filt or {})
    for key in WORKSPACE_CONTROLLER_FILTER_KEYS:
        clean.pop(key, None)
    return clean


def answer_grounding_floor_report(
    hits: Sequence[Hit],
    policy: OperatingPolicy,
) -> dict[str, Any]:
    """Return the H5 answer-grounding floor report for a support set.

    Low-grounded self-generated support may be retrieved as hypothesis data, but
    it cannot dominate an answer. The report is deterministic and critical-path:
    engines use ``active`` to flag/abstain before returning a result.
    """

    rows: list[dict[str, Any]] = []
    low_self = 0
    grounded = 0
    support_count = len(hits)
    low_threshold = _bounded_unit(
        getattr(policy, "answer_grounding_low_groundedness_threshold", 0.5),
    )
    max_self_fraction = _bounded_unit(
        getattr(policy, "answer_low_grounded_self_max_fraction", 0.5),
    )
    min_grounded_fraction = _bounded_unit(
        getattr(policy, "answer_grounding_min_grounded_fraction", 0.5),
    )
    for index, hit in enumerate(hits):
        metadata = hit.metadata if isinstance(hit.metadata, Mapping) else {}
        standing_payload = metadata.get("standing") if isinstance(metadata.get("standing"), Mapping) else {}
        raw_groundedness = standing_payload.get("groundedness", 0.0)
        try:
            groundedness = _bounded_unit(float(raw_groundedness))
        except (TypeError, ValueError):
            groundedness = 0.0
        reality_class = _normalise_retrieval_reality_class(metadata.get("reality_class"))
        authority = bool(standing_payload.get("authority")) if standing_payload else groundedness >= low_threshold
        low_self_support = reality_class in {"self_generated", "simulated"} and groundedness < low_threshold
        grounded_support = authority and reality_class == "grounded"
        if low_self_support:
            low_self += 1
        if grounded_support:
            grounded += 1
        rows.append(
            {
                "hit_id": hit.id or f"{hit.kind}:{index}",
                "reality_class": reality_class,
                "groundedness": round(groundedness, 6),
                "standing_authority": authority,
                "low_grounded_self_support": low_self_support,
                "grounded_support": grounded_support,
            }
        )
    denominator = max(1, support_count)
    low_self_fraction = round(low_self / denominator, 6)
    grounded_fraction = round(grounded / denominator, 6)
    weak_self_dominates = low_self_fraction > max_self_fraction
    grounded_floor_failed = low_self > 0 and grounded_fraction < min_grounded_fraction
    active = support_count > 0 and (weak_self_dominates or grounded_floor_failed)
    reasons: list[str] = []
    if weak_self_dominates:
        reasons.append("low_grounded_self_support_exceeds_fraction_cap")
    if grounded_floor_failed:
        reasons.append("grounded_support_fraction_below_floor")
    return {
        "applied": True,
        "critical_path": True,
        "shadow_only": False,
        "trigger": "answer_grounding_floor",
        "active": active,
        "flag_as_hypothesis": active,
        "abstain": active,
        "support_count": support_count,
        "low_grounded_self_support_count": low_self,
        "grounded_support_count": grounded,
        "low_grounded_self_fraction": low_self_fraction,
        "grounded_support_fraction": grounded_fraction,
        "max_low_grounded_self_fraction": max_self_fraction,
        "min_grounded_support_fraction": min_grounded_fraction,
        "low_groundedness_threshold": low_threshold,
        "reasons": reasons,
        "rows": rows,
    }


def apply_workspace_retrieval_advisory(
    hits: Sequence[Hit],
    ctx: Mapping[str, Any] | None,
    *,
    tenant_id: str,
    branch: str,
    policy: OperatingPolicy,
) -> tuple[list[Hit], dict[str, Any]]:
    """Apply a gated workspace retrieval advisory to already retrieved hits.

    This is the first promoted retrieval-controller seam. It is default-off,
    requires both a policy knob and an explicit request flag, and can only boost
    already retrieved tenant/branch-scoped hits that are backed by advisory CIDs.
    Raw workspace text and raw advisory CIDs are never copied into the report.
    """

    original = list(hits)
    report = _workspace_retrieval_base_report()
    if not isinstance(ctx, Mapping) or "workspace_retrieval_advisory" not in ctx:
        report["status"] = "not_requested"
        report["reason"] = "no_workspace_retrieval_advisory"
        return original, report

    apply_requested = ctx.get("apply_workspace_retrieval_advisory") is True or ctx.get(
        "workspace_retrieval_advisory_mode"
    ) == "apply"
    report["apply_requested"] = bool(apply_requested)
    raw = ctx.get("workspace_retrieval_advisory")
    if not isinstance(raw, Mapping):
        report.update({"status": "rejected", "reason": "workspace_retrieval_advisory_not_mapping"})
        return original, report
    if not apply_requested:
        report.update(
            {
                "status": "report_only",
                "reason": "explicit_opt_in_required",
                "item_count": _advisory_item_count(raw),
            }
        )
        return original, report
    if not bool(getattr(policy, "workspace_retrieval_advisory_enabled", False)):
        report.update(
            {
                "status": "disabled",
                "reason": "policy_disabled",
                "item_count": _advisory_item_count(raw),
            }
        )
        return original, report

    max_items = max(1, int(getattr(policy, "workspace_retrieval_advisory_max_items", 4)))
    max_boost = _bounded_unit(getattr(policy, "workspace_retrieval_advisory_max_boost", 1.0))
    if max_boost <= 0.0:
        report.update({"status": "disabled", "reason": "zero_boost"})
        return original, report

    contract = _workspace_retrieval_contract_checks(raw, tenant_id=tenant_id, branch=branch)
    report["contract"] = contract
    if not all(contract.values()):
        report.update(
            {
                "status": "rejected",
                "reason": "workspace_retrieval_advisory_contract_invalid",
            }
        )
        return original, report

    raw_items = raw.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
        report.update({"status": "rejected", "reason": "workspace_retrieval_advisory_items_invalid"})
        return original, report

    hit_matches = _workspace_retrieval_matches(original, tenant_id=tenant_id, branch=branch)
    boosts_by_hit: dict[tuple[str, str], dict[str, Any]] = {}
    invalid_reasons: list[str] = []
    considered = 0
    for index, item in enumerate(list(raw_items)[:max_items]):
        considered += 1
        if not isinstance(item, Mapping):
            invalid_reasons.append(f"item_{index + 1}_not_mapping")
            continue
        cid = str(item.get("cid") or item.get("source_cid") or item.get("evidence_cid") or "").strip()
        if not cid:
            invalid_reasons.append(f"item_{index + 1}_missing_cid")
            continue
        priority = _bounded_unit(item.get("priority", item.get("score", item.get("weight", 1.0))))
        if priority <= 0.0:
            invalid_reasons.append(f"item_{index + 1}_nonpositive_priority")
            continue
        matches = hit_matches.get(cid)
        if not matches:
            invalid_reasons.append(f"item_{index + 1}_cid_not_in_candidates")
            continue
        boost = round(max_boost * priority, 6)
        item_id = str(item.get("workspace_item_id") or item.get("id") or f"workspace-retrieval-item-{index + 1}")
        for match_key in matches:
            previous = boosts_by_hit.get(match_key)
            if previous is None or float(previous["boost"]) < boost:
                boosts_by_hit[match_key] = {
                    "boost": boost,
                    "item_id": item_id,
                }

    if invalid_reasons:
        report.update(
            {
                "status": "rejected",
                "reason": "workspace_retrieval_advisory_items_rejected",
                "invalid_reasons": invalid_reasons[:max_items],
                "item_count": considered,
            }
        )
        return original, report
    if not boosts_by_hit:
        report.update({"status": "rejected", "reason": "no_matching_candidate_cids", "item_count": considered})
        return original, report

    boosted: list[Hit] = []
    for hit in original:
        key = (hit.kind, hit.id)
        match = boosts_by_hit.get(key)
        if match is None:
            boosted.append(hit)
            continue
        boost = float(match["boost"])
        metadata = {
            **hit.metadata,
            "workspace_retrieval_advisory": {
                "applied": True,
                "boost": round(boost, 6),
                "workspace_item_id": str(match["item_id"]),
                "critical_path": True,
                "production_mutation": False,
            },
        }
        boosted.append(
            replace(
                hit,
                score=round(float(hit.score) + boost, 6),
                channel=_append_channel(hit.channel, "workspace"),
                metadata=metadata,
            )
        )

    boosted.sort(key=lambda item: (item.score, item.kind, item.id), reverse=True)
    report.update(
        {
            "status": "applied",
            "reason": "explicit_opt_in_validated",
            "used_for_ranking": True,
            "critical_path": True,
            "shadow_only": False,
            "input_shadow_only": True,
            "item_count": considered,
            "applied_item_count": len(boosts_by_hit),
            "applied_hit_count": len(boosts_by_hit),
            "max_items": max_items,
            "max_boost": round(max_boost, 6),
        }
    )
    return boosted, report


def _workspace_broadcast_items(raw: object) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        if isinstance(raw.get("items"), Sequence) and not isinstance(raw.get("items"), (str, bytes, bytearray)):
            candidates = list(raw.get("items", []))
        elif isinstance(raw.get("selected_items"), Sequence) and not isinstance(raw.get("selected_items"), (str, bytes, bytearray)):
            candidates = list(raw.get("selected_items", []))
        elif isinstance(raw.get("trace"), Sequence) and not isinstance(raw.get("trace"), (str, bytes, bytearray)):
            candidates = list(raw.get("trace", []))
        else:
            candidates = [raw]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        candidates = list(raw)
    else:
        candidates = [raw]
    return [
        _workspace_broadcast_item(item, index=index)
        for index, item in enumerate(candidates[:WORKSPACE_BROADCAST_MAX_ITEMS])
    ]


def _workspace_broadcast_item(item: object, *, index: int) -> dict[str, Any]:
    if isinstance(item, Mapping):
        item_id = str(item.get("id") or item.get("focus_id") or f"workspace-focus-{index + 1}")
        text = str(item.get("content") or item.get("text") or "")
        source = str(item.get("source") or item.get("reality_class") or "workspace")
        stripped = sorted(
            str(key)
            for key in item
            if str(key)
            in {
                "apply_workspace_retrieval_advisory",
                "workspace_retrieval_advisory_mode",
                "control_flow",
                "instructions",
                "policy_override",
                "system_prompt",
                "tool_call",
            }
        )
    else:
        item_id = f"workspace-focus-{index + 1}"
        text = str(item or "")
        source = "workspace"
        stripped = []
    text = text[:WORKSPACE_BROADCAST_MAX_CONTENT_CHARS]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""
    return {
        "id": item_id,
        "source": source,
        "content_chars": len(text),
        "content_ref": f"[workspace-broadcast-redacted:{digest}:chars={len(text)}]" if text else "",
        "data_not_instructions": True,
        "used_for_control_flow": False,
        "stripped_control_keys": stripped,
    }


def _workspace_retrieval_base_report() -> dict[str, Any]:
    return {
        "version": WORKSPACE_RETRIEVAL_ADVISORY_VERSION,
        "source": "workspace_retrieval_advisory",
        "status": "not_requested",
        "reason": "",
        "apply_requested": False,
        "used_for_ranking": False,
        "critical_path": False,
        "shadow_only": True,
        "production_mutation": False,
        "promotion_gate_required": True,
        "item_count": 0,
        "applied_item_count": 0,
        "applied_hit_count": 0,
    }


def _workspace_retrieval_contract_checks(raw: Mapping[str, Any], *, tenant_id: str, branch: str) -> dict[str, bool]:
    return {
        "version": str(raw.get("version") or "") == WORKSPACE_RETRIEVAL_ADVISORY_VERSION,
        "tenant_matches": str(raw.get("tenant_id") or "") == tenant_id,
        "branch_matches": str(raw.get("branch") or branch) == branch,
        "shadow_only_input": raw.get("shadow_only") is True,
        "critical_path_false_input": raw.get("critical_path") is False,
        "production_mutation_false": raw.get("production_mutation") is False,
        "advisory_only": raw.get("advisory_only") is True,
        "promotion_gate_required": raw.get("promotion_gate_required") is True,
        "not_preapplied_to_ranking": raw.get("applied_to_ranking") is False,
        "not_preapplied_to_mutation": raw.get("applied_to_mutation") is False,
    }


def _workspace_retrieval_matches(
    hits: Sequence[Hit],
    *,
    tenant_id: str,
    branch: str,
) -> dict[str, list[tuple[str, str]]]:
    matches: dict[str, list[tuple[str, str]]] = {}
    for hit in hits:
        if hit.tenant_id != tenant_id or hit.branch != branch:
            continue
        if hit.metadata.get("erased") is True:
            continue
        key = (hit.kind, hit.id)
        for cid in _workspace_retrieval_refs(hit):
            matches.setdefault(cid, []).append(key)
    return matches


def _workspace_retrieval_refs(hit: Hit) -> set[str]:
    refs = {str(hit.id)}
    refs.update(str(cid) for cid in hit.provenance if str(cid))
    source_cids = hit.metadata.get("source_evidence_cids")
    if isinstance(source_cids, Sequence) and not isinstance(source_cids, (str, bytes, bytearray)):
        refs.update(str(cid) for cid in source_cids if str(cid))
    return refs


def _advisory_item_count(raw: Mapping[str, Any]) -> int:
    items = raw.get("items")
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        return len(items)
    return 0


def _bounded_unit(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalise_retrieval_reality_class(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    lowered = value.strip().lower().replace("-", "_")
    aliases = {
        "evidence_grounded": "grounded",
        "grounded": "grounded",
        "self_generated": "self_generated",
        "simulated": "self_generated",
        "externally_suggested": "externally_suggested",
        "external": "externally_suggested",
        "unknown": "unknown",
    }
    return aliases.get(lowered, "unknown")


def normalise_query_term(token: str) -> str:
    token = token.lower()
    if token in {"owned", "owning", "owns"}:
        return "own"
    if token in {"notifications", "notification", "notified", "notifies", "notify"}:
        return "notify"
    if token == "co2":
        return "carbon"
    for suffix in ("ingly", "edly", "ing", "ied", "ies", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            if suffix == "ies":
                return token[: -len(suffix)] + "y"
            if suffix == "ied":
                return token[: -len(suffix)] + "y"
            return token[: -len(suffix)]
    return token


def similar_query_terms(left: str, right: str) -> bool:
    if left == right:
        return True
    if len(left) >= 5 and len(right) >= 5 and (left.startswith(right[:5]) or right.startswith(left[:5])):
        return True
    return bool(len(left) >= 4 and len(right) >= 4 and (left.startswith(right[:4]) or right.startswith(left[:4])))


def query_support(query: str, hits: Sequence[Hit]) -> dict[str, Any]:
    query_terms: list[str] = []
    for token in tokenize(query):
        term = normalise_query_term(token)
        if len(term) <= 2 or term in QUERY_SUPPORT_STOPWORDS or term in query_terms:
            continue
        query_terms.append(term)
    if not query_terms:
        return {
            "score": 1.0,
            "threshold": QUERY_SUPPORT_THRESHOLD,
            "matched_terms": [],
            "missing_terms": [],
            "query_terms": [],
        }

    evidence_terms: list[str] = []
    for hit in hits[:8]:
        evidence_terms.extend(normalise_query_term(token) for token in tokenize(hit.text) if len(token) > 2)
    matched_terms = [
        term
        for term in query_terms
        if any(similar_query_terms(term, candidate) for candidate in evidence_terms)
    ]
    missing_terms = [term for term in query_terms if term not in matched_terms]
    score = len(matched_terms) / max(len(query_terms), 1)
    return {
        "score": score,
        "threshold": QUERY_SUPPORT_THRESHOLD,
        "matched_terms": matched_terms,
        "missing_terms": missing_terms,
        "query_terms": query_terms,
    }


def schema_fast_path_rerank(
    query: str,
    hits: Sequence[Hit],
    policy: OperatingPolicy,
) -> tuple[list[Hit], dict[str, Any]]:
    """Boost recognized relation/time joins without calling an LLM.

    G1's schema fast path is deliberately narrow: it only fires for simple
    evidence-grounded joins already present in the retrieved candidate set
    (person -> project -> deadline, person -> manager -> led project, and
    temporal as-of/current rows). It never fabricates an answer; it reorders
    existing hits and records every boost in metadata for auditability.
    """

    if not hits or not bool(getattr(policy, "schema_fast_path_enabled", True)):
        return list(hits), {"applied": False, "reason": "disabled_or_empty", "boosted_hit_ids": []}

    boost = max(0.0, float(getattr(policy, "schema_fast_path_boost", 1.25)))
    if boost <= 0.0:
        return list(hits), {"applied": False, "reason": "zero_boost", "boosted_hit_ids": []}

    reasons = _schema_fast_path_reasons(query, hits)
    if not reasons:
        return list(hits), {"applied": False, "reason": "no_schema_pattern", "boosted_hit_ids": []}

    boosted_ids = set(reasons)
    boosted: list[Hit] = []
    for index, hit in enumerate(hits):
        reason = reasons.get(hit.id)
        if reason is None:
            boosted.append(hit)
            continue
        metadata = {
            **hit.metadata,
            "schema_fast_path": {
                "applied": True,
                "reason": reason,
                "boost": round(boost, 6),
                "original_rank": index + 1,
            },
        }
        boosted.append(replace(hit, score=hit.score + boost, channel=_append_channel(hit.channel, "schema"), metadata=metadata))

    return sorted(boosted, key=lambda item: (item.score, item.id in boosted_ids), reverse=True), {
        "applied": True,
        "boost": round(boost, 6),
        "boosted_hit_ids": sorted(boosted_ids),
        "reasons": {key: reasons[key] for key in sorted(reasons)},
    }


def _schema_fast_path_reasons(query: str, hits: Sequence[Hit]) -> dict[str, str]:
    query_text = query.strip()
    query_lower = query_text.lower()
    reasons: dict[str, str] = {}

    deadline_person = _regex_group(r"\bproject\s+([A-Za-z][A-Za-z0-9_-]*)\s+is\s+assigned\s+to\b", query_text)
    if deadline_person and "deadline" in query_lower:
        project = _assigned_project_for_person(deadline_person, hits)
        if project:
            for hit in hits:
                text = hit.text.lower()
                if hit.id not in reasons and _ASSIGNED_PROJECT_RE.search(hit.text) and deadline_person.lower() in text:
                    reasons[hit.id] = "first-hop assigned-project support"
                if hit.id not in reasons and _PROJECT_DEADLINE_RE.search(hit.text):
                    if project.lower() in text and "deadline" in text:
                        reasons[hit.id] = "second-hop project deadline support"

    manager_person = _regex_group(r"\bperson\s+([A-Za-z][A-Za-z0-9_-]*)\s+reports\s+to\b", query_text)
    if manager_person and "led" in query_lower:
        manager = _manager_for_person(manager_person, hits)
        if manager:
            for hit in hits:
                text = hit.text.lower()
                if hit.id not in reasons and _REPORTS_TO_RE.search(hit.text) and manager_person.lower() in text:
                    reasons[hit.id] = "first-hop manager support"
                if hit.id not in reasons and _PROJECT_LEAD_RE.search(hit.text):
                    if manager.lower() in text:
                        reasons[hit.id] = "second-hop project-lead support"

    temporal_subject = _temporal_subject(query_text)
    if temporal_subject is not None:
        selected_id = _temporal_selected_hit_id(query_text, hits, temporal_subject)
        if selected_id:
            reasons[selected_id] = "temporal as-of/current schema support"

    if "current" in query_lower:
        selected_policy = _current_policy_hit_id(query_text, hits)
        if selected_policy:
            reasons[selected_policy] = "current policy schema support"

    return reasons


def _regex_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None


def _assigned_project_for_person(person: str, hits: Sequence[Hit]) -> str | None:
    person_lower = person.lower()
    for hit in hits:
        match = _ASSIGNED_PROJECT_RE.search(hit.text)
        if match and match.group(1).lower() == person_lower:
            return match.group(2)
    return None


def _manager_for_person(person: str, hits: Sequence[Hit]) -> str | None:
    person_lower = person.lower()
    for hit in hits:
        match = _REPORTS_TO_RE.search(hit.text)
        if match and match.group(1).lower() == person_lower:
            return match.group(2)
    return None


def _temporal_subject(text: str) -> tuple[str, ...] | None:
    terms = set(tokenize(text))
    for _, subject_terms in _TEMPORAL_SUBJECTS:
        if set(subject_terms).issubset(terms):
            return subject_terms
    return None


def _temporal_selected_hit_id(query: str, hits: Sequence[Hit], subject_terms: tuple[str, ...]) -> str | None:
    rows: list[tuple[datetime, str]] = []
    subject_set = set(subject_terms)
    for hit in hits:
        if not subject_set.issubset(set(tokenize(hit.text))):
            continue
        match = _AS_OF_RE.search(hit.text)
        if not match:
            continue
        parsed = parse_dt(match.group(1))
        if parsed is not None:
            rows.append((parsed.astimezone(UTC), hit.id))
    if not rows:
        return None
    rows.sort(key=lambda item: item[0])
    query_as_of = _AS_OF_RE.search(query)
    if query_as_of:
        moment = parse_dt(query_as_of.group(1))
        if moment is None:
            return None
        candidates = [row for row in rows if row[0] <= moment.astimezone(UTC)]
        return candidates[-1][1] if candidates else rows[0][1]
    if any(term in query.lower() for term in ("current", "currently", "today", "now")):
        return rows[-1][1]
    if "before" in query.lower() and "latest" in query.lower():
        return rows[-2][1] if len(rows) >= 2 else rows[-1][1]
    return None


def _current_policy_hit_id(query: str, hits: Sequence[Hit]) -> str | None:
    query_terms = set(tokenize(query))
    policy_terms = {term for term in query_terms if term not in QUERY_SUPPORT_STOPWORDS and term != "current"}
    candidates: list[tuple[int, float, str]] = []
    for hit in hits:
        text_terms = set(tokenize(hit.text))
        if "updated" not in text_terms or "policy" not in text_terms:
            continue
        overlap = len(policy_terms & text_terms)
        if overlap <= 0:
            continue
        candidates.append((overlap, max(hit.score, 0.0), hit.id))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][2]


def _append_channel(channel: str, suffix: str) -> str:
    parts = [part for part in channel.split("+") if part]
    if suffix not in parts:
        parts.append(suffix)
    return "+".join(parts)


class EmbeddingProvider(Protocol):
    """Boundary for production embedding models.

    The blueprint calls for a real dense embedding provider. This protocol keeps
    that integration explicit while tests and local development use a
    deterministic provider that has no network dependency.
    """

    name: str
    dims: int

    def embed(self, text: str) -> list[float]:
        """Return a normalized embedding vector for text."""


def _with_query_prefix(text: str, prefix: str) -> str:
    if not prefix:
        return text
    marker = prefix.rstrip()
    if text.startswith(prefix) or (marker and text.startswith(marker)):
        return text
    return f"{prefix}{text}"


def embed_query(provider: EmbeddingProvider, query: str) -> list[float]:
    query_embed = getattr(provider, "embed_query", None)
    if callable(query_embed):
        return query_embed(query)
    return provider.embed(query)


class MediaEmbeddingProvider(Protocol):
    """Boundary for image/audio/video embedding providers."""

    name: str
    dims: int

    def embed_media(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, object] | None = None,
    ) -> list[float]:
        """Return a normalized embedding vector for raw media bytes."""


class Reranker(Protocol):
    """Boundary for production cross-encoder or LLM rerankers."""

    name: str

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        """Return the top-k hits after reranking."""


class LexicalRetriever(Protocol):
    """Boundary for production lexical/BM25 retrieval backends."""

    name: str

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        branch: str,
        k: int,
        filt: Mapping[str, object] | None = None,
    ) -> list[Hit]:
        """Return lexical hits for a tenant-scoped query."""


class GraphRetriever(Protocol):
    """Boundary for production graph/PPR retrieval backends."""

    name: str

    def search(
        self,
        seeds: Sequence[str],
        *,
        tenant_id: str,
        branch: str,
        k: int,
        as_of: datetime | None = None,
        filt: Mapping[str, object] | None = None,
    ) -> list[Hit]:
        """Return graph hits for tenant-scoped seed terms."""


def _run_json_command(
    command: Sequence[str],
    payload: Mapping[str, object],
    *,
    timeout_seconds: float,
    role: str,
) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            input=json.dumps(payload),
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{role} command timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[:512]
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"{role} command failed{suffix}") from exc
    output = completed.stdout.strip()
    if not output:
        raise ValueError(f"{role} command returned no JSON")
    if len(output.encode("utf-8")) > 1_048_576:
        raise ValueError(f"{role} command response exceeded 1 MiB")
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{role} command response must be valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{role} command response must be a JSON object")
    return parsed


def _command_int(value: object, *, default: int, field: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"hit field {field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"hit field {field} must be an integer") from exc


def _command_provenance(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("hit field provenance must be an array")
    return [str(item) for item in value if str(item)]


def _command_hit(
    item: object,
    *,
    tenant_id: str,
    branch: str,
    default_channel: str,
    backend: str,
) -> Hit:
    if not isinstance(item, Mapping):
        raise ValueError("retrieval command hits must contain JSON objects")
    hit_id = str(item.get("id") or "").strip()
    text = str(item.get("text") or "").strip()
    if not hit_id:
        raise ValueError("retrieval command hit requires id")
    if not text:
        raise ValueError("retrieval command hit requires text")
    kind = str(item.get("kind") or "evidence")
    if kind not in {"evidence", "assertion", "relation", "preference"}:
        raise ValueError(f"retrieval command hit kind {kind!r} is not supported")
    score_raw = item.get("score")
    if isinstance(score_raw, bool):
        raise ValueError("retrieval command hit score must be numeric")
    try:
        score = float(score_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("retrieval command hit score must be numeric") from exc
    if not math.isfinite(score):
        raise ValueError("retrieval command hit score must be finite")
    metadata_raw = item.get("metadata")
    metadata = dict(metadata_raw) if isinstance(metadata_raw, Mapping) else {}
    metadata.setdefault("backend", backend)
    metadata["command_retrieval"] = True
    if "tenant_id" in item and str(item["tenant_id"]) != tenant_id:
        raise ValueError("retrieval command hit tenant_id is outside requested tenant")
    if "branch" in item and str(item["branch"]) != branch:
        raise ValueError("retrieval command hit branch is outside requested branch")
    return Hit(
        id=hit_id,
        kind=kind,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        branch=branch,
        text=text,
        score=score,
        channel=str(item.get("channel") or default_channel),
        provenance=_command_provenance(item.get("provenance")),
        trust_tier=_command_int(item.get("trust_tier"), default=0, field="trust_tier"),
        sensitivity=_command_int(item.get("sensitivity"), default=0, field="sensitivity"),
        metadata=metadata,
    )


def _command_hits(
    parsed: Mapping[str, Any],
    *,
    tenant_id: str,
    branch: str,
    k: int,
    default_channel: str,
    backend: str,
) -> list[Hit]:
    raw_hits = parsed.get("hits")
    if not isinstance(raw_hits, list):
        raise ValueError("retrieval command response requires hits array")
    hits = [
        _command_hit(item, tenant_id=tenant_id, branch=branch, default_channel=default_channel, backend=backend)
        for item in raw_hits
    ]
    return sorted(hits, key=lambda item: item.score, reverse=True)[: max(k, 0)]


def validate_adapter_hit_scope(
    hits: list[Hit],
    *,
    tenant_id: str,
    branch: str,
    k: int | None = None,
    adapter_name: str = "retrieval",
) -> list[Hit]:
    """Fail closed if a retrieval adapter returns cross-tenant or cross-branch data."""

    scoped: list[Hit] = []
    for hit in hits:
        if hit.tenant_id != tenant_id:
            raise ValueError(f"{adapter_name} adapter returned hit outside requested tenant")
        if hit.branch != branch:
            raise ValueError(f"{adapter_name} adapter returned hit outside requested branch")
        scoped.append(hit)
    if k is None:
        return scoped
    return scoped[: max(k, 0)]


@dataclass(frozen=True, slots=True)
class HashingEmbeddingProvider:
    """Local embedding provider with deterministic hashing vectors."""

    dims: int = 256
    name: str = "local-hashing"

    def embed(self, text: str) -> list[float]:
        return hashing_embedding(text, dims=self.dims)

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


@dataclass(frozen=True, slots=True)
class LocalSimilarityReranker:
    """Dependency-free reranker using lexical and deterministic dense signals."""

    embedding_provider: EmbeddingProvider = HashingEmbeddingProvider()
    lexical_weight: float = 0.55
    dense_weight: float = 0.45
    name: str = "local-similarity"

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        query_vec = embed_query(self.embedding_provider, query)
        scored: list[Hit] = []
        for hit in hits:
            dense = cosine(query_vec, self.embedding_provider.embed(hit.text))
            lexical = lexical_score(query, hit.text)
            clone = Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=max(0.0, self.lexical_weight * lexical + self.dense_weight * dense),
                channel=f"{hit.channel}+rerank",
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata={**hit.metadata, "reranker": self.name},
            )
            scored.append(clone)
        return sorted(scored, key=lambda item: item.score, reverse=True)[:k]


@dataclass(frozen=True, slots=True)
class HttpEmbeddingProvider:
    """HTTP JSON embedding provider for managed or self-hosted models.

    The adapter accepts OpenAI-style responses (`data[0].embedding`) and a
    compact generic shape (`embedding`). Vectors are Matryoshka-truncated or
    zero-padded to the configured target dimension, then normalized.
    """

    url: str
    model: str | None = None
    api_key: str | None = None
    dims: int = 1024
    timeout_seconds: float = 30.0
    name: str = "http-embedding"
    query_prefix: str = "query: "
    model_revision: str | None = None
    cache_size: int = 8192
    cache_path: str | None = None
    cache_ttl_seconds: float = 86400.0
    cache_scope: str = "default"

    def embed(self, text: str) -> list[float]:
        cache_key = _http_embedding_cache_key(self, text)
        if self.cache_size > 0:
            cached = _http_embedding_cache_get(cache_key)
            if cached is None:
                cached = _http_embedding_disk_cache_get(self, cache_key, text)
            if cached is not None:
                _http_embedding_cache_put(cache_key, cached, self.cache_size)
                return cached
        normalized = self.embed_sensitive(text)
        _http_embedding_cache_put(cache_key, normalized, self.cache_size)
        _http_embedding_disk_cache_put(self, cache_key, text, normalized, self.cache_size)
        return normalized

    def embed_sensitive(self, text: str) -> list[float]:
        """Embed without reading or writing either cache tier.

        Sensitivity-tiered (non-public-partition) text must never enter the
        process-global LRU or the durable cache — the same fail-closed
        admission rule SqliteEngine's A1 embedding cache hardcodes. Engines
        route private-partition content here.
        """
        payload: dict[str, object] = {"input": text}
        if self.model:
            payload["model"] = self.model
        response = _post_json(self.url, payload, self.api_key, self.timeout_seconds)
        return _normalize_vector(_extract_embedding(response), self.dims)

    def purge_cache(self) -> None:
        """Drop every cached vector in this provider's scope (memory + disk).

        Erasure hook: cache entries are keyed by text hash, so precise row
        invalidation is impossible once the source row is erased; scope-wide
        purge is the provably safe form. Erasures are rare, so the cache-warmth
        cost is acceptable.
        """
        scope = _http_embedding_cache_scope(self)
        with _HTTP_EMBEDDING_CACHE_LOCK:
            for key in [k for k in _HTTP_EMBEDDING_CACHE if k[0] == scope]:
                del _HTTP_EMBEDDING_CACHE[key]
        if not self.cache_path:
            return
        path = os.path.expanduser(self.cache_path)
        if not os.path.exists(path):
            return
        scope_hash = _http_embedding_cache_digest(scope)
        with _HTTP_EMBEDDING_CACHE_LOCK, _http_embedding_disk_cache_connect(self) as conn:
            conn.execute(
                "DELETE FROM http_embedding_cache WHERE scope_sha256 = ?",
                (scope_hash,),
            )

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts through the service's OpenAI-style list input.

        Sends one request with ``{"input": [...]}`` and reads the batch
        response (``data[i].embedding`` ordered by ``index``). Servers without
        the batch route (HTTP 4xx on a list payload) and responses without a
        usable batch shape fall back to per-item ``embed`` calls, so results
        and their order always match the sequential path exactly.
        """
        items = list(texts)
        if not items:
            return []
        results: list[list[float] | None] = [None] * len(items)
        missing: list[tuple[int, str, HttpEmbeddingCacheKey]] = []
        for index, text in enumerate(items):
            cache_key = _http_embedding_cache_key(self, text)
            cached = None
            if self.cache_size > 0:
                cached = _http_embedding_cache_get(cache_key)
                if cached is None:
                    cached = _http_embedding_disk_cache_get(self, cache_key, text)
            if cached is None:
                missing.append((index, text, cache_key))
            else:
                _http_embedding_cache_put(cache_key, cached, self.cache_size)
                results[index] = cached
        if not missing:
            return [vector for vector in results if vector is not None]
        if len(missing) == 1:
            index, text, _cache_key = missing[0]
            results[index] = self.embed(text)
            return [vector for vector in results if vector is not None]
        payload: dict[str, object] = {"input": [text for _index, text, _cache_key in missing]}
        if self.model:
            payload["model"] = self.model
        try:
            response = _post_json(self.url, payload, self.api_key, self.timeout_seconds)
        except _ProviderHttpError as exc:
            if 400 <= exc.code < 500:
                for index, text, _cache_key in missing:
                    results[index] = self.embed(text)
                return [vector for vector in results if vector is not None]
            raise
        try:
            vectors = _extract_embeddings_batch(response, expected=len(missing))
        except ValueError:
            for index, text, _cache_key in missing:
                results[index] = self.embed(text)
            return [vector for vector in results if vector is not None]
        for (index, _text, cache_key), vector in zip(missing, vectors, strict=True):
            normalized = _normalize_vector(vector, self.dims)
            _http_embedding_cache_put(cache_key, normalized, self.cache_size)
            _http_embedding_disk_cache_put(self, cache_key, _text, normalized, self.cache_size)
            results[index] = normalized
        return [vector for vector in results if vector is not None]

    def embed_query(self, query: str) -> list[float]:
        return self.embed(_with_query_prefix(query, self.query_prefix))

    def cache_report(self) -> dict[str, object]:
        report: dict[str, object] = {
            "process_lru_enabled": self.cache_size > 0,
            "process_lru_limit": max(0, int(self.cache_size)),
            "process_lru_entries": _http_embedding_memory_cache_size(),
            "durable_enabled": bool(self.cache_path and self.cache_size > 0),
            "durable_configured": bool(self.cache_path),
            "cache_scope_sha256": _http_embedding_cache_digest(_http_embedding_cache_scope(self)),
            "ttl_seconds": float(self.cache_ttl_seconds),
        }
        if self.cache_path and self.cache_size > 0:
            report.update(_http_embedding_disk_cache_stats(self))
        return report


def _http_embedding_cache_key(
    provider: HttpEmbeddingProvider,
    text: str,
) -> HttpEmbeddingCacheKey:
    auth = hashlib.sha256((provider.api_key or "").encode("utf-8")).hexdigest()
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return (
        _http_embedding_cache_scope(provider),
        provider.url,
        provider.model or "",
        provider.model_revision or "",
        provider.dims,
        auth,
        text_hash,
    )


def _http_embedding_cache_get(key: HttpEmbeddingCacheKey) -> list[float] | None:
    with _HTTP_EMBEDDING_CACHE_LOCK:
        vector = _HTTP_EMBEDDING_CACHE.get(key)
        if vector is None:
            return None
        _HTTP_EMBEDDING_CACHE.move_to_end(key)
        return list(vector)


def _http_embedding_cache_put(
    key: HttpEmbeddingCacheKey,
    vector: Sequence[float],
    max_size: int,
) -> None:
    if max_size <= 0:
        return
    with _HTTP_EMBEDDING_CACHE_LOCK:
        _HTTP_EMBEDDING_CACHE[key] = tuple(vector)
        _HTTP_EMBEDDING_CACHE.move_to_end(key)
        while len(_HTTP_EMBEDDING_CACHE) > max_size:
            _HTTP_EMBEDDING_CACHE.popitem(last=False)


def _http_embedding_memory_cache_size() -> int:
    with _HTTP_EMBEDDING_CACHE_LOCK:
        return len(_HTTP_EMBEDDING_CACHE)


def _http_embedding_cache_scope(provider: HttpEmbeddingProvider) -> str:
    scope = str(provider.cache_scope or "default").strip()
    return scope or "default"


def _http_embedding_cache_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _http_embedding_disk_cache_key(key: HttpEmbeddingCacheKey) -> tuple[str, str, str, str, int, str, str]:
    scope, url, model, model_revision, dims, auth, text_hash = key
    return (
        _http_embedding_cache_digest(scope),
        _http_embedding_cache_digest(url),
        _http_embedding_cache_digest(model),
        _http_embedding_cache_digest(model_revision),
        dims,
        auth,
        text_hash,
    )


def _http_embedding_disk_cache_safe(provider: HttpEmbeddingProvider, text: str) -> bool:
    return bool(provider.cache_path and provider.cache_size > 0) and not redaction_findings(
        "http_embedding_cache_input",
        text,
    )


def _http_embedding_disk_cache_connect(provider: HttpEmbeddingProvider) -> sqlite3.Connection:
    if not provider.cache_path:
        raise ValueError("HTTP embedding durable cache path is not configured")
    path = os.path.expanduser(provider.cache_path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS http_embedding_cache (
            scope_sha256 TEXT NOT NULL,
            url_sha256 TEXT NOT NULL,
            model_sha256 TEXT NOT NULL,
            model_revision_sha256 TEXT NOT NULL,
            dims INTEGER NOT NULL,
            api_key_sha256 TEXT NOT NULL,
            text_sha256 TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_access_at REAL NOT NULL,
            PRIMARY KEY (
                scope_sha256,
                url_sha256,
                model_sha256,
                model_revision_sha256,
                dims,
                api_key_sha256,
                text_sha256
            )
        )
        """
    )
    return conn


def _http_embedding_disk_cache_get(
    provider: HttpEmbeddingProvider,
    key: HttpEmbeddingCacheKey,
    text: str,
) -> list[float] | None:
    if not _http_embedding_disk_cache_safe(provider, text):
        return None
    disk_key = _http_embedding_disk_cache_key(key)
    now = time.time()
    ttl = float(provider.cache_ttl_seconds)
    with _HTTP_EMBEDDING_CACHE_LOCK, _http_embedding_disk_cache_connect(provider) as conn:
        row = conn.execute(
            """
            SELECT vector_json, created_at
            FROM http_embedding_cache
            WHERE scope_sha256 = ?
              AND url_sha256 = ?
              AND model_sha256 = ?
              AND model_revision_sha256 = ?
              AND dims = ?
              AND api_key_sha256 = ?
              AND text_sha256 = ?
            """,
            disk_key,
        ).fetchone()
        if row is None:
            return None
        if ttl > 0 and now - float(row[1]) > ttl:
            conn.execute(
                """
                DELETE FROM http_embedding_cache
                WHERE scope_sha256 = ?
                  AND url_sha256 = ?
                  AND model_sha256 = ?
                  AND model_revision_sha256 = ?
                  AND dims = ?
                  AND api_key_sha256 = ?
                  AND text_sha256 = ?
                """,
                disk_key,
            )
            return None
        try:
            decoded = json.loads(str(row[0]))
            vector = [float(value) for value in decoded]
        except (TypeError, ValueError, json.JSONDecodeError):
            conn.execute(
                """
                DELETE FROM http_embedding_cache
                WHERE scope_sha256 = ?
                  AND url_sha256 = ?
                  AND model_sha256 = ?
                  AND model_revision_sha256 = ?
                  AND dims = ?
                  AND api_key_sha256 = ?
                  AND text_sha256 = ?
                """,
                disk_key,
            )
            return None
        conn.execute(
            """
            UPDATE http_embedding_cache
            SET last_access_at = ?
            WHERE scope_sha256 = ?
              AND url_sha256 = ?
              AND model_sha256 = ?
              AND model_revision_sha256 = ?
              AND dims = ?
              AND api_key_sha256 = ?
              AND text_sha256 = ?
            """,
            (now, *disk_key),
        )
        return vector


def _http_embedding_disk_cache_put(
    provider: HttpEmbeddingProvider,
    key: HttpEmbeddingCacheKey,
    text: str,
    vector: Sequence[float],
    max_size: int,
) -> None:
    if not _http_embedding_disk_cache_safe(provider, text):
        return
    disk_key = _http_embedding_disk_cache_key(key)
    now = time.time()
    with _HTTP_EMBEDDING_CACHE_LOCK, _http_embedding_disk_cache_connect(provider) as conn:
        conn.execute(
            """
            INSERT INTO http_embedding_cache (
                scope_sha256,
                url_sha256,
                model_sha256,
                model_revision_sha256,
                dims,
                api_key_sha256,
                text_sha256,
                vector_json,
                created_at,
                last_access_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (
                scope_sha256,
                url_sha256,
                model_sha256,
                model_revision_sha256,
                dims,
                api_key_sha256,
                text_sha256
            )
            DO UPDATE SET
                vector_json = excluded.vector_json,
                created_at = excluded.created_at,
                last_access_at = excluded.last_access_at
            """,
            (*disk_key, json.dumps([float(value) for value in vector], separators=(",", ":")), now, now),
        )
        if max_size > 0:
            conn.execute(
                """
                DELETE FROM http_embedding_cache
                WHERE scope_sha256 = ?
                  AND rowid NOT IN (
                      SELECT rowid
                      FROM http_embedding_cache
                      WHERE scope_sha256 = ?
                      ORDER BY last_access_at DESC
                      LIMIT ?
                  )
                """,
                (disk_key[0], disk_key[0], max_size),
            )


def _http_embedding_disk_cache_stats(provider: HttpEmbeddingProvider) -> dict[str, object]:
    try:
        if not provider.cache_path:
            return {"durable_entries": 0}
        path = os.path.expanduser(provider.cache_path)
        if not os.path.exists(path):
            return {"durable_entries": 0}
        scope_hash = _http_embedding_cache_digest(_http_embedding_cache_scope(provider))
        with _HTTP_EMBEDDING_CACHE_LOCK, sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM http_embedding_cache WHERE scope_sha256 = ?",
                    (scope_hash,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = (0,)
        return {"durable_entries": int(row[0]) if row else 0}
    except Exception as exc:  # noqa: BLE001 - status reporting must not break provider checks.
        return {"durable_error": str(exc)}


class CommandMediaEmbeddingProvider:
    """Shell-free command adapter for operator-managed multimodal embedders.

    The command is invoked as `<command> <tmp-media-path>` with JSON metadata on
    stdin. It must write a JSON object containing `embedding` or
    `data[0].embedding` to stdout.
    """

    name = "command-media-embedding"

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        dims: int = 1024,
        timeout_seconds: float = 30.0,
        max_media_bytes: int = DEFAULT_MAX_INGEST_BYTES,
    ):
        self.command = split_command(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("media embedding command must not be empty")
        if dims <= 0:
            raise ValueError("media embedding dimensions must be positive")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("media embedding timeout must be positive")
        self.dims = dims
        self.timeout_seconds = timeout_seconds
        self.max_media_bytes = validate_byte_limit(max_media_bytes, name="max_media_bytes")

    def embed_media(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, object] | None = None,
    ) -> list[float]:
        enforce_byte_limit(payload, limit=self.max_media_bytes, label="media embedding payload")
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(payload)
            tmp.flush()
            request = {
                "path": tmp.name,
                "media_type": media_type,
                "modality": modality,
                "metadata": metadata or {},
            }
            try:
                completed = subprocess.run(
                    [*self.command, tmp.name],
                    input=json.dumps(request),
                    check=True,
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise ValueError("media embedding command timed out") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()[:512]
                suffix = f": {detail}" if detail else ""
                raise ValueError(f"media embedding command failed{suffix}") from exc
        output = completed.stdout.strip()
        if not output:
            raise ValueError("media embedding command returned no JSON")
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ValueError("media embedding response must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("media embedding response must be a JSON object")
        return _normalize_vector(_extract_embedding(parsed), self.dims)


class CommandLexicalRetriever:
    """Shell-free command adapter for production lexical/BM25 retrieval.

    The command receives a JSON request on stdin and must return
    `{"hits": [...]}`. Deployments can back the command with ParadeDB BM25,
    another Postgres extension, or a managed lexical retrieval service without
    changing the Mnemosyne engine contract.
    """

    name = "command-lexical-retriever"

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        backend: str = "command-lexical",
        timeout_seconds: float = 30.0,
    ):
        self.command = split_command(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("lexical retrieval command must not be empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("lexical retrieval timeout must be positive")
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        branch: str,
        k: int,
        filt: Mapping[str, object] | None = None,
    ) -> list[Hit]:
        payload: dict[str, object] = {
            "role": "lexical_search",
            "query": query,
            "tenant_id": tenant_id,
            "branch": branch,
            "k": k,
            "filter": dict(filt or {}),
        }
        parsed = _run_json_command(
            self.command,
            payload,
            timeout_seconds=self.timeout_seconds,
            role="lexical retrieval",
        )
        return _command_hits(
            parsed,
            tenant_id=tenant_id,
            branch=branch,
            k=k,
            default_channel="command_lexical",
            backend=self.backend,
        )


class CommandGraphRetriever:
    """Shell-free command adapter for production specialist graph retrieval."""

    name = "command-graph-retriever"

    def __init__(
        self,
        command: str | Sequence[str],
        *,
        backend: str = "command-graph",
        timeout_seconds: float = 30.0,
    ):
        self.command = split_command(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("graph retrieval command must not be empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("graph retrieval timeout must be positive")
        self.backend = backend
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        seeds: Sequence[str],
        *,
        tenant_id: str,
        branch: str,
        k: int,
        as_of: datetime | None = None,
        filt: Mapping[str, object] | None = None,
    ) -> list[Hit]:
        payload: dict[str, object] = {
            "role": "graph_ppr",
            "seeds": [str(seed) for seed in seeds],
            "tenant_id": tenant_id,
            "branch": branch,
            "k": k,
            "filter": dict(filt or {}),
        }
        if as_of is not None:
            payload["as_of"] = as_of.isoformat()
        parsed = _run_json_command(
            self.command,
            payload,
            timeout_seconds=self.timeout_seconds,
            role="graph retrieval",
        )
        return _command_hits(
            parsed,
            tenant_id=tenant_id,
            branch=branch,
            k=k,
            default_channel="command_graph_ppr",
            backend=self.backend,
        )


@dataclass(frozen=True, slots=True)
class HttpReranker:
    """HTTP JSON reranker for cross-encoder-style providers.

    The adapter accepts Cohere-style responses (`results[{index, relevance_score}]`)
    and a compact generic shape (`results[{index, score}]`).
    """

    url: str
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 30.0
    name: str = "http-reranker"
    query_prefix: str = "query: "

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        if k <= 0 or not hits:
            return []
        documents = [hit.text for hit in hits]
        payload: dict[str, object] = {
            "query": _with_query_prefix(query, self.query_prefix),
            "documents": documents,
            "top_n": k,
        }
        if self.model:
            payload["model"] = self.model
        response = _post_json(self.url, payload, self.api_key, self.timeout_seconds)
        scored = _extract_rerank_scores(response)
        ranked: list[Hit] = []
        seen: set[int] = set()
        for index, score in scored:
            if index < 0 or index >= len(hits):
                raise ValueError(f"reranker response index {index} is out of range")
            if index in seen:
                raise ValueError(f"reranker response contains duplicate index {index}")
            seen.add(index)
            hit = hits[index]
            ranked.append(
                Hit(
                    id=hit.id,
                    kind=hit.kind,
                    tenant_id=hit.tenant_id,
                    branch=hit.branch,
                    text=hit.text,
                    score=float(score),
                    channel=f"{hit.channel}+rerank",
                    provenance=list(hit.provenance),
                    trust_tier=hit.trust_tier,
                    sensitivity=hit.sensitivity,
                    metadata={**hit.metadata, "reranker": self.name},
                )
            )
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:k]


@dataclass(frozen=True, slots=True)
class RetrievalAdapters:
    """Configured retrieval boundaries used by runtime implementations."""

    embedding: EmbeddingProvider = HashingEmbeddingProvider()
    reranker: Reranker = LocalSimilarityReranker()
    lexical_backend: str = "local-bm25-lite"
    graph_backend: str = "local-ppr"
    lexical_retriever: LexicalRetriever | None = None
    graph_retriever: GraphRetriever | None = None


def retrieval_adapters_from_env(prefix: str = "MNEMOSYNE") -> RetrievalAdapters:
    """Build retrieval adapters from environment variables.

    Supported provider values:
    - `{prefix}_EMBEDDING_PROVIDER=local|http`
    - `{prefix}_RERANKER_PROVIDER=local|http`
    - `{prefix}_LEXICAL_PROVIDER=postgres|command`
    - `{prefix}_GRAPH_PROVIDER=postgres|command`
    """

    embedding_provider = os.environ.get(f"{prefix}_EMBEDDING_PROVIDER", "local").lower()
    reranker_provider = os.environ.get(f"{prefix}_RERANKER_PROVIDER", "local").lower()
    lexical_provider = os.environ.get(f"{prefix}_LEXICAL_PROVIDER", "postgres").lower()
    graph_provider = os.environ.get(f"{prefix}_GRAPH_PROVIDER", "postgres").lower()
    dims = int(os.environ.get(f"{prefix}_EMBEDDING_DIMS", "1024"))
    embedding_cache_size = int(os.environ.get(f"{prefix}_EMBEDDING_CACHE_SIZE", "8192"))
    embedding_cache_ttl_seconds = float(os.environ.get(f"{prefix}_EMBEDDING_CACHE_TTL_SECONDS", "86400"))
    timeout = float(os.environ.get(f"{prefix}_RETRIEVAL_TIMEOUT", "30"))
    if embedding_provider == "http":
        embedding = HttpEmbeddingProvider(
            url=_required_env(f"{prefix}_EMBEDDING_URL"),
            model=os.environ.get(f"{prefix}_EMBEDDING_MODEL"),
            model_revision=os.environ.get(f"{prefix}_EMBEDDING_MODEL_REVISION"),
            api_key=os.environ.get(f"{prefix}_EMBEDDING_API_KEY"),
            dims=dims,
            timeout_seconds=timeout,
            cache_size=embedding_cache_size,
            cache_path=os.environ.get(f"{prefix}_EMBEDDING_CACHE_PATH"),
            cache_ttl_seconds=embedding_cache_ttl_seconds,
            cache_scope=os.environ.get(f"{prefix}_EMBEDDING_CACHE_SCOPE", "default"),
        )
    elif embedding_provider in {"local", "local-hashing", "hashing"}:
        embedding = HashingEmbeddingProvider(dims=dims)
    else:
        raise ValueError(f"unsupported embedding provider: {embedding_provider}")

    if reranker_provider == "http":
        reranker: Reranker = HttpReranker(
            url=_required_env(f"{prefix}_RERANKER_URL"),
            model=os.environ.get(f"{prefix}_RERANKER_MODEL"),
            api_key=os.environ.get(f"{prefix}_RERANKER_API_KEY"),
            timeout_seconds=timeout,
        )
    elif reranker_provider in {"local", "local-similarity"}:
        reranker = LocalSimilarityReranker(embedding_provider=embedding)
    else:
        raise ValueError(f"unsupported reranker provider: {reranker_provider}")

    lexical_backend = os.environ.get(f"{prefix}_LEXICAL_BACKEND", "postgres-fts")
    graph_backend = os.environ.get(f"{prefix}_GRAPH_BACKEND", "postgres-recursive-ppr")
    if lexical_provider == "command":
        lexical_retriever: LexicalRetriever | None = CommandLexicalRetriever(
            _required_env(f"{prefix}_LEXICAL_COMMAND"),
            backend=lexical_backend,
            timeout_seconds=timeout,
        )
    elif lexical_provider in {"postgres", "native"}:
        lexical_retriever = None
    else:
        raise ValueError(f"unsupported lexical provider: {lexical_provider}")

    if graph_provider == "command":
        graph_retriever: GraphRetriever | None = CommandGraphRetriever(
            _required_env(f"{prefix}_GRAPH_COMMAND"),
            backend=graph_backend,
            timeout_seconds=timeout,
        )
    elif graph_provider in {"postgres", "native"}:
        graph_retriever = None
    else:
        raise ValueError(f"unsupported graph provider: {graph_provider}")

    return RetrievalAdapters(
        embedding=embedding,
        reranker=reranker,
        lexical_backend=lexical_backend,
        graph_backend=graph_backend,
        lexical_retriever=lexical_retriever,
        graph_retriever=graph_retriever,
    )


def semantic_entropy(alternatives: Sequence[str]) -> float:
    """Estimate answer uncertainty from lexical clusters of alternatives.

    This is not a substitute for model-logprob entropy. It is a deterministic
    local signal for tests, abstention explanations, and offline canary runs.
    Identical alternatives produce zero entropy; divergent alternatives increase
    toward one.
    """

    normalized = [" ".join(tokenize(item)) for item in alternatives if tokenize(item)]
    if len(normalized) <= 1:
        return 0.0
    counts = Counter(normalized)
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    entropy = -sum((count / total) * math.log(count / total, 2) for count in counts.values())
    max_entropy = math.log(len(counts), 2) if len(counts) > 1 else 1.0
    return entropy / max_entropy if max_entropy else 0.0


def gist_support_report(hits: Sequence[Hit]) -> dict[str, object]:
    """Return whether retrieved support is only fidelity-demoted gist evidence."""

    if not hits:
        return {"applied": False, "gist_hit_ids": [], "hit_count": 0}
    gist_ids = [hit.id for hit in hits if _is_gist_hit(hit)]
    return {
        "applied": len(gist_ids) == len(hits),
        "gist_hit_ids": gist_ids,
        "hit_count": len(hits),
    }


def _is_gist_hit(hit: Hit) -> bool:
    metadata = hit.metadata if isinstance(hit.metadata, dict) else {}
    summary = metadata.get("summary")
    lifecycle = metadata.get("lifecycle")
    source_type = str(metadata.get("source_type") or "")
    relation_predicate = str(metadata.get("predicate") or "").lower()
    summary_kind = str(summary.get("kind") or "").lower() if isinstance(summary, dict) else ""
    lifecycle_tier = str(lifecycle.get("tier") or "").lower() if isinstance(lifecycle, dict) else ""
    confabulation_risk = bool(metadata.get("confabulation_risk")) or (
        isinstance(summary, dict) and bool(summary.get("confabulation_risk"))
    ) or (isinstance(lifecycle, dict) and bool(lifecycle.get("confabulation_risk")))
    return (
        summary_kind in {"abstractive_gist", "statistical_trace"}
        or lifecycle_tier in {"abstractive_gist", "statistical_trace"}
        or source_type in {"consolidation-summary", "statistical-trace"}
        or (hit.kind == "relation" and relation_predicate == "summary-derived-gist")
        or confabulation_risk
    )


def is_retired_summary_metadata(metadata: object) -> bool:
    if not isinstance(metadata, dict):
        return False
    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        return False
    status = str(summary.get("status") or "").lower()
    return status in {"retired", "superseded", "stale"} or bool(
        summary.get("retired_at") or summary.get("superseded_by")
    )


def query_mode_from_filter(filt: Mapping[str, Any] | None) -> str | None:
    """Return a requested retrieve query_mode, or None for the default path."""

    if not isinstance(filt, Mapping):
        return None
    raw = filt.get("query_mode")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"unsupported query_mode: {raw!r}")
    mode = raw.strip()
    return mode or None


def require_supported_query_mode(mode: str | None) -> str | None:
    """Deny unknown retrieve modes; missing/blank mode stays on the default path."""

    if mode is None:
        return None
    if mode not in SUPPORTED_QUERY_MODES:
        raise ValueError(f"unsupported query_mode: {mode}")
    return mode


def is_raptor_summary_item(item: Any) -> bool:
    return is_raptor_summary_metadata(_item_field(item, "source_type"), _item_field(item, "metadata"))


def is_raptor_summary_metadata(source_type: object, metadata: object) -> bool:
    if str(source_type or "") != "consolidation-summary":
        return False
    return raptor_level_of(metadata) is not None


def raptor_level_of(metadata: object) -> int | None:
    if not isinstance(metadata, Mapping):
        return None
    summary = metadata.get("summary")
    raw: object = None
    if isinstance(summary, Mapping) and summary.get("raptor_level") is not None:
        raw = summary.get("raptor_level")
    elif metadata.get("raptor_level") is not None:
        raw = metadata.get("raptor_level")
    if raw is None:
        return None
    try:
        level = int(raw)
    except (TypeError, ValueError):
        return None
    return level if level > 0 else None


def raptor_source_cids(metadata: object) -> list[str]:
    if not isinstance(metadata, Mapping):
        return []
    cids: list[str] = []

    def add(values: object) -> None:
        if not isinstance(values, list):
            return
        for value in values:
            cid = str(value)
            if cid and cid not in cids:
                cids.append(cid)

    summary = metadata.get("summary") if isinstance(metadata.get("summary"), Mapping) else {}
    add(summary.get("source_evidence_cids") if isinstance(summary, Mapping) else None)
    add(metadata.get("source_evidence_cids"))
    return cids


def iter_raptor_summary_items(ops: Any, tenant_id: str, branch: str) -> list[Any]:
    """Load RAPTOR nodes from the engine seam, then fall back to tenant export."""

    list_fn = getattr(ops, "list_raptor_summaries", None)
    if callable(list_fn):
        items = [item for item in list(list_fn(tenant_id, branch) or []) if is_raptor_summary_item(item)]
        return sorted(items, key=lambda item: str(_item_field(item, "cid") or ""))
    export_fn = getattr(ops, "export_tenant", None)
    if not callable(export_fn):
        return []
    snapshot = export_fn(tenant_id)
    evidence = snapshot.get("evidence") if isinstance(snapshot, Mapping) else None
    rows: list[Any] = []
    for item in evidence or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("branch") or "main") != branch:
            continue
        if item.get("erased"):
            continue
        if not is_raptor_summary_item(item):
            continue
        rows.append(item)
    return sorted(rows, key=lambda item: str(item.get("cid") or ""))


def classify_raptor_node(
    item: Any,
    *,
    tenant_id: str,
    branch: str,
    filt: Mapping[str, Any],
    policy: OperatingPolicy,
) -> tuple[bool, str]:
    """Return whether a RAPTOR node is readable in the caller scope, plus a deny reason."""

    return classify_scoped_evidence(
        item,
        tenant_id=tenant_id,
        branch=branch,
        filt=filt,
        policy=policy,
    )


def classify_scoped_evidence(
    item: Any,
    *,
    tenant_id: str,
    branch: str,
    filt: Mapping[str, Any],
    policy: OperatingPolicy,
) -> tuple[bool, str]:
    """Return whether an evidence row is readable in the caller scope."""

    item_tenant = str(_item_field(item, "tenant_id") or "")
    item_branch = str(_item_field(item, "branch") or "main")
    if item_tenant != tenant_id:
        return False, "foreign_tenant"
    if item_branch != branch:
        return False, "foreign_branch"
    if bool(_item_field(item, "erased")):
        return False, "erased"
    metadata = _item_field(item, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if is_retired_summary_metadata(metadata):
        return False, "retired_or_superseded"
    if metadata.get("quarantine_reason") and not filt.get("include_quarantined"):
        return False, "quarantined"
    try:
        trust_tier = int(_item_field(item, "trust_tier") or 0)
        sensitivity = int(_item_field(item, "sensitivity") or 0)
    except (TypeError, ValueError):
        return False, "hidden"
    include_quarantined = bool(filt.get("include_quarantined", False))
    default_max_trust = int(policy.max_trust_tier)
    if include_quarantined:
        default_max_trust = max(default_max_trust, 5)
    try:
        max_trust = int(filt.get("max_trust_tier", filt.get("min_trust_tier", default_max_trust)))
    except (TypeError, ValueError):
        max_trust = default_max_trust
    if trust_tier > max_trust:
        return False, "trust_ceiling"
    max_sensitivity = effective_max_sensitivity(filt, policy.max_sensitivity)
    if sensitivity > max_sensitivity:
        return False, "sensitivity_ceiling"
    access_policy = _item_field(item, "access_policy") or {}
    if not isinstance(access_policy, Mapping):
        access_policy = {}
    decision = may_read_item(
        item_tenant_id=item_tenant,
        sensitivity=sensitivity,
        access_policy=access_policy,
        context=filt,
        policy_max_sensitivity=policy.max_sensitivity,
        status="active",
        erased=bool(_item_field(item, "erased")),
    )
    if not decision.allowed:
        reason = str(decision.reason or "hidden")
        if reason == "s4_raw_not_retrievable":
            return False, "sensitivity_ceiling"
        if reason in {"tenant_mismatch", "policy_tenant_mismatch"}:
            return False, "foreign_tenant"
        return False, reason
    return True, ""


def global_sensemaking_projection(
    ops: Any,
    *,
    query: str,
    tenant_id: str,
    branch: str,
    filt: Mapping[str, Any],
    policy: OperatingPolicy,
    deep: bool = False,
) -> tuple[list[Hit], dict[str, Any]]:
    """Map readable RAPTOR nodes and reduce them under a stable node budget."""

    node_budget = _sensemaking_node_budget(filt, policy, deep=deep)
    items = iter_raptor_summary_items(ops, tenant_id, branch)
    readable_items: list[Any] = []
    policy_denied = 0
    hidden_source_dropped = 0
    denied_cids: set[str] = set()
    for item in items:
        cid = str(_item_field(item, "cid") or "")
        if not cid:
            continue
        allowed, _reason = classify_raptor_node(
            item,
            tenant_id=tenant_id,
            branch=branch,
            filt=filt,
            policy=policy,
        )
        if not allowed:
            policy_denied += 1
            denied_cids.add(cid)
            continue
        readable_items.append(item)
    validated_hits: dict[str, Hit] = {}
    validated_summary_ids: set[str] = set()
    for item in sorted(
        readable_items,
        key=lambda row: (raptor_level_of(_item_field(row, "metadata") or {}) or 0, str(_item_field(row, "cid") or "")),
    ):
        cid = str(_item_field(item, "cid") or "")
        hit = _raptor_node_hit(
            item,
            ops=ops,
            filt=filt,
            policy=policy,
            query=query,
            readable_summary_ids=validated_summary_ids,
            denied_cids=denied_cids,
        )
        if hit is None:
            hidden_source_dropped += 1
            continue
        validated_hits[cid] = hit
        validated_summary_ids.add(cid)

    mapped: list[Hit] = []
    source_cids: list[str] = []
    levels: set[int] = set()
    for item in readable_items:
        hit = validated_hits.get(str(_item_field(item, "cid") or ""))
        if hit is None:
            continue
        mapped.append(hit)
        level = int(hit.metadata.get("raptor_level") or 0)
        if level:
            levels.add(level)
        for source_cid in hit.metadata.get("source_evidence_cids") or []:
            if source_cid and source_cid not in source_cids:
                source_cids.append(source_cid)

    # Return the complete ranked candidate set so the shared pipeline can pack
    # tokens first and then fill the node budget from smaller surviving nodes.
    reduced, theme_roots, incomplete = _reduce_sensemaking_hits(
        mapped,
        node_budget=max(node_budget, len(mapped)),
        query=query,
    )
    exclusions: list[dict[str, Any]] = []
    if policy_denied:
        exclusions.append({"reason": "policy_denied", "count": policy_denied})
    if hidden_source_dropped:
        exclusions.append({"reason": "hidden_source", "count": hidden_source_dropped})
    kept_ids = {hit.id for hit in reduced}
    for hit in mapped:
        if hit.id not in kept_ids:
            exclusions.append({"cid": hit.id, "reason": "node_budget"})
    exclusions.sort(key=lambda item: (str(item.get("reason") or ""), str(item.get("cid") or ""), int(item.get("count") or 0)))
    report = {
        "version": GLOBAL_SENSEMAKING_VERSION,
        "query_mode": GLOBAL_SENSEMAKING_MODE,
        "data_only": True,
        "source_cids": source_cids,
        "mapped_node_cids": [hit.id for hit in mapped],
        "theme_root_cids": theme_roots,
        "raptor_levels": sorted(levels),
        "map_count": len(mapped),
        "reduce_count": len(reduced),
        "exclusions": exclusions,
        "budget": {
            "token_budget": int(policy.token_budget),
            "used_tokens": 0,
            "node_budget": node_budget,
            "used_nodes": len(reduced),
        },
        "incomplete_theme_coverage": incomplete,
        "abstention_reason": "incomplete_theme_coverage" if incomplete else None,
        "query": query,
    }
    return reduced, report


def _sensemaking_node_budget(filt: Mapping[str, Any], policy: OperatingPolicy, *, deep: bool) -> int:
    raw = filt.get("sensemaking_node_budget")
    if raw is None:
        return max(1, int(policy.deep_top_k if deep else policy.top_k))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, int(policy.deep_top_k if deep else policy.top_k))


def _raptor_node_hit(
    item: Any,
    *,
    ops: Any,
    filt: Mapping[str, Any],
    policy: OperatingPolicy,
    query: str,
    readable_summary_ids: set[str],
    denied_cids: set[str],
) -> Hit | None:
    cid = str(_item_field(item, "cid") or "")
    tenant_id = str(_item_field(item, "tenant_id") or "")
    branch = str(_item_field(item, "branch") or "main")
    metadata = _item_field(item, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    level = raptor_level_of(metadata)
    if not cid or level is None:
        return None
    access_policy = _item_field(item, "access_policy") or {}
    if not isinstance(access_policy, Mapping):
        access_policy = {}
    decision = may_read_item(
        item_tenant_id=tenant_id,
        sensitivity=int(_item_field(item, "sensitivity") or 0),
        access_policy=access_policy,
        context=filt,
        policy_max_sensitivity=policy.max_sensitivity,
        status="active",
        erased=bool(_item_field(item, "erased")),
    )
    if not decision.allowed:
        return None
    if decision.redacted:
        return None
    content = str(_item_field(item, "content") or "")
    text, privacy = apply_text_redactions(content, access_policy, decision)
    if not text:
        return None
    text = _redact_denied_cids(text, denied_cids)
    if not text:
        return None
    referenced = raptor_source_cids(metadata)
    source_cids, hidden_source, source_reality_classes = _revalidate_source_cids(
        ops,
        referenced,
        tenant_id=tenant_id,
        branch=branch,
        filt=filt,
        policy=policy,
    )
    if hidden_source:
        return None
    text = _redact_denied_cids(text, set(referenced) - set(source_cids))
    summary = dict(metadata["summary"]) if isinstance(metadata.get("summary"), dict) else {}
    for key in ("child_summary_cids", "source_summary_cids"):
        raw_children = summary.get(key)
        if isinstance(raw_children, list):
            children = [str(child) for child in raw_children if str(child)]
            if any(child not in readable_summary_ids for child in children):
                return None
            summary[key] = children
    summary["source_evidence_cids"] = list(source_cids)
    provenance = [cid, *source_cids]
    return Hit(
        id=cid,
        kind="evidence",
        tenant_id=tenant_id,
        branch=branch,
        text=text,
        score=float(lexical_score(query, text)),
        channel=GLOBAL_SENSEMAKING_CHANNEL,
        provenance=provenance,
        trust_tier=int(_item_field(item, "trust_tier") or 0),
        sensitivity=int(_item_field(item, "sensitivity") or 0),
        metadata={
            "source_type": str(_item_field(item, "source_type") or "consolidation-summary"),
            "summary": summary,
            "raptor_level": level,
            "source_evidence_cids": list(source_cids),
            "query_mode": GLOBAL_SENSEMAKING_MODE,
            "memory_type": GLOBAL_SENSEMAKING_MODE,
            "data_only": True,
            "privacy": privacy,
            "source_reality_classes": dict(source_reality_classes),
            "reality_class": _aggregate_raptor_source_reality(source_reality_classes),
        },
    )


def _revalidate_source_cids(
    ops: Any,
    source_cids: Sequence[str],
    *,
    tenant_id: str,
    branch: str,
    filt: Mapping[str, Any],
    policy: OperatingPolicy,
) -> tuple[list[str], bool, dict[str, str]]:
    get_evidence = getattr(ops, "get_evidence", None)
    readable: list[str] = []
    source_reality_classes: dict[str, str] = {}
    hidden = False
    for cid in source_cids:
        if not cid:
            continue
        if not callable(get_evidence):
            hidden = True
            continue
        evidence = get_evidence(tenant_id, cid, branch)
        if evidence is None:
            hidden = True
            continue
        allowed, _reason = classify_scoped_evidence(
            evidence,
            tenant_id=tenant_id,
            branch=branch,
            filt=filt,
            policy=policy,
        )
        if not allowed:
            hidden = True
            continue
        access_policy = _item_field(evidence, "access_policy") or {}
        if not isinstance(access_policy, Mapping):
            access_policy = {}
        decision = may_read_item(
            item_tenant_id=tenant_id,
            sensitivity=int(_item_field(evidence, "sensitivity") or 0),
            access_policy=access_policy,
            context=filt,
            policy_max_sensitivity=policy.max_sensitivity,
            status="active",
            erased=bool(_item_field(evidence, "erased")),
        )
        if not decision.allowed or decision.redacted:
            hidden = True
            continue
        if cid not in readable:
            readable.append(cid)
            source_reality_classes[cid] = _classify_raptor_source_reality(evidence)
    return readable, hidden, source_reality_classes


def _preserve_source_reality_class(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    aliases = {
        "grounded": "grounded",
        "evidence_grounded": "grounded",
        "external_grounded": "grounded",
        "observed": "grounded",
        "user_grounded": "grounded",
        "self_generated": "self_generated",
        "self": "self_generated",
        "generated": "self_generated",
        "assistant_generated": "self_generated",
        "simulation": "simulated",
        "simulated": "simulated",
        "externally_suggested": "externally_suggested",
        "suggested": "externally_suggested",
        "external": "externally_suggested",
        "untrusted_suggestion": "externally_suggested",
        "unknown": "unknown",
    }
    return aliases.get(value.strip().lower().replace("-", "_"))


def _classify_raptor_source_reality(item: Any) -> str:
    metadata = _item_field(item, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    explicit = _preserve_source_reality_class(metadata.get("reality_class"))
    source_type = str(_item_field(item, "source_type") or "").lower()
    actor = str(_item_field(item, "actor") or "").lower()
    if any(marker in source_type for marker in ("simulation", "synthetic", "generated", "hypothesis")):
        base_class = "simulated"
    elif any(marker in source_type for marker in ("summary", "trace", "analysis", "consolidation")):
        base_class = "self_generated"
    elif actor == "assistant":
        base_class = "self_generated"
    elif actor in {"system", "tool"} and any(
        marker in source_type for marker in ("scratchpad", "workspace", "thought", "reflection")
    ):
        base_class = "self_generated"
    elif actor == "external" or int(_item_field(item, "trust_tier") or 0) >= 2:
        base_class = "externally_suggested"
    else:
        base_class = "grounded"
    if explicit == "grounded" and base_class != "grounded":
        return "unknown"
    return explicit or base_class


def _aggregate_raptor_source_reality(source_reality_classes: Mapping[str, str]) -> str:
    classes = [item for item in source_reality_classes.values() if item]
    if not classes:
        return "unknown"
    if all(item == "grounded" for item in classes):
        return "grounded"
    if "self_generated" in classes:
        return "self_generated"
    if "simulated" in classes:
        return "simulated"
    if "externally_suggested" in classes:
        return "externally_suggested"
    return "unknown"


def _reduce_sensemaking_hits(
    mapped: list[Hit],
    *,
    node_budget: int,
    query: str,
) -> tuple[list[Hit], list[str], bool]:
    if not mapped:
        return [], [], False
    for hit in mapped:
        hit.score = float(lexical_score(query, hit.text))
    child_to_parent = _sensemaking_child_to_parent(mapped)
    groups: dict[str, list[Hit]] = {}
    for hit in mapped:
        root_id = _sensemaking_theme_root(hit.id, child_to_parent)
        hit.metadata["theme_root_cid"] = root_id
        groups.setdefault(root_id, []).append(hit)
    for members in groups.values():
        members.sort(key=lambda item: (-item.score, -int(item.metadata.get("raptor_level") or 0), item.id))
    group_order = sorted(
        groups,
        key=lambda root_id: (-groups[root_id][0].score, root_id),
    )
    incomplete = node_budget < len(groups)
    selected_roots = group_order[: min(node_budget, len(group_order))]
    reduced: list[Hit] = []
    for root_id in selected_roots:
        if len(reduced) >= node_budget:
            break
        reduced.append(groups[root_id][0])
    if len(reduced) < node_budget:
        taken = {hit.id for hit in reduced}
        leftover = [
            hit
            for root_id in selected_roots
            for hit in groups[root_id]
            if hit.id not in taken
        ]
        leftover.sort(key=lambda item: (-item.score, -int(item.metadata.get("raptor_level") or 0), item.id))
        for hit in leftover:
            if len(reduced) >= node_budget:
                break
            reduced.append(hit)
    reduced.sort(key=lambda item: (-item.score, -int(item.metadata.get("raptor_level") or 0), item.id))
    return reduced, selected_roots if incomplete else group_order, incomplete


def _sensemaking_child_to_parent(hits: Sequence[Hit]) -> dict[str, str]:
    known = {hit.id for hit in hits}
    mapping: dict[str, str] = {}
    for hit in hits:
        summary = hit.metadata.get("summary") if isinstance(hit.metadata, dict) else {}
        if not isinstance(summary, Mapping):
            continue
        children = list(summary.get("child_summary_cids") or []) + list(summary.get("source_summary_cids") or [])
        for child in children:
            child_id = str(child)
            if child_id in known:
                mapping[child_id] = hit.id
    return mapping


def _sensemaking_theme_root(node_id: str, child_to_parent: Mapping[str, str]) -> str:
    current = node_id
    seen: set[str] = set()
    while current in child_to_parent and current not in seen:
        seen.add(current)
        current = child_to_parent[current]
    return current


def _redact_denied_cids(text: str, denied_cids: set[str]) -> str:
    redacted = text
    for cid in sorted(denied_cids, key=len, reverse=True):
        if cid:
            redacted = redacted.replace(cid, "[redacted]")
    return redacted


def _item_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def apply_activation_scores(hits: Sequence[Hit], policy: OperatingPolicy, *, now: datetime | None = None) -> list[Hit]:
    """Apply blueprint-style activation scoring to already retrieved hits."""

    if not hits:
        return []
    moment = now or utc_now()
    max_relevance = max((max(hit.score, 0.0) for hit in hits), default=0.0)
    weights = dict(policy.activation_weights)
    total_weight = max(sum(max(float(value), 0.0) for value in weights.values()), 0.01)
    # ACT-R spreading activation (blueprint §22.4: the `w_s · spreading(m, q)` term).
    # It is opt-in via a `spreading` activation weight so the default policy — and
    # the config-drift baseline that pins it — stay byte-identical. When enabled,
    # each memory gains activation from the co-retrieved memories it is associated
    # with (shared provenance / entities), with an explicit per-hit override.
    include_spreading = "spreading" in weights
    spreading_by_id = _spreading_activation(hits) if include_spreading else {}
    activated: list[Hit] = []
    for hit in hits:
        semantic = max(hit.score, 0.0) / max(max_relevance, 0.01)
        confidence = _bounded_float(hit.metadata.get("confidence", 0.7), default=0.7)
        access_count = _bounded_int(hit.metadata.get("access_count", 0))
        recency = _recency_score(hit.metadata.get("last_accessed"), moment, policy.decay)
        actr_d = max(float(getattr(policy, "actr_decay", 0.0)), 0.0)
        if actr_d > 0.0:
            age_days = _age_days(hit.metadata.get("last_accessed"), moment)
            raw_base_level = math.log1p(access_count) - actr_d * math.log1p(age_days)
            base_level = max(
                0.0,
                min(1.0, (raw_base_level + actr_d * math.log1p(_BASE_LEVEL_AGE_REF)) / math.log(11)),
            )
        else:
            base_level = min(1.0, math.log1p(access_count) / math.log(11))
        importance = confidence * trust_weight(hit.trust_tier)
        activation_numerator = (
            max(weights.get("base_level", 0.0), 0.0) * base_level
            + max(weights.get("semantic", 0.0), 0.0) * semantic
            + max(weights.get("importance", 0.0), 0.0) * importance
            + max(weights.get("recency", 0.0), 0.0) * recency
        )
        components = {
            "base_level": round(base_level, 6),
            "semantic": round(semantic, 6),
            "importance": round(importance, 6),
            "recency": round(recency, 6),
        }
        if include_spreading:
            spreading = spreading_by_id.get(hit.id, 0.0)
            activation_numerator += max(weights.get("spreading", 0.0), 0.0) * spreading
            components["spreading"] = round(spreading, 6)
        activation = activation_numerator / total_weight
        metadata = {
            **hit.metadata,
            "activation": {
                "score": round(max(0.0, min(1.0, activation)), 6),
                "components": components,
            },
        }
        activated.append(
            Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=max(hit.score, 0.0) * (0.5 + max(0.0, min(1.0, activation))),
                channel=hit.channel,
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata=metadata,
            )
        )
    return sorted(activated, key=lambda item: item.score, reverse=True)


def activation_explain(hits: Sequence[Hit], policy: OperatingPolicy) -> dict[str, object]:
    return {
        "weights": dict(policy.activation_weights),
        "applied": True,
        "hits": [
            {
                "id": hit.id,
                "kind": hit.kind,
                "score": round(hit.score, 6),
                "activation": hit.metadata.get("activation", {}),
            }
            for hit in hits
        ],
    }


def _spreading_activation(hits: Sequence[Hit]) -> dict[str, float]:
    """Deterministic ACT-R associative spreading signal per hit id (§22.4).

    Spreading is estimated as the fraction of *other* retrieved hits that share
    an association cue (provenance id, subject/object/predicate, or an entity
    link) with the hit — co-activation within the retrieved set. An explicit
    ``metadata['spreading_activation']`` (e.g. a graph-precomputed signal, see
    :class:`GraphSignalCache`) overrides the derived estimate.
    """

    cue_sets: list[set[str]] = []
    for hit in hits:
        cues = {str(item).lower() for item in hit.provenance if str(item)}
        meta = hit.metadata if isinstance(hit.metadata, dict) else {}
        for key in ("subject", "object", "predicate", "entity"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                cues.add(value.lower())
        entities = meta.get("entities")
        if isinstance(entities, (list, tuple)):
            cues.update(str(item).lower() for item in entities if str(item))
        cue_sets.append(cues)
    total = len(hits)
    signals: dict[str, float] = {}
    for index, hit in enumerate(hits):
        meta = hit.metadata if isinstance(hit.metadata, dict) else {}
        override = meta.get("spreading_activation")
        if override is not None:
            signals[hit.id] = _bounded_float(override, default=0.0)
            continue
        if total <= 1 or not cue_sets[index]:
            signals[hit.id] = 0.0
            continue
        shared = sum(1 for other in range(total) if other != index and cue_sets[index] & cue_sets[other])
        signals[hit.id] = shared / (total - 1)
    return signals


def marginal_gain_cutoff(
    hits: Sequence[Hit],
    *,
    token_budget: int,
    cost: float = 0.05,
    redundancy_lambda: float = 0.5,
    token_estimator: Callable[[Hit], int] | None = None,
) -> tuple[list[Hit], int]:
    """Assemble context by expected marginal gain (ACT-R "retrieve while C < pG").

    Walks hits in rank order, admitting each while its expected marginal gain —
    relevance discounted by lexical redundancy with the already-selected set —
    exceeds ``cost`` and the running token estimate stays within ``token_budget``
    (blueprint §22.4 marginal-gain / context-budget assembly). Returns the
    selected hits plus the estimated tokens used. Deterministic and side-effect
    free, so an engine can swap it in for a fixed top-k truncation.
    """

    if token_budget < 0:
        raise ValueError("token_budget must be non-negative")
    estimate = token_estimator or (lambda hit: max(1, len(hit.text.split())))
    max_score = max((max(hit.score, 0.0) for hit in hits), default=0.0) or 1.0
    selected: list[Hit] = []
    used = 0
    for hit in hits:
        tokens = estimate(hit)
        if used + tokens > token_budget:
            break
        relevance = max(hit.score, 0.0) / max_score
        redundancy = max((lexical_score(hit.text, chosen.text) for chosen in selected), default=0.0)
        marginal = relevance - redundancy_lambda * redundancy
        if selected and marginal < cost:
            break
        selected.append(hit)
        used += tokens
    return selected, used


class GraphSignalCache:
    """Cache of graph-channel signals for fast-path fusion (blueprint §22.2).

    The deep path runs a live PPR traversal; the fast path must fuse a graph
    signal without paying that cost. Deep retrieval (or a consolidation job)
    calls :meth:`put` to cache the graph hits for a tenant/branch, and the fast
    path calls :meth:`fast_signal` to fold the cached signal into RRF fusion.
    Cached hits carry ``metadata['graph_signal_cached'] = True`` so downstream
    scoring can distinguish cached graph evidence from a live traversal.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], list[Hit]] = {}

    def put(self, tenant_id: str, branch: str, hits: Sequence[Hit]) -> None:
        cached = [
            Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=hit.score,
                channel=hit.channel,
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata={**hit.metadata, "graph_signal_cached": True},
            )
            for hit in hits
        ]
        self._store[(tenant_id, branch)] = sorted(cached, key=lambda item: item.score, reverse=True)

    def fast_signal(
        self,
        tenant_id: str,
        branch: str,
        k: int,
        *,
        seeds: Sequence[str] | None = None,
    ) -> list[Hit]:
        if k <= 0:
            return []
        cached = self._store.get((tenant_id, branch), [])
        if seeds:
            seed_terms = {term.lower() for term in seeds if term}
            filtered = [hit for hit in cached if seed_terms & set(tokenize(hit.text))]
            cached = filtered or cached
        return cached[: max(k, 0)]

    def invalidate(self, tenant_id: str, branch: str) -> None:
        self._store.pop((tenant_id, branch), None)

    def clear(self) -> None:
        self._store.clear()


# Blueprint §22.2 memory channels fused alongside exact/lexical/dense/graph.
MEMORY_CHANNELS: frozenset[str] = frozenset({"preference", "procedure", "lesson"})


def scored_channel_for_hit(*, kind: str, base_channel: str) -> str:
    """Map a scored candidate to its retrieval channel name.

    Preference rows remain first-class memory channel hits (§22.2 / residual #8)
    rather than being relabeled as generic lexical/dense after scoring.
    """

    if kind == "preference":
        return "preference"
    return base_channel


def build_channel_hits(
    items: Sequence[Mapping[str, object]],
    *,
    channel: str,
    tenant_id: str,
    branch: str,
    kind: str = "assertion",
    default_trust_tier: int = 0,
) -> list[Hit]:
    """Build channel-tagged hits for the preference/procedure/lesson channels.

    Blueprint §22.2 fuses preference, procedure, and lesson channels alongside
    exact/lexical/dense/graph — "what make this *memory*, not document RAG". Those
    channels read from engine-owned stores, so the engine passes already-loaded
    records as mappings and this helper normalizes them into uniformly-shaped,
    channel-tagged :class:`Hit` objects ready for RRF fusion. ``channel`` should
    be one of ``preference`` / ``procedure`` / ``lesson``.
    """

    if channel not in MEMORY_CHANNELS:
        raise ValueError(
            f"memory channel must be one of {sorted(MEMORY_CHANNELS)}; got {channel!r}"
        )

    hits: list[Hit] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError(f"{channel} channel items must be mappings")
        hit_id = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not hit_id or not text:
            raise ValueError(f"{channel} channel item requires id and text")
        score_raw = item.get("score", 0.0)
        if isinstance(score_raw, bool):
            raise ValueError(f"{channel} channel item score must be numeric")
        try:
            score = float(score_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{channel} channel item score must be numeric") from exc
        metadata = dict(item.get("metadata") or {})  # type: ignore[arg-type]
        metadata.setdefault("channel_source", channel)
        hits.append(
            Hit(
                id=hit_id,
                kind=kind,  # type: ignore[arg-type]
                tenant_id=str(item.get("tenant_id") or tenant_id),
                branch=str(item.get("branch") or branch),
                text=text,
                score=score,
                channel=channel,
                provenance=[str(value) for value in (item.get("provenance") or []) if str(value)],  # type: ignore[union-attr]
                trust_tier=int(item.get("trust_tier", default_trust_tier)),  # type: ignore[arg-type]
                sensitivity=int(item.get("sensitivity", 0)),  # type: ignore[arg-type]
                metadata=metadata,
            )
        )
    return sorted(hits, key=lambda item: item.score, reverse=True)


def _working_field(item: object, name: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _working_datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"working-memory {field} must be timezone-aware") from exc
    else:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise ValueError(f"working-memory {field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _working_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _working_json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): value for key, value in value.items()}


def _working_task_text(*, task_id: str, kind: str, metadata: Mapping[str, Any]) -> str:
    values = [task_id, kind]
    for key in ("task", "task_description", "goal", "query", "topic", "task_terms"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    # Working-item identifiers commonly use task-foo / task_foo / task/foo.
    # Treat those separators as words for deterministic task matching.
    return re.sub(r"[_:/.-]+", " ", " ".join(values))


def working_memory_hits(
    items: Sequence[object],
    *,
    query: str,
    tenant_id: str,
    session_id: str | None,
    evaluated_at: datetime | str,
    branch: str = "main",
    limit: int | None = None,
    access_context: Mapping[str, Any] | None = None,
    policy_max_sensitivity: int | None = None,
    max_trust_tier: int | None = None,
) -> list[Hit]:
    """Rank active working items for one tenant/session at an explicit instant.

    The store owns authorization and provenance validation; this read-side
    adapter still repeats the tenant/session and half-open TTL checks so a
    caller cannot accidentally widen a working-memory read. Expired rows are
    ignored without mutation. Task relevance is deliberately weighted above
    content relevance, then blended with TTL-relative recency. Every result is
    copied into a ``Hit`` and marked as data so working text cannot become
    instruction authority downstream.
    """

    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return []
    if not isinstance(session_id, str) or not session_id.strip():
        return []
    clock = _working_datetime(evaluated_at, field="evaluated_at")
    candidates: list[dict[str, Any]] = []
    for item in items:
        item_tenant = _working_text(_working_field(item, "tenant_id"))
        item_session = _working_text(_working_field(item, "session_id"))
        item_metadata = _working_json_object(_working_field(item, "metadata", {}))
        item_branch = _working_field(item, "branch", item_metadata.get("branch"))
        if item_tenant != tenant_id or item_session != session_id:
            continue
        if item_branch is not None and _working_text(item_branch) != branch:
            continue
        if _working_text(_working_field(item, "status", "active")) != "active":
            continue
        try:
            created_at = _working_datetime(_working_field(item, "created_at"), field="created_at")
            expires_at = _working_datetime(_working_field(item, "expires_at"), field="expires_at")
        except ValueError:
            # A malformed row is not allowed to widen a read; the owning store
            # is responsible for surfacing its write-time validation error.
            continue
        if created_at > clock or clock >= expires_at:
            continue
        item_id = _working_text(_working_field(item, "item_id", _working_field(item, "id")))
        kind = _working_text(_working_field(item, "kind"))
        content = _working_text(_working_field(item, "content", _working_field(item, "text")))
        task_id = _working_text(_working_field(item, "task_id"))
        if not item_id or not kind or not content or not task_id:
            continue
        metadata = copy.deepcopy(item_metadata)
        evidence_ids = _working_field(item, "evidence_ids", _working_field(item, "provenance", []))
        if not isinstance(evidence_ids, (list, tuple)):
            evidence_ids = []
        provenance = [str(value) for value in evidence_ids if str(value).strip()]
        trust_value = _working_field(item, "trust_tier", metadata.get("trust_tier", 0))
        sensitivity_value = _working_field(item, "sensitivity", metadata.get("sensitivity", 0))
        if isinstance(trust_value, bool) or isinstance(sensitivity_value, bool):
            continue
        try:
            trust_tier = int(trust_value)
            sensitivity = int(sensitivity_value)
        except (TypeError, ValueError):
            continue
        if max_trust_tier is not None and trust_tier > max_trust_tier:
            continue
        access_policy = _working_json_object(_working_field(item, "access_policy", metadata.get("access_policy", {})))
        if access_context is not None:
            decision = may_read_item(
                item_tenant_id=tenant_id,
                sensitivity=sensitivity,
                access_policy=access_policy,
                context=access_context,
                policy_max_sensitivity=(
                    policy_max_sensitivity if policy_max_sensitivity is not None else sensitivity
                ),
                status="active",
                erased=False,
            )
            if not decision.allowed:
                continue
        else:
            policy_tenant = str(access_policy.get("tenant") or access_policy.get("tenant_id") or tenant_id)
            if policy_tenant != tenant_id or sensitivity >= 4:
                continue
            try:
                policy_max = access_policy.get("max_sensitivity")
                if policy_max is not None and sensitivity > int(policy_max):
                    continue
            except (TypeError, ValueError):
                continue
            if access_policy.get("restricted") or access_policy.get("hold"):
                continue
            if any(
                key in access_policy
                for key in (
                    "allow_principals",
                    "allow_roles",
                    "require_capabilities",
                    "scope",
                    "scopes",
                    "purpose",
                    "purposes",
                    "residency",
                    "residencies",
                    "lawful_basis",
                    "min_role_for_raw",
                )
            ):
                continue
            decision = None
        content_for_hit = content
        privacy_metadata: dict[str, Any] = {}
        if decision is not None:
            content_for_hit, privacy_metadata = apply_text_redactions(content, access_policy, decision)
            if not content_for_hit:
                continue
        if privacy_metadata:
            metadata["privacy"] = privacy_metadata
        capability_tags = _working_field(item, "capability_tags", metadata.get("capability_tags"))
        if isinstance(capability_tags, (list, tuple, set)):
            metadata["capability_tags"] = [str(value) for value in capability_tags if str(value).strip()]
        metadata["access_policy"] = copy.deepcopy(access_policy)
        for field_name in ("reality_class", "source_type", "source_identity"):
            field_value = _working_field(item, field_name)
            if field_value is not None:
                metadata.setdefault(field_name, field_value)
        task_text = _working_task_text(task_id=task_id, kind=kind, metadata=metadata)
        task_raw = lexical_score(query, task_text)
        content_raw = lexical_score(query, content)
        ttl_seconds = max((expires_at - created_at).total_seconds(), 1.0)
        age_seconds = max((clock - created_at).total_seconds(), 0.0)
        recency = max(0.0, min(1.0, 1.0 - (age_seconds / ttl_seconds)))
        candidates.append(
            {
                "item": item,
                "item_id": item_id,
                "kind": kind,
                "content": content_for_hit,
                "task_id": task_id,
                "metadata": metadata,
                "provenance": provenance,
                "trust_tier": trust_tier,
                "sensitivity": sensitivity,
                "created_at": created_at,
                "expires_at": expires_at,
                "task_raw": task_raw,
                "content_raw": content_raw,
                "recency": recency,
            }
        )

    max_task = max((float(row["task_raw"]) for row in candidates), default=0.0)
    max_content = max((float(row["content_raw"]) for row in candidates), default=0.0)
    ranked: list[Hit] = []
    for row in candidates:
        task_relevance = min(1.0, float(row["task_raw"]) / max(max_task, 1.0))
        content_relevance = min(1.0, float(row["content_raw"]) / max(max_content, 1.0))
        relevance = 0.8 * task_relevance + 0.2 * content_relevance
        score = WORKING_MEMORY_TASK_WEIGHT * relevance + WORKING_MEMORY_RECENCY_WEIGHT * row["recency"]
        metadata = dict(row["metadata"])
        metadata.update(
            {
                "memory_type": "working",
                "working_item_id": row["item_id"],
                "session_id": session_id,
                "task_id": row["task_id"],
                "working_memory_route": WORKING_MEMORY_ROUTE_VERSION,
                "working_memory": {
                    "task_relevance": round(task_relevance, 6),
                    "content_relevance": round(content_relevance, 6),
                    "relevance": round(relevance, 6),
                    "recency": round(row["recency"], 6),
                    "evaluated_at": clock.isoformat(),
                    "created_at": row["created_at"].isoformat(),
                    "expires_at": row["expires_at"].isoformat(),
                    "data_only": True,
                    "promotion_gate_required": True,
                },
            }
        )
        metadata["retrieved_text"] = sanitize_retrieved_text(row["content"], row["trust_tier"])
        ranked.append(
            Hit(
                id=row["item_id"],
                # Keep transient working items out of durable-evidence identity
                # and access-marking paths.
                kind="working",
                tenant_id=tenant_id,
                branch=branch,
                text=row["content"],
                score=round(score, 12),
                channel=WORKING_MEMORY_CHANNEL,
                provenance=list(row["provenance"]),
                trust_tier=row["trust_tier"],
                sensitivity=row["sensitivity"],
                metadata=metadata,
            )
        )
    ranked.sort(
        key=lambda hit: (
            -hit.score,
            -float(hit.metadata["working_memory"]["task_relevance"]),
            -float(hit.metadata["working_memory"]["recency"]),
            hit.id,
        )
    )
    if limit is not None:
        return ranked[: max(0, int(limit))]
    return ranked


def build_working_memory_hits(
    items: Sequence[object],
    *,
    query: str,
    tenant_id: str,
    session_id: str | None,
    evaluated_at: datetime | str,
    branch: str = "main",
    limit: int | None = None,
    access_context: Mapping[str, Any] | None = None,
    policy_max_sensitivity: int | None = None,
    max_trust_tier: int | None = None,
) -> list[Hit]:
    """Named adapter alias used by engine lanes and retrieval tests."""

    return working_memory_hits(
        items,
        query=query,
        tenant_id=tenant_id,
        session_id=session_id,
        evaluated_at=evaluated_at,
        branch=branch,
        limit=limit,
        access_context=access_context,
        policy_max_sensitivity=policy_max_sensitivity,
        max_trust_tier=max_trust_tier,
    )


def working_memory_route_hits(
    items: Sequence[object],
    *,
    query: str,
    tenant_id: str,
    session_id: str,
    evaluated_at: datetime,
    branch: str,
    limit: int,
    access_context: Mapping[str, Any],
    policy_max_sensitivity: int,
    max_trust_tier: int,
) -> list[Hit]:
    """Adapt the Phase-3 security-aware working route to the shared plane shape."""

    hits = build_working_memory_hits(
        items,
        query=query,
        tenant_id=tenant_id,
        session_id=session_id,
        evaluated_at=evaluated_at,
        branch=branch,
        limit=limit,
        access_context=access_context,
        policy_max_sensitivity=policy_max_sensitivity,
        max_trust_tier=max_trust_tier,
    )
    for hit in hits:
        raw_id = hit.id
        hit.metadata.update(
            {
                "memory_plane": WORKING_MEMORY_CHANNEL,
                "working_memory_id": raw_id,
            }
        )
    return hits


def _recency_score(value: object, now: datetime, decay: float) -> float:
    accessed = value if isinstance(value, datetime) else parse_dt(value)
    if accessed is None:
        return 0.0
    accessed = accessed.astimezone(UTC) if accessed.tzinfo else accessed.replace(tzinfo=UTC)
    age_days = max((now - accessed).total_seconds(), 0.0) / 86_400.0
    return 1.0 / (1.0 + max(decay, 0.0) * age_days)


_BASE_LEVEL_AGE_REF = 30.0


def _age_days(value: object, now: datetime) -> float:
    accessed = value if isinstance(value, datetime) else parse_dt(value)
    if accessed is None:
        return _BASE_LEVEL_AGE_REF
    accessed = accessed.astimezone(UTC) if accessed.tzinfo else accessed.replace(tzinfo=UTC)
    return max((now - accessed).total_seconds(), 0.0) / 86_400.0


def _bounded_float(value: object, *, default: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def _bounded_int(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


class _ProviderHttpError(ValueError):
    """HTTP-status failure from a provider endpoint.

    Subclasses ``ValueError`` so existing callers' error handling is
    unchanged; carries the status code so batch callers can feature-detect a
    missing batch route (4xx) without parsing the message.
    """

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def _post_json(url: str, payload: dict[str, object], api_key: str | None, timeout: float) -> dict[str, object]:
    validated_url = _validate_http_provider_config(url, timeout)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with safe_urlopen(request, validated=validated_url, timeout=timeout) as response:
            decoded = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        reason = str(getattr(exc, "reason", "") or "").strip()
        suffix = f" {reason}" if reason else ""
        raise _ProviderHttpError(
            f"provider returned HTTP {exc.code}{suffix}; response body omitted",
            code=int(exc.code),
        ) from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"provider request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ValueError("provider response must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("provider response must be a JSON object")
    return parsed


def _extract_embedding(response: dict[str, object]) -> list[float]:
    if isinstance(response.get("embedding"), list):
        return _coerce_vector(response["embedding"], field="embedding")  # type: ignore[arg-type,index]
    data = response.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict) and isinstance(data[0].get("embedding"), list):
        return _coerce_vector(data[0]["embedding"], field="data[0].embedding")
    raise ValueError("embedding response must contain `embedding` or `data[0].embedding`")


def _extract_embeddings_batch(response: dict[str, object], expected: int) -> list[list[float]]:
    """Parse an OpenAI-style batch embedding response into input order.

    Entries are placed by their ``index`` field (defaulting to list position),
    so a server may return them out of order; every input index must be
    covered exactly once.
    """
    data = response.get("data")
    if not isinstance(data, list) or len(data) != expected:
        raise ValueError("batch embedding response must contain a `data` list matching the input length")
    vectors: list[list[float] | None] = [None] * expected
    for position, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise ValueError("batch embedding entries must contain `embedding`")
        index = item.get("index", position)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < expected:
            raise ValueError("batch embedding entry index out of range")
        if vectors[index] is not None:
            raise ValueError("batch embedding entry index duplicated")
        vectors[index] = _coerce_vector(item["embedding"], field=f"data[{index}].embedding")
    if any(vector is None for vector in vectors):
        raise ValueError("batch embedding entries must cover every input index")
    return [vector for vector in vectors if vector is not None]


def _extract_rerank_scores(response: dict[str, object]) -> list[tuple[int, float]]:
    results = response.get("results")
    if not isinstance(results, list):
        raise ValueError("reranker response must contain `results`")
    scored: list[tuple[int, float]] = []
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("reranker results must be objects")
        index = item.get("index")
        score = item.get("score", item.get("relevance_score"))
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("reranker result index must be an integer")
        scored.append((index, _finite_float(score, field="reranker score")))
    if not scored:
        raise ValueError("reranker response must contain at least one scored result")
    return scored


def _normalize_vector(vector: Sequence[float], dims: int) -> list[float]:
    if dims <= 0:
        raise ValueError("embedding dimensions must be positive")
    adjusted = list(vector[:dims])
    if len(adjusted) < dims:
        adjusted.extend([0.0] * (dims - len(adjusted)))
    norm = math.sqrt(sum(value * value for value in adjusted))
    if norm == 0.0:
        raise ValueError("embedding response must contain a non-zero vector")
    return [value / norm for value in adjusted]


def _retrieval_allowed_internal_hosts() -> tuple[str, ...]:
    """Internal hostnames the HTTP embedding/reranker providers may reach.

    Self-hosted deployments serve the embedder/reranker on an isolated network
    (e.g. ``tei.mnemo.local``) whose name resolves to a private address. The
    network-safety guard blocks private/internal addresses by default; this
    allowlist is the explicit, operator-scoped escape hatch, matching the Vault
    and Ollama provider paths (``MNEMOSYNE_*_ALLOWED_INTERNAL_HOSTS``).
    """
    raw = os.environ.get("MNEMOSYNE_RETRIEVAL_ALLOWED_INTERNAL_HOSTS", "")
    return tuple(host.strip() for host in raw.split(",") if host.strip())


def _validate_http_provider_config(url: str, timeout: float):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("retrieval provider timeout must be positive")
    try:
        return validate_fetch_url(
            url,
            allow_insecure_localhost=True,
            allow_internal_hosts=_retrieval_allowed_internal_hosts(),
            purpose="retrieval provider URL",
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _coerce_vector(values: Sequence[object], *, field: str) -> list[float]:
    if not values:
        raise ValueError(f"{field} must contain at least one value")
    return [_finite_float(value, field=field) for value in values]


def _finite_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} values must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} values must be finite")
    return number
