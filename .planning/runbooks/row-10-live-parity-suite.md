# Row 10 - Live Parity Suite

## Objective

Prove final Local/Postgres runtime parity with production adapters enabled where
available.

## Real-Infra Dependency

Optional production adapters enabled for the full compose-Postgres suite and
belief revision check.

## Gate Commands

Run for the row-10 operator evidence pass:

- `MNEMOSYNE_POSTGRES_DSN="$PRODUCTION_POSTGRES_DSN" .venv/bin/python -m pytest -q`
- `belief-revision-check`

The full suite is not itself one of the frozen 28 production soak manifest
commands, so retain its redacted output and coverage summary as row-10 input
evidence before running the production soak/profile process. Place that
redacted suite artifact at
`$MNEMOSYNE_PROD_EVIDENCE_DIR/row-10-full-suite-evidence.json` before rendering
the production soak manifest; the template retains it through
`checks[].input_artifacts` so preflight snapshots, hashes, redaction-scans, and
custody-verifies it without adding a new command-line argument to
`belief-revision-check`.

## Redaction Requirement

Evidence must not include raw tenant data, queries, documents, tokens, keys,
credentials, or provider payloads. Store suite counts, covered engine/runtime
method families, adapter names, redacted failure summaries, and command output
shapes.

## Scope Note

Local/Postgres direct configured lexical/graph adapter parity is now covered.
Final done still requires every engine/runtime method green with production
adapters enabled.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest to `SOAK_MANIFEST`, run
`infra/scripts/capture-production-evidence.sh --preflight-only "$SOAK_MANIFEST" "$PREFLIGHT_OUT_ROOT"`
as setup proof only, then run
`infra/scripts/capture-production-evidence.sh "$SOAK_MANIFEST" "$OUT_ROOT"` for the real
`deployment-soak` + `release-audit` capture. The preflight output does not flip this row to Done.
Use absolute external paths outside the repo for `SOAK_MANIFEST`, `PREFLIGHT_OUT_ROOT`, `OUT_ROOT`, and the `MNEMOSYNE_PROD_EVIDENCE_DIR` input-artifact directory.
After capture, reviewers must run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`, retained `source-soak-manifest.json` custody,
and source/operator command-profile agreement; offline custody verification must pass before this row can flip Done.

## Acceptance

Operator runs the suite and gate against real infra, evidence is redacted, the
suite artifact is retained through `checks[].input_artifacts` under
`OUT_ROOT/input-artifacts/`, `deployment-soak` runs with production scope and
operator attestation, and `release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
passes with required output shapes present and empty findings.

Done when every engine/runtime method is green with production adapters enabled,
`belief-revision-check` is green, there are 0 failures/errors, and final
`release-audit` is ok.
The full wrapper summary must have `release_audit_ok=true`,
`redaction_scan_ok=true`, no redaction findings or skipped files, a retained
`bundle-manifest.json`/fingerprint, and passing `production-evidence-verify`.

## Operator Resume Signal

Resume this row after the operator reports `row-10 evidence captured` and the
final live parity suite evidence bundle passes
`release-audit --evidence-manifest "$OUT_ROOT/evidence/manifest.json" --require-production-validated --require-provider-forbid-local`
plus `production-evidence-verify`.

After all 10 strict-audit rows are Done and attestation is recorded, resume the
v1.0 handoff with `v1.0 signed off`.
Use `skip operator gates` only to explicitly defer the production evidence pass.
