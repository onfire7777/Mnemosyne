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
(k) prospective-memory intention scheduling, cancellation, listing, and evaluation
(l) working-memory put, get, list, and deterministic expiry

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
its fixture param (`@pytest.fixture(params=["local", "postgres", "sqlite"])`) and the
parity suites (`tests/test_parity_*.py`) pass against the `LocalMemoryEngine`
oracle.

## Prospective-memory contract

`LocalMemoryEngine`, `PostgresEngine`, and `SqliteEngine` provide the same
`schedule_intention`, `cancel_intention`, `list_intentions`, and
`evaluate_due_intentions` surface. Scheduling accepts only a canonical scheduled
`Intention` whose evidence resolves to live main-branch rows for the same tenant
and user. The provenance trust ceiling and data-only capability checks fail
closed before mutation. Listing is tenant-scoped; cancellation is tenant- and
user-scoped and idempotent.

Evaluation requires an explicit `ProspectiveOperatingPoint` and a tenant-matched
`TriggerEvaluationContext`. It supports `exact_time`, `time_window`, `event`,
`condition`, and `dependency_completion` triggers. Satisfied intentions fire in
deterministic order. Each fire atomically transitions the intention, appends its
provenance-linked audit record, and creates a durable firing receipt, so retries
and identifier reuse cannot produce a second fire. Unavailable infrastructure
does not fire an intention. Returned intentions are detached values, and
retrieval treats their action and trigger payloads as data only.

## Working-memory contract

The same three engines provide `put_working`, `get_working`, `list_working`, and
`expire_working`. A `WorkingMemoryItem` is tenant-, session-, and item-scoped,
must cite live evidence for the same tenant, user, and session, and has a TTL in
the interval `(0, 24 hours]`. Reads expose active items over the half-open window
`created_at <= as_of < expires_at`, return detached values, and never expose an
item across a tenant or session boundary. Working content remains outside the
durable evidence ledger and is never promoted implicitly.

Expiry is deterministic and audited. `expire_working` selects only active items
whose `expires_at <= expired_at`, orders them by deadline, session, and item ID,
and atomically records the transition and audit receipt. Its optional
`session_id`, `user_id`, `agent_id`, `task_id`, and `branch` selectors are
conjunctive scope restrictions; omitting them is the supported tenant-wide
sweep. Repeating the same sweep returns no items.

## Legacy evidence-CID compatibility

New ledger writes use subject-scoped evidence CIDs. On all three engines, the
erased-evidence replay guard also recognizes the former unscoped CID shape so a
legacy tombstone cannot be bypassed by replaying its content. This compatibility
is limited to erased-replay detection: a live legacy unscoped row does not
deduplicate or replace a new subject-scoped write for a different user.

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
