# Provider Bake-Off Protocol

This runbook binds Phase 3 provider comparisons to the existing Mnemosyne
evaluation harness. It is a measurement protocol only: it does not flip provider
defaults, relax protected cases, or authorize product claims.

## Rule

A candidate provider can be promoted only when all of these are true:

- The shared provider conformance lane passes for the Python service, Python
  HTTP adapters, and Rust sidecar. The fixture is
  `tests/fixtures/provider_contract.json`; CI runs it through the
  `provider-conformance` job.
- It is non-inferior to the pinned baseline on the scoped private suite.
- It has no protected-case regression.
- Its margin is larger than measured run-to-run noise.
- It reports confidence intervals from the harness output.

If a delta is inside run-to-run noise, record it as `no signal`, not as a win or
a regression. Provider promotion still rests on the scoped private suite. A
public benchmark number may become a claim only under the Public-Benchmark
Publication Protocol (PBPP) in
`docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` §2: pinned public harness,
complete artifact bundle, separate retrieval-recall and LLM-judged-QA columns
with judge disclosure, no private-suite conflation, and independent
reproduction before any headline claim.

Source policy:

- `docs/blueprint/Mnemosyne-Evaluation-and-Test-Plan.md` lines 246-249:
  promotion requires non-inferior, no protected-case regression, and margin
  greater than run-to-run noise with confidence intervals.
- `docs/EXECUTION-PLAN-B-Benchmark-and-Leaderboard.md` §2: PBPP governs public
  numbers; private-suite results remain internal QA and never headline claims.
- `docs/blueprint/Mnemosyne-Evaluation-and-Test-Plan.md` lines 227 and 256-260:
  strict judges and confidence intervals remain mandatory.

## Inputs

Use `eval/provider_bakeoff/sidecar-local-smoke.json` as the local smoke fixture.
It defines two arms:

- `local-deterministic`: the current local deterministic engine.
- `deterministic-sidecar`: the Phase 3 compact HTTP sidecar using deterministic
  `/embed` and `/rerank` routes.

The fixture intentionally uses loopback URLs and no API key. Production provider
manifests must keep credentials outside this repo and pass `mnemosyne
provider-check --provider-manifest ...` before any bake-off run is compared.

## Smoke Commands

Local baseline:

```bash
uv run --locked python eval/run_eval.py \
  --quick \
  --out-dir /tmp/mnemosyne-provider-bakeoff/local-deterministic
```

Deterministic sidecar candidate:

```bash
cargo run --manifest-path rust/mneme-providers/Cargo.toml --bin mneme-providers
```

In another shell:

```bash
uv run --locked python eval/run_eval.py \
  --quick \
  --out-dir /tmp/mnemosyne-provider-bakeoff/deterministic-sidecar \
  --global-flag=--embedding-provider --global-flag http \
  --global-flag=--embedding-url --global-flag http://127.0.0.1:8000/embed \
  --global-flag=--reranker-provider --global-flag http \
  --global-flag=--reranker-url --global-flag http://127.0.0.1:8000/rerank
```

Evidence paths:

- `/tmp/mnemosyne-provider-bakeoff/local-deterministic/slo_report_latest.json`
- `/tmp/mnemosyne-provider-bakeoff/deterministic-sidecar/slo_report_latest.json`
- The matching `.md` files in the same directories.

## Evidence Harness

After the arm reports exist, summarize them with the provider bake-off harness.
It preserves raw reports and emits a promotion-safe JSON envelope:

```bash
uv run --locked python eval/provider_bakeoff/run.py \
  --fixture eval/provider_bakeoff/sidecar-local-smoke.json \
  --provider-check-report /tmp/mnemosyne-provider-bakeoff/provider-check.json \
  --noise-notes /tmp/mnemosyne-provider-bakeoff/noise-notes.md \
  --output /tmp/mnemosyne-provider-bakeoff/bakeoff-report.json \
  --strict
```

If a provider manifest is available but a retained provider-check report is not,
the harness can run the existing check itself:

```bash
uv run --locked python eval/provider_bakeoff/run.py \
  --fixture eval/provider_bakeoff/sidecar-local-smoke.json \
  --provider-manifest /secure/operator/provider-manifest.json \
  --noise-notes /tmp/mnemosyne-provider-bakeoff/noise-notes.md \
  --output /tmp/mnemosyne-provider-bakeoff/bakeoff-report.json \
  --strict
```

Use `--execute-arms` only when the sidecar/TEI/Python provider processes are
already started or managed by the calling runbook. The local smoke fixture
always reports `promotion.allowed=false`; it can prove evidence packaging and
regression shape, not a production default flip.

## Review Checklist

For every candidate comparison:

- Keep the baseline and candidate reports together with the exact fixture used.
- Compare only scoped, relevant verdicts and protected cases.
- Preserve the raw JSON reports; summarize from them, do not rewrite them.
- Mark `promotion: false` unless the non-inferiority, protected-case, noise, and
  CI requirements are all satisfied.
- Do not cite a public benchmark score in release notes, README claims, or
  Tier-B status unless its PBPP bundle and independent reproduction are on file.
  Never blend it with private-suite evidence or provider-promotion evidence.
