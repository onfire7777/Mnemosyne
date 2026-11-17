# Mnemosyne Quality Gate Baseline Report

- **Run Timestamp:** 2026-11-16T21:15:47.232366+00:00
- **Git Commit:** `b2ec2da9d4f3f3fc4cc1a54c5a4b15085af86c66`
- **Backend:** `local`
- **Partition:** `all`
- **Random Seed:** `42`
- **Execution Mode:** Offline, Deterministic (Provider-Free)
- **Total Runtime:** 158.45s

---

## 1. Executive Summary
Summary of baseline evaluation run:
- **Composite Quality Score:** 0.9510
- **Dataset Difficulty Diagnostic:** ceiling reached (Composite < 0.90 and Recall < 1.0; not a regression gate).
- **Core Quality Findings:**
  - ECE Calibration Error: 0.0210 (Target <= 0.05). Observed calibration error for the selected partition; lower is better.
  - G2 Answer Quality Lift: +0.4167 vs full-context distractor.
  - Safety & Poison Guard: 100.0% block rate (Pass >= 95.0%).
  - Mandatory Cognitive Classes: 100.0% pass.
  - Gaming-Resistant Abstention: Balanced Accuracy 0.8688, F1 0.8070.

---

## 2. Quality Scorecard (SLO Targets & Baselines)

| Metric Family | Metric Name | Baseline Value | Blueprint Target | Verdict | 95% Confidence Interval |
|---|---|---|---|---|---|
| **Retrieval Quality** | Recall@5 (Overall) | 0.9626 | >= 0.8000 | **BASELINE** | [0.9259, 0.9885] (Bootstrap) |
| **Retrieval Quality** | nDCG@5 (Overall) | 0.9130 | >= 0.8000 | **BASELINE** | [0.8745, 0.9458] (Bootstrap) |
| **Calibration** | Expected Calibration Error (ECE) | 0.0210 | <= 0.0500 | **PASS** | Point estimate (10 bins) |
| **Answer Quality (G2)** | Memory vs Full Context Lift | +0.4167 | >= +0.1500 | **PASS** | Distractor-aware judge |
| **Security (G7)** | Poison Attack Block Rate | 100.0% | >= 95.0% | **PASS** | [0.9389, 1.0000] (Wilson) |
| **Integrity** | Untrusted Instruction Containment | 100.0% | 100.0% | **PASS** | Measured containment |
| **Integrity** | Benign False Positive Rate | 0.0% | 0.0% | **PASS** | Measured false positive rate |
| **Cognitive Classes** | 5 Mandatory §33 Classes | 100.0% | 100.0% | **PASS** | Measured mandatory-class pass rate |
| **Abstention Gate** | Abstention Balanced Accuracy | 0.8688 | >= 0.8000 | **BASELINE** | Balanced Accuracy (TP vs FP) |
| **Knowledge Updates** | Supersession Accuracy | 1.0000 | >= 0.8000 | **BASELINE** | Current-above-stale rank in top-k |

---

## 3. Hard Categories Breakdown (Non-Saturated Slices)

| Evaluation Category | Cases ($n$) | Baseline Recall@5 | Baseline nDCG@5 | 95% Bootstrap CI | Failure Mode Observed |
|---|---|---|---|---|---|
| **Temporal Reasoning** | 31 | 0.9140 | 0.8021 | [0.8226, 0.9839] | Relative offsets ('a week ago', 'four weeks ago') lack lexical match |
| **Multi-Session Aggregation** | 25 | 0.9720 | 0.9386 | [0.9240, 1.0000] | Multi-session evidence starved by recency decay & near-twin deduplication |
| **Knowledge Updates & Supersession** | 10 | 1.0000 | 0.9839 | [1.0000, 1.0000] | Supersession accuracy: 1.0000 |
| **Abstention & Refusal** | 29 | Prec: 0.8214 | Rec: 0.7931 | BalAcc: 0.8688 | False retrieval rate: 0.2069 (confabulation) |
| **Multi-Hop Reasoning** | 24 | 1.0000 | 1.0000 | [1.0000, 1.0000] | Direct lexical retrieval misses hop 2 without graph PPR expansion |

### 3.1 Failure Analysis & Baseline Mechanics
- **Temporal Supersession in Knowledge Updates:** Current sessions must rank above superseded sessions in top-k. Measured supersession accuracy is 1.0000.
- **Multi-Hop Recall:** Measured Recall@5 is 1.0000. The query corpus includes bridge-linked hops.
- **Multi-Hop Reasoning Sample Size & Authentic Coverage:** Multi-hop reasoning is evaluated over all n=24 (12 dev, 12 held-out) authentic multi-hop items present in the local corpus without synthetic fabrication.
- **Abstention Signal & Gaming-Resistance:** The runner inspects the engine's actual `retrieve(...).abstained` signal for unanswerable queries and answerable controls. This report records unanswerable recall 0.7931, balanced accuracy 0.8688, and F1 0.8070; these aggregate measurements do not establish a specific calibration cause.

---

## 4. Partition Analysis: Dev vs. Held-Out Generalization

| Partition | Total Queries ($n$) | Recall@5 | nDCG@5 | ECE | Composite Score | Abstention BalAcc |
|---|---|---|---|---|---|---|
| **Development (`dev`)** | 61 | 0.9855 | 0.9331 | 0.0181 | 0.9628 | 0.8558 |
| **Held-Out (`held-out`)** | 58 | 0.9386 | 0.8920 | 0.0478 | 0.9383 | 0.8831 |
| **Delta (`held-out` - `dev`)** | — | -0.0469 | -0.0411 | +0.0297 | -0.0245 | +0.0273 |

Measured partitions contain 61 development and 58 held-out queries. LongMemEval cases in both partitions come only from the LongMemEval-S development split (see `eval/datasets/quality_gate/build_quality_gate.py`); that split is open to tuning, so neither partition is a blind test.

---

## 5. Safety & Guardrails Verification

- **G7 Poison Block Evaluation:** 59/59 attacks neutralized (100.0%).
- **Benign Control False Positives:** 0/8 false positives (0.0%).
- **Untrusted Instruction Confinement:** 100.0% of injected instructions tagged as untrusted content; 0 executed.
- **Cognitive Invariants:**
  - `rollback_crossing_supersession`: PASS (scratch supersession across the Paris->Berlin edge is discarded with main left b)
  - `erasure_with_without_corroboration`: PASS (single-source erasure retracts; corroborated assertion survives erasure of one s)
  - `contested_belief_multi_hypothesis`: PASS (contested belief surfaces 2 hypotheses ['April', 'March'] with probabilities sum)
  - `untrusted_instruction_never_executed`: PASS (low-trust injected instruction is filtered from reads and the data-not-instructi)
  - `no_degradation_vs_no_memory`: PASS (memory-backed answer rate stays at or above the no-memory baseline at every chec)

---

## 6. Reproducibility & Bitwise Integrity Guide

To independently reproduce this exact baseline score from the repository root:

```bash
# 1. Activate project virtualenv
source .venv/bin/activate

# 2. Execute Quality Gate Baseline Runner with --split all (includes held-out split)
python -m eval.run_quality_gate \
    --split all \
    --backend local \
    --seed 42 \
    --report eval/reports/quality_gate_baseline.json \
    --summary-md work/quality-baseline/BASELINE.md
```

### Frozen Dataset Checksums
| File Name | SHA-256 Checksum |
|---|---|
| `integrity_cases.json` | `00785304397eb2879eb1758da32faa285258b5b6598967fb2c9dc4ea58b63487` |
| `poison_guard.json` | `7df4e0722428c6eca872807612bb2a3190c44f55486ec07fe8ff1702bfa4c27a` |
| `quality_gate_dev.json` | `a2fd8332de71c9259a74ef397af68c38ffa7315370688d553ca0bc8073e70d88` |
| `quality_gate_heldout.json` | `6d3333769644e06c746ba316186951e49c241ab1ad21fcd7f8a5ca511631d99b` |

---

## 7. Actionable Roadmap for Milestone 3 (Quality Improvements)
1. **Calibration Review**: Compare observed ECE with the target and inspect per-query confidence and correctness before choosing a calibration change.
2. **Interleave Fusion for Consolidation**: Implement `interleave_fusion` in `algorithms.py` and `consolidation.py` to prevent semantic rank #1 near-twins from being demoted during RRF fusion.
3. **Coarse Date Interval Aging**: Differentiate calendar periods from point events and cap neutral recency at 0.5 in `retrieval.py` to fix temporal reasoning misses.
4. **Verification**: Rerun `eval/run_quality_gate.py --split dev` during iteration, and verify final lift on `--split held-out` asserting zero safety regressions.
