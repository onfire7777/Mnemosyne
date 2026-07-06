#!/usr/bin/env bash
#
# rollback-perf-runtime.sh — undo apply-perf-runtime.sh:
#   1. Restore the prior colima size (recorded in the apply state file;
#      falls back to the measured pre-flip default of 4 CPU / 10 GiB).
#   2. git-checkout the previous docker-compose.prod.yml (default ref: the
#      perf-branch base ee30b5b — the last compose without the perf ceilings).
#   3. `docker compose up -d --remove-orphans` — restarts in-VM ollama, removes
#      the host-llm-proxy relay container, restores the pre-flip topology.
#
# GUARDED: prints the plan and refuses to act unless MNEMO_CONFIRM=1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_ROOT="$(cd "${INFRA_DIR}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.prod.yml"

ROLLBACK_REF="${1:-ee30b5b}"
STATE_FILE="${MNEMO_PERF_STATE_FILE:-${HOME}/.mnemosyne-perf-runtime-state}"
PREV_CPUS=4
PREV_MEMORY_GIB=10
if [ -f "${STATE_FILE}" ]; then
  # state file is two KEY=value lines written by apply-perf-runtime.sh
  # shellcheck disable=SC1090
  . "${STATE_FILE}"
fi

step() { echo; echo "==> $*"; }

step "PLAN"
cat <<EOF
  1. colima stop && colima start --cpu ${PREV_CPUS} --memory ${PREV_MEMORY_GIB}   [FULL STACK RESTART]
     (from ${STATE_FILE}$([ -f "${STATE_FILE}" ] || echo ' — MISSING, using pre-flip defaults'))
  2. git checkout ${ROLLBACK_REF} -- infra/docker-compose.prod.yml   (in ${REPO_ROOT})
  3. docker compose -f ${COMPOSE_FILE} up -d --remove-orphans
     (restarts in-VM ollama, removes the host-llm-proxy relay)
  4. post-check: docker compose ps
EOF

if [ "${MNEMO_CONFIRM:-0}" != "1" ]; then
  echo "REFUSING: set MNEMO_CONFIRM=1 to execute (this restarts the whole production stack)." >&2
  exit 1
fi

: "${MNEMO_SECRETS_DIR:?export MNEMO_SECRETS_DIR (e.g. \$HOME/mnemosyne-prod-secrets) first}"
KC_DB_PASSWORD="$(cat "${MNEMO_SECRETS_DIR}/kc_db_pw")"
KC_ADMIN_PASSWORD="$(cat "${MNEMO_SECRETS_DIR}/kc_admin_pw")"
export KC_DB_PASSWORD KC_ADMIN_PASSWORD MNEMO_SECRETS_DIR

step "1/4 restoring colima to --cpu ${PREV_CPUS} --memory ${PREV_MEMORY_GIB}"
colima stop
colima start --cpu "${PREV_CPUS}" --memory "${PREV_MEMORY_GIB}"

step "2/4 restoring infra/docker-compose.prod.yml from ${ROLLBACK_REF}"
git -C "${REPO_ROOT}" checkout "${ROLLBACK_REF}" -- infra/docker-compose.prod.yml

step "3/4 docker compose up -d --remove-orphans"
docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans

step "4/4 post-check"
docker compose -f "${COMPOSE_FILE}" ps
echo
echo "Rolled back. NOTE: the working tree now carries the ${ROLLBACK_REF} compose;"
echo "'git checkout -- infra/docker-compose.prod.yml' from your branch restores the perf edits."
