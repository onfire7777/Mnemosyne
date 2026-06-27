---
phase: 07-unified-cognitive-substrate
plan: 05
status: pre-owner-checkpoint
target_metric: standing_erasure_cascade_contract
target_value: 1.0
gate_decision: passed
requirements_completed: [FR-7, FR-8, OQ6, "spec:§13-H8", "spec:§13-H12"]
requirements_remaining: ["spec:§9-P5-toggle-retirement", "owner-checkpoint", "final-no-toggle-audit"]
completed: 2026-06-27
---

# 07-05 Pre-Owner-Checkpoint: Cascade And Observability

Phase 7 P5 is partially implemented up to the owner checkpoint. The safe
pre-checkpoint H8/H12 work is wired and G0-gated; operational toggle deletion
has not been performed.

## Implemented

- Retrieval hit metadata now includes `standing.observability.v1` records with
  the derived Standing values, source evidence CIDs, replayability flags, and
  bitemporal projection metadata.
- Local and Postgres `forget()` cascades now include
  `standing.erasure-cascade.v1` in deletion propagation and audit diffs.
- Erasure reports identify erased and source-trimmed self-derivations and mark
  Standing as recomputed on read rather than stored as an authority column.
- Belief-core dependency invalidation now annotates retracted assertions and
  audit entries with `standing.belief-cascade.v1`.
- G0 has a pre-checkpoint fixture, `eval/g0/unified_substrate.py`, and
  preregistration, `eval/g0/preregistrations/g5-unified-substrate-cascade.json`.

## Gate Evidence

- `standing_observability_trace_contract`: `1.0`
- `standing_erasure_cascade_contract`: `1.0`
- `belief_standing_cascade_contract`: `1.0`
- G0 coverage after regeneration: `69/70` measured; only
  `controller_watts_per_dollar` remains intentionally missing without explicit
  controller power telemetry.
- Gate command:
  `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate eval/g0/reports/report.json --prereg eval/g0/preregistrations/g5-unified-substrate-cascade.json --print-json`
- Gate result: passed.

## Remaining Owner Checkpoint

Do not delete `shadow_only` or `service.enabled` operational toggles from this
checkpoint alone. The remaining P5 work is:

- confirm all prior `g5-*` gates and differential Standing parity are green,
- get the owner checkpoint for toggle retirement,
- remove operational toggles,
- preregister/run the final `g5-toggle-retirement` gate,
- write `docs/blueprint/cognitive-architecture/UNIFIED-SUBSTRATE-AUDIT.md`,
- create the final `07-05-SUMMARY.md`.
