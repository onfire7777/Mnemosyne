# LongMemEval-S run of 29 Oct 2026

Run with `eval/longmemeval_s/run_bench_LongMemEval.py` on all 500 questions of
`longmemeval_s_cleaned.json`. Copied from the local, git-ignored output folder
`work/longmemeval-openrouter/`.

| Setting | Value |
| --- | --- |
| Retrieval | dense, top 10 sessions, `qwen/qwen3-embedding-8b` |
| Reader | `anthropic/claude-haiku-5.5`, reasoning effort `xhigh`, chain of thought, 32,000-token cap |
| Judge | `openai/gpt-4o-mini-2024-07-18` (LongMemEval autoeval prompt) |
| Provider | OpenRouter, provider-reported cost $3.11 |

## Result

| Split | Correct | Accuracy |
| --- | --- | --- |
| All 500 | 486 | **97.2%** (Wilson 95% CI 95.4–98.3%) |
| Development 100 | 98 | **98.0%** |
| Held-out 400 | 388 | 97.0% |

Task-averaged accuracy 97.9%. Evidence recall of the retrieved sessions: 99.7%.
By type: single-session-assistant 100%, single-session-preference 100%,
knowledge-update 98.7%, single-session-user 97.1%, temporal-reasoning 97.0%,
multi-session 94.7%; abstention 86.7% (26/30).

## How to read this score

- This run (`…-xhigh-v2-all`) came 19 minutes after the same configuration scored
  93.8% (`…-xhigh-all.summary.json`), and 11 minutes after a re-run of that run's 31
  wrong answers (`verify-31-misses…summary.json`). 21 of those 31 are held-out
  questions, 27 of the 31 are correct in this run, and retrieval differs for 330 of
  the 500 questions. The held-out 400 were therefore seen while the code changed,
  so 97.0% is not a clean held-out score.
- The files record no commit id, so the exact code of this run is not pinned.
- The audited, clean result remains 92.4% (462/500, held-out 91.5%); see
  [the score audit](../../../docs/2026-10-22-memory-audit-report.md#what-the-score-actually-means).
- Hindsight publishes 94.6% under other models and conditions; neither number is a
  controlled comparison.

## Files

| File | SHA-256 |
| --- | --- |
| `dense-top10-claude-haiku-5.5-xhigh-v2-all.jsonl` (one row per question) | `082b1fd23071899a68ff75d6d476a8c4f58ee64d5c7734e6e78a0386fbabb1cd` |
| `dense-top10-claude-haiku-5.5-xhigh-v2-all.summary.json` | `caf6a6a932d56d628fd9925136083b90e732f4fcdd37e425bd8baf57159521bc` |
| `dense-top10-claude-haiku-5.5-xhigh-all.summary.json` (previous run, 93.8%) | `714356c3cba74e10ab41c7605a6b042b3863a45c543a09833406b36fb2a0956f` |
| `verify-31-misses-haiku-5.5-xhigh.summary.json` | `32f0214d2fe164590035119373f9456d94a618ab1f74b2294667e54c60c8a422` |
