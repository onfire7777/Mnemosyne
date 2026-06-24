#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"

STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_ROOT="${1:-/tmp/mnemosyne-tierb-local-evidence-${STAMP}}"
mkdir -p "${OUT_ROOT}"

PYTHON="${MNEMOSYNE_PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
    PYTHON="${REPO_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

for required in \
  "${INFRA_DIR}/keycloak/out/oidc.env" \
  "${INFRA_DIR}/vault/out/vault.env" \
  "${INFRA_DIR}/c2pa/out/provenance.env"
do
  if [ ! -f "${required}" ]; then
    echo "ERROR: ${required} is missing; run infra/scripts/setup-all.sh first." >&2
    exit 1
  fi
done

# shellcheck source=/dev/null
source "${INFRA_DIR}/keycloak/out/oidc.env"
# shellcheck source=/dev/null
source "${INFRA_DIR}/vault/out/vault.env"
# shellcheck source=/dev/null
source "${INFRA_DIR}/c2pa/out/provenance.env"

export MNEMOSYNE_IDP_TOKEN="$("${INFRA_DIR}/scripts/keycloak-token.sh" agent-a agent-a-password)"
export MNEMOSYNE_OBJECT_STORE_ENCRYPTION="aesgcm"
export MNEMOSYNE_OBJECT_STORE="${OUT_ROOT}/objects"
export OUT_ROOT REPO_DIR INFRA_DIR

STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export STARTED_AT

"${PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

out_root = Path(os.environ["OUT_ROOT"])
repo_dir = Path(os.environ["REPO_DIR"])
started_at = os.environ["STARTED_AT"]
policy = json.loads(Path(os.environ["MNEMOSYNE_PROVENANCE_TRUST_POLICY"]).read_text(encoding="utf-8"))

suite = {
    "name": "mnemosyne-local-real-c2pa",
    "tool": os.environ["MNEMOSYNE_C2PA_TOOL"],
    "trusted_issuers": policy.get("trusted_issuers", []),
    "trusted_roots": policy.get("trusted_roots", []),
    "trust_policy": policy,
    "required_cases": ["c2pa-signed-asset"],
    "cases": [
        {
            "id": "c2pa-signed-asset",
            "asset_path": os.environ["C2PA_SIGNED_ASSET"],
            "expect_valid": True,
            "expect_trusted": True,
            "expect_quarantine": False,
            "manifest": {
                "source_type": "camera",
                "modality": "binary",
                "tenant_id": "tenant-a",
                "source_trust_tier": 5,
            },
        }
    ],
}
suite_path = out_root / "provenance-trust-suite.json"
suite_path.write_text(json.dumps(suite, indent=2), encoding="utf-8")

manifest = {
    "validation_scope": {
        "production_validated": False,
        "target_environment": "local-real-services",
        "operator_asserted": True,
        "run_id": f"local-real-services-{started_at}",
        "started_at": started_at,
        "completed_at": started_at,
        "note": (
            "Local real-service evidence only: Keycloak, Vault transit, "
            "Postgres retrieval, and c2patool are real services/tools on "
            "localhost. This is not production operator evidence."
        ),
    },
    "checks": [
        {
            "name": "keycloak-live-jwks",
            "command": "idp-jwks-live-check",
            "args": [],
            "timeout": 60,
        },
        {
            "name": "vault-kms-provider",
            "command": "provider-check",
            "global_args": ["--object-store", str(out_root / "objects")],
            "args": ["--provider-manifest", str(repo_dir / "infra/vault/providers.json")],
            "timeout": 60,
        },
        {
            "name": "c2pa-real-trust",
            "command": "provenance-trust-check",
            "args": ["--suite", str(suite_path), "--require-case", "c2pa-signed-asset"],
            "timeout": 90,
        },
    ],
}
(out_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

cd "${REPO_DIR}"
"${PYTHON}" -m mnemosyne.cli \
  --store "${OUT_ROOT}/store.json" \
  deployment-soak \
  --soak-manifest "${OUT_ROOT}/manifest.json" \
  --evidence-dir "${OUT_ROOT}/evidence" \
  --check-timeout 60 > "${OUT_ROOT}/deployment-soak.stdout.json"

"${PYTHON}" -m mnemosyne.cli \
  --store "${OUT_ROOT}/store.json" \
  release-audit \
  --evidence-manifest "${OUT_ROOT}/evidence/manifest.json" \
  --require-command idp-jwks-live-check \
  --require-command provider-check \
  --require-command provenance-trust-check \
  --require-provider-check object_key_manager \
  --require-provider-check retrieval_backends \
  --allow-provider-local > "${OUT_ROOT}/release-audit.json"

"${PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

out_root = Path(os.environ["OUT_ROOT"])
soak = json.loads((out_root / "deployment-soak.stdout.json").read_text(encoding="utf-8"))
audit = json.loads((out_root / "release-audit.json").read_text(encoding="utf-8"))
summary = {
    "out_root": str(out_root),
    "evidence_manifest": str(out_root / "evidence/manifest.json"),
    "deployment_soak_ok": soak.get("ok") is True,
    "release_audit_ok": audit.get("ok") is True,
    "release_audit_fingerprint": audit.get("fingerprint"),
    "commands": audit.get("commands"),
    "findings": audit.get("findings"),
    "scope": soak.get("validation_scope"),
}
print(json.dumps(summary, indent=2))
PY
