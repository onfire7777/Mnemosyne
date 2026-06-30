#!/usr/bin/env bash
#
# setup-keycloak.sh — seed the running Keycloak with the Mnemosyne realm and
# emit the OIDC settings Mnemosyne's `session-exchange` / `idp-jwks-live-check`
# need. Idempotent: re-importing an existing realm is skipped.
#
# After this runs you will have:
#   - realm `mnemosyne` with client `mnemosyne-cli` (direct-access grant)
#   - users analyst-a (operator, trust 0) and agent-a (agent, trust 3)
#   - claims tenant_id / mnemosyne_role / mnemosyne_source_trust_tier / jti
#   - auth_time / acr / amr for the MFA-gated production authz-policy contract
#   - infra/keycloak/out/oidc.env  (source-able OIDC env for Mnemosyne)
#   - infra/keycloak/out/jwks.json (snapshot of the live JWKS)
#
# Requires: docker (compose stack up), curl, jq, python3.
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.providers.yml"
OUT_DIR="${INFRA_DIR}/keycloak/out"
mkdir -p "${OUT_DIR}"
chmod 700 "${OUT_DIR}"

KC_BASE="${KEYCLOAK_BASE_URL:-http://localhost:8089}"
REALM="mnemosyne"
CLIENT_ID="mnemosyne-cli"
CLIENT_SECRET="mnemosyne-cli-secret"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
ADMIN_PASS="${KEYCLOAK_ADMIN_PASS:-admin}"
ISSUER="${KC_BASE}/realms/${REALM}"
JWKS_URL="${ISSUER}/protocol/openid-connect/certs"
TOKEN_URL="${ISSUER}/protocol/openid-connect/token"
AUDIENCE="mnemosyne"

# Username/password used to mint a real ID token for validation.
EXCHANGE_USER="${KEYCLOAK_EXCHANGE_USER:-agent-a}"
EXCHANGE_PASS="${KEYCLOAK_EXCHANGE_PASS:-agent-a-password}"

compose() { docker compose -f "${COMPOSE_FILE}" "$@"; }

echo "==> Waiting for Keycloak admin endpoint at ${KC_BASE} ..."
for _ in $(seq 1 60); do
  if curl -fsS "${KC_BASE}/realms/master/.well-known/openid-configuration" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "${KC_BASE}/realms/master/.well-known/openid-configuration" >/dev/null

echo "==> Importing realm '${REALM}' (idempotent) ..."
# kcadm.sh runs inside the container; the realm JSON is bind-mounted via the
# admin import path. We copy then import so an existing realm is left alone.
compose cp "${INFRA_DIR}/keycloak/realm-mnemosyne.json" keycloak:/tmp/realm-mnemosyne.json

compose exec -T keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 \
  --realm master \
  --user "${ADMIN_USER}" \
  --password "${ADMIN_PASS}"

if compose exec -T keycloak /opt/keycloak/bin/kcadm.sh get "realms/${REALM}" >/dev/null 2>&1; then
  echo "    realm '${REALM}' already exists; leaving as-is."
else
  compose exec -T keycloak /opt/keycloak/bin/kcadm.sh create realms \
    -f /tmp/realm-mnemosyne.json
  echo "    realm '${REALM}' created."
fi

echo "==> Fetching live JWKS ..."
for _ in $(seq 1 30); do
  if curl -fsS "${JWKS_URL}" -o "${OUT_DIR}/jwks.json" 2>/dev/null; then
    break
  fi
  sleep 2
done
jq -e '.keys | length > 0' "${OUT_DIR}/jwks.json" >/dev/null
echo "    JWKS written to ${OUT_DIR}/jwks.json ($(jq '.keys | length' "${OUT_DIR}/jwks.json") key(s))."

echo "==> Minting a real ID token for ${EXCHANGE_USER} (direct-access grant) ..."
TOKEN_RESPONSE="$(curl -fsS -X POST "${TOKEN_URL}" \
  -d "grant_type=password" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "username=${EXCHANGE_USER}" \
  -d "password=${EXCHANGE_PASS}" \
  -d "scope=openid mnemosyne")"
ID_TOKEN="$(echo "${TOKEN_RESPONSE}" | jq -r '.id_token')"
if [ -z "${ID_TOKEN}" ] || [ "${ID_TOKEN}" = "null" ]; then
  echo "ERROR: no id_token returned. Response was:" >&2
  echo "${TOKEN_RESPONSE}" >&2
  exit 1
fi
printf '%s' "${ID_TOKEN}" > "${OUT_DIR}/id_token.jwt"
chmod 600 "${OUT_DIR}/id_token.jwt"

# Decode the claim set so the operator can eyeball the mapping.
echo "==> ID token claims (for verification):"
python3 - "${ID_TOKEN}" <<'PY'
import base64, json, sys
tok = sys.argv[1].split(".")[1]
tok += "=" * (-len(tok) % 4)
claims = json.loads(base64.urlsafe_b64decode(tok))
keep = (
    "iss",
    "aud",
    "sub",
    "exp",
    "auth_time",
    "acr",
    "amr",
    "jti",
    "tenant_id",
    "mnemosyne_role",
    "mnemosyne_source_trust_tier",
)
print(json.dumps({k: claims.get(k) for k in keep}, indent=2, sort_keys=True))
PY

cat > "${OUT_DIR}/oidc.env" <<EOF
# Load with infra/scripts/load-env.py; do not shell-source generated env files.
export MNEMOSYNE_IDP_ISSUER="${ISSUER}"
export MNEMOSYNE_IDP_AUDIENCE="${AUDIENCE}"
export MNEMOSYNE_IDP_JWKS_URL="${JWKS_URL}"
# Keycloak dev mode serves JWKS over http; allow the insecure URL locally only.
export MNEMOSYNE_IDP_ALLOW_INSECURE_JWKS_URL="1"
export MNEMOSYNE_IDP_TENANT_CLAIM="tenant_id"
export MNEMOSYNE_IDP_USER_CLAIM="sub"
export MNEMOSYNE_IDP_ROLE_CLAIM="mnemosyne_role"
export MNEMOSYNE_IDP_TRUST_CLAIM="mnemosyne_source_trust_tier"
export MNEMOSYNE_IDP_SESSION_ID_CLAIM="jti"
export MNEMOSYNE_IDP_ALGORITHMS="RS256"
export MNEMOSYNE_IDP_TOKEN="${ID_TOKEN}"
# Token URL + client creds in case you want to mint fresh tokens:
export KEYCLOAK_TOKEN_URL="${TOKEN_URL}"
export KEYCLOAK_CLIENT_ID="${CLIENT_ID}"
export KEYCLOAK_CLIENT_SECRET="${CLIENT_SECRET}"
EOF
chmod 600 "${OUT_DIR}/oidc.env"

echo
echo "==> Done. OIDC env written to ${OUT_DIR}/oidc.env"
echo "    Issuer:   ${ISSUER}"
echo "    Audience: ${AUDIENCE}"
echo "    JWKS:     ${JWKS_URL}"
echo "    Next:     ./infra/validate/validate-keycloak.sh"
