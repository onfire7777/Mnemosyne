# FR-17 Cold-Loop Replay-Fidelity Check (OQ2)

- **Generated:** 2026-06-29T01:01:53.827806+00:00
- **Mode:** `default`
- **Blueprint refs:** OQ2, FR-17 cold-loop gate, §23.3, §30.6
- **OQ2 bar:** rho>=0.6 & CI-lower>0.3, sign>=0.8, gap<=0.15, window>=50, coverage>=0.8

## Verdict: PASS (exit 0)

- golden guarantee holds: **True**
- cf term wired into gate: **True**
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

**Current status — replay hook wired, promotion still shadow-only until proven.** `ShadowPolicyOptimizer` attaches the default replay hook to promotion (`cf_wired=True`), and restores base policy after evaluation (`shadow_only=True`). The default hook now fails closed when the replay-pair window is below the OQ2 bar: default promotion result = False, reason = `cf proxy unproven: 0 replay pairs < window 50`. The src-side real replay-pair corpus available to the live cold loop is 0; window 0 < 50, so the proxy is not authorized to promote. The golden corpus still proves the scorer can authorize a faithful corpus once real pairs exist.

### Required src wiring to authorize the proxy as a gate

- Populate real replay pairs in `SelfModelStore.record_replay_pair` from post-promotion outcomes.
- Run `replay_fidelity_check.py --require-wired` only after real pairs meet the OQ2 bar.
- Keep default promotion fail-closed while the real replay-pair window remains below the OQ2 minimum.
