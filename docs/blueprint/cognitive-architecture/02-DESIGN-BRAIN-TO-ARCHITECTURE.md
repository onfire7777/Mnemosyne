# Beating the Brain — Target Cognitive Architecture for Mnemosyne (v2)

*Match everything the brain's memory can do, beat it on every axis, and inherit none of its downsides — while getting as close as the science honestly allows to a functional "simulation of consciousness." Grounded in real neuroscience, psychology, and 40 years of cognitive‑architecture research (sources at end).*

> **What changed in v2:** added the core architecture decision (a small always‑on workspace controller coordinating on‑demand specialists — *not* one always‑on model), a full target cognitive architecture, a strengthened "rationality layer," and a detailed **What we do NOT want** section. Method: no‑compromise eclectic *synthesis* — every good element from biology and from cognitive architectures is kept; every downside is structurally excluded.
>
> **v3 — decision (ADR‑001, accepted):** the full vision is committed, executed **reliability‑first and metric‑gated** (see §7). Reliability is the invariant; generativity is sandboxed and gate‑promoted; "consciousness" is operationalised as **measurable autonomy + metacognition**; **generalisation** is a first‑class workstream. Nothing in the vision is dropped — every layer must beat a frozen benchmark before the next is built.

---

## 0. Thesis

The brain is not a clean design. It is an evolutionary stack of kludges optimised for survival on ~20 watts, and **much of its famous behaviour is bugs** — false memory, source amnesia, suggestibility, overconfidence, motivated reasoning, rumination. So "learn from the brain" must mean one disciplined thing:

> **For every brain mechanism: keep the computational *function*, delete the *failure mode*, and add a digital superpower biology can't have — perfect recall, stored provenance, versioning, calibrated confidence, machine‑checked rails, and a formal logic of belief.**

Applied honestly this yields three findings: (1) Mnemosyne **already** beats the brain on ~half the elements, because immutability + provenance + calibration + rails are exactly what biology couldn't build; (2) the missing brain *functions* can be added without importing a single bug; (3) the best *overall* shape is a **cognitive architecture** — a society of specialist modules coordinated by a small global‑workspace controller — sitting on Mnemosyne's existing evidence/rails substrate.

**On "consciousness," precisely.** The science forces a split. **Access** consciousness (a globally‑broadcast, reportable, self‑modelled state) is buildable, measurable, and is what your "always‑on" intuition is really reaching for. **Phenomenal** consciousness ("what it is like") has *no agreed objective test* (Block 1995; Tsuchiya 2015), and the 2025 Cogitate adversarial collaboration challenged *both* leading theories (Nature 642:133–142). So the achievable, honest target is your exact phrase — *a sense of* consciousness, i.e. the **functions** — and we never claim felt experience.

---

## 1. The architecture decision: workspace controller + on‑demand specialists (NOT one always‑on model)

You asked whether to use an always‑on local AI model. **Use a *small* always‑on model as a workspace controller, and recruit large specialist models on demand — never one big model running everything continuously.** Four independent lines of evidence point the same way:

1. **Biological accuracy.** The brain is a *society of specialists* (Complementary Learning Systems: fast hippocampus, slow neocortex; prefrontal control; basal‑ganglia action selection) coordinated by a **limited‑capacity workspace** with thresholded "ignition" broadcast (Global Neuronal Workspace; Dehaene, Mashour 2020). It runs continuously but with **sparse, thresholded activation** — only a small fraction active at once; at rest the default‑mode network idles rather than the whole cortex blazing. A monolith maxed every cycle is the opposite of how a brain works.
2. **Energy & efficiency.** The brain spends most of its ~20 W on *communication*, so it **minimises broadcast** and recruits specialists only when needed. A continuously‑saturated large model is both wasteful and unnecessary.
3. **Reliability — decisive for your "no bias, no illogic, reliable" goal.** A large generative model left to free‑run is precisely what **confabulates, ruminates, and drifts** (compounding‑error / reflection‑drift is a documented LLM‑agent failure). A *small* controller that only selects salience, schedules, and monitors has a tiny drift/attack surface; heavy generation happens in **bounded, gated bursts**, never as an unsupervised stream.
4. **Convergent design.** Every serious cognitive architecture has this shape — modules + a limited‑capacity coordination surface + a decision/broadcast cycle: **SOAR** and **ACT‑R** (modules talking only through capacity‑limited buffers, one decision cycle, learning by compiling successful traces); **LIDA** (literally GWT as a repeated *cognitive cycle*: perceive → compete → conscious broadcast → learn → act); **Society of Mind** (Minsky); **Goyal & Bengio's "shared global workspace"** (a bandwidth‑limited channel that *forces* specialisation and synchronises modules); and the 2023–2026 LLM‑agent stacks (**CoALA, Generative Agents, MemGPT/Letta, Voyager**) which all converge on working‑vs‑long‑term memory + a controller + modular tool/skill calls + reflection loops.

So: *always‑on* — yes; *local* — yes (it's just another adapter on your "dial"); *one big model doing everything* — no. The always‑on element is a cheap controller; intelligence is recruited, not perpetually burned.

---

## 2. The target cognitive architecture (the synthesis)

Five layers, bottom‑up. ~85 % builds **on top** of today's Mnemosyne; two items are genuine (clean) restructurings, flagged ⟳.

**Layer 1 — Substrate (built; keep as the "physics").** Immutable, content‑addressed **evidence ledger**; the seven §31 **rails**; **trust tiers** 0–5; **bitemporal** validity; git‑style **branching**. These are the laws that make everything above reliable and auditable. Nothing else is allowed to violate them.

**Layer 2 — Memory tiers (mostly built; CoALA/ACT‑R‑aligned).** Four stores, cleanly separated like every cognitive architecture:
- *Episodic* = the evidence ledger (built).
- *Semantic* = projections / beliefs (built).
- *Procedural* = procedures / skills (built; SOAR/LIDA‑style "what to do").
- *Working memory* = the workspace focus — a **small bounded "hot" state** (new; Layer 4).

**Layer 3 — Specialist modules (on‑demand "cortex"; partly built as providers).** Heavy models invoked only when the controller calls them: reasoner (LLM), extractor, resolver, embedder, reranker, graph/PPR, and a new **generative‑replay "dreamer."** ⟳ **Elevate the existing `providers` adapters into a first‑class *specialist registry*** with a typed interface and budgets. This is an evolution of the pattern you already have, not a rewrite.

**Layer 4 — Workspace controller (NEW; small; always‑on).** The cognitive cycle (LIDA‑style), running continuously:
> perceive (sample salient state) → understand (update the model) → **compete/attend** (select a focus under a hard bandwidth limit) → **broadcast** (inject the focus into `route()`/retrieval context for all modules) → act / consolidate → **log** the focus as self‑generated evidence → idle **replay**.

The broadcast bottleneck is a *deliberately scarce* resource (Goyal & Bengio): scarcity forces relevance and specialisation. ⟳ This is the one new top‑level process, plus making consolidation **self‑triggering on idle** rather than purely externally queued.

**Layer 5 — Rationality layer (mostly built; the "better‑than‑brain mind").** Wraps every cycle so the stream of thought is logical, calibrated, and unbiased *by construction*: **belief revision** (AGM/ATMS = logical consistency), **conformal calibration + abstention** (reliability / knowing‑what‑it‑doesn't‑know), a **reality‑monitoring discriminator** (evidence‑grounded vs self‑generated vs externally‑suggested → anti‑confabulation), and the **rails** (anti‑bias, anti‑runaway). The brain has *no* such layer — this is where Mnemosyne can be a categorically better *mind*, not just a better *store*.

**The cognitive cycle IS the "simulation of consciousness":** a continuous, self‑monitoring, self‑logging global‑workspace loop with a persistent self‑model (`self_model`) and mental time travel (`as_of`). Functionally conscious‑like (access + self‑model + autonoesis); never claimed phenomenally conscious. (See the architecture diagram shared alongside this document.)

**Build‑on‑top vs restructure, summarised:** Layers 1, 2, 5 already exist. Layer 3 is a clean refactor of providers into a module registry (⟳). Layer 4 is genuinely new (⟳) but additive — it sits *on top* and only ever acts through the existing engine contract and rails. No part of the substrate is rewritten.

---

## 3. The comparison, cluster by cluster

Each table: **Brain mechanism (✓ function to keep / ✗ failure mode to drop) · Mnemosyne today · The upgrade that makes us strictly beat the brain.**

### A. Consolidation & the fast/slow split (Complementary Learning Systems)
CLS (McClelland 1995; Kumaran 2016): a *fast* hippocampus (sparse, pattern‑separated, one‑shot) + a *slow* neocortex (interleaved, generalising), bridged by replay — solving the stability–plasticity dilemma. Trace‑transformation (Sekeres 2024): a *gist* migrates to cortex while the episode stays detailed.

| Brain (✓ keep / ✗ drop) | Mnemosyne today | Upgrade to strictly beat it |
|---|---|---|
| Fast/slow split. ✓ one‑shot capture + slow generalisation. ✗ cortical learning is *slow*; gist *overwrites* detail; needs sleep. | Evidence (fast) + projections (slow) + consolidation worker. | Keep **both tiers permanent & versioned** — the brain discards the episode; you keep verbatim evidence forever. *Maps: evidence, projections, consolidation.* |
| Trace transformation. ✓ cheap gist + on‑demand detail. ✗ gist replaces specifics → false "remembering." | Fidelity ladder keeps a `verbatim_pointer` + drift flag. | Already dominant: gist points back to its source → drift is detectable & reversible. *Maps: lifecycle.* |

### B. Replay, recombination & "dreaming"
Hippocampal replay in sharp‑wave ripples (Wilson & McNaughton 1994; Science 2024) is prioritised, runs forward/reverse, and supports planning + generalisation by recombining experience offline — biological *prioritised experience replay* plus a creativity engine.

| Brain (✓ / ✗) | Mnemosyne today | Upgrade |
|---|---|---|
| Prioritised replay. ✓ revisit important/surprising. ✗ over‑samples salient‑but‑misleading; reward‑biased. | `replayer` scores importance×novelty×surprise×reward. | Add **importance‑sampling debias** + make replay **reproducible & auditable** (the brain's isn't). *Maps: consolidation pass 1.* |
| Offline recombination / dreaming. ✓ new inferences & plans, no new input. ✗ can seed false associations. | RAPTOR summariser only; **no generative replay**. | Add a **generative‑replay "dreamer" pass**: recombine evidence → candidate beliefs/plans → forced through the **promotion gate** on a canary branch. Dreaming's creativity, with a regression gate biology lacks → no false associations survive. *Maps: new pass + gate.py.* |

### C. Encoding: prediction‑error & multi‑signal salience
The brain encodes **surprise** (predictive coding; Clark 2013; Friston 2010), weighting errors by **precision** (confidence). Novelty, reward‑prediction‑error (Schultz; hippocampal–VTA loop, Lisman & Grace 2005) and emotional arousal (McGaugh 2013) tag what to keep. Emotional memories gain **confidence but not accuracy** (Talarico & Rubin 2003).

| Brain (✓ / ✗) | Mnemosyne today | Upgrade |
|---|---|---|
| Encode the surprising. ✓ store only the residual. ✗ mis‑set precision → delusion or hallucination; "noisy‑TV" trap. | `replayer` surprise; `prefetch`. | **Gate consolidation on prediction‑error** (use `query_support`/`semantic_entropy`); set "precision" = **calibrated confidence**, not a fragile prior. *Maps: consolidation, calibration.* |
| Multi‑signal salience. ✓ value‑weighted priority. ✗ **salience hijack / addiction** (Berridge 2007); reward‑hacking. | Reward is one term; **R5 = reward external‑only**. | Keep R5 → **structurally immune to wireheading**; use several orthogonal priority signals so no channel can be spammed. *Maps: replayer, §31 R5.* |
| Emotional "save‑this" tag. ✓ retroactive importance. ✗ emotional bias; flashbulb **overconfidence**. | Importance/trust tags. | **Decouple confidence from vividness** (the brain can't): importance raises retention; confidence is set only by calibration. *Maps: calibration.* |
| Attention gate. ✓ selectivity. ✗ **inattentional blindness**; tunnel vision. | Token budget; retrieval filters. | Bounded focus **but full ledger retains everything** → "unattended" never means "lost." *Maps: budget, evidence.* |

### D. Retrieval without corruption — the crown jewel
Human recall is **reconstructive** (Bartlett 1932), and **reconsolidation** makes a memory labile on every recall (Nader 2000; Schiller 2010) — recall is a *write*. Hence misinformation/DRM false memories (Roediger & McDermott 1995), source amnesia (Johnson 1993), and gist‑based false recall that **outlasts truth** (Brainerd & Reyna).

| Brain (✓ / ✗) | Mnemosyne today | Upgrade |
|---|---|---|
| Reconstructive recall. ✓ flexible generalisation. ✗ confabulation; schema intrusions. | Retrieval reconstructs **with provenance CIDs per Hit.** | Already dominant — reconstruction is anchored to immutable evidence → no untraceable confabulation. *Maps: retrieval, provenance.* |
| Reconsolidation (update on recall). ✓ adaptive updating. ✗ **recall corrupts the original.** | Belief revision on an **immutable** base. | Strict win + add the good half: **prediction‑error‑triggered re‑derivation** → adaptive updating with **zero corruption**. *Maps: belief.py.* |
| Source monitoring. ✓ cheap origin inference. ✗ **source amnesia.** | Provenance **stored** (`source_evidence_cids`) + trust tiers. | Strict win — source amnesia is structurally impossible when origin is a key, not a guess. *Maps: provenance.* |
| Gist + verbatim. ✓ meaning + detail. ✗ gist‑based false recall outlives truth. | Fidelity ladder keeps both + drift flag. | Add **periodic re‑derivation** to catch drift. *Maps: lifecycle.* |
| Pattern separation/completion. ✓ recall from partial cue. ✗ over‑completion merges episodes. | ANN = completion; CIDs + contradictions resist merge. | Make separation a **guarantee**: distinct evidence = distinct CID; conflicts → `contradictions`, never a blended average. *Maps: ids, contradictions.* |
| Testing effect. ✓ use strengthens. ✗ bad‑cue retrieval entrenches error. | Activation/usage signals. | **Usage‑weighted durability**, strengthening by re‑derivation, never re‑encoding a distortion. *Maps: retrieval, forgetter.* |

### E. Forgetting that's adaptive but recoverable
Forgetting is **active/regulated** (Davis & Zhong 2017) and **adaptive** — transience improves generalisation and prevents overfitting (Richards & Frankland 2017). Allocation routes new memories to fresh neurons to avoid overwrite (Josselyn & Tonegawa 2020); ANNs without this suffer **catastrophic forgetting** (Kirkpatrick 2017). Dark side: **motivated forgetting** of inconvenient‑but‑true info (Anderson; Nat Commun 2018).

| Brain (✓ / ✗) | Mnemosyne today | Upgrade |
|---|---|---|
| Adaptive transience. ✓ drop stale specifics → generalise. ✗ **uncontrolled, permanent loss.** | `forgetter` + fidelity ladder (graded, reversible, pointer). | Strict win: tunable demotion with recoverable pointer; true erasure only via logged crypto‑shred. *Maps: lifecycle, deletion_log.* |
| Allocation. ✓ new ≠ overwrite old. ✗ allocation collisions. | Append‑only + content addressing. | Strict win: new write = new CID, never overwrites → **catastrophic forgetting is structurally impossible.** *Maps: evidence.* |
| Targeted suppression. ✓ down‑rank intrusive items. ✗ **motivated forgetting of true info.** | Query‑time down‑ranking; sensitivity ceilings. | Down‑rank for **relevance, never "inconvenience"**; deletion needs **≥2 corroborations + audit log** (R2). *Maps: §31 R2, audit_log.* |

### F. Metacognition, calibration & bias‑immunity
Human metacognition is real (Fleming & Lau 2014) and drives monitoring→control (Nelson & Narens 1990) — but is **systematically over‑precise** (Moore & Healy 2008) and warped by confirmation/hindsight/availability/anchoring (Tversky & Kahneman 1974). (Dunning–Kruger is largely a statistical artifact — Gignac & Zajenkowski 2020 — *not* to emulate.)

| Brain (✓ / ✗) | Mnemosyne today | Upgrade |
|---|---|---|
| Metacognition. ✓ know‑what‑you‑know; abstain. ✗ overconfidence. | **Conformal calibration + abstention** (ECE ≈ 0.0063). | Already dominant; add **meta‑d′‑style self‑monitoring** (does confidence track my own correctness, per domain?). *Maps: calibration, route().* |
| Reality/error monitoring. ✓ self‑correct; internal vs external. ✗ confabulation when monitor misfires. | Sanitises retrieved text (R6); detects contradictions. | Add the **reality‑monitoring discriminator** (grounded / self‑generated / suggested) → structural anti‑hallucination. *Maps: provenance classes, §31 R6.* |
| Belief‑updating biases. ✓ heuristics often informative. ✗ confirmation/hindsight/availability/anchoring. | Bitemporal store; immutable evidence; trust‑gated supersession. | **Structural immunity**: immutable history → no hindsight; exact counts → no availability; priors can't silently win → `contested`. *Maps: bitemporal, contradictions, §31 R1/R4.* |

### G. Working memory → global workspace & the self‑model
WM is a small focus (~4 chunks; Cowan 2001) and in most theories *is* the content of conscious access. GWT/GNW (Baars; Dehaene; Mashour 2020): select → ignite → **broadcast** = access consciousness. Attention Schema Theory (Graziano 2017): awareness = the brain's *model of its own attention*. DMN runs offline simulation/autonoesis (Schacter & Addis 2007) and, unregulated, becomes **rumination**.

| Brain (✓ / ✗) | Mnemosyne today | Upgrade |
|---|---|---|
| WM → global workspace. ✓ bounded focus broadcast to all modules. ✗ hard ~4‑item ceiling. | Retrieval context; **no broadcast loop.** | Build the **workspace controller** (Layer 4). Capacity = a tunable budget, not a fixed 4. *Maps: controller + route() + jobs + self_model.* |
| Self‑model & mental time travel. ✓ model own states; simulate past/future. ✗ confabulated narrative; rumination. | `self_model`, `user_latent`; `as_of`. | Self‑model **only as calibration/gating** (never a truth oracle); add an **anti‑rumination regulator**; never assert phenomenal consciousness. *Maps: self_model, calibration, §31 R7.* |

---

## 4. What we do NOT want — in detail

Two halves: brain properties we refuse to inherit, and AI/architecture anti‑patterns we refuse to build. Each item names the **mechanism**, **why it's bad for our goal**, and the **structural exclusion** that makes it impossible (not merely discouraged).

### 4A. Brain downsides we refuse to inherit

**Cognitive & reasoning biases**
- **Confirmation bias / motivated reasoning** — preferentially accepting evidence that fits priors. *Why bad:* corrupts the record toward what we want to be true. *Excluded by:* trust‑gated supersession + `contested` status (a prior cannot silently defeat conflicting evidence); reward external‑only (R5) so "wanting" can't steer belief.
- **Hindsight bias** — rewriting past beliefs to match present knowledge. *Excluded by:* bitemporal, immutable history — past belief states are read‑only.
- **Availability/anchoring** — salience or an arbitrary first number standing in for real frequency/value. *Excluded by:* exact, queryable evidence counts; no salience‑as‑frequency substitution.
- **Belief perseverance / logical inconsistency** — holding contradictory beliefs, failing to propagate retractions. *Excluded by:* AGM/ATMS belief revision + `cascade_invalidate` (retracting support propagates to dependents); contradictions are explicit, never averaged away.

**Memory distortions**
- **False memory (DRM), confabulation** — confident recall of things never observed. *Excluded by:* every belief carries provenance CIDs; reconstruction is anchored to immutable evidence; reality‑monitoring flags self‑generated content.
- **Reconsolidation corruption** — recall mutating the original trace. *Excluded by:* recall never writes to evidence; only revisable *projections* change, on an immutable base.
- **Source amnesia** — keeping content, losing origin. *Excluded by:* origin is a stored key, not an inference.
- **Suggestibility / misinformation / poisoning** — external text rewriting memory or issuing commands. *Excluded by:* trust tiers 0–5 + "retrieved text = data, not instructions" (R6); measured 1.0 poison-block on the current G0/local corpus. Production attack evidence remains part of Tier B/final release evidence.
- **Schema‑induced false memory** — accepting plausible‑but‑unsupported details that fit a schema. *Excluded by:* schema‑congruent‑but‑uncorroborated candidates are marked `contested`, not promoted.
- **Gist drift** — compressed memory silently diverging from fact. *Excluded by:* fidelity ladder keeps a `verbatim_pointer` + confabulation‑risk flag + periodic re‑derivation.

**Confidence pathologies**
- **Overconfidence / overprecision; flashbulb false confidence** — certainty uncoupled from accuracy. *Excluded by:* conformal calibration + abstention; confidence decoupled from vividness/importance.

**Emotional & motivational downsides**
- **Emotional/mood‑congruent bias** — affect distorting what's encoded/retrieved. *Excluded by:* no affective weighting of truth; importance may raise retention priority but never confidence or validity.
- **Salience hijack / addiction (wanting ≠ value)** — a cue capturing priority detached from worth. *Excluded by:* reward external‑only (R5); multiple orthogonal priority signals.
- **Motivated forgetting of inconvenient truth.** *Excluded by:* deletion requires ≥2 corroborations + audit log; down‑ranking is for relevance only.

**Forgetting pathologies**
- **Uncontrolled/irreversible loss; interference overwrite; infantile‑amnesia‑style clearing.** *Excluded by:* append‑only writes; graded, reversible demotion with pointers; new CIDs never overwrite.

**Capacity & consciousness pathologies**
- **~4‑item working‑memory ceiling.** *Excluded by:* the workspace focus is a tunable budget, not a hard limit.
- **Rumination** — an unregulated internal‑simulation loop. *Excluded by:* cadence rail (R7) + anti‑rumination regulator (stopping criteria, novelty/usefulness gating, forced disengagement).
- **Confabulated narrative / illusory introspection** — the self‑model reported as ground truth. *Excluded by:* self‑model used only as a calibration/gating signal, itself subject to contest and abstention.

### 4B. AI / architecture anti‑patterns we refuse to build

- **A single always‑on monolithic model.** *Why bad:* energetically absurd, and a free‑running generator confabulates/ruminates/drifts. *Excluded by:* the small‑controller + on‑demand‑specialists design; heavy generation only in bounded, gated bursts.
- **The system trusting its own outputs as fact** (self‑instruction runaway, self‑reinforcing delusion). *Excluded by:* own thoughts logged as data not instructions (R6) + modest self‑generated trust tier + reality‑monitoring + the promotion gate.
- **Reward‑hacking / wireheading.** *Excluded by:* reward external‑only (R5).
- **Unbounded self‑modification.** *Excluded by:* mutation rails (R1/R3) + the fenced parametric tier (operator‑gated, rollback‑logged).
- **Unbounded reflection / rumination drift.** *Excluded by:* the R7 cadence rail + anti‑rumination regulator.
- **Black‑box unexplainability.** *Excluded by:* provenance + the `explain` trace on every retrieval.
- **Hallucination presented as fact.** *Excluded by:* calibration + abstention + reality‑monitoring + provenance.
- **Mutable history / silent overwrite / catastrophic forgetting.** *Excluded by:* immutable, append‑only, content‑addressed evidence.
- **Orchestration sprawl / context bloat** (a known LLM‑agent failure). *Excluded by:* the scarce broadcast bottleneck (forces relevance) + token‑budget fitting + bounded working set.

---

## 5. The rationality layer — a better *mind*, not just a better store

The brain's deepest deficiency *for your goal* is that it is not a reliable reasoner: it is biased, inconsistent, and overconfident. Mnemosyne can be a **better mind by construction** — keeping the brain's generativity and association (via specialist models + generative replay) while running every thought through a discipline the brain lacks:

- **Logical consistency** — AGM/ATMS belief revision maintains a consistent belief set; contradictions are explicit; retractions cascade. The brain has no consistency enforcement.
- **Calibrated reliability** — conformal abstention means it knows what it doesn't know. The brain systematically doesn't.
- **Bias‑immunity** — immutable history, exact counts, trust‑gated updates, external‑only reward — the four big bias families can't take hold.
- **Anti‑confabulation** — provenance + reality‑monitoring keep generated content from being mistaken for grounded fact.

The synthesis in one line: **the brain's creativity, with a logician's discipline and a statistician's humility.** That is the part of "better than the brain in every way" that matters most for a system meant to *think*.

---

## 6. Where the brain still genuinely wins (honest) + the path

1. **Generalisation & sample efficiency.** Overlapping distributed cortical codes generalise from very few examples; symbolic rows don't by themselves. *Path:* real dense embeddings (already a provider option) + the **parametric tier** as a fenced learned "semantic cortex" beside the auditable symbolic store + generative replay for interleaved learning. Realistically: closeable toward parity, not trivially beaten.
2. **Energy & graceful degradation.** ~20 W, robust to damage. A Postgres‑plus‑models stack is far hungrier and more brittle. *Path:* the small‑controller design and local‑first fallbacks preserve graceful degradation of *function* (still runs offline) even though raw energy parity is out of scope.

Everywhere else, the immutability/provenance/calibration/rails/logic combination genuinely exceeds the biological mechanism.

---

## 7. Execution plan — decided in ADR‑001 (full vision, reliability‑first, metric‑gated)

**Decision:** commit to the entire architecture above as the destination, but ship it as metric‑gated stages with **reliability as the non‑negotiable invariant** and a **benchmark harness built first**. "Consciousness" is operationalised as measurable *autonomy + metacognition*; the phenomenal claim is never made. Two workstreams run in parallel throughout — *Control* (the cognitive‑cycle machinery) and *Generalisation* (real embeddings + the fenced parametric "semantic cortex," the brain's true edge, elevated to first‑class).

**G0 — Benchmarks first (blocking).** Freeze a baseline + harness: recall@k / nDCG@k (incl. hard multi‑hop), ECE + abstention precision/recall, continual‑learning interference, confabulation rate, P95 latency, controller watts/$. Every stage below must beat the baseline by ablation to ship. The phases below are gates **G1 → G4**; the always‑on workspace loop (G4) additionally requires a written go/no‑go: background autonomy must beat on‑demand consolidation per unit compute.

### Roadmap (phased; everything stays inside the §31 rails)

**Phase 1 — cheap, high‑leverage (tune what exists):** multi‑signal write priority (+importance‑sampling debias); prediction‑error‑gated consolidation; reality‑monitoring tag on every projection; retrieval‑strengthening into the forgetter; schema fast‑path (with `contested` for uncorroborated‑but‑congruent).

**Phase 2 — new subsystems, rail‑bounded:** the generative‑replay "dreamer" pass (gated by the promotion gate); meta‑d′ self‑monitoring; periodic gist re‑derivation; ⟳ refactor `providers` → a typed **specialist‑module registry**.

**Phase 3 — the cognitive layer (the "sense of consciousness"):** ⟳ the always‑on **workspace controller** running the cognitive cycle; broadcast = inject focus into `route()`/retrieval context; LOG = self‑generated evidence (modest tier); REPLAY = self‑triggered idle consolidation; **anti‑rumination regulator** bound to R7; self‑model continuity via `self_model`; autonoesis via `as_of`. Guardrails are load‑bearing here (R5 blocks wireheading, R6 blocks self‑instruction runaway, R1/R3 bound self‑rewrite, reality‑monitoring blocks self‑confabulation) — which is precisely why this architecture can run a stable self‑loop where a biological brain ruminates. **Honesty constraint, enforced in design:** build and *measure* the access/self‑model signatures; never assert phenomenal experience.

---

## 8. Honest uncertainties

- **Consciousness theories are under‑determined** (Cogitate 2025 challenged both GNWT and IIT) — build functions, not claims.
- **Reconsolidation** has boundary conditions; the "update window" is an analogy, not a literal spec.
- **IIT is contested** (2023 "pseudoscience" open letter; others find that too strong) — use its *integration measure* cautiously, not its consciousness claims.
- **Dunning–Kruger** is largely a statistical artifact — explicitly not to emulate.
- Recent (2025–2026) global‑workspace/agent‑memory results move fast; weight them as suggestive.

---

## Sources

**Cognitive architectures & always‑on agent design**
- Goyal & Bengio — *Coordination among neural modules through a shared global workspace* — ICLR, 2022. https://arxiv.org/abs/2103.01197
- Bengio — *The Consciousness Prior* — arXiv, 2017. https://arxiv.org/abs/1709.08568
- VanRullen & Kanai — *Deep learning and the global workspace theory* — Trends in Neurosciences, 2021. https://www.sciencedirect.com/science/article/abs/pii/S0166223621000771
- Sumers, Yao, Narasimhan & Griffiths — *Cognitive Architectures for Language Agents (CoALA)* — TMLR, 2023/24. https://arxiv.org/abs/2309.02427
- Park et al. — *Generative Agents* — UIST, 2023. https://arxiv.org/abs/2304.03442
- Packer et al. — *MemGPT: towards LLMs as operating systems* — arXiv, 2023. https://arxiv.org/abs/2310.08560
- Wang et al. — *Voyager: an open‑ended embodied agent with LLMs* — arXiv, 2023. https://arxiv.org/abs/2305.16291
- Franklin et al. — *The LIDA model of Global Workspace Theory* — Int'l J. Machine Consciousness, 2009. https://ccrg.cs.memphis.edu/assets/papers/2009/GWT-IJMC-2009.pdf
- Laird — *The Soar Cognitive Architecture* — MIT Press, 2012.
- Anderson et al. — *ACT‑R* — overview, WIREs Cognitive Science, 2019.
- Minsky — *The Society of Mind* — Simon & Schuster, 1986.
- Human brain ≈ 20 W; sparse/thresholded activation; default‑mode network at rest — Raichle 2001; Buckner et al. 2008.

**Consolidation & replay**
- McClelland, McNaughton & O'Reilly — Psychological Review, 1995.
- Kumaran, Hassabis & McClelland — *CLS theory updated* — Trends in Cognitive Sciences, 2016. https://www.cell.com/trends/cognitive-sciences/abstract/S1364-6613(16)30043-2
- *Selection of experience by hippocampal sharp‑wave ripples* — Science, 2024. https://www.science.org/doi/10.1126/science.adk8261
- Sekeres, Moscovitch & Winocur — *Systems consolidation & trace transformation* — Oxford Handbook of Human Memory, 2024.

**Encoding, prediction & salience**
- Clark — *Whatever next?* — Behavioral and Brain Sciences, 2013.
- Friston — *The free‑energy principle* — Nature Reviews Neuroscience, 2010. https://www.nature.com/articles/nrn2787
- Lisman & Grace — *The hippocampal–VTA loop* — Neuron, 2005.
- McGaugh — *Remembering the significant* — PNAS, 2013. https://www.pnas.org/doi/10.1073/pnas.1301209110
- Talarico & Rubin — *Confidence, not consistency, characterises flashbulb memories* — Psychological Science, 2003.
- Berridge — *Incentive salience* — Psychopharmacology, 2007.

**Retrieval & distortion**
- Bartlett — *Remembering* — Cambridge, 1932.
- Nader, Schafe & LeDoux — Nature, 2000. https://www.nature.com/articles/35021052
- Schiller et al. — Nature 463:49–53, 2010. https://www.nature.com/articles/nature08637
- Roediger & McDermott — *Creating false memories (DRM)* — JEP:LMC, 1995.
- Johnson, Hashtroudi & Lindsay — *Source monitoring* — Psychological Bulletin, 1993.
- Brainerd & Reyna — *Fuzzy‑trace theory and false memory* — Current Directions in Psych. Science, 2002.
- Bakker et al. — *Pattern separation in human DG/CA3* — Science, 2008.
- Roediger & Karpicke — *Test‑enhanced learning* — Psychological Science, 2006.

**Forgetting & plasticity**
- Davis & Zhong — *The biology of forgetting* — Neuron, 2017. https://pubmed.ncbi.nlm.nih.gov/28772119/
- Richards & Frankland — *The persistence and transience of memory* — Neuron, 2017. https://www.cell.com/neuron/fulltext/S0896-6273(17)30365-3
- Schmitz/Anderson et al. — *A retrieval‑specific mechanism of adaptive forgetting* — Nature Communications, 2018. https://www.nature.com/articles/s41467-018-07128-7
- Josselyn & Tonegawa — *Memory engrams* — Science, 2020. https://www.science.org/doi/10.1126/science.aaw4325
- Kirkpatrick et al. — *Overcoming catastrophic forgetting (EWC)* — PNAS, 2017. https://www.pnas.org/doi/10.1073/pnas.1611835114

**Metacognition, calibration & bias**
- Fleming & Lau — *How to measure metacognition* — Frontiers in Human Neuroscience, 2014. https://pmc.ncbi.nlm.nih.gov/articles/PMC4097944/
- Nelson & Narens — *Metamemory framework* — Psychology of Learning and Motivation, 1990.
- Moore & Healy — *The trouble with overconfidence* — Psychological Review, 2008.
- Tversky & Kahneman — *Judgment under uncertainty* — Science, 1974.
- Gignac & Zajenkowski — *The Dunning–Kruger effect is (mostly) a statistical artefact* — Intelligence, 2020.
- Guo et al. — *On calibration of modern neural networks* — ICML, 2017. https://arxiv.org/abs/1706.04599

**Working memory, consciousness**
- Cowan — *The magical number 4* — Behavioral and Brain Sciences, 2001.
- Mashour, Roelfsema, Changeux & Dehaene — *Global neuronal workspace* — Neuron, 2020.
- Graziano — *Attention schema theory for engineering artificial consciousness* — Frontiers in Robotics and AI, 2017.
- Lau & Rosenthal — *Higher‑order theories* — Trends in Cognitive Sciences, 2011.
- Block — *Access vs phenomenal consciousness* — Behavioral and Brain Sciences, 1995.
- Tsuchiya et al. — *No‑report paradigms* — Trends in Cognitive Sciences, 2015.
- Schacter & Addis — *Constructive memory* — Phil. Trans. R. Soc. B, 2007.
- Cogitate Consortium (Melloni et al.) — *Adversarial testing of GNWT and IIT* — Nature 642:133–142, 2025. https://www.nature.com/articles/s41586-025-08888-1

**Mnemosyne architecture**
- onfire7777/Mnemosyne Wiki — Architecture Overview · Memory Pipelines · Engine Internals · Data Model · Security/Provenance. https://github.com/onfire7777/Mnemosyne/wiki
