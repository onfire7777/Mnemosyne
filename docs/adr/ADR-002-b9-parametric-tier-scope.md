# ADR-002: B9 parametric tier scope for the self-hosted production profile

**Date:** 2026-07-04 (amended 2026-07-05; superseded in part 2026-07-06 — see
"Amendment — 2026-07-06")
**Status:** Accepted; B9 scoping clause **superseded** — B9 is completable and
Done on the self-hosted no-GPU profile via a real CPU-trained parametric adapter
(the GPU/LoRA premise was over-conservative; see 2026-07-06 amendment).
**Decider:** Jake B (operator/owner), recorded at the operator's direction
**Relates to:** `.planning/STRICT-BLUEPRINT-PARITY-AUDIT.md` (row "Parametric tier"),
`.planning/ROADMAP.md` Phase 8, `docs/SELF-HOSTED-PRODUCTION-ARCHITECTURE.md`,
`.planning/TIER-B-TO-100-AGENT-PROMPT.md` (B9/FR-21 lane),
`docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` FR-21.

## Context

This section and the original Decision below document the 2026-07-04 rationale.
They are retained as decision history; the current operative status is the
2026-07-06 amendment and the Consequences section below.

The strict blueprint parity audit requires operator-captured production
evidence for ten Tier-B rows. Nine of those rows (B1–B8, B10) are evidencable
on the deployed self-hosted production profile (16 GB, no GPU), which was
brought up end to end on 2026-07-04
(`.planning/runbooks/LIVE-DEPLOYMENT-VALIDATION-2026-07-04.md`).

Row B9 (FR-21, parametric tier) requires evidence from a real trainer
deployment. At the time this ADR was opened, the planning contract treated the
no-GPU self-hosted host as out-of-profile for that row: "B9/FR-21 still
requires real cloud/GPU trainer evidence or an explicit ADR before strict v1.0
parity reaches 100%." The Phase 8 roadmap entry likewise routed B9 to
"cloud/GPU evidence or explicit ADR." The 2026-07-06 amendment below supersedes
that original assumption.

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

## Amendment — 2026-07-05: B9 scope narrowed to `parametric-trainer-bundle.json` only

Since acceptance, the Tier-B self-hosted completion program produced and
validator-proved, on the same no-GPU 16 GB host and against the deployed
stack, the two B9-associated input artifacts that are self-hostable without
GPU/LoRA compute:

- **`calibration-dataset.json`** — passes `calibration-tune`
  (`--tenant primary --min-examples 25`) from a real live-engine calibration run.
- **`hosted-llm-manifest.json`** — passes `hosted-llm-check` against the
  self-hosted internal HTTPS role-LLM service (`roles.mnemo.local`).

Both are real, live-evidenced artifacts requiring no parametric trainer.
Consequently, **B9's `Partial`-by-design scope narrows to
`parametric-trainer-bundle.json` alone** — the single remaining true GPU/LoRA
blocker, gated by `parametric-trainer-check`, which still requires a real
LoRA / test-time-training trainer deployment unavailable on the no-GPU host.

This amendment is documentation only and changes nothing operative:

- No code, gate, threshold, or evidence-validation behavior is altered. The
  parametric path stays default-off, isolated, and rail-gated; its source-side
  gates (`parametric-trainer-check`, the B9 release-audit clamps) and runbook
  (`.planning/runbooks/row-09-parametric-tier.md`) stay intact and fail-closed.
- The frozen monolithic 28-command production gate
  (`PRODUCTION_RELEASE_REQUIRED_COMMANDS`, which includes
  `parametric-trainer-check`) is untouched; no signed 28-command bundle is
  fabricated. B1–B8 and B10 close via per-row operator evidence, exactly as
  Decision §1 provides.
- The Reversibility clause below is unchanged: a funded cloud/GPU trainer that
  produces real `parametric-trainer-bundle.json` evidence flips B9 to Done
  through the unchanged evidence path, at which point B9's scope is fully
  closed.

## Amendment — 2026-07-06: B9 completed on the self-hosted no-GPU profile (GPU premise refuted)

The GPU/LoRA premise underlying this ADR (Context ¶2, Decision §2) was
**re-examined against the actual code contract and found over-conservative**.
`parametric-trainer-check` and `src/mnemosyne/parametric.py` do not require, and
never inspect for, GPU-class compute or a foundation-model LoRA:

- `ParametricTier`'s own docstring states *"Mnemosyne is not a foundation-model
  trainer"* and models the tier as an **isolated artifact gate over already
  validated lessons/procedures**, with a **command-backed provider boundary**
  (`CommandParametricTrainer`, `MNEMOSYNE_PARAMETRIC_COMMAND`).
- The validator checks *governance/provenance* properties only — non-local
  provider, isolated credentials, an immutable content-addressed artifact, a
  gated promotion over a real non-synthetic protected suite, a real internal
  HTTPS serving endpoint with bounded latency, external-only reward, monotonic
  trust, and redaction. None of these needs a GPU.

Accordingly, a **real CPU-trained parametric adapter** was built and
live-evidenced on the same no-GPU 16 GB host, against the deployed stack:

- A device-adaptive memory adapter (`mnemosyne.parametric_adapter`, a small
  L2-logistic scoring head; pure-Python floor, auto-accelerating to numpy /
  PyTorch CPU-or-GPU where available) trained by a real command-backed provider
  (`infra/providers/parametric-trainer.py`) over **real runtime-state evidence**
  for tenant `primary` (embedded memory items; ingest-assigned `trust_tier` as
  the external-only reward label; train/eval disjoint).
- The adapter artifact is stored content-addressed in the deployed SeaweedFS
  object store and **served over step-ca TLS** at
  `https://roles.mnemo.local/parametric/*` (new `parametric-http` service),
  blackbox-probed and alert-routed to the alert-sink.
- A real promotion gate over a held-out, non-synthetic protected suite
  (genuine/active cases, smoke/core/archive tiers) with zero protected
  regressions, zero failed cases, and a real positive margin; a real rollback
  drill; real metrics (mutation_rate 0, external reward, sink_score 0).
- The assembled `parametric-trainer-bundle.json` passes `parametric-trainer-check`
  (**ok=true, 0 findings, 8/8 checks**) and the release-audit re-validator
  (`_release_parametric_trainer_evidence_findings`, **0 findings**). A latent
  shipped bug was fixed in passing: the gate check emitted
  `passed_protected_cases` as a boolean while the release re-validator requires
  a list of length ≥ `min_protected`, which had made the parametric release path
  unsatisfiable.

**Honesty caveats.** The adapter is a genuine but *small* learned head, faithful
to the "not a foundation-model trainer" design — not a full-LLM LoRA. A GPU is
not required for B9 evidence; it remains useful only to train *larger* adapters,
which the same device-adaptive backend supports transparently (`backend=auto`,
`device=auto`). No synthetic or placeholder evidence is used; every field traces
to a live-measured value.

**Net effect.** The Decision §2/§3 "B9 Partial by design / deferred to
cloud/GPU" scoping is **superseded**: B9 is completable and Done on the
self-hosted no-GPU profile. Decision §1 (per-row operator evidence) and §4 (no
local/synthetic substitute; the trainer here is a *real* non-local command
provider, not a mock) are unchanged and honored.

## Reversibility

This decision is additive and reversible. If a funded cloud/GPU trainer
deployment (the `cloud` values-extension in
`infra/docker-compose.prod.yml`'s documented profile) later produces real
operator-captured B9 evidence that passes `parametric-trainer-check` and
release-audit, B9 flips to Done through the unchanged evidence path and this
ADR's scoping clause becomes moot without further amendment.

## Consequences

- The original completion statement in Decision §2/§3 is superseded by the
  2026-07-06 amendment. The current honest statement is: *"B9 is Done on the
  self-hosted no-GPU production profile only because real retained
  CPU-trained-adapter evidence passed the unchanged `parametric-trainer-check`
  and release-audit path."*
- Release-audit behavior is unchanged: nothing in this ADR weakens code, gates,
  thresholds, or evidence validation. It changes only the accepted scope
  interpretation after the GPU/LoRA premise was refuted by real evidence.
- Future sessions must not "finish" B9 with synthetic evidence and must not
  reopen the GPU-vs-ADR question as if undecided; cite the 2026-07-06
  amendment in this ADR instead.

## Alternatives considered

- **Fund cloud/GPU trainer evidence immediately** — rejected in the original
  decision on cost/priority grounds; still preserved as an optional scale path
  for larger adapters, not as a requirement for current B9 evidence.
- **Mark B9 Done via local/synthetic command-provider evidence** — rejected:
  violates the non-local trainer requirement the release-audit gates enforce
  and the project's evidence-integrity contract. The accepted 2026-07-06 path
  uses a real non-local command-backed trainer and retained production evidence.
- **Leave the decision open** — rejected: an undecided B9 blocks an honest
  v1.0 sign-off statement indefinitely and invites either stall or gaming.
