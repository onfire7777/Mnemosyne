# Leaderboard Methodology Policy

Version: 0.1.0  
Status: draft; External activation required

## Reproducibility and eligibility

Every result binds dataset revision and license, split role, adapter, harness,
configuration, environment, build provenance, raw traces, metrics, and a
reproduction bundle by cryptographic digest. Headline eligibility additionally
requires independent reproduction and every PBPP (publishable benchmark
provenance protocol) gate. Development smoke results are never headline-ready.

## Measurement

Distinct metric families remain separate; no composite may hide a regression
across retrieval, grounded answer quality, safety, calibration, latency, cost,
or scale. Reports include sample counts, uncertainty method and confidence interval,
missingness, exclusions, and deterministic tie handling. Ties are
reported as ties when intervals and the preregistered rule do not distinguish
systems.

Any model-based judge requires judge disclosure: provider/model and pinned
revision, prompt, sampling parameters, rubric, calibration set, agreement or
sensitivity analysis, and cost. Judge output is evidence, never an unexplained
authority.

## Integrity

Contamination controls separate development and held-out splits, record prior
access and tuning, prohibit training on confidential evaluation items, test
near-duplicates, and disclose suspected leakage. Runs use equal budgets and the
operator firewall. Corrections and appeals follow their versioned public
policies.
