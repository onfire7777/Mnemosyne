# M12 natural-language formation corpus

Status: DEVELOPMENT corpus, not an executed or registered benchmark. This
advances the original M12 implicit-case requirement without changing the
explicit action workloads, production APIs, BurnOS contract or acceptance gates.

## Inputs and labels

`eval/public/action_implicit_plan.py` generates 220 independent conversations:
five seeds, four weekly start dates per seed and eleven scenarios per date.
The scenarios are exact time, future commitment, window, event, condition,
recurrence, missing timing, completed task, quotation, cancellation and
rescheduling. Dates and action wording vary deterministically. Offered action
order and scenario order are shuffled using a local seeded generator.

The public task asks the system to track prospective reminders and future
commitments using offered inert actions, ask about missing timing and avoid
creating reminders from quotations or completed tasks. This explicit task
definition makes the narrative commitment's intended treatment assessable;
it is not a claim that every bare future-tense statement should automatically
create a reminder in normal product use. Other conversational policies need
separately identified variants.

The public projection contains opaque case/action IDs, action descriptions,
UTC timezone, a task definition, available signal vocabulary and user turns
with virtual timestamps. It contains no expected trigger, disposition, scenario
name or seed label. `public_turn(case, index)` returns a detached conversation
prefix, preventing future cancellations or reschedules from appearing early.
Each case needs fresh tenant/session/storage state; cases that reuse an offered
action ID must not share memory.

Evaluator labels give each turn's disposition (`form`, `clarify`, `no_action`,
`cancel` or `reschedule`) and expected active schedules. Cancellation and
rescheduling are assessed after both turns, so merely inspecting the final
state cannot hide an incorrect initial response. A cancelled schedule has no
active schedule; historical cancellation records may still exist. Recurrence
uses three weekly occurrences. Windows are explicitly half-open; event and
condition eligibility starts at the stated UTC boundary.

`write_corpus` emits separate `public.jsonl` and `labels.jsonl` files and a
manifest binding their exact bytes and generator source hash. The manifest
states `candidate_execution: not-run`, `formation_adapter: required` and
`publishable: false`. File separation and Python projections are not a sandbox:
the future runner must prevent the candidate from accessing evaluator labels
and future turns, rather than mounting the whole fixture directory as input.

## Current public-interface boundary

The existing `ActionCLI` translates `task.create` payloads into public
`intention-schedule` calls with structured trigger, action and due-date fields.
It does not turn the natural-language conversations here into intentions.
The earlier PM-Bench/TriggerBench development adapter also supplies structured
tasks at introduction; that is not evidence of implicit formation.

Do not read these labels and call `task.create` on behalf of a candidate. A
future formation adapter must obtain its schedules from the actual system or
explicitly identified agent-plus-memory stack through public operations, retain
its raw responses and count that processing's time, resources and model cost.
The current structured adapter alone has no supported mapping for this corpus;
the development bridge below requires a separately configured formation provider.
That is an unvalidated provider path, not a measured zero or proof that the
underlying memory system cannot participate in a larger agent stack.

## Remaining acceptance work

- Validate the development response bridge and incremental runner below with
  an actual pinned formation provider, isolated contexts and retained responses.
- Run the implemented development timing diagnostic on actual provider outputs,
  evaluating firing behavior, cancellation and recurrence after formation through
  virtual observations and the same inert sink; formation labels alone cannot
  establish successful prospective action.
- Define scoring for clarification and semantic schedule equivalence before
  using candidate outcomes. Preserve per-scenario failures and ambiguous cases.
- Expand beyond these templates to dependency formation, more contextual and
  adversarial language, timezone variation, paraphrases and cross-turn ambiguity.
- Keep development, calibration and held-out instances distinct. These public
  fixtures are unsuitable as private held-out evidence.
- Complete the existing overload, reference-policy, calibration, licensed
  official-variant and resource-admission requirements. No ranking follows
  from a corpus generator or its tests.

## Reproduction

```sh
python -m eval.public.action_implicit_plan /new/absolute/output-directory
python -m pytest tests/test_action_implicit_plan.py -q -o addopts=''
```

Generation refuses an existing output directory. Tests verify deterministic
coverage, hand-checked boundary labels, evaluator-label separation, mutation
isolation, future-turn exclusion and byte-identical materialization. No model,
candidate system or external action is invoked by generation.

## Development response bridge and execution runner

`eval/public/action_formation.py` now provides a separate, opt-in command
transport and bridge. It does not reuse or change the preregistered grounded
reader protocol. `action_formation_run.py` drives the generated cases with
fresh public action adapters and local stores. Its provider is explicitly
configured; there is no default model, parser, gold lookup or synthetic fallback.

The provider command receives UTF-8 JSON on stdin. Requests have schema
`m12-formation-request/v1`, a `conversation` prefix, `current_tasks` obtained
from public inspection, `prior_responses` from earlier successful turns, and a
`response_contract`. No evaluator label, later user turn, store path or session
credential is included. The same executable may be called again for each turn;
the request contains the permitted history. Its model wrapper must implement
the following response protocol rather than assuming a generic chat response.

Responses are JSON objects with exactly `operations` and `clarification`.
`clarification` is null or a nonempty question; asking a question requires an
empty operation list. `operations` contains at most sixteen objects with
`command` and `payload`. Only `task.create` and `task.update` are allowed.
Creation accepts the existing public symbolic task fields: task/action IDs,
trigger, optional dependencies, recurrence and idempotency key. Updates accept
cancel, override or reschedule; keyed updates require the original public
revision. Action IDs must come from the offered inert actions. Dependencies
and update targets must identify tasks already known in the current case or
created earlier in the same batch. The bridge caps known tasks at 128.

The complete batch's command/field envelopes are checked before writes. The
public CLI remains responsible for trigger and mutation semantics. This is
not an atomic multi-command transaction: if a later command is rejected,
earlier successful mutations remain in that case and the log records both.
The bridge does not retry a failed model response or silently repair it.

Input and output limits are 256 KiB and 128 KiB. Commands execute as an argv
list without a shell, with a configured per-call timeout and the existing
bounded subprocess transport. Identity is caller-declared, not attested.
The program records raw stdout as base64 before parsing, including nonzero
exits and malformed UTF-8/JSON. Timeouts and transport-limit errors may have
no complete stdout available; they retain an error and failed attempt instead
of a fabricated response. Stderr is not copied into public artifacts.

The runner retains public inputs, provider configuration, source hashes and
flushed/fsynced operation records. Requests are logged before actions. Public
responses, elapsed call durations, model stdout, clarification and per-turn
task inspections are retained. Logging failure stops subsequent actions.
Runtime failures produce `status: failed` with completed-case and record counts;
a completed execution still has `scored: false` and `publishable: false`.

Example invocation, using an already configured provider program:

```sh
python -m eval.public.action_formation_run \
  --output /new/absolute/formation-attempt \
  --provider-identity pinned-provider-description \
  --timeout-seconds 30 -- /absolute/path/to/formation-provider
```

Provider argv is recorded, so configuration secrets belong outside command-line
arguments. Separate harness stores do not prove provider-side isolation. Local
commands are not filesystem-sandboxed, and repository fixtures are accessible
to same-user code: `filesystem_isolation_verified` remains false. Admission
requires a separately verified provider boundary and model/runtime custody.
No unchanged failed eight-billion-parameter reader probe is repeated here.

Validation currently uses explicitly identified scripted test doubles and real
public CLI calls, including revision-keyed cancellation. That proves plumbing,
not natural-language understanding. No real formation-provider run has been
retained. Broader state-equivalence policy, downstream firing scoring,
resource/cost capture, provider pinning and calibrated comparisons remain open.
The formation runner now calls the opt-in public `evidence.capture` seam before
each provider request. It captures the canonical conversation prefix through
the authenticated public CLI, records the returned CID and exact content hash,
and binds subsequent new intentions to that CID. Neither evaluator labels nor
future turns enter the captured content. Existing non-formation callers keep
their generic probe evidence and unchanged command responses.
Evidence capture is harness-controlled: the provider operation allowlist still
contains only `task.create` and `task.update`, never `evidence.capture`.

Within one adapter session, a recognized keyed creation retains its original
evidence CID across later captures. Reconstructing an adapter for a creation
retry still requires replaying the original evidence before the original keyed
request; the in-memory association is not a durable recovery mechanism. A
capture failure does not replace the prior binding, and the formation runner
stops rather than creating from stale evidence after that failure.

Updates and cancellations preserve the backend's original creation evidence;
their available source context is linked by the ordered per-turn evidence and
operation records. The current public mutation API has no replacement-evidence
argument. This change does not claim that mutation evidence is independently
bound inside each backend intention record or that provenance admission is
complete. Public-CLI regressions inspect the returned intention evidence IDs,
including a creation retry after a later source capture.


## Stored-state diagnostic

Formation now requests `task.inspect` with `include_schedule: true`. The adapter
returns a detached projection of the authenticated public `intention-list`
record: trigger, due time, dependencies, recurrence policy/state and evidence
IDs. The default inspection response remains unchanged. Both projections use
the same tenant, session, principal, revision and status checks.

`action_formation_scoring.py` compares these stored snapshots to the evaluator's
labels after each turn. It imports neither the product engine nor the provider
proposal/translator. Schedules are compared as multisets: a second distinct
intention with identical content is an extra schedule, not a deduplicated success.
Duplicate snapshot identities are rejected as malformed evidence instead.

Equivalent timezone spellings normalize to UTC. Other JSON values retain their
exact types, including nested booleans versus numbers. Nonrecurrence normalizes
the label's null to the public `type: none` policy. Differences in trigger
content, action, due time, recurrence or dependencies remain visible. This is a
versioned structural equivalence policy, not proof of all behavioral equivalences;
the previously documented nested-condition semantics question remains open.

The diagnostic reports per-turn true-positive/extra/missing active schedules,
exact active-state match, premature fired tasks, and occurrence advances. The
current corpus's turns precede their requested due times, so firing or advancing
recurrence during formation is a separate violation even if no active schedule
remains. Cancelled records may remain as history without counting as active.

Clarification expectation and observed question presence are separate fields.
No claim is made that a present question asks the right thing. State match is not
an overall correctness score and cannot offset premature firing or an inadequate
clarification. Missing turns, incomplete schedule inspection, wrong case IDs or
out-of-order snapshots fail rather than yielding fabricated zero scores.

The runner writes `formation-state.json` beside its execution log and identifies
it from the new `m12-formation-execution/v2` artifact. The existing `scored: false`
flag continues to mean that the full benchmark has not been scored; `scoring_scope`
explicitly identifies the descriptive active-state diagnostic. No confidence
interval, aggregate winner, acceptance floor or rank is produced. The complete
ordered trace is retained. A separate command now recomputes trace consistency,
while independent reproduction and provider custody remain required before admission. A scripted-provider integration check that only asks
questions correctly produces a missing intended schedule on the first turn.

No completed real-model benchmark is claimed. Independent reproduction, clarification quality,
broader semantic policy, cost, resource admission and calibrated comparisons
remain unfinished.


## Downstream observation and inert delivery

The formation runner now writes a fixed `observation-plan.json` before executing
providers, then observes the same public ActionCLI store after each conversation.
The version-one plan derives only from the public conversation origin, never gold
labels or candidate schedules. Twelve probes exercise early timing, a nonmatching
and matching delivery/condition signal, window expiry, rescheduled time, three
weekly occurrences and a fourth-week control. Overlapping conversation turns fail
rather than moving the virtual clock backward.

Every public probe request is retained before execution; responses and errors are
retained in `operations.jsonl`. Each observed firing is delivered to `sink.sqlite3`
and retried once through the existing scoped inert sink. `observations.json`
contains raw ticks and receipt snapshots. Execution schema v4 also produces
`formation-timing.json`, an evaluator-only diagnostic against the final labeled
schedule (or the cancelled original schedule). It requires every fixed probe,
retains misses, false alarms, duplicates, due-date drift and per-trigger timing,
and treats event/condition eligibility as the matching stimulus tick only.
Negative and ambiguous cases have no expected firings; extra outputs remain
false positives. Three recurrence occurrences are scored individually. No
model-quality result, admission or rank is implied. Independent reproduction remains open.
The first real-model attempt below failed before downstream execution. Tests use an
explicitly scripted command or manually created intention to validate plumbing.
The fixed schedule is specific to corpus v1 and must be revised together with any
change in that corpus's timing; it is not a general natural-language time parser.


## Saved-trace recomputation

`python -m eval.public.action_formation_replay /path/to/completed-run` checks a
complete current-version capture without invoking the recorded executable or
running the product engine. It requires the full frozen corpus and exact public
prefixes, replays successful raw provider outputs through the versioned protocol,
checks the ordered public-operation and observation trace, recomputes stored-state
and timing reports, and reconstructs inert deliveries in a temporary database.
The reconstructed receipt and attempt rows must match both the JSON snapshots
and the saved SQLite database. Every declared source-file hash must match the
replay checkout. The result binds all eleven input artifacts with SHA-256 hashes.
Input artifacts are snapshotted with file/total/record bounds and checked again
for changes before a successful return; the verifier never edits them.

This is internal consistency verification using the same protocol driver and
scorers, not an independent implementation or cryptographic execution proof.
It can reject inconsistent or incomplete edits; a coherently fabricated trace
cannot be authenticated by these checks. Wall durations are validated as bounded
numbers but not remeasured. The result explicitly leaves provider execution,
engine execution, independent implementation, ranking eligibility and publication
unverified/false. Failed and partial captures remain diagnostic evidence and are
not accepted as completed runs. Actual model measurement, independent custody,
clarification quality, broader semantics and calibration remain open.


## Opt-in local Ollama formation role

`eval.public.action_formation_ollama` implements the command protocol with an
explicit model selector and required server-reported digest. It checks the local
inventory before and after one nonstreaming chat request. It never downloads a
model, follows redirects, uses environment proxies or contacts a non-loopback
origin. Temperature/seed, context/output budgets, two CPU threads and immediate
unload are explicit. The complete public request is sent without truncation;
a conservative byte-based context guard rejects oversized inputs. That guard
is not exact tokenizer or template custody.

The role uses [Ollama's chat API](https://docs.ollama.com/api/chat) with JSON output,
thinking disabled and `keep_alive: 0`. The system prompt describes the public
operation contract, not any corpus answer. Per-invocation exclusive JSONL files
retain the prompt/source hashes, HTTP request bodies, exact raw responses,
server-reported token/timing fields and failure status. Provider content passes
unchanged to the formation bridge; invalid JSON is not repaired. Incomplete
responses or a changed model digest fail rather than producing a success.
The saved-trace verifier covers the formation trace and derived reports; these
additional HTTP evidence files are not yet independently authenticated or replayed.

Example provider command (use an installed model's actual 64-character digest):

```sh
python -m eval.public.action_formation_ollama \
  --model MODEL --digest SHA256 --evidence-dir /new/run/provider-http
```

This is an agent-plus-memory formation role for development, distinct from the
frozen grounded-reader model in existing registered protocols. Installing a
smaller model for local feasibility does not change those protocols. The
[Qwen3 0.6B package](https://ollama.com/library/qwen3:0.6b) is approximately 523 MB;
its resource and quality suitability must be measured, not inferred from size.
The outer Mac memory-pressure guard still applies. Its process-group RSS does
not include the separately running Ollama server or prove total model memory.


## Retained first local-model attempt

The [Qwen3 0.6B feasibility capture](../../eval/reports/m12-formation-feasibility-2026-10-04/README.md)
at clean source `88a56f24` attempted all 220 conversations in frozen order.
The model returned one response; the bridge rejected it for combining a
clarification question with a write. No task was created and no case completed.
Raw HTTP output, failed trace, monitor samples and cleanup are retained.
All three pressure samples were normal; this supports feasibility of that small
invocation only, not full-run resource admission or the prior 8B reader workload.

The next protocol-development step is schema-constrained decoding of the public
operation envelope, without inserting labels or repairing model answers.
Any changed provider variant must retain this initial failure and identify its
new settings. A full valid run, semantic accuracy, independent custody and all
original M12 admission/calibration requirements remain open.


## Schema-constrained development variant

The optional `--output-mode schema` provider flag now supplies a JSON Schema to
Ollama. Plain `json` remains available and is still the default, preserving the
first attempt's settings. The schema uses only public action IDs and the public
operation contract. It covers all five trigger shapes, interval recurrence,
cancel/override/reschedule and paired revision/idempotency fields. It separates
clarification-only responses from operations, preventing that structural error
without choosing a decision, timestamp or expected action on the model's behalf.

HTTP evidence records the chosen mode, exact schema in the request body and its
SHA-256 digest. Generated content is still returned unchanged and validated by
the bridge. Grammar-valid incorrect timing, unnecessary reminders or bad
clarification remain model errors; schema conformance is not memory quality.
Any run with this flag is a distinct development variant, not a repair of the
retained initial failure or a replacement for the frozen reader configuration.


## Retained schema-variant attempt and HTTP diagnostics

The [schema-variant capture](../../eval/reports/m12-formation-schema-attempt-2026-10-04/README.md)
from clean `dec91100` completed 21 of 220 cases before an HTTP error on the next
chat request. All 25 successful model responses asked for clarification and
scheduled no task. The completed prefix therefore missed 17 eligible
occurrences. This is not a full-corpus score or a measurement of the engine's
scheduling accuracy. Every completed prefix case is retained in partial state
and timing diagnostics; the completed-run verifier does not certify this failed
capture as a complete run. The original plain-JSON failure remains separate.

All 161 pressure samples were normal, and cleanup found no loaded model.
The old wrapper retained only the HTTP error class; its status/body and cause
are unknown. Subsequent source now records the HTTP status and up to 2 MiB of
error body, explicitly marking truncation, without retrying or inventing model
output. This diagnostic change does not retroactively fill the earlier gap.
Full completion, reliable formation quality, independent custody and the
original acceptance/calibration gates remain open.

## Explicit wire-order variants

The provider now exposes `--wire-order canonical|declared`. Canonical remains
the default and preserves the earlier alphabetically sorted HTTP JSON encoding.
Declared order preserves schema property insertion order, placing `operations`
before `clarification`. JSON objects are logically unordered, but the
[upstream grammar tests](https://github.com/ggml-org/llama.cpp/blob/master/tests/test-json-schema-to-grammar.cpp)
show that property order can affect constrained output order. Whether this
explains the observed over-clarification must be measured, not assumed.

Each HTTP request record now retains its exact body bytes as base64 plus a
SHA-256 digest, alongside the parsed body. This prevents canonical log encoding
from concealing a wire-order difference. Both modes send the same public input
and schema meaning. No labels, expected decisions or answer repair are added.


The [four-cell wire-order diagnostic](../../eval/reports/m12-formation-wire-diagnostic-2026-10-04/README.md)
now tests that hypothesis on one fixed public input. Both Qwen3 0.6B and 1.7B
asked for clarification under canonical order and proposed an exact-time task
under declared order. The input required an event condition, so neither proposal
was correct. This establishes sensitivity on that input, not general causality
or a completed benchmark. Earlier over-clarification is a result of the tested
model-plus-adapter configuration, not evidence about model capability alone.
The same failed HTTP input succeeded on a single diagnostic repeat; the earlier
HTTP error's cause remains unknown. All variants and failures remain retained.


## Failed-attempt coverage accounting

`python -m eval.public.action_formation_failure CAPTURE/workload` now emits
all 220 planned cases, with completed, incomplete and not-attempted states.
It recomputes state/timing diagnostics only for the completed prefix and checks
frozen public inputs, diagnostic-source hashes, trace ordering, retained record
counts and all observation probes. Inputs are bounded and checked for changes
during analysis. It does not replay the full protocol or attest execution.

Applied to the retained initial attempt, this reports 0 completed, 1 incomplete
and 219 not attempted. The schema variant reports 21 completed, 1 incomplete
and 198 not attempted, retaining the 17 missed eligible occurrences in the
completed prefix. Neither report supplies a full-corpus score or permits ranking.
This makes missing evidence explicit without treating unattempted cases as
observed model failures or hiding failures behind a completed-case denominator.
