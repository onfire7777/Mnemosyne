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

- Reuse `src/mnemosyne/retrieval.py::HttpReranker` and the existing compact
  reranker JSON contract. Do not add an ML runtime to Python core.
- Reuse `rust/mneme-providers` for the model sidecar. Its existing FastEmbed
  reranker path and model-name custody are the shortest supported route.
- Reuse `src/mnemosyne/providers/grounded_reader.py::CommandGroundedProvider`
  for disclosed command custody and `src/mnemosyne/answering.py` for the
  authoritative grounded-reader protocol.
- Add an extractive sidecar endpoint only when the bakeoff selects a reader.
  It returns evidence CID, start offset, end offset, null score, confidence,
  model revision, and artifact digest; the host reconstructs the answer.
- Keep ONNX Runtime, tokenizer assets, and model weights behind an optional
  Rust feature/sidecar image. The required Python dependency set remains
  unchanged.

## Pinned no-download bakeoff

### Reader candidates

| Candidate | Hub revision | Parameters | Context | License | Use |
|---|---|---:|---:|---|---|
| `deepset/bert-medium-squad2-distilled` | `35d9bf85420e75cd5685551e825e02fd2c553b4c` | 41.11M | 512 | MIT | Preferred 8 GB baseline |
| `deepset/minilm-uncased-squad2` | `934656cdda79824eabf503ed56e15c01ddbdbe3f` | 33.36M | 512 | CC-BY-4.0 | Smallest baseline |
| `deepset/tinyroberta-squad2` | `12b287c9df677e28b07f0a023850dba68c997dbf` | 81.53M | 514 | CC-BY-4.0 | Compact challenger |
| `deepset/deberta-v3-base-squad2` | `eea39c60cc305c2e4a9504f5ff117294bebb42db` | 183.83M | 512 | CC-BY-4.0 | Quality reference/teacher |
| `answerdotai/ModernBERT-base` | `8949b909ec900327062f0ebf497f51aef5e6f0c8` | 149.66M | 8192 | Apache-2.0 | Experimental custom-head challenger |

ModernBERT is not the first reader implementation: current Transformers
support does not provide an official ModernBERT question-answering class. A
custom span head and export must pass separate parity and supply-chain review.

### Reranker candidates

| Candidate | Hub revision | Parameters | Context | License | Use |
|---|---|---:|---:|---|---|
| `cross-encoder/ms-marco-MiniLM-L6-v2` | `c5ee24cb16019beea0893ab7796b1df96625c6b8` | 22.71M | 512 | Apache-2.0 | Preferred floor baseline/student |
| `Alibaba-NLP/gte-reranker-modernbert-base` | `f7481e6055501a30fb19d090657df9ec1f79ab2c` | 149.61M | 8192 | Apache-2.0 | Primary quality challenger/teacher |
| `BAAI/bge-reranker-base` | `2cfc18c9415c912f9d8155881c133215df768a70` | 278.04M | 514 | MIT | Standard-tier challenger |
| `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | 567.76M | 8194 | Apache-2.0 | Multilingual teacher/higher tier |

The Qwen3 0.6B reranker is not the floor default: it is a causal language
model and adds complexity without solving the exact-span reader boundary.

## Resource contract

The 8 GB floor is a deployment admission target, not a claim of measured
performance:

- one inference request and one loaded model at a time;
- batch size 1 and a bounded queue;
- 384-512 token windows with deterministic overlap and answer-span mapping;
- sidecar RSS hard ceiling of 3 GiB;
- whole deployment ceiling of 6.5 GiB;
- at least 1.5 GiB available memory and no sustained swap growth;
- CPU threads capped from detected physical cores;
- no simultaneous PyTorch and ONNX copies; and
- dynamic INT8 promoted only after FP32-to-INT8 exact-span, null-decision,
  calibration, retrieval, and rail parity.

INT4 is not the default for encoders. If distillation or quantization misses a
quality gate, retain the larger model and accept slower floor operation rather
than weakening the gate.

## Purpose-built model

The preferred owned model is a roughly 50-100M parameter shared encoder with:

- a pairwise relevance head for candidate/evidence ranking;
- start and end span heads;
- a calibrated no-answer/null head; and
- no decoder or free-form generation surface.

Distill from the strongest custody-approved teacher pair. The student must
beat both compact baselines on the same public development corpus before it can
replace either component. A stronger model may remain available in the
existing `standard`, `accelerated`, or `frontier` profiles; all profiles use
the same evidence contract and quality gates.

## Dataset custody

| Source | Pinned revision | Disposition |
|---|---|---|
| `rajpurkar/squad_v2` | `3ffb306f725f7d2ce8394bc1873b24868140c412` | TRAIN only; reserve validation; CC-BY-SA-4.0 |
| `hotpotqa/hotpot_qa` | `1908d6afbbead072334abe2965f91bd2709910ab` | `distractor/train` only; do not duplicate `fullwiki/train`; CC-BY-SA-4.0 |
| `xanhho/2WikiMultihopQA` | `612bc5039a457880d9e7d84c3b0a4cf154b70e4f` | Conditional TRAIN only after upstream equivalence and file-hash proof; Apache-2.0 card |
| Official MuSiQue v1.0 | Pending exact upstream pin | Deny mirrors without provenance/license metadata |
| `UCLNLP/adversarial_qa` | `c2d5f738db1ad21a4126a144dfbb00cb51e0a4a9` | Quarantine: conflicting license metadata and SQuAD passage overlap |

Permanently deny `qa_hard_v2`, every LongMemEval split, every Hippo evaluation
track, and all derived benchmark artifacts from training, distillation,
calibration, prompt examples, or hard-negative mining.

Each authorized row records source repo, exact revision, split, upstream ID,
license, content hash, transform hash, and overlap verdict. Deduplicate by
source ID plus normalized question/context/answer hashes. Near-duplicate checks
use protected one-way fingerprints only; any overlap drops the entire source
document cluster without revealing protected content.

Only exact contiguous authorized spans train the reader. Yes/no,
non-contiguous, or unsupported answers may train ranking but never span output.

## Training and promotion order

1. Materialize and hash the authorized TRAIN-only corpus without model work.
2. Run the compact baseline pair.
3. Run the quality challenger pair as teachers/reference models.
4. Train the shared dual-head student with deterministic seeds and a held-out
   public development/calibration partition.
5. Export ONNX FP32, then dynamic INT8.
6. Measure exact spans, null decisions, calibration, retrieval contribution,
   peak RSS, swap delta, and latency under the hardware preflight.
7. Run the exact 24-row development wrapper and all rail/regression classes.
8. Preregister a new candidate only after every development gate passes.

Remote Hugging Face training is preferable to loading training models on the
current 16 GB development Mac. No paid job may start until the corpus manifest,
training script, private output target, cost/timeout estimate, and explicit
spend authority are all present. Training output remains private until PBPP
and independent reproduction permit publication.

## Promotion gates

- no regression in deterministic Recall@5 or nDCG@5;
- exact-span and no-answer thresholds fixed before protected access;
- zero unsupported/fabricated CID or span output;
- positive provenance-linked graph/PPR participation where applicable;
- float/quantized parity within preregistered tolerances;
- 8 GB resource admission without swap thrashing;
- every §31 rail and §33 test class green; and
- a new immutable model/runtime/candidate manifest, never reuse of v19 custody.

## Sources

- Hugging Face model cards for every pinned repository above.
- [Transformers ModernBERT documentation](https://huggingface.co/docs/transformers/model_doc/modernbert).
- [Optimum ONNX and quantization quick tour](https://huggingface.co/docs/optimum/quicktour).
- Plan A, Plan B, PBPP, Phase 12 validation, and the hardware workload
  preflight in this repository remain authoritative over this research note.
