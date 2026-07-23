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
Explicit working-memory promotion is also an app-side composition: the engine
stores working items but does not decide whether to promote them.

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
five-method surface with byte-identical signatures:

- `schedule_intention(self, intention: Intention) -> str`
- `update_intention(self, tenant_id, intention_id, *, user_id, agent_id, session_id, due_at=None, action=None, recurrence_policy=None) -> Intention`
- `cancel_intention(self, tenant_id, intention_id, *, cancelled_by, session_id) -> None`
- `evaluate_due_intentions(self, tenant_id, *, evaluated_at, trigger_context, operating_point) -> list[Intention]`
- `list_intentions(self, tenant_id) -> list[Intention]`

The engine method is `evaluate_due_intentions`; the MCP tool that wraps it is
named `evaluate_intentions`. The `Intention` dataclass, its trigger constants
(`exact_time`, `time_window`, `event`, `condition`, `dependency_completion`),
`ProspectiveOperatingPoint`, and `TriggerEvaluationContext` are all defined in
`src/mnemosyne/engine.py` and shared by every engine — no dedicated intention
module exists.

**Scheduling.** `schedule_intention` accepts only a canonical `status="scheduled"`
`Intention` whose `evidence_ids` are non-empty, unique, and resolve to live
main-branch evidence for the same tenant and user. The provenance trust ceiling
(`trust_tier <= max_trust_tier`) and the data-only capability check
(`is_write_tainted`) fail closed **before any mutation** — an over-ceiling or
write-tainted origin raises `PermissionError`; missing / erased / cross-tenant /
cross-user evidence raises `ValueError`.

**Session-auth contract.** Scheduling does not itself require a session token: the
optional `Intention.session_id`, when present, must be a non-empty string and
binds the intention to that session. `update_intention` and `cancel_intention`
both take a keyword-only `session_id: str` with no default. Only the owning
user/agent may mutate (`cancelled_by` / `user_id`+`agent_id` must match), and only
`scheduled` intentions may be updated. When the stored intention already carries a
`session_id`, a differing token raises
`PermissionError("intention session does not match authenticated session")`; an
empty or non-string token raises `ValueError`. An intention scheduled without a
session binds to the first `session_id` that updates or cancels it. Listing is
tenant-scoped; cancellation is tenant-scoped, restricted to the owning user or
agent, and idempotent.

**Evaluation.** `evaluate_due_intentions` requires an explicit
`ProspectiveOperatingPoint` (a caller-supplied precision/recall point — there is no
engine, CLI, or MCP default) and a tenant-matched `TriggerEvaluationContext`. Due
intentions fire in deterministic `(due_at, intention_id)` order.
`trigger_context.infrastructure_available == False` raises with zero mutation —
unavailable infrastructure never fires. Each fire executes in one atomic
transaction that transitions the intention, appends its provenance-linked audit
record, and writes a durable, content-addressed firing receipt keyed by
`intention_fire_receipt_id(tenant_id, intention_id, occurrence)` (persisted in
`intention_firing_receipts` / `intention_firing_receipts_v2` on Postgres and the
engine-local equivalents on Sqlite), so clock replay (a repeated `evaluated_at`),
retries, and identifier reuse cannot produce a second fire; a backwards clock
raises. Returned intentions are detached values, and retrieval treats their action
and trigger payloads as data only.

**Recurrence & watermark.** An `Intention` carries a `recurrence_policy`
(`{"type": "none"}` or `{"type": "interval", "interval_seconds": …,
"max_occurrences"?: …}`) and a `recurrence_state` (`{"occurrence",
"last_evaluated_at"?, "consumed_signal"?}`). The **recurrence watermark** is
`recurrence_state.consumed_signal` — the latest consumed `event`/`condition` signal
(ordered by `(occurred_at|observed_at, event_id|condition_id)`), which may never be
dated after `last_evaluated_at`. On each fire the engine records the watermark for
the completed occurrence; then, for an `interval` policy that has not reached
`max_occurrences`, it advances `due_at` by `interval_seconds`, increments
`occurrence`, appends a bounded `"reason": "recurrence"` reschedule entry, and
shifts the `exact_time.at` / `time_window.start`+`end` bounds forward. The
watermark-plus-`last_evaluated_at` cursor is what prevents re-consuming a signal or
double-firing an occurrence; an `OverflowError` on the next due date ends the
recurrence rather than poisoning tenant-wide evaluation.

## Working-memory contract

The same three engines provide `put_working`, `get_working`, `list_working`, and
`expire_working`. A `WorkingMemoryItem` is tenant-, session-, and item-scoped,
must cite live evidence for the same tenant, user, and session, and has a TTL in
the interval `(0, 24 hours]`. Reads expose active items over the half-open window
`created_at <= as_of < expires_at`, return detached values, and never expose an
item across a tenant or session boundary. Working content remains outside the
durable evidence ledger and is never promoted implicitly.

Explicit promotion is an app-side `PromotionGate` operation exposed as the MCP
`working_promote` tool and CLI `working-promote` command. It requires
consolidator or operator authority and explicit regression cases. Durable state
is retained on the main branch only when the gate passes; the source working
item is not mutated or deleted by promotion.

Expiry is deterministic and audited. `expire_working` selects only active items
whose `expires_at <= expired_at`, orders them by deadline, session, and item ID,
and atomically records the transition and audit receipt. Its optional
`session_id`, `user_id`, `agent_id`, `task_id`, and `branch` selectors are
conjunctive scope restrictions; omitting them is the supported tenant-wide
sweep. Repeating the same sweep returns no items.

## Cross-engine assertion-identity map

Every engine's branch `merge(frm, into, tenant_id)` returns a `MergeReport`
(`src/mnemosyne/models.py`) whose trailing `assertion_id_map: dict[str, str]` maps
each promoted **source** assertion id to its **actual durable destination** id —
one complete entry per promoted assertion, including identity mappings. Local and
Sqlite frequently preserve the source id (an identity entry); Postgres mints a
deterministic per-`(source id, target branch)` clone id via
`_merge_clone_assertion_id` (a `uuid5(NAMESPACE_URL, …)`) so replaying the same
merge converges through `ON CONFLICT (id)` instead of duplicating rows. Destination
values need not be unique — several sources may absorb into one existing peer.

The MCP `confirm` tool is backend-agnostic: it promotes the proposal branch, then
resolves the caller's submitted id through `assertion_id_map` and returns the
envelope `{"id", "source_id", "confirmed_id", "branch", "into", "merge",
"security"}`, where `confirmed_id == merge.assertion_id_map[source_id]` and `merge`
is the full `MergeReport.to_dict()`. Resolution **fails closed**: if the merge
produced no non-blank string mapping for the requested source, `confirm` raises
rather than fabricate an identity. `tests/test_shared_engine_contract.py` and the
per-engine parity suites pin this `confirmed_id` equivalence across
Local/Postgres/Sqlite.

## Signed deletion manifest

The signed-deletion subsystem (`src/mnemosyne/deletion.py` `DeletionCoordinator`
plus `src/mnemosyne/deletion_manifest.py`) is engine-agnostic — it wraps whatever
`MemoryEngine` it is constructed with and is exercised by
`tests/completion/security/test_deletion_residue.py`. It is **distinct** from the
engine `forget(...)` erasure method (the `ErasureMode` / `deletion_log` path exposed
by the CLI/MCP `forget` surface); the signed manifest has no CLI subcommand or MCP
tool.

`DeletionCoordinator.delete(...)` is idempotent on `operation_id`, requires a
verified `SessionIdentity`, tenant/user ownership, an authorized destructive write
role (`policy.authorize_write("deletion.hard_delete_legal", identity.role, …)`, one
of the four `WriteRole`s) carrying a `requested_by_role == "legal"` request field, and
`hard_delete_legal` mode, and drives a forward-only, resumable saga whose durable
per-surface receipts are journalled by an `SQLiteDeletionLedger` (WAL +
`synchronous=FULL` + POSIX `flock` + CAS `revision`). Custody-bearing values are
replaced by keyed-HMAC `opaque:<hex>` tokens.

**Verify contract.** `verify_deletion_manifest(manifest) -> {"complete", "errors"}`
is a *semantic* verifier that never raises. It fails closed unless the manifest:
uses `schema == "mnemosyne.deletion_manifest.v1"` with no unknown/missing fields;
carries no canary material, no `://` source URIs, and no raw hashes, with custody
nesting `≤ 32`; has opaque `tenant_ref` / `user_scope` / `reason`; has
`operation_id` a UUID with `request_id == operation_id` (identity linkage);
`requested_at <= completed_at`; `mode == "hard_delete_legal"` with
`requested_by_role == "legal"`; `branch_scope ∈ {main, all}`; `policy.version ==
"w2"`; a durable positive `fence`; full `surfaces ⇄ stores ⇄
policy.required_surfaces` coverage set-equality with no duplicate labels; every
surface `verified_removed` with `residue_probe == 0`, `state == "verified"`,
`backend == "synthetic"`, and matching durability checkpoints; a zero-residue
summary (`cascade_percent == 100`, `recoverable_residue_count == 0`,
`cross_tenant_mutations == 0`); and `retention_exceptions == []`.
`verify_signed_deletion_manifest(manifest_path, public_key_path)` additionally
requires a valid detached **Ed25519** collector signature (`evidence_signing.py`,
`mnemosyne.evidence_signature.v1`) *and* rebinds it to the exact bytes it verifies
via a `manifest_sha256` TOCTOU check; `complete` is true only when both signature
and semantics pass. `write_signed_deletion_manifest` refuses to sign a semantically
incomplete manifest.

## Legacy evidence-CID compatibility

New ledger writes use subject-scoped evidence CIDs. On all three engines, the
erased-evidence replay guard also recognizes the former unscoped CID shape so a
legacy tombstone cannot be bypassed by replaying its content. This compatibility
is limited to erased-replay detection: a live legacy unscoped row does not
deduplicate or replace a new subject-scoped write for a different user.

## Phase 0 substrate implementation mapping

This historical substrate mapping records the Local/Postgres scope verified at
Phase 0 completion. It is not the complete current engine inventory; the
three-engine prospective and working-memory mapping follows it.

| Capability | LocalMemoryEngine (`src/mnemosyne/engine.py`) | PostgresEngine (`src/mnemosyne/postgres_engine.py`) |
|---|---|---|
| (a) ledger | `LocalMemoryEngine.append_evidence` | `PostgresEngine.append_evidence` — CID-keyed `INSERT INTO evidence` |
| (g) branch | `LocalMemoryEngine.branch` / `LocalMemoryEngine.discard` | `PostgresEngine.branch` / `PostgresEngine.discard` — row copies of `evidence` and `assertions` into the new branch |
| (h) as-of | `LocalMemoryEngine.as_of` | `PostgresEngine.as_of` — bitemporal SQL over `assertions` (`valid_from`/`valid_to` window) |
| (i) cached graph | `mnemosyne.retrieval.GraphSignalCache` (app-side `put`/`fast_signal`); `LocalMemoryEngine.graph_ppr` accepts `use_cache` for contract shape but always computes live | `PostgresEngine.graph_ppr(use_cache=True)` → `PostgresEngine._read_graph_ppr_cache` over the `graph_ppr_cache` table (`_ensure_graph_ppr_cache_schema`) |
| (j) queue | `mnemosyne.queue.InProcessQueue` (in-memory `enqueue`/`lease`/`complete`/`fail`) | `mnemosyne.queue.PostgresQueue` (durable leases, same surface — also defined in `src/mnemosyne/queue.py`) |

## Memory-plane implementation mapping

| Capability | LocalMemoryEngine (`src/mnemosyne/engine.py`) | PostgresEngine (`src/mnemosyne/postgres_engine.py`) | SqliteEngine (`src/mnemosyne/sqlite_engine.py`) |
|---|---|---|---|
| (k) prospective memory | `schedule_intention` / `update_intention` / `cancel_intention` / `list_intentions` / `evaluate_due_intentions` | `schedule_intention` / `update_intention` / `cancel_intention` / `list_intentions` / `evaluate_due_intentions` | `schedule_intention` / `update_intention` / `cancel_intention` / `list_intentions` / `evaluate_due_intentions` |
| (l) working memory | `put_working` / `get_working` / `list_working` / `expire_working` | `put_working` / `get_working` / `list_working` / `expire_working` | `put_working` / `get_working` / `list_working` / `expire_working` |
