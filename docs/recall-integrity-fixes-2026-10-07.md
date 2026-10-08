# Retrieval integrity fixes — 2026-10-07

Implemented in `C:\Users\Onfire\Documents\Codex\Mnemosyne`, based on the supplied
Mnemetric brief. The initial implementation did not locate the original brief or
reproduction scripts. They were subsequently located at
`C:\Users\Onfire\Desktop\QT projects\Mnemosyne\docs\recall-90-fix-prompt.md`
and `C:\Users\Onfire\Desktop\QT projects\Mnemosyne\_scratch\benchmark`.
The current source, Desktop Mnemetric harness/reports, and MnemetricData corpus
and diagnostics were inspected instead. The checkout is newer than the brief's
`e1ad2d0c` pin; the starting revision was `1e19ac52`.
Landed as one commit on `main` on 7 Oct 2026, with one fix found on review: once
the CID header left the summary text, two summaries with the same words over
different sources or RAPTOR levels hashed to the same evidence CID and collapsed
into one row (the root became a copy of a leaf). Each summary now ends with a
single `[gist <source fingerprint>]` token, which keeps every node distinct
without putting source lists back into the searchable text.

## Implemented

- Consolidation no longer assigns the entire input batch to every fact. Each
  candidate keeps its own source CIDs. Model-backed extraction preserves and
  validates explicit citations; ambiguous multi-document responses fail closed.
- The corroboration lookup now requires all subject/object terms, rather than
  any two overlapping words. Independent-source and promotion gates remain.
  This is still a lexical support check, not an entailment model.
- Bare capitalized-name co-occurrence no longer creates `related_to` assertions.
  The deterministic extractor remains conservative and heuristic.
- Summary provenance stays in metadata, outside searchable summary text.
- U-curve layout no longer reorders search results. Memory activation uses the
  request's evaluation instant. Passage search omits activation, recency, MMR,
  and the hashing-based local reranker so they cannot destroy BM25 order.
- `query_mode="passages"` ranks authorized source evidence using corpus-aware
  BM25, excluding generated summaries and assertions. It uses at least 100
  candidates and preserves an actual configured semantic provider/reranker.
  Hashing is not treated as a second semantic signal in this route.
- The graph candidate allowance in ordinary retrieval is increased from half
  the result count to at least the configured rerank width.
- Grounded answering can proceed past insufficient first-hop query coverage.
  Empty results, missing grounding diagnostics, gist-only support, and hard
  grounding gates still stop expansion. Final source and claim checks remain.
- Sourced consolidation summaries no longer consume the autonomous
  self-generation event allowance. Sources must exist, match tenant/branch,
  remain unerased, and classify as grounded. Summaries retain their derived,
  non-authoritative classification. Unsourced generation remains capped.
- Scoring gives a direct passage ID precedence and does not expand a
  multi-source fact into a fabricated passage ranking. An unambiguous
  single-source projection can still resolve to its passage.
- The HippoRAG-family adapter uses a single bounded query process for these
  1,000-query suites, passage mode, 24 results, a 16,384-token budget, and compact
  output. Trace rows reference the stored corpus by count and SHA-256 instead
  of repeating every corpus ID. The corpus remains in the benchmark artifact.
- The passage index is reused within an engine, always after authorization;
  mutations/erasure invalidate it. Only selected local hits are cloned.

The existing general memory search stays available for preferences, assertions,
and temporal retrieval. The benchmark adapter explicitly selects passage mode.
Existing poisoned stores are **not repaired in place**; rebuild evaluation
stores from their source corpus. Historical published artifacts were not edited.
Desktop Mnemetric's separate installed dependency and the live website were not
updated by these source changes.

## Measurements

Ranking was fixed using synthetic tests before examining these held-out scores.
All supplied 1,000-question sets were measured without parameter selection or
tuning on the results. The runner is `eval/recall_integrity.py`.

| Dataset | Passages | Recall@5 | Mean query | P95 query | BM25 top-five mismatches |
|---|---:|---:|---:|---:|---:|
| 2Wiki | 6,119 | 0.66425 | 15.80 ms | 19.35 ms | 0 / 1,000 |
| HotpotQA | 9,811 | 0.72750 | 27.66 ms | 35.74 ms | 0 / 1,000 |
| MuSiQue | 11,656 | 0.42808 | 33.64 ms | 42.95 ms | 0 / 1,000 |

These are **in-memory, passage-only engine measurements**, not an end-to-end
consolidated-store or model-backed HippoRAG reproduction. The parity check
compares the public engine result with its BM25 lexical route; it is not an
independent second implementation of BM25. Original passage ingest took 2.51,
5.33, and 7.33 seconds respectively, without consolidation. The old 2.7-second
per-question figure used a different store/path, so no direct speedup ratio is
claimed. Answer abstention and retrieval recall are distinct; abstentions were
19, 40, and 48, while retrieved passages were scored for every question.

Raw measurement and input hashes:
`C:\Users\Onfire\MnemetricData\runs\recall-integrity-20261007.json`.
The 2Wiki input hashes match the archived Desktop Mnemetric report.

Reproduce from this checkout:

```powershell
.venv\Scripts\python.exe -m eval.recall_integrity --data-root C:\Users\Onfire\MnemetricData\hipporag --output C:\Users\Onfire\MnemetricData\runs\recall-integrity-rerun.json
```

Use the compact passage route on an existing clean evaluation store:

```powershell
.venv\Scripts\python.exe -m mnemosyne.cli --backend local --store STORE.json --evaluation-read-only eval-query-batch --input-jsonl QUERIES.jsonl --retrieval-mode passages --retrieval-top-k 24 --retrieval-token-budget 16384 --compact
```

## Verification

- 389 focused tests passed, covering consolidation, source integrity, local and
  SQLite passage authorization/index refresh/erasure, summary budgets, grounded
  answering, engine parity, the public adapter/CLI, and promotion gates.
- Ruff passed on the changed implementation and regression tests.
- The public CLI adapter was exercised end to end on a synthetic corpus.
- Broader tests exposed existing Windows command-execution failures in C2PA and
  command lesson/skill fixtures, plus a telemetry newline/hash fixture failure.
  Those failures were reproduced with original `HEAD` runtime modules loaded
  directly from Git, without changing the working tree. The broad public-eval
  suite also failed; it is not included in the focused green-test claim.
- PostgreSQL code paths were updated, but no live PostgreSQL verification was
  performed. Its passage route currently uses the existing authorized export;
  it is correct-by-filtering rather than an optimized server-side BM25 index.

## Remaining model/research work

This section records the initial integrity implementation, not current project
acceptance. Subsequent graph/model work and its reported held-out measurements
are documented in [passage-graph.md](passage-graph.md). Those results do not close
the rolling-budget, all-suite, latency or exact-replay acceptance requirements.

No 90% recall claim is made. A learned embedding model, a learned cross-encoder,
and an actual OpenIE/synonym/PPR HippoRAG implementation were not installed or
validated here. The existing HTTP model/provider seams remain available, but
this machine's project environment has no torch, sentence-transformers,
transformers, or ONNX runtime and no cached text retrieval models. The existing
graph algorithm is not relabeled as HippoRAG. Source-bound answer expansion was
fixed and regression-tested, but no held-out model-backed second-hop study or
development-split tuning was performed. Autonomous unsourced memory still uses
its existing lifetime cap; the verified-summary exemption fixes the reported
summary blockage, not a general rolling-window budget redesign.
