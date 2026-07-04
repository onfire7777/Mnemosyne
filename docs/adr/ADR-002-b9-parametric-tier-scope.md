# ADR-002: Scope strict v1.0 parity to self-hosted-evidencable rows; B9 parametric trainer is out-of-profile by design

**Date:** 2026-07-04
**Status:** Accepted
**Decider:** Jake B (operator/owner), recorded at the operator's direction
**Relates to:** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (row "Parametric tier"),
`.planning/ROADMAP.md` Phase 8, `docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`,
`.planning/TIER-B-TO-100-AGENT-PROMPT.md` (B9/FR-21 lane),
`docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` FR-21.

## Context

The strict blueprint parity audit requires operator-captured production
evidence for ten Tier-B rows. Nine of those rows (B1–B8, B10) are evidencable
on the deployed self-hosted production profile (16 GB, no GPU), which was
brought up end to end on 2026-07-04
(`.planning/runbooks/LIVE-DEPLOYMENT-VALIDATION-2026-07-04.md`).

Row B9 (FR-21, parametric tier) requires evidence from a real LoRA /
test-time-training trainer deployment. The planning contract has been explicit
since 2026-06-30 that this is **not satisfiable on the no-GPU self-hosted
host**: "B9/FR-21 still requires real cloud/GPU trainer evidence or an
explicit ADR before strict v1.0 parity reaches 100%." The Phase 8 roadmap
entry likewise routes B9 to "cloud/GPU evidence or explicit ADR."

This ADR is that explicit decision record.

## Decision

1. **Strict v1.0 parity sign-off is scoped to the self-hosted production
   profile**: rows B1–B8 and B10, evidenced by operator-captured, signed,
   redacted bundles passing manifest-bound `release-audit` and offline custody
   verification against the deployed self-hosted stack.
2. **B9 remains `Partial` by design** on this profile. It is not waived,
   weakened, or marked Done: the row, its source-side gates
   (`parametric-trainer-check`, the B9 release-audit evidence clamps), and its
   runbook (`.planning/runbooks/row-09-parametric-tier.md`) stay intact and
   fail-closed.
3. **The strict audit's completion language is amended** to read: with this
   ADR accepted, v1.0 strict parity is complete when B1–B8 and B10 are Done;
   B9 is tracked as an explicitly deferred cloud-profile row, documented as
   out-of-profile rather than incomplete-by-neglect.
4. **No local/synthetic substitute is permitted for B9.** The existing
   prohibition on placeholder or locally-generated trainer evidence stands.
   The parametric code path remains default-off, isolated, and rail-gated as
   shipped.

## Reversibility

This decision is additive and reversible. If a funded cloud/GPU trainer
deployment (the `cloud` values-extension in
`infra/docker-compose.prod.yml`'s documented profile) later produces real
operator-captured B9 evidence that passes `parametric-trainer-check` and
release-audit, B9 flips to Done through the unchanged evidence path and this
ADR's scoping clause becomes moot without further amendment.

## Consequences

- The honest completion statement becomes: *"v1.0 strict parity: complete on
  the self-hosted profile (B1–B8, B10); B9 parametric trainer deferred to a
  funded cloud/GPU deployment by ADR-002."*
- Release-audit behavior is unchanged: nothing in this ADR alters code,
  gates, thresholds, or evidence validation. It changes only what the
  final sign-off claims and how B9's `Partial` status is categorized.
- Future sessions must not "finish" B9 with synthetic evidence and must not
  reopen the GPU-vs-ADR question as if undecided; cite this ADR instead.

## Alternatives considered

- **Fund cloud/GPU trainer evidence now** — rejected for now on cost/priority
  grounds; explicitly preserved as the reversal path above.
- **Mark B9 Done via local command-provider evidence** — rejected: violates
  the non-local trainer requirement the release-audit gates enforce and the
  project's evidence-integrity contract.
- **Leave the decision open** — rejected: an undecided B9 blocks an honest
  v1.0 sign-off statement indefinitely and invites either stall or gaming.
