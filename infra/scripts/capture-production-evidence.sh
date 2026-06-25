#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage:
  infra/scripts/capture-production-evidence.sh [--preflight-only] SOAK_MANIFEST [OUT_ROOT]

Runs the existing production evidence path:
  1. Validate that SOAK_MANIFEST is explicitly production-scoped.
  2. Run deployment-soak with --evidence-dir.
  3. Run release-audit with --require-production-validated and
     --require-provider-forbid-local.

The manifest must contain validation_scope.production_validated=true,
validation_scope.target_environment="production", and
validation_scope.operator_asserted=true. Secrets must come from environment,
files, or command providers; do not put tokens directly in manifest args.

Options:
  --preflight-only  Validate and copy the manifest, write preflight.json, then
                    exit before deployment-soak or release-audit runs.
USAGE
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"

PREFLIGHT_ONLY=0
while [ "$#" -gt 0 ]; do
  case "${1}" in
    --help|-h)
      usage
      exit 0
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "ERROR: unknown option: ${1}" >&2
      usage
      exit 64
      ;;
    *)
      break
      ;;
  esac
done

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
if [ -e "${OUT_ROOT}" ]; then
  if [ ! -d "${OUT_ROOT}" ]; then
    echo "ERROR: production evidence output path exists and is not a directory: ${OUT_ROOT}" >&2
    exit 65
  fi
  if [ -n "$(find "${OUT_ROOT}" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "ERROR: production evidence output directory must be empty: ${OUT_ROOT}" >&2
    exit 65
  fi
fi

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
export MANIFEST_PATH OUT_ROOT REPO_DIR STARTED_AT PREFLIGHT_ONLY

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
from mnemosyne.evidence_redaction import (  # noqa: E402
    redaction_findings,
    write_redaction_scan,
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

manifest_findings = redaction_findings(str(manifest_path), manifest_text)
if manifest_findings:
    print(
        "ERROR: high-confidence secret material found in the production soak manifest:",
        file=sys.stderr,
    )
    for finding in manifest_findings:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
    print(
        "Redact the manifest or move secrets to environment, files, or command "
        "providers before capture.",
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
command_list: list[str] = []
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
        command_list.append(command)
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

required_commands = set(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
missing = sorted(required_commands - commands)
if missing:
    errors.append("manifest is missing production release commands: " + ", ".join(missing))
extra = sorted(commands - required_commands)
if extra:
    errors.append("manifest contains unknown production release commands: " + ", ".join(extra))
duplicates = sorted({command for command in command_list if command_list.count(command) > 1})
if duplicates:
    errors.append("manifest contains duplicate production release commands: " + ", ".join(duplicates))

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(65)

out_root.mkdir(parents=True, exist_ok=True)
shutil.copyfile(manifest_path, out_root / "operator-soak-manifest.json")
redaction_scan_path = out_root / "redaction-scan.json"
write_redaction_scan(
    redaction_scan_path,
    scope="preflight",
    scanned_files=[str(manifest_path)],
    findings=[],
)
preflight = {
    "ok": True,
    "preflight_only": os.environ.get("PREFLIGHT_ONLY") == "1",
    "source_manifest": str(manifest_path),
    "copied_manifest": str(out_root / "operator-soak-manifest.json"),
    "redaction_scan": str(redaction_scan_path),
    "started_at": os.environ["STARTED_AT"],
    "required_commands": list(PRODUCTION_RELEASE_REQUIRED_COMMANDS),
    "provided_commands": sorted(commands),
}
(out_root / "preflight.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
PY

if [ "${PREFLIGHT_ONLY}" = "1" ]; then
  cat "${OUT_ROOT}/preflight.json"
  exit 0
fi

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
import hashlib
import json
import os
import sys
from pathlib import Path

repo_dir = Path(os.environ["REPO_DIR"])
sys.path.insert(0, str(repo_dir / "src"))

from mnemosyne.evidence_redaction import scan_evidence_tree  # noqa: E402


out_root = Path(os.environ["OUT_ROOT"])
soak = json.loads((out_root / "deployment-soak.stdout.json").read_text(encoding="utf-8"))
audit = json.loads((out_root / "release-audit.json").read_text(encoding="utf-8"))
redaction_scan = scan_evidence_tree(out_root)
(out_root / "redaction-scan.json").write_text(
    json.dumps(redaction_scan, indent=2),
    encoding="utf-8",
)
if redaction_scan["findings"]:
    print(
        "ERROR: high-confidence secret material found in the production evidence bundle:",
        file=sys.stderr,
    )
    for finding in redaction_scan["findings"]:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
if redaction_scan.get("skipped_files"):
    print(
        "ERROR: production evidence bundle contains unscanned files:",
        file=sys.stderr,
    )
    for skipped in redaction_scan["skipped_files"]:
        print(
            f"  - {skipped['path']}: {skipped['reason']}",
            file=sys.stderr,
        )
if not redaction_scan["ok"]:
    print(
        "Do not publish this bundle. Redact the affected file or move the secret "
        "to environment, files, or command providers; remove unscannable artifacts; "
        "then rerun capture.",
        file=sys.stderr,
    )
    sys.exit(65)

excluded_manifest_paths = {"bundle-manifest.json", "summary.json"}
bundle_files = []
for file_path in sorted(path for path in out_root.rglob("*") if path.is_file()):
    rel_path = file_path.relative_to(out_root).as_posix()
    if rel_path in excluded_manifest_paths:
        continue
    payload = file_path.read_bytes()
    bundle_files.append(
        {
            "path": rel_path,
            "size_bytes": len(payload),
            "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }
    )
bundle_manifest_payload = {
    "schema": "mnemosyne.production-evidence-bundle.v1",
    "files": bundle_files,
}
bundle_fingerprint = "sha256:" + hashlib.sha256(
    json.dumps(
        bundle_manifest_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
bundle_manifest = {
    **bundle_manifest_payload,
    "artifact_count": len(bundle_files),
    "fingerprint": bundle_fingerprint,
}
(out_root / "bundle-manifest.json").write_text(
    json.dumps(bundle_manifest, indent=2),
    encoding="utf-8",
)

summary = {
    "out_root": str(out_root),
    "operator_manifest": str(out_root / "operator-soak-manifest.json"),
    "evidence_manifest": str(out_root / "evidence/manifest.json"),
    "redaction_scan": str(out_root / "redaction-scan.json"),
    "bundle_manifest": str(out_root / "bundle-manifest.json"),
    "bundle_fingerprint": bundle_fingerprint,
    "redaction_scan_ok": redaction_scan["ok"],
    "deployment_soak_ok": soak.get("ok") is True,
    "release_audit_ok": audit.get("ok") is True,
    "release_audit_fingerprint": audit.get("fingerprint"),
    "release_audit_findings": audit.get("findings", []),
    "completed_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
}
(out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
PY
