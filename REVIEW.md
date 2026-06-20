---
phase: ad-hoc-runtime-surfaces
reviewed: 2026-06-19T21:23:12Z
depth: deep
files_reviewed: 17
files_reviewed_list:
  - src/mnemosyne/retrieval.py
  - src/mnemosyne/postgres_engine.py
  - src/mnemosyne/mcp_server.py
  - src/mnemosyne/mcp_tools.py
  - src/mnemosyne/engine.py
  - src/mnemosyne/__init__.py
  - src/mnemosyne/models.py
  - sql/schema.sql
  - pyproject.toml
  - tests/test_runtime_surfaces.py
  - tests/test_engine_contract.py
  - tests/test_nfrs_and_schema.py
  - tests/test_blueprint_later_phases.py
  - tests/test_belief_and_calibration.py
  - tests/test_learning_and_attack_suite.py
  - tests/test_self_optimization.py
  - tests/test_user_model_and_guards.py
findings:
  critical: 6
  warning: 3
  info: 0
  total: 9
status: issues_found
resolution_status: partially_remediated
---

# Phase ad-hoc-runtime-surfaces: Code Review Report

**Reviewed:** 2026-06-19T21:23:12Z
**Depth:** deep
**Files Reviewed:** 17
**Status:** partially_remediated

## Resolution Update

After this review, the following blocker fixes were implemented and verified:

- CR-01 fixed: `LocalMemoryEngine.graph_ppr()` now accepts tenant and branch filters, `retrieve()` passes those filters for deep graph search, and `tests/test_engine_contract.py` reproduces the cross-tenant/branch case.
- CR-02 partially fixed: `PostgresEngine` now exposes `retrieve`, `deep_search`, `explain`, `correct`, `forget`, and `export_tenant`.
- CR-03 fixed at the adapter boundary: public string tenant/user IDs are mapped to deterministic internal UUIDs by `PostgresEngine`.
- CR-04 partially fixed: Postgres branch lifecycle now deletes assertions before branch rows and clones/merges assertions and relations in addition to evidence; the live DB smoke now exercises branch/discard, but the full shared branch contract suite is still required.
- CR-05 partially fixed: `tools/call` now returns MCP-style `content`, `structuredContent`, and `isError`; `notifications/initialized` is suppressed in stdio serving.
- CR-06 partially fixed: Postgres retrieval now writes assertion embeddings/lexemes, uses SQL FTS, pgvector assertion search, deterministic dense evidence fallback, recursive graph/PPR, RRF/MMR, and reranker boundaries. Remaining production work is external embedding providers, ParadeDB/BM25 where needed, AGE/specialist graph adapters where needed, and cross-encoder integration.
- Security follow-up: `MemoryTools` now fail-closes preference writes, hard-instruction profile writes, and destructive forget operations through `SecurityPolicy`; CLI/facade tests cover denied low-trust writes and allowed explicit/operator writes.
- Session-auth follow-up: `security.py` now verifies HMAC-SHA256 signed session identity claims, rejects malformed/tampered/expired/out-of-range tokens, and `mneme` binds tenant/user/role/source-trust claims before command execution. CLI tests cover session-bound writes, token-supplied branch authority, tenant mismatch denial, missing-secret denial, and missing non-session auth context.
- Tenant isolation follow-up: `sql/schema.sql` now enables/forces tenant RLS for tenant-owned tables, and `PostgresEngine` sets `mnemosyne.tenant_id` before tenant-scoped SQL. Fresh-schema live tests pass through engine and CLI paths.
- Privacy follow-up: local and Postgres forget paths now support `tombstone_recompute` and `hard_delete_legal`, with CLI and fresh-schema live coverage for hard-delete evidence removal.
- Retrieval follow-up: HTTP-compatible embedding and reranker adapters now support production provider endpoints through CLI/env configuration, strictly validate provider responses, and fail CLI provider health checks closed while preserving deterministic defaults for local verification.
- WR-01 fixed: Postgres evidence conflict handling restores content, metadata, modality, trust, sensitivity, signed provenance, and access policy.
- WR-02 fixed for current scope: stdio framing/tool-result envelope tests were added, static Postgres retrieval guards were added, and `tests/test_postgres_engine_live.py` exercises both the live Postgres adapter and CLI `--backend postgres` path when `MNEMOSYNE_POSTGRES_DSN` is set.
- WR-03 fixed: the public `MemoryEngine` protocol now includes the high-level runtime methods used by `MemoryTools`.

Current verification: `uv run python -m compileall -q src tests` passes; `uv run pytest -q` collects 153 tests and returns 133 passing tests plus 20 skipped live-DB tests; `MNEMOSYNE_POSTGRES_DSN=postgresql://... uv run pytest -q tests/test_postgres_engine_live.py tests/test_shared_engine_contract.py` returns 30 passing live/shared adapter tests covering tenant RLS, SQL FTS, pgvector assertion search, dense evidence fallback, recursive graph/PPR, branch/discard, branch merge retrieval, bitemporal supersession, tenant isolation, tombstone and hard-delete forget modes, transitive derived-evidence erasure, retrieval trust/sensitivity/quarantine filtering, deep graph tenant/branch isolation, hard-delete audit export, stateless MCP ingestion over tenant-scoped durable Postgres queues, HTTP-configurable retrieval adapter wiring with strict provider response validation, CLI `--backend postgres`, fail-closed CLI `provider-check`, durable Postgres queue leasing/drain, signed-provenance asset binding, externalized payload derived-text retrieval, async media extraction, gated consolidation promotion, and shared local/Postgres evidence/retrieval/branch/as-of/relation/preference/correction/forget-propagation contract parity.

## Summary

Reviewed the newly added runtime surfaces (`retrieval.py`, `postgres_engine.py`, `mcp_server.py`), the existing local engine/facade, schema, package entrypoints, and tests. The submitted runtime work is not ready to ship: deep graph retrieval leaks cross-tenant data, the Postgres adapter is not substitutable for the local engine or MCP facade, the MCP server does not return MCP-compliant tool results, and the current tests validate only in-process happy paths.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: [BLOCKER] Deep graph search leaks relations across tenants and branches

**File:** `src/mnemosyne/engine.py:325`

**Issue:** `graph_ppr()` iterates every relation in `self.relations` without checking tenant or branch (`lines 331-337`), and `retrieve()` calls it with only query tokens (`line 378`). Dense and lexical retrieval apply `tenant_id` and `branch` filters (`lines 372-377`), but deep graph hits bypass those filters. A live reproduction returned a `tenant-b` relation from `engine.deep_search(..., tenant_id="tenant-a")`. This is a tenant data isolation failure.

**Fix:**
```python
def graph_ppr(
    self,
    seeds: list[str],
    k: int,
    as_of: datetime | None = None,
    tenant_id: str | None = None,
    branch: str = "main",
) -> list[Hit]:
    ...
    for rel in self.relations.values():
        if tenant_id is not None and rel.tenant_id != tenant_id:
            continue
        if rel.branch != branch:
            continue
        ...

# in retrieve()
graph = self.graph_ppr(tokenize(query), max(4, k // 2), tenant_id=tenant_id, branch=branch) if deep else []
```
Add a regression test with a relation in `tenant-b` and assert `tenant-a` deep search returns no `tenant-b` hits.

### CR-02: [BLOCKER] PostgresEngine is not substitutable for the runtime facade

**File:** `src/mnemosyne/postgres_engine.py:27`

**Issue:** `PostgresEngine` does not implement the high-level runtime methods used by `MemoryTools`: `retrieve`, `deep_search`, `explain`, `correct`, `forget`, and `export_tenant`. `MemoryTools.search()` calls `self.engine.retrieve(...)` at `src/mnemosyne/mcp_tools.py:124`, and the other facade methods call `deep_search`, `explain`, `correct`, `forget`, and `export_tenant` at lines `127`, `130`, `143`, `156`, and `159`. Swapping in `PostgresEngine` will fail with `AttributeError` for normal MCP/CLI workflows.

**Fix:** Either implement the full `LocalMemoryEngine` behavioral surface on `PostgresEngine`, or make `MemoryTools` depend on a smaller protocol and provide separate Postgres-backed tool implementations. At minimum:
```python
class PostgresEngine:
    def retrieve(...): ...
    def deep_search(...): ...
    def explain(...): ...
    def correct(...): ...
    def forget(...): ...
    def export_tenant(...): ...
```
Then run the existing engine contract tests against both `LocalMemoryEngine` and `PostgresEngine`.

### CR-03: [BLOCKER] PostgresEngine rejects the string tenant/user IDs accepted by the engine model

**File:** `src/mnemosyne/postgres_engine.py:47`

**Issue:** The dataclass contract defines `Evidence.tenant_id` and `Evidence.user_id` as `str` (`src/mnemosyne/models.py:45-46`), and the existing tests use values such as `"tenant-a"` and `"user-a"`. The Postgres schema stores tenants and evidence users as UUIDs (`sql/schema.sql:7-9`, `sql/schema.sql:23-27`), while `PostgresEngine` inserts the raw strings directly into UUID columns (`postgres_engine.py:47-48`, `postgres_engine.py:82-83`). Any non-UUID tenant or user that works in `LocalMemoryEngine` fails in Postgres.

**Fix:** Preserve the public string ID contract and map it to internal UUIDs, or change the schema to use text IDs consistently. Example:
```sql
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
Then resolve `external_id` before writing branch/evidence/assertion rows. Add shared tests that call both engines with `"tenant-a"` and `"user-a"`.

### CR-04: [BLOCKER] Postgres branch/merge/discard lose assertions and relations and are tenant-global

**File:** `src/mnemosyne/postgres_engine.py:291`

**Issue:** `branch()` selects every tenant that has `frm` by branch name (`lines 296-297`) and clones only evidence (`lines 307-324`), not assertions or relations. `merge()` has the same tenant-global branch-name behavior (`lines 330-331`) and merges only evidence (`lines 341-359`). `discard()` deletes relations, evidence, and branch rows by branch name globally (`lines 374-376`) but never deletes assertions; because assertions reference `(tenant_id, branch)` (`sql/schema.sql:74`), deleting branch rows with assertions present can fail, while successful branch/merge operations silently drop belief state. This violates the LocalMemoryEngine branch semantics in `src/mnemosyne/engine.py:514-572`.

**Fix:** Make branch operations tenant-scoped, or explicitly document and authorize global branch operations. Clone/merge/discard evidence, assertions, and relations in one transaction:
```sql
-- discard tenant-scoped branch
DELETE FROM relations WHERE tenant_id = $1 AND branch = $2;
DELETE FROM assertions WHERE tenant_id = $1 AND branch = $2;
DELETE FROM evidence WHERE tenant_id = $1 AND branch = $2;
DELETE FROM branches WHERE tenant_id = $1 AND name = $2;
```
Add tests with two tenants using the same branch name and assertions/relations on that branch.

### CR-05: [BLOCKER] The stdio MCP server is not MCP-compliant enough for real clients

**File:** `src/mnemosyne/mcp_server.py:35`

**Issue:** `tools/call` returns raw tool dictionaries (`lines 52-67`) instead of an MCP `CallToolResult` with required `content` and optional `structuredContent`. The server also returns an error response for `notifications/initialized` because only `initialize`, `tools/list`, and `tools/call` are recognized (`lines 35-47`). The current test asserts the raw dict shape (`tests/test_runtime_surfaces.py:85-89`), so it locks in the non-compliant behavior. Real MCP clients expect lifecycle notification handling and `CallToolResult` shape.

**Fix:**
```python
if method == "notifications/initialized":
    return None  # and serve() must not write a response for notifications

def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    raw = self._dispatch_tool(name, arguments)
    return {
        "content": [{"type": "text", "text": json.dumps(raw, sort_keys=True)}],
        "structuredContent": raw,
        "isError": False,
    }
```
Prefer using the official MCP Python SDK transport/handler rather than hand-rolling JSON-RPC lifecycle behavior.

### CR-06: [BLOCKER] Postgres retrieval is not hybrid semantic/lexical/graph retrieval

**File:** `src/mnemosyne/postgres_engine.py:263`

**Issue:** `lexical_search()` and `vector_search()` both call `_local_rank()`, which scores with `lexical_score()` only (`lines 263-267`, `lines 397-427`). `graph_ppr()` is a stub that always returns `[]` (`lines 269-271`). This means the Postgres adapter does not provide the blueprint-required dense and graph channels, despite the schema defining vector and relation tables and the roadmap requiring lexical + dense + graph fusion.

**Fix:** Implement dense retrieval with the configured embedding provider/pgvector column and graph PPR over tenant/branch-filtered relations. Do not label lexical fallback results as dense hits. Add contract tests that assert Postgres returns distinct lexical, dense, and graph channels with provenance.

## Warnings

### WR-01: [WARNING] Postgres append can resurrect erased evidence without restoring content

**File:** `src/mnemosyne/postgres_engine.py:75`

**Issue:** On `(tenant_id, branch, cid)` conflict, `append_evidence()` only runs `DO UPDATE SET erased = false` (`lines 75-77`). If an erased row has had `content` cleared by an erasure path or external migration, re-appending the same evidence marks it visible again but leaves the old blank/stale content and metadata in place. LocalMemoryEngine replaces erased evidence on re-append (`src/mnemosyne/engine.py:162-170`).

**Fix:** Update all durable fields on conflict:
```sql
DO UPDATE SET
  erased = false,
  content = EXCLUDED.content,
  content_pointer = EXCLUDED.content_pointer,
  modality = EXCLUDED.modality,
  metadata = EXCLUDED.metadata,
  trust_tier = EXCLUDED.trust_tier,
  capability_tags = EXCLUDED.capability_tags,
  sensitivity = EXCLUDED.sensitivity,
  signed_provenance = EXCLUDED.signed_provenance,
  access_policy = EXCLUDED.access_policy
```

### WR-02: [WARNING] Runtime surface tests validate happy-path shims, not real protocol or Postgres behavior

**File:** `tests/test_runtime_surfaces.py:50`

**Issue:** The MCP test calls `MnemosyneMcpServer.handle()` directly and asserts raw results (`lines 50-89`), so it cannot catch stdio framing/lifecycle/tool-result contract failures. The Postgres test only covers private CID/UUID helpers (`lines 99-104`) and never instantiates `PostgresEngine`, initializes schema, or runs shared engine semantics. This leaves the new runtime surfaces effectively untested.

**Fix:** Add tests that:
- drive `serve()` over stdin/stdout and include `initialize`, `notifications/initialized`, `tools/list`, and `tools/call`;
- validate `CallToolResult.content` and `structuredContent`;
- run the engine contract suite against Postgres with a real test database or isolated container;
- seed two tenants/branches to verify isolation.

### WR-03: [WARNING] The public protocol is narrower than the facade behavior

**File:** `src/mnemosyne/engine.py:32`

**Issue:** `MemoryEngine` declares only low-level primitives (`append_evidence`, `upsert_assertion`, `vector_search`, `lexical_search`, `graph_ppr`, `as_of`, `branch`, `merge`, `discard`; lines `32-61`), but runtime code depends on higher-level methods (`retrieve`, `deep_search`, `explain`, `correct`, `forget`, `export_tenant`). The protocol also declares `as_of(subject, predicate, t)` while concrete engines require or accept tenant/branch arguments (`src/mnemosyne/engine.py:415`, `src/mnemosyne/postgres_engine.py:273-276`). This allowed `PostgresEngine` to look protocol-shaped while missing runtime semantics.

**Fix:** Promote the actual runtime surface into a protocol, e.g. `RuntimeMemoryEngine`, and type `MemoryTools` against it. Use `typing.Protocol` plus shared tests to enforce substitutability.

---

_Reviewed: 2026-06-19T21:23:12Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
