# Phase 11 deterministic retrieval evidence

This projection records the truth boundaries shared by the four verified,
non-headline Phase 11 bundles. It supplements the manifest-bound generated
reports without changing their bytes or external report digests.

## Mnemosyne results and measured channel participation

| Dataset | Eligible | Recall@2 | Recall@5 | nDCG@5 | Graph observed | `graph_ppr` channel sum | QA EM/F1 |
|---|---:|---:|---:|---:|---:|---:|---|
| LongMemEval cleaned | 500 | n/a | 0.2806 | 0.2967188496001503 | n/a | n/a | absent |
| MuSiQue | 1000 | 0.08083333333333333 | 0.10416666666666667 | n/a | 0/1000 | 0 | absent |
| 2Wiki | 1000 | 0.17525 | 0.23725 | n/a | 0/1000 | 0 | absent |
| HotpotQA | 1000 | 0.319 | 0.374 | n/a | 0/1000 | 0 | absent |

No reader or judge ran on the HippoRAG tracks, every answer field is null, and
the metric keyset is retrieval-only. The configured graph backend is disclosed
as `postgres-recursive-ppr`, but positive graph/PPR participation was not
demonstrated. Zero is a measured limitation, not HippoRAG parity.

## Published baseline context

The values below are upstream HippoRAG 2 Llama-3.3-70B Recall@2/Recall@5
context from the pinned Phase 11 research. They are not comparable pass
thresholds and are not Mnemosyne results.

| Dataset | Mnemosyne R@2 (%) | Mnemosyne R@5 (%) | Upstream R@2 (%) | Upstream R@5 (%) |
|---|---:|---:|---:|---:|
| MuSiQue | 8.083333333333333 | 10.416666666666668 | 56.1 | 74.7 |
| 2Wiki | 17.525 | 23.725 | 76.2 | 90.4 |
| HotpotQA | 31.9 | 37.4 | 83.5 | 96.3 |

## Custody and status

- All four source bundles and reproduced bundles verify and have byte-identical
  `traces.jsonl` and `metrics.json` files.
- All four generated reports verify against their committed Markdown notes.
- Every bundle remains `publishable=false`, `pbpp_headline_eligible=false`, and
  `independent_external_reproduction=false`.
- LongMemEval normalization deterministically redacted four secret-shaped raw
  substrings while retaining pinned raw-asset hashes and a reproducible
  normalized dataset digest.
- BENCH-004 is complete. BENCH-005 remains partial: retrieval measurement is
  complete, positive graph/PPR participation was not demonstrated, and Phase
  12 owns real disclosed-reader EM/F1 evidence.
