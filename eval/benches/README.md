# §17 Measurement Benches

Four runnable benches that measure the **CURRENT** `src/mnemosyne` tree honestly
against the blueprint's §17 open questions (OQ1/OQ3/OQ4/OQ7). They import the real
engine / jobs / lifecycle / security modules **in-process** (no mocks, no CLI
subprocess) and each prints a JSON `metric` block plus the blueprint `target`.

Where a feature a bench measures is **not yet wired** in src, the bench still runs
end-to-end and reports the honest current status as a forcing function, naming the
precise src wiring under `wiring_to_*`.

## Run

```bash
# reuse the ready venv (torch + sentence-transformers; benches don't need torch)
.venv-eval/bin/python eval/benches/run_benches.py          # all four
.venv-eval/bin/python eval/benches/bench_oq1_ppr_latency.py
.venv-eval/bin/python eval/benches/bench_oq3_recompute_amplification.py
.venv-eval/bin/python eval/benches/bench_oq4_demotion_objective.py
.venv-eval/bin/python eval/benches/bench_oq7_capability_overhead.py
```

Each bench prints a pretty JSON object, then a final `BENCH_JSON <compact json>`
line so a wrapper can `json.loads` the last line. Exit code is always 0 — these
are measurement forcing-functions, not gates.

## What each bench measures + src wiring

| Bench | OQ | Measures | Primary src seam |
|---|---|---|---|
| `bench_oq1_ppr_latency.py` | OQ1 | live-PPR P50/P95 scale sweep over relation counts vs §15/§16 P95 budget; cached-vs-warm probe | `graph.LocalRelationGraphAdapter.ppr` → `engine.LocalMemoryEngine.graph_ppr` (graph.py:34, engine.py:615); `graph.benchmark_graph_adapter` (graph.py:58) |
| `bench_oq3_recompute_amplification.py` | OQ3 | passes-executed / projections-truly-invalidated + memo-hit-rate on add/retraction/erasure cascades | `jobs.RuntimeJobHandlers.run_projection_recompute` (jobs.py:88); `_affected_projections` (jobs.py:442); `_surviving_evidence_cids` (jobs.py:457); `DEFAULT_CONSOLIDATION_PASSES` (consolidation.py:25) |
| `bench_oq7_capability_overhead.py` | OQ7 | full read-path mediation vs trust-tier-only, as a fraction of the P95 budget (threshold 5%) | `security.sanitize_retrieved_text` (security.py:921) + `meets_trust`/`trust_weight` (security.py:49,55); engine trust filter `_candidate_hits` (engine.py:1166); read path `retrieve` (engine.py:687) |
| `bench_oq4_demotion_objective.py` | OQ4 | current `exp(-age/45)` decay vs ACT-R power-law `t^-0.5`; divergence, threshold-crossing age, half-life | `lifecycle.decayed_salience` (lifecycle.py:64); `lifecycle.demotion_decision` (lifecycle.py:74) |

## Honest current-src status (the forcing functions)

- **OQ1** — There is **no cached-PPR column** today: `graph_ppr` rebuilds adjacency
  and runs the 12-iteration power method on every call, so warm repeats are not
  cheaper than cold (the `warm_vs_cold_speedup_x` ratio converges to ~1.0 at
  scale). The "cached" column is reported as N/A, not fabricated. Live P95 stays
  within the 400 ms budget at the local-engine scales tested; the bench names the
  cache + postgres-materialization wiring that OQ1 would add.
- **OQ3** — There is **no dirty-check / memo table**: recompute enqueues a full
  11-pass consolidation per surviving cid in the BFS closure and re-enqueues
  identically on replay, so `memo_hit_rate == 0.0` and amplification is **>> 1.0**.
- **OQ7** — `sanitize_retrieved_text` is defined but **not invoked per-hit inside
  the engine read path** (`LocalMemoryEngine.retrieve` only applies the trust
  filter). The bench measures the *primitive* cost of full mediation so the 5%
  threshold can be checked now, and flags that the wrap is not yet engine-side.
- **OQ4** — src uses a pure **exponential** decay (`exp(-age/45)`, half-life
  ~31 days); the bench quantifies the gap to the ACT-R **power law** so OQ4 is
  resolved against a measured divergence rather than intuition. No code changes.

## Rules honored

- Net-new files only, all under `eval/benches/`. **No edits to `src/mnemosyne`.**
- Reuses `.venv-eval`; never imported torch needlessly (deterministic local engine).
- Imports the real `mnemosyne` package by adding `<repo>/src` to `sys.path`
  exactly like the CLI does — if the src contract breaks, the benches break.
