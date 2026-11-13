# Benchmark integrity tools

From the `legit-memory-benchmarks` skill. Rules: no held-out benchmark material in the code base,
development-split-only tuning, frozen single final run, audited receipt.

- `split.py` - deterministic development / held-out split (LongMemEval-S: `eval/longmemeval_s/split.json`, lowest 100 sha256(question_id) = development)
- `sanitize.py` - system-visible inputs vs scorer-only key
- `contamination_scan.py` - plain-text scan for held-out questions, answers, gold-evidence phrases and rare names (needs the dataset)
- `fingerprints.py` - hashed held-out fingerprints; `check` needs no dataset and runs in CI against `.benchmark-guard/longmemeval_s.fp.json`
- `freeze.py` - freeze a run (clean tree, leak check, pinned hashes, append-only attempt ledger)
- `audit_results.py` - completeness / scope / model checks and the run receipt
