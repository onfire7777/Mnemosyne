# Whole-Memory Reference Harness and Pilot Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Use
> `superpowers:test-driven-development` for every code change and
> `superpowers:verification-before-completion` before any delivery claim.

**Goal:** Build the smallest auditable reference harness and development pilots
for M01, M03, M10, M12, M13, M15, and M20 without running an official
benchmark, publishing a result, or claiming certification or superiority.
Freeze the contracts needed to preserve official upstream protocols unchanged
and to add separately named enhanced successor tracks later, without blending
their scores.

**Architecture:** Extend the existing `eval/public` runner, CLI-only driver,
bundle custody, scoring dispatch, and Phase 16 leaderboard contracts. Add one
closed JSON ABI, one reference adapter, deterministic development fixtures,
an isolated execution/metering boundary, and an additive result-v2 path.
Preserve result-v1 bytes and the signed ledger. Do not build a parallel
benchmark lifecycle. Store immutable per-attempt backend results as the
evidence authority; comparison and future website views are derived,
reproducible projections only.

**Tech Stack:** Python 3.12 standard library, JSON Schema documents validated
through repository-owned fail-closed code, existing `mneme` CLI,
pytest/Hypothesis already in the development environment, Ruff, OCI-compatible
container tooling when the sandbox gate is exercised, and existing
Ed25519/ledger infrastructure.

## Authority and execution boundary

- Governing design:
  `docs/superpowers/specs/2026-07-26-whole-memory-benchmark-standard-design.md`.
- Authored against `origin/main@489e1361` after the documentation branch
  merged current main. Before implementation, fetch current main and re-run a
  read-only conflict/authority check.
- Do not start implementation while another active `GOAL.md` lease owns an
  overlapping path. A future owner must install an exact lease for only the
  files named here.
- This plan does not authorize implementation, benchmark execution, a push, a
  pull request, public rendering, hosted publication, or an official result.
- The implementation lane may not touch M02, M04–M09, M11, M14, or M16–M19
  except where a shared existing contract must remain compatible.
- No new runtime dependency. Use the standard library and already-installed
  project dependencies. Any unavoidable sandbox runtime is an external
  prerequisite, not a Python dependency.
- All new suites are repository-named `*-development` suites. They must never
  use an upstream official benchmark name.
- This pilot implements no official or enhanced benchmark cell. Its schemas
  must nevertheless close `track_kind` to `OFFICIAL-UPSTREAM`,
  `ENHANCED-SUCCESSOR`, or `DEVELOPMENT`; require official fidelity and
  successor-difference manifests where applicable; and prohibit a blended
  official/enhanced certified score.
- Existing functional and safety rails are inherited unchanged. A diagnostic
  threshold cannot replace `M-DEDUP-EXACT=1.0`, `M-ASOF-ACC=1.0`,
  `M-ECE <= 0.05`, zero confident unanswerable assertions, zero protected
  regressions, or the
  publication/custody gates.
- One process and one worker at a time on the 16 GiB Apple Silicon profile.
  Before any measured pilot run, perform the full admission procedure in
  `.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md`.

## Target evidence state

| Module | Maximum `admission_state` | Maximum `evidence_level` | Hard deferral retained |
|---|---|---|---|
| M01 | `PILOT-READY-DEV` for Local only | `INTERNALLY_MEASURED` | SQLite/P32 and seeded process-kill durability |
| M03 | `PROPOSED` for full M03 | `INTERNALLY_MEASURED` for the valid-time slice | full bitemporal transaction-time query semantics |
| M10 | `PILOT-READY-DEV` for deterministic reader | `INTERNALLY_MEASURED` | model-backed/judged QA and absent numeric confidence |
| M12 | `PROPOSED` | `INTERNALLY_MEASURED` development smoke | recurrence plumbing, official pins, calibrated baseline, certification scale |
| M13 | `PROPOSED` | `INTERNALLY_MEASURED` development smoke | multi-capacity/promotion experiment and certification scale |
| M15 | `PILOT-READY-DEV` for admitted pilot payloads | `INTERNALLY_MEASURED` | any missing manifest/seed/canonical projection |
| M20 | `CONTRACT-READY` for result-v2/local ledger | `IMPLEMENTED` | identity-bound signing, public rendering/publication, PBPP, independent custody |

No row may advance merely because its tests pass. The exact §4 feasibility
record, measured resource receipt, sandbox receipt, BOM, and replay evidence
must exist for the claimed state.

## Pilot tranche order

1. **WMB-P1 — Contract freeze:** common ABI, fixtures, scorers, baselines,
   M15 canonical projection, additive M20 result-v2/ledger semantics, and
   expected failures.
2. **WMB-P2 — Isolation and metering:** SUT boundary, sandbox, external meters,
   unscored resource smoke, pre-run admission artifacts, and resource receipt.
3. **WMB-P3 — Core development cells:** implement M01, M03 valid-time slice,
   and M10; do not run scored trials before admission.
4. **WMB-P4 — Existing action/working-memory cells:** M12 and M13 evidence with
   explicit gaps; do not run scored trials before admission.
5. **WMB-P5 — Admitted execution and evidence migration:** run admitted cells,
   enforce M15 replay, and exercise the additive M20 result-v2/local ledger.
6. **WMB-P6 — Integrated review:** exact receipts, cross-cell replay, docs, and
   no publication.

---

### Task 1: Freeze the closed ABI and fail-closed validator

**Status:** Closed-ABI slice completed at source head
`8d64f554c565edeb0c43868ff6d436e6e09df33a`, merged by PR #79 at
`a95fe4d291093253f8ce49adff32ba875a35e884`. Result-v2 compatibility and
ledger fixtures remain open.

**Files:**

- Create: `eval/public/schema/wmbs-0.1-draft.schema.json`
- Create: `eval/public/adapters/whole_memory_reference.py`
- Create: `leaderboard/schema/result-v2.schema.json`
- Create: `tests/test_public_whole_memory_reference.py`
- Modify: `tests/test_leaderboard_result_contract.py`
- Modify: `tests/test_leaderboard_ledger.py`

**Interfaces:**

- Protocol ID: `wmbs/0.1-draft`.
- Requests: `negotiate`, `create_run`, `ingest`, `retrieve`, `answer`,
  `finalize`.
- Shared `RequestContext`: `protocol_version`, `run_id`, `attempt_id`,
  `request_id`, `idempotency_key`, `sequence`, `deadline_utc`, `tenant_id`,
  optional `principal_id`, and optional `session_id`.
- Responses: `IngestReceipt`, `RetrievalEnvelope`, `AnswerEnvelope`,
  `FinalizeReceipt`, and closed `ErrorEnvelope`.
- Evidence definitions in the same compound schema: `FeasibilityRecord`,
  `BaselineManifest`, `PowerPlan`, `SoftwareDataBOM`, `SandboxReceipt`, and
  `ResourceReceipt`, plus the identity/result-bound `SmokeReceipt` required for
  `PILOT-READY-DEV`; each artifact carries its own schema ID and digest.
- Result-v2 atomic identity:
  `system_id`, `system_version`, `adapter_id`, `adapter_version`,
  `track_kind`, `benchmark_id`, `benchmark_version`, `module_id`, `division`,
  `resource_profile`, `backend_id`, `hardware_fingerprint`,
  `model_policy_id`, `dataset_split_digest`, `run_id`, `attempt_id`, and
  `seed`.
- `OFFICIAL-UPSTREAM` records require pinned upstream protocol/data/split/
  preprocessing/scorer/environment/revision digests.
  `ENHANCED-SUCCESSOR` records require a parent official construct and a
  digest-bound difference manifest. `DEVELOPMENT` records are never
  publishable or upstream-comparable.
- Response modes: `normal` and `forced`; forced answers are diagnostic.
- Error codes: `INVALID_REQUEST`, `UNSUPPORTED_OPERATION`, `UNAUTHORIZED`,
  `CONFLICT`, `ORDER_VIOLATION`, `DEADLINE_EXCEEDED`, `RESOURCE_LIMIT`,
  `DEPENDENCY_UNAVAILABLE`, and `INTERNAL_ERROR`.
- Freeze before any module cell: the M15 canonical/volatile-field projection
  and the result-v2 fields, four digest meanings, version dispatch, and
  append-only cross-version supersession semantics described in Task 10.

- [x] Write failing tests for every required field, unknown-field rejection,
      timezone-aware UTC normalization, bounded strings/arrays, finite numbers,
      duplicate request/idempotency behavior, sequence monotonicity, deadline
      failure, and exact error-code closure.
- [x] Write failing evidence-record tests for all fourteen feasibility fields,
      SPDX/license and data-rights declarations, PII/consent/takedown fields,
      baseline pins, inferential fields, sandbox/meter provenance, and
      digest-bound cross-references.
- [ ] Write the result-v2 schema and RED compatibility/ledger fixtures before
      any module implementation. These fixtures freeze the contract; Task 10
      later completes validator/ledger/render code without changing them.
- [ ] Add RED fixtures proving atomic attempts cannot contain aggregate
      metrics, official records fail without a complete fidelity manifest,
      successor records fail without a parent/difference manifest, and no
      projection can combine official and enhanced scores into a certified
      result.
- [x] Freeze the M15 canonical projection and volatile-field exclusion list in
      golden tests before any module creates a bundle.
- [x] Add golden request/response objects for each operation and prove canonical
      JSON equality independent of input mapping order.
- [x] Run
      `PYTHONPATH=src uv run --extra mcp pytest -q
      tests/test_public_whole_memory_reference.py` and capture the expected RED
      failure because the schema/adapter do not exist.
- [x] Add the compound schema and the minimum standard-library validator in
      `whole_memory_reference.py`; do not add a general schema framework.
- [x] Implement only protocol validation and canonicalization. Do not call
      Mnemosyne or score a module in this task.
- [x] Re-run the focused test and Ruff:
      `uv run ruff check eval/public/adapters/whole_memory_reference.py
      tests/test_public_whole_memory_reference.py`.
- [x] Record `sha256` for the schema and golden vectors in the test receipt.

**Acceptance evidence:**

- Exact schema digest and protocol ID.
- Golden-vector test output.
- Proof that extra fields, non-finite numbers, stale deadlines, reused request
  IDs, and unknown error codes fail closed.
- No network, model, database, or benchmark run.

**Deferral:** If any request or response meaning conflicts with the design
specification or an existing public contract, stop at `DEFERRED-CONFLICT`.
Do not implement an ambiguous field.

### Task 2: Add the development sandbox and external resource receipt

**Files:**

- Create: `eval/public/sandbox.py`
- Create: `eval/public/sandbox/Dockerfile`
- Modify: `eval/public/schema/wmbs-0.1-draft.schema.json`
- Modify: `tests/test_public_whole_memory_reference.py`

**Interfaces:**

- `run_isolated(argv, *, input_dir, output_dir, limits, allow_network=False)
  -> ResourceReceipt`.
- `argv` is a validated string array executed with `shell=False`; shell
  strings are rejected.
- Receipt fields: schema/profile IDs, SUT command/image/build digest, start/end
  times, exit/abort state, wall/CPU time, peak RSS, disk high-water/I/O,
  network bytes, API calls, tokens, retries, billed cost, workers, host
  admission samples, cold/warm state, and meter provenance.

- [ ] Write RED tests using a harmless fixture child process. Require an
      environment allowlist, empty secret values, a new temporary working
      directory, timeout termination, output quota, canonical receipt, and
      explicit `unavailable` for a meter the host cannot provide. Prove timeout
      cleanup terminates descendants, not only the direct child.
- [ ] Require the OCI execution profile to use a digest-pinned image,
      non-root user, read-only root, tmpfs scratch, dropped capabilities,
      `no-new-privileges`, PID/CPU/memory limits, no host repository mount,
      read-only fixture mount, write-only result mount, and `--network none`.
- [ ] Build the image only after the workload preflight passes. Record the
      resulting image digest; never treat a mutable tag as evidence.
- [ ] Pin every base image by digest, generate a content-bound SPDX 2.3 or
      CycloneDX SBOM for the exact image and dependency lock, retain build
      provenance, and fail policy tests for missing license conclusions,
      forbidden redistribution, or unbound components.
- [ ] Run a deterministic fixture privacy scan and lineage check; negative
      fixtures containing raw personal data, missing consent/authority, or no
      takedown rule must fail admission. Manually asserted BOM/privacy fields
      are not sufficient evidence.
- [ ] Measure outside the SUT. Reuse the field semantics from
      `eval/g0/resource_usage.py`, but do not reuse its self-reported fixture as
      the external meter.
- [ ] Add one unit-level fake-meter path so CI can test receipt validation
      without Docker/Colima.
- [ ] Run the focused tests and Ruff. Then, only on an admitted host, run one
      no-op sandbox smoke and validate its receipt against the schema.

**Acceptance evidence:**

- OCI build digest and effective sandbox arguments.
- Receipt proving non-root, read-only root, no network, bounded resources, and
  external wall/CPU/RSS/disk measurement.
- A negative test showing a network attempt or output-quota breach fails.

**Deferral:** If no approved OCI runtime is available, or any required
isolation/meter cannot be enforced, unit tests may pass but every suite remains
at `admission_state=PROPOSED`; do not assign `PILOT-READY-DEV` or a resource
rank.

### Task 3: Register the common harness without creating a second runner

**Files:**

- Modify: `eval/public/runner.py`
- Modify: `eval/public/scoring.py`
- Modify: `eval/public/bundle.py`
- Modify: `eval/public/registry.json`
- Modify: `eval/public/README.md`
- Modify: `src/mnemosyne/cli.py`
- Modify: `tests/test_public_eval.py`
- Modify: `tests/test_public_eval_cli.py`
- Modify: `tests/test_public_eval_scoring.py`
- Modify: `tests/test_public_whole_memory_reference.py`

**Interfaces:**

- Reuse `run_public_suite`, `_ADAPTERS`, `_NORMALIZERS`, and
  `_PROFILE_CONTRACTS`.
- Reuse `write_bundle`, `verify_bundle`, and `reproduce_bundle`.
- New development suite IDs:
  `wmbs-m01-development`, `wmbs-m03-valid-time-development`,
  `wmbs-m10-development`, and `wmbs-m20-development`.
- Scoring profile IDs:
  `wmbs-m01-v1`, `wmbs-m03-valid-time-v1`, `wmbs-m10-v1`, and
  `wmbs-m20-v1`.
- The host CLI flag `--execution-profile wmbs-l16-dev` must route the suite
  into `run_isolated`; direct in-process execution is unit-test evidence only.

- [ ] Write RED tests proving the four suite IDs route through the existing
      runner, reject unknown profiles, emit independent manifests, and remain
      `publishable:false` and `pbpp_headline_eligible:false`.
- [ ] Bind the suite child PID/container ID, immutable image digest, exact argv,
      and meter identity into the sandbox/resource receipt and bundle. Prove
      that `--execution-profile wmbs-l16-dev` cannot silently fall back to the
      in-process runner.
- [ ] Add the smallest dispatch entries. Do not copy runner/bundle lifecycle
      code into the reference adapter.
- [ ] Extend bundle manifests only with versioned optional references needed
      for ABI schema, sandbox receipt, BOM, baseline, power plan, and resource
      receipt. Preserve existing bundle verification behavior.
- [ ] Make `reproduce_bundle` fail if any manifest-owned pilot artifact
      differs.
- [ ] Document exact local commands, development-only labels, and deferrals.
- [ ] Run:
      `PYTHONPATH=src uv run --extra mcp pytest -q
      tests/test_public_eval.py tests/test_public_eval_scoring.py
      tests/test_public_whole_memory_reference.py`.

**Acceptance evidence:** Existing public-runner tests stay green; each new suite
has a distinct profile, fixture digest, scorer digest, and non-publishable
bundle; no official registry row is created.

**Deferral:** Any bundle-field change that would reinterpret an existing
manifest requires a new bundle schema version. Do not silently extend a closed
shape.

### Task 4: Implement the M01 Local capture pilot

**Files:**

- Create: `eval/public/fixtures/wmbs-m01-development.json`
- Modify: `src/mnemosyne/cli.py`
- Modify: `eval/harness/cli_driver.py`
- Modify: `eval/public/adapters/whole_memory_reference.py`
- Modify: `eval/public/scoring.py`
- Modify: `tests/test_public_eval_cli.py`
- Modify: `tests/test_public_whole_memory_reference.py`

**Interfaces:**

- Permit each `capture-batch` row to carry validated `public_metadata` with
  `event_id`, `event_time`, and `ingestion_time`.
- Map returned CIDs to ordered `accepted`, `deduplicated`, and `rejected`
  receipts without exposing private storage.
- Canonical replay projection excludes runtime timestamps and host paths.

- [ ] Write RED CLI tests for metadata acceptance/preservation, unknown-key
      rejection, duplicate idempotency, malformed records, and atomic failure.
- [ ] Add only the narrow metadata pass-through. Do not widen arbitrary
      metadata or add SQLite support.
- [ ] Run the focused CLI contract:
      `PYTHONPATH=src uv run --extra mcp pytest -q
      tests/test_public_eval_cli.py -k capture_batch`.
- [ ] Generate a bounded deterministic fixture containing mixed events, 5%
      exact duplicates, 5% near duplicates, malformed rows, stable event IDs,
      and restart boundaries. Pin generator version/seed and fixture digest.
- [ ] Score zero acknowledged loss, zero exact duplicate materialization,
      schema outcomes, provenance retention, and canonical replay equality.
- [ ] Unit-check the scorer against five golden payloads plus one
      reopen/export fixture. These are unscored contract tests, not an admitted
      benchmark execution.
- [ ] Defer every measured suite run, bundle verification, and reproduction to
      Task 11 after the pre-run admission record is frozen.

**Acceptance evidence:**

- `M-DEDUP-EXACT=1.0`, zero acknowledged loss, exact provenance-field
  retention.
- Five canonical payload digests plus the clean-process replay digest.
- External resource receipt within the proposed Local L16-DEV ceiling.

**Deferral:** SQLite, PostgreSQL/P32, and process-kill crash durability remain
`DEFERRED`. If metadata cannot cross the public CLI without weakening
validation, M01 remains `PROPOSED`.

### Task 5: Implement only the honest M03 valid-time development slice

**Files:**

- Create: `eval/public/fixtures/wmbs-m03-valid-time-development.json`
- Modify: `src/mnemosyne/cli.py`
- Modify: `eval/harness/cli_driver.py`
- Modify: `eval/public/adapters/whole_memory_reference.py`
- Modify: `eval/public/scoring.py`
- Modify: `tests/test_public_whole_memory_reference.py`
- Modify: `tests/test_cli_runtime_tools.py`

**Interfaces:**

- Add public, timezone-aware `valid_from` input to assertion/supersession
  operations and the matching `MnemoCLI` wrapper.
- Use existing `graph-as-of`/engine `as_of` only for valid-time questions.
- Do not expose or inspect internal validity tables.

- [ ] Write RED tests for aware/naive timestamps, ordered/late events,
      retroactive corrections, exact boundaries, tied valid times, current
      answers, and historical answers.
- [ ] Add the minimum public valid-time argument and thread it through the
      existing shared write path.
- [ ] Run the focused CLI/runtime contract:
      `PYTHONPATH=src uv run --extra mcp pytest -q
      tests/test_cli_runtime_tools.py -k 'graph_as_of or supersede'`.
- [ ] Build five bounded timelines across at least five seeds, with exact
      virtual-clock, event, and query order.
- [ ] Score `M-ASOF-ACC=1.0`, zero stale-current leakage, and exact tie-policy
      replay for the valid-time slice.
- [ ] Unit-check the same observable queries through the CLI-only adapter; no
      direct engine import in the scorer and no measured suite execution before
      Task 11.
- [ ] Label the suite `wmbs-m03-valid-time-development`, not “full bitemporal.”

**Acceptance evidence:** Golden valid-time vectors, exact current/history
scores, five-seed canonical replay, and an explicit unsupported disclosure for
transaction-time queries.

**Deferral:** Current `as_of` behavior does not accept a separate
`transaction_time`. Full M03 remains `DEFERRED` until a public
`query_as_of(valid_time, transaction_time)` contract and implementation exist.
Do not broaden this pilot to implement that product feature without a separate
approved goal.

### Task 6: Implement the M10 deterministic abstention pilot

**Files:**

- Create: `eval/public/fixtures/wmbs-m10-development.json`
- Modify: `eval/public/adapters/whole_memory_reference.py`
- Modify: `eval/public/scoring.py`
- Modify: `tests/test_public_whole_memory_reference.py`

**Interfaces:**

- Harness-owned deterministic reader consumes only `RetrievalEnvelope` and
  returns `AnswerEnvelope`.
- `normal` mode may abstain; `forced` mode must answer and is diagnostic.
- Numeric confidence is optional and never synthesized when the SUT omits it.

- [ ] Write RED tests for answerable, unanswerable, contradictory,
      distribution-shifted, and adversarial cases.
- [ ] Split generator seeds before scoring into a threshold-calibration
      partition and a disjoint scored partition; bind both split manifests and
      prove no event/question digest appears in both.
- [ ] Prove an always-abstain adapter cannot pass the useful-coverage gate.
- [ ] Implement the smallest deterministic reader and exact scorer for
      assertion accuracy, abstention precision/recall, risk coverage, useful
      coverage, and Brier/ECE only when confidence exists.
- [ ] Implement exact no-memory, full-context, canonical BM25, and canonical
      vector baseline entries through the same reader, budget, metering, and
      scorer. Freeze their complete `BaselineManifest` and the useful-coverage
      floor on the calibration partition before exposing scored cases or
      submitted-system outputs.
- [ ] Generate at least five seeds and unit-check normal/forced golden outputs
      separately; measured execution waits for Task 11 admission.
- [ ] Treat finite-corpus intervals as descriptive full-corpus evidence; do not
      claim population inference.

**Acceptance evidence:** Zero confident assertions on canonical
unanswerables, `M-ECE <= 0.05` when confidence exists, disjoint split digests,
reproduced applicable baselines, the frozen useful-coverage gate, five-run
evidence, and explicit `unsupported` numeric calibration when confidence is
absent.

**Deferral:** No LLM judge, paid provider, model-backed QA, or official
retrieval benchmark is in scope. If a useful-coverage floor cannot be
calibrated from disjoint baseline runs without looking at entrant results, or
any applicable baseline is absent, M10 stays `PROPOSED`.

### Task 7: Capture M12 development evidence without upgrading its claim

**Files:**

- Modify only if a test exposes a real shared-path defect:
  `eval/public/action_cli.py`
- Modify only if needed for accurate metadata:
  `eval/public/adapters/pm_bench_triggerbench.py`
- Modify: `tests/test_public_pm_bench_triggerbench.py`
- Modify: `eval/public/README.md`

- [ ] Re-run the existing PM-Bench and TriggerBench development tests unchanged
      before editing.
- [ ] Verify schedule/update/cancel/tick request fields, virtual time, and
      idempotent test-sink behavior that the current code actually exposes.
- [ ] Unit-check the existing adapter/fixture contracts. Defer isolated
      measured runs and reproduction of `pm-bench-development` and
      `triggerbench-development` to Task 11.
- [ ] Record the exact fixture counts, steps, unsupported recurrence field,
      baseline absence, and missing lateness/cost coverage.
- [ ] Do not add a synthetic recurrence implementation merely to pass the
      benchmark.

**Acceptance evidence:** Existing unit contracts remain green and a gap
disclosure names the exact limited fixture sizes and unsupported fields. After
Task 11 produces admitted receipts, `evidence_level` may remain
`INTERNALLY_MEASURED`; `admission_state` remains `PROPOSED`.

**Deferral:** M12 cannot become `PILOT-READY-DEV` until recurrence is forwarded
through `ActionCLI`, at least five virtual-week seeds exist, the idempotent sink
is proven, and absolute F1/recall plus baseline non-inferiority are calibrated.
Official PM-Bench/TriggerBench names also require upstream pins and rights.

### Task 8: Capture M13 development evidence without upgrading its claim

**Files:**

- Modify only if a test exposes a real shared-path defect:
  `eval/public/adapters/working_memory_action_probe.py`
- Modify: `tests/test_public_working_memory_action_probe.py`
- Modify: `eval/public/README.md`

- [ ] Re-run the existing working-memory action tests unchanged before editing.
- [ ] Verify session/tenant isolation, expiry, bounded capacity, and the
      existing prohibition on automatic promotion.
- [ ] Unit-check the existing adapter/fixture contract. Defer the isolated
      measured run and reproduction of `working-memory-action-development` to
      Task 11.
- [ ] Record the current seed count, capacity setting, case count, and absence
      of a promotion-versus-no-promotion control.
- [ ] Do not infer promotion utility from “automatic promotion blocked.”

**Acceptance evidence:** Green unit contract plus explicit gap disclosure.
After Task 11 produces an admitted reproducible bundle, record zero observed
scope leakage and exact expiry only for the declared fixture;
`evidence_level=INTERNALLY_MEASURED` and `admission_state=PROPOSED`.

**Deferral:** M13 cannot become `PILOT-READY-DEV` until at least five seeds,
three capacities, active-recall/capacity floors, and an explicit promotion
control are frozen and measured.

### Task 9: Enforce M15 canonical replay across all pilot payloads

**Files:**

- Modify: `eval/public/bundle.py`
- Modify: `eval/public/adapters/whole_memory_reference.py`
- Modify: `tests/test_public_whole_memory_reference.py`
- Modify: `tests/test_public_eval.py`

- [ ] Define the canonical projection: ABI schema, fixture/generator,
      candidate/config/build/judge data, metrics, traces, manifests, and
      deterministic SUT outputs.
- [ ] Explicitly exclude volatile timestamps, signatures, host paths, wall/RSS
      samples, and runtime-generated receipt IDs from byte equality while
      retaining them in the bundle.
- [ ] Write RED tests for missing seed/manifest data, unstable ordering,
      float/non-finite values, locale/timezone drift, and one-byte tampering.
- [ ] Add one composed cassette, without duplicating fixture data: ingest the
      M01 duplicates, apply an M03 valid-time correction, ask current,
      historical, answerable, and unanswerable M10 questions, then replay the
      exact sequence. Require dedup, current/history, abstention, and canonical
      replay gates to pass together.
- [ ] Unit-check each deterministic suite projection against five golden
      payloads plus one new-process-shaped fixture. Actual five-run and
      `reproduce_bundle` execution waits for Task 11 admission.
- [ ] Require exact canonical payload equality; stochastic metrics require all
      seed outputs and frozen tolerances rather than byte equality.

**Acceptance evidence:** A six-run digest table per admitted suite, exact
canonical equality, complete seed records, negative tamper/missing-manifest
tests, and the joint M01/M03/M10 cassette proving that no constituent rail is
averaged away.

**Deferral:** Any suite lacking a complete manifest, seed record, canonical
projection, or clean-process reproduction remains non-publishable and cannot
earn M15.

### Task 10: Complete local result-v2 without mutating result-v1

**Files:**

- Modify only to resolve reviewed contract defects:
  `leaderboard/schema/result-v2.schema.json` (created and frozen in Task 1)
- Modify: `leaderboard/validate.py`
- Modify: `leaderboard/ledger.py`
- Modify: `leaderboard/render.py`
- Modify: `leaderboard/publish.py`
- Modify: `leaderboard/readiness.py`
- Modify: `eval/provider_bakeoff/README.md`
- Modify: `tests/test_leaderboard_result_contract.py`
- Modify: `tests/test_leaderboard_ledger.py`
- Modify: `tests/test_leaderboard_render.py`
- Modify: `tests/test_leaderboard_publish.py`

**Interfaces:**

- Version-dispatch validation; `result-v1` behavior is byte-for-byte
  unchanged.
- Result-v2 adds module identity, separate `admission_state` and
  `evidence_level`, track kind and lineage, atomic system/adapter/benchmark/
  backend/hardware/model/split/run/attempt identity, division,
  native/emulated/unsupported disclosures, safety gates,
  run/profile/resources, seeds/retries/aborts, custody/exposure and signer-role
  labels, generic `trace_id`, and complete digest bindings.
- Atomic result rows contain only attempt-level outcomes. Any aggregate or
  comparison is a derived projection that declares source record IDs, filters,
  compatibility key, exclusions, metric version/unit, weighting,
  numerator/denominator, uncertainty method, and missing/unsupported counts.
  Official and enhanced records are never members of one certified
  projection.
- Preserve meanings:
  `build_fingerprint = sha256(build.json)`,
  `config_digest = sha256(config.json)`,
  `bundle_digest = sha256(bundle-manifest.json)`,
  `trace_index_digest = sha256(traces.jsonl)`.

- [ ] Snapshot the current v1 validator/ledger golden cases and prove they are
      unchanged before adding v2.
- [ ] Complete the RED v2 tests frozen in Task 1 for each required field,
      closed admission/evidence enums, disclosure values, safety-gate failure,
      resource-unverified handling, signer-role distinctions, and all four
      digest mismatches.
- [ ] Add explicit schema-version dispatch. Never loosen the v1 schema.
- [ ] Reject duplicate atomic identity keys and reject cross-attempt aggregate
      fields in signed result rows.
- [ ] Add projection tests for side-by-side system/backend filters,
      confidence intervals, and cost/latency/peak-RSS/hardware groupings.
      User-selected averages must disclose their exact records and formula,
      remain exploratory, and reject incompatible track/scorer/division/
      metric/resource semantics.
- [ ] Prove a safety-gate failure remains visible and non-averageable through
      every supported projection; missing, unsupported, failed, aborted, and
      not-measured remain distinct.
- [ ] Verify build, config, bundle, and trace-index payloads before render or
      publish.
- [ ] Add cross-version supersession tests: append a linked v2 successor after
      a v1 entry; never rewrite or resign the v1 bytes.
- [ ] Keep mixed v1/v2 rendering blocked until both schema-specific renderers
      and supersession rules pass.
- [ ] Keep every development result `publishable:false`,
      `pbpp_headline_eligible:false`, and human-gated.
- [ ] Reconcile `eval/provider_bakeoff/README.md` with the controlling PBPP:
      independent reproduction strengthens an operator-run public result but
      is not a prerequisite unless the claim uses `independent`, `neutral`, or
      `certified`.

**Acceptance evidence:** 100% valid fixture acceptance, 100% invalid fixture
rejection, exact four-digest verification, immutable historical v1 ledger
bytes, unique atomic identities, official/successor lineage enforcement,
reproducible projection fixtures, non-averageable safety-failure fixtures, and
fail-closed readiness/publication tests.

**Deferral:** If current renderer/publisher semantics cannot represent v2
without weakening v1, land validator/ledger support only and keep rendering
`DEFERRED`. Without identity-bound signing, transparency inclusion, trust-root
rotation/revocation, and offline verification, M20 cannot exceed
`admission_state=CONTRACT-READY`; local Ed25519 integrity does not prove
neutrality. No website or hosted publication belongs in this plan.

### Task 11: Produce measured L16-DEV feasibility receipts

**Files:**

- Create under the future exact evidence lease:
  `eval/public/receipts/wmbs-pilot-evidence-index-v1.json`
- Create in the content-addressed run staging area: preregistration,
  feasibility record, baseline manifest, power plan, software/data BOM,
  privacy/rights report, build provenance, sandbox/resource receipt, and
  reproduced bundle per suite.
- Modify: `eval/public/README.md` with commands and state labels.

- [ ] Before any scored run, generate, validate, digest, and locally sign the
      preregistration, exact adapter/fixture/scorer contracts, disjoint splits,
      baseline manifests, power plans, SBOM/rights/privacy reports, build
      provenance, sandbox profile, and result contract for every suite.
- [ ] Run only an explicitly unscored no-op/representative resource smoke to
      prove the sandbox and proposed ceiling. Use it to complete the pre-run
      resource receipt; if it fails, do not execute a scored suite.
- [ ] Validate all fourteen design §4.1 fields and freeze the resulting
      admission digest before exposing scored cases or submitted-system
      outputs.
- [ ] Pass the exact hardware preflight: three samples 15 seconds apart, at
      least 55% free memory, host load within 7.0/8.0, no resident model, and no
      concurrent benchmark/index/test/pull/evidence capture.
- [ ] Run one suite/process/worker at a time. Do not overlap tests and measured
      pilot runs.
- [ ] After admission, execute every scored/reproduced SUT run through the
      sandbox-bound execution profile:

```sh
uv run --locked mneme eval-public \
  --execution-profile wmbs-l16-dev \
  --suite SUITE \
  --out-dir SOURCE
uv run --locked mneme eval-public --verify-bundle SOURCE
uv run --locked mneme eval-public \
  --execution-profile wmbs-l16-dev \
  --reproduce-bundle SOURCE \
  --out-dir REPRODUCED
```

- [ ] Use these exact `SUITE` values:
      `wmbs-m01-development`, `wmbs-m03-valid-time-development`,
      `wmbs-m10-development`, `pm-bench-development`,
      `triggerbench-development`, and
      `working-memory-action-development`, plus
      `wmbs-m20-development` for local result-v2/ledger conformance.
- [ ] Compare measured results to the proposed ceilings, but report actual
      values and aborts rather than editing a timeout to make a run pass.
- [ ] Keep raw/sensitive run output outside tracked source. Under the explicit
      evidence lease, land only the redacted content-addressed evidence index
      that binds receipt/bundle digests, source commit, profile, admission
      state, and evidence level. If that index cannot be landed, committed
      states remain `PROPOSED` or `CONTRACT-READY`.

**Acceptance evidence:** Valid feasibility and resource receipts for the exact
host/profile, schema and artifact hashes, successful verify/reproduce commands,
an immutable redacted evidence index, and honest separate `admission_state` and
`evidence_level` per module.

**Deferral:** A failed hardware gate, sandbox gate, meter gap, exceeded
resource ceiling, missing BOM/right, or reproduction mismatch keeps that
module `PROPOSED` or `DEFERRED`. It is not permission to raise a limit.

### Task 12: Run the exact review gates and prepare a local-only commit

**Files:**

- All files changed by Tasks 1–11, within the future exact lease.
- Update the future `GOAL.md` receipt only if that lease explicitly owns it.

- [ ] Run focused tests:

```sh
PYTHONPATH=src uv run --extra mcp pytest -q \
  tests/test_public_whole_memory_reference.py \
  tests/test_public_pm_bench_triggerbench.py \
  tests/test_public_working_memory_action_probe.py
PYTHONPATH=src uv run --extra mcp pytest -q \
  tests/test_public_eval.py \
  tests/test_public_eval_cli.py \
  tests/test_public_eval_scoring.py
PYTHONPATH=src uv run --extra mcp pytest -q \
  tests/test_cli_runtime_tools.py -k 'graph_as_of or supersede'
PYTHONPATH=src uv run --extra mcp pytest -q \
  tests/test_leaderboard_result_contract.py \
  tests/test_leaderboard_ledger.py \
  tests/test_leaderboard_render.py \
  tests/test_leaderboard_publish.py
```

- [ ] Run Ruff on every changed Python file and the repository's normal
      documentation/reference checker.
- [ ] Run a clean-tree source-to-test trace review for every requirement in
      the target evidence table.
- [ ] Independently review trust boundaries, statistical claims, result-v1
      compatibility, official-name usage, rights/privacy BOM, and every
      `PILOT-READY-DEV` assertion.
- [ ] Inspect `git diff --check`, changed-file scope, risky files, secrets, and
      generated artifacts before staging named paths.
- [ ] Create a local commit only after every claimed receipt is present.
      Do not push or open a pull request without a new explicit instruction.

**Completion rule:** The work is complete only when the implementation and
receipts support the exact states reported. It is also a valid outcome for
M03, M12, or M13 to remain deferred after their honest development evidence.
No result, ranking, certification, launch-readiness statement, or superiority
claim is part of this plan.

## Explicitly out of scope

- Official or held-out entrants and external adapter certification.
- M02, M04–M09, M11, M14, and M16–M19 implementation.
- Paid/model-backed QA, LLM judging, provider bakeoffs, or UQC/ranking.
- PostgreSQL/P32 crash, replica, object-store, PITR, or custody certification.
- Full transaction-time bitemporal product implementation.
- M12 recurrence product work or M13 promotion-policy product work beyond a
  separately approved goal.
- Website design, hosted publication, GitHub push/PR, or governance activation.
- Detailed website UI, interaction design, ranking layout, and hosting. The
  backend result/projection contract is in scope only so a later website can
  render side-by-side systems, transparent filters/averages, intervals, and
  resource views without changing evidence.
- Any “best,” “whole-system certified,” neutral, independent, industry
  standard, launch-ready, or production-ready claim.
