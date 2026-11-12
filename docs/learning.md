# Outcome-grounded learning

Learning is enabled by default. Every runtime component starts in `active` mode. Distillation defaults to deterministic operation. Provider distillation requires explicit configuration. Existing stored policies receive these defaults when their learning fields are absent.

A host first calls `prepare_context` with tenant, user, session and query. The runtime returns filtered hits, eligible learned artifacts, a prediction and an immutable receipt. After the assistant completes, the host calls `observe_turn` with the actual user text, assistant text, receipt and observed tool events. External feedback can arrive later through `record_signal`.

Retrieval and repetition earn no outcome credit. Assistant prose earns no reward. Evidence and authority remain separate from learned utility. The runtime's mandatory guards validate changes through its single learning writer.

Completed tool results can resolve an episode immediately. Failures and every ten resolved outcomes per user trigger consolidation through shared host orchestration. Hosts that set `defer_semantic_review` (the Codex integration) skip this in-turn pass; their background worker consolidates instead, outside the hook deadline. Atomic claims prevent duplicate feedback from scheduling the same automatic pass twice; failed passes remain retryable. Session closure resolves remaining episodes under the runtime's expiration rules and runs maintenance even without new outcomes. The `learning_consolidate` queue job and `learning_reflect` slow-cadence pass use the same guarded runtime and configured providers.

## Learning mechanisms

Receipts freeze the served items, routes, revisions, task class, prediction, effective policy and trace parameters before feedback arrives. Eligibility decays with elapsed time and intervening turns. Resolved external outcomes update success posteriors. Utility and route changes additionally require positive treatment-versus-control evidence for the same task class. Delayed feedback resolves its original episode.

Serving combines tested success, bounded utility, route weights, need-weighted exploration and older-task importance. Proven procedures can use a goal-checked fast path, with deliberate comparison samples. Calibration uses observed outcomes. The optional policy learner compares safe retrieval variants through recorded replay observations, protected cases and the existing OQ2 fidelity check.

Consolidation interleaves recurring tasks and prioritizes new outcome evidence. Source-grounded candidates include correction lessons, procedures, quoted schema nodes, reusable chunks and simpler rules. Pattern separation requires held-out improvement for both classes. Provider proposals pass the same provenance, regression and effect-approval gates. Hypotheses request external verification before admission.

Artifacts move through candidate, probation, active, labile, demoted and terminal states. Successful admission starts probation. Promotion requires tested outcomes and controls. Failures can open a reconsolidation window and propose a new revision. Revisions use compare-and-swap and outcome-based trials. Scheduled revalidation requests fresh evidence, and failed chunks invalidate their parents. Retirement and erasure prevent old revisions returning through a context change.

The implementation reuses `LearningSystem`, `SkillStore`, `PromotionGate`, `LocalCritic`, the route and policy learners, background jobs, user profiles and the existing engine access controls. New coordination and storage live in `src/mnemosyne/experience`. The host integration guide explains automatic capture in SDK and Hermes adapters.

The [unified ownership map](learning-unification.md) explains each preserved
capability and its authoritative implementation. Provider-assisted induction
supplements local induction; matching candidates retain combined provenance in
one record. Existing callers and long-lived hosts share the current configured
providers, skill library, and protected cases.

## Controls

MCP tool names use underscores. Equivalent CLI commands use hyphens.

| Tool | Purpose |
| --- | --- |
| `prepare_context` | Capture context and a receipt |
| `observe_turn` | Record a completed turn and real tool results |
| `record_signal` | Attach feedback to an owned episode |
| `end_session` | Close the current session and consolidate |
| `learning_status` | Inspect tenant runtime status |
| `learning_explain` | Inspect an owned episode or an artifact |
| `learning_pause`, `learning_resume` | Pause and resume tenant learning |
| `learning_mode` | Select `off`, `shadow` or `active` for a component |
| `learning_pin`, `learning_lock` | Protect an artifact |
| `learning_rollback` | Revert an auditable learning change |
| `learning_defects`, `learning_defect_export` | Inspect defect reports |
| `learning_reflect` | Run consolidation |
| `learning_verify_defect` | Replay and verify a defect repair |
| `learning_export_training` | Export eligible procedures for explicit shadow training |

Tenant-wide controls require operator authority and the operator source-trust tier. A signed MCP session binds tenant, user, session, role and source trust. Verifier and test events require a trusted authenticated host with source trust at most 1. User corrections and ratings can use their own feedback channel. Feedback must identify an episode owned by that user and session.

Pausing or changing component modes does not disable the invariant guards. Open defects prevent resuming. Source erasure is handled by the engine's learning erasure cascade.

Components support `off`, `shadow` and `active`. Shadow mode records evaluation state while active mode permits its bounded serving changes. Tenant pause suspends learning updates. Capture continues to preserve actual experience. All 22 component defaults are active. Model-provider distillation and parametric training require explicit configuration.

## Guard catalogue

`experience/guards.py` validates the learning writer boundary. `experience/monitors.py` checks retained state and sufficiently sampled calibration, exploration, reward-proxy and protected-case observations. Statistical checks use uncertainty intervals. Calibration and exploration checks use the enabled components recorded in each immutable receipt. A violation blocks the mutation, freezes learning and records a replayable defect. The following table describes the implemented boundaries. Statistical benefit and long-run absence claims require the evaluations described below.

| Code | Failure class | Implemented boundary or check |
| --- | --- | --- |
| X1 | Strengthening from use alone | Utility and route changes require matching resolved credit. Reads preserve learned statistics. |
| X2 | Repetition as authority | Exposure and authority fields are excluded from learned inputs. |
| X3 | Spurious causation | One owned episode per receipt, frozen eligibility and positive matched contingency. |
| X4 | Loss of exploration | Configuration floor and observed-exploration monitoring after sufficient decisions. |
| X5 | Asymmetric feedback | Symmetric bounded rates and sampled calibration monitoring. |
| X6 | Rigid habits | Goal and condition checks on serving, plus deliberate comparison sampling. |
| X7 | Reward capture | External signal allowlist, verified promotion evidence and proxy-gap monitoring. |
| X8 | Unchanged replay | Outcome fingerprints prevent replay earning new credit or candidates repeatedly. |
| X9 | Overgeneralization | Exact one-shot scope and recorded successful evidence for scope changes. |
| X10 | Revival of retired behavior | Terminal revisions cannot resume serving. |
| X11 | Misinformation rewriting evidence | Immutable evidence ownership, data-only wrapping and recorded source-hash checks. |
| X12 | Hindsight | Immutable receipts and prediction hashes. |
| X13 | Outcome bias | Credit uses the frozen prediction error and promotion requires accumulated verification. |
| X14 | Anchoring and availability | Outcome-backed posterior consistency and order-invariant sufficient statistics. |
| X15 | Wrong provenance | Live evidence IDs, owned source episodes and literal source quotes. |
| X16 | Confidence from familiarity | Posterior counts must be supported by recorded outcomes. |
| X17 | Erasure residue | Source-linked cascade, recomputed statistics, external-store retraction and audit-key revocation. |
| X18 | Destructive interference | Immutable content revisions, locked-artifact checks and protected-case monitoring. |
| X19 | Unbounded plasticity | Rate, utility and route bounds with importance-based stiffness. |
| X20 | Invented schema content | Each assimilated node requires a live literal quote. |
| X21 | Popularity as trust | Weak import prior, source validation and probation admission. |
| X22 | Novelty as truth | Novelty affects scheduling priority and is excluded from authority inputs. |
| E1 | Harmful task splitting | Both child classes must improve on held-out observations. |
| E2 | Broken chunk propagation | Active parents require valid active chunk dependencies. |
| E3 | Worse abstract rules | Held-out candidate results must match or exceed replaced rules. |
| E4 | Unsupported explanation | Explanation links must match the live supporting episodes and quotes. |

Test-only mutations cover every code through the real writer and verify containment. Production builds exclude the mutation fixtures. `learning_defect_export` produces a redacted replay bundle and `learning_verify_defect` runs its verification. Resume requires verified defects and operator authorization.

## Persistence and compatibility

Receipts, episodes, credit, statistics, artifacts, defects and policy state live in the owning engine's learning storage. `Trajectory`, `Lesson` and `Procedure` serialize these canonical records; the existing `LearningSystem` API is a compatibility view over them. Older side-state files and embedded legacy archives migrate into this storage without retaining a second mutable copy. Compatibility saves preserve native metadata and reject conflicting edits. Historical trajectories are retained as `legacy` episodes, with claimed outcomes stored separately from verified rewards and credit. Existing artifacts require contemporary evidence before entering the active learning runtime.

The runtime owns the lifecycle of learned and runtime-imported skills. `SkillStore` projects their states and distinct episode outcomes, including rollback and erasure, instead of applying a second promotion threshold. When one library revision supports several task classes, its public state conservatively summarizes those scopes and `native_states` exposes each artifact's state. Native revisions retain their library lineage without importing the library projection as another candidate. Standalone skill imports keep their existing validation path until they enter the runtime. Legacy consolidation skips evidence already owned by native episodes, preventing duplicate lesson and procedure induction.

Audit payloads are encrypted with independently revocable keys. Erasure removes the relevant keys and source-dependent learning state while retaining append-only audit events. Terminal revisions remain terminal. Rolling back retirement creates a new candidate revision for validation.

## Evaluation status

All F1–F26 families have executable specialized probes, and the test suite exercises concrete guard faults for X1–X22 and E1–E4. Advanced probes report unmet training prerequisites explicitly. A full all-arm sealed evaluation, external-model evaluation and production latency validation have not been completed. Current diagnostics do not establish that every learning mechanism improves task success. See `eval/learning/COVERAGE.md` for the remaining evaluation work and `eval/learning/README.md` for reporting rules.


## Implementation choices

Success predictions are probabilities. The prediction-error update compares an outcome in the range −1 to 1 with the corresponding expected reward `2 * prediction - 1`. This preserves symmetric positive and negative errors.

Success posteriors count comparable resolved outcomes. Eligibility-weighted prediction error drives causal utility separately, so confidence in task success and credited contribution retain distinct meanings.

The rolling regression breaker requires a decline of at least fifteen percentage points and non-overlapping Wilson intervals for the two twenty-outcome windows. This prevents small-sample fluctuations from freezing a stationary learner. Calibration reports the measured error and requires its uncertainty-adjusted lower bound to exceed the tolerance before opening a defect.

Legacy induction remains readable, but its validation and promotion commands require recorded outcome provenance. Passing candidates enter probation. Retired revisions remain terminal, and rollback creates a new candidate revision when restoring their content.

The implementation was built across dependent phases before evaluating the complete benchmark gates. Learning is enabled by default at the user's request. The outcome, provenance, effects-approval, erasure and defect guards remain mandatory.
