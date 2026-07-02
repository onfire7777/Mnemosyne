# Mnemosyne Native Acceleration Layer — Design

**Date:** 2026-07-01 (v2 — post documentation-alignment review)
**Status:** PENDING USER APPROVAL
**Authority:** subordinate to the blueprint (`docs/blueprint/`) and `docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`; where this doc conflicts with either, they win.
**Review provenance:** v1 was audited by a five-auditor documentation-alignment review (blueprint core, production gates, lifecycle/merge/rollback, privacy/eval, adversarial code critic) with the 12 most serious findings adversarially verified against source files. All confirmed findings are incorporated below.

## 1. Goal and constraints

Deliver the largest achievable performance and quality gains via **surgical Rust adoption at existing contract seams**, with:

- **Zero feature loss, zero destructive change.** The ~48k-line Python core (security gates, §31 rails, bitemporal beliefs, 11-role consolidation, conformal calibration, provenance) remains authoritative. No gate weakened, no rail modified, no Postgres schema change.
- **Local-first as the center of gravity** (blueprint constraint envelope: no-GPU ~16 GB Mac baseline).
- **Byte-parity determinism** on the default path: native compute produces bit-identical results to pure Python; the pure path remains a first-class automatic fallback. Explicitly **approximate tiers** (ANN indexes, quantized candidate scans) sit outside the byte-parity guarantee: they are candidate-generation only, always exact-f64-rescored, disabled in parity mode, and governed by the projection-registry rebuild rules (§4.0).
- **Blueprint §22.5 latency contract:** fast-path memory overhead P95 ≤ 300–400 ms. CI gates on the owned §22.5 budget; the tighter internal target (P95 ≤ 200 ms full pipeline) is a **non-gating** benchmark floor unless the owning lane formally tightens §22.5. Live PPR stays deep-mode-only; **cached PPR signals serve the fast path** (§22.2, FR-11, §30.4).
- **The parity suite is the acceptance harness** for every phase, as it proved Local↔Postgres equivalence.

### Measured baselines motivating this design (2026-07-01, M-series Mac)

| Hot path | Today (pure Python) |
|---|---|
| `cosine` 1024-dim | 44 µs/call (~23k/s) |
| `hashing_embedding` 80-token doc (cold) | 96 µs/doc |
| `lexical_score` scan, 2k docs | 71 ms |
| `tokenize` | 41 MB/s |
| Local `_persist()` | O(entire store) JSON rewrite per mutation (`engine.py:445`) |
| `import mnemosyne.cli` | ~270 ms cold / ~146 ms warm (`cli.py` itself ≈4 ms; cost is transitive imports shared with `mcp_server`) |
| Python MCP server cold start | ~615 ms / ~97 MB RSS (Rust rmcp reference: ~38 ms / ~7 MB) |

## 2. Decision record (verified research, 2026-07-01)

1. **PyO3 0.29 + maturin 1.14, mixed layout, abi3-py312 wheels.** Rust float semantics are strict IEEE-754 by default (RFC 3514): no FMA contraction, no reassociation → scalar sequential loops are bit-identical to CPython. Kernel-crate lint bans `mul_add` and transcendentals; shared surface is `+ - * / sqrt abs`. maturin has no pure-fallback mode → try-import dispatch with `MNEMOSYNE_PURE=1` override; both paths in CI.
2. **`hashlib.blake2b(digest_size=8)` ≠ truncation** — digest length lives in the parameter block. Rust uses `Blake2bVar::new(8)`; golden vectors prove equality.
3. **CID canonicalization stays in Python.** Python float `repr` differs from Rust float formatting in edge cases; Rust never computes CIDs.
4. **Storage: stdlib `sqlite3`, one file per tenant.** SQLite is the only embedded engine speaking enough SQL to pass a parity suite written against Postgres semantics. sqlite-vec (brute force) now; ANN upgrade paths: sqlite-vec DiskANN alphas and SQLite's official `vec1`. libSQL is in maintenance; DuckDB vss persistence experimental; Kuzu archived.
5. **Turso Database: fork REJECTED; adopt-later with engineered optionality.** 17-agent adversarially-verified evaluation: (a) every functional Turso gap is neutralized app-side — Mnemosyne contains zero recursive SQL (PPR is app-side power iteration in both engines); (b) fork economics fail (~98 upstream commits/week concentrated where we'd patch; flag-gated experimental index trait; open corruption-class MVCC bugs; beta warning in Turso's own manual); (c) optionality is free — with the §4.0 seam hardening, a future `TursoEngine` is a ~1–2 person-month adapter. Revisit triggers in §9.
6. **Embedder/reranker (local quality tier):** fastembed-rs with EmbeddingGemma-300M-Q (dims follow the configured `MNEMOSYNE_EMBEDDING_DIMS` via MRL truncation) and jina-reranker-v1-turbo-en (≤50 candidates). potion-retrieval-32M as the cheap ingest/candidate tier. The hashing embedder remains the deterministic default for tests and fallback. **These are candidates in — not replacements for — the production doc's bake-off** (arctic-embed-l-v2.0 @1024d and the bge/gte reranker pair); production profile model/dims values are not changed by this design.
7. **Front-end:** official Rust MCP SDK `rmcp` (0.16.x pinned) + warm-daemon pattern over a unix socket. Embedding CPython in the binary rejected (doesn't remove import cost; distribution pain). Honest scoping from review: MCP stdio servers spawn once per client session, so the ~615 ms cold start is per-session, not per-call — C4 is therefore **gated on measured evidence** that session-spawn latency matters for a real workflow (short-lived CLI-style MCP invocations), and A4 (lazy imports) ships first.
8. **Market positioning (verified):** no leading memory system ships a Rust serving layer; sub-second p95 retrieval is the published bar. **Public performance claims rest on our measured latency/SLO numbers and the §33 private regression suite; public benchmark sets (LongMemEval, LoCoMo, …) are internal sanity gates only, never headline claims (§9).**

## 3. Architecture

Rust enters at exactly four existing seams; each already has a contract and tests guarding it.

```
                    ┌─ Seam 4: front-end ─────────────┐
  MCP client ──────▶│ mneme-native (Rust, rmcp stdio)  │  ~40 ms handshake
  CLI user ────────▶│ auto-starts warm Python daemon   │  (gated: see §4.4)
                    └───────────┬─────────────────────┘
                      unix socket (0600, peer-uid checked)
                    ┌───────────▼─────────────────────┐
                    │  Python core (UNCHANGED logic)   │
                    │  engine contract · security ·    │
                    │  rails · consolidation · calib   │
                    └──┬──────────────┬───────────────┘
        Seam 1: kernels│              │Seams 2+3: engine + providers
                    ┌──▼───────────┐ ┌▼────────────────────────┐
                    │ mnemosyne.   │ │ SqliteEngine (3rd engine │
                    │ _native      │ │  behind MemoryEngine     │
                    │ (PyO3 crate) │ │  contract; per-tenant    │
                    │ byte-parity  │ │  files, FTS5, sqlite-vec)│
                    │ kernels +    │ ├─────────────────────────┤
                    │ pure-Py      │ │ mneme-providers (Rust    │
                    │ fallback     │ │  sidecar, local profile; │
                    └──────────────┘ │  existing Http* contract)│
                                     └─────────────────────────┘
```

**Explicitly out of scope (non-destructive guarantee):** rewrite of engine/consolidation/security logic; removal of the JSON store or in-memory engine; gate/rail modification; Postgres schema changes; Rust-computed CIDs; forking any upstream database.

## 4. Components

### 4.0 Phase-0 engine-seam hardening (prerequisite, no Rust)

**Shared algorithm extraction — scoped to what is actually duplicated** (review-corrected): the `retrieve()` orchestration pipeline (`engine.py:1426ff` vs `postgres_engine.py:2332ff`), `_rrf`, `_mmr`, `_u_curve_order`, `_fit_budget`, and PPR power iteration (`engine.py:1369` vs `postgres_engine.py:2044`) move to one engine-agnostic module. NOT extracted: `lexical_score` and activation scoring (already single-source via `mnemosyne.text` / `retrieval.py:1501`); PostgresEngine's SQL lexical channel (`ts_rank_cd`, unchanged). MMR embedding sourcing differs between engines today (adapter+stored-embedding gate vs hashing) — it is **parameterized per engine**, not unified (no behavior change). Without this extraction SqliteEngine would become a third ~1000-line copy of the retrieve/abstention logic.

**Gate-name stability (Phase-0 exit criterion):** externally reported provider/backend identifiers (`postgres-recursive-ppr`, `postgres-fts`, and the `local-*` names the forbid_local denylist keys on) are byte-identical after extraction, asserted by test. The extraction is an internal relocation; the SLO-proven Postgres retrieval behavior stays byte-identical (parity suite as proof), reconciling with SELF-HOSTED §7's do-not-touch list.

**`ENGINE-CONTRACT.md`** — the storage surface any engine must provide, in two layers:
- *Storage primitives:* (a) append-only ledger writes with CID verification; (b) flat scans filtered by tenant/branch/valid-window **returning the full §19 meta-envelope** (status, trust_tier, fidelity, confabulation-risk flag — the §22.3 filter and §26 calibration depend on them); (c) plain-term lexical candidate retrieval; (d) vector top-k (exact, or ANN + exact re-rank); (e) transactional projection rebuild + per-projection watermarks; (f) `embedding_partition` split and never-embed rules; (g) branch create/discard and branch-scoped visibility; (h) as-of (bitemporal) reads; (i) cached graph-signal read (`graph_ppr(use_cache=True)` shape); (j) durable queue lease surface.
- *App-side compositions (documented, proven in the parity suite):* retrieval pipeline, PPR computation, merge semantics, RRF/MMR/U-curve/budget, activation, calibration. Engine-specific channel names are forbidden in the contract but preserved verbatim in each engine's reporting surface (gate-name stability above).

**Parity suite parametrization:** the engine fixture already exists (`test_shared_engine_contract.py:213`); Phase 0 additionally triages every `isinstance(engine, …)` branch in that suite (each becomes contract-level behavior or a documented engine-specific extension), so "a fourth engine = one fixture" becomes true before Phase 2 relies on it.

**CID journal (per tenant):** every ledger append is also written to an append-only canonical-JSON journal. **Ordering & authority:** engine transaction commits first; journal append+fsync follows; on divergence the engine ledger is authoritative and the journal segment is re-derived from it; a journal CID absent from the ledger raises an alarm (anomaly, not auto-repair). The nightly integrity run asserts ledger≡journal for all engines from Phase 0 on. **At-rest posture:** journal and tenant DB files participate in the deployment's at-rest encryption/KMS model so `hard_delete_legal` can key-shred (or an ADR explicitly documents and accepts the local-first deviation); privacy-ops-check-style shred verification covers both (Phase 2).

**Projection registry:** every derived index (FTS, vectors, graph tables, **cached-PPR vectors**) is a named, versioned, fingerprinted rebuildable projection with rebuild-on-mismatch. ANN and quantized tiers live here, always exact-rescored.

**Determinism harness (right-sized, review-corrected):** Phase 0 ships hypothesis-based property tests over the CID journal (append-only-ness, rebuild determinism) plus cheap replay-checkable lane invariants (lifecycle lane-L never writes `valid_to`/`superseded_by`; no contested item closed by lifecycle retirement). The full DST/chaos harness (seeded fault injection: kill-9 mid-transaction, torn journal writes; `LocalMemoryEngine` as differential oracle; nightly seeded-chaos run) lands in **Phase 2**, where SqliteEngine provides real multi-file fault surfaces. TLA+/Quint is an optional stretch, not a deliverable. **Ratchet:** every chaos-found failure becomes a seed-pinned permanent protected test before its fix ships (eval plan §6.1).

**Honeytokens:** Phase 0 seeds per-class honeytoken memories; tests assert they never appear beyond their class boundary in the CID journal, the embedding cache (when non-embeddable), sidecar/front-end logs, benchmark output, or chaos artifacts; appearance fires the privacy §10 alarm.

### 4.1 C1 — `mnemosyne._native` kernel crate (PyO3)

Byte-parity kernels: `tokenize`, `lexical_score`, `hashing_embedding` (Blake2bVar(8)), `cosine`; batched `dense_scan` (vector-channel candidate scoring) and `mmr_select` (**slotted at the post-rerank `_mmr` stage**, matching the shipped pipeline — not the candidate scan).

**Kernel ABI (review-mandated precision):** inputs = (query_vec, row-major f64 matrix with validity mask, base_scores, λ); semantics reproduce the shipped code exactly: dot-product with zip-truncation on dims mismatch (`text.py:68`), `score > 0` filtering stays with the caller, MMR objective = λ·relevance − (1−λ)·max_similarity **+ base_score** (`engine.py:2791`), missing-vector rows = relevance 0 with no diversity penalty. **Matrix assembly stays in Python** — `_embedding_for_hit` runs per-hit security decisions; the seam is "matrix + base scores in, indices/scores out". Kernels return scores **aligned to input order**; Python keeps doing the stable sort. Any Rust-side ordering uses (score desc, input-index asc); `mmr_select` breaks argmax ties by lowest input index. Phase-1 golden vectors include tie-saturated cases (duplicate texts, equal RRF ranks) and dims-mismatch/missing-embedding rows.

**Parallelism:** rayon across items only; per-item op order unchanged → parity-safe. **Quantization (review-corrected):** int8/f16 scans are an explicitly **approximate candidate-generation tier** — excluded from the byte-parity guarantee, disabled in parity mode, final scores always from exact f64 rescore, adoption governed by the same registry rules as ANN. Dispatch: try-import + `MNEMOSYNE_PURE=1`; startup log line states the active path. Wheels: macOS arm64, linux x86_64/arm64, abi3-py312.

### 4.2 C2 — `SqliteEngine` (pure Python; third `MemoryEngine` backend)

- One file per tenant (`.mnemosyne/tenants/<tenant>.db`; WAL, `synchronous=FULL`, integrity-check on open). Isolation: tenant-id→file-path binding (ADR documents the RLS-vs-file model). GDPR delete = file delete.
- **Branch/fork (review-corrected):** branch = in-file branch-scoped row copy, exactly matching `PostgresEngine.branch()` semantics and cost class (O(branch source rows)); `VACUUM INTO` is reserved for whole-tenant snapshot/export, and long-lived detached copies are forbidden unless registered (erasure must be able to enumerate them). Cost classes stated so Phase-2 tests can assert them.
- **Merge (review-corrected):** SqliteEngine merge reproduces the **currently-shipped replay-upsert semantics** that the cross-engine parity suite tests (`test_parity_merge_branch_into_main`). Full Conflict-Resolution §6 three-way merge (LCA merge base, resolution records, deciding_axis) is **implemented in no engine today** and is deferred blueprint work (Phase 6 candidate, engine-agnostic layer for all three engines). Any future changeset-based fast path must produce byte-identical resolved truth and pass the merge-policy §10 replay-stability/commutativity/idempotency criteria before adoption.
- **Channels:** FTS5 as **candidate pre-filter only**, re-scored app-side with the shared `lexical_score` (mirroring `PostgresEngine._local_rank`); per-term quoting/escaping defined for MATCH; tokenizer-mismatch tests (hyphenated tags, version strings) in Phase 2. sqlite-vec dense channel with **fallback**: if `enable_load_extension` is unavailable or the extension fails to load, the vector channel falls back to the kernel-accelerated exact `dense_scan`, with a doctor/startup line reporting the active channel implementation (CI tests this path). **Cached-PPR projection** (consolidation-computed, watermarked, registry-managed) serves the fast-path graph channel — the exact pattern the repo already ships (`GraphSignalCache`, `graph_ppr(use_cache=True)`); live PPR stays deep-only. Bitemporal as-of; durable queue table with leases.
- **Writer concurrency (review-mandated):** WAL + `busy_timeout` with defined retry semantics for the daemon-free CLI path; when the daemon socket is present the CLI auto-routes **writes** through the daemon (reads stay direct under WAL). Phase-2 live test: concurrent CLI append + daemon consolidation on one tenant file.
- **Read-strengthening telemetry (§22.7):** `last_accessed`/`access_count` updates are batched async appends (blueprint §18 classifies them as telemetry, not truth mutation → relaxed durability is acceptable), folded in by the warm loop; base-level activation inputs verified correct.
- Schema carries the full §19 meta-envelope (fidelity, confabulation-risk flag, status, trust_tier); fidelity feeds §26 calibration/abstention through the new fast path; round-trip parity cases included.
- Replaces O(store) `_persist()` with transactional incremental writes. JSON store and in-memory engine remain supported, unchanged.
- **A1 embedding cache (review-corrected for privacy):**
  - **Admission** = the same predicate as the embedding-partition rules: {S4, `embed_ok:false`, restricted, held, unknown-policy} are never cached; S3 cached only under the sensitive-embedding deployment flag. Covers evidence-content embeddings only (redacted/derived retrieval texts are not CID-addressable and are excluded).
  - **Key scoping:** for S2+ content the key is subject/branch-scoped (per-subject salted CID exactly as the privacy policy mandates), so a cross-subject probe is indistinguishable from a miss — including in hit-rate telemetry granularity. This closes the `dedup_oracle_cross_subject_s2plus` rail violation found in v1.
  - **Read side:** cache reads pass the same `may_use_stored_embedding`/`may_read_item` gate as stored embeddings; a denied context gets a miss-equivalent, never the cached vector.
  - **Purge triggers:** both erasure modes **plus** restriction-of-processing, hold, and consent-withdrawal, within the policy's propagation window. Privacy test classes 10 (dedup oracle) and 13 (no `sha256(guess)` confirmation post-erasure) run in Phase 2.
- **Erasure (review-corrected, mode-aware):** `tombstone_recompute` → journal rewrites erased entries as tombstone records (retained CID — already subject-salted for S2+ — + timestamps + erased marker), preserving the erased-replay blocklist on rebuild; `hard_delete_legal` → full exclusion plus key-shred under the at-rest model. Post-erasure parity assertion: ledger rebuild ≡ journal rebuild in both modes. Projection cleanup is **targeted invalidation** of rows for affected CIDs (full rebuild only as fingerprint-mismatch fallback). Erased CIDs in retained compaction/deletion/watermark records are replaced with random/HMAC ids. Erasure propagates to all branches in the tenant file and all registered snapshot copies; erased items are excluded from merge candidacy (merge policy E0).
- **Config-drift artifacts (Phase-2 exit):** `config/drift-baseline.toml` backends + `test_config_drift.py` + CONFIG-DRIFT-CHECKS.md "Configuration sources" updated for the third backend and new env surface (`MNEMOSYNE_PURE`, daemon socket, sidecar endpoints, tenant db paths). **Production topology remains Postgres-only:** SqliteEngine in a production/postgres topology is environment drift under check D, exactly like the JSON store today.
- **Verifier coverage (Phase-2 exit):** the four ops-check bundles (privacy/retrieval/auth/provenance) and the canonical policy's §9 protected-suite cases run green against SqliteEngine; the engine emits the observability checklist's evidence-durability, rebuild-lag, per-write audit-stream, and erasure-propagation signals (cache purges and journal compaction steps included in the propagation log).

### 4.3 C3 — `mneme-providers` (Rust sidecar; fastembed/ort)

Serves the existing `HttpEmbeddingProvider`/`HttpReranker` contracts. **Profile scoping (review-corrected):** C3 is a **local-profile provider**. Its localhost URL would fail the production locality gates by design (non-loopback + real-CA); if it ever backs the production profile it must be deployed like the existing `embedder` service — internal network behind the Caddy alias, non-loopback HTTPS profile URL, models baked into the image (no egress), `<<: *hardened`, no published ports — so it passes `test_prod_compose_policy` and retrieval-ops-check unchanged.

Models: EmbeddingGemma-300M-Q embeddings (dims follow `MNEMOSYNE_EMBEDDING_DIMS` via MRL), jina-reranker-v1-turbo-en (≤50 candidates), optional potion-retrieval-32M endpoint. **Embedding-space discipline:** potion vectors are a separate registered projection used only for candidate generation with exact rescoring in the quality space; stored and query-time quality vectors share one `model_id`/`embedding_version`; mixing spaces in one distance computation is forbidden. **Default-flip methodology:** the Phase-3 bake-off binds to eval-plan §7/§6.6 — strict judge, confidence intervals, margin-exceeds-noise required before any provider becomes a default. **Logging boundary:** C3 never logs request/response bodies, embeddings, credentials, or tenant/user values — fingerprints only; honeytoken-based log-redaction test in Phase 3.

### 4.4 C4 — `mneme-native` front-end (Rust binary; rmcp) — **gated**

**Sequencing (review-corrected):** A4 (lazy imports) ships in Phase 1 and covers both `cli.py` and `mcp_server.py`'s eager import graph (the measured cost is transitive imports — `cryptography.x509`, consolidation, ingestion, media — shared by both entry points). C4 proceeds only on measured evidence that per-session spawn latency matters for a real client workflow; its first-request latency still pays full Python daemon startup after auto-spawn, and the spec says so.

**Daemon trust boundary (review-mandated):** socket at 0600 in a per-user runtime dir; peer-uid (LOCAL_PEERCRED) verification on accept; daemon identity = (binary version, config fingerprint) — a client with a different config fingerprint gets a separate daemon, not a shared warm engine; requests are explicitly serialized (the engine assumes one client); a daemon with no auth/session config refuses non-owner peers.

**Production profile:** the daemon honors `MNEMOSYNE_MCP_PRODUCTION_PROFILE`/`MNEMOSYNE_MCP_REQUIRE_SESSION` identically to the Python server (refuse-start when preconditions unmet); the **raw session token** traverses the socket and is verified by the Python daemon, which holds session-verifier custody — claims are never Rust-side pre-verified nor reconstructed from tool arguments. The C4 streamable-HTTP listener is loopback-only and off-by-default locally (service-credential class per the secret-handling taxonomy; Q-SEC-1 referenced in the ADR) and is **out of scope for production B3 evidence** unless placed behind Caddy with the same profile gates. MCP conformance covers **every tool in `TOOL_SPEC` (currently 50)**, derived programmatically so the criterion cannot drift.

### 4.5 A3 — Consolidation quality tier (scope-corrected)

The role-LLM ladder (frontier command-backed → `qwen3:4b` → deterministic) applies **only to proposal/generation roles** (extractor, summarizer, lesson-distiller, procedure/skill-inducer). The write-decision predicate, precedence ladder, Forgetter dispositions, and promotion-gate evaluation remain deterministic rule-based code — **no model call at decision time** (merge policy §3/§10.2; lifecycle §13.3 Forgetter purity). Frontier outputs are **recorded as proposals in the ledger** so consolidation replay consumes recorded proposals and idempotency holds despite model nondeterminism. Per-role scoping follows blueprint §28: frontier tier eligible only for low-volume, high-stakes passes (hard contradiction resolution, skill induction); cheap/local tier is the default for high-volume passes; the `consolidation_cadence_bounds` rail bounds total frontier spend.

**B-model disclosure invariants (privacy §8) as acceptance criteria:** bounded PII-redacted gist packets preserved on the frontier path; S3+ never sent verbatim to a retentive/out-of-region endpoint; S2 only to contracted zero-retention in-region endpoints, else pseudonymized with per-disclosure salting; disclosure-axis gate tests in Phase 3. **Tier-B:** enabling the frontier tier in a production profile requires a fresh §9.2-item-1 evidence capture (gist-packet proof + no-raw-prompt-logging proof) — the blanket "no capture re-run" claim from v1 is narrowed accordingly.

### 4.6 A6 — Benchmark + SLO regression harness (Phase 0)

criterion (Rust) + pytest-benchmark (Python) capture today's baselines. **CI gates on the owned §22.5 budget (300–400 ms)**; the 200 ms internal target is a non-gating benchmark floor. The harness **feeds** the observability checklist's §1 signals (it does not restate or alter SLO targets — that lane verifies, it does not own thresholds). **Tiered gating (review-corrected):** CI enforces *relative regression* vs captured baseline at ~10k items (absolute budgets on shared runners are flaky); the reference-Mac nightly measures the absolute 100k-item budget. If 100k-at-P95 is a launch requirement, the ANN/MRL-truncation decision moves into Phase-2 exit criteria. **LongMemEval is an internal sanity gate only** (strict judge, confidence intervals, corpus exceeding the context window, per eval plan §5); public evidence = measured latency/SLO numbers + the §33 private regression suite.

## 5. Data flow

**Fast path (local) — matches the shipped pipeline (`engine.py:1431–1443`), with native kernels slotted in:**
query → front-end → daemon (socket) → **security gate/session** → query embedding (cache → sidecar; see write path for space discipline) → channels: dense (sqlite-vec or kernel `dense_scan`), lexical (FTS5 pre-filter → shared `lexical_score` rescore), **cached-graph (cached-PPR projection)** → trust/validity filter (envelope fields) → RRF → cross-encoder rerank ≤50 → MMR dedup (kernel `mmr_select`) → **activation scoring → U-curve ordering → token budget → provenance tags + packet confidence → conformal abstain** — all of which remain unchanged in Python. Budget: ~5 ms transport+gate, 10–50 ms query embedding (sidecar model), 10–25 ms candidates, ~5 ms fuse, 50–150 ms rerank, ~5 ms MMR+activation, ~10 ms assembly → internal target P95 ≤ 200 ms; owned gate at §22.5's 300–400 ms. Deep mode unchanged (live app-side PPR, exhaustive traversal, async). *Known blueprint-vs-code gap, out of scope here and documented:* preference/procedure/lesson as first-class fast-path channels (§22.2) are not in the shipped `retrieve()` fan-out today; candidate for Phase 6.

**Write path (review-corrected — §20 "synchronous, cheap, never blocks on compilation"):**
capture → gate/sanitize → CID (Python) → ledger insert (engine txn) → CID-journal append+fsync (ledger authoritative on divergence) → **cheap synchronous cache lookup only**; on miss, embedding is **enqueued for the warm-loop Embedder role** (or embedded synchronously only with the cheap deterministic/potion tier, upgraded asynchronously with an `embedding_version` bump per §28). **Ledger insert and CID journal never wait on the providers sidecar.** Dense-channel staleness until the Embedder runs is the blueprint's own accepted design.

**Consolidation:** queue lease → 11 roles (unchanged) → role-LLM ladder (§4.5) → promotion gate → projection writes + watermark bumps (including the cached-PPR projection refresh). **Prioritized replay selection lives in the Replayer role independent of queue arrival order** (importance·novelty·surprise·reward, §21/§30.5); a behavior test asserts high-surprise episodes consolidate first.

## 6. Error handling & fallback semantics

| Failure | Behavior |
|---|---|
| `_native` missing/broken | try-import → pure-Python kernels; byte-parity ⇒ identical results. `MNEMOSYNE_PURE=1` forces; startup log states path. |
| sqlite-vec unavailable | vector channel falls back to kernel-accelerated exact scan; doctor/startup line reports active channel implementation. |
| `mneme-providers` down | health checks → hashing embedder / local-similarity reranker (today's behavior). **Capture is unaffected** (embedding is off the write path). Production fail-closed rules unchanged. |
| Daemon dead/stale | front-end auto-spawns; (version, config-fingerprint) mismatch → separate daemon; socket errors surface as MCP errors. Python entry points always work daemon-free. |
| SQLite writer contention | WAL + `busy_timeout` + defined retry; CLI writes auto-route via daemon when socket present; live concurrency test. |
| SqliteEngine file corruption | per-tenant blast radius; projections rebuild from ledger; ledger dual-written (engine + journal); integrity-check on open; nightly run proves rebuild. |
| Journal divergence | engine ledger authoritative; journal segment re-derived; journal-only CIDs raise an alarm. |
| Embedding cache | admission/read gates per §4.2; miss = enqueue; purge on erasure/restriction/consent events; never consulted for CIDs. |
| Parallel scans | rayon across items only; ties broken by input index; tie-saturated goldens guard it. |
| ANN / quantized tiers | approximate candidate generation only; exact f64 rescore; registered projections — fingerprint mismatch ⇒ rebuild; disabled in parity mode. |

## 7. Security & privacy invariants (acceptance criteria)

- All reads/writes traverse the Python security gate; C4 proxies raw session tokens to the Python daemon for verification; identity never derives from tool arguments; the daemon enforces production-profile refuse-to-boot semantics identically to the Python server.
- Ranking side-channels: redaction is applied after the access decision and **before ranking returns candidates**; `dense_scan`/`mmr_select` consume partition-aware vectors (private-partition raw vectors only for raw-authorized callers; redacted-projection vectors otherwise); the C3 reranker scores the disclosure form the caller is entitled to. The canonical policy's redaction-vs-drop and raw-vector-ranking test cases run in Phases 1–2.
- Embedding cache: admission predicate, subject-scoped S2+ keys, gated reads, extended purge triggers (§4.2); privacy test classes 10 and 13.
- Erasure: mode-aware journal handling (tombstones vs exclusion), targeted projection invalidation, HMAC replacement of erased CIDs in retained records, propagation to branches/snapshots/cache within the bounded window, merge-candidacy exclusion (E0), at-rest key-shred coverage.
- Honeytoken leak canaries seeded per class across all new boundaries (journal, cache, sidecar/front-end logs, benchmark output); appearance fires the privacy §10 alarm.
- C3/C4 emitting boundaries: no content/secret logging (fingerprints only), per secret-handling P4.
- Tier-B: the capture path (gates, manifest template, profiles, preflight) is unchanged; nothing here alters production profile values. Phases landing before the pending operator capture must be parity-green so captured evidence reflects the refactored code. The A3 frontier path requires its own fresh §9.2 capture before production enablement.
- Production topology remains Postgres-only; SqliteEngine there is environment drift (check D).

## 8. Phased delivery (each phase independently shippable; native pieces off-by-default for one release, then flipped after soak)

- **Phase 0 — Seam hardening + harness:** rescoped algorithm extraction + gate-name-stability test; ENGINE-CONTRACT.md (two-layer surface); parity-fixture isinstance triage; CID journal (+ authority rule, at-rest posture); projection registry; A6 harness (tiered gating); hypothesis property tests + lane invariants; honeytoken seeding.
- **Phase 1 — Kernels (C1) + A4:** golden vectors (incl. blake2b, tie-saturated, dims-mismatch); proptest/hypothesis bit-equality; parity green under `MNEMOSYNE_PURE=0/1`; wheel matrix; ranking-side-channel tests for kernel inputs; lazy imports for `cli.py` + `mcp_server.py`. Exit: ≥10× measured on scan benches, zero parity diffs, CLI ≤100 ms.
- **Phase 2 — SqliteEngine (C2 + A1 + watermarks + cached-PPR projection):** contract + parity fixture green; fork/merge (shipped semantics + §10-style replay/commutativity tests scoped to them)/as-of/queue live tests; DST/chaos harness + differential oracle + nightly run; writer-contention test; FTS5 tokenizer tests; sqlite-vec fallback CI leg; erasure suite (both modes, forks/branches, cache, journal, HMAC ids, test classes 10/13); drift-baseline + CONFIG-DRIFT-CHECKS updates; four ops-check bundles + protected privacy suite green; observability signals emitted; L4 adversarial suite (poison corpus ≥95% block rate, ≈0 utility drop) against SqliteEngine; ANN/MRL decision if 100k is launch-gated.
- **Phase 3 — Providers (C3) + A3:** sidecar behind Http contracts + health checks + logging-redaction tests; bake-off under eval-plan methodology (strict judge, CIs, margin>noise); scoped role-LLM ladder + recorded-proposal replay test + B-model disclosure gate tests; schedule the §9.2 frontier-path evidence capture.
- **Phase 4 — Front-end (C4), gated on measured spawn-latency evidence:** daemon trust boundary (socket perms, peer-uid, config-fingerprint identity, serialization); production-profile refusal test; raw-token verification over socket; MCP conformance derived from `TOOL_SPEC` (currently 50 tools); L4 suite re-run through `mneme-native`.
- **Phase 5 — Docs + ADRs:** per-tenant isolation model; at-rest/KMS posture (or accepted deviation); Q-SEC-1 custody posture; README claims updated with measured numbers (no public-benchmark claims).
- **Phase 6 — Designed, scheduled later:** IVM incremental maintenance on the watermarks; preference/procedure/lesson fast-path channels (blueprint-vs-code gap); full Conflict-Resolution §6 three-way merge in the engine-agnostic layer (all three engines); DiskANN/`vec1` adoption trigger; TursoEngine adapter spike per §9; Metal rerank contingency; free-threaded Python watch.

**Rollout guards (rollback guidance P5/P6/A7):** every flip and every reversion is a logged evidence event; a reverted component re-enters via the off-by-default (shadow) stage, never straight back to default; repeated flip-revert cycles freeze further flips pending investigation. **Engine cut-over procedure (rollback §4/A10):** pre-flip verification that the CID journal is complete and deterministic rebuild passes; the old JSON store is retained read-only through the soak window; rollback = flag revert + deterministic rebuild of the previous engine's state from the CID journal; the flip and any rollback recorded as evidence.

## 9. Turso revisit triggers (any one reopens the decision)

1. Beta warning removed / GA announced, MVCC corruption-class issues closed, encryption out of experimental → run the gated TursoEngine adapter spike (ledger stays sqlite3 + CID journal for the first release; Turso gets projections first, ledger custody only after journal-vs-engine divergence checks soak green).
2. COMPAT.md flips `WITH RECURSIVE` to supported → benchmark PPR-in-SQL vs kernel PPR; adopt only if it wins under the SLO.
3. Per-tenant relations near ~10⁶ edges or fast-path P95 over budget → redesign PPR (incremental/cached), engine-independent.
4. sqlite-vec breaks/abandoned → swap the vector projection to usearch (contract isolates it).
5. Team scale changes the economics, or Turso relicenses/is abandoned.

## 10. Success criteria

1. Parity suite green on all three engines and both kernel paths — zero byte-level diffs **in parity mode** (approximate tiers excluded by definition and validated separately via exact-rescore + quality harness).
2. Fast-path P95: CI-gated relative regression at ~10k items; reference-Mac nightly proves the absolute §22.5 budget (and the 200 ms internal floor) at 100k items/tenant.
3. Local write path O(change), not O(store); capture latency independent of the providers sidecar; re-embedding eliminated for repeated content (subject-scoped hit rates reported at privacy-safe granularity).
4. `mneme-native` MCP handshake ≤ 50 ms (first request after auto-spawn additionally pays Python daemon startup — stated, measured); pure-Python CLI ≤ 100 ms after A4.
5. Zero regressions: full test suite, six SLOs, seven rails, four ops-check bundles, protected privacy suite, and the L4 adversarial floors (≥95% block, ≈0 utility drop) green through every new component.
6. Nightly: ledger integrity + journal equivalence + full deterministic rebuild green, continuously; every chaos-found failure ratcheted into a protected test.
