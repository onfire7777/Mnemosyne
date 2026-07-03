# Phase 4 Plan: C4 MCP Front-End Gate

**Spec:** `docs/superpowers/specs/2026-07-01-native-acceleration-design.md` section 4.4.
**Status:** Evidence-gated; implementation deferred.
**Branch context:** planned after Phase 3 provider consolidation.

## Goal

Decide whether to build the C4 `mneme-native` Rust MCP front-end and warm Python
daemon without weakening the existing Python MCP production/session controls.

The C4 implementation is not automatically justified by the Phase 0-3 work.
It proceeds only when measured client workflow evidence shows that per-session
Python process startup is a material user-facing bottleneck.

## Current Evidence

Fresh local measurements on 2026-07-03 from `/Users/admin/Mnemosyne`:

| Probe | Median | Notes |
|---|---:|---|
| `import mnemosyne` | 21.8 ms | Package import stays light. |
| `import mnemosyne.cli` | 63.1 ms | Phase 1 A4 target remains met. |
| `import mnemosyne.mcp_server` | 126.4 ms | MCP import still heavier than CLI. |
| `mneme-mcp --self-test` | 161.5 ms | Local deployment preflight, temp store. |
| stdio `initialize` | 115.5 ms | Real newline JSON-RPC subprocess path. |
| stdio `initialize` + `tools/list` | 115.8 ms | Tools list adds negligible local cost. |

Verification:

```bash
uv run --locked pytest tests/test_import_time.py -q
# 4 passed
```

Interpretation: the pure-Python CLI target is already met, and the current local
MCP stdio startup is roughly 116 ms median. That misses the spec's optional
50 ms `mneme-native` handshake target, but it is not yet enough evidence that a
warm daemon is worth adding and operating. The missing proof is a real client
workflow where repeated per-session process spawn materially affects latency,
UX, or resource use.

## Non-Goals

- Do not replace the Python MCP server.
- Do not weaken `MNEMOSYNE_MCP_PRODUCTION_PROFILE` or
  `MNEMOSYNE_MCP_REQUIRE_SESSION` behavior.
- Do not reconstruct session claims in Rust from tool arguments.
- Do not enable loopback Streamable HTTP by default.
- Do not claim Tier-B, blueprint parity, or production readiness from this phase.

## Gate

C4 implementation may start only after all of the following are true:

1. A real client workflow shows repeated `mneme-mcp` spawn/handshake cost in a
   captured trace, not just a synthetic one-shot process timer.
2. The trace includes p50/p95 startup, initialize, tools-list, first tool-call,
   and steady-state warm-call timings.
3. The trace identifies whether latency is dominated by Python import, durable
   store initialization, object/key custody, queue setup, or client orchestration.
4. The operator accepts the additional daemon lifecycle surface: socket path,
   ownership, restart behavior, stale-daemon cleanup, config fingerprinting,
   and failure diagnostics.

If the evidence stays near today's local numbers, keep the current Python MCP
entry point and spend Phase 5 on final claim hygiene instead.

## Implementation Tasks If Gate Opens

### T1. Trace Harness

- Add a benchmark harness for stdio MCP startup and a real client loop.
- Record p50/p95 for spawn, `initialize`, `tools/list`, first read-only call,
  warm read-only call, and process teardown.
- Store results under `eval/` with redacted command/env metadata.

### T2. Daemon Contract

- Define the Unix socket location, permissions, peer-uid check, config
  fingerprint, and binary-version identity.
- Ensure a different config gets a different daemon.
- Define stale-daemon cleanup and user-facing diagnostics.

### T3. Rust Front-End

- Build `mneme-native` with `rmcp` only after T1/T2 are accepted.
- Forward raw session tokens over the local socket to the Python daemon.
- Keep the Rust layer transport-only; it must not authorize from tool args or
  mint/reconstruct identity.

### T4. Compatibility And Tests

- Cover every `TOOL_SPEC` entry through the front-end.
- Verify initialize/tools-list/tool-call parity with Python JSON-RPC and SDK
  surfaces.
- Test production-profile refusal paths, signed-session binding, socket
  permissions, wrong-uid/wrong-config rejection, and daemon restart behavior.

### T5. Docs And Rollout

- Keep the feature off by default behind an explicit command/flag.
- Document that first request after auto-spawn still pays Python daemon startup.
- Add operator troubleshooting for socket ownership, config mismatch, and
  daemon logs.

## Exit Criteria

- Evidence packet demonstrates the need for C4 on a real workflow.
- `mneme-native` MCP handshake p95 is <= 50 ms after daemon warmup.
- First-request auto-spawn latency is measured and documented honestly.
- Python MCP parity suite and production-profile/session tests remain green.
- No default provider/runtime flip occurs without a separate bake-off decision.
