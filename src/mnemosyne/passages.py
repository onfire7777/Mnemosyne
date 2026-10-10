"""Passage retrieval over already authorized, redacted source evidence.

Two rankers share this module:

* :class:`PassageIndex` - corpus BM25 over the caller's readable passages.
* :class:`PassageGraphIndex` - the HippoRAG 2 passage graph: OpenIE triples extracted from
  each passage, synonym edges between near-identical entity phrases, and Personalized
  PageRank seeded by the facts closest to the query plus dense passage scores.

The graph is an INDEX of what each passage says, never a belief. It is rebuilt from the
passages the caller may already read, so it can only reorder evidence the caller could see
anyway; extracted triples never become assertions and never leave this module as hits.
What it derives from passage text (triples, vectors) lives in a sidecar SQLite file keyed by
the sha256 of the text, so a passage two tenants both hold is extracted and embedded once; a
membership table (scope, evidence CID -> text hash) says which tenant holds which passage, and
what no remaining passage of any tenant derives is purged when a source passage is erased.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from array import array
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from math import log
from pathlib import Path
from typing import Any

from mnemosyne.models import Hit
from mnemosyne.text import tokenize


def is_passage(hit: Hit) -> bool:
    return (
        hit.kind == "evidence"
        and hit.metadata.get("source_type") not in {
            "consolidation-summary", "statistical-trace", "provider-proposal",
        }
        and not hit.metadata.get("summary")
        and hit.metadata.get("reality_class") not in {"self_generated", "simulated"}
    )


class PassageIndex:
    """BM25 with positive IDF, scoped to the caller's readable corpus.

    No global text cache: the owning engine retains at most its latest scope.
    Candidates are reauthorized before every lookup, including cache hits.
    """

    def __init__(self, texts: tuple[str, ...]):
        self.texts = texts
        self.lengths = []
        self.postings = defaultdict(list)
        for index, text in enumerate(texts):
            counts = Counter(tokenize(text))
            self.lengths.append(sum(counts.values()))
            for term, count in counts.items():
                self.postings[term].append((index, count))
        self.average_length = sum(self.lengths) / max(len(texts), 1) or 1.0

    def scores(self, query: str) -> dict[int, float]:
        scores = defaultdict(float)
        for term, query_count in Counter(tokenize(query)).items():
            postings = self.postings.get(term, ())
            idf = log(1.0 + (len(self.texts) - len(postings) + 0.5) / (len(postings) + 0.5))
            for index, count in postings:
                norm = 1.2 * (0.25 + 0.75 * self.lengths[index] / self.average_length)
                scores[index] += query_count * idf * count * 2.2 / (count + norm)
        return dict(scores)


def rank_passages(owner: object, query: str, candidates: Sequence[Hit], k: int) -> list[Hit]:
    passages = [hit for hit in candidates if is_passage(hit)]
    texts = tuple(hit.text for hit in passages)
    index = getattr(owner, "_passage_bm25_index", None)
    if index is None or index.texts != texts:
        index = PassageIndex(texts)
        owner._passage_bm25_index = index
    scores = index.scores(query)
    ranked = sorted(scores, key=lambda i: (-scores[i], passages[i].id))[:max(k, 0)]
    return [replace(passages[i], score=scores[i], channel="lexical_bm25") for i in ranked]


# --------------------------------------------------------------------------------------------
# HippoRAG 2 passage graph
# --------------------------------------------------------------------------------------------

OPENIE_VERSION = "openie.v1"
OPENIE_PROMPT = """Extract the named entities and the facts (RDF triples) stated in the passage below.

Rules:
- named_entities: every specific person, place, organization, creative work, event, date and number in the passage, written as it appears.
- triples: [subject, predicate, object] facts stated in the passage. Each triple must contain at least one, preferably two, of the named entities. Keep the predicate a short relation phrase.
- The first line of the passage is its title and names the main subject. Resolve pronouns (he, she, it, they, the film...) to the specific name they refer to.
- Only extract what the passage states. Do not add outside knowledge.
- Answer with one compact JSON object and nothing else.

Example passage:
Radio City
Radio City is India's first private FM radio station and was started on 3 July 2001. It plays Hindi, English and regional songs. Radio City recently forayed into New Media in May 2008 with the launch of a music portal - PlanetRadiocity.com that offers music related news, videos, songs, and other music-related features.

Example answer:
{"named_entities": ["Radio City", "India", "3 July 2001", "Hindi", "English", "May 2008", "PlanetRadiocity.com"], "triples": [["Radio City", "located in", "India"], ["Radio City", "is", "private FM radio station"], ["Radio City", "started on", "3 July 2001"], ["Radio City", "plays songs in", "Hindi"], ["Radio City", "plays songs in", "English"], ["Radio City", "forayed into", "New Media"], ["Radio City", "launched", "PlanetRadiocity.com"], ["PlanetRadiocity.com", "launched in", "May 2008"], ["PlanetRadiocity.com", "is", "music portal"], ["PlanetRadiocity.com", "offers", "news"], ["PlanetRadiocity.com", "offers", "videos"], ["PlanetRadiocity.com", "offers", "songs"]]}

Passage:
{passage}
"""

RERANK_PROMPT = """You select the passages a question needs.

Question: {question}

Passages:
{passages}

List the numbers of the passages needed to answer the question, most useful first. Include a passage about an intermediate person, place or thing the question depends on, even when it does not mention the question's words. Answer with one compact JSON object: {"passages": [numbers]}.
"""

SECOND_HOP_PROMPT = """You plan the second step of a memory search.

Question: {question}

Passages found by the first search:
{passages}

Some questions need two steps: first an intermediate person, place or thing (the director of a film), then a fact about it (where that director was born). The passages may name the intermediate without holding that fact.

Write ONE search for what is still missing:
- Name the intermediate exactly as the passages spell it, followed by the fact the question needs, for example "Jane Doe nationality" or "Paul Moreau date of birth".
- When the question compares two things, name every intermediate it needs in the same search, for example "Anna Berg date of death, Paul Moreau date of death".
- Never write an answer, a date or a sentence: only names and what is needed about them.
- If the passages already hold everything the question needs, use an empty string.

Answer with one compact JSON object: {"query": "..."}.
"""

RECOGNITION_PROMPT = """You select facts from a memory that help answer a question.

Question: {question}

Candidate facts, each [subject, predicate, object]:
{facts}

Select every candidate fact that helps answer the question, including facts about an intermediate person, place or thing the question depends on. Copy each selected fact exactly. Answer with one compact JSON object: {"facts": [[subject, predicate, object], ...]}. Use an empty list when no candidate helps.
"""

# Qwen3-Embedding / NV-Embed style query instructions; documents are embedded bare.
PASSAGE_TASK = "Given a question, retrieve relevant documents that best answer the question."
FACT_TASK = "Given a question, retrieve relevant triplet facts that matches this question."
_MAX_TRIPLES = 64
_MAX_FIELD_CHARS = 200


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def phrase_key(text: str) -> str:
    """Entity phrase identity: lower case, punctuation folded to spaces, single-spaced."""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def fact_text(subject: str, predicate: str, obj: str) -> str:
    return f"{phrase_key(subject)} {' '.join(predicate.lower().split())} {phrase_key(obj)}"


def clean_triples(raw: object) -> list[list[str]]:
    """Well-formed, de-duplicated, length-capped triples from untrusted model output."""
    triples: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, list) or len(item) != 3 or not all(isinstance(part, str) for part in item):
            continue
        subject, predicate, obj = (" ".join(part.split())[:_MAX_FIELD_CHARS] for part in item)
        if not phrase_key(subject) or not phrase_key(obj) or not predicate:
            continue
        key = (phrase_key(subject), predicate.lower(), phrase_key(obj))
        if key not in seen:
            seen.add(key)
            triples.append([subject, predicate, obj])
        if len(triples) == _MAX_TRIPLES:
            break
    return triples


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model answer holds no JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model answer must be a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class ChatModel:
    """An OpenAI-compatible chat-completions endpoint (Ollama, OpenRouter, vLLM, ...)."""

    url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 300.0
    reasoning_effort: str | None = None

    def json(self, prompt: str) -> dict[str, Any]:
        from mnemosyne.retrieval import _post_json

        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        response = _post_json(self.url, payload, self.api_key, self.timeout_seconds)
        try:
            content = response["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("chat response has no choices[0].message.content") from exc
        if not isinstance(content, str):
            raise ValueError("chat response content must be text")
        return _json_object(content)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS passages (
  scope TEXT NOT NULL, cid TEXT NOT NULL, sha TEXT NOT NULL,
  PRIMARY KEY (scope, cid));
CREATE INDEX IF NOT EXISTS passages_by_sha ON passages (sha);
CREATE TABLE IF NOT EXISTS openie (
  sha TEXT NOT NULL, model TEXT NOT NULL, triples TEXT NOT NULL,
  PRIMARY KEY (sha, model));
CREATE TABLE IF NOT EXISTS vectors (
  sha TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL, vec BLOB NOT NULL,
  PRIMARY KEY (sha, kind, model));
"""
# The first layout keyed openie and passage vectors by (scope, evidence CID): the same text under
# two tenants, or under two source identities, was extracted twice. Its rows are carried over
# keyed by the CID and re-keyed to the text hash the next time the passage is indexed, so nothing
# already extracted is extracted again.
_MIGRATE_V1 = """
BEGIN;
ALTER TABLE openie RENAME TO openie_v1;
ALTER TABLE vectors RENAME TO vectors_v1;
""" + _SCHEMA + """
INSERT OR IGNORE INTO openie (sha, model, triples) SELECT sha, model, triples FROM openie_v1;
INSERT OR IGNORE INTO vectors (sha, kind, model, vec) SELECT sha, kind, model, vec FROM vectors_v1;
INSERT OR IGNORE INTO passages (scope, cid, sha) SELECT scope, sha, sha FROM openie_v1;
INSERT OR IGNORE INTO passages (scope, cid, sha) SELECT scope, sha, sha FROM vectors_v1 WHERE kind = 'passage';
DROP TABLE openie_v1;
DROP TABLE vectors_v1;
COMMIT;
"""


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class PassageIndexStore:
    """SQLite sidecar of what was derived from passage TEXT: OpenIE triples and vectors.

    Triples and vectors are keyed by the sha256 of the text they came from, shared by every
    scope (tenant) that holds the text; ``passages`` records which scope holds which passage,
    by evidence CID, and is what every read goes through, so a scope only ever sees rows for
    passages it registered. Writes of a passage's derivatives therefore happen once per text,
    reads stay per scope, and a purge drops only what no scope still derives.
    """

    def __init__(self, path: str | os.PathLike[str], *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            self._conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
            if "scope" in self._columns("openie"):
                raise ValueError("the passage index has the old per-tenant layout; open it writable once to migrate it")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            if "scope" in self._columns("openie"):
                self._conn.executescript(_MIGRATE_V1)
            else:
                self._conn.executescript(_SCHEMA)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        self._lock = threading.Lock()

    def _columns(self, table: str) -> set[str]:
        return {row[1] for row in self._conn.execute(f"PRAGMA table_info({table})")}

    def close(self) -> None:
        self._conn.close()

    def _select(self, sql: str, params: tuple[Any, ...], keys: Iterable[str]) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        wanted = list(dict.fromkeys(keys))
        with self._lock:
            for chunk in _chunks(wanted, 900):
                marks = ",".join("?" * len(chunk))
                rows.extend(self._conn.execute(sql.format(marks=marks), (*params, *chunk)).fetchall())
        return rows

    def register(self, scope: str, shas: Mapping[str, str]) -> None:
        """Record that ``scope`` holds these passages (evidence CID -> text sha256).

        A passage carried over from the first layout is still keyed by its CID; it is re-keyed
        to its text hash here, so what was extracted and embedded for it is kept.
        """
        with self._lock, self._conn:
            for cid, sha in shas.items():
                if self._conn.execute("SELECT 1 FROM passages WHERE sha = ? LIMIT 1", (cid,)).fetchone() is not None:
                    self._conn.execute("UPDATE OR IGNORE openie SET sha = ? WHERE sha = ?", (sha, cid))
                    self._conn.execute("DELETE FROM openie WHERE sha = ?", (cid,))
                    self._conn.execute("UPDATE OR IGNORE vectors SET sha = ? WHERE sha = ? AND kind = 'passage'", (sha, cid))
                    self._conn.execute("DELETE FROM vectors WHERE sha = ? AND kind = 'passage'", (cid,))
                    self._conn.execute("UPDATE passages SET sha = ? WHERE sha = ?", (sha, cid))
                self._conn.execute(
                    "INSERT OR REPLACE INTO passages (scope, cid, sha) VALUES (?, ?, ?)", (scope, cid, sha)
                )

    def openie(self, scope: str, model: str, cids: Iterable[str]) -> dict[str, list[list[str]]]:
        """Triples of the scope's passages, by evidence CID."""
        rows = self._select(
            "SELECT p.cid, o.triples FROM passages p JOIN openie o ON o.sha = p.sha "
            "WHERE p.scope = ? AND o.model = ? AND p.cid IN ({marks})",
            (scope, model), cids,
        )
        return {cid: json.loads(triples) for cid, triples in rows}

    def put_openie(self, sha: str, model: str, triples: list[list[str]]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO openie (sha, model, triples) VALUES (?, ?, ?)",
                (sha, model, json.dumps(triples, ensure_ascii=False)),
            )

    def vectors(self, scope: str, kind: str, model: str, keys: Iterable[str]) -> dict[str, bytes]:
        """Passage vectors by evidence CID (through the scope's registrations); fact and entity
        vectors by the sha256 of their text."""
        if kind == "passage":
            rows = self._select(
                "SELECT p.cid, v.vec FROM passages p JOIN vectors v ON v.sha = p.sha "
                "WHERE p.scope = ? AND v.kind = 'passage' AND v.model = ? AND p.cid IN ({marks})",
                (scope, model), keys,
            )
        else:
            rows = self._select(
                "SELECT sha, vec FROM vectors WHERE kind = ? AND model = ? AND sha IN ({marks})", (kind, model), keys
            )
        return {key: bytes(vec) for key, vec in rows}

    def put_vectors(self, kind: str, model: str, items: Sequence[tuple[str, list[float]]]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO vectors (sha, kind, model, vec) VALUES (?, ?, ?, ?)",
                [(sha, kind, model, array("f", vector).tobytes()) for sha, vector in items],
            )

    def purge(self, scope: str, passage_cids: Iterable[str]) -> dict[str, int]:
        """Erasure: forget that the scope holds these passages; drop the triples and vector of
        any text no scope holds any more, then every fact or entity vector no remaining passage
        derives."""
        cids = list(dict.fromkeys(passage_cids))
        with self._lock, self._conn:
            released: set[str] = set()
            for chunk in _chunks(cids, 900):
                marks = ",".join("?" * len(chunk))
                released.update(
                    sha for (sha,) in self._conn.execute(
                        f"SELECT sha FROM passages WHERE scope = ? AND cid IN ({marks})", (scope, *chunk)
                    )
                )
                self._conn.execute(f"DELETE FROM passages WHERE scope = ? AND cid IN ({marks})", (scope, *chunk))
            removed = 0
            for sha in released:
                if self._conn.execute("SELECT 1 FROM passages WHERE sha = ? LIMIT 1", (sha,)).fetchone() is None:
                    removed += self._conn.execute("DELETE FROM openie WHERE sha = ?", (sha,)).rowcount
                    self._conn.execute("DELETE FROM vectors WHERE sha = ? AND kind = 'passage'", (sha,))
            live: set[str] = set()
            for (triples,) in self._conn.execute("SELECT triples FROM openie"):
                for subject, predicate, obj in json.loads(triples):
                    live.update(
                        (text_sha(fact_text(subject, predicate, obj)), text_sha(phrase_key(subject)), text_sha(phrase_key(obj)))
                    )
            orphans = [
                (sha, kind)
                for sha, kind in self._conn.execute("SELECT sha, kind FROM vectors WHERE kind IN ('fact', 'entity')")
                if sha not in live
            ]
            self._conn.executemany("DELETE FROM vectors WHERE sha = ? AND kind = ?", orphans)
        return {"passages": removed, "derived_vectors": len(orphans)}


_TRUE = {"1", "true", "yes", "on"}


def build_passage_graph(
    index: str | os.PathLike[str],
    *,
    extractor: str = "",
    chat_url: str | None = None,
    chat_api_key: str | None = None,
    reasoning_effort: str | None = None,
    embedding_url: str | None = None,
    embedding_model: str | None = None,
    embedding_api_key: str | None = None,
    embedding_dims: int = 1024,
    query_task: str | None = None,
    query_timeout_seconds: float | None = None,
    embedding_body: str | None = None,
    recognition_filter: bool = False,
    rerank_top: int = 0,
    rerank_model: str | None = None,
    rerank_reasoning_effort: str | None = None,
    second_hop: bool = False,
    read_only: bool = False,
) -> PassageGraphIndex:
    """The passage graph for one index file and its (OpenAI-compatible) chat and embedding endpoints.

    Without an ``extractor`` the index is embeddings-only: no OpenIE, no graph walk, passages
    ranked by the cosine of their embedding to the question.
    """
    from mnemosyne.retrieval import HttpEmbeddingProvider

    try:
        import numpy  # noqa: F401
    except ImportError as exc:
        raise ValueError("the passage graph needs numpy: install mnemosyne-memory[graph]") from exc
    chat = (
        ChatModel(url=chat_url, model=extractor, api_key=chat_api_key, reasoning_effort=reasoning_effort)
        if chat_url else None
    )
    # A separate (larger) local model may rerank and write second-hop searches; OpenIE and the
    # index keep the extractor, so changing it never invalidates the stored triples.
    rerank_chat = (
        ChatModel(url=chat_url, model=rerank_model, api_key=chat_api_key, reasoning_effort=rerank_reasoning_effort)
        if chat_url and rerank_model else None
    )
    embedder = (
        HttpEmbeddingProvider(url=embedding_url, model=embedding_model, api_key=embedding_api_key,
                              dims=int(embedding_dims), timeout_seconds=120.0, query_prefix="", cache_size=0,
                              extra_body_json=embedding_body or None)
        if embedding_url else None
    )
    tuned: dict[str, Any] = {}
    if query_task:
        tuned["passage_task"] = query_task
    if query_timeout_seconds:
        tuned["query_timeout_seconds"] = float(query_timeout_seconds)
    return PassageGraphIndex(
        store=PassageIndexStore(index, read_only=read_only),
        extractor=extractor,
        chat=chat,
        embedder=embedder,
        recognition_filter=recognition_filter,
        rerank_top=max(0, int(rerank_top)),
        rerank_chat=rerank_chat,
        second_hop=bool(second_hop),
        **tuned,
    )


def passage_graph_from_env(environ: Mapping[str, str] | None = None, *, read_only: bool = False) -> PassageGraphIndex | None:
    """The passage graph MNEMOSYNE_PASSAGE_* configure, or None when no index is set."""
    env = os.environ if environ is None else environ
    index = env.get("MNEMOSYNE_PASSAGE_INDEX")
    if not index:
        return None
    extractor = env.get("MNEMOSYNE_PASSAGE_CHAT_MODEL") or ""
    embedding_url = env.get("MNEMOSYNE_PASSAGE_EMBEDDING_URL")
    if not extractor and not embedding_url:
        raise ValueError(
            "MNEMOSYNE_PASSAGE_INDEX needs MNEMOSYNE_PASSAGE_CHAT_MODEL, the OpenIE model it was built "
            "with, or MNEMOSYNE_PASSAGE_EMBEDDING_URL alone for an embeddings-only index"
        )
    key_env = env.get("MNEMOSYNE_PASSAGE_CHAT_API_KEY_ENV")
    embedding_key_env = env.get("MNEMOSYNE_PASSAGE_EMBEDDING_API_KEY_ENV")
    return build_passage_graph(
        index,
        extractor=extractor,
        chat_url=env.get("MNEMOSYNE_PASSAGE_CHAT_URL"),
        chat_api_key=env.get(key_env) if key_env else None,
        reasoning_effort=env.get("MNEMOSYNE_PASSAGE_CHAT_REASONING_EFFORT"),
        embedding_url=embedding_url,
        embedding_model=env.get("MNEMOSYNE_PASSAGE_EMBEDDING_MODEL"),
        embedding_api_key=env.get(embedding_key_env) if embedding_key_env else None,
        embedding_dims=int(env.get("MNEMOSYNE_PASSAGE_EMBEDDING_DIMS", "1024")),
        query_task=env.get("MNEMOSYNE_PASSAGE_QUERY_TASK") or None,
        query_timeout_seconds=float(env.get("MNEMOSYNE_PASSAGE_QUERY_TIMEOUT") or 0) or None,
        embedding_body=env.get("MNEMOSYNE_PASSAGE_EMBEDDING_BODY") or None,
        recognition_filter=env.get("MNEMOSYNE_PASSAGE_RECOGNITION_FILTER", "").lower() in _TRUE,
        rerank_top=int(env.get("MNEMOSYNE_PASSAGE_RERANK_TOP", "0")),
        rerank_model=env.get("MNEMOSYNE_PASSAGE_RERANK_MODEL") or None,
        rerank_reasoning_effort=env.get("MNEMOSYNE_PASSAGE_RERANK_REASONING_EFFORT") or None,
        second_hop=env.get("MNEMOSYNE_PASSAGE_SECOND_HOP", "").lower() in _TRUE,
        read_only=read_only,
    )


def _embedding_model_key(embedder: Any) -> str:
    return f"{getattr(embedder, 'model', None) or embedder.name}|{int(embedder.dims)}"


def _embed(embedder: Any, texts: Sequence[str]) -> list[list[float]]:
    from mnemosyne.retrieval import _coerce_vector

    embed_many = getattr(embedder, "embed_many", None)
    vectors = list(embed_many(list(texts))) if callable(embed_many) else [embedder.embed(text) for text in texts]
    if len(vectors) != len(texts):
        raise ValueError("embedding provider must return one vector per text")
    validated = [_coerce_vector(vector, field="passage embedding") for vector in vectors]
    if any(len(vector) != int(embedder.dims) for vector in validated):
        raise ValueError("passage embedding dimensions must match the provider")
    return validated


def _require_semantic(embedder: Any) -> None:
    if getattr(embedder, "name", "") == "local-hashing":
        raise ValueError("the passage graph needs a semantic embedding provider (--embedding-provider http)")


@dataclass(slots=True)
class _Graph:
    """The in-memory graph for one exact passage list (numpy arrays)."""

    passage_ids: tuple[str, ...]
    n_passages: int
    fact_entities: list[tuple[int, ...]]
    facts: list[tuple[str, str, str]]
    entity_passages: list[int]
    passage_vectors: Any
    #: Passages with a vector: the rest (withheld above the disclosure ceiling, or not yet
    #: indexed) are still found, by BM25, and merged into the ranking.
    indexed: Any
    fact_vectors: Any
    src: Any
    dst: Any
    transition: Any
    dangling: Any
    size: int
    stats: dict[str, Any]


def _matrix(np: Any, blobs: dict[str, bytes], shas: Sequence[str], dims: int) -> Any:
    matrix = np.zeros((len(shas), dims), dtype=np.float32)
    for row, sha in enumerate(shas):
        blob = blobs.get(sha)
        if blob is not None:
            vector = np.frombuffer(blob, dtype=np.float32)
            if vector.shape[0] == dims:
                matrix[row] = vector
    return matrix


@dataclass(slots=True)
class PassageGraphIndex:
    """HippoRAG 2 retrieval over a caller's readable passages (needs numpy).

    Five linked facts, passage-node weight 0.05 and damping 0.5 are HippoRAG 2's. Synonym
    edges at cosine 0.95 (HippoRAG 2: 0.8) and a 0.1 dense mix were chosen on a 2Wiki
    DEVELOPMENT split with qwen3-embedding (0.8 joined ~17 phrases per entity and diluted
    the walk: recall@5 0.854 -> 0.914); never on held-out data.
    """

    store: PassageIndexStore
    #: Names the OpenIE extraction the index holds (the chat model that built it); queries
    #: need it even when no chat endpoint is configured for them. Empty = an embeddings-only
    #: index: nothing is extracted and passages are ranked by cosine alone.
    extractor: str
    chat: ChatModel | None = None
    #: Embedding provider for passages, facts and entities; None = the engine's own (which
    #: must then be semantic). A separate one keeps capture and consolidation unchanged.
    embedder: Any = None
    recognition_filter: bool = False
    link_top_k: int = 5
    passage_node_weight: float = 0.05
    damping: float = 0.5
    synonym_threshold: float = 0.95
    synonym_top_k: int = 100
    #: Weight of the min-max dense passage score added to the min-max PageRank score (0 = pure PPR).
    dense_mix: float = 0.1
    #: Let the chat model reorder the top N passages (0 = off; one call per query).
    rerank_top: int = 0
    #: Model for reranking and second-hop searches (None = ``chat``, the extractor).
    rerank_chat: ChatModel | None = None
    #: Passage text the reranker sees in total: each passage gets an equal share of at most
    #: 600 characters, so a wide head still fits a 4k-token local context.
    rerank_chars: int = 9000
    #: Ask the chat model for a follow-up search (the bridge person, place or thing a two-step
    #: question needs), walk the graph again with it and fuse both rankings (one call per query).
    second_hop: bool = False
    #: Top passages the follow-up search is written from.
    second_hop_top: int = 5
    #: Reciprocal-rank fusion of the two walks: a small constant and half weight for the second
    #: keep the first hop's head on top and lift the second's best few into the top five (a
    #: plateau on the 2Wiki DEVELOPMENT split, k 1-3 and weight 0.3-0.6: recall@5 0.914 ->
    #: 0.928; k 60 at full weight buried the first hop's answers: 0.788).
    second_hop_rrf_k: int = 2
    second_hop_weight: float = 0.5
    max_disclosed_sensitivity: int = 1
    query_template: str = "Instruct: {task}\nQuery: {query}"
    #: Seconds a query may wait for its embedding before search falls back to BM25.
    query_timeout_seconds: float = 30.0
    #: Instruction on the query side of the passage embedding (documents are embedded bare).
    passage_task: str = PASSAGE_TASK
    #: An embeddings-only index scores passages by cosine. A best score at or above this floor
    #: supports an answer that shares no word with the question (chosen on BurnOS's own
    #: development questions with qwen3-embedding-8b; see docs/passage-graph.md).
    support_floor: float = 0.55
    #: Index new memories in a background thread (a long-running server turns this on).
    live_index: bool = False
    live_debounce_seconds: float = 1.0
    _cache: tuple[tuple[Any, ...], _Graph] | None = field(default=None, repr=False)
    _query_vectors: dict[str, Any] = field(default_factory=dict, repr=False)
    _cache_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _erased: set[str] = field(default_factory=set, repr=False)
    _live_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _live_wake: threading.Event = field(default_factory=threading.Event, repr=False)
    _live_jobs: dict[str, tuple[Callable[[], Sequence[Hit]], Any]] = field(default_factory=dict, repr=False)
    _live_worker: threading.Thread | None = field(default=None, repr=False)
    _live_status: dict[str, Any] = field(default_factory=lambda: {"running": False, "failures": 0}, repr=False)

    @property
    def openie_model(self) -> str:
        return f"{self.extractor}|{OPENIE_VERSION}"

    @property
    def embeddings_only(self) -> bool:
        """No OpenIE and no graph walk: passages are ranked by their dense score alone."""
        return not self.extractor

    def disclosable(self, hit: Hit) -> bool:
        """Only passages at or below the disclosure ceiling are sent to the models."""
        return (
            is_passage(hit)
            and int(hit.sensitivity) <= self.max_disclosed_sensitivity
            and hit.metadata.get("embedding_partition") != "none"
        )

    # -- indexing (write path) --------------------------------------------------------------

    def index(
        self,
        scope: str,
        passages: Sequence[Hit],
        embedder: Any,
        *,
        workers: int = 8,
        batch_size: int = 64,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Extract triples for, and embed, every disclosable passage not yet indexed."""
        if self.store.read_only:
            raise ValueError("the passage index is open read-only")
        if self.chat is None and not self.embeddings_only:
            raise ValueError("indexing passages needs a chat model for OpenIE")
        embedder = self.embedder or embedder
        _require_semantic(embedder)
        started = time.perf_counter()
        texts: dict[str, str] = {}
        withheld = 0
        for hit in passages:
            # Keyed by evidence CID: content-addressed, and exactly what erasure names.
            if hit.id in self._erased:
                continue
            if self.disclosable(hit):
                texts.setdefault(hit.id, hit.text)
            else:
                withheld += 1
        model = self.openie_model
        # Derivatives are keyed by the text, so a passage already indexed for another tenant (or
        # under another source identity) is neither extracted nor embedded again.
        shas = {cid: text_sha(text) for cid, text in texts.items()}
        cids_by_sha: dict[str, list[str]] = defaultdict(list)
        for cid, sha in shas.items():
            cids_by_sha[sha].append(cid)
        self.store.register(scope, shas)
        extracted = {} if self.embeddings_only else self.store.openie(scope, model, texts)
        todo = [] if self.embeddings_only else list(
            {shas[cid]: text for cid, text in texts.items() if cid not in extracted}.items()
        )
        failures: list[str] = []
        chat = self.chat

        def extract(item: tuple[str, str]) -> tuple[str, list[list[str]]]:
            sha, text = item
            return sha, clean_triples(chat.json(OPENIE_PROMPT.replace("{passage}", text)).get("triples"))

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(extract, item) for item in todo]
            for done, future in enumerate(as_completed(futures), 1):
                try:
                    sha, triples = future.result()
                except Exception as exc:  # noqa: BLE001 - one bad answer must not stop the batch
                    failures.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                    continue
                self.store.put_openie(sha, model, triples)
                for cid in cids_by_sha[sha]:
                    extracted[cid] = triples
                if progress is not None and (done % 100 == 0 or done == len(futures)):
                    progress(f"openie {done}/{len(futures)} ({time.perf_counter() - started:.0f}s)")
        kinds: dict[str, dict[str, str]] = {"passage": {shas[cid]: text for cid, text in texts.items()}, "fact": {}, "entity": {}}
        for triples in extracted.values():
            for subject, predicate, obj in triples:
                fact = fact_text(subject, predicate, obj)
                kinds["fact"][text_sha(fact)] = fact
                for phrase in (phrase_key(subject), phrase_key(obj)):
                    kinds["entity"][text_sha(phrase)] = phrase
        embed_model = _embedding_model_key(embedder)
        embedded: dict[str, int] = {}
        for kind, items in kinds.items():
            if kind == "passage":
                present = {shas[cid] for cid in self.store.vectors(scope, kind, embed_model, texts)}
            else:
                present = set(self.store.vectors(scope, kind, embed_model, items))
            missing = [(sha, text) for sha, text in items.items() if sha not in present]
            chunks = list(_chunks(missing, batch_size))
            # Several batches in flight keep a server's parallel slots busy; map keeps the order.
            with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
                batches = pool.map(lambda chunk: _embed(embedder, [text for _sha, text in chunk]), chunks)
                for number, (chunk, vectors) in enumerate(zip(chunks, batches), 1):
                    self.store.put_vectors(kind, embed_model, [(sha, vec) for (sha, _t), vec in zip(chunk, vectors)])
                    if progress is not None and number % 20 == 0:
                        progress(f"embed {kind} {number * batch_size}/{len(missing)}")
            embedded[kind] = len(missing)
        raced = self._erased.intersection(texts)
        if raced:
            # Forgotten while this run was extracting it: drop what the run wrote back.
            self.store.purge(scope, raced)
        self._cache = None
        return {
            "scope": scope,
            "passages": len(texts),
            "withheld_above_disclosure_ceiling": withheld,
            "openie_new": len(todo) - len(failures),
            "openie_failures": len(failures),
            "failure_samples": failures[:5],
            "embedded": embedded,
            "facts": len(kinds["fact"]),
            "entities": len(kinds["entity"]),
            "openie_model": model,
            "embedding_model": embed_model,
            "seconds": round(time.perf_counter() - started, 3),
        }

    def purge(self, scope: str, passage_cids: Iterable[str]) -> dict[str, int]:
        passage_cids = list(passage_cids)
        self._erased.update(passage_cids)
        self._cache = None
        if self.store.read_only:
            return {"passages": 0, "derived_vectors": 0}
        return self.store.purge(scope, passage_cids)

    # -- live indexing (a long-running server) ----------------------------------------------

    def schedule(self, scope: str, collect: Callable[[], Sequence[Hit]], embedder: Any) -> bool:
        """Index ``scope`` soon, in a background thread; returns at once.

        ``collect`` returns the passages a reader of the scope may see. Calls within the
        debounce window coalesce into one run, and a run only extracts and embeds what is
        new. A model that is down costs nothing here: the run fails, is recorded in
        :meth:`health`, and the next capture (or ``index-passages``) catches up. Until a
        passage is indexed, search still finds it by BM25.
        """
        if not self.live_index or self.store.read_only or (self.chat is None and not self.embeddings_only):
            return False
        with self._live_lock:
            self._live_jobs[scope] = (collect, embedder)
            if self._live_worker is None or not self._live_worker.is_alive():
                self._live_worker = threading.Thread(target=self._live_loop, name="passage-index", daemon=True)
                self._live_worker.start()
            self._live_wake.set()
        return True

    def _live_loop(self) -> None:
        while True:
            self._live_wake.wait()
            time.sleep(self.live_debounce_seconds)
            with self._live_lock:
                jobs = dict(self._live_jobs)
                self._live_jobs.clear()
                self._live_wake.clear()
                self._live_status["running"] = True
            for scope, (collect, embedder) in jobs.items():
                try:
                    report = self.index(scope, collect(), embedder, workers=4)
                    summary = {key: report[key] for key in ("passages", "openie_new", "openie_failures", "embedded", "seconds")}
                    with self._live_lock:
                        self._live_status.update(last_report=summary, last_error=None,
                                                 last_indexed_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
                except Exception as exc:  # noqa: BLE001 - a model that is down must not stop the worker
                    with self._live_lock:
                        self._live_status["last_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                        self._live_status["failures"] += 1
            with self._live_lock:
                self._live_status["running"] = False

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Block until no live run is pending or running (tests, shutdown); False on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._live_lock:
                idle = not self._live_jobs and not self._live_wake.is_set() and not self._live_status["running"]
            if idle:
                return True
            time.sleep(0.05)
        return False

    def health(self) -> dict[str, Any]:
        """What a health check reports: the models it is set up with and how live indexing goes."""
        with self._live_lock:
            status = dict(self._live_status)
            pending = len(self._live_jobs)
        return {
            "configured": True,
            "index": str(self.store.path),
            "extractor": self.extractor,
            "chat_url": getattr(self.chat, "url", None),
            "embedding_model": getattr(self.embedder, "model", None),
            "rerank_top": self.rerank_top,
            "rerank_model": getattr(self.rerank_chat or self.chat, "model", None),
            "second_hop": self.second_hop,
            "live_index": self.live_index,
            "pending_scopes": pending,
            **status,
        }

    # -- graph (read path) ------------------------------------------------------------------

    def _graph(self, scope: str, passages: Sequence[Hit], embedder: Any) -> _Graph:
        import numpy as np

        key = (scope, self.openie_model, _embedding_model_key(embedder), tuple(hit.id for hit in passages))
        with self._cache_lock:
            if self._cache is not None and self._cache[0] == key:
                return self._cache[1]
            started = time.perf_counter()
            dims = int(embedder.dims)
            embed_model = _embedding_model_key(embedder)
            shas = [hit.id if self.disclosable(hit) else "" for hit in passages]
            triples_by_sha = self.store.openie(scope, self.openie_model, [sha for sha in shas if sha])
            entities: dict[str, int] = {}
            facts: dict[tuple[str, str, str], int] = {}
            fact_entities: list[tuple[int, ...]] = []
            entity_passages: list[set[int]] = []
            entity_edges: Counter[tuple[int, int]] = Counter()
            passage_edges: set[tuple[int, int]] = set()
            for row, sha in enumerate(shas):
                for subject, predicate, obj in triples_by_sha.get(sha, ()):
                    ends = []
                    for phrase in (phrase_key(subject), phrase_key(obj)):
                        if phrase not in entities:
                            entities[phrase] = len(entities)
                            entity_passages.append(set())
                        ends.append(entities[phrase])
                    fact = (phrase_key(subject), " ".join(predicate.lower().split()), phrase_key(obj))
                    if fact not in facts:
                        facts[fact] = len(facts)
                        fact_entities.append(tuple(dict.fromkeys(ends)))
                    for end in ends:
                        entity_passages[end].add(row)
                        passage_edges.add((row, end))
                    if ends[0] != ends[1]:
                        entity_edges[(min(ends), max(ends))] += 1
            n_passages, n_entities = len(passages), len(entities)
            entity_list = list(entities)
            fact_list = list(facts)
            passage_vectors = _matrix(np, self.store.vectors(scope, "passage", embed_model, [s for s in shas if s]), shas, dims)
            entity_shas = [text_sha(phrase) for phrase in entity_list]
            entity_vectors = _matrix(np, self.store.vectors(scope, "entity", embed_model, entity_shas), entity_shas, dims)
            fact_shas = [text_sha(fact_text(*fact)) for fact in fact_list]
            fact_vectors = _matrix(np, self.store.vectors(scope, "fact", embed_model, fact_shas), fact_shas, dims)
            synonym: set[tuple[int, int]] = set()
            synonym_weight: dict[tuple[int, int], float] = {}
            for start in range(0, n_entities, 1024):
                sims = entity_vectors[start : start + 1024] @ entity_vectors.T
                for offset in range(sims.shape[0]):
                    sims[offset, start + offset] = -1.0
                rows, cols = np.nonzero(sims >= self.synonym_threshold)
                per_row: dict[int, list[int]] = defaultdict(list)
                for r, c in zip(rows.tolist(), cols.tolist()):
                    per_row[r].append(c)
                for r, cols_of_row in per_row.items():
                    if len(cols_of_row) > self.synonym_top_k:
                        cols_of_row = sorted(cols_of_row, key=lambda c: -sims[r, c])[: self.synonym_top_k]
                    for c in cols_of_row:
                        pair = (min(start + r, c), max(start + r, c))
                        if pair not in synonym:
                            synonym.add(pair)
                            synonym_weight[pair] = float(sims[r, c])
            src: list[int] = []
            dst: list[int] = []
            weight: list[float] = []

            def link(a: int, b: int, w: float) -> None:
                src.extend((a, b))
                dst.extend((b, a))
                weight.extend((w, w))

            for row, end in passage_edges:
                link(row, n_passages + end, 1.0)
            for (a, b), count in entity_edges.items():
                link(n_passages + a, n_passages + b, float(count))
            for pair in synonym:
                link(n_passages + pair[0], n_passages + pair[1], synonym_weight[pair])
            size = n_passages + n_entities
            src_a = np.asarray(src, dtype=np.int64)
            dst_a = np.asarray(dst, dtype=np.int64)
            weight_a = np.asarray(weight, dtype=np.float64)
            out = np.bincount(src_a, weights=weight_a, minlength=size) if size else np.zeros(0)
            transition = weight_a / out[src_a] if len(src_a) else weight_a
            graph = _Graph(
                passage_ids=key[3],
                n_passages=n_passages,
                fact_entities=fact_entities,
                facts=fact_list,
                entity_passages=[len(rows_of) for rows_of in entity_passages],
                passage_vectors=passage_vectors,
                indexed=np.any(passage_vectors != 0, axis=1),
                fact_vectors=fact_vectors,
                src=src_a,
                dst=dst_a,
                transition=transition,
                dangling=out == 0,
                size=size,
                stats={
                    "passages": n_passages,
                    "indexed_passages": sum(1 for sha in shas if sha in triples_by_sha),
                    "entities": n_entities,
                    "facts": len(fact_list),
                    "synonym_edges": len(synonym),
                    "build_seconds": round(time.perf_counter() - started, 3),
                },
            )
            self._cache = (key, graph)
            return graph

    def _ppr(self, graph: _Graph, reset: Any) -> Any:
        import numpy as np

        x = reset
        for _ in range(100):
            moved = np.bincount(graph.dst, weights=x[graph.src] * graph.transition, minlength=graph.size)
            moved += x[graph.dangling].sum() * reset
            nxt = (1.0 - self.damping) * reset + self.damping * moved
            if np.abs(nxt - x).sum() < 1e-10:
                return nxt
            x = nxt
        return x

    def _rerank(self, question: str, head: Sequence[Hit]) -> list[int]:
        """Positions in ``head`` the chat model picked, most useful first; [] on any failure."""
        chat = self.rerank_chat or self.chat
        share = max(160, min(600, int(self.rerank_chars) // max(len(head), 1)))
        listed = "\n".join(f"[{n}] {' '.join(hit.text.split())[:share]}" for n, hit in enumerate(head, 1))
        prompt = RERANK_PROMPT.replace("{question}", question).replace("{passages}", listed)
        try:
            picked = chat.json(prompt).get("passages") if chat else None
        except (ValueError, OSError):
            return []
        chosen: list[int] = []
        for value in picked if isinstance(picked, list) else []:
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= len(head):
                if value - 1 not in chosen:
                    chosen.append(value - 1)
        return chosen

    def _recognize(self, question: str, graph: _Graph, ranked_facts: list[int]) -> list[int]:
        if self.chat is None or not ranked_facts:
            return ranked_facts
        listed = [list(graph.facts[index]) for index in ranked_facts]
        prompt = RECOGNITION_PROMPT.replace("{question}", question).replace(
            "{facts}", "\n".join(json.dumps(fact, ensure_ascii=False) for fact in listed)
        )
        try:
            chosen = clean_triples(self.chat.json(prompt).get("facts"))
        except (ValueError, OSError):
            return ranked_facts
        keys = {(phrase_key(s), " ".join(p.lower().split()), phrase_key(o)) for s, p, o in chosen}
        return [index for index in ranked_facts if graph.facts[index] in keys]

    def prepare(self, queries: Sequence[str], embedder: Any, *, batch_size: int = 64) -> None:
        """Embed a batch of queries up front (in memory, this process only).

        A batch evaluation that also calls the chat model per query would otherwise make a
        small GPU swap the embedding and chat models on every question.
        """
        embedder = self.embedder or embedder
        texts = [
            text
            for text in dict.fromkeys(
                self.query_template.format(task=task, query=query)
                for query in queries
                for task in ((self.passage_task,) if self.embeddings_only else (FACT_TASK, self.passage_task))
            )
            if text not in self._query_vectors
        ]
        for chunk in _chunks(texts, batch_size):
            for text, vector in zip(chunk, _embed(embedder, list(chunk))):
                self._query_vectors[text] = vector

    def _query_vector(self, task: str, query: str, embedder: Any) -> Any:
        text = self.query_template.format(task=task, query=query)
        vector = self._query_vectors.get(text)
        if vector is not None:
            return vector
        if hasattr(embedder, "timeout_seconds") and hasattr(embedder, "__dataclass_fields__"):
            embedder = replace(embedder, timeout_seconds=min(float(embedder.timeout_seconds), self.query_timeout_seconds))
        return _embed(embedder, [text])[0]

    def _walk(self, graph: _Graph, query: str, embedder: Any) -> tuple[Any, dict[str, Any]]:
        """HippoRAG 2 scores of every graph passage for one query: fact-seeded PPR, else dense."""
        import numpy as np

        # An index without facts has nothing to link: one query embedding, not two.
        query_fact = (
            np.asarray(self._query_vector(FACT_TASK, query, embedder), dtype=np.float32) if len(graph.facts) else None
        )
        query_passage = np.asarray(self._query_vector(self.passage_task, query, embedder), dtype=np.float32)
        dense = graph.passage_vectors @ query_passage
        if graph.indexed.any():
            dense = np.where(graph.indexed, dense, float(dense[graph.indexed].min()))
        explain: dict[str, Any] = {}
        scores = dense.astype(np.float64)
        linked: list[int] = []
        if len(graph.facts):
            fact_scores = graph.fact_vectors @ query_fact
            ranked_facts = [int(i) for i in np.argsort(-fact_scores)[: self.link_top_k]]
            linked = self._recognize(query, graph, ranked_facts) if self.recognition_filter else ranked_facts
            explain["candidate_facts"] = [list(graph.facts[i]) for i in ranked_facts]
            explain["linked_facts"] = [list(graph.facts[i]) for i in linked]
            if linked:
                low, high = float(fact_scores.min()), float(fact_scores.max())
                spread = (high - low) or 1.0
                entity_weight = np.zeros(graph.size - graph.n_passages)
                occurrences = np.zeros(graph.size - graph.n_passages)
                for index in linked:
                    normalized = (float(fact_scores[index]) - low) / spread
                    for entity in graph.fact_entities[index]:
                        entity_weight[entity] += normalized / max(graph.entity_passages[entity], 1)
                        occurrences[entity] += 1
                seen = occurrences > 0
                entity_weight[seen] /= occurrences[seen]
                d_low, d_high = float(dense.min()), float(dense.max())
                passage_weight = (dense - d_low) / ((d_high - d_low) or 1.0) * self.passage_node_weight
                reset = np.concatenate([passage_weight.astype(np.float64), entity_weight])
                if reset.sum() > 0:
                    reset /= reset.sum()
                    scores = self._ppr(graph, reset)[: graph.n_passages]
                    if self.dense_mix > 0:
                        p_low, p_high = float(scores.min()), float(scores.max())
                        scores = (scores - p_low) / ((p_high - p_low) or 1.0) + self.dense_mix * (
                            (dense - d_low) / ((d_high - d_low) or 1.0)
                        )
        explain["route"] = "ppr" if linked else "dense"
        return scores, explain

    @staticmethod
    def _order(graph: _Graph, scores: Any) -> list[int]:
        import numpy as np

        return [i for i in np.argsort(-scores, kind="stable").tolist() if graph.indexed[i]]

    def _follow_up(self, question: str, head: Sequence[Hit]) -> str | None:
        """The chat model's search for the missing step of a two-step question; None if none."""
        chat = self.rerank_chat or self.chat
        if chat is None or not head:
            return None
        listed = "\n".join(f"[{n}] {' '.join(hit.text.split())[:500]}" for n, hit in enumerate(head, 1))
        prompt = SECOND_HOP_PROMPT.replace("{question}", question).replace("{passages}", listed)
        try:
            value = chat.json(prompt).get("query")
        except (ValueError, OSError):
            return None
        if not isinstance(value, str):
            return None
        return " ".join(value.split())[:300] or None

    def _second_hop(
        self, query: str, graph: _Graph, passages: Sequence[Hit], ranked: list[int], embedder: Any
    ) -> tuple[list[int], dict[int, float] | None, dict[str, Any]]:
        """The first-hop order fused (reciprocal rank) with a walk from the follow-up search."""
        follow = self._follow_up(query, [passages[i] for i in ranked[: self.second_hop_top]])
        explain: dict[str, Any] = {"query": follow, "applied": False}
        if not follow or follow.casefold() == query.casefold():
            return ranked, None, explain
        try:
            scores, walked = self._walk(graph, follow, embedder)
        except (ValueError, OSError) as exc:
            explain["error"] = f"{type(exc).__name__}: {exc}"[:200]
            return ranked, None, explain
        explain.update(applied=True, route=walked["route"], linked_facts=walked.get("linked_facts", []))
        fused: dict[int, float] = {}
        for order, weight in ((ranked, 1.0), (self._order(graph, scores), self.second_hop_weight)):
            for position, i in enumerate(order, 1):
                fused[i] = fused.get(i, 0.0) + weight / (self.second_hop_rrf_k + position)
        return sorted(fused, key=lambda i: -fused[i]), fused, explain

    def rank(self, query: str, passages: Sequence[Hit], embedder: Any, k: int) -> tuple[list[Hit], dict[str, Any]]:
        """The caller's passages in HippoRAG 2 order, best first, at most ``k``."""
        import numpy as np

        embedder = self.embedder or embedder
        _require_semantic(embedder)
        if not passages:
            return [], {"applied": False, "reason": "no_passages"}
        started = time.perf_counter()
        graph = self._graph(passages[0].tenant_id, passages, embedder)
        explain: dict[str, Any] = {"applied": True, "graph": graph.stats}
        scores, walked = self._walk(graph, query, embedder)
        explain.update(walked)
        ranked = self._order(graph, scores)
        final = {i: float(scores[i]) for i in ranked}
        # An embeddings-only index hands back cosines: one scale for every question, so a
        # caller can tell a strong match from the best of a bad lot.
        cosine = self.embeddings_only and bool(ranked)
        if cosine:
            explain["score_scale"] = "cosine"
            explain["top_score"] = round(final[ranked[0]], 4)
        reranker = self.rerank_chat or self.chat
        if self.second_hop and reranker is not None and ranked:
            ranked, fused, explain["second_hop"] = self._second_hop(query, graph, passages, ranked, embedder)
            if fused is not None:
                final = fused
        if self.rerank_top > 0 and reranker is not None and ranked:
            head = ranked[: self.rerank_top]
            chosen = self._rerank(query, [passages[i] for i in head])
            if chosen:
                first = [head[j] for j in chosen]
                taken = set(first)
                ranked = first + [i for i in ranked if i not in taken]
                final = {i: 1.0 / (1 + position) for position, i in enumerate(ranked)}
            explain["reranked"] = len(chosen)
        unindexed = np.flatnonzero(~graph.indexed).tolist()
        if unindexed:
            # Reciprocal-rank merge with BM25 over the passages the graph cannot see.
            lexical = PassageIndex(tuple(passages[i].text for i in unindexed)).scores(query)
            others = [unindexed[j] for j in sorted(lexical, key=lambda j: -lexical[j])]
            fused = {i: 1.0 / (60 + rank) for rank, i in enumerate(ranked, 1)}
            for rank, i in enumerate(others, 1):
                fused[i] = 1.0 / (60 + rank)
            if cosine:
                # Stay on the cosine scale: a passage not embedded yet takes the score of the
                # embedded passage it shares a rank with.
                for rank, i in enumerate(others, 1):
                    final[i] = final[ranked[min(rank, len(ranked)) - 1]]
            else:
                final = fused
            ranked = sorted(fused, key=lambda i: -fused[i])
            explain["unindexed_passages"] = len(unindexed)
        explain["seconds"] = round(time.perf_counter() - started, 4)
        hits = [
            replace(passages[i], score=final[i], channel="passage_graph", metadata=dict(passages[i].metadata))
            for i in ranked[: max(k, 0)]
        ]
        return hits, explain
