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

from typing import Any, Protocol

from mnemosyne.calibration import CalibrationSet, conformal_threshold, should_abstain
from mnemosyne.models import Hit, RetrievalResult
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
    strip_workspace_broadcast_filter,
    workspace_broadcast_from_context,
)
from mnemosyne.text import tokenize


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
) -> RetrievalResult:
    """The shared retrieve() orchestration — LocalMemoryEngine's body verbatim."""

    workspace_broadcast = workspace_broadcast_from_context(filt)
    effective_filter = strip_workspace_broadcast_filter(filt)
    effective_filter.update({"tenant_id": tenant_id, "branch": branch})
    k = policy.deep_top_k if deep else policy.top_k
    dense = ops.vector_search(query, policy.rerank_width, effective_filter)
    lexical = ops.lexical_search(query, policy.rerank_width, effective_filter)
    graph = (
        ops.graph_ppr(tokenize(query), max(4, k // 2), tenant_id=tenant_id, branch=branch, filt=effective_filter)
        if deep
        else []
    )
    fused = ops._rrf([dense, lexical, graph], k=max(k * 2, policy.rerank_width))
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
    read_marks = ops._record_retrieval_access(budgeted)
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
    return RetrievalResult(
        query=query,
        hits=budgeted,
        confidence=confidence,
        abstained=abstained,
        uncertainty_note=note,
        token_budget=policy.token_budget,
        used_tokens=used,
        explain={
            "channels": {
                dense_key: len(dense),
                lexical_key: len(lexical),
                graph_key: len(graph),
            },
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
        },
    )
