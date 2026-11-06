# One coordinated learning system

The existing Mnemosyne suite and the experience runtime share learning state,
configuration, evidence, and lifecycle decisions. All 22 learning components
remain active by default. Existing APIs remain usable, including callers that
start before a newer host configures learning providers or a skill library.

## Ownership and preserved capabilities

| Capability | Coordinated implementation |
| --- | --- |
| Capture, retrieval, and access control | Existing engine and SDK/MCP/Hermes entry points retain their roles. Receipts connect served context to externally observed outcomes. |
| Trajectories, lessons, procedures, and attribution | `LearningSystem` and its existing models expose the engine's canonical records. Both manual induction and automatic consolidation use the same scoped candidate identities. |
| Failure interpretation | Legacy failure attribution reuses the runtime's tool-result interpretation for verifier verdicts, test counts, and exit codes. Attribution remains diagnostic, not invented causal reward. |
| Local and provider-assisted induction | Local corrections, demonstrated procedures, chunks, schemas, and abstractions remain available when provider proposals are enabled. Equivalent candidates share one record while retaining source episodes, provider receipts, and verified hypothesis links. |
| Skill libraries and lifecycle | Existing `SkillStore` imports, framework representations, and library APIs remain. The experience runtime owns lifecycle and outcome counting for managed skills; the library projects those decisions. |
| Route adaptation | Existing `AdaptiveRouteWeighter` supplies one bounded normalization algorithm. Native learning applies its daily movement limits through that algorithm, preserving both total weight and per-route bounds. |
| Retrieval policy experiments | Existing bandit, replay-fidelity checks, tripwires, and shadow optimizer remain. Each episode/variant contributes one observation; live and replay records remain auditable. Native state owns persistent serving overrides. |
| Calibration | Existing calibration jobs evaluate external learning outcomes. Retrieval confidence, episode-success conformal diagnostics, and success-probability bins retain their distinct statistical targets. A threshold for one is not silently applied to another. |
| Consolidation and background maintenance | Existing workers and explicit reflection use the shared runtime and current engine-owned configuration. Evidence consolidation and experience consolidation operate on their respective inputs; native episode sources are not induced again through the legacy evidence path. |
| Parametric learning | Existing `ParametricTier`, trainer adapters, artifact storage, and approval gates remain authoritative. Exports and old MCP proposal calls preserve or refresh canonical admission metadata so eligible native procedures reach that tier. |
| Persistence, retirement, rollback, and erasure | Existing engine storage and source-erasure handling remain in use. Shared learning writes preserve provenance and lifecycle; historical records do not gain verified outcomes merely by migration. |

## Function and use-case boundaries

- **Entry points coordinate; they do not implement another learner.** SDK, MCP,
  jobs, and legacy APIs delegate to shared records, extraction helpers, candidate
  identities, and learning writes.
- **Evidence consolidation maintains facts; experience consolidation learns
  behavior from outcomes.** Native-owned experience sources are excluded from
  duplicate legacy lesson/procedure induction.
- **Generators propose; validation admits; lifecycle promotes.** Local rules and
  configured providers feed one candidate stream. A provider cannot grade its
  own proposal into active use. Passing admission begins probation; external
  outcome evidence governs later promotion.
- **The skill library handles representation and discovery.** Runtime-managed
  skills have one lifecycle and one outcome counter owned by the learning
  runtime, rather than an additional library promotion policy.
- **Route adaptation changes retrieval-channel weights; policy experiments
  evaluate retrieval configurations.** Each uses its own defined output, and
  shadow experiments do not independently mutate persistent serving policy.
- **Different calibration targets remain explicit.** A retrieval-confidence
  score, an episode-success probability, and evidence that a particular skill
  helps are not interchangeable measurements.

## Changes from the unification audit

- Repeated old API calls reuse native artifacts and preserve their lifecycle;
  repeated historical induction and hot-loop diagnostics are idempotent.
  Pending compatibility edits pass through the conflict-aware writer before
  native records are refreshed.
- An unevaluated candidate created through the old API can receive its first
  admission check through normal consolidation.
- Provider mode supplements local learning. Candidate coalescing preserves all
  contributing provider and hypothesis links without duplicating the artifact.
  Repeated evidence for the same exact task, including case-only variations,
  does not broaden its applicability. Older stored identities retain their
  validated scope and lifecycle, including retirement.
- Older worker and MCP objects cannot overwrite newer explicit settings.
  Factory-created SDK runtimes read the same current engine configuration;
  directly constructed runtimes retain their explicit local dependencies.
  Direct skill-library operations also resolve the current configured library.
- Route weights remain normalized while respecting floors, caps, and daily
  movement limits. Policy selection includes the current verified replay and
  counts each episode/variant only once.
- Training export carries full native provenance and admission evidence. The
  `procedure_records` field provides lossless canonical serialization alongside
  the existing `procedures` compatibility representation of those same records.
  The older MCP proposal entry point refreshes native records after saving pending
  compatibility edits. Neither path weakens trainer eligibility.

These changes preserve distinct responsibilities rather than merging unrelated
statistical targets or deleting useful APIs. Operator-authored inputs, historical
unverified records, runtime-managed skills, and shadow policy experiments keep
their explicit admission rules.

## Execution and verification boundaries

Automatic learning still depends on the host providing completed turns and real
outcomes. New candidates still require admission, probation, and evidence for
promotion. Provider-assisted generation and actual model training require
explicit configuration; this audit runs neither paid providers nor a trainer.

Mnemetric remains a separate project. Its benchmark archives and public scores
are not shared storage or runtime dependencies of this learning system.

Focused regression tests cover legacy/native identity in both invocation orders,
current configuration in long-lived hosts, provider/local synthesis, hypothesis
completion, route bounds, unique policy observations, and training provenance.
An integrated SDK → old API → worker → durable reload test verifies that one
procedure and one episode survive the combined path. The associated validation
record lists the final test run and its limits.

Passing these integration tests establishes the tested behavior. It does not
establish that every learning mechanism improves performance on every task;
the full sealed benefit evaluation remains separate work.
