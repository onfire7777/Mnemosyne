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
(scope, evidence CID) - facts and entity phrases by the sha256 of their text - and is purged
when the source passage is erased.
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
from collections.abc import Callable, Iterable, Sequence
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
CREATE TABLE IF NOT EXISTS openie (
  scope TEXT NOT NULL, sha TEXT NOT NULL, model TEXT NOT NULL, triples TEXT NOT NULL,
  PRIMARY KEY (scope, sha, model));
CREATE TABLE IF NOT EXISTS vectors (
  scope TEXT NOT NULL, sha TEXT NOT NULL, kind TEXT NOT NULL, model TEXT NOT NULL, vec BLOB NOT NULL,
  PRIMARY KEY (scope, sha, kind, model));
"""


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class PassageIndexStore:
    """SQLite sidecar of what was derived from passage TEXT: OpenIE triples and vectors."""

    def __init__(self, path: str | os.PathLike[str], *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            self._conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.executescript(_SCHEMA)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def _select(self, sql: str, scope: str, extra: tuple[Any, ...], shas: Iterable[str]) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        keys = list(dict.fromkeys(shas))
        with self._lock:
            for chunk in _chunks(keys, 900):
                marks = ",".join("?" * len(chunk))
                rows.extend(self._conn.execute(sql.format(marks=marks), (scope, *extra, *chunk)).fetchall())
        return rows

    def openie(self, scope: str, model: str, shas: Iterable[str]) -> dict[str, list[list[str]]]:
        rows = self._select(
            "SELECT sha, triples FROM openie WHERE scope = ? AND model = ? AND sha IN ({marks})",
            scope, (model,), shas,
        )
        return {sha: json.loads(triples) for sha, triples in rows}

    def put_openie(self, scope: str, model: str, sha: str, triples: list[list[str]]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO openie (scope, sha, model, triples) VALUES (?, ?, ?, ?)",
                (scope, sha, model, json.dumps(triples, ensure_ascii=False)),
            )

    def vectors(self, scope: str, kind: str, model: str, shas: Iterable[str]) -> dict[str, bytes]:
        rows = self._select(
            "SELECT sha, vec FROM vectors WHERE scope = ? AND kind = ? AND model = ? AND sha IN ({marks})",
            scope, (kind, model), shas,
        )
        return {sha: bytes(vec) for sha, vec in rows}

    def put_vectors(self, scope: str, kind: str, model: str, items: Sequence[tuple[str, list[float]]]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO vectors (scope, sha, kind, model, vec) VALUES (?, ?, ?, ?, ?)",
                [(scope, sha, kind, model, array("f", vector).tobytes()) for sha, vector in items],
            )

    def purge(self, scope: str, passage_cids: Iterable[str]) -> dict[str, int]:
        """Erasure: drop a passage's triples and vector, then every fact or entity vector no
        remaining passage of the scope still derives."""
        shas = list(dict.fromkeys(passage_cids))
        with self._lock, self._conn:
            removed = 0
            for chunk in _chunks(shas, 900):
                marks = ",".join("?" * len(chunk))
                removed += self._conn.execute(
                    f"DELETE FROM openie WHERE scope = ? AND sha IN ({marks})", (scope, *chunk)
                ).rowcount
                self._conn.execute(
                    f"DELETE FROM vectors WHERE scope = ? AND kind = 'passage' AND sha IN ({marks})", (scope, *chunk)
                )
            live: set[str] = set()
            for (triples,) in self._conn.execute("SELECT triples FROM openie WHERE scope = ?", (scope,)):
                for subject, predicate, obj in json.loads(triples):
                    live.update(
                        (text_sha(fact_text(subject, predicate, obj)), text_sha(phrase_key(subject)), text_sha(phrase_key(obj)))
                    )
            orphans = [
                (sha, kind)
                for sha, kind in self._conn.execute(
                    "SELECT sha, kind FROM vectors WHERE scope = ? AND kind IN ('fact', 'entity')", (scope,)
                )
                if sha not in live
            ]
            self._conn.executemany(
                "DELETE FROM vectors WHERE scope = ? AND sha = ? AND kind = ?",
                [(scope, sha, kind) for sha, kind in orphans],
            )
        return {"passages": removed, "derived_vectors": len(orphans)}


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
    #: need it even when no chat endpoint is configured for them.
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
    max_disclosed_sensitivity: int = 1
    query_template: str = "Instruct: {task}\nQuery: {query}"
    _cache: tuple[tuple[Any, ...], _Graph] | None = field(default=None, repr=False)
    _query_vectors: dict[str, Any] = field(default_factory=dict, repr=False)
    _cache_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def openie_model(self) -> str:
        return f"{self.extractor}|{OPENIE_VERSION}"

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
        if self.chat is None:
            raise ValueError("indexing passages needs a chat model for OpenIE")
        embedder = self.embedder or embedder
        _require_semantic(embedder)
        started = time.perf_counter()
        texts: dict[str, str] = {}
        withheld = 0
        for hit in passages:
            # Keyed by evidence CID: content-addressed, and exactly what erasure names.
            if self.disclosable(hit):
                texts.setdefault(hit.id, hit.text)
            else:
                withheld += 1
        model = self.openie_model
        extracted = self.store.openie(scope, model, texts)
        todo = [(sha, text) for sha, text in texts.items() if sha not in extracted]
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
                self.store.put_openie(scope, model, sha, triples)
                extracted[sha] = triples
                if progress is not None and (done % 100 == 0 or done == len(futures)):
                    progress(f"openie {done}/{len(futures)} ({time.perf_counter() - started:.0f}s)")
        kinds: dict[str, dict[str, str]] = {"passage": dict(texts), "fact": {}, "entity": {}}
        for triples in extracted.values():
            for subject, predicate, obj in triples:
                fact = fact_text(subject, predicate, obj)
                kinds["fact"][text_sha(fact)] = fact
                for phrase in (phrase_key(subject), phrase_key(obj)):
                    kinds["entity"][text_sha(phrase)] = phrase
        embed_model = _embedding_model_key(embedder)
        embedded: dict[str, int] = {}
        for kind, items in kinds.items():
            present = self.store.vectors(scope, kind, embed_model, items)
            missing = [(sha, text) for sha, text in items.items() if sha not in present]
            chunks = list(_chunks(missing, batch_size))
            # Several batches in flight keep a server's parallel slots busy; map keeps the order.
            with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
                batches = pool.map(lambda chunk: _embed(embedder, [text for _sha, text in chunk]), chunks)
                for number, (chunk, vectors) in enumerate(zip(chunks, batches), 1):
                    self.store.put_vectors(
                        scope, kind, embed_model, [(sha, vec) for (sha, _t), vec in zip(chunk, vectors)]
                    )
                    if progress is not None and number % 20 == 0:
                        progress(f"embed {kind} {number * batch_size}/{len(missing)}")
            embedded[kind] = len(missing)
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
        self._cache = None
        if self.store.read_only:
            return {"passages": 0, "derived_vectors": 0}
        return self.store.purge(scope, passage_cids)

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
        listed = "\n".join(f"[{n}] {' '.join(hit.text.split())[:600]}" for n, hit in enumerate(head, 1))
        prompt = RERANK_PROMPT.replace("{question}", question).replace("{passages}", listed)
        try:
            picked = self.chat.json(prompt).get("passages") if self.chat else None
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
                for task in (FACT_TASK, PASSAGE_TASK)
            )
            if text not in self._query_vectors
        ]
        for chunk in _chunks(texts, batch_size):
            for text, vector in zip(chunk, _embed(embedder, list(chunk))):
                self._query_vectors[text] = vector

    def _query_vector(self, task: str, query: str, embedder: Any) -> Any:
        text = self.query_template.format(task=task, query=query)
        vector = self._query_vectors.get(text)
        return vector if vector is not None else _embed(embedder, [text])[0]

    def rank(self, query: str, passages: Sequence[Hit], embedder: Any, k: int) -> tuple[list[Hit], dict[str, Any]]:
        """The caller's passages in HippoRAG 2 order, best first, at most ``k``."""
        import numpy as np

        embedder = self.embedder or embedder
        _require_semantic(embedder)
        if not passages:
            return [], {"applied": False, "reason": "no_passages"}
        started = time.perf_counter()
        graph = self._graph(passages[0].tenant_id, passages, embedder)
        query_fact = np.asarray(self._query_vector(FACT_TASK, query, embedder), dtype=np.float32)
        query_passage = np.asarray(self._query_vector(PASSAGE_TASK, query, embedder), dtype=np.float32)
        dense = graph.passage_vectors @ query_passage
        if graph.indexed.any():
            dense = np.where(graph.indexed, dense, float(dense[graph.indexed].min()))
        explain: dict[str, Any] = {"applied": True, "graph": graph.stats}
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
        ranked = [i for i in np.argsort(-scores, kind="stable").tolist() if graph.indexed[i]]
        final = {i: float(scores[i]) for i in ranked}
        if self.rerank_top > 0 and self.chat is not None and ranked:
            head = ranked[: self.rerank_top]
            chosen = self._rerank(query, [passages[i] for i in head])
            if chosen:
                first = [head[j] for j in chosen]
                ranked = first + [i for i in ranked if i not in set(first)]
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
            ranked = sorted(fused, key=lambda i: -fused[i])
            final = fused
            explain["unindexed_passages"] = len(unindexed)
        explain["seconds"] = round(time.perf_counter() - started, 4)
        hits = [
            replace(passages[i], score=final[i], channel="passage_graph", metadata=dict(passages[i].metadata))
            for i in ranked[: max(k, 0)]
        ]
        return hits, explain
