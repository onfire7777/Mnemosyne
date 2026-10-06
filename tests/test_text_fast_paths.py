"""The fast retrieval scorers must equal the original pure functions bit for bit."""

from __future__ import annotations

import random
import struct

import pytest

from mnemosyne.text import (
    SparseCosine,
    _cosine_pure,
    _hashing_embedding_pure,
    _lexical_score_pure,
    lexical_scorer,
)

WORDS = ("film Film FILM directed 1970 the of in a by born died Move (1970 film) actor actress "
         "Paris paris. v1.2 data-only x/y http://a.b/c café naïve Ünïcode _under +plus --dash "
         "award won won won american American director's").split()


def _texts(rng: random.Random, n: int) -> list[str]:
    texts = ["", " ", "...", "a", "the the the"]
    for _ in range(n):
        length = rng.choice([1, 3, 8, 40, 200])
        texts.append(" ".join(rng.choice(WORDS) for _ in range(length)) + rng.choice(["", ".", "!", "\n"]))
    return texts


def _bits(value: float) -> bytes:
    return struct.pack("<d", float(value))


@pytest.mark.parametrize("seed", range(5))
def test_lexical_scorer_equals_the_pure_score_bit_for_bit(seed: int) -> None:
    rng = random.Random(seed)
    texts = _texts(rng, 120)
    for query in _texts(rng, 25):
        score = lexical_scorer(query)
        for text in texts:
            expected = _lexical_score_pure(query, text)
            actual = score(text)
            assert type(actual) is type(expected)
            assert _bits(actual) == _bits(expected), (query, text)


@pytest.mark.parametrize("dims", [16, 256])
@pytest.mark.parametrize("seed", range(5))
def test_sparse_cosine_equals_the_pure_dot_product(seed: int, dims: int) -> None:
    rng = random.Random(seed)
    texts = _texts(rng, 120)
    for query in _texts(rng, 25):
        query_vec = list(_hashing_embedding_pure(query, dims))
        sparse = SparseCosine(query_vec)
        for text in texts:
            expected = _cosine_pure(query_vec, list(_hashing_embedding_pure(text, dims)))
            actual = sparse.hashing(text, dims)
            # Callers only ever ask `score > 0` and then use the score itself.
            assert (actual > 0) == (expected > 0), (query, text)
            if expected > 0:
                assert _bits(actual) == _bits(expected), (query, text)
            else:
                assert actual == expected
