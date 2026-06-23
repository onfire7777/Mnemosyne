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
# A real baseline JPEG so c2patool has a valid asset to embed a manifest into.
# The previous hand-rolled hex blob was not a parseable JPEG and c2patool 0.9.12
# rejected it ("Could not parse input JPEG"). Generate a real one with Pillow
# when available; otherwise fall back to a vetted minimal baseline JPEG.
if python3 -c "import PIL" >/dev/null 2>&1; then
  python3 - "${OUT_DIR}/asset.jpg" <<'PY'
import sys
from PIL import Image
img = Image.new("RGB", (64, 64), (200, 120, 40))
for x in range(64):
    for y in range(64):
        if (x // 8 + y // 8) % 2 == 0:
            img.putpixel((x, y), (40, 90, 160))
img.save(sys.argv[1], "JPEG", quality=90)
PY
else
  python3 - "${OUT_DIR}/asset.jpg" <<'PY'
import base64, sys
# Vetted minimal 16x16 baseline JPEG (valid, parseable by c2patool 0.9.12).
JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAAQABABAREA/8QAHwAA"
    "AQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQR"
    "BRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RF"
    "RkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEB"
    "AAA/APf6KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK"
    "KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK"
    "KKKKKKKKKKKKKKKKKKKKKKKK/9k="
)
open(sys.argv[1], "wb").write(base64.b64decode(JPEG_B64))
PY
fi

echo "==> Signing the asset with the real c2patool ..."
# c2patool 0.9.12 takes the signing material from the manifest definition
# (`private_key` / `sign_cert` path fields), NOT the legacy C2PA_PRIVATE_KEY /
# C2PA_SIGN_CERT environment variables (those now yield "Invalid certification
# data ... No supported data to decode"). Inject the signer paths into a copy of
# the manifest so the real signer chain is used.
python3 - "${C2PA_DIR}/manifest.json" "${OUT_DIR}/manifest.signed.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
manifest["private_key"] = "/work/out/signer.key.pem"
manifest["sign_cert"] = "/work/out/signer.cert.pem"
json.dump(manifest, open(sys.argv[2], "w"), indent=2)
PY
${RUN} sh -c '
  set -e
  c2patool /work/out/asset.jpg \
    --manifest /work/out/manifest.signed.json \
    --output /work/out/asset.signed.jpg \
    --force
'

echo "==> Verifying the signed asset with the real c2patool ..."
# c2patool 0.9.12 prints the JSON report by default; the legacy `--json` flag
# was removed. Invoke without it.
${RUN} c2patool /work/out/asset.signed.jpg > "${OUT_DIR}/c2patool-report.json" || {
  echo "ERROR: c2patool verification of the signed asset failed." >&2
  exit 1
}
echo "    c2patool report written to ${OUT_DIR}/c2patool-report.json"

ASSET_SHA="$(openssl dgst -sha256 -r "${OUT_DIR}/asset.signed.jpg" | awk '{print $1}')"
echo "    signed-asset SHA-256: ${ASSET_SHA}"

echo "==> Discovering the signer string the real c2patool report surfaces ..."
# Mnemosyne's C2paToolVerifier picks the signer via provenance._find_first over
# the keys {issuer, signer, claim_generator, claimGenerator, common_name,
# commonName} in *insertion order*. In a real c2patool --json report the active
# manifest's "claim_generator" is encountered before the signature_info issuer/
# common_name, so the signer string Mnemosyne actually evaluates against
# trusted_issuers is the claim_generator (e.g. "Mnemosyne-Test-Signer/1.0
# c2patool/<ver>"), NOT the leaf CN "mnemosyne-test-signer". We extract that
# exact string from the report this run produced so issuer trust matches reality.
SURFACED_SIGNER="$(
  C2PA_REPORT="${OUT_DIR}/c2patool-report.json" python3 - <<'PY'
import json, os
keys = {"issuer", "signer", "claim_generator", "claimGenerator", "common_name", "commonName"}
def find_first(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in keys and v:
                return v
        for v in value.values():
            r = find_first(v)
            if r:
                return r
    elif isinstance(value, list):
        for v in value:
            r = find_first(v)
            if r:
                return r
    return None
try:
    report = json.load(open(os.environ["C2PA_REPORT"], encoding="utf-8"))
except Exception:
    report = {}
print(find_first(report) or "")
PY
)"
# The container path enriches via c2pa-enrich.py, which only injects a fallback
# "signer" when none of {issuer, signer, common_name} are already present. If the
# real report exposed nothing, c2pa-enrich falls back to the active_manifest id
# or the literal "Mnemosyne-Test-Signer"; mirror that fallback here so the policy
# still matches when the report is sparse.
if [ -z "${SURFACED_SIGNER}" ]; then
  SURFACED_SIGNER="$(
    C2PA_REPORT="${OUT_DIR}/c2patool-report.json" python3 - <<'PY'
import json, os
try:
    report = json.load(open(os.environ["C2PA_REPORT"], encoding="utf-8"))
except Exception:
    report = {}
print(report.get("active_manifest") or report.get("activeManifest") or "Mnemosyne-Test-Signer")
PY
  )"
fi
echo "    surfaced signer: ${SURFACED_SIGNER}"

echo "==> Writing Mnemosyne trust policy ..."
# Trust-path correctness (P0 fix):
#   * trusted_issuers MUST contain the signer string Mnemosyne actually surfaces
#     (the claim_generator, captured above as SURFACED_SIGNER) -- the old policy
#     listed only "mnemosyne-test-signer"/"Mnemosyne-Test-Signer", which the
#     verifier never sees, so the positive path quarantined.
#   * The camera-binary-tenant-a rule MUST set require_trusted_issuer:false
#     EXPLICITLY. provenance.ProvenanceTrustRule.from_dict defaults a missing
#     require_trusted_issuer to TRUE, and for_context() OR-merges rule flags into
#     the scoped policy -- so an omitted flag silently forces issuer trust ON for
#     this scope (defeating the top-level false) and quarantines. This rule trusts
#     by certificate ROOT (require_trusted_root:true); issuer trust is not required
#     for it. Belt-and-suspenders: SURFACED_SIGNER also satisfies issuer trust if
#     ever evaluated.
cat > "${OUT_DIR}/trust-policy.json" <<EOF
{
  "trusted_issuers": ["${SURFACED_SIGNER}", "mnemosyne-test-signer", "Mnemosyne-Test-Signer"],
  "trusted_roots": ["${ROOT_FPR}"],
  "require_trusted_issuer": false,
  "require_trusted_root": false,
  "rules": [
    {
      "name": "camera-binary-tenant-a",
      "scope": {"tenant_id": "tenant-a", "source_type": "camera", "modality": "binary"},
      "trusted_issuers": ["${SURFACED_SIGNER}"],
      "trusted_roots": ["${ROOT_FPR}"],
      "require_trusted_issuer": false,
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
