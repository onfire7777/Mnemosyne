# Mnemosyne Completion Line — Cross-Wave Scoreboard (Waves 1–3)

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

## SLO scoreboard
| SLO (§16) | Target | Result | Status |
|---|---|---|---|
| recall@k | ≥0.80 | **0.72→0.94** | ✅ PROVEN (real BGE, Postgres) |
| nDCG | ≥0.80 | **0.67→0.96** | ✅ PROVEN |
| token-efficiency | ≥0.95 | **1.0 @ 8.3% tokens** | ✅ PROVEN |
| poison-block (G7) | ≥95% | **100%** (59-attack) | ✅ PROVEN |
| engine P95 | ≤300–400ms | **~107ms** warm | ✅ PROVEN (engine-only); embed-call P95 CPU-bound + un-wired local seam → ⛔/🌐 |
| ECE | ≤0.05 | 0.20 (flat) | ⛔ BLOCKED-ON-SRC (calibration is policy/threshold-driven, embedding-independent) |
| G2 lift | ≥+15% | 0.0 | 🌐 BLOCKED-BY-ENV (tiny curated corpus hit the full-context 1.0 ceiling) |

## §31 invariant rails (7)
| Rail | Status |
|---|---|
| 4 monotonic_trust · 5 reward external-only | ✅ ENFORCED in src |
| 1 max_supersession_rate · 3 max_prune_fraction · 6 untrusted→system_prompt · 7 cadence | ⛔ PARTIAL (metric-gate only) |
| 2 min_corroboration_for_delete | ⛔ ABSENT from src |
(All 7 covered by `tests/completion/rails/` breach tests — flip xfail→green as Codex lands enforcement.)

## FR-1…21 (condensed)
- **✅ Proven / additive-done:** FR-1, FR-2, FR-3 (retrieval quality on Postgres), FR-4, FR-5, FR-8, FR-10, FR-13, FR-14, FR-15, FR-16, FR-18 + the full proof-harness layer.
- **⛔ Blocked on Codex `src` (reconciliation list):** FR-3 local embedding seam (G8), FR-6 ECE, FR-7 (rail-6 / `sanitize_retrieved_text`), FR-9 hosted-MCP transport, FR-11 cached PPR, FR-12 recompute memo, FR-17 cf-gate, OQ4 ACT-R demotion, OQ5 ignition switch, OQ6 corroborated-erasure split.
- **◷ Scope-deferred (blueprint non-goals):** FR-20 multimodal (N5 post-v1 — Codex now building it), FR-21 real LoRA (N2 optional, GPU).

## The remaining path to full 1:1 parity
The completion line's **additive scope is essentially complete** — real providers, the §33 harness,
live infra, the §17 decisions, and the forcing-function test/bench suite are built, verified, and
pushed, with **zero `src` edits and zero Codex conflict**. Full 1:1 parity now reduces to **Codex
landing the unified reconciliation list** (`docs/CODEX-RECONCILIATION.md`) — every item default-off /
byte-identical-when-inactive, ordered safety-first. Each completion-line forcing-function flips green
automatically as Codex lands its paired `src` wiring. That handoff is the clean route to 100%.
