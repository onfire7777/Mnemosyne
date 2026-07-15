# Compact Model Physical 8 GB Acceptance

Status: preregistration contract; no 8 GB compatibility or performance claim
exists until this protocol is completed on physical 8 GB systems.

## Scope

This contract proves the compact grounded QA stack can operate on low-end
hardware without lowering Mnemosyne's quality, custody, authorization, or
publication gates. It is separate from `HARDWARE-WORKLOAD-PREFLIGHT.md`, which
protects the current 16 GiB development Mac and is not a product requirement.

Required floor evidence covers native x86-64 AVX2 Windows and Linux CPU
systems with exactly 8 GiB physical memory. ARM64 CPU evidence is an additional
target, not a substitute. Runtime profiles remain `floor`, `standard`,
`accelerated`, and `frontier`; this contract does not create or rename a tier.

## Immutable prerequisites

Before downloading or executing a model, freeze an external no-overwrite
manifest containing:

- repository and code SHA;
- source/transformed corpus manifests and overlap-policy version;
- model, tokenizer, config, LICENSE, README, ONNX, and sidecar filenames plus
  SHA-256 or LFS OIDs;
- base/checkpoint/dataset licenses and attribution obligations;
- exporter, Transformers, Optimum, ONNX, ORT, and Rust-ORT versions;
- opset, graph optimization, execution provider, and quantization config;
- score fusion, rank width, top-k, token/window/stride, null threshold,
  calibrator, thread, queue, deadline, and resource settings; and
- hardware/OS/CPU profile and exact-scale receipt digest.

Only safetensors and ONNX are allowed. Pickle, `trust_remote_code`, runtime
downloads, symlinked model files, protected data, and network model access are
forbidden. Missing or drifted inputs fail closed.

## Fixed floor runtime envelope

- model/tokenizer artifacts: at most 1 GiB total;
- compact sidecar peak RSS/working set: at most 3 GiB, target at most 2 GiB;
- entire Mnemosyne process-tree PSS/working set: at most 6.5 GiB;
- system available memory: at least 1.5 GiB after warmup and throughout the
  exact-scale workload;
- batch size 1, request concurrency 1, queue depth 1, one model session loaded;
- ORT intra-op threads `min(2, detected physical cores)`, inter-op threads 1;
- 512-token maximum context, fixed 128-token stride, rank width at most 8;
- request at most 64 KiB, query at most 2,000 characters, at most 20 evidence
  rows and 24,000 evidence characters;
- hard 30-second request deadline; and
- loopback bind or mandatory bearer authentication.

For a two-model baseline, the ranker and reader are loaded sequentially under
an explicit unload/reload policy; they may not be co-resident. Measure both
cold load and warm inference. Any sustained Linux swap, Windows pagefile
growth, macOS swapout, memory-pressure throttling, OOM, deadline breach, or
fallback rejects the candidate.

## Quality and rail parity

Run the same immutable inputs through reference, ONNX FP32, and ONNX INT8
artifacts. Promotion requires:

- exact decoded span and abstention agreement on every rail fixture and every
  `qa_scale_dev_v1` row;
- the canonical receipt remains 24/24 with EM/F1 and Recall@5/nDCG@5 all 1.0;
- zero CID, authorization, provenance, raw-offset, or retrieval-trace drift;
- no decrease in locked TRAIN-derived development EM/F1, ranking metrics,
  calibration ECE, or abstention quality;
- explicit coverage at lengths 64/128/384/512 plus Unicode, repeated answers,
  null answers, window boundaries, and multi-window reconstruction; and
- every §31 invariant rail and §33 test class green.

Static quantization may use only the locked TRAIN-derived calibration
partition. INT4 is outside this contract until a separate parity protocol is
preregistered and passes.

## Physical-machine procedure

For each required OS/platform:

1. Start from a clean 8 GiB machine with no unrelated intensive workload.
2. Record OS/build, CPU model/features, physical/logical cores, memory, storage,
   runtime versions, power mode, and manifest digests.
3. Record idle memory/swap/pagefile and process inventory.
4. Run one cold load, three warm exact-scale runs, and one unload/reload run.
5. Sample process-tree and system memory at least once per second; retain raw
   RSS/PSS/working-set, available-memory, swap/pagefile, CPU, latency, timeout,
   and error traces.
6. Report cold/warm P50/P95 latency, throughput, peak memory, swap/pagefile
   delta, failures, and exact output-parity hashes without selecting the best
   run.
7. Seal the evidence bundle and reproduce it on the second required platform.

A failure is evidence, not permission to raise a resource limit, weaken a
quality threshold, or omit a platform. The candidate returns to development
under a new preregistration.

## Claim boundary

Passing this contract establishes internal 8 GB admission evidence only. No
externally facing compatibility, performance, benchmark, or leadership claim
may be published until PBPP and genuine independent reproduction are complete.
