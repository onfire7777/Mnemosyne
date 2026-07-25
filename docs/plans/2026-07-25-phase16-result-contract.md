# Phase 16 L2 Public Result Contract Implementation Plan

> **For agentic workers:** Execute task-by-task with Ponytail, strict TDD, and
> the configured native RalphEx/Codex review stages. Do not widen the lease.

**Goal:** Add a versioned, fail-closed public leaderboard result contract and
deterministic validator without producing or publishing a benchmark result.

**Architecture:** Keep the contract in `leaderboard/schema/` and implement one
standard-library validator in `leaderboard/validate.py`. The validator loads
JSON, validates structural and cross-field invariants, emits stable JSON-pointer
errors, and exposes `python leaderboard/validate.py RECORD.json`. Tests use only
synthetic fixtures and the public API.

**Tech Stack:** Python standard library, JSON Schema as a checked-in data
contract, pytest, Ruff.

## Global Constraints

- `GOAL.md` and every controlling source it names are binding.
- Exact write lease: `leaderboard/schema/**`, `leaderboard/validate.py`,
  `leaderboard/__init__.py`, `tests/test_leaderboard_result_contract.py`, and
  this plan/progress metadata only.
- Use no new dependency and no network, protected-environment, production,
  external-custody, benchmark, or hardware access.
- Do not update `.planning/` or canonical governance status unless verified
  implementation evidence changes their truth.
- Plan/task/review model: `gpt-5.6-sol:low`; native Codex executor; no external
  review binding; no Hermes.

---

### Task 1: Define the versioned result schema from executable examples

**Files:**
- Create: `leaderboard/__init__.py`
- Create: `leaderboard/schema/result-v1.schema.json`
- Create: `tests/test_leaderboard_result_contract.py`

**Interfaces:**
- Consumes: the retained bundle conventions in `eval/public/bundle.py`.
- Produces: schema identifier `mnemosyne.leaderboard.result/v1` and test fixture
  builders local to the test module.

- [ ] **Step 1: Write failing tests for the two accepted records**

Create literal synthetic deterministic-retrieval and disclosed-judge records.
Add tests named
`test_accepts_minimal_deterministic_retrieval_record` and
`test_accepts_minimal_disclosed_judged_qa_record` that call
`validate_record(record)` and expect an empty error list. The import must fail
because `leaderboard.validate` does not exist yet.

- [ ] **Step 2: Run RED and verify the missing validator is the cause**

Run:

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
```

Expected: collection fails on missing `leaderboard.validate`, not fixture syntax.

- [ ] **Step 3: Add the minimal schema contract**

The checked-in schema must require literal, non-empty fields for:
`schema_version`, `record_id`, `system`, `track`, `benchmark`,
`benchmark_version`, `run_commit`, `build_fingerprint`, `config_digest`,
`bundle_digest`, `trace_index_digest`, `metrics`, `publication`,
`operator_entry`, and `history`. Each metric must declare exactly one family
(`retrieval` or `judged_qa`), a numeric value, unit, and confidence interval.
Judged metrics must carry judge model, prompt digest, and config digest.

- [ ] **Step 4: Add only enough validator surface to make accepted examples green**

Create:

```python
def validate_record(record: object) -> list[str]:
    """Return stable JSON-pointer errors; an empty list means valid."""
```

Use explicit standard-library type and presence checks. Do not build a generic
schema engine.

- [ ] **Step 5: Run GREEN**

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
```

Expected: both accepted-record tests pass.

### Task 2: Enforce publication and history invariants fail closed

**Files:**
- Modify: `leaderboard/validate.py`
- Modify: `tests/test_leaderboard_result_contract.py`

**Interfaces:**
- Consumes: `validate_record(record: object) -> list[str]`.
- Produces: deterministic, sorted JSON-pointer errors and process exit status.

- [ ] **Step 1: Add one failing table-driven test per prohibited mutation**

Use literal mutations and expected error pointers for:

- missing bundle or trace provenance;
- retrieval and judged-QA metrics mixed in one record;
- judged-QA without complete judge disclosure;
- unpinned commit or non-`sha256:` fingerprints/digests;
- `development` evidence marked `publishable: true`;
- a replacement record that omits `supersedes`, or a superseded record without
  a new `record_id`;
- operator entry disclosure missing;
- use of the `neutral` label without an explicit satisfied Register B field.

Name each parametrized case after the production mutation it catches. Run the
focused test and verify every case fails because validation is absent.

- [ ] **Step 2: Implement the minimal cross-field checks**

Add small private functions only where one invariant becomes clearer. Sort and
deduplicate errors before return. Never infer missing evidence, default
publishability to true, or rewrite input.

- [ ] **Step 3: Add the deterministic CLI**

Implement:

```python
def main(argv: list[str] | None = None) -> int:
    """Validate one record or an array; print errors to stderr; return 0/1/2."""
```

Return `0` for valid input, `1` for contract violations, and `2` for unreadable
or invalid JSON. Accept no network URL and write no file.

- [ ] **Step 4: Verify GREEN and CLI behavior**

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
uv run python leaderboard/validate.py tests/fixtures/does-not-exist.json
```

Expected: tests pass; missing-file command exits `2` with a stable error and no
traceback.

### Task 3: Verify the exact lease and review the implementation

**Files:**
- Modify only files already named by this plan if a verified finding requires it.

- [ ] **Step 1: Run the scoped acceptance matrix**

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
uv run ruff check leaderboard tests/test_leaderboard_result_contract.py
git diff --check
```

- [ ] **Step 2: Confirm no protected or hardware evidence was touched**

Inspect `git status --short` and `git diff --name-only` against the plan base.
The changed-file set must be a subset of the exact lease. No evidence bundle,
benchmark output, `.planning` status, governance status, deployment file, or
hardware artifact may appear.

- [ ] **Step 3: Run native review stages and resolve confirmed findings**

Use the configured `gpt-5.6-sol:low` first and second review phases. For a
confirmed logic defect, add a failing regression test before the fix. Do not
invoke an external review bot.

- [ ] **Step 4: Commit the coherent package**

Stage explicit paths only and create an atomic conventional commit after the
acceptance matrix and review are green.

