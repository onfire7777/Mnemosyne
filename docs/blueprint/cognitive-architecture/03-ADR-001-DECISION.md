# ADR-001: A cognitive‑architecture layer for Mnemosyne — objective evaluation

**Status:** Accepted (decided at owner's delegation, 2026‑06‑25)
**Date:** 2026‑06‑25
**Deciders:** onfire7777 (owner/maintainer)
**Related:** `02-DESIGN-BRAIN-TO-ARCHITECTURE.md` (the design this ADR evaluates) · lives in `docs/cognitive-architecture/`; mirrors the repo's `docs/decisions/` convention

> **Purpose of this ADR.** The prior documents in this thread were written in an affirming register. This one re‑examines the same design *objectively*, names the biases in that earlier analysis, and recommends a path. The goal — a reliable, durable agent memory that is better than human memory on the axes that matter, with as much functional "self‑awareness" as the science honestly supports — is unchanged. What changes is the rigor applied to *how* to get there.

---

## Context

We are deciding how far to extend Mnemosyne (a working local‑first memory engine: immutable evidence ledger, projections, consolidation, calibration, §31 rails) toward a brain‑inspired "cognitive architecture" with an always‑on workspace controller and a "simulation of consciousness."

Three forces are in tension:

1. **Reliability vs. generativity.** The stated goal prizes reliability, logic, and freedom from bias. Several proposed additions (generative "dreaming," an always‑on self‑narrating loop) *increase* the surface for hallucination and drift. These pull in opposite directions; both cannot be maximised at once.
2. **Ambition vs. shippability.** "No‑compromise eclectic synthesis" (adopt every good idea from SOAR, ACT‑R, LIDA, CLS, predictive coding, GWT, conformal prediction, AGM/ATMS…) is, from an engineering standpoint, a scope‑and‑integration risk. More moving parts means more ways to fail and a longer path to anything validated.
3. **Measurable engineering vs. unfalsifiable goals.** "Better than the brain" and "simulation of consciousness" are not, as stated, measurable. Without metrics, they cannot guide or validate design decisions.

### Three biases in the prior analysis (named, so they can be corrected)

- **Scorecard category error.** "Mnemosyne already beats the brain on ~half the elements" overstates the achievement. Immutability, provenance, auditability, and no‑catastrophic‑forgetting are **database properties** — a plain filesystem also "beats the brain" at them. They are real and valuable, but they are *not* the hard part of memory. The hard parts — flexible generalisation, abstraction, robust associative retrieval, grounding — are where the brain still dominates. The honest scorecard is: *Mnemosyne wins the bookkeeping; the brain wins the cognition.*
- **Neuro‑inspiration as decoration.** Naming a pass `replayer` or mapping evidence→hippocampus does not guarantee the underlying computational function is captured. Some borrowings are load‑bearing (CLS fast/slow split, prioritised replay, prediction‑error‑gated encoding, the global‑workspace bottleneck). Others are largely analogy. The two should not be given equal weight.
- **"Consciousness" as an objective.** Treating "simulation of consciousness" as a design driver is the weakest part of the plan. The phenomenal part is untestable; the functional part (global workspace, self‑model) is buildable but its **value to the actual product — memory quality — is unproven**. Complexity justified by a philosophical aim, rather than a measured capability gain, is exactly what an objective review should flag.

---

## Decision (accepted) — Option E: the whole vision, built reliability‑first and metric‑gated

Decided here at the owner's delegation. **Build the entire cognitive architecture as the destination — nothing in the vision is dropped — but execute it as a sequence of metric‑gated stages with reliability as a non‑negotiable invariant.** This is the genuinely *no‑compromise* choice: it sacrifices neither the ambition (Option B's ceiling) nor the rigor (Option D's discipline). The only thing given up is building everything blindly at once — which is a failure mode, not a value.

Framing: **a research vehicle held to product‑grade verification.** Treat the project as the moonshot it is, but require every layer to earn its place with a benchmark win before the next is built.

Three standing principles follow:
1. **Reliability is the invariant.** Generativity ("dreaming," the self‑loop) is always sandboxed, low‑trust, and gate‑promoted; it never sits on the critical path to an answer.
2. **"Consciousness" is operationalised, not abandoned.** The target becomes measurable *autonomy + metacognition* (self‑triggered consolidation quality, anticipatory retrieval, calibrated self‑monitoring). The functional vision is pursued in full; the unmeasurable phenomenal claim is simply never made.
3. **Generalisation is a first‑class workstream**, advanced at every stage alongside the control layer — it is the brain's real advantage and the true capability ceiling.

This corresponds to a synthesised **Option E = Option B's destination via Option D's discipline** (added to the options below).

---

## Options considered

### Option A — Reliability‑only increments (no cognitive layer)
Tune what exists: multi‑signal write priority, prediction‑error‑gated consolidation, reality‑monitoring tags, retrieval‑strengthening.

| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | Low |
| Reversibility | High (all additive) |
| Risk | Low |
| Capability ceiling | Moderate — better store, not a "mind" |

**Pros:** cheap, safe, ships, each item independently testable. **Cons:** does not pursue the autonomy/"self‑awareness" goal at all.

### Option B — Full cognitive architecture now (the v2 proposal, incl. always‑on workspace loop)
Build the controller, specialist registry, generative replay, and self‑model loop together.

| Dimension | Assessment |
|---|---|
| Complexity | High |
| Cost | High (always‑on compute + ops) |
| Reversibility | Low once the loop is load‑bearing |
| Risk | High — drift, rumination surface, integration |
| Capability ceiling | Highest (if it works) |

**Pros:** directly targets the vision; the most novel/interesting. **Cons:** large unvalidated bet; generativity fights the reliability goal; "consciousness" framing is unmeasurable; heavy for a solo maintainer; easy to over‑engineer and never finish.

### Option C — Monolithic always‑on large model
A single big model runs continuously and does everything.

| Dimension | Assessment |
|---|---|
| Complexity | Medium |
| Cost | Very high (always‑on heavy compute) |
| Reversibility | Medium |
| Risk | Very high — confabulation, drift, uncontrollable |
| Capability ceiling | Unclear |

**Rejected** — contradicts both brain energetics (sparse, thresholded activation) and every cognitive‑architecture precedent; and it is the *least reliable* option. Listed for completeness.

### Option D — Reliability‑first, phased, metric‑gated (recommended)
Option A now, plus the specialist registry; the workspace loop and generative replay are built **only after** Phase‑1 upgrades demonstrate measured wins and only behind ablation evidence.

| Dimension | Assessment |
|---|---|
| Complexity | Low→High, incremental |
| Cost | Scales with proven value |
| Reversibility | High at each gate |
| Risk | Controlled (each layer validated before the next) |
| Capability ceiling | Highest, reached safely |

**Pros:** pursues the full vision without a blind bet; every layer earns its place; reliability stays primary. **Cons:** slower to the "wow"; requires discipline to hold the gates and to build benchmarks first.

### Option E — CHOSEN: B's destination via D's discipline (synthesis)
Commit to the complete architecture (Option B's ceiling) and execute it through Option D's metric‑gated sequence. Ambition and rigor both at maximum; only "build it all at once, unvalidated" is given up.

| Dimension | Assessment |
|---|---|
| Complexity | High, but sequenced and reversible per gate |
| Cost | Scales with proven value |
| Reversibility | High at every gate |
| Risk | Controlled — each layer validated before the next |
| Capability ceiling | Highest, reached without a blind bet |

**Pros:** no compromise on vision *or* reliability; always shippable; failures caught cheaply. **Cons:** demands the discipline to hold the gates and to build benchmarks before features.

---

## Trade‑off analysis

- **Reliability vs. generativity is a real frontier, not a free lunch.** "Creative like a brain" and "calibrated unlike a brain" trade off. Given the stated goal (no bias, no illogic, reliable), reliability should be the dominant objective and generative replay should be **off the critical path** — a gated, sandboxed producer whose outputs are low‑trust until corroborated. The earlier "no‑compromise, have‑both" framing understated this tension.
- **The genuinely hard problem is under‑addressed.** The brain's real advantage is sample‑efficient generalisation. The proposal mostly adds *control* machinery (workspace, scheduling, monitoring) and storage discipline; it does comparatively little for generalisation, which is the capability gap that actually limits a memory system. Embeddings + the parametric tier are the relevant levers and deserve more weight than the consciousness loop.
- **"Consciousness" is the wrong success criterion; autonomy and metacognition are the right ones.** Reframed objectively, the workspace loop is worth building *iff* it measurably improves: (i) continual consolidation quality without supervision, (ii) anticipatory retrieval, (iii) calibrated self‑monitoring. If it does, it's valuable regardless of any consciousness interpretation. If it doesn't, the consciousness framing is not a reason to keep it.
- **Steel‑man for Option B.** If Mnemosyne is a **research vehicle** (exploring machine cognition) rather than a **product** (shipping reliable memory), the eclectic, ambitious build is legitimate and the "earn‑each‑layer" discipline matters less than breadth of exploration. This product‑vs‑research distinction is the single biggest variable in the decision — see Consequences.
- **Self‑reported status is unverified.** The "~82% complete, 6/6 SLOs" figures come from the project's own wiki and have not been independently reproduced here. Treat them as claims, not evidence, when planning.

---

## Consequences

**The deciding variable is product vs. research:**
- **If product (ship a reliable agent memory):** choose **Option D**. Reliability‑first, consciousness reframed as measurable autonomy, workspace loop gated. The "beat the brain" story becomes "a memory that is auditable, calibrated, and continually self‑maintaining" — defensible and testable.
- **If research vehicle (explore machine cognition / a personal moonshot):** **Option B** is defensible *provided* metrics and ablations are still built, so results are interpretable rather than anecdotal.

**Easier under the recommendation:** incremental validation; lower near‑term cost/ops; honest external claims; reversibility at each step.
**Harder:** the vision is deferred and must prove itself; requires building benchmarks before features; demands resisting the "add everything" pull.
**To revisit:** after Phase‑1 metrics land — does background autonomy beat passive consolidation on quality‑per‑cost? Only then commit to the workspace loop.

---

## Success metrics (turn "better than the brain" into numbers)

No upgrade is accepted without moving one of these against a frozen baseline, via ablation:

- **Retrieval quality:** recall@k, nDCG@k (incl. the hard multi‑hop set the wiki flags as weak).
- **Calibration:** ECE; abstention precision/recall.
- **Continual learning:** interference / forgetting curve across sequential tasks (the catastrophic‑forgetting axis).
- **Faithfulness:** confabulation/hallucination rate = answers unsupported by provenance.
- **Cost/latency:** P95 read; always‑on compute watts/$ for the controller.
- **Workspace‑loop‑specific gate:** does self‑triggered background consolidation improve retrieval/calibration **per unit compute** vs. on‑demand consolidation? If not, do not ship it.

---

## Risks & open questions

- **Over‑engineering / never‑shipping** from eclectic scope. *Mitigation:* the metric gates of Option D.
- **Generativity regressing reliability.** *Mitigation:* keep generative replay sandboxed, low‑trust, gate‑promoted only.
- **Neuro‑inspiration theater.** *Mitigation:* require each "brain‑inspired" feature to cash out as a metric win, not a naming analogy.
- **Anthropomorphism risk.** A self‑narrating loop invites over‑attribution of "understanding"/"experience" by users and by the builder. *Mitigation:* the design already forbids phenomenal claims; keep that explicit in any UX and documentation.
- **Verification debt.** The project's quality claims are self‑reported; independent benchmarks are a prerequisite, not an afterthought.

---

## Action items (gated program — full execution plan in design doc §7)

Framing is **decided**: research vehicle, product‑grade verification. Sequence:

- [x] **G0 — Benchmarks first (blocking).** Implemented at repo root `eval/g0/`: harness + frozen baseline for recall@k / nDCG@k (incl. hard multi‑hop), ECE + abstention precision/recall, continual‑learning interference, confabulation rate (answers unsupported by provenance), P95 latency, paid-provider cost, and controller watts/$ when explicit telemetry is supplied. No feature ships without an ablation win here.
- [ ] **G1 — Reliability core.** Multi‑signal write priority; prediction‑error‑gated consolidation; reality‑monitoring tags wired to abstention; retrieval‑strengthening; schema fast‑path (`contested` for uncorroborated‑but‑congruent).
- [ ] **G2 — Structure + generalisation.** Refactor `providers` → typed **specialist‑module registry**; advance embeddings + the fenced parametric "semantic cortex"; meta‑d′ self‑monitoring.
- [ ] **G3 — Generative replay, sandboxed.** Low‑trust recombination, gate‑promoted only; must not raise the confabulation rate.
- [ ] **G4 — Always‑on workspace controller.** Behind a written go/no‑go: self‑triggered background autonomy must beat on‑demand consolidation on quality‑per‑unit‑compute, or it does not ship. Anti‑rumination regulator bound to R7.
- [ ] Independently reproduce the headline SLOs before citing them.
- [ ] Keep the phenomenal‑consciousness claim out of all docs and UX; report only measured functional signatures.
