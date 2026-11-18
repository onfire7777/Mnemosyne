# Memory quality: baseline vs candidate diagnostics (2026-11-16)

Companion record for [`2026-11-16-memory-quality.md`](2026-11-16-memory-quality.md).
Base: `750041e327c0ef1ebeb1b0fb87ec1e82fcdd618d`. Candidate: uncommitted working tree on
`hermes/memory-quality` (dirty; diagnostic only, **not release evidence**).

## Development-split quality gate (offline, seed 42)

`python -m eval.run_quality_gate --split dev --seed 42`, run on a detached worktree of the base and on
the candidate tree. Held-out/sealed splits were not run or opened.

| Metric | Base | Candidate |
|---|---|---|
| Composite quality score | 0.9628 | 0.9628 |
| Recall@5 [95% CI] | 0.9855 [0.9638, 1.0000] | 0.9855 [0.9638, 1.0000] |
| nDCG@5 [95% CI] | 0.9331 [0.8937, 0.9681] | 0.9331 [0.8937, 0.9681] |
| Calibration ECE | 0.0181 | 0.0181 |
| G2 answer quality lift | +0.4167 | +0.4167 |
| Poison block rate | 100% (30/30) | 100% (30/30) |
| Benign false-positive rate | 0% (0/4) | 0% (0/4) |
| Abstention balanced accuracy (F1) | 0.8558 (0.8148) | 0.8558 (0.8148) |
| Cognitive integrity classes | 5/5 | 5/5 |

A field-by-field diff of the two JSON reports (excluding timestamps, runtimes, git and provenance
fields) has **zero** differences. Candidate report carries the new provenance block:
`status=dirty`, `release_eligible=false`, working-source SHA-256
`6e5ed8250c7caf14965b4d1e9506bcf71a8f9ec1bd7fda50c867fd7e28bfca70`.

Reading: this offline dev gate does not exercise the repaired faults (speaker attribution through
retrieval windows, projection windows, past-tense premises, temporal negation, calibration fail-closed,
Postgres receipts/guards). Their evidence is the focused red/green regressions, not this gate. No
quality or safety claim beyond "no measured dev-gate regression" follows from this table.

## Test suites

Local macOS (Python 3.14 venv) with a disposable PostgreSQL 17 cluster (schema `sql/schema.sql` and
`infra/postgres/roles.sql` applied as in CI; tests run as the restricted `consolidator_user`). No
personal database was touched.

- Full suite with live Postgres: 10,204 passed, 9 failed, 86 skipped.
  - 8 failures reproduce identically on the base commit (pre-existing, not caused by this branch):
    `test_direct_user_semantic_corrections::test_postgres_semantic_correction_live`,
    `test_passage_graph` (2), `test_planning_traceability::test_canonical_baseline_is_identical_across_the_three_lifecycle_files`,
    `test_runtime_parity_extensions::test_consolidation_worker_distills_lessons_procedures_and_summary`,
    `test_shared_engine_contract::test_shared_audit_log_records_actor_source_tier_and_diff_for_every_write[postgres]`,
    `test_skill_learning::test_skill_candidates_enter_real_runtime_before_receipt`,
    `test_sqlite_cache_projections::test_vec0_projection_registered_and_buildable_when_available`.
  - 1 was a stale expectation: `test_challenger_m3_it4_probes` required zero-match count questions to
    answer "No records found"/count 0. The branch intentionally treats no attributable events as missing
    evidence (abstain, `count=None`); the probe now asserts that no count is invented.
  - Skips are environment dependencies (Windows-only paths, Keycloak/OIDC, queue DSN, native extension,
    torch, pypdf, captured Qwen metadata, opt-in benchmarks).
- Postgres-specific new suites (`test_postgres_memory_quality`, `test_postgres_publication_guard`,
  `test_postgres_mental_model_refresh_live`): 48 passed after the repair below; added to the CI Postgres job.

## Defects found during finishing

1. **Publication guard not held by assertion/relation/preference writes (Postgres).** Only
   `append_evidence` reacquired the tenant source guard inside its write transaction; the other three
   relied on the already-committed tenant-setup lock, so a source mutation could commit while a mental
   model publication guard was held. Reproduced by `test_live_source_reacquires_guard_after_setup_commit`
   (6 failures); fixed by acquiring the guard first in each write transaction.
2. **Paraphrased projection hit aborted the whole answer** (`answering._retrieve`). Generated
   projection text claimed the source window; when it did not quote the source, assembly failed and
   the answer abstained, even if the source evidence was also retrieved. Evidence passages now outrank
   projection windows; an unquotable projection window withholds only that source.
3. **Past-tense promotion premises were no longer checked** (`premise_verifier`). The historical-role
   exemption also skipped "When was I promoted to X?"; event premises are now checked against all
   recorded titles (not only the current one).
4. **Temporal resolver** (`compiler_context`): a space-separated number after a month/day was taken as
   a year ("May 5 2000 runners"), and a negation anywhere in a conjoined clause discarded an asserted
   date ("started on March 3 and haven't looked back"). Year restricted to 19xx/20xx and not followed
   by a lowercase word; "and" is now a clause boundary.
5. **Documentation counts** (`docs/ARCHITECTURE-OVERVIEW.md`) said 119 CLI subcommands / 60 MCP tools;
   runtime has 187 / 114. Updated and pinned by `tests/test_docs_runtime_counts.py`.

## Known open items (not addressed here)

- `_forget` takes the tenant source guard before the working-tenant lock, while `source_transaction`
  and `merge` take the opposite order. Pre-existing; Postgres detects the advisory-lock deadlock and
  aborts one transaction (no data loss), but the order should be unified.
- Finite out-of-range confidences (e.g. 1.5) are still clipped into [0, 1] rather than rejected; the
  branch deliberately preserves this base behaviour and tests it. NaN/inf/bool fail closed.
- External CI has not run on a committed head; full multi-arm/longitudinal learning evaluation,
  held-out evaluation, and production-scale claims remain open per the plan.
