"""Request-owned query vectors shared by wiki and ordinary retrieval."""
from __future__ import annotations

from collections import OrderedDict


class ScopedQueryEmbeddingProvider:
    """Share query work inside one facade, optionally using an owner's cache.

    Hosts create a fresh facade per request. Source embeddings retain the
    wrapped provider's public/private policy; private page content is never
    entered into this query cache.
    """
    def __init__(self, provider, *, owner_query_cache=False):
        self.provider = provider
        self.owner_query_cache = owner_query_cache
        self._queries = OrderedDict()

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def embed(self, text):
        return self.provider.embed(text)

    def embed_sensitive(self, text):
        return self.provider.embed_sensitive(text)

    def _query(self, text):
        if text not in self._queries:
            # A single-owner authenticated host may opt into its existing
            # owner-scoped query cache. Source/page text never uses this path.
            embed = self.provider.embed if self.owner_query_cache else self.provider.embed_sensitive
            self._queries[text] = tuple(embed(text))
            while len(self._queries) > 4:
                self._queries.popitem(last=False)
        return list(self._queries[text])

    def embed_query(self, text):
        prefix = getattr(self.provider, "query_prefix", "")
        return self._query(text if prefix and text.startswith(prefix) else prefix + text)

    def embed_query_sensitive(self, text):
        """Explicit query channel; source strings can never impersonate it."""
        return self.embed_query(text)
