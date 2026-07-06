# src/mnemosyne/algorithms.py
"""Engine-agnostic retrieval algorithms (blueprint §22, spec §4.0).

Single source of truth for algorithms previously duplicated across
LocalMemoryEngine and PostgresEngine. Pure functions only: no engine
state, no I/O, no policy object — tunables are parameters, though
fit_budget binds approx_tokens as its token-cost model.
Phase-1 native kernels (mnemosyne._native) mirror these signatures.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping

from mnemosyne import text
from mnemosyne.retrieval import Hit
from mnemosyne.text import approx_tokens, cosine


def rrf_fuse(
    ranked_lists: list[list[Hit]],
    k: int,
    *,
    rrf_k: float,
    annotate_channel_scores: bool = False,
) -> list[Hit]:
    """Reciprocal-rank fusion of per-channel ranked hit lists.

    With ``annotate_channel_scores=False`` (default) this reproduces the
    LocalMemoryEngine behavior: fused hits are fresh reconstructions with
    summed RRF scores and merged channel labels (equal to the historical
    deepcopy output). With ``annotate_channel_scores=True``
    it reproduces the PostgresEngine behavior, which additionally records
    ``channels`` and per-channel max ``channel_scores`` in hit metadata.
    """
    by_id: dict[tuple[str, str], Hit] = {}
    scores: dict[tuple[str, str], float] = defaultdict(float)
    channels: dict[tuple[str, str], list[str]] = defaultdict(list)
    channel_scores: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            key = (hit.kind, hit.id)
            by_id[key] = hit
            scores[key] += 1.0 / (rrf_k + rank)
            channels[key].append(hit.channel)
            if annotate_channel_scores:
                channel_scores[key][hit.channel] = max(
                    channel_scores[key].get(hit.channel, 0.0), hit.score
                )
    fused = []
    for key, hit in by_id.items():
        if annotate_channel_scores:
            item = Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=scores[key],
                channel="+".join(sorted(set(channels[key]))),
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata={
                    **hit.metadata,
                    "channels": sorted(set(channels[key])),
                    "channel_scores": dict(sorted(channel_scores[key].items())),
                },
            )
        else:
            # Explicit reconstruction (mirrors the postgres branch above) in
            # place of copy.deepcopy — equal output proven against a deepcopy
            # reference in tests/test_engine_perf_lanes.py.
            item = Hit(
                id=hit.id,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                branch=hit.branch,
                text=hit.text,
                score=scores[key],
                channel="+".join(sorted(set(channels[key]))),
                provenance=list(hit.provenance),
                trust_tier=hit.trust_tier,
                sensitivity=hit.sensitivity,
                metadata=dict(hit.metadata),
            )
        fused.append(item)
    return sorted(fused, key=lambda item: item.score, reverse=True)[:k]


def u_curve_order(hits: list[Hit]) -> list[Hit]:
    """U-curve reorder: strongest hits at the ends, weakest in the middle.

    Even-indexed hits fill the front in order; odd-indexed hits are pushed
    to the back in reverse, countering LLM lost-in-the-middle attention.
    """
    front: list[Hit] = []
    back: list[Hit] = []
    for idx, hit in enumerate(hits):
        if idx % 2 == 0:
            front.append(hit)
        else:
            back.insert(0, hit)
    return front + back


def fit_budget(hits: list[Hit], budget: int) -> tuple[list[Hit], int]:
    """Greedy token-budget packing preserving hit order.

    Skips (rather than stops at) any hit whose ``approx_tokens`` cost would
    exceed the remaining budget; returns the kept hits and tokens used.
    """
    kept: list[Hit] = []
    used = 0
    for hit in hits:
        cost = approx_tokens(hit.text)
        if used + cost > budget:
            continue
        kept.append(hit)
        used += cost
    return kept, used


def mmr_select(
    hits: list[Hit],
    k: int,
    *,
    query_vec: list[float],
    embed_hit: Callable[[Hit], list[float] | None],
    mmr_lambda: float,
) -> list[Hit]:
    """Maximal-marginal-relevance selection (spec §4.1 kernel ABI).

    Objective per candidate: ``mmr_lambda * relevance - (1 - mmr_lambda) *
    max_similarity + hit.score``. A missing vector (``embed_hit`` returns
    ``None``) means relevance 0.0 AND no diversity penalty; the strict ``>``
    argmax gives first-wins tie-breaking on input order.

    Embedding sourcing is deliberately NOT unified (spec §4.0): the two
    engines stay behaviorally divergent via ``embed_hit`` —
    LocalMemoryEngine passes its security-gated
    ``_embedding_for_hit(hit, allow_fallback=True)`` path, PostgresEngine
    passes ``hashing_embedding(hit.text)``. In the pure loop below,
    selected-item vectors are recomputed inside every candidate loop on
    purpose: byte parity with the shipped engines over speed — do not cache.
    The native fast path instead materializes ``embed_hit`` exactly once per
    hit and delegates to the byte-parity-proven ``mmr_select_indices`` kernel.
    """
    if k <= 0:
        # Both modes already agree on the result: the pure loop's
        # ``while remaining and len(selected) < k`` condition is False from
        # the start (len(selected) == 0 is never < k), so it returns [].
        # Guarding BEFORE the native branch keeps the native path from
        # materializing embed_hit for every hit — the only mode-divergent
        # side effect — when nothing can be selected.
        return []
    if text.NATIVE is not None:
        # Index-aligned 1:1 with hits (the kernel raises ValueError on a
        # length mismatch); one embed_hit call per hit preserves the
        # one-metadata-side-effect-per-hit behavior of embedding sourcing.
        vectors = [embed_hit(hit) for hit in hits]
        indices = text.NATIVE.mmr_select_indices(
            [hit.score for hit in hits], vectors, query_vec, k, mmr_lambda
        )
        return [hits[i] for i in indices]
    selected: list[Hit] = []
    remaining = list(hits)
    while remaining and len(selected) < k:
        best: Hit | None = None
        best_score = float("-inf")
        for hit in remaining:
            hit_vec = embed_hit(hit)
            relevance = cosine(query_vec, hit_vec) if hit_vec is not None else 0.0
            diversity_penalty = 0.0
            if selected and hit_vec is not None:
                selected_vectors = [
                    selected_vec
                    for item in selected
                    if (selected_vec := embed_hit(item)) is not None
                ]
                if selected_vectors:
                    diversity_penalty = max(cosine(hit_vec, selected_vec) for selected_vec in selected_vectors)
            score = mmr_lambda * relevance - (1.0 - mmr_lambda) * diversity_penalty
            score += hit.score
            if score > best_score:
                best = hit
                best_score = score
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return selected


def ppr_power_iteration(
    adjacency: Mapping[str, Collection[str]],
    matches_seed: Callable[[str], bool],
    *,
    iterations: int = 12,
    damping: float = 0.85,
    teleport: float = 0.15,
) -> dict[str, float]:
    """Personalized PageRank by power iteration (blueprint §22.2 deep mode).

    Constants 12/0.85/0.15 are load-bearing for parity with both shipped
    engines — do not change defaults without a cross-engine golden update.

    ``teleport`` defaults to the literal ``0.15`` rather than being derived
    as ``1.0 - damping``: in IEEE 754 doubles ``1.0 - 0.85`` is
    ``0.15000000000000002 != 0.15``, and the inline code this replaces used
    the literal — deriving it would break bit-exact parity with both engines.
    """
    ranks = {node: (1.0 if matches_seed(node) else 0.0) for node in adjacency}
    for _ in range(iterations):
        next_ranks = {node: teleport * (1.0 if matches_seed(node) else 0.0) for node in ranks}
        for node, neighbors in adjacency.items():
            if not neighbors:
                continue
            share = damping * ranks.get(node, 0.0) / len(neighbors)
            for neighbor in neighbors:
                next_ranks[neighbor] = next_ranks.get(neighbor, 0.0) + share
        ranks = next_ranks
    return ranks
