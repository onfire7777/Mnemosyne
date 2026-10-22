# Hindsight comparison: ranking evidence

Verified 22 October 2026 against the live Mnemetric site. This is an evidence
audit, not a new benchmark run or a claim of superiority.

## What sixth place means

The [Mnemetric LongMemEval chart](https://mnemetric.burnos.app/#accuracy)
places Mnemosyne sixth: Chronos 95.6%, Hindsight 94.6%, Mem0 94.4%, ByteRover
92.8%, Mastra 92.8%, Mnemosyne 92.4%. The site explicitly cautions that this
is not a ranking under common conditions. Readers, retrieval settings and
evaluation procedures differ. Its [system listing](https://mnemetric.burnos.app/claims.html)
identifies our entry as `onfire7777/Mnemosyne`, not the unrelated
`mnemosyne-oss/mnemosyne` project.

## Our published result and limitations

The [live claims JSON](https://mnemetric.burnos.app/data/claims.json) reports:

- LongMemEval-S: 462/500 answers correct (92.4%; bootstrap interval 90.0–94.6%).
- Held-out subset: 366/400 (91.5%; interval 88.7–94.3%).
- Dense `qwen3-embedding-8b` retrieval, top ten sessions, `claude-haiku-5.5`
  reader with a 4,000-token cap, and `gpt-4o-mini-2024-07-18` judge using the
  official `evaluate_qa.py` prompts.
- Gold-session coverage 97.9% is a separate retrieval metric, not answer accuracy.
- Operator-run custom evaluation loop; no signed custody bundle; development
  and held-out split reported but not enforced by the runner.
- Earlier 80.6% was understated by an 800-token reader cap and is superseded.

The JSON points to commit `1545424460541b74d629344b96e60b735fd2108c` in
Mnemetric, `docs/evidence/longmemeval-s-2026-10-08/README.md`, lines 18 and 20.
Unauthenticated raw GitHub retrieval returned 404, but the authenticated GitHub
connector recovered the pinned README and all 500 JSONL rows. Recomputing their
aggregate counts confirmed 462/500 overall, 96/100 development and 366/400
held-out; all 500 responses have `finish_reason=stop`. Among the 38 misses,
14 lack complete evidence and 24 have complete evidence (the README labels
the latter as 23 reader failures and one abstention failure). Aggregate type
counts are user facts 68/70, multi-session 113/133, preferences 28/30,
temporal reasoning 126/133, knowledge updates 71/78 and assistant facts 56/56.
This checks recorded outcomes, not the correctness of the judge itself. No
question-level held-out failure analysis was used to tune this change. The local
Mnemetric checkout was an older October 4 development branch and was not
substituted for the current live publication.

## Comparison target

[Hindsight's benchmark page](https://benchmarks.hindsight.vectorize.io/)
reports LongMemEval-S 94.6%, LoCoMo 92%, PersonaMem32K 86.6%, LifeBenchEN
71.5%, and BEAM single-query results of 75%/71.1%/73.9%/64.1% at
100K/500K/1M/10M. Mnemetric also records higher BEAM comparison-table results
with different mode provenance; these must not be merged with single-query
measurements. The [public AMB harness](https://github.com/vectorize-io/agent-memory-benchmark)
is operated by Hindsight's maker, Vectorize.

Our displayed LongMemEval gap is 2.2 percentage points. Closing it requires
measuring both systems with pinned, matching dataset, reader, judge, retrieval
budget and mode. Audit the 38 recorded failures and the 34 held-out failures;
retain question-level traces, cost and latency; keep development tuning apart
from final evaluation. A larger number under different settings would not
establish first place or complete feature parity.
