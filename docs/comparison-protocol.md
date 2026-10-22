# Mnemosyne–Hindsight controlled comparison protocol

This is a **14-question, balanced, held-out pilot of native ingestion and recall with a common reader and judge**. It is not a native `reflect` comparison, a reproduction of a vendor score, a full LongMemEval result, or evidence of a global ranking. A protocol and passing harness tests are not a completed benchmark result. Publish a result only with its frozen manifest, configuration, first-attempt records, and completion status.

**Execution status:** the owner cancelled the 22 October trial during Hindsight
ingestion to prioritize Mnemosyne runtime improvements. No Hindsight case completed
and no common reader/judge run or comparison score was produced. The
[cancellation receipt](../work/hindsight-comparison/controlled/run-v1/hindsight-cancellation.json)
preserves partial usage and cleanup evidence. The protocol below documents the
stopped experiment; it is not an instruction to resume it.

The implementation is [`eval/comparison_protocol.py`](../eval/comparison_protocol.py); regressions are in [`tests/test_comparison_protocol.py`](../tests/test_comparison_protocol.py). It uses only the standard library and existing local metric helpers. The comparison keeps Mnemosyne and Mnemetric code, data, and execution separate.

## Dataset and selection, frozen before inference

Use the complete cleaned LongMemEval S dataset at revision `98d7416c24c778c2fee6e6f3006e7a073259d48f`, with SHA-256:

```text
d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442
```

Source: [pinned dataset file](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json). The [official benchmark repository](https://github.com/xiaowu0162/LongMemEval) documents the question types, `_abs` abstention suffix, session format, and answer/session annotations. The [cleaned dataset page](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) describes the cleaned release.

Selection reads **only `question_id` and `question_type`** from all 500 rows. Exclude the existing local development split: the 100 lowest SHA-256 digests of question IDs, matching `eval/longmemeval_recall.py`. In the remaining 400, select two non-abstention questions per question type and two abstention questions across types. Within each stratum, sort by `SHA256("mnemosyne-hindsight-controlled-v1" + NUL + question_id)`, using the ID to break a hash tie, and take the first two. Row order, history length, prior correctness, and gold answers cannot affect selection.

| Stratum | Frozen IDs |
| --- | --- |
| Knowledge update | `45dc21b6`, `69fee5aa` |
| Multiple sessions | `bf659f65`, `92a0aa75` |
| Single session, assistant | `778164c6`, `8464fc84` |
| Single session, preference | `35a27287`, `1d4e3b97` |
| Single session, user | `21436231`, `3f1e9474` |
| Temporal reasoning | `gpt4_68e94287`, `gpt4_1916e0ea` |
| Abstention | `2311e44b_abs`, `6aeb4375_abs` |

These cases contain **686 full sessions and 6,822,813 message-content Unicode characters**. This is roughly 1.7 million characters-divided-by-four token estimates before native extraction overhead; it is not a tokenizer measurement. Do not shorten histories or substitute cheaper questions after seeing their cost or answers. “Held out” means excluded from this repository's development split, not secret or guaranteed unseen by a pretrained model.

## Frozen execution contract

Before the first scored attempt, write `selection_manifest(rows, dataset_sha256, source_config_sha256=...)` and call `validate_manifest(manifest)` before inference. The source/configuration digest must bind an archived, canonical configuration containing both source revisions (including dirty source-file hashes), Hindsight image/package identity, ingestion and retrieval options, provider/embedding/reranker identities, prompt source hashes, environment versions, timeouts, concurrency, and arm execution order. Archive the configuration itself, not just its digest. Each result must carry the resulting `manifest_sha256`. Changes require a separately named run; do not combine incompatible runs.

Use a fresh store/bank for each question and arm. Give both arms every session, date, and user/assistant message in the same chronological source order. Retention must finish successfully before recall. Record partial or failed retention as a failed case rather than querying an incomplete bank. There is one scored reader attempt and one judge attempt per successful question/arm; do not pick the best of retries. Resume by preserving existing terminal records and their first-attempt identity, not by overwriting them.

| Component | Mnemosyne arm | Hindsight arm |
| --- | --- | --- |
| Source corpus | All original dated sessions | Same original dated sessions |
| Ingestion representation | Existing benchmark `context=rounds`, `mode=default`: deterministic user/assistant rounds appended as evidence | Full-session documents processed by Hindsight's native extraction/chunking |
| Recall | Standard `LocalMemoryEngine.retrieve`, `top_k=200`, large internal context allowance before common packing | Native Hindsight recall; archive exact candidate/budget, embedding, reranker, and native processing options |
| Reader context | The shared `pack_context` applied to returned ranked text | The same shared `pack_context` applied to returned ranked text |
| Answer and grading | Common isolated Codex reader and independent common Codex judge | Same reader, judge, prompt templates, and requested settings |

The two engines produce different representations and may make different numbers of native processing calls. Those differences are part of the measured ingestion/recall pipeline, not a reason to hide processing latency or quota use. The common reader controls the final answer backbone; it does not make every internal algorithm identical. Record any bridge, embedding, or reranker substitution explicitly. Do not label an adapted backend configuration as the vendor's published benchmark configuration.

The Hindsight setup for this pilot pins source commit `0691b504a88480844b2db53384b8c81971b7cf1e` (source archive SHA-256 `f914adefc7976a50f2925a82caa9135f64676dffe6bea6444b99127c1656591e`) and `hindsight-api-slim` version `1.1.0` with local ML dependencies. Frozen native settings are CPU `BAAI/bge-small-en-v1.5` embeddings, CPU `cross-encoder/ms-marco-MiniLM-L-6-v2` reranking, PostgreSQL/pgvector text and vector retrieval, an explicit **32,000-character extraction chunk setting**, synchronous native consolidation, default recall budget, 4,096 native fact tokens, default observation preference, and no source-chunk inclusion. Native fact dates (`occurred_start`, `occurred_end`, `mentioned_at`) are rendered with fact text inside the common reader budget. Background reconciliation is disabled to prevent unrecorded later retries; synchronous consolidation remains enabled. A Codex bridge replaces the native LLM interface; the native requested 64,000 completion-token setting is **not enforced** by that bridge.

The runtime fingerprint in `work/hindsight-comparison/controlled/hindsight-environment.json` binds installed native-code hashes, Python/distribution versions, model revisions and file hashes, PostgreSQL extensions, and image digest. Its canonical SHA-256 is `236bbad5fee82fb9a90114ab222aafb5ddea9e62e067d5b075bbeb285eed6a48`; the database image is `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`. Selected runs require this fingerprint and recompute it before ingestion, checking that its digest is bound by the comparison configuration. The installed runtime completed initialization, and a separate **synthetic one-session native retain/recall smoke test** completed with one retained fact and two recalled candidates. Those setup receipts and 15 passing adapter tests establish integration readiness, not benchmark accuracy or full-corpus completion.

The bridge allows at most three concurrent Codex calls and one CLI attempt per bridge invocation. Native Hindsight operations may independently retry or split work: retain every invocation receipt and include its cost/latency. This is different from rerunning a scored reader response to choose a better answer, which the protocol forbids.

Alternate arm order deterministically by manifest row, or freeze an equivalent ID-hash ordering before execution. Include order in receipts. Run the judge without backend names or identifying comparison commentary. Dataset dates without offsets follow the existing benchmark's UTC convention; archive any backend-specific conversion.

## Inference and label boundaries

`inference_payload(row)` allows only the question, question date, and dated sessions with `role`/`content` turns. It drops question ID (whose `_abs` suffix reveals abstention), question type, gold answer, `answer_session_ids`, `has_answer`, and every other annotation. It rejects malformed or misaligned histories. Feed only its **sessions** to ingestion: the future question must not guide extraction. Supply the question/date only at recall and reading time.

Use a single answer-prompt template for both arms and the existing official type-specific grading templates in `eval/longmemeval_s/run_bench_LongMemEval.py`, with template source hashes frozen in the run configuration. Gold answers and question types are available only in the independent grading step. Do not use oracle histories, evidence labels, previous wrong-case lists, or grader feedback to select documents, change retrieval, or regenerate answers.

Both reader and judge request `gpt-6-astra` at reasoning effort `low` through the existing Codex account. Each call is isolated from tools, files, network, personal memory, plugins, and other benchmark cases by `eval/codex_reader.py`. Archive requested model, observed resolved model (or `null` if unavailable), prompt digest, CLI version, elapsed time, and available usage. An unknown resolved model must remain unknown; a reported mismatch must be disclosed and investigated before claiming a controlled model comparison.

`pack_context(texts)` preserves returned rank order, labels items `[Memory n]`, and admits at most **16,000 Unicode code points**, including labels and separators. It truncates only the last admitted item. Its advertised **4,000 estimated tokens** means `ceil(code_points / 4)`, not a hard tokenizer bound. The question, common prompt, and output are outside this evidence-context cap. Record packed context hash, actual character count, estimated count, candidates offered/included, truncation, native candidate IDs, and original document references when available.

**Codex generation token caps and temperature are not enforced by this adapter.** Report that limitation for both arms. Native backend caps remain separately recorded settings; neither the context estimate nor a backend token option proves enforcement by Codex. Subscription quota is a resource cost even when a separate API charge is absent; unknown monetary cost is `null`, not zero.

## Result records and scoring

For each `(question_id, arm)`, retain the terminal status (`completed` or `failed`), frozen manifest hash, timings, receipts, and error stage/category where applicable. Completed cases require:

- A Boolean `judge_label` agreeing with the judge's exact `yes`/`no` response.
- Separate reader/judge receipts with answer, prompt SHA-256, requested model/effort, and observed model or `null`.
- Finite non-negative `stage_seconds`: `retain`, `recall`, `reader`, `judge`, and `total`. Because ingestion and answering run as separate commands, `total` adds native retain/recall durations to reader/judge-stage wall time; it excludes the wait between those commands and is not calendar elapsed time.

Preserve available timings, partial receipts, and diagnostic errors for failures. Use aware `started_at`/`finished_at` timestamps together when recorded, and state the stage they cover; answer-record timestamps cover the reader/judge phase. Retain per-stage usage and native processing calls in raw receipts; aggregate only compatible counters. Do not infer zero usage from a failed or missing call. Avoid exposing credentials in any artifact.

`score_comparison(manifest, records)` rejects duplicates, unselected IDs, incompatible manifests/settings, contradictory labels, and malformed measurements. **Failed and missing cases score zero, with a fixed denominator of 14 for each arm.** An interrupted run reports `complete=false` and explicitly counts missing cases; its provisional score is not a completed comparison. `complete=true` means all 28 terminal records exist, including failures. `all_inference_completed=true` additionally requires that every case completed inference and grading.

The report includes per-question paired scores and timing, per-stratum accuracy, overall accuracy, completion counts, measured latency mean/p50/p95, and known versus unknown monetary cost. Because the sample is balanced by seven strata, overall accuracy is an equal-stratum pilot measure; it is not an estimate obtained by matching the full dataset's category proportions.

Uncertainty reporting includes per-arm Wilson intervals, paired differences, exact two-sided McNemar diagnostics, and a **paired stratified percentile bootstrap** (10,000 resamples, seed `20261022`). Each resample selects two question pairs with replacement within each of seven strata, keeping the arm pairing intact. A conservative bounded paired-difference Hoeffding interval is also reported. With only two cases per stratum, bootstrap intervals can collapse even for perfect ties or wins; the report flags that collapse. These are descriptive small-sample diagnostics under independence/exchangeability assumptions, not proof of superiority or protection against selection bias, correlated cases, or model nondeterminism.

Publish the actual numerator/denominator, failures, paired intervals, configurations, and unresolved limitations together. A promising pilot justifies a larger, separately frozen evaluation; it cannot support “number one” or “better than Hindsight” as a general claim.
