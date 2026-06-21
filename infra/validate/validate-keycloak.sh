#!/usr/bin/env bash
#
# validate-keycloak.sh — exercise Mnemosyne against the real Keycloak OIDC/JWKS.
#
# Mints a fresh ID token, runs `idp-jwks-live-check` (no token minted) and
# `session-exchange` (mints a Mnemosyne session), and asserts the claim mapping
# round-trips: tenant-a / agent / trust-tier 3.
#
# Requires: the providers stack up + setup-keycloak.sh already run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"
KC_OUT="${INFRA_DIR}/keycloak/out"

# Locate a Mnemosyne Python entrypoint.
PYTHON="${MNEMOSYNE_PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
    PYTHON="${REPO_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi
MN=("${PYTHON}" -m mnemosyne.cli)

# shellcheck source=/dev/null
source "${KC_OUT}/oidc.env"

echo "==> Minting a fresh ID token (agent-a) ..."
FRESH_TOKEN="$("${INFRA_DIR}/scripts/keycloak-token.sh" agent-a agent-a-password)"
export MNEMOSYNE_IDP_TOKEN="${FRESH_TOKEN}"

# A local session secret so session-exchange can mint a Mnemosyne session.
export MNEMOSYNE_SESSION_SECRET="${MNEMOSYNE_SESSION_SECRET:-mnemosyne-local-session-secret}"

echo
echo "==> idp-jwks-live-check (preflight; does NOT mint a session) ..."
( cd "${REPO_DIR}" && "${MN[@]}" idp-jwks-live-check \
    --idp-token "${MNEMOSYNE_IDP_TOKEN}" \
    --idp-jwks-url "${MNEMOSYNE_IDP_JWKS_URL}" \
    --idp-allow-insecure-jwks-url \
    --idp-issuer "${MNEMOSYNE_IDP_ISSUER}" \
    --idp-audience "${MNEMOSYNE_IDP_AUDIENCE}" \
    --idp-algorithm RS256 ) | tee "${KC_OUT}/live-check.json" | jq '.'

echo
echo "==> session-exchange (validates token, mints Mnemosyne session) ..."
RESULT="$( cd "${REPO_DIR}" && "${MN[@]}" \
    --session-secret "${MNEMOSYNE_SESSION_SECRET}" \
    session-exchange \
      --idp-token "${MNEMOSYNE_IDP_TOKEN}" \
      --idp-jwks-url "${MNEMOSYNE_IDP_JWKS_URL}" \
      --idp-allow-insecure-jwks-url \
      --idp-issuer "${MNEMOSYNE_IDP_ISSUER}" \
      --idp-audience "${MNEMOSYNE_IDP_AUDIENCE}" \
      --idp-algorithm RS256 )"
echo "${RESULT}" | jq '.'
echo "${RESULT}" > "${KC_OUT}/session-exchange.json"

echo
echo "==> Asserting claim mapping (tenant-a / agent / trust 3) ..."
echo "${RESULT}" | jq -e '
  .ok == true
  and .identity.tenant_id == "tenant-a"
  and .identity.role == "agent"
  and .identity.source_trust_tier == 3
  and (.session_token | type == "string")
' >/dev/null && echo "    OK: real OIDC token exchanged into a Mnemosyne session." \
  || { echo "    FAIL: claim mapping mismatch." >&2; exit 1; }

echo
echo "==> Negative test: a token with the wrong audience must be rejected ..."
# Re-sign nothing; instead point at a bogus audience and expect a nonzero exit.
if ( cd "${REPO_DIR}" && "${MN[@]}" \
      --session-secret "${MNEMOSYNE_SESSION_SECRET}" \
      session-exchange \
        --idp-token "${MNEMOSYNE_IDP_TOKEN}" \
        --idp-jwks-url "${MNEMOSYNE_IDP_JWKS_URL}" \
        --idp-allow-insecure-jwks-url \
        --idp-issuer "${MNEMOSYNE_IDP_ISSUER}" \
        --idp-audience "wrong-audience" \
        --idp-algorithm RS256 ) >/dev/null 2>&1; then
  echo "    FAIL: wrong audience was accepted." >&2
  exit 1
else
  echo "    OK: wrong audience correctly rejected (fail-closed)."
fi

echo
echo "==> Keycloak validation PASSED."
