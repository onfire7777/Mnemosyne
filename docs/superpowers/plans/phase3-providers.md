# Phase 3: Providers Sidecar + Consolidation Ladder Plan

> **For agentic workers:** implement task-by-task. For each task: write the biting tests first, implement the narrow change, run the task suite, perform an adversarial review, fix findings, commit, then append the result to `.superpowers/sdd/progress.md`.

**Goal:** Ship Phase 3 from the native-acceleration spec without changing the authoritative Python memory semantics: C3 adds a Rust `mneme-providers` HTTP sidecar behind the existing `HttpEmbeddingProvider` / `HttpReranker` contracts, and A3 adds the proposal-role consolidation ladder with recorded proposals, disclosure-axis gates, and production-evidence hooks.

**Current branch:** `phase3/providers-consolidation` from `main` @ `fa217c1`.

**Source of truth:** `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` §4.3 and §4.5, `.superpowers/sdd/progress.md`, and `.superpowers/sdd/phase3-grounding.md` (verified 2026-07-02). Re-grep every cited anchor before editing; line numbers drift.

## Global Constraints

- **Parity oracle remains `LocalMemoryEngine`.** Provider/consolidation improvements must not alter engine truth semantics, retrieval parity, gate/rail behavior, CID computation, `sql/schema.sql`, or `mcp_tools.py`.
- **Python HTTP contracts are frozen.** C3 must serve the existing compact JSON contracts:
  - `POST /embed` request `{"input": str, "model"?: str}` -> `{"embedding": [float, ...]}` or OpenAI-style `{"data": [{"embedding": [...]}]}`.
  - `POST /rerank` request `{"query": str, "documents": [str, ...], "top_n"?: int, "model"?: str}` -> `{"results": [{"index": int, "score": float}]}` or `relevance_score`.
  - `GET /health` -> health object usable by compose/provider checks.
- **No runtime fallback is invented.** HTTP provider failures currently raise `ValueError`; deterministic/local fallback is config-time only. If a ladder fallback is needed, implement it explicitly in a wrapper/provider layer and test it.
- **Runtime Python deps stay exactly `["cryptography>=42"]`.** New model/runtime dependencies live in Rust/Docker/optional tooling, not default Python install.
- **Production topology remains Postgres-only.** SqliteEngine remains drift in production profiles. A localhost C3 sidecar is local-profile only; production use must be internal-network HTTPS behind the existing Caddy alias and model-baked image posture.
- **Infra edits are named Phase-3 exceptions only.** The handoff says not to casually touch `infra/`; tasks below may update provider profile/compose files only where the Phase-3 requirement explicitly demands it, with profile/drift/provider-check tests.
- **C4 remains evidence-gated.** Do not build `mneme-native` rmcp/front-end work in this phase.

---

### Task 1: Phase-3 Contract Pins and Plan Activation

**Files:** Modify `docs/superpowers/plans/2026-07-01-native-acceleration-program.md`; create/modify tests around provider contract pins if missing; append `.superpowers/sdd/progress.md`.

**Interfaces:**
- Program map points to this file and marks Phase 3 in progress.
- Contract tests pin the existing `HttpEmbeddingProvider` / `HttpReranker` accepted request/response shapes, validation failures, `+rerank` channel suffix, and no-runtime-fallback behavior. Existing coverage in `tests/test_parity_retrieval.py` may be extended but not loosened.
- Plan records that C3 sidecar implements the compact Mnemosyne API, not native TEI JSON.

**Steps:** test-contract inventory -> program-map update -> focused retrieval-provider tests -> `uv run --locked python -m pytest tests/test_parity_retrieval.py` -> ruff -> commit `docs(phase3): add provider and consolidation plan`.

### Task 2: `mneme-providers` Sidecar Scaffold with Deterministic Test Backend

**Files:** Create `rust/mneme-providers/` or `services/mneme-providers/` (plain cargo binary preferred by grounding); add sidecar README; tests under sidecar crate.

**Interfaces:**
- Binary exposes `/embed`, `/rerank`, `/health` over loopback/local HTTP for tests.
- Deterministic backend first: non-zero finite vectors, stable scores, no model downloads. This proves route/JSON/auth/logging before real model work.
- Optional Bearer auth checks `Authorization: Bearer ...` when an env key is configured; no request/response body, embedding, tenant, user, or credential logging.
- Rejects malformed JSON, all-zero vectors, duplicate/out-of-range rerank indices, and invalid `top_n` with sanitized errors.

**Steps:** Rust tests first (route shape + auth + malformed inputs + no-body logs) -> implement scaffold -> cargo test -> Python smoke against `HttpEmbeddingProvider`/`HttpReranker` via live localhost -> commit `feat(providers): scaffold mneme-providers http sidecar`.

### Task 3: Sidecar Model Backend and Packaging Posture

**Files:** Sidecar crate/Dockerfile/docs; optionally compose provider profile only as a named Phase-3 exception.

**Interfaces:**
- Real embedding/rerank backend honors `MNEMOSYNE_EMBEDDING_DIMS` and never emits all-zero vectors.
- Dims decision is explicit: keep the self-hosted 1024-dim profile via projection/adapter, or document and gate a 768-dim reindex path. Do not silently rely on client zero-padding.
- Runtime model path is pinned to a baked image/cache path; no runtime network downloads in production posture (`HF_HOME`-style model cache, offline runtime).
- Sidecar remains a drop-in replacement behind `https://tei.mnemo.local/embed` and `/rerank`; no Python provider contract changes.

**Steps:** model-backend tests/stubs -> implement real backend behind feature/env selection -> Docker build smoke with offline runtime env -> provider live round-trip -> commit `feat(providers): add model-backed sidecar runtime`.

### Task 4: Provider Health, Manifest, and Log-Redaction Gates

**Files:** Tests around `mnemosyne provider-check`, provider manifest fixtures, sidecar log fixtures; possible provider profile/compose exception.

**Interfaces:**
- `provider-check --provider-manifest ...` passes with `forbid_local=true` for HTTP embedding/reranker/retrieval backends and the five consolidation role checks when configured.
- Sidecar health must load models or fail before user traffic; no lazy first-query failure outside `MNEMOSYNE_RETRIEVAL_TIMEOUT`.
- Honeytoken/log tests prove no raw content, embeddings, secrets, tenant/user IDs, or credentials are emitted.

**Steps:** failing manifest/log tests -> health wiring -> provider-check live smoke -> ruff/cargo test -> commit `test(providers): gate sidecar health and log redaction`.

### Task 5: Provider Bake-Off Harness Binding

**Files:** Eval docs/scripts only unless harness gaps require narrow code; use `eval/run_eval.py`, `eval/harness`, and existing datasets.

**Interfaces:**
- Bake-off protocol uses strict judge methodology from `docs/blueprint/Mnemosyne-Evaluation-and-Test-Plan.md`: non-inferior, no protected-case regression, confidence intervals, and margin greater than run-to-run noise.
- Public benchmark sets remain internal sanity gates only; no headline claims.
- Provider default flip is forbidden without measured evidence and protected-case regression pass.

**Steps:** write provider bake-off runbook/fixture -> smoke on deterministic sidecar/local baseline -> record report path -> commit `docs(eval): add provider bakeoff protocol`.

---

### Task 6: Activate Existing Command Role Providers Safely

**Files:** `src/mnemosyne/consolidation.py`, `src/mnemosyne/cli.py`, tests around runtime parity extensions and provider-check; infra profile exception if required.

**Interfaces:**
- The five proposal roles remain the only model-backed roles: candidate extractor, evidence summarizer, lesson distiller, skill/procedure inducer, entity resolver.
- Forgetter, PromotionGate, belief-reviser decision path, write-decision predicate, and precedence ladder stay deterministic.
- Existing `infra/providers/role-llm.py` command is actually activated by config when intended. Current self-hosted profile has command paths but no `MNEMOSYNE_*_PROVIDER=command`; fix with tests or explicit documented validation.
- All five `Command*` adapters send `prompt_boundary`, bounded gist payload/evidence views, and shell-free JSON stdin/stdout. Grounding shows lesson distiller, procedure inducer, and entity resolver are missing `prompt_boundary` today.

**Steps:** tests that all five command payloads include `prompt_boundary` and role-llm dispatch succeeds -> implement payload fixes/config validation -> provider-check role probes -> commit `fix(consolidation): activate command role providers with prompt boundaries`.

### Task 7: Disclosure-Axis Policy Layer for Proposal Roles

**Files:** `src/mnemosyne/consolidation.py` or a new small disclosure module; tests extending `tests/test_runtime_parity_extensions.py`.

**Interfaces:**
- Existing bounded PII-redacted gist remains the base disclosure form.
- Add endpoint classification (`zero_retention` vs `retentive`, region/in-region, local/frontier) and enforce:
  - S3+ is never sent verbatim to retentive/out-of-region endpoints.
  - S2 goes only to contracted zero-retention in-region endpoints or is pseudonymized with per-disclosure salting.
  - Raw content and raw fingerprints stay omitted from provider packets.
- Tests assert on the consolidation gist/prompt-boundary surface, not retrieval `sanitize_retrieved_text`.

**Steps:** red tests for S2/S3+ disclosure cases + secret/pseudonym behavior -> implement disclosure policy helpers -> run runtime parity/security focused tests -> commit `feat(consolidation): add disclosure-axis gates for proposal roles`.

### Task 8: Recorded Proposal Ledger and Replay Idempotency

**Files:** `src/mnemosyne/consolidation.py`, models/tests as needed; no engine truth semantic changes.

**Interfaces:**
- Frontier/command outputs are recorded as replayable proposals before being consumed by consolidation.
- Proposal identity is content-addressed over tenant, branch, role, strategy, input evidence/proposal CIDs, and sanitized payload metadata, similar to `_materialize_summary` source-identity discipline.
- Replay consumes recorded proposals when present so a crash/audit rerun is idempotent despite model nondeterminism.
- Proposal records never contain raw S3+ content, secrets, raw fingerprints, or unbounded provider output.

**Steps:** replay-idempotency tests that fail pre-implementation -> proposal record model/source identity -> replay consume path -> privacy redaction tests -> commit `feat(consolidation): record proposal-role outputs for replay`.

### Task 9: Frontier -> Local -> Deterministic Role Ladder

**Files:** Provider wrapper/role command scripts, CLI/config tests, hosted-llm-check fixtures.

**Interfaces:**
- Ladder applies only to proposal roles. Decision roles remain deterministic.
- Per-role eligibility is explicit: frontier is low-volume/high-stakes only; local Qwen3 command remains default for high-volume passes; deterministic fallback is opt-in and logged.
- Fallback semantics are implemented inside the wrapper/provider layer or via a tested engine-side seam; do not assume current Command* classes degrade on failure.
- Timeout budgets are coherent: wrapper internal retries must fit under `MNEMOSYNE_*_TIMEOUT`; frontier roles can raise explicit per-role timeout defaults.
- Invocation/cost telemetry is privacy-safe and bounded by existing cadence/rail structure.

**Steps:** tests for ladder ordering, fail-closed/fallback, timeout arithmetic, and role scoping -> implement wrapper/config -> hosted-llm-check fixture -> commit `feat(consolidation): add proposal role provider ladder`.

### Task 10: Phase-3 Exit Verification and Evidence Hooks

**Files:** Program map, progress ledger, ADR/runbook docs, CI sidecar optional lane if added.

**Exit gates:**
- Full suite native and `MNEMOSYNE_PURE=1`.
- Retrieval/provider focused suites, runtime parity extensions, consolidation role tests, protected security/privacy tests.
- Sidecar cargo tests and live provider-check smoke.
- DSN-armed parity subset remains green.
- Eval bake-off report generated with strict-judge/CIs or explicitly recorded as pending/no-default-flip.
- Frontier-path production enablement remains blocked until a fresh §9.2 evidence capture proves gist-packet/no-raw-prompt-logging behavior.
- Program map records Phase 3 status with measured numbers only.

**Steps:** run gates -> adversarial whole-phase review -> fix findings -> final docs/ledger update -> commit `docs(phase3): record provider and consolidation exit verification`.

## Exit Verification (2026-07-03)

Phase 3 is code-complete on `phase3/providers-consolidation` through Task 10.
The exit record is local-only until this branch is pushed and CI runs against the
current head.

Measured gates:

- Full native suite: `uv run --locked python -m pytest -q --junitxml=<tmp>` ->
  **1592 passed / 127 skipped**, 0 failures, 0 errors, 144 seconds.
- Full pure suite: `MNEMOSYNE_PURE=1 uv run --locked python -m pytest -q
  --junitxml=<tmp>` -> **1589 passed / 130 skipped**, 0 failures, 0 errors, 152
  seconds.
- Focused provider/security/consolidation slice:
  `tests/test_provider_manifest_phase3.py`,
  `tests/test_phase3_provider_profiles.py`,
  `tests/test_runtime_parity_extensions.py`, honeytoken/session/parity security,
  belief/calibration, production manifest, poison corpus, and consolidation
  cadence tests -> **216 passed / 5 skipped**, 0 failures, 0 errors.
- DSN-armed parity/live subset with the local compose Postgres DSN on port 54329:
  `tests/test_parity_*`, `tests/test_shared_engine_contract.py`, and
  `tests/test_postgres_engine_live.py` -> **434 passed / 6 skipped**, 0
  failures, 0 errors, 332 seconds.
- Sidecar Rust checks: `rust/mneme-providers` cargo fmt/test/clippy green;
  default feature tests **10 passed**, `--features models` tests **12 passed**.
- Native Rust checks: `rust/mnemosyne-native` cargo fmt/test/clippy green.
- Live provider-check smoke: generated a temporary `forbid_local=true` provider
  manifest, exercised local HTTP `/embed` and `/rerank`, command-backed lexical
  and graph retrieval, and all five proposal roles
  (`candidate_extractor`, `summarizer`, `entity_resolver`, `lesson_distiller`,
  `skill_inducer`) through `python -m mnemosyne.cli provider-check`; report
  `ok=true`.
- Static checks: `uv run --locked ruff check` clean and `git diff --check`
  clean.
- CBM graph was refreshed and verified current for `/Users/admin/Mnemosyne`:
  project `Users-admin-Mnemosyne`, status `ready`, 13909 nodes, 52277 edges.

Bake-off and production evidence status:

- The provider bake-off protocol and deterministic sidecar smoke fixture exist,
  but this exit run did **not** generate strict-judge confidence intervals over a
  private suite. Provider default flips remain blocked and must be recorded as
  `pending/no-default-flip`.
- Frontier/provider production enablement remains blocked until a fresh
  operator-captured §9.2 production evidence bundle proves gist-packet behavior,
  no raw prompt/request/response/evidence logging, forbid-local provider
  manifests, and release-audit custody against deployed infrastructure.
- These results do not claim blueprint parity, Tier-B completion, or production
  operator readiness.

## Explicit Non-Goals

- No C4/rmcp daemon work.
- No public benchmark headline claims from LongMemEval/LoCoMo/etc.
- No change to production topology away from Postgres.
- No change to CID canonicalization, rails/gates, or Postgres schema.
- No default provider flip without bake-off evidence.
