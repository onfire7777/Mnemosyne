#!/bin/sh
# Role-dispatching entrypoint for the mnemo-api / mnemo-consolidator services
# (infra/docker-compose.prod.yml). The role comes from MNEMOSYNE_ROLE; extra
# arguments may be appended per-service via `command:` and are passed through.
set -eu

ROLE="${MNEMOSYNE_ROLE:-api}"

case "$ROLE" in
  api)
    # Hosted HTTP JSON-RPC MCP surface behind Caddy (mcp.mnemo.local -> :8080).
    # MNEMOSYNE_MCP_PRODUCTION_PROFILE=1 makes startup fail closed unless signed
    # sessions, session-secret custody, AES-GCM object encryption, and
    # command-backed object-key custody are configured (see profile env).
    # --stateless: rebuild engine/tools per JSON-RPC call from durable Postgres
    # state so any API replica serves any request (horizontal scale, restart
    # durability) and the hosted MCP evidence proves the stateless contract.
    exec mneme-mcp \
      --backend postgres \
      --http \
      --http-host 0.0.0.0 \
      --http-port "${MNEMOSYNE_MCP_HTTP_PORT:-8080}" \
      --stateless \
      "$@"
    ;;
  consolidator)
    # Sole write + KMS authority. worker-run exits by design after bounded
    # cycles; supervise it in a loop so the container is a long-running worker.
    POLL="${MNEMOSYNE_WORKER_SUPERVISOR_INTERVAL:-5}"
    while :; do
      mneme \
        --backend postgres \
        --queue-backend postgres \
        worker-run \
        --poll-interval "${MNEMOSYNE_WORKER_POLL_INTERVAL:-1}" \
        "$@" || echo "worker-run exited nonzero; retrying in ${POLL}s" >&2
      sleep "$POLL"
    done
    ;;
  mcp-stream)
    # Official MCP SDK StreamableHTTP transport (B3 streamable_http evidence),
    # stateless per-request from durable Postgres like the JSON-RPC facade.
    exec mneme-mcp \
      --backend postgres \
      --sdk-streamable-http \
      --http-host 0.0.0.0 \
      --http-port "${MNEMOSYNE_MCP_HTTP_PORT:-8081}" \
      --sdk-streamable-http-path "${MNEMOSYNE_MCP_STREAMABLE_PATH:-/mcp}" \
      --stateless \
      "$@"
    ;;
  metrics-pusher)
    # Read-only ops-report -> VictoriaMetrics push loop. Keeps the
    # mnemosyne_ops_report_timestamp_seconds / mnemosyne_release_gate_open
    # tripwire series alive so the vmalert rules watch real data.
    exec mneme \
      --backend postgres \
      ops-metrics-push \
      --interval "${MNEMOSYNE_OPS_METRICS_INTERVAL:-60}" \
      "$@"
    ;;
  *)
    echo "Unknown MNEMOSYNE_ROLE: $ROLE (expected api|consolidator|metrics-pusher|mcp-stream)" >&2
    exit 64
    ;;
esac
