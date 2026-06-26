# 05 · Glossary & Sources

**Status:** Living. The **full** reputable bibliography (neuroscience, psychology, ML) lives in `02-DESIGN-BRAIN-TO-ARCHITECTURE.md` → *Sources*. This file gives a shared vocabulary and the key anchor references so the other documents read consistently.

---

## Glossary

**System (Mnemosyne) terms**
- **Evidence / evidence ledger** — the immutable, append‑only, content‑addressed store of raw inputs; the source of truth.
- **Projection / belief** — derived, rebuildable memory (assertions, relations, entities, preferences, procedures, lessons, user/self models). Carries `source_evidence_cids`.
- **CID** — content identifier; SHA‑256 over canonical JSON of an input. Identical content → identical CID (store‑once de‑dup).
- **Consolidation** — the background "compiler" that turns evidence into beliefs via 11 ordered passes.
- **Replay / replayer** — the pass that prioritises which pending evidence to process (importance × novelty × surprise × reward).
- **Promotion gate** — the regression check on a throwaway "canary" branch that a candidate belief must pass to become active.
- **Fidelity ladder** — graded forgetting: verbatim → extractive summary → abstractive gist → statistical trace, keeping a `verbatim_pointer`.
- **Trust tiers (0–5)** — source trust ladder; 0 = the direct user (most trusted), 5 = untrusted external.
- **§31 rails** — seven machine‑checked invariants bounding supersession, deletion, pruning, trust monotonicity, reward source (external‑only), "retrieved text = data not instructions," and consolidation cadence.
- **Calibration / abstention** — conformal‑prediction gate that returns "not sure" when support is thin or contested. **ECE** = expected calibration error.
- **Bitemporal / `as_of`** — beliefs carry validity windows; `as_of` answers "what was true at time *t*."
- **Specialist‑module registry** *(proposed)* — Layer 3: the typed evolution of today's `providers` adapters (reasoner, embedder, dreamer, graph, reranker) recruited on demand.
- **Workspace controller** *(proposed)* — Layer 4: the small, always‑on process running the cognitive cycle (perceive → compete → broadcast → act → consolidate).
- **Generative replay / "dreamer"** *(proposed)* — a sandboxed consolidation pass that recombines evidence into low‑trust candidate beliefs, promoted only through the gate.
- **Reality‑monitoring discriminator** *(proposed)* — tags content as evidence‑grounded / self‑generated / externally‑suggested; biases abstention against self‑generated content.

**Neuroscience / cognitive‑science terms**
- **Complementary Learning Systems (CLS)** — fast hippocampus (sparse, one‑shot) + slow neocortex (interleaved, generalising); the fast/slow split.
- **Systems consolidation / trace transformation** — memory reorganising over time; a gist migrates to cortex while detail stays hippocampal.
- **Sharp‑wave ripple replay** — time‑compressed, prioritised reactivation; biological prioritised experience replay.
- **Predictive coding / active inference** — the brain encodes prediction error, weighted by precision (confidence).
- **Reconsolidation** — recall returns a memory to an editable (and corruptible) state.
- **Reconstructive memory / DRM / misinformation effect** — recall rebuilds from gist + schema, producing confident false memories.
- **Source monitoring / source amnesia** — inferring (and losing) where a memory came from.
- **Pattern separation / completion** — dentate gyrus orthogonalises similar inputs; CA3 completes a whole from a partial cue.
- **Metacognition / meta‑d′ / M‑ratio** — second‑order judgement of one's own correctness; efficiency of confidence.
- **Global Workspace / GNW** — selection → ignition → broadcast; the leading functional account of *access* consciousness.
- **Attention Schema Theory** — awareness as the brain's model of its own attention.
- **Access vs phenomenal consciousness (Block)** — globally available/reportable vs "what it is like." Only the former is testable.
- **Autonoesis** — self‑aware "mental time travel"; episodic memory's link to a self across time (Tulving).
- **Default mode network / rumination** — the brain's offline‑simulation system; unregulated, it ruminates.

**Cognitive‑architecture / ML terms**
- **SOAR / ACT‑R** — classical cognitive architectures: modules + capacity‑limited buffers + a decision cycle.
- **LIDA** — a Global‑Workspace‑Theory cognitive architecture built as a repeated "cognitive cycle."
- **CoALA** — "Cognitive Architectures for Language Agents": working + long‑term (episodic/semantic/procedural) memory, a decision loop, modular actions.
- **Experience replay / prioritized replay / generative replay** — ML analogues of hippocampal replay and interleaved learning.
- **EWC (Elastic Weight Consolidation)** — protects task‑important weights ≈ synaptic consolidation; a catastrophic‑forgetting remedy.
- **Conformal prediction / selective prediction** — calibrated uncertainty / principled abstention.

---

## Key anchor sources (full list in `02-DESIGN` → Sources)

**Memory & consolidation:** McClelland, McNaughton & O'Reilly 1995 (CLS); Kumaran, Hassabis & McClelland 2016 (CLS updated); *Selection of experience by sharp‑wave ripples*, Science 2024.
**Encoding & prediction:** Clark 2013; Friston 2010 (free energy); McGaugh 2013 (emotional modulation).
**Retrieval & distortion:** Nader, Schafe & LeDoux 2000 and Schiller et al. 2010 (reconsolidation); Roediger & McDermott 1995 (DRM); Johnson et al. 1993 (source monitoring).
**Forgetting:** Richards & Frankland 2017 (adaptive transience); Davis & Zhong 2017 (active forgetting); Kirkpatrick et al. 2017 (EWC / catastrophic forgetting).
**Metacognition & calibration:** Fleming & Lau 2014; Moore & Healy 2008 (overconfidence); Guo et al. 2017 (calibration/ECE).
**Consciousness & workspace:** Mashour, Roelfsema, Changeux & Dehaene 2020 (GNW); Graziano 2017 (AST); Block 1995 (access vs phenomenal); **Cogitate Consortium / Melloni et al., Nature 642:133–142, 2025** (adversarial test — neither theory vindicated).
**Cognitive architectures / agents:** Goyal & Bengio 2022 (shared global workspace, ICLR); Sumers, Yao, Narasimhan & Griffiths 2023 (CoALA); Park et al. 2023 (Generative Agents); Packer et al. 2023 (MemGPT); Franklin et al. 2009 (LIDA).
**Evaluation benchmark lane:** G0 is implemented at repo root `eval/g0/` using the existing eval lane plus project-native fixtures. External comparability sets remain candidates for future expansion where licensing and format fit: a long‑term conversational‑memory set (LoCoMo‑style), a multi‑hop QA set (HotpotQA‑style), and a continual‑learning task sequence.

**System of record for Mnemosyne itself:** the `onfire7777/Mnemosyne` wiki (Architecture Overview, Memory Pipelines, Engine Internals, Data Model, Security/Provenance).
