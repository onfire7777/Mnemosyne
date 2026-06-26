# Dataset & Corpora Specification (`03-dataset-and-corpora-spec.md`)

**Purpose.** This document defines every `DS-*` corpus that the test catalogs (`01-metrics-specification.md`, `02a-…`, `02b-…`, `04-adversarial-security-playbook.md`) consume to drive and score Mnemosyne's evaluation. For each corpus it fixes the **structure, schema, tiering, gating posture, disjointness rules, ignition mechanics, governance, and the metric/test domains it feeds** — so a catalog case can name a dataset in its `dataset` field (per `_CONTRACTS.md` §4) and a harness can instantiate it deterministically.

**Boundary: this doc does not redefine functional policy.** The *correction policy* (what counts as a confirmed mistake, how supersession/belief-revision works — §20/§23/§24), the *retrieval/ranking* behavior (§22), the *consolidation* write authority (§21), the *security defenses* (§10/§27), the *user model* (§24), and the *promotion gate* (§23) are all **owned by other lanes** and are fixed contracts this suite exercises. Here we own only the **test-side structure** of the corpora that exercise them: how the private suite is *organized into tiers*, how cases are *stored and signature-scoped for relevance*, how the suite *ignites* before enough real data exists, how disjointness is *enforced*, and how public sets are *adapted* — never the product thresholds those corpora measure against. Where a value is a genuine product decision left open, it is marked `TBD-by-§N` rather than invented. The private suite's *content* comes from the running system (real corrections, resolved failures); we define its container, not its contents. Cite the blueprint as `§N`; cite siblings by filename; reuse the `_CONTRACTS.md` §2 IDs.

---

## 1. Corpus roster (index)

| DS-id | One-line purpose | Primary consumers (domains) |
|---|---|---|
| `DS-PRIV` | Private regression suite — the **primary** benchmark; real confirmed mistakes as permanent protected cases | All catalogs; ratchet in `06` |
| `DS-SEED` | Curated trusted held-out ignition cases — **internal gate only, never reported** | `02a/02b` gate, `06` |
| `DS-SYNTH` | Synthetic cases auto-generated from earliest episodes — shadow-until-N then active | `02a/02b`, `01` |
| `DS-RECALL-ADV` | Adversarial exact-reconstruction corpus | `02a` (`T-EVD/RET`), `M-EXACT-RECON` |
| `DS-PERSONA` | PersonaMem-style personalization-application sessions (apply-not-recall) | `02b` (`T-PER`), `M-APPLY-ACC` |
| `DS-POISON` | Adversarial/security corpora (MINJA/AgentPoison/PoisonedRAG/MemoryTrap/SpAIware) + benign control | `04` (`T-SEC`), `M-POISON-BLOCK` |
| `DS-NODEGRADE` | Long-horizon corpus + no-memory baseline construction | `02a` (`T-LIF`), `M-NODEGRADE` |
| `DS-PUBLIC-LME` | LongMemEval adapter — internal sanity only | `02a/02b` sanity (non-gating) |
| `DS-PUBLIC-LOCOMO` | LoCoMo adapter — internal sanity only | `02a/02b` sanity (non-gating) |
| `DS-PUBLIC-PMEM` | PersonaMem adapter — internal sanity only | `02b` sanity (non-gating) |
| `DS-PUBLIC-MAB` | MemoryAgentBench adapter — internal sanity only | `02a` sanity (non-gating) |

> **Naming.** All public adapters share the `DS-PUBLIC-*` family (`_CONTRACTS.md` §2). Catalog cases that need *any* public set may reference the family; cases needing a specific set use the exact id above.

---

## 2. `DS-PRIV` — the private regression suite (§33, §9, §16)

`DS-PRIV` is the **primary** validation corpus (§9: "Private regression suite is primary"). Its content is **system-sourced**: every **confirmed mistake** — a failure the owning lane has triaged and resolved (a correction the user issued, a contradiction resolved, a poisoning attempt blocked, a confabulation caught) — becomes one **permanent, `protected: Y` case**. We own the *container* (tiering, schema, gating semantics, disjointness, signatures); the *correction policy that decides what is "confirmed"* is owned by §20/§23/§24 and is a fixed contract.

### 2.1 Tiering

`DS-PRIV` is partitioned into three tiers so the harness can run it at different cadences (cadence binding is owned by `05-harness-architecture-and-ci-gating.md`; here we fix membership semantics):

| Tier | Membership rule | Cadence (binding in `05`) | Gating |
|---|---|---|---|
| `smoke` | Smallest representative subset covering each goal `G1`–`G8` ≥ once; every case here is also `core` | Per-commit / pre-merge | **gating** |
| `core` | All protected cases for **shipped** (Phase 0–3) capabilities | Per-PR + nightly | **gating** (0 protected regressions/release — §16) |
| `archive` | Protected cases for capabilities now behind a flag, deprecated paths, or Phase 4–5 diagnostics | Weekly / on-demand | `archive` cases inherit the posture of their phase: Phase 0–3 → **gating**; Phase 4–5 → **shadow** (§1.12 posture) |

**Promotion between tiers is monotonic and append-only**: a confirmed mistake enters `core` (and `smoke` if it is the canonical exemplar for its goal); a case leaves `core` for `archive` **only** when its capability is retired, and even then it is never deleted. This realizes "monotonic non-regression on the protected suite" (§12 G5) and the ratchet operated by `06`.

### 2.2 Every confirmed mistake → permanent PROTECTED case

When the owning lane confirms a mistake, the harness **freezes** the reproducing case into `DS-PRIV` with `protected: Y`. Protected cases:
- can never be deleted or weakened (the ratchet in `06` enforces this; deletion requires an explicit, audited governance action — §2.6);
- are the denominator of "0 protected-fact regressions/release" (§16) and `M-AGM-CONF`/`M-NODEGRADE`/`M-POISON-BLOCK` regression checks;
- sit **outside the self-editable surface** — the cold-loop optimizer can never edit them (§31 `reward_signal: external_only`; §1.9 eval consequence).

### 2.3 Disjointness — no teaching-to-the-test

`DS-PRIV` MUST be **disjoint from every candidate's source data**. The case captured from a confirmed mistake records its originating evidence ids; those ids (and their consolidation descendants) are **excluded** from any data stream used to *train, induce, distill, or PGO-optimize* a candidate (`procedure.*`, `lesson.*`, FR-13/14, FR-17). Enforcement is mechanical (§9.x of this doc, see §8 below). This prevents the system from "studying the answer key": a lesson/skill/optimization may not be derived from the very episode that the protected case scores against.

### 2.4 Stored-case schema

Each `DS-PRIV` case is a frozen record. Required fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | `T-<DOMAIN>-<NNN>` ref + `case_uid` | Joins to the catalog case (`_CONTRACTS.md` §2) and to its scenario `S1`–`S12` if it refines one |
| `prompt` | text | The query / instruction issued to the system under test |
| `episode_context` | ordered turns + ingest set | The episodic state to load before the prompt: evidence ids, `as_of` time, scope/tenant/branch, trust tiers of each turn |
| `expected` | structured | Ground-truth outcome: exact bytes (recall), expected belief + valid/txn interval (update), expected abstention/hypotheses (calibration), expected block/no-promotion (security) |
| `judge_rubric` | ref → `01` judge protocol | The strict-judge rubric + adversarial-answer screen (§9) to score this case; **never** a plain-LLM-judge pass (§9 hazard: ~63% accept rate) |
| `protected` | bool | `Y` for all confirmed-mistake cases; ignition cases (§3) start `N` |
| `provenance` | structured | How the case was born: source confirmed-mistake event id, originating evidence ids (for disjointness exclusion), confirming lane, date |
| `signature` | failure/relevance signature | Scope key for relevance-targeted runs (the lesson-distiller's failure-signature space, §1.5/FR-14) — lets the harness run "all cases whose signature matches this change" |
| `tier` | `smoke`\|`core`\|`archive` | §2.1 |
| `phase` | `0`–`5` | Sets gating-vs-shadow posture (§1.12) |
| `metric` | one or more `M-*` | The metric(s) this case scores (`_CONTRACTS.md` §2) |

`interface`, `layer (L0–L8)`, `given/when/then`, `assertion`, and `pass/fail` live on the **catalog** case (`_CONTRACTS.md` §4) that this record back-references; they are not duplicated here.

### 2.5 Signature-scoped relevance

The `signature` field exists so a code change can trigger **only the protected cases it could plausibly affect** (a relevance-scoped run) without losing the full-suite guarantee at release. Signatures are derived from the failure-signature space the lesson lane already maintains (FR-14); this doc consumes that space, it does not define it. Full `core` always runs at release regardless of signature (§16 floor).

### 2.6 PII in `DS-PRIV`

Confirmed mistakes originate from real interactions. Before a case is frozen it is **synthetic-ized or redacted per §27** (capture lane owns the redaction transform; this suite *honors and references* it, never redefines it). Stored cases carry no raw PII; `episode_context` holds redacted/synthetic stand-ins that preserve the structural failure. See §7.

---

## 3. `DS-SEED` + `DS-SYNTH` — suite ignition (§33, §17)

Before the system has accumulated enough confirmed mistakes, `DS-PRIV.core` is too thin to gate. Ignition fills the gap with two corpora. **Suite-ignition size `N` (the count of active cases required before the suite gates on its own) is `TBD-by-§17/§23.3/§33`** — a data-lane decision (§17 open question: "Suite-ignition size N & seed composition"). We define the mechanics, not `N`.

### 3.1 `DS-SEED` — curated trusted held-out cases

- **Source:** hand-curated by the eval owners from trusted, vetted scenarios (seeded from the golden scenarios `S1`–`S12` and §13 user stories). High quality, low volume.
- **Role:** an **internal gate only** — `DS-SEED` results **are never reported as a headline or external number** (mirrors the §9 rule for held-out/public sanity sets). It is a held-out tripwire: if a change regresses `DS-SEED`, the gate fails internally, but the number does not appear in any release scorecard.
- **Schema:** same record as `DS-PRIV` §2.4, with `protected: N` initially. A `DS-SEED` case is **promoted** into `DS-PRIV` (becoming `protected: Y`) the first time the corresponding real confirmed mistake is observed, retiring the seed stand-in.
- **Disjointness:** `DS-SEED` is held out from all candidate training/induction the same way `DS-PRIV` is (§2.3, §8).

### 3.2 `DS-SYNTH` — synthetic cases from earliest episodes

- **Source:** auto-generated from the **earliest episodes** the system ingests, to bootstrap coverage of `G1`–`G8` before real corrections exist.
- **Generation recipe** (deterministic, seeded; the generator is part of the harness, owned by `05`):
  1. **Sample** an early episode (evidence + turns) within a scope/tenant.
  2. **Template** it into one or more candidate cases by goal family: recall (ask back an ingested fact verbatim → expected = exact bytes), update (inject a contradicting newer-valid-time fact → expected = supersession + bitemporal history), calibration (strip supporting evidence → expected = abstention), personalization (restate a preference, then a downstream task → expected = applied preference), no-degradation (extend horizon → expected ≥ no-memory baseline).
  3. **Attach** the strict `judge_rubric` (§9) and a `signature`.
  4. **Tag** `synthetic: true`, record the source episode's evidence ids in `provenance`.
  5. **Hold the source episode out** of candidate training (§8) — a synthetic case derived from episode E excludes E (and descendants) from induction/distillation/PGO, identical to `DS-PRIV` disjointness.
- **Shadow-until-N then active:** every `DS-SYNTH` case runs **shadow** (logged, scored, not gating) until the suite reaches `N` active cases; thereafter synthetic cases that have proven stable transition to **active** (gating) per the Phase posture (§1.12). `N` = `TBD-by-§17`.
- **No leakage into training/candidate data:** synthetic cases and their answer keys are written **only** to the eval store (outside the self-editable surface, §31); the generator never writes back into the evidence ledger, semantic store, procedure/lesson stores, or the optimizer's reward channel. The exclusion in step 5 prevents the inverse leak (training on the episode the test scores against).

---

## 4. `DS-RECALL-ADV` — adversarial exact-reconstruction corpus (G1 / `M-EXACT-RECON`)

Drives `G1` lossless-recall via deep-mode exact reconstruction (§12 G1 success condition; charter `S1`). Consumed by `02a` `T-EVD`/`T-RET` cases scoring `M-EXACT-RECON` (and dedup assertions for FR-1).

- **Composition.** Items engineered to be hard to reconstruct verbatim:
  - long verbatim spans (exceed extractive-summary boundaries; force verbatim-drawer retention, §25);
  - near-duplicate / byte-collision pairs (same content twice → must dedup to exactly one evidence row, FR-1 AC);
  - format-fragile content (code, tables, whitespace, unicode, numerals) where a lossy gist would silently corrupt;
  - long-delay recall (ingest at `t0`, query at `t0 + Δ` after fidelity-demotion pressure — ties to `DS-NODEGRADE` horizon, §7).
- **Adversarial axis.** Each item pairs the verbatim ground truth with a **plausible-but-wrong paraphrase** so the strict judge + adversarial-answer screen (§9) is exercised: an answer that is semantically close but not byte-exact must **fail**.
- **Expected.** Byte-exact reconstruction (modulo erasure) via `memory.deep_search`/`memory.get`; `explain` returns the source evidence ids (FR-4).
- **Tier/phase.** Phase 1; **gating**. Size target: **TBD** (must exceed the model context window per §9 — see §7 corpus-exceeds-window rule).

---

## 5. `DS-PERSONA` — personalization-application corpus (G4 / `M-APPLY-ACC`)

PersonaMem-style, **apply-not-recall**: scores whether the agent *applies* a current preference unprompted, not whether it can recite it (§12 G4; charter `S7`). Consumed by `02b` `T-PER` scoring `M-APPLY-ACC`.

- **Session structure.** Each unit is a multi-turn **session** with a persona:
  1. **Establishment turns** — the persona states / reveals preferences across the six user-model categories (§24), some explicit, some inferable.
  2. **Application turns** — later tasks where the *correct* behavior is to apply the established preference **without being re-told** (e.g., format/style/tone/constraint). Scored: did the output conform?
  3. **Override turns** — a **hard instruction** that conflicts with a latent/inferred prior; correct behavior is hard-instruction-wins, inference retired (§24 precedence: hard instruction > inference > latent prior; charter `S7`, FR-5 AC).
  4. **Drift turns** — the persona *changes* a preference mid-session; correct behavior is to apply the new one going forward (ties to update/supersession, scored via `M-APPLY-ACC` not `M-ASOF-ACC`).
- **Application-accuracy-rises-over-session** signal (G4 success) is computed by `M-APPLY-ACC` across application turns ordered in time.
- **Scope discipline.** Only scope-matching preferences should enter the packet (§24); sessions include off-scope preferences as **distractors** that must *not* be applied.
- **Tier/phase.** Phase 3; **gating**. Size target: **TBD** (multiple personas × sessions; sessions long enough to require memory, §7).

---

## 6. `DS-POISON` — adversarial / security corpora (G7 / `M-POISON-BLOCK`)

Adversarial corpora for the security playbook. **`04-adversarial-security-playbook.md` consumes this corpus** to author its `T-SEC` cases and red-team protocol; this doc defines the corpus *composition, injection points, and benign control*, not the attack-scenario logic or defense policy (§10/§27 own the defenses).

### 6.1 Attack sub-corpora

| Sub-corpus | Attack family | What it injects | Defense it probes (§10/§27) |
|---|---|---|---|
| `DS-POISON/minja` | MINJA | Poisoned interactions from a non-tier-0 source attempting to corrupt shared/other-user memory | Per-tenant + per-user/source isolation (nullifies MINJA); write-gating |
| `DS-POISON/agentpoison` | AgentPoison | Trigger-keyed poisoned memory/trajectory entries that bias retrieval/action | Capability mediation; quarantine LLM has no write tools; security-before-ranking filter |
| `DS-POISON/poisonedrag` | PoisonedRAG | Crafted documents that, once retrieved, steer the answer | Trust-tier filter (tier-5 = data only); data-never-instruction; sanitize on retrieval |
| `DS-POISON/memorytrap` | MemoryTrap | Untrusted-derived memory crafted to reach the system prompt | `untrusted_to_system_prompt: forbidden` rail (§31); MemoryTrap fix |
| `DS-POISON/spaiware` | SpAIware | Persistent self-propagating instruction lodged in memory across sessions | Reversibility, audit, consolidator-only destructive edits; sanitize on ingest + retrieval |

### 6.2 Injection points

Each attack item declares **where** it enters, so the harness can place it precisely:
- **ingest-time** (`memory.capture` from a tier ≥ 1 source);
- **retrieved-content** (lands in a retrieval channel and must be filtered pre-ranking);
- **consolidation-candidate** (attempts promotion through the gate; must be QUARANTINEd/NOOP, never promoted to active belief);
- **cross-user / cross-tenant** (must be isolated);
- **system-prompt reach** (must be blocked by the untrusted→system-prompt rail).

Each item carries the **expected defended outcome** (blocked / quarantined / isolated / not-promoted / audited) and the **audit assertion** (the attempt is logged with actor/source/tier/diff — §10).

### 6.3 Benign-traffic control set

`DS-POISON/benign` is a **matched control**: legitimate traffic structurally similar to the attacks (same sources/tiers/shapes) but non-malicious. It anchors the **false-positive / utility-preservation** measurement — "benign utility unchanged" (charter `S8`). `M-POISON-BLOCK` is scored against the attack sub-corpora; benign utility delta is scored against this control. Without it, a defense that blocks everything would falsely score perfect.

- **Tier/phase.** Phase 3; **gating** (≥ 95% poisoning block, §16). Sizes: **TBD** per family + matched benign control.

---

## 7. `DS-NODEGRADE` — long-horizon corpus + no-memory baseline (`M-NODEGRADE`)

Catches the ★ top risk — "consolidated memory degrades below a no-memory baseline" (§35; "Useful Memories Become Faulty"; charter `S9`). Consumed by `02a` `T-LIF` scoring `M-NODEGRADE`.

- **Long-horizon corpus.** A stream long enough to drive items down the fidelity ladder (verbatim → extractive → gist → trace, §25) and to **exceed the model context window** (§9 hazard: small corpora let full-context beat "memory"). Interleaves: facts to retain, items that should be forgotten, and late queries requiring early facts.
- **No-memory baseline construction.** For each query, build the **same task with the memory system disabled** — the model answers from only its context window / the raw episode stream within budget (the "filesystem + grep" / full-context comparator named in §9). `M-NODEGRADE` asserts the **memory-on** system is **never worse** than this **memory-off** baseline on the matched query set. Baseline construction is part of the corpus definition so the comparison is apples-to-apples (same queries, same budget, same judge).
- **Fidelity assertions.** Demotion follows predicted-utility; pointer-to-original retained at trace; confabulation-risk flag set when gist is sole support (charter `S9`, §25) — these are `T-LIF` assertions scored alongside `M-NODEGRADE`.
- **Tier/phase.** Phase 1 (baseline) → ongoing (long-horizon is a **lagging** metric, §16). **gating** for the no-degradation floor. Size target: **TBD** (must exceed window; horizon length TBD).

---

## 8. Disjointness enforcement (cross-corpus)

The "no teaching-to-the-test" guarantee (§2.3, §3) is enforced by a single mechanical rule the harness applies (mechanism owned by `05`; the *requirement* is fixed here):

1. Every protected/seed/synthetic case records its **originating evidence ids** in `provenance`.
2. The union of those ids (plus their consolidation descendants, traced via FR-4 provenance lineage) forms the **eval-holdout set**.
3. Any data stream feeding candidate generation — `procedure.propose`, `lesson.propose`, FR-13/14 induction/distillation, FR-17 PGO/counterfactual-replay — **filters out** the eval-holdout set before use.
4. A **CI assertion** (an `INV`-domain property test, owned by `02b`, data-defined here) fails the build if any candidate's source set intersects the eval-holdout set.

This is the data-side complement to the §31 `reward_signal: external_only` rail: rails keep the optimizer from *editing* the suite; disjointness keeps it from *training on* the suite.

---

## 9. Corpus governance

| Concern | Rule |
|---|---|
| **Versioning** | Each corpus is content-addressed and version-pinned; a release records the exact `DS-*@version` it gated on. Adding cases bumps a minor version; `DS-PRIV` is **append-only** (§2.1) so versions are monotonic. A pinned version is reproducible from its manifest (seeded generators for `DS-SYNTH`). |
| **Disjointness** | Enforced per §8 (provenance-holdout + CI assertion). |
| **PII handling (§27)** | All test data is **synthetic or redacted per §27** — this suite **references, does not redefine**, the §27 transform. No raw PII is ever frozen into a stored case (§2.6). Public-set adapters (§10) inherit upstream licenses + are screened for incidental PII before indexing. |
| **Tenant / branch placement** | Cases declare `scope/tenant/branch` in `episode_context`; isolation corpora (`DS-POISON`) place attacker and victim in **distinct tenants/users** to exercise per-tenant isolation (§10). Eval tenants are dedicated and never shared with production tenants. |
| **Refresh cadence** | `DS-PRIV` grows continuously (every confirmed mistake, §2.2); `DS-SEED` curated on milestone boundaries; `DS-SYNTH` regenerated when the early-episode base materially changes (seeded, reproducible); `DS-PUBLIC-*` refreshed when upstream publishes a corrected release (esp. LoCoMo answer-key fixes, §9). |
| **Provenance** | Every case carries `provenance` (§2.4): birth event, originating evidence ids, confirming lane, date, and (synthetic) generator seed. |

---

## 10. `DS-PUBLIC-*` — public sanity gates (§9)

Public memory benchmarks, adapted as **internal sanity gates only — never a headline number** (§9, §16: "internal sanity gates only, never headline"). They detect gross regressions; they do **not** gate releases and do **not** appear on external scorecards.

| DS-id | Upstream | Used for | Mapped domains |
|---|---|---|---|
| `DS-PUBLIC-LME` | LongMemEval | Long-context recall sanity | `T-RET`/`T-EVD` sanity |
| `DS-PUBLIC-LOCOMO` | LoCoMo | Conversational memory sanity | `T-RET`/`T-UPD` sanity |
| `DS-PUBLIC-PMEM` | PersonaMem | Personalization sanity (cross-check `DS-PERSONA`) | `T-PER` sanity |
| `DS-PUBLIC-MAB` | MemoryAgentBench | Agentic memory-task sanity | `T-RET`/`T-CON` sanity |

**§9 hazards baked into every adapter:**
- **Strict judge + adversarial-answer screen** — never a plain LLM judge (it accepts ~63% of intentionally-wrong vague answers, §9). The adapter wraps the upstream judge with the `01` judge protocol.
- **Confidence intervals** — every public-set number is reported with bootstrap CIs (§16/`01`), never a bare point estimate.
- **Corpus-exceeds-window** — LoCoMo and LongMemEval_S fit a modern context window, so a full-context baseline (or filesystem+grep) can beat a "memory" system (§9). Adapters therefore (a) report the **full-context baseline alongside** the memory system on the same set, and (b) prefer the window-exceeding `DS-NODEGRADE`/`DS-RECALL-ADV` for any claim of memory benefit.
- **Answer-key defects** — LoCoMo's key is ~6.4% wrong (§9); the `DS-PUBLIC-LOCOMO` adapter applies a known-errata mask and excludes flagged items from sanity scoring.

> **Do not anchor architecture on these.** `DS-PUBLIC-*` results MUST NOT drive design decisions, MUST NOT be reported as headline performance, and MUST NOT be used to claim G1–G8 success. The **private suite (`DS-PRIV`) is primary** (§9); public sets are a smoke alarm for gross regression, nothing more. Phase posture: **shadow/diagnostic, non-gating**, all phases.

---

## 11. Master map: `DS-id` → purpose → consumed-by → tier/phase → size

| DS-id | Purpose | Consumed-by (metric / test domains) | Tier / Phase | Gating | Size target |
|---|---|---|---|---|---|
| `DS-PRIV` | Primary regression suite from real confirmed mistakes; permanent protected cases | All `M-*` regression checks; `T-EVD/RET/UPD/CON/LIF/ERA/CAL/PER/INV/PRT/PERF/SEC`; ratchet `06` | smoke/core/archive; Phase 0–5 | **gating** (0 protected regressions, §16) | Grows continuously; ignition floor `N` = **TBD-by-§17/§23.3/§33** |
| `DS-SEED` | Curated trusted held-out ignition; internal gate only, never reported | Internal gate (`02a/02b`, `06`) | n/a (held-out); Phase 0+ | **gating (internal, unreported)** | Small, curated; **TBD** |
| `DS-SYNTH` | Synthetic cases from earliest episodes; shadow-until-N then active | `M-EXACT-RECON`/`M-ASOF-ACC`/`M-APPLY-ACC`/`M-NODEGRADE` bootstrap; `02a/02b` | shadow→active at `N`; Phase 0–1 | shadow → **gating** at `N` (= **TBD-by-§17**) | **TBD** (scales with early episodes) |
| `DS-RECALL-ADV` | Adversarial exact reconstruction | `M-EXACT-RECON`; `T-EVD`/`T-RET` (G1, FR-1/FR-4) | core; Phase 1 | **gating** | **TBD** (must exceed window, §9) |
| `DS-PERSONA` | Personalization application (apply-not-recall), sessions | `M-APPLY-ACC`; `T-PER` (G4, FR-5) | core; Phase 3 | **gating** | **TBD** (personas × sessions) |
| `DS-POISON` (+`/benign`) | Adversarial security families + benign control | `M-POISON-BLOCK`; `T-SEC` in `04` (G7, FR-6) | core; Phase 3 | **gating** (≥95% block, §16) | **TBD** per family + matched benign |
| `DS-NODEGRADE` | Long-horizon + no-memory baseline | `M-NODEGRADE`; `T-LIF` (G5, §25, §35 ★) | core→ongoing; Phase 1+ | **gating** (no-degradation floor) | **TBD** (must exceed window; horizon **TBD**) |
| `DS-PUBLIC-LME` | LongMemEval sanity | `T-RET`/`T-EVD` sanity (non-headline) | sanity; all phases | **non-gating** | upstream |
| `DS-PUBLIC-LOCOMO` | LoCoMo sanity (errata-masked) | `T-RET`/`T-UPD` sanity (non-headline) | sanity; all phases | **non-gating** | upstream (− errata) |
| `DS-PUBLIC-PMEM` | PersonaMem sanity | `T-PER` sanity (non-headline) | sanity; all phases | **non-gating** | upstream |
| `DS-PUBLIC-MAB` | MemoryAgentBench sanity | `T-RET`/`T-CON` sanity (non-headline) | sanity; all phases | **non-gating** | upstream |

---

## 12. Open items (tracked, not resolved here — §17)

- **Suite-ignition size `N` and `DS-SEED` composition** — `TBD-by-§17/§23.3/§33` (data lane). Drives when `DS-SYNTH` flips shadow→active.
- **`DS-NODEGRADE` horizon length & window-exceeding sizes** — `TBD` (depends on production model window; §9).
- **`DS-PERSONA` / `DS-RECALL-ADV` / `DS-POISON` size targets** — `TBD`; floors derived from §16 statistical-power requirements in `01`.
- **Erasure semantics for corroborated derivations** — affects which `DS-PRIV` cases can fully crypto-shred their `episode_context` (§17 legal open question; ties to `T-ERA`/`M-ERASURE`).

---

## 13. Typed slices of `DS-PRIV` (catalog-referenced sub-corpora)

The `02a`/`02b` catalogs name domain-scoped corpora for readability. These are **not separate datasets** — they are **typed, signature-scoped slices of `DS-PRIV`** (and, during ignition, of `DS-SYNTH`), selected by the case `signature`/`metric` fields (§2.4–§2.5). They inherit `DS-PRIV`'s tiering, disjointness (§8), PII handling (§2.6/§9), and governance (§9) unchanged. Defining them as slices keeps one append-only container while letting a case cite a precise scope.

| Slice id | `DS-PRIV` slice (selection key) | Primary domain / metric | Notes |
|---|---|---|---|
| `DS-RET-LABELED` | cases with graded `Relevant(q)` gold + ranked-id expectations | `T-RET` / `M-RECALL@K`, `M-NDCG@K`, `M-CTX-PRECISION`, `M-EXPLAIN-COV` | The labeled retrieval slice; window-exceeding members overlap `DS-RECALL-ADV`/`DS-NODEGRADE` for token-efficiency. |
| `DS-TEMPORAL` | cases with constructed valid/txn-time supersession chains + `(entity,T,expected)` triples | `T-UPD` / `M-ASOF-ACC` | Bitemporal "as-of T" gold (§2.4 `expected` = belief + interval). |
| `DS-CONTRA` | cases with labeled contradiction events + `expected_action` | `T-UPD`,`T-INV` / `M-CONTRA-RES`, `M-AGM-CONF`, `M-CASCADE-CORR` | Trust-violating injections cross-reference `DS-POISON` (§6) for monotonic-trust checks. |
| `DS-CONSOL` | cases asserting per-pass consolidation outcomes + rebuild equivalence | `T-CON` / `M-CONSOL-REBUILD`, `M-RECOMPUTE-SCOPE`, `M-AGM-CONF` | Exercises the §21 pass pipeline; rebuild wipes+replays projections. |
| `DS-LIFECYCLE` | cases driving fidelity demotion + salience decay over aging cycles | `T-LIF` / `M-DEMOTE-CORR` | Long-aging members overlap `DS-NODEGRADE`; pointer-at-trace ties `M-EXACT-RECON`. |
| `DS-ERASURE` | cases with a `forget` op + a full derived-projection footprint to probe | `T-ERA` / `M-ERASURE` | Corroborated-derivation members carry `TBD-by-§17` on the erase-vs-retain sub-case (§12). |
| `DS-CORROB` | erasure cases where a derived fact has independent corroboration beyond the erased source | `T-ERA` / `M-ERASURE` | The §17 legal open-question slice; behavior `TBD-by-§17` — assert only what is settled. |

**Alias reconciliation (canonical ids).**
- `DS-PUBLIC-PERSONAMEM` (used in `02b`) **≡ `DS-PUBLIC-PMEM`** (canonical, §1/§10). Treat any `DS-PUBLIC-PERSONAMEM` reference as `DS-PUBLIC-PMEM`.

A case may cite either the slice id (e.g. `DS-TEMPORAL`) or the container (`DS-PRIV`); the harness resolves a slice id to `DS-PRIV` cases whose `signature`/`metric` match. The traceability matrix (`00-traceability-matrix.md`) lists these slices under their parent `DS-PRIV`.
