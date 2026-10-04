# M12 action observation integrity and recurrence regressions

Date: 2026-10-04. Parent source: `b8a8dc7a` on `codex/development`.
Scope: implementation regressions; not an admitted or official benchmark run.

`ActionCLI` previously converted both returned firing IDs and selected
candidate IDs into sets. Two observations of the same firing could therefore
reach the benchmark as one action, hiding evidence relevant to M12's zero
duplicate-execution requirement. Both transformations now retain multiplicity;
the existing benchmark duplicate-ID check rejects the invalid observation.
Available-action filtering and canonical sort order remain in place. Two
regressions failed before the fix and passed after it, including a duplicated
provider response passed through the actual translation and benchmark layers.
The injected provider response is a test double, not an observed engine defect.

Five additional seeded calendar tests execute the real public CLI in separate
processes. Each covers four virtual weeks with two weekly recurring intentions,
poll delays of 0/60/300/86400 seconds in seeded order, pre-due negative polls,
same-time repeats, cancellation after the second occurrence, a surviving
control and termination at the configured occurrence limit. These tests passed.
No clock sleeps, model calls, real reminder scheduling or action payload
execution occurs. The delays are test inputs, not measured scheduler latency.
The production recurrence implementation and BurnOS public contracts did not
change.

Validation:

- Focused action/prospective-memory/API run: **182 passed** in 0.89 seconds.
- Broader public action/recurrence/harness run: **115 passed, 1 failed** in
  99.64 seconds. The sole failure was a documentation assertion expecting the
  old set-intersection wording. It was updated to require duplicate-preserving
  filtering and passed in a targeted rerun (**1 passed**, 0.22 seconds).
- Ruff and `git diff --check` passed.

The registered PM-Bench/TriggerBench fixtures, scorer formulas, result records
and publication flags are unchanged. Full M12 still requires a versioned
multiweek benchmark corpus, lateness magnitude and cost observations,
idempotent-sink evidence, calibrated baseline/floors and resource admission.
These five seeded regression timelines do not replace that benchmark corpus.
