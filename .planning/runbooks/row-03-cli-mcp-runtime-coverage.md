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

## Acceptance

Operator runs the gates against real infra, evidence is redacted, the outputs
are included in `deployment-soak --evidence-dir` with production scope and
operator attestation, and `release-audit --require-production-validated` passes
with required output shapes present and empty findings.

Done when hosted JSON-RPC and StreamableHTTP soak evidence is in the bundle and
`release-audit` is ok.
