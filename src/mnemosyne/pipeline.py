"""Engine-agnostic retrieve() orchestration (spec §4.0/§4.1, Phase-2 Task 1).

Before this module existed, ``LocalMemoryEngine.retrieve`` (engine.py) and
``PostgresEngine.retrieve`` (postgres_engine.py) carried two near-identical
~130-line copies of the retrieval pipeline. ``run_retrieval_pipeline`` is
LocalMemoryEngine's body moved verbatim (``self.`` -> ``ops.``,
``self.policy`` -> ``policy``); both engines now delegate to it, and future
engines (SqliteEngine) implement :class:`RetrievalPipelineOps` instead of
growing a third copy.

The Protocol was built by INVENTORY of every ``self.*`` call in the two
shipped retrieve() bodies (grounding R7's 13-helper inventory plus the three
channel searches and the ``adapters`` attribute). Divergences between the two
shipped bodies, from a line diff at extraction time:

* explain ``channels`` key names — Local reports ``dense_hash``/``lexical``/
  ``graph_ppr``, Postgres reports ``postgres_dense``/``postgres_lexical``/
  ``postgres_graph_ppr``. Parameterized as the ``retrieval_explain_channel_keys``
  ops attribute; every other difference was behavior-neutral (a local variable
  name, a no-op statement reorder of the calibration reads, and the placement
  of ``note = None``), so Local's ordering is the canonical body.

Workspace-broadcast filter handling (``workspace_broadcast_from_context`` ->
``strip_workspace_broadcast_filter``), activation, u-curve ordering, budget
fitting, calibration/abstention, and the full explain-dict assembly (incl.
read_marks, standing, reality_monitoring, schema_fast_path,
workspace_broadcast, workspace_retrieval_advisory, adapters, rails) live here;
engine-specific storage access stays behind the ops members.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.models import Hit, RetrievalResult, parse_dt, utc_now
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import (
    GLOBAL_SENSEMAKING_CHANNEL,
    GLOBAL_SENSEMAKING_MODE,
    QUERY_SUPPORT_THRESHOLD,
    PROSPECTIVE_MEMORY_CHANNEL,
    RetrievalAdapters,
    WORKING_MEMORY_CHANNEL,
    activation_explain,
    answer_grounding_floor_report,
    apply_activation_scores,
    apply_workspace_retrieval_advisory,
    gist_support_report,
    global_sensemaking_projection,
    query_mode_from_filter,
    query_support,
    prospective_memory_hits,
    require_supported_query_mode,
    schema_fast_path_rerank,
    semantic_entropy,
    strip_workspace_broadcast_filter,
    workspace_broadcast_from_context,
    working_memory_route_hits,
)
from mnemosyne.text import tokenize

#: Capability-tier default to overlap the dense/lexical/graph channel calls on
#: a 3-worker thread pool (registered in CONFIG-DRIFT-CHECKS.md). Operators can
#: still force the knob on/off explicitly. Channel identity and the RRF input
#: order stay exactly [dense, lexical, graph, prospective, working]; parallel results are
#: byte-identical (tests/test_engine_perf_lanes.py).
_PARALLEL_CHANNELS_ENV = "MNEMOSYNE_PARALLEL_CHANNELS"
_PARALLEL_CHANNELS_TRUTHY = {"1", "true", "yes", "on"}
_PARALLEL_CHANNELS_DEFAULT_CACHE: tuple[str | None, bool] | None = None

#: Default-OFF LRU for whole retrieval results. Entries are written only after
#: budget fitting, policy redaction, retrieved-text sanitization, and access
#: marking; callers get defensive copies. The cache key includes an engine
#: mutation token so write-on-read access marks and ordinary writes invalidate
#: stale result entries instead of replaying obsolete lifecycle scores.
_RESULT_CACHE_SIZE_ENV = "MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE"
_RESULT_CACHE: OrderedDict[tuple[Any, ...], RetrievalResult] = OrderedDict()
_RESULT_CACHE_LOCK = threading.Lock()
_RESULT_CACHE_EXPLAIN_KEY = "retrieval_result_cache"


def _parallel_channels_default_enabled() -> bool:
    """Default the overlap lane from the resolved capability tier.

    The capability probe may import optional acceleration libraries, so cache the
    resolved posture per explicit tier override. Hardware facts are stable for a
    process, while an operator-set ``MNEMOSYNE_PARALLEL_CHANNELS`` bypasses this
    helper entirely.
    """
    global _PARALLEL_CHANNELS_DEFAULT_CACHE
    override = os.environ.get("MNEMOSYNE_CAPABILITY_TIER")
    if _PARALLEL_CHANNELS_DEFAULT_CACHE is not None and _PARALLEL_CHANNELS_DEFAULT_CACHE[0] == override:
        return _PARALLEL_CHANNELS_DEFAULT_CACHE[1]

    from mnemosyne import capability

    tier, _ = capability.resolve_tier()
    enabled = tier != "floor"
    _PARALLEL_CHANNELS_DEFAULT_CACHE = (override, enabled)
    return enabled


def parallel_channels_enabled() -> bool:
    raw = os.environ.get(_PARALLEL_CHANNELS_ENV)
    if raw is not None:
        return raw.strip().lower() in _PARALLEL_CHANNELS_TRUTHY
    return _parallel_channels_default_enabled()


def retrieval_result_cache_size() -> int:
    raw = os.environ.get(_RESULT_CACHE_SIZE_ENV, "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _cache_fingerprint(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(value)


def _clone_hit(hit: Hit) -> Hit:
    return Hit(
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
        metadata=copy.deepcopy(hit.metadata),
    )


def _clone_result(result: RetrievalResult) -> RetrievalResult:
    return RetrievalResult(
        query=result.query,
        hits=[_clone_hit(hit) for hit in result.hits],
        confidence=result.confidence,
        abstained=result.abstained,
        uncertainty_note=result.uncertainty_note,
        token_budget=result.token_budget,
        used_tokens=result.used_tokens,
        explain=copy.deepcopy(result.explain),
    )


def _engine_result_cache_token(
    ops: RetrievalPipelineOps,
    *,
    tenant_id: str,
    branch: str,
    effective_filter: dict[str, Any],
) -> Any | None:
    token_fn = getattr(ops, "_retrieval_result_cache_token", None)
    if callable(token_fn):
        return token_fn(tenant_id, branch, effective_filter)
    token_fn = getattr(ops, "_retrieval_cache_token", None)
    if callable(token_fn):
        return token_fn(tenant_id, branch, effective_filter)
    store_version = getattr(ops, "_store_version", None)
    if store_version is not None:
        return ("local", id(ops), store_version)
    return None


def _adapter_cache_key(ops: RetrievalPipelineOps) -> tuple[Any, ...]:
    return (
        ops.adapters.embedding.name,
        ops.adapters.embedding.dims,
        ops.adapters.reranker.name,
        ops.adapters.lexical_backend,
        ops.adapters.graph_backend,
    )


def _result_cache_key(
    ops: RetrievalPipelineOps,
    *,
    query: str,
    tenant_id: str,
    branch: str,
    deep: bool,
    effective_filter: dict[str, Any],
    workspace_broadcast: dict[str, Any],
    k: int,
    graph_k: int,
    policy: OperatingPolicy,
) -> tuple[Any, ...] | None:
    if retrieval_result_cache_size() <= 0 or deep or workspace_broadcast.get("applied"):
        return None
    token = _engine_result_cache_token(
        ops,
        tenant_id=tenant_id,
        branch=branch,
        effective_filter=effective_filter,
    )
    if token is None:
        return None
    return (
        "retrieval-result-v1",
        _cache_fingerprint(token),
        query,
        tenant_id,
        branch,
        deep,
        k,
        graph_k,
        _cache_fingerprint(effective_filter),
        _cache_fingerprint(policy.to_dict()),
        _adapter_cache_key(ops),
    )


def _result_cache_get(key: tuple[Any, ...]) -> RetrievalResult | None:
    with _RESULT_CACHE_LOCK:
        cached = _RESULT_CACHE.get(key)
        if cached is None:
            return None
        _RESULT_CACHE.move_to_end(key)
        return _clone_result(cached)


def _result_cache_put(key: tuple[Any, ...], result: RetrievalResult) -> None:
    size = retrieval_result_cache_size()
    if size <= 0:
        return
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[key] = _clone_result(result)
        _RESULT_CACHE.move_to_end(key)
        while len(_RESULT_CACHE) > size:
            _RESULT_CACHE.popitem(last=False)


def _result_cache_explain(*, hit: bool, stored: bool) -> dict[str, Any]:
    return {
        "backend": "process_lru",
        "enabled": True,
        "hit": hit,
        "stored": stored,
    }


def _fast_graph_hits(hits: list[Hit], *, deep: bool) -> list[Hit]:
    if deep:
        return hits
    return [
        hit
        for hit in hits
        if not (
            hit.kind == "relation"
            and str((hit.metadata if isinstance(hit.metadata, dict) else {}).get("predicate") or "").lower()
            == "summary-derived-gist"
        )
    ]


def _working_route_requested(effective_filter: dict[str, Any]) -> bool:
    return any(
        key in effective_filter
        for key in (
            "session_id",
            "working_session_id",
            "evaluated_at",
            "working_evaluated_at",
        )
    )


def _working_session_id(effective_filter: dict[str, Any]) -> str | None:
    raw = effective_filter.get("working_session_id", effective_filter.get("session_id"))
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _working_memory_route(
    ops: RetrievalPipelineOps,
    *,
    query: str,
    tenant_id: str,
    branch: str,
    k: int,
    effective_filter: dict[str, Any],
    policy: OperatingPolicy,
    evaluated_at: datetime,
) -> tuple[list[Hit], dict[str, Any]]:
    """Load the optional fourth route without widening the existing stores."""

    requested = _working_route_requested(effective_filter)
    session_id = _working_session_id(effective_filter)
    report: dict[str, Any] = {
        "version": "working-memory-route.v1",
        "requested": requested,
        "session_id_present": session_id is not None,
        "evaluated_at": None,
        "status": "not_requested",
        "reason": "no_working_selector",
        "candidate_count": 0,
        "selected_count": 0,
        "data_only": True,
        "promotion_gate_required": True,
        "used_for_ranking": False,
    }
    if not requested or session_id is None:
        report["reason"] = "missing_session_selector"
        return [], report
    report["evaluated_at"] = evaluated_at.isoformat()

    try:
        list_working = getattr(ops, "list_working", None)
        if not callable(list_working):
            report.update({"status": "unavailable", "reason": "working_store_not_exposed"})
            return [], report
        items = list_working(tenant_id, session_id, as_of=evaluated_at)
        scoped = working_memory_route_hits(
            _scope_working_items(list(items or []), effective_filter),
            query=query,
            tenant_id=tenant_id,
            session_id=session_id,
            evaluated_at=evaluated_at,
            branch=branch,
            limit=k,
            access_context=effective_filter,
            policy_max_sensitivity=policy.max_sensitivity,
            max_trust_tier=policy.max_trust_tier,
        )
    except Exception as exc:  # optional route failures must not suppress durable retrieval
        report.update(
            {
                "status": "unavailable",
                "reason": "working_store_error",
                "error_type": type(exc).__name__,
            }
        )
        return [], report
    report.update(
        {
            "status": "applied",
            "reason": "session_scoped_active_items",
            "candidate_count": len(scoped),
            "selected_count": len(scoped),
            "used_for_ranking": bool(scoped),
        }
    )
    return scoped, report


#: Reserved retrieval-filter key: the caller's own token budget for the hits.
TOKEN_BUDGET_FILTER_KEY = "token_budget"

#: Per-hit diagnostics a lean answer leaves out (:func:`lean_retrieval_payload`).
LEAN_HIT_DIAGNOSTIC_KEYS = (
    "standing",
    "standing_observability",
    "reality_monitoring",
    "retrieved_text",
    "activation",
    "privacy",
    "lifecycle",
)

_LEADING_STAMP_RE = re.compile(r"^\s*(?:\[[^\]\n]{1,64}\]\s*)+")
_LEADING_SPEAKER_RE = re.compile(r"^\s*[^\W\d_][\w-]{0,31}\s*:\s+")


def requested_token_budget(effective_filter: Mapping[str, Any], policy: OperatingPolicy) -> int:
    """The budget the hits are fitted to: the caller's own, never above the policy's.

    A request above ``policy.token_budget`` is clamped to it rather than
    refused; anything that is not a positive integer is refused.
    """

    raw = effective_filter.get(TOKEN_BUDGET_FILTER_KEY)
    if raw is None:
        return policy.token_budget
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("token_budget must be a positive integer")
    return min(policy.token_budget, raw)


def _item_field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _scope_working_items(items: list[Any], effective_filter: Mapping[str, Any]) -> list[Any]:
    """Narrow a session's working items to the authenticated subject, when one is named.

    ``working_user_id`` / ``working_agent_id`` are set by a caller that has
    verified a session identity; without them the route stays session-scoped,
    exactly as before.
    """

    scoped = items
    for key, field_name in (("working_user_id", "user_id"), ("working_agent_id", "agent_id")):
        wanted = effective_filter.get(key)
        if isinstance(wanted, str) and wanted.strip():
            subject = wanted.strip()
            scoped = [item for item in scoped if str(_item_field(item, field_name) or "") == subject]
    return scoped


def _turn_body(text: str) -> str:
    """A stored line without a leading ``[timestamp]`` or ``Speaker:`` label."""

    body = _LEADING_STAMP_RE.sub("", text or "", count=1)
    return _LEADING_SPEAKER_RE.sub("", body, count=1).strip()


def _same_words(first: str, second: str) -> bool:
    """True when two stored lines are the same text once labels are stripped.

    A fragment is a different memory: ``4411`` is not the line
    ``the old gate code is 4411``.
    """

    body_a, body_b = _turn_body(first), _turn_body(second)
    if not body_a or not body_b:
        return False
    return body_a.casefold() == body_b.casefold()


def _collapse_session_duplicates(hits: list[Hit]) -> tuple[list[Hit], int]:
    """One turn, one hit.

    A line of conversation is stored twice: verbatim in the ledger, and as a
    working item that cites that record. When both are candidates they are the
    same words, so the working copy is folded into the durable record. The
    record keeps its id (the evidence cid), its trust and its grounding, is
    scored as ONE candidate found by one more channel (the fused scores add,
    as reciprocal-rank fusion adds them), and names the working items it
    absorbed. A working item that cites a record but says something else - a
    note, a conclusion - is a different memory and stays its own hit.
    """

    records = {hit.id: index for index, hit in enumerate(hits) if hit.kind == "evidence"}
    if not records:
        return hits, 0
    absorbed: dict[int, int] = {}
    for index, hit in enumerate(hits):
        if hit.kind != "working":
            continue
        for cid in hit.provenance:
            target = records.get(cid)
            if target is not None and _same_words(hit.text, hits[target].text):
                absorbed[index] = target
                break
    if not absorbed:
        return hits, 0
    survivors = list(hits)
    for index, target in absorbed.items():
        working = hits[index]
        record = survivors[target]
        if record is hits[target]:
            # Never write into a hit another caller may still hold.
            record = _clone_hit(record)
            survivors[target] = record
        record.score = record.score + working.score
        record.channel = "+".join(sorted({*record.channel.split("+"), *working.channel.split("+")} - {""}))
        item_ids = record.metadata.setdefault("working_item_ids", [])
        if working.id not in item_ids:
            item_ids.append(working.id)
        session = working.metadata.get("session_id")
        if session:
            record.metadata["working_session_id"] = session
    kept = [survivors[index] for index in range(len(hits)) if index not in absorbed]
    kept.sort(key=lambda hit: -hit.score)
    return kept, len(absorbed)


def _iso_utc(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        try:
            value = parse_dt(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _stamp_hit_origin(
    ops: RetrievalPipelineOps,
    hits: list[Hit],
    *,
    tenant_id: str,
    branch: str,
) -> None:
    """Say, in a stable place, which plane a hit is from and when it was made.

    ``memory_type`` is ``working`` for a working item and otherwise mirrors the
    hit's kind. ``created_at`` (ISO 8601, UTC) is the record's own time for
    evidence and working items; a derived hit (assertion, relation,
    preference) that carries no time of its own takes the time of the first
    evidence it cites, and says so in ``created_at_source``. A working hit
    also lists the ``evidence_ids`` it cites.

    The time comes from ``evidence_created_at``, not ``get_evidence``. Grounded
    answering fingerprints ``access_policy`` across successive ``get_evidence``
    results and fails closed when they drift; a dating read on that same
    method would spend the pre-drift observation before the fingerprint.
    """

    lookup_created_at = getattr(ops, "evidence_created_at", None)
    known: dict[tuple[str, str], str | None] = {}

    def cited_evidence_time(cid: str, record_branch: str) -> str | None:
        key = (cid, record_branch)
        if key not in known:
            created = None
            if cid and callable(lookup_created_at):
                try:
                    created = _iso_utc(lookup_created_at(tenant_id, cid, record_branch))
                except Exception:  # a missing or unreadable record only costs the date
                    created = None
            known[key] = created
        return known[key]

    for hit in hits:
        metadata = hit.metadata
        metadata.setdefault("memory_type", hit.kind)
        record_branch = hit.branch or branch
        source = "record"
        if hit.kind == "working":
            metadata["evidence_ids"] = list(hit.provenance)
            working = metadata.get("working_memory")
            created = _iso_utc(working.get("created_at")) if isinstance(working, Mapping) else None
        elif hit.kind == "evidence":
            created = _iso_utc(metadata.get("created_at")) or cited_evidence_time(hit.id, record_branch)
        else:
            created = _iso_utc(metadata.get("created_at"))
            if created is None:
                for cid in hit.provenance:
                    created = cited_evidence_time(cid, record_branch)
                    if created is not None:
                        source = "source_evidence"
                        break
        if created is not None:
            metadata["created_at"] = created
            metadata["created_at_source"] = source


def lean_retrieval_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A retrieval answer without the ``explain`` block and the per-hit diagnostics.

    The ranking, the budget and the abstention verdict are the full answer's:
    this only leaves out what a caller that reads five lines does not need.
    ``abstained``, ``confidence``, ``uncertainty_note``, ``used_tokens`` and
    every hit's id, kind, text, score, channel, trust tier, provenance and
    origin metadata stay.
    """

    lean = {key: value for key, value in payload.items() if key != "explain"}
    hits: list[Any] = []
    for hit in payload.get("hits") or []:
        if not isinstance(hit, Mapping):
            hits.append(hit)
            continue
        trimmed = dict(hit)
        metadata = hit.get("metadata")
        if isinstance(metadata, Mapping):
            trimmed["metadata"] = {
                key: value for key, value in metadata.items() if key not in LEAN_HIT_DIAGNOSTIC_KEYS
            }
        hits.append(trimmed)
    lean["hits"] = hits
    return lean


class RetrievalPipelineOps(Protocol):
    """Exactly the per-engine calls the shipped retrieve() bodies make.

    Both shipped engines already satisfy this Protocol structurally; a new
    engine implements these members and calls :func:`run_retrieval_pipeline`.
    """

    # -- per-engine attributes ------------------------------------------------
    adapters: RetrievalAdapters
    #: explain["channels"] key names for (dense, lexical, graph) counts.
    retrieval_explain_channel_keys: tuple[str, str, str]

    # -- channel searches -----------------------------------------------------
    def vector_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]: ...

    def lexical_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]: ...

    def graph_ppr(
        self,
        seeds: list[str],
        k: int,
        as_of: Any = None,
        tenant_id: str | None = None,
        branch: str | None = None,
        use_cache: bool = False,
        filt: dict[str, Any] | None = None,
    ) -> list[Hit]: ...

    # -- volatile memory-plane routes ----------------------------------------
    def list_intentions(self, tenant_id: str) -> list[Any]: ...

    def get_evidence(self, tenant_id: str, cid: str, branch: str = "main") -> Any: ...

    def evidence_created_at(self, tenant_id: str, cid: str, branch: str = "main") -> Any:
        """Timestamp of one evidence row, never an access-policy snapshot."""
        ...

    def list_working(self, tenant_id: str, session_id: str, *, as_of: Any) -> list[Any]: ...

    # -- fusion / ordering / budget helpers ------------------------------------
    def _rrf(self, ranked_lists: list[list[Hit]], k: int) -> list[Hit]: ...

    def _mmr(self, query: str, hits: list[Hit], k: int) -> list[Hit]: ...

    def _apply_standing_scores(self, hits: list[Hit]) -> list[Hit]: ...

    def _u_curve_order(self, hits: list[Hit]) -> list[Hit]: ...

    def _merge_schema_fast_path_reports(
        self, first: dict[str, Any], second: dict[str, Any]
    ) -> dict[str, Any]: ...

    def _fit_budget(self, hits: list[Hit], budget: int) -> tuple[list[Hit], int]: ...

    def _mark_retrieved_text_as_data(self, hits: list[Hit]) -> list[Hit]: ...

    # -- store access / telemetry ----------------------------------------------
    def _record_retrieval_access(self, hits: list[Hit]) -> dict[str, int]: ...

    def _calibration_for(self, tenant_id: str, memory_type: str) -> CalibrationSet | None: ...

    # -- confidence / calibration / reality monitoring --------------------------
    def _confidence(self, query: str, hits: list[Hit], *, support_score: float | None = None) -> float: ...

    def _prediction_set_size(self, hits: list[Hit], threshold: float) -> int: ...

    def _reality_monitoring_report(self, hits: list[Hit]) -> dict[str, Any]: ...

    def _calibration_explain(
        self, calibration: CalibrationSet | None, threshold: float
    ) -> dict[str, Any]: ...


def _run_global_sensemaking(
    ops: RetrievalPipelineOps,
    *,
    query: str,
    tenant_id: str,
    branch: str,
    deep: bool,
    effective_filter: dict[str, Any],
    policy: OperatingPolicy,
    record_access: bool,
    token_budget: int,
) -> RetrievalResult:
    """Project readable RAPTOR nodes through the shared retrieve seam."""

    hits, report = global_sensemaking_projection(
        ops,
        query=query,
        tenant_id=tenant_id,
        branch=branch,
        filt=effective_filter,
        policy=policy,
        deep=deep,
    )
    node_budget = int(report["budget"]["node_budget"])
    candidate_costs: dict[str, int] = {}
    token_fitted: list[Hit] = []
    for hit in hits:
        individually_fitted, cost = ops._fit_budget([hit], token_budget)
        if individually_fitted:
            token_fitted.append(hit)
            candidate_costs[hit.id] = cost
    root_groups: dict[str, list[Hit]] = {}
    for hit in token_fitted:
        root = str(hit.metadata.get("theme_root_cid") or hit.id)
        root_groups.setdefault(root, []).append(hit)
    budgeted: list[Hit] = []
    used = 0
    for members in root_groups.values():
        representative = min(
            members, key=lambda hit: (candidate_costs[hit.id], -hit.score, hit.id)
        )
        fitted, cost = ops._fit_budget([representative], token_budget - used)
        if not fitted:
            continue
        budgeted.append(representative)
        used += cost
        if len(budgeted) >= node_budget:
            break
    # Coverage is reserved with compact representatives first. Spend the
    # remaining shared budget upgrading each occupied theme slot by relevance.
    for index, representative in enumerate(list(budgeted)):
        root = str(representative.metadata.get("theme_root_cid") or representative.id)
        available = token_budget - used + candidate_costs[representative.id]
        for candidate in sorted(
            root_groups[root],
            key=lambda hit: (-hit.score, candidate_costs[hit.id], hit.id),
        ):
            if candidate_costs[candidate.id] <= available:
                budgeted[index] = candidate
                used += candidate_costs[candidate.id] - candidate_costs[representative.id]
                break
    if len(budgeted) < node_budget:
        selected_ids = {hit.id for hit in budgeted}
        for hit in token_fitted:
            if hit.id in selected_ids:
                continue
            fitted, cost = ops._fit_budget([hit], token_budget - used)
            if not fitted:
                continue
            budgeted.append(hit)
            selected_ids.add(hit.id)
            used += cost
            if len(budgeted) >= node_budget:
                break
    token_fitted_ids = {hit.id for hit in token_fitted}
    kept_ids = {hit.id for hit in budgeted}
    for hit in hits:
        if hit.id not in token_fitted_ids:
            report["exclusions"].append({"cid": hit.id, "reason": "token_budget"})
        elif hit.id not in kept_ids:
            report["exclusions"].append({"cid": hit.id, "reason": "node_budget"})
    report["exclusions"] = sorted(
        report["exclusions"],
        key=lambda item: (str(item.get("reason") or ""), str(item.get("cid") or ""), int(item.get("count") or 0)),
    )
    report["reduce_count"] = len(budgeted)
    report["budget"]["used_nodes"] = len(budgeted)
    report["budget"]["used_tokens"] = used
    kept_roots = {
        str(hit.metadata.get("theme_root_cid") or hit.id)
        for hit in budgeted
        if hit.metadata.get("theme_root_cid") or hit.id
    }
    mapped_roots = {str(root) for root in report.get("theme_root_cids") or [] if root}
    if mapped_roots and kept_roots != mapped_roots:
        report["incomplete_theme_coverage"] = True
    coverage_reason: str | None = None
    coverage_note: str | None = None
    if report["map_count"] == 0:
        coverage_reason = "insufficient_readable_coverage"
        coverage_note = "Readable RAPTOR coverage is insufficient for global sensemaking."
    elif report["reduce_count"] == 0:
        coverage_reason = "budget_exhausted"
        coverage_note = "Global sensemaking exceeded the token or node budget before a projection could be emitted."
    elif report.get("incomplete_theme_coverage"):
        coverage_reason = "incomplete_theme_coverage"
        coverage_note = "Global sensemaking omitted at least one RAPTOR theme root under the node budget."
    budgeted = ops._mark_retrieved_text_as_data(budgeted)
    _stamp_hit_origin(ops, budgeted, tenant_id=tenant_id, branch=branch)
    read_marks = (
        {"assertions": 0, "evidence": 0}
        if not record_access
        else ops._record_retrieval_access(budgeted)
    )
    calibration = ops._calibration_for(tenant_id, "fact")
    threshold = conformal_threshold(calibration) if calibration else policy.abstention_threshold
    support_report = query_support(query, budgeted)
    insufficient_support = support_report["score"] < QUERY_SUPPORT_THRESHOLD
    confidence = ops._confidence(query, budgeted, support_score=support_report["score"]) if budgeted else 0.0
    prediction_set_size = ops._prediction_set_size(budgeted, threshold)
    entropy = semantic_entropy([hit.text for hit in budgeted])
    gist_support = gist_support_report(budgeted)
    reality_monitoring = ops._reality_monitoring_report(budgeted)
    standing_report = reality_monitoring["standing"]
    ungrounded_reality_only = bool(standing_report["abstention_gate"]["active"])
    if ungrounded_reality_only != bool(reality_monitoring["ungrounded_only"]):
        raise AssertionError("Standing P1 mirror diverged from reality-monitoring abstention gate")
    answer_grounding_floor = answer_grounding_floor_report(budgeted, policy)
    answer_grounding_floor_active = bool(answer_grounding_floor["active"])
    # RAPTOR consolidation-summary hits are the intended evidence for this
    # projection. Record gist_support for provenance, but do not treat them as
    # gist-only hard-abstain or crush confidence for that reason alone.
    if ungrounded_reality_only:
        confidence = min(confidence, threshold * 0.95)
    if answer_grounding_floor_active:
        confidence = min(confidence, threshold * 0.95)
    if calibration:
        gated = (
            should_abstain(confidence, calibration, prediction_set_size=prediction_set_size)
            or insufficient_support
            or ungrounded_reality_only
            or answer_grounding_floor_active
        )
    else:
        gated = (
            confidence < threshold
            or prediction_set_size == 0
            or insufficient_support
            or ungrounded_reality_only
            or answer_grounding_floor_active
        )
    gate_reason: str | None = None
    gate_note: str | None = None
    if ungrounded_reality_only:
        gate_reason = "ungrounded_reality_only"
        gate_note = (
            "Retrieved support has low groundedness or insufficient independent "
            "external support; abstaining until grounded evidence is available."
        )
    elif answer_grounding_floor_active:
        gate_reason = "answer_grounding_floor"
        gate_note = (
            "Retrieved support is dominated by low-grounded self-generated content; "
            "flagging as hypothesis and abstaining until grounded support is available."
        )
    elif insufficient_support:
        gate_reason = "insufficient_query_support"
        gate_note = "Retrieved evidence did not cover enough query terms; abstaining until stronger support is available."
    elif gated:
        gate_reason = "calibrated_uncertainty"
        gate_note = "Evidence is too thin, low-trust, or conflicting for a confident answer."
    abstention_reason = coverage_reason or gate_reason
    note = coverage_note or gate_note
    report["abstention_reason"] = abstention_reason
    explain = {
        "query_mode": GLOBAL_SENSEMAKING_MODE,
        "global_sensemaking": report,
        "channels": {GLOBAL_SENSEMAKING_CHANNEL: len(budgeted)},
        "source_cids": list(report["source_cids"]),
        "raptor_levels": list(report["raptor_levels"]),
        "map_count": report["map_count"],
        "reduce_count": report["reduce_count"],
        "exclusions": list(report["exclusions"]),
        "budget": dict(report["budget"]),
        "abstention_reason": abstention_reason,
        "gist_support": gist_support,
        "reality_monitoring": reality_monitoring,
        "standing": standing_report,
        "answer_grounding_floor": answer_grounding_floor,
        "semantic_entropy": entropy,
        "calibration": ops._calibration_explain(calibration, threshold),
        "confidence": {
            "score": confidence,
            "answer_score": confidence,
            "prediction_set_size": prediction_set_size,
            "threshold": threshold,
            "source": "conformal" if calibration else "evidence_quality",
            "query_support": support_report,
        },
        "read_marks": read_marks,
        "adapters": {
            "embedding": ops.adapters.embedding.name,
            "embedding_dims": ops.adapters.embedding.dims,
            "reranker": ops.adapters.reranker.name,
            "lexical_backend": ops.adapters.lexical_backend,
            "graph_backend": ops.adapters.graph_backend,
        },
        "rails": policy.immutable_rails,
    }
    return RetrievalResult(
        query=query,
        hits=budgeted,
        confidence=confidence,
        abstained=abstention_reason is not None,
        uncertainty_note=note,
        token_budget=token_budget,
        used_tokens=used,
        explain=explain,
    )


def run_retrieval_pipeline(
    ops: RetrievalPipelineOps,
    *,
    query: str,
    tenant_id: str,
    branch: str,
    deep: bool,
    filt: dict[str, Any] | None,
    policy: OperatingPolicy,
    record_access: bool = True,
) -> RetrievalResult:
    """The shared retrieve() orchestration — LocalMemoryEngine's body verbatim."""

    workspace_broadcast = workspace_broadcast_from_context(filt)
    effective_filter = strip_workspace_broadcast_filter(filt)
    effective_filter.update({"tenant_id": tenant_id, "branch": branch, "_retrieval_deep": deep})
    query_mode = require_supported_query_mode(query_mode_from_filter(effective_filter))
    retrieval_instant = (
        parse_dt(effective_filter.get("as_of"))
        or parse_dt(effective_filter.get("evaluated_at"))
        or parse_dt(effective_filter.get("working_evaluated_at"))
        or utc_now()
    )
    prospective_requested = isinstance(effective_filter.get("prospective_owner"), dict)
    working_requested = _working_route_requested(effective_filter)
    k = policy.deep_top_k if deep else policy.top_k
    graph_k = max(4, k // 2)
    token_budget = requested_token_budget(effective_filter, policy)
    cache_key = (
        None
        if query_mode == GLOBAL_SENSEMAKING_MODE
        else _result_cache_key(
            ops,
            query=query,
            tenant_id=tenant_id,
            branch=branch,
            deep=deep,
            effective_filter=effective_filter,
            workspace_broadcast=workspace_broadcast,
            k=k,
            graph_k=graph_k,
            policy=policy,
        )
    )
    if cache_key is not None:
        cached = _result_cache_get(cache_key)
        if cached is not None:
            cached.explain["read_marks"] = (
                {"assertions": 0, "evidence": 0}
                if not record_access
                else ops._record_retrieval_access(cached.hits)
            )
            cached.explain[_RESULT_CACHE_EXPLAIN_KEY] = _result_cache_explain(hit=True, stored=False)
            return cached
    if query_mode == GLOBAL_SENSEMAKING_MODE:
        result = _run_global_sensemaking(
            ops,
            query=query,
            tenant_id=tenant_id,
            branch=branch,
            deep=deep,
            effective_filter=effective_filter,
            policy=policy,
            record_access=record_access,
            token_budget=token_budget,
        )
        if cache_key is not None:
            current_cache_key = _result_cache_key(
                ops,
                query=query,
                tenant_id=tenant_id,
                branch=branch,
                deep=deep,
                effective_filter=effective_filter,
                workspace_broadcast=workspace_broadcast,
                k=k,
                graph_k=graph_k,
                policy=policy,
            )
            stored = current_cache_key == cache_key
            result.explain[_RESULT_CACHE_EXPLAIN_KEY] = _result_cache_explain(hit=False, stored=stored)
            if stored:
                _result_cache_put(cache_key, result)
        return result
    if parallel_channels_enabled():
        with ThreadPoolExecutor(max_workers=5) as pool:
            dense_future = pool.submit(ops.vector_search, query, policy.rerank_width, effective_filter)
            lexical_future = pool.submit(ops.lexical_search, query, policy.rerank_width, effective_filter)
            graph_future = pool.submit(
                ops.graph_ppr,
                tokenize(query),
                graph_k,
                as_of=effective_filter.get("as_of"),
                tenant_id=tenant_id,
                branch=branch,
                use_cache=not deep,
                filt=effective_filter,
            )
            prospective_future = pool.submit(
                prospective_memory_hits,
                ops,
                query,
                policy.rerank_width,
                effective_filter,
                as_of=retrieval_instant,
            )
            working_future = pool.submit(
                _working_memory_route,
                ops,
                query=query,
                tenant_id=tenant_id,
                branch=branch,
                k=policy.rerank_width,
                effective_filter=effective_filter,
                policy=policy,
                evaluated_at=retrieval_instant,
            ) if working_requested else None
            dense = dense_future.result()
            lexical = lexical_future.result()
            graph = _fast_graph_hits(graph_future.result(), deep=deep)
            prospective = prospective_future.result()
            working, working_explain = working_future.result() if working_future is not None else ([], {})
    else:
        dense = ops.vector_search(query, policy.rerank_width, effective_filter)
        lexical = ops.lexical_search(query, policy.rerank_width, effective_filter)
        graph = _fast_graph_hits(
            ops.graph_ppr(
                tokenize(query),
                graph_k,
                as_of=effective_filter.get("as_of"),
                tenant_id=tenant_id,
                branch=branch,
                use_cache=not deep,
                filt=effective_filter,
            ),
            deep=deep,
        )
        prospective = prospective_memory_hits(
            ops, query, policy.rerank_width, effective_filter, as_of=retrieval_instant
        )
        working, working_explain = (
            _working_memory_route(
                ops,
                query=query,
                tenant_id=tenant_id,
                branch=branch,
                k=policy.rerank_width,
                effective_filter=effective_filter,
                policy=policy,
                evaluated_at=retrieval_instant,
            )
            if working_requested
            else ([], {})
        )
    ranked_routes = [dense, lexical, graph, prospective, working]
    fused = ops._rrf(ranked_routes, k=max(k * 2, policy.rerank_width))
    collapsed_turns = 0
    if working:
        fused, collapsed_turns = _collapse_session_duplicates(fused)
    reranked = ops.adapters.reranker.rerank(query, fused, k=max(k * 2, k))
    reranked, schema_fast_path = schema_fast_path_rerank(query, reranked, policy)
    diversified = ops._mmr(query, reranked, k=max(k, 1))
    activated = ops._apply_standing_scores(apply_activation_scores(diversified, policy))
    ordered = ops._u_curve_order(activated)
    ordered, schema_fast_path_final = schema_fast_path_rerank(query, ordered, policy)
    schema_fast_path = ops._merge_schema_fast_path_reports(schema_fast_path, schema_fast_path_final)
    ordered, workspace_retrieval_advisory = apply_workspace_retrieval_advisory(
        ordered,
        filt,
        tenant_id=tenant_id,
        branch=branch,
        policy=policy,
    )
    budgeted, used = ops._fit_budget(ordered, token_budget)
    budgeted = ops._mark_retrieved_text_as_data(budgeted)
    _stamp_hit_origin(ops, budgeted, tenant_id=tenant_id, branch=branch)
    if working_requested:
        working_explain["selected_count"] = sum(
            1 for hit in budgeted if hit.metadata.get("memory_type") == "working"
        )
        working_explain["collapsed_count"] = collapsed_turns
    read_marks = (
        {"assertions": 0, "evidence": 0}
        if not record_access
        else ops._record_retrieval_access(budgeted)
    )
    calibration = ops._calibration_for(tenant_id, "fact")
    threshold = conformal_threshold(calibration) if calibration else policy.abstention_threshold
    support_report = query_support(query, budgeted)
    insufficient_support = support_report["score"] < QUERY_SUPPORT_THRESHOLD
    confidence = ops._confidence(query, budgeted, support_score=support_report["score"])
    prediction_set_size = ops._prediction_set_size(budgeted, threshold)
    entropy = semantic_entropy([hit.text for hit in budgeted])
    gist_support = gist_support_report(budgeted)
    gist_only = bool(gist_support["applied"])
    reality_monitoring = ops._reality_monitoring_report(budgeted)
    standing_report = reality_monitoring["standing"]
    ungrounded_reality_only = bool(standing_report["abstention_gate"]["active"])
    if ungrounded_reality_only != bool(reality_monitoring["ungrounded_only"]):
        raise AssertionError("Standing P1 mirror diverged from reality-monitoring abstention gate")
    answer_grounding_floor = answer_grounding_floor_report(budgeted, policy)
    answer_grounding_floor_active = bool(answer_grounding_floor["active"])
    if gist_only:
        confidence = min(confidence, threshold * 0.95)
    if ungrounded_reality_only:
        confidence = min(confidence, threshold * 0.95)
    if answer_grounding_floor_active:
        confidence = min(confidence, threshold * 0.95)
    if calibration:
        abstained = (
            should_abstain(confidence, calibration, prediction_set_size=prediction_set_size)
            or insufficient_support
            or gist_only
            or ungrounded_reality_only
            or answer_grounding_floor_active
        )
    else:
        abstained = (
            confidence < threshold
            or prediction_set_size == 0
            or insufficient_support
            or gist_only
            or ungrounded_reality_only
            or answer_grounding_floor_active
        )
    note = None
    if gist_only:
        note = "Only gist-tier memory support was retrieved; inspect source evidence before answering."
    elif ungrounded_reality_only:
        note = (
            "Retrieved support has low groundedness or insufficient independent "
            "external support; abstaining until grounded evidence is available."
        )
    elif answer_grounding_floor_active:
        note = (
            "Retrieved support is dominated by low-grounded self-generated content; "
            "flagging as hypothesis and abstaining until grounded support is available."
        )
    elif insufficient_support:
        note = "Retrieved evidence did not cover enough query terms; abstaining until stronger support is available."
    elif abstained:
        note = "Evidence is too thin, low-trust, or conflicting for a confident answer."
    dense_key, lexical_key, graph_key = ops.retrieval_explain_channel_keys
    channels = {
        dense_key: len(dense),
        lexical_key: len(lexical),
        graph_key: len(graph),
    }
    if prospective_requested:
        channels[PROSPECTIVE_MEMORY_CHANNEL] = len(prospective)
    if working_requested:
        channels[WORKING_MEMORY_CHANNEL] = len(working)
    explain = {
        "channels": channels,
        "rrf_k": policy.rrf_k,
        "mmr_lambda": policy.mmr_lambda,
        "activation": activation_explain(budgeted, policy),
        "calibration": ops._calibration_explain(calibration, threshold),
        "confidence": {
            "score": confidence,
            "answer_score": confidence,
            "prediction_set_size": prediction_set_size,
            "threshold": threshold,
            "source": "conformal" if calibration else "evidence_quality",
            "query_support": support_report,
        },
        "semantic_entropy": entropy,
        "gist_support": gist_support,
        "reality_monitoring": reality_monitoring,
        "standing": standing_report,
        "answer_grounding_floor": answer_grounding_floor,
        "schema_fast_path": schema_fast_path,
        "workspace_broadcast": workspace_broadcast,
        "workspace_retrieval_advisory": workspace_retrieval_advisory,
        "read_marks": read_marks,
        "adapters": {
            "embedding": ops.adapters.embedding.name,
            "embedding_dims": ops.adapters.embedding.dims,
            "reranker": ops.adapters.reranker.name,
            "lexical_backend": ops.adapters.lexical_backend,
            "graph_backend": ops.adapters.graph_backend,
        },
        "rails": policy.immutable_rails,
    }
    if prospective_requested or working_requested:
        explain["routes"] = [
            {"channel": dense_key, "count": len(dense), "requested": True},
            {"channel": lexical_key, "count": len(lexical), "requested": True},
            {"channel": graph_key, "count": len(graph), "requested": True},
            {
                "channel": PROSPECTIVE_MEMORY_CHANNEL,
                "count": len(prospective),
                "requested": prospective_requested,
            },
            {
                "channel": WORKING_MEMORY_CHANNEL,
                "count": len(working),
                "requested": working_requested,
            },
        ]
    if working_requested:
        explain["working_memory"] = working_explain
    result = RetrievalResult(
        query=query,
        hits=budgeted,
        confidence=confidence,
        abstained=abstained,
        uncertainty_note=note,
        token_budget=token_budget,
        used_tokens=used,
        explain=explain,
    )
    if cache_key is not None:
        current_cache_key = _result_cache_key(
            ops,
            query=query,
            tenant_id=tenant_id,
            branch=branch,
            deep=deep,
            effective_filter=effective_filter,
            workspace_broadcast=workspace_broadcast,
            k=k,
            graph_k=graph_k,
            policy=policy,
        )
        stored = current_cache_key == cache_key
        result.explain[_RESULT_CACHE_EXPLAIN_KEY] = _result_cache_explain(hit=False, stored=stored)
        if stored:
            _result_cache_put(cache_key, result)
    return result
