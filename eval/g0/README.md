# Mnemosyne G0 Benchmark Harness

G0 is the baseline and ablation layer from
`docs/blueprint/cognitive-architecture/04-G0-BENCHMARK-SPEC.md`. It reuses the
existing eval lane instead of forking it.

Run:

```bash
python -m eval.g0.runner --write-baseline
```

This writes:

- `eval/g0/reports/report.json` and `report.md`
- `eval/g0/baselines/baseline-0.json` when `--write-baseline` is used
- an embedded computed `continual_learning_eval` fixture measuring the current
  backward-transfer accuracy drop after later overlapping ingests
- an embedded computed `confabulation_eval` fixture measuring the current
  false-accept rate for generated / low-fidelity support; this is the local
  deterministic proxy for the full provenance-entailment plus sampled-audit G0
  metric

Evaluate a preregistered ablation:

```bash
python -m eval.g0.gate \
  --baseline eval/g0/baselines/baseline-0.json \
  --candidate path/to/candidate-g0-report.json \
  --prereg path/to/preregistration.json \
  --decision-log eval/g0/decision-log.jsonl
```

The gate fails unless the preregistered target metric improves by its margin and
every guardrail metric remains non-regressed.
