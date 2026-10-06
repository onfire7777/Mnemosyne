# src/mnemosyne/algorithms.py
"""Engine-agnostic retrieval algorithms (blueprint §22, spec §4.0).

Single source of truth for algorithms previously duplicated across
LocalMemoryEngine and PostgresEngine. Pure functions only: no engine
state, no I/O, no policy object — tunables are parameters, though
fit_budget binds approx_tokens as its token-cost model.
Phase-1 native kernels (mnemosyne._native) mirror these signatures.
"""
from __future__ import annotations

from array import array
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from itertools import chain

from mnemosyne import text
from mnemosyne.cid_lists import shared_or_copy
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
                provenance=shared_or_copy(hit.provenance),
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
                provenance=shared_or_copy(hit.provenance),
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


def _sparse(vec: list[float] | None) -> tuple[dict[int, float], int] | None:
    """Non-zero entries and length of a finite vector; None for a missing or non-finite one."""
    if vec is None:
        return None
    entries: dict[int, float] = {}
    for index, value in enumerate(vec):
        if value != 0.0:
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("non-finite vector")
            entries[index] = value
    return entries, len(vec)


def _sparse_dot(left: tuple[dict[int, float], int], right: tuple[dict[int, float], int]) -> float:
    """``_cosine_pure(a, b)`` for finite vectors, summing only terms where both are non-zero.

    ``zip`` stops at the shorter vector, and every other term is a +-0.0 product, which
    leaves the builtin ``sum``'s running value and Neumaier compensation unchanged; terms
    are taken in increasing index order, as zip yields them, and ``x * y == y * x``.
    """
    a, a_len = left
    b, b_len = right
    limit = min(a_len, b_len)
    return sum(value * other for index, value in a.items() if index < limit and (other := b.get(index)) is not None)


def _mmr_select_once(
    hits: list[Hit],
    k: int,
    *,
    query_vec: list[float],
    embed_hit: Callable[[Hit], list[float] | None],
    mmr_lambda: float,
) -> list[Hit]:
    """The pure MMR loop with each hit embedded once and each cosine computed once.

    Valid only for a deterministic ``embed_hit`` whose side effects are the same on every
    call (the local engine with its built-in hashing embedder): the pure loop recomputes the
    same vectors and the same dot products every round, so caching them changes no score,
    no comparison and no tie-break.
    """
    try:
        query = _sparse(query_vec)
        vectors = [_sparse(embed_hit(hit)) for hit in hits]
    except ValueError:
        return mmr_select(hits, k, query_vec=query_vec, embed_hit=embed_hit, mmr_lambda=mmr_lambda)
    assert query is not None
    relevance = [_sparse_dot(query, vec) if vec is not None else 0.0 for vec in vectors]
    pair: dict[tuple[int, int], float] = {}

    def similarity(i: int, j: int) -> float:
        key = (i, j) if i < j else (j, i)
        found = pair.get(key)
        if found is None:
            found = pair[key] = _sparse_dot(vectors[i], vectors[j])  # type: ignore[arg-type]
        return found

    selected: list[int] = []
    remaining = list(range(len(hits)))
    while remaining and len(selected) < k:
        best: int | None = None
        best_score = float("-inf")
        for i in remaining:
            diversity_penalty = 0.0
            if selected and vectors[i] is not None:
                chosen = [j for j in selected if vectors[j] is not None]
                if chosen:
                    diversity_penalty = max(similarity(i, j) for j in chosen)
            score = mmr_lambda * relevance[i] - (1.0 - mmr_lambda) * diversity_penalty
            score += hits[i].score
            if score > best_score:
                best = i
                best_score = score
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return [hits[i] for i in selected]


def mmr_select(
    hits: list[Hit],
    k: int,
    *,
    query_vec: list[float],
    embed_hit: Callable[[Hit], list[float] | None],
    mmr_lambda: float,
    embed_once: bool = False,
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
    if embed_once:
        # The caller guarantees embed_hit is deterministic with idempotent side effects.
        return _mmr_select_once(hits, k, query_vec=query_vec, embed_hit=embed_hit, mmr_lambda=mmr_lambda)
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


def _ppr_power_iteration_pure(
    adjacency: Mapping[str, Collection[str]],
    matches_seed: Callable[[str], bool],
    *,
    iterations: int,
    damping: float,
    teleport: float,
) -> dict[str, float]:
    """THE pure oracle for ``ppr_power_iteration`` — the former inline body,
    unchanged, kept directly callable so the parity suite and the pure
    baseline bench never route through dispatch (same convention as the
    ``_*_pure`` bodies in ``mnemosyne.text``)."""
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


def _ppr_power_iteration_closed(
    adjacency: Mapping[str, Collection[str]],
    matches_seed: Callable[[str], bool],
    *,
    iterations: int,
    damping: float,
    teleport: float,
) -> dict[str, float]:
    """Bit-identical to ``_ppr_power_iteration_pure`` for a CLOSED adjacency.

    Closed: every neighbour is itself a key (both shipped engines add every edge in both
    directions), so the pure loop's dicts always hold exactly the adjacency keys, in
    adjacency order. A node whose rank is 0.0 then adds ``damping * 0.0 / n == 0.0`` to each
    neighbour, and ``x + 0.0 == x`` for every non-negative x the loop produces, so skipping
    it changes no value and no key order. Only ranked nodes are visited, still in adjacency
    order and with each node's own neighbour collection, so every float addition happens in
    the pure sequence. ``matches_seed`` is asked once per node, as the native kernel does.
    """
    nodes = list(adjacency)
    seed_flags = [1.0 if matches_seed(node) else 0.0 for node in nodes]
    if iterations <= 0:
        return dict(zip(nodes, seed_flags))
    order = {node: slot for slot, node in enumerate(nodes)}
    seed_nodes = [node for node, flag in zip(nodes, seed_flags) if flag]
    seed_value = teleport * 1.0
    zero_value = teleport * 0.0
    ranked = dict(zip(seed_nodes, [1.0] * len(seed_nodes)))
    final: dict[str, float] = {}
    for _ in range(iterations):
        final = dict.fromkeys(seed_nodes, seed_value)
        for node in sorted(ranked, key=order.__getitem__):
            neighbors = adjacency[node]
            if not neighbors:
                continue
            share = damping * ranked[node] / len(neighbors)
            for neighbor in neighbors:
                final[neighbor] = final.get(neighbor, zero_value) + share
        ranked = {node: value for node, value in final.items() if value != 0.0}
    return {node: final.get(node, zero_value) for node in nodes}


def ppr_power_iteration(
    adjacency: Mapping[str, Collection[str]],
    matches_seed: Callable[[str], bool],
    *,
    iterations: int = 12,
    damping: float = 0.85,
    teleport: float = 0.15,
    closed: bool = False,
) -> dict[str, float]:
    """Personalized PageRank by power iteration (blueprint §22.2 deep mode).

    Constants 12/0.85/0.15 are load-bearing for parity with both shipped
    engines — do not change defaults without a cross-engine golden update.

    ``teleport`` defaults to the literal ``0.15`` rather than being derived
    as ``1.0 - damping``: in IEEE 754 doubles ``1.0 - 0.85`` is
    ``0.15000000000000002 != 0.15``, and the inline code this replaces used
    the literal — deriving it would break bit-exact parity with both engines.

    The native fast path (Wave 2, byte-parity-proven in
    tests/test_native_parity.py) hands the kernel ORDERED index structures so
    every float accumulation happens in exactly the pure loop's dict
    insertion-order sequence; it calls ``matches_seed`` exactly once per node
    (the pure loop re-asks every iteration — both shipped engines pass a pure
    set-membership predicate), mirroring how the native MMR path materializes
    ``embed_hit`` exactly once per hit.
    """
    if text.NATIVE is not None and iterations > 0:
        # iterations <= 0 stays on the canonical pure path: its result is the
        # seed dict over the adjacency keys ONLY, whereas the kernel's node
        # universe already includes out-of-adjacency neighbors.
        #
        # `nodes` = pure result key order: adjacency keys in mapping order
        # (the sources), then out-of-adjacency neighbors appended in
        # first-touch order of the edge sweep — the order the pure dict pass
        # inserts them. Neighbor slots keep each collection's own iteration
        # order (the same objects the pure loop would iterate), so the
        # kernel's summation order is bit-identical. The edge structure
        # crosses the FFI as packed LE-u64 buffers (flat slots + row lengths,
        # the dense_scan_packed strategy): boxed-int extraction measured as
        # the dominant kernel-call cost at a list-of-lists seam.
        nodes = list(adjacency)
        index = {node: slot for slot, node in enumerate(nodes)}
        values = list(adjacency.values())
        row_lens = list(map(len, values))
        try:
            # One C-level pipeline; each dict lookup reuses the key string's
            # cached hash, so this is the cheapest slot resolution available.
            flat = array("Q", map(index.__getitem__, chain.from_iterable(values)))
        except KeyError:
            # Rare shape: out-of-adjacency neighbor(s) — both shipped engines
            # add every edge in BOTH directions, so their neighbors are always
            # keys. Re-walk from the start (Collection values are re-iterable
            # containers with a stable order — the pure loop already re-walks
            # them once per iteration), appending externals in first-touch
            # order — the pure dict pass's insertion order.
            slots: list[int] = []
            for neighbors in values:
                for neighbor in neighbors:
                    slot = index.get(neighbor)
                    if slot is None:
                        slot = len(nodes)
                        index[neighbor] = slot
                        nodes.append(neighbor)
                    slots.append(slot)
            flat = array("Q", slots)
        # bool(...) preserves the pure truthiness test (`1.0 if matches_seed(
        # node) else 0.0`) for predicates returning non-bool truthy values.
        seeds = [bool(matches_seed(node)) for node in nodes]
        scores = text.NATIVE.ppr_power_iteration(
            seeds,
            flat.tobytes(),
            array("Q", row_lens).tobytes(),
            iterations,
            damping,
            teleport,
        )
        return dict(zip(nodes, scores, strict=True))
    if closed:
        # The caller guarantees every neighbour is a key (see _ppr_power_iteration_closed).
        return _ppr_power_iteration_closed(
            adjacency, matches_seed, iterations=iterations, damping=damping, teleport=teleport
        )
    return _ppr_power_iteration_pure(
        adjacency, matches_seed, iterations=iterations, damping=damping, teleport=teleport
    )
