# Phase 16 L2 Signed Run Ledger Implementation Plan

> Canonical execution plan for P16-L2-B. `GOAL.md` and its controlling sources
> are binding.

## Global Constraints

- Exact write lease: `GOAL.md`, `leaderboard/ledger.py`,
  `tests/test_leaderboard_ledger.py`, and this plan only.
- Native RalphEx plan/task/review: `gpt-5.6-sol:low`; external review none;
  Hermes off; maximum 12 rounds.
- Reuse the existing audit-chain, journal, result-validator, and Ed25519
  evidence-signing patterns. Add no dependency.
- Use synthetic fixtures and ephemeral local keys only. Do not access a
  protected environment, production system, external custody surface, public
  benchmark, or physical hardware gate.
- Work only in the Worktrunk checkout
  `/Users/admin/Mnemosyne.codex-phase16-run-ledger` on
  `codex/phase16-run-ledger`.

### Task 1: Specify accepted ledger events with failing tests

**Files:**
- Create: `tests/test_leaderboard_ledger.py`

- [x] Add synthetic fixtures for succeeded, failed, aborted, discarded,
  `no_run`, and superseded entries.
- [x] Add RED tests for canonical JSONL, contiguous sequence/hash links,
  signatures, required reasons, result validation, recorded absence, and
  append-only supersession.
- [x] Add RED tamper tests for mutation, deletion, reorder, duplicate IDs,
  unknown/repeated supersession, invalid result records, and wrong keys.
- [x] Run `uv run pytest -q tests/test_leaderboard_ledger.py` and confirm the
  failure is the missing ledger implementation.

### Task 2: Implement the minimum signed append-only ledger

**Files:**
- Create: `leaderboard/ledger.py`

- [x] Reuse existing canonical hashing and Ed25519 key-loading patterns.
- [x] Implement entry construction/signing, durable append, full-ledger
  verification, and stable fail-closed errors.
- [x] Preserve acknowledged bytes exactly; repair only an unacknowledged torn
  final fragment following the existing journal precedent.
- [x] Add `python -m leaderboard.ledger verify` with deterministic nonzero
  failure behavior; do not add a project script or dependency.
- [x] Run focused tests until GREEN, then run Ruff and `git diff --check`.

### Task 3: Verify and deliver the exact lease

**Files:**
- Modify only files already named by this plan when a verified finding requires
  it.

- [x] Inspect `git diff --name-only` and reject any file outside the lease.
- [x] Inspect the complete diff and secret/risky-file surface.
- [x] Run:

```sh
uv run pytest -q tests/test_leaderboard_ledger.py
uv run ruff check leaderboard/ledger.py tests/test_leaderboard_ledger.py
git diff --check
```

- [x] Run both configured native review stages and resolve confirmed findings
  with a failing regression test before each logic fix.
- [ ] Commit explicit paths, push normally, and open or update the pull request.
- [ ] Monitor exact-head CI/review; merge normally only when every gate is
  green, review is clear, and GitHub reports mergeable.
- [ ] Verify post-merge `main` CI, refresh CBM, sync the coherent Gbrain
  milestone, and select the next dependency-ready package.
