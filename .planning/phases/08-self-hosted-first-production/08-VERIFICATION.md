---
phase: 08-self-hosted-first-production
verified: 2026-07-10
status: passed
score: 7/7 truths verified
reconstructed: true
evidence_classes: current-and-retained
---

# Phase 08 Verification: Self-Hosted-First Production

This aggregate verification was reconstructed on 2026-07-10. Current source
checks are distinguished from retained repository and external operator
evidence; no historical checklist action is inferred from file existence.

## Goal Achievement

| # | Observable truth | Status | Evidence |
|---|---|---|---|
| 1 | A preferred hardened self-hosted profile exists without weakening provider or release gates. | VERIFIED | Production profile/compose files and policy/manifest tests. |
| 2 | Identity, TLS, secrets, RLS, network, audit, privacy, supply-chain, and evidence-custody boundaries fail closed. | VERIFIED | Focused security/runtime tests and release-audit validators. |
| 3 | Real target-class bring-up exercised the production topology. | VERIFIED (retained) | `LIVE-DEPLOYMENT-VALIDATION-2026-07-04.md`. |
| 4 | B1-B10 are complete under the unchanged Tier-B contract. | VERIFIED (external) | `verify-bc10.json`: 74 artifacts, 10/10 complete, matching fingerprint, zero findings. |
| 5 | Release and soak evidence are production/operator validated and redacted. | VERIFIED (external) | `capture-bc10/release-audit.json` and `summary.json`. |
| 6 | B9 uses the accepted CPU-parametric ADR-002 path and passed the same custody gates. | VERIFIED (external) | ADR-002 plus retained release audit. |
| 7 | External evidence remains external and source-owned claims do not impersonate operator proof. | VERIFIED | Repository contains references/gates, not copied custody payloads. |

## Requirements

| Requirement | Disposition | Evidence role |
|---|---|---|
| REQ-003 | VERIFIED | Production tenant/trust/auth evidence and RLS/session gates. |
| REQ-004 | VERIFIED | Hosted/public runtime evidence and stable production commands. |
| REQ-006 | VERIFIED | Non-local retrieval/provider evidence gates and retained production result. |
| REQ-010 | VERIFIED | Capability, audit, signing, and reversible/fail-closed operations evidence. |
| REQ-011 | VERIFIED | Protected release gates and zero-regression evidence custody. |
| NFR-002 | VERIFIED | Self-hosted production parity and shared release checks. |
| NFR-004 | VERIFIED | Privacy, residency, erasure, redaction, and KMS evidence gates. |

## Explicit Boundaries

Tier-C six-SLO reproving, LongMemEval R@5, and an official-profile badge are not
invented by this reconstruction. Historical unchecked boxes remain historical;
the later custody packet closes only the B1-B10 claims it directly attests.
