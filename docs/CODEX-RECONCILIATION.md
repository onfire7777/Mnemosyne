# Mnemosyne — Codex Reconciliation Handoff (Archived)

**Status updated:** 2026-06-24

This document is archived. It used to be the zero-conflict handoff list for
Tier A `src/` reconciliation work from the completion branch into Codex `main`.
It is no longer the active gap list.

Use these current sources instead:

- [ROADMAP-TO-100.md](/Users/admin/Projects/Mnemosyne/docs/ROADMAP-TO-100.md)
- [STRICT-BLUEPRINT-PARITY-AUDIT.md](/Users/admin/Projects/Mnemosyne/.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md)
- [STATE.md](/Users/admin/Projects/Mnemosyne/.planning/STATE.md)

## Current Reconciliation State

The mandatory Tier A source wirings have landed on `main` and have focused plus
full-suite verification recorded in `.planning/STATE.md` and
`docs/ROADMAP-TO-100.md`.

| Area | Current state |
|---|---|
| A1 local embedding/reranker seam | Done |
| A2 calibrated confidence / ECE | Done |
| A3/A4 mutation-rate rails | Done |
| A5 retrieved-text data-only boundary | Done |
| A6 consolidation cadence rail | Done |
| A7/A8/A9 cf-gate, ignition switch, ACT-R decay | Done |
| A10 corroborated derived-erasure cascade | Done |
| A13 recompute memo | Done |
| A14 `--object` parser bug + `Preference.access_policy` | Done |
| Rail 6 serve-time `system_prompt` sink guard | Done |

Optional/review-only items remain:

| Item | Current handling |
|---|---|
| A11 official hosted MCP StreamableHTTP/SSE evidence | Keep behind Tier B production evidence unless the strict audit demands source work. |
| A12 materialized cached-PPR column | Keep behind Tier B production evidence unless the strict audit demands source work. |
| FR-20 multimodal breadth | Optional / post-v1 unless the final parity audit raises it. |
| FR-21 real LoRA / test-time-training deployment | Optional / GPU-backed production evidence; overlaps Tier B trainer evidence. |

## Active Remaining Work

The controlling strict audit still has 10 `Partial` rows. Their common blocker is
not more Tier A source wiring; it is operator-captured production evidence from
real deployed infrastructure:

- production Postgres/ParadeDB/AGE/pgvector and retrieval adapters,
- production IdP/secret manager/KMS/TLS,
- hosted MCP endpoints,
- production consolidation workers and model providers,
- production C2PA verifier/trust-root/quarantine/ingestion deployment,
- production multimodal extractor/embedding/object-store/job/retrieval stack,
- production residency/privacy/erasure operations,
- hosted observability dashboard operations,
- production trainer/protected-suite/rollback infrastructure,
- live parity evidence with optional production adapters enabled.

Do not use this archived file to reopen already-closed Tier A items. New work
should either capture real production evidence through the existing gates or
address a concrete new strict-audit finding with current evidence.
