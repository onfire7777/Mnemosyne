"""Deterministic local retrieval primitives."""

from __future__ import annotations

import math
import re
from collections import Counter
from hashlib import blake2b
from typing import Iterable

TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_:+./-]*")


def tokenize(text: str) -> list[str]:
    # Strip trailing/leading sentence punctuation so e.g. "instructions." matches
    # the query "instructions", while keeping internal dots/hyphens/slashes that
    # carry meaning (URLs, versions, hyphenated capability tags like "data-only").
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0).lower().strip("./:+-")
        if token:
            tokens.append(token)
    return tokens


def term_counts(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def lexical_score(query: str, text: str) -> float:
    q = term_counts(query)
    if not q:
        return 0.0
    doc = term_counts(text)
    score = 0.0
    doc_len = max(sum(doc.values()), 1)
    for term, q_count in q.items():
        tf = doc.get(term, 0)
        if tf:
            score += (1.0 + math.log(tf)) * q_count
    return score / math.sqrt(doc_len)


def hashing_embedding(text: str, dims: int = 256) -> list[float]:
    vec = [0.0] * dims
    for token in tokenize(text):
        digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))

