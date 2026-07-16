# W4 Implementation Plan — Full Neutral Benchmark Adapter Suite

**Date:** 2026-07-15
**Parent spec:** `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` (§8, Workstream W4)
**Requirements:** BENCH-006/007, REPRO-001/002, LEAD-001..003, GOV-001 (Phases 13/14/16).
**Depends on:** W1 (retrieval), and consumes adapters/capabilities from W2 (Memora/deletion/procedural) and W3 (PM-Bench/action). W4 is the measurement backbone for per-category world-best.

## Goal

Wire every remaining memory-benchmark family as a neutral-harness adapter under
PBPP, with per-competency reporting and reproducible bundles, so Mnemosyne can be
measured against the field on one identical harness. This is the backbone of the
"best per category, reproducible" claim (spec §1, §8). No averaged score may hide
a weak category.

## Acceptance criteria (goal-backward)

1. **Adapters exist and run under one harness** for: LongMemEval-V2,
   MemoryAgentBench (4 competencies reported separately), BEAM-1M/10M, LoCoMo,
   PM-Bench/TriggerBench (from W3), MemoryArena, STATE-Bench, GroupMemBench/GateMem,
   plus the W2 families (Memora/FAMA, deletion, AFTER). Each pins an exact dataset
   version and a frozen evaluation protocol.
2. **Per-benchmark protocol-frozen targets met or exceeded** per spec §8.1/§8.2:
   ≥86% LongMemEval-S, ≥72.5% LongMemEval-V2, every MemoryAgentBench competency
   beats its reproduced baseline, ~≥75%/≥65% BEAM-1M/10M, ≥65.1 PM-Bench, etc.
   Reported per category; the static QA gates (2Wiki/HotpotQA/MuSiQue) come from
   W5's answering plane.
3. **Extreme scale on 8 GiB proven** — BEAM-10M runs on the compact profile with
   the corpus disk-backed (SqliteEngine), demonstrating no quality collapse as
   history grows (latency-bound, not quality-bound — spec §1.3).
4. **Reproducibility standard (REPRO-001):** a neutral bundle standard covers
   manifests, raw traces, configs, environment/build fingerprints, metrics,
   intervals, integrity hashes; an agent can reproduce a result from the bundle
   (M2). Independent third-party reproduction (M3/REPRO-002) is human-owned.
5. **Scheduled regression-only CI (BENCH-007)** runs the deterministic suites on
   cadence without tuning on held-out/test data.
6. **PBPP + integrity:** every headline number on the full production stack;
   disclosure = execution byte-for-byte; separate retrieval/QA columns with judge
   diagnostics; no private-suite conflation.

## Context the executor needs

- Existing harness: `eval/public/` with the pinned-asset/bundle custody model
  (Phase 10/11). Follow it exactly; each adapter is additive.
- Phase 13 already scopes MemoryAgentBench + BEAM; this plan completes the rest.
- MemoryAgentBench measures four separate abilities (retrieval, test-time
  learning, long-range understanding, conflict resolution); conflict resolution
  is ~6–14% field-wide — a target to lead. Report the four separately.
- LongMemEval-V2: static state, changing state, workflow knowledge,
  environment-specific problems, premise awareness; strongest baseline ~72.5%.
  Uses the W3 working/prospective planes.
- Dataset versions vary (LongMemEval re-cleaned; MuSiQue-Ans vs -Full). Pin the
  exact version per adapter and record it in the bundle.
- Competitor self-reported numbers (e.g. 92–96%) are treated as unreproduced
  until run under this harness; do not cite them as targets.

## Phase 1 — Conversational + agent-experience adapters

- [ ] LoCoMo adapter (deterministic where possible; disclose judge).
- [ ] LongMemEval-V2 adapter over the W3 working/prospective planes; report the
  five categories separately; target ≥72.5% at lower latency than the baseline.
- [ ] Verify: focused adapter tests green; bundles produced.

## Phase 2 — MemoryAgentBench (4 competencies, reported separately)

- [ ] Build the adapter with four independent scorers (retrieval, test-time
  learning, long-range understanding, conflict resolution).
- [ ] Beat the best reproduced baseline in EACH competency; surface conflict
  resolution explicitly (the field's weak spot and a leadership target).
- [ ] Verify: per-competency results emitted; no averaged headline.

## Phase 3 — Extreme scale (BEAM-1M / 10M) on the compact profile

- [ ] BEAM adapter with a fixed answerer + judge; run 1M then 10M.
- [ ] Prove BEAM-10M runs on the 8 GiB profile with a disk-backed corpus; measure
  quality vs. scale to show no collapse; record latency separately (spec §1.3).
- [ ] Verify: 1M/10M results with the fixed protocol; bundles + fingerprints.

## Phase 4 — Action-oriented + multi-user

- [ ] MemoryArena + STATE-Bench adapters (experience-driven improvement; consume
  W2 procedural + W3 working memory).
- [ ] GroupMemBench + GateMem adapters — preserve utility + access control +
  deletion simultaneously; wire to the tenancy/ACL rails.
- [ ] Verify: focused tests green.

## Phase 5 — Reproducibility standard + scheduled CI + decision packets

- [ ] REPRO-001: freeze the neutral bundle standard (manifests, raw traces,
  configs, env/build fingerprints, metrics, Wilson/bootstrap intervals, integrity
  hashes); prove agent-reproduces-from-bundle (M2).
- [ ] BENCH-007: add a scheduled regression-only CI cadence for the deterministic
  suites; guard against any tuning on held-out/test data.
- [ ] Prepare (human-owned, do not perform): the M3 independent-reproduction
  packet + rubric, the L0/GOV-001 governance charter + COI/outreach packet, and
  the publication decision packet. Agents prepare; only the operator seats the
  board, commissions reproduction, ratifies policy, approves wording, or
  publishes a number.
- [ ] Verify: full deterministic suite green under the admitted preflight;
  per-category report assembled with no hidden average.

## Validation commands

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
git diff --check
.venv/bin/ruff check --quiet .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  eval/public/ tests/test_public_eval.py tests/test_benchmark_publication_policy.py \
  tests/test_planning_traceability.py
# Extreme-scale + production-stack headline runs under the admitted preflight only.
```

## Rails (unchanged, enforced)

Never weaken §31/§33; no core dependency. Every headline number on the full
production stack, disclosure = execution byte-for-byte, separate retrieval/QA
columns, judge model+prompt + wrong-but-topical acceptance rate disclosed, per
category with no hidden average, never conflated with the private suite. Never
headline LoCoMo/DMR/MSC or a self-defined benchmark; never tune on held-out/test
data; pin exact dataset versions. Independent reproduction, board seating, public
wording, and publication are human-owned — prepare packets, never perform. Small
conventional commits, exact-head CI, no red merges.
