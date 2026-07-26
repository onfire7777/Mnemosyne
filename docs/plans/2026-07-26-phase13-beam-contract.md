# Phase 13 BEAM Reader Disclosure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add a deterministic source-only BEAM reader disclosure envelope that
reuses the existing public candidate-manifest validation boundary.

**Architecture:** Add one adapter module that validates BEAM-specific revision
metadata, delegates candidate validation to `eval.public.runner`, and emits a
fixed canonical mapping. Keep execution, datasets, models, judges, I/O, CLI
wiring, measurements, and publication out of scope.

**Tech Stack:** Python standard library, existing public harness, pytest, Ruff.

## Global Constraints

- Exact lease: `GOAL.md`, `eval/public/adapters/beam.py`,
  `tests/test_public_beam.py`, and this plan.
- No new dependency or duplicated candidate-manifest validation.
- No BEAM dataset, reader, judge, production, protected, or hardware run.
- Plan/task/review use `gpt-5.6-sol:low`; external review is `none`.
- TDD is mandatory: observe RED before production code.

---

### Task 1: Freeze the disclosure behavior

**Files:**
- Create: `tests/test_public_beam.py`
- Modify: `GOAL.md`

**Interfaces:**
- Consumes: `eval.public.runner.build_candidate_manifest` for valid fixtures.
- Produces: expected public API
  `build_disclosure(candidate_manifest, *, dataset_revision, protocol_id)`.

- [x] Write tests that require the exact top-level order
  `schema_version`, `dataset_revision`, `protocol_id`, `candidate_manifest`.
- [x] Prove equivalent candidate mappings yield identical envelopes.
- [x] Prove invalid revision, whitespace-bearing protocol, malformed candidate,
  boolean, non-finite, missing, and extra candidate fields fail closed through
  `BeamDisclosureError`.
- [x] Run
  `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_beam.py` and
  confirm failure because the BEAM module/API does not exist. (The prescribed
  command could not resolve `python-multipart` under network isolation; the
  installed runner reproduced the expected collection failure:
  `ModuleNotFoundError: No module named 'eval.public.adapters.beam'`.)
- [x] Commit only the RED test, plan, and task receipt after the supervisor
  repaired the Worktrunk metadata writable-root boundary.

### Task 2: Implement the minimum shared-flow adapter

**Files:**
- Create: `eval/public/adapters/beam.py`
- Modify: `GOAL.md`

**Interfaces:**
- Consumes: public `eval.public.runner.validate_candidate_manifest`.
- Produces:
  `build_disclosure(candidate_manifest: object, *, dataset_revision: object,
  protocol_id: object) -> dict[str, object]`.

- [x] Define `BeamDisclosureError(ValueError)`.
- [x] Validate the exact lowercase 40-hex dataset revision and canonical
  protocol identifier.
- [x] Require a mapping candidate, delegate its semantic validation to
  `validate_candidate_manifest`, translate validation errors to
  `BeamDisclosureError`, and copy candidate keys in sorted order.
- [x] Emit the fixed schema version `beam-reader-disclosure-v1`.
- [x] Run the focused suite and confirm GREEN: the authoritative
  `PYTHONPATH=src uv run --extra mcp pytest -q tests/test_public_beam.py`
  completed with 16 passed, and focused Ruff passed.
- [x] Commit only the implementation and accurate task receipt after the
  supervisor repaired the Worktrunk metadata writable-root boundary.

### Task 3: Verify and deliver

**Files:**
- Modify only leased task/verification receipts if evidence changes.

**Interfaces:**
- Consumes: Tasks 1-2 committed behavior.
- Produces: reviewed branch, normal PR, exact-head gates, normal merge, and
  exact post-merge main verification.

- [ ] Run both native review stages and repair only reproduced in-lease issues.
- [x] Run focused tests, unrestricted
  `uv run --extra mcp pytest -q`, and `uv run ruff check .`. (16 focused tests,
  unrestricted full pytest, and full Ruff passed.)
- [x] Run `git diff --check`, exact-lease, risky-file, and secret checks.
- [ ] Commit deliberately, push normally, and open/update the PR.
- [ ] Require exact-head CI, CodeRabbit, Greptile, clear reviewDecision, and zero
  active non-outdated threads before normal merge.
- [ ] Verify exact post-merge main CI before the next CBM/Gbrain refresh.
