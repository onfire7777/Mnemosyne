# Mnemosyne — Codex Reconciliation Handoff (`src/` changes for 1:1 parity)

**Date:** 2026-06-21 · **Status:** living (Wave-1 + §17 done; Wave-2 items appended on completion)
**Canonical src tree:** `/Users/admin/Projects/Mnemosyne/src/mnemosyne` (Codex's `main`)
**Completion line (additive):** branch `completion/blueprint-parity` — provides the tests / services /
harnesses / proofs; it never edits `src/`.

This file is the bridge that makes the zero-conflict split work: the completion line builds the
*additive* layers in parallel; the items below are the **`src/` wirings only Codex can land on
`main`** to reach full blueprint parity. **Every item is additive, default-off / shadow-first, and
byte-identical when inactive** — none require new infra, new deps, or a rewrite. Recurring theme
(from the §17 analysis): *wire machinery that already exists but is left disconnected.*

---

## Codex progress snapshot (audited against `origin/main` @ `14353d1`, 2026-06-21)
The reconciliation tracker re-audited every item against Codex's latest committed `src`:

**✅ Already LANDED by Codex — close these:**
- **Rail 6 `untrusted_to_system_prompt`** — live capability check in `authorize_write` (`security.py:903`), wired into consolidation + mcp_tools.
- **OQ6 corroborated-erasure split** — `engine.py:928-976` forget now computes `surviving_sources` → retain-with-updated-provenance vs retract sole-source (the exact OQ6 default).
- **Deletion-trigger param** — `erasure_mode` on both forget signatures distinguishes legal vs operator deletion.

**◐ PARTIAL:**
- `sanitize_retrieved_text` — defined (`security.py:921`) but **0 call sites** in the retrieval/assembly path.
- **Rails 1 & 3** (`max_supersession_rate` 0.05 / `max_prune_fraction_per_pass` 0.02) — constants in `parametric.py` but enforced only as soft post-hoc checks in the trainer path; **no live per-pass clamp** in consolidation.
- Recompute (`jobs.py:run_projection_recompute`) — already dirty-driven/incremental, but no content-fingerprint memo to skip unchanged passes.
- `command backend adapters` (`14353d1`) — added adapter *types* in `retrieval.py`, but did **not** wire providers into the LOCAL engine seam.

**✗ Still ABSENT (the real remaining gaps):**
- `min_corroboration_for_delete` rail (0 matches in src) · Rail 7 `consolidation_cadence_bounds [5_steps,24h]` · LocalMemoryEngine embedding seam (`cli.py:409` still no `adapters=`) · cf-term in `gate.py` PromotionGate.evaluate (pure regression margin) · `RegressionCase.origin` / `PromotionGate.ignition_status` · ACT-R demotion (`lifecycle.decayed_salience` still `exp(-age/45)`; `retrieval` base_level frequency-only) · cached PPR column.

---

## 0. LAND FIRST — coordinated immutable-rails block (3 items)
Downstream gate/validator logic depends on these, so sequence them first.
1. **`min_corroboration_for_delete = 2`** (§31 rail #2) — **ABSENT from `src` entirely** (grep: 0 hits). Add to `OperatingPolicy` immutable rails; gate operator/consolidation deletion. [FR-8, G7, OQ6, Wave-1 rail-2]
2. **`cold_loop_counterfactual_trusted`** (default **off**) — new immutable rail; flips on *only* when the protected `replay-fidelity-check` passes. [FR-17, OQ2]
3. **OQ2 fidelity-bar constants** — one immutable block referenced by gate + validator (ρ≥0.6, sign-agreement≥0.80, coverage≥0.80, window≥50, bootstrap n=1000).

## 1. SAFETY — enforce the 5 breachable §31 rails
The completion line's `tests/completion/rails/` proves these **fail today** (strict-xfail); each flips xfail→green automatically as Codex lands enforcement.
- **Rail 1** `max_supersession_rate 0.05` — partial (self-reported metric only, no live ceiling) → add per-pass clamp.
- **Rail 2** `min_corroboration_for_delete` — **unenforced** (see §0.1).
- **Rail 3** `max_prune_fraction_per_pass 0.02` — partial → add per-pass clamp.
- **Rail 6** `untrusted_to_system_prompt forbidden` — `sanitize_retrieved_text` (`security.py ~921`) **has zero call sites** → wire it (see OQ7).
- **Rail 7** `consolidation_cadence_bounds [5_steps, 24h]` — partial → enforce bounds.

## 2. PER-FR RECONCILIATION (from the §17 decisions — exact files/functions)
- **FR-11 / FR-3 (OQ1, PPR latency):** persist a PPR-score column refreshed on edge-change; wire the cached signal into the **fast branch** of `retrieve()`; keep the adapter `Protocol` as the specialist-swap seam. (Today: undifferentiated Python power-iteration over all relations, deep-only, no cache/column.)
- **FR-4 / FR-12 / I6 (OQ3, incremental recompute):** add `input_fingerprint = sha256(sorted(source_evidence_cids)+erased-flags+pass/rule-version+raptor_level)` + a red/green **memo** to `jobs.py:run_projection_recompute` and each pass in `consolidation.py:DEFAULT_CONSOLIDATION_PASSES`; persist fingerprints on projection metadata (`postgres_engine.py` upsert paths); drive `ErasureMode.TOMBSTONE_RECOMPUTE` through the **same** memoized frontier. (Today: correct affected-CID fixpoint but **no dirty-check** → re-runs all passes unconditionally.) **Do not** add pg_ivm/differential-dataflow.
- **FR-13 / §22.4 (OQ4, fidelity demotion):** add a `DemotionSchedule` config (`policy.py`: `decay_d=0.5`, `retention_halflife_days=30`, per-edge thresholds **0.50/0.25/0.10** replacing flat 0.18, rehearsal `[1,3,7,14,30,60,120,240]`); re-ground `lifecycle.decayed_salience` (`lifecycle.py:59-66`) from orphan `exp(-age/45)` to ACT-R power-law `age^-d`; fix `retrieval.py:384` base_level to include the power-law recency term (not frequency-only); bound all by `max_prune_fraction_per_pass`.
- **FR-14 / FR-17 (OQ5, suite ignition):** add `origin` (`curated|genuine|synthetic`) + `mode` to `RegressionCase`/`PromotionGate` and `PromotionGate.ignition_status` (`gate.py`); **N_active=30 curated** flip (synthetic never counts); shadow-no-merge in `evaluate()`; persist the ignition marker (`runtime_state.py`); CLI flags (`cli.py`); both `learning.py:promote_lesson()` and `self_optimization.py:ShadowPolicyOptimizer.evaluate_variant()` consult `ignition_status` before any real merge.
- **FR-17 / §23.3 / §30.6 (OQ2, cold-loop cf gate):** add a real replay fn over sampled `Trajectory` rows (main vs canary) in `learning.py`; wire the cf-term into the promote decision (`gate.py` / `self_optimization.py`) as **veto-only** whenever the standing fidelity report is below bar (today the gate ignores cf entirely); extend `PolicyOutcome` with `predicted_lift` and persist predicted/realized pairs in `SelfModelStore`.
- **FR-8 / Privacy (OQ6, corroborated erasure):** extend the corroboration-aware split to the **derived-evidence cascade** (`engine.py:1358-1378`, `postgres_engine.py:1369-1385`) — today it blanket-zeroes every transitively-derived row; add a deletion-trigger param to `forget()` (orthogonal to `ErasureMode`); record updated-provenance markers in `deletion_log`. Policy: **legal erasure = corroboration-blind** (overrides the rail, GDPR Art.17); **operator/consolidation deletion = corroboration-gated** by rail #2.
- **FR-7 / I11 (OQ7, mediation asymmetry):** wire `sanitize_retrieved_text` (`security.py ~921`, 0 call sites) into an opt-in read/re-injection path emitting `instruction_authority=none`; document the asymmetric boundary (full mediation on writes/tool-flows, trust-tier-only on reads) as a constant so the optimizer can't move it; (optional) promote to `SecurityPolicy.immutable_rails`.

## 3. FR-19 C2PA src note
`provenance._find_first` (`~line 334`) surfaces `claim_generator` (`c2patool/0.9.x`) as the signer instead of the real signer. The Wave-2 fix is config-side (trust-policy), but for robust real-signer trust Codex should make `_find_first` extract the actual signer field. *(Wave-2 will confirm/refine.)*

## 4. WAVE-2 reconciliation items (proven with real providers + live infra)
- **FR-3 / G8 — `LocalMemoryEngine` has NO embedding seam (CRITICAL, read-only verified).** `cli.py:359` returns `LocalMemoryEngine(store_path=...)` with **no `adapters=`** (only the Postgres branch `cli.py:356` passes `adapters=load_retrieval_adapters`); `LocalMemoryEngine.__init__(self, store_path, policy)` has no embedding hook. Net: `--backend local` **silently ignores real embedding/reranker providers** — real dense retrieval works *only* on Postgres. Codex must add an embedding/reranker adapter seam to `LocalMemoryEngine` and wire it through `cli.py:load_engine`, so local↔prod are the same architecture (G8). *Proven impact:* on Postgres+real-providers recall 0.72→0.94, nDCG 0.67→0.96; on `--backend local` the same flags moved nothing (0 `/embed` calls).
- **FR-6 — ECE is policy/threshold-driven, not embedding-driven.** ECE stayed flat at 0.20 even with real embeddings → the conformal calibration thresholds need a real per-memory-type calibration set + tuning to reach §16's ≤0.05. (Completion line will provide the calibration harness; Codex tunes the thresholds.)
- **FR-19 (optional hardening) — `provenance._find_first` (~line 334)** surfaces `claim_generator` as the signer instead of the leaf signer; and `ProvenanceTrustRule.from_dict` defaults an omitted `require_trusted_issuer` to True (foot-gun the Wave-2 infra fix worked around config-side). Optional: extract the real signer field and/or use a sentinel default. Not a correctness bug — the config fix already makes the positive path trust correctly.
- **Eval/latency note (completion-additive, not src):** P95 failed only because the harness uses subprocess-per-call + per-call HTTP model round-trips, not a long-lived server. The completion line will add a long-lived-server P95 bench; no src change implied.
- **Infra: Keycloak validate had 1/3 checks fail** (Vault + c2patool PASS) — investigate in the completion infra layer (additive).

---
## 5. WAVE-4 new findings (the additive corpora surfaced these)
- **`cli.py` argparse `--object` ambiguity (real bug, affects Codex `main`).** `propose`/`supersede`/`assert --object` is now an ambiguous prefix of the newer top-level globals `--object-store`/`--object-store-encryption`/`--object-key-*`, so `... propose --object X` errors `ambiguous option: --object`. Fix: `allow_abbrev=False` on those subparsers (or rename the globals). Breaks 1/26 harness tests + blocks `assert`/`propose` from eval.
- **FR-6 — local engine confidence is degenerate.** On `--backend local`, `search` returns a constant **0.7** confidence and **never abstains** (nonsense/hard-negative/poison all `abstained=False`), so ECE can't reach §16 ≤0.05 (measured **0.155**). Codex must give the local retrieval path varied, calibrated confidence + working abstention. The Wave-4 calibration set re-runs unchanged once fixed.
- **Minor:** `eval/run_eval.py` hardcodes `DATASETS = _EVAL_DIR/'datasets'` — a 1-line env shim (`os.environ.get('MNEMO_EVAL_DATASET_DIR', …)`) lets the stock runner select v2 (default unchanged). `models.Preference` lacks the `access_policy` field that Evidence/Assertion/Relation have (asymmetry note).

---
**Safety contract:** every change above preserves current default routing/outputs exactly (memo
all-GREEN ≡ current recompute; cf veto-only until bar; ignition shadow-no-merge; sanitize opt-in).
The completion line ships the tests/harnesses/services that **prove** each once landed.
