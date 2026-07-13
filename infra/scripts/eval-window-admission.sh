#!/usr/bin/env bash
# Reclaim two explicitly allowlisted desktop apps before a separately run eval preflight.
# This helper is intentionally not an admission authority.
set -euo pipefail

RUNBOOK='.planning/runbooks/HARDWARE-WORKLOAD-PREFLIGHT.md'
KEEP=${MNEMO_EVAL_KEEP:-}

if [ "${MNEMO_CONFIRM:-0}" != "1" ]; then
  printf '%s\n' \
    'REFUSING: set MNEMO_CONFIRM=1 to reclaim the allowlisted desktop apps.' >&2
  exit 64
fi

if [ "${MNEMO_EVAL_QUIT+x}" = x ]; then
  printf '%s\n' \
    'REFUSING: MNEMO_EVAL_QUIT is retired; the reclaim allowlist is immutable.' >&2
  exit 64
fi
if [ "${MNEMO_EVAL_FLOOR+x}" = x ]; then
  printf '%s\n' \
    'REFUSING: MNEMO_EVAL_FLOOR is retired; this helper performs no admission check.' >&2
  exit 64
fi

case "$KEEP" in
  '' | 'Brave Browser' | 'Discord' | 'Brave Browser|Discord' | 'Discord|Brave Browser') ;;
  *)
    printf '%s\n' \
      'REFUSING: MNEMO_EVAL_KEEP accepts only Brave Browser and/or Discord separated by |.' >&2
    exit 64
    ;;
esac

is_kept() {
  case "|$KEEP|" in
    *"|$1|"*) return 0 ;;
    *) return 1 ;;
  esac
}

quit_app() {
  local app=$1
  local status

  if is_kept "$app"; then
    printf 'keep: %s\n' "$app"
    return
  fi

  if pgrep -fq "$app"; then
    case "$app" in
      'Brave Browser')
        if ! osascript \
          -e 'with timeout of 5 seconds' \
          -e 'tell application "Brave Browser" to quit' \
          -e 'end timeout'; then
          printf 'reclaim failed: %s did not quit\n' "$app" >&2
          exit 1
        fi
        ;;
      'Discord')
        if ! osascript \
          -e 'with timeout of 5 seconds' \
          -e 'tell application "Discord" to quit' \
          -e 'end timeout'; then
          printf 'reclaim failed: %s did not quit\n' "$app" >&2
          exit 1
        fi
        ;;
    esac
    printf 'quit: %s\n' "$app"
    return
  else
    status=$?
  fi

  if [ "$status" -ne 1 ]; then
    printf 'reclaim failed: could not inspect %s\n' "$app" >&2
    exit 1
  fi
  printf 'not running: %s\n' "$app"
}

quit_app 'Brave Browser'
quit_app 'Discord'

printf '%s\n' \
  'ADMISSION PENDING — desktop reclamation completed; no admission checks were run.' \
  "Follow ${RUNBOOK} before any hardware-intensive workload."
exit 3
