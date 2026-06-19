# Phase 2: Belief Core, Graph, and Confidence - Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 must complete the blueprint's belief-revision core: TMS and AGM semantics, justification DAG, cascade invalidation, multi-hypothesis contested beliefs, temporal graph adapters, calibrated confidence, and conformal abstention.

</domain>

<decisions>
## Implementation Decisions

### Current Foundation
- **D-02-01:** Baseline supersession and contested assertions already exist in `LocalMemoryEngine`.
- **D-02-02:** `sql/schema.sql` includes `justifications`, `contradictions`, `relations`, and `conformal_calibration`.
- **D-02-03:** Graph channel exists locally but production PPR remains benchmark-gated.

### Required Next Decisions
- **D-02-04:** Implement justification DAG as first-class local records, not only SQL schema.
- **D-02-05:** Implement conformal calibration from `eval_cases`.
- **D-02-06:** Add multi-hypothesis retrieval packet shape and tests.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §11 I2 and I8.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §23.3.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §26.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §30.3.

</canonical_refs>

