---
phase: 07-unified-cognitive-substrate
plan: 05
status: complete-local-gated
slice: operational-toggle-retirement
target_metric: operational_toggle_retirement_contract
target_value: 1.0
requirements_completed: ["spec:§9-P5-service-enabled-retirement", "spec:§9-P5-operational-toggle-retirement", "g5-toggle-retirement", "final-no-toggle-audit"]
requirements_remaining: []
completed: 2026-06-28
---

# 07-05 Service Toggle Retirement Summary

Phase 7 P5 now retires the concrete `ShadowWorkspaceService.enabled`
default-off gate and the specialist-budget `shadow_only` operational control.
Remaining historical report labels are compatibility schema, not live
operational toggles.

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
- Removed `SpecialistBudget.shadow_only` and replaced the dreamer safety budget
  with explicit `critical_path_allowed=false`, `answer_authority_allowed=false`,
  and `promotion_gate_required=true`.
- Replaced the controller `spec.budget.shadow_only` admission branch with
  authority/promotion-gate checks.
- Replaced `standing_from_shadow_flag` with `standing_from_authority_state`.
- Added `operational_toggle_retirement_contract` and the
  `g5-toggle-retirement` preregistration/decision-log custody.

## Verification

- `workspace_service_no_enable_toggle_contract`: `1.0`
- `operational_toggle_retirement_contract`: `1.0`
- `g5-toggle-retirement`: passed with target delta `+1.0`
- Focused checks:
  - `.venv/bin/python -m pytest tests/test_parity_retrieval.py::test_specialist_registry_builds_modules_and_blocks_shadow_critical_path tests/test_parity_retrieval.py::test_specialist_registry_rejects_invalid_specs_and_duplicate_names tests/test_dreamer.py::test_shadow_workspace_controller_recruits_dreamer_off_critical_path tests/test_dreamer.py::test_shadow_workspace_controller_rejects_replaced_dreamer_factory tests/test_standing_parity.py::test_standing_mirrors_authority_state tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract -q`
  - `.venv/bin/python -m pytest tests/test_g0_harness.py::test_committed_g0_preregistrations_have_passing_decisions tests/test_g0_harness.py::test_current_g0_candidate_replays_preregistrations_without_regression tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract -q`
  - `.venv/bin/python -m ruff check src/mnemosyne/workspace.py eval/g0/shadow_workspace.py eval/g0/consciousness.py eval/g0/runner.py tests/test_workspace_stream.py tests/test_g0_harness.py`
  - `.venv/bin/python -m pytest tests/test_g0_harness.py::test_current_g0_candidate_replays_preregistrations_without_regression tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract tests/test_g0_harness.py::test_g0_consciousness_scorecard_reports_indicator_properties -q`
  - `.venv/bin/python -m pytest tests/test_workspace_stream.py tests/test_always_on_heartbeat.py -q`

## Remaining Work

- Tier-B production/operator evidence remains outside Phase 7 P5.
- Historical `shadow_only` report labels can be cleaned in a later
  preregistered schema-compatibility slice, but they are no longer live
  operational toggles.
