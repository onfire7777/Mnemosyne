#!/usr/bin/env bash
# Validate the production Vault server bundle against the current step-ca root.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
export PRODUCTION_TLS_IDENTITY='production Vault'
export PRODUCTION_TLS_HOSTNAME=${VAULT_TLS_HOSTNAME:-vault.mnemo.local}
export PRODUCTION_TLS_PURPOSE=sslserver
export PRODUCTION_TLS_MIN_VALIDITY_SECONDS=${VAULT_TLS_MIN_VALIDITY_SECONDS:-0}
exec "$SCRIPT_DIR/validate-production-tls.sh" "$@"
