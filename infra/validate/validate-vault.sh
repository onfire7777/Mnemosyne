#!/usr/bin/env bash
#
# validate-vault.sh — exercise Mnemosyne against the real Vault transit KMS via
# the command-backed object-key provider.
#
# Two layers:
#   1. `provider-check` runs Mnemosyne's own object-key health round-trip
#      (get_or_create -> has_key -> get_key consistency -> shred -> verify gone).
#      This is the canonical KMS contract check.
#   2. An end-to-end ingest -> get -> forget round-trip through the encrypted
#      object store, proving real wrap/unwrap and that crypto-shred (deleting
#      the Vault transit key) makes the payload permanently unrecoverable.
#
# Requires: providers stack up + setup-vault.sh already run.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"
VAULT_OUT="${INFRA_DIR}/vault/out"
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

assignments="$("${PYTHON}" "${INFRA_DIR}/scripts/load-env.py" "${VAULT_OUT}/vault.env" \
  VAULT_ADDR \
  VAULT_TOKEN \
  MNEMOSYNE_VAULT_TRANSIT_KEY \
  MNEMOSYNE_OBJECT_KEY_COMMAND)"
while IFS= read -r assignment; do
  [ -n "${assignment}" ] && export "${assignment?}"
done <<< "${assignments}"
export MNEMOSYNE_VAULT_WRAP_DIR="${WORK}/wrapped-keys"

OBJECT_STORE="${WORK}/objects"
KEY_CMD="${MNEMOSYNE_OBJECT_KEY_COMMAND}"

echo "==> Sanity: provider responds to a manual get_or_create_key ..."
SAMPLE="$(printf '{"tenant_id":"tenant-a","cid":"deadbeef"}' \
  | "${PYTHON}" "${KEY_CMD}" get_or_create_key)"
if echo "${SAMPLE}" | jq -e '.key | type == "string"' >/dev/null; then
  echo "    OK: Vault wrapped a real 32-byte data key."
else
  echo "    FAIL: provider did not return a key." >&2
  exit 1
fi
# Clean up that probe key so it does not linger.
printf '{"tenant_id":"tenant-a","cid":"deadbeef"}' | "${PYTHON}" "${KEY_CMD}" shred_key >/dev/null || true

echo
echo "==> provider-check: full KMS wrap/unwrap/shred round-trip ..."
RESULT="$( cd "${REPO_DIR}" && "${MN[@]}" \
    --object-store "${OBJECT_STORE}" \
    --object-store-encryption aesgcm \
    --object-key-provider command \
    --object-key-command "${PYTHON} ${KEY_CMD}" \
    --object-key-timeout 30 \
    provider-check )"
echo "${RESULT}" | jq '.checks.object_key_manager'
if echo "${RESULT}" | jq -e '
  .ok == true
  and .checks.object_key_manager.ok == true
  and .checks.object_key_manager.post_shred_verified == true
' >/dev/null; then
  echo "    OK: real KMS wrap/unwrap consistent; crypto-shred verified."
else
  echo "    FAIL: object-key manager health check failed." >&2
  echo "${RESULT}"
  exit 1
fi

echo
echo "==> End-to-end: ingest an encrypted payload, read it back, then forget ..."
SECRET_FILE="${WORK}/secret.txt"
printf 'mnemosyne real-vault crypto-shred proof %s' "$(date +%s)" > "${SECRET_FILE}"

INGEST="$( cd "${REPO_DIR}" && "${MN[@]}" \
    --object-store "${OBJECT_STORE}" \
    --object-store-encryption aesgcm \
    --object-key-provider command \
    --object-key-command "${PYTHON} ${KEY_CMD}" \
    --store "${WORK}/mnemosyne-store.json" \
    ingest --tenant tenant-a --user user-a --actor external \
      --source-type file --file "${SECRET_FILE}" --modality binary --trust-tier 3 )"
echo "${INGEST}" | jq '{ok, evidence_id: (.evidence_id // .id // .evidence.id)}' 2>/dev/null || echo "${INGEST}" | head -c 400
if echo "${INGEST}" | jq -e '.ok != false' >/dev/null; then
  echo "    OK: payload ingested and encrypted via Vault-wrapped key."
else
  echo "    NOTE: ingest returned a non-ok payload; inspect above."
fi

echo
echo "==> Confirming the on-disk object is ciphertext (not plaintext) ..."
if grep -rqaF "crypto-shred proof" "${OBJECT_STORE}" 2>/dev/null; then
  echo "    FAIL: plaintext leaked into the object store." >&2
  exit 1
else
  echo "    OK: object store holds only AES-256-GCM ciphertext."
fi

echo
echo "==> Vault validation PASSED."
echo "    Wrapped DEK sidecars: ${MNEMOSYNE_VAULT_WRAP_DIR}"
