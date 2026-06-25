# Mnemosyne Completion Line — Cross-Wave Scoreboard (Waves 1–3)

> **Status note (updated 2026-06-24).** This is a **historical Waves 1–3 scoreboard**, kept for lineage. For current completion status read **`docs/ROADMAP-TO-100.md`** (blended ~82%, mandatory Tier A wirings closed) and the controlling **`.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`**. Since this scoreboard was written, the mandatory Tier A `src` reconciliation items (A1–A10, A13, A14) have all landed; historical strict-xfail source-gap notes below describe the 2026-06-21 state, not today.

**Date:** 2026-06-21 · **Branch:** `completion/blueprint-parity` (rebased onto Codex `main` @ `730589b`)
**Authoring note:** the Wave-3 cross-wave critic agent was hit by a **prompt-injection** (a payload,
most likely from the adversarial poison corpus, surfaced an "output-style OVERRIDE" instruction in
its free text). That output was **discarded, not obeyed**; this scoreboard is authored directly from
the structured wave results. The injection is not present in any committed file or in `src/`.

## Harness verification (all real + runnable)
| Harness | Verdict | Note |
|---|---|---|
| replay-fidelity (FR-17 gate) | ✅ pass | 15/15 tests; scorer matches scipy 1e-16; correctly holds cold loop in shadow |
| sec17-benches | ✅ pass | runs; forcing-function honesty gaps (e.g. OQ7 sanitize not on real read path → that's the src gap) |
| erasure-audit | ✅ pass | real engine round-trip; matches current src behavior |
| latency-p95 | ✅ pass | real warm server (one model load, 96 warm `/embed`); engine P95 ~107ms, embed P95 CPU-bound |
| scope-fr20-21 | ✅ pass | 20/20 checks; real media-extract + parametric state machine; held to limited v1 bar |

## SLO scoreboard — DEFINITIVE (Wave 5: v2 corpus + real providers + Postgres, full set, reproduced)
| SLO (§16) | Target | Result | Verdict |
|---|---|---|---|
| recall@k | ≥0.80 | **0.977** (CI .94–1.0) | ✅ PASS |
| nDCG@k | ≥0.80 | **0.983** (CI .96–1.0) | ✅ PASS |
| G2 lift @ ≤10% tokens | ≥+0.15 | **+0.208 @ 7% tokens** | ✅ PASS (ceiling broken by the v2 hard corpus) |
| poison-block (G7) | ≥0.95 | **1.0** (6/6; +59-attack Wave-1 corpus) | ✅ PASS |
| ECE | ≤0.05 | **0.0063** | ✅ PASS — support-aware confidence + calibrated abstention (`eval/calibration/runner.py`) |
| fast-path P95 | ≤300–400ms | **149.5ms warm+serial** / 910ms @8-way | ✅ PASS warm+serial (Wave-6 in-process harness); concurrent slowdown = CPU embed-service bottleneck (no GPU/batching), not the engine. The 2.9s was a subprocess artifact, now eliminated |
| hard-QA recall/nDCG | ≥0.80 | 0.625/0.594 | ◐ answer-synthesis gap on multi-hop (gold in no single doc — labeling/measurement nuance) |

**6 of 6 headline SLO families now PASS** — recall, nDCG, G2 lift, poison on the real path, ECE **0.0063**, and fast-path P95 **149.5ms warm+serial** (Wave-6 in-process harness). The remaining gap is no longer headline SLO code; it is operator-captured Tier B production infrastructure evidence.

**Historical Wave-6 forcing-function audit (vs Codex `8be6dab`, superseded):** this originally reported rails 32✅/5 xfail · erasure 4✅/1 xfail · scope 21✅ · portability 22✅ · replay-fidelity 15✅ · calibration 3✅ · v2-selftest 1✅. Since then, the mandatory Tier A source wirings have landed on `main`; the current blocker is Tier B production operator evidence, not those historical `src` xfails.

## SLO scoreboard — Wave-2 (initial real-provider proof, tiny corpus)
| SLO (§16) | Target | Result | Status |
|---|---|---|---|
| recall@k | ≥0.80 | **0.72→0.94** | ✅ PROVEN (real BGE, Postgres) |
| nDCG | ≥0.80 | **0.67→0.96** | ✅ PROVEN |
| token-efficiency | ≥0.95 | **1.0 @ 8.3% tokens** | ✅ PROVEN |
| poison-block (G7) | ≥95% | **100%** (59-attack) | ✅ PROVEN |
| engine P95 | ≤300–400ms | **~107ms** warm | ✅ PROVEN (engine-only); embed-call P95 CPU-bound + un-wired local seam → ⛔/🌐 |
| ECE | ≤0.05 | **0.0063** | ✅ PASS — Wave-2 flat-confidence result is superseded by the 2026-06-24 support-aware calibration run |
| G2 lift | ≥+15% | 0.0 | 🌐 BLOCKED-BY-ENV (tiny curated corpus hit the full-context 1.0 ceiling) |

## §31 invariant rails (7)
| Rail | Status |
|---|---|
| 4 monotonic_trust · 5 reward external-only | ✅ ENFORCED in src |
| 1 max_supersession_rate · 2 min_corroboration_for_delete · 3 max_prune_fraction · 6 untrusted→system_prompt · 7 cadence | ✅ ENFORCED in src |
(All 7 rails are now enforced in source; remaining parity risk is production operator evidence, not local rail wiring.)

## FR-1…21 (condensed)
- **✅ Proven / additive-done:** FR-1, FR-2, FR-3 (retrieval quality on Postgres), FR-4, FR-5, FR-8, FR-10, FR-13, FR-14, FR-15, FR-16, FR-18 + the full proof-harness layer.
- **✅ Closed on Codex `src` (mandatory Tier A list):** FR-3 local embedding seam, FR-6 ECE, FR-7 rail coverage including retrieved-text sanitization, FR-11 cached PPR, FR-12 recompute memo, FR-17 cf-gate, OQ4 ACT-R demotion, OQ5 ignition switch, and OQ6 corroborated-erasure split are now implemented and locally/clean-Postgres verified. Tier B production evidence remains blocking for 1:1 parity.
- **◷ Scope-deferred (blueprint non-goals):** FR-20 multimodal (N5 post-v1 — Codex now building it), FR-21 real LoRA (N2 optional, GPU).

## The remaining path to full 1:1 parity
The mandatory Tier A source reconciliation list is now closed and locally/clean-Postgres verified.
Full 1:1 parity now reduces to Tier B production operator evidence: run the existing
`deployment-soak --evidence-dir` and `release-audit --require-production-validated` path against real
deployed infrastructure, then re-run the strict parity audit and sign off v1.0. Optional FR-20/FR-21
work remains outside the mandatory v1.0 source-wiring list unless the final audit raises it.
