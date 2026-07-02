# MemoryEngine Storage Contract

Normative surface for any Mnemosyne storage engine
(spec `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` §4.0).

## Layer 1 — storage primitives (engine MUST provide)

(a) append-only ledger writes with CID verification
(b) flat scans filtered by tenant/branch/valid-window returning the full §19
    meta-envelope (status, trust_tier, fidelity, confabulation-risk flag)
(c) plain-term lexical candidate retrieval (no operator grammar)
(d) vector top-k (exact, or ANN + exact re-rank)
(e) transactional projection rebuild + per-projection watermarks
(f) embedding_partition split and never-embed rules
(g) branch create/discard and branch-scoped visibility
(h) as-of (bitemporal) reads
(i) cached graph-signal read (graph_ppr(use_cache=True) shape)
(j) durable queue lease surface

## Layer 2 — app-side compositions (engine MUST NOT reimplement)

retrieval pipeline, PPR computation (`mnemosyne.algorithms.ppr_power_iteration`),
merge semantics (shipped replay-upsert), RRF/MMR/U-curve/budget
(`mnemosyne.algorithms.rrf_fuse`, `mnemosyne.algorithms.mmr_select`,
`mnemosyne.algorithms.u_curve_order`, `mnemosyne.algorithms.fit_budget`),
activation scoring, calibration.

## Naming rules

Engine-specific channel names are forbidden in this contract but each engine's
externally REPORTED backend identifiers are pinned verbatim
(`tests/test_backend_name_stability.py`): `postgres-fts`, `postgres-recursive-ppr`,
`local-bm25-lite`, `local-ppr`.

## Conformance

An engine is conformant when `tests/test_shared_engine_contract.py` passes with
its fixture param (`@pytest.fixture(params=["local", "postgres"])`) and the
parity suites (`tests/test_parity_*.py`) pass against the `LocalMemoryEngine`
oracle.

## Current implementation mapping

All symbols below are verified against the codebase as of Phase 0
completion; both engines implement `append_evidence`, `branch`,
`discard`, and `as_of` under those exact names.

| Capability | LocalMemoryEngine (`src/mnemosyne/engine.py`) | PostgresEngine (`src/mnemosyne/postgres_engine.py`) |
|---|---|---|
| (a) ledger | `LocalMemoryEngine.append_evidence` | `PostgresEngine.append_evidence` — CID-keyed `INSERT INTO evidence` |
| (g) branch | `LocalMemoryEngine.branch` / `LocalMemoryEngine.discard` | `PostgresEngine.branch` / `PostgresEngine.discard` — row copies of `evidence` and `assertions` into the new branch |
| (h) as-of | `LocalMemoryEngine.as_of` | `PostgresEngine.as_of` — bitemporal SQL over `assertions` (`valid_from`/`valid_to` window) |
| (i) cached graph | `mnemosyne.retrieval.GraphSignalCache` (app-side `put`/`fast_signal`); `LocalMemoryEngine.graph_ppr` accepts `use_cache` for contract shape but always computes live | `PostgresEngine.graph_ppr(use_cache=True)` → `PostgresEngine._read_graph_ppr_cache` over the `graph_ppr_cache` table (`_ensure_graph_ppr_cache_schema`) |
| (j) queue | `mnemosyne.queue.InProcessQueue` (in-memory `enqueue`/`lease`/`complete`/`fail`) | `mnemosyne.queue.PostgresQueue` (durable leases, same surface — also defined in `src/mnemosyne/queue.py`) |
