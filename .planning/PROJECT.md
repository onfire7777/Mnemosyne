# Project: Mnemosyne Memory

## Core Value

Build a memory compiler for AI agents that keeps an immutable, content-addressed evidence ledger and compiles it into safe, explainable, branchable, typed memory projections without silent corruption.

## Authoritative Inputs

| Source | Role | Precedence |
|--------|------|------------|
| `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` | Research report, PRD, architecture, implementation blueprint, DDL, build plan | Controlling |
| `/Users/admin/Desktop/Mnemosyne/README.md` | Folder guide and v2-over-v1 precedence note | Supporting |
| `/Users/admin/Desktop/Mnemosyne/earlier-versions/Mnemosyne-Recursive-Memory-System-Design.md` | Superseded lineage design | Reference only |

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
| 2026-06-19 | Build in `/Users/admin/Projects/Mnemosyne` because `/Users/admin/Desktop/Mnemosyne` is write-blocked by macOS. | Shell write probes returned `Operation not permitted` on Desktop and succeeded in Projects. |
| 2026-06-19 | Keep Phase 0-1 executable first, but keep Phases 2-5 mandatory in the roadmap. | Updated goal requires following the full build blueprint precisely and completely. |

## Quality Bar

- Every phase must have context, plan, implementation, verification, and an explicit pass or gaps-found status.
- Tests must validate user-observable invariants, not just module imports.
- Security checks must enforce trust boundaries in code and storage, not only in prompts.
- No phase is complete because files exist; it is complete only when its verification report passes.
