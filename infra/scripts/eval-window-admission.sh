#!/usr/bin/env bash
#
# eval-window-admission.sh — open a hardware eval window and prove it.
#
# Implements the operator half of .planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md:
#   1. RECLAIM: gracefully quit the host reclaim list (desktop apps that are
#      safe to close) and stop non-Mnemosyne brew services that hold memory.
#      Never touches: host ollama (eval reader), colima/the prod stack, or
#      any application named in MNEMO_EVAL_KEEP.
#   2. ADMIT: run the runbook's 3-sample admission check (15 s apart).
#      Every sample must pass: memory free >= 55%, load 1m <= 7.0 / 5m <= 8.0,
#      no resident ollama model, colima at 6 CPU / 12 GiB, no restarting or
#      unhealthy container.
#
# Exit 0  => window OPEN (all samples passed).
# Exit 1  => window CLOSED (reasons printed per sample).
#
# GUARDED: refuses to act unless MNEMO_CONFIRM=1 (reclaim quits real apps).
# The mTLS client-pair validation the runbook requires before the first
# sample runs automatically when MNEMO_SECRETS_DIR and the validator exist;
# otherwise it is reported as SKIPPED and must be run manually.
#
# Knobs:
#   MNEMO_EVAL_QUIT   space-separated app names to quit
#                     (default: "Brave Browser" Discord)
#   MNEMO_EVAL_KEEP   app names never to quit even if listed in QUIT
#   MNEMO_EVAL_FLOOR  free-memory floor percent (default 55; the runbook
#                     lightweight rule is 35)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
FLOOR="${MNEMO_EVAL_FLOOR:-55}"
QUIT_APPS_DEFAULT='Brave Browser|Discord'
QUIT_APPS="${MNEMO_EVAL_QUIT:-${QUIT_APPS_DEFAULT}}"

step() { echo; echo "==> $*"; }

step "PLAN"
cat <<EOF
  1. gracefully quit: ${QUIT_APPS//|/, }   (skip any in MNEMO_EVAL_KEEP)
  2. stop brew postgresql@17 if running (gbrain; on-demand by design)
  3. validate production mTLS client pair (if MNEMO_SECRETS_DIR is set)
  4. run 3 admission samples 15 s apart against floor ${FLOOR}% free
  NEVER touched: host ollama, colima VM, prod containers, ChatGPT/Codex,
  Claude, Terminal/IDE sessions.
EOF

if [ "${MNEMO_CONFIRM:-0}" != "1" ]; then
  echo "REFUSING: set MNEMO_CONFIRM=1 to execute (this quits desktop apps)." >&2
  exit 64
fi

step "1/4 reclaim"
IFS='|' read -ra APPS <<< "${QUIT_APPS}"
for app in "${APPS[@]}"; do
  case "|${MNEMO_EVAL_KEEP:-}|" in *"|${app}|"*) echo "  keep: ${app}"; continue;; esac
  if pgrep -fq "${app}"; then
    osascript -e "tell application \"${app}\" to quit" >/dev/null 2>&1 \
      && echo "  quit: ${app}" || echo "  quit FAILED (continuing): ${app}"
  else
    echo "  not running: ${app}"
  fi
done
if brew services list 2>/dev/null | grep -q '^postgresql@17.*started'; then
  brew services stop postgresql@17 >/dev/null && echo "  stopped: brew postgresql@17 (gbrain)"
else
  echo "  not running: brew postgresql@17"
fi

step "2/4 mTLS client-pair validation (runbook precondition)"
VALIDATOR="${INFRA_DIR}/validate/validate-production-mcp-client-tls.sh"
if [ -n "${MNEMO_SECRETS_DIR:-}" ] && [ -x "${VALIDATOR}" ]; then
  "${VALIDATOR}" \
    "${MNEMO_SECRETS_DIR}/stepca-acme-root.crt" \
    "${MNEMO_SECRETS_DIR}/mcp-client.crt" \
    "${MNEMO_SECRETS_DIR}/mcp-client.key" \
    && echo "  mTLS pair: OK" || { echo "  mTLS pair: FAILED — admission rejected"; exit 1; }
else
  echo "  SKIPPED (set MNEMO_SECRETS_DIR and ensure validator exists); run manually before protected work."
fi

step "3/4 settling 20 s before first sample"
sleep 20

step "4/4 admission samples (3 x 15 s, floor ${FLOOR}% free)"
fail=0
for i in 1 2 3; do
  free_pct="$(memory_pressure -Q | awk -F': ' '/free percentage/ {gsub(/%/,"",$2); print $2}')"
  read -r l1 l5 _ <<< "$(sysctl -n vm.loadavg | tr -d '{}')"
  resident="$(/opt/homebrew/bin/ollama ps 2>/dev/null | tail -n +2 | head -1 || true)"
  vmspec="$(colima list 2>/dev/null | awk '$1=="default" {print $4"cpu/"$5}')"
  bad_ctr="$(docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -ciE 'restarting|unhealthy' || true)"
  verdict="PASS"; why=""
  awk -v f="${free_pct}" -v m="${FLOOR}" 'BEGIN{exit !(f<m)}' && { verdict=FAIL; why+=" mem=${free_pct}%<${FLOOR}%"; }
  awk -v l="${l1}" 'BEGIN{exit !(l>7.0)}' && { verdict=FAIL; why+=" load1=${l1}>7.0"; }
  awk -v l="${l5}" 'BEGIN{exit !(l>8.0)}' && { verdict=FAIL; why+=" load5=${l5}>8.0"; }
  [ -n "${resident}" ] && { verdict=FAIL; why+=" model-resident"; }
  [ "${vmspec}" != "6cpu/12GiB" ] && { verdict=FAIL; why+=" vm=${vmspec}!=6cpu/12GiB"; }
  [ "${bad_ctr}" != "0" ] && { verdict=FAIL; why+=" ${bad_ctr}-unhealthy-containers"; }
  echo "  sample ${i}: ${verdict}  free=${free_pct}% load=${l1}/${l5} vm=${vmspec}${why:+  [${why# }]}"
  [ "${verdict}" = "FAIL" ] && fail=1
  [ "${i}" -lt 3 ] && sleep 15
done

echo
if [ "${fail}" = "0" ]; then
  echo "WINDOW OPEN — all 3 samples passed the ${FLOOR}% floor."
  echo "Proceed per runbook order: full verification -> scale receipt -> protected attempt."
else
  echo "WINDOW CLOSED — see failing samples above. Do not raise timeouts or run in parallel; wait and recheck."
  exit 1
fi
