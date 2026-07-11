# Public evaluation harness

Run the redistributable development self-test with `uv run --locked mneme
eval-public --suite smoke --out-dir /tmp/mneme-smoke`, then verify it with
`uv run --locked mneme eval-public --verify-bundle /tmp/mneme-smoke`.

The smoke suite exercises Mnemosyne exclusively through public CLI subprocesses.
It is permanently non-publishable, ineligible for PBPP headlines, and is not an
independent external reproduction. Retrieval proportions use Wilson intervals;
future answer-quality tracks must name their reader/judge and use bootstrap
intervals. Families are never aggregated.

## Frozen Phase 12 QA protocol

The `_qa_protocol` registry entry preregisters the static `qwen3:8b` Ollama
selector, exact decoding options, evidence and hop budgets, canonical empty
answer abstention, `qa-em-f1-v1`, frozen split roles, zero transport retries,
and a single held-out attempt. A post-commit candidate manifest is external,
no-overwrite, and must bind the exact git SHA plus resolved model-content,
prompt-template, evidence-serializer, decoding, and protocol digests before a
frozen run. The registry deliberately contains no self-referential git SHA.

Phase 11 point metrics and generated report/manifest digests are frozen in that
entry. QA bundles are separate from retrieval bundles, disclose reader custody
in `judge.json`, carry benchmark-owned answer labels only for scorer
recomputation, and require cited atomic claims or canonical abstention. The
held-out LongMemEval and HippoRAG splits are never development inputs.

QA bundle verification is intentionally exact-checkout scoped: the embedded
candidate manifest, QA-only `build.json`, reader custody, and current checkout
must all name the same 40-hex commit. Reproduction reuses the retained canonical
`candidate-manifest.json`; verifying from another commit fails closed instead
of silently treating different code as the frozen candidate.
