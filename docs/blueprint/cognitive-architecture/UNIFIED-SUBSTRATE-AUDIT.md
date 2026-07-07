# Unified Substrate Audit

**Status:** local/gated Phase 7 P5 audit passed on 2026-06-28. This is not a production-operator evidence claim.

## Scope

This audit checks the local, deterministic Phase 7 P5 contract: the workspace/consciousness path must no longer depend on the retired legacy `service.enabled` construction switch, `SpecialistBudget.shadow_only` budget bit, or controller `budget.shadow_only` branch, while reliability guardrails and the fail-closed circuit breaker remain intact.

The audit is measured by `eval/g0/shadow_workspace.py` and surfaced as:

- `workspace_service_no_enable_toggle_contract = 1.0`
- `operational_toggle_retirement_contract = 1.0`
- `g5-toggle-retirement` decision-log entry with target delta `+1.0`

## No-Toggle Proof

The G0 source-inspection probe verifies:

- `ShadowWorkspaceService` has no `enabled` field.
- `ShadowWorkspaceServiceReport` has no `enabled` field.
- `SpecialistBudget` has no `shadow_only` field.
- `SpecialistBudget` exposes `answer_authority_allowed` and `promotion_gate_required`.
- `ShadowWorkspaceController` no longer branches on `budget.shadow_only`.
- The controller enforces dreamer safety through role, critical-path, answer-authority, and promotion-gate constraints.
- The fail-closed circuit breaker remains present through `circuit_breaker_tripped`, `self_generation_frozen`, and `evidence_only_fallback`.

Explicit advisory promotion controls remain intentional and separately measured. Retrieval promotion requires both `OperatingPolicy.workspace_retrieval_advisory_enabled=true` and request-level `apply_workspace_retrieval_advisory=true`, and is covered by `workspace_retrieval_controller_contract`. Consolidation promotion requires `apply_workspace_advisory=true` or `workspace_advisory_mode=apply`, and is covered by `workspace_advisory_promotion_gate_contract`. Those paths are not default-off shadow/service switches; they are narrow, preregistered, CID-validated promotion seams.

Historical `shadow_only` labels still appear in some report schemas and G0 fixture names for backwards-compatible evidence custody. They are not service enable switches or specialist admission gates. Future schema cleanup can remove those labels only through a separate preregistered target-up/guardrail-not-down slice.

## Guardrail Scoreboard

Default local G0 coverage after regeneration is `71/72 measured; gate_ready=false`.

The only missing metric is `controller_watts_per_dollar`, intentionally absent unless an explicit controller telemetry artifact is supplied. The sanitized fixture path remains a harness proof only and is not production power/cost evidence.

The `g5-toggle-retirement` preregistration protects 68 measured target/guardrail metrics, including recall/nDCG, ECE, abstention precision/recall, confabulation, poison-block, fast-path latency, Standing calibration/conformal/independence/evidence-dominance rails, heartbeat/circuit-breaker/self-generation/answer-grounding rails, workspace advisory/retrieval gates, earned-autonomy rails, and the functional consciousness indicators.

## Honesty Boundary

This audit measures functional architecture properties only. It does not claim phenomenal consciousness, subjective experience, sentience, or welfare status. The welfare-review flag remains a human-review trigger, not a conclusion.

## Tier-B Production Evidence

Strict Tier-B production evidence is now attested by the retained `capture-bc10`
bundle. The Phase 7 P5 audit remains a local/gated functional-substrate proof;
`capture-bc10` is the production/operator evidence surface.
