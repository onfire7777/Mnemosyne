# Authorized TRAIN asset intake

Five exact-pinned files (348,175,076 bytes) were fetched to the operator-local
`/Users/admin/.local/state/mnemosyne/compact-train-intake-2026-10-04` quarantine.
They comprise the SQuAD v2 TRAIN shard, two Hotpot distractor TRAIN shards and
the two pinned dataset cards. No validation/test shard, fullwiki duplicate,
model weight or protected artifact was fetched. All five files were rehashed
independently after completion; sizes and digests match the allowlist.

`original-intake.json` retains the original receipt unchanged. Its source hash
must NOT be treated as execution identity: the old downloader computed it at
completion and its source file was edited during transfer. `verification.json`
records this defect, the known launch revision and independent asset checks.
The downloader now captures identity at entry and publishes its receipt
atomically; a regression test edits source during transfer to check this.

These are raw quarantined assets, not a training corpus. Exact-span validation,
row provenance, document/entity grouping, protected-overlap checks before and
after transformation, immutable grouped partitions and complete license /
attribution handling remain open. No training or model-selection score exists.
The upstream cards declare CC-BY-SA-4.0; raw data stays outside Git.

Reproduce intake into a new operator-owned directory with:
`python -m eval.compact_answering.train_intake /absolute/new/quarantine`
The command uses only the standard library, pins every filename/revision/hash,
streams at most 1 MiB per read, and keeps failed partial files for inspection.
