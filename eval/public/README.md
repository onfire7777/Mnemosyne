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

The M12 fixtures are deliberately small: `pm-bench-development` has one seed
(`7`), one case, five tasks, and seven steps; `triggerbench-development` has
one seed (`7`), twenty one-step cases, and no calibrated baseline. Recurrence
is represented in fixture metadata but is not forwarded as production
recurrence plumbing. Lateness is scored only as a binary `late` safety counter,
which is zero on both committed fixtures because they are easy rather than
because the counter is inert; neither suite measures lateness magnitude or
cost.

The M13 working-memory fixture has one seed (`94125`) and six cases, one for
each declared item category. Its operating point has no capacity parameter,
and the fixture contains no promotion-versus-no-promotion control. These are
development gap disclosures, not evidence of capacity scaling or promotion
utility.

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

The M01 capture/durability and M10 calibration/abstention reference cores also
run through the common bundle custody path:

```bash
uv run --locked mneme eval-public --suite wmbs-m01-development --out-dir /tmp/wmbs-m01
uv run --locked mneme eval-public --verify-bundle /tmp/wmbs-m01
uv run --locked mneme eval-public --suite wmbs-m10-development --out-dir /tmp/wmbs-m10
uv run --locked mneme eval-public --verify-bundle /tmp/wmbs-m10
```

Both suites remain `PROPOSED`, `ENHANCED-SUCCESSOR`, development-only reference
runs. They exercise harness-owned deterministic cores rather than a real SUT,
remain non-publishable and non-comparable to upstream tracks, and support no
benchmark superiority claim.

The M03 valid-time cell runs through the same bundle custody path, but over the
public CLI subprocess seam rather than a harness-owned core:

```bash
uv run --locked mneme eval-public --suite wmbs-m03-valid-time-development --out-dir /tmp/wmbs-m03
uv run --locked mneme eval-public --verify-bundle /tmp/wmbs-m03
```

`wmbs-m03-valid-time-development` is `PROPOSED`, `DEVELOPMENT`,
`split_role: development`, and carries `publishable: false`,
`pbpp_headline_eligible: false`, `headline_eligible: false`,
`upstream_comparable: false`, and
`independent_external_reproduction: false`. Its registration is a reachability
fix only — it advances no admission state and supports no publication,
comparability, or superiority claim.

The cell covers **valid-time only**. Full bitemporal transaction-time query
semantics stay a hard deferral: the fixture itself declares
`transaction_time.supported: false`, because transaction-time is system-owned
and not exposed by this development cell. Scored coverage is the five canonical
timelines (`ordered-events`, `late-event`, `retroactive-correction`,
`exact-boundary`, `tied-valid-time`) across the five canonical seeds
`[11, 23, 37, 53, 71]`.

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
awaits its first frozen response. A first response must arrive before the
request deadline; an already-frozen identical response remains replayable after
that deadline.
`WholeMemoryValidationError.code` carries one of the closed protocol error
codes.

The specification's `?` fields may be omitted or explicitly null. Portable
events require `valid_to`, when both interval endpoints exist, to be no earlier
than `valid_from`, and `content_sha256` is SHA-256 over the event content's
UTF-8 bytes.
Retrieval hits use contiguous ranks `1..N` in response order and unique
`stable_item_id` values. Accepted and deduplicated ingest statuses must be
acknowledged and error-free; rejected statuses must be unacknowledged, carry an
error, and omit an evidence handle.

The protocol version remains `wmbs/0.1-draft`; the compound JSON Schema uses
the absolute ID `urn:wmbs:0.1-draft`. Its public evidence IDs are:
`urn:wmbs:0.1-draft#AdapterContract`,
`urn:wmbs:0.1-draft#DataSourceContract`,
`urn:wmbs:0.1-draft#ScorerContract`,
`urn:wmbs:0.1-draft#BaselineManifest`,
`urn:wmbs:0.1-draft#PowerPlan`,
`urn:wmbs:0.1-draft#SoftwareDataBOM`,
`urn:wmbs:0.1-draft#SandboxReceipt`,
`urn:wmbs:0.1-draft#ResourceReceipt`,
`urn:wmbs:0.1-draft#SmokeReceipt`, and
`urn:wmbs:0.1-draft#FeasibilityRecord`.
Each evidence artifact's `artifact_sha256` is the canonical SHA-256 of that
artifact with the `artifact_sha256` field omitted. `validate_definition`
checks this self-digest. A `PROPOSED` feasibility record keeps all fourteen
categories present but uses `null` for at least one absent artifact.
Readiness labels are accepted only by `validate_evidence_bundle`, which
resolves every required top-level and nested digest reference against supplied
content. `CONTRACT-READY` binds the loaded ABI schema plus the referenced data,
scorer, baseline, sandbox-profile, and supply-chain artifacts, but requires no
resource receipt.
`PILOT-READY-DEV` additionally requires a finalized attempt, a completed
resource receipt for the same SUT boundary, and content-bound offline L16-DEV
sandbox controls. The pinned L16-DEV profile requires a 16 GiB Apple Silicon
macOS host, and measured wall time, peak RSS, disk use, and worker count must
remain within its declared ceilings. Its passing `SmokeReceipt` binds the exact
module identity, sandbox receipt, resource receipt, and supplied result
artifact. Result-v1 smoke evidence is limited to 1,000 metrics before the
legacy validator runs.
`RUN-READY-*` remains rejected until profile-specific signed evidence exists.

`SandboxReceipt` records the digest-bound profile, environment allowlist,
syscall policy, UID/GID, mounts, locale/timezone, cleanup and log-redaction
policy, resource limits, scorer/model isolation, and a default-deny or metered
endpoint/DNS/IP/protocol allowlist. Cloud metadata and private ranges remain
blocked in both egress modes; allowlisted CIDRs must be valid and globally
routable.

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

### M02/M04/M05 Stage-A development oracles (unregistered)

`wmbs_m02.py`, `wmbs_m04.py`, and `wmbs_m05.py` are Stage-A development oracles.
Each runs no system and observes no SUT: the module generates a deterministic
synthetic fixture and scores harness-supplied observations, so a green run
evidences generator and scorer determinism over that exact finite fixture and
nothing whatsoever about any memory system.

All three are **unregistered**. None has a `registry.json` entry, an adapter, a
runner route, or a scoring-profile registration, so none can be selected with
`mneme eval-public --suite`, none produces a bundle, and none produces a
benchmark result. Every one of them is admission state `PROPOSED`: M02 and M04
declare `ADMISSION_STATE = "PROPOSED"` directly, and M05 carries
`admission_state: "PROPOSED"` in both its labels and its committed fixture. M04's
score envelope and M05's labels and fixture record `publishable: false` and
`pbpp_headline_eligible: false`; M02 emits no publication or headline field at
all and makes no publication claim. M02 and M05 declare `license: "CC0-1.0"`;
M04 declares no license field at all, which is itself a disclosed Stage-A gap
rather than a permissive grant.

None of the three measures cost or resources. M02's scorer reports `latency`,
`tokens`, `calls`, and `storage` literally as `unsupported`; M04 and M05 emit no
latency, token, call, or storage metric of any kind. Treat all four classes as
unsupported for every one of these modules.

**M02 (`wmbs-m02-retrieval-development`).** The committed fixture is generated
from seed `20260801` and holds 240 documents and 60 questions — ten per query
family across `exact`, `paraphrase`, `entity`, `relation`, `multi-hop`, and
`unanswerable`. The specification names a 2,000-event local corpus; Stage A
commits 240 documents and defers the 2,000-event variant behind a measured
resource receipt, so the committed corpus scale is a disclosed deferral rather
than a scaled-down result. Its metrics are descriptive over that finite corpus
only.

**M04 (`wmbs-m04-development`).** The committed fixture is generated from seed
`20260801` and holds 140 cases over five per-case seeds (`11`, `23`, `37`, `53`,
`71`), three orderings (`as_authored`, `reversed`, `interleaved`), and seven
source classes (`independent`, `duplicated`, `low_quality`, `high_quality`,
`malicious`, `unresolved`, `later_resolved`). Numeric confidence calibration is
`unsupported`: the unresolved-calibration metric scores only abstention
behavior. Its declared disclosures also record `branch_merge` as
`UNSUPPORTED-BY-SYSTEM`, `transaction_time` as `unsupported`, `update_hook` as
`emulated`, and the `sqlite` and `postgresql` backends as `DEFERRED`. M04's
fixture events deliberately depart from the closed `portable_event` ABI: they
reuse the portable-event key vocabulary but carry an additional load-bearing
`source_id` that keys the ablation gold. That reuse is a shape-vocabulary
borrowing for a Stage-A ablation task and is never an ABI conformance claim.

**M05 (`wmbs-m05-provenance-development`).** The committed fixture is generated
from seed `13`, declares the five seeds `13`, `29`, `41`, `59`, `73`, and holds
five slices of twenty cases each (`protected-grounding`, `distractor-sources`,
`tampered-lineage`, `unsupported-claim`, `derived-claims`). The module declares
three retrieval stage IDs (`dense_hash`, `lexical`, `graph_ppr`), but every
committed case freezes `lexical` alone: the other two stages are declared
vocabulary, not exercised evidence. It scores **one-hop**
claim-to-source grounding only; derived-claim lineage, explanation
faithfulness, promoted-item slices, and `query_with_evidence` are all recorded
as deferred rather than measured. Its source manifest is content-addressed but
explicitly **unsigned** (`signed: false`, signing deferred behind the protected
lease), and it names eight unresolved integration dependencies in
`INTEGRATION_DEPENDENCIES` — Q1 `query_with_evidence` absent from the frozen
ABI, Q2 scorer-enforced rather than schema-proven grounding, Q3 self-declared
and ignored `provenance_status`, Q4 evidence handles not digest-bound, Q7 replay
hashes needing real artifact binding, Q9 model-backed grounded answering, Q10
unwired `HowProvenance`, and Q12 missing artifacts failing rather than skipping.

Stage B — harness integration for all three modules — is **not delivered**. It
remains gated on the public-harness integration owner's lease and on the
quarantines named in
[`docs/plans/wmb-m02-retrieval-organization-implementation-plan.md`](../../docs/plans/wmb-m02-retrieval-organization-implementation-plan.md),
[`docs/plans/wmb-m04-conflict-correction-implementation-plan.md`](../../docs/plans/wmb-m04-conflict-correction-implementation-plan.md),
and
[`docs/plans/wmb-m05-provenance-explanation-implementation-plan.md`](../../docs/plans/wmb-m05-provenance-explanation-implementation-plan.md).
Nothing here is a publication, comparability, ranking, superiority, or
upstream-equivalence claim.
