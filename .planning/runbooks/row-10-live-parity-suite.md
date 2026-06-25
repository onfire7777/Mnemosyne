# Row 10 - Live Parity Suite

## Objective

Prove final Local/Postgres runtime parity with production adapters enabled where
available.

## Real-Infra Dependency

Optional production adapters enabled for the full compose-Postgres suite and
belief revision check.

## Gate Commands

Run in the production soak/profile process:

- Full compose-Postgres suite with `MNEMOSYNE_POSTGRES_DSN` set.
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
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.

## Acceptance

Operator runs the suite and gate against real infra, evidence is redacted, the
outputs are included in `deployment-soak --evidence-dir` with production scope
and operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local`
passes with required output shapes present and empty findings.

Done when every engine/runtime method is green with production adapters enabled,
`belief-revision-check` is green, there are 0 failures/errors, and final
`release-audit` is ok.
