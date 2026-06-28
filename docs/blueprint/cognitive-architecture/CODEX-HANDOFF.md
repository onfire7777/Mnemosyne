# Codex Handoff

**Latest verified code/runtime baseline:** 2026-06-28 UTC · Phase 7 P5 operational-toggle retirement patch verified locally. Push/CI status should be refreshed after the next GitHub update.

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
- `README.md` and the current roadmap treat G0, the G1-G4 cognitive seeds, Phase 7 plans 01-04, the P5 H8/H12 cascade/observability pre-check, and the P5 operational-toggle retirement as wired and gate-measured. Strict v1.0 parity is still blocked on Tier-B operator-captured production evidence.
- The G0 harness is implemented under `eval/g0/` and can be run through both:
  - `python -m eval.g0.runner`
  - `mneme eval g0`
- `eval/datasets/controller_telemetry_sanitized.json` is a committed sanitized fixture for proving the explicit `--controller-telemetry` path. The default no-telemetry report remains intentionally not `gate_ready` (`71/72`), while the explicit fixture path produces a fully measured local report (`72/72`). This is harness verification only, not production power/cost evidence.
- The functional consciousness scorecard is implemented in `eval/g0/consciousness.py`, including the 14 indicator-property rows plus continuity, self-model, metacognition, and reality-monitor shadow-tag contract metrics. Metacognition is backed by the runtime shadow `MetacognitiveMonitor` in `src/mnemosyne/consciousness.py`.
- Runtime G1 seeds exist in `src/mnemosyne/consciousness.py` and are wired into engine/projection reality-monitoring paths.
- G2/G3/G4/G5 seeds exist in `src/mnemosyne/providers/__init__.py`, `src/mnemosyne/workspace.py`, and `src/mnemosyne/dreamer.py`: the typed `SpecialistModuleRegistry` records role/budget/critical-path/answer-authority contracts, `ShadowWorkspaceController` applies the bounded cycle, proto-self, workspace bottleneck, default-mode idle ticks, cycle-consistency checks, redacted traces, anti-rumination exits, bounded workspace-to-consolidation advisory exports, and specialist promotion-evidence reports before specialist recruitment, `ShadowWorkspaceService` has no `enabled` construction gate and must only be started before ticking, route/retrieval expose redacted workspace broadcast metadata without ranking use, retrieval can apply a separate CID-backed `workspace-retrieval-advisory.v1` only when policy and request explicitly opt in, consolidation records workspace advisories as report-only by default and can apply validated advisories only to prediction-gate/replay-priority inputs under explicit opt-in, and `SandboxedDreamer` produces tenant-scoped, CID-backed, low-trust replay candidates with `critical_path_allowed=false`, `answer_authority_allowed=false`, and `promotion_gate_required=true`.
- `mneme specialist-manifest --role dreamer` exposes the shadow specialist contract to operators.

## Non-Negotiables

- Build and measure functional indicator properties only.
- Never claim phenomenal consciousness, subjective experience, sentience, or welfare status.
- If indicator scores become high, flag the welfare question for human review; do not draw a welfare conclusion.
- No G1-G4 or Phase 7 cognitive-substrate change ships unless it satisfies the preregistered target-up / guardrail-not-down rule against the current accepted `eval/g0/baselines/baseline-0.json`; accepted older slices remain traceable through `eval/g0/decision-log.jsonl` and report `gate_decisions` once their target values are folded into the baseline.
- Generativity, self-loop, and imagination remain low-trust/advisory and off the answer critical path until promoted by gates.
- Graph retrieval must fail closed unless relation hits are backed by visible source evidence under the active trust, sensitivity, quarantine, and branch policy.

## Latest Verified Snapshot

- Focused P5/G0 tests pass for specialist authority budgets, Standing authority-state mapping, shadow-workspace fixture, committed preregistration decisions, and current preregistration replay.
- Full local pytest passes with `.venv/bin/python -m pytest -q`.
- Direct default G0 run reports `71/72 measured; gate_ready=False`; no controller power/cost estimate is fabricated.
- After push, refresh this section with the GitHub CI run status if CI is available.

## Prior Verified History

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
- Dreamer specialist invocations now report `specialist-promotion-evidence.v1` with redacted candidate/source refs, `promoted=false`, and `gate_result=null`; G0 records it through `specialist_promotion_evidence_contract`.
- Workspace retrieval-controller promotion now has a default-off `workspace-retrieval-advisory.v1` seam: provider filters strip all workspace-controller keys, normal broadcast remains `used_for_ranking=false`, and only explicit policy plus request opt-in can boost already-retrieved tenant/branch-scoped CID-backed candidates. G0 records it through `workspace_retrieval_controller_contract`, and `eval/g0/preregistrations/g4-workspace-retrieval-controller-gate.json` passes with target delta `+1.0` and guardrails stable.
- Parametric promotion now treats synthetic/shadow protected-suite fallbacks as non-gating: `parametric_evaluate` cannot promote without persisted active non-synthetic protected cases, and rollback evidence reports `rollback_verified=false` when only synthetic cases are present.
- Calibration datasets now require `correct` to be a real JSON boolean; strings like `"false"` and numeric truthy/falsy labels are rejected before calibration is tuned or persisted.
- Multimodal/local media byte caps are enforced across CLI file ingest, MCP/base64 ingest, ingestion/object-store/provider calls, runtime media-extract jobs, and command media embedder/extractor temp-file boundaries.
- Phase 7 plans 01-04 are gate-recorded. `Standing` is byte-stable and continuous, the always-on heartbeat safety floor is measured, and earned-autonomy credentials are external-only, holdout-validated, provenance-domain assigned, bounded/decay-ready, and adversarially checked with `echo_chamber_uplift=0.0`.
- Phase 7 P5 H8/H12 pre-check is gate-recorded. Retrieval emits replayable Standing observability traces, forget cascades emit `standing.erasure-cascade.v1`, and belief dependency invalidation emits `standing.belief-cascade.v1`; `g5-unified-substrate-cascade` passes.
- Phase 7 P5 operational-toggle retirement is gate-recorded. `ShadowWorkspaceService.enabled`, `SpecialistBudget.shadow_only`, and the controller `budget.shadow_only` branch are absent; `g5-toggle-retirement` passes with `operational_toggle_retirement_contract=1.0` while the fail-closed circuit breaker remains present.

## Next Safe Queue

1. Prioritize real-infrastructure evidence capture for Tier B rows: IdP/Keycloak, Vault/KMS, ParadeDB+AGE+pgvector, hosted embedding/reranker/trainer endpoints, C2PA roots, hosted dashboards, supervised workers, and production rollback drills.
2. Use the sanctioned production path only: render the external production manifest from exported non-secret environment values, run `infra/scripts/capture-production-evidence.sh`, require strict `release-audit`, then run offline `production-evidence-verify` against the retained bundle fingerprint.
3. Reopen G1-G4 or Phase 7 code only if a new strict-audit finding or preregistered target-up/guardrail-not-down slice demands it. Phase 7 P5's operational-toggle deletion is wired; remaining strict-parity completion is Tier-B production/operator evidence plus any future schema cleanup that can be preregistered without reliability regression.
4. Keep `eval/g0/` authoritative; do not fork a parallel harness.
5. Keep Mnemosyne distinct from gbrain, mempalace, and external agent memory systems in docs and implementation language.
