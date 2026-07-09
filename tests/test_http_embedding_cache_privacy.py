"""Privacy admission + purge invariants for the HTTP embedding caches.

Mirrors the SqliteEngine A1 rule: sensitivity-tiered (non-public-partition)
text must never enter the process-global LRU or the durable cache, and
erasure purges the provider's cache scope.
"""

from mnemosyne import retrieval
from mnemosyne.postgres_engine import _partition_embed
from mnemosyne.retrieval import HttpEmbeddingProvider


class _CountingPost:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url, payload, api_key, timeout):  # noqa: ANN001 - test stub
        self.calls += 1
        return {"embedding": [1.0, 2.0, 3.0, 4.0]}


def _provider(tmp_path, scope: str) -> HttpEmbeddingProvider:
    return HttpEmbeddingProvider(
        url="http://embedder.test/embed",
        dims=4,
        cache_path=str(tmp_path / "cache.sqlite3"),
        cache_scope=scope,
    )


def _scope_keys(scope: str) -> list:
    with retrieval._HTTP_EMBEDDING_CACHE_LOCK:
        return [key for key in retrieval._HTTP_EMBEDDING_CACHE if key[0] == scope]


def test_embed_sensitive_never_touches_either_cache_tier(tmp_path, monkeypatch):
    post = _CountingPost()
    monkeypatch.setattr(retrieval, "_post_json", post)
    provider = _provider(tmp_path, "privacy-test-sensitive")

    first = provider.embed_sensitive("tier-3 private fact")
    second = provider.embed_sensitive("tier-3 private fact")

    assert first == second
    assert post.calls == 2, "sensitive embeds must never be served from cache"
    assert _scope_keys("privacy-test-sensitive") == []
    assert provider.cache_report().get("durable_entries", 0) == 0


def test_purge_cache_clears_memory_and_durable_scope(tmp_path, monkeypatch):
    post = _CountingPost()
    monkeypatch.setattr(retrieval, "_post_json", post)
    provider = _provider(tmp_path, "privacy-test-purge")

    provider.embed("public fact")
    provider.embed("public fact")
    assert post.calls == 1, "second call must be a cache hit"
    assert len(_scope_keys("privacy-test-purge")) == 1
    assert provider.cache_report().get("durable_entries", 0) == 1

    provider.purge_cache()

    assert _scope_keys("privacy-test-purge") == []
    assert provider.cache_report().get("durable_entries", 0) == 0
    provider.embed("public fact")
    assert post.calls == 2, "purged entries must not be served"


def test_partition_embed_routes_private_content_around_the_cache(tmp_path, monkeypatch):
    post = _CountingPost()
    monkeypatch.setattr(retrieval, "_post_json", post)
    provider = _provider(tmp_path, "privacy-test-partition")

    _partition_embed(provider, "private statement", "private")
    _partition_embed(provider, "private statement", "private")
    assert post.calls == 2, "private partition must bypass the cache"
    assert _scope_keys("privacy-test-partition") == []

    _partition_embed(provider, "public statement", "public")
    _partition_embed(provider, "public statement", "public")
    assert post.calls == 3, "public partition keeps cache admission"


def test_partition_embed_falls_back_for_plain_providers():
    class _Plain:
        def embed(self, text: str) -> list[float]:
            return [1.0, 0.0]

    assert _partition_embed(_Plain(), "anything", "private") == [1.0, 0.0]
