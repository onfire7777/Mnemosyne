#!/usr/bin/env bash
#
# validate-c2pa.sh — exercise Mnemosyne against the real c2patool + test root.
#
# Ingests the C2PA-signed asset through Mnemosyne's C2paToolVerifier and asserts
# the manifest verifies and is trusted under the test trust-root policy. Then a
# negative test: a byte-tampered copy must fail asset binding and quarantine.
#
# Requires: setup-c2pa.sh already run (signed asset + trust policy + env).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"
C2PA_OUT="${INFRA_DIR}/c2pa/out"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

PYTHON="${MNEMOSYNE_PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
    PYTHON="${REPO_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi
MN=("${PYTHON}" -m mnemosyne.cli)

# shellcheck source=/dev/null
source "${C2PA_OUT}/provenance.env"

SIGNED="${C2PA_OUT}/asset.signed.jpg"
[ -f "${SIGNED}" ] || { echo "ERROR: ${SIGNED} missing; run setup-c2pa.sh first." >&2; exit 1; }

echo "==> Direct wrapper check: real c2patool verifies + report binds ..."
REPORT="$( "${MNEMOSYNE_C2PA_TOOL}" "${SIGNED}" --json )"
echo "${REPORT}" | jq '{asset_sha256, certificate_roots, signer: (.signer // .issuer // .active_manifest)}' 2>/dev/null \
  || { echo "ERROR: wrapper did not emit JSON." >&2; echo "${REPORT}"; exit 1; }

echo
echo "==> Ingesting the signed asset through Mnemosyne's C2PA verifier ..."
INGEST="$( cd "${REPO_DIR}" && "${MN[@]}" \
    --store "${WORK}/store.json" \
    --c2pa-tool "${MNEMOSYNE_C2PA_TOOL}" \
    --provenance-trust-policy "${MNEMOSYNE_PROVENANCE_TRUST_POLICY}" \
    ingest --tenant tenant-a --user user-a --actor external \
      --source-type camera --file "${SIGNED}" --modality binary --trust-tier 5 )"
echo "${INGEST}" | jq '.' 2>/dev/null | head -60 || echo "${INGEST}" | head -c 800

echo
echo "==> Asserting the manifest verified, was TRUSTED, and NOT quarantined ..."
# IngestionResult exposes top-level `quarantined` and a `provenance` decision.
# `provenance.trusted == true` is load-bearing: the emitted trust policy must
# accept the signer string Mnemosyne actually surfaces (the report's
# claim_generator, selected by provenance._find_first) AND must not let the
# camera-binary-tenant-a rule's defaulted require_trusted_issuer (from_dict
# defaults missing → true, then OR-merged in for_context) force issuer trust on.
# If `trusted` is false the asset is quarantined; assert it positively here so a
# regression of the trust path is caught, not silently downgraded.
echo "${INGEST}" | jq -e '
  .quarantined == false
  and .provenance.valid == true
  and .provenance.trusted == true
  and .provenance.quarantine == false
' >/dev/null \
  && echo "    OK: real C2PA manifest verified, trusted, and bound to the asset bytes." \
  || { echo "    FAIL: signed asset did not verify as valid+trusted+not-quarantined." >&2; echo "${INGEST}" | jq '.provenance // .'; exit 1; }

echo "==> Provenance trust decision:"
echo "${INGEST}" | jq '{quarantined, valid: .provenance.valid, trusted: .provenance.trusted, reason: .provenance.reason}'

echo
echo "==> Negative test: a tampered copy must fail asset binding ..."
TAMPERED="${WORK}/tampered.jpg"
cp "${SIGNED}" "${TAMPERED}"
# Flip the final byte so the bytes no longer match the C2PA hard binding.
"${PYTHON}" - "${TAMPERED}" <<'PY'
import sys
p = sys.argv[1]
data = bytearray(open(p, "rb").read())
data[-1] ^= 0xFF
open(p, "wb").write(data)
PY

# Real c2patool detects the broken C2PA hard binding and exits nonzero; the
# verify wrapper propagates that, so Mnemosyne marks the decision invalid and
# quarantines. (stdout = ingest JSON; stderr captured separately.)
set +e
TAMPER_OUT="$( cd "${REPO_DIR}" && "${MN[@]}" \
    --store "${WORK}/store2.json" \
    --c2pa-tool "${MNEMOSYNE_C2PA_TOOL}" \
    --provenance-trust-policy "${MNEMOSYNE_PROVENANCE_TRUST_POLICY}" \
    ingest --tenant tenant-a --user user-a --actor external \
      --source-type camera --file "${TAMPERED}" --modality binary --trust-tier 5 2>"${WORK}/tamper.err" )"
TAMPER_RC=$?
set -e
if echo "${TAMPER_OUT}" | jq -e '.quarantined == true or .provenance.quarantine == true or .provenance.valid == false' >/dev/null 2>&1; then
  echo "    OK: tampered asset quarantined / invalidated (asset binding enforced)."
  echo "${TAMPER_OUT}" | jq '{quarantined, valid: .provenance.valid, reason: .provenance.reason}'
elif [ "${TAMPER_RC}" -ne 0 ] || grep -qi 'quarantine\|verification failed\|does not bind\|hash mismatch' "${WORK}/tamper.err"; then
  echo "    OK: tampered asset rejected (c2patool failure propagated)."
else
  echo "    FAIL: tampered asset was accepted as trusted." >&2
  echo "${TAMPER_OUT}" | head -c 600
  exit 1
fi

echo
echo "==> C2PA validation PASSED."
