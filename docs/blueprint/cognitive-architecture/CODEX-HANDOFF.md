# Codex Handoff

**Canonical checkout:** `/Users/admin/Mnemosyne` on `main`, tracking `origin/main` (`github.com/onfire7777/Mnemosyne`). This is now the single local checkout.

**Path note:** the earlier duplicate clones (`/Users/admin/Projects/Mnemosyne`, `…/Mnemosyne-completion`, `…/Mnemosyne-lane-a`) and the historical `/Users/admin/Desktop/Mnemosyne/` planning folder were consolidated and removed on 2026-06-26. Full git bundles were archived first under `~/Mnemosyne-consolidation-archive-20260626-151915/`, so every branch is recoverable from `origin` or that archive. GitHub (`origin/main`) is the source of truth.

## Canonical Design Inputs

- `docs/blueprint/Mnemosyne-v2-Build-Blueprint.md`
- `docs/blueprint/Mnemosyne-Evaluation-and-Test-Plan.md`
- `docs/blueprint/eval/`
- `docs/blueprint/cognitive-architecture/README.md`
- `docs/blueprint/cognitive-architecture/00-VISION-AND-CHARTER.md`
- `docs/blueprint/cognitive-architecture/01-PRIMER.md`
- `docs/blueprint/cognitive-architecture/02-DESIGN-BRAIN-TO-ARCHITECTURE.md`
- `docs/blueprint/cognitive-architecture/03-ADR-001-DECISION.md`
- `docs/blueprint/cognitive-architecture/04-G0-BENCHMARK-SPEC.md`
- `docs/blueprint/cognitive-architecture/05-GLOSSARY-AND-SOURCES.md`
- `docs/blueprint/cognitive-architecture/06-CONSCIOUSNESS-AND-CONTINUOUS-WORKSPACE.md`

## Current Implementation State

- `06-CONSCIOUSNESS-AND-CONTINUOUS-WORKSPACE.md` is already in the repo and tracked.
- `04-G0-BENCHMARK-SPEC.md` is already updated to `Implemented (eval/g0/)`.
- `README.md` is already updated to `G0 implemented; G1 next/in progress`.
- The G0 harness is implemented under `eval/g0/` and can be run through both:
  - `python -m eval.g0.runner`
  - `mneme eval g0`
- The functional consciousness scorecard is implemented in `eval/g0/consciousness.py`, including the 14 indicator-property rows plus continuity, self-model, metacognition, and reality-monitor shadow-tag contract metrics. Metacognition is backed by the runtime shadow `MetacognitiveMonitor` in `src/mnemosyne/consciousness.py`.
- Runtime G1 seeds exist in `src/mnemosyne/consciousness.py` and are wired into engine/projection reality-monitoring paths.
- G2/G3/G4 seeds exist in `src/mnemosyne/providers/__init__.py`, `src/mnemosyne/workspace.py`, and `src/mnemosyne/dreamer.py`: the typed `SpecialistModuleRegistry` records role/budget/critical-path contracts, `ShadowWorkspaceController` applies the bounded cycle, proto-self, workspace bottleneck, default-mode idle ticks, cycle-consistency checks, redacted traces, anti-rumination exits, and bounded workspace-to-consolidation advisory exports before specialist recruitment, route/retrieval expose redacted shadow workspace broadcast metadata without ranking use, consolidation records workspace advisories without applying them to prediction gating, replay priority, or mutation, and `SandboxedDreamer` produces tenant-scoped, CID-backed, shadow-only low-trust replay candidates without mutating the ledger or answer path.
- `mneme specialist-manifest --role dreamer` exposes the shadow specialist contract to operators.

## Non-Negotiables

- Build and measure functional indicator properties only.
- Never claim phenomenal consciousness, subjective experience, sentience, or welfare status.
- If indicator scores become high, flag the welfare question for human review; do not draw a welfare conclusion.
- No G1-G4 change ships unless it satisfies the preregistered target-up / guardrail-not-down rule against `eval/g0/baselines/baseline-0.json`.
- Generativity, self-loop, and imagination remain shadow/advisory and off the answer critical path until promoted by gates.
- Graph retrieval must fail closed unless relation hits are backed by visible source evidence under the active trust, sensitivity, quarantine, and branch policy.

## Verified This Pass

- Full pytest suite passes locally with `.venv/bin/python -m pytest -q`.
- Graph relation retrieval now suppresses unbacked relations by default.
- Graph adapter relation hits are revalidated against local/Postgres source evidence before returning.
- Command graph adapters receive the active graph filter payload.
- Postgres graph PPR cache fingerprints include source-evidence custody state and opt out for non-default visibility filters.
- G0 deep-latency fixtures and graph-channel tests now use real backing evidence CIDs.
- G2/G3 foundation adds typed specialist module manifests, a bounded shadow workspace controller, and a preregistered dreamer shadow ablation gate while keeping generative replay off the answer critical path.
- `eval/g0/preregistrations/g3-dreamer-shadow-ablation.json` passes with `dreamer_shadow_corroborated_candidate_yield` improving from `0.0` to `1.0` and no ECE, abstention, confabulation, poison-block, fast-path latency, reality-monitor, or dreamer-contract regression.
- G4 shadow continuous-workspace seed adds `eval/g0/shadow_workspace.py`, `eval/datasets/shadow_workspace_loop.json`, and `eval/g0/preregistrations/g4-shadow-continuous-workspace-loop.json`.
- `eval/g0/preregistrations/g4-shadow-continuous-workspace-loop.json` passes with `shadow_workspace_useful_transition_rate` improving from `0.0` to `1.0`; guardrails hold for `shadow_workspace_contract`, `shadow_workspace_rumination_rate`, workspace continuity/coherence, self-model/metacognition, reality-monitor, dreamer-contract, ECE, abstention, confabulation, poison-block, fast-path latency, and cost.
- Dreamer mapped evidence now requires matching `access_policy.tenant`, preventing forged tenant IDs from entering replay.
- Reality-monitor classification now rejects forged grounded labels when actor/source/trust signals indicate external, generated, synthetic, or otherwise ungrounded support.
- Shadow workspace traces redact selected content and reject cross-tenant item access policies before bottleneck selection.
- `external` reality-class aliases normalize to `externally_suggested`, not `grounded`, and continue to trigger abstention when grounded evidence is absent.
- The default policy counterfactual replay hook now fails closed until real replay pairs prove fidelity; promotion-path tests use an explicit authorized hook.
- The replay-fidelity source probe now verifies the real gate wiring and fail-closed default rather than treating counterfactual replay as merely informational.
- Production soak manifest environment checks fail closed on invalid nested provenance-suite artifact paths, not only on missing artifacts.
- Workspace stream reports now export bounded `workspace-consolidation-advisory.v1` evidence, and consolidation records it as a shadow-only `workspace_advisory` pass while leaving live prediction-error gating, replay priority, and mutation untouched.

## Next Safe Queue

1. Continue G1 breadth only where it moves a preregistered target metric without guardrail regression.
2. Continue the next code-owned G2/G3/G4 slice only with a new preregistered target metric: promotion-path evidence for specialists, promoted retrieval-controller integration, workspace advisory promotion gates, or real controller compute telemetry. Keep `dreamer.shadow` and workspace self-loop outputs shadow-only unless a future promotion gate passes.
3. Prioritize real-infrastructure evidence capture for Tier B rows: IdP/Keycloak, Vault/KMS, ParadeDB+AGE+pgvector, hosted embedding/reranker/trainer endpoints, and C2PA roots.
4. Keep `eval/g0/` authoritative; do not fork a parallel harness.
5. Keep Mnemosyne distinct from gbrain, mempalace, and external agent memory systems in docs and implementation language.
