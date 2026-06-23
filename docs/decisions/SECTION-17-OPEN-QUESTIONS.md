# Mnemosyne — Blueprint §17 Open Questions: DECISION MEMO

**Date:** 2026-06-21 · **Status:** resolved (7/7, all high confidence)
**Method:** 8-agent read-only analysis fleet, grounded in the blueprint's standing decisions + the
current `src/mnemosyne` tree. **No code was modified to produce this.**

## Decisions

- **OQ1 — PPR latency.** Cached PPR on the **fast** path; live PPR only in **async deep** mode behind the engine adapter; swap a graph specialist only on a profiled SLO tripwire (~1e7–1e9 edges/tenant). Consolidation precomputes a per-relation PPR score the fast path reads under a small cap. *(Today: undifferentiated power-iteration over all relations, deep-only, no cache/column.)* → **FR-11, FR-3 P95**.
- **OQ2 — Replay fidelity.** Gate the FR-17 cold loop behind a **pre-registered, shadow-only replay-fidelity backtest**; counterfactual replay is **veto-only** until it clears the bar: Spearman ρ≥0.6 (95% CI lower >0.3), sign-agreement ≥0.80, proxy-true gap ≤0.15, rolling window ≥50 (≥10 active), coverage ≥0.80, bootstrap n=1000. New immutable rail `cold_loop_counterfactual_trusted` (default **off**). → **FR-17**.
- **OQ3 — Incremental recompute.** Adopt **salsa-style memoization** on the existing queue substrate; **do NOT** add pg_ivm/differential-dataflow now. Add `input_fingerprint = sha256(sorted(source_evidence_cids)+erased-flags+pass/rule-version+raptor_level)` + red/green dirty-check. *(Today: correct affected-CID fixpoint but no dirty-check → re-runs all passes.)* → **FR-4, FR-12, I6**.
- **OQ4 — Fidelity demotion.** Freeze **ACT-R d=0.5**; 4-tier ladder (verbatim→extractive→gist→trace), per-edge thresholds **0.50/0.25/0.10** (replacing flat 0.18), `retention_halflife_days=30`, rehearsal `[1,3,7,14,30,60,120,240]`. Re-ground decay to power-law `age^-d` (today `exp(-age/45)` is an orphan); fix `retrieval` base_level to include power-law recency. Tune within rails [0.3,0.7]. → **FR-13, §22.4**.
- **OQ5 — Suite ignition N.** Flip shadow→active at **N_active=30 curated** cases (≥20 curated held-out, ≥5 genuine, all protected tiers); synthetic **never** counts (capped 2× curated). Smallest suite where per-slice pass-rate has a usable binomial CI. *(Today: no shadow/active distinction — gated as active from case zero.)* → **FR-14, FR-17**.
- **OQ6 — Corroborated erasure.** **Retain-with-updated-provenance** is the DEFAULT for projections keeping independent corroboration; recompute/retract only for sole-source-derived. **Legal erasure = corroboration-blind** (overrides the rail, GDPR Art.17); **operator deletion = corroboration-gated** by `min_corroboration_for_delete=2`. → **FR-8**.
- **OQ7 — Capability overhead.** Asymmetric: **full mediation on writes/tool-flows, trust-tier-only on reads** + a cheap data-not-instruction envelope (avoids CaMeL's ~2.7× read-path tax). Wire `sanitize_retrieved_text` (currently **0 call sites**). → **FR-7, I11**.

## What this means for the build
1. **The recurring theme is "wire what's already half-built," not "build new."** 5 of 7 are disconnected seams where the blueprint already decided and the upstream half exists in code.
2. **Uniform safety contract:** default-off / shadow-first / byte-identical-when-inactive.
3. **Land 3 rails/constants first as a block:** `cold_loop_counterfactual_trusted`, `min_corroboration_for_delete=2` (absent from src), the OQ2 fidelity-bar constants.
4. **One ignition switch (OQ5)** is the keystone that makes G5 and the Phase-0→4 transition *evaluable*.
5. **The profiling/measurement harnesses are the long-pole completion-additive deliverable** — they convert "SLOs unproven" into *measured* (the §38 "measure before claiming" exit).

See `docs/CODEX-RECONCILIATION.md` for the exact `src`-level wiring list each decision implies.
