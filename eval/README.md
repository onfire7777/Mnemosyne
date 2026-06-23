# Mnemosyne §33 Evaluation / SLO Measurement Harness

This is the **proof harness** the blueprint calls the "single largest gap between
'looks done' and 'blueprint-complete'" (§E). It drives **only the public CLI**
(`python -m mnemosyne.cli ...`) — never internal modules — and turns every Goal /
SLO from "claimed by construction" into "measured, with confidence intervals."

It runs **end-to-end against the local deterministic engine right now** and emits
real numbers. The same harness sharpens automatically once the real embedding /
cross-encoder service and Postgres backend are wired (no harness changes).

---

## TL;DR — run it

```bash
# Full run (SLO suites + 5 mandatory §33 test classes + ignition gate + reports)
python eval/run_eval.py

# Fast smoke run (skips the synthetic + latency-heavy suites)
python eval/run_eval.py --quick

# Unit + integration tests for the harness itself
python -m pytest eval/tests/ -v
```

Reports land in `eval/reports/`:
- `slo_report_<stamp>.json` + `slo_report_latest.json` — machine-readable evidence artifact
- `slo_report_<stamp>.md`   + `slo_report_latest.md`   — human SLO scorecard with CIs
- `suite_state.json` — the suite-ignition (shadow-until-N) gate state, persisted across runs

Exit code: **0** when in SHADOW mode (advisory) or when ACTIVE and all checks
pass; **non-zero** only when ACTIVE *and* a binding check fails. That non-zero is
the promotion gate.

---

## What it measures (blueprint §33 measurement set / §16 SLOs)

| Suite | Metric | Blueprint target | Module |
|---|---|---|---|
| `retrieval` (curated + synthetic) | recall@k, nDCG@k | internal seed bar (FR-3, §12 N3: private) | `suites.retrieval_suite` |
| `fast_path_latency` | P95 latency under concurrent load | ≤ ~300–400 ms (§16) | `suites.latency_suite` |
| `calibration` | Expected Calibration Error (ECE) + abstention | ECE ≤ 0.05 (§16, FR-6) | `suites.calibration_suite` |
| `answer_quality_g2` | answer quality + token-efficiency vs full context | +15% at ≤10% tokens (§16 G2) | `suites.answer_quality_suite` |
| `poison_block_rate_g7` | MINJA/AgentPoison block rate | ≥ 95% (§16 G7) | `suites.poison_suite_eval` |

All point estimates carry a **95% confidence interval** (Wilson for proportions,
percentile-bootstrap for means / latency percentiles) — the §33 methodology
guardrail that "most deltas are within noise." Bootstraps are deterministically
seeded so the suite is reproducible (a regression suite must distinguish a true
regression from generator noise).

## The five mandatory §33 test classes (runnable now)

Implemented in `harness/test_classes.py`, each as a self-contained CLI-driven
scenario returning a PASS/FAIL with a captured evidence block:

1. **rollback_crossing_supersession** — create a Paris→Berlin supersession on
   `main`, branch a scratch, supersede Berlin→Tokyo *across* that edge on the
   branch, then `discard` (rollback). Asserts `main` is left bit-identical and the
   branch's write is gone.
2. **erasure_with_without_corroboration** — a single-source assertion is
   **retracted** when its only evidence is forgotten; a two-source (independently
   corroborated) assertion **survives (trimmed)** when one source is forgotten.
3. **contested_belief_multi_hypothesis** — two same-subject/predicate hypotheses
   with equal valid-time are both retained as `contested`, surfaced via
   `belief-revision-check` with normalized probabilities summing to 1.0.
4. **untrusted_instruction_never_executed** — a low-trust injected "ignore all
   instructions" memory is filtered out of a trust-bounded read, and the
   `retrieved_text_is_data_not_instruction` rail is asserted enabled on every read.
5. **no_degradation_vs_no_memory** — over a long horizon (corpus loaded in 25/50/
   75/100% checkpoints) the memory-backed answer rate never drops below the
   no-memory baseline and strictly improves at full horizon (G5 anti-degradation).

## Seed dataset (curated + synthetic) — `eval/datasets/`

- `retrieval_curated.json` — curated, trusted, held-out QA cases (corpus + queries
  + gold relevance labels + an unanswerable/abstain case). Internal-only; never
  reported as a public benchmark (§9 / §12 N3).
- `poison_suite.json` — MINJA + AgentPoison memory-injection attacks (permanent
  protected tier).
- `belief_cases.json` — belief-revision cases (supersession, cascade invalidation,
  contested multi-hypothesis, noop) validated by `belief-revision-check`.
- **Synthetic cases** are auto-generated at runtime from the earliest episodes
  (`harness/synthetic.py`, deterministic) — the §33 suite-ignition mechanism.

## Suite ignition — shadow-until-N (§33 / §17 P1)

The blueprint's cold-start fix. Until the private suite reaches ignition size **N**
the harness runs in **SHADOW** mode: verdicts are logged but **advisory only** and
never gate promotion. At `suite_size >= N` it flips to **ACTIVE** and verdicts
become binding (the harness becomes the promotion gate). `N` is a blueprint-open
question (§17 P1); the default is `40`, override with `--ignition-n`. State and the
shadow↔active transition history are persisted to `eval/reports/suite_state.json`.

---

## How this sharpens once the real services are wired

The current numbers are **honest measurements of the local deterministic engine**
(hashing pseudo-embeddings + local lexical reranker). Retrieval/calibration/G2 are
therefore **floor estimates** — they prove the harness and the contract, and they
move the moment real backends arrive. No harness code changes are required:

1. **Real embedding + cross-encoder (FR-3 keystone).** Stand the service up
   (docker-compose, §I) and forward the CLI flags:
   ```bash
   python eval/run_eval.py \
     --global-flag --embedding-provider --global-flag http \
     --global-flag --embedding-url --global-flag http://localhost:8080/embed \
     --global-flag --reranker-provider --global-flag http \
     --global-flag --reranker-url --global-flag http://localhost:8081/rerank
   ```
   The `cli_driver` forwards them verbatim; recall@k / nDCG / ECE / G2 all sharpen.

2. **Postgres backend (G8 portability + true concurrent-load latency).**
   ```bash
   python eval/run_eval.py --backend postgres --postgres-dsn "$MNEMOSYNE_POSTGRES_DSN"
   ```
   The latency suite then measures a **shared concurrent-safe store** (no per-worker
   cloning) — true service-side P95. (The local single-file backend is single-writer
   by design; production concurrency is Postgres's job, §16/§I.)

3. **Strict LLM judge for G2.** Set `MNEMO_EVAL_JUDGE_CMD` to a command that reads
   `{"question","context","gold"}` on stdin and prints `{"score": 0..1}`. This
   replaces the deterministic substring judge with the blueprint's "strict judge +
   adversarial-answer screening" — under which the +15%-lift verdict becomes the
   real signal (the substring judge can't beat a full-context ceiling, so today the
   lift verdict is reported as a documented FLOOR alongside the achievable
   token-efficiency proxy).

### Why two latency verdicts?

Each CLI call is a fresh Python process, so raw wall-time includes interpreter +
import cold-start (~200–300 ms). The suite reports **`fast_path_p95_ms_raw`** (a
conservative CLI-cold-start upper bound) and **`fast_path_p95_ms_engine_only`**
(raw minus the measured `tools`-command startup baseline) — the engine-only
estimate is what a long-lived server backend exposes, since startup is paid once,
not per request.

---

## Layout

```
eval/
  run_eval.py            # runner: orchestrates suites + classes + ignition + reports
  datasets/              # curated + attack + belief seed datasets
  harness/
    cli_driver.py        # the ONLY seam to Mnemosyne — subprocess CLI driver
    metrics.py           # recall/nDCG/ECE/percentiles + Wilson & bootstrap CIs
    synthetic.py         # deterministic synthetic-case generator (suite ignition)
    answer_quality.py    # G2 judges (substring now, LLM-judge real path) + token count
    test_classes.py      # the 5 mandatory §33 test classes
    suites.py            # the SLO measurement suites
    ignition.py          # shadow-until-N promotion gate
    report.py            # JSON + Markdown SLO report writer
  tests/                 # unit (metrics) + integration (full harness) tests
  reports/               # emitted reports + persisted ignition state
```

Design rule honored throughout: **drive only the public CLI**; never import
`mnemosyne.engine` / `retrieval` / `belief` / etc. If the agent-facing contract
(§30.7 ABI) breaks, the harness breaks — which is the point.
