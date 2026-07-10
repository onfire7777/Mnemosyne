---
phase: 09-performance-and-refactoring-continuation
plan: 09-10
status: complete
completed: 2026-07-09
---

# 09-10 Summary: Durable HTTP Embedding Cache

The source-owned provider-cache hardening slice is complete locally.
`HttpEmbeddingProvider` now keeps the existing process-local LRU and can also
use an explicit SQLite durable cache path for repeated HTTP embedding vectors.

What changed:

- `HttpEmbeddingProvider` gained `cache_path`, `cache_ttl_seconds`, and
  `cache_scope` fields.
- In-memory and durable cache keys include the explicit cache scope.
- The durable cache stores hashed scope/provider/model/revision/API-key/text
  identity plus normalized vector JSON; it does not store raw text, raw URLs, or
  raw API keys.
- Existing redaction patterns gate durable cache use, so secret-like text is not
  persisted even as a hash key.
- TTL expiry deletes stale durable rows before falling back to the provider.
- `provider-check` reports cache configuration/status but disables caching for
  the latency probe, so cache hits cannot hide provider latency.
- CLI/env/config builders now expose the same cache path, TTL, and scope knobs.

Verification:

- `uv run pytest tests/test_provider_batching.py::test_http_embedding_durable_cache_survives_provider_instances tests/test_provider_batching.py::test_http_embedding_durable_cache_is_scoped tests/test_provider_batching.py::test_http_embedding_durable_cache_honors_ttl tests/test_provider_batching.py::test_http_embedding_durable_cache_skips_secret_like_text tests/test_provider_batching.py::test_http_embedding_cache_report_does_not_create_durable_file tests/test_cli_runtime_tools.py::test_cli_exposes_retrieval_provider_flags tests/test_parity_retrieval.py::test_env_builder_threads_http_embedding_cache_knobs tests/test_parity_retrieval.py::test_registry_builds_http_and_command_providers -q`
  passed.
- `uv run ruff check src/mnemosyne/retrieval.py src/mnemosyne/cli.py src/mnemosyne/providers/__init__.py tests/test_provider_batching.py tests/test_cli_runtime_tools.py tests/test_parity_retrieval.py`
  passed.

Remaining gap:

This does not claim a production cache performance win. Retained hit-rate,
latency, and provider bake-off evidence are still required before changing any
provider default or closing the broader provider-cache blueprint item.
