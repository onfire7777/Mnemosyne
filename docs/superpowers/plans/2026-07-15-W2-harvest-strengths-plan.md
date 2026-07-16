# W2 Implementation Plan — Harvest Unmeasured Strengths

**Date:** 2026-07-15
**Parent spec:** `docs/superpowers/specs/2026-07-15-world-best-memory-platform-design.md` (§2.4, §8.2/§8.3, Workstream W2)
**Requirements:** BENCH (new adapter families), CAP-002 (provenance/abstention), the forgetting/supersession rails already built.
**Depends on:** W1 substrate fix landing (retrieval must work before these adapters produce headline-eligible numbers). Adapters may be *built* in parallel with W1; *measured for record* after W1.

## Goal

Measure three capabilities Mnemosyne already implements but does not yet
benchmark, each architecturally aligned with a benchmark where Mnemosyne can
plausibly lead: **bitemporal supersession → Memora/FAMA**, **crypto-shred
forgetting → deletion-residue/leakage suite**, **procedural memory →
AFTER/STATE-Bench**. Wire them as neutral-harness adapters under PBPP with
per-category reporting. This is the fastest path to demonstrated leadership
because the capability already exists — only the measurement is missing.

## Acceptance criteria (goal-backward)

1. **Memora/FAMA adapter:** runs Mnemosyne's supersession path over
   weeks/months/quarters of updated/deleted facts; reports FAMA (penalizing
   stale-memory use) at all three horizons; beats released baselines; the
   stale-memory-usage rate is reported separately with target < 5% (spec §8.3).
2. **Deletion-residue/leakage suite:** a deterministic adversarial suite proves
   cascade deletion removes information across raw + derived facts + entity
   summaries + graph edges + embeddings + lexical indexes + conversation
   summaries + cached context + learned procedures + retention-bound backups;
   emits a **signed deletion manifest** enumerating every affected object and
   verifying removal; **hard gate: 100% cascade deletion, 0% recoverable
   residue**. Includes a cross-user leakage test (no cross-tenant recall).
3. **Procedural adapter (AFTER / STATE-Bench):** measures procedural-skill
   transfer and experience-driven improvement; demonstrates positive transfer
   without over-specialization; procedures require repeated validation +
   regression + rollback (no single-trajectory promotion — spec §10.2).
4. **PBPP:** all three run under the pinned `eval/public/` harness on the full
   production stack, disclosure = execution byte-for-byte, per-category reporting,
   reproducible bundles.
5. **Rails intact:** §31/§33 green; no core dependency added.

## Context the executor needs

- Supersession is built: bitemporal beliefs with `valid_from`/`valid_until`,
  `supersedes`/`contradicts`, `as_of()` time-travel (~1,066 refs). The belief
  revision core resolves currently-valid state. FAMA measures exactly this.
- Forgetting is built: graduated tiers VERBATIM → EXTRACTIVE_SUMMARY →
  ABSTRACTIVE_GIST → STATISTICAL_TRACE, ACT-R demotion, crypto-shred erasure via
  Vault. The deletion suite must exercise the FULL pipeline purge, not raw-only
  (raw-only leaves ~20% derived residue per recent research).
- Procedural is built: `Procedure`/`ProcedureInducer` with utility/outcome
  stats; `Lesson`/`LessonDistiller`.
- Existing adapters live in `eval/public/adapters/` (LongMemEval, HippoRAG);
  follow their custody/bundle patterns. Deterministic where possible; disclose
  any LLM judge model+prompt and its acceptance rate on
  intentionally-wrong-but-topical answers.

## Phase 1 — Memora/FAMA supersession adapter (TDD)

- [ ] RED: `eval/public/adapters/memora_fama.py` skeleton + a focused test that a
  known update sequence (fact asserted → superseded → queried at three time
  points) yields the currently-valid answer at each `as_of`, and that a query
  after supersession does NOT surface the stale value.
- [ ] GREEN: implement the adapter — ingest the Memora conversation/update
  streams through the normal write+consolidation path; run queries; score FAMA at
  weekly/monthly/quarterly horizons; emit the stale-memory-usage rate separately.
- [ ] Pin the exact Memora dataset version; record the bundle + manifest.
- [ ] Verify: focused test green; §31/§33 unaffected.

## Phase 2 — Deletion-residue + cross-user leakage suite (TDD)

- [ ] RED: `tests/completion/security/test_deletion_residue.py` — after
  `forget_memory` on an episode, assert the value is unrecoverable from EVERY
  derived tier (facts, entity summaries, graph edges, embeddings, lexical index,
  conversation summaries, cached context, procedures), and that a signed deletion
  manifest lists each object with a verified-removed flag. Add a cross-tenant
  recall test asserting 0% leakage.
- [ ] GREEN: extend the forgetting/erasure path so a deletion traverses all
  derived tiers (crypto-shred where applicable) and produces the signed manifest;
  fix any tier that leaves residue.
- [ ] Verify: 100% cascade, 0% residue, 0% cross-tenant leakage under the focused
  suite; §31 rails green.

## Phase 3 — Procedural transfer adapter (AFTER / STATE-Bench)

- [ ] RED: `eval/public/adapters/procedural_transfer.py` skeleton + a test that a
  procedure induced from repeated successful trajectories transfers to a
  held-out but related task, and that a single successful trajectory does NOT
  promote to a trusted skill.
- [ ] GREEN: implement the adapter over AFTER (skill transfer) and STATE-Bench
  (experience improvement); measure positive transfer and over-specialization;
  enforce versioning + regression + rollback on procedures.
- [ ] Pin dataset versions; record bundle + manifest.
- [ ] Verify: focused test green.

## Phase 4 — Harness integration, PBPP, reporting

- [ ] Register all three adapters with the neutral `eval/public/` harness;
  produce reproducible bundles with separate retrieval/QA columns and judge
  diagnostics where an LLM judge is used.
- [ ] Ensure every run discloses executed engine/model/custody byte-for-byte
  (spec §8.4) and runs on the full production stack for any headline number.
- [ ] Add result notes under `eval/reports/`; report per-category (no averaging).
- [ ] Update `.planning/` requirement rows + traceability for the new families.

## Validation commands

```sh
set -e
cd "$(git rev-parse --show-toplevel)"
git diff --check
.venv/bin/ruff check --quiet .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
  eval/public/adapters/ tests/completion/security/test_deletion_residue.py \
  tests/test_planning_traceability.py
# Full suite + production-stack headline runs under the admitted preflight only.
```

## Rails (unchanged, enforced)

Never weaken §31/§33; no core dependency. All headline numbers on the full
production stack with byte-exact disclosure (spec §8.4). Deterministic grading
preferred; any LLM judge discloses model+prompt + acceptance rate on
wrong-but-topical answers. Never tune on held-out/test data; pin exact dataset
versions. Small conventional commits, exact-head CI, no red merges. Headline-
eligible measurement waits on W1's retrieval fix; building the adapters does not.
