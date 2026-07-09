# mneme-providers

Rust HTTP provider sidecar for the existing Mnemosyne `HttpEmbeddingProvider`
and `HttpReranker` contracts.

## Modes

- Default build: deterministic backend for contract tests and local smoke.
- `--features models`: FastEmbed/ONNX backend with `EmbeddingGemma300MQ` and
  `JinaRerankerV1TurboEN`; this path requires Rust 1.88 because the FastEmbed
  dependency graph includes ORT/image crates with that MSRV.

The model backend uses `FASTEMBED_CACHE_DIR`, falling back to `HF_HOME`, then
`/models`. Production images must bake that cache during image build and run
with `HF_HUB_OFFLINE=1`; runtime model downloads are not part of the production
posture.

## Local Checks

The default test suite includes fixture-backed conformance tests against
`tests/fixtures/provider_contract.json`, shared with the Python embedding
service and Python HTTP adapters.

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo check --features models
cargo clippy --all-targets --features models -- -D warnings
```

## Docker

```bash
docker build -f rust/mneme-providers/Dockerfile rust/mneme-providers
```

The Dockerfile downloads models only in the `models` build stage, copies
`/models` into the runtime image, and sets `HF_HUB_OFFLINE=1` for the final
container.
