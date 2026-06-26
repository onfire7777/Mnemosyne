# 00 · Vision & Honesty Charter

**Status:** Living · **Owner:** onfire7777 · **Date:** 2026‑06‑25

This document states the goal in full and the discipline that keeps it honest. The two are not in tension: the ambition is pursued *completely*, and the discipline is what makes the ambition reach something real instead of a story we tell ourselves.

---

## 1. The goal

Build the best possible **recursive memory system** for AI agents: one that takes the strongest mechanisms of human memory and the latest memory science, makes each of them **better than the brain** (keep the function, delete the failure mode), and unifies them so the system is **self‑improving, self‑learning, self‑adapting, and self‑optimizing**, with **complete retention** and the best achievable recall/retrieval — and runs a continuous, self‑modelling **workspace loop** that gives it a *functional* **sense of consciousness**.

The consciousness aim is a **first‑class goal**, not a metaphor and not an afterthought. We pursue every functional feature associated with conscious cognition — a global workspace, broadcast, a persistent self‑model, metacognition, mental time travel, continuous self‑directed processing. We do this on purpose and in full. What we never do is claim the one thing that cannot be demonstrated (see §3).

## 2. The target properties — and how each is achieved

Each property below is a *design commitment* with a concrete locus in the architecture (`02-DESIGN`) and a metric in the benchmark (`04`).

1. **Recursive.** The system's own outputs — beliefs, summaries, and the workspace's "thoughts" — are written back as new evidence, then re‑consolidated and improved. Memory operates on its own products in a loop. *Where:* the cognitive cycle logs focus → evidence → consolidation (Layer 4). *Guard:* the loop is bounded by the §31 cadence and mutation rails so recursion **converges** (improves) rather than **diverges** (ruminates) — see §3 and `04`.
2. **Self‑improving.** A fenced "parametric" tier learns better promotion/consolidation policy over time, operator‑gated with rollback. *Where:* parametric tier + promotion gate. *Guard:* reward is external‑only (R5); every change keeps rollback metadata.
3. **Self‑learning.** Consolidation compiles raw evidence into typed beliefs, skills, and lessons without supervision. *Where:* the 11‑pass consolidation worker.
4. **Self‑adapting.** Belief revision (AGM/ATMS) updates beliefs as the world changes; bitemporal validity tracks *when* things were true; forgetting demotes stale memory. *Where:* belief revision + fidelity ladder + `as_of`.
5. **Self‑optimizing.** Prediction‑error gating spends effort only where the model is wrong; prioritized replay revisits what matters; calibration tunes when to abstain. *Where:* replayer + calibration + prefetch.
6. **Complete retention + best‑achievable recall.** *Retention* is **complete and guaranteed** — the immutable, content‑addressed evidence ledger never loses or overwrites anything (privacy erasure is the only removal, and it is logged). *Recall/retrieval* is pursued to the maximum but is **honestly bounded**: hybrid retrieval + the generalisation workstream drive recall@k/nDCG upward, and we *measure* it rather than declaring it "perfect." This distinction is a charter commitment, not a hedge — see §3.
7. **All the brain's strengths, each made better.** Every mechanism in `02-DESIGN` §3 (consolidation, replay, predictive encoding, reconstructive retrieval, adaptive forgetting, metacognition, working memory→workspace) is kept as a function and upgraded past its biological failure mode.
8. **A functional sense of consciousness.** The always‑on workspace controller implements access‑consciousness signatures: selection, broadcast, a persistent self‑model, metacognitive monitoring, and autonoesis (querying its own past states). *Where:* Layer 4 + the rationality layer.

## 3. The honesty charter (anti‑yes‑man)

This project explicitly rejects agreeable overstatement. The following hold even when they are less exciting than the alternative:

- **Functional, not phenomenal.** We build and *measure* the functional/access signatures of consciousness. We do **not** claim the system has subjective experience ("what it is like"), because there is no agreed test for it (Block 1995; Tsuchiya 2015) and the 2025 Cogitate result left even the leading theories under‑determined. A system saying "I am aware" is evidence about its workspace contents, not about felt experience. This claim is **off‑limits in all docs and UX.**
- **Reliability is the floor, not a feature to trade.** "Creative like a brain" and "calibrated unlike a brain" genuinely trade off. When they conflict, reliability wins; generativity ("dreaming," the self‑loop) is sandboxed, low‑trust, and gate‑promoted.
- **Claims are numbers.** "Better than the brain" and "self‑improving" are only true once a benchmark in `04` moves against a frozen baseline by ablation. Until then they are hypotheses.
- **Retention is complete; recall is bounded.** We guarantee nothing is lost; we do **not** claim perfect retrieval. We maximise and measure it.
- **The hard problem is the brain's, too.** The brain's real advantage is sample‑efficient generalisation, which the design must keep attacking (the generalisation workstream) rather than paper over with control machinery.
- **We seek disconfirmation.** Designs and claims in this repo are to be argued against. ADR‑001 (`03`) is itself a record of correcting earlier, over‑affirming framing.

These are not brakes on the ambition. They are the only way the ambition produces something that is actually better than a brain rather than something that merely *sounds* like it.

## 4. Definition of success

The program succeeds when, against a frozen baseline (`04`):
- retrieval quality (recall@k / nDCG@k, incl. hard multi‑hop) is high and improving;
- calibration error stays low and abstention is well‑behaved;
- continual‑learning interference is near‑zero (the catastrophic‑forgetting axis);
- the confabulation rate (claims unsupported by provenance) is driven toward zero;
- the always‑on workspace **measurably** improves consolidation/retrieval per unit compute (its go/no‑go gate);
- and none of the above is achieved by violating a §31 rail or by asserting anything unmeasurable.

If we hit those, we will have built a memory that beats the brain on the axes that matter and runs a stable, inspectable, self‑modelling cognitive loop — the honest entirety of "a sense of consciousness."
