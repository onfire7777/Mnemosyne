---
phase: 07-unified-cognitive-substrate
plan: 05
status: partial
slice: service-enabled-retirement
target_metric: workspace_service_no_enable_toggle_contract
target_value: 1.0
requirements_completed: ["spec:§9-P5-service-enabled-retirement"]
requirements_remaining: ["spec:§9-P5-shadow-only-retirement", "g5-toggle-retirement", "final-no-toggle-audit"]
completed: 2026-06-28
---

# 07-05 Service Toggle Retirement Summary

Phase 7 P5 now retires the concrete `ShadowWorkspaceService.enabled`
default-off gate. This is not the final P5 completion artifact: remaining
`shadow_only` compatibility/reporting fields, `g5-toggle-retirement`, and
`UNIFIED-SUBSTRATE-AUDIT.md` remain open.

## Implementation

- Removed the `enabled` field from `ShadowWorkspaceService` construction and
  `ShadowWorkspaceServiceReport`.
- Removed the disabled-by-default runtime error path. The service retains an
  explicit started/running lifecycle for bounded execution telemetry, but no
  service-level enable toggle.
- Updated G0 consciousness and shadow-workspace probes to construct the native
  service without `enabled=True`.
- Added `workspace_service_no_enable_toggle_contract` to the G0 report and
  `baseline-0.json`, proving the service payload omits the former `enabled`
  field while preserving running lifecycle and telemetry.

## Verification

- `workspace_service_no_enable_toggle_contract`: `1.0`
- Focused checks:
  - `.venv/bin/python -m ruff check src/mnemosyne/workspace.py eval/g0/shadow_workspace.py eval/g0/consciousness.py eval/g0/runner.py tests/test_workspace_stream.py tests/test_g0_harness.py`
  - `.venv/bin/python -m pytest tests/test_g0_harness.py::test_current_g0_candidate_replays_preregistrations_without_regression tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract tests/test_g0_harness.py::test_g0_consciousness_scorecard_reports_indicator_properties -q`
  - `.venv/bin/python -m pytest tests/test_workspace_stream.py tests/test_always_on_heartbeat.py -q`

## Remaining P5 Work

- Remove remaining `shadow_only` compatibility/reporting fields where Standing
  now supplies authority.
- Preregister and pass `eval/g0/preregistrations/g5-toggle-retirement.json`.
- Write `docs/blueprint/cognitive-architecture/UNIFIED-SUBSTRATE-AUDIT.md`.
- Create the final `07-05-SUMMARY.md`.
