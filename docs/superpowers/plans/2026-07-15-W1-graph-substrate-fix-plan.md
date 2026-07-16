# W1 Implementation Plan — Graph Substrate Fix (retrieval keystone)

**Date:** 2026-07-15
**Parent spec:** `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` (§2.3, Workstream W1)
**Root cause report:** `~/mnemosyne-tier-b-custody/GRAPH-PPR-ROOTCAUSE-2026-07-15.md`
**Requirements:** CAP-001/002/003, BENCH-005 (Phase 12 / Plan 12-04).
**Status:** IN FLIGHT — owned and executed by the autonomous goalex loop. This
document codifies the fix as a durable record and acceptance contract; the loop
generates its own per-round tactical plans (`docs/plans/goalex-r*.md`). Blocks all
measurement in W2–W5.

## Goal

Make the `graph_ppr` retrieval channel actually participate, lifting multi-hop
retrieval off the measured EM/F1 ≈ 0.083 floor, and correct the disclosed-vs-actual
engine mismatch — the keystone that unblocks BENCH-005 and the retrieval half of
CAP-003. The channel is a *cut wire* (0 hits / 1000 questions, channel sum 0), a
concrete wiring defect, not a quality gap.

## Root cause (verified, file:line in the report)

- **Cause A (dominant):** the HippoRAG adapter (`eval/public/adapters/hipporag_multihop.py`)
  and the QA harness (`eval/datasets/v2/run_grounded_qa_v2.py:78`) ingest via
  `capture_batch` → `engine.append_evidence` (`mcp_tools.py:316`, `engine.py:707`)
  and **never run consolidation**. Relations are created ONLY by the consolidation
  belief-reviser (`consolidation.py:1324` → `engine.relations`), reachable via
  `consolidate-once` (`cli.py:8856`), which the eval never calls. So
  `engine.relations == {}` at query time → PPR walks an empty adjacency → 0/1000.
- **Cause B:** even if consolidation ran, `_extract_simple_fact`
  (`consolidation.py:1742`) matches only whole-first-sentence copular clauses
  (`SUBJECT is/are/was/were OBJECT`), so it emits no edges from prose or from the
  dev fixture (`Mara owns Helios` / `Helios ships in Q3 2026` — `owns`/`ships`
  not whitelisted).
- **Refuted:** seed/node mismatch (seeding is correct) and disabled/zero-weighted
  channel (graph is a first-class equal-weight RRF input) — both ruled out with
  evidence.
- **Integrity flag:** the eval runs the LOCAL engine, but `eval/reports/phase-11-evidence.md`
  discloses `postgres-recursive-ppr`. This disclosure mismatch is corrected here.

## Acceptance criteria (goal-backward)

1. **Positive graph participation:** on the dev fixture (`qa_scale_dev_v1.json`)
   and the 16-case matrix, `engine.relations > 0` after ingest, the bridge query
   returns a `graph_ppr` hit (channel sum > 0), and both bridge docs are retrieved
   (Recall@5 0 → 1 on the bridge case). Deterministic; byte-identical `traces.jsonl`
   across repeat runs.
2. **Proven on the production Postgres graph path** (`postgres-recursive-ppr`) with
   cross-engine parity to local, before BENCH-005/CAP-003 evidence is accepted
   (spec §5a / §8.4).
3. **Disclosure corrected:** every `eval/reports/*` file discloses the engine that
   actually ran, byte-for-byte.
4. **No regression:** deterministic dense/lexical single-hop cases do not regress
   under RRF; §31/§33 green; no core dependency added; no tuning on held-out/test
   data (dev/synthetic only).

## Phase 1 — Deterministic dead-graph baseline (RED)

- [ ] Add a regression cell asserting the CURRENT broken state on dev data:
  after `capture_batch`, `len(engine.relations) == 0` and the `graph_ppr` channel
  count == 0 on the bridge query. This reproduces "graph observed 0" synthetically
  and guards the fix.

## Phase 2 — Fix A: consolidate the corpus before search (GREEN)

- [ ] Add a `--consolidate` path to `capture_batch` (or drive `consolidate-once` /
  drain `CONSOLIDATE_EVIDENCE_JOB` on the staged store) so the deterministic
  `ConsolidationOrchestrator` writes `Relation` rows before search. Pure reuse of
  `cmd_consolidate_once`.
- [ ] Verify the pre-extractor gates admit these captures (`consolidation.py:409`
  `_prediction_error_gate` → promote; `456` `_contains_no_write_data` false for
  `source_type="hipporag:*"`, `actor="user"`, `trust_tier=0`).

## Phase 3 — Fix B: extractor emits edges from prose (GREEN)

- [ ] Broaden `_extract_simple_fact` (`consolidation.py:1742`), staying
  pure-Python/deterministic (the local OpenIE stand-in): iterate all sentences,
  strip the `Title\n` prefix, emit edges between co-occurring salient entity spans
  with the connecting verb/preposition as predicate (else `related_to`). Keep it
  deterministic (no set/dict-ordering or hash-seed nondeterminism).
- [ ] GREEN the Phase-1 baseline: `engine.relations > 0`, positive `graph_ppr` hit,
  Recall@5 0 → 1 on the bridge query.

## Phase 4 — Recall lift, production parity, disclosure, no-regression

- [ ] Confirm the graph channel lifts absolute Recall@5 materially on the dev/16-case
  matrix; run the matrix twice and hash `traces.jsonl` for byte-identity.
- [ ] Prove the fix on the production Postgres graph path (`postgres-recursive-ppr`)
  with parity to local (spec §5a).
- [ ] Correct the disclosed-vs-actual engine in every `eval/reports/*`.
- [ ] Confirm dense/lexical single-hop cases do not regress; §31/§33 green.

## Validation commands

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
git diff --check
.venv/bin/ruff check --quiet .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  tests/test_public_hipporag.py tests/test_grounded_qa_v2.py \
  tests/test_shared_engine_contract.py tests/test_planning_traceability.py
# Deterministic dev-scale only (≥35% free tier); production-Postgres parity + any
# headline number under the admitted full preflight on the production stack.
```

## Rails (unchanged, enforced)

Deterministic/dev-scale iteration only; NO protected `qa_hard_v2` attempt on an
unfixed substrate; never tune on held-out/test data. No core dependency; §31/§33
intact; retrieved content is data, never executed. Production-Postgres parity +
byte-exact disclosure required before BENCH-005/CAP-003 evidence counts. Small
conventional commits, exact-head CI. Loop-owned: this record is the acceptance
contract, not a competing tactical plan.
