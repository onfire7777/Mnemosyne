"""Bit-equality between mnemosyne_native kernels and the pure-Python path.

Every comparison is on struct.pack('<d') bytes — parity means BITS, not ==.
(Python float == would conflate NaN and blur ±0.0; byte comparison does not.)

Covers Phase-1 Tasks 2–5: hashing_embedding, tokenize, lexical_score /
lexical_scan, cosine / dense_scan, mmr_select_indices, plus the single
documented transcendental exception: the `ln` inside lexical_score must match
CPython's math.log bit-for-bit (proven by the tf=1..10_000 loop below via the
test-only native._ln helper).
"""
from __future__ import annotations

import math
import array
import struct

import pytest
from hypothesis import given, settings, strategies as st

native = pytest.importorskip("mnemosyne_native")

# The _*_pure functions are THE oracles: parity is native-vs-PURE by
# construction, never native-vs-native, regardless of which path the
# dispatching public functions take in this process (Task 6).
from mnemosyne.text import (  # noqa: E402
    _cosine_pure as cosine,
    _hashing_embedding_pure,
    _lexical_score_pure as lexical_score,
    _tokenize_pure as tokenize,
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
    # _hashing_embedding_pure = the raw uncached pure compute (the lru_cache
    # now wraps the DISPATCHING compute, whose __wrapped__ would be
    # native-vs-native in native mode; parity target is the raw pure compute).
    pure = _hashing_embedding_pure(text, dims)
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
        pure = _hashing_embedding_pure(text, dims)
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


# --- Task 4: cosine / dense_scan --------------------------------------------


floats = st.floats(allow_nan=False, allow_infinity=False, width=64)
vecs = st.lists(floats, min_size=0, max_size=64)


@given(vecs, vecs)
@settings(max_examples=300, deadline=None)
def test_cosine_bit_identical_incl_truncation(a, b):
    assert struct.pack("<d", native.cosine(a, b)) == struct.pack("<d", cosine(a, b))


def test_cosine_golden_truncation():
    # zip(strict=False) semantics: silently truncate to the shorter input.
    assert native.cosine([1.0, 2.0, 3.0], [4.0, 5.0]) == 14.0
    assert native.cosine([], [1.0, 2.0]) == 0.0


@given(vecs, st.lists(st.one_of(st.none(), vecs), min_size=0, max_size=20))
@settings(max_examples=200, deadline=None)
def test_dense_scan_matches_per_row_loop(q, rows):
    expected = [None if r is None else cosine(q, r) for r in rows]
    got = native.dense_scan(q, rows)
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        if e is None:
            assert g is None
        else:
            assert struct.pack("<d", g) == struct.pack("<d", e)


@st.composite
def _packed_dense_cases(draw):
    # dense_scan_packed's contract is equal-dims rows (the packed layout has
    # no per-row length), so every present row is exactly `dims` long.
    dims = draw(st.integers(min_value=0, max_value=8))
    fixed_vec = st.lists(floats, min_size=dims, max_size=dims)
    q = draw(fixed_vec)
    rows = draw(st.lists(st.one_of(st.none(), fixed_vec), min_size=0, max_size=20))
    return dims, q, rows


@given(_packed_dense_cases())
@settings(max_examples=200, deadline=None)
def test_dense_scan_packed_matches_dense_scan_bitwise(case):
    # dense_scan is the bit-parity-proven oracle (vs pure cosine above), so
    # packed-vs-dense_scan bit-equality transitively proves packed-vs-pure.
    dims, q, rows = case
    packed = bytearray()
    mask = bytearray()
    placeholder = bytes(8 * dims)  # masked-out rows: bytes never read
    for r in rows:
        if r is None:
            mask.append(0)
            packed += placeholder
        else:
            mask.append(1)
            packed += array.array("d", r).tobytes()
    got = native.dense_scan_packed(
        array.array("d", q).tobytes(), bytes(packed), dims, bytes(mask)
    )
    expected = native.dense_scan(q, rows)
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        if e is None:
            assert g is None
        else:
            assert struct.pack("<d", g) == struct.pack("<d", e)


# --- Task 5: mmr_select_indices ---------------------------------------------


def _reference_mmr(base_scores, vectors, query_vec, k, mmr_lambda):
    """Pure mirror of algorithms.mmr_select over pre-materialized vectors.

    THE oracle for the native kernel — line-for-line faithful to the pure
    code: two-statement objective (`lam * rel - (1.0 - lam) * penalty` THEN
    `+= base`), strict `>` argmax (first-wins on input index), penalty SKIPS
    None vectors of selected items and stays 0.0 when all of them are None.
    """
    selected: list[int] = []
    remaining = list(range(len(base_scores)))
    while remaining and len(selected) < k:
        best = None
        best_score = float("-inf")
        for i in remaining:
            vec = vectors[i]
            relevance = cosine(query_vec, vec) if vec is not None else 0.0
            diversity_penalty = 0.0
            if selected and vec is not None:
                selected_vectors = [v for j in selected if (v := vectors[j]) is not None]
                if selected_vectors:
                    diversity_penalty = max(cosine(vec, sv) for sv in selected_vectors)
            score = mmr_lambda * relevance - (1.0 - mmr_lambda) * diversity_penalty
            score += base_scores[i]
            if score > best_score:
                best = i
                best_score = score
        if best is None:
            break
        selected.append(best)
        remaining.remove(best)
    return selected


@given(
    st.lists(floats, min_size=0, max_size=12),  # base_scores
    st.data(),
)
@settings(max_examples=200, deadline=None)
def test_mmr_select_indices_matches_reference(base_scores, data):
    n = len(base_scores)
    vectors = data.draw(
        st.lists(
            st.one_of(st.none(), st.lists(floats, min_size=3, max_size=3)),
            min_size=n,
            max_size=n,
        )
    )
    k = data.draw(st.integers(min_value=0, max_value=n + 2))
    lam = data.draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    q = data.draw(st.lists(floats, min_size=3, max_size=3))
    assert native.mmr_select_indices(base_scores, vectors, q, k, lam) == _reference_mmr(
        base_scores, vectors, q, k, lam
    )


def test_mmr_ties_first_wins_on_input_order():
    # identical base scores, no vectors: argmax ties resolve to lowest index
    assert native.mmr_select_indices(
        [5.0, 5.0, 5.0], [None, None, None], [1.0], 2, 0.7
    ) == [0, 1]


def test_mmr_penalty_skips_none_selected_vectors():
    # Selected item 0 has NO vector => later candidates see ZERO diversity
    # penalty (the pure comprehension skips None vectors of selected items;
    # empty => penalty stays 0.0). Ranking is then lam*relevance + base only.
    base = [10.0, 0.0, 0.0]
    vectors = [None, [1.0, 0.0, 0.0], [0.9, 0.0, 0.0]]
    q = [1.0, 0.0, 0.0]
    got = native.mmr_select_indices(base, vectors, q, 3, 0.5)
    assert got == _reference_mmr(base, vectors, q, 3, 0.5)
    assert got == [0, 1, 2]


def test_mmr_k_nonpositive_or_exhaustion():
    # k <= 0 selects nothing (mirrors `len(selected) < k` in the pure loop);
    # k > n exhausts remaining and returns all indices in selection order.
    assert native.mmr_select_indices([1.0], [None], [], 0, 0.5) == []
    assert native.mmr_select_indices([1.0], [None], [], -1, 0.5) == []
    assert native.mmr_select_indices(
        [0.0, 1.0], [None, None], [1.0, 2.0, 3.0], 5, 0.3
    ) == [1, 0]


def test_mmr_rejects_length_mismatch():
    # Kernel contract: vectors are PRE-materialized 1:1 with base_scores
    # (Task 6 owns materialization). A mismatch is a caller bug, not a
    # truncation case.
    with pytest.raises(ValueError):
        native.mmr_select_indices([1.0, 2.0], [None], [1.0], 1, 0.5)
