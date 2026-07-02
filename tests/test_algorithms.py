# tests/test_algorithms.py
"""Shared retrieval-algorithm module: characterization + delegation tests."""
from __future__ import annotations

import copy
from types import SimpleNamespace

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.retrieval import Hit


def _hit(kind: str, id_: str, score: float, channel: str) -> Hit:
    return Hit(
        kind=kind,
        id=id_,
        tenant_id="tenant-a",
        branch="main",
        text=f"text-{id_}",
        score=score,
        channel=channel,
    )


def _sample_lists() -> list[list[Hit]]:
    dense = [_hit("evidence", "a", 0.9, "dense_hash"), _hit("evidence", "b", 0.7, "dense_hash")]
    lexical = [_hit("evidence", "b", 3.0, "lexical"), _hit("evidence", "c", 1.0, "lexical")]
    graph: list[Hit] = []
    return [dense, lexical, graph]


def test_rrf_fuse_matches_engine_private_rrf():
    from mnemosyne.algorithms import rrf_fuse

    engine = LocalMemoryEngine()
    lists = _sample_lists()
    expected = engine._rrf(copy.deepcopy(lists), k=4)
    actual = rrf_fuse(copy.deepcopy(lists), k=4, rrf_k=engine.policy.rrf_k)
    assert [(h.kind, h.id, h.score, h.channel) for h in actual] == [
        (h.kind, h.id, h.score, h.channel) for h in expected
    ]


def test_rrf_fuse_merges_channels_and_dedups_by_kind_id():
    from mnemosyne.algorithms import rrf_fuse

    fused = rrf_fuse(_sample_lists(), k=10, rrf_k=60.0)
    b = next(h for h in fused if h.id == "b")
    assert b.channel == "dense_hash+lexical"
    assert len([h for h in fused if h.id == "b"]) == 1
    # rank-1 in one list + rank-2 in another beats a single rank-1
    assert fused[0].id == "b"


def test_rrf_fuse_matches_postgres_private_rrf():
    """The Postgres `_rrf` body carries extra channel-score annotation logic;
    rrf_fuse(annotate_channel_scores=True) must reproduce it byte-identically."""
    from mnemosyne.algorithms import rrf_fuse

    fake_self = SimpleNamespace(policy=SimpleNamespace(rrf_k=60.0))
    lists = _sample_lists()
    expected = PostgresEngine._rrf(fake_self, copy.deepcopy(lists), k=4)
    actual = rrf_fuse(
        copy.deepcopy(lists), k=4, rrf_k=60.0, annotate_channel_scores=True
    )
    assert [h.to_dict() for h in actual] == [h.to_dict() for h in expected]


def test_rrf_fuse_channel_score_annotation():
    from mnemosyne.algorithms import rrf_fuse

    fused = rrf_fuse(_sample_lists(), k=10, rrf_k=60.0, annotate_channel_scores=True)
    b = next(h for h in fused if h.id == "b")
    assert b.metadata["channels"] == ["dense_hash", "lexical"]
    assert b.metadata["channel_scores"] == {"dense_hash": 0.7, "lexical": 3.0}
    # default path leaves metadata untouched
    plain = rrf_fuse(_sample_lists(), k=10, rrf_k=60.0)
    b_plain = next(h for h in plain if h.id == "b")
    assert "channels" not in b_plain.metadata
    assert "channel_scores" not in b_plain.metadata


def test_u_curve_order_interleaves_front_back():
    from mnemosyne.algorithms import u_curve_order

    hits = [_hit("evidence", str(i), 1.0 - i * 0.1, "lexical") for i in range(5)]
    ordered = u_curve_order(hits)
    assert [h.id for h in ordered] == ["0", "2", "4", "3", "1"]


def test_fit_budget_skips_items_over_budget_and_reports_usage():
    from mnemosyne.algorithms import fit_budget
    from mnemosyne.text import approx_tokens

    small = _hit("evidence", "s", 1.0, "lexical")
    small.text = "tiny"
    big = _hit("evidence", "b", 0.9, "lexical")
    big.text = "x" * 4000
    kept, used = fit_budget([big, small], budget=approx_tokens("tiny") + 1)
    assert [h.id for h in kept] == ["s"]
    assert used == approx_tokens("tiny")


def test_extracted_helpers_match_engine_statics():
    from mnemosyne.algorithms import fit_budget, u_curve_order

    engine = LocalMemoryEngine()
    hits = [_hit("evidence", str(i), 1.0 - i * 0.05, "lexical") for i in range(7)]
    assert [h.id for h in u_curve_order(hits)] == [h.id for h in engine._u_curve_order(hits)]
    assert fit_budget(hits, 50) == engine._fit_budget(hits, 50)


def test_ppr_power_iteration_constants_and_ranking():
    from mnemosyne.algorithms import ppr_power_iteration

    adjacency = {"seed": ["a", "b"], "a": ["b"], "b": [], "island": []}
    ranks = ppr_power_iteration(adjacency, lambda n: n == "seed")
    # b receives mass from both seed and a -> outranks a; island gets nothing
    assert ranks["b"] > ranks["a"] > 0.0
    assert ranks.get("island", 0.0) == 0.0
    # teleport keeps the seed's own rank anchored at >= 0.15
    assert ranks["seed"] >= 0.15


def test_ppr_power_iteration_is_deterministic():
    from mnemosyne.algorithms import ppr_power_iteration

    adjacency = {"s": ["x", "y"], "x": ["y"], "y": ["x"]}
    r1 = ppr_power_iteration(adjacency, lambda n: n == "s")
    r2 = ppr_power_iteration(adjacency, lambda n: n == "s")
    assert r1 == r2


def test_ppr_power_iteration_defaults_are_pinned_exactly():
    """teleport MUST be the literal 0.15: 1.0 - 0.85 != 0.15 in IEEE-754.

    These defaults are load-bearing for cross-engine bit parity (plan §Global
    Constraints) and for the Phase-1 native kernel, which must mirror the
    literal, never derive it.
    """
    from mnemosyne.algorithms import ppr_power_iteration

    assert ppr_power_iteration.__kwdefaults__ == {
        "iterations": 12,
        "damping": 0.85,
        "teleport": 0.15,
    }
    assert ppr_power_iteration.__kwdefaults__["teleport"] != 1.0 - 0.85


def test_mmr_select_matches_local_engine_mmr():
    from mnemosyne.algorithms import mmr_select

    engine = LocalMemoryEngine()
    hits = [_hit("evidence", str(i), 0.5 + i * 0.1, "lexical") for i in range(4)]
    for h in hits:
        h.text = f"unique text {h.id}"
    expected = engine._mmr("some query", list(hits), k=3)
    query_vec = engine._embed_text("some query")
    actual = mmr_select(
        list(hits), 3,
        query_vec=query_vec,
        embed_hit=lambda h: engine._embedding_for_hit(h, allow_fallback=True),
        mmr_lambda=engine.policy.mmr_lambda,
    )
    assert [h.id for h in actual] == [h.id for h in expected]


def test_mmr_select_matches_postgres_private_mmr():
    """The Postgres `_mmr` hardcodes hashing_embedding for BOTH query and hit
    vectors (deliberately divergent from Local's security-gated sourcing,
    spec §4.0); mmr_select with those exact closures must reproduce it."""
    from mnemosyne.algorithms import mmr_select
    from mnemosyne.text import hashing_embedding

    fake_self = SimpleNamespace(policy=SimpleNamespace(mmr_lambda=0.7))
    hits = [_hit("evidence", str(i), 0.5 + i * 0.1, "lexical") for i in range(4)]
    for h in hits:
        h.text = f"unique text {h.id}"
    expected = PostgresEngine._mmr(fake_self, "some query", list(hits), k=3)
    actual = mmr_select(
        list(hits), 3,
        query_vec=hashing_embedding("some query"),
        embed_hit=lambda h: hashing_embedding(h.text),
        mmr_lambda=0.7,
    )
    assert [h.id for h in actual] == [h.id for h in expected]


def test_mmr_select_base_score_dominates_and_ties_are_first_wins():
    from mnemosyne.algorithms import mmr_select

    a = _hit("evidence", "a", 5.0, "lexical")
    b = _hit("evidence", "b", 5.0, "lexical")  # identical score: 'a' must win (input order)
    picked = mmr_select([a, b], 1, query_vec=[0.0], embed_hit=lambda h: None, mmr_lambda=0.7)
    assert picked[0].id == "a"


def test_mmr_select_missing_vector_means_zero_relevance_no_penalty():
    from mnemosyne.algorithms import mmr_select

    strong = _hit("evidence", "strong", 1.0, "lexical")
    weak = _hit("evidence", "weak", 0.0, "lexical")
    picked = mmr_select([weak, strong], 2, query_vec=[1.0], embed_hit=lambda h: None, mmr_lambda=0.7)
    assert {h.id for h in picked} == {"weak", "strong"}
