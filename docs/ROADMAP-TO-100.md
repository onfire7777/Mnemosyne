# Mnemosyne — Roadmap to 100% Blueprint Parity

**Authored:** 2026-06-24 · **Current baseline:** main after the 2026-06-24 A2 calibrated-confidence slice
**Controlling status doc:** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (10 gap rows, all "Partial")
**Verdict source:** blended completion **~70%** — this doc explains *why it has been stuck there* and *exactly what flips it to 100%*.

---

## 0. Why the number has been stuck at ~70% (read this first)

The "70%" is a **blended** figure, and the blend hides the real shape of the work:

- **~85% functional / architectural scaffold** — nearly every blueprint capability is built and green-tested on the deterministic local engine.
- **6 of 6 headline SLOs are now empirically PROVEN** across the real retrieval/calibration paths: recall 0.977, nDCG 0.983, G2 lift +0.208 @7% tokens, poison-block 1.0, warm+serial P95 149.5 ms, and ECE 0.0063 vs §16 ≤0.05 from `eval/calibration/runner.py`.
- **But ~55–60% production-grade 1:1 parity.** Every one of the 10 audit gap rows is "Partial" for the *same* reason: the code contracts and local/compose-Postgres validation are done, but **operator-captured evidence from real production deployments does not yet exist**.

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
| Token efficiency / G2 lift / poison-block / recall / nDCG / warm P95 / ECE SLOs | ✅ 6/6 proven |
| Additive proof layer (real provider services, §33 eval/SLO harness, infra scripts, 59-attack poison corpus, portability tests) | ✅ built on `completion/blueprint-parity` |

---

## 2. The remaining 30% — three tiers

### TIER A — `src` reconciliation wirings (code; Codex owns `main`)

Every item is **additive, default-off / shadow-first, byte-identical when inactive** — no new deps, no rewrite. Theme: *wire machinery that already exists but is left disconnected.* Each has a paired forcing-function test on the completion branch that flips `xfail → green` the moment the wiring lands.

| # | Item (FR/§) | Current status | Fix | Flips green | Effort |
|---|---|---|---|---|---|
| A1 | **Local embedding seam** (FR-3 / G8) — **KEYSTONE** | **Done 2026-06-24.** `LocalMemoryEngine` now accepts `RetrievalAdapters`, local vector search/MMR use the configured embedding provider, local retrieval calls the configured reranker before diversification, and `cli.py:load_engine` passes the same adapter factory into `--backend local` that Postgres already used. | Complete; keep local and Postgres provider wiring aligned when adding new retrieval providers. | Engine and CLI adapter seam regressions are green. | **Done** |
| A2 | **Calibrated confidence / ECE** (FR-6) — **KEYSTONE** | **Done 2026-06-24.** Local and Postgres retrieval now compute support-aware answer confidence, abstain when retrieved evidence does not cover the query, expose confidence explain metadata, and the calibration runner scores accept-vs-abstain decision confidence. | `eval/calibration/runner.py` now reports ECE 0.0063 / Brier 0.0002, 25/25 good abstains, 0 false accepts, and `meets_target: true`; full local and clean Postgres suites pass with 837 tests, 0 failures/errors. | **ECE SLO green = 6/6 SLOs PASS** | **Done** |
| A3 | **§31 Rail 1** `max_supersession_rate 0.05` | **Done 2026-06-24.** Consolidation promotions now share a pass-scoped mutation budget and `PromotionGate.evaluate()` accepts a pre-merge rail veto, so candidate branches that would supersede more than the allowed active-fact fraction are discarded before merge. | Complete; keep manual/operator corrections outside this automated pass budget unless a separate batch API is introduced. | `tests/completion/rails/test_supersession_rate.py` is green. | **Done** |
| A4 | **§31 Rail 3** `max_prune_fraction_per_pass 0.02` | **Done 2026-06-24.** The consolidation forgetter and summary-retirement path consume the same pass-scoped prune budget and defer extra lifecycle demotions/summary retirements once the allowed fraction is exhausted. | Complete; keep `mutation_rails` pass reporting visible in future consolidation changes. | `tests/completion/rails/test_prune_fraction.py` is green. | **Done** |
| A5 | **§31 Rail 6** `sanitize_retrieved_text` | **Done 2026-06-24.** Local and Postgres returned retrieval hits now carry `metadata["retrieved_text"]` from `sanitize_retrieved_text`, preserving visible hit text while marking retrieved memory as data-only/no-write-authority. | Complete; keep retrieval metadata envelope on future hit builders. | Shared Local/Postgres sanitizer regression is green. | **Done** |
| A6 | **§31 Rail 7** `consolidation_cadence_bounds [5 steps, 24h]` | **Done 2026-06-24.** `ConsolidationWorker.run_queue_payload()` now enforces a default five-step lower bound per tenant, accepts explicit `consolidation_step` inputs for deterministic pass scheduling, and allows stale tenants through once the 24h upper bound is crossed. | Complete; keep repeated-pass tests advancing explicit steps. | `tests/completion/rails/test_consolidation_cadence_bounds.py` is green. | **Done** |
| A7 | **cf-gate** (FR-17) + `cold_loop_counterfactual_trusted` | **Done 2026-06-24.** `PromotionGate.evaluate()` now records the counterfactual `replay_predicted_lift` term and `OperatingPolicy.cold_loop_counterfactual_trusted` exists as a default-off top-level rail gate without mutating the all-true `immutable_rails` map. | Complete; future replay-fidelity automation can flip the trust flag only after the protected replay check passes. | Counterfactual gate/policy regressions are green. | **Done** |
| A8 | **Ignition switch** (OQ5) — `RegressionCase.origin`, `PromotionGate.ignition_status()` | **Done 2026-06-24.** `RegressionCase` now carries `origin` and `mode`; `PromotionGate.ignition_status()` counts active curated/genuine cases only, excludes synthetic/shadow cases from `N_active`, and `require_ignition=True` keeps otherwise-passing candidates shadow-no-merge until the suite is ready. | Complete; keep synthetic/shadow generated cases from satisfying private-suite ignition. | Ignition shadow/active gate regression is green. | **Done** |
| A9 | **ACT-R demotion** (OQ4) | **Done 2026-06-24.** `OperatingPolicy.actr_decay` defaults to `0.0` for legacy byte-stable behavior, and when enabled drives ACT-R power-law lifecycle salience, consolidation forgetter demotion, and retrieval base-level activation instead of frequency-only scoring. | Complete; keep default-off path unchanged unless deployments opt into ACT-R decay. | Lifecycle, forgetter, and activation regressions are green. | **Done** |
| A10 | **Corroborated-erasure derived-evidence cascade** (OQ6/FR-8) | **Done 2026-06-24.** Local and Postgres forget paths now split derived evidence into erased vs retained rows: legal hard-delete by `requested_by="legal"` still shreds all derived evidence, while normal/operator erasure retains derived rows with surviving source support and trims their source metadata before projection propagation. | Complete; keep retained-derived metadata trimming aligned with future summary metadata fields. | Shared Local/Postgres corroborated-derived forget regression is green. | **Done** |
| A11 | **Hosted-MCP transport** (FR-9) | Local JSON-RPC/TLS/self-test done; official StreamableHTTP/SSE not validated. | Implement/validate official transport (evidence in Tier B). | — | **M** |
| A12 | **Cached PPR column** (FR-11) | Recursive PPR works; no materialized cached-PPR column. | Add cached-PPR column + refresh path. | — | **M** |
| A13 | **Recompute memo** (FR-12) | **Done 2026-06-24.** `RuntimeJobHandlers.run_projection_recompute()` now computes a stable SHA-256 fingerprint over changed CIDs, affected evidence/projections, surviving source CIDs, pass list, branch, tenant, and enqueue mode; repeated unchanged recomputes skip duplicate consolidation enqueue side effects unless `force_recompute` is set. | Complete; keep fingerprint inputs aligned with future projection dependencies. | Runtime and shared Local/Postgres recompute memo tests are green. | **Done** |
| A14 | **`--object` argparse bug + `Preference.access_policy`** | **Done 2026-06-24.** Root and subcommand parsers now disable implicit option abbreviation while preserving explicit `branch --from`; `Preference.access_policy` now round-trips through Local/Postgres model, schema, export, and audit diff. | Complete; keep future CLI aliases explicit. | Parser and shared Local/Postgres access-policy tests are green. | **Done** |

> **Note — Rail 2 is DONE.** `min_corroboration_for_delete` is landed (`policy.py:32` default=2; enforced `engine.py:994-1017`). Cross it off any older reconciliation list.
> **Note — A7/A8/A9 are now ported to `main`.** The lane-a checkout remains useful as historical source material only; do not merge it wholesale over newer `main` changes.

### TIER B — Real-infrastructure evidence capture (ops/deployment; not feature code)

This is the **bulk of the remaining percentage** and the universal blocker on all 10 audit rows. The code paths, adapter boundaries, and evidence gates already exist; `infra/` already scripts Keycloak/Vault/c2patool. Local real-service evidence is now captured for Keycloak, Vault transit, Postgres-backed provider reporting, and C2PA trust verification; what's still missing is **operator-captured production evidence bundles**.

> **Checkpoint — local real services now pass.** On 2026-06-24, `infra/scripts/setup-all.sh` and `infra/validate/validate-all.sh` passed locally. A scoped `deployment-soak --evidence-dir` bundle plus `release-audit --allow-provider-local` passed for `idp-jwks-live-check`, `provider-check`, and `provenance-trust-check` with fingerprint `c37aa7aeba44aa82ccc0c5f4f9e130701f34c106136468de1be16c5c0105175c`. This is not production validation; it is the staging proof that the official evidence path works against real local services.

| # | Parity row | Real infra to stand up | Capture command |
|---|---|---|---|
| B1 | Production Postgres retrieval | Deployed **ParadeDB BM25** + **Apache AGE** graph + **pgvector** + reranker adapters | `retrieval-ops-check` evidence bundle |
| B2 | Tenant isolation & auth | Live **Keycloak** IdP/JWKS now passes locally; still needs production IdP/JWKS, **Vault** session-secret custody/rotation, **KMS** key provider, TLS cert lifecycle | `auth-ops-check`, `tls-lifecycle-ops-check` |
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

1. **Run the production real-infra evidence pass (Tier B).** The local `infra/` stack now passes and scoped release evidence is captured. Next bring up production-equivalent Postgres+ParadeDB+AGE+pgvector plus real embedding/reranker/model endpoints, then run the `*-ops-check` / `provider-check` / `release-audit --require-production-validated` captures. This is what flips the 10 parity rows Partial→Done.
2. **Close any strict-audit leftovers found during the evidence pass.** The mandatory Tier A source wirings A1/A2/A3/A4/A5/A6/A7/A8/A9/A10/A13/A14 are now closed.
3. **Review optional A11/A12 only if the v1.0 bar requires them.** Keep them behind the real-infra evidence pass unless strict audit rows still demand code work.
4. **Re-run the parity audit and sign off v1.0.** A11/A12/B8 + Tier C are optional polish beyond the v1.0 bar.

---

## 4. Completion math

| Milestone | Blended % | What changed |
|---|---|---|
| **Now** (after Tier A + local Tier B smoke) | **~82%** | Mandatory source wirings are closed, 6/6 SLOs are proven, and local real-service evidence now passes through `deployment-soak`/scoped `release-audit`; production parity still remains blocked by missing operator-captured production evidence |
| After **Tier A** (code wirings) | **~82%** | Reached for mandatory source wirings; optional A11/A12 remain review-only unless v1.0 parity audit demands them |
| After **Tier B** (real-infra evidence) | **~97%** | 10 audit rows flip Partial→Done |
| After **Tier C** + sign-off | **100%** | multimodal/LoRA (optional) + v1.0 attestation |

---

## 5. Hazards / working rules (don't lose progress)

- **Live edit hazard:** `main` is edited by an autonomous Codex/GSD session. Never `git add -A`; stage specific files only; push fast-forward only; verify it is not mid-edit before committing.
- **Don't build more gates/tests by default** — the machine-checkable evidence layer (`PRODUCTION_RELEASE_REQUIRED_COMMANDS`, `RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS`) now rejects placeholder/hollow release evidence; further gate work needs a concrete audit finding.
- **Lane-a checkout is historical source material now** — A7/A8/A9 have been selectively ported to `main`; do not wholesale-merge `/Users/admin/Projects/Mnemosyne-lane-a` over newer commits.
- The completion branch's additive scope is **essentially complete** — it never edits `src/`; treat it as the proof/forcing-function layer.
