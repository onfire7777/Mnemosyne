#!/usr/bin/env bash
# Admit a near-expiry production MCP client pair without weakening the normal validator.
set -euo pipefail
set +x

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

fail() {
  printf 'production MCP client TLS rotation diagnosis failed: %s\n' "$1" >&2
  exit 65
}

if [ "$#" -ne 3 ]; then
  printf 'usage: %s ROOT_CA_PEM CERT_BUNDLE_PEM PRIVATE_KEY_PEM\n' "$0" >&2
  exit 64
fi

ROOT_CA=$1
CERT_BUNDLE=$2
PRIVATE_KEY=$3
SECRETS_DIR=${MNEMO_SECRETS_DIR:-/secure/outside/repo}
CANONICAL_ROOT=$SECRETS_DIR/stepca-acme-root.crt
CANONICAL_CERT=$SECRETS_DIR/mcp-client.crt
CANONICAL_KEY=$SECRETS_DIR/mcp-client.key
VALIDATOR=$SCRIPT_DIR/validate-production-mcp-client-tls.sh

for source_path in "$SECRETS_DIR" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY"; do
  case "$source_path" in
    /*) ;;
    *) fail 'rotation diagnosis requires absolute canonical source paths' ;;
  esac
done

OPENSSL=$(command -v openssl) || fail 'openssl is required'
PYTHON=$(command -v python3) || fail 'python3 is required'

path_error=$(
  "$PYTHON" - \
    "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" \
    "$CANONICAL_ROOT" "$CANONICAL_CERT" "$CANONICAL_KEY" 2>/dev/null <<'PY'
import os
import stat
import sys


def reject(message: str) -> None:
    print(message)
    raise SystemExit(1)


provided = [os.path.abspath(path) for path in sys.argv[1:4]]
expected = [os.path.abspath(path) for path in sys.argv[4:7]]
if provided != expected:
    reject("rotation diagnosis is restricted to the canonical current source pair")

for index, raw_path in enumerate(provided):
    path = os.path.abspath(raw_path)
    current = os.path.sep
    for component in path.split(os.path.sep)[1:]:
        current = os.path.join(current, component)
        try:
            component_stat = os.lstat(current)
        except OSError:
            reject("root, certificate bundle, and private key must be regular files")
        if stat.S_ISLNK(component_stat.st_mode):
            reject("path components must not be symlinks")

    file_stat = os.lstat(path)
    if not stat.S_ISREG(file_stat.st_mode):
        reject("root, certificate bundle, and private key must be regular files")
    if file_stat.st_uid != os.getuid():
        reject("certificate inputs must be owned by the current user")
    mode = stat.S_IMODE(file_stat.st_mode)
    if index == 2:
        if mode != 0o600:
            reject("private key must have mode 0600")
    elif mode & 0o022:
        reject("certificate inputs must not be group/world writable")
PY
) || fail "$path_error"

canonical_certificate_count=$(
  awk '/-----BEGIN CERTIFICATE-----/{count++} END{print count+0}' \
    "$CANONICAL_ROOT"
) || fail 'canonical Caddy client-auth root could not be read'
[ "$canonical_certificate_count" -eq 1 ] || \
  fail 'canonical Caddy client-auth root must contain exactly one certificate'
cmp -s "$ROOT_CA" "$CANONICAL_ROOT" || \
  fail 'caller root must match the canonical Caddy client-auth root'

leaf_start=$("$OPENSSL" x509 -in "$CERT_BUNDLE" -noout -startdate 2>/dev/null) || \
  fail 'source certificate validity could not be read'
if "$PYTHON" - "$leaf_start" 2>/dev/null <<'PY'
from email.utils import parsedate_to_datetime
import sys
import time


try:
    _, value = sys.argv[1].split("=", 1)
    not_before = int(parsedate_to_datetime(value).timestamp())
except (TypeError, ValueError, OverflowError):
    raise SystemExit(2)
raise SystemExit(not_before <= int(time.time()))
PY
then
  fail 'source certificate is not yet valid'
fi

if normal_error=$(env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$VALIDATOR" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" \
  2>&1 >/dev/null); then
  fail 'normal validator still accepts source pair'
fi
permitted_error='production MCP client TLS validation failed: leaf certificate is expired or inside the minimum validity window'
[ "$normal_error" = "$permitted_error" ] || \
  fail 'normal validator failure is not the permitted leaf validity-window failure'

if LC_ALL=C grep -Eq \
  '^(-----BEGIN ENCRYPTED PRIVATE KEY-----[[:space:]]*|Proc-Type:[[:space:]]*4,ENCRYPTED[[:space:]]*)$' \
  "$PRIVATE_KEY"; then
  fail 'private key must not be encrypted'
fi

certificate_count=$(
  awk '/-----BEGIN CERTIFICATE-----/{count++} END{print count+0}' "$CERT_BUNDLE"
) || fail 'certificate bundle could not be read'
[ "$certificate_count" -eq 2 ] || \
  fail 'certificate file must contain exactly the leaf and issuing intermediate'

verify_help=$("$OPENSSL" verify -help 2>&1 || :)
x509_help=$("$OPENSSL" x509 -help 2>&1 || :)
case "$verify_help" in
  *-verify_hostname*) ;;
  *) fail 'openssl is missing required capability: verify -verify_hostname' ;;
esac
case "$verify_help" in
  *-attime*) ;;
  *) fail 'openssl is missing required capability: verify -attime' ;;
esac
case "$x509_help" in
  *-checkend*) ;;
  *) fail 'openssl is missing required capability: x509 -checkend' ;;
esac

umask 077
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/mnemo-mcp-rotation-diagnosis.XXXXXX") || \
  fail 'private diagnostic workspace could not be created'
cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT
trap 'exit 65' HUP INT TERM
chmod 700 "$WORK_DIR" || fail 'private diagnostic workspace could not be secured'

LEAF=$WORK_DIR/leaf.pem
INTERMEDIATE=$WORK_DIR/intermediate.pem
DATES=$WORK_DIR/dates.txt
awk '
  /-----BEGIN CERTIFICATE-----/ { certificate++ }
  certificate == 1 { print }
' "$CERT_BUNDLE" >"$LEAF" || fail 'leaf certificate could not be isolated'
awk '
  /-----BEGIN CERTIFICATE-----/ { certificate++ }
  certificate == 2 { print }
' "$CERT_BUNDLE" >"$INTERMEDIATE" || \
  fail 'issuing intermediate could not be isolated'

: >"$DATES"
for certificate in "$LEAF" "$INTERMEDIATE" "$ROOT_CA"; do
  "$OPENSSL" x509 -in "$certificate" -noout -startdate -enddate \
    >>"$DATES" 2>/dev/null || fail 'certificate validity could not be read'
done

probe_result=$(
  "$PYTHON" - "$DATES" 2>/dev/null <<'PY'
from email.utils import parsedate_to_datetime
from pathlib import Path
import sys
import time


lines = Path(sys.argv[1]).read_text(encoding="ascii").splitlines()
if len(lines) != 6:
    print("invalid")
    raise SystemExit(1)

epochs = []
for line in lines:
    try:
        _, value = line.split("=", 1)
        epochs.append(int(parsedate_to_datetime(value).timestamp()))
    except (TypeError, ValueError, OverflowError):
        print("invalid")
        raise SystemExit(1)

now = int(time.time())
leaf_not_before = epochs[0]
if leaf_not_before > now:
    print("future")
    raise SystemExit(1)
if epochs[1] - now > 21600:
    print("outside")
    raise SystemExit(1)

not_before = max(epochs[0], epochs[2], epochs[4])
not_after = min(epochs[1], epochs[3], epochs[5])
if epochs[1] > now:
    if not (not_before <= now < not_after):
        print("current")
        raise SystemExit(1)
    probe = now
else:
    probe = max(not_before + 1, min(now, not_after - 1))
    if not_before >= not_after or not (not_before < probe < not_after):
        print("empty")
        raise SystemExit(1)
print(probe)
PY
) || {
  case "$probe_result" in
    future) fail 'source certificate is not yet valid' ;;
    outside) fail 'source leaf is outside the rotation diagnostic window' ;;
    current) fail 'unexpired source chain is not valid at the current time' ;;
    *) fail 'certificate validity intervals do not overlap' ;;
  esac
}

"$OPENSSL" verify \
  -attime "$probe_result" \
  -verify_hostname mcp-client.mnemo.local \
  -purpose sslclient \
  -CAfile "$ROOT_CA" \
  -untrusted "$INTERMEDIATE" \
  "$LEAF" >/dev/null 2>&1 || \
  fail 'leaf bundle does not validate against the current root CA, hostname, and purpose'

cert_key_digest=$(
  "$OPENSSL" x509 -in "$LEAF" -pubkey -noout 2>/dev/null |
    "$OPENSSL" pkey -pubin -outform DER 2>/dev/null |
    "$OPENSSL" dgst -sha256 2>/dev/null
) || fail 'certificate public key could not be read'
private_key_digest=$(
  "$OPENSSL" pkey -in "$PRIVATE_KEY" -passin pass: -pubout -outform DER 2>/dev/null |
    "$OPENSSL" dgst -sha256 2>/dev/null
) || fail 'private key could not be read'
[ "$cert_key_digest" = "$private_key_digest" ] || \
  fail 'private key does not match the leaf certificate'

printf 'production MCP client TLS rotation source verified\n'
