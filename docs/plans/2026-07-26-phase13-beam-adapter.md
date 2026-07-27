# Phase 13 BEAM Reader and Judge Configuration Plan

**Goal:** Extend the merged source-only BEAM disclosure adapter with a
deterministic reader-and-judge configuration contract that follows the existing
public QA metadata conventions.

## Constraints

- Exact lease: `GOAL.md`, `eval/public/adapters/beam.py`,
  `tests/test_public_beam.py`, and this plan.
- No new dependency and no parallel bundle/config schema.
- No dataset, reader, judge, protected production, publication, or hardware run.
- Plan/task/review use `gpt-5.6-sol:low`; external review is `none`.
- TDD is mandatory.

## Task 1 — Freeze behavior

- [x] Inspected the shared public QA conventions: reader custody uses
  `name`/`provider`/`selector`/`model_revision` plus a raw lowercase
  `model_content_sha256`; judged QA binds the judge model, prompt digest, and
  config digest.
- [x] Froze `build_reader_judge_config(reader, judge)` as the smallest reusable
  interface. It returns exactly `schema_version`, `reader`, and `judge`;
  preserves the existing metadata names; and includes canonical nested
  `config`/`prompt` values with matching raw lowercase SHA-256 fields.
- [x] Added RED coverage for canonical ordering and detachment, exact keys,
  canonical strings, pinned model revisions, matching digests, booleans, and
  non-finite nested values.

RED receipt: `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q
tests/test_public_beam.py` produced 13 expected failures and 23 passing tests;
every failure is the missing `build_reader_judge_config` implementation held
for Task 2. The planned `.venv/bin/python` path is absent in this worktree.

## Task 2 — Implement

- Reuse shared validation/canonicalization where it already exists.
- Add only the minimum BEAM-specific source contract.
- Keep the builder deterministic, detached, and free of I/O or execution.

## Task 3 — Verify and deliver

- Run focused and unrestricted full tests, full Ruff, native review, and all
  lease/diff/secret/risky-file checks.
- Commit and push deliberately, open the normal PR, and require fresh exact-head
  CI, CodeRabbit, Greptile, clear review state, and zero active threads.
- Merge normally only after every gate clears; verify post-merge main CI.
