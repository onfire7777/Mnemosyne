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
- `src/mnemosyne/mcp_server.py` — stdio JSON-RPC MCP runtime shim with `initialize`, `tools/list`, `tools/call`, and notification handling.
- `src/mnemosyne/postgres_engine.py` — PostgreSQL adapter for the canonical schema, including tenant RLS context, SQL FTS, pgvector assertion search, deterministic evidence dense fallback, recursive graph/PPR, and live smoke coverage for append/get/upsert/retrieve/as-of/branch/discard/forget/export.
- `src/mnemosyne/retrieval.py` — embedding/reranker adapter protocols, deterministic local fallbacks, and semantic-entropy signal.
- `src/mnemosyne/ingestion.py` — text/blob/multimodal ingestion pipeline with object externalization and signed-provenance decisions.
- `src/mnemosyne/storage.py` — local content-addressed object store.
- `src/mnemosyne/queue.py` — local and Postgres-backed queues with queued/running/retry/complete/dead lifecycle.
- `src/mnemosyne/prefetch.py` — anticipatory prefetch with predictability gate.
- `src/mnemosyne/parametric.py` — isolated parametric-tier artifact promotion boundary.
- `src/mnemosyne/runtime_state.py` — JSON-backed local runtime state for CLI/MCP user-profile and learning-loop objects.
- `src/mnemosyne/security.py` — trust tiers, capability mediation, fail-closed write authorization, signed CLI session identity, and data-never-instruction sanitization.
- `src/mnemosyne/lifecycle.py` — fidelity demotion and gist-risk abstention hooks.
- `src/mnemosyne/gate.py` — promotion gate with protected regression cases and branch rollback.
- `src/mnemosyne/consolidation.py` — warm-loop consolidation worker through the promotion gate.
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

Use `provider-check` with the same flags, or `provider-check --provider-manifest ./providers.json`, for deployment smoke checks. It returns structured JSON and exits nonzero if any required embedding, reranker, media-extractor, media-embedding, object-key/KMS, parametric-provider, or residency-policy contract fails.

Signed CLI session tokens can bind tenant/user identity and write authority before a subcommand executes:

```bash
MNEMOSYNE_SESSION_SECRET="$SESSION_SECRET" \
python -m mnemosyne.cli --session-token "$SIGNED_SESSION_TOKEN" \
  assert --tenant tenant-a --subject Mnemosyne --predicate has --object "session-bound writes"
```

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

`mneme-mcp` accepts the same object-store encryption, key-provider, allowed-residency, runtime queue, and parametric provider flags for MCP ingestion and runtime learning.
By default it runs Mnemosyne's deterministic stdio JSON-RPC shim; pass `--sdk` to run through the official Python MCP SDK. Use `--self-test` as a local deployment preflight before wiring stdio into a host:

```bash
mneme-mcp --store .mnemosyne/mcp-store.json --sdk
mneme-mcp --backend postgres --postgres-dsn "$MNEMOSYNE_POSTGRES_DSN" \
  --queue-backend postgres --stateless
mneme-mcp --store .mnemosyne/mcp-store.json \
  --auth-token "$MNEMOSYNE_MCP_TOKEN" \
  --session-secret "$MNEMOSYNE_MCP_SESSION_SECRET" \
  --require-session --self-test
```

The self-test exercises `initialize`, `tools/list`, strict MCP input schemas, auth-token rejection, signed-session enforcement, and a read-only tool call. It redacts configured secrets and does not replace hosted HTTP/SSE/TLS/IdP/stateless soak validation.

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
- `.venv/bin/python -m pytest -q` collects 231 tests and returns 206 passing tests plus 25 skipped live-DB tests when `MNEMOSYNE_POSTGRES_DSN` is unset.
- With Docker compose Postgres running, `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py tests/test_shared_engine_contract.py` returns 63 passing live/shared adapter tests covering tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, explain channels/rails/provenance, branch/discard, branch merge retrieval, bitemporal supersession, tenant isolation, tombstone and hard-delete forget modes, command-backed object key management, transitive derived-evidence erasure across assertions/preferences/relations, retrieval trust/sensitivity/quarantine filtering, deep graph tenant/branch isolation, hard-delete audit export, HTTP-configurable retrieval adapter wiring with strict provider response validation, CLI `--backend postgres`, fail-closed CLI `provider-check`, stateless MCP ingestion over tenant-scoped durable Postgres queues, shared local/Postgres evidence/retrieval/explain/branch/as-of/relation/preference/correction/forget-propagation contracts, durable Postgres queue leasing/drain, asset-bound CLI file ingestion through the C2PA verifier adapter, externalized payload derived-text retrieval, async media extraction, gated consolidation promotion on Postgres, and shared local/Postgres contract parity.

Exact 1:1 blueprint parity is still in progress. The controlling status artifact is `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.
