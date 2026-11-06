# LongMemEval-S Archived Evaluation Receipts

This directory contains the aggregate `.summary.json` receipts and per-question `.jsonl` prediction and judge logs for Mnemosyne's **LongMemEval-S** evaluations.

For the full architectural and methodology write-up, see [`docs/benchmark/LONGMEMEVAL-S-RESULTS.md`](../../../docs/benchmark/LONGMEMEVAL-S-RESULTS.md).

## Headline Result (`dense-top10-claude-haiku-5.5-xhigh-v2-all`)

- **Overall Accuracy (`500` Questions):** **`97.20%` (`486 / 500`)** — 95% Wilson CI `[95.36%, 98.32%]`
- **Task-Averaged Accuracy (`6` Categories):** **`97.93%`**
- **Frozen Dev Split (`100` Questions):** **`98.00%` (`98 / 100`)** (Task-Averaged: `97.87%`)
- **Unseen Held-Out Split (`400` Questions):** **`97.00%` (`388 / 400`)** (Task-Averaged: `97.82%`)
- **Evidence Session Recall@10:** **`99.70%`**
- **Evidence Turn Coverage@10:** **`99.90%`**
- **Reader / Judge:** `anthropic/claude-haiku-5.5` (`--reasoning-effort xhigh`, `32,000` max tokens) / `openai/gpt-4o-mini-2024-07-18`

| Category | Questions (`N`) | Accuracy | Correct / Total |
| --- | :---: | :---: | :---: |
| `single-session-assistant` | `56` | **`100.00%`** | `56 / 56` |
| `single-session-preference` | `30` | **`100.00%`** | `30 / 30` |
| `knowledge-update` | `78` | **`98.72%`** | `77 / 78` |
| `single-session-user` | `70` | **`97.14%`** | `68 / 70` |
| `temporal-reasoning` | `133` | **`96.99%`** | `129 / 133` |
| `multi-session` | `133` | **`94.74%`** | `126 / 133` |

## Files in This Directory

| File | Split | Questions | Accuracy | Task-Averaged | Notes |
| --- | :---: | :---: | :---: | :---: | --- |
| [`dense-top10-claude-haiku-5.5-xhigh-v2-all.summary.json`](dense-top10-claude-haiku-5.5-xhigh-v2-all.summary.json) | `all` | `500` | **`97.20%`** | **`97.93%`** | Final v2 run summary receipt |
| [`dense-top10-claude-haiku-5.5-xhigh-v2-all.jsonl`](dense-top10-claude-haiku-5.5-xhigh-v2-all.jsonl) | `all` | `500` | **`97.20%`** | **`97.93%`** | Final v2 per-question predictions & judge labels |
| [`dense-top10-claude-haiku-5.5-xhigh-all.summary.json`](dense-top10-claude-haiku-5.5-xhigh-all.summary.json) | `all` | `500` | `93.80%` | `94.85%` | Intermediate v1 run summary (`100.0%` `30/30` abstention) |
| [`dense-top10-claude-haiku-5.5-xhigh-all.jsonl`](dense-top10-claude-haiku-5.5-xhigh-all.jsonl) | `all` | `500` | `93.80%` | `94.85%` | Intermediate v1 per-question predictions & judge labels |
| [`dense-top10-claude-haiku-5.5-all.summary.json`](dense-top10-claude-haiku-5.5-all.summary.json) | `all` | `500` | `93.00%` | `93.66%` | Baseline dense top-10 summary (`claude-haiku-5.5` standard) |
| [`dense-top10-claude-haiku-5.5-all.jsonl`](dense-top10-claude-haiku-5.5-all.jsonl) | `all` | `500` | `93.00%` | `93.66%` | Baseline dense top-10 per-question predictions |
| [`dense-top10-claude-haiku-5.5-dev.summary.json`](dense-top10-claude-haiku-5.5-dev.summary.json) | `dev` | `100` | `94.00%` | `93.73%` | Initial 100-question `dev` split baseline summary |
| [`dense-top10-claude-haiku-5.5-dev.jsonl`](dense-top10-claude-haiku-5.5-dev.jsonl) | `dev` | `100` | `94.00%` | `93.73%` | Initial 100-question `dev` split baseline predictions |
| [`verify-31-misses-haiku-5.5-xhigh.summary.json`](verify-31-misses-haiku-5.5-xhigh.summary.json) | `31` R1 misses | `31` | `74.19%` | `68.97%` | Targeted diagnostic verification on the 31 Run 1 misses |
| [`verify-31-misses-haiku-5.5-xhigh.jsonl`](verify-31-misses-haiku-5.5-xhigh.jsonl) | `31` R1 misses | `31` | `74.19%` | `68.97%` | Per-question logs for the 31 Run 1 misses check |
| [`smoke-dev-wrong-haiku-5.5-xhigh-v2.summary.json`](smoke-dev-wrong-haiku-5.5-xhigh-v2.summary.json) | `6` Dev misses | `6` | **`66.67%`** | **`72.22%`** | Dev-miss verification run (`4/6` solved) |
| [`smoke-dev-wrong-haiku-5.5-xhigh-v2.jsonl`](smoke-dev-wrong-haiku-5.5-xhigh-v2.jsonl) | `6` Dev misses | `6` | **`66.67%`** | **`72.22%`** | Per-question logs for Dev-miss verification (`4/6`) |
| [`smoke-dev-wrong-haiku-5.5-xhigh.summary.json`](smoke-dev-wrong-haiku-5.5-xhigh.summary.json) | `6` Dev misses | `6` | `66.67%` | `77.78%` | Initial Dev-miss smoke test (`4/6` solved) |
| [`smoke-dev-wrong-haiku-5.5-xhigh.jsonl`](smoke-dev-wrong-haiku-5.5-xhigh.jsonl) | `6` Dev misses | `6` | `66.67%` | `77.78%` | Per-question logs for initial Dev-miss smoke test |
