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
- `src/mnemosyne/security.py` — trust tiers, capability mediation, fail-closed write authorization, and data-never-instruction sanitization.
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

`mneme-mcp` accepts the same object-store encryption, key-store, and allowed-residency flags for MCP ingestion.
By default it runs Mnemosyne's deterministic stdio JSON-RPC shim; pass `--sdk` to run through the official Python MCP SDK:

```bash
mneme-mcp --store .mnemosyne/mcp-store.json --sdk
```

C2PA verifier trust can be scoped through a JSON policy file:

```bash
python -m mnemosyne.cli \
  --c2pa-tool c2patool \
  --provenance-trust-policy ./c2pa-trust-policy.json \
  ingest --tenant tenant-a --user user-a --actor external --source-type camera \
  --file ./capture.bin --modality binary --trust-tier 5
```

Policy files can define global `trusted_issuers` or scoped `rules` such as `{"rules": [{"scope": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"}, "trusted_issuers": ["issuer-a"]}]}`. When scoped rules are present, no matching rule means the otherwise valid manifest is quarantined instead of trusted.

## Status

The repository has a verified local scaffold plus runtime parity extensions. Current checks:

- `.venv/bin/python -m pytest -q` returns 114 passing tests and 9 skipped live-DB tests with the optional MCP SDK extra installed.
- With Docker compose Postgres running, `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py` returns 9 passing live adapter tests covering tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, branch/discard, branch merge retrieval, bitemporal supersession, tenant isolation, tombstone and hard-delete forget modes, transitive derived-evidence erasure across assertions/preferences/relations, HTTP-configurable retrieval adapter wiring, CLI `--backend postgres`, durable Postgres queue leasing/drain, asset-bound CLI file ingestion through the C2PA verifier adapter, externalized payload derived-text retrieval, async media extraction, and gated consolidation promotion on Postgres.

Exact 1:1 blueprint parity is still in progress. The controlling status artifact is `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.
