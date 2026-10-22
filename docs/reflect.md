# Grounded reflection

`reflect` answers questions from authorized long-term memory through the same
bounded, multi-hop orchestrator used by the grounded evaluation path. It is
available as an MCP tool, a Python method, and the `mneme reflect` command.

For example, evidence saying “Ada owns project Zephyr” can lead to another
record saying “Project Zephyr launches Friday.” Reflection can follow that
connection and return “Friday” with the supporting evidence CID, exact span,
and a hash of the cited text. It does not save the generated answer or promote
it into a fact.

## Calling it

With the server's grounded providers configured, an MCP client can call:

```json
{
  "name": "reflect",
  "arguments": {
    "tenant_id": "my-tenant",
    "user_id": "my-user",
    "question": "When does Ada's project launch?",
    "branch": "main"
  }
}
```

Use the server's existing signed-session mechanism in a shared deployment.
With `--require-session`, a valid token binds tenant, user, role, and source
trust before reflection runs. Conflicting tenant/user arguments are rejected;
caller-supplied role and source trust cannot override the token. Without session
authentication, this tool has the same trusted-caller boundary as ordinary
search. Provider commands and models are never MCP arguments.

The equivalent local command uses the configured store and providers:

```sh
mneme --store ./memory.json reflect \
  --tenant my-tenant --user my-user \
  --question "When does Ada's project launch?"
```

Optional scope arguments include `--branch`, `--max-trust-tier`,
`--max-sensitivity`, repeated `--capability-tag`, `--purpose`, and
`--lawful-basis`, plus `--residency`, `--region`, and `--as-of`.
`--as-of` requires a timezone-aware ISO 8601 timestamp. Trust tier zero is the
most trusted; the maximum is a ceiling on the least-trusted tier admitted.
Session-only working memory is not included in this initial reflection surface.
The older `answer` and `eval-answer-batch` commands retain their evaluation-only
requirements.

The result contains `answer`, `abstained`, `claims`, `hops`, and `reader`.
Each claim has `evidence_cids`, exact `spans`, and a `derivation` identifying a
quotation or a deterministic synthesis operation. Span offsets index Unicode
code points in the source string; `slice_sha256` hashes the cited substring's
UTF-8 bytes. Raw evidence bodies and private read-context fields are not returned
in the trace. Retrieval, reader, or replay failures produce an abstention;
missing/invalid provider configuration is an explicit configuration error.

## Provider setup

Reflection creates a fresh provider per request using
`CommandGroundedProvider.from_environment()`. This reuses the existing command
or compact-reader configuration and preserves its model, artifact, prompt, and
protocol checks. It does not choose a provider automatically or loosen the
existing identity pins.

For the existing local command path, use a matching trusted installation of the
grounded runtime. The installer below requires a clean, committed checkout and
creates an immutable installation outside the repository; it does not download
the model:

```sh
.venv/bin/python infra/providers/install-grounded-runtime.py
```

Use the printed installation path's `bin` directory for the role commands and
configure the server process before launch:

| Environment variable | Required value for the command path |
| --- | --- |
| `MNEMOSYNE_QUERY_DECOMPOSER_PROVIDER` | `command` |
| `MNEMOSYNE_QUERY_DECOMPOSER_COMMAND` | Absolute path to the installed `bin/role-ladder` |
| `MNEMOSYNE_QUERY_DECOMPOSER_SELECTOR` | `SELECTOR` from `mnemosyne.providers.extractive_decomposer` |
| `MNEMOSYNE_QUERY_DECOMPOSER_CONTENT_SHA256` | `CONTENT_SHA256` from that same matching installed source |
| `MNEMOSYNE_GROUNDED_READER_PROVIDER` | `command` |
| `MNEMOSYNE_GROUNDED_READER_COMMAND` | Absolute path to the installed `bin/role-ladder` |
| `MNEMOSYNE_ROLE_LADDER_LOCAL_COMMAND` | Absolute path to the installed `bin/role-llm` |
| `MNEMOSYNE_GROUNDED_MODEL_SELECTOR` | `MODEL_SELECTOR` from `mnemosyne.providers.grounded_protocol` (currently `qwen3:8b`) |
| `MNEMOSYNE_GROUNDED_MODEL_CONTENT_SHA256` | `MODEL_CONTENT_SHA256` from that matching protocol |
| `OLLAMA_MODEL` | The same pinned model selector |
| `OLLAMA_URL` | The reachable Ollama base URL, for example `http://127.0.0.1:11434` |

The installed Ollama model must match the pinned digest. The
[`local-grounded-candidate.env`](../infra/profiles/local-grounded-candidate.env)
profile documents the existing command runtime and per-command timeout settings;
replace its installation placeholders and verify its source identity values
against the matching install. The compact-reader alternative continues to
require its full endpoint and artifact identity configuration, as validated by
[`grounded_reader.py`](../src/mnemosyne/providers/grounded_reader.py).

Applications embedding `MemoryTools` can inject a trusted
`grounded_provider_factory` instead. Each factory invocation must return a fresh
provider with `decompose(payload)`, `read(payload)`, and `disclosure`, using the
existing grounded protocol. For example:

```python
tools = MemoryTools(engine, grounded_provider_factory=build_my_grounded_provider)
result = tools.reflect(
    tenant_id="my-tenant",
    user_id="my-user",
    question="When does Ada's project launch?",
)
```

The factory is application configuration, not a tool argument. Commands run
without a shell and remain subject to the existing input, output, and timeout
bounds. Configured retrieval and reader providers may make network calls; this
feature does not imply that an external provider is free or local.

## Grounding and current limits

The fixed server-side limits are three hops, four queries per hop, twenty
evidence records, 24,000 evidence characters, and a 2,000-character question.
Provider commands have per-command timeouts; these limits do not impose one
overall wall-clock deadline for the complete request.
The same immutable authorization context applies to every retrieval. Evidence
is reauthorized and replayed before and after the reader; content or access
policy drift causes abstention. Retrieval does not record access reinforcement,
and generated answers are never written to the memory ledger. Existing provider
caches and service housekeeping retain their normal behavior.

The built-in command reader selects exact quotations. The orchestrator also
accepts provider proposals for deterministic `add`, `subtract`, `multiply`,
`divide`, and `compose_date` operations over authorized quoted values. Unsupported
operations, unknown CIDs, fabricated text, ambiguous synthesis quotes, or
invalid spans fail closed.

This is a grounded reflection surface, not full Hindsight feature parity.
Freeform advisory synthesis, personality-driven reasoning and automatic reflection
writeback are not added by this surface. The separate [mental-model lifecycle](mental-models.md)
can explicitly persist and refresh a private grounded answer; `reflect` remains ephemeral.
Exact-source validation proves citation membership and deterministic computation;
it does not prove that a chosen quotation semantically answers every question.
