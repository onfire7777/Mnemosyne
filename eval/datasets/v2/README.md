# Mnemosyne eval corpus — v2 (large, discriminating, G2-measurable)

Blueprint refs: **§33** (private regression suite / measurement set), **§16 G2**
(+15% answer quality at ≤10% tokens), **FR-3** (hybrid retrieval recall@k / nDCG@k).

This directory is a **net-new, larger, realistic retrieval + QA eval corpus** that
replaces the tiny Wave-1 seed (`eval/datasets/retrieval_curated.json`, 12 docs / 10
queries) so the SLOs are measured *meaningfully*. It is loadable by the **existing
harness with no harness edits**.

## Why v2

The Wave-1 set is too small to discriminate:

- **Retrieval saturates.** With a 12-doc corpus, a `k=5` read trivially contains
  the single gold doc, so recall@k / nDCG@k sit near 1.0 and cannot tell a good
  ranker from a mediocre one.
- **G2 has a ceiling artifact ("Wave-2 ceiling").** The curated gold answers
  (e.g. `Paris`) appear verbatim in the corpus, so the G2 "full context" = whole
  corpus concatenated → the substring judge scores full-context a permanent **1.0**.
  `memory − full` can therefore never be positive and the +15% lift is structurally
  unmeasurable.

v2 fixes both, **deterministically**.

## Files

| File | What it is |
|---|---|
| `generate_v2.py` | **Deterministic synthetic generator** (seeded). Builds the corpus + queries and writes the two JSON datasets. Same-seed → byte-identical output. |
| `retrieval_v2.json` | **≥40 curated retrieval cases** (44 answerable + 1 abstain) over a **105-doc** distractor-rich corpus. Same schema as `retrieval_curated.json`. |
| `qa_hard_v2.json` | **24 hard QA cases** (12 multi-hop, 8 temporal/as-of, 4 contradiction-resolution). Superset of the retrieval-query schema. |
| `v2_judge.py` | A **deterministic, distractor-aware judge** (drop-in for `MNEMO_EVAL_JUDGE_CMD`) that breaks the G2 ceiling **without an LLM**. |
| `run_eval_v2.py` | A **net-new runner** that drives the unmodified `eval/harness` suites against v2. |

Regenerate (idempotent, deterministic):

```bash
python eval/datasets/v2/generate_v2.py            # writes both JSON files
python eval/datasets/v2/generate_v2.py --selftest # determinism + schema + ceiling assertions
```

## Schema (matches the existing harness exactly)

`retrieval_v2.json` is byte-for-byte the same shape the harness already consumes:

```jsonc
{
  "dataset_id": "retrieval_v2",
  "description": "...",
  "tenant": "eval-retrieval-v2",
  "user": "eval-user",
  "k": 5,
  "corpus":  [ {"doc_id": "...", "content": "...", "trust_tier": 0}, ... ],   // 105 docs
  "queries": [ {"qid": "...", "query": "...", "relevant_doc_ids": ["..."],
                "gold_answer": "...", "answerable": true}, ... ]              // 44 + 1 abstain
}
```

`qa_hard_v2.json` is a **superset**: identical top-level keys, and each query adds
*optional* keys the harness ignores (so it loads unchanged through
`retrieval_suite` and `answer_quality_suite`):

```jsonc
{
  "qid": "qa_asof_default_cloud",
  "query": "as of 2025-12-15, what was the default cloud provider",
  "relevant_doc_ids": ["tmp_default_cloud_1"],
  "gold_answer": "GCP",
  "answerable": true,
  // ---- extra v2-only keys (optional; harness-ignored) ----
  "qa_type": "temporal_as_of",              // multi_hop | temporal_as_of | contradiction
  "as_of": "2025-12-15",                     // (temporal) the date the question is asked
  "hops": ["...","..."],                     // (multi_hop) ordered doc_ids to chain
  "distractor_doc_ids": ["tmp_default_cloud_2","tmp_default_cloud_0"],
  "gold_aliases": ["GCP"],                    // accepted surface forms of the answer
  "distractor_answer": "Azure"               // the plausible WRONG value in full context
}
```

### How the hard cases defeat a trivial full-context baseline (the G2 fix)

Every hard case's `gold_answer` is a **synthesized, resolved** value (the result of
a multi-hop join / as-of cut / supersession), and the corpus is salted with a
**contradictory distractor doc** that asserts a plausible WRONG value using the
same cue words. Consequences:

- A **full-context dump** contains BOTH the right and the wrong value, so a judge
  reading the whole corpus is genuinely challenged — it does **not** trivially
  score 1.0.
- A **memory layer** that resolves the hop / as-of / contradiction returns a
  focused, distractor-free slice → it can answer correctly at ≤10% tokens. That
  asymmetry **is** the G2 lift.

This makes the +15%-at-≤10%-tokens lift a real, measurable quantity instead of a
ceiling artifact.

## Running v2

### A. No-edit path (recommended now) — the net-new runner

```bash
# local deterministic engine (runs today)
python eval/datasets/v2/run_eval_v2.py

# break the G2 ceiling without an LLM (deterministic distractor-aware judge)
python eval/datasets/v2/run_eval_v2.py --distractor-judge

# sharpen with real services (flags forwarded verbatim, exactly like run_eval.py)
python eval/datasets/v2/run_eval_v2.py \
  --global-flag --embedding-provider --global-flag http \
  --global-flag --embedding-url --global-flag http://localhost:8080/embed \
  --global-flag --reranker-provider --global-flag http \
  --global-flag --reranker-url --global-flag http://localhost:8081/rerank

# write a JSON scorecard
python eval/datasets/v2/run_eval_v2.py --distractor-judge --out eval/reports/slo_report_v2.json
```

The runner imports the **unmodified** `eval/harness` suites — it is purely additive.

### B. Strict LLM judge for G2 (real signal)

The harness's pluggable judge ABI is unchanged: set `MNEMO_EVAL_JUDGE_CMD` to a
command that reads `{"question","context","gold"}` on stdin and prints
`{"score": 0..1}`. The deterministic stand-in lives here:

```bash
export MNEMO_EVAL_QA_DATASET=eval/datasets/v2/qa_hard_v2.json
export MNEMO_EVAL_JUDGE_CMD="python eval/datasets/v2/v2_judge.py"
python eval/datasets/v2/run_eval_v2.py     # full-context drops below 1.0 → lift is measurable
```

`v2_judge.py` scores `1.0` only when the gold (or an alias) is present in the
context **and** the case's `distractor_answer` is **absent** — i.e. the context is
unambiguous. The full corpus contains both, so it scores `0.0`; the resolved memory
slice scores `1.0`.

### C. Pointing the stock `run_eval.py` at v2 (one-line additive shim — see reconciliation)

`eval/run_eval.py` currently hardcodes its dataset directory:

```python
DATASETS = _EVAL_DIR / "datasets"
```

To let it pick up v2 **without changing its behaviour by default**, this single
additive line makes it env-overridable (the change is *recorded as a reconciliation
item* and intentionally NOT applied here, to keep this deliverable net-new only):

```python
import os
DATASETS = Path(os.environ.get("MNEMO_EVAL_DATASET_DIR", _EVAL_DIR / "datasets"))
```

Then point it at v2 by file naming — copy/symlink the v2 files to the names
`run_eval.py` loads (`retrieval_curated.json`, plus `poison_suite.json` /
`belief_cases.json` which v2 does not change), e.g.:

```bash
mkdir -p eval/datasets/v2-run
ln -s ../v2/retrieval_v2.json eval/datasets/v2-run/retrieval_curated.json
ln -s ../poison_suite.json    eval/datasets/v2-run/poison_suite.json
ln -s ../belief_cases.json    eval/datasets/v2-run/belief_cases.json
MNEMO_EVAL_DATASET_DIR=eval/datasets/v2-run python eval/run_eval.py
```

Until that one line lands, **use `run_eval_v2.py` (path A)** — it needs no harness
or runner changes at all.

## What the numbers look like (local deterministic engine, today)

| Suite | Wave-1 | v2 | Why it matters |
|---|---|---|---|
| retrieval recall@k | ~1.0 (saturated) | **0.767** | discriminating, not saturated |
| retrieval nDCG@k | ~1.0 (saturated) | **0.756** | ranking quality is now visible |
| hard-QA recall@k | — | **0.667** | harder set (needs hop/temporal resolution) |
| G2 full-context (substring) | 1.0 (ceiling) | 1.0 (ceiling) | the artifact, reproduced |
| G2 full-context (distractor judge) | n/a | **0.0** | **ceiling broken** → lift measurable |
| G2 absolute lift (distractor judge) | capped ≤0 | **+0.083** (deterministic floor) | real, positive, moves with real services |

The G2 +15% target legitimately **fails** on the deterministic engine — the local
lexical reranker does not resolve multi-hop / temporal / contradiction, so it
rarely returns a distractor-free slice. That is the honest floor: it sharpens the
moment the real embedding / cross-encoder + temporal/graph resolution paths rank
the resolved doc above the distractor. No harness change is needed for that — the
same suites measure the improvement automatically.

## Determinism & provenance

`generate_v2.py` is fully seeded (`RETRIEVAL_SEED=1107`, `QA_SEED=2207`). The
committed `retrieval_v2.json` / `qa_hard_v2.json` are exactly what the generator
emits; `--selftest` asserts byte-identical regeneration, schema parity with
Wave-1, the size bars (≥40 retrieval / ≥20 hard QA / ≥100 docs), and the
G2-ceiling-broken property (every hard case's distractor answer is present in the
corpus). Per §9 / §12 N3 this is an **internal-only** suite and is never reported
as a public benchmark.
