---
phase: 07-unified-cognitive-substrate
plan: 05
status: partial-service-toggle-retired
target_metric: standing_erasure_cascade_contract
target_value: 1.0
gate_decision: passed
requirements_completed: [FR-7, FR-8, OQ6, "spec:§13-H8", "spec:§13-H12"]
requirements_remaining: ["spec:§9-P5-shadow-only-retirement", "owner-checkpoint", "final-no-toggle-audit"]
completed: 2026-06-27
---

# 07-05 Pre-Owner-Checkpoint: Cascade And Observability

Phase 7 P5 is partially implemented. The safe H8/H12 work is wired and
G0-gated, and the `service.enabled` default-off gate has been retired and
G0-measured. Final `shadow_only` compatibility retirement and the final
no-toggle audit/gate remain open.

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

## Gate Evidence

- `standing_observability_trace_contract`: `1.0`
- `standing_erasure_cascade_contract`: `1.0`
- `belief_standing_cascade_contract`: `1.0`
- `workspace_service_no_enable_toggle_contract`: `1.0`
- G0 coverage after regeneration: `70/71` measured; only
  `controller_watts_per_dollar` remains intentionally missing without explicit
  controller power telemetry.
- Gate command:
  `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate eval/g0/reports/report.json --prereg eval/g0/preregistrations/g5-unified-substrate-cascade.json --print-json`
- Gate result: passed.

## Owner Checkpoint Packet

This checkpoint is a pause point, not approval to retire all remaining
compatibility fields. Current synced head when this packet was refreshed:
`c8aa8bc` on `main` / `origin/main`, with GitHub CI `28317585328` passing
before the service-toggle retirement edit.

Prior Phase 7 G5 gates already recorded:

| Gate | Target metric | Recorded outcome |
| --- | --- | --- |
| `g5-standing-byte-stable-parity` | `standing_decision_divergence` | passed with `0.0` divergence |
| `g5-standing-continuous` | `standing_calibration_error` | passed with `0.0` target delta |
| `g5-always-on-heartbeat` | `always_on_heartbeat_contract` | passed with bounded compute and rumination `0.0` |
| `g5-earned-autonomy` | `earned_autonomy_external_expansion` | passed; echo-chamber uplift `0.0`, credential rails green |
| `g5-unified-substrate-cascade` | `standing_erasure_cascade_contract` | passed; observability, erasure cascade, and belief cascade contracts `1.0` |

Missing final P5 artifacts until remaining compatibility retirement is approved:

- `eval/g0/preregistrations/g5-toggle-retirement.json`
- `docs/blueprint/cognitive-architecture/UNIFIED-SUBSTRATE-AUDIT.md`
- `.planning/phases/07-unified-cognitive-substrate/07-05-SUMMARY.md`
- a final `g5-toggle-retirement` decision-log row

Before any retirement edit, refresh the inventory with:

```bash
rg -n '\bShadowWorkspaceService\b|\benabled:\s*bool\b|\bself\.enabled\b|\benabled=self\.enabled\b|\benabled=True\b' \
  src/mnemosyne/workspace.py eval/g0/consciousness.py eval/g0/shadow_workspace.py

rg -n '\bshadow_only\b' \
  src/mnemosyne/workspace.py src/mnemosyne/dreamer.py src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py eval/g0

rg -n '\bstanding_from_shadow_flag\b|\bshadow_tags_shadow_only\b|\bshadow_tags_critical_path\b' \
  src/mnemosyne/standing.py src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py
```

Accepted resume signals:

- Type `retire the toggles` to authorize operational toggle deletion and final
  `g5-toggle-retirement` work.
- Type `hold toggles` to keep remaining `shadow_only` compatibility boundaries
  and stop P5 at this checkpoint.

## Remaining Owner Checkpoint

Do not delete remaining `shadow_only` compatibility fields from this checkpoint
alone. The remaining P5 work is:

- confirm all prior `g5-*` gates and differential Standing parity are green,
- get the owner checkpoint for toggle retirement,
- remove remaining `shadow_only` compatibility/reporting fields where Standing
  now supplies authority,
- preregister/run the final `g5-toggle-retirement` gate,
- write `docs/blueprint/cognitive-architecture/UNIFIED-SUBSTRATE-AUDIT.md`,
- create the final `07-05-SUMMARY.md`.
