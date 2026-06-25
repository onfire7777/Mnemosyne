# Row 10 - Live Parity Suite

## Objective

Prove final Local/Postgres runtime parity with production adapters enabled where
available.

## Real-Infra Dependency

Optional production adapters enabled for the full compose-Postgres suite and
belief revision check.

## Precondition

The full compose-Postgres suite with `MNEMOSYNE_POSTGRES_DSN` set must already
be green with production-equivalent adapters enabled where available. That suite
is supporting runtime evidence; it is not itself one of the frozen 28 production
soak manifest commands.

## Gate Commands

Run in the production soak/profile process:

- `belief-revision-check`

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
After capture, reviewers may run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`; this is custody review only and does not
flip this row.

## Acceptance

Operator runs the suite and gate against real infra, evidence is redacted, the
outputs are included in `deployment-soak --evidence-dir` with production scope
and operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local`
passes with required output shapes present and empty findings.

Done when every engine/runtime method is green with production adapters enabled,
`belief-revision-check` is green, there are 0 failures/errors, and final
`release-audit` is ok.
