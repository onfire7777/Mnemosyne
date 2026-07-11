---
phase: 12-grounded-multi-hop-answer-synthesis
plan: 02
status: complete
completed: 2026-07-11
requirements-completed: []
---

# Phase 12 Plan 02 Summary: Bounded Grounded Orchestration

## Outcome

Mnemosyne now has a bounded, dependency-free answer orchestration layer over
the existing shared deep-retrieval/PPR pipeline. It preserves one immutable
authorization context across every query, admits only authorized active
evidence CIDs, groups safe adjacent episode turns, replays every hop before
emission, and returns one existence-silent abstention shape on any failure.

## Security and Truth Contracts

- Role, tenant, branch, user/source identity, source/trust ceilings,
  sensitivity, capabilities, purpose, residency/region, lawful basis,
  break-glass, and timezone-aware `as_of` are validated and non-widening.
- Legacy `min_trust_tier` is canonicalized to the engines' real maximum-ceiling
  semantics; TrustTier and sensitivity values are strictly bounded.
- Temporal scope reaches graph PPR and evidence hydration.
- Relation/projection IDs are never citable; provenance sources are admitted
  only after same-context filtered authorization as evidence rows.
- Episode metadata must exactly match canonical source/session identity and a
  nonnegative non-boolean turn index; missing/mismatched identities never join.
- Per-hop fingerprints bind content, source/session/episode, trust/sensitivity,
  provenance, authorization metadata, and access policy while ignoring volatile
  score/order.
- Every hop is replayed; replayed rows—not stale originals—are emitted.
- Typed `record_access=False` suppresses only retrieval access telemetry for
  answer orchestration, including cached/uncached paths, without forking
  ranking or exposing a policy-filter bypass.

## Verification

- Grounded-answering, shared-engine, access-policy, prompt-injection rail,
  public CLI metadata, retrieval parity, engine performance/cache, SQLite,
  CLI/runtime, and runtime-surface suites passed; live Postgres cases remained
  correctly DSN-gated.
- Full locked repository suite passed with expected external-engine skips.
- Ruff, diff, dependency/lock, and secret checks passed.
- Independent security review: 98/100, safe to commit, no blockers.

## Boundary

No model-generated answer or public QA score exists yet. CAP-001 and CAP-002
remain open until Plan 12-03 supplies the configured reader/public answer
surface and Plan 12-04 proves the measured grounding and QA gates.
