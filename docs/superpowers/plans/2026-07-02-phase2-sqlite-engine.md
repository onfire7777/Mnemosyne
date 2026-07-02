# Phase 2: SqliteEngine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `SqliteEngine` — the third `MemoryEngine` backend (one SQLite file per tenant) — with FTS5-prefiltered lexical, kernel-batched dense scans, cached-PPR projection, bitemporal as-of, durable queue, branch/merge, the A1 embedding cache, full erasure wiring (journal tombstone/purge), the DST/chaos harness, and the drift/ops-check/L4 suites green — validated by the same parity harness that proved Local↔Postgres.

**Architecture:** Pure Python (stdlib `sqlite3`; `sqlite-vec` optional, kernel exact-scan is the default dense path). The still-duplicated `retrieve()` pipeline is extracted FIRST into an engine-agnostic orchestrator so SqliteEngine never becomes a third copy. SqliteEngine mirrors `LocalMemoryEngine` semantics (the parity oracle) — external IDs stored verbatim (no uuid5 mapping), `dt_to_json` timestamps everywhere, replay-upsert merge.

**Tech Stack:** Python 3.12 stdlib sqlite3 (verified: 3.50.x with `enable_load_extension` in the dev venv), optional `sqlite-vec` (new optional extra), existing `mnemosyne_native` kernels via `text.NATIVE`, hypothesis, honeytokens, CIDJournal, ProjectionRegistry.

## GROUNDING FILE (mandatory reading per task)

`.superpowers/sdd/phase2-grounding.md` — verified facts with file:line evidence (2026-07-02). Section map: **R1**=branch/merge/as-of/queue; **R2**=L4 poison/drift/config; **R3**=persistence/projections/consolidation-contract; **R4**=erasure/forget/blocklist/partitions; **R5**=engine construction/scan/model surfaces; **R6**=ops-checks/observability/audit; **R7**=critic gaps (CR-03 IDs, dt_to_json, workspace filters, retrieve-pipeline inventory, contract-suite construction, schema conventions). Line anchors drift — re-grep every anchor before editing.

## Global Constraints

- Runtime deps stay exactly `["cryptography>=42"]`; `sqlite-vec` ONLY under a new optional extra `sqlitevec`; nothing new in the default install.
- **LocalMemoryEngine is the parity oracle**: SqliteEngine must pass `tests/test_shared_engine_contract.py` as a third fixture param and the cross-engine parity suites with zero test-semantic changes. Every public method signature byte-matches the `MemoryEngine` Protocol (engine.py:242-360, runtime_checkable — the full 21-method list is in R5).
- **Decisions locked by grounding (do not relitigate):** external tenant/user IDs stored VERBATIM (no CR-03 uuid5 mapping — R7); timestamps stored and compared as `models.dt_to_json` strings, rehydrated via `models.parse_dt` (R7); merge = Local-style replay-upsert through own `upsert_assertion` (R1); backend names `sqlite-fts5` / `sqlite-cached-ppr` (must NOT match the `local-` forbid_local denylist — R2/R6); preferences/entities cascade tenant-scoped, assertions/relations branch-scoped (R4); production topology stays Postgres-only (SqliteEngine in a production topology = drift check D).
- Both kernel modes stay green: run the full suite native AND `MNEMOSYNE_PURE=1` at phase exit (per-task: native mode suffices except where a task touches dispatch-adjacent code).
- Suite baseline at phase start: recorded in the ledger at branch cut (Phase-1 final numbers). Zero regressions per task. Long suites: `nohup ... > /tmp/suite-X.log 2>&1 &` + marker pattern.
- Do NOT touch: gates/rails logic, `sql/schema.sql` (Postgres-only, doubly pinned by drift check G), `infra/`, CID computation, `mcp_tools.py` (TOOL_SPEC), the Postgres engine's behavior.
- Test invocation `uv run --locked python -m pytest <path>` (addopts has -q); never edit source mid-run; commits `type(scope): summary`. Branch: `phase2/sqlite-engine`.

---

### Task 1: Extract the `retrieve()` pipeline (prerequisite — spec §4.0 remainder)

**Files:** Create `src/mnemosyne/pipeline.py`; Modify `src/mnemosyne/engine.py` (retrieve ~1426-1556 + its 13 private helpers stay, but retrieve delegates), `src/mnemosyne/postgres_engine.py` (retrieve ~2316ff same); Test `tests/test_pipeline_extraction.py` (new).

**Interfaces:**
- Produces `run_retrieval_pipeline(ops: RetrievalPipelineOps, *, query: str, tenant_id: str, branch: str, deep: bool, filt: dict | None, policy) -> RetrievalResult` and `class RetrievalPipelineOps(Protocol)` enumerating exactly the per-engine calls the shipped retrieve() makes. Build the Protocol by INVENTORY, not invention: read both retrieve() bodies and list every `self.*` call (R7 names the 13-helper inventory; Local's body is the reference — Phase-0 established the two bodies are structurally mirrored). Workspace handling (`workspace_broadcast_from_context` → `strip_workspace_broadcast_filter` — retrieval.py:146/172), activation, u-curve, budget, calibration/abstention, explain-dict assembly (ALL keys incl. read_marks, standing, reality_monitoring, schema_fast_path, workspace_broadcast, workspace_retrieval_advisory, adapters, rails) live in the shared orchestrator; engine-specific bits (channel searches, _apply_standing_scores, _record_retrieval_access, _calibration_for, _confidence, _prediction_set_size, _reality_monitoring_report, _calibration_explain, _mark_retrieved_text_as_data, _merge_schema_fast_path_reports) are ops members.
- Characterization FIRST: goldens capturing full `RetrievalResult` (hits tuples + confidence bits + explain key-set + channel counts) for seeded stores on Local (and Postgres if DSN present), asserted identical before/after extraction, both kernel modes.
- Exit: both engines' retrieve() = thin delegation; full suite + DSN-armed parity green; explain-structure goldens byte-identical.

Steps: characterization goldens → red on missing module → Protocol + orchestrator (move Local's body verbatim, `self.` → `ops.`) → Local delegates → suite → Postgres delegates (diff-first: any PG-only line becomes an ops override, documented) → DSN parity → commit `refactor(pipeline): extract shared retrieve orchestration (spec §4.0)`.

### Task 2: SqliteEngine store core + schema

**Files:** Create `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/sqlite_schema.py`; Test `tests/test_sqlite_engine_core.py`.

**Interfaces:**
- `SqliteEngine(root_dir, policy=None, adapters=None, journal_dir=None)` — kwargs mirror LocalMemoryEngine (R5); `root_dir` holds one `<tenant>.db` per tenant via `journal.journal_filename`-style safety (reuse that helper's pattern for db filenames — factor a shared `safe_tenant_filename(tenant_id, suffix)` into journal.py and reuse). `isinstance(engine, MemoryEngine)` must hold.
- Schema (in `sqlite_schema.py` as `ENSURE_STATEMENTS: list[str]`, applied idempotently on open — SQLite convention differs from Postgres' external DDL, document why): all 13 store collections (R3) with the exact uniqueness keys the Local dicts encode — evidence UNIQUE(tenant_id,branch,cid); assertions/relations UNIQUE(tenant_id,branch,id); preferences/justifications/contradictions PK(id); calibrations PK(tenant_id,memory_type); entities PK(tenant_id,canonical) — plus branches(name,from_branch,created_at), runtime_jobs (mirror R1's PostgresQueue DDL shape for sqlite), audit_log/deletion_log/merge_log, meta(key,value) for schema_version + projection watermarks. JSON columns as TEXT via `json.dumps(sort_keys=True)`; timestamps via `dt_to_json`.
- Pragmas on every connect: `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout=5000`; `PRAGMA integrity_check` on first open per file (raise on failure).
- Row rehydration through the exact constructors: `Evidence.from_dict`, `Assertion.from_dict`, `CalibrationSet(**row)`, `dict(row)` for entities (R3) so exports are byte-compatible.

Steps: failing construction/round-trip tests (open, pragmas asserted via `PRAGMA` queries, integrity check, tenant-file naming incl. hostile ids, schema idempotency, Evidence round-trip byte-compat vs Local's to_dict) → implement → suite → commit `feat(sqlite): SqliteEngine store core, per-tenant WAL files, 13-collection schema`.

### Task 3: Ledger surface + journal wiring

**Files:** Modify `src/mnemosyne/sqlite_engine.py`; Test `tests/test_sqlite_engine_core.py` (extend).

**Interfaces (R4/R5/R3):** `append_evidence` (CID via Python `ids.evidence_cid` path exactly as Local does — read Local's append flow incl. validate_access_policy, _require_branch, dedup, budget-deferral, blocked_erased_replay with BOTH scoped and legacy unscoped CID probes, audit, journal append AFTER commit when journal_dir set); `get_evidence`; `update_evidence_metadata` (ValueError on access_policy in patch); `set_evidence_embedding` (may_embed_item + metadata.embedding_partition via `vector_partition_for_item`, fail-closed); `backfill_evidence_privacy`; `export_tenant`/`export_tenant_filtered` byte-compatible with Local. Audit rows must round-trip (R3's audit row shape).

Steps: characterization tests comparing against a seeded LocalMemoryEngine oracle (same inputs → same export_tenant output modulo store-format) → implement → suite → commit `feat(sqlite): ledger surface with erased-replay blocklist and CID-journal wiring`.

### Task 4: Scan surfaces (dense / lexical / graph)

**Files:** Modify `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/sqlite_schema.py` (FTS5 virtual table + triggers); root `pyproject.toml` (optional extra `sqlitevec = ["sqlite-vec>=0.1.9"]`); Test `tests/test_sqlite_scans.py` (new).

**Interfaces:**
- `_candidate_hits`-equivalent SQL respecting the EXACT filter surface (R5): tenant_id, branch (default "main"), include_quarantined, max_trust_tier with min_trust_tier legacy fallback, effective_max_sensitivity; `may_read_item` and redaction stay app-side per hit (post-SQL), identical to Local.
- `vector_search`: candidates → per-hit gated embedding acquisition (same `_embedding_for_hit` semantics — port Local's, including `stored_embedding_used`/`dense_media` metadata and `may_use_stored_embedding`) → batched `text.NATIVE.dense_scan` when native else pure loop (mirror engine.py's Task-7 pattern verbatim); channels `dense_hash`/`dense_media`.
- `lexical_search`: adapter branch honored (adapters.lexical_retriever); fallback = FTS5 MATCH prefilter (per-term quoted, unicode61 tokenizer-mismatch documented) → rescore ALL candidates app-side with shared `lexical_score` (kernel `lexical_scan` when native) — FTS5 is candidate recall ONLY, never ranking (spec §4.2); channel "lexical"; tokenizer-mismatch tests (hyphenated tags, version strings, URLs) prove recall parity vs Local on the plan's stressor corpus, falling back to full-table scan when FTS5 misses candidates that Local's scan finds... NO — deterministic rule instead: FTS5 prefilter with OR-of-quoted-terms + always-union of rows whose tokenized text the FTS index may split differently is NOT tractable; therefore: FTS5 prefilter ONLY when every query token is unicode61-safe (`[a-z0-9_]+` after tokenize), else full scan. Encode that predicate as `fts_safe_query(tokens) -> bool` with tests; document in the engine docstring.
- `graph_ppr`: live path = build adjacency from relations (mirror Local's graph_ppr body semantics incl. bitemporal validity window and `mark_retrieved_text_as_data`), shared `ppr_power_iteration`; `use_cache=True` path reads the cached-PPR projection (Task 8). Backend names reported: `lexical_backend="sqlite-fts5"`, `graph_backend="sqlite-cached-ppr"`; add pins to `tests/test_backend_name_stability.py` and confirm both escape `_is_local_retrieval_backend` (cli.py:~14051) — with a test.
- sqlite-vec: IF importable and extension loading available, register vec0 table as an optional dense candidate index behind the projection registry; default remains the kernel exact scan; `doctor`-style startup line reports the active dense channel. All sqlite-vec code paths must be skip-tested when absent.
- **PACKED-BLOB dense seam (Phase-1 handoff — spec §8 Phase-1 exit item completed here):** embeddings are stored as packed little-endian f64 BLOBs (`array.array('d', vec).tobytes()`), and `vector_search`'s native path feeds them to `mnemosyne_native.dense_scan_packed(query_bytes, rows_bytes, dims, row_mask)` with ZERO per-call conversion (the Phase-1 list-FFI seam measured 1.8×; kernel-on-prepacked measured ~30×). **Binding exit gate for this task:** end-to-end sqlite dense scan ≥10× vs the clean pure baseline (`_gate_speedup` bench added to tests/benchmarks). Unpacking to list[float] happens only for gated per-hit reads (`may_use_stored_embedding` paths), never for the scan hot path.

Steps: TDD against a Local oracle (same seeded content, byte-compare (id, score-bits, channel) for vector+lexical+graph across both kernel modes) → implement → suite → commit `feat(sqlite): dense/lexical/graph scan surfaces with FTS5-safe prefilter`.

### Task 5: Assertions, bitemporal as-of, remaining writes

**Files:** Modify `src/mnemosyne/sqlite_engine.py`; Test `tests/test_sqlite_engine_core.py` (extend).

**Interfaces (R1/R5):** `upsert_assertion` (replay semantics — supersede/contest logic identical to Local: read Local's method fully; merge replays through this), `add_relation`, `add_preference` (supersession semantics from Local ~1150), `register_entity`, `as_of` (half-open [valid_from, valid_to) UTC window over dt_to_json TEXT comparisons — add the R7 regression test proving 'Z'-format consistency), `set_calibration`/`_calibration_for`, `explain`, `correct`, `deep_search` (delegates through pipeline/uc paths as Local does).

Steps: TDD with Local-oracle comparisons (incl. supersession/contradiction cases from the shared contract suite's shapes) → implement → suite → commit `feat(sqlite): assertions, bitemporal as-of, preferences/relations/entities`.

### Task 6: Branch / merge / discard + queue

**Files:** Modify `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/queue.py` (add `SqliteQueue` mirroring PostgresQueue's surface over the tenant file's runtime_jobs); Test `tests/test_sqlite_branch_merge.py` (new).

**Interfaces (R1/R3):**
- `branch(name, frm="main", kind="scratch", tenant_id=...)` — TENANT-SCOPED kwargs form (gate.py's canary flow needs it; the TypeError fallback silently degrades — implement the kwarg form); row-copies exactly evidence+assertions+relations; evidence keeps cid (INSERT OR IGNORE on the unique key); assertions/relations get fresh uuid4 ids (PG-style — safer for id uniqueness); copies include embedding, embedding_partition, last_accessed, access_count.
- `merge(frm, into, tenant_id=...)`: Local-style replay-upsert — loop frm assertions → own `upsert_assertion(cloned, branch=into)`, count added vs merged; evidence/relations copied with dedup; `MergeReport(frm, into, evidence_added, assertions_added, assertions_merged, relations_added, conflicts=[])` POSITIONAL field order per R1; conflicts always [].
- `discard(branch, tenant_id=...)`; branches registry table + a dict-shaped `.branches` property (PromotionGate._reset_branch requirement, R3).
- `SqliteQueue`: enqueue/lease/complete/fail/snapshot matching InProcessQueue/PostgresQueue surfaces (R1's QueueJob shape); lease semantics = visibility-timeout update in one transaction (BEGIN IMMEDIATE).

Steps: TDD incl. the cross-engine merge parity shapes (`test_parity_merge_branch_into_main` assertions: evidence_added/assertions_added/relations_added/conflicts==[]/merged_on_main) → implement → suite → commit `feat(sqlite): branch/merge/discard row-copies + SqliteQueue leases`.

### Task 7: `retrieve()` via the shared pipeline + consolidation duck-type

**Files:** Modify `src/mnemosyne/sqlite_engine.py`; Test `tests/test_sqlite_retrieve.py` (new).

**Interfaces:** Implement the `RetrievalPipelineOps` members for SqliteEngine (Task 1's Protocol): channel searches from Task 4; port Local's `_apply_standing_scores`, `_confidence`, `_prediction_set_size`, `_reality_monitoring_report`, `_calibration_explain`, `_mark_retrieved_text_as_data`, `_merge_schema_fast_path_reports` usage — SHARED WHERE POSSIBLE: any helper that is pure (no store access) must be imported from its existing module, not copied (audit each; the spec forbids a third copy of pipeline logic). `_record_retrieval_access` = synchronous write matching shipped engines (R7's collision note: shipped behavior wins for parity; the spec's async-telemetry optimization is deferred, documented in the engine docstring + ledger). Consolidation duck-type contract (R3): get_evidence, export_tenant, append_evidence, add_relation, update_evidence_metadata, set_evidence_embedding, register_entity, upsert_assertion, retrieve, `adapters` attribute — a ConsolidationWorker smoke test flips passes from 'skipped' to 'complete'.

Steps: TDD (retrieve explain-parity vs Local goldens from Task 1; consolidation worker smoke via run_queue_payload with SqliteQueue) → implement → suite both kernel modes → commit `feat(sqlite): retrieve via shared pipeline + consolidation compatibility`.

### Task 8: Embedding cache (A1) + cached-PPR projection + registry integration

**Files:** Modify `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/sqlite_schema.py`; Test `tests/test_sqlite_cache_projections.py` (new).

**Interfaces (spec §4.2 A1 + R4/R6):**
- `embedding_cache` table in the tenant file: key = (cache_key, model_id) where cache_key = cid for S0/S1 content and the SUBJECT-SCOPED salted cid for S2+ (the salting already lives in `ids.evidence_cid` — reuse the stored row's cid, which is already subject-salted for S2+/PII per R4; document that this is what closes the dedup-oracle rail); admission predicate = `vector_partition_for_item` rules: {S4, embed_ok:false, restricted, held, unknown-policy} never cached; S3 only under the sensitive-embedding deployment flag (locate the existing flag via access_policy.py; if none exists, S3 is never cached — fail closed, documented). Read side passes `may_use_stored_embedding`-equivalent gating: a denied context gets a miss. Purge hooks: called from forget (Task 9) for both modes + on restriction/hold policy changes via `backfill_evidence_privacy`/`update_evidence_metadata` paths. Hit-rate telemetry only at tenant granularity.
- Cached-PPR projection: `ProjectionSpec(name="cached-ppr", version=1, fingerprint=<relations watermark>, rebuild=<recompute PPR vectors per seed-set policy>)` registered in a per-tenant `ProjectionRegistry(state_dir=<tenant dir>)`; `graph_ppr(use_cache=True)` reads it (GraphSignalCache-compatible metadata `graph_signal_cached=True`); consolidation refresh hook mirrors `refresh_graph_ppr_cache` (R5). FTS5 + vec tables also registered as named projections with rebuild-on-mismatch (rebuild = re-derive from evidence/assertions rows).
- Privacy test classes 10 & 13 (R6): test 10 — cross-subject S2+ probe indistinguishable from miss (timing-insensitive assertion: same code path, assert cache row absent + provider called); test 13 — post-erasure, `sha256(guess)` finds no confirmation in cache/journal/deletion artifacts (ties into Task 9's HMAC work).

Steps: TDD → implement → suite → commit `feat(sqlite): subject-scoped embedding cache + registered rebuildable projections`.

### Task 9: Erasure wiring (forget + journal + HMAC + propagation)

**Files:** Modify `src/mnemosyne/sqlite_engine.py`, `src/mnemosyne/journal.py` (repair-before-append), `src/mnemosyne/engine.py` + `src/mnemosyne/postgres_engine.py` (deletion_log HMAC — cross-engine, see below); Create `src/mnemosyne/erasure_ids.py` (salted-hash producer); Test `tests/test_sqlite_erasure.py` (new) + extend `tests/test_journal.py`.

**Interfaces (R4 verbatim + spec §4.2/§7):**
- `forget` clones the shipped signature + return/refusal dict shapes exactly; tombstone_recompute = UPDATE content='' erased=1 keeping all other columns (the row IS the blocklist); hard_delete_legal = DELETE; legal_blind cascade reuses the module-level `postgres_engine._derived_evidence_forget_plan` pure function (import it — it is engine-independent per R4); min_corroboration guard; cascade asymmetry (preferences/entities tenant-scoped; assertions/relations branch-scoped); propagated dict key-set incl. standing_cascade.
- Journal wiring: tombstone_recompute → `CIDJournal.tombstone(cid, salted_hash=..., erased_at=...)`; hard_delete_legal → `CIDJournal.purge(cid)`. Salted-hash producer (NONE exists today — R4): `erasure_ids.erasure_tombstone_hash(content, tenant_id, user_id) -> str` = sha256 over a documented salt construction; used for journal tombstones AND deletion-log HMAC ids.
- **Repair-before-append** (Phase-0 handoff, FIRST journal item): `CIDJournal.append` detects a torn tail (missing trailing newline / undecodable last line) and repairs (truncate the torn fragment — it is by-construction unfsynced/unacknowledged) BEFORE appending; property test: append-after-torn-tail preserves all complete records + the new one, records() clean.
- **Deletion-log HMAC (spec §7, privacy invariant 13) — cross-engine:** deletion_log rows for hard_delete_legal replace `evidence_cid` with `erasure_ids` HMAC (retain mode keeps the cid — it still exists as a tombstone row). Applies to SqliteEngine AND Local AND Postgres (a behavior change sanctioned by the spec; guard with tests per engine + a compat note: existing logs unchanged, only new rows). If the shared contract suite pins the old behavior, update those assertions in the SAME commit with the spec citation.
- Erasure propagation: embedding-cache purge (both modes), targeted projection invalidation (delete affected rows; full rebuild only on fingerprint mismatch), branch propagation (erase across all branches in the tenant file — mirror Local's branch behavior first: verify what Local does cross-branch and MATCH it; if Local is single-branch-scoped, match that and record the spec-vs-shipped gap in the ledger rather than diverging from the oracle).

Steps: TDD (mode-matrix tests: both modes × {journal, cache, projections, deletion_log, blocklist-survival}; ledger-rebuild ≡ journal-rebuild post-erasure in both modes) → implement → suite (this task touches Local/PG — DSN-armed parity required) → commit `feat(sqlite): full erasure wiring — journal tombstones, HMAC deletion ids, targeted invalidation`.

### Task 10: Contract-suite + CLI/MCP + drift integration

**Files:** Modify `tests/test_shared_engine_contract.py` (fixture param "sqlite" + capabilities + seed-helper), `src/mnemosyne/cli.py` (backend choices + selection), `src/mnemosyne/mcp_server.py` (same), `config/drift-baseline.toml`, `tests/test_config_drift.py`, `CONFIG-DRIFT-CHECKS.md`; Test: the whole contract suite.

**Interfaces (R2/R3/R7):** fixture: `params=["local", "postgres", "sqlite"]` (sqlite = tmp root dir, no DSN needed → contract tests RUN by default, no skip); `engine_capabilities` adds `frozenset({"sqlite_file", "fts5"})`-appropriate flags — audit every capability-gated test for correct sqlite behavior (graph_ppr_cache_table gates stay Postgres-only; live_db stays Postgres-only). Seed-helper TypeError contract (R7). CLI/MCP: `choices=["local","postgres","sqlite"]` at the R2-cited literals + engine construction path (root dir from store-path-style flag) — grep ALL choices sites (R2 lists them). drift-baseline `[topology].backends += "sqlite"`, test_config_drift literals, CONFIG-DRIFT-CHECKS Configuration sources (+ explicit note: production topology remains Postgres-only; sqlite there = check-D drift).

Steps: fixture first (watch the contract suite fail per missing behavior — this is the acceptance run for Tasks 2-9; fix SqliteEngine, not tests) → CLI/MCP wiring + drift artifacts → full suite + DSN parity + `MNEMOSYNE_PURE=1` → commit `feat(sqlite): third engine behind contract fixture, CLI/MCP backends, drift artifacts`.

### Task 11: DST/chaos harness + differential oracle + lane invariants

**Files:** Create `tests/chaos/__init__.py`, `tests/chaos/conftest.py` (gated: skip unless `MNEMOSYNE_CHAOS=1` — mirror benchmarks conftest pattern, R2), `tests/chaos/test_sqlite_chaos.py`, `tests/chaos/test_differential_oracle.py`; Modify `.github/workflows/ci.yml` (nightly job stub, non-gating).

**Interfaces (spec §4.0/§8 + R3):** seeded workload generator (hypothesis or seeded random: append/upsert/branch/merge/forget ops), replayable by seed; fault injection: kill-9 subprocess mid-transaction (subprocess running a scripted op sequence, SIGKILL at randomized byte/time offsets), torn journal writes (byte truncation — reuse test_journal_properties pattern); post-fault assertions: `PRAGMA integrity_check` ok OR file recoverable via rebuild-from-ledger; ledger≡journal (torn-tail aware); projections rebuild-on-mismatch; honeytoken cross-tenant isolation under chaos (reuse honeytokens API). Differential oracle: same seeded workload applied to LocalMemoryEngine and SqliteEngine → export_tenant outputs equal (modulo documented format deltas — assert on normalized dicts). Lane invariants (Phase-0 deferral): predicates asserted over generated workloads — lifecycle lane never writes valid_to/superseded_by (identify the lane marker via consolidation.py ROLE_NAMES; if not assertable without full lifecycle machinery, implement the two cheap predicates the spec names over audit/deletion logs and DOCUMENT scope). Chaos-found failures → seed-pinned protected tests (ratchet).

Steps: harness → run 100+ seeds locally (record pass) → nightly CI stub (`MNEMOSYNE_CHAOS=1`, continue-on-error until soak) → commit `test(chaos): seeded DST harness, differential oracle, lane invariants`.

### Task 12: L4 poison corpus + ops-checks + observability

**Files:** Modify `tests/completion/security/poison_runner.py` (engine-neutral tombstone probe), Create `tests/completion/security/test_poison_corpus_sqlite.py`; Modify `src/mnemosyne/cli.py` (ops-check backend parameterization); Modify `src/mnemosyne/sqlite_engine.py` (observability signal emission); Test all.

**Interfaces (R2/R6):**
- Poison: refactor `_eval_tombstone_replay` to an engine-neutral probe (public erased-evidence accessor — add `get_evidence`-based probe or a small `evidence_is_erased(tenant, branch, cid) -> bool` engine method to the contract; fixes the pre-existing PostgresEngine gap too); new test module = `tools_factory=lambda: MemoryTools(SqliteEngine(fresh tmp root))` per case; assert ≥95% overall + per-category, 100% deterministic gates, 0.0 false-positive rate, benign controls surfaced (mirror test_poison_corpus.py assertions exactly).
- Ops-checks: parameterize the backend-acceptance sets — retrieval-ops-check accepts `sqlite` backend evidence with `sqlite-fts5`/`sqlite-cached-ppr` names (still non-`local-`); auth-ops-check accepts `tenant_isolation.sqlite_file_per_tenant: true` as the RLS-analog (new requirement key, documented); provenance-ops-check accepts ingestion backend `sqlite`. Guard: production-profile bundles must STILL require postgres (the parameterization is profile-scoped — production manifests unchanged; add tests proving a production bundle with sqlite backend still FAILS).
- Observability: SqliteEngine emits the checklist §1-3 signals via the existing observability.py surface (R6): evidence-durability (journal fsync count/lag), rebuild-lag (projection watermark deltas), per-write audit stream (already via _audit), erasure-propagation log (deletion_log + cache/journal steps recorded in propagated dict).

Steps: TDD → implement → run the sqlite poison corpus (must hit the SLO floors — if a category fails, fix the ENGINE, the corpus is protected) → suite → commit `feat(sqlite): L4 corpus green, ops-check sqlite profile, observability signals`.

### Task 13: Benchmarks + phase exit

**Files:** Modify `tests/benchmarks/test_retrieval_baselines.py` (sqlite fast-path bench: seeded 10k items, retrieve p-mean vs §22.5 owned budget under MNEMOSYNE_BENCH_ABSOLUTE; relative gate vs captured sqlite baseline), `docs/superpowers/plans/2026-07-01-native-acceleration-program.md` (Phase 2 → DONE), ledger.

Exit checklist (all recorded with real output): full suite native + pure; DSN-armed parity; contract suite (three engines); chaos 25-seed smoke; sqlite poison corpus; benchmarks (+ absolute run on this Mac); ruff; drift tests; both-directions optional-extra sync (`sqlitevec` present/absent). Per-tenant isolation ADR: `docs/adr/0001-sqlite-per-tenant-file-isolation.md` (RLS-analog argument, journal/at-rest posture per spec §4.0 note, Q-SEC-1 reference). Commit `docs(phase2): sqlite engine complete — exit verification + isolation ADR`.

---

## Self-Review (authoring time)

1. **Spec §4.2 coverage:** per-tenant files/WAL/integrity → T2; branch=row-copy, merge=shipped replay-upsert, VACUUM INTO snapshot only (T6 — snapshot/export explicitly NOT implemented this phase; ledger it); FTS5-prefilter-only + rescore → T4; sqlite-vec optional + kernel fallback → T4; cached-PPR projection → T8; as-of → T5; queue → T6; O(change) writes → T2/T3 by construction; A1 cache with privacy rules → T8; watermarks → T2/T8; erasure §4.2/§7 → T9; drift/ops-check/L4/observability → T10/T12; chaos+oracle+lane invariants+ratchet → T11; §4.6 SLO benches → T13. §4.0 remainder (pipeline extraction) → T1. Phase-0 handoffs: repair-before-append → T9; lane invariants → T11; projections TOCTOU note → T8 registrant docs; _fsync_dir promotion → T2 (3rd consumer arrives: do it there).
2. **Oracle-first discipline:** every SqliteEngine behavior is pinned to LocalMemoryEngine comparisons, not to the spec's aspirations; where spec > shipped (async telemetry, cross-branch erasure, deletion-log HMAC), the plan names the resolution explicitly (parity-first with documented deviation, except HMAC which the spec mandates cross-engine and T9 implements).
3. **No invented symbols:** every cited symbol traces to the grounding file (R1-R7) with re-grep instructions; the two genuinely new modules (pipeline.py, erasure_ids.py, sqlite_*) define their own interfaces in full.
