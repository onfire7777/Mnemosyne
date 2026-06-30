# Production Evidence Capture Runbook

This runbook is the operator handoff for flipping the remaining Tier B parity rows from Partial to Done. It does not add a new gate; it uses the existing `deployment-soak` evidence bundle plus manifest-bound `release-audit --evidence-manifest ... --require-production-validated --require-provider-forbid-local` path.

## Preconditions

- Start with an external no-secret custody packet instead of hand-assembling the
  workspace. The helper copies the render env template, the shared provider
  manifest template, operator docs, packet-local row runbooks under
  `docs/runbooks/`, and a row-scoped gap report into a new absolute directory
  outside the repo. It exits nonzero while operator evidence is still missing;
  that is expected setup feedback, not a failed release gate:

  ```bash
  infra/scripts/prepare-production-evidence-custody.py \
    /secure/path/to/mnemosyne-tier-b-custody
  open /secure/path/to/mnemosyne-tier-b-custody/reports/tier-b-gap-report.md
  ```

  The generated packet is not evidence and cannot flip rows. Use its
  `operator_input_inventory` report section to prepare the three operator edit
  surfaces: `production-render.env`,
  `input-artifacts/provider-manifest.production.json` plus the remaining B1-B10
  input artifacts, and the separate external runtime env file for
  secret-bearing provider/runtime values. The adjacent `capture_blockers`
  section summarizes the current blocked lanes and missing blocker classes so
  dispatcher handoff can start from one machine-readable report field instead
  of re-parsing every row. The packet also writes
  `reports/mnemosyne-production-runtime.env.example` and
  `reports/next-commands.sh`; copy the generated no-secret runtime example to
  the real external runtime env path, set mode `0600`, and fill values there.
  After filling or changing packet inputs, refresh the row-scoped report and
  generated command script without overwriting operator artifacts. Refresh also
  backfills missing read-only packet guidance docs for older packets, but it
  does not overwrite existing copied docs:

  ```bash
  infra/scripts/prepare-production-evidence-custody.py \
    --refresh \
    /secure/path/to/mnemosyne-tier-b-custody
  ```
- Review `infra/templates/production-operator-env.inventory.md` before capture. It is a no-secret name inventory for render placeholders, provider-manifest references, and runtime/secret-custody environment names. Do not fill values in that file.
- Fill the packet's external `production-render.env` with the blank non-secret
  `MNEMOSYNE_PROD_*` values, then pass it to
  `render-production-soak-manifest.sh --env-file`. Do not shell-source render
  env files; the renderer parses them with `infra/scripts/load-env.py` and
  rejects symlinks, group/world-readable files, unexpected keys, unsafe syntax,
  repo-local paths, and missing placeholder keys.
- Populate `MNEMOSYNE_PROD_EVIDENCE_DIR` with the manifest-referenced production input artifacts before running `--check-environment --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env --runtime-env-file /secure/path/to/mnemosyne-production-runtime.env`. The check is no-write and reports the static template-derived artifact inventory plus `parity_row_readiness` grouping even before environment values are complete; after all required `MNEMOSYNE_PROD_*` values are set, including `MNEMOSYNE_PROD_EVIDENCE_DIR`, it fails if required relative artifact names are missing from that external directory and shows which strict-audit row is blocked. Use `infra/templates/production-input-artifacts.checklist.md` as the non-secret operator checklist for the required artifact names.
- Copy `infra/templates/provider-manifest.production.template.json` to `$MNEMOSYNE_PROD_EVIDENCE_DIR/provider-manifest.production.json` and fill the external copy with production provider values or environment-variable references. This file is shared evidence for retrieval, auth/session provider custody, consolidation roles, multimodal/object-key providers, privacy/residency policy, parametric adapters, and the final parity row. It must keep `forbid_local: true` and include every required provider-check subcheck listed in the template. `--check-environment` parses this external manifest when present, reports referenced provider env-var names, and fails before capture if any referenced provider env var is unset in either the process environment or the strict external `--runtime-env-file`; `capture-production-evidence.sh --preflight-only` also rejects manifests missing `forbid_local: true`, missing or unsupported required provider checks, or a non-object `providers` block.
- Provider manifest `command` values must resolve to absolute, non-symlinked, external executable paths. During capture, those command executables are copied into `OUT_ROOT/tool-artifacts/`, retained as mode `0500` custody artifacts, rewritten into the retained provider manifest snapshot, and recorded in `preflight.json.executable_tool_references` with original path, retained snapshot path, size, SHA-256 digest, and provider-manifest field label.
- Provider manifest `command` values must be a single external executable with no arguments after `argv[0]`. Commands such as `/external/python -m provider`, `/bin/sh -c provider`, or `/external/provider --config=/external/config.json` are rejected because only `argv[0]` is retained under `tool-artifacts/`; put provider implementation/config into the deployed executable wrapper or an explicit production input artifact covered by a row runbook.
- `render-production-soak-manifest.sh --check-environment` and `capture-production-evidence.sh --preflight-only` both validate provider-manifest shape plus command executable paths before capture, including relative-path, symlink, repo-local, missing-file, and non-executable failures, so renderer readiness and preflight cannot pass values the capture wrapper or offline verifier will later reject.
- The renderer and capture wrapper both reject symlinked input artifacts. Production capture preflight also rejects skeletal manifests with no retained input artifacts, and `provenance-trust-check` must retain C2PA executable metadata through `--suite` with `tool`/`c2pa_tool`, direct `--c2pa-tool`, or `MNEMOSYNE_C2PA_TOOL`.
- Render `infra/templates/production-soak-manifest.template.json` outside the repo with `infra/scripts/render-production-soak-manifest.sh --output /secure/path/to/production-soak-manifest.json`. Manual edits are only a fallback and must still leave no unresolved `MNEMOSYNE_PROD_*` placeholders; the capture wrapper rejects unresolved placeholders before running production checks.
- `MNEMOSYNE_PROD_EVIDENCE_DIR` and the second positional output-root argument passed to `capture-production-evidence.sh` must be absolute external custody paths outside the repository; output roots must be new and must not already exist. The wrapper does not consume a separate `PREFLIGHT_OUT_ROOT` environment variable.
- Keep raw secrets out of `args` and `global_args`. The production wrapper rejects secret-bearing options such as `--access-token`, `--api-token`, `--github-token`, `--session-secret`, and `--password`, and it fails closed on high-confidence secret material such as JWTs, private-key blocks, GitHub tokens, AWS access keys, and `sk-*` API keys.
- Provide secrets through environment variables, a strict external runtime env
  file, or command/provider files. Required examples include
  `MNEMOSYNE_POSTGRES_DSN`, `MNEMOSYNE_IDP_TOKEN`, `MNEMOSYNE_MCP_TOKEN`, and
  `MNEMOSYNE_MCP_SESSION_TOKEN` where the selected checks need them. Prefer
  `render-production-soak-manifest.sh --runtime-env-file /secure/path/to/mnemosyne-production-runtime.env`
  for readiness validation and
  `capture-production-evidence.sh --env-file /secure/path/to/mnemosyne-production-runtime.env`
  for capture when secret-bearing runtime/provider values should not be shell-sourced;
  the file must be mode `0600`, outside the repo, non-symlinked, and limited to
  names listed in `infra/templates/production-operator-env.inventory.md`.
- The manifest must include:
  - `validation_scope.production_validated: true`
  - `validation_scope.target_environment: "production"`
  - `validation_scope.operator_asserted: true`
- The manifest must include the exact production release profile: every command in the current 28-command set from `src/mnemosyne/cli.py`, with no duplicate or unknown commands.
- The output root must be new and outside this repository. The wrapper rejects repo-local or pre-existing output roots so stale artifacts cannot enter a production bundle and final-directory creation stays race-resistant.
- Every manifest-referenced production input artifact must already exist at an absolute external path before preflight. The wrapper inventories those paths in `preflight.json`, recursively scans referenced directories, and fails closed on missing, symlinked, secret-shaped, non-UTF-8, or over-limit input artifacts. Accepted inputs are snapshotted under `OUT_ROOT/input-artifacts/` with per-file size and SHA-256 metadata, and the copied operator manifest is rewritten to use those immutable snapshots so later mutation of the external source paths cannot change the capture inputs. Provenance trust-suite metadata is hashed after nested asset-path rewrites, so `preflight.json` describes the retained staged suite exactly.
- `MNEMOSYNE_PROD_C2PA_TOOL` is the absolute canonical path to the deployed c2patool-compatible executable. Preflight verifies it exists outside the repository, is not reached through a symlink or non-canonical path, and is executable. It records the canonical path, size, and SHA-256 digest under `executable_tool_references`, copies the executable into `OUT_ROOT/tool-artifacts/`, rewrites direct `--c2pa-tool` and retained suite `tool`/`c2pa_tool` references to that snapshot, emits `tool-env.sh` when the `MNEMOSYNE_C2PA_TOOL` fallback must be pointed at the retained snapshot for the soak, and marks the retained binary under `redaction-scan.json.binary_custody_files`.
- Production manifests must not pass `ops-report --dashboard-html` or `ops-report --dashboard-package-dir`; those are generated output targets, not input artifacts, and the capture wrapper rejects them before snapshotting custody inputs.
- For `provenance-trust-check --suite`, nested suite `asset_path` and `c2pa_asset_path` values are also treated as production input artifacts. Preflight snapshots those assets and rewrites the staged suite JSON to point at the immutable snapshots. Inline `--suite-json` is rejected for production capture because nested paths cannot be custody-rewritten safely.

## Capture

Run the production wrapper from the repository root:

```bash
infra/scripts/prepare-production-evidence-custody.py \
  /secure/path/to/mnemosyne-tier-b-custody
open infra/templates/production-operator-env.inventory.md
# Fill /secure/path/to/mnemosyne-tier-b-custody/production-render.env outside this repository.
infra/scripts/prepare-production-evidence-custody.py \
  --runtime-env-file /secure/path/to/mnemosyne-production-runtime.env \
  --refresh \
  /secure/path/to/mnemosyne-tier-b-custody
# Once refresh reports ready_for_capture=true, either run the generated
# script below or run the expanded sequence that follows:
# /secure/path/to/mnemosyne-tier-b-custody/reports/next-commands.sh
infra/scripts/render-production-soak-manifest.sh \
  --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env \
  --runtime-env-file /secure/path/to/mnemosyne-production-runtime.env \
  --check-environment
infra/scripts/render-production-soak-manifest.sh \
  --env-file /secure/path/to/mnemosyne-tier-b-custody/production-render.env \
  --runtime-env-file /secure/path/to/mnemosyne-production-runtime.env \
  --output /secure/path/to/production-soak-manifest.json
infra/scripts/capture-production-evidence.sh \
  --env-file /secure/path/to/mnemosyne-production-runtime.env \
  --preflight-only \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-preflight
infra/scripts/capture-production-evidence.sh \
  --env-file /secure/path/to/mnemosyne-production-runtime.env \
  --fingerprint-record-output /secure/path/to/mnemosyne-production-bundle-fingerprint.json \
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
the operator readiness files needed to prepare the external capture directory,
including `production-operator-env.inventory.md` as the names-only inventory for
render, provider, runtime, and secret-custody env preparation.
For provider/readiness validation, pass the same strict external runtime file
with `--runtime-env-file /secure/path/to/mnemosyne-production-runtime.env`.
That file is parsed through `load-env.py --allow-missing`, must be absolute,
external, non-symlinked, mode `0600`, and may contain only names from
`production-operator-env.inventory.md` or variables referenced by the provider
manifest. Values are loaded only into the readiness process, never written to
the rendered manifest or reports. For automation, it keeps the legacy
`present`/`missing` placeholder fields and
also emits explicit `present_environment`, `present_environment_count`,
`missing_environment`, and `missing_environment_count` aliases. Row readiness
entries carry both `row` and `strict_audit_row` so downstream handoff scripts do
not have to infer strict-audit row numbers from lane names.
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

Full production capture must write the out-of-band fingerprint record outside
the bundle under review:

```bash
FINGERPRINT_RECORD=/secure/path/to/mnemosyne-production-bundle-fingerprint.json
infra/scripts/capture-production-evidence.sh \
  --env-file /secure/path/to/mnemosyne-production-runtime.env \
  --fingerprint-record-output "$FINGERPRINT_RECORD" \
  /secure/path/to/production-soak-manifest.json \
  /secure/path/to/mnemosyne-production-evidence
```

After a successful full capture, reviewers can recheck the completed bundle
offline without production credentials:

The fingerprint record also includes a `reviewer_handoff` object with a
suggested external verifier report path and argv template. Treat it as a
no-secret convenience for replaying the review command; the
`production-evidence-verify` report remains the custody authority.

```bash
PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"
BUNDLE_DIR=/secure/path/to/mnemosyne-production-evidence
FINGERPRINT_RECORD=/secure/path/to/mnemosyne-production-bundle-fingerprint.json
VERIFY_REPORT=/secure/path/to/mnemosyne-production-evidence-verify.json
"$PYTHON" -m mnemosyne.cli production-evidence-verify \
  "$BUNDLE_DIR" \
  --fingerprint-record "$FINGERPRINT_RECORD" \
  --report-output "$VERIFY_REPORT"
```

This command verifies `summary.json`, `redaction-scan.json`,
`bundle-manifest.json`, every manifest-listed artifact hash/size, the captured
`release-audit.json`, the retained `source-soak-manifest.json`, the retained
`input-artifacts/` inventory, retained `tool-artifacts/` executable snapshots,
and a fresh offline replay of `release-audit`
against `evidence/manifest.json`. It rejects symlinked or unrecorded retained
input artifacts, fails if preflight paths do not resolve to the retained bundle
files, checks that the retained source and operator soak manifests have matching
production command profiles, and checks that the retained operator manifest plus
nested suite JSON still reference the staged artifacts recorded in
`preflight.json`. A completed bundle must have a non-empty
`preflight.json.required_input_artifacts` list, retained `input-artifacts/`
directory, and `preflight.json.parity_row_readiness` value matching those
retained snapshots. `summary.json.parity_row_readiness` mirrors that same
non-secret row-routing metadata and records
`row_review_source=preflight.json.parity_row_readiness` so reviewers can route a
completed bundle without treating the summary as a separate authority.
`production-evidence-verify` also emits a non-gating `row_review` object sourced
only from retained `preflight.json.parity_row_readiness`, including row counts
and any row-local missing-artifact/error routing. Provider manifest command
fields and C2PA verifier paths must also have matching retained
executable snapshot metadata in
`preflight.json.executable_tool_references`; offline verification checks the
retained `tool-artifacts/` bytes rather than trusting mutable external paths.
It also rejects retained provider-manifest commands that contain any arguments
after `argv[0]`, because only the executable is retained under
`tool-artifacts/` and extra arguments can dispatch unretained scripts, modules,
shell commands, or config files during offline review.
It also validates `summary.json.offline_verify.argv` as a
template that requires the reviewer-supplied out-of-band fingerprint, so a
handoff cannot silently point reviewers at a stale bundle path,
self-authorizing expected fingerprint, or non-custody replay command. It does
not contact production
services, does not run `deployment-soak`, does not create production evidence,
and cannot flip any strict-audit row to Done unless the bundle was originally
captured by the production wrapper against deployed infrastructure.
`production-evidence-verify` reports the expected out-of-band fingerprint,
retained `bundle-manifest.json` fingerprint, recomputed current-files
fingerprint, diagnostic-only `reviewer_guidance`, and retained preflight row
review. For custody review with `--fingerprint-record` or
`--expected-bundle-fingerprint`, `--report-output` is required unless the
operator is running diagnostic `--internal-consistency-only`;
it writes the same JSON report to an absolute, non-existing path outside the
bundle under review so the review artifact can be retained without changing the
bundle fingerprint.
`--fingerprint-record` is the preferred custody-review input and must point to
the independently retained out-of-band fingerprint record. The legacy
`--expected-bundle-fingerprint` fallback is still accepted when populated from
that record, but reviewers should avoid manual transcription. The
`--internal-consistency-only` flag exists only for local diagnostics and does
not satisfy Tier B custody review. If the expected fingerprint mismatches the
retained bundle, stop the review: do not copy a replacement value from the
bundle under review. Reconcile the external fingerprint record, the reviewed
bundle path, and `bundle-manifest.json`; if they cannot be reconciled, rerun the
production capture wrapper and retain a new external fingerprint record. If
multiple fingerprint modes are present, rerun in exactly one mode.

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
