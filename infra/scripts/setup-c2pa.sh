#!/usr/bin/env bash
#
# setup-c2pa.sh — produce a real C2PA test trust root and a signed asset for
# Mnemosyne's C2paToolVerifier (FR-19).
#
# Builds the c2patool image (if needed), generates a self-signed certificate
# ROOT and a leaf signing certificate, signs a test asset with the real
# c2patool, then writes:
#   - infra/c2pa/out/root.cert.pem / root.key.pem      (test trust root)
#   - infra/c2pa/out/signer.cert.pem / signer.key.pem  (leaf signer chain)
#   - infra/c2pa/out/asset.jpg                          (unsigned source)
#   - infra/c2pa/out/asset.signed.jpg                   (C2PA-signed asset)
#   - infra/c2pa/out/root.fingerprint.sha256            (DER SHA-256 of root)
#   - infra/c2pa/out/trust-policy.json                  (Mnemosyne policy)
#   - infra/c2pa/out/provenance.env                     (source-able env)
#
# Requires: docker (to run the c2patool image), openssl, jq, python3 on host.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
COMPOSE_FILE="${INFRA_DIR}/docker-compose.providers.yml"
C2PA_DIR="${INFRA_DIR}/c2pa"
OUT_DIR="${C2PA_DIR}/out"
mkdir -p "${OUT_DIR}"

IMAGE="mnemosyne-c2patool:local"
RUN="docker run --rm -v ${C2PA_DIR}:/work/config:ro -v ${OUT_DIR}:/work/out -w /work ${IMAGE}"

echo "==> Building c2patool image '${IMAGE}' (cached after first run) ..."
docker compose -f "${COMPOSE_FILE}" build c2pa

echo "==> Generating test certificate ROOT + leaf signer (openssl, on host) ..."
# Root CA
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout "${OUT_DIR}/root.key.pem" -out "${OUT_DIR}/root.cert.pem" \
  -subj "/C=US/O=Mnemosyne Test Root CA/CN=Mnemosyne Test Root CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1

# Leaf signing key + CSR
openssl req -newkey rsa:2048 -sha256 -nodes \
  -keyout "${OUT_DIR}/signer.key.pem" -out "${OUT_DIR}/signer.csr.pem" \
  -subj "/C=US/O=Mnemosyne Test Signer/CN=mnemosyne-test-signer" >/dev/null 2>&1

# Sign the leaf with the root, with the extensions c2patool expects.
cat > "${OUT_DIR}/signer.ext" <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=critical,emailProtection
EXT
openssl x509 -req -in "${OUT_DIR}/signer.csr.pem" \
  -CA "${OUT_DIR}/root.cert.pem" -CAkey "${OUT_DIR}/root.key.pem" \
  -CAcreateserial -days 825 -sha256 \
  -extfile "${OUT_DIR}/signer.ext" -out "${OUT_DIR}/signer.leaf.pem" >/dev/null 2>&1

# c2patool wants the full chain (leaf first, then root) in the cert file.
cat "${OUT_DIR}/signer.leaf.pem" "${OUT_DIR}/root.cert.pem" > "${OUT_DIR}/signer.cert.pem"

echo "==> Computing root certificate DER SHA-256 fingerprint ..."
ROOT_FPR="$(openssl x509 -in "${OUT_DIR}/root.cert.pem" -outform DER 2>/dev/null \
  | openssl dgst -sha256 -r | awk '{print $1}')"
printf '%s\n' "${ROOT_FPR}" > "${OUT_DIR}/root.fingerprint.sha256"
echo "    root SHA-256: ${ROOT_FPR}"

echo "==> Creating a deterministic test asset ..."
# A tiny valid JPEG so c2patool has a real asset to embed a manifest into.
python3 - "${OUT_DIR}/asset.jpg" <<'PY'
import sys
# Smallest viable baseline JPEG (1x1 white). c2patool embeds the C2PA manifest.
data = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
    "07090908"+"0a"*0+"0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c"
    "231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100"
    "ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400"
    "b5100002010303020403050504040000017d01020300041105122131410613516107227"
    "1143281a1ffda0008010100003f00d2cf20ffd9"
)
with open(sys.argv[1], "wb") as fh:
    fh.write(data)
PY

echo "==> Signing the asset with the real c2patool ..."
# Run c2patool inside the image. Manifest + signer material are visible under
# /work/config (ro) and /work/out (rw). The signed asset lands in out/.
${RUN} sh -c '
  set -e
  C2PA_PRIVATE_KEY=/work/out/signer.key.pem \
  C2PA_SIGN_CERT=/work/out/signer.cert.pem \
  c2patool /work/out/asset.jpg \
    --manifest /work/config/manifest.json \
    --output /work/out/asset.signed.jpg \
    --force
'

echo "==> Verifying the signed asset with the real c2patool ..."
${RUN} c2patool /work/out/asset.signed.jpg --json > "${OUT_DIR}/c2patool-report.json" || {
  echo "ERROR: c2patool verification of the signed asset failed." >&2
  exit 1
}
echo "    c2patool report written to ${OUT_DIR}/c2patool-report.json"

ASSET_SHA="$(openssl dgst -sha256 -r "${OUT_DIR}/asset.signed.jpg" | awk '{print $1}')"
echo "    signed-asset SHA-256: ${ASSET_SHA}"

echo "==> Writing Mnemosyne trust policy ..."
cat > "${OUT_DIR}/trust-policy.json" <<EOF
{
  "trusted_issuers": ["mnemosyne-test-signer", "Mnemosyne-Test-Signer"],
  "trusted_roots": ["${ROOT_FPR}"],
  "require_trusted_issuer": false,
  "require_trusted_root": false,
  "rules": [
    {
      "name": "camera-binary-tenant-a",
      "scope": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"},
      "trusted_roots": ["${ROOT_FPR}"],
      "require_trusted_root": true
    }
  ]
}
EOF

cat > "${OUT_DIR}/provenance.env" <<EOF
# Source before running ingest with real C2PA verification.
#   source infra/c2pa/out/provenance.env
# The C2PA verify wrapper (runs the real c2patool, then binds the report).
export MNEMOSYNE_C2PA_TOOL="${C2PA_DIR}/c2pa-verify-host.sh"
export MNEMOSYNE_PROVENANCE_TRUST_POLICY="${OUT_DIR}/trust-policy.json"
export MNEMOSYNE_TRUSTED_PROVENANCE_ROOTS="${ROOT_FPR}"
export C2PA_TRUST_ROOT="${OUT_DIR}/root.cert.pem"
export C2PATOOL_IMAGE="${IMAGE}"
export C2PA_SIGNED_ASSET="${OUT_DIR}/asset.signed.jpg"
EOF

# Clean intermediates.
rm -f "${OUT_DIR}/signer.csr.pem" "${OUT_DIR}/signer.ext" "${OUT_DIR}/signer.leaf.pem"

echo
echo "==> Done. C2PA test material in ${OUT_DIR}"
echo "    Signed asset:  ${OUT_DIR}/asset.signed.jpg"
echo "    Trust root:    ${OUT_DIR}/root.cert.pem (sha256 ${ROOT_FPR})"
echo "    Trust policy:  ${OUT_DIR}/trust-policy.json"
echo "    Next:          ./infra/validate/validate-c2pa.sh"
