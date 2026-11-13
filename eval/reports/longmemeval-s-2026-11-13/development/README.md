# LongMemEval-S development runs (12-13 Nov 2026)

Development split only: the 100 question ids with the lowest sha256 (`eval/longmemeval_s/split.json`).
No held-out question was run, read or inspected during this tuning. Reader `anthropic/claude-haiku-5.5`
(reasoning effort xhigh, 32,000 output tokens), official judge `openai/gpt-4o-2024-08-06`, dense retrieval
(`qwen/qwen3-embedding-8b`), top 10 sessions, a fresh in-memory store per question.

| Run | Reader prompt | Accuracy | Task-avg | Abstention | Cost |
| --- | --- | --- | --- | --- | --- |
| dev-baseline-clean | official LongMemEval prompt | 95/100 | 95.2% | 5/5 | $0.64 |
| dev-rules-v1 | official + `reader_rules_v1.txt` | 97/100 | 97.4% | 3/5 | $0.66 |
| dev-rules-v2 | official + `reader_rules_v2.txt` | 95/100 | 94.6% | 4/5 | $0.66 |
| full-context baseline | official prompt, every session, no memory system | 41/45 (stopped: credits) | - | - | $4.25 |

On the same 45 questions the memory system scored 42/45 and full context 41/45; the full-context run was
cut short when the OpenRouter balance ran out, so it is a partial comparison.

**Decision:** the frozen final run uses the official reader prompt with no added rules. The rule sets did not
give a gain that survives run-to-run noise on 100 questions (v1: +2 overall but -2/5 abstention; v2: no gain),
and the unmodified official prompt is the most comparable and reproducible configuration.

The rules files were written from development misses only and name no benchmark content; they remain in
`eval/longmemeval_s/` as recorded, unadopted experiments.

`dev-rules-v2` ran while quality-gate reports were being regenerated in the same tree, so its summary records
`git_dirty: true`; the code under test was committed.
