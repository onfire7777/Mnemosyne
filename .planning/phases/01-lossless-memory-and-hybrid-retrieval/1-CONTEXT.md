# Phase 1: Lossless Memory and Hybrid Retrieval - Context

**Gathered:** 2026-06-19
**Status:** Verified

<domain>
## Phase Boundary

Phase 1 delivers bitemporal assertions, supersession, provenance, hybrid retrieval, explainability, correction, export, forget, confidence, and abstention.

</domain>

<decisions>
## Implementation Decisions

### Belief Updates
- **D-01-01:** Implement baseline supersession by subject, predicate, scope, and valid time.
- **D-01-02:** Preserve older assertions as superseded instead of destructively overwriting them.

### Retrieval
- **D-01-03:** Use lexical scoring plus deterministic hashing vectors for local dense retrieval.
- **D-01-04:** Include graph PPR in deep mode when relation data exists.
- **D-01-05:** Return provenance and channel counts for explainability.

### User Controls
- **D-01-06:** Implement forget as tombstone plus provenance propagation.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §14 — FR-2 through FR-8.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §22 and §30.4 — retrieval design.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §25 — erasure propagation.

</canonical_refs>

