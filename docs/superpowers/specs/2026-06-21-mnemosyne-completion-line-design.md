# Mnemosyne Completion Line — Design Spec

**Date:** 2026-06-21 · **Status:** approved, executing

> **Superseded / archival (2026-06-26):** this completion-line effort has concluded and its work is reconciled into `main`. The `~/Projects/Mnemosyne-completion` worktree and `~/Projects/Mnemosyne` clone referenced below were consolidated into the single canonical checkout `/Users/admin/Mnemosyne` (branches preserved on `origin` and in `~/Mnemosyne-consolidation-archive-20260626-151915/`). The working-directory paths below are historical.
**Baseline:** branched from `origin/main` @ `8c24197` (Codex's live line)
**Requirements source of truth:** `docs/BLUEPRINT-COMPLETION-PLAN.md` (full FR-1…21 traceability) +
`docs/blueprint/Mnemosyne-v2-Build-Blueprint.md` (the 40-page blueprint).

## Objective
Drive Mnemosyne to **full, no-compromise 1:1 parity** with the blueprint using a **parallel
multi-agent fleet**, with **zero architectural or merge conflict** with Codex's continuous work on
`main`.

## The hard constraint and its only solution
Two fleets (mine + Codex) cannot edit the same files with zero conflict. The resolution: **do not
share a working surface with Codex**, while building *on top of* its latest work, not duplicating it.

### Isolation architecture (guarantees zero conflict)
1. All work happens in an **isolated git worktree** `~/Projects/Mnemosyne-completion/` on branch
   **`completion/blueprint-parity`**, branched from Codex's current `origin/main`.
2. **`main` and Codex's working tree are never touched.** Only the completion branch is pushed.
3. **Additive-first:** agents create net-new files/dirs (`services/`, `eval/`, `infra/`,
   `tests/completion/`) and integrate through Mnemosyne's *existing config seams* (e.g.
   `--embedding-url`, `--reranker-url`, `--object-key-command`) rather than editing Codex's modules.
   Existing-module edits are avoided; if unavoidable they are minimal, bounded, and logged for
   reconciliation.
4. **Periodic `rebase onto origin/main`** absorbs Codex's commits — clean because additive files
   don't collide.
5. **Reconciliation is deliberate and user-controlled** — the branch is merged when the user
   chooses; Codex is never disrupted.

### Parallel fleet + verification
- Ultracode **Workflow** orchestration fans out **one agent per disjoint component** (no two agents
  touch the same path → no intra-fleet conflict), each paired with an **adversarial verifier**.
- Pattern per item: `build → adversarially verify → integrate`; a **completeness critic** closes
  each wave ("what FR/§ is unproven or missing?").

### No-compromise parity guarantee (Gate A + Gate B)
Every work item maps to a blueprint **FR/§**. Acceptance =
- **Gate A — built-to-spec:** implements the blueprint mechanism (no deterministic placeholder).
- **Gate B — proven:** meets the §12/§34 success criterion via the §33 harness (with confidence
  intervals).
Research-track items (FR-17, FR-21) use the blueprint's own bar (shadow + rails + measured, *not*
proven-lift). Scope-gated items (FR-20 multimodal, FR-21 LoRA) are held to blueprint scope — no
over-build. A parity-verification agent audits each item against the blueprint.

## Execution waves (parallel within each wave)
**Wave 1 — keystone foundations (all net-new, fully parallel):**
- `services/embedding/` — real embedding + cross-encoder reranker service matching the HTTP-adapter
  contract (FR-3 keystone; unblocks FR-6/ECE, G2/+15%).
- `eval/` — §33 evaluation/SLO harness + seed/synthetic dataset + suite-ignition (measures
  recall@k/nDCG, P95 latency, ECE, +15%-vs-full-context, poison-block).
- `infra/` — real-services `docker-compose.providers.yml` (Keycloak / Vault / c2patool) + setup.
- `tests/completion/security/` — adversarial poison/injection corpus (MINJA/AgentPoison-style) for
  the ≥95% block SLO.
- `tests/completion/rails/` — invariant-rail (§31) breach tests for all 7 rails.

**Wave 2 — prove + harden:** wire real providers via config seam; run harness → prove the 5 SLOs
(Gate B); harden partial FRs (3, 6, 9, 11, 12, 19) to full parity; data-model + MCP-ABI parity diffs.

**Wave 3 — research-track + scope + portability:** FR-17 cold loop to blueprint bar (shadow + rails
+ measured + counterfactual-replay fidelity); FR-20/21 to blueprint scope; G8 local↔prod shared
suite; resolve §17 open questions (PPR-latency benchmark, suite-ignition N, etc.).

## Agent rules of engagement (enforced in every agent prompt)
- Work **only** under `~/Projects/Mnemosyne-completion/`. Never touch `~/Projects/Mnemosyne`.
- Write **net-new files at disjoint paths**; do **not** edit existing `src/mnemosyne/*` modules.
- Do **not** run `git` / push / rebase (the orchestrator commits per wave to avoid races).
- Read the existing code to match contracts exactly (HTTP adapter shapes, CLI surface).

## Non-goals (respected, per blueprint §12)
N1 not a foundation model · N3 not a public-benchmark chase (private suite) · N4 not an agent
framework · N5 multimodal is post-v1 · N2 weight-tuning/LoRA is an optional advanced tier.
