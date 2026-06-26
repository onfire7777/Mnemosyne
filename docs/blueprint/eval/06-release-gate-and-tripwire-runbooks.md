# 06 — Release Gate, Protected-Test Ratchet & Tripwire Runbooks

**Purpose.** This document defines the **release acceptance criteria** for the Mnemosyne eval suite: the hard floors a build must clear to ship, the **protected-test ratchet** that makes every confirmed mistake a permanent regression guard, the **statistical-honesty rule** that separates a real win from run-to-run noise, the **phase posture** that decides which checks gate vs. only inform, and the **tripwire alarms + runbooks** the continuous-eval pipeline fires when the self-improving loops start to misbehave. It is the place a release captain comes to answer one question: *can this build ship, and if a tripwire trips after it ships, what do we do?*

**Boundary — this doc does not redefine functional policy.** It does **not** define the promotion gate (§23) or the observability policies that *emit* the tripwire signals (§32) — those are owned by other lanes and are exercised, not authored, here. The promotion gate's pass/fail contract is **asserted, not redefined** (`§23` rule restated verbatim in §3.5). The §32 signal-generators (diversity/entropy, proxy-vs-true divergence, no-degradation) belong to the owning lanes; this lane owns only the **alarm thresholds and the continuous-eval response** (the runbooks). All numeric floors are **quoted from §16/§15/§31** as floors; nothing here invents a threshold — where a value is a genuine open product decision it is marked `TBD-by-§N`. Metric definitions live in `01-metrics-specification.md`; concrete test cases in `02a/02b/04-…`; corpora in `03-dataset-and-corpora-spec.md`; harness/CI plumbing in `05-harness-architecture-and-ci-gating.md`. This doc references them; it does not duplicate them.

---

## 1. Vocabulary & owned artifacts

| Term | Meaning |
|---|---|
| **Hard floor** | A release acceptance criterion that **blocks** a release if not met (Phases 0–3). |
| **Protected case** | A test (`protected? = Y`) derived from a confirmed mistake; a regression on it is a release blocker. Lives in `DS-PRIV` (private regression suite, §33). |
| **Protected-fact regression** | A previously-passing protected case now fails (`M-PROTECTED-REG > 0`). |
| **Ratchet** | The append-only discipline (§2) by which protected cases only ever accumulate; never deleted for convenience. |
| **Tripwire** | A continuous-eval alarm (`TW-*`) consuming a §32 signal; fires a runbook (`RB-*`). |
| **Runbook** | The validation-lane response procedure when a tripwire trips. |
| **Discard-the-branch (I3)** | The canonical rollback path: speculative/candidate state lives on a branch; rollback = discard it, clean and transitive by construction (§11-I3, FR-15). |
| **Run-to-run noise** | The measured variability of a metric across identical re-runs; the bar a delta must clear to count as signal (§3.4, ties to §23 "margin > run-to-run noise"). |

---

## 2. The protected-test ratchet (heart of regression protection)

> **Owning rule (§33, asserted here).** Every confirmed mistake — a **user correction** *or* a **resolved failure** — is converted into a **permanent protected test before the fix is considered done**. Protected tests can be quarantined **only by the owning lane with written rationale**; they are **never deleted for convenience**. The ratchet is **append-only**, exactly like the evidence ledger (FR-1).

This is the mechanism that turns G3 ("0 protected-fact regressions after updates") and G5 ("monotonic non-regression on the protected suite") from aspirations into enforced state. A mistake fixed without a protected case is a fix that can silently reappear; the ratchet forbids that.

### 2.1 Operational steps — "no fix is done without its guard"

A fix is **not mergeable** until the ratchet completes. Step-by-step:

- [ ] **1. Trigger detected.** A confirmed mistake exists: either (a) a user issued a correction via `memory.correct` / `profile.correct` (tier-0, authoritative), or (b) a failure was reproduced and resolved (bug, missed retrieval, wrong belief revision, leaked poison, etc.).
- [ ] **2. Reproduce as a failing case.** Author a test in the correct catalog (`T-<DOMAIN>-<NNN>`, owner map per `_CONTRACTS §2`) that **fails on the pre-fix build** through the MCP/CLI surface (§30.7) where possible. The case must back-reference any golden scenario `S1–S12` it refines.
- [ ] **3. Confirm disjointness.** The case's source data must be **disjoint from any candidate's source/training data** — no teaching-to-the-test (§9 / charter §6). Record provenance so the disjointness is auditable.
- [ ] **4. Mark `protected? = Y`** and assign it to the tier (`smoke` / `core` / `archive`, §33) and to `DS-PRIV`.
- [ ] **5. Apply the fix; case now passes.** The same case must pass on the post-fix build. The diff that fixes the bug and the diff that adds the protected case land **together** (or the case lands first, red).
- [ ] **6. Register in the ratchet ledger** (append-only): `case-id`, `requirement(s)`, `originating mistake` (correction id / failure id), `owning lane`, `date`, `tier`. This ledger is the enumerable input to `M-PROTECTED-REG` and to `00-traceability-matrix.md`.
- [ ] **7. Done-check.** CI refuses the merge if a fix references a resolved mistake but no new/updated protected case appears in the ratchet ledger (enforced by `05-harness-architecture-and-ci-gating.md`).

### 2.2 Quarantine — the *only* legal way to stop running a protected case

Deletion is never permitted. **Quarantine** (skip-with-record) is permitted only under all of:

- [ ] **Owning-lane authority only.** Only the lane that owns the case's domain (per `_CONTRACTS §2` owner map) may quarantine it — never the release captain, never the optimizer, never "for convenience."
- [ ] **Written rationale, appended.** A rationale entry is appended to the ratchet ledger (append-only): who, why, the contract change or upstream defect that makes the case currently invalid, and an **exit condition** for un-quarantining.
- [ ] **Never silent.** A quarantined protected case is surfaced on the release scorecard (§7) as an explicit line item; a build with open quarantines ships only if the release captain records acknowledgement.
- [ ] **Append-only invariant.** Quarantine **adds** a status record; it never removes the case row. The case remains in the ledger forever (ratchet is append-only).

### 2.3 Ownership

| Action | Owner |
|---|---|
| Author / register a protected case | The engineer landing the fix + the **owning lane** (domain per owner map) |
| Maintain the ratchet ledger (append-only) | Eval-suite lane (this doc) |
| Quarantine a protected case | **Owning lane only**, with written rationale |
| Enforce "no fix done without its guard" in CI | Harness (`05-…`) |
| Block release on `M-PROTECTED-REG > 0` | Release captain, per §3 |

---

## 3. Release gate — HARD FLOORS (Phases 0–3, gating)

> **Blocking rule.** A regression on **ANY** hard floor below **BLOCKS the release** — no exceptions, no overrides for convenience. Phases 0–3 evals are hard gates (§1.12 posture rule). A floor is "met" only when its metric clears the quoted threshold **and** the delta passes the statistical-honesty rule (§4).

### 3.1 Hard-floor checklist

| # | Hard floor (gate item) | Metric id | Threshold (quoted) | Source | Owning catalog/doc |
|---|---|---|---|---|---|
| H1 | **0 protected-fact regressions** | `M-PROTECTED-REG` | **= 0** per release | §16 ("0 protected-fact regressions/release"); G3/G5 | `DS-PRIV` ratchet (§2); `02a`/`02b`/`04` protected cases |
| H2 | **Recall floor** | `M-RECALL@K` | **≥ stored floor** (`TBD-by-§16` per-corpus value; §16 names recall@k as a leading metric, floor calibrated to data) | §16 | `01-metrics-specification.md`; `02a` (`T-RET-*`) |
| H3 | **Ranking-quality floor** | `M-NDCG@K` | **≥ stored floor** (`TBD-by-§16` per-corpus value) | §16 | `01-…`; `02a` (`T-RET-*`) |
| H4 | **Token-efficiency / answer-quality floor** | `M-TOKEN-EFF` | **≥ +15% answer quality vs full-context at ≤ 10% tokens** | §16; G2; charter S4 | `02a`/`02b`; scenario `S4` |
| H5 | **Calibration error** | `M-ECE` | **≤ 0.05** | §16 | `01-…` (judge/calibration protocol); `02b` (`T-CAL-*`) |
| H6 | **Fast-path latency** | `M-FASTP95` | **≤ ~300–400 ms** (fast-mode P95) | §15 (§22 pipeline) | `02b` (`T-PERF-*`) |
| H7 | **Poisoning block rate** | `M-POISON-BLOCK` | **≥ 95%** | §16; G7 | `04-adversarial-security-playbook.md` (`T-SEC-*`); scenario `S8` |
| H8 | **Benign-drop rate** (no over-blocking) | `M-BENIGN-DROP` | **≈ 0** (benign content not falsely quarantined; tolerance `TBD-by-§16`) | §16 (block-rate paired with false-positive control); G7 | `04-…` (`T-SEC-*`) |
| H9 | **Erasure + transitive invalidation** | `M-ERASURE` | **passes** (delete ⇒ evidence crypto-shredded; all derived projections/indexes/caches/embeddings invalidated or recomputed; corroborated items retained with erased source dropped from provenance) | §14 FR-8; §27 | `02a` (`T-ERA-*`); scenarios `S9`/`S10` |
| H10 | **Local↔production parity** | `M-PARITY` | **identical pass/fail** on both environments | §16; G8 | `02b` (`T-PRT-*`); scenario `S12` |
| H11 | **Deep-mode exact reconstruction** | `M-RECALL@K` (deep-mode exact-reconstruction sub-suite) | **passes** on the adversarial recall suite (`DS-RECALL-ADV`) | §12 G1; charter S1 | `02a` (`T-EVD-*`/`T-RET-*`); scenario `S1` |

> Belief-revision / as-of-time conformance (`M-ASOF-ACC`, `M-AGM-CONF`) and calibrated-abstention precision (`M-ABST-PREC`) become hard floors as their **phase** opens (Phase 2 for G3/G6; see §5). They are listed in `01-metrics-specification.md` and gated per the phase-posture table.

### 3.2 Gate evaluation order (fail-fast)

1. **H1 first.** If `M-PROTECTED-REG > 0`, the release is **blocked** immediately — protected regressions are non-negotiable and short-circuit the rest of the gate.
2. **Security floors (H7–H9).** A poisoning-block or erasure failure blocks regardless of quality wins.
3. **Quality & latency floors (H2–H6, H10–H11).** Each must clear its threshold *and* pass §4.
4. **Open quarantines / open tripwires** surfaced (not auto-blocking unless a tripwire's runbook has frozen promotion — see §6).

### 3.3 What "blocks" means

A blocked release does not ship. The remedy is **not** to weaken the floor (that would violate the invariant rails, §31, which the optimizer can never widen) — it is to fix the regression, then re-run the gate. The reward/verifier (this suite) is `reward_signal: external_only` (§31): the build under test can never edit the gate to pass itself.

### 3.4 Statistical-honesty gate rule

Every gate comparison is a measurement with uncertainty. The rule:

- **Report confidence intervals.** Every metric on the scorecard (§7) carries a CI (bootstrap per `01-metrics-specification.md`). A bare point estimate is not an acceptable gate input.
- **A delta inside run-to-run noise is "no signal."** If a metric's change between candidate and baseline falls **within measured run-to-run noise**, it is **neither a pass-worthy improvement nor a regression** — it is recorded as **"no signal."**
- **Margins must exceed measured noise to count.** An improvement counts as real only if its lower CI bound clears the floor *and* the margin exceeds run-to-run noise; a regression counts as real (and blocks) only if its degradation exceeds run-to-run noise. This is the direct tie to **§23's "margin > run-to-run noise."**
- **Floors are one-sided.** For a hard floor, the **lower** CI bound must sit at or above the threshold (e.g., `M-RECALL@K` lower bound ≥ stored floor; `M-ECE` upper bound ≤ 0.05). A point estimate that clears the floor while its CI straddles it is **"no signal" → does not clear the floor.**
- **Honesty over optics.** A "no signal" result is reported as such on the scorecard; it never silently becomes a green check.

> **Consequence for `M-PROTECTED-REG` (H1):** protected cases are deterministic assertions, not noisy metrics. H1 is **binary** — any protected case flips red ⇒ regression ⇒ block. The noise rule does **not** soften H1.

### 3.5 Promotion gate — asserted, not redefined (from §23)

The eval suite **asserts** the promotion gate's contract; it does not author it. Restated verbatim for the captain's reference:

> A candidate promotes **only if** *non-inferior* **AND** *no protected-case regression* **AND** *margin > run-to-run noise*, with source data **disjoint** from the suite. **Rollback = discard the branch** (I3).

This document's release gate is the *acceptance* layer; the promotion gate (§23) is the *learning-loop* layer that feeds it. Both share the same protected-regression and noise rules above.

---

## 4. Statistical-honesty gate rule (summary card)

| Situation | Verdict |
|---|---|
| Lower CI bound clears floor AND margin > run-to-run noise | **PASS** |
| Point estimate clears floor but CI straddles it | **NO SIGNAL** → does not clear floor |
| Delta within run-to-run noise (better or worse) | **NO SIGNAL** — not a pass, not a regression |
| Degradation exceeds run-to-run noise on a hard floor | **BLOCK** |
| Any protected case flips red (H1) | **BLOCK** (binary; noise rule N/A) |

*(Detailed CI/bootstrap method and per-metric noise estimation: `01-metrics-specification.md`. This card is the gate's decision rule, not the statistics spec.)*

---

## 5. Phase posture — what gates vs. what only informs

Per the posture rule (§1.12): **Phases 0–3 evals are hard gates; Phases 4–5 evals are diagnostics behind rails until their own measurement validity is proven.**

| Phase | Scope | Posture | Becomes-gating condition |
|---|---|---|---|
| **0** Foundations & contracts | Ledger, branches, isolation, MCP/CLI skeleton, CI + seed regression + shadow harness | **GATING** | — (H1, H9 erasure-precursors, H10 parity, idempotent dedup) |
| **1** Lossless memory + hybrid retrieval | G1–G3 partial, G7/G8 partial | **GATING** | — (H2–H4, H10, H11 deep reconstruction; charter S1, S4) |
| **2** Belief core + graph + confidence | G3, G6 | **GATING** | — (`M-AGM-CONF`, `M-ASOF-ACC`, `M-ECE` H5, `M-ABST-PREC`) |
| **3** Personalization + abstention + security + erasure hardening | G4, G6, G7, FR-8 | **GATING** | — (H5–H9, `M-APPLY-ACC`; charter S7, S8, S9, S10) |
| **4** Validated lessons/skills (gated learning) | G5 | **SHADOW-FIRST** | Flips to **GATING once `M-TTL-SLOPE` is positive AND stable** (§16: "positive test-time-learning slope by Phase 4"). Until then: diagnostic, behind rails; never blocks release. |
| **5** Cold-loop self-optimization (PGO) | FR-17 | **SHADOW-ONLY** | Stays shadow-only **until counterfactual-replay fidelity is validated (§17 open question)**. **Never blocks release pre-proof.** Promotion runs on canary branches; rollback = discard branch (I3). |

> Phase-4/5 work runs against the invariant rails (§31) at all times — `consolidation_cadence_bounds: [5_steps, 24h]`, `reward_signal: external_only`, `untrusted_to_system_prompt: forbidden`, `max_supersession_rate: 0.05`, etc. The cold loop tunes **within** these rails and can never widen them; the suite asserts the rails hold under all paths regardless of phase.

---

## 6. Tripwire alarms + runbooks (continuous-eval, consumed from §32)

The §32 observability policies **emit** the signals (diversity/entropy of learned lessons, proxy-vs-true success divergence, long-horizon-vs-no-memory quality). **This lane owns the alarm thresholds and the response runbooks** — not the signal generators. Where a threshold is not fixed in §16 it is marked `TBD-by-§32` (the emitting lane sets the detector's sensitivity; the eval lane sets the *response*).

All three tripwires target the self-improving loops (Phases 4–5) — the cited failure modes from the risk register (§35): model collapse, reward hacking, and consolidated-memory degradation. A tripping tripwire **freezes promotion** (the loop stops landing new learned state) but does **not** by itself revoke an already-shipped release unless its runbook escalates. Rollback path for every runbook is **discard the branch (I3)** — clean and transitive.

### Severity scale
- **SEV-1** — production trust at risk / regression already shipped → page owning lane immediately, freeze promotion, consider rollback.
- **SEV-2** — degradation detected in shadow/continuous-eval, not yet shipped → freeze promotion, investigate within the cycle.

---

### `TW-COLLAPSE` — Model-collapse tripwire → **RB-1**

| Field | Value |
|---|---|
| **Signal (from §32)** | Diversity / entropy of learned lessons (and induced workflows) drops — tails vanishing first (Shumailov et al. 2024 failure mode; §35). |
| **Trigger condition** | Lesson/skill diversity (entropy) falls below the §32 detector threshold over a rolling window. Threshold: `TBD-by-§32`. |
| **Severity** | **SEV-2** in shadow; **SEV-1** if collapsed state was promoted to active. |
| **Immediate action** | **Freeze promotion** of lessons/skills (Phase 4 loop halts landing new learned state). |
| **Who's paged** | Owning lane = **consolidation / gated-learning lane** (lesson-distiller + skill-inducer, §21/§23). Eval-suite lane co-paged (owns the alarm). |
| **Investigate** | Confirm against the **protected suite** (collapse must not have regressed H1); inspect whether the learned set is self-referential (training on own outputs). Cross-check anchor real/edge-data coverage (§35 mitigation). |
| **Rollback path (I3)** | **Discard the candidate/canary branch** carrying the low-diversity learned state — clean, transitive. If collapsed state reached active memory, **rebuild from evidence** (replay the evidence ledger FR-1 through consolidation with diversity-anchored sampling). |
| **Exit criteria** | Lesson/skill entropy recovers above the §32 threshold over the rolling window; **0 protected-fact regressions** (H1) on the rebuilt state; `M-TTL-SLOPE` non-negative; written all-clear appended by the owning lane. Promotion un-frozen only by the owning lane. |

### `TW-REWARDHACK` — Reward-hacking tripwire → **RB-2**

| Field | Value |
|---|---|
| **Signal (from §32)** | **Proxy-vs-true success divergence widens** — the loop's internal proxy reward climbs while true (externally-judged) success does not (or falls). Reward-tampering failure mode (§35). |
| **Trigger condition** | Divergence between proxy success and externally-judged true success exceeds the §32 detector band. Threshold: `TBD-by-§32`. |
| **Severity** | **SEV-1** (reward hacking directly attacks the gate's integrity). |
| **Immediate action** | **Freeze promotion.** **Recall the rail:** `reward_signal: external_only` (§31) — the verifier/eval-suite is **not editable by the optimizer**; confirm the optimizer has not found an indirect path to influence it. |
| **Who's paged** | Owning lane = **cold-loop / PGO lane (§23.4)**. Eval-suite lane co-paged. |
| **Investigate** | **Re-anchor the proxy** to the external judge (`01-metrics-specification.md` judge protocol — strict judge + adversarial-answer screening, §9). Verify the proxy was never inside the self-editable surface; if it was, that is an invariant-rail breach (a finding routed to the §31 owning lane, not a fix here). |
| **Rollback path (I3)** | **Discard the branch** running the hacking policy variant. Restore the last gate-passing policy. |
| **Exit criteria** | Proxy-vs-true divergence back within the §32 band; the reward signal re-confirmed `external_only` and outside the editable surface; **0 protected-fact regressions** (H1); written all-clear by the owning lane before un-freezing promotion. |

### `TW-NODEGRADE` — No-degradation tripwire → **RB-3**

| Field | Value |
|---|---|
| **Signal (from §32)** | Long-horizon **consolidated** answer quality approaches the **no-memory baseline** — i.e., `M-NODEGRADE → 0`. "Useful Memories Become Faulty" failure mode (§35); lossy-summary semantic noise (MMPO). |
| **Trigger condition** | `M-NODEGRADE` (long-horizon consolidated quality minus no-memory baseline) trends toward 0 / below the §32 floor. Threshold: `TBD-by-§32`. |
| **Severity** | **SEV-1** (the system's core promise — memory must beat no-memory — is failing). |
| **Immediate action** | **Halt consolidation-cadence changes** (freeze the cadence knob within rails `[5_steps, 24h]`, §31). Freeze promotion. |
| **Who's paged** | Owning lane = **consolidation lane (§21)**; **page the owning lane** (this is the explicit §35-mandated page). Eval-suite lane co-paged. |
| **Investigate** | Identify whether fidelity-demotion is over-aggressive (gist-only support confabulating, §25 confab-risk flag) or summaries are injecting semantic noise. Confirm raw episodes are still first-class and verbatim drawers retained (§25 anti-degradation guard). |
| **Rollback path (I3)** | **Discard the branch** carrying the degraded consolidation policy. **Rebuild from evidence** — re-consolidate from the evidence ledger (FR-1) with the prior cadence/demotion schedule; pointer-to-original is always retained (§25), so reconstruction is lossless modulo erasure. |
| **Exit criteria** | `M-NODEGRADE` recovers a positive margin above the no-memory baseline over the long-horizon window; deep-mode exact reconstruction (H11) still passes; **0 protected-fact regressions** (H1); written all-clear by the consolidation lane before resuming cadence changes or promotion. |

> **Common runbook spine.** Every runbook: (1) freeze promotion, (2) confirm H1 (`M-PROTECTED-REG = 0`) is held or restored, (3) rollback = **discard the branch (I3)**, rebuild from the evidence ledger if active state was touched, (4) un-freeze only by the **owning lane** with a written all-clear appended to the continuous-eval log. The eval-suite lane never un-freezes another lane's loop unilaterally.

---

## 7. Release-readiness scorecard (template — release captain fills)

The captain completes this table per release candidate. A release ships **only if every hard-floor row is PASS** (H1–H11), no open tripwire has frozen promotion (§6), and every open quarantine (§2.2) is acknowledged. Any **BLOCK** stops the release; any **NO SIGNAL** on a row required to *improve* over a floor is treated as not clearing that floor (§4).

| # | Gate item | Metric id | Threshold (floor) | Result (point est.) | CI (95%) | Noise band | Verdict |
|---|---|---|---|---|---|---|---|
| H1 | 0 protected-fact regressions | `M-PROTECTED-REG` | = 0 | _____ | n/a (binary) | n/a | ☐ PASS / ☐ **BLOCK** |
| H2 | Recall floor | `M-RECALL@K` | ≥ stored floor (`TBD-by-§16`) | _____ | [__,__] | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H3 | Ranking quality | `M-NDCG@K` | ≥ stored floor (`TBD-by-§16`) | _____ | [__,__] | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H4 | Token-eff / answer quality | `M-TOKEN-EFF` | ≥ +15% @ ≤10% tokens | _____ | [__,__] | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H5 | Calibration error | `M-ECE` | ≤ 0.05 | _____ | [__,__] (upper) | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H6 | Fast-path latency | `M-FASTP95` | ≤ ~300–400 ms | _____ | [__,__] | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H7 | Poisoning block rate | `M-POISON-BLOCK` | ≥ 95% | _____ | [__,__] | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H8 | Benign-drop rate | `M-BENIGN-DROP` | ≈ 0 (tol `TBD-by-§16`) | _____ | [__,__] | ±__ | ☐ PASS / ☐ NO SIGNAL / ☐ BLOCK |
| H9 | Erasure + transitive invalidation | `M-ERASURE` | passes | _____ | n/a (binary) | n/a | ☐ PASS / ☐ **BLOCK** |
| H10 | Local↔production parity | `M-PARITY` | identical pass/fail | _____ | n/a (binary) | n/a | ☐ PASS / ☐ **BLOCK** |
| H11 | Deep-mode exact reconstruction | `M-RECALL@K` (deep) | passes (`DS-RECALL-ADV`) | _____ | n/a (binary) | n/a | ☐ PASS / ☐ **BLOCK** |

**Phase-2/3 floors as they open** (append rows when the phase is gating, §5): `M-AGM-CONF` (contradiction-resolution conformance), `M-ASOF-ACC` (as-of-time), `M-ABST-PREC` (abstention precision), `M-APPLY-ACC` (personalization application).

**Sign-off block:**

| Check | Status |
|---|---|
| All hard-floor rows PASS (H1–H11) | ☐ |
| No open tripwire has frozen promotion (`TW-COLLAPSE` / `TW-REWARDHACK` / `TW-NODEGRADE`) | ☐ |
| Open protected-case quarantines acknowledged (count: __) | ☐ |
| Statistical-honesty rule applied to every non-binary row (CIs reported; "no signal" not counted as pass) | ☐ |
| Phase posture correct for build (Phase 4 gating only if `M-TTL-SLOPE` positive & stable; Phase 5 shadow-only) | ☐ |
| **Release decision** | ☐ SHIP / ☐ **BLOCK** |

*Release captain: ______________  Date: __________  Build/commit: __________*

---

## 8. Cross-references

- Metric definitions, formulas, judge protocol, CI/bootstrap method, target derivation → `01-metrics-specification.md`.
- Protected cases (correctness/retrieval/temporal/lifecycle) → `02a-catalog-correctness-retrieval-temporal-lifecycle.md`.
- Protected cases (calibration/personalization/invariants/portability/perf) → `02b-catalog-calibration-personalization-invariants-portability-perf.md`.
- Security protected cases + poisoning/erasure attack scenarios → `04-adversarial-security-playbook.md`.
- Corpora (`DS-PRIV`, `DS-RECALL-ADV`, `DS-POISON`, …) → `03-dataset-and-corpora-spec.md`.
- CI triggers, shadow↔active switching, "no fix done without its guard" enforcement, dashboards → `05-harness-architecture-and-ci-gating.md`.
- Goal×FR×Metric×Test×Scenario×Protected coverage and gaps → `00-traceability-matrix.md`.
- Golden scenarios `S1`–`S12` → charter `../Mnemosyne-Evaluation-and-Test-Plan.md §4`.
- Fixed contracts, thresholds, ID schemes, conventions → `_CONTRACTS.md`.
