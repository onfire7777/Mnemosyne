# Mnemosyne — Roadmap to 100% Blueprint Parity

**Authored:** 2026-06-24 · **Current baseline:** main after the 2026-06-24 A14 parser/model slice
**Controlling status doc:** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (10 gap rows, all "Partial")
**Verdict source:** blended completion **~70%** — this doc explains *why it has been stuck there* and *exactly what flips it to 100%*.

---

## 0. Why the number has been stuck at ~70% (read this first)

The "70%" is a **blended** figure, and the blend hides the real shape of the work:

- **~85% functional / architectural scaffold** — nearly every blueprint capability is built and green-tested on the deterministic local engine.
- **5 of 6 headline SLOs are now empirically PROVEN** on the real retrieval path (real BGE embeddings + cross-encoder + Postgres, v2 hard corpus, adversarially reproduced): recall 0.977, nDCG 0.983, G2 lift +0.208 @7% tokens, poison-block 1.0, warm+serial P95 149.5 ms. **Only ECE (0.279 vs ≤0.05) is still red.**
- **But ~55–60% production-grade 1:1 parity.** Every one of the 10 audit gap rows is "Partial" for the *same* reason: the code contracts and local/compose-Postgres validation are done, but **operator-captured evidence from real production deployments does not yet exist**, and **~8 `src` wirings remain disconnected**.

So the number has not moved because the remaining 30% is **not "write more code in the same style."** It is two distinct kinds of work that coding-as-usual does not produce:

1. **~8 small `src` reconciliation wirings** (the disconnected machinery — Tier A below). These are owned by the autonomous **Codex** session on `main`; several may already be built additively/default-off in the local `reconcile/lane-a-cold` checkout.
2. **Standing up real infrastructure and capturing evidence** (Tier B below) — real IdP, secret manager, KMS, ParadeDB/AGE, hosted embedding/reranker/trainer endpoints, C2PA trust roots. This is **ops/deployment work**, not feature code. The `*-ops-check` / `provider-check` / `release-audit` gates already exist and *demand* this evidence; nothing can fake it (the gates were deliberately hardened through `7f795df` to reject placeholder and hollow evidence).

**The trap to avoid (already observed):** Codex has been spending recent cycles adding more `test(...)` coverage and more release-audit *gates*. After the placeholder/hollow evidence hardening through `7f795df`, real progress should pivot to Tier A wirings and Tier B evidence unless a concrete audit finding exposes a missing fail-closed gate.

---

## 1. What is actually DONE (so "70%" is legible)

| Area | State |
|---|---|
| Foundations (schema, CAS object store, branches, time-travel) | ✅ solid |
| Belief core (assertions, supersession, corrections, confidence) | ✅ strongest phase |
| Retrieval quality on Postgres (FTS + pgvector + recursive PPR) | ✅ proven (recall .977 / nDCG .983) |
| Consolidation (RAPTOR hierarchy, gist materialize/retire/refresh, prioritized replay) | ✅ built |
| Privacy/erasure contracts, audit logging, trust-tier model | ✅ contract-level |
| MCP transport (JSON-RPC + TLS + SDK HTTP + self-test) | ✅ local |
| OIDC/JWKS verifier (real RSA-PKCS1v15 + EC-ECDSA, fail-closed, rotation) | ✅ real crypto |
| §31 Rails 2, 4, 5 | ✅ enforced in `src` |
| Token efficiency / G2 lift / poison-block / recall / nDCG / warm P95 SLOs | ✅ 5/6 proven |
| Additive proof layer (real provider services, §33 eval/SLO harness, infra scripts, 59-attack poison corpus, portability tests) | ✅ built on `completion/blueprint-parity` |

---

## 2. The remaining 30% — three tiers

### TIER A — `src` reconciliation wirings (code; Codex owns `main`)

Every item is **additive, default-off / shadow-first, byte-identical when inactive** — no new deps, no rewrite. Theme: *wire machinery that already exists but is left disconnected.* Each has a paired forcing-function test on the completion branch that flips `xfail → green` the moment the wiring lands.

| # | Item (FR/§) | Current status | Fix | Flips green | Effort |
|---|---|---|---|---|---|
| A1 | **Local embedding seam** (FR-3 / G8) — **KEYSTONE** | `cli.py:455` `LocalMemoryEngine(store_path=…)` has **no `adapters=`** (only Postgres branch `cli.py:452` does); `engine.py:233 __init__` has no embedding hook; retrieval still calls `hashing_embedding` (`engine.py:685, 1380, 1403, 1408`). `--backend local` silently ignores real embedding/reranker providers. | Add embedding/reranker adapter seam to `LocalMemoryEngine`; wire through `cli.py:load_engine` local branch so local↔prod are one architecture. | portability suite; real dense retrieval on local | **M** |
| A2 | **Calibrated confidence / ECE** (FR-6) — **KEYSTONE (the one red SLO)** | `engine.py:1454` returns constant `0.7` and **never abstains** → ECE 0.279 vs §16 ≤0.05. | Varied per-memory-type conformal confidence + working abstention; run `calibration-tune` on the completion-branch calibration set. | **ECE SLO red→green = 6/6 SLOs PASS** | **M** |
| A3 | **§31 Rail 1** `max_supersession_rate 0.05` | **Done 2026-06-24.** Consolidation promotions now share a pass-scoped mutation budget and `PromotionGate.evaluate()` accepts a pre-merge rail veto, so candidate branches that would supersede more than the allowed active-fact fraction are discarded before merge. | Complete; keep manual/operator corrections outside this automated pass budget unless a separate batch API is introduced. | `tests/completion/rails/test_supersession_rate.py` is green. | **Done** |
| A4 | **§31 Rail 3** `max_prune_fraction_per_pass 0.02` | **Done 2026-06-24.** The consolidation forgetter and summary-retirement path consume the same pass-scoped prune budget and defer extra lifecycle demotions/summary retirements once the allowed fraction is exhausted. | Complete; keep `mutation_rails` pass reporting visible in future consolidation changes. | `tests/completion/rails/test_prune_fraction.py` is green. | **Done** |
| A5 | **§31 Rail 6** `sanitize_retrieved_text` | **Done 2026-06-24.** Local and Postgres returned retrieval hits now carry `metadata["retrieved_text"]` from `sanitize_retrieved_text`, preserving visible hit text while marking retrieved memory as data-only/no-write-authority. | Complete; keep retrieval metadata envelope on future hit builders. | Shared Local/Postgres sanitizer regression is green. | **Done** |
| A6 | **§31 Rail 7** `consolidation_cadence_bounds [5 steps, 24h]` | **Done 2026-06-24.** `ConsolidationWorker.run_queue_payload()` now enforces a default five-step lower bound per tenant, accepts explicit `consolidation_step` inputs for deterministic pass scheduling, and allows stale tenants through once the 24h upper bound is crossed. | Complete; keep repeated-pass tests advancing explicit steps. | `tests/completion/rails/test_consolidation_cadence_bounds.py` is green. | **Done** |
| A7 | **cf-gate** (FR-17) + `cold_loop_counterfactual_trusted` | `gate.py PromotionGate.evaluate` is pure regression margin; no counterfactual `replay_predicted_lift` term; rail absent. | Add cf-term + new immutable rail (default off; flips on only when `replay-fidelity-check` passes). **Already built additively on `reconcile/lane-a-cold` — merge it.** | replay-fidelity suite | **S–M** |
| A8 | **Ignition switch** (OQ5) — `RegressionCase.origin`, `PromotionGate.ignition_status()` | `ignition_status` absent (0 hits); `RegressionCase.origin` not present. | Shadow-no-merge until ignition. **Already built additively on `reconcile/lane-a-cold` — merge it.** | ignition/v2-selftest | **S** |
| A9 | **ACT-R demotion** (OQ4) | `lifecycle.py:72` still `exp(-age_days/45)` (not power-law `(1+age)^-d`); retrieval base_level frequency-only. | Add `policy.actr_decay` (default 0.0 = off) driving decay + base_level. **Already built additively on `reconcile/lane-a-cold` — merge it.** | demotion tests | **S** |
| A10 | **Corroborated-erasure derived-evidence cascade** (OQ6/FR-8) | Projections split is done (`engine.py:931-976`), but the derived-evidence cascade (`engine.py:909-914`) still **blanket-zeroes every transitively-derived row**. | Extend the corroboration-aware retain/retract split to the derived-evidence cascade. | erasure xfail | **M** |
| A11 | **Hosted-MCP transport** (FR-9) | Local JSON-RPC/TLS/self-test done; official StreamableHTTP/SSE not validated. | Implement/validate official transport (evidence in Tier B). | — | **M** |
| A12 | **Cached PPR column** (FR-11) | Recursive PPR works; no materialized cached-PPR column. | Add cached-PPR column + refresh path. | — | **M** |
| A13 | **Recompute memo** (FR-12) | `jobs.py run_projection_recompute` is dirty-driven but has no content-fingerprint memo to skip unchanged passes. | Add fingerprint memo. | — | **S** |
| A14 | **`--object` argparse bug + `Preference.access_policy`** | **Done 2026-06-24.** Root and subcommand parsers now disable implicit option abbreviation while preserving explicit `branch --from`; `Preference.access_policy` now round-trips through Local/Postgres model, schema, export, and audit diff. | Complete; keep future CLI aliases explicit. | Parser and shared Local/Postgres access-policy tests are green. | **Done** |

> **Note — Rail 2 is DONE.** `min_corroboration_for_delete` is landed (`policy.py:32` default=2; enforced `engine.py:994-1017`). Cross it off any older reconciliation list.
> **Note — A7/A8/A9 are pre-built.** They exist additive/default-off on the local-only branch `reconcile/lane-a-cold` (commit `9820d0b`); the hot-file legs are specified in `~/Projects/Mnemosyne-lane-a/docs/LANE-A-HANDOFF.md`. Merging that branch + landing the handoff legs closes them with proven zero-conflict.

### TIER B — Real-infrastructure evidence capture (ops/deployment; not feature code)

This is the **bulk of the remaining percentage** and the universal blocker on all 10 audit rows. The code paths, adapter boundaries, and evidence gates already exist; `infra/` already scripts Keycloak/Vault/c2patool. What's missing is **running real services and capturing operator evidence bundles**.

| # | Parity row | Real infra to stand up | Capture command |
|---|---|---|---|
| B1 | Production Postgres retrieval | Deployed **ParadeDB BM25** + **Apache AGE** graph + **pgvector** + reranker adapters | `retrieval-ops-check` evidence bundle |
| B2 | Tenant isolation & auth | Live **Keycloak** IdP/JWKS (validate currently 1/3 checks fail — fix in `infra/`), **Vault** session-secret custody/rotation, **KMS** key provider, TLS cert lifecycle | `auth-ops-check`, `tls-lifecycle-ops-check` |
| B3 | CLI/MCP runtime | Official **StreamableHTTP/SSE** transport + stateless soak on a real deployed endpoint | hosted MCP soak evidence |
| B4 | Embedding/reranker providers | Real **embedding + cross-encoder + image/audio embedding** endpoints behind the HTTP adapter boundary | `provider-check` |
| B5 | Entity resolution | Real deployed **entity-resolver** behind the command boundary | `provider-check` |
| B6 | Consolidation model providers | Real **extractor + summarizer** model deployments with prompt-boundary enforcement | `provider-check` |
| B7 | Provenance (FR-19) | Real **C2PA trust-root** validation (c2patool PASS locally; needs deployed trust roots) | `privacy/provenance` evidence |
| B8 | Parametric (FR-21) | Isolated **LoRA / test-time-training** deployment + protected-suite + production rollback (GPU) | trainer evidence |
| B9 | Privacy ops | Production **residency-policy** + **legal-erasure / operator-delete** (KMS-backed) operations | `privacy-ops-check` |
| B10 | Worker / observability | Real **worker supervision/deployment** + deployment observability; headline SLOs demonstrated on **real production** (not the completion harness) | `worker-run` + `release-audit` |

### TIER C — Scope-deferred (blueprint non-goals) + final sign-off

- **FR-20 multimodal** (N5, post-v1) — Codex is now building it. Optional for v1.0.
- **FR-21 real LoRA** (N2, optional, GPU) — overlaps B8.
- **Final 1:1 sign-off:** re-run `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, flip the 10 rows Partial→Done, supersede with a v1.0 release attestation.

---

## 3. The fastest honest path (sequenced)

1. **Inspect and selectively port the pre-built additive items** (A7, A8, A9 from `/Users/admin/Projects/Mnemosyne-lane-a` on `reconcile/lane-a-cold`) — keep them default-off and verify conflicts before merging because that checkout is currently dirty.
2. **Codex lands the two keystones in order: A1 (embedding seam) → A2 (ECE).** This is the chain to the single red SLO → **6/6 SLOs PASS**.
3. **Codex lands the remaining small rails + bugs:** A10, A13 (A3/A4/A5/A6/A14 are now closed).
4. **One real-infra evidence pass (Tier B):** bring up `infra/` (fix the Keycloak 1/3 failure first) plus a Postgres+ParadeDB+AGE+pgvector instance and one real embedding/reranker endpoint; run the `*-ops-check` / `provider-check` / `release-audit` captures. This flips the 10 parity rows Partial→Done.
5. **Re-run the parity audit and sign off v1.0.** A11/A12/B8 + Tier C are optional polish beyond the v1.0 bar.

---

## 4. Completion math

| Milestone | Blended % | What changed |
|---|---|---|
| **Now** (after A14 + A5 + A3/A4 + A6) | **~74%** | ~85% scaffold; 5/6 SLOs proven; §31 live mutation-rate and cadence rails now enforced; ~55–60% production parity remains blocked by no real-infra evidence and remaining `src` wirings |
| After **Tier A** (code wirings) | **~82%** | 6/6 SLOs; all 7 §31 rails enforced; all FR `src` gaps closed; local↔prod architecture unified |
| After **Tier B** (real-infra evidence) | **~97%** | 10 audit rows flip Partial→Done |
| After **Tier C** + sign-off | **100%** | multimodal/LoRA (optional) + v1.0 attestation |

---

## 5. Hazards / working rules (don't lose progress)

- **Live edit hazard:** `main` is edited by an autonomous Codex/GSD session. Never `git add -A`; stage specific files only; push fast-forward only; verify it is not mid-edit before committing.
- **Don't build more gates/tests by default** — the machine-checkable evidence layer (`PRODUCTION_RELEASE_REQUIRED_COMMANDS`, `RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS`) now rejects placeholder/hollow release evidence; further gate work needs a concrete audit finding.
- **Tier A items A7/A8/A9 may already exist** in `/Users/admin/Projects/Mnemosyne-lane-a` on `reconcile/lane-a-cold`; inspect and port, don't rebuild blindly.
- The completion branch's additive scope is **essentially complete** — it never edits `src/`; treat it as the proof/forcing-function layer.
