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

The runtime accepts an existing `skill_store` reference. Imported skills begin in probation with a fixed weak provenance prior. Only matching tenant/user sources enter the runtime context. Local episode outcomes update revision-specific posteriors once per episode. Changed effects require explicit approval and retired revisions cannot be reactivated. Operators can approve effects through `skill-set-state --approve-effects --role operator --source-trust-tier 0`. Twelve local outcomes and a success lower bound of at least 0.5 are required for standalone activation.

The SDK supports synchronous iterators and asynchronous iterators. It forwards chunks unchanged and captures their accumulated text and explicit tool events only after natural exhaustion. Closing or cancelling a stream early does not fabricate a completed outcome. Framework context variables are applied while advancing each stream and restored before yielding to the caller.

The generic benchmark stream is diagnostic and is not a completed benefit evaluation.


## Hermes

The profile-scoped adapter is in `mnemosyne.hosts.hermes`. The plugin entry point is in `integrations/hermes`. It forwards prefetch, completed turns, actual tool events, skill-use identifiers and session closure to the same learning runtime. Each profile owns its own SQLite directory. The repository includes the adapter without changing an existing Hermes provider selection.

The plugin requires Mnemosyne to be installed in the Python environment used by Hermes. Place `integrations/hermes` in the target profile's memory-plugin directory and select the `mnemosyne` provider through Hermes configuration.


## Final serving and verification behavior

The SDK renders every hit named by its context receipt. Ordinary chat lets the runtime infer the task class. An explicit `risk_level="high"` or a safety-sensitive task class suppresses exploration and effectful candidates. Exact-goal, tightly verified active procedures can use the fast path without full retrieval; the configured comparison sample still runs retrieval and creates an external comparison request.

Supply `used_skills` and `used_lessons` with completed responses or directly to `post_turn_capture`. The runtime accepts only served targets and normalizes original SkillStore IDs or `skill_id@revision` into their served native artifact IDs. The SDK reuses its returned source CIDs in the episode, so erasing those CIDs reaches dependent learning state.

Policy proposals require real fingerprint-matched paired replay observations from a trusted `policy_variant_verifier` tool. They remain shadow while independent OQ2, tripwire, protected-case or ignition evidence is missing. `learning-export-training` is an operator-only read/export path; it does not run a trainer.
