"""MMR with each hit embedded once and sparse dot products selects exactly what the pure loop does."""

from __future__ import annotations

import random

import pytest

from mnemosyne import text
from mnemosyne.algorithms import _mmr_select_once, mmr_select
from mnemosyne.models import Hit
from mnemosyne.text import hashing_embedding

WORDS = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho".split()


def _hits(rng: random.Random) -> list[Hit]:
    hits = []
    for i in range(rng.randint(0, 25)):
        words = rng.sample(WORDS, rng.randint(1, 6))
        hits.append(Hit(id=f"h{i}", kind="assertion", tenant_id="t", branch="main", text=" ".join(words),
                        score=rng.choice([0.0, 0.5, rng.random(), rng.random() * 3]), channel="dense"))
    return hits


@pytest.mark.parametrize("seed", range(150))
def test_mmr_embedding_each_hit_once_selects_like_the_pure_loop(seed: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text, "NATIVE", None)
    rng = random.Random(seed)
    hits = _hits(rng)
    dims = rng.choice([16, 64, 256])
    missing = {hit.id for hit in hits if rng.random() < 0.15}
    # Some hits carry "stored" dense vectors of another length, as stored embeddings can.
    stored = {hit.id: [rng.uniform(-1, 1) for _ in range(rng.choice([dims, dims // 2]))]
              for hit in hits if rng.random() < 0.2}

    def embed(hit: Hit) -> list[float] | None:
        if hit.id in missing:
            return None
        return list(stored[hit.id]) if hit.id in stored else hashing_embedding(hit.text, dims)

    query_vec = hashing_embedding(" ".join(rng.sample(WORDS, 3)), dims)
    k = rng.randint(0, 12)
    mmr_lambda = rng.choice([0.0, 0.3, 0.5, 0.7, 1.0])
    pure = mmr_select(hits, k, query_vec=query_vec, embed_hit=embed, mmr_lambda=mmr_lambda)
    once = mmr_select(hits, k, query_vec=query_vec, embed_hit=embed, mmr_lambda=mmr_lambda, embed_once=True)
    assert [hit.id for hit in once] == [hit.id for hit in pure]
    if k > 0:
        assert [hit.id for hit in _mmr_select_once(hits, k, query_vec=query_vec, embed_hit=embed,
                                                  mmr_lambda=mmr_lambda)] == [hit.id for hit in pure]


def test_non_finite_vectors_take_the_pure_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text, "NATIVE", None)
    hits = [Hit(id=f"h{i}", kind="assertion", tenant_id="t", branch="main", text=f"w{i}", score=0.1 * i, channel="d")
            for i in range(4)]
    vectors = {"h0": [float("nan"), 1.0], "h1": [0.0, 1.0], "h2": [1.0, 0.0], "h3": [0.5, 0.5]}
    embed = lambda hit: vectors[hit.id]  # noqa: E731
    pure = mmr_select(hits, 3, query_vec=[1.0, 0.0], embed_hit=embed, mmr_lambda=0.5)
    once = mmr_select(hits, 3, query_vec=[1.0, 0.0], embed_hit=embed, mmr_lambda=0.5, embed_once=True)
    assert [hit.id for hit in once] == [hit.id for hit in pure]
