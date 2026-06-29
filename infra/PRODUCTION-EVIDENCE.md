# Production Evidence Capture Runbook

This runbook is the operator handoff for flipping the remaining Tier B parity rows from Partial to Done. It does not add a new gate; it uses the existing `deployment-soak` evidence bundle plus manifest-bound `release-audit --evidence-manifest ... --require-production-validated --require-provider-forbid-local` path.

## Preconditions

- Copy `infra/templates/production-render.env.example` outside the repo, fill the blank non-secret `MNEMOSYNE_PROD_*` values there, and source the external copy before rendering.
- Populate `MNEMOSYNE_PROD_EVIDENCE_DIR` with the manifest-referenced production input artifacts before running `--check-environment`. The check is no-write and reports the static template-derived artifact inventory plus `parity_row_readiness` grouping even before environment values are sourced; after `MNEMOSYNE_PROD_EVIDENCE_DIR` is set, it fails if required relative artifact names are missing from that external directory and shows which strict-audit row is blocked. Use `infra/templates/production-input-artifacts.checklist.md` as the non-secret operator checklist for the required artifact names.
- Copy `infra/templates/provider-manifest.production.template.json` to `$MNEMOSYNE_PROD_EVIDENCE_DIR/provider-manifest.production.json` and fill the external copy with production provider values or environment-variable references. This file is shared evidence for retrieval, auth/session provider custody, consolidation roles, multimodal/object-key providers, privacy/residency policy, parametric adapters, and the final parity row. It must keep `forbid_local: true` and include every required provider-check subcheck listed in the template.
- Render `infra/templates/production-soak-manifest.template.json` outside the repo with `infra/scripts/render-production-soak-manifest.sh --output /secure/path/to/production-soak-manifest.json`. Manual edits are only a fallback and must still leave no unresolved `MNEMOSYNE_PROD_*` placeholders; the capture wrapper rejects unresolved placeholders before running production checks.
- `MNEMOSYNE_PROD_EVIDENCE_DIR` and the second positional output-root argument passed to `capture-production-evidence.sh` must be absolute external custody paths outside the repository; output roots must be new and must not already exist. The wrapper does not consume a separate `PREFLIGHT_OUT_ROOT` environment variable.
- Keep raw secrets out of `args` and `global_args`. The production wrapper rejects secret-bearing options such as `--access-token`, `--api-token`, `--github-token`, `--session-secret`, and `--password`, and it fails closed on high-confidence secret material such as JWTs, private-key blocks, GitHub tokens, AWS access keys, and `sk-*` API keys.
- Provide secrets through environment variables or command/provider files. Required examples include `MNEMOSYNE_POSTGRES_DSN`, `MNEMOSYNE_IDP_TOKEN`, `MNEMOSYNE_MCP_TOKEN`, and `MNEMOSYNE_MCP_SESSION_TOKEN` where the selected checks need them.
- The manifest must include:
  - `validation_scope.production_validated: true`
  - `validation_scope.target_environment: "production"`
  - `validation_scope.operator_asserted: true`
- The manifest must include the exact production release profile: every command in the current 28-command set from `src/mnemosyne/cli.py`, with no duplicate or unknown commands.
- The output root must be new and outside this repository. The wrapper rejects repo-local or pre-existing output roots so stale artifacts cannot enter a production bundle and final-directory creation stays race-resistant.
- Every manifest-referenced production input artifact must already exist at an absolute external path before preflight. The wrapper inventories those paths in `preflight.json`, recursively scans referenced directories, and fails closed on missing, symlinked, secret-shaped, non-UTF-8, or over-limit input artifacts. Accepted inputs are snapshotted under `OUT_ROOT/input-artifacts/` with per-file size and SHA-256 metadata, and the copied operator manifest is rewritten to use those immutable snapshots so later mutation of the external source paths cannot change the capture inputs. Provenance trust-suite metadata is hashed after nested asset-path rewrites, so `preflight.json` describes the retained staged suite exactly.
- `MNEMOSYNE_PROD_C2PA_TOOL` is the absolute canonical path to the deployed c2patool-compatible executable. Preflight verifies it exists outside the repository, is not reached through a symlink or non-canonical path, and is executable. It records the canonical path, size, and SHA-256 digest under `executable_tool_references` and does not snapshot it as input evidence; keep the C2PA trust-suite JSON and trust-root evidence under `MNEMOSYNE_PROD_EVIDENCE_DIR` instead.
- For `provenance-trust-check --suite`, nested suite `asset_path` and `c2pa_asset_path` values are also treated as production input artifacts. Preflight snapshots those assets and rewrites the staged suite JSON to point at the immutable snapshots. Inline `--suite-json` is rejected for production capture because nested paths cannot be custody-rewritten safely.

## Capture

Run the production wrapper from the repository root:

```bash
cp infra/templates/production-render.env.example \
  /secure/path/to/production-render.env
# Fill /secure/path/to/production-render.env outside this repository.
set -a
. /secure/path/to/production-render.env
set +a
infra/scripts/render-production-soak-manifest.sh --check-environment
infra/scripts/render-production-soak-manifest.sh \
  --output /secure/path/to/production-soak-manifest.json
infra/scripts/capture-production-evidence.sh \
  --preflight-only \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-preflight
infra/scripts/capture-production-evidence.sh \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-evidence
```

The `--preflight-only` command validates production scope, exact command
coverage, absence of unresolved placeholders, absence of secret-bearing CLI
options, absolute external custody paths for production input artifacts,
existence of manifest-referenced input artifacts, and a high-confidence
redaction scan over the rendered manifest plus staged snapshots of those
referenced inputs. It writes `preflight.json`, `redaction-scan.json`, a
`source-soak-manifest.json` copy of the rendered source manifest, and a copied
operator manifest whose artifact arguments and custody-only `input_artifacts`
metadata point at `OUT_ROOT/input-artifacts/` snapshots. It then exits before
`deployment-soak` or `release-audit` runs. Full
capture executes that copied operator manifest from `OUT_ROOT`, not the mutable
source path. A passing preflight is setup proof only; it does not flip any
strict-audit row to Done.

The `--check-environment` command is a no-write readiness check. It reports only
placeholder names, the static template-derived input artifact inventory, and
the operator readiness files needed to prepare the external capture directory.
When all required `MNEMOSYNE_PROD_*` keys are present, it also confirms
`MNEMOSYNE_PROD_EVIDENCE_DIR` is an existing external directory and
`MNEMOSYNE_PROD_C2PA_TOOL` is an existing external executable. It renders the
manifest in memory, derives the required input artifacts under
`MNEMOSYNE_PROD_EVIDENCE_DIR`, and fails if any are missing. It reports only
relative artifact names, per-artifact `exists` status, and the manifest
check/command/option references that require each artifact via
`required_input_artifacts_detail` and `missing_input_artifacts_detail`. Those
entries include Tier-B lane, strict-audit row, and row-runbook routing metadata
so operators can assign missing evidence without exposing custody paths. The
same JSON also includes `parity_row_readiness`, grouped by Tier-B lane and
runbook. In static no-env mode, each row lists the required relative artifacts
and check references. In env-backed mode, each row also lists missing relative
artifacts, row-scoped input-artifact validation errors, and
`input_artifacts_complete`. This is readiness routing metadata only; it is not a
new release gate and cannot flip a strict-audit row without the production
capture and release-audit path below. It does not print configured absolute
paths or secret values. Invalid configured production paths and executable
references are reported in the same redacted JSON shape through
`environment_errors`, with stable error codes and variable names but without the
configured values.

The wrapper performs these steps:

1. Validates the operator manifest is explicitly production-scoped.
2. Runs `deployment-soak --evidence-dir`.
3. Runs `release-audit --evidence-manifest ... --require-production-validated --require-provider-forbid-local`, which verifies the deployment evidence manifest's report and check SHA-256 digests, rejects artifact paths that resolve outside the evidence bundle, and confirms retained check JSON matches the audited report before auditing.
4. Scans the generated evidence bundle for high-confidence secret material and fails closed if any retained artifact cannot be scanned.
5. Writes `bundle-manifest.json` with SHA-256 hashes for every retained artifact before writing the final summary.

After a successful full capture, reviewers can recheck the completed bundle
offline without production credentials:

```bash
PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"
BUNDLE_DIR=/secure/path/to/mnemosyne-production-evidence
# Set this from the operator's out-of-band capture record, not from summary.json
# inside the bundle under review.
EXPECTED_BUNDLE_FINGERPRINT=sha256:...
"$PYTHON" -m mnemosyne.cli production-evidence-verify \
  "$BUNDLE_DIR" \
  --expected-bundle-fingerprint "$EXPECTED_BUNDLE_FINGERPRINT"
```

This command verifies `summary.json`, `redaction-scan.json`,
`bundle-manifest.json`, every manifest-listed artifact hash/size, the captured
`release-audit.json`, the retained `source-soak-manifest.json`, the retained
`input-artifacts/` inventory, and a fresh offline replay of `release-audit`
against `evidence/manifest.json`. It rejects symlinked or unrecorded retained
input artifacts, fails if preflight paths do not resolve to the retained bundle
files, checks that the retained source and operator soak manifests have matching
production command profiles, and checks that the retained operator manifest plus
nested suite JSON still reference the staged artifacts recorded in
`preflight.json`. It also validates `summary.json.offline_verify.argv` as a
template that requires the reviewer-supplied out-of-band fingerprint, so a
handoff cannot silently point reviewers at a stale bundle path,
self-authorizing expected fingerprint, or non-custody replay command. It does
not contact production
services, does not run `deployment-soak`, does not create production evidence,
and cannot flip any strict-audit row to Done unless the bundle was originally
captured by the production wrapper against deployed infrastructure.
`--expected-bundle-fingerprint` is required for custody review and must come
from the independently retained out-of-band capture record. The
`--internal-consistency-only` flag exists only for local diagnostics and does
not satisfy Tier B custody review.

## Acceptance

The resulting `release-audit.json` must report `ok: true` with no findings, and
`redaction-scan.json` must report `ok: true` with no findings and no skipped
files. `production-evidence-verify` must also report `ok: true` when pointed at
the completed bundle and the independently retained `bundle_fingerprint`
recorded at capture time. Retain `bundle-manifest.json`, `summary.json`, and the
out-of-band `bundle_fingerprint` record as the handoff chain-of-custody record
for the captured files. The offline verifier independently rechecks the retained
`preflight.json`, `source-soak-manifest.json`, and
`operator-soak-manifest.json` for production scope, input-artifact reference
binding, operator attestation, unresolved production placeholders,
copied-manifest custody metadata, source/operator command-profile agreement, and
the frozen production command set. A passing local or compose-only bundle is
useful staging evidence, but it does not satisfy Tier B unless the manifest is
operator asserted and the checks use production infrastructure.

The current strict audit remains incomplete until the production evidence bundle proves:

- Deployed ParadeDB/BM25, Apache AGE, pgvector, embedding, reranker, multimodal, and trainer providers are non-local.
- Live IdP/JWKS, TLS, session-secret custody, KMS/object-key, and residency controls are production-backed.
- Hosted MCP, worker supervision, dashboards, privacy erasure, C2PA trust roots, consolidation providers, and parametric rollback drills pass their existing ops checks.
