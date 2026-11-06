# Learning integration validation — 2026-11-05

This cleanup integrates the learning implementation with Mnemosyne's existing APIs. All 22 learning components retain their `active` default. Explicit pause/off settings and mandatory provenance, outcome, effect-approval, and erasure guards remain effective.

The implementation is integrated with the reorganized `dev`/`main` baseline `d0143fe8`, including its journal/SQLite tenant ownership, redacted retrieval, ingestion validation, queue recovery, and parametric artifact-path fixes. The local architecture work and separately edited source files are preserved.

## Ownership after cleanup

| Area | Authoritative implementation |
| --- | --- |
| Trajectories, lessons, procedures | Native episodes/artifacts, serialized by the existing model classes; `LearningSystem` provides compatibility views. |
| Historical storage | Side-state archives and duplicate trajectory wrappers migrate into the native writer. Reported historical success remains distinct from verified outcomes. |
| Learned skill lifecycle | The native runtime owns admission, promotion, demotion, revisions, retirement, and rollback. `SkillStore` projects its per-scope states and distinct episode outcomes. |
| Host completion and cadence | SDK, MCP, Hermes, and jobs use shared runtime configuration and orchestration. Atomic claims deduplicate automatic consolidation and allow failed attempts to retry. |
| Legacy induction | Existing evidence consolidation skips sources already owned by native episodes. |
| Training sources | Automatic sources must have canonical active admission and provenance. Historical learned status claims are excluded. Explicit curated operator inputs retain their separate supported path. |
| Shared calculations | One observed-step extraction contract and one Wilson numerical kernel, with each public API retaining its empty-sample semantics. |
| Profile erasure | One branch-wide decision and persistence operation; direct engine callbacks preserve entries while another live branch still supports them. |

Standalone manually imported skills retain their original validation path until native registration. This is deliberate API compatibility, not a second owner for runtime-managed skills.

## Regression coverage

New tests cover immediate native skill ownership; promotion with and without control outcomes; duplicate and concurrent signals; failed consolidation retries; session-end maintenance; disabled-component outcomes; scoped library projections; source erasure; revision/rollback lineage; stale archive resurrection; concurrent compatibility edits; native metadata preservation; shared engine ownership after reload; and training-source filtering.

The final isolation review also separates consolidation, abstraction, chunks, and candidate identities by user. Serving enforces artifact ownership independently of source readability. Native source identities preserve user/session provenance when different users produce identical text; supplied host evidence remains reused. Existing owner-matched identities remain stable during migration.

Full-suite investigation also identified a pre-existing relation replay bug. Empty or inverted validity windows did not overlap themselves, so replay could repeatedly clone the same relation. Matching the same relation identity and window makes replay idempotent. Tests cover thin/full canaries and preserve distinct relation identities.

The PostgreSQL source-locked publication path also attempted schema-readiness DDL during export. It now keeps that transaction read-only until the guarded model update; missing schema fails closed instead of being created while source locks are held.

The wheel builds successfully. An isolated import of the built wheel verifies all 22 active defaults, SDK external-outcome resolution, one canonical trajectory, and durable reload.

## Original integration verification

| Check | Result |
| --- | --- |
| Default suite, consolidated across eight partitions and final fix verification | 7,846 passed; 550 skipped; 10 golden-fixture mismatches, resolved by the targeted follow-up below. |
| Current collection coverage | All 8,406 selected test cases accounted for; zero missing. The existing 191 configured deselections remain excluded. |
| Final focused run in the actual main checkout | 1,362 passed; 115 skipped. |
| Final skill-owner projection, serving, and host checks in main | 42 passed. |
| Repeated current quality-gate runs | Bit-for-bit reproducibility and historical nonregression checks passed. |
| Additional evaluation tests outside the default suite | 50 passed; one archived-receipt failure, resolved by the targeted follow-up below. |
| Built-wheel isolation | Passed: installed-target imports, 22 active defaults, one canonical episode/compatibility view, separate-process reload, and same-text runtime/SDK capture for distinct users. |

Counts are deduplicated by current test identity; overlapping fix-verification runs are not added twice. Superseded test identities and repeated collection-level skips are not counted as selected cases. Environment-dependent tests, including live PostgreSQL coverage, remain skipped rather than reported as passing.

The original integration wheel is `mnemosyne_memory-1.7.0-py3-none-any.whl`, SHA256 `6f412e4c88701d4db24649d1b10fba168d4c6d4bd99925747ac6edf138a90339`. At that integration checkpoint, all 118 source files in the integrated worktree matched the main checkout. This wheel predates the targeted fixes below and was not rebuilt for that follow-up. Validation logs, the per-case coverage audit, and the installed-wheel smoke scripts are retained locally under `/Users/admin/.codex/tmp/mnemosyne-learning-validation-20261105/`.

## Targeted follow-up: all 11 failures resolved

Only the 11 previously failing cases were rerun together: **11 passed in 20.26 seconds**, with no skips or failures. The full suite was not rerun for this follow-up; the earlier counts above remain historical results.

| Previously failing cases | Fix and verification |
| --- | --- |
| Six golden-equivalence cases: growth, rails, and conflicts in thin/full branch modes | Corrected thin-canary relation isolation and replay, made synthetic encrypted audit comparison deterministic, and refreshed the three snapshots for the integrated default-on learning behavior. Every scenario repeats exactly and has identical complete output across both branch modes. |
| Four pipeline snapshots: fast, deep, empty, and low support | Fixed seed, engine, and evaluation timestamps so salience does not depend on wall-clock age. Refreshed the approved retrieval and learning-rail surfaces while retaining exact float-bit, hit-order, adapter, and explanation comparisons. |
| One latency receipt case | Exercises the real local synthetic receipt writer into a temporary directory, validates both distributions and receipt identities, and verifies historical latest reports are untouched. No dependency on Mnemetric's archived files remains. |

The canary fix copies only relation peers of touched assertion groups and snapshots relation inputs before assertion replay can mutate their validity windows. Inherited copies replay once; newly added relations replay separately. The canary path and ordinary supersession path share one predicate-alias matcher. Both retain tenant and branch isolation.

The golden harness still uses real authenticated encryption. It authenticates each returned audit envelope with its referenced key before erasure can destroy that key, then requires the exact captured token and matching key ID when canonicalizing persisted output. Complete decrypted payloads, envelope key IDs, and encryption timestamps remain compared; internal IDs use the existing canonical relabeling. Unknown or altered tokens fail. Deterministic test-only clock/entropy overrides restore their original bindings on normal and exceptional exit. Production encryption remains unchanged; the learning store's only adjustment is moving its UUID import to module scope.

The three synthetic fixtures were refreshed only after repeated-run and thin/full equality checks passed. The G0 fixture was not changed. All 22 learning components retain their active defaults. Ruff and `git diff --check` passed on the changed files.

The exact 11-case selector manifest, pytest log, JUnit report, and scenario comparison logs are retained under `/Users/admin/.codex/tmp/mnemosyne-remaining-failures-20261105/`.

## Separate benchmark ownership

Mnemetric owns public benchmark reporting and archives. The public LongMemEval report and copied receipts added to Mnemosyne in `f73f90e9` were removed from its current tree. All 14 original JSON/JSONL receipts were byte-checked against Mnemetric: eight already existed in its October 29 evidence archive, and six development receipts were preserved in its `development/` subdirectory with hashes and provenance. Mnemetric's corrected report remains authoritative; the superseded report remains recoverable in Mnemosyne's Git history and a local backup.

Mnemosyne retains its runtime, internal regression fixtures, and independent development runner. Local runner output is ignored by Git. This correction runs no external benchmark and changes no public scores.

Live PostgreSQL verification still requires a configured PostgreSQL test database. The targeted local checks do not establish learning benefit on a sealed benchmark.
