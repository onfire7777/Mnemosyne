# Frozen common-runner review

Reviewed on 2026-10-22 by the independent `ranking_audit` agent. Scope: `eval/controlled_comparison.py`, `eval/codex_bridge.py`, `eval/codex_reader.py`, and `eval/comparison_protocol.py`. No frozen source was edited during review; reproductions used temporary synthetic data and mocked providers.

Run manifest: `bd5c598b12e916b4224caaa173b9f9e44426ae8667baa4d761e18f8cc2ebacf3`. All 96 source hashes matched the frozen configuration, and manifest/configuration validation passed. There were no answer result files at inspection. The existing common-runner/protocol/bridge/reader tests passed: **93 passed in 0.48s**.

## Findings requiring a later fix

### P2 — Active claims are mistaken for interrupted attempts

At `controlled_comparison.py:273`, a second `run_answers` invocation converts an existing claim into a failed result without checking whether its owner is still running. `run_mnemosyne` has the same liveness issue at line 188. Atomic final publication prevents overwriting the incorrect failure but does not prevent creating it.

Confirmed reproduction: block the first invocation's synthetic reader, launch a second invocation against the same output directory, then release the first. The stored result is `failed / interrupted`; the first invocation finishes its two synthetic provider calls and raises `FileExistsError` when publishing its valid result.

Current-run control: exactly one active runner per action/output directory; resume only after the previous process has exited. The parent confirmed one native runner, no answer runner yet, and a single answer invocation after all contexts are available. No effect on the actual run has been observed. After the frozen run, archive its exact source and add process-held exclusive run-directory locking with concurrent-process tests. A lock must not be removed merely because a claim exists.

### P2 — Keyboard interruption continues queued work but drops its results

At `controlled_comparison.py:286`, `ThreadPoolExecutor` context-manager shutdown waits for all submitted jobs; it does not cancel queued jobs. If `KeyboardInterrupt` leaves the `as_completed` loop, those jobs still call providers and their results are never published by the abandoned loop.

Confirmed reproduction: interrupt after submitting four synthetic question/arm jobs. All **eight** reader/judge calls still complete, **zero** answer files are published, and **four** claims remain. A later resume misclassifies this completed work as interrupted. This wastes quota and loses receipts while conservatively lowering scores.

Current-run control: no Ctrl-C pause is planned during the answer invocation. A genuine request to stop must still be honored; if interruption happens, report incompleteness and retain known receipts rather than claiming a completed comparison. After the run, cancel queued jobs, prevent a new judge call after cancellation, drain already admitted calls, and publish each result inside its worker. Preserve first-attempt identity and do not retry canceled/failed attempts. Coordinate this repair with the exclusive-lock change above.

## Passed checks and interpretation limits

- Selection uses only IDs/types and excludes the existing 100 development IDs. Sanitized inference data omits gold answers, evidence labels, question type, and abstention-bearing question IDs from model prompts. The independent judge alone receives gold data. No actual input-label leak was found.
- Both arms use the same 16,000-character evidence packing, requested reader/judge model and effort, and exact yes/no grading rule. The fixed denominator is 14 per arm; failures and missing results score zero, and incomplete runs are labeled explicitly. Pairing and stratified bootstrap accounting are consistent with the documented small pilot.
- Codex executes in a fresh temporary directory with user configuration, tools, MCP, skills, memory, and browsing disabled. Unexpected tool events, malformed output, extra completed turns, and failed calls are rejected. This verifies configured isolation and fail-closed receipt handling, not absence of pretrained knowledge.
- Generation-token caps and temperature are not enforced; resolved model may be unknown. These are disclosed limitations. The result cannot establish a vendor leaderboard score or global rank.
- `stage_seconds.total` combines native stage durations with answer-phase wall time, excluding idle gaps between commands. Answer timestamps cover the answer phase only. Answer-record usage explicitly covers reader/judge calls only; final resource reporting must also include the separate native receipts and their incomplete-usage flags. Missing usage and monetary cost must not be presented as zero or as complete savings.

Verdict: continue the current **single-runner, uninterrupted** measurement with the stated controls. Two confirmed recovery defects remain for repair after preserving the frozen source. No other score-invalidating flaw was found in this bounded review.

## Proposed repair, not applied

`proposed-answer-recovery.patch` contains the answer-admission, cancellation, draining, and durable-publication repair plus two focused tests. Claims are created only by an executing worker. Queued cancellations do not call a provider or acquire a claim. An admitted reader may finish within its existing timeout; its receipt is saved and cancellation prevents a subsequent judge call. Completed outcomes are published by the worker even if the result observer is interrupted. Resume preserves canceled/failed first attempts and runs only work that was never admitted.

The proposal was loaded as an in-memory module and validated with its two new tests plus the four existing common test modules: **95 tests passed**. Its unified diff passes `git apply --check`. All 96 frozen source hashes still match after validation. Apply this patch only after preserving/completing the frozen run, followed by the separate exclusive-lock wrapper proposal owned by `baseline_review`.
