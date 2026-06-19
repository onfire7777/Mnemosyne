# Phase 5: Profile-Guided Self-Optimization - Context

**Gathered:** 2026-06-19
**Status:** Verified

<domain>
## Phase Boundary

Phase 5 implements shadow-first policy optimization within immutable rails: self-model outcome windows, policy variant proposal, canary gate evaluation, and diversity/proxy-divergence tripwires.

</domain>

<decisions>
## Implementation Decisions

### Self Model
- **D-05-01:** Store self-model records by tenant, metric, policy version, value, and time window.
- **D-05-02:** Use latest metric windows to propose safe policy variants.

### Safety
- **D-05-03:** Variants must satisfy immutable rails before evaluation.
- **D-05-04:** Diversity and proxy-vs-true divergence tripwires block bad variants.
- **D-05-05:** Policy variants promote through canary branch gate.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §23.4 and §23.5 — cold loop and immutable outer invariant.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §34 Phase 5.

</canonical_refs>

