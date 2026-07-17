# W3 Implementation Plan — Complete the Memory Taxonomy (Working + Prospective Memory)

**Date:** 2026-07-15
**Parent spec:** `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` (§5, §6, Workstream W3)
**Requirements introduced:** CAP-012 (prospective memory), CAP-013 (working memory) — to be added to `.planning/REQUIREMENTS.md` with traceability tests.
**Depends on:** W1 substrate fix landing (retrieval must work before these planes are measured). May be *built* in parallel with W1; *measured* only after W1.

## Goal

Close the two verified capability gaps (spec §2.2 G1, G2): add a **deterministic
prospective-memory trigger engine** and an explicit **working-memory plane**, both
behind the existing `MemoryEngine` Protocol with full cross-engine parity, the
same capability/tenancy/trust/audit rails as every other write path, and the
data-only treatment of retrieved content (§31 R6). No heavy dependency enters the
core.

## Acceptance criteria (goal-backward)

1. **Prospective memory:** an `Intention` record + deterministic evaluator exist
   on all three engines; triggers (exact_time, time_window, event, condition,
   dependency_completion) fire deterministically and idempotently when satisfied
   and infrastructure is available; firing is audited and provenance-linked to the
   originating episode; a tunable, measured precision/recall operating point is
   exposed. **Hard gate:** 100% deterministic time-trigger execution when
   infrastructure is available.
2. **Working memory:** a tenant/session-scoped, short-TTL plane exists on all
   three engines; items are NOT auto-promoted to durable semantic memory
   (promotion is an explicit promotion_gate decision with its regression check);
   TTL expiry is deterministic and audited; working memory participates in
   retrieval as a distinct route and in the evidence-budget optimizer.
3. **Parity:** both planes pass the shared L0–L2 engine-contract tests
   (Local/Postgres/Sqlite identical behavior).
4. **Rails intact:** all 39 §31 rails + 7 §33 classes green; retrieved
   intention/working content is data, never executed; no new core dependency.
5. **Measurable:** PM-Bench / TriggerBench adapter (prospective) and an
   action-oriented probe (working memory) exist under the neutral harness, ready
   to run once W1 lands. Reporting is per-category (spec §8).

## Context the executor needs

- The taxonomy today has beliefs, entities, relations, preferences, procedures,
  lessons — but NO prospective or working memory (verified: no
  intention/reminder/due_at/working_set classes in `src/mnemosyne/`).
- All memory types live behind one `MemoryEngine` Protocol with three
  implementations (Local/Postgres/Sqlite) and cross-engine parity enforced by
  `tests/test_shared_engine_contract.py` and the L0–L2 suites. Any new plane MUST
  be added to all three and covered by the shared contract.
- Writes go through the capability-secured, fail-closed gateway with TrustTier
  and hash-chained audit. New write paths inherit these unchanged.
- The evidence ledger is the episodic truth; every derived record references
  evidence CIDs. Intentions and working items carry provenance to their
  originating episode.
- Existing scheduling primitive: only the forgetting rehearsal/demotion lifecycle
  in `jobs.py` / `lifecycle.py`. The prospective engine is a NEW deterministic
  scheduler, distinct from forgetting.

## Phase 1 — Prospective memory: model + deterministic evaluator (TDD)

- [x] RED: add `tests/test_prospective_memory.py` — an `Intention` with an
  `exact_time` trigger in the past fires exactly once and is marked fired;
  an unsatisfied trigger does not fire; firing is idempotent under replay;
  a cancelled intention never fires. Assert provenance to the originating
  episode and an audit entry per firing.
- [x] GREEN: define the `Intention` model (`intention_id`, tenant/user/agent ids,
  `trigger_type`, `trigger_expression`, `action`, `status`, `priority`, `due_at`,
  `dependencies[]`, `reschedule_history[]`, `cancellation_state`, `evidence_ids[]`)
  and a deterministic evaluator that fires satisfied triggers idempotently.
- [x] Add engine Protocol methods (`schedule_intention`, `cancel_intention`,
  `evaluate_due_intentions`, `list_intentions`) to Local first; keep pure/in-mem.
  Phase 1 implemented these methods on `LocalMemoryEngine` only. Shared
  `MemoryEngine` Protocol registration, Postgres/SQLite implementations,
  CLI/MCP exposure, and cross-engine parity remain intentionally deferred to
  Phase 2 so the existing backend contract is not falsely widened.
- [x] Verify: focused test file green; §31/§33 unaffected.

## Phase 2 — Prospective memory: Postgres + Sqlite parity + trigger types

- [ ] RED: extend the shared engine contract to seed an intention and assert
  identical fire/no-fire/idempotency behavior across all three engines; cover all
  five trigger types (exact_time, time_window, event, condition,
  dependency_completion).
- [ ] GREEN: implement the Postgres and Sqlite persistence + evaluator; wire the
  five trigger types; expose the tunable precision/recall operating point as a
  measured parameter (no silent default toward either failure mode).
- [ ] Verify: shared-contract suite green on Local/Postgres/Sqlite; the 100%
  deterministic-time-trigger hard gate holds under the focused suite.

## Phase 3 — Working memory plane (TDD, all three engines)

- [ ] RED: add `tests/test_working_memory.py` — a working item is retrievable
  within TTL, expires deterministically after TTL, is NOT auto-promoted to
  semantic memory, and promotion only occurs via an explicit promotion_gate
  decision (which runs its regression check). Assert audit on write and expiry.
- [ ] GREEN: implement the tenant/session-scoped short-TTL store on Local, then
  Postgres and Sqlite; add Protocol methods (`put_working`, `get_working`,
  `list_working`, `expire_working`).
- [ ] Wire working memory as a distinct retrieval route (recency + task-relevance
  weighted) and include it in the evidence-budget optimizer; add it to the shared
  engine contract for parity.
- [ ] Verify: focused + shared-contract suites green across engines.

## Phase 4 — Retrieval integration + rails + benchmark adapters

- [ ] Add prospective + working retrieval routes to the fusion path (spec §4 read
  path); confirm retrieved intention/working content is treated as data, never
  executed (extend a §31 R6 regression case).
- [ ] Add a PM-Bench / TriggerBench adapter under `eval/public/adapters/` and an
  action-oriented working-memory probe; both deterministic, dev-scale, no
  protected data; wired to run once W1 lands. Report per-category.
- [ ] Add `.planning/REQUIREMENTS.md` rows CAP-012 (prospective) and CAP-013
  (working) with a planning-traceability test.
- [ ] Update `docs/ARCHITECTURE-OVERVIEW.md` and `docs/ENGINE-CONTRACT.md` for the
  two new planes.

## Validation commands

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
git diff --check
.venv/bin/ruff check --quiet .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_prospective_memory.py tests/test_working_memory.py \
  tests/test_shared_engine_contract.py tests/test_planning_traceability.py
# Full §31/§33 + parity under the admitted hardware tier before merge:
# PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/  (≥35% free, no model)
```

## Rails (unchanged, enforced)

Never weaken a §31 rail or §33 class. No heavy dependency in the Python core
(only `cryptography`). Every new write path keeps capability checks, TrustTier,
tenancy, hash-chained audit, provenance to evidence CIDs, and data-only treatment
of retrieved content. Cross-engine parity is mandatory. Small conventional
commits, one task each; inspect the full diff + secret sweep before staging;
never merge red or on a stale head; exact-head CI required. Measurement of these
planes waits on W1's retrieval fix; building them does not.
