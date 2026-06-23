#!/usr/bin/env bash
#
# validate-all.sh — run all three real-service validations against Mnemosyne.
# Exits nonzero if any validation fails.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rc=0

run() {
  local name="$1"; shift
  echo
  echo "############################################################"
  echo "# VALIDATE: ${name}"
  echo "############################################################"
  if "$@"; then
    echo "## ${name}: PASS"
  else
    echo "## ${name}: FAIL" >&2
    rc=1
  fi
}

run "Keycloak OIDC/JWKS (FR-7/9)" "${HERE}/validate-keycloak.sh"
run "Vault transit KMS (KMS)"      "${HERE}/validate-vault.sh"
run "c2patool provenance (FR-19)"  "${HERE}/validate-c2pa.sh"

echo
if [ "${rc}" -eq 0 ]; then
  echo "==> ALL REAL-SERVICE VALIDATIONS PASSED."
else
  echo "==> ONE OR MORE VALIDATIONS FAILED." >&2
fi
exit "${rc}"
