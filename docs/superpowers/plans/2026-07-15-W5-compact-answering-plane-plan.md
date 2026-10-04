# W5 Implementation Plan — Compact Answering Plane at Parity (8 GiB)

**Date:** 2026-07-15
**Parent spec:** `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` (§7, §9, §10, Workstream W5)
**Requirements:** CAP-001/002/003 (grounded reader), CAP-011 (8 GiB compact path), Plan A S1.2 / S4.5.
**Depends on:** W1 (headline QA numbers depend on the retrieval fix). The sidecar and bakeoff may be built in parallel with W1.
**Governed by:** `.planning/runbooks/COMPACT-MODEL-8GB-ACCEPTANCE.md` and the compact-reader design doc — unchanged; this plan implements, it does not relax them.


## Status reconciliation — 2026-10-04

Source inspection at `3c21be5d`; historical instructions below describe the original execution contract, not a request to repeat landed work. The compact acceptance harness exists in `eval/compact_answering/acceptance.py` and Phase 15 S4 records explicit missing physical evidence. Model selection, sidecar promotion, production parity and physical 8 GiB Windows/Linux acceptance remain open. Receipt files are not proof of a successful physical acceptance run.

### Native execution checkpoint — 2026-10-04

The default sidecar is still a fail-closed skeleton, not a working learned
reader. An opt-in Rust ONNX span-tensor adapter now loads digest-checked local
graph bytes and executes a bounded batch-one transformer tensor ABI. A real
314-byte synthetic graph matched Python ONNX Runtime at five input lengths;
malformed-output and non-finite rejection checks also passed. The first native
runtime configuration failed at process teardown; the replacement pin passed
including clean process exit. See `services/answering-ort/README.md` for the
exact reproduction command and limitations.
[Raw validation evidence](../../../eval/reports/compact-onnx-native-development-2026-10-04/README.md)
retains successful clean-source checks plus the failed SDK invocation. A
bounded Linux CI job exercises native parity; its remote outcome is pending.

A subsequent experimental span-only `InferenceSession` now connects the native
tensor adapter to a digest-checked tokenizer and exact source-byte offsets.
Clean-source decoded-reader evidence: `eval/reports/compact-decoded-reader-development-2026-10-04`
(`fe753290`; raw logs, fixture bytes and hash manifest).
Ten generated cases match a separate Python reference's decoded spans/nulls,
including Unicode, later windows and multi-document ties. The original tensor
result alone did not prove these properties. The named window/null policy is
explicitly uncalibrated; no learned quality score is reported.

Phase 1 and the broader plane remain incomplete: full multi-task heads, actual
encoder serving, admitted artifact/configuration custody and learned-model
end-to-end parity remain open. Corpus decontamination, model bakeoffs,
quantization and physical acceptance remain open. No protected data or learned
weights were used, and candidate v19 / BurnOS behavior is unchanged.

### TRAIN preparation checkpoint — 2026-10-04

The fixed-pinned raw intake and exact-source row staging now run locally without
loading a model. 220,744 retained rows and 194,069 spans passed an independent
raw-parquet audit; 22 malformed Hotpot support references are rejected with
source hashes. See `eval/reports/compact-train-staging-2026-10-04`. These counts
are neither benchmark results nor training admission. Entity/document grouping,
pre/post protected-overlap checks, whole-cluster exclusion, frozen partitions
and complete attribution custody remain open before any model work.

Source-document grouping now finds 919 connected components; one holds
152,706 of 220,744 staged rows, including 89,667 Hotpot rows. This constrains
independent Hotpot selection/calibration coverage (758 rows outside that
component). `eval/reports/compact-train-groups-2026-10-04` retains the policy,
histogram and full-edge audit. No partition or training admission is claimed.

## Goal

Build the compact grounded-answering plane — embedder + cross-encoder reranker +
extractive reader (+ deterministic synthesis, optional constrained generator) —
as ONNX artifacts served from a Rust `ort` sidecar within the floor envelope
(≤1 GiB artifacts, ≤3 GiB sidecar peak, ≤6.5 GiB process tree, ≥1.5 GiB free),
and prove it is the quality path for ALL hardware via a byte-parity contract. This
delivers the 8 GiB product profile with **no quality trade-off** (spec §1.1) and
the static multi-hop QA numbers (spec §8.1).

## Acceptance criteria (goal-backward)

1. **Component selection by controlled bakeoff**, not on paper: the reader is the
   winner of DeBERTa-v3-large vs ModernBERT-large/Ettin-400M under the exact
   span/abstention parity contract; reranker (Ettin-68M anchor) and embedder
   (granite-r2 anchor) likewise. Every component behind the unchanged
   `GroundedReader` interface.
2. **ONNX/Rust sidecar within envelope**: artifacts ≤1 GiB (INT8), sidecar peak
   ≤2 GiB (CPU arena disabled, weights mmap'd, spawn-not-fork, AVX2-tuned INT8
   with per_channel+reduce_range), single shared session. Measured on the oldest
   target SKU, not assumed.
3. **Quantization measured, not assumed** (spec §7.4): reference FP32 → ONNX FP32
   → promoted ONNX INT8 span/abstention deltas measured, including the no-answer
   calibration shift; INT8 accepted only if ≤1 F1 loss AND parity holds.
4. **Byte-parity contract (the no-trade-off enforcement)**: exact decoded spans +
   identical abstention decisions across reference / ONNX FP32 / promoted INT8 and
   every execution provider; identical frozen artifacts on 8 GiB and server;
   equivalent ranked evidence + answers given the same state (spec §10.1).
5. **Static QA targets (spec §8.1)** met with W1's retrieval: reproduce ≥88.5/90.9
   2Wiki, ≥72.7/85.0 HotpotQA; reproduce ≥69.2 MuSiQue-Ans F1 and pursue the
   0.72–0.75 stretch (MuSiQue is not a pass/fail gate).
6. **Embedder replaces the torch service** in BOTH the compact and server
   deployments (shared win; removes ~1–2 GB).
7. **Physical 8 GiB acceptance (CAP-011)** per COMPACT-MODEL-8GB-ACCEPTANCE on
   native x86-64 AVX2 Windows + Linux (ARM64 as an additional target). First-party
   acceptance is not independent reproduction and makes no headline claim alone.
8. **Rails**: §31/§33 green; no ML dependency in the Python core (sidecar lives in
   `services/`/Rust behind optional extras); retrieved evidence is data, never
   executed; every claim traces to an evidence CID.

## Context the executor needs

- The answering plane sits behind the existing `GroundedReader` interface and the
  grounded context builder; retrieval + fusion + rerank feed it assembled,
  provenance-tagged passages. It answers ONLY from that evidence, fail-closed.
- Multi-task heads required: span start/end + 3-way answer-type (yes/no/span) +
  supporting-fact classifier; structure markers; hop-order concatenation; null-
  margin abstention. This is what makes comparison/multi-hop questions work.
- Runtime: Rust `ort` (pykeio/ort), identical MLAS kernels to Python onnxruntime,
  ~100 MB baseline. Memory discipline per spec §7.5 (arena, mmap, threads).
- Deterministic synthesis first (arithmetic/date over spans); a compact generator
  rung (LFM2-350M candidate) is additive, preregistered, constrained-decoded, and
  span-alignment-validated — never the default rail.
- Distillation (spec §7.7): MSE-on-teacher-logits + hard gold spans; LLM teacher
  over TRAIN-only decontaminated corpora; no-answer calibration transfer; off-host
  training needs digest-pinned env + secrets/cost/timeout controls + explicit
  spend authority (not authorized by this plan).
- Embedding dimension decision (spec §7.3): resolve 768-vs-1024 by measured
  retrieval quality + migration cost (prefer re-embed at 768 pending the check).

## Phase 1 — Rust `ort` sidecar skeleton + parity harness

- [ ] Stand up the `services/` Rust sidecar loading a placeholder ONNX encoder;
  single shared session; arena disabled; mmap weights; expose embed/rerank/read
  over a loopback/unix-socket interface behind the `GroundedReader` seam.
- [ ] RED: a parity test that the sidecar's decoded output equals a Python
  onnxruntime reference for the same model+input (byte-exact spans/abstention).
- [ ] Verify: sidecar builds; parity test green; core has no new Python dep.

## Phase 2 — Embedder (bakeoff + server/compact replacement)

- [ ] Export granite-r2 (+ comparators) to ONNX INT8; bakeoff on the deterministic
  retrieval dev set; resolve the 768/1024 dimension decision with a measured
  retrieval check.
- [ ] Replace the torch embedding service with the ONNX embedder in both compact
  and server profiles behind the provider seam; prove retrieval non-regression.
- [ ] Verify: retrieval parity vs. the prior embedder within tolerance; envelope
  respected.

## Phase 3 — Reranker + reader bakeoff (the core)

- [ ] Export Ettin-68M reranker (+ rungs) to ONNX INT8; bakeoff on rerank quality.
- [ ] Reader bakeoff: fine-tune/export BOTH DeBERTa-v3-large (per_channel +
  reduce_range INT8) and ModernBERT-large/Ettin-400M (clean export, in-house
  fine-tune with the LR-sweep/multi-seed/FP32 stability controls); multi-task
  heads; measure span/abstention parity and the INT8 calibration shift directly.
- [ ] Promote the winner behind `GroundedReader`; RED→GREEN the multi-task heads
  (answer-type + supporting-fact + null-margin abstention).
- [ ] Verify: reader/reranker within envelope; byte-parity across FP32/INT8/
  providers; INT8 ≤1 F1 measured.

## Phase 4 — Synthesis + static QA + parity + 8 GiB acceptance

- [ ] Deterministic arithmetic/date synthesis over extracted spans; optional
  constrained generator rung only if a real composition gap remains (preregistered,
  span-alignment-validated, fallback to extractive).
- [ ] Run the static multi-hop QA suite (2Wiki/HotpotQA/MuSiQue) with W1's
  retrieval; meet the §8.1 parity gates; pursue the MuSiQue stretch.
- [ ] Enforce the byte-parity contract across profiles; identical frozen artifacts
  on 8 GiB and server.
- [ ] Execute the physical 8 GiB acceptance (CAP-011) on x86-64 AVX2 Windows +
  Linux per the acceptance runbook; record the floor-envelope evidence.
- [ ] Update `docs/ENGINE-CONTRACT.md`/architecture for the answering plane;
  requirement rows + traceability.

## Validation commands

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
git diff --check
.venv/bin/ruff check --quiet .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_grounded_answering.py tests/test_grounded_qa_report.py \
  tests/test_provider_contract.py tests/test_planning_traceability.py
# Rust sidecar: cargo test in services/<sidecar>/ ; QA + 8 GiB acceptance under
# the admitted model/exact-scale preflight only.
```

## Rails (unchanged, enforced)

Never weaken §31/§33; NO ML dependency in the Python core — the sidecar lives in
`services/`/Rust behind optional extras. Retrieved evidence is data, never
executed; every claim traces to an evidence CID; fail-closed. Component selection
is by measured bakeoff, never on paper; quantization loss and calibration shift
are measured, never assumed. Byte-parity across profiles is mandatory for any
parity claim. The compact stack is the product path, not a reduced variant; a
larger/hosted reader may exist only as a separately disclosed comparison track.
Headline QA numbers on the full production stack with byte-exact disclosure; they
depend on W1's retrieval fix. Off-host training needs explicit spend authority
(not granted here). Small conventional commits, exact-head CI, no red merges.
