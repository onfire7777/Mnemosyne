# Codex Handoff

**Verified checkout:** `/Users/admin/Mnemosyne` on `main`.

**Important path note:** a stale planning note names `/Users/admin/Desktop/Mnemosyne/`, but that path is absent in the current Codex runtime. Do not edit `/Users/admin/Projects/Mnemosyne` for this work; it is a separate older checkout.

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
- G2/G3 seeds exist in `src/mnemosyne/providers/__init__.py` and `src/mnemosyne/dreamer.py`: the typed `SpecialistModuleRegistry` records role/budget/critical-path contracts, and `SandboxedDreamer` produces shadow-only, low-trust replay candidates without mutating the ledger or answer path.

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
- G2/G3 foundation adds typed specialist module manifests and a sandboxed dreamer contract while keeping generative replay off the answer critical path.
- `external` reality-class aliases normalize to `externally_suggested`, not `grounded`, and continue to trigger abstention when grounded evidence is absent.
- The default policy counterfactual replay hook now fails closed until real replay pairs prove fidelity; promotion-path tests use an explicit authorized hook.
- The replay-fidelity source probe now verifies the real gate wiring and fail-closed default rather than treating counterfactual replay as merely informational.
- Production soak manifest environment checks fail closed on invalid nested provenance-suite artifact paths, not only on missing artifacts.

## Next Safe Queue

1. Continue G1 breadth only where it moves a preregistered target metric without guardrail regression.
2. Continue the next code-owned G2/G3 slice: wire typed specialists into controller/retrieval orchestration and add a preregistered dreamer ablation gate before any promotion beyond shadow mode.
3. Prioritize real-infrastructure evidence capture for Tier B rows: IdP/Keycloak, Vault/KMS, ParadeDB+AGE+pgvector, hosted embedding/reranker/trainer endpoints, and C2PA roots.
4. Keep `eval/g0/` authoritative; do not fork a parallel harness.
5. Keep Mnemosyne distinct from gbrain, mempalace, and external agent memory systems in docs and implementation language.
