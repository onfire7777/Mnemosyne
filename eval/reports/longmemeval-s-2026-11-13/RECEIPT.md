# Benchmark receipt — longmemeval_s_cleaned.json (all)

**Score: 465/500 = 93.0%** (Wilson 95% CI 90.4%–94.9%); task-averaged 94.2%; abstention 28/30

| Setting | Value |
| --- | --- |
| Run id / attempt on this scope | b79f4719088a / 1 |
| Code | /Users/admin/Desktop/Mnemosyne @ `044ddd7bc3f1ceccfb81dfd1e719bcc02571a735` |
| Dataset sha256 | `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442` |
| Reader / judge | anthropic/claude-haiku-5.5 / openai/gpt-4o-2024-08-06 |
| Settings | {"reasoning_effort": "xhigh", "reader_tokens": "32000", "mode": "dense", "embedding": "cloud:qwen/qwen3-embedding-8b", "top_k": "10", "reader_prompt": "official"} |
| Pinned files | eval/longmemeval_s/run_bench_LongMemEval.py `c50ea4ad39b0`, eval/longmemeval_s/split.json `cee1c4b7a3cb` |
| Leak check before run | passed |
| Command | `python -m eval.longmemeval_s.run_bench_LongMemEval --data longmemeval_s_cleaned.json --reader anthropic/claude-haiku-5.5 --reasoning-effort xhigh --reader-tokens 32000 --mode dense --embed cloud --top-k 10 --split all --workers 4 --run final-500` |

| Type | Correct | Accuracy |
| --- | --- | --- |
| knowledge-update | 68/72 | 94.4% |
| knowledge-update/abstention | 5/6 | 83.3% |
| multi-session | 104/121 | 86.0% |
| multi-session/abstention | 11/12 | 91.7% |
| single-session-assistant | 56/56 | 100.0% |
| single-session-preference | 28/30 | 93.3% |
| single-session-user | 63/64 | 98.4% |
| single-session-user/abstention | 6/6 | 100.0% |
| temporal-reasoning | 118/127 | 92.9% |
| temporal-reasoning/abstention | 6/6 | 100.0% |

## Audit

- PASS: every in-scope item graded once, scope respected, frozen dataset/models, results after freeze

## Disclosure

- **One attempt.** The run was frozen once (run `b79f4719088a`, commit `044ddd7b`). It was interrupted twice by
  infrastructure and resumed with the same frozen code and settings; finished questions were kept, never rerun
  (`benchmark-runs.jsonl`): a dropped connection after 76 questions, and the OpenRouter credit in-flight limit after
  479. Parallel workers went 4 → 2 → 1; nothing else changed. `freeze.py verify` passed after the run.
- **Official configuration.** Reader prompt: the unmodified LongMemEval Chain-of-Note prompt (no added rules).
  Judge: `openai/gpt-4o-2024-08-06` with the official per-type prompts. Reader `anthropic/claude-haiku-5.5`,
  reasoning effort xhigh. Dense retrieval (`qwen/qwen3-embedding-8b`), top 10 of ~50 sessions, a fresh store per question.
  Retrieved sessions contained the gold evidence for 98.3% of questions. Cost $3.21.
- **Splits.** Development = the 100 lowest sha256(question_id) (`eval/longmemeval_s/split.json`); tuning used only
  those (`development/`). Development 96/100, held-out 369/400 = 92.25%. LongMemEval reuses filler sessions across
  questions, so development haystacks contain evidence turns for 63 held-out questions; this is part of the dataset.
- **Full-context baseline (partial).** Same reader, every session, no memory system: 41/45 development questions
  before the credit balance ran out; the memory system scored 42/45 on the same 45.
- **Earlier exposure, now removed.** Before the 12–13 Nov 2026 cleanup, development of this code base had seen
  held-out questions: the internal quality gate contained 99 held-out LongMemEval questions, engine rules and
  examples were written around specific held-out questions, and a benchmark reader prompt contained held-out
  answers. All identified material was removed (merges `lme-src`, `lme-tests`, `lme-gate`); the plain-text
  contamination scan and the hashed fingerprint guard (`.benchmark-guard/`, run in CI) are clean at the frozen
  commit. Aggregate tuning from that period (weights, thresholds) cannot be fully separated and may remain.
  Earlier LongMemEval-S figures (92.4%, 97.2%) are retired.
- **Comparisons.** Hindsight's published 94.6% and other vendor numbers use different readers, judges or setups;
  none is a controlled comparison with this run.
