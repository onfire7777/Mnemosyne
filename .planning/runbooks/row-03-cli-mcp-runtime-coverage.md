# Row 03 - CLI/MCP Runtime Coverage

## Objective

Prove hosted MCP runtime coverage over production endpoints.

## Real-Infra Dependency

Hosted MCP JSON-RPC and StreamableHTTP endpoints with TLS.

## Gate Commands

Run in the production soak profile:

- `mcp-ops-check`
- `mcp-http-soak`
- `mcp-streamable-http-soak`

## Redaction Requirement

Evidence must not include bearer tokens, session tokens, raw tool payloads, or
tenant-private memory content. Store endpoint class, auth mode, redacted request
shape, response shape, latency, restart/soak status, and findings only.

## Scope Note

This row carries the A11 hosted-MCP transport scope. Local JSON-RPC and
StreamableHTTP paths are already covered; this row requires hosted-endpoint
operator evidence.

## Production Capture

Use the universal Tier B production capture flow in `infra/PRODUCTION-EVIDENCE.md`:
render the production soak manifest, run
`infra/scripts/capture-production-evidence.sh --preflight-only` as setup proof only, then run
`infra/scripts/capture-production-evidence.sh` for the real `deployment-soak` +
`release-audit` capture. The preflight output does not flip this row to Done.
After capture, reviewers may run `"$PYTHON" -m mnemosyne.cli production-evidence-verify` with the retained
`summary.json` `bundle_fingerprint`; this is custody review only and does not
flip this row.

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated --require-provider-forbid-local` passes
with required output shapes present and empty findings.

Done when hosted JSON-RPC and StreamableHTTP soak evidence is in the bundle and
`release-audit` is ok.
