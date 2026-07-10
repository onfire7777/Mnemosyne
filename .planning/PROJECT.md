# Project: Mnemosyne Memory

## What This Is

Mnemosyne is a blueprint-controlled memory compiler for AI agents. It stores
lossless evidence, compiles safe typed projections, supports branchable
updates, and exposes CLI/MCP/runtime surfaces for local and production use.

## Core Value

Build a memory compiler for AI agents that keeps an immutable, content-addressed evidence ledger and compiles it into safe, explainable, branchable, typed memory projections without silent corruption.

## Authoritative Inputs

| Source | Role | Precedence |
|--------|------|------------|
| `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` | Research report, PRD, architecture, implementation blueprint, DDL, build plan | Controlling |
| `docs/blueprint/README.md` | Folder guide and v2-over-v1 precedence note | Supporting |
| `docs/blueprint/earlier-versions/Mnemosyne-Recursive-Memory-System-Design.md` | Superseded lineage design | Reference only |

## Requirements

The controlling requirements are the v2 blueprint, the active roadmap phases,
and the strict production evidence gates retained under `.planning/`. Source
changes must preserve tenant isolation, evidence provenance, bitemporal
behavior, trust/sensitivity controls, retrieved-content-as-data semantics,
operator overrides, and parity tests across supported backends.

Validated in Phase 09.1: REQ-003, REQ-004, REQ-007, and NFR-004 now preserve
one fail-closed caller read context across direct, CLI, generated MCP, JSON-RPC,
and official SDK search/deep-search/explain surfaces without response-schema or
access-policy drift.

Validated in Phase 09.2: REQ-016, REQ-018, and NFR-005 now mount one bounded
workspace heartbeat in the supported public worker runtime, retain queue
non-interference, and fail closed when release evidence shows terminal-state
resurrection, unbounded attempts, or inconsistent counters.

## Current State

Milestone v1.0 shipped and was archived on 2026-07-10 after a 100/100 audit.
All 23 canonical requirements, 13 phase identifiers, six cross-phase
integrations, and six end-to-end flows passed; the retained Tier-B packet and
final exact-SHA CI are green. The complete roadmap, requirements, audit, and
phase artifacts are preserved under `.planning/milestones/`.

## Next Milestone Goals

The next milestone executes the two authoritative post-v1.0 programs:

- Plan B first: M1.1 public benchmark harness, then deterministic LongMemEval
  retrieval and HippoRAG multi-hop tracks with PBPP reproducibility bundles.
- Plan A in coordinated sequence: S1 grounded iterative multi-hop answer
  synthesis, followed by public security/calibration and performance/scale
  capability close-out.
- Neutral leaderboard governance L0 begins in parallel with M1; the public site
  remains blocked until Part I results and PBPP publication gates are satisfied.
- No public headline number may be published before the pinned harness, complete
  artifact bundle, separate retrieval/QA columns, and independent reproduction.

## Product Thesis

Mnemosyne combines lossless memory, compiled truth, truth-maintenance belief revision, git-like branches, bitemporal queries, fidelity-tiered forgetting, calibrated abstention, user-controlled correction, and shadow-first self-optimization into one portable local-to-production memory substrate.

Mnemosyne is its own memory system. It is distinct from gbrain and mempalace, and those systems must not be treated as interchangeable source-of-truth implementations. Mnemosyne can learn from prior systems, but this repository is building an independent, blueprint-controlled memory compiler with its own CLI/MCP surfaces, storage contracts, trust model, and parity tests.

## Implementation Defaults

| Area | Decision | Rationale |
|------|----------|-----------|
| MVP boundary | Phase 0 and Phase 1 first, then continue through Phases 2-5 | The blueprint front-loads hard-to-retrofit ledger, bitemporality, provenance, isolation, and tests. |
| Stack | Python local engine plus canonical PostgreSQL schema | Local deterministic tests run without services; schema preserves the production path. |
| Production store | PostgreSQL 16 plus pgvector, FTS, and later ParadeDB or AGE by profiling | Matches the blueprint's Postgres-centric default and avoids early multi-store sync drift. |
| Graph/PPR | Interface and local deterministic channel now; production fast path gated by benchmarks | Blueprint marks graph/PPR latency as an open risk and Phase 2 focus. |
| Self-optimization | Shadow mode behind promotion gate and immutable rails | Blueprint requires policy learning to pass regression and counterfactual replay before promotion. |
| Retrieved text | Always data, never instruction authority | Required by the security and memory-poisoning threat model. |

## Key Decisions

| Date | Decision | Evidence |
|------|----------|----------|
| 2026-06-19 | Use v2 blueprint as controlling spec; v1 is lineage only. | README states v2 is final deliverable and v1 is superseded. |
| 2026-06-19 | Build in `/Users/admin/Projects/Mnemosyne` because `/Users/admin/Desktop/Mnemosyne` is write-blocked by macOS. _(Superseded 2026-06-26: canonical checkout is now `/Users/admin/Mnemosyne`; see STATE.md.)_ | Shell write probes returned `Operation not permitted` on Desktop and succeeded in Projects. |
| 2026-06-30 | Treat `/Users/admin/Mnemosyne` as the canonical live implementation checkout; Desktop/Projects paths are historical unless `git rev-parse` proves a newer valid checkout. | Historical resume checks on 2026-06-30 verified the then-current `main` and CI. Future status claims must refresh `git status`, `git log -1`, and GitHub Actions for the live `HEAD` rather than reusing that snapshot. |
| 2026-06-19 | Keep Phase 0-1 executable first, but keep Phases 2-5 mandatory in the roadmap. | Updated goal requires following the full build blueprint precisely and completely. |
| 2026-07-10 | Use one canonical `_read_context` authorization contract for search, deep search, and explain while preserving legacy positional meaning and narrowing omitted role to `reader`. | Phase 09.1 verification, clean code review, and security audit at `threats_open: 0`. |
| 2026-07-10 | Treat terminal workspace heartbeat evidence as absorbing and enforce bounded, monotonic, internally consistent counters in release attestation. | Phase 09.2 independent verification 100/100, full suite green, and exact-SHA CI success. |
| 2026-07-10 | Reconstruct missing milestone artifacts with explicit provenance labels and enforce one-owner, three-source traceability for all 23 canonical requirements. | Phase 09.3 independent re-audit 100/100, deterministic traceability test, retained custody verification, and exact-SHA CI. |

## Quality Bar

- Every phase must have context, plan, implementation, verification, and an explicit pass or gaps-found status.
- Tests must validate user-observable invariants, not just module imports.
- Security checks must enforce trust boundaries in code and storage, not only in prompts.
- No phase is complete because files exist; it is complete only when its verification report passes.

Last updated: 2026-07-10
