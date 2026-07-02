"""Bit-equality between mnemosyne_native kernels and the pure-Python path.

Every comparison is on struct.pack('<d') bytes — parity means BITS, not ==.
(Python float == would conflate NaN and blur ±0.0; byte comparison does not.)

Covers Phase-1 Tasks 2–3: hashing_embedding, tokenize, lexical_score /
lexical_scan, plus the single documented transcendental exception: the `ln`
inside lexical_score must match CPython's math.log bit-for-bit (proven by the
tf=1..10_000 loop below via the test-only native._ln helper).
"""
from __future__ import annotations

import math
import struct

import pytest
from hypothesis import given, settings, strategies as st

native = pytest.importorskip("mnemosyne_native")

from mnemosyne.text import (  # noqa: E402
    _hashing_embedding_cached,
    lexical_score,
    tokenize,
)


def bits(xs: list[float]) -> bytes:
    return b"".join(struct.pack("<d", x) for x in xs)


texts = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs",)),
    max_size=400,
)


# --- Task 2: hashing_embedding -------------------------------------------


@given(texts, st.sampled_from([16, 256, 1024]))
@settings(max_examples=200, deadline=None)
def test_hashing_embedding_bit_identical(text, dims):
    # __wrapped__ = the uncached pure function (lru_cache would otherwise
    # serve tuples cached across examples; parity target is the raw compute).
    pure = _hashing_embedding_cached.__wrapped__(text, dims)
    assert bits(native.hashing_embedding(text, dims)) == bits(list(pure))


def test_hashing_embedding_golden_zero_norm():
    # No tokens => zero vector, returned UNNORMALIZED (norm==0.0 branch)
    assert native.hashing_embedding("!!! ???", 8) == [0.0] * 8


def test_hashing_embedding_golden_examples_bit_identical():
    cases = [
        ("alpha beta", 8),
        ("alpha alpha alpha", 16),  # repeated token accumulation order
        ("v1.2.3 data-only token-with/slash instructions.", 16),
        ("The THE the", 256),  # lower() folding into one bucket
    ]
    for text, dims in cases:
        pure = _hashing_embedding_cached.__wrapped__(text, dims)
        assert bits(native.hashing_embedding(text, dims)) == bits(list(pure))


# --- Task 3: tokenize ------------------------------------------------------


@given(texts)
@settings(max_examples=200, deadline=None)
def test_tokenize_identical(text):
    assert native.tokenize(text) == tokenize(text)


def test_tokenize_golden_examples():
    cases = [
        "Hello, WORLD... v1.2.3 data-only",
        "http://a.b/c d-e- -f .g. :::",
        "a....b ++c++ -- ../..",  # strip-to-empty and edge punctuation
        "MiXeD_Case:token+one/two.three-",
        "π ünïcode around ascii1 tokens2",  # non-ASCII never matches
    ]
    for text in cases:
        assert native.tokenize(text) == tokenize(text)


# --- Task 3: lexical_score / lexical_scan ----------------------------------


@given(texts, texts)
@settings(max_examples=200, deadline=None)
def test_lexical_score_bit_identical(query, text):
    assert struct.pack("<d", native.lexical_score(query, text)) == struct.pack(
        "<d", lexical_score(query, text)
    )


def test_lexical_score_duplicate_query_tokens_bit_identical():
    # Accumulation order = FIRST-OCCURRENCE order of query tokens (dict
    # insertion order in the pure path); duplicates must not reorder terms.
    query = "beta alpha beta gamma alpha beta"
    text = "alpha beta beta gamma alpha delta gamma gamma"
    assert struct.pack("<d", native.lexical_score(query, text)) == struct.pack(
        "<d", lexical_score(query, text)
    )


def test_lexical_scan_matches_loop_bitwise():
    docs = ["alpha beta beta", "beta gamma", "", "alpha alpha alpha delta"]
    q = "beta alpha beta"  # duplicate first-occurrence-order stressor
    assert bits(native.lexical_scan(q, docs)) == bits(
        [lexical_score(q, d) for d in docs]
    )


# --- The documented transcendental exception: ln vs math.log ---------------


def test_ln_matches_math_log_bitwise_tf_1_to_10000():
    # lexical_score computes (1.0 + ln(tf)) * q_count; tf is a positive
    # integer term frequency. Prove Rust f64::ln == CPython math.log
    # bit-for-bit across the realistic tf range. native._ln is test-only.
    divergent = [
        (tf, native._ln(float(tf)), math.log(tf))
        for tf in range(1, 10_001)
        if struct.pack("<d", native._ln(float(tf)))
        != struct.pack("<d", math.log(tf))
    ]
    assert divergent == []


@given(st.integers(min_value=1, max_value=2**53))
@settings(max_examples=200, deadline=None)
def test_ln_matches_math_log_bitwise_property(tf):
    assert struct.pack("<d", native._ln(float(tf))) == struct.pack(
        "<d", math.log(tf)
    )
