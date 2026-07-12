#!/usr/bin/env bash
# Validate the production Vault leaf bundle against the current step-ca root.
# Prints no certificate, key, token, path, or digest material.
set -euo pipefail

fail() {
  printf 'production Vault TLS validation failed: %s\n' "$1" >&2
  exit 65
}

if [ "$#" -ne 3 ]; then
  printf 'usage: %s ROOT_CA_PEM VAULT_CERT_BUNDLE_PEM VAULT_PRIVATE_KEY_PEM\n' "$0" >&2
  exit 64
fi

ROOT_CA=$1
CERT_BUNDLE=$2
PRIVATE_KEY=$3
HOSTNAME=${VAULT_TLS_HOSTNAME:-vault.mnemo.local}

command -v openssl >/dev/null 2>&1 || fail 'openssl is required'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'

for path in "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY"; do
  [ ! -L "$path" ] || fail 'certificate inputs must not be symlinks'
  [ -f "$path" ] || fail 'root, certificate bundle, and private key must be regular files'
done

python3 - "$PRIVATE_KEY" <<'PY' || fail 'private key must not be group/world accessible'
import os
import sys

raise SystemExit(bool(os.stat(sys.argv[1], follow_symlinks=False).st_mode & 0o077))
PY

certificate_count=$(awk '/-----BEGIN CERTIFICATE-----/{count++} END{print count+0}' "$CERT_BUNDLE")
[ "$certificate_count" -ge 2 ] || fail 'Vault certificate file must contain the leaf and issuing intermediate'

openssl verify \
  -verify_hostname "$HOSTNAME" \
  -purpose sslserver \
  -CAfile "$ROOT_CA" \
  -untrusted "$CERT_BUNDLE" \
  "$CERT_BUNDLE" >/dev/null 2>&1 || \
  fail 'leaf bundle does not validate against the current root CA and hostname'

cert_key_digest=$(
  openssl x509 -in "$CERT_BUNDLE" -pubkey -noout 2>/dev/null |
    openssl pkey -pubin -outform DER 2>/dev/null |
    openssl dgst -sha256 2>/dev/null
) || fail 'certificate public key could not be read'
private_key_digest=$(
  openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null |
    openssl dgst -sha256 2>/dev/null
) || fail 'private key could not be read'
[ "$cert_key_digest" = "$private_key_digest" ] || \
  fail 'private key does not match the Vault leaf certificate'

printf 'production Vault TLS chain verified\n'
