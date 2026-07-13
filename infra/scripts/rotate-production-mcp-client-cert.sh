#!/usr/bin/env bash
# Stage a replacement production MCP client certificate through a confined issuer.
set -euo pipefail
set +x

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
VALIDATOR=$REPO_ROOT/infra/validate/validate-production-mcp-client-tls.sh
DIAGNOSTIC=$REPO_ROOT/infra/validate/diagnose-production-mcp-client-tls-for-rotation.sh
STEP_IMAGE='smallstep/step-ca:0.28.4@sha256:0f88382ac5af5c6b7bbba0c6e8fcefef52aee6f22ea364df8e02a09ffd0d22f3'

result() {
  printf 'mcp-client-rotation result=%s\n' "$1"
}

preflight_failed() {
  result preflight_failed
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 65
}

runtime_unavailable() {
  result runtime_unavailable
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 69
}

issuance_failed() {
  result issuance_failed
  printf 'mcp-client-rotation failed: %s\n' "$1" >&2
  exit 70
}

classify_remaining() {
  case "$1" in
    '' | -) return 1 ;;
  esac
  case "${1#-}" in
    *[!0-9]*) return 1 ;;
  esac
  if [ "$1" -gt 43200 ]; then
    printf 'healthy\n'
  elif [ "$1" -gt 21600 ]; then
    printf 'renewal_due\n'
  elif [ "$1" -gt 7200 ]; then
    printf 'hard_floor\n'
  elif [ "$1" -ge 0 ]; then
    printf 'emergency\n'
  else
    printf 'expired\n'
  fi
}

if [ "${1:-}" = '--classify-remaining' ]; then
  [ "$#" -eq 2 ] || {
    printf 'usage: %s --classify-remaining SECONDS\n' "$0" >&2
    exit 64
  }
  renewal_state=$(classify_remaining "$2") || {
    printf 'usage: %s --classify-remaining SECONDS\n' "$0" >&2
    exit 64
  }
  printf 'mcp-client-rotation renewal_state=%s\n' "$renewal_state"
  exit 0
fi

[ "$#" -eq 0 ] || {
  printf 'usage: %s\n' "$0" >&2
  exit 64
}

OPENSSL=$(command -v openssl) || preflight_failed 'openssl is required'
PYTHON=$(command -v python3) || preflight_failed 'python3 is required'
SECRETS_DIR=${MNEMO_SECRETS_DIR:-/secure/outside/repo}
case "$SECRETS_DIR" in
  /*) ;;
  *) preflight_failed 'external secret root must be an absolute path' ;;
esac
ROOT_CA=$SECRETS_DIR/stepca-acme-root.crt
CERT_BUNDLE=$SECRETS_DIR/mcp-client.crt
PRIVATE_KEY=$SECRETS_DIR/mcp-client.key
PROVISIONER_PASSWORD=$SECRETS_DIR/step-ca-jwk-provisioner-password
COMPOSE_FILE=${MCP_CLIENT_ROTATOR_COMPOSE_FILE:-$REPO_ROOT/infra/docker-compose.prod.yml}
ROTATION_DIR=$SECRETS_DIR/.mcp-client-rotation
STAGE_DIR=${MCP_CLIENT_ROTATOR_STAGE_DIR:-$ROTATION_DIR/stage.$$.new}

source_path_error=$(
  "$PYTHON" - \
    "$ROOT_CA" public \
    "$CERT_BUNDLE" public \
    "$PRIVATE_KEY" private 2>/dev/null <<'PY'
import os
import stat
import sys


def reject(message: str) -> None:
    print(message)
    raise SystemExit(1)


arguments = sys.argv[1:]
for raw_path, kind in zip(arguments[::2], arguments[1::2]):
    path = os.path.abspath(raw_path)
    current = os.path.sep
    for component in path.split(os.path.sep)[1:]:
        current = os.path.join(current, component)
        try:
            component_stat = os.lstat(current)
        except OSError:
            reject("source certificate inputs must be regular files")
        if stat.S_ISLNK(component_stat.st_mode):
            reject("source certificate path components must not be symlinks")
    file_stat = os.lstat(path)
    if not stat.S_ISREG(file_stat.st_mode):
        reject("source certificate inputs must be regular files")
    if file_stat.st_uid != os.getuid():
        reject("source certificate inputs must be owned by the current user")
    mode = stat.S_IMODE(file_stat.st_mode)
    if kind == "private" and mode != 0o600:
        reject("source private key must have mode 0600")
    if kind == "public" and mode & 0o022:
        reject("source certificate inputs must not be group/world writable")
PY
) || preflight_failed "$source_path_error"

if env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$VALIDATOR" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" \
  >/dev/null 2>&1; then
  :
elif env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$DIAGNOSTIC" "$ROOT_CA" "$CERT_BUNDLE" "$PRIVATE_KEY" \
  >/dev/null 2>&1; then
  :
else
  preflight_failed 'source certificate validation failed'
fi

DECISION_EPOCH=$(date +%s) || preflight_failed 'renewal decision time is unavailable'
end_date=$("$OPENSSL" x509 -in "$CERT_BUNDLE" -noout -enddate 2>/dev/null) || \
  preflight_failed 'source certificate expiry could not be read'
end_epoch=$(
  "$PYTHON" - "$end_date" 2>/dev/null <<'PY'
from email.utils import parsedate_to_datetime
import sys


try:
    _, value = sys.argv[1].split("=", 1)
    print(int(parsedate_to_datetime(value).timestamp()))
except (TypeError, ValueError, OverflowError):
    raise SystemExit(1)
PY
) || preflight_failed 'source certificate expiry could not be parsed'
remaining_seconds=$((end_epoch - DECISION_EPOCH))
renewal_state=$(classify_remaining "$remaining_seconds") || \
  preflight_failed 'source certificate lifetime could not be classified'

if [ "$renewal_state" = healthy ]; then
  result healthy_noop
  exit 0
fi

for configuration_path in "$COMPOSE_FILE" "$STAGE_DIR"; do
  case "$configuration_path" in
    /*) ;;
    *) preflight_failed 'rotation configuration paths must be absolute' ;;
  esac
done

[ ! -e "$STAGE_DIR" ] && [ ! -L "$STAGE_DIR" ] || \
  preflight_failed 'staging directory already exists'

mount_path_error=$(
  "$PYTHON" - \
    "$ROOT_CA" public \
    "$PROVISIONER_PASSWORD" secret \
    "$COMPOSE_FILE" public \
    "$ROTATION_DIR" rotation \
    "$SECRETS_DIR" directory \
    "$STAGE_DIR" future 2>/dev/null <<'PY'
import os
import stat
import sys


def reject(message: str) -> None:
    print(message)
    raise SystemExit(1)


arguments = sys.argv[1:]
paths = list(zip(arguments[::2], arguments[1::2]))
for raw_path, kind in paths:
    if any(character in raw_path for character in (",", "\n", "\r")):
        reject("mount paths contain unsupported characters")
    path = os.path.abspath(raw_path)
    inspected = os.path.dirname(path) if kind == "future" else path
    current = os.path.sep
    for component in inspected.split(os.path.sep)[1:]:
        current = os.path.join(current, component)
        try:
            component_stat = os.lstat(current)
        except OSError:
            reject("rotation mount inputs are missing")
        if stat.S_ISLNK(component_stat.st_mode):
            reject("rotation mount path components must not be symlinks")
    if kind == "future":
        continue
    file_stat = os.lstat(path)
    expected_type = (
        stat.S_ISDIR if kind in ("directory", "rotation") else stat.S_ISREG
    )
    if not expected_type(file_stat.st_mode):
        reject("rotation mount inputs have the wrong type")
    if file_stat.st_uid != os.getuid():
        reject("rotation mount inputs must be owned by the current user")
    mode = stat.S_IMODE(file_stat.st_mode)
    if kind == "secret" and mode != 0o600:
        reject("provisioner password must have mode 0600")
    if kind == "public" and mode & 0o022:
        reject("rotation public inputs must not be group/world writable")
    if kind == "directory" and mode & 0o022:
        reject("rotation directories must not be group/world writable")
    if kind == "rotation" and mode != 0o700:
        reject("private rotation directory must have mode 0700")

rotation = os.path.abspath(paths[3][0])
secrets = os.path.abspath(paths[4][0])
stage = os.path.abspath(paths[5][0])
if os.path.dirname(stage) != rotation or os.path.basename(stage) in ("", ".", ".."):
    reject("staging directory must be a direct child of the private rotation directory")
if os.stat(rotation).st_dev != os.stat(secrets).st_dev:
    reject("staging and canonical certificate paths must share a filesystem")

password = os.path.abspath(paths[1][0])
data = open(password, "rb").read(4097)
if not data or len(data) > 4096 or b"\0" in data or b"\r" in data:
    reject("provisioner password has an invalid encoding")
if b"\n" in data[:-1] or data.count(b"\n") > 1:
    reject("provisioner password must contain exactly one line")
PY
) || preflight_failed "$mount_path_error"

compose_image=$(
  awk '$1 == "image:" && $2 ~ /^smallstep\/step-ca:/ {print $2}' "$COMPOSE_FILE"
) || preflight_failed 'Compose step-ca image could not be read'
[ "$compose_image" = "$STEP_IMAGE" ] || \
  preflight_failed 'Compose step-ca image is not the required digest pin'

DOCKER_BIN=${MCP_CLIENT_ROTATOR_DOCKER_BIN:-}
if [ -z "$DOCKER_BIN" ]; then
  DOCKER_BIN=$(command -v docker || :)
fi
[ -n "$DOCKER_BIN" ] && [ -x "$DOCKER_BIN" ] && [ ! -d "$DOCKER_BIN" ] || \
  runtime_unavailable 'Docker is unavailable'

SAFE_PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin
SAFE_HOME=$(
  "$PYTHON" -c 'import os, pwd; print(pwd.getpwuid(os.getuid()).pw_dir)' 2>/dev/null
) || preflight_failed 'current user home could not be resolved'
SAFE_TMPDIR=/tmp
docker_call() {
  env -i \
    HOME="$SAFE_HOME" \
    LC_ALL=C \
    PATH="$SAFE_PATH" \
    TMPDIR="$SAFE_TMPDIR" \
    "$DOCKER_BIN" "$@"
}

if ! active_context=$(docker_call context show 2>/dev/null); then
  runtime_unavailable 'Docker is unavailable'
fi
[ "$active_context" = colima ] || preflight_failed 'Docker context must be colima'

network_json=$(
  docker_call --context colima network inspect infra_internal 2>/dev/null
) || preflight_failed 'required Docker network is unavailable'
printf '%s' "$network_json" | "$PYTHON" -c '
import json
import sys

value = json.load(sys.stdin)
if isinstance(value, list):
    if len(value) != 1:
        raise SystemExit(1)
    value = value[0]
labels = value.get("Labels") or {}
valid = (
    value.get("Name") == "infra_internal"
    and value.get("Internal") is True
    and labels.get("com.docker.compose.project") == "infra"
    and labels.get("com.docker.compose.network") == "internal"
)
raise SystemExit(not valid)
' 2>/dev/null || preflight_failed 'required Docker network identity is invalid'

docker_call --context colima image inspect "$STEP_IMAGE" \
  >/dev/null 2>&1 || preflight_failed 'required step-ca image is unavailable'

version_output=$(
  docker_call --context colima run \
    --rm \
    --pull never \
    --read-only \
    --user 1000:1000 \
    --pids-limit 64 \
    --cap-drop ALL \
    --security-opt no-new-privileges=true \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --network none \
    --entrypoint /usr/local/bin/step \
    "$STEP_IMAGE" version 2>/dev/null
) || preflight_failed 'step CLI version probe failed'
[ "$version_output" = 'Smallstep CLI/0.28.7' ] || \
  preflight_failed 'step CLI version is not approved'

mkdir -m 700 "$STAGE_DIR" || preflight_failed 'private staging directory could not be created'
stage_mode=$(
  "$PYTHON" - "$STAGE_DIR" 2>/dev/null <<'PY'
import os
import stat
import sys


value = os.lstat(sys.argv[1])
if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.getuid():
    raise SystemExit(1)
print(f"{stat.S_IMODE(value.st_mode):03o}")
PY
) || preflight_failed 'private staging directory could not be verified'
[ "$stage_mode" = 700 ] || preflight_failed 'private staging directory must have mode 0700'

if ! docker_call --context colima run \
  --rm \
  --pull never \
  --read-only \
  --user 1000:1000 \
  --pids-limit 64 \
  --cap-drop ALL \
  --security-opt no-new-privileges=true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  --network infra_internal \
  --entrypoint /usr/local/bin/step \
  --mount "type=bind,src=$ROOT_CA,dst=/run/mnemo/root.crt,readonly" \
  --mount "type=bind,src=$PROVISIONER_PASSWORD,dst=/run/mnemo/provisioner-password,readonly" \
  --mount "type=bind,src=$STAGE_DIR,dst=/work" \
  "$STEP_IMAGE" \
  ca certificate \
  --ca-url https://ca.mnemo.local:9000 \
  --root /run/mnemo/root.crt \
  --provisioner admin \
  --provisioner-password-file /run/mnemo/provisioner-password \
  --san mcp-client.mnemo.local \
  --not-after 24h \
  mcp-client.mnemo.local \
  /work/mcp-client.crt \
  /work/mcp-client.key \
  </dev/null >/dev/null 2>&1; then
  issuance_failed 'staged issuance failed'
fi

if ! "$PYTHON" - "$STAGE_DIR" "$SECRETS_DIR" >/dev/null 2>&1 <<'PY'
import os
import stat
import sys


stage = os.path.abspath(sys.argv[1])
secrets = os.path.abspath(sys.argv[2])
stage_stat = os.lstat(stage)
if (
    not stat.S_ISDIR(stage_stat.st_mode)
    or stage_stat.st_uid != os.getuid()
    or stat.S_IMODE(stage_stat.st_mode) != 0o700
    or stage_stat.st_dev != os.stat(secrets).st_dev
):
    raise SystemExit(1)

expected = {"mcp-client.crt", "mcp-client.key"}
if set(os.listdir(stage)) != expected:
    raise SystemExit(1)

for name in expected:
    value = os.lstat(os.path.join(stage, name))
    mode = stat.S_IMODE(value.st_mode)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or value.st_dev != stage_stat.st_dev
        or value.st_size == 0
    ):
        raise SystemExit(1)
    if name.endswith(".key") and mode != 0o600:
        raise SystemExit(1)
    if name.endswith(".crt") and mode & 0o022:
        raise SystemExit(1)
PY
then
  issuance_failed 'staged validation failed'
fi

if ! env \
  LC_ALL=C \
  MCP_CLIENT_TLS_HOSTNAME=mcp-client.mnemo.local \
  MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS=21600 \
  MNEMO_SECRETS_DIR="$SECRETS_DIR" \
  "$VALIDATOR" \
  "$ROOT_CA" \
  "$STAGE_DIR/mcp-client.crt" \
  "$STAGE_DIR/mcp-client.key" \
  >/dev/null 2>&1; then
  issuance_failed 'staged validation failed'
fi

result staged_only
