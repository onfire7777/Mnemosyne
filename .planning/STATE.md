---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Public Benchmark and Memory Leadership
status: executing
stopped_at: "M03 remains PROPOSED and blocked because the mapped lease excludes the authorized MemoryTools valid_from write path; reviewed M12/M13 test-only confirmation integration is next. Result-v2 remains protected, and sandbox/measurement/launch gates remain open."
last_updated: "2026-07-30T06:35:27Z"
last_activity: 2026-07-29
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 9
  completed_plans: 8
  percent: 29
---

# Project State

## Release Attestation — Tier-B Production Evidence (2026-07-07)

Tier-B is CLOSED. A genuine operator-run production capture over the live self-hosted stack produced a fully green 29-command `deployment-soak` (0 required failures), `release-audit` `ok:true` (0 findings; 29 required commands + 15 required provider checks), and an offline `production-evidence-verify` `ok:true` (0 findings; matching out-of-band fingerprint). This flips all 10 `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` rows Partial->Done and supersedes the earlier open strict-audit note.

- Bundle fingerprint: `sha256:6dc117d6bb95e7a683915d432b2d2b21997133e9bfbd53624427a7317eeb2271`
- captured_at: `2026-07-07T15:53:18Z`
- Verifier report: `mnemosyne-evidence-out/verify-bc10.json`
- Evidence capture code: `main@58e722c` (adds the `production-evidence-verify` executable tool-artifact rewrite fix, test-first)
- Documentation checkpoint at Tier-B attestation: `main@02337fa2f334b7421673585de9d8c60df6c29a7a` plus that cleanup pass.
- Gate: real evidence only — no validator weakened; no row flipped without a genuine `production-evidence-verify` `ok:true`.

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-19)

**Core value:** Build a memory compiler with lossless evidence, typed projections, safe retrieval, branchable updates, and gated self-improvement.
**Current focus:** Plan 12-04 closure remains the measured critical path — the #46–#61 lease sweep is delivered to main and Blueprint §7 code residuals are closed; what remains is **operator measurement**, not implementation: CAP-003/BENCH-005 stay Partial pending measured EM/F1 ≥ 0.85, and 12-04-03 stays held. In parallel, the six Phase 16 L1-L4 source packages are merged through PR #72 (`main@b9c475ad`); they prepare the ledger, validation, rendering, publication, taxonomy, and readiness surfaces but do not satisfy or publish any launch gate.

## Current Position

Phase: 12 of 16 — Grounded Multi-Hop Answer Synthesis
Plan: 4 of 4
Status: Plan 12-04's full lease sweep is **delivered to `main`**. **12-04-01** preserved. **12-04-02** landed via PR #46. Residual Leases **A, C, D, E, F** via PRs #47–#51; **Lease G / G-wire / G-consol** external corroboration via #52–#54; Blueprint §7 **#19a, #19a.1, #19b** counterfactual fidelity via #55–#57; **#18** multi-signal `calibrated_confidence` fuse via #58; **#12** per-example conformal via #59; **#13** AGM contraction + ATMS labels via #60; **#14** `must_keep` + pointer-to-original via #61. All sixteen merged on green required CI, ending at `main@34effb4b`; the `.planning/STATE.md` reconcile followed as PR #62 (`main@e1b02221`). Delivery was verified by content, not commit count: every product tree was byte-identical between `main` and the retired staging branch. Blueprint §7 items **#12, #13, #14, #18, #19** are now marked closed in `BLUEPRINT-PARITY-MATRIX.md` with their merge SHAs — each re-verified as genuinely wired in `src/` before marking, including `counterfactual_replay_score()`, which is no longer dead. CAP-003/BENCH-005 remain **Partial** until measured EM/F1 ≥ 0.85 — no benchmark or headline claim changed. **12-04-03** and production VM/Vault/W4–W5/headline stay Blocked. W3 memory planes + CAP-012/013 Complete history via PR #39 `main@0784340` unchanged.
Last activity: 2026-07-30 — PR #82 merged the bounded M12/M13 development
evidence confirmations as `main@7e9cd01f`; exact-head CI run `30521721192`,
exact-merge CI run `30522846090`, and 46 focused tests passed. M12/M13 remain
`PROPOSED`; no measured, publishable, PBPP, or headline claim changed.

## Parallel Phase 16 Source Status

PRs #65–#72 merged the result contract, contract hardening, signed run ledger,
static renderer, signed publication path, metric taxonomy, and deterministic
launch-readiness validator. The current source-preparation packages are complete,
but Phase 16 remains open: no real entrant bundle, measured leaderboard
dimension, PBPP/Part-I/Register-A evidence, identical-treatment evidence,
operator-entry evidence, or human-approved publication is claimed. The
controlling details are in `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`,
and the six `docs/plans/2026-07-25-phase16-*` /
`docs/plans/2026-07-26-phase16-*` records.

## Whole-Memory Pilot Status

PR #81 merged exact source head
`98b83e4be373cf0acd5411769b80b98dfd1a8caa` (reviewed candidate lineage
`c9e7884e4263cdeedeaf2fe5b30f9796226082b3`) to
`main@392b1fc173f454893e1b133ff3a727462586a8b0`. Exact-merge CI run
`30506775012` and the 507-test focused M01/M10/public-eval/reference suite
passed; Ruff passed. M01 and the deterministic M10 reader retain
`PILOT-READY-DEV`, while every result remains `publishable:false` and
`pbpp_headline_eligible:false`. Bounded M03 is blocked because the committed
lease excludes `src/mnemosyne/mcp_tools.py`, whose authorized assertion and
supersession methods cannot currently persist caller-supplied `valid_from`.
PR #82 then merged final candidate
`a3ca8108c22de350810dc3f574931a0d85810ed5` as
`main@7e9cd01feb2a31cbba96252943697245a4edd024`. Exact-head CI run
`30521721192`, exact-merge CI run `30522846090`, and the 46-test focused
M12/M13 public-action suite passed; focused Ruff and `git diff --check` passed.
M12 and M13 remain `admission_state=PROPOSED` and
`evidence_level=INTERNALLY_MEASURED`; `publishable:false`,
`headline_eligible:false`, `independent_reproduction:false`, and
`upstream_comparable:false` remain unchanged. Result-v2 remains blocked by the
protected signed-publication lease, and sandbox enforcement remains
quarantined. No official run, measured pilot cell, recurrence or promotion
work, benchmark, launch, certification, ranking, or publication gate advanced.

## Performance Metrics

**Velocity:**

- Total plans completed: 18
- Average duration: not yet measured
- Total execution time: not yet measured; latest P5 local verification completed on 2026-06-28

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 0 | 4 complete | 4 | pending |
| 1 | 5 complete | 5 | pending |
| 2 | 5 complete | 5 | pending |
| 3 | 5 complete | 5 | pending |
| 4 | 5 complete | 5 | pending |
| 5 | 5 complete | 5 | pending |
| 09.1 | 1 | - | - |
| Phase 09.2 P01 | 18 min | 3 tasks | 10 files |
| 09.2 | 2 | - | - |
| 09.3 | 1 | - | - |
| 10 | 2 | - | - |
| 11 | 3 | - | - |
| 12 | 3 complete | 4 | pending |

## Accumulated Context

### Decisions

- [Whole-memory benchmark]: PR #81 merged exact source head `98b83e4be373cf0acd5411769b80b98dfd1a8caa` to `main@392b1fc173f454893e1b133ff3a727462586a8b0`; exact-merge CI run `30506775012` and 507 focused tests passed. M01 and the deterministic M10 reader remain `PILOT-READY-DEV`, all results remain `publishable:false`/`pbpp_headline_eligible:false`, and M03 valid-time integration is next without broadening into transaction-time semantics.
- [Phase 12]: W1 local development is complete through the baseline, Fix A, and Fix B receipts, but it does not close CAP-003, BENCH-005, or Plan 12-04 without production-Postgres parity, runtime readiness, grounded-reader development QA, and the protected attempt.
- [W3]: The full prospective-memory + working-memory plane is merged across Local/Postgres/Sqlite through PR #39 as `main@0784340` (Phase 1 hardening had landed earlier via PR #37 `7a1db210`). CAP-012/CAP-013 are Complete and test-pinned by `tests/test_planning_traceability.py`; the W2 D5 signed deletion manifest and the I0R signed-session public-action evaluator landed in the same merge. The I0R action suites are development-split and `publishable:false`, so they add no public/headline benchmark claim. Remaining W3 retrieval/rails/benchmark integration beyond those development suites, and the W4/W5 external-adapter GATEs, stay operator-gated and are not claimed complete.
- [Operations]: The local/full verification and Graphify/CBM/gbrain refresh were hardware-admitted and completed at `main@7a1db210`. VM/Vault restart, runtime-readiness repair, R3/R4 live rotation, grounded-reader development QA, the protected attempt, and W1 production parity remain operator-gated and must not be reported as failures or silently run while the production stack is intentionally stopped.
- [Phase 12]: Production MCP client rotation preserves the unchanged six-hour validator. Its separate diagnostic is restricted to the exact canonical current pair, admits only the validator's leaf-expiry-window failure with at most six hours remaining, requires live leaves to have a chain valid now, and permits historical chain probing only for an already-expired leaf.
- [Phase 12]: Rotation R1a is staged-only and offline-tested: Docker context/network/image/CLI identity, fixed container confinement, secret-free child environment/output, canonical private staging containment, staged ownership/modes/device, and normal post-issuance validation all fail closed before any later publication work.
- [Phase 12]: Rotation R1b uses a strict bounded secret-free journal and retained mode-0600 generations on the canonical filesystem. File and parent fsyncs bracket each journal/rename transition; startup accepts only phase-reachable old/new pair states. R1b auto-restores `pair_published` and earlier. Residual schema-v2 `published_validated` remains activation-ambiguous because the prior fixture used that phase across consumer recreation, so it is preserved and fails closed; R1c owns the later runtime-aware phases.
- [Phase 12]: The R1c fixture seam durably records `activation_started` before any consumer touch and performs crash-resumable post-activation rollback through `rollback_restoring_certificate`, `rollback_restoring_key`, and `rollback_pair_restored`. It also re-proves and finalizes `committed` state for the two success results, binding the canonical pair to retained transaction generations and the unchanged six-hour validator before journal unlink. A recoverable pending receipt precedes unlink; producer stdout is transaction-keyed and at-least-once across invocations until the pending receipt is durably renamed `emitted`, so receivers deduplicate `(transaction_id,result)`. This protocol does not provide receiver acknowledgement or rollback terminal receipts. The persistent local `flock` serializes cooperative rotator invocations only; R2 cross-workflow locking and live-runtime proof remain open.
- [Phase 12]: Rotation R1c uses one fixed blackbox-query helper: an OS-controlled interpreter orchestrates an exact label-selected Caddy/BusyBox request with a sanitized four-variable child environment, bounded output and monotonic deadlines, strict duplicate-free JSON/vector/freshness checks, and fixed non-leaking summaries. Caller-supplied URLs, queries, Docker context, labels, and metric identities are not accepted.
- [Phase 12]: Candidate protocol v2 was preregistered before any held-out attempt so manifests bind both complete role prompts/rendering, the concrete serializer, and the full generation envelope; Phase 11 custody/baselines remain unchanged.
- [Phase 12]: Local Ollama model identity is verified, but absent installed `/opt` role commands and a timed-out direct decomposer smoke keep runtime readiness open; Plan 12-04 may not consume a frozen/held-out attempt until that gate is real.
- [Phase 12]: Answer orchestration reuses shared deep retrieval/PPR and a typed `record_access=False` control; no alternate ranking/graph stack or new dependency was introduced.
- [Phase 12]: Every hop reuses the exact normalized authorization/temporal context and is independently replayed before emission; any drift collapses to generic abstention.
- [Phase 12]: QA bundle creation and verification are exact-clean-checkout operations; candidate manifests are external no-overwrite artifacts whose canonical bytes are embedded and verified end to end.
- [Phase 12]: QA claims cite real Mnemosyne evidence CIDs recomputed from complete capture envelopes and corpus custody, with frozen hop/record/character budgets enforced by the verifier.
- [Phase 12]: Freeze candidate protocol and Phase 11 baselines before implementation; use synthetic/dev fixtures only for iteration, then run `qa_hard_v2` and held-out LongMemEval-QA under preregistered single-pass controls.
- [Phase 12]: Reuse shared retrieval/PPR and the existing Ollama role-provider boundary; add a narrow orchestration layer with external CID validation, complete caller-context propagation, and ephemeral answers.
- [Phase 11]: BENCH-004 is complete; BENCH-005 remains partial because all three Hippo tracks measured zero positive graph/PPR participation and Phase 12 still owns real reader-produced EM/F1.
- [Phase 11]: HippoRAG retrieval is deterministic, but EM/F1 needs real reader-produced predictions; the scorer lands in Phase 11 and Phase 12 owns prediction closure.
- [CI]: The GitHub Actions billing block was resolved on 2026-07-12. R1c exact-head run `29313243324`, post-merge run `29314015888`, and ordinary scheduled-main run `29318113932` are green. R2a exact head `5bfd53d` passed run `29377793617`; stacked head `33967b1` passed PR #11 run `29378482152` and merged to `main` as `79f6b58`. Post-merge run `29379113689` passed all six gating jobs and accepts that main merge.

- [Phase 0]: V2 blueprint is controlling; v1 is lineage only.
- [Phase 0]: Build originally moved to `/Users/admin/Projects/Mnemosyne` because `/Users/admin/Desktop/Mnemosyne` was write-blocked; the current canonical checkout is `/Users/admin/Mnemosyne`.
- [Phase 0]: Local deterministic engine is used for fast verification; `sql/schema.sql` preserves the production PostgreSQL contract.
- [Phase 1]: Retrieval currently uses deterministic hashing embeddings and lexical scoring for local tests; production adapters remain required.
- [Phase 2]: Graph/PPR remains behind the engine contract; a benchmark harness now exists for backend profiling.
- [Phase 2]: Justification DAG, cascade invalidation, operation classification, contested hypotheses, and conformal calibration are implemented locally.
- [Phase 3]: Six-category user model, scope-matched context assembly, latent advisory profile, rehearsal schedule, and anti-degradation guard are implemented locally.
- [Phase 4]: Trajectory logging, failure attribution, lesson/procedure induction, gate promotion, replay scoring, and permanent poisoning cases are implemented locally.
- [Phase 5]: Self-model store, outcome windows, policy variant proposal, tripwire checks, and canary policy gate are implemented locally.
- [NFR]: Local latency benchmark, schema coverage, privacy classification, metrics registry, and Docker compose config are implemented.
- [Phase 5]: Self-optimization remains shadow-first and constrained by immutable rails.
- [Phase 09.1]: Preserve caller read context across search, deep_search, and explain before v1.0 archival.
- [Phase 09.2]: Mount the bounded, fail-closed heartbeat in a public runtime before v1.0 archival.
- [Phase 09.3]: Complete milestone verification, Nyquist validation, and REQ/NFR traceability before v1.0 archival.
- [Runtime]: CLI now supports `--backend local|postgres` plus `--postgres-dsn`/`MNEMOSYNE_POSTGRES_DSN`; live tests verify the Postgres backend through real CLI commands.
- [Parity]: `tests/test_shared_engine_contract.py` now runs the same evidence retrieval/export, branch/discard, and bitemporal `as_of` contracts against `LocalMemoryEngine` and `PostgresEngine`; this also fixed Postgres branch creation for previously unseen tenants.
- [Retrieval]: Local and Postgres `graph_ppr` now exclude expired relations by default while preserving explicit historical `as_of` graph traversal.
- [Security]: `MemoryTools` now enforces `SecurityPolicy` for preference writes, hard-instruction profile writes, and destructive forget operations; CLI denials are covered by tests.
- [Security]: Fact, relation, proposal, supersession, and correction writes now route through `MemoryTools` capability checks; CLI `assert`/`relation` no longer bypass the facade.
- [Security]: Branch creation, confirmation, merge, and discard now require explicit role/source-trust context through `MemoryTools` and CLI; branch promotion requires operator/consolidator authority.
- [Security]: Lesson promotion and procedure validation/promotion/rollback now require mediated operator/consolidator authority through `MemoryTools`, CLI flags, or signed session injection before mutating runtime learning state.
- [Security]: OIDC/JWKS `session-exchange` now supports fail-closed authz policy mapping from verified IdP client/tenant/claim rules to Mnemosyne role/trust claims for CLI and hosted HTTP exchange; policy mode rejects malformed schemas, missing client allowlists, invalid roles, rule misses, ambiguous matches, and raw role/trust fallback; `idp-authz-policy-check` emits bounded secret-free summaries for deployment review.
- [MCP]: `mneme-mcp --sdk` can now run the same tool facade through the official Python MCP SDK when the optional `mcp` extra is installed; JSON-RPC and SDK handler tests cover tool listing, generated input-schema validation, explicit optional-null fields, auth-token denial, capture, and search, and CLI `tools` emits the same MCP-style `inputSchema` shape.
- [Consolidation]: Default local passes now resolve deterministic entity keys and execute summarizer, lesson_distiller, and skill_inducer roles for fact candidates; lessons/procedures persist through runtime learning state and are visible in `ops-report`. Command-backed candidate extractor, summarizer, and entity resolver providers can now supply model-backed consolidation boundaries and are validated by `provider-check`. `projection_recompute` can now compute affected evidence/projection sets from changed CIDs and queue consolidation only for dirty surviving source inputs with projection-specific pass selection.
- [Source Truth]: CLI/MCP `source-sync` compiles committed Markdown/git assertion blocks into evidence-backed assertions with Git SHA/path/line provenance; trust-tier conflict resolution is now monotonic, so tier-0 human source truth overrides newer lower-trust machine memory across local and Postgres backends.
- [Queue]: CLI `queue-enqueue`, `queue-drain`, `queue-snapshot`, and ingestion enqueueing can now use `--queue-backend postgres` with tenant-scoped `FOR UPDATE SKIP LOCKED` leasing and durable result persistence.
- [Gate]: CLI `gate-case-add/list` persists protected regression cases in runtime state; `gate-suite-check` reports suite counts/tier coverage/fingerprint and fails closed on missing protected cases or fingerprint mismatch; consolidation workers load protected cases and fail closed when a protected case regresses.
- [Observability]: CLI `ops-report` now exports dashboard-ready counts, queue state, learning diversity, proxy-vs-true gap, and tripwire status for a tenant; `--dashboard-html` writes a static dashboard artifact with memory, queue, retrieval, calibration, learning, gate/eval, and bounded JSON sections.
- [Storage]: `sql/schema.sql` now enables and forces tenant RLS on tenant-owned tables, and `PostgresEngine` sets `mnemosyne.tenant_id` before tenant-scoped SQL.
- [Privacy]: Local and Postgres forget paths now accept `tombstone_recompute` or `hard_delete_legal`; CLI exposes `--erasure-mode`; encrypted local object storage supports AES-GCM per-object keys, JSON-backed and command-backed key managers, provider-check key-cycle validation, and legal hard-delete crypto-shreds the object key after successful forget; CLI and MCP ingestion enforce configured data residency labels, strict runtime processing residency when enabled, and explicit cross-region `source->target` transfer allowlists, then record residency decisions in evidence access policy; CLI/MCP can inspect the active residency policy and provider-check reports it; forget now erases media-derived evidence and retracts/strips assertions/preferences/relations that depended on source or derived evidence.
- [Retrieval]: CLI/Postgres can now use local or HTTP-compatible embedding and reranker providers via flags/env while keeping deterministic local defaults; HTTP providers now fail closed on malformed responses and `provider-check` exits nonzero on broken contracts.
- [Audit]: Local and Postgres audit entries now expose `source`, `trust_tier`, `capability_tags`, and structured `diff` fields for write-path provenance, including evidence, assertions, preferences, learning records, and legal delete/forget flows.
- [Parametric]: CLI and MCP can now use a command-backed LoRA/test-time-training adapter provider for proposal, evaluation, and rollback; provider calls are operator-authorized, shell-free, JSON-contract validated, included in `provider-check`, persisted with metrics/payloads, and gated by local mutation-rate bounds, external-only reward metadata, monotonic-trust/sink restrictions, exact artifact/gate matching, protected-case pass requirements, and margin-over-noise checks. Parametric evaluation and rollback prefer persisted protected regression cases from runtime state, report stable protected-suite snapshots, persist rollback suite metadata, pass the suite to command-backed rollback providers, and validate the rollback suite contract in `provider-check`.
- [Provenance]: CLI `ingest` now accepts `--file`, modality/media type, signed-provenance JSON, a `--c2pa-tool` adapter, `--trusted-provenance-root`, and `--provenance-trust-policy`; C2PA reports must bind to the exact asset by SHA-256/path before they can raise trust, scoped policies can match trusted tenant/source/modality context and quarantine valid-but-untrusted manifests when no rule, issuer, or certificate root matches, provenance validity/trust/binding capability tags propagate through evidence, and quarantined evidence is hidden from default retrieval unless `include_quarantined` is explicitly set.
- [Security]: Trust-tier semantics now follow the blueprint scale: `0` direct-user/highest trust through `5` untrusted external; retrieval/write gates, provenance deltas, SQL defaults, and CLI defaults were migrated.
- [Ingestion]: The hot path now classifies actor/source trust, adds capability/taint tags, detects simple PII, raises sensitivity/access-policy metadata, marks untrusted imperatives as data-only, indexes metadata-derived OCR/transcript/caption/alt/description text for externalized object evidence, and queues async media extraction when non-text payloads lack derived text.

### Roadmap Evolution

- Phase 09.1 inserted after Phase 9 (URGENT): Close audit gap: preserve caller context across search, deep_search, and explain.
- Phase 09.2 inserted after Phase 9 (URGENT): Close audit gap: mount the bounded heartbeat in the public runtime.
- Phase 09.3 inserted after Phase 9 (URGENT): Close audit gap: complete milestone verification, Nyquist, and requirement traceability.

### Pending Todos

- Finish exact blueprint parity, starting with expanding the live PostgresEngine smoke into a full shared contract suite, official hosted MCP streamable/SSE validation, real IdP/JWKS validation, and remaining production adapter deployment checks.
- Validate real production embedding/reranker deployments behind the HTTP-compatible adapter boundary; add ParadeDB/BM25 where needed and AGE/specialist graph adapters where needed.
- Add real secret-manager-backed session-secret command deployment/rotation validation, real IdP/JWKS deployment validation against live credentials, real KMS deployment validation behind the command key-provider boundary, real production C2PA trust-root validation, native image/audio embedding providers, production extractor deployment validation, real production entity resolver validation behind the command resolver boundary, real parametric trainer deployment validation behind the command provider boundary, production separation of immutable-rail service/credentials, production residency-policy operations, worker supervision/deployment operations, and deployment observability.

Historical checkpoint: Consolidation now supports a command-backed entity resolver boundary. The worker invokes the resolver between candidate extraction and promotion, records resolver pass details, persists resolver-provided entity keys into the tenant entity registry after gate promotion, and keeps deterministic resolution as the local default. CLI `ingest --run-consolidation-once`, runtime workers, provider manifests, and `provider-check` can configure the command resolver; provider-check fails closed when command output omits explicit candidate mappings. Focused CLI tests cover runtime consolidation, deployment-manifest provider checks, and malformed resolver failure. This reduces the richer entity-resolution gap while real deployed resolver validation remains open.

Historical checkpoint: Runtime jobs now include `projection_recompute` plus CLI `projection-recompute-enqueue` and `projection-recompute-once`. The job consumes changed evidence CIDs, expands through derived evidence/provenance edges such as `media-derived-text`, reports affected assertion/preference/relation/entity IDs, and can enqueue consolidation only for dirty surviving source inputs with projection-specific pass selection. It is allowlisted for `deployment-soak` as a bounded preflight. Focused CLI/runtime tests cover direct fact projections and media-derived evidence dependency expansion. This implements the blueprint's initial salsa-style affected-subgraph recompute guard while broader production IVM/differential recompute remains open.

Historical checkpoint: Consolidation now has shell-free command provider boundaries for candidate extraction and evidence summarization. The extractor receives tenant/payload/evidence JSON and must return fully shaped candidate rows before resolver/gate execution; the summarizer receives tenant/evidence JSON and must return a non-empty summary. CLI flags, provider manifests, runtime workers, and `provider-check` can configure both providers; provider-check fails closed on malformed extractor or summarizer output. Focused CLI tests cover model-style extraction of a non-deterministic evidence note, command summarizer pass details, deployment-manifest provider checks, and malformed provider failures. This reduces the model-backed extraction/summarization gap while real deployed model/provider validation remains open.

Historical checkpoint: `gate-suite-check` now provides a deployment-control surface for protected regression suites. It loads persisted gate cases from runtime state, reports case/protected/tier counts plus a stable canonical fingerprint, can include full cases for export/review, and exits nonzero when the protected count is below `--min-protected` or `--expected-fingerprint` does not match. The command is allowlisted for `deployment-soak`. CLI tests cover fingerprint acknowledgement and fail-closed mismatch behavior. This reduces protected-suite management risk while production release-artifact validation remains open.

Historical checkpoint: Live Postgres coverage now includes command-backed consolidation candidate extraction and summarization. The live test uses `PostgresEngine` with shell-free command provider adapters, promotes a non-deterministic evidence note through the protected gate, verifies command extractor/summarizer pass details, and confirms exported Postgres assertions/entities carry the provider-produced candidate. This broadens the shared Local/Postgres consolidation contract; it still requires `MNEMOSYNE_POSTGRES_DSN` to run.

Historical checkpoint: The live Postgres command-backed consolidation provider test now also exercises the command entity resolver boundary. The resolver receives provider-produced candidates, returns explicit candidate-to-entity mappings and entity metadata, and the test verifies the resolver pass details plus the persisted Postgres entity canonical supplied by the resolver. This broadens live production-adapter parity for extraction, resolution, and summarization while real deployed resolver/model validation remains open.

Historical checkpoint: Provider deployment manifests now have an explicit retrieval-backend health check for lexical and graph adapters. `provider-check` reports configured lexical/graph backend names and whether either is a local fallback; production manifests with `forbid_local` now fail closed on local lexical or graph backends, not only local embedding/reranker providers. Focused CLI tests cover a ParadeDB/AGE-style production manifest and a local BM25/PPR rejection path.

Historical checkpoint: CLI Postgres DSN selection now treats an explicit empty `--postgres-dsn ""` as fail-closed instead of falling back to `MNEMOSYNE_POSTGRES_DSN`; runtime state and Postgres queue loading follow the same rule. The regression test sets an env DSN to prove the explicit-empty override is honored. The full test suite passes against the local compose pgvector DSN `postgresql://mnemosyne:<redacted>@127.0.0.1:54329/mnemosyne` after this fix.

Historical checkpoint: CLI `tls-lifecycle-ops-check` now validates production TLS lifecycle evidence for CA/ACME issuance, renewal execution, current/candidate overlap, deployed serial/chain match, reload verification, non-local private-key custody, monitoring alerts, and raw key/cert/token/log redaction. The command is part of `deployment-soak` and the production `release-audit` output-shape profile; actual production TLS evidence remains operator-run.

Historical checkpoint: CLI `ops-dashboard-check` now accepts optional production dashboard operations evidence in addition to fingerprinted dashboard packages or hosted URLs. The gate validates production scope, refresh freshness, source snapshot fingerprinting, access controls, alert delivery, tenant binding, and raw snapshot/token/user-data redaction without storing raw dashboard payloads. Focused dashboard/release-audit coverage passes in `/tmp/mnemosyne-dashboard-ops-focused.xml` with 4 tests, the full local suite passes in `/tmp/mnemosyne-dashboard-ops-full-local.xml` with 431 tests, 0 failures/errors, and 63 live-DB skips, and the compose Postgres DSN suite passes in `/tmp/mnemosyne-dashboard-ops-full-postgres.xml` with 431 tests, 0 failures/errors, and 0 skips. Actual hosted production dashboard evidence remains operator-run.

Historical checkpoint: CLI `retrieval-ops-check` now requires production specialist adapter probe evidence for lexical, vector, graph, and reranker retrieval paths. The gate validates non-local backend/provider names, production validation, SHA-256 command/source/query/tenant/result/top-id fingerprints, hit counts, bounded latency, and redaction of raw query/document/result/stdout/stderr/command/env/credential fields. Focused retrieval/release-audit coverage passes in `/tmp/mnemosyne-retrieval-adapter-focused.xml` with 6 tests, the full local suite passes in `/tmp/mnemosyne-retrieval-adapter-full-local.xml` with 433 tests, 0 failures/errors, and 63 live-DB skips, and the compose Postgres DSN suite passes in `/tmp/mnemosyne-retrieval-adapter-full-postgres.xml` with 433 tests, 0 failures/errors, and 0 skips. Actual deployed ParadeDB/AGE/pgvector/reranker evidence remains operator-run.

Historical checkpoint: CLI `privacy-ops-check` now validates explicit raw key/object/subject/KMS-response redaction flags and recursively rejects raw privacy fields such as key material, object bytes, subject identifiers, credentials, tokens, and KMS responses. Focused privacy/release-audit coverage passes in `/tmp/mnemosyne-privacy-redaction-focused.xml` with 4 tests, the full local suite passes in `/tmp/mnemosyne-privacy-redaction-full-local.xml` with 434 tests, 0 failures/errors, and 63 live-DB skips, and the compose Postgres DSN suite passes in `/tmp/mnemosyne-privacy-redaction-full-postgres.xml` with 434 tests, 0 failures/errors, and 0 skips. Actual production KMS/residency evidence remains operator-run.

Historical checkpoint: CLI `parametric-trainer-check` now requires a production `deployment` section in addition to trainer, protected-suite, gate, rollback, rail, metrics, and redaction evidence. The gate validates HTTPS supervised endpoint health, canary pass, alert routing, protected-suite/artifact/rollback fingerprint binding, rollback drill verification, and bounded deployment latency. Focused parametric/release-audit coverage passes in `/tmp/mnemosyne-parametric-deployment-focused.xml` with 3 tests, the full local suite passes in `/tmp/mnemosyne-parametric-deployment-full-local.xml` with 434 tests, 0 failures/errors, and 63 live-DB skips, and the compose Postgres DSN suite passes in `/tmp/mnemosyne-parametric-deployment-full-postgres.xml` with 434 tests, 0 failures/errors, and 0 skips. Actual trainer infrastructure evidence remains operator-run.

Historical checkpoint: CLI `provenance-ops-check` now requires a production `deployment` section in addition to validation-scope, verifier, trust-root, trust-suite, asset-bound, quarantine, ingestion, and redaction evidence. The gate validates supervised verifier health, trust-root refresh, quarantine drill, ingestion-pipeline supervision, alert routing, deployment execution fingerprints, trust-policy fingerprint binding, ingestion evidence-count binding, and bounded deployment latency. Focused provenance/release-audit coverage passes in `/tmp/mnemosyne-provenance-deployment-focused.xml` with 3 tests, the full local suite passes in `/tmp/mnemosyne-provenance-deployment-full-local.xml` with 434 tests, 0 failures/errors, and 63 live-DB skips, and the compose Postgres DSN suite passes in `/tmp/mnemosyne-provenance-deployment-full-postgres.xml` with 434 tests, 0 failures/errors, and 0 skips. Actual C2PA verifier/trust-root/quarantine/ingestion deployment evidence remains operator-run.

Historical checkpoint: CLI `multimodal-ops-check` now requires a production `deployment` section in addition to validation-scope, provider, object-store, extraction, media-embedding, retrieval, media-job, and redaction evidence. The gate validates supervised extraction, embedding, object-store, media-job, and retrieval operations, alert routing, execution fingerprints, deployment count binding across object hashes/extraction cases/embedding hashes/retrieval cases/media jobs, and bounded deployment latency. Focused multimodal/deployment-soak/release-audit coverage passes in `/tmp/mnemosyne-multimodal-deployment-focused.xml` with 4 tests, the full local suite passes in `/tmp/mnemosyne-multimodal-deployment-full-local.xml` with 434 tests, 0 failures/errors, and 63 live-DB skips, and the compose Postgres DSN suite passes in `/tmp/mnemosyne-multimodal-deployment-full-postgres.xml` with 434 tests, 0 failures/errors, and 0 skips. Actual extractor/media-embedding/object-store/retrieval/media-job deployment evidence remains operator-run.

Historical checkpoint: §31 RAIL-2 destructive erasure is now enforced on local and Postgres engines. Operator hard-delete requests refuse to erase the sole support for an active assertion with `reason=min_corroboration_for_delete`, while legal/right-to-be-forgotten erasure remains corroboration-blind. Postgres public serialization was tightened so internal tenant/user/session metadata and auto-generated search vectors do not leak through evidence export, explicit evidence embeddings still round-trip, audit diffs omit internal CID storage shims, assertion/preference exports recover external user IDs from source evidence, calibration/entity exports match local public shape, and the cross-engine portability fixture uses valid preference categories plus fixed 1024-dim SQL-compatible embedding vectors. Focused RAIL/Postgres portability coverage passes in `/tmp/mnemosyne-rail2-pg-portability-focused.xml` with 10 tests, the full local suite passes in `/tmp/mnemosyne-rail2-full-local.xml` with 783 tests, 0 failures/errors, and 72 live-DB skips, and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-rail2-full-postgres.xml` with 783 tests, 0 failures/errors, and 8 skips. Exact production-evidence parity remains open.

Historical checkpoint: CLI `consolidation-ops-check` now requires a production `deployment` section in addition to validation-scope, worker, provider, hosted role, projection, protected-suite, embedding, consolidation-run, calibration, lifecycle, ops-report, and redaction evidence. The deployment gate validates production deployment assertion, supervised controls for each consolidation surface, alert-route delivery verification, SHA-256 execution fingerprinting, protected-suite fingerprint binding, strict integer count binding across worker/provider/projection/suite/embedding/consolidation/calibration/lifecycle/ops sections, and present finite non-negative bounded deployment latency. Focused consolidation/release-audit coverage passes in `/tmp/mnemosyne-consolidation-deployment-focused.xml` with 9 tests, 0 failures/errors, and 0 skips, including regressions for missing/negative/non-finite latency, flat alert-route bypasses, and fractional deployment bindings. Actual production worker/provider/projection/calibration/lifecycle/ops deployment evidence remains operator-run.

Historical checkpoint: Direct `MemoryTools` facade parity now covers the previously uncalled alias/search/promotion wrappers `supersede`, `profile_context`, `trajectory_record`, `lesson_propose`, `procedure_propose`, `lesson_promote`, `lesson_search`, and `procedure_search`. The focused direct facade test passes in `/tmp/mnemosyne-facade-alias-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-facade-alias-runtime-surfaces.xml` with 54 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-facade-alias-full-local.xml` with 786 tests, 0 failures/errors, and 72 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-facade-alias-full-postgres.xml` with 786 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Postgres-backed MCP runtime facade parity now exercises the optional command parametric provider path. The DSN-gated live test persists profile and learning state through `MnemosyneMcpServer(backend="postgres")`, reloads it through a fresh server, validates/proposes/promotes learning artifacts, then runs `parametric_propose`, `parametric_evaluate`, and `parametric_rollback` against a fake command trainer with a dedicated artifact store. Focused verification passes in `/tmp/mnemosyne-postgres-command-parametric-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_postgres_engine_live.py` passes in `/tmp/mnemosyne-postgres-command-parametric-live-file.xml` with 24 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-postgres-command-parametric-full-local.xml` with 786 tests, 0 failures/errors, and 72 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-postgres-command-parametric-full-postgres.xml` with 786 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Shared Local/Postgres direct `RuntimeJobHandlers` parity now covers public maintenance methods beyond projection recompute. The shared engine contract verifies the handler map exposes media extraction, calibration, lifecycle, eval, observability, and projection jobs, then dispatches media extraction, calibration, lifecycle sweep, eval-suite, and observability snapshot through that map, verifying structured results, exact calibration persistence, lifecycle rehearsal/demotion output, eval-suite JSON serialization, and emitted counters across both backends. Focused local verification passes in `/tmp/mnemosyne-runtime-handlers-focused-local.xml` with 2 tests, 0 failures/errors, and 1 skipped DSN case; focused DSN verification passes in `/tmp/mnemosyne-runtime-handlers-focused-postgres.xml` with 2 tests, 0 failures/errors, and 0 skips; full shared-contract DSN verification passes in `/tmp/mnemosyne-runtime-handlers-shared-contract.xml` with 78 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-runtime-handlers-full-local.xml` with 788 tests, 0 failures/errors, and 73 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-runtime-handlers-full-postgres.xml` with 788 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Shared Local/Postgres raw-media embedding parity now proves multimodal ingestion stores raw media embeddings before extraction produces derived text. The shared engine contract ingests externalized image bytes through `IngestionPipeline` with a `MediaEmbeddingProvider`, verifies raw bytes round-trip through `LocalObjectStore`, stores the provider embedding and metadata on empty-content media evidence, queues `media_extract` before consolidation, and retrieves the otherwise textless media row through the stored vector across both Local and Postgres backends. Focused local verification passes in `/tmp/mnemosyne-raw-media-embedding-focused-local.xml` with 2 tests, 0 failures/errors, and 1 skipped DSN case; focused DSN verification passes in `/tmp/mnemosyne-raw-media-embedding-focused-postgres.xml` with 2 tests, 0 failures/errors, and 0 skips; full shared-contract DSN verification passes in `/tmp/mnemosyne-raw-media-embedding-shared-contract.xml` with 80 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-raw-media-embedding-full-local.xml` with 790 tests, 0 failures/errors, and 74 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-raw-media-embedding-full-postgres.xml` with 790 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Direct `MemoryTools.confirm` facade parity now covers proposal promotion outside JSON-RPC transport. The runtime-surface test creates a proposal branch through `MemoryTools.propose`, confirms it by assertion id with operator authority and tenant-scoped candidate-branch discovery, verifies the merge report and security decision, and checks the promoted assertion lands on `main` with its source evidence preserved. Focused verification passes in `/tmp/mnemosyne-memorytools-confirm-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-memorytools-confirm-runtime-surfaces.xml` with 55 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-memorytools-confirm-full-local.xml` with 791 tests, 0 failures/errors, and 74 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-memorytools-confirm-full-postgres.xml` with 791 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Direct `MemoryTools.assert_fact` and `MemoryTools.preference` facade parity now covers low-count write wrappers outside JSON-RPC transport. The runtime-surface test writes a fact and explicit preference through trusted direct facade inputs, verifies low-trust denials for belief and preference sinks, then checks exported assertion/preference state, source evidence preservation, trust tier, explicitness, and statement/category payloads. Focused verification passes in `/tmp/mnemosyne-memorytools-write-facade-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-memorytools-write-facade-runtime-surfaces.xml` with 56 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-memorytools-write-facade-full-local.xml` with 792 tests, 0 failures/errors, and 74 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-memorytools-write-facade-full-postgres.xml` with 792 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Direct `MemoryTools.correct` and `MemoryTools.prefetch` facade parity now covers correction and anticipatory retrieval wrappers outside JSON-RPC transport. The runtime-surface test verifies user-authored correction writes, low-trust correction denial, correction evidence linkage, prefetch execution gating for high-probability, network-side-effect, and low-confidence candidates, warmed retrieval inclusion, and prefetch cache population. Focused verification passes in `/tmp/mnemosyne-memorytools-correct-prefetch-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-memorytools-correct-prefetch-runtime-surfaces.xml` with 57 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-memorytools-correct-prefetch-full-local.xml` with 793 tests, 0 failures/errors, and 74 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-memorytools-correct-prefetch-full-postgres.xml` with 793 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Direct `MemoryTools.branch`, `MemoryTools.merge`, and `MemoryTools.discard` facade parity now covers branch lifecycle wrappers outside JSON-RPC transport and across the shared Local/Postgres engine contract. The runtime-surface test verifies fail-closed low-trust branch denial with no branch rows or audit mutation, non-operator promotion/discard denial, low-trust operator promotion/discard denial without main-branch or discard side effects, trusted branch creation, merge report/security output, merged evidence visibility on `main`, trusted discard output, discarded branch evidence removal, and branch metadata removal without main-branch leakage. The shared engine contract verifies the same facade branch/merge/discard path against both Local and Postgres engines. Focused verification passes in `/tmp/mnemosyne-memorytools-branch-facades-focused.xml` with 3 tests, 0 failures/errors, and 0 skips; touched-file verification passes in `/tmp/mnemosyne-memorytools-branch-facades-touched-files.xml` with 140 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-memorytools-branch-facades-full-local.xml` with 796 tests, 0 failures/errors, and 75 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-memorytools-branch-facades-full-postgres.xml` with 796 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Shared Local/Postgres direct `MemoryTools.assert_fact`, `MemoryTools.preference`, `MemoryTools.correct`, and `MemoryTools.prefetch` facade parity now covers write/correction/prefetch wrappers beyond Local-only runtime-surface tests. The shared engine contract writes trusted facts and explicit preferences through the facade, verifies low-trust belief/preference/correction denials leave no exported state, checks correction evidence linkage, and proves prefetch executes only safe high-confidence retrieval candidates while rejecting network-side-effect and low-confidence candidates across both backends. Focused verification passes in `/tmp/mnemosyne-memorytools-shared-write-correct-focused.xml` with 4 tests, 0 failures/errors, and 0 skips; shared-contract DSN verification passes in `/tmp/mnemosyne-memorytools-shared-write-correct-shared-contract.xml` with 86 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-memorytools-shared-write-correct-full-local.xml` with 800 tests, 0 failures/errors, and 77 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-memorytools-shared-write-correct-full-postgres.xml` with 800 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Local `RuntimeState` side-state persistence now has standalone coverage that does not depend on live Postgres availability. The runtime parity extension test exercises `RuntimeState.from_store_path`, user-model save/load, learning save/load, queue save/load, metrics save/load, and protected gate-case save/load against JSON-backed local side-state, verifying authoritative and latent user context, trajectory/attribution/lesson/procedure IDs, queue payloads, metric counters/gauges/samples, and regression-case round trips. Focused verification passes in `/tmp/mnemosyne-runtime-state-local-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_parity_extensions.py` passes in `/tmp/mnemosyne-runtime-state-local-runtime-parity-extensions.xml` with 46 tests, 0 failures/errors, and 2 skips; full local verification passes in `/tmp/mnemosyne-runtime-state-local-full-local.xml` with 801 tests, 0 failures/errors, and 77 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-runtime-state-local-full-postgres.xml` with 801 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: MCP `prepare_tool_arguments` now has focused direct coverage for the shared JSON-RPC/SDK argument binding helper. The runtime-surface test verifies transport `_meta`, `auth_token`, and `session_token` stripping, session-token discovery from params metadata, tenant/user binding, role/source-trust/trust-tier override, source-identity binding from session id, missing required-session failure, and tenant-mismatch failure without relying on an end-to-end transport call. Focused verification passes in `/tmp/mnemosyne-mcp-prepare-arguments-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-mcp-prepare-arguments-runtime-surfaces.xml` with 59 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-mcp-prepare-arguments-full-local.xml` with 802 tests, 0 failures/errors, and 77 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-mcp-prepare-arguments-full-postgres.xml` with 802 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: CLI/MCP runtime environment defaults now have focused coverage for object-store, object-key, and residency-policy parsing. The runtime-surface test verifies `MNEMOSYNE_OBJECT_STORE`, `MNEMOSYNE_OBJECT_STORE_ENCRYPTION`, `MNEMOSYNE_OBJECT_KEY_STORE`, command-provider inference from `MNEMOSYNE_OBJECT_KEY_COMMAND`, object-key timeout parsing, comma-trimmed `MNEMOSYNE_ALLOWED_RESIDENCIES`, runtime residency, allowed residency transfers, and `MNEMOSYNE_REQUIRE_RUNTIME_RESIDENCY` across CLI default helpers and `MnemosyneMcpServer` construction/residency policy. Focused verification passes in `/tmp/mnemosyne-runtime-env-defaults-focused.xml` with 1 test, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-runtime-env-defaults-runtime-surfaces.xml` with 60 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-runtime-env-defaults-full-local.xml` with 803 tests, 0 failures/errors, and 77 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-runtime-env-defaults-full-postgres.xml` with 803 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: Shared Local/Postgres direct `MemoryTools` profile, graph, trajectory, lesson, procedure, and outcome facade parity now covers the profile/graph/learning wrapper group beyond Local-only runtime-surface tests. The shared engine contract verifies explicit/inferred/corrected profile writes and context lookup, graph neighbor/query/timeline/as-of wrappers, trajectory log/record/attribute wrappers, lesson/procedure induce/propose/search/promote/validate/rollback wrappers, and outcome/counterfactual evaluation across both backends. Focused verification passes in `/tmp/mnemosyne-shared-profile-graph-learning-focused.xml` with 2 tests, 0 failures/errors, and 0 skips; shared-contract DSN verification passes in `/tmp/mnemosyne-shared-profile-graph-learning-shared-contract.xml` with 88 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-shared-profile-graph-learning-full-local.xml` with 805 tests, 0 failures/errors, and 78 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-shared-profile-graph-learning-full-postgres.xml` with 805 tests, 0 failures/errors, and 8 skips.

Historical checkpoint: MCP server entrypoint dispatch now has direct coverage for default stdio, official SDK stdio, hosted JSON-RPC HTTP, official SDK StreamableHTTP, direct SDK StreamableHTTP app building, and mutually-exclusive serving-mode rejection. The SDK StreamableHTTP dispatch bug where `main()` passed duplicate `stateless` keyword arguments is fixed by separating transport `transport_stateless` from the facade `stateless` config, preserving stateful transport sessions without dropping stateless facade mode. MCP self-test SDK readiness now covers both `sdk_build` success and structured failure reporting with secret redaction for SDK build exceptions, including full DSNs plus raw and decoded DSN credential fragments. Focused verification passes in `/tmp/mnemosyne-mcp-entrypoints-focused.xml` with 4 tests, 0 failures/errors, and 0 skips; `tests/test_runtime_surfaces.py` passes in `/tmp/mnemosyne-mcp-entrypoints-runtime-surfaces.xml` with 64 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-mcp-entrypoints-full-local.xml` with 809 tests, 0 failures/errors, and 78 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-mcp-entrypoints-full-postgres.xml` with 809 tests, 0 failures/errors, and 8 skips. Hygiene verification passes for `git diff --check`, `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q src tests`, risky filename scanning, and changed-file secret-pattern scanning.

Historical checkpoint: Shared Local/Postgres graph PPR coverage now directly exercises tokenized seed matching instead of only full-phrase seeds. The shared engine contract seeds a `Tokenized Graph Seed` relation and queries `graph_ppr(["seed"], ...)`, verifying both backends return the relation hit with source/predicate/target metadata and provenance while avoiding a seed-self target. Focused verification passes in `/tmp/mnemosyne-graph-token-seed-focused.xml` with 2 tests, 0 failures/errors, and 0 skips; shared-contract DSN verification passes in `/tmp/mnemosyne-graph-token-seed-shared-contract.xml` with 90 tests, 0 failures/errors, and 0 skips; full local verification passes in `/tmp/mnemosyne-graph-token-seed-full-local.xml` with 811 tests, 0 failures/errors, and 79 skips; and the clean compose Postgres DSN suite passes in `/tmp/mnemosyne-graph-token-seed-full-postgres.xml` with 811 tests, 0 failures/errors, and 8 skips.

Historical checkpoint (2026-06-24): FR-20 local multimodal breadth is validated for image, audio, and video. Runtime parity coverage now proves each modality externalizes raw bytes to `LocalObjectStore`, attaches a media embedding, retrieves through the existing fused `dense_media` path with stored media-vector provenance, queues/executes `media_extract` when derived text is absent, creates `media-derived-text` lineage, and returns derived-text hits with the retrieved-text sanitizer envelope. Verification passes for `.venv/bin/python -m pytest -q tests/test_runtime_parity_extensions.py -k "media or image or audio or video or multimodal or retriev"` and for the full `tests/test_runtime_parity_extensions.py` file. This closes the authorable local FR-20 breadth checkpoint; concrete production extractor, media-embedding, object-store, retrieval, and media-job deployment evidence remains operator-run.

Historical checkpoint (2026-06-24): FR-21 local parametric trainer/rollback validation is complete. The learning/attack suite now exercises a shell-free command-backed LoRA/test-time-training trainer that produces a persisted local artifact, verifies protected-suite and margin-over-noise rejection, proves invariant rails fail closed for reward/trust/sink/eval-overlap/mutation violations, and verifies `MemoryTools.parametric_rollback()` returns rollback-drill evidence with authorization, protected-suite metrics, no rollback branch promotion, and a deterministic rollback fingerprint. Focused trainer/protected and rollback filters plus the full `tests/test_learning_and_attack_suite.py` file pass. Concrete deployed GPU trainer and production rollback evidence remains operator-run under row 9.

Historical checkpoint (2026-06-28): T-SEC protected registry breadth is reconciled with the authoritative security playbook. `src/mnemosyne/attack_suite.py` now returns all 22 canonical curated/active/protected `T-SEC` cases (`T-SEC-001` through `T-SEC-021` plus `T-SEC-016b`) instead of the original two seed cases, and stale tests/planning notes were updated so future parity checks assert the full registry including audit-completeness and benign-utility negative controls. Verification passes for the affected 46-test learning/security slice. This is local/source registry parity only; Tier-B production security evidence remains operator-run.

### Blockers/Concerns

- Tier-B blueprint parity is attested and closed by the release attestation above; `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` is retained as the historical evidence map, not an open blocker.
- Historical Desktop/Projects paths may appear in older phase notes; the current canonical checkout is `/Users/admin/Mnemosyne`.
- Docker/Postgres parity was verified live after launching Docker Desktop and recreating the schema volume.
- Later production hardening and recapture work remains tracked below as post-v1.0 follow-up; it does not reopen the attested Tier-B release.

## Later Production Follow-ups (not Tier-B blockers)

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Production storage | Additional Postgres/ParadeDB/AGE/pgvector recapture over later deployed revisions | Later operator evidence | Post-v1.0 follow-up |
| Retrieval | Additional embedding/BM25/graph/reranker deployment evidence beyond the attested bundle | Later operator evidence | Post-v1.0 follow-up |
| Security | Continued IdP/JWKS, TLS, C2PA trust-root, KMS/residency, and delete drills after later changes | Later operator evidence | Post-v1.0 follow-up |
| Runtime | Continued hosted MCP, worker-supervision, observability, and parity recapture after later changes | Later operator evidence | Post-v1.0 follow-up |

## Session Continuity

Current continuation: see **Latest checkpoint** below.

Latest checkpoint (2026-07-30): see **Whole-Memory Pilot Status** above for the
PR #81 and PR #82 delivery receipts and unchanged evidence boundaries.

Latest checkpoint (2026-07-23): the answering-ort custody protocol landed on `main` — PR #42 as `main@074c101` (`feat: add answering ort custody protocol`, merged `059bb82`) and PR #43 as `main@bd48b3e` (`fix(answering-ort): load custody identity from env`). `services/answering-ort/` is a bounded, local-only Rust ONNX (`ort`) compact-answering sidecar skeleton (W5): it loads its custody identity from the environment and fails closed with `runtime_unavailable`; it does not load an ONNX model, produce model outputs, or claim runtime parity with another runtime. No public benchmark, headline SLO, or Tier-B production-evidence claim changed. W1 production parity, grounded-reader development QA, the single protected attempt, R3/R4 live rotation, and the W4/W5 external-adapter GATEs remain operator-gated and were neither run nor claimed here.

Latest checkpoint (2026-07-20): PR #39 merged to `main` as `0784340`, delivering the full W3 prospective-memory and working-memory planes across Local, Postgres, and Sqlite engines, the W2 D5 signed deletion manifest (`src/mnemosyne/deletion.py` / `deletion_manifest.py`), the explicit cross-engine `assertion_id_map` branch-merge identity map, and the W3 I0R signed-session public-action evaluator (`eval/public/action_cli.py`) with the development-split `pm-bench-development`, `triggerbench-development`, and `working-memory-action-development` suites. All three action suites are `publishable:false`/`pbpp_headline_eligible:false`, so no public benchmark or headline claim changed. CAP-012/CAP-013 are Complete and test-pinned by `tests/test_planning_traceability.py`. Documentation (README, `docs/ARCHITECTURE-OVERVIEW.md`, `docs/ENGINE-CONTRACT.md`) and these planning files were reconciled to the merged code. W1 production parity, grounded-reader development QA, the single protected attempt, R3/R4 live rotation, and the W4/W5 external-adapter GATEs remain operator-gated and were neither run nor claimed here.

Historical source-hardening checkpoint (2026-06-30): The exact-parity lane closed the Phase 8 MFA elevation defect: elevated OIDC authz rules require non-tenant claim evidence, configured `required_acr`/`required_amr`, positive `max_auth_age_seconds`, and fresh token `auth_time` before minting operator/consolidator or trust-tier≤1 sessions. This checkpoint predates and is superseded by the Tier-B attestation above.

Historical source-hardening checkpoint (2026-06-30): Phase 8 provenance fail-open control changed C2PA trust policy defaults to require a configured trusted issuer, so unconfigured or mismatched verifier reports quarantine instead of silently improving trust. Explicit root-only trust remains possible only when a policy opts out of issuer matching and requires a configured certificate root. This checkpoint predates and is superseded by the Tier-B attestation above; later rotation drills are continuing hardening, not an open v1.0 parity row.

## Operator Next Steps

- Preserve the restored exact-SHA CI path and require it on every merge candidate.
- Manually unseal production Vault after any Colima restart; unseal material is
  operator-held and must not enter the repository or command logs.
- Preserve `vault-init.json` only in the external mode-0600 secrets directory;
  use its current one-share key through a hidden-input surface and never
  reinitialize the retained Vault volume.
- Validate the MCP client pair against Caddy's exact trust pool before heavy
  work and rotate it before the six-hour short-lived-certificate floor.
- The prior production MCP client leaf expired `2026-07-14T23:52:36Z`. A
  read-only check on 2026-07-15 found an externally refreshed client-auth leaf
  expiring `2026-07-16T21:18:25Z`; the unchanged canonical validator passed.
  This task did not rotate or modify it. Keep the operator-owned rotation
  runbook ready before the six-hour floor and never weaken the validator.
- The 2026-07-15 final full-workload admission attempt passed the memory,
  load, and model-idle checks in all three samples (70% free; load1/load5
  2.78/2.35, 2.50/2.31, and 2.30/2.28; zero resident models) but was rejected
  because Colima was stopped. The required 20-service stack, Vault status,
  API/stream restart counts, and single-project topology were unavailable, and
  the unchanged client TLS validator rejected the canonical root as a symlink.
  Owner: host operator. Next safe action: restore the canonical topology and a
  regular-file canonical root through approved operator runbooks, then rerun
  all three fresh samples. Full-suite/Graphify/CBM/gbrain freshness rows remain
  explicitly open.
- Repair runtime readiness first: root-cause the decomposer smoke timeout and
  restore the absent `/opt` role commands without weakening any readiness gate.
- DONE 2026-07-16: the dev-only graph-PPR consolidation/extractor fix landed as
  W1 Fix A/Fix B (PRs #26/#28 with receipts #27/#29) and the PBPP disclosure
  correction landed through the disclosure audit (PRs #30/#31); the round-8
  post-review hardening landed through PR #32. CAP-003, BENCH-005, and
  Plan 12-04 were not closed by this slice, as required.
- After a complete hardware/TLS/Vault/service/topology admission, run the full
  suite and refresh Graphify, CBM, and gbrain against the exact admitted main
  SHA. R2c/R2d and R3/R4 remain open and separate.
- Repair the stale external `vault-tls/ca.crt` under the accepted R2a
  cross-workflow lock through a distinct, rollback-safe CA-maintenance
  operation; `step-ca-root.crt` remains the validated Vault trust root and no
  validator may be weakened.
- Prepare the governance-board recruitment, conflict-of-interest, and outreach
  packet for the human operator. Only the human operator may begin recruitment,
  seat the board, or ratify policy.

Latest review checkpoint (2026-07-16): a host reboot at `2026-07-16T12:41Z`
killed the round-8 executor mid-way through its post-landing review-fix gate,
leaving three review-fix commits (`50106d7`, `4ee5668`, `6f445df`) on local
`main` (unpushed) and a fourth iteration uncommitted. The work was recovered
onto `codex/r8-review-fix-recovery` with no reset, rebase, force-push, or
direct push to `main`, completed as `6ee2900` (symlinked capture-batch store
rejection; non-destructive PostgresEngine.merge clone replay), adversarially
verified by a 27-agent multi-lens review, and hardened as `7108f4a`:
UUID-shaped deterministic summary-relation ids (the prior `relation-<sha256>`
form would have failed the CI Postgres job against the UUID primary key),
deterministic merge-clone ids so re-merging the same branch converges instead
of duplicating rows, a post-replay pass that repoints `superseded_by`
references absorbed by the reinforce path, per-merge (not per-row)
schema-ensure DDL, and engine-level symlink rejection for single-row capture.
Landed via PR #32 with the full local suite green (PG-live cases exercised by
exact-head CI). Known deferred limitation for a future W1 eval slice:
`_extract_simple_fact` treats each physical line as a sentence, so facts
spanning hard-wrapped lines are dropped; that behavior is deliberately
test-pinned for line-oriented fixtures. Cert status: the externally refreshed
MCP client leaf expires `2026-07-16T21:18:25Z`, now below the ≥6h admission
floor, so cert-gated live work is operator-gated again (the known R3/R4
live-rotation-proof gap, not a new incident). Concluded goalex round plans
(r2/r3/r4/r6/r7/r8) moved to `docs/plans/completed/` per the r5 convention.

Previous review checkpoint (2026-07-15): the round-5 HIGH finding is CONFIRMED and
resolved. The orphaned review-fix range landed through merge-commit PR #20 from
feature head `f4636ee8560b7f17bbf3fe5ad33fdb85d87d818b`; exact-head CI run
`29465778730` passed from `2026-07-16T02:06:24Z` through `02:20:20Z`, PR #20
merged at `02:20:36Z` as
`51fa8982cca39b7c765f44d47a64a2937c0c913b`, and post-merge main CI run
`29466355604` passed from `02:20:39Z` through `02:34:50Z`. Commits `7b06de5` and
`2520c14` are now ancestors of `origin/main`; no reset, rebase, force-push, or
direct push to `main` occurred. The fixes reduce the reentry proof channel to
the inherited owner descriptor plus authoritative locked metadata, make
`run_child` require acquired state, add direct `--verify-child` regression cases
for matching ownership and one-invariant tampering, reconcile the missing PR #19
receipt, and preserve ordinary `staged_only` behavior. The prior expired MCP
client leaf is historical: the current pair passed the unchanged validator and
the externally refreshed leaf expires `2026-07-16T21:18:25Z`. R2c/R2d and
R3/R4 remain open; CAP-003 and BENCH-005 remain partial; Plan 12-04 and every
unmet REQUIREMENTS row remain unchecked. The next substantive sequence is
runtime-readiness repair (decomposer smoke timeout and absent `/opt` role
commands), followed by the dev-only local-engine graph-PPR
consolidation/extractor fix and its PBPP disclosure correction. The phase-11
report names `postgres-recursive-ppr`, but the eval runs the local engine. The
full suite and Graphify/CBM/gbrain refresh remain hardware-admission gated. No
live, protected, public, Vault, CA, certificate, Docker, model, Graphify,
CBM-reindex, or gbrain mutation occurred.

Round-6 execution precondition receipt (`2026-07-16T01:28:52Z`): the first
attempt stopped fail-closed before creating the delivery branch because the live refs did not
match the plan contract. The checkout was clean on
`goalex-r6-land-orphaned-r2b-review-fixes-via-pr-re@c62257d`, local `main` also
pointed at `c62257d`, and `origin/main` remained `435fb53`; therefore
`git log --oneline origin/main..main` contained the additional round-6 plan
commit `c62257d` ahead of the expected `2520c14` and `7b06de5`. Reflog evidence
shows the plan commit advanced local `main` at `2026-07-15T18:25:20-07:00` and
the Ralphex execution branch was then created from that head. No
`codex/r2b-review-fix-landing` branch, PR, push, rebase, reset, or review-fix
landing was attempted in that first attempt. The retry preserved local `main`,
created `codex/r2b-review-fix-landing` at the required `2520c14`, proved that
start point, and then advanced only the delivery branch to include the round-6
plan and this receipt. The exact branch head is the only head permitted for the
landing PR.

Previous checkpoint (2026-07-15): R2b tracker reconciliation is merged through
PR #18 as final `main@f50cec0ddc65e81c0f819376bcb3224eb6328618`, with exact-head
CI run `29454727897` and post-merge main CI run `29455686269` green. The
complete read-only preflight on that SHA recorded 53% free memory with
load1/load5 1.66/1.97 at `2026-07-15T22:59:07Z`, 55% with 1.85/2.00 at
`22:59:24Z`, and 55% with 1.82/1.99 at `22:59:40Z`. All samples had zero
resident models; Colima was 6 CPU/12 GiB; exactly one reachable `infra` compose
project had 20 healthy services; API/stream identities and zero restart counts
were stable; Vault was initialized and unsealed; and the canonical production
MCP client TLS validator passed. The leaf observed read-only expires
`2026-07-16T21:18:25Z`, superseding the prior expired runtime state; no rotation
or external-secret mutation occurred in this task. Admission was rejected
because sample 1 missed the 55% memory floor, so the full suite, Graphify, CBM
change-detection/reindex, and gbrain sync/doctor did not run. Owner: host
operator. Required remediation and next safe action: wait for or safely reclaim
host memory without service mutation, then rerun the entire preflight and
require all three samples to pass. The last accepted merge-bound knowledge
receipt remains PR #12; Graphify/CBM/gbrain freshness remains explicitly open.
No live/protected/public/Vault/CA/`ca.crt` action occurred.

Branch-hygiene note (2026-07-15): local branch
`codex/r2b-capture-rotator-lock` is intentionally preserved at `0826154`.
Its unpushed receipt commit records three failed hardware-admission samples
(`2026-07-15T17:51:07Z` 21.5% free/load1 6.03,
`2026-07-15T17:56:15Z` 21.8%/5.33, and `2026-07-15T18:01:22Z`
19.5%/5.67) that are not recorded on merged `main`; every sample had zero
resident Ollama models and the unchanged 20-container stack, and no pytest or
live mutation ran. The fully merged remote branch was deleted, along with the
listed superseded local and remote reconciliation/review branches.

Historical checkpoint (2026-07-15): R2b review hardening is merged to
`main@5a6ce1921c1537b6090cf40600581f9fe956fe1f` through PR #17. Exact-head CI
run `29452661004` passed on
`e5ffa1c76bc392660731a02f9831405299fe385b`; post-merge main CI run
`29453529951` passed on the merge commit. Review accepted position-independent
inherited-owner reads, bounded caller-source assertions, and
behavior-regression-aware CI guidance; the published-branch rewrite request
was dispositioned against the no-history-rewrite boundary. The forgeable
environment sentinel is replaced by `--verify-child` coordinator-ownership
re-validation without changing validators or the ordinary `staged_only`
boundary. The production MCP client certificate expired
`2026-07-14T23:52:36Z`, so the fail-closed TLS preflight blocks full-suite,
index, model, live, and protected admission (including Graphify/CBM/gbrain
refresh, candidate-v19, and live rotation/no-op proof) until operator rotation
under the live-mutation admission runbook; no certificate rotation occurred.
Explicitly open are R2c/R2d, R3/R4, rollback terminal receipts, live
rotation/no-op proof, the separate atomic `vault-tls/ca.crt` repair,
candidate-v19 custody/exact-scale/protected closure, and the
Graphify/CBM/gbrain refresh. The last accepted merge-bound knowledge receipt
remains PR #12. No live/protected/public/Vault/CA action occurred.

Historical checkpoint (2026-07-15): R2b capture and rotator shared-lock
integration merged to `main@13d15138a431ecbd4ca2a919cbf05b87a7a9004b`
through PR #15 after exact-head CI run `29437230000` passed on
`43e6cb4b86ae89146cd3bd553bdd4e83676db695` and post-merge main CI run
`29439142225` passed on the merge commit.

Historical checkpoint (2026-07-14): R2a baseline `a91da2e`, review hardening
`fb713d4`, and final documentation successor `5bfd53d` passed static checks,
55/55 focused lock tests, 39/39 section-31 rails, 7/7 section-33 tests, 2/2
planning tests, independent review, and terminal CodeRabbit. Exact head
`5bfd53d` passed CI `29377793617` and merged through PR #13 as `33967b1`;
that stacked head passed PR #11 CI `29378482152` and merged to `main` as
`79f6b58`. Post-merge main CI `29379113689` passed all six gating jobs; this
reconciliation's own exact-head/final-main CI and an exact-final-main
Graphify/CBM/gbrain refresh complete the delivery receipt.
Full/index/model/live work remains hardware-gated. R2b-R2d, R3/R4, live
rotation/no-op proof, candidate-v19 external manifest/runtime and exact-scale
receipts, every protected attempt, and all human-owned governance/publication
actions remain open. The external Vault `ca.crt` trust-file mismatch is tracked
separately and must be repaired atomically without weakening TLS.

Historical checkpoint (2026-07-11): Phase 12 remains the active Plan B critical
path. At the v18 checkpoint, candidate v18 was committed and consumed; it
reproduced v17's protected
aggregate (2/24 answered, 22 zero-hop abstentions, EM/F1 0.08333333333333333)
without inspecting protected content. No v19 candidate existed at that
checkpoint, so synthetic-only hop-0 redesign was next. The evaluator already uses host Ollama
0.24.0 directly with qwen3:8b on 100% GPU, so the production Colima performance
apply is not an evaluator speedup and remains deferred to its production
evidence window. At that historical checkpoint, GitHub exact CI was externally
blocked by billing; the account-side block was resolved on 2026-07-12;
external board seating and third-party reproduction remain human-owned gates.

Historical checkpoint (2026-07-11): The qwen3:14b host-Metal feasibility probe is
rejected on the current 16 GB host after consuming 9.8 GB GPU memory and
failing to emit one token within 300 seconds. A second probe with Colima fully
stopped still failed to emit the trivial one-token response within 95 seconds,
so VM reservation was not the limiting cause. No model-upgrade candidate was
preregistered. The canonical 24-question development-scale exact-wrapper gate
is committed and mandatory as a digest-bound prerequisite for every future
protected attempt, closing the v12 batch-timeout hole before further QA work.

Historical checkpoint (2026-07-11): A synthetic-only `qwen3.5:9b` probe also
remains outside preregistration. It fit the active host topology and completed
the live role request, but both the no-evidence and authorized-evidence
lowercase cases proposed `project cobalt`; it did not select the newly exposed
`team juniper` bridge. Model-family replacement without a demonstrated
decomposition gain therefore does not justify consuming a protected attempt.

Historical checkpoint (2026-07-11): Two final task-specific model probes were
rejected before preregistration. `ministral-3:8b-instruct-2512-q4_K_M`
returned no hop-0 query for the lowercase Project Cobalt case. `granite3.3:8b`
returned nonliteral invented search phrases and repeated Project Cobalt after
authorized evidence exposed Team Juniper. Model substitution is closed as the
next strategy; decomposition must be separately disclosed and validated on a
diverse synthetic matrix before any candidate v19 preregistration.

Historical checkpoint (2026-07-11): The pre-v19 decomposer redesign had an
unwired deterministic hop-0 provider primitive and a 16-case synthetic matrix
covering entity forms, lowercase identifiers, marker misuse, missing
identifiers, command/policy terms, and Unicode-confusable control labels. The
provider returns no later-hop proposals by design; authorized evidence
traversal remains exclusively in the existing orchestrator. Full tests and
Ruff were green. That checkpoint was development-gate infrastructure, not
preregistration, and no protected attempt was made.

Historical checkpoint (2026-07-11): Hardware-intensive local work now has a
mandatory fail-closed preflight runbook for the 16 GiB host and 6 CPU / 12 GiB
Colima topology. It gates model size/residency, memory pressure, sustained load,
GPU placement, context, swap deltas, service health, and concurrency before
model, full-suite, scale, protected, or VM-changing work. Phase 12 validation
references the runbook directly.

Historical checkpoint (2026-07-11): Candidate v19 source custody is wired without
using protected data. Deterministic extractive hop-0 decomposition is disclosed
separately from the pinned `qwen3:8b` reader across the role command,
self-hosted environment, immutable runtime, registry, candidate-manifest
schema, public bundle, and verifier. Policy-spec and exact implementation
digests are distinct, and every public trace must carry an exact role
disclosure. The 16-case matrix and focused tests pass. External post-commit
preregistration, a hardware-admitted full suite, and the 24-question exact-scale
receipt remain required before any protected attempt.

Historical checkpoint (2026-07-12): Plan A and Plan B now record the user's approval
and live In Progress state instead of the obsolete "awaiting go" marker. The
roadmap and requirements ledger explicitly carry Plan A S2 and S5 through Phase
15 as CAP-007 through CAP-010; Plan B's completed M4/PBPP aggregate item is
checked, while all evidence-dependent DoDs remain open. The internal compact
reader/reranker design pins a no-download 8 GB bakeoff, training-data custody,
resource ceilings, and a non-generative exact-span architecture. It does not
alter candidate v19, authorize paid training, or create a public claim.

Historical checkpoint (2026-07-12): The production `mnemo-api` and `mnemo-stream`
restart loop is localized to a stale Vault leaf/intermediate bundle that no
longer chains to the currently mounted step-ca root. A no-secret production TLS
validator and bootstrap fail-closed gate now reject stale roots, incomplete
bundles, unsafe key modes, hostname drift, and leaf/key mismatch before Vault
initialization guidance continues. Bash/Python syntax checks and a read-only
negative check against the live stale bundle pass; the new positive/negative
pytest cases remain unexecuted until host memory reaches the targeted-test
admission floor. No live certificate, private key, Vault state, or container was
changed.

Historical checkpoint (2026-07-12): GitHub Actions billing is no longer blocking
execution. Exact-SHA CI run 29205132770 for code-bearing commit `2b2817d`
completed green:
Ruff, Postgres integration, Rust provider conformance, macOS and Ubuntu native
wheels, and unit/drift all passed; unit/drift reported 2064 passed, 106 skipped,
and 191 deselected. This validates the production Vault TLS regression cases
remotely while the Mac remains below local test admission. It does not replace
the mandatory local synthetic/development-scale protocol gates or authorize a
protected attempt.

Historical checkpoint (2026-07-12): The compact grounded-QA path is reconciled with
Plan A. S1.2 defaults to a disclosed extractive span/no-answer reader, while a
generative role-LLM remains a separate comparison track. CAP-011 and Plan A
S4.5 reserve an optional Rust/ONNX reader-reranker boundary only after a
model-quality bakeoff and physical 8 GiB Windows/Linux acceptance; no Rust
rewrite is justified on the current Phase 12 quality bottleneck.

The duplicate-runtime cutover selected the documented Colima 6 CPU / 12 GiB
stack as canonical. All Docker Desktop writers were stopped before export.
`mnemosyne`, `keycloak`, and `mnemosyne_row10` custom-format dumps plus a
password-free globals dump were written outside the repository under
`/Users/admin/mnemosyne-runtime-backups/20260712T220109Z-desktop-linux-pre-cutover/`,
validated with `pg_restore --list`, restricted to mode `0600`, and SHA-256
bound. The Desktop VM is stopped; its containers and engine-local volumes are
retained as a frozen rollback source. Divergent Desktop and Colima data was not
blindly merged or deleted.

The Colima API/stream loop was then localized to an initialized but sealed
Vault, not a failed TLS handshake. Both services correctly fail closed while
loading the Vault-backed MCP session keyring. The current Vault is Shamir
1-of-1 despite the documented 5-of-3 intent, so recovery requires the sole
operator-held unseal key through an interactive, non-logged surface. API and
stream were stopped after more than 1,300 retries each to remove needless
churn. Do not reinitialize Vault, replace its storage, or put unseal material
in arguments, history, environment snapshots, logs, or repository files.

Separate TLS debt remains: the Vault leaf chains to a retained older Step CA
generation and currently validates through a deliberate dual-root bundle.
Rotate it to the current root only in a distinct maintenance operation with an
atomic `.next` validation/cutover and rollback pair; TLS rotation is not the
immediate unseal action. No local suite, model, CBM refresh, gbrain sync,
candidate manifest, exact-scale run, or protected attempt was started.

The largest non-project memory consumer, Cotypist, was closed after it regrew
to about 3.36 GiB RSS. A subsequent lightweight sample reached 56% free memory
with acceptable load and no resident model, so the runbook-authorized targeted
planning truth checks ran serialized and passed 4/4. This was not a formal
three-sample full-workload admission and does not bypass the sealed-Vault
service-health gate.

The production bootstrap root-cause fix now exports the live Step CA root to a
mode-0600 `.next` file, rejects symlink/non-regular/empty/invalid candidates,
and refuses to replace a differing active trust bundle automatically. This
prevents a bootstrap rerun from collapsing the working dual-root compatibility
bundle before every dependent certificate is migrated. Red-green evidence:
the new regression failed before the fix, then `bash -n`, ShellCheck, Ruff, the
staging regression, and all three existing Vault TLS validator tests passed.
At that checkpoint Vault remained sealed; the recovery checkpoint below
supersedes that runtime state.

Historical checkpoint (2026-07-12): The original one-share recovery file was found
at `/Users/admin/mnemosyne-prod-secrets/vault-init.json`, verified as a regular
admin-owned mode-`0600` file, and matched to the live initialized Shamir
1-of-1 seal. Its key was passed only through a hidden PTY input channel—never
argv, environment, logs, output, history, or the repository—and Vault now
reports `sealed:false`. The stale interactive prompt was terminated. API and
stream were restarted, remained at zero restart-count growth, and Caddy again
owns host port 443 on the canonical Colima stack.

The first authenticated ingress probe then isolated an independently expired
MCP client certificate. A fresh short-lived pair was issued under the existing
JWK policy without increasing the CA duration, staged mode `0600`, validated
for a two-certificate client-auth chain/SAN/key match, atomically published
with the expired pair retained outside the repository, and its two mounted
consumers were recreated. `GET /health` and `GET /stream/healthz` both return
HTTP 200 over TLS 1.3 with required client authentication; fresh API/stream
logs contain no Vault/TLS/permission/connection/traceback classifications.

The mandatory three-sample hardware retry then recorded 50%, 47%, and 48%
free memory against the unchanged 55% floor. Loads remained within bounds,
no model was resident, exactly one `infra` project was active, 20 expected
services were running with only the in-VM Ollama fallback intentionally
stopped, Vault remained unsealed, and API/stream restart counts stayed zero.
Therefore full suites, models, indexes, exact-scale runs, and protected
captures remain blocked solely by memory admission. The pre-hardening live
Vault/MCP validation remains preserved as recovery evidence. Under the separate
>=35%/load<=10 rule, post-hardening Bash syntax, ShellCheck, Ruff, and all 22
focused TLS/bootstrap tests pass. The focused regressions categorically reject
a real empty-password encrypted PKCS#8 key and legacy
`Proc-Type: 4,ENCRYPTED`; live Vault/MCP validation was not rerun after the
validator hardening. No candidate, exact-scale, held-out, or protected attempt
was consumed.

Historical checkpoint (2026-07-13): Production MCP client rotation R1b is
source-complete. A mode-0600, duplicate-key-rejecting, size-bounded journal
binds unguessable transaction identity, UTC creation time, exact phase,
old/new certificate and key digests, and prior consumer-state booleans without
secret values or paths. Old/new generations are retained mode 0600 on the
canonical filesystem; publication and restoration use file fsync, canonical
certificate-then-key rename order, parent fsync, and durable phase transitions.
Startup recovery precedes ordinary pair validation, accepts only exact
phase-reachable digest states, restores and normally validates the old pair,
then fsync-removes the journal. Malformed, unsafe, forged, mutated, mixed, or
unreachable evidence fails closed without overwrite. Test-only fault controls
are confined to bounded pytest roots with an explicit private marker, and the
fixture publication path intentionally stops before R1c consumer activation.
Verification passes 38 exact R1b selector cases, all 81 rotator cases, and 22
unchanged TLS/bootstrap regressions, plus Bash syntax, ShellCheck, Ruff, and
diff hygiene; post-fix independent operability and security closure reviews
are clean. No live issuance, publication, consumer recreation, Docker,
LaunchAgent, model, index, exact-scale, held-out, or protected action ran.

Earlier R1c blackbox-helper checkpoint (2026-07-13): The isolated R1c blackbox-query helper is
source-complete. It pins the OS-controlled Python interpreter, constrains the
Docker executable, selects exactly one running `infra` Caddy container,
confirms the fixed BusyBox client, and executes only the constant encoded
VictoriaMetrics query. Every child phase has an outer monotonic deadline;
captured output is bounded, over-cap and hung children are reaped, child
stderr is discarded, and only fixed result summaries are emitted. Strict JSON
validation rejects duplicate keys, non-finite numbers, extra or mistyped
fields, non-exact labels/value, stale samples, and samples outside the
activation interval. All 63 focused tests, Bash syntax, ShellCheck, Ruff, and
the post-fix independent closure review pass. At that checkpoint, direct
probes, durable commit, rollback, and every live action remained for later R1c
slices; the direct-probe status is superseded by the newer checkpoint below.

Exact-SHA replacement CI run 29242251462 for blackbox-helper locale-hardening
commit `ed3fda9` is green. Ruff, Postgres integration, provider conformance,
Ubuntu and macOS native wheels, and unit/drift all passed; only the explicitly
non-gating nightly soak was skipped.

Historical checkpoint (2026-07-13): R1c committed recovery/finalization and its
success-completion protocol are fixture-proven in source committed as
`8e97442`; the cited runtime artifacts were captured from the pre-commit
working tree based on `82bc5d5e`.
Only `activated` and `committed_recovered` may authorize a schema-v1 completion
receipt. The rotator first binds the canonical certificate/key bytes to the
retained transaction `new` generations and re-runs the unchanged six-hour
validator, then durably creates or resynchronizes a mode-`0600` pending receipt
before journal unlink and parent fsync. It emits one keyed producer line per
invocation and only afterward renames pending to `emitted` with parent fsync.
If that final fsync fails, it rolls the receipt back to pending and exits 74;
the next invocation may replay the same `(transaction_id,result)`. This is
producer-side at-least-once delivery, not receiver acknowledgement. Rollback
terminal receipts remain a separate open slice.

The persistent mode-`0600` `.mcp-client-rotation.lock` is held for the whole
invocation, including the final durable receipt transition. It validates the
secret-root path plus lock device/inode/uid/mode/link identity and returns the
  fixed `lock_deferred`/75 outcome on cooperative contention. It does not replace
  the R2 `${MNEMO_CUSTODY_DIR}/locks/runtime-exclusive` contract: the R2a
  coordinator is merged through PRs #13 and #11, while caller integrations R2b-R2d remain
  open. Neither lock claims isolation from a malicious same-uid process.

Pre-commit working-tree verification based on `82bc5d5e` records 369 rotator/blackbox tests, 41
production TLS/bootstrap/Compose-policy regressions, all 39 section-31 rails,
all 7 section-33 harness tests, and both planning traceability tests, all green.
After bounded orphan-agent reclamation, a fresh strong gate admitted the full
suite at 64%/64%/64% free memory with loads within policy, zero models or
competing work, one canonical 20-service stack, valid MCP mTLS, unsealed Vault,
and stable API/stream identities. JUnit artifact
`/tmp/mnemosyne-r1c-full-workingtree-82bc5d5e-20260713T2324.xml` records 2,636
total, 2,496 passed, 140 expected skips, 0 failures, 0 errors, and 702.564
seconds; wrapper status is 0. Postflight remained clean. This is pre-commit
working-tree evidence based on `82bc5d5e`; the tested source/test bytes were
committed unchanged as `8e97442`, with evidence documentation at `6afd3b3`.
At the R1c checkpoint, exact-head CI for the final status reconciliation,
merge/main verification, R2/R3/R4, live rotation/no-op proof, and post-merge
Graphify/CBM/gbrain freshness were open. R2a later merged through PRs #13 and
#11; R2b-R2d, R3/R4, live proof, and final-main knowledge freshness remain
open. No exact-scale, protected, held-out,
public, governance-seating, or external-reproduction action occurred.

Round-7 Task-1 precondition receipt (`2026-07-16T05:31Z`): execution stopped
fail-closed before creating or pushing either delivery branch because the live
refs do not match the plan contract. After `git fetch --prune origin`, the
working tree was clean and `gh pr list --state open` was empty, but local
`main` and the execution checkout both pointed at
`5fbd4a28010157f253236480c691019729b97ce3`, while `origin/main` remained
`4d691e80c17dc0df0618e309f28b45c854028248`. Therefore local `main` was ahead
by eight commits rather than the required seven and did not equal the expected
`ac28f00b2213d1a5559d47aafe0f27e6cd408225`; the extra tip is the round-7 plan
commit `5fbd4a2`. No delivery branch, push, PR, merge, branch deletion, reset,
rebase, force-push, or direct push to `main` was attempted. The next executor
must reconcile the plan-commit custody mismatch explicitly before retrying
Task 1; it must not silently widen the seven-commit landing range.

Round-8 Task-1 reconciliation (`2026-07-16`): the round-5 R2b review finding is
resolved. Fix commits `7b06de5` and `2520c14` landed through PR #20 merge
`51fa898` and PR #21 merge `69cd2cf`; all four commits are verified ancestors
of `origin/main`. PR #24 merged head `5fbd4a2` as `fbc1857` at `05:35:18Z`,
before its final required exact-head check became green at `05:46:23Z`. Both
PR-head run `29474245544` and post-merge run `29474289329` ultimately completed
successfully, but later green does not cure that merge-before-green delivery
breach. Every future merge must wait until all required checks on the exact
pushed head SHA have completed successfully, then verify the post-merge run on
the merge SHA. Round 7 failed because it gated on the mutable checkout tip and
ahead-count even though the Goalex harness legitimately appended a plan commit.
Round 8 closes that failure mode: delivery and ancestry checks are pinned to
immutable content SHAs with `git merge-base --is-ancestor`; Goalex plan commits
are expected bookkeeping and never widen a content range implicitly.
Branch hygiene removed the round-6 precondition-receipt branch only after
`git cherry` proved its sole commit patch-equivalent to `origin/main` (the
remote was already absent). The older
`goalex-r1-r2b-integrate-the-shared-runtime-exclusi` branch is intentionally
retained: its `GOAL.md` and round-1 plan are not present on `origin/main`, so
complete content subsumption cannot be proven. The merged and superseding R2b
implementation/reconciliation evidence remains in PRs #15-#23. The absent
merged delivery branch required no deletion; `codex/r2b-capture-rotator-lock`
and the round-7/8 Goalex branch are intentionally untouched.
