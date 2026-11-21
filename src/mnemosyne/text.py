"""Deterministic local retrieval primitives.

Dispatch layer (Phase-1 Task 6): each primitive routes through the native
kernels in ``mnemosyne_native`` when the extension is importable, falling back
to the pure-Python bodies (kept as ``_*_pure``) otherwise. ``MNEMOSYNE_PURE=1``
forces the pure path at import time. The two paths are byte-parity-proven
(tests/test_native_parity.py) on ASCII text, so dispatch is a pure speed
decision — never a behavior decision. The native tokenizer is ASCII-only, so
non-ASCII text always takes the pure path.
"""

from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from functools import lru_cache
from hashlib import blake2b
from typing import Callable, Iterable, Mapping

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
# shortcut: kana/han/hangul are one token per character, and Thai/Indic/vocalised-Arabic words
# split at combining signs; upgrade to bigrams or a segmenter if precision matters.
_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
# (?=\w) keeps punctuation inside the kana block ("\u30fb") from becoming a token
_UNICODE_TOKEN_RE = re.compile(rf"(?=\w)[{_CJK}]|[^\W{_CJK}](?:[^\W{_CJK}]|[:+./-])*")
_ACCENT_RE = re.compile("(?<=[a-z])[\u0300-\u036f]+")  # Latin only: Cyrillic й is not и


def _tokenize_pure(text: str) -> list[str]:
    # Strip trailing/leading sentence punctuation so e.g. "instructions." matches
    # the query "instructions", while keeping internal dots/hyphens/slashes that
    # carry meaning (URLs, versions, hyphenated capability tags like "data-only").
    tokens: list[str] = []
    token_re = TOKEN_RE
    if not text.isascii():
        # Fold case and Latin accents so "naive" finds "naïve"; NFC recomposes everything else.
        text = unicodedata.normalize(
            "NFC", _ACCENT_RE.sub("", unicodedata.normalize("NFD", text.casefold()))
        )
        token_re = _UNICODE_TOKEN_RE
    for match in token_re.finditer(text):
        token = match.group(0).lower().strip("./:+-")
        if token:
            tokens.append(token)
            if "-" in token:
                for part in token.split("-"):
                    cleaned = part.strip("./:+-")
                    if cleaned and cleaned != token:
                        tokens.append(cleaned)
    return tokens


_ASCII_CHARS = frozenset(chr(i) for i in range(128))
_UNICODE_SEP_FORBIDDEN_RE = re.compile(r"[\w:+./-]")
_UNICODE_SEP_CACHE: dict[str, bool] = {}


def _is_unicode_separator(ch: str) -> bool:
    """True iff ``ch`` (ord >= 128) is strictly a token separator under ``_tokenize_pure``.

    Combining marks (category M*) are always False because NFD/NFC or ``_ACCENT_RE``
    can interact with adjacent ASCII letters. Any character whose raw, casefolded,
    NFD, or accent-stripped NFC form matches ``[\\w:+./-]`` is also False.
    """
    cached = _UNICODE_SEP_CACHE.get(ch)
    if cached is not None:
        return cached
    if unicodedata.category(ch).startswith("M") or _UNICODE_SEP_FORBIDDEN_RE.search(ch):
        result = False
    else:
        folded = ch.casefold()
        if _UNICODE_SEP_FORBIDDEN_RE.search(folded):
            result = False
        else:
            nfd = unicodedata.normalize("NFD", folded)
            if _UNICODE_SEP_FORBIDDEN_RE.search(nfd):
                result = False
            else:
                nfc = unicodedata.normalize("NFC", _ACCENT_RE.sub("", nfd))
                result = not _UNICODE_SEP_FORBIDDEN_RE.search(nfc)
    if len(_UNICODE_SEP_CACHE) < 16_384:
        _UNICODE_SEP_CACHE[ch] = result
    return result


def _project_ascii_separators(text: str) -> str | None:
    """Project separator-only non-ASCII text to bit-equivalent ASCII, or return None.

    When every non-ASCII code point in ``text`` is a pure separator (e.g. em-dashes,
    curly quotes, arrows, box-drawing characters, emojis), replacing them with ASCII
    space yields the exact same token stream as ``_tokenize_pure`` while allowing the
    fast ASCII/native tokenizer to run.
    """
    if text.isascii():
        return text
    non_ascii = set(text) - _ASCII_CHARS
    for ch in non_ascii:
        if not _is_unicode_separator(ch):
            return None
    return text.translate({ord(ch): 32 for ch in non_ascii})


def _tokenize_native_ascii(ascii_text: str) -> list[str]:
    raw = NATIVE.tokenize(ascii_text)
    tokens: list[str] = []
    for t in raw:
        tokens.append(t)
        if "-" in t:
            for part in t.split("-"):
                cleaned = part.strip("./:+-")
                if cleaned and cleaned != t:
                    tokens.append(cleaned)
    return tokens


def tokenize(text: str) -> list[str]:
    if NATIVE is not None:
        if text.isascii():
            return _tokenize_native_ascii(text)
        projected = _project_ascii_separators(text)
        if projected is not None:
            return _tokenize_native_ascii(projected)
    return _tokenize_pure(text)


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
    if NATIVE is not None:
        q_ascii = _project_ascii_separators(query)
        if q_ascii is not None:
            t_ascii = _project_ascii_separators(text)
            if t_ascii is not None:
                return NATIVE.lexical_score(q_ascii, t_ascii)
    return _lexical_score_pure(query, text)


@lru_cache(maxsize=131_072)
def _document_term_stats(text: str) -> tuple[Counter[str], float]:
    """A document's token counts and sqrt(length), computed once per distinct text."""
    doc = Counter(tokenize(text))
    return doc, math.sqrt(max(sum(doc.values()), 1))


def lexical_scorer(query: str) -> Callable[[str], float]:
    """``lexical_scorer(query)(text) == _lexical_score_pure(query, text)``, bit for bit.

    Scoring one query against many candidates used to re-tokenize every candidate text on
    every query. Here the query is tokenized once and each text's counts are cached; the
    same terms are visited in the same order and the same float operations run in the same
    order, so every score is identical (tests/test_text_fast_paths.py).
    """
    q = Counter(tokenize(query))
    if not q:
        return lambda text: 0.0
    terms = list(q.items())

    def score(text: str) -> float:
        doc, root = _document_term_stats(text)
        total = 0.0
        for term, q_count in terms:
            tf = doc.get(term, 0)
            if tf:
                total += (1.0 + math.log(tf)) * q_count
        return total / root

    return score


def lexical_scan(query: str, texts: list[str]) -> list[float]:
    """``NATIVE.lexical_scan`` for ASCII texts, cached token-stat scorer for non-ASCII."""
    if not texts:
        return []
    score = lexical_scorer(query)
    if NATIVE is None:
        return [score(text) for text in texts]
    q_ascii = _project_ascii_separators(query)
    if q_ascii is None:
        return [score(text) for text in texts]
    # Only dispatch pure-ASCII texts to NATIVE.lexical_scan so non-ASCII texts
    # are not scanned twice; non-ASCII texts use cached _document_term_stats
    # (which itself projects separator-only non-ASCII into NATIVE.tokenize once).
    ascii_indices: list[int] = []
    ascii_texts: list[str] = []
    results = [0.0] * len(texts)
    for idx, text in enumerate(texts):
        if text.isascii():
            ascii_indices.append(idx)
            ascii_texts.append(text)
        else:
            results[idx] = score(text)
    if ascii_texts:
        native_scores = NATIVE.lexical_scan(q_ascii, ascii_texts)
        for idx, val in zip(ascii_indices, native_scores, strict=True):
            results[idx] = val
    return results


_BM25_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "actually",
        "all",
        "also",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "me",
        "more",
        "most",
        "my",
        "not",
        "now",
        "of",
        "on",
        "or",
        "our",
        "please",
        "really",
        "should",
        "some",
        "still",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_BM25_IRREGULAR_STEMS: dict[str, str] = {
    "bought": "buy",
    "built": "build",
    "drove": "driv",
    "driven": "driv",
    "found": "find",
    "gave": "giv",
    "given": "giv",
    "goes": "go",
    "going": "go",
    "went": "go",
    "made": "mak",
    "paid": "pay",
    "ran": "run",
    "said": "say",
    "saw": "see",
    "seen": "see",
    "sent": "send",
    "sold": "sell",
    "spent": "spend",
    "took": "tak",
    "taken": "tak",
    "told": "tell",
    "written": "writ",
    "wrote": "writ",
}

_BM25_STEM_IRREGULARS: dict[str, tuple[str, ...]] = {}
for _irr_word, _irr_stem in _BM25_IRREGULAR_STEMS.items():
    _BM25_STEM_IRREGULARS[_irr_stem] = _BM25_STEM_IRREGULARS.get(_irr_stem, ()) + (_irr_word,)


@lru_cache(maxsize=65_536)
def _bm25_stem(token: str) -> str:
    """Conservative, deterministic ASCII suffix stemmer for corpus-IDF BM25."""
    t = token.lower()
    if t in _BM25_IRREGULAR_STEMS:
        return _BM25_IRREGULAR_STEMS[t]
    if len(t) < 4 or not (t.isascii() and t.isalpha()):
        return t
    if len(t) >= 5 and t.endswith(("ies", "ied")):
        return t[:-3] + "y"
    if len(t) >= 5 and t.endswith("es") and not t.endswith(("aes", "ees", "oes")):
        if t.endswith(("ches", "shes", "sses", "xes", "zes")):
            t = t[:-2]
        else:
            t = t[:-1]
    elif len(t) >= 4 and t.endswith("s") and not t.endswith(("ss", "us", "is", "as", "os")):
        t = t[:-1]
    if len(t) >= 6 and t.endswith("ing"):
        base = t[:-3]
        if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "lsz":
            base = base[:-1]
        t = base
    elif len(t) >= 5 and t.endswith("ed") and not t.endswith("eed"):
        base = t[:-2]
        if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "lsz":
            base = base[:-1]
        t = base
    if len(t) >= 4 and t.endswith("e") and not t.endswith(("ee", "ie", "ye", "oe")):
        t = t[:-1]
    return t


def bm25_fts_match_clauses(query: str) -> list[str]:
    """FTS5 MATCH clauses forming a recall superset of ``bm25_query_terms(query)``."""
    clauses: list[str] = []
    seen: set[str] = set()
    for stem, _ in bm25_query_terms(query):
        if stem.isascii() and stem.isalpha() and len(stem) >= 3:
            prefix = stem[:-1] if (stem.endswith("y") and len(stem) >= 4) else stem
            clause = f'"{prefix}"*'
            if clause not in seen:
                seen.add(clause)
                clauses.append(clause)
        else:
            clause = f'"{stem}"'
            if clause not in seen:
                seen.add(clause)
                clauses.append(clause)
        for irr in _BM25_STEM_IRREGULARS.get(stem, ()):
            irr_clause = f'"{irr}"'
            if irr_clause not in seen:
                seen.add(irr_clause)
                clauses.append(irr_clause)
    return clauses


def bm25_corpus_avg_doc_len(texts: Sequence[str]) -> float:
    """Average tokenized document length across ``texts`` (uses cached doc stats)."""
    if not texts:
        return 1.0
    total = sum(_bm25_doc_stats(text)[1] for text in texts)
    return (total / len(texts)) if total > 0 else 1.0


@lru_cache(maxsize=131_072)
def _bm25_doc_stats(text: str) -> tuple[dict[str, int], int]:
    """Cached stemmed term-frequency map and token length for one document."""
    toks = tokenize(text)
    counts: dict[str, int] = {}
    for tok in toks:
        st = _bm25_stem(tok)
        counts[st] = counts.get(st, 0) + 1
    return counts, len(toks)


def bm25_query_terms(query: str) -> list[tuple[str, int]]:
    """Ordered stemmed query terms with conversational stopwords stripped when content remains."""
    raw = tokenize(query)
    if not raw:
        return []
    filtered = [tok for tok in raw if tok not in _BM25_STOPWORDS]
    chosen = filtered if filtered else raw
    counts: dict[str, int] = {}
    for tok in chosen:
        st = _bm25_stem(tok)
        counts[st] = counts.get(st, 0) + 1
    return list(counts.items())


def bm25_lexical_scan(
    query: str,
    texts: Sequence[str],
    *,
    k1: float = 1.2,
    b: float = 0.75,
    corpus_size: int | None = None,
    avg_doc_len: float | None = None,
) -> list[float]:
    """Corpus-IDF Okapi BM25 over stemmed tokens with conversational stopword filtering.

    Deterministic and backend-identical between LocalMemoryEngine and SqliteEngine.
    """
    n_texts = len(texts)
    if n_texts == 0:
        return []
    q_terms = bm25_query_terms(query)
    if not q_terms:
        return [0.0] * n_texts
    doc_stats = [_bm25_doc_stats(text) for text in texts]
    n_corpus = max(int(corpus_size) if corpus_size is not None else n_texts, n_texts, 1)
    if avg_doc_len is not None and avg_doc_len > 0.0:
        avgdl = float(avg_doc_len)
    else:
        total_len = sum(dl for _, dl in doc_stats)
        avgdl = (total_len / n_texts) if total_len > 0 else 1.0

    k1_plus_1 = k1 + 1.0
    one_minus_b = 1.0 - b
    term_idfs: list[tuple[str, float]] = []
    for term, q_tf in q_terms:
        df = 0
        for counts, _ in doc_stats:
            if term in counts:
                df += 1
        if df == 0:
            continue
        idf = math.log(1.0 + (n_corpus - df + 0.5) / (df + 0.5))
        term_idfs.append((term, idf * float(q_tf)))
    if not term_idfs:
        return [0.0] * n_texts

    scores = [0.0] * n_texts
    for idx, (counts, dl) in enumerate(doc_stats):
        if dl == 0:
            continue
        norm = k1 * (one_minus_b + b * (dl / avgdl))
        total = 0.0
        for term, weight in term_idfs:
            tf = counts.get(term, 0)
            if tf:
                total += weight * (tf * k1_plus_1) / (tf + norm)
        scores[idx] = total
    return scores


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
        t_ascii = _project_ascii_separators(text)
        if t_ascii is not None:
            return tuple(NATIVE.hashing_embedding(t_ascii, dims))
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


@lru_cache(maxsize=131_072)
def _hashing_nonzero(text: str, dims: int) -> dict[int, float]:
    """The non-zero entries of ``hashing_embedding(text, dims)``, cached per distinct text."""
    return {index: value for index, value in enumerate(_hashing_embedding_cached(text, dims)) if value != 0.0}


class SparseCosine:
    """Dot products against one query vector, touching only the query's non-zero entries.

    ``_cosine_pure(query, v)`` sums ``q * v`` over every dimension in order with the builtin
    ``sum``. A term whose query entry is zero is +-0.0, which changes neither the sum nor its
    compensation, so summing only the query's non-zero dimensions, in the same increasing
    order and with the same ``sum``, gives the identical value. Callers compare the result with ``> 0``
    exactly as before; a sum with no non-zero term returns 0 instead of 0.0, which compares
    the same. Only for finite vectors - the engine uses it for local hashing embeddings only.
    """

    __slots__ = ("_nonzero",)

    def __init__(self, query_vec: Sequence[float]) -> None:
        self._nonzero = [(index, value) for index, value in enumerate(query_vec) if value != 0.0]

    def hashing(self, text: str, dims: int) -> float:
        """Equal to ``_cosine_pure(query_vec, hashing_embedding(text, dims))``.

        Uses the builtin ``sum`` like ``_cosine_pure``: since Python 3.12 it sums floats with
        Neumaier compensation, and a +-0.0 term leaves both its running sum and its
        compensation unchanged, so dropping the zero terms keeps the result bit-identical.
        """
        entries = _hashing_nonzero(text, dims)
        return sum(
            value * other
            for index, value in self._nonzero
            if (other := entries.get(index)) is not None
        )


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # Type nuance on empty inputs: the pure path returns int 0 (builtin sum of
    # an empty stream) while the native kernel returns float 0.0. The two are
    # == equal and bit-equal under struct.pack('<d'); neither side is
    # normalized here — coercing either one would be a behavior change in that
    # mode.
    return NATIVE.cosine(a, b) if NATIVE is not None else _cosine_pure(a, b)


def approx_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


TAXONOMIC_EXPANSIONS: dict[str, tuple[str, ...]] = {
    # Kinship hypernyms -> hyponyms
    "parent": ("mother", "father", "mom", "dad"),
    "parents": ("mother", "father", "mom", "dad"),
    # General creative/performer role hypernyms -> hyponyms
    "artist": ("musician", "singer", "band", "songwriter", "composer", "rapper", "vocalist", "album", "song"),
    "artists": ("musicians", "singers", "bands", "songwriters", "composers", "rappers", "vocalists"),
    # Common lexical synonyms & category hypernyms
    "bike": ("bicycle", "cycling", "biking"),
    "bikes": ("bicycles", "bicycle", "bike"),
    "pet": ("dog", "cat", "puppy", "kitten", "rabbit", "parrot", "hamster", "bird", "turtle"),
    "pets": ("dogs", "cats", "dog", "cat", "puppies", "kittens", "rabbits", "parrots"),
}


def damerau_levenshtein_at_most_one(left: str, right: str) -> bool:
    """Return True iff ``left`` and ``right`` are within optimal string alignment distance <= 1.

    Used for conservative human spelling/transposition typo recovery on alphabetic words.
    """
    if left == right:
        return True
    la, lb = len(left), len(right)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = [i for i in range(la) if left[i] != right[i]]
        if len(diffs) == 1:
            return True
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            i = diffs[0]
            return left[i] == right[i + 1] and left[i + 1] == right[i]
        return False
    # Insertion / deletion of 1 character
    shorter, longer = (left, right) if la < lb else (right, left)
    i = j = edits = 0
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
        else:
            edits += 1
            if edits > 1:
                return False
            j += 1
    return True


def expand_taxonomic_concepts(terms: Iterable[str]) -> list[str]:
    """Expands category hypernyms to concrete hyponyms."""
    expanded: list[str] = []
    seen: set[str] = set()
    for term in terms:
        norm = term.lower()
        if norm not in seen:
            expanded.append(term)
            seen.add(norm)
        hyponyms = TAXONOMIC_EXPANSIONS.get(norm)
        if hyponyms:
            for h in hyponyms:
                if h not in seen:
                    expanded.append(h)
                    seen.add(h)
    return expanded


def dynamic_concept_bridge(
    term: str,
    corpus_cooccurrences: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    """Combines taxonomic concept expansion with dynamic corpus co-occurrence bridging."""
    norm = term.lower()
    results = list(TAXONOMIC_EXPANSIONS.get(norm, ()))
    seen = set(results)
    if corpus_cooccurrences:
        for co in corpus_cooccurrences.get(norm, ()):
            if co not in seen:
                results.append(co)
                seen.add(co)
    return results
