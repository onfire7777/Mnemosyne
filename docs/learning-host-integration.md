# Host integration

## Python SDK

```python
from mnemosyne import AutoMemorySession
from mnemosyne.engine import LocalMemoryEngine

engine = LocalMemoryEngine(store_path="memory.json")
with AutoMemorySession(engine, tenant_id="team", user_id="alice") as session:
    chat = session.wrap(my_chat_callable)
    response = chat("Check the deployment")
```

The wrapper prepares context before the call and records the response after completion. Awaitable responses are captured after awaiting. A failed callable does not fabricate a successful episode.

To provide external results, return a response mapping with a `tool_events` array alongside the response text. Events should contain the actual tool name and its real result. Supported verifier results include `verdict`, explicit test counts, and nonzero exit codes. A zero exit code alone does not prove task success. Trusted corrective instructions belong in `expected_steps` or `corrective_steps`, linked to the external tool's recorded output.

```python
return {
    "content": "The test run completed.",
    "tool_events": [
        {"name": "test_runner", "source": "tool", "passed": passed, "failed": failed}
    ],
}
```

The SDK's learning runtime currently supports the `main` branch. Existing SDK sessions on other branches retain their branch-specific memory operations and do not invoke the main-branch learning runtime. Use an explicit main-branch session when learning capture is required.

For a custom host, use `MemoryTools.prepare_context`, retain its `receipt_id`, then call `MemoryTools.observe_turn` with that receipt after completion. Use `record_signal` for delayed outcomes and `end_session` on closure. The lower-level `LearningRuntime` is available to trusted in-process hosts, which own their authentication boundary.

## CLI

```sh
mneme --store memory.json prepare-context \
  --tenant-id team --user-id alice --session-id demo \
  --query 'Check the deployment'

mneme --store memory.json learning-status \
  --tenant-id team --role operator --source-trust-tier 0
```

Pass tool events, receipt IDs and used artifact IDs as JSON arrays. For example, `--receipt-ids '["RECEIPT_ID"]'`. Keep the same tenant, user and session for feedback. Administrative commands default to a read-only role, so specify the authorized operator role and trust tier explicitly.

## Background worker

`RuntimeJobHandlers.handlers()` includes `learning_consolidate`. Its payload requires `tenant_id` and accepts `branch="main"`. A non-main branch is rejected. The slow consolidation cadence also includes `learning_reflect`. Both paths call the same guarded `LearningRuntime.consolidate` implementation.

## Current boundaries

The runtime accepts an existing `skill_store` reference. SDK, MCP, jobs and host adapters share configured skill libraries, distillation providers and active protected regression cases through `experience.integration.build_learning_runtime`. Runtime-imported skills begin in probation with a fixed weak provenance prior. Only matching tenant/user sources enter the runtime context. Local episode outcomes update revision-specific posteriors once per episode. The runtime owns promotion; the library reflects its states and counters. Twelve successful uses alone cannot bypass the runtime's control-outcome requirement.

Changed effects require explicit approval and retired revisions cannot be reactivated. Operators can approve effects through `skill-set-state --approve-effects --role operator --source-trust-tier 0`; managed revisions route that operation through the native writer. Standalone text skills require twelve local outcomes and a success lower bound of at least 0.5 for activation. Explicitly verified, complete BurnSkill framework imports retain their existing validation and effect-approval path. Once a skill enters runtime management, direct library outcome calls do not add a second observation; submit feedback with the owned episode instead.

The SDK supports synchronous iterators and asynchronous iterators. It forwards chunks unchanged and captures their accumulated text and explicit tool events only after natural exhaustion. Closing or cancelling a stream early does not fabricate a completed outcome. Framework context variables are applied while advancing each stream and restored before yielding to the caller.

The generic benchmark stream is diagnostic and is not a completed benefit evaluation.


## Hermes

The profile-scoped adapter is in `mnemosyne.hosts.hermes`. The plugin entry point is in `integrations/hermes`. It forwards prefetch, completed turns, actual tool events, skill-use identifiers and session closure to the same learning runtime. Each profile owns its own SQLite directory. The repository includes the adapter without changing an existing Hermes provider selection.

The plugin requires Mnemosyne to be installed in the Python environment used by Hermes. Place `integrations/hermes` in the target profile's memory-plugin directory and select the `mnemosyne` provider through Hermes configuration.

## Codex

`mnemosyne.hosts.codex.CodexAdapter` handles `SessionStart`, `UserPromptSubmit`,
`PostToolUse`, `Stop`, and `SessionEnd`. The entry point in
`integrations/codex/hook.py` binds it to a local authenticated `runtime` module
that supplies `STATE`, `TENANT`, `USER`, `open_facade`, `locked`, and `invoke`.
The existing MCP configuration and provider credentials stay in that local
runtime configuration.

The adapter keeps durable per-session state and validates a recovered
transcript's session and turn identities. Completed command records preserve
exit codes and actual test output. A standalone pytest invocation can provide
test counts. Arbitrary shell output, compound commands, and a zero exit code
alone do not establish a successful task outcome.

The `integrations/codex/automatic_learning.py` entry point advances consolidation
when recorded outcomes, artifact state, learning controls, or protected cases
change. Successful passes record their resulting input fingerprint. Trainer
validation failures remain retryable on the next scheduled worker pass.

If a prompt hook was missed, a completed transcript turn can still be recorded.
That recovered turn carries only an existing matching context receipt, so a
later retrieval cannot receive credit for earlier work. Retry reconciliation
and migration of older hook state prevent duplicate episodes after a restart.
Subagent instructions have an internal origin and are excluded from human-turn
capture.

Only retained source evidence enters a new episode's provenance. If an older
episode refers to unavailable evidence, consolidation excludes that episode
from induction and reports the skipped count while retaining its history.

## Task identity

Automatic task identity includes the complete Unicode-normalized request and
the available tool set. Outer whitespace and tool ordering are normalized.
Case, internal whitespace, identifiers, numbers, negation, and request details
remain distinct. New automatic identities use the `lexical:v3:` namespace. Earlier identities
and their outcome history remain readable under their original keys.

Hosts that know two differently worded requests represent the same task can
supply the same `task_type` to `prepare_context`. That explicit class is the
supported contract for sharing learning across semantic paraphrases.


## Final serving and verification behavior

The SDK renders every hit named by its context receipt. Ordinary chat lets the runtime infer the task class. An explicit `risk_level="high"` or a safety-sensitive task class suppresses exploration and effectful candidates. Exact-goal, tightly verified active procedures can use the fast path without full retrieval; the configured comparison sample still runs retrieval and creates an external comparison request.

Supply `used_skills` and `used_lessons` with completed responses or directly to `post_turn_capture`. The runtime accepts only served targets and normalizes original SkillStore IDs or `skill_id@revision` into their served native artifact IDs. The SDK reuses its returned source CIDs in the episode, so erasing those CIDs reaches dependent learning state.

Policy proposals require real fingerprint-matched paired replay observations from a trusted `policy_variant_verifier` tool. They remain shadow while independent OQ2, tripwire, protected-case or ignition evidence is missing. `learning-export-training` is an operator-only read/export path; it does not run a trainer.
