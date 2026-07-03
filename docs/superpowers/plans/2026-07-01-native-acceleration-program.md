# Native Acceleration Program — Plan Map

**Spec:** `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` (commit 31c50a5).
The spec defines six independently-shippable phases → one implementation plan per phase. Each later plan is written when its predecessor's real interfaces exist to cite (no speculative signatures).

| # | Plan | Status | Gated on |
|---|------|--------|----------|
| 0 | `2026-07-01-phase0-seam-hardening.md` | **DONE** | — |
| 1 | `2026-07-02-phase1-kernels.md` (C1 `mnemosyne._native` + A4 lazy imports) | **DONE** (exit: lexical 40.5×, prepacked dense 82.5× — both 10×-gated; hashing 4.6× vs 3.0× floor; list-FFI dense 4.6× informational, end-to-end dense 10× re-homed to Phase 2 packed-BLOB seam; CLI import <100ms; CI wheels job non-gating) | — |
| 2 | `2026-07-02-phase2-sqlite-engine.md` (C2 + A1 cache + chaos harness + drift/ops-check/L4 suites) | **IN PROGRESS** on `phase2/sqlite-engine` (Tasks 1-8 landed through `789b5f9`; Tasks 9-13 pending) | Phase 0/1 contracts and kernels are already in the local stack; packed-BLOB dense owns the Phase 2 end-to-end 10× gate; no remote branch/CI yet |
| 3 | `phase3-providers.md` (C3 sidecar + A3 consolidation ladder) | to write | Start only after Phase 2 exit gates; independent provider work must still preserve Phase 0/1/2 parity contracts |
| 4 | `phase4-front-end.md` (C4 rmcp + daemon) | to write | **Evidence gate:** measured proof that per-session spawn latency matters (spec §4.4); Phase 1 (A4) and Phase 2 backend readiness first |
| 5 | folded into each phase (docs/ADR steps) + final README/claims pass | — | Phases 0–4 |
| 6 | future-directions (IVM, three-way merge, TursoEngine spike) | not planned now | spec §8/§9 triggers |

Execution rule: run each plan to completion (all tasks, parity suite green, off-by-default flags per spec §8 rollout guards) before writing the next plan.
