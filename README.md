# Mnemosyne Memory

Mnemosyne is a local-first memory compiler for AI agents. It implements the Mnemosyne v2 blueprint as a content-addressed evidence ledger plus rebuildable typed projections, bitemporal assertions, branchable memory, hybrid retrieval, provenance, confidence and abstention, capability-mediated writes, fidelity-tiered lifecycle controls, promotion gates, and shadow-mode self-optimization.

## Source Blueprint

The authoritative planning source is read-only on this machine:

- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md`
- `/Users/admin/Desktop/Mnemosyne/README.md`
- `/Users/admin/Desktop/Mnemosyne/earlier-versions/Mnemosyne-Recursive-Memory-System-Design.md`

The v2 blueprint controls implementation. The earlier design is lineage only unless v2 is silent.

## Current Build Surface

- `src/mnemosyne/engine.py` — local deterministic engine implementing the MemoryEngine contract.
- `src/mnemosyne/mcp_tools.py` — MCP-compatible tool facade: capture, search, deep_search, explain, correct, forget, export.
- `src/mnemosyne/mcp_server.py` — MCP runtime surfaces for stdio JSON-RPC, hosted HTTP JSON-RPC, official SDK stdio, and official SDK StreamableHTTP.
- `src/mnemosyne/postgres_engine.py` — PostgreSQL adapter for the canonical schema, including tenant RLS context, SQL FTS, pgvector assertion search, provider-backed evidence pgvector storage, raw-media pgvector retrieval, deterministic evidence dense fallback, recursive graph/PPR, and live smoke coverage for append/get/upsert/retrieve/provider-backed search/as-of/branch/discard/forget/export.
- `src/mnemosyne/retrieval.py` — embedding/reranker adapter protocols, deterministic local fallbacks, and semantic-entropy signal.
- `src/mnemosyne/ingestion.py` — text/blob/multimodal ingestion pipeline with object externalization, signed-provenance decisions, async extraction, and optional raw-media embedding.
- `src/mnemosyne/storage.py` — local content-addressed object store.
- `src/mnemosyne/queue.py` — local and Postgres-backed queues with queued/running/retry/complete/dead lifecycle.
- `src/mnemosyne/prefetch.py` — anticipatory prefetch with predictability gate.
- `src/mnemosyne/parametric.py` — isolated parametric-tier artifact promotion boundary.
- `src/mnemosyne/runtime_state.py` — JSON-backed local runtime state for CLI/MCP user-profile and learning-loop objects.
- `src/mnemosyne/security.py` — trust tiers, capability mediation, fail-closed write authorization, signed CLI session identity, and data-never-instruction sanitization.
- `src/mnemosyne/lifecycle.py` — fidelity demotion and gist-risk abstention hooks.
- `src/mnemosyne/gate.py` — promotion gate with protected regression cases and branch rollback.
- `src/mnemosyne/consolidation.py` — warm-loop consolidation worker through the promotion gate with deterministic and command-backed extraction, summarization, and entity resolution.
- `src/mnemosyne/self_optimization.py` — shadow-first policy variants constrained by immutable rails.
- `sql/schema.sql` — canonical PostgreSQL schema aligned with the blueprint DDL.
- `tests/` — regression tests for the hard invariants.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel pytest
python -m pip install -e '.[mcp]'
python -m pytest
python -m mnemosyne.cli tools
python -m mnemosyne.cli ops-report --tenant tenant-a --dashboard-html ./ops-dashboard.html
```

Example capture and retrieval:

```bash
python -m mnemosyne.cli capture --tenant tenant-a --user user-a --source-type chat --content "The preferred database is Postgres." --trust-tier 0
python -m mnemosyne.cli search --tenant tenant-a --query "preferred database"
```

Postgres-backed CLI usage:

```bash
docker compose up -d postgres
MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne \
  python -m mnemosyne.cli --backend postgres search --tenant tenant-a --query "preferred database"
```

Runtime jobs can use the same Postgres deployment for durable queue leasing:

```bash
python -m mnemosyne.cli --backend postgres --queue-backend postgres \
  --postgres-dsn "$MNEMOSYNE_POSTGRES_DSN" --queue-tenant tenant-a \
  queue-drain --limit 10
```

HTTP-compatible embedding/reranker providers can be selected from the same CLI:

```bash
python -m mnemosyne.cli --backend postgres \
  --embedding-provider http --embedding-url http://127.0.0.1:8000/embed \
  --reranker-provider http --reranker-url http://127.0.0.1:8000/rerank \
  search --tenant tenant-a --query "preferred database"
```

The live Postgres suite covers this CLI path with local fake HTTP providers: capture persists provider-generated 1024-dim pgvectors, search/explain report `http-embedding` and `http-reranker` adapters, reranker ordering is reflected in the final hits, and malformed embedding output fails closed instead of falling back to local hashing.

Use `provider-check` with the same flags, or `provider-check --provider-manifest ./providers.json`, for deployment smoke checks. It returns structured JSON and exits nonzero if any required embedding, reranker, media-extractor, media-embedding, object-key/KMS, parametric-provider, candidate-extractor, summarizer, entity-resolver, OIDC/JWKS, authz-policy, session-secret, or residency-policy contract fails. Use `hosted-llm-check --hosted-llm-manifest ./hosted-llm.json` to validate live hosted candidate-extractor, summarizer, and entity-resolver HTTP/model endpoints with HTTPS-by-default URL policy, redacted auth, role-specific contract checks, and stable fingerprints. Use `idp-jwks-live-check --idp-token "$OIDC_ID_TOKEN" --idp-jwks-url https://idp.example.com/.well-known/jwks.json --idp-issuer https://idp.example.com/ --idp-audience mnemosyne` for a redacted live-token/JWKS validation report before exposing hosted auth. Use `tls-cert-check --url https://mnemosyne.example.com --min-days-valid 30` for CA-chain, hostname, TLS-version, and certificate-expiry gates. Use `tls-rotation-plan-check --current-cert-file ./current.pem --candidate-cert-file ./candidate.pem --hostname mnemosyne.example.com --min-overlap-days 7` before swapping certificate material. Use `mcp-http-soak --base-url https://mnemosyne.example.com --auth-token "$MNEMOSYNE_MCP_TOKEN" --require-stateless` for bounded hosted JSON-RPC MCP health, stateless, `initialize`, `tools/list`, and read-only `tools/call` loops. Use `mcp-streamable-http-soak --base-url https://mnemosyne.example.com --auth-token "$MNEMOSYNE_MCP_TOKEN"` for the official MCP SDK StreamableHTTP transport. Use `mcp-sse-soak --base-url https://mnemosyne-legacy.example.com --auth-token "$MNEMOSYNE_MCP_TOKEN"` for legacy SSE stream handshakes, `endpoint` event detection, and secret-redacted event previews. Use `ops-report --tenant tenant-a --dashboard-html ./ops-dashboard.html` for a static observability dashboard with a top-level tripwire `ok` gate. Use `ops-dashboard-check --dashboard-package-dir ./dashboard-package --expected-tenant tenant-a` to validate dashboard packages or hosted dashboard URLs for manifest shape, snapshot health, tripwire pass state, dashboard markers, tenant binding, HTTPS-by-default hosted access, raw HTML/JSON redaction, and stable fingerprints. Use `calibration-tune --tenant tenant-a --dataset ./calibration.json --min-examples 100 --min-correct 50 --min-incorrect 50` to tune conformal abstention from labeled production eval rows and fail closed on insufficient sample shape, low empirical coverage, or high false-accept rate. Use `belief-revision-check --cases ./belief-revision.json --require-case supersession-contradiction --require-case cascade-invalidation --require-case contested-hypotheses` to validate TMS/AGM supersession, contradiction, cascade invalidation, and contested-hypothesis probability cases with a stable fingerprint. Use `forgetting-policy-check --cases ./forgetting-policy.json --require-case demote-low-utility --require-case must-keep-rehearsal --require-case gist-risk-abstention` to validate demotion, rehearsal, and gist-risk abstention cases with a stable fingerprint. Use `policy-ops-check --bundle ./policy-ops.json --require-variant stable --require-variant recall` to validate shadow-only policy variants, invariant rails, external-reward outcomes, cadence limits, tripwires, and contextual-bandit recommendation fingerprints. Use `provenance-trust-check --suite ./provenance-trust.json --require-case asset-bound` to validate C2PA trust-root suites with asset-bound verifier reports, trusted issuer/root expectations, redacted verifier evidence, and stable fingerprints. Use `deployment-soak --soak-manifest ./deployment-soak.json --evidence-dir ./soak-evidence` to run an allowlisted JSON manifest of deployment preflights without shell execution or secret-bearing argument echo; each check may include non-secret `global_args` such as `--queue-backend` and `--queue-tenant` before the child command. Use `release-audit --evidence-manifest ./soak-evidence/manifest.json --require-production-validated` as the second-stage release gate: it requires the production command profile, provider subchecks, non-local retrieval/provider evidence, redaction flags, and an optional expected fingerprint acknowledgement before marking a release bundle ready. Use `gate-suite-check --min-protected 1 --expected-fingerprint "$EXPECTED_SUITE_SHA256"` to verify protected-suite deployment shape and change-control acknowledgement. Use `--queue-backend postgres --queue-tenant tenant-a worker-run --max-cycles 20 --idle-exit-after 2 --fail-on-dead` for bounded supervised runtime-job cycles with JSON heartbeat and fail-closed dead-job gating. Use `projection-recompute-once --tenant tenant-a --cid <changed-cid>` to compute the affected evidence/projection set and queue consolidation only for surviving affected evidence.

Use `privacy-ops-check --bundle ./privacy-ops.json --require-case residency-deny --require-case legal-delete` to validate production privacy evidence bundles for non-local KMS lifecycle/rotation/shred, strict residency allow/deny enforcement, tombstone recompute safety, legal hard-delete safety, redacted key/object/subject evidence, and stable fingerprints.

Signed CLI session tokens can bind tenant/user identity and write authority before a subcommand executes:

```bash
MNEMOSYNE_SESSION_SECRET="$SESSION_SECRET" \
python -m mnemosyne.cli --session-token "$SIGNED_SESSION_TOKEN" \
  assert --tenant tenant-a --subject Mnemosyne --predicate has --object "session-bound writes"
```

For deployment secret custody, `--session-secret-command` / `MNEMOSYNE_SESSION_SECRET_COMMAND` invokes a shell-free adapter with a `get_session_secret` action and JSON stdin. The adapter returns either `{"secret":"..."}` or `{"keyring":{"kid":"..."}, "active_key_id":"kid"}`; Mnemosyne uses the material for signing or verification without echoing it in command output. `provider-check` can validate the same adapter from flags or a manifest `session_secret` provider block by proving a redacted signed-session round trip.

`session-exchange` validates an external OIDC/JWT identity token against a configured JWKS and mints the bounded Mnemosyne signed-session token used by CLI and MCP authorization:

```bash
python -m mnemosyne.cli --session-secret-command "$SESSION_SECRET_COMMAND" session-exchange \
  --idp-token "$OIDC_ID_TOKEN" \
  --idp-jwks-url https://idp.example.com/.well-known/jwks.json \
  --idp-issuer https://idp.example.com/ \
  --idp-audience mnemosyne \
  --idp-authz-policy-file ./mnemosyne-idp-authz-policy.json
```

By default the verifier requires issuer, audience, expiration, and the tenant/user/role/trust claims `tenant_id`, `sub`, `mnemosyne_role`, and `mnemosyne_source_trust_tier`. Deployments can instead pass `--idp-authz-policy` or `--idp-authz-policy-file` to map verified IdP client, tenant, and claim rules to Mnemosyne roles (`reader`, `agent`, `consolidator`, `operator`) plus a source trust tier. Policy mode requires `allowed_client_ids`, rejects malformed or unknown policy fields, denies missing and ambiguous rule matches, rejects invalid roles such as `writer`, and never falls back to raw IdP role/trust claims when a policy is configured. JWKS input can be inline JSON, a file, or HTTPS URL; insecure JWKS URLs are rejected unless explicitly allowed for local testing. File and URL JWKS sources support bounded reads, cache TTL refresh, and refresh-on-unknown-`kid` rotation through `--idp-jwks-max-bytes`, `--idp-jwks-cache-ttl-seconds`, and `--idp-disable-refresh-on-unknown-kid`.

`idp-jwks-live-check` uses the same OIDC/JWKS/authz-policy verifier as `session-exchange`, but it does not mint or print a Mnemosyne session token. It emits a deployment preflight report with JWKS source/key count, token algorithm and hashed `kid`, redacted user identity, role, trust tier, policy presence, and fail-closed errors without echoing the IdP token.

Validate a deployment authz policy without exchanging an IdP token:

```bash
python -m mnemosyne.cli idp-authz-policy-check \
  --idp-authz-policy-file ./mnemosyne-idp-authz-policy.json
```

The check emits a bounded summary with a stable policy fingerprint, client/rule counts, role and trust-tier coverage, and matcher field names only; it does not print client IDs, tenant IDs, group values, scopes, or tokens. Use the fingerprint for rollout/change-control acknowledgement:

```bash
python -m mnemosyne.cli idp-authz-policy-rollout-check \
  --current-idp-authz-policy-file ./current-idp-authz-policy.json \
  --candidate-idp-authz-policy-file ./candidate-idp-authz-policy.json \
  --expected-current-fingerprint "$CURRENT_POLICY_SHA256" \
  --expected-candidate-fingerprint "$CANDIDATE_POLICY_SHA256" \
  --simulation-file ./idp-claim-simulations.json
```

The rollout check compares redacted summaries, reports secret-free diffs, and fails closed if any claim simulation changes authorization unless `--allow-simulation-changes` is supplied.

Encrypted local object storage is available for crypto-shred legal erasure:

```bash
python -m mnemosyne.cli \
  --object-store .mnemosyne/objects \
  --object-store-encryption aesgcm \
  --object-key-store .mnemosyne/object-keys.json \
  --allowed-residency local \
  ingest --tenant tenant-a --user user-a --actor user --source-type upload \
  --file ./private-capture.bin --modality binary --trust-tier 0
```

For production key custody, use `--object-key-provider command --object-key-command "<kms-wrapper>"`. Mnemosyne invokes the command without a shell, passes JSON on stdin, and expects JSON on stdout for `get_or_create_key`, `get_key`, `has_key`, and `shred_key`.

For isolated parametric adapter custody, use `--parametric-provider command --parametric-command "<trainer-wrapper>"`. Mnemosyne invokes the command without a shell, passes JSON on stdin for `propose` and `rollback`, requires operator-grade role/trust authorization before trainer calls, enforces local mutation-rate/reward/sink/gate rails, and persists provider metrics/payloads with rollback metadata.

For model-backed consolidation, use `--candidate-extractor-provider command --candidate-extractor-command "<extractor-wrapper>"` and `--summarizer-provider command --summarizer-command "<summarizer-wrapper>"`. Mnemosyne invokes each command without a shell. The extractor receives `{"tenant_id":"...","payload":{...},"evidence":[...]}` and must return `{"candidates":[...]}` rows containing `signature`, `query`, `candidate_subject`, `candidate_predicate`, and `candidate_object`; malformed or empty required fields fail closed before promotion. The summarizer receives `{"tenant_id":"...","evidence":[...]}` and must return a non-empty `summary`. Neither provider can bypass data-only/quarantine skips or the protected promotion gate.

For production entity resolution, use `--entity-resolver-provider command --entity-resolver-command "<resolver-wrapper>"`. Mnemosyne invokes the resolver without a shell after consolidation candidate extraction and passes `{"tenant_id":"...","candidates":[...]}` on stdin. The resolver must return a JSON object with a `candidates` array containing one row per input candidate: `{"signature":"...","entity_key":"..."}`. It may also return `entities` rows with `key`, `label`, `aliases`, and `candidate_signatures`. Missing, duplicate, unknown, or keyless candidate mappings fail closed, and successful promotions persist the resolver-provided `entity_key` into the tenant entity registry. Provider manifests can require this check with `required_checks: ["entity_resolver"]` and a `providers.entity_resolver` block containing `provider: "command"` plus `command`.

`mneme-mcp` accepts the same object-store encryption, key-provider, allowed-residency, runtime queue, and parametric provider flags for MCP ingestion and runtime learning.
By default it runs Mnemosyne's deterministic stdio JSON-RPC shim; pass `--sdk` to run stdio through the official Python MCP SDK, or `--sdk-streamable-http` for the official SDK StreamableHTTP transport. Use `--self-test` as a local deployment preflight before wiring stdio into a host, or `--http` for Mnemosyne's hosted HTTP JSON-RPC transport:

```bash
mneme-mcp --store .mnemosyne/mcp-store.json --sdk
mneme-mcp --store .mnemosyne/mcp-store.json --sdk-streamable-http \
  --http-host 127.0.0.1 --http-port 8765
mneme-mcp --backend postgres --postgres-dsn "$MNEMOSYNE_POSTGRES_DSN" \
  --queue-backend postgres --stateless
mneme-mcp --store .mnemosyne/mcp-store.json \
  --auth-token "$MNEMOSYNE_MCP_TOKEN" \
  --session-secret-command "$MNEMOSYNE_MCP_SESSION_SECRET_COMMAND" \
  --require-session --self-test
mneme-mcp --http --http-host 127.0.0.1 --http-port 8765 \
  --auth-token "$MNEMOSYNE_MCP_TOKEN" \
  --session-secret-command "$MNEMOSYNE_MCP_SESSION_SECRET_COMMAND" \
  --require-session \
  --tls-cert-file ./certs/server.pem \
  --tls-key-file ./certs/server-key.pem \
  --tls-client-ca-file ./certs/client-ca.pem \
  --tls-require-client-cert \
  --idp-jwks-url https://idp.example.com/.well-known/jwks.json \
  --idp-issuer https://idp.example.com/ \
  --idp-audience mnemosyne
```

The self-test exercises `initialize`, `tools/list`, strict MCP input schemas, auth-token rejection, signed-session enforcement, and a read-only tool call. It redacts configured secrets and does not replace operator-run production IdP/JWKS checks, certificate issuance/renewal execution, deployed secret distribution, or operator-run `deployment-soak` evidence.
`mneme-mcp` accepts the same command-backed session custody contract through `--session-secret-command` / `MNEMOSYNE_MCP_SESSION_SECRET_COMMAND`.
The official SDK StreamableHTTP transport serves the MCP endpoint at `/mcp` and liveness metadata at `/healthz` by default, uses stateless SDK sessions unless `--sdk-streamable-stateful` is set, and can be relocated with `--sdk-streamable-http-path` / `--sdk-streamable-health-path`. Local runtime tests verify SDK-client `initialize`, `tools/list`, and `tools/call` over the in-process StreamableHTTP ASGI surface; production network/soak validation requires operator-run endpoint evidence.
The hosted HTTP transport serves liveness metadata at `/healthz` and JSON-RPC at `/mcp`, reusing the same tool schema, auth-token, signed-session, stateless, queue, and backend enforcement as stdio. Pass bearer auth in `Authorization` and signed sessions in `X-Mnemosyne-Session-Token`, or through JSON-RPC `_meta` for non-HTTP transports. `--tls-cert-file` and `--tls-key-file` enable HTTPS; `--tls-client-ca-file --tls-require-client-cert` enforces client certificate identity. When OIDC settings are configured, `POST /session/exchange` accepts `{"idp_token":"..."}` with the static bearer token and returns a Mnemosyne signed session; hosted JWKS file/URL sources support the same bounded read, TTL refresh, unknown-`kid` refresh controls, and optional authz policy mapping with `MNEMOSYNE_MCP_IDP_*` environment variables. `/healthz` reports only whether TLS, client-certificate enforcement, session exchange, and authz policy are configured, not policy contents. Deployments should still pass `--self-test`, `idp-authz-policy-rollout-check`, `idp-jwks-live-check`, and `tls-rotation-plan-check` before exposure; HTTP mode is not a substitute for certificate issuance/renewal execution, deployed secret distribution, or operator-run `mcp-sse-soak` against deployed legacy SSE URLs.
The `mcp-http-soak` CLI command validates a hosted HTTP JSON-RPC endpoint without echoing bearer or session tokens. It checks `/healthz`, optional stateless requirements, and repeated SDK-style `initialize`, `tools/list`, and configurable read-only `tools/call` loops; local tests run it against the real in-process hosted server, while production endpoint `deployment-soak` runs remain operator-supplied.
The `mcp-sse-soak` CLI command validates a legacy MCP SSE endpoint without echoing bearer/session tokens or endpoint query secrets. It opens bounded `text/event-stream` connections, requires an `endpoint` event with data by default, and fails closed on non-SSE endpoints, missing expected events, or missing endpoint data.
The `deployment-soak` CLI command runs an allowlisted deployment manifest of existing preflight commands (`provider-check`, `idp-jwks-live-check`, `tls-cert-check`, `mcp-http-soak`, `mcp-sse-soak`, `worker-run`) through shell-free subprocesses. It parses child JSON reports, omits command arguments from output, reports required vs optional failures, and fails closed when required checks fail, time out, emit non-JSON, or request a disallowed command.
The `tls-rotation-plan-check` CLI command validates local current/candidate certificate files before deployment. It verifies SAN hostname coverage on both certs, current and candidate minimum validity windows, overlap days, issuer continuity when required, and reports hashed serials instead of raw serial numbers.

C2PA verifier trust can be scoped through a JSON policy file:

```bash
python -m mnemosyne.cli \
  --c2pa-tool c2patool \
  --provenance-trust-policy ./c2pa-trust-policy.json \
  ingest --tenant tenant-a --user user-a --actor external --source-type camera \
  --file ./capture.bin --modality binary --trust-tier 5
```

Policy files can define global `trusted_issuers`, `trusted_roots`, or scoped `rules` such as `{"rules": [{"scope": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"}, "trusted_issuers": ["issuer-a"], "trusted_roots": ["<sha256-root-fingerprint>"]}]}`. When scoped rules are present, no matching rule means the otherwise valid manifest is quarantined instead of trusted.

## Status

The repository has a verified local scaffold plus runtime parity extensions. Current checks:

- `.venv/bin/python -m compileall -q src tests` passes.
- `.venv/bin/python -m pytest -q` collects 313 tests and returns 271 passing tests plus 42 skipped live-DB tests when `MNEMOSYNE_POSTGRES_DSN` is unset.
- With Docker compose Postgres running, `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py tests/test_shared_engine_contract.py` returns 66 passing live/shared adapter tests covering tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, explain channels/rails/provenance, branch/discard, branch merge retrieval, bitemporal supersession, tenant isolation, tombstone and hard-delete forget modes, command-backed object key management, transitive derived-evidence erasure across assertions/preferences/relations, retrieval trust/sensitivity/quarantine filtering, deep graph tenant/branch isolation, hard-delete audit export, HTTP-configurable retrieval adapter wiring with strict provider response validation, provider-backed CLI/Postgres evidence pgvector storage, HTTP reranker final-hit ordering, fail-closed malformed provider output, command-backed raw-media embedding storage and vector retrieval, CLI `--backend postgres`, fail-closed CLI `provider-check`, stateless MCP ingestion over tenant-scoped durable Postgres queues, shared local/Postgres evidence/retrieval/explain/branch/as-of/relation/preference/correction/forget-propagation contracts, durable Postgres queue leasing/drain, bounded `worker-run` supervision, asset-bound CLI file ingestion through the C2PA verifier adapter, externalized payload derived-text retrieval, async media extraction with graph lineage, gated consolidation promotion on Postgres, and shared local/Postgres contract parity.

Exact 1:1 blueprint parity is still in progress. The controlling status artifact is `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.
