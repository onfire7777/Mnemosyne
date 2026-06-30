# Mnemosyne Runbook Index

This directory indexes operator runbooks for Mnemosyne production parity. It does
not define new release gates; the canonical gate binaries remain the existing
CLI commands consumed by `deployment-soak` and `release-audit`.

## Production Evidence

- `infra/README.md` - local infra stack and evidence capture entry points.
- `infra/PRODUCTION-EVIDENCE.md` - Tier B production evidence runbook.
- `infra/templates/production-soak-manifest.template.json` - secret-free
  manifest template covering the production release command profile.
- `infra/templates/production-render.env.example` - blank non-secret input
  template operators copy outside the repo before filling render values;
  `MNEMOSYNE_PROD_EVIDENCE_DIR` must be an absolute external input-artifact path
  outside the repository.
- `infra/templates/production-operator-env.inventory.md` - names-only operator
  inventory covering render placeholders, provider manifest references, and
  runtime/secret-custody env names; do not put values in this file.
- `infra/templates/provider-manifest.production.template.json` - non-secret
  provider-check template copied to
  `$MNEMOSYNE_PROD_EVIDENCE_DIR/provider-manifest.production.json` outside the
  repo and filled with production provider values or environment references.
- `infra/templates/production-input-artifacts.checklist.md` - row-routed
  checklist for the external input artifacts that must exist before preflight.
- `infra/scripts/render-production-soak-manifest.sh` - canonical renderer for
  non-secret `MNEMOSYNE_PROD_*` placeholders; refuses repo-local output by
  default and validates the production command profile before writing. Its
  optional `--runtime-env-file` lets readiness checks validate provider-manifest
  env refs from the same strict external runtime/provider file later passed to
  capture, without retaining secret values or shell-sourcing them. Its
  `--check-environment` JSON exposes `parity_row_readiness` so the flat
  manifest-referenced input-artifact inventory can be assigned to the matching
  Tier-B row runbook without exposing custody paths. The row entries also scope
  missing render env, missing provider-manifest env refs, input-artifact
  completeness, and `ready_for_capture` where those checks have enough
  information to evaluate them.
- `infra/scripts/capture-production-evidence.sh` - operator capture wrapper
  invoked with `--env-file <external-runtime-env>` so secret-bearing
  runtime/provider values stay outside shell history and committed artifacts. It
  validates the rendered manifest, rejects unresolved production
  placeholders, rejects duplicate or unknown production commands, rejects
  high-confidence secret material, rejects secret-bearing manifest options in
  split and `--option=value` forms, rejects unscannable retained artifacts,
  rejects repo-local or pre-existing output roots, supports `--preflight-only`
  setup validation, runs `deployment-soak --evidence-dir` from the copied
  `operator-soak-manifest.json`, and then runs
  `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json"
  --require-production-validated --require-provider-forbid-local`. Successful
  preflight and capture runs write `redaction-scan.json`; successful full
  captures bind the deployment report/check artifacts with manifest SHA-256
  digests, reject path escape and report/check divergence during release audit,
  snapshot manifest-referenced input artifacts under `OUT_ROOT/input-artifacts/`,
  rewrite the copied operator manifest to those staged paths, and also write
  `bundle-manifest.json` with SHA-256 hashes for retained artifacts. Check-level
  `input_artifacts` metadata is retained through the same custody path for row
  evidence that is not a command-line argument.
- Executable tool paths such as `MNEMOSYNE_PROD_C2PA_TOOL` are validated as
  absolute, external, executable tool references outside the repository,
  reached without symlinks or non-canonical wrapper paths, and recorded in
  `preflight.json` with size and SHA-256 metadata; they are not snapshotted as
  evidence input artifacts.
- `provenance-trust-check --suite` is parsed during preflight: nested
  `asset_path` and `c2pa_asset_path` values are snapshotted and rewritten in
  the staged suite JSON, while inline `--suite-json` is rejected for production
  capture.

## Row Runbooks

- `row-01-production-postgres-retrieval.md`
- `row-02-tenant-isolation-and-auth.md`
- `row-03-cli-mcp-runtime-coverage.md`
- `row-04-consolidation-role-pipeline.md`
- `row-05-signed-provenance.md`
- `row-06-multimodal-retrieval.md`
- `row-07-privacy-and-erasure.md`
- `row-08-observability-dashboards.md`
- `row-09-parametric-tier.md`
- `row-10-live-parity-suite.md`

## Scope Rules

- Local and compose evidence can prove gate mechanics, but cannot satisfy Tier B.
- `--preflight-only` output is setup proof only; it does not flip any row to
  Done.
- `parity_row_readiness` output from the renderer is readiness routing metadata
  only; it does not add a gate and does not flip any row to Done.
- Each row handoff resumes only after the operator reports the row's evidence
  capture signal from the row runbook. The generic defer signal is
  `skip operator gates`.
- Production evidence must be operator-captured against the real production
  wrapper and manifest-bound release-audit path over deployed IdP,
  Postgres/retrieval, provider, MCP, dashboard, worker, object-store,
  KMS/residency, C2PA, and trainer surfaces. Local staging, compose, and
  non-production dry runs are setup evidence only and cannot satisfy Tier B.
- Secrets must be supplied through environment variables, provider files, Vault,
  Keycloak, KMS, or equivalent runtime custody. Do not place raw secrets in the
  soak manifest or committed docs; production bundles must keep
  `redaction-scan.json` at `ok: true` with no skipped files and a
  `scanned_files` list matching the retained `bundle-manifest.json` artifact
  set except `redaction-scan.json` itself, plus an independently retained
  out-of-band fingerprint record for handoff custody.
- After capture, select the repo interpreter with
  `PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"`;
  set `BUNDLE_DIR=/secure/path/to/mnemosyne-production-evidence`; set
  `FINGERPRINT_RECORD=/secure/path/to/mnemosyne-production-bundle-fingerprint.json`
  from the capture wrapper's `--fingerprint-record-output`;
  set `VERIFY_REPORT=/secure/path/to/mnemosyne-production-evidence-verify.json`
  outside the bundle under review; then
  `"$PYTHON" -m mnemosyne.cli production-evidence-verify "$BUNDLE_DIR"
  --fingerprint-record "$FINGERPRINT_RECORD" --report-output "$VERIFY_REPORT"`
  can recheck the completed bundle offline and retain a
  no-overwrite reviewer report, including fresh redaction recompute and
  `scanned_files` coverage against `bundle-manifest.json`, retained
  `source-soak-manifest.json` custody, source/operator command-profile
  agreement, diagnostic-only `reviewer_guidance`, and row review sourced from
  retained `preflight.json.parity_row_readiness`.
  This is custody review only; it does not contact production, rerun
  `deployment-soak`, create evidence, or replace operator capture.
