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
The current structured adapter has no supported mapping for this corpus.
That is an unimplemented adapter path, not a measured zero or proof that the
underlying memory system cannot participate in a larger agent stack.

## Remaining acceptance work

- Implement and validate the public formation-response/inspection mapping and
  incremental runner, including isolated contexts and all responses retained.
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
