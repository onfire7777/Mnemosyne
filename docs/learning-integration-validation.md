# Learning integration validation — 2026-11-05

## 2026-11-09 memory effectiveness fixes

This follow-up addresses observed memory behavior through the existing runtime
and shared retrieval pipeline:

- Repeated captured requests no longer fill ordinary relevance results with the
  same text. Duplicate candidates trigger a bounded refill, with original source
  identities, author separation, and authorization preserved. Explicit history,
  deep, and passage reads retain their individual occurrences.
- Gated probationary memories without an active incumbent receive paired trial
  allocations, so they can collect useful served and control outcomes sooner.
  Promotion still requires the existing verified-outcome counts and causal
  confidence checks. Reading or preparing context alone cannot promote a memory.
- A failed procedure followed by an explicit external correction and independent
  successful executions can propose an exact-query revision. Old successes no
  longer veto that changed procedure before its comparison trial. Historical
  episodes remain intact; current conflicting outcomes, protected cases, live
  source custody, and the existing revision promotion gates still apply.
- Calibration learns against the raw forecast input while preserving the emitted
  prediction and its hash. Previously mixed calibration buckets rebuild from new
  receipts. Turns that never received a forecast no longer create false
  miscalibration defects or freeze learning.
- Clear user corrections remain learnable after an earlier tool verdict has
  closed the turn. A separate, source-linked feedback record retains the later
  correction without rewriting the original outcome or reusing its receipt.
  Neutral follow-ups, quoted criticism, and repeated questions no longer create
  automatic failure rewards merely because they contain correction keywords.
- Exact user corrections can pass the internal source-retention check using the
  live, authorized user quote. Factual regression cases still require their
  normal retrieval result and confidence; a retained correction enters probation
  and still needs observed trial outcomes before promotion.
- Transient capture metadata (`expires_at` and imported `valid_until`) now
  constrains current recall alongside access-policy expiry. Derived facts,
  profiles, learning sources, maintained-answer snapshots, and source-backed
  working memory share this boundary. Warm caches recheck time-dependent
  custody without deleting the historical source record.
- Exploratory withholding preserves `must_keep` evidence and protected-case
  sources. Learning source checks share retrieval's current, transitive custody
  checks, including access-policy expiry, retirement, quarantine, and erasure.
  Retained assistant provenance remains distinct from external outcome authority.

The focused regressions exercise real Local/SQLite stores, actual receipt-bound
outcomes, revision trials through promotion, persistence/reload, and negative
cases for source custody and ownership. Trial allocation and receipt insertion
share the existing store transaction, including across SQLite engine instances;
retrieval and provider work stay outside it. This follow-up changes no benchmark
definitions or thresholds and does not replace the historical evaluation results
below.

Final focused integration: **689 passed, 83 skipped in 122.78 seconds** across
31 explicit selectors covering the changed learning, retrieval, source-custody,
working-memory, maintained-answer, and host paths. Environment-dependent skips
remain skips, not passes. Ruff and `git diff --check` passed. The source/test
snapshot remained unchanged throughout verification.

The offline wheel build and isolated installed-wheel smoke passed: SQLite
calibration persisted across reload, repeated requests left the stored answer
retrievable, and expired evidence remained stored but absent from current
recall. All changed package files matched the wheel payload. Wheel SHA256:
`3201dfb3a9df2b60d62191fed912b7addfdedf7f135d57a1069e560432175aa8`.

Exact selectors, JUnit results, source hashes, original failing reproductions,
and the installed-wheel receipt are retained locally in
`/Users/admin/.codex/tmp/mnemosyne-learning-effectiveness-20261109/`
(`ship-focused-selectors.json`, `ship-focused.xml`, `ship-source-sha256.json`,
and `ship-wheel-smoke.json`). These are focused local checks, not a new broad
benchmark result or deployed-host validation.

The full-repository test run was stopped at the user's request and was not
restarted. Its profile fixture used nonexistent source IDs; the fixture now
captures real evidence and is included in the focused verification. Existing
working-route fixtures likewise retain their routing assertions with real source
custody. Correction-admission fixtures now assert probation with explicit
user-quote gate evidence. No full-suite pass is claimed for this follow-up.

## Original 2026-11-05 integration

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

## Learning ownership and synthesis follow-up

The next audit joined the remaining legacy/native induction paths, retained local
learning when providers are configured, coalesced equivalent proposals with all
source and hypothesis links, and preserved old artifact identities and retirement.
Exact-query identity and revision matching now use the same case equivalence as
serving; repeated observations of one query do not create a broader duplicate.

Long-lived SDK, worker, and MCP hosts share current engine-owned configuration.
Direct skill tools resolve the same configured library. Training exports retain
canonical admission and provenance, and compatibility refreshes preserve pending
edits and conflict detection. Route adaptation shares bounded normalization;
policy observations count each episode/variant once. Responsibilities and retained
capabilities are listed in [Learning unification](learning-unification.md).

After the behavioral fixes, **736 tests passed and 3 skipped in 62.25 seconds**:
43 related learning, host, skill, calibration, and parametric test files plus the
exact 11 previous failure cases. Default test collection also passed. A test-package
collision discovered by combining skill and latency tests was fixed by making
root test-helper imports explicit. This was a scoped regression run, not a rerun
of the historical full-suite or a sealed learning-benefit benchmark.

The selector manifest, logs, and JUnit reports are retained under
`/Users/admin/.codex/tmp/mnemosyne-unified-learning-20261105/`; the behavioral
checkpoint is `bugfix-results.xml`. All 22 learning components remain active by
default. No paid provider, model trainer, or external benchmark was run.

The subsequent behavior-preserving simplification removes unused route counters,
repeated legacy record conversions, and duplicate protected-case filtering. Skill
library selection delegates directly to its existing resolver. No tests changed
for this refactor. The final combined run again passed: **736 passed, 3 skipped in
63.26 seconds** (`final-results.xml`). Skips cover unavailable Torch and PDF
dependencies and a Windows-only path check. Ruff and `git diff --check` passed.

An offline wheel build and isolated wheel-import smoke check also passed, including
all 22 active defaults, shared legacy/native procedure identity, and durable
reload. This follow-up wheel's SHA256 is
`a1d9488db01acefcd46be41eb4d0155a522edfdcd550785f51ab23eaed62efd6`;
its build log and smoke receipt are in the same validation directory. This is
local package validation, not deployed-host or learning-benefit evidence.

## Separate benchmark ownership

Mnemetric owns public benchmark reporting and archives. The public LongMemEval report and copied receipts added to Mnemosyne in `f73f90e9` were removed from its current tree. All 14 original JSON/JSONL receipts were byte-checked against Mnemetric: eight already existed in its October 29 evidence archive, and six development receipts were preserved in its `development/` subdirectory with hashes and provenance. Mnemetric's corrected report remains authoritative; the superseded report remains recoverable in Mnemosyne's Git history and a local backup.

Mnemosyne retains its runtime, internal regression fixtures, and independent development runner. Local runner output is ignored by Git. This correction runs no external benchmark and changes no public scores.

Live PostgreSQL verification still requires a configured PostgreSQL test database. The targeted local checks do not establish learning benefit on a sealed benchmark.

## 2026-11-06 reliability follow-up

The implementation and verification window spans 6–8 November 2026. Long-run
wall time includes a host suspension and is unsuitable as a throughput result.

The implementation checkpoint is `0bae7e93`. Codex lifecycle capture now
recovers completed turns from session-bound transcripts, retains actual command
outcomes, deduplicates retries, and excludes subagent instructions from human
turns. The worker reconsiders changed outcomes, artifact state, and protected
cases, and retries trainer failures. Deferred source writes and older episodes
with unavailable provenance no longer generate invalid learning candidates.

Automatic task identifiers now preserve case, internal whitespace, numbers,
and complete request details in a versioned namespace. An explicit `task_type`
shares learning across different phrasings. The regression monitor requires
an installed learning intervention and checks receipt participation before
attributing a performance decline to learning.

Maintained answers use incremental source snapshots across Local, SQLite, and
PostgreSQL. Source writes, rollback, current access policy, expiry, deletion,
and dependent projections participate in freshness checks. Committed sensitive
changes purge private cached plaintext across local engine instances, with
publication and purge serialized on the same cache lock. Older PostgreSQL
schemas retain a complete-snapshot fallback until migration.

The development scaling check used 5,000 source rows on each backend. Each
one-row update fetched and revalidated one row with zero complete exports.

| Backend | Initial snapshot | One-row update |
| --- | --- | --- |
| Local | 0.423 seconds | 0.000720 seconds |
| SQLite | 0.524 seconds | 0.000986 seconds |
| PostgreSQL 16.15 | 0.826 seconds | 0.0677 seconds |

These timings describe one local development measurement. The final regression
tests also verify access counts, expiry, source deletion, concurrent publication,
and old-record compatibility. The scaling script and raw receipt are retained
under `/Users/admin/.codex/tmp/mnemosyne-completion-20261106/freshness/`.

All 380 tests in the PostgreSQL-specific files passed against PostgreSQL 16.15.
The additional incremental-source matrix passed 65 cases and skipped seven
cases that apply only to other backends. One older test
was updated to distinguish unverified historical learning from explicitly
curated trainer inputs and to check canonical storage after migration.

An expanded run of shared-backend tests passed 1,104 unique cases with live
PostgreSQL enabled; 13 skips were backend-inapplicable checks. No selected
PostgreSQL check remained skipped for lack of a database. A second stale mirror
assertion now checks canonical learning episodes and artifacts while retaining
tenant isolation and requiring the legacy tables to contain no duplicate rows.
The failed initial assertions, focused corrections, and remaining-case run are
retained separately in the `postgres/` validation directory.

The learning harness now permutes public choices independently of the gold
answer, preserves model response receipts, and supports bounded local Ollama
evaluation. `common-pretraining-v2` separately tests retention, adaptation, and
transfer after matched setup. Its held-out scripted competence probes omit
deliberate exploration while training retains exploration. The original
protocol and its thresholds remain available.

The offline wheel build passed. Its SHA-256 is
`49224966d4777132c12dcb5595f3585e1e9792f8e66f91828237bcce80cb531b`.
Every packaged Python source matched the checkout. An isolated wheel import
passed the SQLite incremental snapshot check, case-sensitive task identity
check, Codex adapter imports, profile source-custody check, and all 22 active
learning defaults.

### Local model measurement

The completed Qwen3 1.7B diagnostic used development seed 11 and 128 tasks per
arm at `f624623f`, for 384 model calls. All calls completed, with zero transport
errors, prompt-truncation events, or guard detections. The source hashes stayed
unchanged throughout the run.

| Arm | Held-out ordered-step success | Area under the learning curve |
| --- | --- | --- |
| Learning enabled | 92.19% | 0.9111 |
| Frozen memory | 92.19% | 0.9033 |
| No memory | 62.50% | 0.6436 |

This is a single-seed comparison on the synthetic ordered-operation task.
It demonstrates a descriptive memory advantage in that task, with equal
held-out accuracy for enabled learning and frozen memory. All three arms
remain below F2's strict 100% acceptance threshold. It does not establish
broad production learning benefit. Complete requests, responses, model
identity, and receipts are in
`/Users/admin/.codex/tmp/mnemosyne-completion-20261106/evaluation/final-model128-packed/`.

### Paired scripted learning measurement

The F2 `common-pretraining-v2` diagnostic completed five development seeds with
512 tasks per arm. All five learning-enabled runs passed the strict held-out
ordered-step check at 100%, with zero guard detections. Mean held-out success
was 26.72% for frozen memory and 23.59% for no memory.

| Comparison | Mean area-under-curve lift | Paired bootstrap interval |
| --- | --- | --- |
| Learning versus frozen memory | 0.5318 | 0.4820 to 0.5803 |
| Learning versus no memory | 0.5401 | 0.4875 to 0.5928 |

The frozen-memory slope interval included zero, and all comparison workloads
matched. This establishes learning benefit for this scripted procedure task.
The report remains a development diagnostic covering one family, so its overall
all-family acceptance flag remains false. The run began at `0bae7e93`; later
changes affected the model transport and optional zero-count diagnostics,
with the source hashes retained in the report. Raw rows and comparisons are in
`/Users/admin/.codex/tmp/mnemosyne-completion-20261106/evaluation/final-v2-f2-paired512.json`.

### Default suite coverage

The final collection contains 8,668 selected cases, including the added profile
regressions. The coverage audit combines the default run, remaining-case run,
focused corrections, and configured PostgreSQL checks: **8,620 passed, 48 skipped,
zero remaining failures, and zero missing cases**. The remaining skips cover
platform-specific, optional-dependency, external-identity, benchmark opt-in, and
backend-inapplicable checks; none is a PostgreSQL availability skip. The repository's existing
191 deselections remain outside that collection. Exact pass and skip counts are
recorded in `suite-coverage-audit.json` in the validation directory.

Validation used the initial suite, the remaining-case run, and focused reruns
after corrections. The audit accounts for every selected test group and its
parameter count, including fixtures whose process identifiers change between
collections. Initial failures and interrupted runs remain in the retained
artifacts. A framework-conversion fixture now uses a unique model scope so
unrelated background work cannot contaminate its extraction-call count.

The selector manifests, JUnit files, and coverage audit are retained under
`/Users/admin/.codex/tmp/mnemosyne-completion-20261106/`.

### Complete development matrix

The original protocol completed all 3,640 scheduled streams across its families,
seeds, controls, and ablations. It recorded zero runtime exceptions and zero
guard detections, but **the broad learning acceptance gate failed**. Of 130
learning-enabled streams, 70 supported their family prerequisites and 42 passed
their family checks. Across all arms, 1,475 streams were supported and 869
verified. Twenty-seven computed comparisons failed their lift or frozen-control
requirements, twelve passed, and twelve required comparisons were unavailable.
Six ablation arms intentionally remain unsupported.

Unmet cases include procedure acquisition within the short training budget,
revision and retention prerequisites, schema activation, contingency contrasts,
held-out abstraction, chunk formation, import selection, calibration, and
consistent benefit over controls. These are outstanding capability or empirical
validation gaps; passing software tests and enabling components do not resolve
them. The longer F2 run does not substitute for this matrix.

This run started at `0bae7e93`. The report records source drift during the run,
including later model-adapter, profile-privacy, and compatibility changes. It is
retained as a development diagnostic with its original hashes, not relabeled as
a sealed result for the final checkout. Summary and raw data are in
`/Users/admin/.codex/tmp/mnemosyne-completion-20261106/evaluation/final-all-arm32-summary.json`
and `final-all-arm32.json`. No sealed evaluation was consumed.

### Profile erasure and failed cleanup

The profile corrections are committed in `3d1bd9a0` and `ec83e883`. Cleanup now runs after the
owning source transaction commits, with its captured request context. A rollback
cancels cleanup. A cleanup failure cannot
skip cache invalidation or journal erasure, and the committed deletion remains
retryable. Public profile packets recheck their source custody before returning
entries, inferred preferences, support strategies, or consolidated latent data.
Erased or unauthorized evidence is withheld even when projection cleanup fails.

Checks use exact content IDs and branch registries rather than exporting the
whole corpus. Manual unsourced entries remain available, as do entries supported
by a current authorized branch copy. Cyclic or malformed profile lineage and
missing support events fail closed. Independently sourced corrections do not
depend on the superseded entry's evidence. Regression tests exercise commit,
rollback, cleanup failure and retry, reload, branch copies, and shared facades.
Public packets omit internal drift history, which may cite a different source
from the current statement. Cleanup also removes source-dependent history and
latent summaries and embeddings from persisted state, including transitive
sources. It retains independently supported entries and manual profiles.
Failures during source checks or persistence restore the in-memory profile so
a retry can complete cleanup even after the source was hard-deleted. Reload
tests check both runtime payloads and PostgreSQL mirrors. The final cross-backend
profile run passed all 267 cases; the broader profile, erasure, host, and MCP run
passed 805 cases with 21 environment-dependent skips.

### Local host state

The installed Codex hook and automatic-learning shim load the shared host
implementation. A fresh authenticated local status read on 8 November reported
all 22 components active, learning enabled and unfrozen, seven episodes, zero
credit rows, and zero open defects. Five protected retrieval checks were added
using existing retained sources and verified with actual retrieval.

Zero credit rows remain a real data limitation. The system needs repeated,
source-linked, verified user outcomes before it can establish personal learning
benefit or admit sufficient examples to the configured trainer. Synthetic
benchmark outcomes were not inserted into the personal store. Existing MCP
processes retain already imported code; new host processes load these changes.

### Matched retention setup

A separate F11 development check at `06235183` used the same 258 setup rows
and five evaluation tasks for each arm. The simulated long-gap success rates
were 80% with learning, 100% with frozen memory, and 20% without memory. Both
memory arms passed the family threshold, with zero guard detections. This
small single-seed check validates the matched-setup control path and provides
no incremental retention advantage over frozen memory. Its clock advances
virtually; it is not a longitudinal production observation.

The corrected frozen control serves its acquired memory while pausing updates.
The earlier retention attempt, which accidentally disabled serving as well,
is retained as an invalid-control diagnostic. The corrected rows and alignment
checks are in
`/Users/admin/.codex/tmp/mnemosyne-completion-20261106/evaluation/final-v2-retention256-corrected/`.
