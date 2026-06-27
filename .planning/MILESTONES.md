# Milestones

## v1.0 — Mnemosyne Local Scaffold Checkpoint

**Status:** superseded by strict blueprint parity continuation  
**Completed:** 2026-06-19  
**Audit:** `.planning/v1.0-MILESTONE-AUDIT.md`

This checkpoint verified the deterministic local scaffold and initial GitHub project. It does not satisfy the later exact 1:1 blueprint parity objective. Current controlling status: `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.

### Shipped

- Content-addressed evidence ledger with byte recall, deduplication, branch, merge, discard, and audit log.
- Bitemporal assertions, supersession, as-of queries, hybrid retrieval, explainability, correction, export, and forget propagation.
- TMS/AGM-style belief revision core with justifications, contradiction records, cascade invalidation, contested hypotheses, and conformal calibration.
- Six-category user model, latent advisory profile, fidelity lifecycle, spaced rehearsal, consolidation worker, and no-degradation guard.
- Trajectory logging, failure attribution, lesson and procedure induction, protected attack suite, counterfactual replay scoring, and promotion gate.
- Self-model store, policy variant proposal, tripwires, canary policy gate, latency benchmark, observability metrics, privacy classification, and live Postgres schema parity.

### Verification

- Earlier checkpoint: `python -m pytest` returned `39 passed`.
- Current strict-continuation suite: `.venv/bin/python -m pytest -q` collects 300 tests and returns 261 passing tests plus 39 skipped live-DB tests when `MNEMOSYNE_POSTGRES_DSN` is unset.
- Current live Postgres smoke: `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py tests/test_shared_engine_contract.py` returns 63 passing tests against the compose database and exercises tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR retrieval, explain channels/rails/provenance, hard-delete erasure, command-backed object key management, HTTP-configurable retrieval adapter wiring with strict provider response validation, manifest-backed CLI `provider-check` gates, command-backed parametric adapter proposal/rollback, the CLI `--backend postgres` path, stateless MCP ingestion over tenant-scoped durable Postgres queues, CLI file ingestion through the C2PA verifier adapter, async media extraction with derived evidence and graph lineage, shared local/Postgres parity, and gated consolidation promotion on Postgres.
- Current strict-continuation compile check: `.venv/bin/python -m compileall -q src tests` passes.
- `python -m mnemosyne.cli tools` returned the expected tool list.
- Docker Postgres initialized `sql/schema.sql` and reported 21 public tables.
- `mneme-mcp --self-test` locally preflights MCP initialize/list/schema/auth/session/read-only-call behavior without exposing secrets.
- `mneme-mcp --http` hosts the JSON-RPC MCP facade with health, bearer/session-header binding, body-size and malformed-request guards, and stateless restart durability coverage.
- CLI `idp-jwks-live-check` validates operator-supplied IdP tokens against live JWKS URLs/files with the same OIDC/authz-policy verifier as session exchange, while redacting the token, user id, session id, and raw `kid`.
- CLI `mcp-http-soak` validates hosted MCP health, stateless reporting, repeated `initialize`, `tools/list`, and read-only `tools/call` loops without echoing bearer/session tokens.
- CLI `mcp-streamable-http-soak` validates the official MCP SDK StreamableHTTP transport with repeated SDK initialize/list/read-only call loops and deployment-soak orchestration without echoing bearer/session tokens.
- CLI `mcp-sse-soak` validates legacy SSE stream handshakes, `text/event-stream` responses, `endpoint` event data, and secret-redacted event previews.
- CLI `deployment-soak` runs allowlisted deployment preflight manifests, including IdP authz rollout, TLS rotation-plan/lifecycle, worker, and ops dashboard checks, through shell-free subprocesses, supports a narrow non-secret `global_args` allowlist for runtime placement flags, parses child JSON reports, omits command arguments, and fails closed on required failures/timeouts/non-JSON/disallowed commands.
- CLI `release-audit` reads deployment-soak reports or evidence manifests, requires the production command profile and provider subchecks including TLS lifecycle evidence, rejects local retrieval/provider evidence when `forbid_local` is required, verifies redaction flags, requires production target plus operator attestation when production validation is requested, validates required command output sections instead of accepting placeholder `{ok: true}` evidence, supports fingerprint acknowledgement, and fails closed on incomplete release evidence.
- CLI `tls-cert-check` validates live TLS endpoint CA chains, hostname matching, TLS protocol floor, and certificate expiry thresholds.
- CLI `tls-rotation-plan-check` validates current/candidate certificate files for SAN hostname coverage, minimum validity windows, overlap days, optional issuer continuity, and hashed serial reporting before certificate swaps.
- CLI `tls-lifecycle-ops-check` validates production TLS lifecycle evidence for CA/ACME issuance, renewal execution, deployed serial/chain match, reload verification, non-local private-key custody, monitoring alerts, and raw key/cert/token/log redaction.
- Media extraction jobs now append searchable derived-text evidence and a `media-derived-text` relation from the source asset evidence to the derived text evidence, so multimodal derivations participate in graph lineage and forget propagation.
- CLI `provider-check` validates command-backed session-secret custody with a redacted signed-token round trip, key-count/active-key presence reporting, and fail-closed bad rotation handling.
- CLI `auth-ops-check` validates fingerprinted production auth evidence bundles for live IdP/JWKS validation and rotation, authz rollout fingerprints/simulations, command-backed session-secret rotation, TLS certificate and rotation controls, tenant RLS/session-binding cases, and raw token/claim/secret/private-key redaction.
- CLI `mcp-ops-check` validates fingerprinted hosted MCP runtime evidence bundles for JSON-RPC HTTP, official StreamableHTTP, optional legacy SSE, stateless loops, bearer/signed-session binding, latency thresholds, TLS/client-certificate controls, and raw token/request/response redaction.
- CLI `retrieval-ops-check` validates fingerprinted production Postgres retrieval evidence bundles for forbid-local provider manifests, non-local embedding/reranker providers, non-local lexical and graph backends, hashed lexical/vector/graph/reranker adapter probes, hashed tenant/query retrieval cases, calibration dataset fingerprints/metrics, bounded adapter latency, and raw query/document/embedding/result/stdout/stderr/command/env/credential redaction.
- CLI `hosted-llm-check` validates hosted HTTP/model endpoints for candidate extraction, summarization, and entity resolution with HTTPS-by-default URL policy, redacted authorization, role contracts, and stable fingerprints.
- CLI `provenance-trust-check` validates fingerprinted C2PA trust-root suites with asset-bound verifier reports, trusted issuer/root expectations, required case IDs, redacted verifier evidence, and release-audit profile coverage.
- CLI `provenance-ops-check` validates fingerprinted production C2PA operations bundles for production validation scope, non-local verifier identity, trusted issuer/root policy fingerprints, trust-root rotation/rejection controls, asset-bound trusted/quarantined cases, quarantine retrieval exclusion, Postgres ingestion tags, hashed evidence IDs, supervised verifier/trust-root/quarantine/ingestion deployment evidence, alert routing, and raw asset/manifest/verifier/certificate/credential redaction.
- CLI `calibration-tune` and queue-backed calibration jobs tune conformal thresholds from labeled eval datasets, report empirical coverage/false-accept/abstention metrics, and persist calibration only when sample-shape and safety gates pass.
- CLI `belief-revision-check` validates fingerprinted TMS/AGM belief revision suites for supersession, contradiction creation, cascade invalidation, and contested hypothesis probability surfacing.
- CLI `forgetting-policy-check` validates fingerprinted lifecycle policy suites for demotion, must-keep rehearsal, and gist-risk abstention expectations, and fails closed on missing required cases or expectation mismatches.
- CLI `policy-ops-check` validates fingerprinted shadow policy-ops bundles for invariant-rail-safe variants, external reward outcomes, cadence bounds, tripwires, and contextual-bandit recommendation evidence.
- CLI `privacy-ops-check` validates fingerprinted production privacy evidence bundles for non-local KMS lifecycle/rotation/shred, strict residency allow/deny enforcement, tombstone recompute safety, legal hard-delete safety, required cases, explicit key/object/subject/KMS-response redaction flags, and recursive raw-field rejection.
- CLI `parametric-trainer-check` validates fingerprinted production parametric trainer evidence bundles for non-local trainer providers, immutable artifact URI/hash proof, canonical protected-suite IDs/counts/source/tier coverage, gate candidate/artifact matching, passed protected cases, margin floors, HTTPS supervised deployment/canary/alert evidence, protected-suite/artifact/rollback fingerprint binding, rollback drill verification, runtime rail metadata, authorized rollback, mutation/reward/sink thresholds, and verified redaction.
- CLI `consolidation-ops-check` validates fingerprinted production consolidation role-pipeline bundles for production validation scope, Postgres-backed supervised worker cycles, forbid-local provider/hosted role checks, projection recompute with consolidation re-enqueue, protected-suite tier coverage, production embedding evidence, consolidator write authority, calibration/lifecycle/ops tripwire health, deployment supervision/alert/fingerprint/count binding with bounded latency, and raw prompt/request/response/evidence/embedding/CID/credential/tenant/user redaction.
- CLI `multimodal-ops-check` validates fingerprinted production multimodal retrieval bundles for production validation scope, forbid-local media extractor/embedder checks, encrypted external object storage, image/audio/video extraction cases, raw media embedding indexing, Postgres retrieval over stored media vectors and derived text, Postgres-backed `media_extract` jobs, supervised extraction/embedding/object-store/job/retrieval deployment evidence, alert routing, execution fingerprints, deployment count binding, and raw media/extractor/embedding/document/credential redaction.
- CLI `ops-dashboard-check` validates fingerprinted dashboard packages or hosted dashboard URLs plus optional production operations evidence for manifest shape, snapshot health, tripwire pass state, dashboard markers, tenant binding, HTTPS-by-default hosted access, refresh freshness, access control, alert delivery, and raw HTML/JSON/snapshot/token/user-data redaction.
- Production `release-audit` now requires `projection-recompute-once` evidence, making affected-subgraph recompute validation part of the default release handoff instead of an optional deployment-soak command.
- Command-backed lexical and graph retrieval adapters can route Postgres retrieval through shell-free production BM25/specialist graph services such as ParadeDB/AGE wrappers; CLI flags, provider manifests, provider-check probes, and PostgresEngine delegation are covered while native Postgres FTS/recursive-PPR remains the default.
- Shared Local/Postgres runtime-state parity now round-trips user model entries, latent profiles, learning trajectories/attributions/lessons/procedures, queued payloads, metrics, and protected gate cases.
- Live helper parity now directly verifies idempotent Postgres tenant/branch setup, Postgres queue schema/listing and tenant isolation, and `RuntimeState.from_store_path` sidecar path derivation.
- Shared Local/Postgres evidence-embedding parity now verifies missing-CID fail-closed behavior, persisted vector/export equality, and audit provenance for embedder writes.
- Runtime job handler parity now directly exercises media-extract skip handling, calibration, lifecycle sweep, eval suite, and observability snapshot methods in addition to queue-worker dispatch.
- Direct `MemoryTools` facade parity now exercises source-sync, profile, graph, learning, procedure, and outcome wrapper methods separately from JSON-RPC transport tests.
- Live Postgres queue failure-path parity now verifies worker exceptions persist retry then dead status, attempts, last_error, snapshots, and tenant-isolated lease/list behavior.
- Postgres runtime-state tenant isolation now verifies two tenants cannot cross-load user model, learning, queue, metrics, gate cases, or mirrored runtime table rows.
- CLI `eval` now reports the full seed-suite JSON contract through the real subprocess path, remains independent of engine backend selection, and serializes slotted `EvalOutcome` rows safely.
- CLI `worker-run` supervises bounded runtime-job cycles across queue handlers, emits cycle heartbeats/metrics, persists local queue progress, and can fail closed on dead jobs.
- CLI `worker-ops-check` validates production worker deployment evidence for external supervision, restart policy, heartbeat freshness, Postgres tenant-scoped queue health, required runtime job handlers, observability alerts, and raw env/DSN/payload/log redaction.
- CLI `session-exchange` and hosted HTTP `/session/exchange` validate OIDC/JWKS IdP tokens and mint bounded Mnemosyne signed-session tokens for the existing CLI/MCP authorization path; bounded JWKS loading, cache TTL refresh, refresh-on-unknown-`kid` rotation, fail-closed authz policy mapping, redacted `idp-authz-policy-check` validation/audit summaries, fingerprint-acknowledged `idp-authz-policy-rollout-check` diffs with claim-simulation change gates, command-backed session-secret custody for CLI/MCP signing and verification plus provider-check OIDC/JWKS/authz-policy/session-secret preflight, hosted HTTP TLS/client-certificate enforcement, TLS endpoint certificate-chain checks, TLS rotation-plan and lifecycle evidence validation, redacted live IdP/JWKS token validation, official SDK StreamableHTTP adapter validation, local hosted HTTP soak coverage, local legacy SSE handshake validation, manifest-driven deployment soak orchestration, local worker supervision, and worker deployment evidence validation are locally covered, while operator-run validation against production credentials/endpoints and production evidence-producing operations remains outside this superseded checkpoint.
- CLI `provider-check` fails command KMS providers that retain keys after claimed shred success.
- `gsd-sdk roadmap analyze` reported 6/6 original scaffold phases complete; strict blueprint parity remains reopened.

---

## vNext — Unified Cognitive Substrate (in progress)

**Status:** in progress — Phase 7 plans 01-04 gate-proven; P5 owner-checkpoint toggle retirement remains open
**Spec:** `docs/superpowers/specs/2026-06-27-unified-cognitive-substrate-design.md`
**Roadmap:** `.planning/ROADMAP.md` → Phase 7 · **Plans:** `.planning/phases/07-unified-cognitive-substrate/`

Turn the consciousness layer from a default-off shadow lane into a single, always-on, deeply-integrated cognitive substrate with **zero compromise to memory reliability**. Replaces the `shadow_only` / `enabled` toggles with one continuous, derived **Standing** signal `(groundedness ⟂ salience)`, runs the cognitive loop always-on via a tiered heartbeat, and lets autonomy grow only as corroboration earns it — all above the unbreakable §31-rails + immutable-ledger floor. This is the ADR-001 **Option E** destination and continues the G1→G4 program; it supersedes the *staging model* of the G4 shadow service, not the substrate, the rails, or the honesty charter.

### Relationship to v1.0
Post-v1.0. Does not block, and is not blocked by, the v1.0 strict-parity sign-off (the 10 Partial production-evidence rows). Phase 7 plans `07-01` through `07-04` are additive/gate-proven; `07-05` is the owner-checkpoint toggle-retirement step.

### Success Criteria (what must be TRUE)
- `Standing` is the single derived decision signal; P1 is byte-stable (zero divergence vs the boolean path).
- Standing is `(groundedness ⟂ salience)`; answer-authority depends on `groundedness` only; only **independent** external evidence raises groundedness; a permanent **evidence-dominance gap** holds (self < external, always).
- The cognitive loop is always-on via a tiered heartbeat with **hard** anti-rumination + proto-self; self-generation budget, answer-grounding floor, broadcast-as-data, and a fail-closed circuit-breaker hold; rumination ~ 0 and heartbeat compute bounded.
- Autonomy grows only as external corroboration earns it; an adversarial echo-chamber/sleeper corpus cannot raise a credential (Goodhart meta-rail).
- **No operational on/off toggle remains** (only the fail-closed floor fuse); every reliability guardrail (ECE, confabulation, poison-block, recall/nDCG, P95, 7 rails, 14 indicators) stays green; honesty charter intact (functional only; welfare flag stays; no phenomenal claim).

### Plans
- `07-01` … `07-05` in `.planning/phases/07-unified-cognitive-substrate/` (P1 byte-stable Standing → P5 retire toggles). Plans `07-01` through `07-04` are complete and gate-recorded; no plan ships on a guardrail regression. Toggle removal (P5) pauses for an owner checkpoint.

### Verification (planned gates)
- `eval/g0/preregistrations/g5-*.json` (bytestable-parity, continuous, always-on-heartbeat, earned-autonomy, toggle-retirement) — each must pass target-up / guardrails-not-down against `eval/g0/baselines/baseline-0.json`.
