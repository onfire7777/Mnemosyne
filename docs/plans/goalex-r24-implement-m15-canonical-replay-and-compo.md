# Plan: Implement M15 Canonical Replay and Composed Rails

## Overview
Work from clean canonical `main@7f60d8ba8274a8ac8036a80737467654f862008f` in a new isolated Worktrunk branch. Never edit `codex/goalex-whole-memory-pilot`, canonical `main`, `/Users/admin/Mnemosyne.codex-whole-memory-benchmark-spec`, or `/Users/admin/Mnemosyne.codex-phase16-signed-publication`.

Implement only Task 9 of `docs/superpowers/plans/2026-07-28-whole-memory-reference-harness-pilots.md`. PR #81 already delivered M01/M10 development pilots, and PR #83 delivered the bounded valid-time portion of M03. Reuse their fixtures, adapters, scorers, bundle custody, canonical JSON encoding, and public interfaces. Do not create another fixture, runner, registry, evidence store, replay framework, or dependency.

The exact shared-file lease is:

- `eval/public/bundle.py`
- `eval/public/adapters/whole_memory_reference.py`
- `tests/test_public_whole_memory_reference.py`
- `tests/test_public_eval.py`

M15 must fail closed unless every admitted deterministic pilot payload has complete seed and manifest custody and an exact canonical projection. Canonical equality covers ABI schema, fixture/generator custody, configuration, build/judge data, metrics, traces, manifests, and deterministic SUT outputs. Volatile timestamps, signatures, host paths, wall/RSS samples, and runtime-generated receipt IDs remain retained but are excluded from equality by an explicit projection. Reject non-finite floats, unstable ordering, missing custody, locale/timezone drift, and tampering.

Add one composed cassette without copying fixture data: ingest the existing M01 duplicates, apply the existing M03 valid-time correction, then exercise current, historical, answerable, and unanswerable M10 queries. Exact replay must prove deduplication, valid-time history, deterministic answers, abstention, and canonical equality independently; no averaged aggregate may hide a failed constituent rail.

This remains development evidence only: `publishable:false`, `pbpp_headline_eligible:false`, `independent_external_reproduction:false`, and `upstream_comparable:false`. Do not run official suites, measured cells, protected data, paid providers, five real clean-process runs, or Task 11 `reproduce_bundle` admission. No independent post-round findings require adjudication.

## Validation Commands
- `test "$(git rev-parse main)" = "$(git rev-parse origin/main)" && test "$(git rev-parse main)" = "7f60d8ba8274a8ac8036a80737467654f862008f"`
- `test "$(git diff --name-only main...HEAD | sort)" = "$(printf '%s\n' eval/public/adapters/whole_memory_reference.py eval/public/bundle.py tests/test_public_eval.py tests/test_public_whole_memory_reference.py)"`
- `uv run pytest -q tests/test_public_whole_memory_reference.py tests/test_public_eval.py`
- `uv run ruff check eval/public/bundle.py eval/public/adapters/whole_memory_reference.py tests/test_public_whole_memory_reference.py tests/test_public_eval.py`
- `git diff --check`

### Task 1: Establish the isolated exact lease
- [ ] Fetch `origin`, prove canonical `main` is clean and exactly `7f60d8ba`, refresh/index the actual checkout with CBM, and create one isolated Worktrunk branch owning only the four authorized paths.
- [ ] Trace the existing M01, M03, M10, canonical JSON, bundle verification, and reproduction flows before editing; reuse the shared custody and adapter paths.
- [ ] Stop if `main` advanced incompatibly, another writer owns a leased path, or implementation requires registry, fixture, scorer, CLI, result-v2, sandbox, documentation, or publication changes.

### Task 2: Write failing canonical-replay contracts
- [ ] Add RED tests defining the exact canonical projection and proving that allowed volatile-field changes do not alter its digest while deterministic payload changes do.
- [ ] Add RED failures for missing seed or manifest custody, unstable map/list ordering, non-finite floats, locale/timezone-dependent values, one-byte tampering, and unexpected excluded fields.
- [ ] Unit-shape five golden deterministic payloads plus one new-process-shaped payload per admitted suite, recording their projection digests without claiming actual clean-process reproduction.

### Task 3: Implement the minimum fail-closed projection
- [ ] Add one shared canonical projection/digest path in `eval/public/bundle.py`, reusing existing canonical JSON and bundle verification rather than creating a second serializer.
- [ ] Retain volatile evidence in bundles but exclude only the frozen field set from equality; reject ambiguous values, missing custody, unsupported stochastic equality, and non-finite numbers.
- [ ] Thread the projection through the existing whole-memory reference adapter only as needed to produce deterministic replay evidence for M01, bounded M03, and M10.

### Task 4: Add the composed M01→M03→M10 cassette
- [ ] Compose existing fixture data and public adapter operations: exercise M01 duplicate ingestion, M03 valid-time correction/current/history queries, and M10 answerable/unanswerable behavior, then replay the identical sequence.
- [ ] Require separate exact gates for deduplication, current state, historical state, deterministic answer, abstention, complete seeds/manifests, and canonical equality so no aggregate can average away a failure.
- [ ] Preserve the M03 transaction-time deferral and every non-publication, non-headline, non-independent, and non-comparability label.

### Task 5: Verify the candidate without delivering it
- [ ] Run the two focused test files, focused Ruff, and `git diff --check`; do not duplicate exact-head CI or perform Task 11 measured reproduction.
- [ ] Review the complete diff for lease compliance, fail-closed custody, canonicalization ambiguity, trust boundaries, secret-like material, path leakage, dependency churn, and prohibited evidence-language upgrades.
- [ ] Commit the clean candidate and report its exact SHA, test count, six unit-shaped digest records per admitted suite, composed-rail results, and remaining Task 11/operator deferrals. Leave push, PR, review, exact-head CI, merge, post-merge proof, CBM refresh, and durable milestone recording for the next round.
