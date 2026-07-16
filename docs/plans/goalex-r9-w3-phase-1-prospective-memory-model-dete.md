# Plan: W3 Phase 1 — prospective-memory model + deterministic evaluator (Local engine, TDD)

## Overview

You are executing round 9 of the Mnemosyne v2.0 program. The authoritative plan
for this slice is `docs/superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md`
(**Phase 1 only**), governed by the master spec
`docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` (§5, §6, W3).
Read both before writing code. This advances ROADMAP Phase 15 (Memory Capability
and Evidence Closure) toward the future CAP-012 requirement row (the row itself is
added in W3 Phase 4 per the plan doc — do NOT add it now).

State you must respect:
- `main` == `origin/main` at `4eec00f`, clean tree, no open PRs. Never push to
  `main` directly, never force-push, never rewrite shared history.
- The Colima production VM is INTENTIONALLY STOPPED and the production MCP client
  cert is expired below the admission floor. Do not start the VM, touch Vault,
  rotate certs, or run any live/protected/model work. This slice is deterministic,
  local-engine, no-model work at the ≥35% free-memory targeted-test tier.
- W1 graph-substrate local work is DONE (PRs #23–#34); do not redo it. W3 may be
  *built* now but *measured* only after W1 production parity — build only.
- Rails: never weaken any §31 invariant or §33 test class; no new core dependency
  (core allows `cryptography` only); every new write path inherits capability
  checks, TrustTier, tenancy, hash-chained audit, provenance to evidence CIDs,
  and data-only treatment of retrieved content.
- Prior verification: no `Intention` class, no `schedule_intention`/
  `evaluate_due_intentions`/`put_working` anywhere in `src/`; neither
  `tests/test_prospective_memory.py` nor `tests/test_working_memory.py` exists.
  The only scheduling primitive today is the forgetting rehearsal/demotion
  lifecycle in `jobs.py`/`lifecycle.py` — the prospective engine is a NEW,
  distinct deterministic scheduler.
- Repo conventions: TDD (RED before GREEN), small conventional commits (one task
  each), full-diff inspection + secret/risky-file sweep before staging, PR with
  evidence-bearing description, merge only on green exact-head CI for the pushed
  SHA, verify the merged SHA locally, clean up the merged branch, reconcile
  `.planning/` trackers in the same slice.

Scope boundary: Phase 1 is Local engine only. Do NOT implement Postgres/Sqlite
persistence (Phase 2), the working-memory plane (Phase 3), retrieval-route
integration, benchmark adapters, REQUIREMENTS rows, or architecture-doc updates
(Phase 4). If extending the shared `MemoryEngine` Protocol would break the other
engines' contract tests, implement the four methods on the Local engine only and
leave Protocol registration to Phase 2 — note that decision in the PR body.

## Validation Commands
- `set -e; cd "$(git rev-parse --show-toplevel)"; git diff --check; .venv/bin/ruff check --quiet .`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_prospective_memory.py`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_planning_traceability.py tests/test_config_drift.py tests/test_shared_engine_contract.py`
- Full local suite before merge (only if the host clears the ≥35% free-memory tier): `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/`

### Task 1: Preflight and branch
- [x] Confirm clean state: `git status` clean, `main` == `origin/main` (fetch first); confirm no open PRs with `gh pr list --state open`.
- [x] Run the hygiene gate (first validation command) and confirm exit 0 before any edit.
- [x] Take a free-memory sample for the ≥35% targeted-test tier (e.g. via `memory_pressure` / `vm_stat` percentage-free). If below 35%, proceed with code + focused tests only, skip the full-suite run, and record that explicitly in `.planning/STATE.md` in Task 5 — a host-pressure note, not a failure.
- [x] Create branch `codex/w3-p1-prospective-memory` from `origin/main`.

### Task 2: RED — failing prospective-memory tests
- [ ] Read `docs/superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md` Phase 1 and the existing Local engine surface (`src/mnemosyne/engine.py`, audit + evidence-CID patterns used by other write paths) to match conventions.
- [ ] Write `tests/test_prospective_memory.py` asserting, against the Local engine: (a) an `Intention` with an `exact_time` trigger in the past fires exactly once and is marked fired; (b) an unsatisfied (future) trigger does not fire; (c) firing is idempotent under replay — re-running `evaluate_due_intentions` never double-fires; (d) a cancelled intention never fires; (e) each intention carries provenance (`evidence_ids[]`) to its originating episode and each firing writes an audit entry.
- [ ] Run the focused file, confirm it FAILS for the expected reason (missing implementation, not a typo), and commit the tests alone (`test: add RED prospective-memory Phase 1 contract`).

### Task 3: GREEN — Intention model, deterministic evaluator, Local engine methods
- [ ] Implement the `Intention` model with the plan-doc fields: `intention_id`, tenant/user/agent ids, `trigger_type`, `trigger_expression`, `action`, `status`, `priority`, `due_at`, `dependencies[]`, `reschedule_history[]`, `cancellation_state`, `evidence_ids[]`.
- [ ] Implement a deterministic, pure/in-memory evaluator plus Local engine methods `schedule_intention`, `cancel_intention`, `evaluate_due_intentions`, `list_intentions`. Evaluation must be a deterministic function of stored state and an explicitly passed evaluation time (no hidden wall-clock reads inside the evaluator), so replay is idempotent and testable.
- [ ] Route the new write path through the same capability/TrustTier/tenancy checks and hash-chained audit as existing writes; stored `action`/`trigger_expression` content is data only — nothing retrieved is ever executed.
- [ ] Run the focused file to green, run `ruff`, inspect the full diff, run the secret/risky-file sweep, and commit (`feat: add prospective-memory Intention model and deterministic evaluator (Local)`).

### Task 4: Verify and land via PR
- [ ] Run all Validation Commands; run the full local suite only if the ≥35% tier sample from Task 1 admitted it. Confirm no §31/§33 test is modified or weakened by the diff.
- [ ] Push the branch, open a PR titled `feat: W3 Phase 1 — prospective-memory model + deterministic evaluator (Local)` whose body carries the RED/GREEN evidence, test output, tier-sample result, and the Protocol-registration decision from the Overview.
- [ ] Wait for exact-head CI on the pushed SHA; merge only on green; then verify the merged SHA locally, sync local `main` to `origin/main`, and delete the merged branch (local + remote).

### Task 5: Reconcile trackers
- [ ] Tick the Phase 1 checkboxes in `docs/superpowers/plans/2026-07-15-W3-taxonomy-completion-plan.md`.
- [ ] Update `.planning/STATE.md`: `stopped_at`/Current Position note that W3 Phase 1 (prospective-memory Local model + evaluator) is merged with the PR number and merged SHA; W3 Phases 2–4 open next; W1 production-parity/runtime-readiness/protected-attempt items remain operator-gated unchanged; include the host-pressure note if the full suite was skipped, and note that CBM/gbrain/Graphify refresh at the merged SHA stays an explicit open item if not hardware-admitted.
- [ ] Land the tracker/plan-doc update through the same PR-based flow (either in the Task 4 PR or a small follow-up docs PR merged on green CI) — never as a direct push to `main`.
