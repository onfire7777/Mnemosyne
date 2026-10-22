# Saved mental models

A mental model is a private saved question and its current grounded answer. It
uses the [reflection provider and grounding protocol](reflect.md#provider-setup)
and stores the result separately from factual memory. Creating a model records
the question with `status: pending`; it does not call a provider. Refresh can be
requested explicitly or enabled per model through an interval schedule and a
separately started worker.

## CLI workflow

Use the same store, tenant, user, branch, and read scope for every operation:

```sh
mneme --store ./memory.json mental-model create \
  --tenant my-tenant --user my-user \
  --name "Zephyr launch" --question "When does project Zephyr launch?"
```

Copy the returned `model_id`. After configuring the grounded providers, refresh
it, then read the saved result:

```sh
mneme --store ./memory.json mental-model refresh \
  --tenant my-tenant --user my-user --model-id MODEL_ID

mneme --store ./memory.json mental-model get \
  --tenant my-tenant --user my-user --model-id MODEL_ID

mneme --store ./memory.json mental-model list \
  --tenant my-tenant --user my-user
```

`get` and `list` check current authorized sources without inference or embedding
calls. Stale or invalid answers are withheld. `get --refresh-if-stale` explicitly
allows regeneration for pending, stale, or errored models. `refresh` reuses a
still-current ready or abstained result; `refresh --force` attempts regeneration
even when it is current. If forced regeneration fails or abstains, a previous
successful answer survives only if it still passes current scope, source, and
claim checks. The response then includes a `refresh_error` code.

| Subcommand | Additional arguments |
| --- | --- |
| `create` | Required `--name`, `--question` |
| `get` | Required `--model-id`; optional `--refresh-if-stale` |
| `list` | None |
| `refresh` | Required `--model-id`; optional `--force` |
| `update` | Required `--model-id`; optional `--name`, `--question`, `--expected-version` |
| `schedule` | Required `--model-id`; optional `--interval-seconds` (default `300`), `--disable`, `--expected-version` |
| `delete` | Required `--model-id`; optional `--expected-version` |
| `history` | Required `--model-id` |

Every subcommand requires `--tenant` and `--user`. Common scope flags are
`--branch` (default `main`), `--role` (default `agent`),
`--source-trust-tier`, `--max-trust-tier`, `--max-sensitivity`, repeated
`--capability-tag`, `--purpose`, and `--lawful-basis`, plus `--residency`,
`--region`, and `--as-of`. Persistent models reject `--break-glass`.

Updating a question clears its answer and returns it to pending. Updating a name
does not regenerate its answer. Supply the last returned positive `version` as
`--expected-version` on update, schedule, or delete to reject an intervening change. Even
when this option is omitted, storage compares the version loaded by the service
before writing. Concurrent refresh or edit conflicts do not overwrite the newer
record. Manual refresh, edits, schedule changes, and deletion also invalidate
any outstanding worker claim.

## Opt-in scheduled refresh

Scheduling records a durable freshness-check interval; it does not start a
worker or call a provider. Intervals must be integers from `60` to `604800`
seconds (one minute to seven days). Enabling or replacing a schedule makes its
first check due immediately and resets its retry state. Existing models remain
unscheduled until explicitly enabled.

The standalone worker supports SQLite and PostgreSQL. For SQLite, `--store` is
a directory containing per-tenant databases. Create the model in that same
backend and directory, then schedule the returned ID:

```sh
mneme --backend sqlite --store ./memory-db mental-model create \
  --tenant my-tenant --user my-user \
  --name "Zephyr launch" --question "When does project Zephyr launch?"

mneme --backend sqlite --store ./memory-db mental-model schedule \
  --tenant my-tenant --user my-user --model-id MODEL_ID \
  --interval-seconds 300

mneme --backend sqlite --store ./memory-db mental-model-worker \
  --tenant my-tenant --user my-user --limit 10 --once
```

Omit `--once` to keep polling until interrupted. For PostgreSQL, replace the
global SQLite options with `--backend postgres --postgres-dsn "$MNEMOSYNE_POSTGRES_DSN"`,
or set `MNEMOSYNE_POSTGRES_DSN` and omit `--postgres-dsn`. Use the model's exact
scope flags for both scheduling and worker commands. To disable a schedule:

```sh
mneme --backend sqlite --store ./memory-db mental-model schedule \
  --tenant my-tenant --user my-user --model-id MODEL_ID --disable
```

| Worker option | Default | Meaning |
| --- | --- | --- |
| `--limit` | `10` | At most 1–100 due models processed per cycle |
| `--lease-seconds` | `300` | Claim duration, 30–3600 seconds |
| `--poll-interval` | `5` | Seconds between cycles, 1–300 |
| `--check-changes` | Off | Check for source/clock changes before the next scheduled interval; early refreshes are spaced at least 60 seconds apart |
| `--max-cycles` | `0` | Stop after this many cycles; zero runs until stopped |
| `--once` | Off | Run one cycle and exit, overriding `--max-cycles` |

Each cycle emits counts and per-model outcomes, including `refreshed`,
`unchanged`, `abstained`, `retry`, and `lost`. `change_check_failed` counts failed
shared freshness scans; early refresh candidates are skipped for that cycle.
Model reads expose
`refresh_schedule`, including the next due time, failure count, last outcome,
and whether an unexpired claim exists; claim tokens are not exposed.

An unchanged, valid answer or legitimate abstention is reused without provider
calls. Assembly, reader, replay, or invalid-proposal failures are operational
errors and remain retryable. Retries use the interval as their initial delay,
capped at 3600 seconds, then double up to that same cap. Successful checks reset
the failure count and schedule the next check one interval after completion.
Due times, claims, and retry state survive worker restarts.

Enable `--check-changes` when saved answers should react sooner to new facts,
corrections, deletion, or access-policy changes. The worker takes one shared
authorized-corpus snapshot per eligible polling cycle and compares it with the
saved answers. It processes normally due work first and can then refresh stale
models before their interval expires. The existing batch limit still applies.
Early attempts require at least 60 seconds since that model's last start and finish;
active leases and retry backoff are respected. Unchanged models never load a
provider. This is opt-in polling, not an event subscription or incremental
synthesis, and the snapshot cost grows with the readable corpus.

```sh
mneme --backend sqlite --store ./memory-db mental-model-worker \
  --tenant my-tenant --user my-user --check-changes --poll-interval 5
```

Versioned, expiring claims prevent competing workers from publishing the same
claim. A worker that loses or outlives its claim cannot publish or complete it.
An expired worker's provider call may still be running when a successor starts,
so inference can overlap. Provider work stays outside storage transactions.

Workers are bound to one explicitly supplied owner and exact read scope; they
do not obtain authority from saved records. The CLI revalidates signed-session
credentials and write authorization before attempts and publication. Revoked
or expired authority stops work. The MCP server does not automatically start a
worker. Scheduling accepts intervals, not cron expressions, and does not add
consolidation-triggered refresh.

## MCP and Python

The MCP tools and `MemoryTools` methods are `mental_model_create`,
`mental_model_get`, `mental_model_list`, `mental_model_refresh`,
`mental_model_update`, `mental_model_schedule`, `mental_model_delete`, and
`mental_model_history`.
They accept the corresponding underscore-named arguments, including
`tenant_id`, `user_id`, `model_id`, `refresh_if_stale`, and `expected_version`.
For example:

```json
{
  "name": "mental_model_create",
  "arguments": {
    "tenant_id": "my-tenant",
    "user_id": "my-user",
    "name": "Zephyr launch",
    "question": "When does project Zephyr launch?"
  }
}
```

Embedded applications can use `MentalModelService(engine, provider_factory=...)`
with an `AnswerReadContext`, or inject `grounded_provider_factory` into
`MemoryTools` as described in [reflection](reflect.md#provider-setup). Provider
configuration is server-side, never a model tool argument. The configured
providers retain their normal network, runtime, and cost requirements.

`mental_model_schedule` accepts `model_id`, `interval_seconds` (default `300`),
`enabled` (default `true`), and optional `expected_version`, alongside the common
scope arguments. It only changes the schedule. Embedded applications can run
`MentalModelRefreshWorker(service, context, max_batch=10, lease_seconds=300, check_changes=True)`
from `mnemosyne.mental_model_refresh` and call `run_once()`. Supply a trusted
`AnswerReadContext`; when external credentials need revalidation, supply both
an `authorize` callback and a side-effect-free `validate_authority` callback.
The latter also runs inside publication transactions. Omit `check_changes` for
interval-only behavior. A Local engine supports only an in-process worker sharing that
same engine instance; the standalone worker rejects Local JSON storage.

## Scope, freshness, and retention

Models bind to their creator, tenant, branch, and exact normalized read scope.
Capability tags, purposes, and lawful bases are compared as sorted unique sets.
Other scope changes, including a different role or `as_of`, are rejected on
direct reads; lists include only matching models. Signed MCP sessions bind the
tenant, user, role, and source trust as on other authenticated tools. Mutation
and requested refresh require write authorization.

Freshness scans and fingerprints the authorized branch's evidence, assertions,
relations, preferences, and policy, excluding read telemetry. Its cost grows with
that corpus; incremental change tracking is not yet implemented. New facts and corrections can
invalidate an answer even when its old citations remain. Before returning a
ready answer, the service revalidates exact citation spans, hashes, claim text,
and supported deterministic derivations. A stale read hides the answer rather
than silently refreshing it.

Parsed relative day windows also invalidate when their boundaries change,
without requiring a memory write. Continuously moving questions such as
“this week,” “now,” or “currently” require an explicit timezone-aware
`--as-of`, for example `2026-10-22T12:00:00-07:00` (`as_of` in MCP/Python).
That timestamp becomes part of the saved scope and must be repeated on later
operations. This surface has no separate `--query-timezone` option.

History retains at most 32 revision entries containing timestamps, versions,
events, status, source counts, and answer hashes. It contains no historical
answer prose, questions, or source excerpts. Deleting a model removes its
record and revision history. Source erasure conservatively clears saved answers
for models in the affected tenant and branch, marks them stale, and advances
their versions. Discarding a branch purges its models.

Models never become evidence or search candidates and are omitted from scoped
exports. Raw administrative exports and backups include model records and must
be governed accordingly; deleting a live record does not rewrite existing
external backups.

## Storage and current limits

Local, SQLite, and PostgreSQL storage provide versioned model records. SQLite
uses one `BEGIN IMMEDIATE` transaction for the final source snapshot, model
write, and final fresh view, excluding competing source writers during
publication. Local storage uses its engine instance's lock. Provider work runs
outside those guards. PostgreSQL pins one tenant-bound connection for final
source validation, the versioned write, and the final fresh view. Its publication
transaction uses `READ COMMITTED` and `SHARE` locks on `tenants`, `branches`,
`evidence`, `assertions`, `relations`, and `preferences`, with a five-second lock
timeout. These table locks also block relevant source writes across other
tenants while publication completes; this is a correctness-versus-throughput
tradeoff. Live PostgreSQL 16.15 tests now cover competing source insertion,
deletion and privacy changes, lease takeover/expiry, rollback, owner and tenant
isolation, readonly denial, and actual five-second lock timeout/recovery.
The [validation report](../work/hindsight-comparison/postgres-live/REPORT.md)
records **239 mixed live/unit tests passed**, including **20 live tests**,
with zero skips/failures and **9/9 live role checks**. Providers were deterministic
fixtures; lease expiry used a controlled clock with real database sessions.
Production load, remote deployments and other PostgreSQL versions were not tested.

Existing PostgreSQL deployments need the updated [schema](../sql/schema.sql)
and the narrow `mental_models` DELETE grant in [roles.sql](../infra/postgres/roles.sql).
That grant fixes owner-authorized model deletion and the branch foreign-key
cascade. Model service ownership checks still apply; app DELETE on evidence,
branches and audit rows remains denied. Apply the equivalent grant through the
deployment's migration process rather than rerunning role creation.

Refresh uses reflection's bounded orchestrator and exact quotations or supported
deterministic calculations. Citation validity does not guarantee that a chosen
quotation answers the question well. Interval workers perform the same full
freshness checks and bounded regeneration as explicit refresh. Incremental
delta synthesis, wiki generation, and freeform model synthesis are not
implemented. This feature makes no comparative ranking claim; the separate
[controlled comparison protocol](comparison-protocol.md) requires completed
run receipts before reporting benchmark results.
