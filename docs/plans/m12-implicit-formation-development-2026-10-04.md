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
- Evaluate firing behavior, cancellation and recurrence after formation through
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
retained. Full state-equivalence scoring, downstream firing/sink evaluation,
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
