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
- an embedded computed `deep_latency_eval` fixture recording reported-only
  local deep-search P95 latency over a versioned graph corpus
- an embedded computed `resource_usage_eval` fixture recording paid-provider
  spend per 1k local G0 queries; controller watts/$ remains unmeasured unless
  an explicit power/cost telemetry artifact is supplied, because the harness
  does not estimate power data

To measure `controller_watts_per_dollar`, pass a local telemetry artifact:

```bash
python -m eval.g0.runner \
  --controller-telemetry /secure/path/controller-telemetry.json \
  --write-baseline
```

The telemetry JSON must contain positive numeric values:

```json
{
  "controller_avg_watts": 12.5,
  "controller_cost_usd_per_hour": 0.25,
  "controller_cost_window_hours": 1.0
}
```

`controller_cost_window_hours` is optional and defaults to `1.0`; the reported
watts/$ denominator is `controller_cost_usd_per_hour * controller_cost_window_hours`.
The report records the telemetry basename and SHA-256, not the absolute source
path. Do not commit operational power/cost telemetry unless it is intentionally
sanitized fixture data.

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
