# Performance Program — Full-Stack Speed Without Weakened Gates (2026-07-05)

**Status:** PROPOSED (analysis complete; no code changed). Written from a fresh
three-lane audit: native-accel program state, `src/mnemosyne/` hot paths, and
live runtime evidence from the deployed no-GPU stack.

**Prime directive (unchanged from the native-accel spec):** the pure-Python
path stays canonical; every accelerator is a byte-parity-proven speed decision,
never a behavior decision. No gate is weakened; misses are reported BLOCKED
with measured numbers.

---

## 1. Where the time actually goes (measured, ranked)

| Rank | Cost center | Evidence | Scale |
|---|---|---|---|
| 1 | **CPU-only role-LLM inside the colima VM** | qwen3:4b warm = 95–133 s/trivial call (~0.5 tok/s); forced downgrade to qwen3:0.6b; role timeouts 280–320 s | seconds–minutes per consolidation role call |
| 2 | **VM topology**: 4 vCPU / 10 GB colima hosting ~19 containers; explicit mem limits alone (ollama 6g + embedder 4g + kc 1g = 11 GB) exceed the VM; zero CPU limits anywhere | compose + worknotes PM5 | multiplier on everything |
| 3 | **Serialized consolidation role pipeline** (5 roles sequential per job) on top of #1 | consolidation.py:462-519 | minutes per job |
| 4 | **Engine orchestration Python** (see §3): conn-per-channel, double candidate scan, Python PPR, deepcopy RRF, sequential channels | agent-2 report | tens of ms today; scaling cliff at 10k–100k items |
| 5 | **fp32 torch CPU embedder/reranker**, single-item HTTP, no thread tuning | services/embedding | ms–tens of ms per embed, shares the 4 vCPUs |

Retrieval today is 11–147 ms and MCP transport 100–300 ms — NOT the constraint
yet, but several latent cliffs (unindexed evidence FTS, O(V·E) PPR mapping,
full-store double scans) will bite as the corpus grows.

What is already fast and must not be re-done: `mnemosyne-native` kernels
(cosine/dense_scan/lexical/tokenize/hashing/MMR — 40–82×, byte-parity, wired at
text.py:22, algorithms.py:144, engine.py:1270/1325), SqliteEngine packed-BLOB
dense (~43×, 9 ms retrieves), and the `mneme-providers` Rust sidecar (built,
bake-off pending, not defaulted).

---

## 2. Phase P0 — Measure first (no code; ~1 session)

1. Extend `tests/benchmarks/` + `eval/latency/` with **end-to-end** baselines:
   retrieve p50/p95 at 1k / 10k / 100k synthetic items per engine;
   consolidation job wall-clock per role; embed round-trip single vs batch.
2. Capture the **real MCP client-workflow trace** required by the Phase-4 gate
   (p50/p95 spawn/initialize/tools-list/first-call/warm-call + attribution).
   This either opens or permanently closes the Rust front-end question with
   data instead of vibes.
3. Record VM contention: per-container CPU seconds during a consolidation job.

Exit: committed baseline JSONs; every later phase must beat them, not vibes.

## 3. Phase P1 — Runtime right-sizing (config only; no code; biggest $/hr win)

1. Resize colima: `--cpu 6 --memory 12` (host is 16 GB; leave ≥4 for macOS).
2. Add `cpus:` limits so ollama/embedder/postgres cannot starve each other;
   right-size `mem_limit` so explicit ceilings sum ≤ VM memory.
3. Ollama: pin explicit quant (`qwen3:4b-q4_K_M` class), set `num_ctx` to the
   role-call envelope (roles are ≤700-token JSON outputs; default ctx wastes
   memory), keep `OLLAMA_KEEP_ALIVE=24h`.
4. Embedder: `torch.set_num_threads`/OMP pinning; switch callers to the
   existing `embed_batch` path (app.py:253) — the service already supports it.
5. Postgres: `work_mem`, `effective_cache_size`; add HNSW `ef_search` and
   explicit `m`/`ef_construction` choices (currently library defaults).

Exit: consolidation job wall-clock improvement measured against P0; no
functional change; all ops bundles unaffected (config drift doc updated).

## 4. Phase P2 — Host-Metal serving tier (THE dominant win; ~40–80×)

Docker-on-macOS cannot pass Metal into the VM — but the architecture already
has the seam to escape the VM: **hosted_http role providers** (B4 shipped
`roles.mnemo.local`) and the HTTP embedding/reranker contract, both behind the
fail-closed URL validator with internal-host allowlists.

1. Run Ollama **natively on macOS** (Metal). On an M-series 16 GB this serves
   qwen3:4b at tens of tok/s vs 0.5 — restoring the architecture doc's intended
   model quality AND cutting role calls from ~100 s to ~2–5 s.
2. Point the in-VM `role-llm`/`role-http` providers at the host endpoint via
   the existing allowlist env seams (Caddy re-terminates TLS; token-gate the
   host listener; bind to the VM bridge only).
3. Same seam scales UP on bigger machines: a Linux/CUDA host swaps in a GPU
   ollama container with zero engine changes; a rented GPU box becomes a
   `hosted_http` rung of the existing provider ladder.
4. Optional: host-native MLX embedding service (bge-large / Qwen3-Embedding)
   behind the same HTTP provider contract for +8–12 retrieval pts (arch doc §5).

Security invariants: no new authz surface; providers stay fail-closed;
`forbid_local` production posture is preserved because the endpoint is
non-loopback from the VM's perspective and allowlisted explicitly.
Evidence note: re-run consolidation-ops/hosted-llm drills after the flip.

## 5. Phase P3 — Engine hot-path surgery (Python/SQL; no new deps)

Ranked by measured leverage (agent-2 report, file:line verified):

1. **Postgres connection pool** (`postgres_engine.py:127-133`): one pooled
   conn reused across dense/lexical/graph channels of a retrieve (≥2–3 fresh
   TCP+TLS+auth handshakes per retrieve today).
2. **Compute `_candidate_hits` once per retrieve** (`engine.py:1281` +
   `1329/1337` scan the whole store twice) and share across channels; memoize
   the redacted-Hit projection per (item version, access context).
3. **Evidence FTS index**: materialized `tsvector` column + GIN on `evidence`
   (assertions already have `lexeme` + GIN; evidence does query-time
   `to_tsvector` = seq scan — `postgres_engine.py:1468-1492`).
4. **Kill the O(V·E) PPR mapping** (`engine.py:1482` linear scan per ranked
   node): pre-index `relation_by_pair` by node. Pure Python, huge at scale.
5. **Shallow-reconstruct RRF** instead of `copy.deepcopy` (`algorithms.py:71`;
   the Postgres branch already shows the no-deepcopy pattern).
6. **Parallelize the three retrieval channels** (independent; DB-bound
   channels release the GIL) and the independent consolidation role calls
   (summarizer/lesson/skill) — bounded ThreadPool, engine locks reviewed.
7. **Batch embeddings end-to-end**: add `embed_many` to the HTTP provider
   (`retrieval.py:1101-1126` posts one text per request) and use the
   service's existing batch endpoint; batch the consolidation embedder pass
   (`consolidation.py:1381`).
8. **Lazy imports in `mcp_server.py`** (eager engine+cryptography imports are
   the ~116 ms cold-start; cli.py already demonstrates the lazy pattern).
9. **PostgresEngine MMR should reuse pgvector vectors** instead of re-hashing
   text into hashing-space (`postgres_engine.py:4128`) — perf AND quality.

All changes ride the existing 3-engine parity suites + DSN-armed live tests.

## 6. Phase P4 — Native kernel wave 2 (Rust, inside the parity regime)

Parity contract preserved: scalar-sequential f64 per item, rayon across items
only, no FMA/transcendentals (documented `ln` exception), byte-parity tests +
10× bench gate before wiring, `MNEMOSYNE_PURE` escape hatch.

1. **`ppr_power_iteration` kernel** (`algorithms.py:182-206`): + * / only —
   fits the parity regime exactly; called by BOTH engines
   (`engine.py:1478`, `postgres_engine.py:2065`). Pairs with P3.4.
2. **Fused candidate scan-and-score** for the SQLite packed-BLOB seam (the
   seam already proved ~43×; extend to filter+score in one pass).
3. **Promote the `mneme-providers` sidecar** (fastembed/ONNX int8) through the
   REQUIRED bake-off with strict-judge confidence intervals — replaces fp32
   torch CPU embedding on the floor tier. Built already; needs evidence, not code.
4. Explicit NON-goals (per existing plans): no `dense_scan_packed` for
   list-vector engines (measured slower end-to-end); quantized kernel tier
   stays deferred; no new kernels without a P0 baseline showing they matter.

## 7. Phase P5 — Capability tiering: "do more on every machine"

Generalize the `parametric_adapter.py` pattern (pure-python → numpy → torch
cpu/cuda/mps, byte-portable artifact) into a **boot-time capability probe**
selecting a declared profile tier, all values registered in the config-drift
doc, all overridable by env:

| Tier | Trigger | Role model | Embedder | Reranker | PPR | Adapter |
|---|---|---|---|---|---|---|
| floor | ≤8 GB, no accel | qwen3:0.6b | hashing/ONNX-int8 sidecar | off/narrow | capped iters | pure-python |
| standard | 16 GB CPU | 0.6b–1.7b | bge-small ONNX | MiniLM narrow | default | numpy |
| metal/gpu | host Metal or CUDA/MPS | qwen3:4b+ | bge-large / Qwen3-Emb | full width | native kernel | torch (mps/cuda), wider heads |
| frontier | operator-configured | hosted rung | hosted | hosted | native | torch + optional true-LoRA rung (opt-in, same rails) |

The parametric tier "gets less conservative" here honestly: same fenced
boundary, protected-suite gate, and rollback — but the trainer backend, adapter
width, and (on gpu/frontier, opt-in) a genuine LoRA rung scale with hardware
instead of being pinned to the floor.

## 8. Phase P6 — Gated items (open only on evidence)

- **Rust rmcp front-end / warm daemon**: decided by the P0 trace against the
  existing phase4-front-end.md gate. Current ~116 ms stdio init does NOT
  justify it; do not build early.
- **SqliteEngine as the default edge/floor engine** for lesser machines
  (already 9 ms retrieves, per-tenant files): promote only after chaos + L4
  suites re-run under the tiering profile.

## 9. Sequencing constraint (do not skip)

The Tier-B production capture (24/24 artifacts ready) should run on the
CURRENT proven stack BEFORE P1/P2 change the production topology — otherwise
gathered live facts (timeouts, provider manifests, soak envelopes) go stale
and bundles must be re-drilled. Order: capture → v1.0 attestation → P0 →
P1 → P2 → P3 → (P4 ∥ P5) → P6. P0 may run anytime (read-only).

## 10. Expected impact (order-of-magnitude, to be verified by P0/P-exit benches)

- Consolidation role call: ~100 s → 2–5 s (P2 Metal) on the same Mac.
- Retrieve at 100k items: avoids 2×O(N) scan + seq-scan FTS cliffs (P3) —
  keeps p95 inside the §22.5 400 ms budget where today's path would blow it.
- Embed throughput: 5–10× (batch + ONNX int8 sidecar).
- Cold start: ~116 ms → ~50–60 ms (lazy imports), no daemon needed.
- Lesser machines: floor tier keeps everything functional (pure path,
  0.6b, sqlite); bigger machines auto-unlock quality instead of requiring
  hand-tuning.
