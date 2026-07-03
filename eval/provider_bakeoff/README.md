# Provider Bake-Off Protocol

This runbook binds Phase 3 provider comparisons to the existing Mnemosyne
evaluation harness. It is a measurement protocol only: it does not flip provider
defaults, relax protected cases, or authorize product claims.

## Rule

A candidate provider can be promoted only when all of these are true:

- It is non-inferior to the pinned baseline on the scoped private suite.
- It has no protected-case regression.
- Its margin is larger than measured run-to-run noise.
- It reports confidence intervals from the harness output.

If a delta is inside run-to-run noise, record it as `no signal`, not as a win or
a regression. Public benchmark sets remain internal sanity checks only and must
not become headline claims.

Source policy:

- `docs/blueprint/Mnemosyne-Evaluation-and-Test-Plan.md` lines 246-249:
  promotion requires non-inferior, no protected-case regression, and margin
  greater than run-to-run noise with confidence intervals.
- `docs/blueprint/Mnemosyne-Evaluation-and-Test-Plan.md` lines 227 and
  256-260: public sets are sanity gates only, strict judges and confidence
  intervals are mandatory, and claims rest on the private suite.

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

## Review Checklist

For every candidate comparison:

- Keep the baseline and candidate reports together with the exact fixture used.
- Compare only scoped, relevant verdicts and protected cases.
- Preserve the raw JSON reports; summarize from them, do not rewrite them.
- Mark `promotion: false` unless the non-inferiority, protected-case, noise, and
  CI requirements are all satisfied.
- Do not cite public benchmark scores in release notes, README claims, or Tier-B
  status. They are sanity signals only.
