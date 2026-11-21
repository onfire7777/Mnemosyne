"""Bounded derived candidates from already scored, source-owned vectors."""
from __future__ import annotations

from dataclasses import replace

from mnemosyne.access_policy import may_read_item, may_use_stored_embedding
from mnemosyne.retrieval import projection_sources_readable, scored_channel_for_hit
from mnemosyne.text import lexical_score


def expand_source_vectors(engine, query, hits, candidates, k, filt, *, oracle=None):
    """Propose readable projections for the normal downstream text reranker.

    The score belongs to a source, not to a made-up assertion embedding. Keep
    that provenance explicit, admit at most two projections per top source,
    and retain at least half the source candidates when enough sources exist.
    Every projection is already in the engine's custody-filtered candidate
    set; its own embedding/redaction policy is checked separately here.
    """
    ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)[:max(0, k)]
    if k < 2 or not ranked:
        return ranked
    from mnemosyne.engine import _clone_candidate_hit

    lookup = oracle if oracle is not None else engine
    finish = getattr(candidates, "finish", None)
    sources = {(hit.tenant_id, hit.branch, hit.id): hit for hit in ranked if hit.kind == "evidence"}
    grouped = {}
    for candidate in candidates:
        if candidate.kind not in {"assertion", "preference"}:
            continue
        anchors = [sources[(candidate.tenant_id, candidate.branch, cid)] for cid in candidate.provenance
                   if (candidate.tenant_id, candidate.branch, cid) in sources]
        if not anchors:
            continue
        if oracle is not None:
            if candidate.kind == "assertion":
                projection = oracle.assertions.get(candidate.id)
                if projection is None:
                    projection = oracle.assertions.get(
                        oracle._branch_key(candidate.tenant_id, candidate.branch, candidate.id)
                    )
            else:
                projection = oracle.preferences.get(candidate.id)
            if projection is not None and projection.tenant_id != candidate.tenant_id:
                projection = None
        else:
            projection = engine._get_projection_for_adapter(candidate.tenant_id, candidate.branch,
                                                             candidate.kind, candidate.id)
        if projection is None:
            continue
        if not projection_sources_readable(lookup, candidate.provenance, tenant_id=candidate.tenant_id,
            branch=candidate.branch, filt=filt, policy=engine.policy):
            continue
        sensitivity = int(getattr(projection, "sensitivity", 0))
        decision = may_read_item(item_tenant_id=candidate.tenant_id, sensitivity=sensitivity,
            access_policy=projection.access_policy, context=filt,
            policy_max_sensitivity=engine.policy.max_sensitivity, status=projection.status)
        if not may_use_stored_embedding(decision=decision, sensitivity=sensitivity,
                                        access_policy=projection.access_policy):
            continue
        anchor = max(anchors, key=lambda hit: hit.score)
        cloned = _clone_candidate_hit(candidate)
        if finish is not None:
            cloned = finish(cloned, candidate)
        proposed = replace(cloned, score=anchor.score,
            channel=scored_channel_for_hit(kind=cloned.kind, base_channel="dense"),
            metadata={**cloned.metadata, "source_vector_proxy": True,
                      "dense_source_cids": [hit.id for hit in anchors], "stored_embedding_used": False})
        grouped.setdefault(anchor.id, []).append((lexical_score(query, cloned.text), proposed))
    proposed = []
    for rows in grouped.values():
        proposed.extend(hit for _, hit in sorted(rows, key=lambda pair: (-pair[0], pair[1].id))[:2])
    proposed.sort(key=lambda hit: (-hit.score, -lexical_score(query, hit.text), hit.id))
    # Fill unused source capacity when there are fewer anchors than k/2.
    source_count = min(len(ranked), max((k + 1) // 2, k - len(proposed)))
    result = ranked[:source_count] + proposed[:k - source_count]
    return sorted(result, key=lambda hit: hit.score, reverse=True)
