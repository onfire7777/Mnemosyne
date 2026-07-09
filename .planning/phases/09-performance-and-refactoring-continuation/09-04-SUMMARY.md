---
phase: 09-performance-and-refactoring-continuation
plan: 04
status: complete-local-gated
completed: 2026-07-09
---

# 09-04 Summary: Provider Contract Conformance CI

## Outcome

Provider contract drift is now a first-class CI failure. A shared fixture drives
the Python embedding service, Python HTTP adapters, and Rust `mneme-providers`
sidecar tests for the `/embed` and `/rerank` request/response shapes.

## Implementation Notes

- `tests/fixtures/provider_contract.json` captures canonical single embed,
  batch embed, and rerank requests plus expected model/dimension/top-rank
  assertions.
- `tests/test_provider_contract.py` loads `services/embedding/app.py` directly
  in fallback mode and monkeypatches the HTTP adapters to prove they send the
  same payloads.
- `rust/mneme-providers` now accepts either a string or list for `/embed`;
  list input returns OpenAI-style ordered `data` rows.
- `.github/workflows/ci.yml` now has a `provider-conformance` job covering
  Python contract tests, embedding service self-test, and Rust sidecar tests.

## Verification

- `uv run pytest -q tests/test_provider_contract.py tests/test_provider_batching.py tests/test_parity_retrieval.py tests/test_runtime_surfaces.py::test_http_embedding_and_reranker_adapters_use_json_provider_contract`
- `EMBEDDING_SERVICE_FORCE_FALLBACK=1 uv run python services/embedding/selftest.py`
- `cargo test --manifest-path rust/mneme-providers/Cargo.toml`
- `cargo clippy --manifest-path rust/mneme-providers/Cargo.toml --all-targets -- -D warnings`

## Remaining Work

TEI deployment, model-backed sidecar benchmarking, throughput-true batching,
and provider default selection remain Wave B bake-off work. This slice is only
the shared contract gate.
