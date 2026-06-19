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
- `src/mnemosyne/queue.py` — in-process queue with queued/running/retry/complete/dead lifecycle.
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
python -m pip install -e .
python -m pytest
python -m mnemosyne.cli tools
```

Example capture and retrieval:

```bash
python -m mnemosyne.cli capture --tenant tenant-a --user user-a --source-type chat --content "The preferred database is Postgres." --trust-tier 3
python -m mnemosyne.cli search --tenant tenant-a --query "preferred database"
```

Postgres-backed CLI usage:

```bash
docker compose up -d postgres
MNEMOSYNE_POSTGRES_DSN=postgresql://mnemosyne:mnemosyne-local-dev@127.0.0.1:54329/mnemosyne \
  python -m mnemosyne.cli --backend postgres search --tenant tenant-a --query "preferred database"
```

## Status

The repository has a verified local scaffold plus runtime parity extensions. Current checks:

- `.venv/bin/python -m pytest -q` returns 65 passing tests and 2 skipped live-DB tests.
- With Docker compose Postgres running, `MNEMOSYNE_POSTGRES_DSN=postgresql://... .venv/bin/python -m pytest -q tests/test_postgres_engine_live.py` returns 2 passing live adapter tests covering tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, and CLI `--backend postgres`.

Exact 1:1 blueprint parity is still in progress. The controlling status artifact is `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md`.
