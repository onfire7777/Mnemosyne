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
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.models import Hit, RetrievalResult, parse_dt
from mnemosyne.policy import OperatingPolicy
from mnemosyne.retrieval import (
    QUERY_SUPPORT_THRESHOLD,
    RetrievalAdapters,
    activation_explain,
    answer_grounding_floor_report,
    apply_activation_scores,
    apply_workspace_retrieval_advisory,
    gist_support_report,
    query_support,
    schema_fast_path_rerank,
    semantic_entropy,
    build_working_memory_hits,
    strip_workspace_broadcast_filter,
    workspace_broadcast_from_context,
)
from mnemosyne.text import tokenize

#: Capability-tier default to overlap the dense/lexical/graph channel calls on
#: a 3-worker thread pool (registered in CONFIG-DRIFT-CHECKS.md). Operators can
#: still force the knob on/off explicitly. Channel identity and the RRF input
#: order stay exactly [dense, lexical, graph]; parallel results are
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
    raw = effective_filter.get("session_id", effective_filter.get("working_session_id"))
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _working_evaluation_instant(effective_filter: dict[str, Any]) -> Any | None:
    raw = effective_filter.get("evaluated_at", effective_filter.get("working_evaluated_at"))
    if raw is None:
        raw = effective_filter.get("as_of")
    try:
        evaluated_at = parse_dt(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if evaluated_at is None or getattr(evaluated_at, "tzinfo", None) is None:
        return None
    return evaluated_at


def _working_memory_route(
    ops: RetrievalPipelineOps,
    *,
    query: str,
    tenant_id: str,
    branch: str,
    k: int,
    effective_filter: dict[str, Any],
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
    evaluated_at = _working_evaluation_instant(effective_filter)
    if evaluated_at is None:
        report.update(
            {
                "status": "rejected",
                "reason": "explicit_evaluation_instant_required",
            }
        )
        return [], report
    report["evaluated_at"] = evaluated_at.isoformat()

    search = getattr(ops, "working_memory_search", None)
    if callable(search):
        raw_hits = search(query, k, effective_filter)
        hits = [hit for hit in (raw_hits or []) if isinstance(hit, Hit)]
        scoped: list[Hit] = []
        for hit in hits:
            if hit.tenant_id != tenant_id or hit.branch != branch:
                continue
            marker = hit.metadata.get("session_id") if isinstance(hit.metadata, dict) else None
            if not isinstance(marker, str) or marker != session_id:
                continue
            copied = _clone_hit(hit)
            copied.metadata = {
                **copied.metadata,
                "memory_type": "working",
                "session_id": session_id,
                "working_memory_route": "working-memory-route.v1",
            }
            scoped.append(copied)
    else:
        list_working = getattr(ops, "list_working", None)
        if not callable(list_working):
            report.update({"status": "unavailable", "reason": "working_store_not_exposed"})
            return [], report
        items = list_working(tenant_id, session_id, as_of=evaluated_at)
        scoped = build_working_memory_hits(
            list(items or []),
            query=query,
            tenant_id=tenant_id,
            session_id=session_id,
            evaluated_at=evaluated_at,
            branch=branch,
            limit=k,
        )
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

    # -- optional working-memory route ---------------------------------------
    # Engine lanes may expose either this normalized route or list_working();
    # the orchestrator keeps both behind the same tenant/session/clock gate.
    def working_memory_search(self, query: str, k: int, filt: dict[str, Any]) -> list[Hit]: ...

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
    k = policy.deep_top_k if deep else policy.top_k
    graph_k = max(4, k // 2)
    working_requested = _working_route_requested(effective_filter)
    cache_key = _result_cache_key(
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
    if parallel_channels_enabled():
        with ThreadPoolExecutor(max_workers=4 if working_requested else 3) as pool:
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
            working_future = pool.submit(
                _working_memory_route,
                ops,
                query=query,
                tenant_id=tenant_id,
                branch=branch,
                k=policy.rerank_width,
                effective_filter=effective_filter,
            ) if working_requested else None
            dense = dense_future.result()
            lexical = lexical_future.result()
            graph = _fast_graph_hits(graph_future.result(), deep=deep)
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
        working, working_explain = (
            _working_memory_route(
                ops,
                query=query,
                tenant_id=tenant_id,
                branch=branch,
                k=policy.rerank_width,
                effective_filter=effective_filter,
            )
            if working_requested
            else ([], {})
        )
    ranked_channels = [dense, lexical, graph]
    if working_requested:
        ranked_channels.append(working)
    fused = ops._rrf(ranked_channels, k=max(k * 2, policy.rerank_width))
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
    budgeted, used = ops._fit_budget(ordered, policy.token_budget)
    budgeted = ops._mark_retrieved_text_as_data(budgeted)
    if working_requested:
        working_explain["selected_count"] = sum(
            1 for hit in budgeted if hit.metadata.get("memory_type") == "working"
        )
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
    if working_requested:
        channels["working_memory"] = len(working)
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
    if working_requested:
        explain["working_memory"] = working_explain
    result = RetrievalResult(
        query=query,
        hits=budgeted,
        confidence=confidence,
        abstained=abstained,
        uncertainty_note=note,
        token_budget=policy.token_budget,
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
