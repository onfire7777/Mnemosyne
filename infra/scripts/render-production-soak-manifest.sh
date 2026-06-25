#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'USAGE'
Usage:
  infra/scripts/render-production-soak-manifest.sh --output OUT [--template TEMPLATE] [--force]
  infra/scripts/render-production-soak-manifest.sh --list-placeholders [--template TEMPLATE]

Renders infra/templates/production-soak-manifest.template.json by replacing every
MNEMOSYNE_PROD_* placeholder from the current environment. The rendered manifest
is validated for production scope and full release-command coverage. Secret
values still belong in environment variables, mounted files, Vault/KMS, or
command providers; do not put raw secrets in MNEMOSYNE_PROD_* placeholders.

Options:
  --template PATH       Template path. Defaults to infra/templates/production-soak-manifest.template.json.
  --output PATH         Destination manifest path. Required unless --list-placeholders is used.
  --force              Overwrite OUT if it already exists.
  --allow-repo-output  Permit writing OUT inside this repository. Default is to refuse.
  --list-placeholders  Print required MNEMOSYNE_PROD_* placeholder names as JSON.
  -h, --help           Show this help text.
USAGE
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"

TEMPLATE="${REPO_DIR}/infra/templates/production-soak-manifest.template.json"
OUTPUT=""
FORCE=0
ALLOW_REPO_OUTPUT=0
LIST_PLACEHOLDERS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --template)
      TEMPLATE="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --allow-repo-output)
      ALLOW_REPO_OUTPUT=1
      shift
      ;;
    --list-placeholders)
      LIST_PLACEHOLDERS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 64
      ;;
  esac
done

PYTHON="${MNEMOSYNE_PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
    PYTHON="${REPO_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

export TEMPLATE OUTPUT FORCE ALLOW_REPO_OUTPUT LIST_PLACEHOLDERS REPO_DIR

"${PYTHON}" - <<'PY'
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

repo_dir = Path(os.environ["REPO_DIR"]).resolve()
sys.path.insert(0, str(repo_dir / "src"))

from mnemosyne.cli import PRODUCTION_RELEASE_REQUIRED_COMMANDS  # noqa: E402

template_path = Path(os.environ["TEMPLATE"]).expanduser().resolve()
output_raw = os.environ.get("OUTPUT", "")
force = os.environ.get("FORCE") == "1"
allow_repo_output = os.environ.get("ALLOW_REPO_OUTPUT") == "1"
list_placeholders = os.environ.get("LIST_PLACEHOLDERS") == "1"
placeholder_re = re.compile(r"MNEMOSYNE_PROD_[A-Z0-9_]+")

if not template_path.is_file():
    print(f"ERROR: template not found: {template_path}", file=sys.stderr)
    raise SystemExit(66)

template_text = template_path.read_text(encoding="utf-8")
required = sorted(set(placeholder_re.findall(template_text)))

if list_placeholders:
    print(json.dumps({"template": str(template_path), "placeholders": required}, indent=2))
    raise SystemExit(0)

if not output_raw:
    print("ERROR: --output is required unless --list-placeholders is used", file=sys.stderr)
    raise SystemExit(64)

output_path = Path(output_raw).expanduser().resolve()
try:
    output_path.relative_to(repo_dir)
    inside_repo = True
except ValueError:
    inside_repo = False

if inside_repo and not allow_repo_output:
    print(
        "ERROR: refusing to write production manifest inside the repository; "
        "choose an external path or pass --allow-repo-output",
        file=sys.stderr,
    )
    raise SystemExit(73)

if output_path.exists() and not force:
    print(f"ERROR: output already exists: {output_path} (pass --force to overwrite)", file=sys.stderr)
    raise SystemExit(73)

missing = [name for name in required if not os.environ.get(name)]
if missing:
    print("ERROR: missing required production placeholder environment variables:", file=sys.stderr)
    for name in missing:
        print(f"  - {name}", file=sys.stderr)
    raise SystemExit(78)

evidence_dir_raw = os.environ.get("MNEMOSYNE_PROD_EVIDENCE_DIR", "")
evidence_dir = Path(evidence_dir_raw).expanduser()
if not evidence_dir.is_absolute():
    print(
        "ERROR: MNEMOSYNE_PROD_EVIDENCE_DIR must be an absolute external production input-artifact path",
        file=sys.stderr,
    )
    raise SystemExit(78)
evidence_dir_resolved = evidence_dir.resolve(strict=False)
try:
    evidence_dir_resolved.relative_to(repo_dir)
except ValueError:
    pass
else:
    print(
        "ERROR: MNEMOSYNE_PROD_EVIDENCE_DIR must not point inside the repository; "
        f"choose an external custody path: {evidence_dir_resolved}",
        file=sys.stderr,
    )
    raise SystemExit(78)

manifest = json.loads(template_text)

def render_value(value: Any) -> Any:
    if isinstance(value, str):
        rendered = value
        for name in required:
            rendered = rendered.replace(name, os.environ[name])
        return rendered
    if isinstance(value, list):
        return [render_value(item) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item) for key, item in value.items()}
    return value

rendered_manifest = render_value(manifest)
rendered_text = json.dumps(rendered_manifest, indent=2) + "\n"
leftovers = sorted(set(placeholder_re.findall(rendered_text)))
if leftovers or "MNEMOSYNE_PROD_" in rendered_text:
    print("ERROR: unresolved production placeholders remain after rendering:", file=sys.stderr)
    for name in leftovers or ["MNEMOSYNE_PROD_"]:
        print(f"  - {name}", file=sys.stderr)
    raise SystemExit(78)

scope = rendered_manifest.get("validation_scope", {})
errors: list[str] = []
if not isinstance(scope, dict):
    errors.append("validation_scope must be an object")
else:
    if scope.get("production_validated") is not True:
        errors.append("validation_scope.production_validated must be true")
    if scope.get("target_environment") != "production":
        errors.append('validation_scope.target_environment must be "production"')
    if scope.get("operator_asserted") is not True:
        errors.append("validation_scope.operator_asserted must be true")

checks = rendered_manifest.get("checks", [])
if not isinstance(checks, list):
    errors.append("checks must be a list")
    check_commands: list[str] = []
else:
    check_commands = [str(check.get("command")) for check in checks if isinstance(check, dict)]

required_commands = set(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
command_set = set(check_commands)
missing_commands = sorted(required_commands - command_set)
extra_commands = sorted(command_set - required_commands)
duplicate_commands = sorted({command for command in check_commands if check_commands.count(command) > 1})
if missing_commands:
    errors.append(f"missing production release commands: {', '.join(missing_commands)}")
if extra_commands:
    errors.append(f"unknown production release commands: {', '.join(extra_commands)}")
if duplicate_commands:
    errors.append(f"duplicate production release commands: {', '.join(duplicate_commands)}")

if errors:
    print("ERROR: rendered production manifest is invalid:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    raise SystemExit(78)

output_path.parent.mkdir(parents=True, exist_ok=True)
tmp_path = output_path.with_name(f".{output_path.name}.tmp")
tmp_path.write_text(rendered_text, encoding="utf-8")
tmp_path.chmod(0o600)
tmp_path.replace(output_path)
output_path.chmod(0o600)

print(
    json.dumps(
        {
            "ok": True,
            "template": str(template_path),
            "output": str(output_path),
            "placeholder_count": len(required),
            "command_count": len(check_commands),
            "values_redacted": True,
            "production_validated": scope.get("production_validated"),
            "target_environment": scope.get("target_environment"),
            "operator_asserted": scope.get("operator_asserted"),
        },
        indent=2,
    )
)
PY
