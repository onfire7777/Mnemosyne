---
phase: 07-unified-cognitive-substrate
plan: 03
status: implemented
target_metric: always_on_heartbeat_contract
target_value: 1.0
gate_decision: passed
requirements_completed: [FR-7, FR-17, OQ5, "spec:§4-L4", "spec:§9-P3", "spec:§13-H4", "spec:§13-H5", "spec:§13-H6", "spec:§13-H9"]
completed: 2026-06-27
---

# 07-03 Always-On Heartbeat Safety Summary

The workspace loop now has a measured P3 safety floor: tiered heartbeat
reporting, hard anti-rumination, self-generation write budgeting, an
answer-grounding floor, broadcast-as-data redaction, and a fail-closed
circuit-breaker are implemented and G0-gated.

## Implementation

- Added `always-on-heartbeat-safety.v1` reports to workspace stream and service
  outputs. Reports include engaged/idle tick counts, compute budget, estimated
  compute, anti-rumination stop reason, proto-self circuit-breaker state,
  self-generation freeze/fallback state, and broadcast control-flow flags.
- Added the H4 self-generation budget rail for Local and Postgres
  `append_evidence`: self-generated/simulated writes are counted per
  tenant/branch, over-budget writes are deferred with audit custody, duplicate
  appends remain no-ops, and grounded user evidence is unaffected.
- Added low-groundedness lifecycle metadata for admitted self-generated
  content: demotable, not answer-critical, pointer-preserved, and bound by the
  configured idle-GC cadence. The immutable evidence ledger is not pruned.
- Added the H5 answer-grounding floor to Local and Postgres retrieval. Support
  dominated by low-grounded self-generated/simulated content is flagged as a
  hypothesis, confidence-clamped, and abstained before an answer can rely on it.
- Hardened H9 workspace broadcast handling so control-shaped payload keys are
  stripped, raw content stays redacted, and the broadcast report records
  `data_not_instructions=true` and `used_for_control_flow=false`.
- Extended `eval/g0/shadow_workspace.py` with P3 runtime probes:
  engaged+idle heartbeat, circuit-breaker drill, broadcast injection, H4
  self-generation budget, and H5 answer-grounding floor.
- Registered new G0 metrics and preregistration
  `eval/g0/preregistrations/g5-always-on-heartbeat.json`.

## Verification

- `always_on_heartbeat_contract`: `1.0`
- `always_on_rumination_rate`: `0.0`
- `heartbeat_compute_bounded_contract`: `1.0`
- `heartbeat_compute_reported_contract`: `1.0`
- `circuit_breaker_contract`: `1.0`
- `workspace_broadcast_as_data_contract`: `1.0`
- `self_generation_budget_rail_contract`: `1.0`
- `answer_grounding_floor_contract`: `1.0`
- Reliability guardrails held in the regenerated report:
  - `ece`: `0.006271`
  - `abstention_precision`: `1.0`
  - `abstention_recall`: `1.0`
  - `confabulation_rate`: `0.0`
  - `poison_block_rate`: `1.0`
  - `fast_path_p95_ms`: `92.1`
- G0 coverage after regeneration: `59/60` measured; only
  `controller_watts_per_dollar` remains intentionally missing without explicit
  controller power telemetry.
- G5 always-on heartbeat gate:
  - command: `.venv/bin/python -m eval.g0.gate --baseline eval/g0/baselines/baseline-0.json --candidate eval/g0/reports/report.json --prereg eval/g0/preregistrations/g5-always-on-heartbeat.json --decision-log eval/g0/decision-log.jsonl --print-json`
  - result: passed
  - `target_delta`: `0.0`
  - guardrails checked: `57`, all passed

## Local Checks

- `.venv/bin/python -m py_compile src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py src/mnemosyne/retrieval.py src/mnemosyne/workspace.py eval/g0/shadow_workspace.py eval/g0/runner.py tests/test_always_on_heartbeat.py tests/test_g0_harness.py`
- `.venv/bin/ruff check src/mnemosyne/engine.py src/mnemosyne/postgres_engine.py src/mnemosyne/retrieval.py src/mnemosyne/workspace.py eval/g0/shadow_workspace.py eval/g0/runner.py tests/test_always_on_heartbeat.py tests/test_g0_harness.py`
- `.venv/bin/python -m pytest tests/test_always_on_heartbeat.py tests/test_workspace_stream.py::test_shadow_workspace_stream_runs_bounded_default_mode_ticks tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract -q`
- `.venv/bin/python -m pytest tests/test_g0_harness.py -q`

All completed successfully.

## Planned Compatibility Boundary

The native controller heartbeat is the promoted P3 measurement path. The
existing `ShadowWorkspaceService.enabled` compatibility wrapper remains until
P5, where toggle retirement is explicitly scoped with an owner checkpoint. This
keeps P3 focused on the hard safety floor and avoids conflating heartbeat safety
with final no-toggle deletion.

## Next Phase Readiness

Plan 04 can build on a G0-proven always-on safety floor: self-generation cannot
flood memory, weak self-content cannot dominate answers, broadcast content
cannot steer control flow, and proto-self risk trips an evidence-only fallback.
