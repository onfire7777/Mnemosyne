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

## Acceptance

Operator runs the suite and gate against real infra, evidence is redacted, the
outputs are included in `deployment-soak --evidence-dir` with production scope
and operator attestation, and `release-audit --require-production-validated`
passes with required output shapes present and empty findings.

Done when every engine/runtime method is green with production adapters enabled,
`belief-revision-check` is green, there are 0 failures/errors, and final
`release-audit` is ok.
