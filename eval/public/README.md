# Public evaluation harness

Run the redistributable development self-test with `uv run --locked mneme
eval-public --suite smoke --out-dir /tmp/mneme-smoke`, then verify it with
`uv run --locked mneme eval-public --verify-bundle /tmp/mneme-smoke`.

The smoke suite exercises Mnemosyne exclusively through public CLI subprocesses.
It is permanently non-publishable, ineligible for PBPP headlines, and is not an
independent external reproduction. Retrieval proportions use Wilson intervals;
future answer-quality tracks must name their reader/judge and use bootstrap
intervals. Families are never aggregated.

## Deterministic action development suites

The live registry exposes three repository-authored, non-publishable action
profiles, and all three run through the authenticated public CLI subprocess
seam. Each mints a per-scope signed session token and presents it through the
production `--session-token` seam so every write and evaluation is verified and
scoped by the engine. Run any of them, then verify and reproduce its
byte-identical bundle:

```
uv run --locked mneme eval-public --suite pm-bench-development --out-dir /tmp/mneme-pm-bench
uv run --locked mneme eval-public --suite triggerbench-development --out-dir /tmp/mneme-triggerbench
uv run --locked mneme eval-public --suite working-memory-action-development --out-dir /tmp/mneme-working-action
uv run --locked mneme eval-public --verify-bundle /tmp/mneme-pm-bench
uv run --locked mneme eval-public --reproduce-bundle /tmp/mneme-pm-bench --out-dir /tmp/mneme-pm-bench-reproduced
```

`pm-bench-development` and `triggerbench-development` translate their
repository-authored fixtures into authenticated `intention-schedule`,
`intention-update`, `intention-cancel`, and `intention-evaluate` subprocess
commands, and route the fixtures' time, event, and condition observations
through the production evaluator's `intention-evaluate` arguments. Selection is
the evaluator-side intersection of the production evaluator's fired data-only
action IDs with the available opaque IDs; the harness never executes or exposes
an action payload or fixture gold, and it fails closed on missing auth, scope
mismatch, gold leakage, payload execution, or unsupported semantics.
`working-memory-action-development` drives the authenticated
`capture`/`working-seed`/`working-query`/`working-expire` commands under the
same signed-session seam.

Every profile produces a deterministic development bundle with its exact
operating point, action traces, null reader/judge fields, registry revision and
dataset digest, and false publication/headline flags. None is an official
PM-Bench, TriggerBench, or Working Memory reproduction.

This is deterministic synthetic/development eval only: no official
dataset/model download, no benchmark run against protected/upstream data, and no
publication or headline claim. The authenticated action lane descends from A1
`t_5163502e` → P5 `t_8c72180a` → I0R `t_63a207ee`; downstream R1/R2/F0 remain
future work.

## Frozen Phase 12 QA protocol

The `_qa_protocol` registry entry preregisters the deterministic
`mnemosyne-extractive-hop0-v1` decomposer separately from the static
`qwen3:8b` Ollama reader selector, exact reader decoding options, evidence and
hop budgets, canonical empty-answer abstention, `qa-em-f1-v1`, frozen split
roles, zero transport retries,
and a single held-out attempt. A post-commit candidate manifest is external,
no-overwrite, and must bind the exact git SHA plus decomposer, resolved reader
model-content, decomposer-spec, decomposer-implementation, prompt-template,
evidence-serializer, decoding, and protocol digests before a frozen run. The
registry deliberately contains no self-referential git SHA or implementation
digest; those are bound in the external post-commit manifest.

`qa-smoke` is only a redistributable schema-and-custody self-test. It constructs
a fixed prediction and exact disclosures without executing the grounded role
runtime, so it is not runtime or answer-quality evidence.

Phase 11 point metrics and generated report/manifest digests are frozen in that
entry. QA bundles are separate from retrieval bundles, disclose reader custody
in `judge.json`, carry benchmark-owned answer labels only for scorer
recomputation, and require cited atomic claims or canonical abstention. The
held-out LongMemEval and HippoRAG splits are never development inputs.

QA bundle verification is intentionally exact-checkout scoped: the embedded
candidate manifest, QA-only `build.json`, reader custody, and current checkout
must all name the same 40-hex commit. Reproduction reuses the retained canonical
`candidate-manifest.json`; verifying from another commit fails closed instead
of silently treating different code as the frozen candidate.

## Whole-memory common ABI (development draft)

The `wmbs/0.1-draft` compound schema and standard-library reference validator
live at
[`schema/wmbs-0.1-draft.schema.json`](schema/wmbs-0.1-draft.schema.json) and
[`adapters/whole_memory_reference.py`](adapters/whole_memory_reference.py).
They define the closed development-only lifecycle
`negotiate → create_run → ingest/retrieve/answer → finalize`; finalization is
terminal.

`finalize.reason` is closed to `completed` or `cancelled`. A successful
`cancelled` finalization is terminal and uses identical idempotent request and
response replay. Closed errors and negative finalize receipts leave the attempt
active.

The adapter exports `canonical_json`, `canonical_sha256`,
`canonical_artifact_sha256`, `canonical_projection`, `validate_definition`,
`validate_evidence_bundle`, and `ProtocolValidator`.
Canonical JSON is sorted, compact UTF-8 with one trailing newline. Validation
requires canonical UTC deadlines, one stable tenant/run/attempt scope,
monotonically increasing sequences, unique request IDs, and identical content
for idempotent replay. Canonical Python mappings require string keys, and schema
constants preserve JSON type distinctions such as `true` versus `1`.
`ProtocolValidator.validate_response` binds receipts to
accepted requests, freezes the first closed response for idempotent replay, and
commits lifecycle transitions only after successful responses. Closed error
responses and negative create/finalize receipts preserve the prior phase;
retries use a fresh request ID and idempotency key. Response binding also
enforces exact ingest event order, receipt scope, retrieval `top_k`, and forced
answer behavior. Finalize is rejected while any accepted active request still
awaits its first frozen response.
`WholeMemoryValidationError.code` carries one of the closed protocol error
codes.

The specification's `?` fields may be omitted or explicitly null. Portable
events require `valid_to`, when both interval endpoints exist, to be no earlier
than `valid_from`.
Retrieval hits use contiguous ranks `1..N` in response order and unique
`stable_item_id` values. Accepted and deduplicated ingest statuses must be
acknowledged and error-free; rejected statuses must be unacknowledged, carry an
error, and omit an evidence handle.

The protocol version remains `wmbs/0.1-draft`; the compound JSON Schema uses
the absolute ID `urn:wmbs:0.1-draft`. Its public evidence IDs are:
`urn:wmbs:0.1-draft#BaselineManifest`,
`urn:wmbs:0.1-draft#PowerPlan`,
`urn:wmbs:0.1-draft#SoftwareDataBOM`,
`urn:wmbs:0.1-draft#SandboxReceipt`,
`urn:wmbs:0.1-draft#ResourceReceipt`, and
`urn:wmbs:0.1-draft#FeasibilityRecord`.
Each evidence artifact's `artifact_sha256` is the canonical SHA-256 of that
artifact with the `artifact_sha256` field omitted. `validate_definition`
checks this self-digest. A `PROPOSED` feasibility record keeps all fourteen
categories present but uses `null` for at least one absent artifact.
Readiness labels are accepted only by `validate_evidence_bundle`, which
resolves every non-null digest reference against supplied content and requires
a completed resource receipt.

`SandboxReceipt` records the digest-bound profile, environment allowlist,
syscall policy, UID/GID, mounts, locale/timezone, cleanup and log-redaction
policy, resource limits, scorer/model isolation, and a default-deny or metered
endpoint/DNS/IP/protocol allowlist. Cloud metadata and private ranges remain
blocked in both egress modes.

M15 replay freezes canonical payload `m15-v1`, exactly five runs, and required
clean-process replay. Canonical projection excludes only `path`,
`rss_samples_bytes`, `runtime_timestamp_utc`, `signature`, and `wall_time_ms`.

The in-memory validator admits at most 10,000 requests, 16 MiB per request or
response, 64 levels of JSON nesting, and 64 MiB of retained canonical request
bytes. It performs no persistence, network, model, benchmark, ranking, or publication
work. Run its contract suite with:

```bash
uv run --locked python -m pytest tests/test_public_whole_memory_reference.py -q
```
