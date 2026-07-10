# Phase 11 Patterns

- One allowlisted adapter per schema family; registry metadata selects it.
- External assets require exact source revision, file SHA-256, license,
  citation, split role, and contamination declaration.
- Normalize upstream rows into stable document IDs, question IDs, gold passage
  IDs, answers/aliases, and source annotations before any system call.
- Reject ambiguous title-only mappings and incomplete gold mappings.
- Capture corpus content and retrieve only through `MnemoCLI`; use public
  `explain` data for graph/PPR participation without inventing unavailable
  scores.
- Recompute every metric from benchmark-owned labels and canonical traces.
- Never use top-k equal to the candidate pool in smoke or publication evidence.
- Full datasets stay outside git; tiny fixtures are schema tests only.

