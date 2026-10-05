# M12 exact-time diagnostic implementation

Date: 2026-10-04. Parent source: `5882d192` on `codex/development`.

The [development protocol](../../docs/plans/m12-exact-time-development-protocol-2026-10-04.md)
is now implemented by `ActionCLI`'s opt-in `intention.observe` path and
`action_timing.score_exact_time`. Existing `intention.query` output and the
registered PM-Bench/TriggerBench scoring contracts are unchanged. The new
path preserves public firing identity, recurrence index, due date, requested
virtual clock, nullable provider clock and measured CLI wall duration.
Scope/identity/clock checks reject inconsistent observations.

The scorer consumes a caller-supplied expected schedule and retains all
observations. It separates early, on-time, late, missed, pending and cancelled
outcomes, preserves duplicate/unexpected observations, and checks reported
due-date drift. Missing firings have null offsets; no observations produce no
lateness estimate. Wall duration and virtual lateness are separate, and money
cost remains unmeasured. There is no aggregate quality score or pass claim.

Validation completed:

- **57 passed in 16.76 seconds:** scorer edge cases, public action/recurrence
  tests, five seeded four-week real-CLI timing sequences and signed-session /
  semantic-boundary tests. No model or external action payload executed.
- **55 passed in 0.43 seconds:** renderer/output and action documentation checks.
- Ruff and `git diff --check` passed. Locally served coverage/comparison HTML
  was fetched and verified to display the updated status.

This is not a registered multiweek corpus or an admitted benchmark result.
Event/window/dependency timing is intentionally rejected by this exact-time
diagnostic. Full M12 still needs those protocol definitions, calibrated
reference comparisons, revision/idempotency and sink evidence, cost/resource
measurements, bundle integration and admission. No previous result or signed
artifact was changed; no M12 score was added to the website.
