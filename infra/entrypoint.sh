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
    exec mneme-mcp \
      --backend postgres \
      --http \
      --http-host 0.0.0.0 \
      --http-port "${MNEMOSYNE_MCP_HTTP_PORT:-8080}" \
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
  *)
    echo "Unknown MNEMOSYNE_ROLE: $ROLE (expected api|consolidator)" >&2
    exit 64
    ;;
esac
