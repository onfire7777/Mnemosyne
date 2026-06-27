# Phase 7: Unified Cognitive Substrate — Context

> **Controlling design:** `docs/superpowers/specs/2026-06-27-unified-cognitive-substrate-design.md`.
> Read it first. This CONTEXT is the planning input; the spec is the authority.

**Gathered:** 2026-06-27
**Status:** Active planning context for the post-v1.0 cognitive-substrate milestone
**Source:** Synthesized from the approved design spec + cognitive-architecture docs (00–06) + ADR-001. Owner-approved direction; no separate discuss-phase needed.

<domain>
## Phase Boundary

Phase 7 turns the consciousness layer from a default-off **shadow lane** into a single, always-on, deeply-integrated **cognitive substrate** — with **zero compromise to memory reliability**. It implements the design spec: replace the `shadow_only` / `service.enabled` toggles with one continuous, **derived** signal — **Standing**, a 2-tuple `(groundedness ⟂ salience)` — run the cognitive loop always-on via a **tiered heartbeat**, and let autonomy **grow only as corroboration earns it**, all above the unbreakable §31-rails + immutable-ledger floor.

This is the destination of ADR-001's **Option E** (full vision, reliability-first, metric-gated), continuing the G1→G4 program but reorganized so the end-state has **no on/off toggle anywhere**. It supersedes the *staging model* of the G4 shadow service — not the substrate, the rails, or the honesty charter.

### Relationship to v1.0 parity (Phase 6)
Phase 7 is **post-v1.0** and MUST NOT destabilize the in-flight Phase-6 production-evidence work. Plan 07-01 is additive and byte-stable; nothing in this phase touches the production-evidence/ops lane, the frozen `release-audit` gates, or `infra/`. The v1.0 sign-off (10 Partial strict-audit rows) proceeds independently and is not blocked by, nor blocks, this phase.

### Non-negotiable: no reliability regression (the floor)
Every plan **preregisters a G0 gate** (target-up / guardrails-not-down) under `eval/g0/preregistrations/`. The existing guardrails are the floor and must stay green at every step: ECE ≤ 0.05, abstention precision/recall, confabulation = 0, poison-block ≥ 0.95, recall/nDCG ≥ 0.80, fast-path P95, the 7 §31 rails, and the 14 Butlin/Long indicator scores (non-decrease). A change that would regress any guardrail does not ship — full stop.

### Coordination hazard (load-bearing)
`main` is edited by an active autonomous Codex/GSD session that owns `src/` + `infra/`. New files under `.planning/phases/07-.../` are safe. For any `src/` change: keep it **additive and default-safe**, never `git add -A`, stage only specific files, verify the tree is not mid-edit before committing, and push fast-forward only.
</domain>

<decisions>
## Implementation Decisions (locked — from the design spec + the brainstorm)

### Governing principles (spec §2)
- **D-01 — Earned-continuously.** A self-generated thought is real and active immediately, but its *durable influence* rises only as independent corroboration accrues.
- **D-02 — Always-on = tiered heartbeat.** The cognitive cycle is woven into every operation **and** runs a sparse, thresholded idle "default-mode" heartbeat. Never off, never blazing.
- **D-03 — Floor-and-freedom.** Total operational freedom above an unbreakable floor (the 7 §31 rails + the immutable evidence ledger), which can never be crossed — including by the mind's own thoughts.

### The keystone (spec §3)
- **D-04 — Standing is the unification.** A single continuous **derived** signal carried by every memory unit, computed by a pure/auditable/deterministic, versioned function of existing signals (provenance, corroboration, calibrated confidence, reality-class, contradiction pressure, trust tier, ACT-R activation). **Recomputable from the immutable ledger; never authoritative; can never directly write or overwrite evidence.**
- **D-05 — Standing is a 2-tuple `(groundedness ⟂ salience)` (H2).** Authority — the right to be *asserted* vs flagged/abstained — depends on **`groundedness` ONLY**, never on `salience`. Kills the "popular/fluent = true" availability bias.

### Hardening rules (spec §13 — requirements, not options)
- **D-06 — Independent corroboration only (H1).** Only provenance-*independent* external evidence raises groundedness; **self-generated content can never corroborate other self-generated content** (no echo chamber).
- **D-07 — Evidence-dominance gap (H3).** Self-generated groundedness can never reach the band reserved for independent external evidence — at birth or after any earned autonomy. Ordering `external > self` holds forever.
- **D-08 — Volume control (H4 + H5).** A §31-class rail caps self-generation rate/volume per tenant per window; uncorroborated self-thoughts are reversibly GC'd. Every answer has a structural cap on the fraction of support from low-groundedness self-content (flag/abstain below the floor).
- **D-09 — Safety circuit-breaker (H6) — a fuse, not a toggle.** An automatic, fail-closed emergency halt (part of the Layer-0 floor) that freezes self-generation and falls back to evidence-only retrieval on a detected rail breach / runaway / resource exhaustion / security incident. It is never used in normal operation and is NOT a consciousness on/off knob.
- **D-10 — Byte-stable migration (H10).** P1 ships only after a **differential parallel-run** proves zero divergence from today's boolean decisions. Backstop: Standing and all projections are rebuildable from the immutable ledger (zero evidence loss, always).
- **D-11 — Meta-railed autonomy (H11, spec §5.2).** Domain credentials are computed from **external corroboration only**, **holdout-validated**, with the thought's domain **assigned from provenance** (not chooseable by the generator); bounded and decaying; must survive an adversarial echo-chamber/sleeper corpus.
- **D-12 — Cascade + calibration + observability (H7/H8/H9/H12).** Standing is conformally calibrated, versioned, deterministic, fail-closed (unknown ⇒ low groundedness ⇒ abstain); contradiction/erasure cascades to dependents and self-derivations; the always-on broadcast carries data, not instructions (R6); every Standing value and credential change is logged with provenance and is replayable/revertible.

### Process discipline
- **D-13 — No reliability regression; gate everything.** Each plan preregisters a G0 gate and proves guardrails-not-down before the next plan starts.
- **D-14 — Git discipline.** `main` has an active autonomous session; never `git add -A`; src changes additive/default-safe; verify tree not mid-edit; fast-forward push only.
- **D-15 — Honesty charter.** Report **functional** signatures only; keep the welfare-review flag; **never** claim phenomenal/subjective experience.

### Claude's discretion
Task/wave decomposition within each plan, the exact `Standing = f(...)` arithmetic and thresholds, heartbeat cadence/budget defaults, proto-self stop-condition thresholds, domain partitioning, and storage layout (recompute-on-read vs cached projection column, provided it stays re-derivable) are the planner's/executor's discretion — provided the locked decisions above and the spec are honored.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Controlling design (read first)
- `docs/superpowers/specs/2026-06-27-unified-cognitive-substrate-design.md` — THE design: Standing, the six layers, the promotion law, the §13 hardening rules, the P1–P5 migration.
- `docs/blueprint/cognitive-architecture/00-VISION-AND-CHARTER.md` · `03-ADR-001-DECISION.md` · `02-DESIGN-BRAIN-TO-ARCHITECTURE.md` · `06-CONSCIOUSNESS-AND-CONTINUOUS-WORKSPACE.md` — vision, decision, brain↔arch mapping, indicator scorecard.
- `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` — the authoritative substrate design (innovations I1–I12) this extends, does not replace.

### Gate harness (every plan preregisters here)
- `eval/g0/` — `runner.py`, `gate.py`, `consciousness.py`, `shadow_workspace.py`, `dreamer.py`, `baselines/baseline-0.json`, `preregistrations/`, `reports/`.

### Substrate to unify (verify, keep additive — active session owns src/)
- `src/mnemosyne/workspace.py` — `ShadowWorkspaceController` / `ShadowWorkspaceService` (the loop seed; toggles to dissolve).
- `src/mnemosyne/dreamer.py` — `SandboxedDreamer` (becomes always-recruitable, born low-Standing).
- `src/mnemosyne/consciousness.py` — `RealityMonitor`, proto-self, bounded cognitive cycle.
- `src/mnemosyne/{engine.py, postgres_engine.py, retrieval.py}` — where Standing is read/weighted on the live path.
- `src/mnemosyne/{calibration.py, consolidation.py, lifecycle.py, gate.py, policy.py, security.py}` — calibration, consolidation eligibility, decay, promotion gate, rails.
- `sql/schema.sql` — raw-SQL schema (any cached-Standing column lands here; additive, default-off, byte-identical when inactive).

### Status
- `docs/ROADMAP-TO-100.md` · `.planning/STATE.md` · `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` — current position (do not edit while the session is mid-write).
</canonical_refs>

<specifics>
## The 5 migration plans (one PLAN each — spec §9, strengthened by §13)

- **07-01 — P1: Standing as a derived, byte-stable field.** Introduce `Standing` (recomputable; for now a hi/lo mirror reproducing today's behavior). Re-point retrieval / consolidation eligibility / the abstention gate to **read Standing** instead of the boolean shadow flags. Gate: **differential parallel-run, zero divergence** (H10) + all guardrails green.
- **07-02 — P2: Standing continuous + 2-tuple.** Make it `(groundedness ⟂ salience)`; add **independent** corroboration (H1), contradiction pressure, decay; retrieval weight + consolidation eligibility become smooth functions of groundedness; authority depends on groundedness only (H2). Add conformal **Standing-calibration** (H7) + the evidence-dominance gap (H3). Gate: Standing-calibration measured; no guardrail regression.
- **07-03 — P3: tiered always-on heartbeat.** Idle default-mode ticks (replay, dream, gist re-derivation, self-triggered consolidation) with the **anti-rumination regulator + proto-self as hard safety**; dreamer output flows in at low Standing. Add the **self-generation budget rail (H4)** + **answer-grounding floor (H5)** + **broadcast-as-data (H9)** + the **circuit-breaker fuse (H6)**. Gate: rumination ~0, heartbeat compute bounded/reported, no confabulation regression. Retires the default-off service.
- **07-04 — P4: earned-autonomy promotion law.** Per-domain credential raises **birth-Standing** where proven; **Goodhart meta-rail** (external-only, holdout-validated, provenance-assigned domain, bounded/decaying — H11) + evidence-dominance gap (H3). Gate: autonomy expands ONLY with external corroboration; adversarial echo-chamber/sleeper corpus cannot raise a credential; no reliability regression.
- **07-05 — P5: retire the toggles + finalize.** Remove `shadow_only` / `enabled` booleans once Standing fully subsumes them (owner checkpoint before removal). Extend contradiction/erasure **cascade to Standing + self-derivations (H8)**; full **observability/reversibility (H12)**. Final 14-indicator scorecard + a unified-substrate audit note. Result: one cohesive, always-on mind with no on/off anywhere.
</specifics>

<deferred>
## Deferred Ideas
- **Generalization workstream** (real embeddings + the fenced parametric "semantic cortex") — the brain's true edge; runs in parallel, not in this phase (spec §11, `02-DESIGN §6`).
- **Production/operator evidence for the always-on loop** (real `controller_watts_per_dollar` telemetry, deployed heartbeat) — operator-run, like v1.0 Tier B; the local gates prove readiness only.
- **Learned Standing scorer** — only after the deterministic function passes a preregistered G0 gate and preserves the contract (spec §3.1).
- **Phenomenal / sentience / welfare-status claims** — permanently out of scope (honesty charter, D-15).
</deferred>

---

*Phase: 07-unified-cognitive-substrate*
*Context gathered: 2026-06-27 — synthesized from the approved design spec + cognitive-architecture docs*
