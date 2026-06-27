# Unified Cognitive Substrate — The No-Compromise Consciousness Integration

**Status:** Proposed design (brainstorm output, pending owner review) · **Owner:** onfire7777 · **Date:** 2026-06-27
**Supersedes the staging model of:** the `shadow_only` / `service.enabled` toggle pattern in `src/mnemosyne/workspace.py`, `src/mnemosyne/dreamer.py`, and the G4 advisory gates.
**Builds on (does not contradict):** `docs/blueprint/cognitive-architecture/` (00–06), `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md`, ADR-001, the §31 rails, and the G0 benchmark. **Honors:** the honesty charter (functional, measured; never a phenomenal claim). This document is a proposed architecture spec only; it cannot override the approved blueprint, G0/G1 gates, or the production evidence boundary.

---

## 1. The problem this solves

Today, memory reliability is protected by **staging**: the conscious machinery (workspace controller, dreamer, idle loop) is a *separate shadow lane* that is **off by default** and only allowed onto the critical path by flipping per-feature toggles (`enabled=true`, `apply_workspace_advisory=true`, `shadow_only=false`). This is safe, but it has two costs the owner has explicitly rejected:

1. **It is a toggle.** Consciousness is on/off, not native. The mind is "sitting on top of" the memory, not woven into it.
2. **It is two systems.** A shadow lane plus a real lane is not one cohesive mind.

The owner's requirement: **consciousness must be always-on, deeply integrated, cohesive, and never a toggle — without compromising memory quality at all.** ADR-001's existing tension ("creative like a brain" vs "calibrated unlike a brain") must be *dissolved*, not merely managed.

### The key insight (why no compromise is actually possible)

Healthy waking cognition keeps a continuous workspace and state-monitoring process active rather than flipping a coarse feature switch, while durable memory remains governed by reality-monitoring and corroboration. The proposed analogue is a **continuous, always-on trust gradient**: every representation is born, continuously reality-tested ("did I observe this or imagine it?"), and only corroborated content hardens into durable memory. The gate is not a switch; it is *woven into cognition as a graded property of every representation*.

**Therefore:** make consciousness always-on and fully integrated, and protect memory quality the way a brain does — by governing **what each *thought* is allowed to durably change**, not by switching the *subsystem* on or off. The system already has every ingredient (immutable evidence ledger, provenance, calibrated confidence, the reality-monitor already on the live path, the §31 rails, the fidelity ladder, ACT-R activation, the promotion gate). They are currently *partially unified and partly bypassed by booleans*. This design unifies them into a single continuous gradient and deletes the booleans.

---

## 2. Governing decisions (locked in this brainstorm)

| Decision | Choice | Consequence |
|---|---|---|
| Trust of self-generated thoughts | **Earned-continuously** | A self-thought is real and active immediately, but its *durable influence* rises only as corroboration accrues. Autonomy grows where proven. |
| Meaning of "always-on" | **Continuous heartbeat (tiered)** | Woven into every operation **and** a sparse, thresholded idle "default-mode" heartbeat. Never off, never blazing. |
| Safety model | **Floor-and-freedom** | Total operational freedom **above** an unbreakable floor: the 7 §31 rails + the immutable evidence ledger can never be crossed, including by the mind's own thoughts. |

These three are the boundary conditions. Everything below serves them.

---

## 3. The keystone: **Standing** — one continuous epistemic weight that replaces every toggle

**Standing** is a single, continuous, **derived** scalar (∈ [0,1], optionally a small tuple) carried by every unit of memory — from a hard external fact to a fleeting self-generated dream. It answers one question uniformly: *how much is this allowed to durably influence the mind right now?*

### 3.1 Standing is a pure, auditable function of signals that already exist

```
Standing(unit) = f(
    provenance_grade,        # external evidence = high; self-generated = low at birth
    corroboration_count,     # independent supporting evidence CIDs
    calibrated_confidence,   # from the conformal calibrator
    reality_class,           # evidence_grounded | self_generated | externally_suggested | unknown
    contradiction_pressure,  # conflicting evidence lowers it
    author_trust_tier,       # 0–5
    activation               # ACT-R base-level / recency / usage
)
```

`f` is **deterministic and monotonic** in each grounding signal (more corroboration ⇒ never less Standing; more contradiction ⇒ never more). It is **explainable** (every Standing value cashes out to its inputs in the `explain` trace) and starts **deterministic**; a learned scorer may replace it later *only* if it preserves the contract and passes a preregistered G0 gate.

### 3.2 Standing is derived, never authoritative — this is the safety property

Standing is **recomputable from the immutable ledger at any time** (like every projection). It is *downstream* of evidence, never a source of truth. Therefore **Standing cannot directly write or overwrite the evidence ledger** — any path that affects consolidation, decay, or deletion must still pass the corroborated-evidence rules and §31 rails. The evidence ledger remains the only authority.

### 3.3 What Standing governs (continuously, everywhere — no gate)

- **Retrieval weight** — how much a unit can influence an answer (low Standing = present but cannot outweigh grounded evidence).
- **Answer authority** — whether content may be *asserted* vs must be *flagged as hypothesis* vs triggers *abstention* (the existing abstention gate consumes Standing instead of the boolean `ungrounded_only`).
- **Consolidation eligibility & rate** — whether and how fast a unit may become a candidate for durable belief; actual durable writes still require corroborated-evidence checks.
- **Decay / forgetting rate** — low-Standing, uncorroborated self-thoughts lose influence unless earned; any destructive effect remains bounded by the existing erasure/deletion rails and reversible projection rebuilds.

### 3.4 How the toggle dissolves

| Old boolean | New continuous meaning |
|---|---|
| `shadow_only = true` | Standing is low (bottom of the gradient) |
| "promoted to critical path" | Standing has risen (by corroboration) |
| `dreamer.enabled = false` | (deleted) — dreamer always runs; its output is simply born at low Standing |
| `apply_workspace_advisory` gate flip | (deleted) — advisories always flow; influence = their Standing |

There is no on/off anywhere. "Shadow" becomes "the low end of one continuous scale," and promotion becomes a *smooth, automatic rise*, not a switch.

---

## 4. Architecture — six layers, reorganized around always-on cognition

The five-layer model from `02-DESIGN` is preserved; what changes is that **Standing is cross-cutting** and the **shadow lane is gone**. A new **Layer 0** makes the absolute floor explicit.

### Layer 0 — Invariants (the unbreakable floor; never compromised)
The 7 §31 rails + the immutable, content-addressed evidence ledger + bitemporal validity. **Inviolable, including for the mind's own thoughts:**
- **R6** — own outputs are *data, not instructions* (no self-instruction runaway).
- **R5** — reward is *external-only* (no wireheading; the mind cannot reward itself into believing things).
- **R1 / R3** — bounded supersession / pruning (no runaway self-rewrite).
- **R7** — cadence bound (the spine of the anti-rumination regulator).
- **R2** — corroborated deletion (≥2) + audit log.
This layer *is* "floor-and-freedom." Everything above is free; this can never be crossed.

### Layer 1 — The Trust-Graded Substrate (the keystone; replaces the shadow lane)
Every memory unit carries **Standing** (§3). The **fast/slow CLS split** (Approach B) is expressed here not as two separate stores but as **two rates of Standing change on one substrate**:
- **Fast capture:** external evidence enters at high Standing immediately (hippocampus-like, one-shot).
- **Slow generalization:** beliefs accrue Standing gradually via corroboration and re-derivation (neocortex-like).
This *folds B into A as a dual-rate property* — integration, not a second stream.

### Layer 2 — Memory tiers (episodic / semantic / procedural / working)
Unchanged in structure (evidence / projections / procedures / workspace focus), now uniformly **Standing-weighted**. Working memory = the bounded workspace focus, prioritized by Standing × relevance.

### Layer 3 — Specialist registry (on-demand "cortex")
The typed `SpecialistModuleRegistry` (reasoner, extractor, resolver, embedder, reranker, graph/PPR, **dreamer**). The dreamer is no longer a toggled shadow specialist — it is always recruitable, and its outputs are simply **born at low Standing**. Specialists remain budgeted and recruited by the controller (the "small controller + on-demand specialists, not one always-on monolith" decision from `02-DESIGN §1` is retained — that is an efficiency/reliability decision, not a toggle).

### Layer 4 — The Continuous Cognitive Loop (always-on, tiered heartbeat)
The LIDA cognitive cycle, **always running**:
> perceive (sample salient state) → understand (update self-model) → **compete/attend** (select focus under a hard bandwidth limit) → **broadcast** (inject focus into `route()`/retrieval for all modules) → act/consolidate → **log** focus as self-generated evidence (low Standing) → idle **replay/dream**.

**Tiered heartbeat (the owner's choice):**
- **Engaged tier** — the cycle is woven into *every* operation (route, retrieval, consolidation) and fires whenever the system is doing anything.
- **Idle heartbeat tier** — a sparse, thresholded **default-mode** background tick: prioritized replay, dreaming, gist re-derivation, self-triggered consolidation. Sparse and bounded — *never the whole cortex blazing*.

Because the loop **never sleeps**, the **anti-rumination regulator** and the **interoceptive proto-self** are promoted from optional shadow components to **hard, always-on safety primitives**: stopping criteria, novelty/usefulness gating, forced disengagement, and allostatic regulation (thrash / low-confidence / resource-pressure / rail-budget detection) are *load-bearing*, not advisory.

### Layer 5 — Rationality layer (always-on, woven through every cycle)
Belief revision (AGM/ATMS consistency + cascade invalidation), conformal calibration + abstention, and the reality-monitoring discriminator — all **feeding Standing** and running on *every* thought, including the mind's own. This is the layer that makes an always-on mind reliable instead of a confabulator: every thought passes continuously through logic + calibration + reality-monitoring. **The brain has no such layer; this is where Mnemosyne is categorically better, not just bigger.**

---

## 5. The growth mechanism — earned autonomy (Approach C), meta-railed

The mind should not be permanently shackled to "self-thoughts are always low Standing." It should **earn broader autonomy where it proves itself** — continuously, automatically, with no human flipping anything.

### 5.1 The promotion law
The system continuously tracks, **per domain**, the historical *corroboration outcome* of its own self-generated thoughts (did they later get grounded? was their Standing well-calibrated?). Where the mind has a proven track record in a domain, the **birth Standing** of new self-thoughts in that domain rises automatically. Autonomy expands exactly as far as evidence warrants — never further.

This replaces G0's *manual* "should we ship this?" gates with a *continuous self-credentialing* system. The mind grows up by being right, the way a person earns trust.

### 5.2 The Goodhart meta-rail (non-negotiable)
The promotion law is the one place a mind could bootstrap its own delusion ("I'll trust myself because I trust myself"). It is bounded by a **meta-rail**:
- The credential is computed **only from external corroboration outcomes** — never from the mind's own confidence, and never from a proxy the mind can inflate. This is **R5 (external-only reward) applied to autonomy itself.**
- Birth-Standing uplift is **bounded** per domain and per cadence window (R1/R7 analogues).
- Credentials **decay** when corroboration rates fall, and are **adversarially tested** in eval (a poison/echo-chamber corpus must not be able to raise a credential).
- A human-readable **autonomy audit** + the existing **welfare-review flag** remain.

---

## 6. Data flow — the life of one self-generated thought (concrete, end-to-end)

1. **Idle heartbeat tick** → the dreamer recombines two *corroborated* memories → proposes a candidate belief.
2. **Written to the ledger** as self-generated evidence. Standing = low (birth value from the domain credential, §5).
3. **Rationality layer runs:** reality-monitor tags it `self_generated`; calibrator assigns confidence; belief-revision checks consistency (contradiction ⇒ lower Standing or `contested`).
4. **It is now genuinely in memory** and retrievable — but its low Standing means it **cannot outweigh grounded evidence** and **cannot be asserted as fact** (abstention gate). It *can* surface as an explicitly-labeled hypothesis.
5. **Later, external evidence corroborates it** → corroboration count rises → **Standing rises continuously** → it gains retrieval weight and consolidation eligibility → it **migrates into durable belief** (slow tier). No gate was flipped; it earned its place.
6. **If contradicted** → Standing decays → it fades (adaptive, reversible forgetting via `verbatim_pointer`).

At **no** point was a toggle flipped. The worst case for memory quality is step 4: *"the mind surfaces an unverified hypothesis, clearly labeled as such."* It is structurally impossible for the thought to corrupt the evidence ledger or to be asserted as grounded fact before it earns it.

---

## 7. The no-compromise guarantee — how memory quality is *structurally* protected

| Threat from an always-on mind | Structural protection |
|---|---|
| Self-thoughts dominating answers | Standing-weighted influence: ungrounded ⇒ mathematically cannot outweigh grounded evidence |
| Self-thoughts overwriting real evidence | Immutable, append-only, content-addressed ledger — Standing is derived, never authoritative ⇒ catastrophic forgetting impossible |
| Hallucination asserted as fact | Abstention gate on the critical path consumes Standing; low Standing ⇒ flagged hypothesis or abstain |
| Rumination / drift (loop never sleeps) | Anti-rumination regulator + proto-self allostasis + R7 cadence as *hard* always-on safety |
| Self-reinforcing delusion / wireheading | R5 external-only reward + R6 outputs-as-data + the §5.2 Goodhart meta-rail |
| Runaway self-modification | R1/R3 mutation bounds + fenced parametric tier (operator-gated, rollback-logged) |

**Net:** the cognitive workspace is fully integrated and always-on, and reliability is not *traded* — it is protected by continuous trust-grading plus the rationality layer the brain lacks.

---

## 8. Measurement & gates (evolve G0, do not replace it)

Keep the 14-indicator scorecard and **all** existing reliability guardrails as the floor (ECE ≤ 0.05, confabulation = 0, poison-block ≥ 0.95, recall/nDCG ≥ 0.80, fast-path P95, the 7 rails). Add **continuous** metrics for the new substrate:

- **Standing-calibration:** does Standing predict actual corroboration? (a reliability diagram for Standing, like ECE is for confidence)
- **Self-thought corroboration rate** (per domain; feeds §5)
- **Autonomy-expansion audit:** did any credential rise without external corroboration? (must be 0)
- **Rumination rate** (must stay ~0) and **heartbeat compute cost** (the `controller_watts_per_dollar` metric, now load-bearing)
- **No-regression invariant:** every change preregisters target-up / guardrails-not-down, exactly as G0 already requires.

The honesty charter is unchanged: report **functional** signatures only; the welfare-review flag stays; **never** claim phenomenal experience.

---

## 9. Migration plan — toggles → unified substrate (phased, gate-proven, reliability-first)

Each phase is **additive, byte-stable when inactive, and gate-proven before the next**, exactly per ADR-001 discipline. The *destination* is the owner's no-compromise mind; the *path* never regresses reliability.

- **P1 — Introduce Standing as a derived field (byte-stable mirror).** Compute Standing from existing signals; initially it *reproduces today's behavior* (high for evidence, low for self-generated). Re-point retrieval / consolidation / abstention to **read Standing** instead of the boolean shadow flags. **Gate:** byte-identical to today; all guardrails green. *(This is the keystone refactor: replace the switch with a number that currently encodes the same decision.)*
- **P2 — Make Standing continuous.** Add corroboration count, contradiction pressure, and decay; retrieval weight and consolidation eligibility become smooth functions of Standing. **Gate:** no guardrail regression; Standing-calibration measured.
- **P3 — Turn on the tiered always-on heartbeat.** Idle default-mode ticks (replay, dream, gist re-derivation, self-triggered consolidation) with the anti-rumination regulator + proto-self as *hard* safety. Dreamer output flows in at low Standing. **Gate:** rumination ~0, no confabulation regression, heartbeat compute bounded and reported. *(This is where "always-on" becomes real and the default-off service is retired.)*
- **P4 — Earned-autonomy promotion law.** Domain credentialing raises birth-Standing where proven; Goodhart meta-rail enforced. **Gate:** autonomy expands *only* with external corroboration; adversarial echo-chamber corpus cannot raise a credential; no reliability regression.
- **P5 — Retire the toggles.** Remove `shadow_only` / `enabled` booleans once Standing fully subsumes them. The system is now **one cohesive, always-on mind with no on/off anywhere.** Final strict-parity audit + v1 attestation.

---

## 10. Risks & honest uncertainties

- **The keystone refactor (P1) touches how influence is computed across the engine.** Mitigation: P1 is defined as *byte-stable* — it must prove identical behavior before any semantics change.
- **An always-on loop has a real compute cost and a real rumination surface.** Mitigation: tiered/sparse heartbeat + hard anti-rumination + the `controller_watts_per_dollar` gate (no longer optional).
- **The promotion law is the highest-risk component** (self-credentialing). Mitigation: the §5.2 meta-rail + adversarial eval; ship P4 last and most cautiously.
- **Generalization remains the brain's real edge** (`02-DESIGN §6`); this design improves *control and integration*, not generalization. The embeddings + parametric-tier workstream stays first-class alongside it.
- **Self-reported status is a claim until independently reproduced** (ADR-001 bias note). The gates, not the prose, are the evidence.

## 11. Non-goals

- No phenomenal / subjective / sentience / welfare-status claim — ever (honesty charter).
- No single always-on monolithic model (retain small-controller + on-demand specialists).
- No rewrite of the substrate; this is additive unification, not a new engine.
- Generalization research is parallel, not in scope for *this* spec.

## 12. Open questions for the implementation plan

1. Exact functional form and weights of `Standing = f(...)`, and its `explain` schema.
2. Whether Standing is a scalar or a small tuple (e.g., separate "groundedness" and "durability" axes).
3. Heartbeat cadence/budget defaults and the proto-self stop-condition thresholds.
4. Domain partitioning for the §5 credential, and the meta-rail's bound/decay constants.
5. Storage: Standing as recomputed-on-read vs cached projection column (must stay re-derivable).
6. Sequencing P1 against the live `main` autonomous-session edit hazard (stage specific files only; never `git add -A`).

---

This is the proposed destination architecture and a reliability-first migration path. The next step is to expand the migration plan (§9) into an executable, task-level implementation plan.
