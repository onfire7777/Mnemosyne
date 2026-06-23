#!/usr/bin/env bash
#
# down.sh — tear down the provider stack. Pass --volumes to also drop the
# Keycloak data volume (full reset).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.providers.yml"

if [ "${1:-}" = "--volumes" ]; then
  echo "==> Tearing down stack AND volumes ..."
  docker compose -f "${COMPOSE_FILE}" --profile c2pa down -v
else
  echo "==> Tearing down stack (keeping volumes) ..."
  docker compose -f "${COMPOSE_FILE}" --profile c2pa down
fi
echo "==> Done."
