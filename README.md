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
- `src/mnemosyne/security.py` — trust tiers, capability mediation, and data-never-instruction sanitization.
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

## Status

The repository has a tested Phase 0-1 foundation and executable scaffolding for Phases 2-5. The full blueprint remains the active target; later phases are not marked complete until their dedicated verification reports pass.
