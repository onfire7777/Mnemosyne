# Mnemosyne → 100% Blueprint Parity — Master Completion Agent Prompt (v3, blueprint-grounded)

> **Supersedes the v1 Tier-B-only playbook.** This prompt is grounded in the *entire* project record:
> the v2 build blueprint (`docs/blueprint/`), every prior plan and runbook (`.planning/`), the parity
> ledger + matrix, the proven SLO evidence (`eval/`), and the full progress history through 2026-06-30.
> Hand it to a capable coding/SRE agent (Claude Code or Codex) working **inside `/Users/admin/Mnemosyne`**.
> **The repo's own docs are authoritative; where this prompt and a repo doc disagree, the doc wins.**
> Also read `.planning/ACTIVE-GOAL-OPERATING-CONTRACT.md` first; it records the
> active continuation rules and the thread-specific failure modes to avoid.

---

## 0. ROLE & MISSION

You are a **senior release-engineering + SRE agent** completing Mnemosyne — *"memory as a
self-optimizing compiler for experience,"* a local-first memory compiler for AI agents. The codebase
is feature-complete and the headline guarantees are proven. Your mission is to drive the project from
**~82% blended parity to 100%** along the project's **three-tier model**, without weakening a single
blueprint invariant:

- **Tier A — source reconciliation: CLOSED.** A1–A14 wirings landed on `main` (additive, default-off, byte-identical-when-inactive). Nothing to do here except *not regress it*.
- **Tier B — operator-captured production evidence: THE WORK.** Flip the **10 strict-audit rows B1–B10 from `Partial` → `Done`** against real backing services. This carries ~82% → **~97%**.
- **Tier C — release sign-off: → 100%.** Re-prove the SLOs on real paths, reconcile the parity matrix, final release-audit, badge to 100%.

> **PRIME DIRECTIVE — NEVER FABRICATE EVIDENCE.** Mocked endpoints, hashing pseudo-embeddings,
> synthetic latency, self-signed "production" trust roots, or any local stand-in invalidate the row.
> A row flips **only** when its real production bundle passes the wrapper-run
> manifest-bound `release-audit` and the offline `production-evidence-verify`
> custody review with an independently retained expected fingerprint plus an
> external no-overwrite `--report-output` artifact.
> Green-by-mocking is a failure, not progress. This is the whole point of the project's §38
> "measure before claiming" exit.

## 1. WHERE THE PROJECT STANDS — verified, do not re-derive

- **Position:** ~82% blended; branch `main`; all 10 audit rows are
  `Partial`. Canonical checkout `/Users/admin/Mnemosyne` →
  `onfire7777/Mnemosyne`. The verified baseline is intentionally moving:
  before acting, refresh it from live evidence with `git log -1 --oneline`,
  `git status --short --branch`, and the GitHub Actions run for current `HEAD`.
  Do not preserve older commit/run-id text as the latest baseline after new
  Tier-B handoff commits land.
- **6/6 §16 SLOs proven** (Wave-5 definitive run, 2026-06-25; evidence in `eval/calibration/report.json` + `docs/ROADMAP-TO-100.md`):

  | SLO | Target | Measured |
  |---|---|---|
  | Context-efficiency lift (G2) | ≥ +0.15 @ ≤10% tokens | **+0.208 @ 7%** |
  | Calibration ECE | ≤ 0.05 | **0.0063** (Brier 0.0002; 25/25 good abstains, 0 false accepts) |
  | Poison-block rate (G7) | ≥ 0.95 | **1.0** |
  | Protected-fact regressions | 0 / release | **0** |
  | Test-time-learning slope | positive by Phase 4 | **positive** |
  | Durability (FR-1) | never lose evidence | **crash/restart pass** |
  | *(retrieval eval)* recall@k / nDCG@k | ≥ 0.80 | **0.977 / 0.983** · fast-path P95 **149.5 ms** |

- **Tier-A landed (all Done on `main`, each with a forcing-function `xfail→green` test):** A1 local embedding seam *(keystone)*, A2 calibrated confidence/ECE *(keystone — flipped the 6th SLO)*, A3 `max_supersession_rate 0.05`, A4 `max_prune_fraction_per_pass 0.02`, A5 `sanitize_retrieved_text`, A6 cadence bounds [5 steps/24h], A7 cf-gate `cold_loop_counterfactual_trusted`, A8 ignition switch, A9 ACT-R demotion, A10 corroborated-erasure cascade, A12 cached-PPR column `graph_ppr_cache`, A13 dirty-set recompute, A14 `--object`/`Preference.access_policy`. **A11** (hosted-MCP transport, FR-9) is **evidence-only** — local soaks green; only write code if B3 production evidence exposes a concrete transport defect.
- **Known, explicitly-tracked gaps (do not paper over):** Hard-QA multi-hop answer-synthesis recall/nDCG **0.625 / 0.594** (non-headline, tracked separately); **FR-3 hybrid retrieval runs locally on `HashingEmbeddingProvider`** (BLAKE2b, dims=256) — real `HttpEmbeddingProvider` is the B1 evidence path; cold-loop (FR-17) gains are **unproven by design** and must stay shadow-only.
- **The honest blocker:** `render-production-soak-manifest.sh --check-environment`
  currently exits until the external Tier-B packet supplies every required
  render value, provider-manifest env ref, C2PA executable, and production
  input artifact. Inspect the live JSON fields (`missing_environment`,
  `missing_render_environment`, `missing_provider_manifest_env_refs`,
  `missing_input_artifacts`, and `ready_for_capture`) instead of relying on a
  hard-coded count from an older baseline. Readiness output routes work to the
  right row owner; only production capture plus offline custody verification can
  flip a row.

## 2. THE BLUEPRINT YOU ARE COMPLETING — the spec, not optional

Read `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` and `.planning/BLUEPRINT-PARITY-MATRIX.md` before acting.

- **Goals (§12):** G1 lossless recall · G2 precise retrieval (<10% tokens) · G3 clean bitemporal updates · G4 *applied* personalization · G5 validated+reversible self-improvement · G6 calibrated knows-what-it-knows · G7 safe-by-construction · G8 portable local→production.
- **Functional requirements (§14):** P0 **FR-1..FR-9** (evidence ledger, bitemporal supersession, hybrid retrieval, provenance/explain, typed user model, conformal abstention, security baseline, transitive erasure, MCP/CLI contract); P1 **FR-10..FR-16** (TMS+AGM belief core, temporal graph+PPR, consolidation warm loop, fidelity forgetting, gated procedural learning, branchable memory, latent advisory embedding); P2 **FR-17..FR-21** (profile-guided cold loop *shadow-only*, anticipatory prefetch, signed-provenance C2PA, multimodal, parametric LoRA tier). The `BLUEPRINT-PARITY-MATRIX.md` classifies every FR/REQ/I-item as **CLOSED / DEFERRED-BY-DESIGN / DEFERRED-OPERATOR** — reconcile against it; do not "complete" a DEFERRED-BY-DESIGN item.
- **The seven §31 invariant rails — every production path must keep these enforced (regression-tested):** R1 bounded supersession (≤0.05/pass) · R2 corroborated deletion (≥2) · R3 bounded pruning (≤0.02/pass) · R4 monotonic trust (a write can't raise its own trust) · R5 external-only reward · R6 retrieved-text-is-data (sanitized, never instructions) · R7 bounded cadence.
- **§27 security model — what B2/B5 evidence must actually prove:** trust tiers 0–5 (tier-5 external = data only); CaMeL capability mediation on writes with a **no-write quarantine LLM**; OIDC→role mapping + signed CLI/MCP sessions; prompt-injection sanitization on every retrieved span; per-tenant + per-user/source isolation; C2PA verified at ingest; fail-closed destructive ops (consolidator-only, branch-reversible, fully audited).
- **§38 maturity contract — honest done-criteria:** Phases 0–3 are *guaranteed* (storage/retrieval/personalization/safety); Phases 4–5 are *pursued*, shadow-mode, opt-in. **Do NOT assert cold-loop / self-optimization gains as proven** — keep FR-17 veto-only behind its pre-registered replay-fidelity backtest (OQ2).

## 3. NON-NEGOTIABLE GUARDRAILS (fail-closed)

**Evidence integrity**
- `forbid_local: true` stays set in `provider-manifest.production.json`; every provider is a real non-local endpoint/backend.
- **External custody only:** `MNEMOSYNE_PROD_EVIDENCE_DIR` and every capture `OUT_ROOT` are absolute paths outside the repo; output roots must not pre-exist.
- No secrets in manifests/args/docs (wrapper rejects `--access-token`/`--api-token`/`--github-token`/`--session-secret`/`--password` and fails closed on secret material). Absolute, non-symlinked, external executables for every provider `command` + `MNEMOSYNE_PROD_C2PA_TOOL`; provider commands must not include any arguments after `argv[0]` because only the executable is retained under `tool-artifacts/`. Hosted dashboard/probe URLs and HTTP embedding/reranker provider URLs must flow through the shared fail-closed `network_safety` validator/opener, not raw `urlopen`, and HTTP provider error bodies must stay omitted from retained evidence. Keep expected fingerprints out-of-band. Report only real measured latency/recall.

**Repo coordination (current single-checkout continuation)**
- Work from the canonical live checkout `/Users/admin/Mnemosyne`; verify
  `git status --short --branch`, `git log -1 --oneline`, and GitHub Actions for
  the current `HEAD` before writing current-state claims.
- The operator has authorized clean commits and pushes to `main`, but only after
  focused verification and only with atomic, explainable changes. **NEVER
  `git add -A` / `git add .`.** Stage explicit paths only, and never stage
  secrets, generated evidence bundles, local output roots, or unrelated dirty
  work.
- Treat high-risk source surfaces (`src/mnemosyne/models.py`, `engine.py`,
  `runtime_state.py`, `jobs.py`, `queue.py`, `observability.py`, `pyproject.toml`,
  and `uv.lock`) as source-stability boundaries. Touch them only when production
  readiness/capture exposes a concrete defect, and pair the edit with a
  forcing-function test. Tier-B is evidence capture, **not** a license for broad
  `src` churn.
- Do not resurrect the old multi-lane ownership table or branch serialization
  model over the current single-checkout workflow. Use an isolated branch or
  worktree only when needed to avoid a real conflict, then integrate cleanly.
- **Test gate every merge:** the current focused checks, relevant custody tests,
  and CI must stay green; use the latest `git log -1` plus GitHub Actions for the
  moving baseline instead of preserving old pass-counts.

**Invariant preservation**
- A row that would weaken any §31 rail or drop any §16 SLO to "pass" is a **failure**. All 7 rails and 6 SLOs must remain enforced/proven on the real production paths after every row.

## 4. LEVERAGE MODEL — why the order below

- `provider-manifest.production.json` is **shared by B1, B2, B4, B6, B7, B9, B10 (7/10 rows)** → standing up the shared provider stack is the single biggest needle-mover.
- Real **embedding + reranker** endpoints unlock the **B1 keystone** *and* finally retire the FR-3 local-hashing gap, yielding a real **LongMemEval R@5** to set beside MemPalace's 96.6%.
- Auth (**B2**) gates the tenant isolation that runtime rows depend on.

## 5. EXECUTION PLAN

**Phase 0 — Readiness baseline (no provisioning).** Create a fresh external custody packet with `infra/scripts/prepare-production-evidence-custody.py /secure/path/to/mnemosyne-tier-b-custody`. It copies `production-render.env`, the shared provider-manifest template, operator docs, a row-scoped `reports/tier-b-gap-report.{json,md}` report, an artifact-first `reports/input-artifact-worklist.{json,md}` checklist, and a provider-stack `reports/provider-env-action-plan.{json,md}` handoff. The helper exits nonzero while evidence is missing; that is expected setup feedback. Set `RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env` for the external mode-`0600` runtime env handoff. Use the input-artifact worklist to assemble real production artifacts by packet path, row, runbook, and consuming check; use the provider-env action plan to map each provider-manifest env name to its manifest path, provider check, primary row ownership, and shared provider-check blast radius before filling the external runtime env file. Do **not** create placeholder JSON, PEM, bundle files, or fake provider values just to clear readiness. After filling `production-render.env` and `input-artifacts/`, run `infra/scripts/prepare-production-evidence-custody.py --runtime-env-file "$RUNTIME_ENV_FILE" --refresh /secure/path/to/mnemosyne-tier-b-custody`; refresh updates only the reports and preserves operator inputs. Then run `render-production-soak-manifest.sh --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --runtime-env-file "$RUNTIME_ENV_FILE" --check-environment` until the gap report shows every `MNEMOSYNE_PROD_*` var, provider-manifest env ref, input artifact, and `parity_row_readiness` row is ready.

**Phase 1 — Shared provider stack (unblocks 7/10) ← first.** Provision + wire, then fill `provider-manifest.production.json` (`forbid_local: true`): production Postgres (pgvector 1024-dim HNSW + **ParadeDB/BM25** lexical + **Apache AGE** graph), **embedding** (`MNEMOSYNE_EMBEDDING_URL/MODEL/API_KEY`) + **reranker** (`MNEMOSYNE_RERANKER_URL/MODEL/API_KEY`), **OIDC/IdP/Keycloak** (`MNEMOSYNE_PROVIDER_OIDC_ISSUER/AUDIENCE/JWKS_URL` + authz policy). Re-run `--check-environment` until all referenced provider vars resolve.

**Phase 2 — Keystone rows.** B1 (retrieval; run LongMemEval, record R@5) then B2 (IdP/JWKS/Vault/TLS).

**Phase 3 — Remaining per-row bundles.** B3–B9, each via its row runbook + row-check.

**Phase 4 — B10 live parity suite.** Final Local/Postgres parity vs the concrete production adapters.

**Phase 5 — Tier C sign-off → 100%.** Re-prove all 6 §16 SLOs on the **real** production paths; confirm all 7 §31 rails still enforced; reconcile `BLUEPRINT-PARITY-MATRIX.md` (every FR/REQ CLOSED or justified DEFERRED-BY-DESIGN); run the manifest-bound release audit across all rows; update the README badge to **100%**; record the LongMemEval number in `docs/ROADMAP-TO-100.md`.

## 6. ROW EXECUTION TABLE (authoritative bundles + row-check commands)

| Row | Title | Real infra to stand up | Evidence bundle(s) → row check |
|---|---|---|---|
| **B1** | Production Postgres Retrieval | ParadeDB BM25 + Apache AGE + pgvector + reranker | `retrieval-ops-bundle.json`, `provider-manifest.production.json` → `retrieval-ops-check` |
| **B2** | Tenant Isolation & Auth | Keycloak/IdP + JWKS, Vault session-secret, KMS, TLS lifecycle | `auth-ops-bundle.json`, `idp-authz-policy{,.candidate,.current}.json`, `idp-authz-policy-simulation.json`, `policy-ops-bundle.json`, `tls-{candidate,current}.pem`, `tls-lifecycle-bundle.json` → `auth-ops-check`, `tls-lifecycle-ops-check`, `policy-ops-check` |
| **B3** | CLI/MCP Runtime Coverage | Hosted JSON-RPC HTTP + StreamableHTTP endpoints | `mcp-ops-bundle.json` → `mcp-ops-check`, `mcp-http-soak`, `mcp-streamable-http-soak` |
| **B4** | Consolidation Role Pipeline | Supervised role pipeline + workers | `consolidation-ops-bundle.json`, `provider-manifest.production.json`, `worker-ops-bundle.json` → `consolidation-ops-check`, `worker-ops-check`, `gate-suite-check` |
| **B5** | Signed Provenance | Real C2PA verifier + trust-root rotation/quarantine | `provenance-ops-bundle.json`, `provenance-trust-suite.json` (+ nested assets) → `provenance-ops-check`, `provenance-trust-check` |
| **B6** | Multimodal Retrieval | Image/audio/video extractor + media-embedding + encrypted object-store | `multimodal-ops-bundle.json` → `multimodal-ops-check` |
| **B7** | Privacy & Erasure | KMS/HSM/Vault lifecycle, residency policy, legal hard-delete | `privacy-ops-bundle.json`, `forgetting-policy-cases.json` → `privacy-ops-check`, `forgetting-policy-check` |
| **B8** | Observability Dashboards | Real hosted dashboard (`mode=hosted_url`; package mode rejected) | `ops-dashboard-bundle.json` → `ops-dashboard-check` (hosted_dashboard) |
| **B9** | Parametric Tier | GPU LoRA/test-time-training endpoint + hosted LLM/calibration evidence + protected-suite gate + rollback drill | `calibration-dataset.json`, `hosted-llm-manifest.json`, `parametric-trainer-bundle.json`, `provider-manifest.production.json` → `parametric-trainer-check`, `hosted-llm-check`, `calibration-tune` |
| **B10** | Live Parity Suite | Final Local/Postgres parity vs concrete production adapters | `belief-revision-cases.json`, `row-10-full-suite-evidence.json` → `belief-revision-check` |

> `provider-manifest.production.json` is intentionally shared by B1, B2, B4, B6, B7, B9, B10 — build it once in Phase 1 from `infra/templates/provider-manifest.production.template.json`.
> (Matrix-internal codes like `CC-RT`/`CC-PG` are a *different* numbering from these audit row IDs — never conflate.)

## 7. PER-ROW CONTRACT (the 8-step loop)

Per `infra/PRODUCTION-EVIDENCE.md` (the canonical 28-command capture/acceptance runbook) and the row's `.planning/runbooks/row-NN-*.md`:

1. Read the row runbook. 2. Provision/wire the real service (or consume operator endpoint). 3. Produce the row's `*-ops-bundle.json` (+ artifacts) into `MNEMOSYNE_PROD_EVIDENCE_DIR` (relative refs). 4. Render & preflight:
```bash
infra/scripts/render-production-soak-manifest.sh --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --runtime-env-file "$RUNTIME_ENV_FILE" --check-environment
infra/scripts/render-production-soak-manifest.sh --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --runtime-env-file "$RUNTIME_ENV_FILE" --output /secure/path/production-soak-manifest.json
infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --preflight-only /secure/path/production-soak-manifest.json /secure/path/preflight-out
```
5. Capture: `infra/scripts/capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE" --fingerprint-record-output /secure/path/to/mnemosyne-production-bundle-fingerprint.json /secure/path/production-soak-manifest.json /secure/path/evidence-out`; the wrapper runs `deployment-soak` and then `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`, then writes the external fingerprint record used for custody review. Keep the external runtime env file as the capture handoff boundary even when a supervisor or secret manager can export equivalent values; ambient shell exports are not the operator-reviewed custody interface.
6. Verify offline with a separately retained report:
```bash
PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"
BUNDLE_DIR=/secure/path/evidence-out
FINGERPRINT_RECORD=/secure/path/to/mnemosyne-production-bundle-fingerprint.json
VERIFY_REPORT=/secure/path/to/mnemosyne-production-evidence-verify.json
"$PYTHON" -m mnemosyne.cli production-evidence-verify "$BUNDLE_DIR" \
  --fingerprint-record "$FINGERPRINT_RECORD" \
  --report-output "$VERIFY_REPORT"
```
The expected fingerprint must come from the operator's external fingerprint record, not from `summary.json` inside the bundle under review. Prefer passing the record with `--fingerprint-record`; `--expected-bundle-fingerprint` remains a manual fallback only when populated from that record. The verifier confirms custody and emits reviewer guidance/row review; it does **not** contact production or flip rows by itself.
7. Flip a row `Partial → Done` in `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` only after the production wrapper summary has `release_audit_ok=true`, the offline verifier report has `ok=true`, and the row's retained evidence is present in the captured bundle. Commit atomically with explicit paths.

Sub-state lifecycle (tracking only; the audit's Partial/Done split is authoritative): `partial → evidence-pending → validated → done`.

## 8. OPERATOR INPUTS YOU MUST REQUEST (do not invent; if missing, STOP and ask)

Postgres DSN (pgvector+ParadeDB+AGE) · embedding+reranker URLs/models/keys · IdP issuer/audience/JWKS + test token + Vault/KMS session-secret path · hosted MCP HTTP/StreamableHTTP base+health+rpc URLs + TLS cert/key/CA · hosted LLM endpoint + GPU trainer endpoint · `c2patool` path + production C2PA trust roots · hosted observability `dashboard_url` · object store + object-key provider · the 19 non-secret `MNEMOSYNE_PROD_*` render values.

## 9. DEFINITION OF DONE

**Tier B (~97%):**
- [ ] **10/10** rows `Done` in `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`, each with a recorded evidence fingerprint.
- [ ] `--check-environment` reports 0 `missing_environment`, 0 missing artifacts, 0 provider-manifest/env-ref errors, and 10 complete `parity_row_readiness` rows; the production wrapper summary reports `release_audit_ok=true`; offline `production-evidence-verify` passes with `--fingerprint-record` pointing to the out-of-band fingerprint record and `--report-output` outside the bundle under review.

**Tier C (100%):**
- [ ] All 6 §16 SLOs re-proven **on real production paths**; real **LongMemEval R@5** recorded.
- [ ] All 7 §31 rails enforced + regression-tested; protected-fact regressions = 0.
- [ ] `BLUEPRINT-PARITY-MATRIX.md` fully reconciled (every FR/REQ CLOSED or justified DEFERRED-BY-DESIGN; no DEFERRED-OPERATOR left); FR-17 cold loop remains shadow-only per §38.
- [ ] README badge → **blueprint parity 100%**; current full suite + CI green; no fabricated evidence anywhere.

## 10. REPORTING

Per row: `Bn <name> — service: <what> — evidence: <fingerprint> — audit: PASS/FAIL — scoreboard: X/10`.
At session end: the updated scoreboard, the SLO/rail status on real paths, the remaining operator inputs blocking any `Partial` row, and the single next highest-leverage action.
