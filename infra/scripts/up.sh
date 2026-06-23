#!/usr/bin/env bash
#
# up.sh — bring up the real-services provider stack (Keycloak + Vault), build
# the c2patool image, and wait for health.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.providers.yml"

echo "==> Starting Keycloak + Vault ..."
docker compose -f "${COMPOSE_FILE}" up -d keycloak vault

echo "==> Building + starting the c2pa helper container ..."
docker compose -f "${COMPOSE_FILE}" --profile c2pa up -d --build c2pa || \
  echo "    (c2pa image build skipped/failed; setup-c2pa.sh will build it)"

echo "==> Waiting for healthchecks (Keycloak can take ~40s) ..."
deadline=$(( $(date +%s) + 180 ))
while :; do
  kc="$(docker inspect -f '{{.State.Health.Status}}' mnemosyne-providers-keycloak-1 2>/dev/null || echo missing)"
  vt="$(docker inspect -f '{{.State.Health.Status}}' mnemosyne-providers-vault-1 2>/dev/null || echo missing)"
  echo "    keycloak=${kc} vault=${vt}"
  if [ "${kc}" = "healthy" ] && [ "${vt}" = "healthy" ]; then
    break
  fi
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    echo "WARNING: services not all healthy before timeout; check 'docker compose -f ${COMPOSE_FILE} ps'." >&2
    break
  fi
  sleep 5
done

echo
echo "==> Stack is up. Next: ./infra/scripts/setup-all.sh"
docker compose -f "${COMPOSE_FILE}" ps
