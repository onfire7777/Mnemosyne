---
type: decision
title: Mnemosyne Compact Grounded QA and Physical 8 GiB Contract
date: '2026-07-12T00:00:00.000Z'
status: active
tags:
  - compact-model
  - grounded-qa
  - hardware
  - mnemosyne
---

# Mnemosyne Compact Grounded QA and Physical 8 GiB Contract

Mnemosyne's learned QA path is non-generative at the model boundary: deterministic source-bound query candidates, learned ranking only over already-authorized evidence, an extractive span/no-answer reader, and host-side CID/span/provenance/authorization validation as final authority.

Canonical repository artifacts:

- `/Users/admin/Mnemosyne/docs/research/Compact-Reader-Reranker-8GB-Design.md`
- `/Users/admin/Mnemosyne/.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md`
- `/Users/admin/Mnemosyne/docs/EXECUTION-PLAN-A-Memory-System.md` S1.2 and S4.5
- requirement `CAP-011`
- source commit `373b765a9978cd5b64e46fc12e384d917a26e110`

The global deterministic retrieval path and its scored column remain unchanged. A future compact reader/reranker is shadow-only, default-off, hosted behind the optional Rust/ONNX sidecar, and cannot enter the active candidate-v19 CLI, registry, bundles, or protected datasets before separate preregistration and promotion.

The physical floor is a measured product contract, not an estimate: native x86-64 AVX2 Windows and Linux systems with exactly 8 GiB physical memory must meet the fixed resource envelope while preserving CAP-003, byte-identical deterministic retrieval, all section 31 rails, and all section 33 test classes. Stronger runtime profiles may add capacity but never weaken quality, grounding, custody, or publication gates.

Hugging Face model and dataset revisions are discovery pins only. Runtime custody additionally binds every source file, tokenizer/config/license digest, ONNX export/quantization toolchain, platform artifact, sidecar digest, corpus provenance, overlap policy, and exact-scale receipt. Training and calibration exclude qa_hard_v2, every LongMemEval split, and all Hippo evaluation tracks.

As of 2026-07-12 no model weights were downloaded, no training or inference job was started, no protected attempt was consumed, and no public performance or 8 GiB compatibility claim was made. Candidate v19 remains unchanged.

## Related

- memory-system-architecture-contract
- Mnemosyne Phase 8 Retrieval Release Gate 2026-07-03
