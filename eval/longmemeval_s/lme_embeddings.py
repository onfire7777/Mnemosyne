"""Embeddings for the LongMemEval run, cloud or local, behind an on-disk vector cache.

Two providers, same model family, same OpenAI-style /v1/embeddings call:
  cloud   OpenRouter, qwen/qwen3-embedding-8b, 32k-token context, paid per token
  local   Ollama on this PC, qwen3-embedding:8b, free; texts are cut to fit Ollama's 4k context

Every text is embedded once and kept in a SQLite file per provider and model (key = sha256 of the
text; value = the vector cut to DIMS, normalised, float16), so a rerun costs nothing and the two
providers never mix vectors. CachedProvider hands the cached vectors to Mnemosyne as an ordinary
embedding provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

DIMS = 1024  # Qwen3 embeddings are Matryoshka-trained: the first 1024 dims, renormalised
PROVIDERS: dict[str, dict] = {
    "cloud": {
        "url": "https://openrouter.ai/api/v1/embeddings",
        "model": "qwen/qwen3-embedding-8b",
        "max_chars": 100_000,  # about 25k tokens, inside the 32k context
        "batch_texts": 32,
        "batch_chars": 120_000,
        "workers": 8,
        "needs_key": True,
        "usd_per_m_tokens": 0.01,
    },
    "local": {
        "url": "http://127.0.0.1:11434/v1/embeddings",
        "model": "qwen3-embedding:8b",
        "max_chars": 12_000,  # about 3k tokens: Ollama is set to a 4k context and cuts the rest silently
        "batch_texts": 8,
        "batch_chars": 48_000,
        "workers": 2,
        "needs_key": False,
        "usd_per_m_tokens": 0.0,
    },
}
QUERY_TASK = (
    "Given a question a user asks about their past conversations with an assistant, "
    "retrieve the conversation that contains the answer"
)


def query_text(question: str) -> str:
    """Qwen3 embedding models take an instruction on the query side only."""
    return f"Instruct: {QUERY_TASK}\nQuery: {question}"


class _TooLarge(Exception):
    pass


class EmbeddingCache:
    def __init__(self, path: Path, provider: str, api_key: str = "", model: str | None = None, dims: int = DIMS) -> None:
        if provider not in PROVIDERS:
            raise SystemExit(f"unknown embedding provider {provider!r}: use cloud or local")
        self.settings = dict(PROVIDERS[provider])
        self.provider = provider
        self.model = model or self.settings["model"]
        self.api_key, self.dims = api_key, dims
        if self.settings["needs_key"] and not api_key:
            raise SystemExit("the cloud embedding provider needs OPENROUTER_API_KEY")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS vec (key TEXT PRIMARY KEY, v BLOB NOT NULL)")
        self._lock = threading.Lock()
        self.tokens = 0
        self.cost = 0.0
        self.requests = 0

    def key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}|{self.dims}|{text}".encode("utf-8")).hexdigest()

    def _load(self, keys: list[str]) -> dict[str, np.ndarray]:
        found: dict[str, np.ndarray] = {}
        with self._lock:
            for start in range(0, len(keys), 900):
                chunk = keys[start : start + 900]
                marks = ",".join("?" * len(chunk))
                for key, blob in self._conn.execute(f"SELECT key, v FROM vec WHERE key IN ({marks})", chunk):
                    found[key] = np.frombuffer(blob, dtype=np.float16).astype(np.float32)
        return found

    def missing(self, texts: list[str]) -> list[str]:
        by_key = {self.key(text): text for text in dict.fromkeys(texts)}
        have: set[str] = set()
        keys = list(by_key)
        with self._lock:
            for start in range(0, len(keys), 900):
                chunk = keys[start : start + 900]
                marks = ",".join("?" * len(chunk))
                have.update(row[0] for row in self._conn.execute(f"SELECT key FROM vec WHERE key IN ({marks})", chunk))
        return [text for key, text in by_key.items() if key not in have]

    def vectors(self, texts: list[str]) -> np.ndarray:
        """One row per text, in order; every text must have been embedded (see ensure)."""
        keys = [self.key(text) for text in texts]
        found = self._load(list(dict.fromkeys(keys)))
        return np.stack([found[key] for key in keys]) if keys else np.zeros((0, self.dims), dtype=np.float32)

    def estimate_usd(self, texts: list[str]) -> tuple[int, float]:
        """(texts still to embed, estimated cost) at 4 characters a token."""
        todo = self.missing([text for text in texts if text])
        tokens = sum(min(len(text), self.settings["max_chars"]) for text in todo) / 4
        return len(todo), tokens / 1e6 * self.settings["usd_per_m_tokens"]

    def ensure(self, texts: list[str], *, workers: int | None = None, label: str = "") -> int:
        """Embed whatever is not cached yet; returns how many texts were sent."""
        todo = self.missing([text for text in texts if text])
        if not todo:
            return 0
        limit = self.settings["max_chars"]
        batches: list[list[str]] = [[]]
        size = 0
        for text in todo:
            cost = min(len(text), limit)
            if batches[-1] and (len(batches[-1]) >= self.settings["batch_texts"] or size + cost > self.settings["batch_chars"]):
                batches.append([])
                size = 0
            batches[-1].append(text)
            size += cost
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max(1, workers or self.settings["workers"])) as pool:
            for number, (batch, vectors) in enumerate(pool.map(lambda b: (b, self._embed(b, limit)), batches), 1):
                with self._lock, self._conn:
                    self._conn.executemany(
                        "INSERT OR REPLACE INTO vec (key, v) VALUES (?, ?)",
                        [(self.key(text), vector.tobytes()) for text, vector in zip(batch, vectors)],
                    )
                if label and (number % 25 == 0 or number == len(batches)):
                    print(f"  {label}: {number}/{len(batches)} batches, {self.tokens / 1e6:.2f} M tokens, "
                          f"${self.cost:.3f}, {time.perf_counter() - started:.0f}s", flush=True)
        return len(todo)

    def _embed(self, texts: list[str], limit: int) -> list[np.ndarray]:
        try:
            return self._post([text[:limit] for text in texts])
        except _TooLarge as exc:
            if len(texts) > 1:
                middle = len(texts) // 2
                return self._embed(texts[:middle], limit) + self._embed(texts[middle:], limit)
            if limit < 2000:
                raise SystemExit(f"embedding request refused: {exc}") from exc
            return self._embed(texts, limit // 2)

    def _post(self, texts: list[str]) -> list[np.ndarray]:
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Title": "Mnemosyne LongMemEval"}
        if self.api_key and self.settings["needs_key"]:
            headers["Authorization"] = f"Bearer {self.api_key}"
        error: object = None
        for attempt in range(6):
            request = urllib.request.Request(self.settings["url"], data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    reply = json.load(response)
                data = reply.get("data")
                if isinstance(data, list) and len(data) == len(texts):
                    usage = reply.get("usage") or {}
                    tokens = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
                    with self._lock:
                        self.tokens += tokens
                        self.cost += float(usage.get("cost") or tokens / 1e6 * self.settings["usd_per_m_tokens"])
                        self.requests += 1
                    vectors = []
                    for item in sorted(data, key=lambda row: row.get("index", 0)):
                        vector = np.asarray(item["embedding"], dtype=np.float32)[: self.dims]
                        norm = float(np.linalg.norm(vector))
                        if len(vector) != self.dims or not np.isfinite(norm) or norm == 0.0:
                            raise RuntimeError(f"unusable embedding from {self.model} (dims {len(vector)})")
                        vectors.append((vector / norm).astype(np.float16))
                    return vectors
                error = reply.get("error") or "no data in the reply"
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                if exc.code in (401, 402, 403, 404):
                    raise SystemExit(f"{self.provider} embeddings refused {self.model}: {exc.code} {detail}") from exc
                if exc.code in (400, 413, 422):
                    raise _TooLarge(f"{exc.code} {detail}") from exc
                error = f"{exc.code} {detail}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                error = exc
            time.sleep(2 ** attempt)
        raise RuntimeError(f"{self.provider} embeddings kept failing for {self.model}: {error}")


def open_cache(provider: str, folder: Path, api_key: str = "", model: str | None = None) -> EmbeddingCache:
    """The vector cache of one provider and model, in its own file under ``folder``."""
    name = model or PROVIDERS.get(provider, {}).get("model", "")
    safe = re.sub(r"[^A-Za-z0-9.]+", "-", name).strip("-")
    return EmbeddingCache(folder / f"embeddings-{provider}-{safe}.sqlite", provider, api_key, model)


class CachedProvider:
    """A Mnemosyne embedding provider that serves the cached vectors (and embeds a text it has not seen)."""

    name = "cached-embedding"

    def __init__(self, cache: EmbeddingCache) -> None:
        self.cache = cache
        self.model = cache.model
        self.dims = cache.dims
        self.misses = 0

    def embed(self, text: str) -> list[float]:
        if self.cache.missing([text]):
            self.misses += 1
            self.cache.ensure([text], workers=1)
        return self.cache.vectors([text])[0].astype(float).tolist()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def embed_query(self, query: str) -> list[float]:
        return self.embed(query_text(query))
