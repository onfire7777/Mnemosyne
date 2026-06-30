# Mnemosyne — Blueprint Parity Matrix

**Maintained by:** AUX-DOCS lane (traceability synthesis). **This is a read-and-track artifact, not a spec.**
**Date:** 2026-06-26 sync note over 2026-06-23 traceability matrix; current repo root: `/Users/admin/Mnemosyne` → `github.com/onfire7777/Mnemosyne`.
**Goal it serves:** exact 1:1 parity with `Mnemosyne-v2-Build-Blueprint.md` (§1–§38 + Appendices A–E).

> **Supersession note (2026-06-25):** this matrix is retained as a traceability
> synthesis. The current status source is
> `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` plus `.planning/STATE.md` and
> `docs/ROADMAP-TO-100.md`. Older rows below that describe ECE/G2 as failing,
> Tier-A rails as open, or
> operator-deferred are superseded by the 2026-06-24/25 updates: mandatory Tier A
> wirings are closed, all 6 headline SLOs are proven locally/compose, and the
> remaining local work is to keep proof artifacts current while Tier B operator
> production-evidence rows remain the blocking parity class.

## Purpose & method

This matrix maps every blueprint surface to the module that implements it, the test that
proves it, and a parity status. It is a **synthesis of existing authoritative sources**, not a
re-derivation — when a status is disputed, the cited source wins:

- **`Mnemosyne-v2-Build-Blueprint.md`** — the spec (scope source).
- **`.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`** — the standing parity audit ("gaps remain; exact 1:1 parity not complete").
- **AUX-XREF traceability audit (Builder 7)** — 6-auditor read-of-source verification of innovations, FRs, NFRs, DDL, ABI, tests. Folded into §2–§6 below.
- **`.planning/ROADMAP.md`** + **`.planning/REQUIREMENTS.md`** — phase/requirement decomposition and per-REQ status.

**Status legend:** ✅ implemented + tested matching blueprint · 🟡 partial / deterministic stand-in / under-tested · ❌ missing · 🔒 deferred (operator-run deployment evidence — *not* a code defect; do not fabricate).
**Gap legend (for the actionable list, §7):** `[C]` codeable now behind existing boundaries · `[T]` test-only · `[D]` deferred-operator.

> **Module/test names below are verified to exist in `src/mnemosyne/` and `tests/` as of this commit.** New parity tests assigned to lanes (e.g. `test_parity_mcp.py`, `test_parity_retrieval.py`, `test_parity_security.py`) and the `providers/**` package are landing during the active completion effort; rows referencing them are marked *(new, lane)* until merged.

---

## 1. Phase parity (ROADMAP Phase 0–6)

| Phase | Title | Requirements | Status | Notes |
|---|---|---|---|---|
| 0 | Foundations & Contracts | REQ-001/002/003/004/011 | ✅ | Evidence ledger, branches, isolation, MCP/CLI skeleton, seed regression suite. |
| 1 | Lossless Memory & Hybrid Retrieval | REQ-005/006/007/008/009 | ✅ | Bitemporal assertions, provenance, hybrid retrieval, explain, correct, export, forget. |
| 2 | Belief Core, Graph, Confidence | REQ-013/014/009 | ✅ (🟡 depth) | TMS/AGM cascade, graph adapter, conformal calibration, multi-hypothesis. Depth gaps: I2/I8 (§7). |
| 3 | Personalization & Consolidation | REQ-012/015/016 | ✅ (🟡 depth) | Six-category user model, latent advisory, warm-loop consolidation, fidelity lifecycle, anti-degradation. |
| 4 | Procedural & Corrective Learning | REQ-017/010/011 | ✅ (🟡 depth) | Trajectory logging, failure attribution, lesson induction, promotion gate, branch promote/rollback, capability-secured writes. Depth: I12 (§7). |
| 5 | Profile-Guided Self-Optimization | REQ-018/011/NFR-005 | ✅ (🟡 depth) | Shadow-first policy optimization, self-model store, canary branches, diversity tripwire, parametric tier. |
| 6 | **Exact Blueprint Runtime Parity** | FR-3/7/9/12/18/19/20/21, production NFRs | 🟡 **in progress** | The active completion effort. Closes the depth-gaps in §2–§7 behind existing provider boundaries + production-evidence rows (🔒). |

Phases 0–5 are checked complete in the roadmap; **Phase 6 is the open milestone** this matrix tracks.

---

## 2. The Twelve Innovations (§11) — I1–I12

| Ref | Innovation | Module(s) | Test(s) | Status | Gap → §7 item | Lane |
|---|---|---|---|---|---|---|
| I1 | Self-optimizing compiler / PGO frame | `self_optimization`, `engine`, `gate` | `test_self_optimization` | ✅ | — | CC-LS |
| I2 | TMS justifications + AGM minimal-change | `belief`, `models` | `test_belief_and_calibration` | 🟡 | #13 explicit AGM ops + ATMS labels | CC-BC |
| I3 | Content-addressed branchable memory | `storage`, `engine`, `ids` | `test_engine_contract` | ✅ | (merge = replica-upsert, not 3-way — by design) | CC-PG |
| I4 | Unified associative substrate | `retrieval`, `engine`, `graph`, schema | `test_engine_contract` | ✅ | #1 `assertions.salience` column | CC-R/CC-PG |
| I5 | Bitemporal facts + queryable provenance | `provenance`, `models`, `engine` | `test_engine_contract` | 🟡 | #25 semiring how-provenance (named "genuine opening") | CC-UPS |
| I6 | Incremental view maintenance | `consolidation`, `belief`, `jobs` | `test_cli_runtime_tools`, `test_runtime_parity_extensions` | ✅ local | #11 dirty-set/memoization is wired locally; production evidence remains Tier B | CC-BC |
| I7 | Graduated forgetting fidelity tiers | `lifecycle` | `test_blueprint_later_phases` | 🟡 | #14 enforce `must_keep` + pointer-to-original | CC-BC |
| I8 | Confidence + conformal abstention | `calibration`, `engine` | `test_belief_and_calibration` | 🟡 | #12 per-example nonconformity | CC-BC |
| I9 | Latent-advisory + explicit-authoritative model | `user_model` | `test_user_model_and_guards` | ✅ | (`latent_never_overrides_explicit` enforced) | CC-UPS |
| I10 | Speculative anticipatory prefetch | `prefetch` | `test_runtime_parity_extensions` | 🟡 | learned predictor + hit-rate metric | CC-R |
| I11 | Capability-secured writes + signed provenance | `security`, `provenance` | `test_runtime_parity_extensions`, `test_security_sessions` | 🟡 | #27 taint labels + propagation | CC-SEC |
| I12 | PGO self-opt + counterfactual replay eval | `self_optimization`, `gate`, `learning`, `eval` | `test_self_optimization` | 🟡 | #19 implement + wire `counterfactual_replay_score()` | CC-LS |

§11.13 honesty map (doc-only): the three self-flagged "genuine openings" (semiring/IVM/capability ≈ I5/I6/I11) are exactly the thinnest code areas — consistent with the audit.

---

## 3. Functional Requirements (§14) — FR-1…FR-21

| Ref | Requirement | Module | Status | Gap → §7 | Lane |
|---|---|---|---|---|---|
| FR-1 | Append-only content-addressed ledger | `engine`/`ingestion`/`storage` | ✅ | — | CC-RT |
| FR-2 | Bitemporal + supersession, no overwrite | `belief`/`engine` | ✅ | — | CC-BC |
| FR-3 | Hybrid dense+lexical+graph, RRF, rerank, MMR, U-curve, budget | `engine`/`retrieval` | 🟡 | #6 fast-path cached graph signal | CC-R |
| FR-4 | Provenance links + explain attribution | `provenance`/`engine` | ✅ | — | CC-UPS |
| FR-5 | Six typed prefs, authority order | `user_model` | ✅ | — | CC-UPS |
| FR-6 | Calibrated confidence + conformal abstention | `calibration`/`engine` | ✅ (🟡 I8) | #12 | CC-BC |
| FR-7 | Tenant/source isolation, trust tiers, gated writes, audit | `security`/`engine`/`ingestion` | ✅ | — | CC-SEC |
| FR-8 | Inspect/correct/export/forget transitive crypto-shred | `privacy`/`storage`/`engine` | ✅ | — | CC-SEC |
| FR-9 | Stable MCP/CLI tool contract | `mcp_tools`/`mcp_server`/`cli` | ✅ | — | CC-MCP |
| FR-10 | Belief-revision TMS+AGM, cascade, contested | `belief`/`engine` | ✅ (🟡 I2) | #13 | CC-BC |
| FR-11 | Temporal graph + PPR (deep) + cached signal (fast) | `graph`/`engine` | 🟡 | #6 | CC-BC/CC-R |
| FR-12 | Consolidation warm loop | `consolidation` | ✅ | #16 cadence-bound | CC-BC |
| FR-13 | Fidelity-tiered forgetting | `lifecycle`/`consolidation` | ✅ | #14 | CC-BC |
| FR-14 | Procedural/corrective learning, gated | `learning`/`gate` | ✅ | #20 CRITIC loop | CC-LS |
| FR-15 | Branchable memory; rollback = discard | `engine`/`gate` | ✅ | — | CC-RT |
| FR-16 | Latent advisory user embedding | `user_model`/`consolidation` | 🟡 | #26 beyond hashing stand-in | CC-UPS |
| FR-17 | Profile-guided self-opt cold loop, shadow-only | `self_optimization` | 🟡 | #19 | CC-LS |
| FR-18 | Anticipatory prefetch w/ predictability gate | `prefetch` | ✅ (🟡 I10) | — | CC-R |
| FR-19 | Signed C2PA provenance ingestion | `provenance` | ✅ | real cert-chain 🔒 | CC-UPS/CC-SEC |
| FR-20 | Multimodal memory behind same interface | `media`/`ingestion` | ✅ | — | CC-UPS |
| FR-21 | Parametric tier (LoRA), isolated + gated | `parametric` | ✅ | real trainer 🔒 | CC-LS |

---

## 4. Requirements ledger (REQ-001…REQ-018)

Status mirrors `.planning/REQUIREMENTS.md` (P0/P1) — all P0 must-haves implemented and tested locally;
several carry production-evidence gates (release-audit / provider-check / OIDC-JWKS) that are 🔒 until operator-run.

| ID | Blueprint anchor | Status |
|---|---|---|
| REQ-001 evidence ledger | FR-1, Phase 0 | ✅ local |
| REQ-002 branchable memory + merge promotion | I3, Phase 0/4 | ✅ local + clean-DSN; deploy evidence via `release-audit` 🔒 |
| REQ-003 tenant/source isolation + trust tiers | FR-7, §27 | ✅ local + RLS live; prod auth via OIDC/JWKS gates 🔒 |
| REQ-004 stable MCP/CLI contract | FR-9, §30.7 | ✅ local |
| REQ-005 bitemporal store + as-of | FR-2, Phase 1 | ✅ local |
| REQ-006 hybrid retrieval (lexical/dense/graph, RRF, MMR, budget, provenance, trust) | FR-3, §22, §30.4 | ✅ local (🟡 depth #6–#9); prod embedding/reranker/backends via provider-check 🔒 |
| REQ-007 explainability facts→evidence→channels | FR-4 | ✅ local |
| REQ-008 inspect/correct/export/forget transitive | FR-8, §25 | ✅ local |
| REQ-009 confidence + abstention | FR-6, §26 | ✅ local; `calibration-tune` for prod thresholds 🔒 |
| REQ-010 capability-mediated writes + audit + reversibility | FR-7, §27 | ✅ local; prod role/auth via release-audit 🔒 |
| REQ-011 private regression suite + protected cases + shadow + gate | §23.3, §33 | ✅ local; release-audit artifact validation 🔒 |
| REQ-012 user model / personalization | Phase 3 | ✅ model/runtime (dedicated UX out of blocking path) |
| REQ-013 belief core / TMS / contested | Phase 2 | ✅ (🟡 I2) |
| REQ-014 graph + PPR | Phase 2 | ✅ (🟡 fast-path #6) |
| REQ-015 fidelity lifecycle + spaced rehearsal | Phase 3 | ✅ storage-backed; `forgetting-policy-check` 🔒 |
| REQ-016 warm-loop consolidation (society of roles) | Phase 3 | ✅ role-pipeline provenance; `hosted-llm-check` 🔒 |
| REQ-017 procedural/corrective learning | Phase 4 | ✅ |
| REQ-018 profile-guided self-optimization (bandit, shadow) | Phase 5 | ✅ contextual-bandit + UCB; `policy-ops-check` 🔒 |

---

## 5. Blueprint implementation sections (§18–§33, §30.x, App A/B)

| Blueprint area | Module(s) | Status | Notes / gap → §7 |
|---|---|---|---|
| §18–19 substrate / data model (DDL) | `models`, `storage`, `sql/schema.sql` | ✅ (🟡 columns) | All 20 tables exist; RLS verified. DDL column gaps #1–#4. |
| §20 ingestion (hot path) | `ingestion`, `engine` | 🟡 | ❌ §20.7 tier-0 correction shortcut (#23) — highest-value missing feature. |
| §21 consolidation (society of roles) | `consolidation` | ✅ | 11-pass; cadence-bound anti-thrash missing (#16). |
| §22 retrieval | `retrieval`, `engine`, `graph` | 🟡 | #6 fast-graph, #7 spreading term, #8 channels, #9 marginal-gain cutoff. |
| §23 self-improvement (hot/cold loops) | `learning`, `self_optimization`, `gate` | 🟡 | #17 corroboration gate, #19 counterfactual replay, #20 CRITIC loop. |
| §24 learn-from-user-mistakes | `user_model` | ❌ | #24 scoped support strategy entirely missing. |
| §25 forgetting / metacognition | `lifecycle`, `guard` | 🟡 | #14 must_keep + pointer, #30 long-horizon anti-degradation. |
| §26 confidence / abstention | `calibration`, `engine` | 🟡 | #18 persist+fuse `calibrated_confidence`. |
| §27 security & governance | `security`, `privacy`, `oidc_jwks` | ✅ (🟡) | #27 taint labels, #28 quarantine component; C2PA cert-chain 🔒. |
| §30.1 engine contract | `engine` | ✅ | Full `MemoryEngine(Protocol)`, Local+Postgres impls, substitutability suite. |
| §30.2 ingestion shortcut | `ingestion`, `belief` | ❌ | tier-0 correction (#23 + #15) — pairs CC-UPS/CC-BC. |
| §30.3 belief revision | `belief` | ✅ | ADD/UPDATE/SUPERSEDE/NOOP/CONTEST + TMS cascade. |
| §30.4 retrieval fast path | `retrieval`, `engine` | 🟡 | #29 cheap classifier `route()` vs hardcoded `deep` bool. |
| §30.5 consolidation worker | `consolidation` | ✅ | candidate-until-gate; `projection_recompute`. |
| §30.6 promotion gate + branches | `gate`, `engine` | ✅ | Counterfactual replay scorer is wired into the gate surface; cold-loop promotion remains rail-gated. |
| §30.7 agent-facing API / MCP tools | `mcp_tools`, `mcp_server`, `cli` | ✅ | Every blueprint-named tool in TOOL_SPEC; CLI parity. **No parity gaps (CC-MCP).** |
| §31 configuration & invariant rails | `policy`, `security`, `config/drift-baseline.toml` | ✅ | Numeric rail values are mirrored by config drift tests; remaining evidence gaps are operator-run Tier B, not missing local constants. |
| §33 testing & eval harness | `eval`, `benchmarks`, `tests/` | 🟡 | #10 recall@k/nDCG, #21 ECE/poison-block/TTL-lift metrics. |

---

## 6. NFRs (§15) & success metrics (§16)

- **NFRs:** reliability / privacy / portability / observability ✅. Latency 🟡 (P95<300ms proven only on small in-memory seed, not at 10⁵ scale). Scale/cost 🟡 (no volume/cost benchmark) → 🔒 scale benchmarks.
- **Success metrics (§16):** the measurement cluster is now **implemented-in-`eval/`** (see §11) — recall@k / nDCG / ECE / poison-block-rate / latency-SLO are real and computable (`eval/harness/metrics.py`, `eval/calibration/`, `eval/latency/`). AUX-QA (B6) confirms at-target by running them; prod-scale SLO at volume stays 🔒 (§8). *(Pre-completion snapshot read 🟡 "harnesses exist, numbers do not"; that is now closed structurally.)*

---

## 7. Actionable parity gap list (folds AUX-XREF §G, Builder 7)

Lane-routed. Status tracked here; owning lane commits only its own files. Cross-lane pairs agree an interface, each committing its own side.

### CC-PG (B4) — schema parity (migration-safe additive)
> **✅ CLOSED @`5103a3a`** (migration-safe additive `ALTER … ADD COLUMN IF NOT EXISTS`): `assertions.{salience,calibrated_confidence,recorded_time}`, `relations.{weight,recorded_at,expired_at,justification_id,status}`, `preferences.superseded_by` — closes items #1–#4 and the column side of #18. (#5 column-level drift guard: B4 `2c1a40d`.)

1. `[C]` add `assertions.salience` (I4 activation) + populate. ✅ column @`5103a3a`
2. `[C]` restore bitemporal `evidence.event_time`+`recorded_time` (or document the collapse w/ test). 🟡
3. `[C]` `relations.{weight,recorded_at,expired_at,justification_id,status}`. 🟡
4. `[C]` `preferences.superseded_by`. 🟡
5. `[C/T]` column-level schema-drift test (catch `gold→expected`, `parent→from_branch`, `window→metric_window`, `calibrated_confidence→calibration` renames). *(coordinate AUX-DOCS `test_config_drift`)*

### CC-R (B11) — retrieval depth + metrics
6. `[C]` fast-path cached graph signal (PPR/1-hop) so fast `retrieve()` fuses graph without `deep=True` (§22.5). *(coordinate CC-BC precompute)*
7. `[C]` add `w_s·spreading(m,q)` term to activation score (§22.4).
8. `[C]` add preference/procedure/lesson channels to `retrieve()` (§22.2).
9. `[C]` expected-marginal-gain top-k cutoff (ACT-R `C>pG`) (§22.4).
10. `[C/T]` recall@k / nDCG benchmark in `benchmarks.py`; latency SLO at larger seed.

### CC-BC (B12) — belief/calibration/consolidation/lifecycle
11. `[C]` real IVM dirty-set/memoization + auto-trigger (I6). ✅ local: projection recompute walks affected evidence/projection edges, queues only dirty surviving source inputs, and memo-skips unchanged fingerprints; production proof remains Tier B.
12. `[C]` per-example conformal nonconformity (I8).
13. `[C]` explicit AGM expansion/revision/contraction + ATMS labels (I2).
14. `[C]` enforce `must_keep` in lifecycle demotion + pointer-to-original (I7/§25).
15. `[C]` tier-0 correction → same-turn supersession in belief core (pairs #23). + `[T]`.
16. `[C]` cadence-bound consolidation anti-thrash (§21).
17. `[C]` gate fact-candidates by external corroboration (§23.3).
18. `[C]` persist + compute per-memory `calibrated_confidence`, fuse signals (§26). *(needs CC-PG column)*

### CC-LS (B2) — learning/self-opt/eval
19. `[C]` implement counterfactual replay + wire dead `counterfactual_replay_score()` into gate/eval (I12/§30.6).
20. `[C]` hot-loop CRITIC verify-with-tools → candidate-lesson (§23.1). *(in progress — see commit `f7e4180`)*
21. `[C/T]` `eval.py` recall@k/nDCG + ECE + poison-block-rate% + TTL-lift + shadow-mode harness.
22. `[C/T]` pin numeric invariant-rail VALUES (`max_supersession_rate`≈0.05, `min_corroboration`≈2, `max_prune_fraction`) as live constants tested by config-drift (§31). *(CC-LS adds constants on `OperatingPolicy`; AUX-DOCS pins them in `config/drift-baseline.toml` + `test_config_drift.py`.)*

### CC-UPS (B3) — user-model/ingestion/provenance
23. `[C]` **tier-0 user-correction hot-path shortcut** (`is_tier0_user_correction`→ungated apply) (§20.7/§30.2) — **highest-value missing feature** (pairs #15).
24. `[C]` §24 learn-from-user-mistakes → scoped support strategy. ❌→
25. `[C]` semiring how-provenance tags + combine operators (I5) *(or document deferred-by-design)*.
26. `[C]` latent user embedding beyond `hashing_embedding` stand-in where codeable (FR-16).

### CC-SEC (B10) — security
27. `[C]` taint labels + propagation blocking on data≠instruction (I11) + write-path tests.
28. `[C]` distinct no-write quarantine component (§27). C2PA real cert-chain = 🔒.

### CC-RT (B1) — engine/gate/guard
29. `[C]` cheap classifier `route()` for fast-vs-deep instead of hardcoded bool (§30.4). *(coordinate CC-R)*
30. `[C]` deepen `guard.py` anti-degradation to long-horizon tracked metric (§25) + gate hook for #19.

### Cross-lane pairs (agree interface; each commits only its own files)
- **tier-0 correction:** CC-UPS #23 (`ingestion.py`) + CC-BC #15 (`belief.py`).
- **calibrated_confidence:** CC-BC #18 (compute) + CC-PG (column).
- **fast-graph:** CC-R #6 + CC-BC precompute.
- **route():** CC-RT #29 + CC-R.
- **numeric rail pins:** CC-LS #22 (constants) + AUX-DOCS (`drift-baseline.toml` + `test_config_drift.py`).

---

## 8. Deferred (🔒 operator deployment evidence — NOT code defects, do not fabricate)

> See **§12** for the full three-bucket accounting that keeps "complete" honest: CLOSED vs DEFERRED-BY-DESIGN (codeable but deliberately out of safe scope, with rationale) vs DEFERRED-OPERATOR (this section).

The provider boundaries already exist in code; these require real infrastructure an operator runs:

- Production ParadeDB/BM25 lexical, Apache AGE graph, pgvector-at-scale adapters.
- Real IdP/JWKS rotation, KMS/HSM/Vault secret manager, TLS lifecycle, hosted MCP soak.
- Real LoRA / test-time-training behind the `parametric` provider boundary.
- Real C2PA signature / certificate-chain verification.
- Scale benchmarks (10⁵ local / 10⁸ prod) and numeric SLO proof at volume.

Local infra now available for *some* of these (Postgres :54329, Vault :8211, Keycloak :8089) — where a live check closes a parity row (e.g. OIDC via Keycloak, secrets via Vault), the owning lane pursues it; genuinely-cloud evidence stays 🔒.

---

## 9. Headline

> **Historical snapshot.** Sections 2–7 and 9–11 describe the 2026-06-23
> completion-merge overlay. They are retained for lineage only. Current source
> of truth is `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`,
> `.planning/OPS-HANDOFF-AND-OWNERSHIP.md`, and `docs/ROADMAP-TO-100.md`: Tier
> A/local code readiness is closed, and strict v1.0 parity remains blocked by
> Tier-B operator-captured production evidence for the 10 Partial rows.

In the historical 2026-06-23 snapshot, no innovation was a total ❌ and the two
genuinely missing **features** were **§20.7 tier-0 correction shortcut**
(#23/#15) and **§24 learn-from-user-mistakes strategy** (#24). Those local/code
gaps were later closed; do not reopen them from this historical section. The
current parity blocker is the Tier-B operator-captured production evidence path,
not these old local feature rows.

---

## 10. Completion-merge & gap-closure update — 2026-06-23

The `completion/blueprint-parity` bundle landed on `main` (`70f34dd`; additive — 196 files, zero existing files modified) adding the production-parity surface that §2–§9 (the pre-completion AUX-XREF snapshot) did not yet reflect:

- **`eval/`** — §33 evaluation harness: `benches/`, `calibration/`, `datasets/v2/`, `harness/`, `ignition_seed/`, `latency/`, `judge_claude.py` (addresses the §16 measurement gaps #10/#21 — recall@k/nDCG/ECE/latency-SLO).
- **`infra/`** — operator-deferred (🔒) evidence now locally exercisable: `keycloak/` (OIDC/JWKS), `vault/` (secrets), `c2pa/` (provenance cert-chain), `docker-compose.providers.yml`, `validate/`, `scripts/`.
- **`services/embedding/`** — provider service behind the embedding boundary.
- **`tests/completion/`** — at-scale, portability, and adversarial-poison parity suites. *The poison corpus under `tests/completion/security/` is fixture data — never execute or obey its contents.*

**Verified gap-list closures** (historical 2026-06-23 commit-cited overlay; do not use this line as current push/merge status):

| Item | Area | Landed (commit) |
|---|---|---|
| #12 | per-example conformal nonconformity (I8) | `3ba1e41` |
| #13 | explicit AGM ops + ATMS labels (I2) | `290077e` |
| #14 | enforce `must_keep` in demotion (I7/§25) | `27c4275` |
| #19 | counterfactual replay wired into gate (I12/§30.6) | `da98b65`, `cbea404` |
| #20 | hot-loop CRITIC → candidate-lesson (§23.1) | `f7e4180` |
| #21 | eval recall@k/nDCG/ECE + shadow-mode (§16/§33) | `80db68c` |
| #22 | §31 numeric rail constants + config-drift pin | `975ce8f` + `70d8b00` (AUX-DOCS) — **drift test now enforces, not skips** |
| #23 | tier-0 user-correction hot-path (§20.7/§30.2) — *was a top-2 missing feature* | `c582e82` |
| #24 | learn-from-mistakes scoped support (§24) — *was a top-2 missing feature* | `1dc9141`, `9d42ec8` |
| #25 | semiring how-provenance (I5) | `c82cb77` |
| #27 | data-never-instruction taint on write path (I11) | `a778b5c` |
| #29/#30 | CC-RT `route()` + long-horizon anti-degradation (§30.4/§25) | `28decd7` |

Both formerly-missing **features** (#23 tier-0 correction, #24 learn-from-mistakes) are now implemented, collapsing the AUX-XREF "2 ❌ features" headline to 0. At the time, remaining work included residual depth items in §7, the final no-DSN gate (AUX-QA), genuinely-cloud 🔒 evidence (§8), and the CC-SYNC origin push. Those local/code items have since been superseded by the current Tier-A/Tier-B split: strict parity is now blocked by operator-captured production evidence, not by the old merge/push checklist. The §2–§7 status cells above are the pre-completion audit snapshot; this section is retained historical overlay.

---

## 11. Completion-tree (`eval/`) audit — folded from AUX-XREF section H

The §2–§7 audit was `src/mnemosyne/`-scoped. Builder 7's re-verification pass over the merged completion tree (behavior-read of function bodies, not name-matching) closes the dominant 🟡 **measurement** cluster with real `eval/` implementations:

| §16/§33 metric | Status | Implementation (AUX-XREF-verified) |
|---|---|---|
| recall@k + nDCG@k (#10/#21) | ✅ implemented-in-`eval/` | `eval/harness/metrics.py:recall_at_k / dcg_at_k / ndcg_at_k` (real DCG/IDCG) |
| ECE / calibration (#21) | ✅ implemented-in-`eval/` | `metrics.py:expected_calibration_error`; `eval/calibration/runner.py` drives the real engine → ECE + Brier + reliability table |
| answer-quality vs full-context (G2) | ✅ implemented-in-`eval/` | `eval/harness/answer_quality.py` (≥+15% quality at ≤10% tokens; tiktoken + substring/LLM judge) |
| poison-block-rate (#21) | ✅ implemented-in-`eval/` | `eval/harness/suites.py:poison_suite_eval` + `poison_block_rate_g7` ≥0.95 gate, asserted in `eval/tests/test_harness_integration.py` |
| latency SLO (NFR-latency) | ✅ implemented-in-`eval/` | `eval/latency/bench.py` + `metrics.py:percentile/latency_summary` (p50/p95), `eval/latency_warm/`, `eval/datasets/v2/run_slo_v2_definitive.py`; Wilson / bootstrap intervals |
| regression-ignition (OQ) | ✅ implemented-in-`eval/` | `eval/ignition_seed/` (cases.json + loader + ignition_status) |
| OQ3 recompute-amplification / OQ7 capability-overhead | ✅ benched | `eval/benches/bench_oq3_*` + `bench_oq7_*` |

Also verified-closed by AUX-XREF on the merged baseline (`@67cbf6c`): **#23** tier-0 correction (`ingestion.py:is_tier0_user_correction`→ungated `upsert_assertion`, `c582e82`), **#24** user-mistake support strategy (`user_model.py:record_user_mistake`→scoped `SupportStrategy`, `1dc9141`), **#25** semiring how-provenance (`provenance.py:HowProvenance` combine_or/and/prune, `c82cb77`).

**Caveat (AUX-QA owns):** these harnesses target the deterministic local engine; "green / at-target" is confirmed by AUX-QA (B6) *running* them, not asserted here.

**Explicit DEFERRED (🔒 operator-run — NOT closed by `eval/`):** prod-scale SLO at volume (10⁵ local / 10⁸ prod); real C2PA signature / certificate-chain; real LoRA / test-time-training trainer; live IdP/JWKS + KMS/Vault rotation. FR-16 latent embedding stays an accepted deterministic local default (`hashing_embedding`) behind the existing HTTP embedding boundary — not a defect.

---

## 12. Final accounting — three distinct buckets (so "complete" is honest)

Remaining-vs-done splits into three buckets that must **not** be conflated. Nothing in 12.2/12.3 is fabricated as "done."

### 12.1 CLOSED — structurally implemented + landed
- **DDL parity** — B4 `5103a3a` (migration-safe additive `ALTER … ADD COLUMN IF NOT EXISTS`): `assertions.{salience, calibrated_confidence, recorded_time}`, `relations.{weight, recorded_at, expired_at, justification_id, status}`, `preferences.superseded_by`. Closes §7 items #1–#4 + the column side of #18; column-level drift guard `2c1a40d`.
- **Feature + depth closures** (§10): items #12–14, #19–25, #27, #29–30 — including both formerly-missing features (#23 tier-0 correction, #24 learn-from-mistakes).
- **Measurement cluster** (§11): recall@k / nDCG / ECE / poison-block-rate / latency-SLO implemented in `eval/` (AUX-QA confirms at-target by running).

### 12.2 DEFERRED-BY-DESIGN — codeable, but deliberately out of safe scope (with rationale; NOT a defect, NOT operator-evidence)
The code seam exists and the deterministic local behavior is correct and tested; going further is a conscious scope boundary, not a gap:
- **#11 true IVM (I6)** — `projection_recompute` already covers the affected subgraph; full incremental view maintenance is a behavior-equivalent *performance* optimization. Blueprint §11.13 itself names this a "genuine opening."
- **#18 `calibrated_confidence` behavioral compute + fuse** — the column is present (12.1); fusing verbalized + entropy + retrieval-agreement + provenance needs a frozen `models.py` field + CC-R fusion. Packet-level conformal abstention already exists.
- **salience → activation behavioral wiring** — the column is present (12.1); wiring it into the activation scorer is an opt-in seam.
- **FR-16 latent learned embedding** — the HTTP embedding boundary exists; the deterministic `hashing_embedding` is the intended local-mode default, not a stand-in to "fix."

### 12.3 DEFERRED-OPERATOR — 🔒 not codeable in this environment (requires real infrastructure / a real model an operator runs)
- Prod-scale SLO at volume (10⁵ local / 10⁸ prod); real C2PA signature / certificate-chain; real LoRA / test-time-training trainer deployment; live IdP/JWKS + KMS/Vault + TLS rotation; production ParadeDB/BM25, Apache AGE, and hosted reranker adapters. The provider boundaries already exist in code.
- **Superseded SLO note:** the historical ECE/G2 deferral is no longer current.
  The controlling strict audit records 6/6 headline SLOs proven after the
  calibrated-confidence and retrieval-source wirings landed; `eval/calibration/report.json`
  reports ECE 0.0063 against the ≤0.05 target. Production-scale reruns still
  belong to Tier B operator evidence, but ECE/G2 are not open code gaps in this
  matrix anymore.

**Honest "complete":** 12.1 is done; 12.2 is a rationale-backed scope boundary (seams present, deterministic local behavior correct + tested); 12.3 is the operator's deployment surface with boundaries already in place.

---

## 13. Historical Tier-A checklist status

This section is no longer the authoritative open-gap list. It is retained to
prevent older `xfail(strict)` notes from reopening closed Tier-A work. The
current open status is controlled by `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`,
`.planning/STATE.md`, and `docs/ROADMAP-TO-100.md`.

| Historical item | Current status | Acceptance signal |
|---|---|---|
| `min_corroboration_for_delete=2` gate on hard-delete | Closed locally | `tests/completion/erasure/test_corroborated_erasure.py` + `tests/completion/rails` |
| consolidation cadence bound (≤5 steps OR 24h) | Closed locally | `tests/completion/rails/test_consolidation_cadence_bounds.py` |
| supersession-rate 0.05 pass-level rail | Closed locally | `tests/completion/rails/test_supersession_rate.py` |
| recompute memo / dirty-check substrate | Closed locally | projection recompute fingerprint/memo path; strict audit and state updates |
| ACT-R power-law demotion | Closed locally | `OperatingPolicy.actr_decay` + lifecycle coverage |
| untrusted→system_prompt pass-level rail | Closed locally | `tests/completion/rails/test_untrusted_to_system_prompt.py` |
| JWKS `enc`-key rejection | Closed locally; live IdP evidence still Tier B | Keycloak/OIDC interop coverage + ops validation surface |
| counterfactual-replay scorer attached to gate hook | Closed locally | `replay_predicted_lift` surfaced by promotion gate/runtime tests |

**Current blocker class:** Tier B operator production evidence. Do not use this
historical matrix section to reopen closed Tier-A code work; use the strict audit
and roadmap for remaining real-infrastructure captures.

---

*Update protocol: AUX-DOCS refreshes this matrix as lanes report `worker_done`. Source of truth for any disputed status is the cited file, not this synthesis.*
