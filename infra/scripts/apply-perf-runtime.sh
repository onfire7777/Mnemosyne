#!/usr/bin/env bash
#
# apply-perf-runtime.sh — P1 runtime capacity flip for the self-hosted prod stack.
#
#   1. Resize the colima VM (default 6 CPU / 12 GiB — the 4 CPU / 10 GiB VM is
#      the measured bottleneck; see infra/PERF-RUNTIME.md).
#   2. `docker compose up -d` so the new per-service cpus/mem_limit ceilings in
#      docker-compose.prod.yml take effect.
#   3. OPTIONAL (--host-llm): repoint the LLM clients at host-Metal ollama
#      through the profile-gated host-llm-proxy relay and stop in-VM ollama.
#   4. Post-checks: container health + a role-LLM probe through the active URL.
#
# GUARDED: prints the full plan and refuses to act unless MNEMO_CONFIRM=1.
# PRECONDITION: the pending production evidence capture must be COMPLETE —
# this restarts every container and invalidates in-flight live evidence
# (infra/PERF-RUNTIME.md § When to run).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.prod.yml"

VM_CPUS="${MNEMO_PERF_VM_CPUS:-6}"
VM_MEMORY_GIB="${MNEMO_PERF_VM_MEMORY:-12}"
STATE_FILE="${MNEMO_PERF_STATE_FILE:-${HOME}/.mnemosyne-perf-runtime-state}"
HOST_LLM=0
if [ "${1:-}" = "--host-llm" ]; then
  HOST_LLM=1
elif [ -n "${1:-}" ]; then
  echo "Usage: apply-perf-runtime.sh [--host-llm]" >&2
  exit 64
fi

step() { echo; echo "==> $*"; }

step "PLAN (host-llm flip: ${HOST_LLM})"
cat <<EOF
  1. record current colima size -> ${STATE_FILE}   (rollback-perf-runtime.sh reads it)
  2. colima stop && colima start --cpu ${VM_CPUS} --memory ${VM_MEMORY_GIB}   [FULL STACK RESTART]
  3. docker compose -f ${COMPOSE_FILE} up -d   (applies the committed cpus/mem_limit ceilings)
  4. [--host-llm only] verify host ollama on 127.0.0.1:11434, start the
     host-llm-proxy relay (profile host-llm), overlay OLLAMA_URL ->
     http://host-llm.mnemo.local:11434 on consolidator/role-http (and on the
     operator bastion when its profile is running), stop in-VM ollama
  5. post-checks: docker compose ps + role-LLM /api/version probe

PRECONDITION: the pending production evidence capture is COMPLETE (PERF-RUNTIME.md).
EOF

if [ "${MNEMO_CONFIRM:-0}" != "1" ]; then
  echo "REFUSING: set MNEMO_CONFIRM=1 to execute (this restarts the whole production stack)." >&2
  exit 1
fi

# Compose interpolation (KC_*) and the secrets block both need the external
# secrets dir; same contract as infra/prod/bootstrap.sh.
: "${MNEMO_SECRETS_DIR:?export MNEMO_SECRETS_DIR (e.g. \$HOME/mnemosyne-prod-secrets) first}"
KC_DB_PASSWORD="$(cat "${MNEMO_SECRETS_DIR}/kc_db_pw")"
KC_ADMIN_PASSWORD="$(cat "${MNEMO_SECRETS_DIR}/kc_admin_pw")"
export KC_DB_PASSWORD KC_ADMIN_PASSWORD MNEMO_SECRETS_DIR

step "1/5 recording current colima size -> ${STATE_FILE}"
colima list -j | python3 -c '
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    profile = json.loads(line)
    if profile.get("name") == "default":
        cpus = profile["cpus"]
        mem_gib = max(1, round(profile["memory"] / (1 << 30)))
        print(f"PREV_CPUS={cpus}")
        print(f"PREV_MEMORY_GIB={mem_gib}")
        break
else:
    sys.exit("no default colima profile found")
' > "${STATE_FILE}"
cat "${STATE_FILE}"

step "2/5 resizing colima to --cpu ${VM_CPUS} --memory ${VM_MEMORY_GIB} (stop/start)"
colima stop
colima start --cpu "${VM_CPUS}" --memory "${VM_MEMORY_GIB}"

step "3/5 docker compose up -d (new cpus/mem_limit ceilings)"
docker compose -f "${COMPOSE_FILE}" up -d

if [ "${HOST_LLM}" = "1" ]; then
  step "4/5 host-LLM flip (relay -> host-Metal ollama)"
  echo "  - verifying host ollama serves on 127.0.0.1:11434"
  curl -fsS -m 5 http://127.0.0.1:11434/api/version >/dev/null || {
    echo "ERROR: host ollama is not serving (brew services list | grep ollama); aborting the flip" >&2
    exit 1
  }
  OVERLAY="$(mktemp -t mnemo-host-llm-overlay.XXXXXX).yml"
  # Mirrors the commented OLLAMA_URL flip lines committed in docker-compose.prod.yml;
  # generated at runtime so the committed default topology stays byte-identical.
  cat > "${OVERLAY}" <<'YAML'
services:
  mnemo-consolidator:
    environment:
      OLLAMA_URL: http://host-llm.mnemo.local:11434
  role-http:
    environment:
      OLLAMA_URL: http://host-llm.mnemo.local:11434
  operator:
    environment:
      OLLAMA_URL: http://host-llm.mnemo.local:11434
YAML
  echo "  - starting relay + repointing consolidator/role-http (overlay: ${OVERLAY})"
  COMPOSE_PROFILES=host-llm docker compose -f "${COMPOSE_FILE}" -f "${OVERLAY}" \
    up -d host-llm-proxy mnemo-consolidator role-http
  # operator is profile-gated (profile "operator", not started by default) and
  # also carries the OLLAMA_URL overlay: recreate it only when it is actually
  # running, otherwise a live bastion would keep pointing at the in-VM ollama
  # we are about to stop. Guarded so an inactive profile never fails the flip.
  if [ -n "$(COMPOSE_PROFILES=operator docker compose -f "${COMPOSE_FILE}" ps -q operator 2>/dev/null || true)" ]; then
    echo "  - repointing running operator bastion at the relay"
    COMPOSE_PROFILES=host-llm,operator docker compose -f "${COMPOSE_FILE}" -f "${OVERLAY}" \
      up -d operator
  else
    echo "  - operator not running (profile inactive); skipping its recreate"
  fi
  echo "  - stopping in-VM ollama (NOTE: any later plain 'up -d' restarts it — re-run this flip after)"
  docker compose -f "${COMPOSE_FILE}" stop ollama
else
  step "4/5 host-LLM flip skipped (pass --host-llm to enable)"
fi

step "5/5 post-checks"
docker compose -f "${COMPOSE_FILE}" ps
echo "  - role-LLM probe through role-http's active OLLAMA_URL:"
docker exec "$(docker compose -f "${COMPOSE_FILE}" ps -q role-http)" python -c '
import os, urllib.request
url = os.environ.get("OLLAMA_URL", "http://ollama.mnemo.local:11434") + "/api/version"
print(" ", url, "->", urllib.request.urlopen(url, timeout=10).read().decode())
'
echo
echo "Done. Re-drill the consolidation-ops + hosted-llm evidence bundles before"
echo "publishing any new Tier-B artifacts (infra/PERF-RUNTIME.md § Evidence)."
