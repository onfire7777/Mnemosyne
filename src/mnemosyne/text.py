"""Deterministic local retrieval primitives.

Dispatch layer (Phase-1 Task 6): each primitive routes through the native
kernels in ``mnemosyne_native`` when the extension is importable, falling back
to the pure-Python bodies (kept as ``_*_pure``) otherwise. ``MNEMOSYNE_PURE=1``
forces the pure path at import time. The two paths are byte-parity-proven
(tests/test_native_parity.py), so dispatch is a pure speed decision — never a
behavior decision.
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from collections.abc import Sequence
from functools import lru_cache
from hashlib import blake2b
from typing import Iterable

try:
    if os.environ.get("MNEMOSYNE_PURE") == "1":
        NATIVE = None
    else:
        import mnemosyne_native as NATIVE  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - environment-dependent
    NATIVE = None

logging.getLogger("mnemosyne.native").info(
    "kernel path: %s",
    "native (mnemosyne_native)" if NATIVE is not None else "pure-python",
)

TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_:+./-]*")


def _tokenize_pure(text: str) -> list[str]:
    # Strip trailing/leading sentence punctuation so e.g. "instructions." matches
    # the query "instructions", while keeping internal dots/hyphens/slashes that
    # carry meaning (URLs, versions, hyphenated capability tags like "data-only").
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0).lower().strip("./:+-")
        if token:
            tokens.append(token)
    return tokens


def tokenize(text: str) -> list[str]:
    return NATIVE.tokenize(text) if NATIVE is not None else _tokenize_pure(text)


def term_counts(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def _lexical_score_pure(query: str, text: str) -> float:
    # Counts via _tokenize_pure (not the dispatching tokenize) so this stays a
    # fully pure oracle for the parity suite even when NATIVE is active.
    q = Counter(_tokenize_pure(query))
    if not q:
        return 0.0
    doc = Counter(_tokenize_pure(text))
    score = 0.0
    doc_len = max(sum(doc.values()), 1)
    for term, q_count in q.items():
        tf = doc.get(term, 0)
        if tf:
            score += (1.0 + math.log(tf)) * q_count
    return score / math.sqrt(doc_len)


def lexical_score(query: str, text: str) -> float:
    return (
        NATIVE.lexical_score(query, text)
        if NATIVE is not None
        else _lexical_score_pure(query, text)
    )


def _hashing_embedding_pure(text: str, dims: int) -> tuple[float, ...]:
    vec = [0.0] * dims
    for token in _tokenize_pure(text):
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return tuple(vec)
    return tuple(x / norm for x in vec)


@lru_cache(maxsize=8192)
def _hashing_embedding_cached(text: str, dims: int) -> tuple[float, ...]:
    # The lru_cache wraps the DISPATCHING compute: it caches whichever backend
    # produced the value, and byte-parity makes the backends interchangeable,
    # so cache behavior (keys, hits, stored tuples) is identical in both modes.
    if NATIVE is not None:
        return tuple(NATIVE.hashing_embedding(text, dims))
    return _hashing_embedding_pure(text, dims)


def hashing_embedding(text: str, dims: int = 256) -> list[float]:
    # Memoized on (text, dims): the function is pure and deterministic, so cache
    # hits return byte-identical values while skipping the tokenize + per-token
    # blake2b work. A fresh list is returned each call so callers may still mutate
    # it safely (the cache holds an immutable tuple). Retrieval (esp. MMR) embeds
    # the same hit texts thousands of times per query, so this is a large win.
    return list(_hashing_embedding_cached(text, dims))


def _cosine_pure(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # Type nuance on empty inputs: the pure path returns int 0 (builtin sum of
    # an empty stream) while the native kernel returns float 0.0. The two are
    # == equal and bit-equal under struct.pack('<d'); neither side is
    # normalized here — coercing either one would be a behavior change in that
    # mode.
    return NATIVE.cosine(a, b) if NATIVE is not None else _cosine_pure(a, b)


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))
