# Phase 6: Exact Blueprint Runtime Parity — Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Source:** Synthesized from controlling parity docs (no discuss-phase needed — design is already locked in ROADMAP-TO-100.md + OPS-HANDOFF-AND-OWNERSHIP.md + STRICT-BLUEPRINT-PARITY-AUDIT.md)

<domain>
## Phase Boundary

Phase 6 converts the verified local scaffold into **exact 1:1 blueprint parity**. As of 2026-06-24
the project is **~82% blended**: the functional/architectural scaffold is ~85% done, **6 of 6
headline SLOs are empirically PROVEN** (recall 0.977, nDCG 0.983, G2 +0.208@7%, poison 1.0, warm
P95 149.5ms, ECE 0.0063), and the mandatory Tier A `src` reconciliation wirings (A1–A10, A13, A14)
are **closed on `main`**. The full local + clean-Postgres suite is green (837 tests, 0 failures).

The remaining ~18% is **NOT "write more code in the same style."** It is two distinct kinds of work:
1. **Operator-captured production evidence** for the 10 "Partial" strict-audit rows (ops/deployment,
   not feature code) — the bulk of the remaining percentage.
2. **Optional code wirings** the operator explicitly opted to include this phase: A11, A12, FR-20,
   FR-21.

### This phase's EXECUTABLE scope (operator decision: "Readiness artifacts, no cloud" + "Include everything")

Everything that is **authorable without standing up paid cloud infrastructure** is in autonomous
scope. The genuine real-infra evidence capture (Keycloak/Vault/KMS prod, ParadeDB+AGE, hosted
endpoints, GPU trainer, deployed C2PA trust roots) is captured as **explicit non-autonomous operator
gates** — the executor authors the runbooks + proves the local-staging dry-run; the operator runs the
production capture later. This phase therefore drives the project to **"one operator run from 100%"**,
not to a literal v1.0 attestation (which requires the operator evidence pass).

### ⚠ LIVE COORDINATION HAZARD (load-bearing)

`main` is being edited by an **autonomous Codex/GSD session right now** — `infra/` has uncommitted
changes and `capture-production-evidence.sh` was touched minutes ago. The Codex session owns the
`src/` and `infra/` ops lane. **This plan must not clobber active work.** Planning artifacts under
`.planning/phases/06-.../` and `.planning/runbooks/`, `.planning/ENV-AND-SECRETS.md`,
`.planning/ROLLBACK.md` are safe (Codex is not touching them). For any `infra/` or `src/` task: VERIFY
and COMPLETE what already exists, coordinate, and never `git add -A`.
</domain>

<decisions>
## Implementation Decisions

### Scope discipline (frozen — from OPS-HANDOFF §0)
- **D-01:** Every "Partial" strict-audit row is **OPS scope, not coding**. Do NOT write code to
  "close" a Partial row. The 28 `PRODUCTION_RELEASE_REQUIRED_COMMANDS` gates and their
  `RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS` validators are **frozen-complete**. Do NOT add new
  `*-ops-check` gates — they add zero parity value. A task that reads "write code to close a Partial
  row" is mis-scoped; STOP.
- **D-02:** The only sanctioned **parity** code is **Lane G** — the live-parity test sweep (test
  determinism + engine/runtime-method coverage). Optional code in D-09–D-12 below is sanctioned
  separately because the operator explicitly opted into A11/A12/FR-20/FR-21 this phase.

### Readiness artifacts to AUTHOR (the executable core — Lanes C/D/F)
- **D-03 (Lane C — runbooks):** Create `.planning/runbooks/` with **one runbook per parity row
  (10 total)**. Each runbook cites the exact frozen gate command(s) and run order, the real-infra
  dependency, redaction requirements, and the universal acceptance pattern (evidence →
  `deployment-soak --evidence-dir` → `release-audit --require-production-validated`). Source the
  per-row command list verbatim from OPS-HANDOFF §3; do not re-derive it.
- **D-04 (Lane D — env/secrets):** Author `.planning/ENV-AND-SECRETS.md` — env-var catalog +
  Vault/Keycloak/KMS wiring + provisioning steps. **NO secret values.** Cross-reference the existing
  `infra/keycloak/`, `infra/vault/`, and `infra/c2pa/` assets rather than restating them.
- **D-05 (Lane F — rollback):** Author `.planning/ROLLBACK.md` — revert procedures, canary-abort,
  rollback drills incl. the `parametric-trainer-check` rollback drill. Reference (don't restate)
  `gstack land-and-deploy` deploy/rollback flow.

### Evidence-capture harness + local-staging proof (Lane G — autonomous, no cloud)
- **D-06:** Verify and, where incomplete, complete `infra/scripts/capture-production-evidence.sh`
  (already exists) so it runs the sanctioned path: operator evidence → `deployment-soak
  --evidence-dir` with `production_validated=true, target_environment=production,
  operator_asserted=true` → `release-audit --require-production-validated
  --require-provider-forbid-local`. Coordinate with the active session; do not rewrite its work.
- **D-07:** Prove the **full LOCAL-staging dry-run end-to-end** and capture the fingerprint:
  `infra/scripts/setup-all.sh` + `infra/validate/validate-all.sh` pass; `deployment-soak
  --evidence-dir` over local real services + provider metadata; `release-audit --allow-provider-local`
  passes for the available checks. This is explicitly **staging proof, NOT production validation**
  (`production_validated=false`); the artifact must say so.
- **D-08 (Lane G — live-parity sweep):** Run the full **compose-Postgres** suite with
  `MNEMOSYNE_POSTGRES_DSN` set; confirm every engine/runtime method is covered and
  `belief-revision-check` is green; 0 failures/errors. Fix any test-determinism or method-coverage
  gaps (sanctioned code only — no engine behavior change).

### Optional items the operator opted to INCLUDE this phase
- **D-09 (A11 — hosted-MCP transport, FR-9):** Official SDK StreamableHTTP + legacy SSE are already
  locally validated (`mcp-streamable-http-soak`, `mcp-sse-soak`, `mcp-http-soak`). Complete any
  remaining readiness so that ONLY operator hosted-endpoint evidence (`mcp-ops-check`) remains; write
  the row-3 runbook to capture it. No new transport code unless a concrete gap is found.
- **D-10 (A12 — materialized cached-PPR column, FR-11):** Add a materialized cached-PPR column +
  refresh path. **Additive, default-off, byte-identical when inactive**; schema migration lives in
  `sql/schema.sql` (raw SQL, no ORM); shared Local/Postgres coverage; no retrieval-quality change
  when disabled. Gate behind the real-infra evidence pass for production claims.
- **D-11 (FR-20 — multimodal breadth):** Extend extractor / media-embedding / object-store / job /
  retrieval contracts for image+audio+video as **authorable code + local validation**. Production
  extractor/embedder evidence stays operator-run under parity **row #6** (`multimodal-ops-check`).
- **D-12 (FR-21 — real LoRA / test-time-training):** Author the trainer / protected-suite / rollback
  **code + local isolated validation**. Real GPU trainer deploy + production rollback evidence stays
  operator-run under parity **row #9** (`parametric-trainer-check`); overlaps that row.

### Acceptance + git discipline
- **D-13:** Per-row production-evidence tasks are **non-autonomous operator gates**
  (`autonomous: false`): they need real cloud infra + operator hands. The executor authors the
  runbook + local dry-run; it must NOT mark a row Done without `release-audit
  --require-production-validated` against real infra.
- **D-14:** Git discipline — `main` is edited by an active autonomous session. **Never `git add -A`.**
  Stage only specific new files (the new phase dir; new `.planning/runbooks/`; `ENV-AND-SECRETS.md`;
  `ROLLBACK.md`; any A12 `sql/` migration; FR-20/FR-21 `src/`). Push fast-forward only. Verify the
  tree is not mid-edit before committing.
- **D-15 (phase DoD):** This phase is DONE (readiness scope) when: all 3 readiness artifacts authored
  (D-03/04/05), the local-staging dry-run is proven with a captured fingerprint (D-07), the Lane G
  sweep is green (D-08), and A11/A12/FR-20/FR-21 code is landed + locally validated (D-09–D-12). Full
  1:1 sign-off (10 rows Partial→Done + v1.0 attestation) remains gated on operator production evidence
  and is tracked as the explicit operator gates from D-13.

### Claude's Discretion
- Plan/wave decomposition, exact runbook section structure, how to split FR-20/FR-21 across plans, and
  test-file organization for the Lane G sweep are the planner's discretion — provided the locked
  decisions above and the OPS-HANDOFF scope rules are honored.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Controlling status + scope (read first)
- `docs/ROADMAP-TO-100.md` — Tier A/B/C breakdown; why ~70%→~82%; completion math (Tier B→~97%, Tier C→100%).
- `.planning/OPS-HANDOFF-AND-OWNERSHIP.md` — THE plan skeleton: 10 ops rows (§3) w/ exact gate commands + "Done when", lane registry (A–G), DoD (§5), DO-NOT-REDERIVE rule (§0).
- `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` — the controlling audit; 10 "Partial" rows are the sign-off checklist.
- `docs/STATE-OF-COMPLETION.md` — historical Waves 1–3 scoreboard + current SLO results.

### Parity detail
- `.planning/BLUEPRINT-PARITY-MATRIX.md` — capability-by-capability parity matrix.
- `.planning/PARTIAL-ITEMS-KEY-SCHEMA.md` — schema/keys for partial-item tracking.
- `.planning/REQUIREMENTS.md` — FR/NFR/REQ source list.
- `.planning/ROADMAP.md` (Phase 6 section) — success criteria (6) + intended plans 06-01…06-06.
- `.planning/v1.0-MILESTONE-AUDIT.md` — v1.0 milestone audit.

### Existing infra + frozen gates (verify, do not clobber — active session owns these)
- `infra/scripts/` — `setup-all.sh`, `up.sh`/`down.sh`, `setup-{keycloak,vault,c2pa}.sh`, `capture-local-evidence.sh`, `capture-production-evidence.sh`.
- `infra/validate/validate-all.sh`, `infra/templates/production-soak-manifest.template.json`, `infra/PRODUCTION-EVIDENCE.md`, `infra/README.md`.
- `infra/keycloak/realm-mnemosyne.json`, `infra/vault/{mnemosyne-transit-policy.hcl,providers.json,vault-object-key-provider.py}`, `infra/c2pa/`.
- `src/mnemosyne/cli.py` — frozen gate commands: `PRODUCTION_RELEASE_REQUIRED_COMMANDS` / `RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS` (do not add gates).
- `sql/schema.sql` — raw-SQL schema (A12 cached-PPR migration lands here).
</canonical_refs>

<specifics>
## Specific Ideas

### The 10 ops rows (from OPS-HANDOFF §3 — one runbook each, D-03)
1. Production Postgres retrieval — `retrieval-ops-check` (+ `provider-check` retrieval_backends) — ParadeDB BM25 + Apache AGE + pgvector + non-local embed/rerank.
2. Tenant isolation & auth — `auth-ops-check` (+ `idp-jwks-live-check`, `idp-authz-policy-rollout-check`, `tls-cert-check`, `tls-rotation-plan-check`, `tls-lifecycle-ops-check`) — Keycloak + Vault + real TLS.
3. CLI/MCP runtime coverage — `mcp-ops-check` (+ `mcp-http-soak`, `mcp-streamable-http-soak`) — hosted MCP endpoint(s) w/ TLS. **[A11 — D-09]**
4. Consolidation role pipeline — `consolidation-ops-check` (+ `worker-run`, `worker-ops-check`, `projection-recompute-once`, `gate-suite-check`) — supervised Postgres worker + model-backed roles.
5. Signed provenance — `provenance-ops-check` (+ `provenance-trust-check`) — real c2patool + trusted issuer/root.
6. Multimodal retrieval — `multimodal-ops-check` — non-local extractor + media-embedding + encrypted object store. **[FR-20 — D-11]**
7. Privacy & erasure — `privacy-ops-check` (+ `policy-ops-check`, `forgetting-policy-check`) — real KMS (Vault) + residency.
8. Observability dashboards — `ops-dashboard-check` (+ `ops-report`) — hosted production dashboard.
9. Parametric tier — `parametric-trainer-check` (+ `hosted-llm-check`, `calibration-tune`) — deployed LoRA/TTT + rollback. **[FR-21 — D-12]**
10. Live parity suite — full compose-Postgres suite + `belief-revision-check`. **[Lane G — D-08]**

### Universal acceptance pattern (every row)
operator runs gate against real infra → evidence redacted → `deployment-soak --evidence-dir`
(production scope + operator attestation) → `release-audit --require-production-validated` passes with
that command's output shape present and `findings` empty.

### Lane registry (one owner per lane, OPS-HANDOFF §2)
A=Memory schema · B=Memory entry templating · C=Runbooks · D=Env & secrets · E=Observability ·
F=Rollback · G=Final validation (aggregation + sign-off + sanctioned live-parity code).
</specifics>

<deferred>
## Deferred Ideas

- **Actual production-infra provisioning + paid cloud + operator-run evidence capture** — out of THIS
  phase's autonomous scope by operator decision ("Readiness artifacts, no cloud"). Tracked as the
  non-autonomous operator gates in D-13; each has an authored runbook.
- **v1.0 1:1 sign-off + release attestation** — flip the 10 strict-audit rows Partial→Done and
  supersede with a v1.0 attestation. Happens only after the operator production-evidence pass; not in
  this phase.
- **Bridgememory memory-schema (Lane A) / entry-templating (Lane B)** — multi-agent memory
  coordination artifacts, separate from the parity sign-off; not in this phase unless the strict audit
  raises them.
</deferred>

---

*Phase: 06-exact-blueprint-runtime-parity*
*Context gathered: 2026-06-24 — synthesized from controlling parity docs*
