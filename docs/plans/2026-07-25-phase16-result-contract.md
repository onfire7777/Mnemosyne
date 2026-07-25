# Phase 16 L2 Public Result Contract Implementation Plan

> **For agentic workers:** Execute task-by-task with Ponytail, strict TDD, and
> the configured native RalphEx/Codex review stages. Use CBM as the primary
> code-discovery surface, Gbrain for durable milestone knowledge, and
> context-mode for retained command/log/document captures and derivation.
> Restrict text search to precise literals/config/errors or an identified graph
> gap, and keep only derived findings active. Do not widen the lease.

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
- Exact write lease: `GOAL.md`, `leaderboard/schema/**`,
  `leaderboard/validate.py`, `leaderboard/__init__.py`,
  `tests/test_leaderboard_result_contract.py`, and this plan/progress metadata
  only.
- Use no new dependency and no product/runtime network, protected-environment,
  production, external-custody, benchmark, or hardware access. GitHub branch,
  pull-request, review, and CI delivery operations are allowed.
- Do not update `.planning/` or canonical governance status unless verified
  implementation evidence changes their truth.
- Plan/task/review model: `gpt-5.6-sol:low`; native Codex executor; no external
  review binding; no Hermes.
- Work only on `codex/phase16-result-contract` in its Worktrunk checkout.
  Never direct-push `main`, force-push, bypass hooks/checks, or merge unresolved
  failures.

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

- [x] **Step 1: Write failing tests for the two accepted records**

Create literal synthetic deterministic-retrieval and disclosed-judge records.
Add tests named
`test_accepts_minimal_deterministic_retrieval_record` and
`test_accepts_minimal_disclosed_judged_qa_record` that call
`validate_record(record)` and expect an empty error list. The import must fail
because `leaderboard.validate` does not exist yet.

- [x] **Step 2: Run RED and verify the missing validator is the cause**

Run:

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
```

Expected: collection fails on missing `leaderboard.validate`, not fixture syntax.

- [x] **Step 3: Add the minimal schema contract**

The checked-in schema must require literal, non-empty fields for:
`schema_version`, `record_id`, `system`, `track`, `benchmark`,
`benchmark_version`, `run_commit`, `build_fingerprint`, `config_digest`,
`bundle_digest`, `trace_index_digest`, `metrics`, `publication`,
`operator_entry`, and `history`. Each metric must declare exactly one family
(`retrieval` or `judged_qa`), a numeric value, unit, and confidence interval.
Judged metrics must carry judge model, prompt digest, and config digest.

- [x] **Step 4: Add only enough validator surface to make accepted examples green**

Create:

```python
def validate_record(record: object) -> list[str]:
    """Return stable JSON-pointer errors; an empty list means valid."""
```

Use explicit standard-library type and presence checks. Do not build a generic
schema engine.

- [x] **Step 5: Run GREEN**

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

- [x] **Step 1: Add one failing table-driven test per prohibited mutation**

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

- [x] **Step 2: Implement the minimal cross-field checks**

Add small private functions only where one invariant becomes clearer. Sort and
deduplicate errors before return. Never infer missing evidence, default
publishability to true, or rewrite input.

- [x] **Step 3: Add the deterministic CLI**

Implement:

```python
def main(argv: list[str] | None = None) -> int:
    """Validate one record or an array; print errors to stderr; return 0/1/2."""
```

Return `0` for valid input, `1` for contract violations, and `2` for unreadable
or invalid JSON. Accept no network URL and write no file.

- [x] **Step 4: Verify GREEN and CLI behavior**

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
uv run python leaderboard/validate.py tests/fixtures/does-not-exist.json
```

Expected: tests pass; missing-file command exits `2` with a stable error and no
traceback.

### Task 3: Verify the exact lease and review the implementation

**Files:**
- Modify only files already named by this plan if a verified finding requires it.

- [x] **Step 1: Run the scoped acceptance matrix**

```sh
uv run pytest -q tests/test_leaderboard_result_contract.py
uv run ruff check leaderboard tests/test_leaderboard_result_contract.py
git diff --check
```

- [x] **Step 2: Confirm no protected or hardware evidence was touched**

Inspect `git status --short` and `git diff --name-only` against the plan base.
The changed-file set must be a subset of the exact lease. No evidence bundle,
benchmark output, `.planning` status, governance status, deployment file, or
hardware artifact may appear.

- [x] **Step 3: Run native review stages and resolve confirmed findings**

Use the configured `gpt-5.6-sol:low` first and second review phases. For a
confirmed logic defect, add a failing regression test before the fix. Do not
invoke an external review bot.

Deferred to the enclosing native RalphEx review lifecycle after task completion;
recursively starting another loop from the active task phase is not automatable
or safe.

- [x] **Step 4: Commit the coherent package**

Stage explicit paths only and create an atomic conventional commit after the
acceptance matrix and review are green.

- [x] **Step 5: Push the isolated branch and open or update its pull request**

Recheck the complete branch diff plus secret/risky-file surface, then push
`codex/phase16-result-contract` normally and open or update its pull request.
Do not modify `main` directly.

- [x] **Step 6: Resolve exact-head delivery findings**

Monitor the pull request's exact head for required CI and review. Reproduce any
confirmed failure, add a focused regression test for logic defects, commit and
push the narrow fix, and wait for the new exact-head gates. Leave merge and
post-merge `main` verification to supervision once every required gate is green
and GitHub reports the pull request mergeable.

### Task 4: Resolve confirmed exact-head review findings

**Files:**
- Modify: `leaderboard/schema/result-v1.schema.json`
- Modify: `leaderboard/validate.py`
- Modify: `tests/test_leaderboard_result_contract.py`
- Modify: `GOAL.md`
- Modify: this plan

- [x] **Step 1: Add failing boundary tests**

Add focused tests proving the validator rejects non-finite values, JSON
`NaN`/`Infinity` constants and overflowed numbers, and confidence intervals
whose `low` bound exceeds `high`. Verify RED for the missing behavior.

- [x] **Step 2: Align the published schema and validator**

Make the checked-in schema enforce the validator's immutable commit/digest,
required publication/operator/history, and interval constraints. Use finite
numeric validation at both the untrusted JSON parser and validator boundary,
and reject inverted intervals. Keep the implementation standard-library only.

- [x] **Step 3: Re-run the local acceptance and risk gates**

Run the focused tests, Ruff, JSON parsing, diff checks, exact-lease check, and
secret/risky-file sweep. Resolve only confirmed review findings; do not widen
the product scope.

- [x] **Step 4: Commit, push, and recheck the successor head**

Commit the narrow review fix, push the existing isolated branch normally, and
monitor PR #65 on the new exact head. Do not merge while review is
changes-requested or any required check is pending or failing.
