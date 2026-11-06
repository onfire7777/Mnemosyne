# Learning integration validation — 2026-11-05

This cleanup integrates the learning implementation with Mnemosyne's existing APIs. All 22 learning components retain their `active` default. Explicit pause/off settings and mandatory provenance, outcome, effect-approval, and erasure guards remain effective.

The implementation is integrated with the reorganized `dev`/`main` baseline `d0143fe8`, including its journal/SQLite tenant ownership, redacted retrieval, ingestion validation, queue recovery, and parametric artifact-path fixes. The local architecture work and separately edited source files are preserved.

## Ownership after cleanup

| Area | Authoritative implementation |
| --- | --- |
| Trajectories, lessons, procedures | Native episodes/artifacts, serialized by the existing model classes; `LearningSystem` provides compatibility views. |
| Historical storage | Side-state archives and duplicate trajectory wrappers migrate into the native writer. Reported historical success remains distinct from verified outcomes. |
| Learned skill lifecycle | The native runtime owns admission, promotion, demotion, revisions, retirement, and rollback. `SkillStore` projects its per-scope states and distinct episode outcomes. |
| Host completion and cadence | SDK, MCP, Hermes, and jobs use shared runtime configuration and orchestration. Atomic claims deduplicate automatic consolidation and allow failed attempts to retry. |
| Legacy induction | Existing evidence consolidation skips sources already owned by native episodes. |
| Training sources | Automatic sources must have canonical active admission and provenance. Historical learned status claims are excluded. Explicit curated operator inputs retain their separate supported path. |
| Shared calculations | One observed-step extraction contract and one Wilson numerical kernel, with each public API retaining its empty-sample semantics. |
| Profile erasure | One branch-wide decision and persistence operation; direct engine callbacks preserve entries while another live branch still supports them. |

Standalone manually imported skills retain their original validation path until native registration. This is deliberate API compatibility, not a second owner for runtime-managed skills.

## Regression coverage

New tests cover immediate native skill ownership; promotion with and without control outcomes; duplicate and concurrent signals; failed consolidation retries; session-end maintenance; disabled-component outcomes; scoped library projections; source erasure; revision/rollback lineage; stale archive resurrection; concurrent compatibility edits; native metadata preservation; shared engine ownership after reload; and training-source filtering.

The final isolation review also separates consolidation, abstraction, chunks, and candidate identities by user. Serving enforces artifact ownership independently of source readability. Native source identities preserve user/session provenance when different users produce identical text; supplied host evidence remains reused. Existing owner-matched identities remain stable during migration.

Full-suite investigation also identified a pre-existing relation replay bug. Empty or inverted validity windows did not overlap themselves, so replay could repeatedly clone the same relation. Matching the same relation identity and window makes replay idempotent. Tests cover thin/full canaries and preserve distinct relation identities.

The PostgreSQL source-locked publication path also attempted schema-readiness DDL during export. It now keeps that transaction read-only until the guarded model update; missing schema fails closed instead of being created while source locks are held.

The wheel builds successfully. An isolated import of the built wheel verifies all 22 active defaults, SDK external-outcome resolution, one canonical trajectory, and durable reload.

## Retained golden-fixture mismatches

The legacy golden fixtures are not rewritten to make this cleanup appear green:

- Six cases in `test_golden_equivalence.py` already disagree with the pre-cleanup baseline. They cover growth, rails, and conflicts in both branch modes. The G0 scenarios pass.
- Four cases in `test_pipeline_extraction.py` already disagree with the pre-cleanup retrieval surface, including old rail lists and scores. Their exact float-bit comparison also depends on elapsed time in the current salience calculation.

Independent comparisons use the pre-cleanup checkpoint and the original main checkout. For the formerly nonterminating relation scenario, only the relation replay fix is injected into the baseline process; baseline files are not changed. In both branch modes, all four scenario query outputs match exactly. Complete rails/G0 dumps match. After normalizing learning audit IDs, growth/conflict differences are limited to the intended reduction in duplicate creation/reuse counters and canonical persistence audit events. With time frozen, all four complete pipeline retrieval surfaces match the pre-cleanup checkpoint exactly.

Live PostgreSQL verification requires a configured PostgreSQL test database. Local/mock backend checks do not substitute for that environment or establish learning benefit on a sealed benchmark.
