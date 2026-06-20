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
- Current strict-continuation suite: `.venv/bin/python -m pytest -q` collects 288 tests and returns 249 passing tests plus 39 skipped live-DB tests when `MNEMOSYNE_POSTGRES_DSN` is unset.
- Current live Postgres smoke: `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py tests/test_shared_engine_contract.py` returns 63 passing tests against the compose database and exercises tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR retrieval, explain channels/rails/provenance, hard-delete erasure, command-backed object key management, HTTP-configurable retrieval adapter wiring with strict provider response validation, manifest-backed CLI `provider-check` gates, command-backed parametric adapter proposal/rollback, the CLI `--backend postgres` path, stateless MCP ingestion over tenant-scoped durable Postgres queues, CLI file ingestion through the C2PA verifier adapter, async media extraction, shared local/Postgres parity, and gated consolidation promotion on Postgres.
- Current strict-continuation compile check: `.venv/bin/python -m compileall -q src tests` passes.
- `python -m mnemosyne.cli tools` returned the expected tool list.
- Docker Postgres initialized `sql/schema.sql` and reported 21 public tables.
- `mneme-mcp --self-test` locally preflights MCP initialize/list/schema/auth/session/read-only-call behavior without exposing secrets.
- `mneme-mcp --http` hosts the JSON-RPC MCP facade with health, bearer/session-header binding, body-size and malformed-request guards, and stateless restart durability coverage.
- CLI `session-exchange` and hosted HTTP `/session/exchange` validate OIDC/JWKS IdP tokens and mint bounded Mnemosyne signed-session tokens for the existing CLI/MCP authorization path; bounded JWKS loading, cache TTL refresh, refresh-on-unknown-`kid` rotation, fail-closed authz policy mapping, redacted `idp-authz-policy-check` validation/audit summaries, fingerprint-acknowledged `idp-authz-policy-rollout-check` diffs with claim-simulation change gates, command-backed session-secret custody for CLI/MCP signing and verification plus provider-check OIDC/JWKS/authz-policy preflight, hosted HTTP TLS/client-certificate enforcement, and official SDK StreamableHTTP adapter validation are locally covered, while real IdP/JWKS validation against live deployment credentials, production certificate lifecycle, legacy SSE validation, and soak testing remain outside this superseded checkpoint.
- CLI `provider-check` fails command KMS providers that retain keys after claimed shred success.
- `gsd-sdk roadmap analyze` reported 6/6 original scaffold phases complete; strict blueprint parity remains reopened.
