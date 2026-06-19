# Phase 4: Procedural and Corrective Learning - Context

**Gathered:** 2026-06-19
**Status:** Verified

<domain>
## Phase Boundary

Phase 4 captures trajectories, attributes failures, induces lessons and procedures, validates candidates through protected regression and counterfactual replay, and enforces capability-secured writes.

</domain>

<decisions>
## Implementation Decisions

### Learning
- **D-04-01:** Trajectories record task, steps, outcome, reward, memory version, and session.
- **D-04-02:** Failure attribution uses failed step evidence to create a stable signature.
- **D-04-03:** Lessons and procedures remain candidates until gate promotion.

### Safety
- **D-04-04:** Promotion uses the existing branch-based `PromotionGate`.
- **D-04-05:** MINJA and AgentPoison cases are permanent protected cases.

</decisions>

<canonical_refs>
## Canonical References

- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §23.3 — promotion gate.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §27 — security governance.
- `/Users/admin/Desktop/Mnemosyne/Mnemosyne-v2-Build-Blueprint.md` §34 Phase 4.

</canonical_refs>

