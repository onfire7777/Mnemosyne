#!/usr/bin/env bash
#
# keycloak-token.sh — print a fresh Keycloak ID token (JWT) on stdout.
# Useful because ID tokens expire; validation re-mints before each run.
#
#   ./infra/scripts/keycloak-token.sh [username] [password]
#
# Defaults to agent-a / agent-a-password.
set -euo pipefail

KC_BASE="${KEYCLOAK_BASE_URL:-http://localhost:8089}"
REALM="mnemosyne"
CLIENT_ID="${KEYCLOAK_CLIENT_ID:-mnemosyne-cli}"
CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-mnemosyne-cli-secret}"
TOKEN_URL="${KEYCLOAK_TOKEN_URL:-${KC_BASE}/realms/${REALM}/protocol/openid-connect/token}"

USER="${1:-${KEYCLOAK_EXCHANGE_USER:-agent-a}}"
PASS="${2:-${KEYCLOAK_EXCHANGE_PASS:-agent-a-password}}"

curl -fsS -X POST "${TOKEN_URL}" \
  -d "grant_type=password" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "username=${USER}" \
  -d "password=${PASS}" \
  -d "scope=openid mnemosyne" | jq -r '.id_token'
