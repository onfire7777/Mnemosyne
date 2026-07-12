#!/usr/bin/env bash
# Validate the production MCP mTLS client bundle with a fail-closed expiry floor.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
MIN_VALIDITY_SECONDS=${MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS:-21600}

fail() {
  printf 'production MCP client TLS validation failed: %s\n' "$1" >&2
  exit 65
}

case "$MIN_VALIDITY_SECONDS" in
  '' | *[!0-9]*)
    printf 'production MCP client TLS validation failed: MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS must be an integer of at least 21600\n' >&2
    exit 65
    ;;
esac
if [ "$MIN_VALIDITY_SECONDS" -lt 21600 ]; then
  printf 'production MCP client TLS validation failed: MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS may not weaken the 21600-second floor\n' >&2
  exit 65
fi

if [ "$#" -ne 3 ]; then
  exec "$SCRIPT_DIR/validate-production-tls.sh" "$@"
fi

CANONICAL_ROOT=${MNEMO_SECRETS_DIR:-/secure/outside/repo}/stepca-acme-root.crt
if [ -L "$CANONICAL_ROOT" ] || [ ! -f "$CANONICAL_ROOT" ]; then
  fail 'canonical Caddy client-auth root must be a regular non-symlink file'
fi
canonical_certificate_count=$(
  awk '/-----BEGIN CERTIFICATE-----/{count++} END{print count+0}' "$CANONICAL_ROOT"
) || fail 'canonical Caddy client-auth root could not be read'
[ "$canonical_certificate_count" -eq 1 ] || \
  fail 'canonical Caddy client-auth root must contain exactly one certificate'
cmp -s "$1" "$CANONICAL_ROOT" || \
  fail 'caller root must match the canonical Caddy client-auth root'

export PRODUCTION_TLS_IDENTITY='production MCP client'
export PRODUCTION_TLS_HOSTNAME=${MCP_CLIENT_TLS_HOSTNAME:-mcp-client.mnemo.local}
export PRODUCTION_TLS_PURPOSE=sslclient
export PRODUCTION_TLS_MIN_VALIDITY_SECONDS=$MIN_VALIDITY_SECONDS
exec "$SCRIPT_DIR/validate-production-tls.sh" "$@"
