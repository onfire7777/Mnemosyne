# Mnemosyne — Deployment & Operations Handoff + Ownership Registry

**Date:** 2026-06-23
**Type:** Ops/deployment coordination + artifact-ownership registry. **NOT a coding plan.**
**Scope source (do not recompute):** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (10 "Partial" rows) and memory `mnemosyne-topology-and-status`.

---

## 0. DO-NOT-REDERIVE RULE — read first, load-bearing

1. **The current split is SETTLED by `docs/ROADMAP-TO-100.md` and `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.** Tier A code/local readiness is closed; all 10 production-evidence rows remain Partial until operator-captured production evidence exists. Do not recompute, re-score, or re-audit percentages.
2. **The machine-checkable gate layer is COMPLETE.** All 28 `PRODUCTION_RELEASE_REQUIRED_COMMANDS` already have output-shape validators in `RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS` (`cli.py`). **Do NOT add new `*-ops-check` gates** — they add zero parity value and re-derive the split.
3. **Every "Partial" row is OPS SCOPE, not coding.** Closing a Partial row = run the existing gate against *real infrastructure* and capture operator evidence. If a task reads as "write code to close a Partial row," STOP — it is mis-scoped.
4. **The only sanctioned acceptance path:** operator evidence → `deployment-soak --evidence-dir` (with `production_validated=true, target_environment=production, operator_asserted=true`) → `release-audit --require-production-validated --require-provider-forbid-local` passes. Use `infra/scripts/capture-production-evidence.sh` to run that path from an operator-authored production soak manifest. `MNEMOSYNE_PROD_EVIDENCE_DIR`, `PREFLIGHT_OUT_ROOT`, and `OUT_ROOT` must be absolute external custody paths outside the repository; output roots must be new or empty. Operators may run `infra/scripts/capture-production-evidence.sh --preflight-only` first as setup proof only; preflight does not flip any row Partial→Done. No code change is required or wanted to flip a row Partial→Done.

If any future session is tempted to re-open the table, regenerate scores, or build another gate: that work is already done. Run infra instead.

---

## 1. Scope rule (enforced)

- **Partial = ops. Coding is frozen for parity.**
- No parity code changes are currently sanctioned unless a new strict-audit finding explicitly reopens code scope. Everything else is deployment/operations/documentation.

---

## 2. Artifact Ownership Registry — ONE owner per lane, NO overlap

Assign exactly one terminal per lane. A lane MAY read another lane's output; a lane MUST NOT write another lane's artifact.

Lanes A/B are external BridgeMemory coordination artifacts for tracking Partial
items. They are not Mnemosyne runtime architecture and do not imply that
Mnemosyne depends on gbrain, mempalace, or any external memory system.

| Lane | Artifact | Owns (scope IN) | Out of scope (belongs to another lane) | Primary surface |
|---|---|---|---|---|
| **A** | Memory schema | Bridgememory hub structure + field/key definitions | Entry body/front-matter rendering, entry content | `Desktop/Bridgememory/.bridgememory/{_layout.json,index.json}` |
| **B** | Memory entry templating | Entry front-matter + body template, naming, cross-links | Hub layout/index, the field-set definition | `Desktop/Bridgememory/.bridgememory/*.md` |
| **C** | Runbooks | Step-by-step deploy/operate procedure per surface; which gate cmd to run + in what order | Secret values, dashboard internals, rollback specifics (reference only) | `.planning/runbooks/` *(to be created by Lane C)* |
| **D** | Env & secrets guidance | Env-var catalog, Vault/Keycloak wiring, provisioning steps — **no secret values** | Operational sequencing, monitoring, rollback | `.planning/ENV-AND-SECRETS.md` *(Lane D)* |
| **E** | Observability | Live dashboards, alert routing, SLO monitors; `ops-report` + `ops-dashboard-check` live wiring | Deploy steps, rollback, secret provisioning | hosted dashboard URL/package |
| **F** | Rollback | Revert procedures, canary-abort, rollback drills + drill evidence | Forward deploy steps, monitoring authorship | `.planning/ROLLBACK.md` *(Lane F)* + `parametric-trainer-check` rollback drill |
| **G** | Final validation | Aggregating gate evidence → `deployment-soak` → `release-audit` sign-off; Live-parity test sweep (sanctioned code) | Producing per-area evidence (each row's lane owns that); authoring runbooks | `release-audit`, `deployment-soak --evidence-dir` |

**This file (the registry) is owned by the coordinator lane (G) and is read-only to A–F.**

---

## 3. Assignment & acceptance — the 10 ops work items

Gate commands already exist and are frozen. Work = run each against real infra and capture redacted evidence.

| # | Parity row | Gate command(s) — already built | Real-infra dependency | Lanes consumed | Done when |
|---|---|---|---|---|---|
| 1 | Production Postgres retrieval | `retrieval-ops-check` (+ `provider-check` retrieval_backends) | ParadeDB BM25 + Apache AGE + pgvector + non-local embedding/reranker | C,D,E,G | gate evidence over deployed adapters in bundle; `release-audit` ok |
| 2 | Tenant isolation & auth | `auth-ops-check` (+ `idp-jwks-live-check`, `idp-authz-policy-rollout-check`, `tls-cert-check`, `tls-rotation-plan-check`, `tls-lifecycle-ops-check`) | Keycloak IdP/JWKS + Vault secrets + real TLS certs/rotation | C,D,E,F,G | live IdP/JWKS/TLS evidence + tenant-RLS cases in bundle; `release-audit` ok |
| 3 | CLI/MCP runtime coverage | `mcp-ops-check` (+ `mcp-http-soak`, `mcp-streamable-http-soak`) | Hosted MCP endpoint(s) with TLS | C,E,G | hosted JSON-RPC + StreamableHTTP soak evidence in bundle; `release-audit` ok |
| 4 | Consolidation role pipeline | `consolidation-ops-check` (+ `worker-run`, `worker-ops-check`, `projection-recompute-once`, `gate-suite-check`) | Supervised Postgres worker + model-backed extractor/summarizer/resolver | C,D,E,F,G | supervised worker + provider + projection evidence in bundle; `release-audit` ok |
| 5 | Signed provenance | `provenance-ops-check` (+ `provenance-trust-check`) | Real c2patool + trusted issuer/root deployment | C,D,G | verifier + trust-root rotation + quarantine evidence in bundle; `release-audit` ok |
| 6 | Multimodal retrieval | `multimodal-ops-check` | Non-local extractor + media-embedding + encrypted object store | C,D,E,G | extraction + media-vector retrieval evidence in bundle; `release-audit` ok |
| 7 | Privacy & erasure | `privacy-ops-check` (+ `policy-ops-check`, `forgetting-policy-check`) | Real KMS (Vault) + residency policy ops | C,D,F,G | KMS lifecycle/shred + residency + tombstone/hard-delete evidence; `release-audit` ok |
| 8 | Observability dashboards | `ops-dashboard-check` (+ `ops-report`) | Hosted production dashboard URL/package | E (primary), G | hosted-dashboard ops evidence in bundle; `release-audit` ok |
| 9 | Parametric tier | `parametric-trainer-check` (+ `hosted-llm-check`, `calibration-tune`) | Deployed LoRA/TTT trainer + rollback orchestration | C,D,F,G | trainer deploy + protected-suite + rollback-drill evidence; `release-audit` ok |
| 10 | Live parity suite | full compose-Postgres suite + `belief-revision-check` | Optional production adapters enabled | G (sanctioned code) | Local/Postgres direct configured lexical/graph adapter parity is now covered; final done still requires every engine/runtime method green with production adapters enabled |

**Universal acceptance pattern (every row):** operator runs the gate against real infra → evidence redacted → included in `deployment-soak --evidence-dir` (production scope + operator attestation) → `release-audit --require-production-validated --require-provider-forbid-local` passes with that command's output shape present and `findings` empty.

---

## 4. Boundary confirmation + overlaps flagged for reassignment

Confirmed distinct as scoped: A↔B and C↔D↔E↔F↔G. Five seams carry overlap risk — each is resolved to a single owner below; reassign here if a terminal disputes it:

- **A vs B (schema ↔ templating):** the entry **field set** (which keys exist) is a SCHEMA concern → **Lane A** owns it in `_layout.json`; **rendering** of those fields → **Lane B**. The template references the schema; it does not redefine fields.
- **C vs G (runbooks ↔ final validation):** both touch `*-ops-check`. **Lane C** documents *how* to run each gate; **Lane G** owns *aggregation + sign-off*. The gate binaries are frozen shared infra — no lane edits them.
- **E vs G (observability ↔ final validation):** `ops-dashboard-check` evidence. **Lane E** owns the live dashboard + alerts; **Lane G** owns that its evidence is in the release bundle.
- **D vs C (env/secrets ↔ runbooks):** secret provisioning. **Lane D** owns the catalog + provisioning steps; **Lane C** references them and never restates values.
- **F vs C (rollback ↔ runbooks):** **Lane F** owns recovery/abort; **Lane C** owns forward deploy steps. No single deploy/rollback step is authored in two lanes.

**No artifact is double-owned.** Memory-schema work (A) is fully separate from memory-entry templating (B); runbooks (C), env/secrets (D), observability (E), rollback (F), and final validation (G) are distinct artifacts with single owners.

---

## 5. Definition of Done (whole effort)

`release-audit --require-production-validated --require-provider-forbid-local` passes on a `deployment-soak` bundle in which **every** required command and required provider sub-check carries real-infra operator evidence. At that point all 10 rows flip Partial→Done. Until then: **Partial = ops backlog, never code backlog.**

Deploy/land flow for each surface: use the external `gstack land-and-deploy` workflow tooling (dry-run -> pre-merge gate -> deploy strategy -> canary verification -> deploy report). Pre-landing diffs (Lane G code only) go through `review/checklist.md`. This tooling reference does not merge Mnemosyne with gstack, gbrain, or mempalace.
