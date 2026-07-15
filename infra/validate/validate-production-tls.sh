#!/usr/bin/env bash
# Validate a production TLS leaf bundle without printing certificate or key material.
set -euo pipefail

IDENTITY=${PRODUCTION_TLS_IDENTITY:-production}
HOSTNAME=${PRODUCTION_TLS_HOSTNAME:-}
PURPOSE=${PRODUCTION_TLS_PURPOSE:-sslserver}
MIN_VALIDITY_SECONDS=${PRODUCTION_TLS_MIN_VALIDITY_SECONDS:-0}

fail() {
  printf '%s TLS validation failed: %s\n' "$IDENTITY" "$1" >&2
  exit 65
}

if [ "$#" -ne 3 ]; then
  printf 'usage: %s ROOT_CA_PEM CERT_BUNDLE_PEM PRIVATE_KEY_PEM\n' "$0" >&2
  exit 64
fi

ROOT_CA=$1
CERT_BUNDLE=$2
PRIVATE_KEY=$3

[ -n "$HOSTNAME" ] || fail 'PRODUCTION_TLS_HOSTNAME is required'
case "$PURPOSE" in
  sslserver | sslclient) ;;
  *) fail 'PRODUCTION_TLS_PURPOSE must be sslserver or sslclient' ;;
esac
case "$MIN_VALIDITY_SECONDS" in
  '' | *[!0-9]*) fail 'PRODUCTION_TLS_MIN_VALIDITY_SECONDS must be a non-negative integer' ;;
esac

OPENSSL=$(command -v openssl) || fail 'openssl is required'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'

verify_help=$("$OPENSSL" verify -help 2>&1 || :)
x509_help=$("$OPENSSL" x509 -help 2>&1 || :)
missing_capabilities=
case "$verify_help" in
  *-verify_hostname*) ;;
  *) missing_capabilities='verify -verify_hostname' ;;
esac
case "$verify_help" in
  *-attime*) ;;
  *) missing_capabilities="${missing_capabilities:+$missing_capabilities, }verify -attime" ;;
esac
case "$x509_help" in
  *-checkend*) ;;
  *) missing_capabilities="${missing_capabilities:+$missing_capabilities, }x509 -checkend" ;;
esac
[ -z "$missing_capabilities" ] || \
  fail "openssl is missing required capabilities: $missing_capabilities"

for path in "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY"; do
  [ ! -L "$path" ] || fail 'certificate inputs must not be symlinks'
  [ -f "$path" ] || fail 'root, certificate bundle, and private key must be regular files'
done

python3 - "$PRIVATE_KEY" <<'PY' || fail 'private key must not be group/world accessible'
import os
import sys

raise SystemExit(bool(os.stat(sys.argv[1], follow_symlinks=False).st_mode & 0o077))
PY

if LC_ALL=C grep -Eq \
  '^(-----BEGIN ENCRYPTED PRIVATE KEY-----[[:space:]]*|Proc-Type:[[:space:]]*4,ENCRYPTED[[:space:]]*)$' \
  "$PRIVATE_KEY"; then
  fail 'private key must not be encrypted'
fi

certificate_count=$(awk '/-----BEGIN CERTIFICATE-----/{count++} END{print count+0}' "$CERT_BUNDLE")
[ "$certificate_count" -ge 2 ] || fail 'certificate file must contain the leaf and issuing intermediate'

"$OPENSSL" x509 -in "$CERT_BUNDLE" -noout -checkend "$MIN_VALIDITY_SECONDS" \
  >/dev/null 2>&1 || fail 'leaf certificate is expired or inside the minimum validity window'

"$OPENSSL" verify \
  -verify_hostname "$HOSTNAME" \
  -purpose "$PURPOSE" \
  -CAfile "$ROOT_CA" \
  -untrusted "$CERT_BUNDLE" \
  "$CERT_BUNDLE" >/dev/null 2>&1 || \
  fail 'leaf bundle does not validate against the current root CA, hostname, and purpose'

VERIFY_AT=$(
  python3 - "$MIN_VALIDITY_SECONDS" <<'PY'
import sys
import time

print(int(time.time()) + int(sys.argv[1]))
PY
) || fail 'minimum validity horizon could not be calculated'
"$OPENSSL" verify \
  -attime "$VERIFY_AT" \
  -verify_hostname "$HOSTNAME" \
  -purpose "$PURPOSE" \
  -CAfile "$ROOT_CA" \
  -untrusted "$CERT_BUNDLE" \
  "$CERT_BUNDLE" >/dev/null 2>&1 || \
  fail 'certificate chain is not valid through the minimum validity window'

cert_key_digest=$(
  "$OPENSSL" x509 -in "$CERT_BUNDLE" -pubkey -noout 2>/dev/null |
    "$OPENSSL" pkey -pubin -outform DER 2>/dev/null |
    "$OPENSSL" dgst -sha256 2>/dev/null
) || fail 'certificate public key could not be read'
private_key_digest=$(
  "$OPENSSL" pkey -in "$PRIVATE_KEY" -passin pass: -pubout -outform DER 2>/dev/null |
    "$OPENSSL" dgst -sha256 2>/dev/null
) || fail 'private key could not be read'
[ "$cert_key_digest" = "$private_key_digest" ] || \
  fail 'private key does not match the leaf certificate'

printf '%s TLS chain verified\n' "$IDENTITY"
