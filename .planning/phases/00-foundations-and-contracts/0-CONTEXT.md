# Phase 0: Foundations and Contracts - Context

**Gathered:** 2026-06-19
**Status:** Verified

<domain>
## Phase Boundary

Phase 0 delivers the hard-to-retrofit foundation from the blueprint: engine contract, content-addressed evidence ledger, branches, tenant and source isolation, trust tiers, MCP/CLI skeleton, audit, and seed regression suite.

</domain>

<decisions>
## Implementation Decisions

### Storage
- **D-00-01:** Use a deterministic JSON-backed local engine for immediate local verification.
- **D-00-02:** Preserve the production PostgreSQL path in `sql/schema.sql`.

### Contract
- **D-00-03:** Use Python dataclasses and a `MemoryEngine` protocol matching the blueprint method names.
- **D-00-04:** Keep the MCP-compatible facade narrow: capture, search, deep_search, explain, correct, forget, export.

### Safety
- **D-00-05:** Treat retrieved memory as data with no instruction authority.
- **D-00-06:** Record every write or dedup no-op in `audit_log`.

</decisions>

<specifics>
## Specific Ideas

The foundation must prove byte-exact recall, idempotent deduplication, branch rollback, and seed regression execution before later phases build on it.

</specifics>

<canonical_refs>
## Canonical References

- `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` §28-33 — implementation stack, data model, component walkthroughs, operations, tests.
- `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` §34 — Phase 0 exit criteria.
- `.planning/REQUIREMENTS.md` — REQ-001, REQ-002, REQ-003, REQ-004, REQ-011.

</canonical_refs>

