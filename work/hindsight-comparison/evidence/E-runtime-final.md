# E-runtime-final
- title: Frozen runtime candidate verification
- observed_at: 2026-10-22
- source_type: command and independent source review
- source_ref: runtime-final-verification.xml
- content_hash: fb8c78d873ff4400080da0106910aab9758901ea53e0d1ae7fad51dbaf64ff9c
- artifact_path: runtime-final-verification.xml
- repro_command: SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk bash work/hindsight-comparison/verify-candidate.sh
- raw_excerpt: 1786 cases; 1672 passed; 114 skipped; 0 failures; 0 errors; 18.612 seconds
- linked_workitems: WI-004, WI-005, WI-006, WI-007, WI-010, WI-011, WI-012
- supersedes_for_current_candidate: E-validation

`runtime-source-manifest.json` pins 381 source/test/dependency files. All remained unchanged
through combined verification and the final local retrieval run. Global Ruff and whitespace
checks passed. The broader exploratory suite was interrupted and is not a whole-suite pass.

Independent retrieval-custody checks: `derived-read-custody-verification.xml` records 682
passes and 106 skips, including the changed portability fixtures. Two independent reviewers
confirmed closure of the legacy partial-deletion and stale lexical-adapter reproductions.

`runtime-retrieval-comparison.json` records matching question IDs and dataset hashes:
95 answerable development questions, default Recall@5 0.5744 -> 0.9232; 48 improved,
0 regressed, 47 unchanged. Passage recall remains 0.9091. This is retrieval-only, not
comparative answer accuracy or a ranking. Held-out question content was not used for tuning.

Live PostgreSQL, Windows, production grounded-provider inference, full Hindsight feature
parity and a controlled cross-system quality comparison remain unverified or incomplete.
