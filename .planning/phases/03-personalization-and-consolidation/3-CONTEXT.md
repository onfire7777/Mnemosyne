# Phase 3: Personalization and Consolidation - Context

**Gathered:** 2026-06-19
**Status:** Verified

<domain>
## Phase Boundary

Phase 3 implements the dual user model, warm-loop consolidation, fidelity-tiered forgetting, spaced rehearsal, and long-horizon anti-degradation guard.

</domain>

<decisions>
## Implementation Decisions

### User Model
- **D-03-01:** Implement the six blueprint categories as `UserMemoryKind`.
- **D-03-02:** Hard instructions, identity, and explicit preferences outrank inferred preferences.
- **D-03-03:** Latent user profile is advisory and cannot override authoritative entries.

### Consolidation and Lifecycle
- **D-03-04:** Consolidation candidates promote only through `PromotionGate`.
- **D-03-05:** Fidelity demotion marks gist and trace tiers as confabulation-risk support.
- **D-03-06:** Anti-degradation guard blocks memory variants below no-memory baseline.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §24 — user model.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §25 — forgetting and lifecycle.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §30.5 — consolidation worker.

</canonical_refs>

