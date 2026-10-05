# Exact-source TRAIN staging

Implementation source: clean `19b9e0b9`; Python 3.11, PyArrow 23.0.1, macOS ARM64.
The parser ran against the five allowlisted, hash-verified files recorded in
`staging.json`. Parquet is read in 128-row, single-threaded batches; no model or
protected dataset is loaded. The 1,485,442,547-byte staged JSONL remains outside
Git at `/Users/admin/.local/state/mnemosyne/compact-train-rows-2026-10-04`.

| Source | Input rows | Span rows | Upstream null rows | Ranking-only rows | Rejected rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| SQuAD v2 TRAIN | 130,319 | 86,821 | 43,498 | 0 | 0 |
| Hotpot distractor TRAIN | 90,447 | 84,910 | 0 | 5,515 | 22 |

These are data-processing counts, not model accuracy or benchmark scores.
Hotpot yes/no and answers lacking an exact match inside a supporting sentence
are ranking-only, never invented null labels. Its original sentence strings
are concatenated without added separators. All repeated exact occurrences in
supporting sentences are retained. SQuAD uses original answer offsets.
Twenty-two Hotpot rows contain out-of-range supporting-sentence references;
`rejected.jsonl` preserves their raw-row hashes, pinned source and failure reason
without changing labels or silently repairing the upstream data.

Every retained row includes pinned upstream source/id, raw-row SHA-256,
question/title/context/answer raw and normalized hashes, exact source texts,
character and UTF-8 byte offsets, license, and transformer digest. Normalization
is explicitly NFKC, casefold, whitespace collapse; it never changes span text.
Title/context grouping keys are only inputs for later grouping, not completed
entity clusters or a frozen partition assignment.

## Independent verification

`audit_source.py` streams original parquet alongside the staged JSONL without
importing the row transformer. It verifies pinned input and output hashes,
source identity, question/document text, exact character and UTF-8 spans,
upstream answer/support membership, actual null labels and rejected-row hashes.
It checked all 220,744 retained rows and 194,069 spans; results are retained in
`source-audit.json`. Thirty focused intake/staging and BurnOS/provider tests
passed; Ruff passed. No physical 8 GiB acceptance claim follows from this run.

Reproduce using the separately installed optional `pyarrow==23.0.1`:

```sh
python -m eval.compact_answering.train_rows /absolute/intake /absolute/new-staging
python eval/reports/compact-train-staging-2026-10-04/audit_source.py /absolute/intake /absolute/new-staging
```

## Still quarantined

No row is admitted for training, calibration, selection or benchmark scoring.
The staged records explicitly set `training_admitted=false` and
`overlap_verdict=unchecked`. Before use, complete source-document/entity
clustering, deterministic pre/post transformation protected-overlap checks,
cluster-wide exclusion, immutable grouped TRAIN-derived partitions, and full
license/attribution custody. This parser does not implement an overlap matcher,
choose thresholds or inspect protected content. Learned-model selection,
training, quality evaluation and promotion remain open.
