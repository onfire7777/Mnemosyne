#!/usr/bin/env bash
#
# apply-perf-runtime.sh — P1 runtime capacity apply for the self-hosted prod stack.
#
#   1. Resize the colima VM (default 6 CPU / 12 GiB — the 4 CPU / 10 GiB VM is
#      the measured bottleneck; see infra/PERF-RUNTIME.md).
#   2. `docker compose up -d` so the new per-service cpus/mem_limit ceilings in
#      docker-compose.prod.yml take effect. host-Metal LLM serving (the
#      host-llm-proxy relay) is now the COMMITTED DEFAULT topology — a plain
#      `up -d` starts the relay and leaves in-VM ollama OFF (opt-in 'in-vm-llm'
#      profile), so there is NO separate flip to perform. The fragile runtime
#      OLLAMA_URL overlay is GONE.
#   3. Post-checks: container health + a role-LLM probe through role-http's
#      active OLLAMA_URL (the relay -> host Metal by default).
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

# --host-llm is retained as a NO-OP for backward compatibility: host-Metal serving
# is the committed default now (a plain `up -d` already brings up the relay and
# leaves in-VM ollama off). The old runtime overlay/flip is removed.
if [ "${1:-}" = "--host-llm" ]; then
  echo "NOTE: --host-llm is a no-op — host-Metal (the host-llm-proxy relay) is the committed DEFAULT topology now."
elif [ -n "${1:-}" ]; then
  echo "Usage: apply-perf-runtime.sh [--host-llm]   (--host-llm is a no-op; host-Metal is the default)" >&2
  exit 64
fi

step() { echo; echo "==> $*"; }

step "PLAN"
cat <<EOF
  1. record current colima size -> ${STATE_FILE}   (rollback-perf-runtime.sh reads it)
  2. colima stop && colima start --cpu ${VM_CPUS} --memory ${VM_MEMORY_GIB}   [FULL STACK RESTART]
  3. docker compose -f ${COMPOSE_FILE} up -d
       - applies the committed cpus/mem_limit ceilings
       - starts host-llm-proxy (DEFAULT host-Metal LLM path); in-VM ollama stays
         OFF (opt-in 'in-vm-llm' profile). No overlay, no manual flip.
  4. post-checks: docker compose ps + role-LLM /api/version probe through the relay

  In-VM fallback (only if host ollama is unavailable):
    COMPOSE_PROFILES=in-vm-llm docker compose -f ${COMPOSE_FILE} up -d ollama
    …then repoint the LLM clients at http://ollama.mnemo.local:11434.

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

step "1/4 recording current colima size -> ${STATE_FILE}"
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

step "2/4 resizing colima to --cpu ${VM_CPUS} --memory ${VM_MEMORY_GIB} (stop/start)"
colima stop
colima start --cpu "${VM_CPUS}" --memory "${VM_MEMORY_GIB}"

step "3/4 docker compose up -d (ceilings + default host-Metal relay; in-VM ollama stays off)"
docker compose -f "${COMPOSE_FILE}" up -d

step "4/4 post-checks"
docker compose -f "${COMPOSE_FILE}" ps
echo "  - role-LLM probe through role-http's active OLLAMA_URL (relay -> host Metal by default):"
docker exec "$(docker compose -f "${COMPOSE_FILE}" ps -q role-http)" python -c '
import os, urllib.request
url = os.environ.get("OLLAMA_URL", "http://host-llm.mnemo.local:11434") + "/api/version"
print(" ", url, "->", urllib.request.urlopen(url, timeout=10).read().decode())
'
echo
echo "Done. Re-drill the consolidation-ops + hosted-llm evidence bundles before"
echo "publishing any new Tier-B artifacts (infra/PERF-RUNTIME.md § Evidence)."
