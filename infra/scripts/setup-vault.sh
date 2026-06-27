#!/usr/bin/env bash
#
# setup-vault.sh — enable the transit secrets engine, create the Mnemosyne
# KEK, install the least-privilege policy, and mint a scoped token for the
# command-backed object-key provider.
#
# After this runs you will have:
#   - transit/ engine enabled
#   - transit key "mnemosyne-objects" (deletion_allowed=true, rotatable)
#   - policy "mnemosyne-transit"
#   - a child token scoped to that policy
#   - infra/vault/out/vault.env (source-able env for the key-provider wrapper)
#
# Requires: docker (compose stack up). Uses the Vault CLI inside the container,
# so no host Vault binary is needed.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.providers.yml"
OUT_DIR="${INFRA_DIR}/vault/out"
mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"

VAULT_ADDR_HOST="${VAULT_ADDR:-http://localhost:8211}"
VAULT_ADDR_IN="http://127.0.0.1:8200"
ROOT_TOKEN="${VAULT_DEV_ROOT_TOKEN_ID:-mnemosyne-dev-root}"
KEY_NAME="${MNEMOSYNE_VAULT_TRANSIT_KEY:-mnemosyne-objects}"
POLICY_NAME="mnemosyne-transit"

vault_exec() {
  docker compose -f "${COMPOSE_FILE}" exec -T \
    -e VAULT_ADDR="${VAULT_ADDR_IN}" \
    -e VAULT_TOKEN="${ROOT_TOKEN}" \
    vault vault "$@"
}

echo "==> Waiting for Vault ..."
for _ in $(seq 1 30); do
  if vault_exec status >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
vault_exec status >/dev/null

echo "==> Enabling transit engine (idempotent) ..."
if vault_exec secrets list -format=json | jq -e '."transit/"' >/dev/null 2>&1; then
  echo "    transit/ already enabled."
else
  vault_exec secrets enable transit
  echo "    transit/ enabled."
fi

echo "==> Creating KEK '${KEY_NAME}' (idempotent) ..."
if vault_exec read "transit/keys/${KEY_NAME}" >/dev/null 2>&1; then
  echo "    key '${KEY_NAME}' already exists."
else
  vault_exec write -f "transit/keys/${KEY_NAME}" type=aes256-gcm96
  echo "    key '${KEY_NAME}' created."
fi
# Allow deletion so crypto-shred of per-object keys can truly delete them.
vault_exec write "transit/keys/${KEY_NAME}/config" deletion_allowed=true >/dev/null

echo "==> Installing policy '${POLICY_NAME}' ..."
docker compose -f "${COMPOSE_FILE}" cp \
  "${INFRA_DIR}/vault/mnemosyne-transit-policy.hcl" \
  vault:/tmp/mnemosyne-transit-policy.hcl
vault_exec policy write "${POLICY_NAME}" /tmp/mnemosyne-transit-policy.hcl

echo "==> Minting a scoped token for the object-key provider ..."
SCOPED_TOKEN="$(vault_exec token create \
  -policy="${POLICY_NAME}" \
  -ttl=24h \
  -display-name=mnemosyne-object-key \
  -format=json | jq -r '.auth.client_token')"
if [ -z "${SCOPED_TOKEN}" ] || [ "${SCOPED_TOKEN}" = "null" ]; then
  echo "ERROR: failed to mint scoped Vault token." >&2
  exit 1
fi

cat > "${OUT_DIR}/vault.env" <<EOF
# Load with infra/scripts/load-env.py; do not shell-source generated env files.
export VAULT_ADDR="${VAULT_ADDR_HOST}"
export VAULT_TOKEN="${SCOPED_TOKEN}"
export MNEMOSYNE_VAULT_TRANSIT_KEY="${KEY_NAME}"
# Mnemosyne CLI wiring (the provider wrapper lives in infra/vault):
export MNEMOSYNE_OBJECT_KEY_COMMAND="${INFRA_DIR}/vault/vault-object-key-provider.py"
EOF
chmod 600 "${OUT_DIR}/vault.env"

echo
echo "==> Done. Vault env written to ${OUT_DIR}/vault.env"
echo "    Addr:        ${VAULT_ADDR_HOST}"
echo "    Transit key: ${KEY_NAME}"
echo "    Policy:      ${POLICY_NAME} (scoped token TTL 24h)"
echo "    Provider:    ${INFRA_DIR}/vault/vault-object-key-provider.py"
echo "    Next:        ./infra/validate/validate-vault.sh"
