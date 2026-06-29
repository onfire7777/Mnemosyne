# §17 Measurement Benches

Four runnable benches that measure the **CURRENT** `src/mnemosyne` tree honestly
against the blueprint's §17 open questions (OQ1/OQ3/OQ4/OQ7). They import the real
engine / jobs / lifecycle / security modules **in-process** (no mocks, no CLI
subprocess) and each prints a JSON `metric` block plus the blueprint `target`.

Where a feature a bench measures is **not yet wired** in src, the bench still
runs end-to-end and reports the honest current status as a forcing function. As
wirings land, keep the reported status current rather than preserving historical
gap text.

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
| `bench_oq3_recompute_amplification.py` | OQ3 | passes-executed / projections-truly-invalidated + memo-hit-rate on add/retraction/erasure cascades | `jobs.RuntimeJobHandlers.run_projection_recompute`; `_affected_projections`; `_surviving_evidence_cids`; `_dirty_recompute_cids`; `_projection_recompute_passes` |
| `bench_oq7_capability_overhead.py` | OQ7 | full read-path mediation vs trust-tier-only, as a fraction of the P95 budget (threshold 5%) | `security.sanitize_retrieved_text` + `meets_trust`/`trust_weight`; engine trust filter `_candidate_hits`; read path `retrieve`; retrieved-text marker `_mark_retrieved_text_as_data` |
| `bench_oq4_demotion_objective.py` | OQ4 | current `exp(-age/45)` decay vs ACT-R power-law `t^-0.5`; divergence, threshold-crossing age, half-life | `lifecycle.decayed_salience` (lifecycle.py:64); `lifecycle.demotion_decision` (lifecycle.py:74) |

## Honest current-src status (the forcing functions)

- **OQ1** — Local `graph_ppr` still measures live recompute cost, while the
  default-off Postgres cached-PPR seam now exists. The bench reports the
  structural cache seam honestly and does not fabricate cached latency from
  local warm repeats; DSN-backed refresh/read timing remains the separate
  measurement needed for a production cache-latency report.
- **OQ3** — Recompute now has an in-process identical-replay memo guard, a
  first-run dirty-set filter, and projection-specific default pass selection, so
  closure traversal no longer means every surviving affected CID or every
  consolidation pass is scheduled.
- **OQ7** — Retrieved text is now marked as data at engine return points through
  `_mark_retrieved_text_as_data`, including local and Postgres read paths. The
  bench remains useful as a primitive overhead measurement for the full
  mediation work owed by §30 rails.
- **OQ4** — src uses a pure **exponential** decay (`exp(-age/45)`, half-life
  ~31 days); the bench quantifies the gap to the ACT-R **power law** so OQ4 is
  resolved against a measured divergence rather than intuition. No code changes.

## Rules honored

- These benches are measurement forcing-functions. When source wirings land,
  keep the honest-status text in sync rather than preserving historical gaps.
- Reuses `.venv-eval`; never imported torch needlessly (deterministic local engine).
- Imports the real `mnemosyne` package by adding `<repo>/src` to `sys.path`
  exactly like the CLI does — if the src contract breaks, the benches break.
