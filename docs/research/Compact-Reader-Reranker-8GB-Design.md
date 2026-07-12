# Compact Reader and Reranker Design for an 8 GB Floor

**Status:** Internal research design; no model selected, trained, downloaded,
or published. **Date:** 2026-07-12.

## Decision

Mnemosyne's quality path should be non-generative at the learned boundary:

1. deterministic, source-bound query candidates;
2. a compact cross-encoder reranker;
3. an extractive start/end/null reader;
4. host-side reconstruction of the exact authorized evidence substring; and
5. the existing CID, span, provenance, authorization, abstention, and replay
   validators as the final authority.

The model never invents query text or answer text. Hardware capability may
change latency, context capacity, and concurrency, but never correctness,
grounding, authorization, or publication thresholds.

Candidate v19 is unchanged by this design. Any learned reader/reranker is a
future, separately preregistered, shadow-first candidate with independent
runtime and model-content custody.

## Existing integration seams

- Preserve `src/mnemosyne/retrieval.py::HttpReranker` and every deterministic
  pre-rerank result unchanged. Learned ranking occurs only inside the disclosed
  QA reader over evidence that the orchestrator has already authorized. The
  trace records pre-rank IDs/scores, learned scores, post-rank order, and
  channel provenance separately; the deterministic retrieval column never
  includes learned scores.
- Reuse `rust/mneme-providers` for the model sidecar. Its existing FastEmbed
  reranker path and model-name custody are the shortest supported route.
- Reuse `src/mnemosyne/answering.py::GroundedReader`,
  `GroundedAnswerOrchestrator`, and `_claims()` as the authorization,
  provenance, and exact-substring authority. Candidate v19's
  `CommandGroundedProvider` remains frozen and is not repurposed.
- Add a default-off `compact-grounded` Rust feature and `/grounded-read`
  endpoint only after the bakeoff selects a reader. The route returns only the
  existing `{"claims": [...], "unresolved": bool}` shape. The host revalidates
  every CID/quote and derives raw offsets and UTF-8 hashes; internal model
  scores never become answer text or a self-tuning reward signal.
- Require an external immutable manifest before the route is available.
  Missing/digest-drifted artifacts, OOM/resource breaches, malformed logits,
  timeout, or inference failure fail closed with no fallback reader.
- Keep ONNX Runtime, tokenizer assets, and model weights behind an optional
  Rust feature/sidecar image. The required Python dependency set remains
  unchanged.

## Pinned no-download bakeoff

### Reader candidates

| Candidate | Hub revision | Parameters | Context | License | Use |
|---|---|---:|---:|---|---|
| `deepset/bert-medium-squad2-distilled` | `35d9bf85420e75cd5685551e825e02fd2c553b4c` | 41.11M | 512 | MIT | Compact baseline |
| `deepset/minilm-uncased-squad2` | `934656cdda79824eabf503ed56e15c01ddbdbe3f` | 33.36M | 512 | CC-BY-4.0 | Smallest compact reference |
| `deepset/tinyroberta-squad2` | `12b287c9df677e28b07f0a023850dba68c997dbf` | 81.53M | 514 | CC-BY-4.0 | Compact challenger |
| `deepset/deberta-v3-base-squad2` | `eea39c60cc305c2e4a9504f5ff117294bebb42db` | 183.83M | 512 | CC-BY-4.0 | Quality reference/teacher |
| `answerdotai/ModernBERT-base` | `8949b909ec900327062f0ebf497f51aef5e6f0c8` | 149.66M | 8192 | Apache-2.0 | Experimental custom-head challenger |

ModernBERT is not the first reader implementation: current Transformers
support does not provide an official ModernBERT question-answering class. A
custom span head and export must pass separate parity and supply-chain review.

### Reranker candidates

| Candidate | Hub revision | Parameters | Context | License | Use |
|---|---|---:|---:|---|---|
| `cross-encoder/ms-marco-MiniLM-L6-v2` | `c5ee24cb16019beea0893ab7796b1df96625c6b8` | 22.71M | 512 | Apache-2.0 | Compact baseline/student |
| `Alibaba-NLP/gte-reranker-modernbert-base` | `f7481e6055501a30fb19d090657df9ec1f79ab2c` | 149.61M | 8192 | Apache-2.0 | Primary quality challenger/teacher |
| `BAAI/bge-reranker-base` | `2cfc18c9415c912f9d8155881c133215df768a70` | 278.04M | 514 | MIT | Quality reference |
| `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | 567.76M | 8194 | Apache-2.0 | Multilingual reference |

`Qwen/Qwen3-Reranker-0.6B` revision
`e61197ed45024b0ed8a2d74b80b4d909f1255473` (595.78M parameters,
40,960-token advertised context, Apache-2.0) is a rejected compact reference:
it is a causal language model and adds complexity without solving the
exact-span reader boundary.

## Resource contract

The 8 GB floor is a deployment admission target, not a claim of measured
performance:

- one inference request and one loaded model at a time;
- batch size 1, request concurrency 1, and queue depth 1;
- 384-512 token windows with deterministic overlap and answer-span mapping;
- model/tokenizer artifacts no larger than 1 GiB in aggregate;
- sidecar RSS target of 2 GiB and hard ceiling of 3 GiB;
- whole deployment ceiling of 6.5 GiB;
- at least 1.5 GiB available memory and no sustained swap growth;
- ORT intra-op threads no greater than two or detected physical cores,
  whichever is lower, and inter-op threads fixed at one;
- request body at most 64 KiB, query at most 2,000 characters, at most 20
  evidence rows and 24,000 evidence characters, rank width at most eight, and
  a hard 30-second request deadline;
- offline-only regular-file model directory with no symlinks or runtime
  downloads, bound to loopback or protected by a mandatory bearer token;
- no simultaneous PyTorch and ONNX copies; and
- dynamic INT8 promoted only after FP32-to-INT8 exact-span, null-decision,
  calibration, retrieval, and rail parity.

INT4 is not the default for encoders. If distillation or quantization misses a
quality gate, retain the larger model and accept slower floor operation rather
than weakening the gate.

The development-host preflight is not proof of this product contract. Physical
8 GB acceptance is defined separately in
`.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`.

## Purpose-built model

The preferred owned-model target is a roughly 50-100M parameter shared encoder
with:

- a pairwise relevance head for candidate/evidence ranking;
- start and end span heads;
- a calibrated no-answer/null head; and
- no decoder or free-form generation surface.

Distill from the strongest custody-approved teacher pair. This size and shared
layout are a target envelope, not a predetermined winner. Promotion requires
the absolute CAP/rail gates, non-inferiority to the selected quality-reference
pair on both ranking and reading, and a preregistered shared-vs-two-encoder
ablation. Protected outcomes never select the architecture. A stronger model
may later be assigned to an existing `standard`, `accelerated`, or `frontier`
profile only after measured admission; all profiles use the same evidence
contract and quality gates.

## Shadow implementation boundary

The smallest future implementation, on a post-v19 branch, is:

1. `rust/mneme-providers/src/compact_grounded.rs`: the default-off feature,
   immutable-manifest loader, bounded `/grounded-read` route, and fail-closed
   ONNX execution;
2. `eval/grounded_compact_shadow.py`: a thin HTTP `GroundedReader` adapter that
   reuses the current decomposer/orchestrator and writes only synthetic/dev
   external shadow artifacts; and
3. focused Rust/provider/orchestrator/parity/config tests covering allocation
   caps, auth, artifact drift, Unicode and repeated-span offsets, window
   boundaries, null thresholds, NaN logits, deterministic ordering, timeouts,
   authorization drift, store immutability, no fallback, and byte-identical
   pre-rerank traces.

The shadow route never enters the active `answer` or `eval-answer-batch` CLI,
candidate-v19 registry/bundles, or any protected dataset. Promotion and public
bundle wiring are later custody changes, not part of the shadow scaffold.

## Dataset custody

| Source | Pinned revision | Disposition |
|---|---|---|
| `rajpurkar/squad_v2` | `3ffb306f725f7d2ce8394bc1873b24868140c412` | TRAIN only; carve train-derived selection/calibration partitions; upstream validation excluded; CC-BY-SA-4.0 |
| `hotpotqa/hotpot_qa` | `1908d6afbbead072334abe2965f91bd2709910ab` | `distractor/train` only; do not duplicate `fullwiki/train`; CC-BY-SA-4.0 |
| `xanhho/2WikiMultihopQA` | `612bc5039a457880d9e7d84c3b0a4cf154b70e4f` | Conditional TRAIN only after upstream equivalence and file-hash proof; Apache-2.0 card |
| Official MuSiQue v1.0 | Pending exact upstream pin | Hard-block inclusion until upstream revision, files, hashes, and license digest are fixed |
| Rejected `dgslibisey/MuSiQue` mirror | `c8f4f8c9465fb69d31a8eae894c3fd509c4ca321` | Denied: no README/license metadata |
| `UCLNLP/adversarial_qa` | `c2d5f738db1ad21a4126a144dfbb00cb51e0a4a9` | Denied: frontmatter says CC-BY-SA-4.0, README body says CC-BY-SA-3.0, and passages reuse SQuAD v1.1 |

Permanently deny `qa_hard_v2`, every LongMemEval split, every Hippo evaluation
track, and all derived benchmark artifacts from training, distillation,
calibration, prompt examples, or hard-negative mining.

Each authorized row records source repo, exact revision, split, upstream ID,
base/checkpoint/dataset licenses, attribution/share-alike obligations, raw and
normalized question/context/answer/title SHA-256 values, transform hash, and
overlap verdict. A versioned normalizer fixes Unicode normalization, casing,
whitespace, and deterministic character/token n-gram thresholds. Checks run
before and after transformation across source-document/entity clusters,
including reused Wikipedia passages. The protected matcher exposes pass/fail
and counts only; a hit drops the complete source-document cluster. Teacher
labels and synthetic augmentations inherit the same denylist.

Only exact contiguous authorized spans train the reader. Preserve source byte
or character offsets, then map through tokenizer offsets using the existing
half-open raw-substring convention. Test Unicode, repeated answers, window
boundaries, and sliding-window reconstruction. Yes/no, non-contiguous, or
unsupported answers may train ranking but never span output. No-answer rows
come only from authorized TRAIN material.

Hub commit SHAs are discovery pins, not complete runtime custody. Before a
download, each candidate manifest must also bind exact source filenames and
SHA-256/LFS OIDs, tokenizer/special-token and LICENSE/README digests, generated
ONNX filename/digest, exporter/Transformers/Optimum/ONNX/ORT/Rust-ORT versions,
opset, graph optimization and quantization settings, CPU execution provider,
and sidecar binary/image digest. Only safetensors and ONNX are allowed; pickle
and `trust_remote_code` are forbidden. A ModernBERT QA head must be
source-owned, reviewed, committed, and digest-bound.

## Training and promotion order

1. Materialize and hash the authorized TRAIN-only corpus without model work.
   Carve selection-development and calibration partitions once, grouped by
   source-document/entity cluster. Upstream validation/test and every
   protected/held-out track are excluded from selection and calibration.
2. Run the compact baseline pair.
3. Run the quality challenger pair as teachers/reference models.
4. Preregister the student bakeoff: Stage A uses seed 17, learning rates
   `1e-5`, `2e-5`, and `3e-5`, effective batch 32, sequence length 384,
   stride 128, and three epochs; Stage B reruns the winning configuration at
   seeds 17/29/43 for at most five epochs. Freeze rank/span/null/distillation
   loss weights, early stopping, and winner selection before results.
5. Export ONNX FP32, then dynamic INT8.
6. Measure exact spans, null decisions, calibration, retrieval contribution,
   peak RSS, swap delta, and latency under the hardware preflight.
7. Run the exact 24-row development wrapper and all rail/regression classes.
8. Preregister a new candidate only after every development gate passes.

Remote Hugging Face training is preferable to loading training models on the
current 16 GB development Mac. No job may start until a digest-pinned image,
read-only authorized corpus, training script, private immutable output target,
secrets isolation, retained logs/manifests, cost/timeout ceiling, and explicit
spend authority are all present; protected assets must be unreachable. Model
weight release requires provenance/license approval. Public performance claims
additionally require PBPP and independent reproduction.

## Promotion gates

- `qa_hard_v2` deterministic Recall@5/nDCG@5 remain 1.0/1.0;
- LongMemEval Recall@5/nDCG@5 and all three Hippo Recall@2/@5 tracks do not
  decrease, with byte-identical deterministic pre-rerank traces;
- reader point EM and token F1 reach at least 0.85 on both held-out QA tracks,
  with the required Wilson/bootstrap intervals;
- exact-span and no-answer thresholds fixed before protected access;
- zero unsupported/fabricated CID or span output;
- positive provenance-linked graph/PPR contribution on applicable Hippo cases,
  with score-component traces and a preregistered counterfactual/ablation that
  proves an effect on retrieval or ordering;
- reference-to-ONNX-FP32 and ONNX-FP32-to-INT8 exact decoded span/abstention
  agreement on every rail fixture and `qa_scale_dev_v1`; its canonical receipt
  remains 24/24 with EM/F1 and Recall@5/nDCG@5 all 1.0;
- no locked train-derived development metric, calibration ECE, or abstention
  metric decreases after export/quantization; lengths 64/128/384/512, Unicode,
  repeated-span, null, and multi-window cases are covered;
- 8 GB resource admission without swap thrashing;
- every §31 rail and §33 test class green; and
- a new immutable model/runtime/candidate manifest, never reuse of v19 custody.

This design serves CAP-003 and BENCH-005 reader production. BEAM remains the
separate disclosed LLM-judged track in Plan B. LongMemEval-QA uses a public
source dataset but remains an internal-only held-out QA result.

## Sources

- Hugging Face model cards for every pinned repository above.
- [Transformers ModernBERT documentation](https://huggingface.co/docs/transformers/model_doc/modernbert).
- [Optimum ONNX and quantization quick tour](https://huggingface.co/docs/optimum/quicktour).
- Plan A, Plan B, PBPP, Phase 12 validation, and the hardware workload
  preflight in this repository remain authoritative over this research note.
