# src/mnemosyne/algorithms.py
"""Engine-agnostic retrieval algorithms (blueprint §22, spec §4.0).

Single source of truth for algorithms previously duplicated across
LocalMemoryEngine and PostgresEngine. Pure functions only: no engine
state, no I/O, no policy object — every tunable is a parameter.
Phase-1 native kernels (mnemosyne._native) mirror these signatures.
"""
from __future__ import annotations

import copy
from collections import defaultdict

from mnemosyne.retrieval import Hit
from mnemosyne.text import approx_tokens


def rrf_fuse(
    ranked_lists: list[list[Hit]],
    k: int,
    *,
    rrf_k: float,
    annotate_channel_scores: bool = False,
) -> list[Hit]:
    """Reciprocal-rank fusion of per-channel ranked hit lists.

    With ``annotate_channel_scores=False`` (default) this reproduces the
    LocalMemoryEngine behavior: fused hits are deep copies with summed RRF
    scores and merged channel labels. With ``annotate_channel_scores=True``
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
            item = copy.deepcopy(hit)
            item.score = scores[key]
            item.channel = "+".join(sorted(set(channels[key])))
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
