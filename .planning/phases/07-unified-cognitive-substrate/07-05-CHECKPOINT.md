---
phase: 07-unified-cognitive-substrate
plan: 05
status: complete-local-gated
target_metric: standing_erasure_cascade_contract
target_value: 1.0
gate_decision: passed
requirements_completed: [FR-7, FR-8, OQ6, "spec:§13-H8", "spec:§13-H12"]
requirements_remaining: []
completed: 2026-06-27
---

# 07-05 Pre-Owner-Checkpoint: Cascade And Observability

Phase 7 P5 is locally implemented and G0-gated. The H8/H12 work is wired,
the `service.enabled` default-off gate has been retired, `SpecialistBudget`
no longer exposes `shadow_only`, and the final operational-toggle gate is
recorded as `g5-toggle-retirement`.

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
- `ShadowWorkspaceService` no longer has an `enabled` field or disabled-by-default
  error path; service reports omit the former flag and G0 measures
  `workspace_service_no_enable_toggle_contract=1.0`.
- `SpecialistBudget.shadow_only` is removed. The dreamer specialist is
  constrained through `critical_path_allowed=false`,
  `answer_authority_allowed=false`, and `promotion_gate_required=true`.
- `ShadowWorkspaceController` rejects dreamer recruitment if those authority
  constraints are weakened.
- `standing_from_shadow_flag` is retired in favor of
  `standing_from_authority_state`.
- `eval/g0/preregistrations/g5-toggle-retirement.json` gate-records the
  source-inspection proof that no operational `service.enabled`,
  `SpecialistBudget.shadow_only`, or controller `budget.shadow_only` branch
  remains while the fail-closed circuit breaker remains present.

## Gate Evidence

- `standing_observability_trace_contract`: `1.0`
- `standing_erasure_cascade_contract`: `1.0`
- `belief_standing_cascade_contract`: `1.0`
- `workspace_service_no_enable_toggle_contract`: `1.0`
- `operational_toggle_retirement_contract`: `1.0`
- G0 coverage after regeneration: `71/72` measured; only
  `controller_watts_per_dollar` remains intentionally missing without explicit
  controller power telemetry.
- Gate command:
  `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate eval/g0/reports/report.json --prereg eval/g0/preregistrations/g5-unified-substrate-cascade.json --print-json`
- Gate result: passed.

## Owner Checkpoint Packet

This checkpoint is now a historical custody packet plus the final local P5
closure evidence. Refresh the top-level handoff after each commit/push for the
current SHA and GitHub CI run.

Prior Phase 7 G5 gates already recorded:

| Gate | Target metric | Recorded outcome |
| --- | --- | --- |
| `g5-standing-byte-stable-parity` | `standing_decision_divergence` | passed with `0.0` divergence |
| `g5-standing-continuous` | `standing_calibration_error` | passed with `0.0` target delta |
| `g5-always-on-heartbeat` | `always_on_heartbeat_contract` | passed with bounded compute and rumination `0.0` |
| `g5-earned-autonomy` | `earned_autonomy_external_expansion` | passed; echo-chamber uplift `0.0`, credential rails green |
| `g5-unified-substrate-cascade` | `standing_erasure_cascade_contract` | passed; observability, erasure cascade, and belief cascade contracts `1.0` |
| `g5-toggle-retirement` | `operational_toggle_retirement_contract` | passed; target delta `+1.0`, 68 target/guardrail metrics non-regressed |

The source inspection remains intentionally narrow: it proves the old
operational toggles are gone, not that every historical compatibility field or
report label has been renamed. Future schema cleanup must be preregistered as a
separate target-up/guardrail-not-down slice.

Refresh the inventory with:

```bash
rg -n '\bShadowWorkspaceService\b|\benabled:\s*bool\b|\bself\.enabled\b|\benabled=self\.enabled\b|\benabled=True\b' \
  src/mnemosyne/workspace.py eval/g0/consciousness.py eval/g0/shadow_workspace.py

rg -n '\bshadow_only\b' \
  src/mnemosyne/workspace.py src/mnemosyne/dreamer.py src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py eval/g0

rg -n '\bstanding_from_shadow_flag\b|\bbudget\.shadow_only\b|\bSpecialistBudget.*shadow_only\b' \
  src/mnemosyne/standing.py src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py
```

## Remaining Work Outside P5

- Tier-B production/operator evidence still blocks strict v1.0 parity.
- Optional future schema cleanup can remove remaining historical `shadow_only`
  report labels, but only behind a new preregistered gate. It is no longer an
  operational-toggle blocker.
