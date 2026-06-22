# FR-17 Cold-Loop Replay-Fidelity Check (OQ2)

- **Generated:** 2026-06-22T00:21:48.311653+00:00
- **Mode:** `require-wired`
- **Blueprint refs:** OQ2, FR-17 cold-loop gate, §23.3, §30.6
- **OQ2 bar:** rho>=0.6 & CI-lower>0.3, sign>=0.8, gap<=0.15, window>=50, coverage>=0.8

## Verdict: FAIL (exit 2)

- golden guarantee holds: **True**
- cf term wired into gate: **False**
- proxy authorized to gate: **False**
- loop correctly SHADOW (veto-only): **True**

## Golden corpus (faithful MUST pass; degenerates MUST be rejected)

| Case | Expected | Actual | OK | n | rho | CI-low | sign | gap | cov | vetoed by |
|---|---|---|---|---|---|---|---|---|---|---|
| faithful | pass | pass | OK | 60 | 0.9872 | 0.9723 | 0.9167 | 0.0717 | 0.95 | — |
| all_tie | reject | reject | OK | 60 | 0.0 | 0.0 | 1.0 | 0.0 | 1.0 | spearman_rho, rho_ci_lower |
| sign_flipped | reject | reject | OK | 60 | -0.9955 | -0.9956 | 0.0 | 0.19 | 0.0667 | spearman_rho, rho_ci_lower, sign_agreement, proxy_true_gap, decision_coverage |
| tiny_window | reject | reject | OK | 8 | 0.994 | 0.9493 | 0.875 | 0.0494 | 0.875 | window |
| noise | reject | reject | OK | 60 | 0.1587 | -0.1023 | 0.5667 | 0.1213 | 0.5833 | spearman_rho, rho_ci_lower, sign_agreement, decision_coverage |
| biased_gap | reject | reject | OK | 60 | 0.9973 | 0.9931 | 0.4 | 0.2407 | 0.4 | sign_agreement, proxy_true_gap, decision_coverage |

## Current-src honest status

**Honest current status — loop correctly held in SHADOW (veto-only).** The counterfactual replay arithmetic exists and runs (`counterfactual_replay_score(2,5,10)` = 0.3), and it is surfaced by `mcp_tools.outcome_evaluate`, but it is **informational only**: `cf term consumed by gate decision = False`. `gate.PromotionGate.evaluate` decides `promoted` purely from the regression-case margin, and `ShadowPolicyOptimizer.evaluate_variant` is veto-only by construction (restores base `OperatingPolicy()` in a `finally`: shadow_only=True). There is **no paired (replay-predicted lift, observed real lift) corpus in src**, so the OQ2 gate has 0 real pairs to score (window 0 < 50). The replay proxy is therefore **NOT authorized to gate self-modifications**, which is exactly why the cold loop must stay in shadow. This harness is the forcing function: it will authorize the proxy only once the cf->gate path is wired AND it clears the OQ2 bar on real paired data.

### Required src wiring to authorize the proxy as a gate

- src/mnemosyne/self_optimization.py — add an `observed_real_lift` field (or a reserved metrics key) to `PolicyOutcome` and have the cold loop record the real post-promotion lift there, paired to the candidate's `replay_predicted_lift` (= counterfactual_replay_score(before,after,total)).
- src/mnemosyne/self_optimization.py — add a `SelfModelStore.replay_pairs(tenant_id)` accessor that returns the (predicted, observed) pairs the OQ2 scorer consumes, so the gate has a first-class source of paired data.
- src/mnemosyne/gate.py — extend `PromotionGate.evaluate` (or add a sibling `replay_fidelity_gate`) so that, before `promoted` can be True for a self-modification candidate, the OQ2 fidelity bar over recent replay_pairs must hold (rho>=0.6 & CI-lower>0.3, sign>=0.80, gap<=0.15, window>=50, coverage>=0.80). Until the bar holds, force veto-only (shadow).
- src/mnemosyne/self_optimization.py — bind the existing `tripwire_check` `max_proxy_gap` (0.15) to the OQ2 `proxy_true_gap` axis so the two gap guards share one threshold and cannot drift apart.
- src/mnemosyne/mcp_tools.py — stop treating `outcome_evaluate`'s `counterfactual_replay_score` as purely informational: route the cf value into the candidate's `replay_predicted_lift` so it is the same number the OQ2 gate scores (single source of truth for the proxy).
- eval — once wired, run `replay_fidelity_check.py --require-wired` in CI; a non-zero exit (code 2) blocks the cold loop from leaving shadow until the proxy proves fidelity on real paired data.
