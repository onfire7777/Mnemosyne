# M12 exact-time diagnostic protocol

Status: development implementation, not registered benchmark admission.
This closes part of the lateness-observability gap while preserving the
existing PM-Bench/TriggerBench fixtures, scoring rules and results.

## Observable interface

`ActionCLI.run("intention.observe", scope, observations)` performs the same
authenticated public `intention-evaluate` call as `intention.query`. It does
not perform a second evaluation. The existing query response is unchanged.
The opt-in response adds:

- `evaluated_at`: the harness-requested virtual clock;
- `evaluation_wall_ms`: the public subprocess invocation's measured wall
  duration, including process startup and CLI/storage overhead;
- `firing_observations`: one row for **every** returned firing, including
  duplicate observations, never a deduplicated set.

Each firing row contains `action_id`, `intention_id`, `occurrence`,
`trigger_type`, `due_at`, `evaluated_at`, and `provider_evaluated_at`.
The due date and occurrence come from the public returned firing snapshot.
`evaluated_at` is explicitly the requested clock, not a newly measured wall
timestamp. `provider_evaluated_at` comes from the public recurrence watermark
when present and otherwise remains null (including one-shot firings without
that watermark). A present provider watermark must equal the requested clock.
The adapter rejects wrong tenant, session, user, agent, unknown intention,
non-fired status, invalid occurrence, naive timestamps and clock mismatch.
This projection contains no action payload, secret or private engine field.

## Descriptive scorer

`eval.public.action_timing.score_exact_time(expected, ticks)` consumes one
isolated case. All rows use a closed schema; each list and the total number of
observed firings are bounded at 10,000. Expected occurrences have exactly
`action_id`, `occurrence`, `due_at`, and `cancelled`. The caller must establish
this schedule independently of system output. A cancelled expectation means
cancellation was requested before that occurrence became due; the scorer does
not infer or verify the cancellation command itself.

The scorer requires nondecreasing tick times, aware timestamps, valid finite
command durations, consistent action-ID multisets, and exact-time triggers.
It deliberately rejects event/window/dependency timing: those require their
own eligibility/deadline definitions rather than silently treating `due_at`
as the correct gold deadline.

For each expected `(action_id, occurrence)`, the first observed firing's signed
offset is `requested evaluation time - expected due time`, in seconds.
Negative/zero/positive values are early/on-time/late. Lateness is the positive
part of that offset. The mean and maximum use **observed, non-cancelled**
expected occurrences only, with an explicit denominator. Missing occurrences
have null offsets, never zero lateness. An unobserved due occurrence is missed
when the final tick reaches its due time; otherwise it is pending. With no
ticks, all unobserved active occurrences are pending. Cancelled-fired and
cancelled-unfired are reported separately for the supplied observation window.

All duplicate observations, unexpected firings and differences between
reported and expected due dates remain visible. Gold due dates determine the
offset even if the provider reports a different due date. Full observation
rows are retained. Repeated firings do not shift the first-firing timestamp.
Command wall durations are summed separately, not used as virtual lateness.
Money cost remains null/not-measured. No confidence interval, pass verdict,
baseline non-inferiority or ranking is fabricated.

## Integration evidence and remaining work

The `eval.public.action_timing_run` entry point now persists a fixed five-seed
development workload, all public operation inputs/outputs and its per-case
reports. Each case has 29 operations and eight expected occurrences; no gold
expectation is sent through the adapter. The replay path requires the exact
plan and full ordered operation log, binds each observation to its planned
clock, and recomputes the saved report. It rejects missing operations, plan
changes, clock mismatches and report drift, including numeric/boolean type
substitution. This is observation replay, not a fresh execution or signed
custody validation. Harness hashes and source commit are descriptive metadata;
the receipt explicitly leaves production runtime matching unverified.

The initial runner/scorer validation passed 20 tests in 13.49 seconds, including
a real local run, report recomputation, overwrite refusal, artifact mutations
and a deliberately failed test-double run retaining its partial operation log.

A subsequent [committed-source capture](../../eval/reports/m12-exact-time-development-2026-10-04/README.md)
completed all 145 operations and reproduced its reports exactly from saved
observations. It retains 22 deliberately late observations, eight on-time
firings and ten unfired cancelled occurrences. This is inspectable development
evidence, not registration, resource admission or a quality ranking.

Five seeded four-week regressions now feed real public CLI observations into
this scorer: weekly recurrences; 0, 60, 300 and 86,400-second injected poll
delays; before-due negative polls; same-time retries; midstream cancellation;
unaffected control; bounded termination. Delays are inputs to this deterministic
workload, not evidence of real scheduler responsiveness. Unit cases separately
cover missed/pending, early/late, duplicate, cancelled and unexpected firings,
due-date drift, malformed evidence and missing provider watermarks.

This is not a complete M12 benchmark. The registered multiweek fixture,
full trigger-family timing definitions, revision/idempotency contract,
independent sink evidence, cost/resource measurements, calibrated baseline,
absolute recall/F1 floors, reproducible admitted bundles and publication
requirements remain open. The adapter's existing synthetic operating-point
values remain development controls, not newly measured calibration evidence.
