# Applied benchmark recovery and runner locks

Applied after the user cancelled the benchmark and the source freeze ended.
No benchmark or provider calls were made for this change. Existing cancellation
records and benchmark results were not modified.

- Answer jobs claim an attempt only when a worker starts. Cancellation leaves
  queued jobs unclaimed, drains active stages, and preserves their receipts.
  Workers publish results before the observer collects them. Resume preserves
  prior terminal outcomes and admits only previously unstarted work.
- Process-held, nonblocking locks protect answer outputs, Mnemosyne context
  outputs, and the native Hindsight output/receipt/runtime directories before
  mutation. Busy callers fail immediately. Permanent lock files are never
  deleted as part of recovery; the operating-system lock determines ownership.
- `eval/runner_lock.py` is included in future frozen source manifests. Old
  frozen runs reject the changed source instead of silently resuming.
- Review reproduced two cancellation gaps during reader/judge prompt preparation.
  Checks immediately before each provider call now prevent those new stages.
  [Before-fix failures](runner-cancellation-before.log) cover both cases.

Verification: **104 passed, 0 skipped, 0 failures/errors, 0.469 seconds** in the
[JUnit receipt](runner-recovery-lock-verification.xml). The suite includes
13 lock tests, 4 recovery tests, and existing comparison/protocol/Codex-reader
tests. Ruff and `git diff --check` passed. All provider calls in these tests were
mocked. Real subprocess death/reacquisition was tested on macOS; Windows byte
locking was mocked, not run on Windows.

The existing isolated Hindsight interpreter also passed **15 adapter contract
tests in 0.041 seconds** ([log](runner-native-adapter-verification.log)), for
**119 passing tests across the two environments**. These contract tests mock
inference and do not initialize the database or runtime services.

```sh
.venv/bin/python -m pytest -q \
  tests/test_benchmark_runner_lock.py \
  tests/test_controlled_comparison_recovery.py \
  tests/test_controlled_comparison.py \
  tests/test_comparison_protocol.py \
  tests/test_codex_reader.py
work/hindsight-comparison/controlled/runtime/venv/bin/python \
  -m unittest eval.hindsight_adapter.test_adapter
```

Limits: these are cooperative locks for the same local filesystem, not
distributed database locks. Processes using different resource directories or
bypassing the entry points are outside the contract. An already-admitted
provider stage may finish within its existing timeout; force-killed provider
responses cannot be recovered by these locks. Native adapter tests need the
isolated Hindsight interpreter; collecting them in the main Mnemosyne virtual
environment correctly fails because `hindsight_api` is not installed there.
