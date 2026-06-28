---
phase: 07-unified-cognitive-substrate
plan: 05
status: complete-local-gated
completed: 2026-06-28
target_metric: operational_toggle_retirement_contract
target_value: 1.0
gate: g5-toggle-retirement
gate_result: passed
---

# 07-05 Summary: P5 Toggle Retirement

Phase 7 P5 is locally implemented and G0-gated. The H8/H12 Standing cascade and observability work is wired, the workspace service no longer has a default-off `enabled` gate, and the specialist budget no longer uses `shadow_only` as an operational control.

## Implementation

- `ShadowWorkspaceService` and `ShadowWorkspaceServiceReport` omit the former `enabled` field.
- `SpecialistBudget.shadow_only` is removed.
- Specialist budgets now expose explicit `critical_path_allowed`, `answer_authority_allowed`, and `promotion_gate_required` controls.
- The built-in dreamer budget is `critical_path_allowed=false`, `answer_authority_allowed=false`, and `promotion_gate_required=true`.
- `ShadowWorkspaceController` rejects dreamer recruitment if the role, critical-path, answer-authority, or promotion-gate contract is weakened.
- `standing_from_shadow_flag` is retired in favor of `standing_from_authority_state`.
- G0 source inspection verifies the retired `service.enabled`, `SpecialistBudget.shadow_only`, and controller `budget.shadow_only` controls are absent while the fail-closed circuit breaker remains present.
- Explicit retrieval and consolidation advisory promotion controls remain intentional, CID-validated, and separately measured by `workspace_retrieval_controller_contract` and `workspace_advisory_promotion_gate_contract`.

## Gate Evidence

- `standing_observability_trace_contract`: `1.0`
- `standing_erasure_cascade_contract`: `1.0`
- `belief_standing_cascade_contract`: `1.0`
- `workspace_service_no_enable_toggle_contract`: `1.0`
- `operational_toggle_retirement_contract`: `1.0`
- `g5-toggle-retirement`: passed with target delta `+1.0`
- Default local G0 coverage: `71/72 measured; gate_ready=false`
- Intentionally missing without explicit telemetry: `controller_watts_per_dollar`

## Verification

- `.venv/bin/python -m eval.g0.runner --repo-root /Users/admin/Mnemosyne --out-dir eval/g0/reports`
- `.venv/bin/python -m eval.g0.gate --baseline /tmp/mnemosyne-g0-p5-toggle/pre-retirement-baseline.json --candidate /tmp/mnemosyne-g0-p5-toggle/report.json --prereg eval/g0/preregistrations/g5-toggle-retirement.json --decision-log eval/g0/decision-log.jsonl --print-json`
- `.venv/bin/python -m pytest tests/test_parity_retrieval.py::test_specialist_registry_builds_modules_and_blocks_shadow_critical_path tests/test_parity_retrieval.py::test_specialist_registry_rejects_invalid_specs_and_duplicate_names tests/test_dreamer.py::test_shadow_workspace_controller_recruits_dreamer_off_critical_path tests/test_dreamer.py::test_shadow_workspace_controller_rejects_replaced_dreamer_factory tests/test_standing_parity.py::test_standing_mirrors_authority_state tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract -q`
- `.venv/bin/python -m pytest tests/test_g0_harness.py::test_committed_g0_preregistrations_have_passing_decisions tests/test_g0_harness.py::test_current_g0_candidate_replays_preregistrations_without_regression tests/test_g0_harness.py::test_g0_shadow_workspace_fixture_reports_bounded_stream_contract -q`

## Remaining Work

The remaining strict-parity blocker is Tier-B production/operator evidence against deployed infrastructure. Historical `shadow_only` report labels can be renamed later only through a separate preregistered schema cleanup; they are not live service/shadow operational toggles.
