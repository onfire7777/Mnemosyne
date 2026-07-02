# Native Acceleration Program — Plan Map

**Spec:** `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` (commit 31c50a5).
The spec defines six independently-shippable phases → one implementation plan per phase. Each later plan is written when its predecessor's real interfaces exist to cite (no speculative signatures).

| # | Plan | Status | Gated on |
|---|------|--------|----------|
| 0 | `2026-07-01-phase0-seam-hardening.md` | **DONE** | — |
| 1 | `phase1-kernels.md` (C1 `mnemosyne._native` + A4 lazy imports) | to write | Phase 0 complete on branch `phase0/seam-hardening` (merge pending) (kernel call sites = `algorithms.py` functions) |
| 2 | `phase2-sqlite-engine.md` (C2 + A1 cache + chaos harness + drift/ops-check/L4 suites) | to write | Phase 0 complete on branch `phase0/seam-hardening` (merge pending) (ENGINE-CONTRACT, fixture parametrization, journal, registry); inherits lane-invariant predicates deferred from Phase 0 |
| 3 | `phase3-providers.md` (C3 sidecar + A3 consolidation ladder) | to write | Phase 0 complete on branch `phase0/seam-hardening` (merge pending); independent of 1–2 |
| 4 | `phase4-front-end.md` (C4 rmcp + daemon) | to write | **Evidence gate:** measured proof that per-session spawn latency matters (spec §4.4); Phase 1 (A4) done first |
| 5 | folded into each phase (docs/ADR steps) + final README/claims pass | — | Phases 0–4 |
| 6 | future-directions (IVM, three-way merge, TursoEngine spike) | not planned now | spec §8/§9 triggers |

Execution rule: run each plan to completion (all tasks, parity suite green, off-by-default flags per spec §8 rollout guards) before writing the next plan.
