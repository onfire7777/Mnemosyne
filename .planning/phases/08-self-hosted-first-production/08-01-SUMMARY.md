---
phase: 08-self-hosted-first-production
plan: 01
status: passed-retrospective
completed: 2026-07-07
reconstructed: true
reconstructed-on: 2026-07-10
requirements-completed:
  - REQ-003
  - REQ-004
  - REQ-006
  - REQ-010
  - REQ-011
  - NFR-002
  - NFR-004
---

# Phase 08 / Plan 01 Summary: Self-Hosted-First Production

This summary was reconstructed on 2026-07-10 from the retained Phase 8 plan,
handoff/security records, repository history, current source checks, and the
external `capture-bc10` custody packet. It was not authored during the original
execution and does not claim that every historical checklist item was completed
at the time it was first written.

## Delivered

- The preferred no-GPU self-hosted production profile, values-only cloud
  extension, hardened production compose topology, and `forbid_local:true`
  provider posture were implemented.
- Production evidence gates were hardened for identity, TLS, retrieval,
  privacy/KMS, hosted MCP, roles/RLS, signed evidence, supply chain, audit
  integrity, parametric training, and release custody.
- The target-class stack was brought up end to end and deployment defects were
  repaired without weakening the strict production gates.
- Phase 8.6 completed the B1-B10 capture/sign-off path. The retained
  `capture-bc10` packet records 74 artifacts, 10/10 complete rows, a matching
  out-of-band fingerprint, zero release findings, production/operator
  attestation, redaction, soak, and offline custody verification.
- B9 closed through ADR-002's accepted CPU-parametric path and the same unchanged
  release/offline custody gates.

## Evidence Boundaries

The later aggregate attestation supersedes old “Partial/open” capture language;
it does not prove that every unchecked task-group checkbox was performed at its
original timestamp. Tier-C SLO reproving, LongMemEval R@5, and an official-profile
badge remain outside this plan's strict B1-B10 closure evidence unless separately
captured. External operator artifacts remain outside git.

## Sources

- `08-01-PLAN.md`, `08-HANDOFF-INDEX.md`, `08-SECURITY-FINDINGS.md`
- `.planning/runbooks/LIVE-DEPLOYMENT-VALIDATION-2026-07-04.md`
- `/Users/admin/mnemosyne-evidence-out/verify-bc10.json`
- `/Users/admin/mnemosyne-evidence-out/capture-bc10/release-audit.json`
- `/Users/admin/mnemosyne-evidence-out/capture-bc10/summary.json`

