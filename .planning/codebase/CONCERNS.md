# Codebase Concerns

**Analysis Date:** 2026-07-08

## Tech Debt

**Monolithic CLI and release gate surface:**
- Issue: `src/mnemosyne/cli.py` is the central command router, runtime loader, operations checker, deployment-soak runner, release-audit validator, and production evidence verifier in one 19,529-line file.
- Files: `src/mnemosyne/cli.py`, `tests/test_cli_runtime_tools.py`, `tests/test_production_evidence_preflight.py`, `tests/test_production_manifest_renderer.py`
- Impact: Small changes to command parsing, output shape, evidence custody, or release validation can regress unrelated runtime tools or production sign-off gates.
- Fix approach: Extract only when changing a concrete release/custody helper and pin the seam with a focused test; otherwise keep `src/mnemosyne/cli.py` as the argparse facade.

**Parallel backend contract drift risk:**
- Issue: Local, Postgres, and SQLite engines carry overlapping MemoryEngine behavior with separate storage, retrieval, graph, erasure, runtime-state, and export implementations.
- Files: `src/mnemosyne/engine.py`, `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/sqlite_engine.py`, `tests/test_shared_engine_contract.py`, `tests/test_postgres_engine_live.py`
- Impact: A behavior can be fixed in one backend and silently diverge in another unless shared contract tests cover the exact path.
- Fix approach: Put cross-backend behavior behind shared helper functions where practical; otherwise add shared Local/Postgres/SQLite contract tests before changing engine behavior.

**Evidence pipeline split across shell, Python, and docs:**
- Issue: Production evidence readiness, capture, manifest rendering, and offline verification are distributed across multiple scripts and CLI commands.
- Files: `infra/scripts/capture-production-evidence.sh`, `infra/scripts/render-production-soak-manifest.sh`, `infra/scripts/prepare-production-evidence-custody.py`, `src/mnemosyne/cli.py`, `infra/README.md`
- Impact: Operator handoff can drift when a script changes without matching CLI validation, tests, and runbook text.
- Fix approach: Treat manifest schema and retained artifact shape as the contract; update renderer, capture wrapper, verifier, tests, and runbooks in the same change.

**Large domain modules:**
- Issue: Several core modules are large enough that unrelated responsibilities are hard to isolate.
- Files: `src/mnemosyne/postgres_engine.py` (4,929 lines), `src/mnemosyne/sqlite_engine.py` (3,414 lines), `src/mnemosyne/consolidation.py` (3,224 lines), `src/mnemosyne/engine.py` (3,156 lines), `src/mnemosyne/retrieval.py` (2,024 lines)
- Impact: Review cost is high and targeted changes often require reading long local context.
- Fix approach: Extract only stable helper boundaries already repeated across modules; avoid new abstractions until a concrete duplicated rule or test seam exists.

## Known Bugs

**Stale status contradiction in strict audit docs:**
- Symptoms: `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` says Tier-B rows are closed by `capture-bc10`, while its "Next Required Ops/Evidence Slice" still says to run Tier-B captures.
- Files: `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, `docs/ROADMAP-TO-100.md`, `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`
- Trigger: Agents updating status text from older sections instead of reconciling the whole current-state document.
- Workaround: Before any status claim, follow `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`: verify root, branch, `HEAD`, dirty tree, CI, and controlling audit status.

**Generated latest-report paths can be mistaken for current truth:**
- Symptoms: `eval/g0/reports/report.json` references `eval/latency/reports/latency_bench_latest.json`, `eval/latency_warm/reports/warm_latency_latest.json`, and `eval/reports/replay_fidelity_latest.json`.
- Files: `eval/g0/reports/report.json`, `eval/latency/bench.py`, `eval/latency/README.md`, `eval/harness/cli_driver.py`
- Trigger: Reading committed `*_latest.*` reports without rerunning the current benchmark or checking report timestamps and hardware context.
- Workaround: Treat committed reports as historical artifacts; rerun the relevant eval before making performance or parity claims.

## Security Considerations

**Operator command-provider trust boundary:**
- Risk: Multiple providers execute operator-configured commands. The code avoids shell invocation and uses timeouts, but the invoked executable receives sensitive payloads such as media bytes, lessons, procedures, object-key requests, or session-secret requests.
- Files: `src/mnemosyne/retrieval.py`, `src/mnemosyne/media.py`, `src/mnemosyne/parametric.py`, `src/mnemosyne/consolidation.py`, `src/mnemosyne/storage.py`, `src/mnemosyne/security.py`
- Current mitigation: Commands are executed as argv arrays with `subprocess.run`, bounded timeouts, JSON request/response contracts, and production provider-manifest checks.
- Recommendations: Keep production command paths absolute, retained, hashed, and least-privileged; never add `shell=True`; route every new command provider through release-audit/provider-check custody.

**Outbound HTTP provider SSRF boundary:**
- Risk: Provider URLs, JWKS fetches, dashboard checks, and metrics pushes cross the network boundary.
- Files: `src/mnemosyne/network_safety.py`, `src/mnemosyne/retrieval.py`, `src/mnemosyne/oidc_jwks.py`, `src/mnemosyne/ops_metrics.py`, `src/mnemosyne/cli.py`
- Current mitigation: `src/mnemosyne/network_safety.py` requires HTTP(S), rejects userinfo, denies redirects, blocks private/reserved/metadata addresses by default, and pins the resolved address used for the request.
- Recommendations: Keep insecure localhost and internal-host allowlists limited to explicit local/operator contexts; any new HTTP client should use `validate_fetch_url` plus `safe_urlopen`.

**Container and supply-chain proof depends on external scanner output:**
- Risk: `infra/docker-compose.prod.yml` uses digest-pinned registry images and hardened service defaults, but local build images still need build provenance and scanner artifacts.
- Files: `infra/docker-compose.prod.yml`, `infra/scripts/verify-supply-chain.sh`, `infra/Dockerfile`, `infra/keycloak/Dockerfile`, `infra/postgres/Dockerfile`, `infra/c2pa/Dockerfile`
- Current mitigation: `infra/scripts/verify-supply-chain.sh` requires gitleaks, trivy, syft, grype, and cosign output under an external evidence directory.
- Recommendations: Do not treat compose config alone as supply-chain evidence; retain the scanner/SBOM/signature artifacts outside the repo for every production capture.

## Performance Bottlenecks

**Local retrieval scans candidate sets in-process:**
- Problem: Local `vector_search` and `lexical_search` iterate over candidate hits and score them in Python unless the optional native extension is available.
- Files: `src/mnemosyne/engine.py`, `rust/mnemosyne-native/Cargo.toml`, `tests/test_native_parity.py`
- Cause: The local backend is deterministic and simple; it is not the scaling backend.
- Improvement path: Use Postgres for production scale; keep native acceleration optional and parity-tested rather than making the local backend a second database.

**Postgres dense fallback can embed many rows per query:**
- Problem: `src/mnemosyne/postgres_engine.py` handles `embedding IS NULL` evidence rows by loading eligible rows and embedding fallback text in Python.
- Files: `src/mnemosyne/postgres_engine.py`
- Cause: Null-embedding legacy fallback preserves retrieval behavior but creates an unbounded per-query CPU path if many rows lack stored embeddings.
- Improvement path: Backfill embeddings during ingestion/consolidation, monitor null-embedding counts, and cap or paginate fallback scans before large production datasets.

**Embedding service dominates warm fast-path latency on CPU:**
- Problem: The current latency notes report warm engine-only P95 passing, but synchronous CPU HTTP embedding dominates `fast_path_total` P95.
- Files: `eval/latency/README.md`, `eval/latency/bench.py`, `services/embedding/app.py`, `src/mnemosyne/retrieval.py`
- Cause: Each query pays model inference plus HTTP/JSON overhead unless cached, batched, colocated, or accelerated.
- Improvement path: Add query/document embedding cache, batch concurrent embeddings, use in-process or low-latency deployed providers, and measure with the current long-lived server benchmark.

## Fragile Areas

**Production evidence and false-completion controls:**
- Files: `src/mnemosyne/cli.py`, `infra/scripts/capture-production-evidence.sh`, `infra/scripts/render-production-soak-manifest.sh`, `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`, `docs/ROADMAP-TO-100.md`
- Why fragile: The release path intentionally rejects placeholder, hollow, symlinked, secret-bearing, and self-authorizing evidence. Relaxing any validator can create a false production-completion claim.
- Safe modification: Change one evidence invariant at a time and run focused production-evidence tests plus the relevant render/capture/verifier dry path.
- Test coverage: Strong local contract coverage exists, but real production evidence remains outside normal unit tests.

**Source-truth and recompute dependency parsing:**
- Files: `src/mnemosyne/source_truth.py`, `src/mnemosyne/jobs.py`, `tests/test_cli_runtime_tools.py`, `tests/test_runtime_surfaces.py`, `tests/test_shared_engine_contract.py`
- Why fragile: Static graph analysis flags transitive loop depth in Markdown/git source parsing and projection recompute affected-set helpers; small parsing changes can alter provenance or recompute fanout.
- Safe modification: Add fixture cases for new Markdown/git shapes or recompute dependencies before changing parser logic.
- Test coverage: Existing tests cover known shapes; malformed or unusually large source documents should get focused regression tests.

**Policy and self-optimization bundle validation:**
- Files: `src/mnemosyne/self_optimization.py`, `src/mnemosyne/policy.py`, `src/mnemosyne/cli.py`, `tests/test_parity_learning.py`
- Why fragile: `validate_policy_ops_bundle` is a large validator for shadow policy variants, outcomes, tripwires, cadence, proxy gaps, and promotion safety.
- Safe modification: Preserve fail-closed behavior and add a negative test for each new accepted field or relaxed condition.
- Test coverage: Local policy tests exist; production policy-ops evidence still depends on retained operator bundles.

**Access policy and redaction boundaries:**
- Files: `src/mnemosyne/access_policy.py`, `src/mnemosyne/evidence_redaction.py`, `src/mnemosyne/privacy.py`, `src/mnemosyne/postgres_engine.py`, `src/mnemosyne/engine.py`
- Why fragile: These functions decide what text, relations, metadata, embeddings, and structured fields can leave the store.
- Safe modification: Treat any new read path as a trust-boundary change; require tests for denied, redacted, and allowed cases.
- Test coverage: Good contract coverage exists, but new export/search/explain surfaces must be explicitly wired through the same redaction helpers.

## Scaling Limits

**Local runtime-state file writes are single-writer:**
- Current capacity: Local development and isolated eval clients.
- Limit: Concurrent shared-engine searches can contend on local runtime metric persistence.
- Files: `eval/latency/README.md`, `src/mnemosyne/mcp_tools.py`, `src/mnemosyne/runtime_state.py`
- Scaling path: Use Postgres runtime state in production or per-client/per-tenant local isolation for benchmarks.

**SQLite and local stores are not the production concurrency target:**
- Current capacity: Local deterministic and tenant-isolated file-backed operation.
- Limit: High-concurrency hosted deployments need durable queueing, Postgres state, and production object/key stores.
- Files: `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/queue.py`, `src/mnemosyne/storage.py`, `src/mnemosyne/postgres_engine.py`
- Scaling path: Keep SQLite/local paths as parity and portability backends; route production to Postgres, supervised workers, and external object/key custody.

## Dependencies at Risk

**Package metadata allows dependency drift outside locked installs:**
- Risk: `pyproject.toml` uses lower-bound runtime dependencies (`cryptography>=42`, `psycopg[binary]>=3.2`, `mcp>=1.28,<2`) while reproducible installs depend on `uv.lock`.
- Impact: Direct `pip install` or unlocked optional installs can pick newer dependency behavior than CI.
- Migration plan: Use `uv sync --locked` for development/CI/release checks; review `uv.lock` changes as dependency changes, not incidental churn.

**Native wheel release surface remains partial:**
- Risk: The current macOS arm64 / Linux x86_64 `native-wheels` CI job is merge-gating and now install/import-smokes its built artifacts, but the full release matrix is not complete yet.
- Impact: Pure-Python behavior remains canonical, and current wheel packaging regressions block merges, but advertised wheel support still needs broader release evidence.
- Files: `.github/workflows/ci.yml`, `rust/mnemosyne-native/Cargo.toml`, `rust/mnemosyne-native/Cargo.lock`
- Migration plan: Keep parity tests in the default test job; add broader wheel matrix coverage and release/publish evidence before advertising universal wheel support.

**Embedding service fallback can hide missing real model dependencies:**
- Risk: `services/embedding/app.py` falls back to deterministic embeddings/reranking when torch/sentence-transformers are unavailable or forced.
- Impact: Contract tests can pass without proving real model latency or quality.
- Migration plan: Production provider checks must assert real backend health and retained endpoint evidence; use fallback only for offline/local contract tests.

## Missing Critical Features

**No source-code critical feature gap detected for current Tier-B status:**
- Problem: Current source and planning docs describe Tier-B strict rows as closed by retained `capture-bc10` evidence, but future recapture remains an external operations process.
- Blocks: Any new release/status claim that lacks current live `HEAD`, CI, retained evidence bundle, out-of-band fingerprint, and offline verifier output.
- Files: `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, `docs/ROADMAP-TO-100.md`, `infra/PRODUCTION-EVIDENCE.md`, `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`

## Test Coverage Gaps

**Non-gating CI lanes:**
- What's not tested as a merge blocker: Native wheel builds and nightly DST/chaos soak failures.
- Files: `.github/workflows/ci.yml`, `tests/chaos`, `rust/mnemosyne-native`
- Risk: Packaging or chaos durability regressions can exist while required CI is green.
- Priority: Medium until native wheels or chaos soak become release gates.

**Live infrastructure tests self-skip without external services:**
- What's not tested: Live Postgres parity/performance and external production provider behavior when required DSNs/endpoints are absent.
- Files: `tests/test_postgres_engine_live.py`, `tests/test_runtime_parity_extensions.py`, `tests/test_postgres_perf_lanes.py`, `tests/test_postgres_role_check.py`
- Risk: Local green runs can miss deployment, role, latency, and provider integration failures.
- Priority: High for release validation; acceptable for quick local development.

**Provider/provenance tests use fakes and stubs for contract coverage:**
- What's not tested: Real C2PA tooling, real Keycloak/Vault/KMS/provider deployments, real model endpoints, and real object-lock retention in normal unit tests.
- Files: `tests/test_cli_runtime_tools.py`, `tests/test_runtime_parity_extensions.py`, `tests/completion/provenance/test_c2pa_infra_trust_policy.py`, `infra/scripts/capture-local-evidence.sh`
- Risk: Contract correctness can be mistaken for production evidence.
- Priority: High for status claims; keep fake/stub tests as fast contract tests only.

## Known Evidence Boundaries

**Current checkout evidence boundary:**
- Finding: These codebase-map docs describe repository structure and risk areas only; current-status and CI claims belong in the tracked status docs plus fresh live checks.
- Files: `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md`, `.planning/STATE.md`, `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, `README.md`
- Boundary: Follow the operator-evidence path before changing parity/status docs; do not infer production completion from local code graph, unit tests, or generated map files.

**Local project skill surface:**
- Finding: `.codex/skills/` and `.agents/skills/` were not present in this repo.
- Files: `.codex/skills`, `.agents/skills`
- Boundary: Repo-specific skill constraints are therefore not available from local skill directories; use AGENTS/config instructions and codebase docs instead.

**Untracked/generated byproducts:**
- Finding: `.planning/codebase/` is currently untracked, and ignored bytecode exists under `services/embedding/__pycache__/`.
- Files: `.planning/codebase/`, `services/embedding/__pycache__/`, `.gitignore`
- Boundary: Do not use `git add -A`; stage only the intended planning document if committing later.

---

*Concerns audit: 2026-07-08*
