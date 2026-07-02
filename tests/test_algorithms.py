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
