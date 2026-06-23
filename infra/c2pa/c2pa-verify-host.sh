#!/usr/bin/env bash
#
# c2pa-verify-host.sh — the executable Mnemosyne's `--c2pa-tool` points at on
# the host. Mnemosyne calls:   c2pa-verify-host.sh <asset_path> --json
#
# It runs the REAL c2patool (inside the c2patool image, since the binary is not
# installed on the host) to perform genuine C2PA verification, then enriches the
# JSON report via c2pa-verify.py so it binds to Mnemosyne's contract:
#   - asset SHA-256 under an asset-named key
#   - certificate root SHA-256 fingerprint under a cert-named key
#
# If c2patool IS installed on the host (C2PATOOL_BIN points at it), it is used
# directly with no Docker round-trip.
#
# Environment:
#   C2PATOOL_BIN     host c2patool binary (if installed). Default: unset.
#   C2PATOOL_IMAGE   docker image carrying c2patool. Default mnemosyne-c2patool:local
#   C2PA_TRUST_ROOT  root cert PEM whose DER SHA-256 is injected as the root fpr.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSET_PATH="${1:?asset path required}"
IMAGE="${C2PATOOL_IMAGE:-mnemosyne-c2patool:local}"
TRUST_ROOT="${C2PA_TRUST_ROOT:-}"

if [ -n "${C2PATOOL_BIN:-}" ] && command -v "${C2PATOOL_BIN}" >/dev/null 2>&1; then
  # Native host c2patool path.
  C2PATOOL_BIN="${C2PATOOL_BIN}" C2PA_TRUST_ROOT="${TRUST_ROOT}" \
    exec python3 "${HERE}/c2pa-verify.py" "${ASSET_PATH}" --json
fi

# Containerized c2patool path. Run real verification, capture JSON, then enrich
# on the host where the asset/trust-root files live.
ASSET_ABS="$(cd "$(dirname "${ASSET_PATH}")" && pwd)/$(basename "${ASSET_PATH}")"
ASSET_DIR="$(dirname "${ASSET_ABS}")"
ASSET_NAME="$(basename "${ASSET_ABS}")"

# c2patool 0.9.12 prints the JSON report by default; the legacy `--json` flag
# was removed (it now errors "unexpected argument '--json'"). Invoke without it.
RAW_REPORT="$(docker run --rm -v "${ASSET_DIR}:/asset:ro" -w /asset "${IMAGE}" \
  c2patool "/asset/${ASSET_NAME}")"
RC=$?
if [ ${RC} -ne 0 ]; then
  echo "${RAW_REPORT}" >&2
  exit ${RC}
fi

# Enrich the (already verified) report on the host so paths/hashes are real.
printf '%s' "${RAW_REPORT}" | \
  C2PA_TRUST_ROOT="${TRUST_ROOT}" ASSET_PATH="${ASSET_ABS}" \
  python3 "${HERE}/c2pa-enrich.py"
