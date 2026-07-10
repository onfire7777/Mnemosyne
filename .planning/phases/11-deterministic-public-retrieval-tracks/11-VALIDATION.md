# Phase 11 Validation Strategy

1. Schema/digest/license tests fail before implementation.
2. Hand-calculated Recall@2/@5, nDCG, EM, and token-F1 cases prove scoring.
3. Fixed-seed bootstrap and Wilson outputs are reproducible.
4. Adversarial bundle tests bind source assets, normalized questions, golds,
   corpus IDs, traces, metrics, and reproduction output.
5. CLI-only integration fixtures run create/verify/reproduce/verify.
6. Full pinned public datasets run from a fresh external cache and emit bundles
   plus result notes; no number is marked headline eligible.
7. Existing Phase 10 focused gates, full pytest, Ruff, GSD consistency, CBM,
   gbrain, and exact-SHA CI run. CI billing refusal remains a reported external
   blocker, never converted into a pass.

