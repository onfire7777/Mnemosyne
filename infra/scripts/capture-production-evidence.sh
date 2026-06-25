#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: infra/scripts/capture-production-evidence.sh SOAK_MANIFEST [OUT_ROOT]

Runs the existing production evidence path:
  1. Validate that SOAK_MANIFEST is explicitly production-scoped.
  2. Run deployment-soak with --evidence-dir.
  3. Run release-audit with --require-production-validated.

The manifest must contain validation_scope.production_validated=true,
validation_scope.target_environment="production", and
validation_scope.operator_asserted=true. Secrets must come from environment,
files, or command providers; do not put tokens directly in manifest args.
USAGE
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

MANIFEST="${1:-}"
if [ -z "${MANIFEST}" ]; then
  usage
  exit 64
fi

if [ ! -f "${MANIFEST}" ]; then
  echo "ERROR: production soak manifest not found: ${MANIFEST}" >&2
  exit 66
fi

STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
OUT_ROOT="${2:-/tmp/mnemosyne-tierb-production-evidence-${STAMP}}"

PYTHON="${MNEMOSYNE_PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
    PYTHON="${REPO_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

MANIFEST_PATH="$(cd "$(dirname "${MANIFEST}")" && pwd)/$(basename "${MANIFEST}")"
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export MANIFEST_PATH OUT_ROOT REPO_DIR STARTED_AT

"${PYTHON}" - <<'PY'
import json
import os
import re
import shutil
import sys
from pathlib import Path

repo_dir = Path(os.environ["REPO_DIR"])
sys.path.insert(0, str(repo_dir / "src"))

from mnemosyne.cli import (  # noqa: E402
    PRODUCTION_RELEASE_REQUIRED_COMMANDS,
)

manifest_path = Path(os.environ["MANIFEST_PATH"])
out_root = Path(os.environ["OUT_ROOT"])
manifest_text = manifest_path.read_text(encoding="utf-8")
unresolved_placeholders = sorted(set(re.findall(r"MNEMOSYNE_PROD_[A-Z0-9_]+", manifest_text)))
if unresolved_placeholders or "MNEMOSYNE_PROD_" in manifest_text:
    print(
        "ERROR: unresolved production placeholders remain in the soak manifest:",
        file=sys.stderr,
    )
    for placeholder in unresolved_placeholders or ["MNEMOSYNE_PROD_"]:
        print(f"  - {placeholder}", file=sys.stderr)
    print(
        "Render the template with infra/scripts/render-production-soak-manifest.sh "
        "before capture.",
        file=sys.stderr,
    )
    sys.exit(65)

manifest = json.loads(manifest_text)

scope = manifest.get("validation_scope", {})
if not isinstance(scope, dict):
    scope = {}

errors: list[str] = []
if scope.get("production_validated") is not True:
    errors.append("validation_scope.production_validated must be true")
if scope.get("target_environment") != "production":
    errors.append('validation_scope.target_environment must be "production"')
if scope.get("operator_asserted") is not True:
    errors.append("validation_scope.operator_asserted must be true")

checks = manifest.get("checks")
if not isinstance(checks, list) or not checks:
    errors.append("checks must be a non-empty array")
    checks = []

commands: set[str] = set()
sensitive_options = {
    "--auth-token",
    "--idp-token",
    "--session-secret",
    "--session-token",
    "--token",
    "--password",
    "--client-secret",
    "--secret",
    "--private-key",
    "--key",
}

for index, check in enumerate(checks, start=1):
    if not isinstance(check, dict):
        errors.append(f"checks[{index}] must be an object")
        continue
    command = check.get("command")
    if isinstance(command, str):
        commands.add(command)
    else:
        errors.append(f"checks[{index}].command must be a string")
    for field in ("args", "global_args"):
        values = check.get(field, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            errors.append(f"checks[{index}].{field} must be an array of strings")
            continue
        for value in values:
            if value in sensitive_options:
                errors.append(
                    f"checks[{index}].{field} contains secret-bearing option {value}; "
                    "use environment, files, or command providers instead"
                )

missing = sorted(set(PRODUCTION_RELEASE_REQUIRED_COMMANDS) - commands)
if missing:
    errors.append("manifest is missing production release commands: " + ", ".join(missing))

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(65)

out_root.mkdir(parents=True, exist_ok=True)
shutil.copyfile(manifest_path, out_root / "operator-soak-manifest.json")
preflight = {
    "ok": True,
    "source_manifest": str(manifest_path),
    "copied_manifest": str(out_root / "operator-soak-manifest.json"),
    "started_at": os.environ["STARTED_AT"],
    "required_commands": list(PRODUCTION_RELEASE_REQUIRED_COMMANDS),
    "provided_commands": sorted(commands),
}
(out_root / "preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
PY

cd "${REPO_DIR}"
"${PYTHON}" -m mnemosyne.cli \
  --store "${OUT_ROOT}/store.json" \
  deployment-soak \
  --soak-manifest "${MANIFEST_PATH}" \
  --evidence-dir "${OUT_ROOT}/evidence" \
  --check-timeout "${MNEMOSYNE_PRODUCTION_SOAK_CHECK_TIMEOUT:-120}" \
  > "${OUT_ROOT}/deployment-soak.stdout.json"

AUDIT_ARGS=(
  --store "${OUT_ROOT}/store.json"
  release-audit
  --evidence-manifest "${OUT_ROOT}/evidence/manifest.json"
  --require-production-validated
  --require-provider-forbid-local
)

if [ -n "${MNEMOSYNE_EXPECTED_RELEASE_FINGERPRINT:-}" ]; then
  AUDIT_ARGS+=(--expected-fingerprint "${MNEMOSYNE_EXPECTED_RELEASE_FINGERPRINT}")
fi

"${PYTHON}" -m mnemosyne.cli "${AUDIT_ARGS[@]}" > "${OUT_ROOT}/release-audit.json"

"${PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

out_root = Path(os.environ["OUT_ROOT"])
soak = json.loads((out_root / "deployment-soak.stdout.json").read_text(encoding="utf-8"))
audit = json.loads((out_root / "release-audit.json").read_text(encoding="utf-8"))
summary = {
    "out_root": str(out_root),
    "operator_manifest": str(out_root / "operator-soak-manifest.json"),
    "evidence_manifest": str(out_root / "evidence/manifest.json"),
    "deployment_soak_ok": soak.get("ok") is True,
    "release_audit_ok": audit.get("ok") is True,
    "release_audit_fingerprint": audit.get("fingerprint"),
    "release_audit_findings": audit.get("findings", []),
    "completed_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
}
(out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
PY
