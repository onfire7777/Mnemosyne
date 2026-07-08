# Phase 09: Performance and Refactoring Continuation - Context

**Gathered:** 2026-07-08
**Status:** Ready for planning
**Mode:** GSD continuation over an already attested v1.0 roadmap

<domain>
## Phase Boundary

Phase 09 continues the performance/refactoring blueprint after Phase 8
production evidence attestation. It is not a new parity claim by itself. The
phase should make small, source-owned, parity-safe improvements that reduce
latency or structural debt while preserving the existing operator evidence
contract and not weakening any release gate.
</domain>

<decisions>
## Implementation Decisions

### Operator Overrides Stay Authoritative

Existing env knobs are the compatibility boundary. A default may move only when
the operator can still force the old behavior and focused tests prove equivalent
results.

### Capability-Tier Defaults Before Hot-Path Rewrites

Use `capability.resolve_tier()` and `capability.recommended_env()` for
hardware-aware defaults. Avoid adding per-query hardware probing or new runtime
configuration layers unless profiling proves the existing boundary is
insufficient.

### GSD/CBM/Gbrain Hygiene Is Part Of Done

Each slice must leave GSD phase artifacts current, refresh CBM after code/doc
changes, sync the `mnemosyne-code` gbrain source, and ship from a clean
`main`/`origin/main` state.
</decisions>

<code_context>
## Existing Code Insights

- `src/mnemosyne/pipeline.py` owns `parallel_channels_enabled()` and the single
  threaded-vs-sequential branch in `run_retrieval_pipeline()`.
- `src/mnemosyne/capability.py` maps host facts to `floor`, `standard`,
  `accelerated`, or `frontier`, and returns advisory env recommendations.
- `tests/test_engine_perf_lanes.py` already proves sequential and parallel
  retrieval channel results are byte-identical on Local and SQLite engines.
- `tests/test_capability.py` already proves recommendation keys, tier
  overrides, and opt-in autotune only-fill-unset behavior.
</code_context>

<specifics>
## Specific Ideas

Start with the B5/§7.5 retrieval pipeline item: make parallel channels default
from capability tier for capable hosts while preserving explicit
`MNEMOSYNE_PARALLEL_CHANNELS=0` and keeping `floor` conservative.
</specifics>

<deferred>
## Deferred Ideas

Provider-layer embedding caches, async provider/SQL I/O, Postgres stored-vector
MMR defaulting, and larger CLI decomposition remain future Phase 09 slices.
They need separate measurement and acceptance criteria.
</deferred>
