#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'USAGE'
Usage:
  infra/scripts/capture-production-evidence.sh [--env-file ENV] --preflight-only SOAK_MANIFEST OUT_ROOT
  infra/scripts/capture-production-evidence.sh [--env-file ENV] --fingerprint-record-output PATH SOAK_MANIFEST OUT_ROOT

Runs the existing production evidence path:
  1. Validate that SOAK_MANIFEST is explicitly production-scoped.
  2. Copy source-soak-manifest.json and operator-soak-manifest.json, snapshot
     referenced external input artifacts under OUT_ROOT/input-artifacts,
     retain command/tool executables under OUT_ROOT/tool-artifacts, and rewrite
     the copied operator manifest to those retained input snapshots.
  3. Preflight redaction-scan the retained manifest and input artifacts.
  4. Run deployment-soak with --evidence-dir.
  5. Run release-audit with --evidence-manifest "$OUT_ROOT/evidence/manifest.json",
     --require-production-validated, and --require-provider-forbid-local.
  6. Redaction-scan generated evidence and fail on findings or skipped files.
  7. Write bundle-manifest.json and summary.json with bundle_fingerprint.

OUT_ROOT is required and must be an explicit absolute external custody path
outside the repository for both preflight-only and full production capture.

Reviewers can recheck a completed bundle offline with the independently retained
bundle fingerprint record written at capture time:
  PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"
  BUNDLE_DIR=OUT_ROOT
  FINGERPRINT_RECORD=/secure/path/to/mnemosyne-production-bundle-fingerprint.json
  EXPECTED_BUNDLE_FINGERPRINT="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["bundle_fingerprint"])' "$FINGERPRINT_RECORD")"
  VERIFY_REPORT=/secure/path/to/mnemosyne-production-evidence-verify.json
  "$PYTHON" -m mnemosyne.cli production-evidence-verify "$BUNDLE_DIR" \
    --expected-bundle-fingerprint "$EXPECTED_BUNDLE_FINGERPRINT" \
    --report-output "$VERIFY_REPORT"
This is custody review only; it does not rerun production checks or flip rows.

The manifest must contain validation_scope.production_validated=true,
validation_scope.target_environment="production", and
validation_scope.operator_asserted=true. Secrets must come from environment,
files, or command providers; do not put tokens directly in manifest args.

Options:
  --env-file ENV   Strict optional runtime/provider dotenv file for production
                   capture. Must be absolute, external, non-symlinked, mode
                   0600, and contain only allowlisted Mnemosyne operator env
                   names. This avoids shell-sourcing secret-bearing env files.
  --preflight-only  Validate and copy the manifest, write preflight.json, then
                    exit before deployment-soak or release-audit runs. Preflight
                    writes source/operator manifest copies, retained input
                    artifact snapshots, and redaction-scan.json for setup proof.
  --fingerprint-record-output PATH
                    Required for full capture. Writes an external JSON record
                    for the bundle fingerprint. Must be absolute, external,
                    outside the evidence bundle, non-symlinked, and must not
                    already exist.
USAGE
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"

PREFLIGHT_ONLY=0
ENV_FILE=""
FINGERPRINT_RECORD_OUTPUT=""
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
    --env-file)
      if [ -z "${2:-}" ]; then
        echo "ERROR: --env-file requires an absolute external path" >&2
        usage
        exit 64
      fi
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --fingerprint-record-output)
      if [ -z "${2:-}" ]; then
        echo "ERROR: --fingerprint-record-output requires an absolute external path" >&2
        usage
        exit 64
      fi
      FINGERPRINT_RECORD_OUTPUT="${2:-}"
      shift 2
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

case "${MANIFEST}" in
  /*) ;;
  *)
    echo "ERROR: production soak manifest path must be absolute: ${MANIFEST}" >&2
    exit 65
    ;;
esac

if [ ! -f "${MANIFEST}" ]; then
  echo "ERROR: production soak manifest not found: ${MANIFEST}" >&2
  exit 66
fi

if [ -z "${2:-}" ]; then
  echo "ERROR: production evidence output root is required; pass an explicit absolute external OUT_ROOT" >&2
  exit 64
else
  OUT_ROOT_RAW="${2}"
fi
case "${OUT_ROOT_RAW}" in
  /*) ;;
  *)
    echo "ERROR: production evidence output root must be absolute: ${OUT_ROOT_RAW}" >&2
    exit 65
    ;;
esac

PYTHON="${MNEMOSYNE_PYTHON:-}"
if [ -z "${PYTHON}" ]; then
  if [ -x "${REPO_DIR}/.venv/bin/python" ]; then
    PYTHON="${REPO_DIR}/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

OUT_ROOT="$("${PYTHON}" - "${OUT_ROOT_RAW}" "${REPO_DIR}" <<'PY'
from pathlib import Path
import sys

out_root_raw = Path(sys.argv[1]).expanduser()
if out_root_raw.is_symlink():
    print(
        f"ERROR: production evidence output root cannot be a symlink: {out_root_raw}",
        file=sys.stderr,
    )
    sys.exit(65)
out_root = out_root_raw.resolve(strict=False)
repo_dir = Path(sys.argv[2]).resolve()
try:
    out_root.relative_to(repo_dir)
except ValueError:
    print(out_root)
else:
    print(
        f"ERROR: refusing to write production evidence inside the repository: {out_root}",
        file=sys.stderr,
    )
    print(
        "Choose an external custody path such as /secure/path/to/mnemosyne-production-evidence.",
        file=sys.stderr,
    )
    sys.exit(65)
PY
)"
if [ -e "${OUT_ROOT}" ] || [ -L "${OUT_ROOT}" ]; then
  echo "ERROR: production evidence output root must not already exist: ${OUT_ROOT}" >&2
  exit 65
fi

if [ "${PREFLIGHT_ONLY}" != "1" ] && [ -z "${FINGERPRINT_RECORD_OUTPUT}" ]; then
  echo "ERROR: full production capture requires --fingerprint-record-output for external custody review" >&2
  exit 64
fi

if [ -n "${FINGERPRINT_RECORD_OUTPUT}" ]; then
  if [ "${PREFLIGHT_ONLY}" = "1" ]; then
    echo "ERROR: --fingerprint-record-output is only valid for full production capture" >&2
    exit 64
  fi
  FINGERPRINT_RECORD_OUTPUT_RESOLVED="$("${PYTHON}" - "${FINGERPRINT_RECORD_OUTPUT}" "${REPO_DIR}" "${OUT_ROOT}" <<'PY'
from pathlib import Path
import sys

raw = Path(sys.argv[1]).expanduser()
repo_dir = Path(sys.argv[2]).resolve()
out_root = Path(sys.argv[3]).resolve(strict=False)
if not raw.is_absolute():
    print("ERROR: production fingerprint record output must be an absolute external path", file=sys.stderr)
    sys.exit(65)
if raw.exists() or raw.is_symlink():
    print("ERROR: production fingerprint record output must not already exist or be a symlink", file=sys.stderr)
    sys.exit(65)
resolved = raw.resolve(strict=False)
try:
    resolved.relative_to(out_root)
except ValueError:
    pass
else:
    print("ERROR: production fingerprint record output must be outside the evidence bundle", file=sys.stderr)
    sys.exit(65)
parent = raw.parent
if parent.is_symlink():
    print("ERROR: production fingerprint record output parent must not be a symlink", file=sys.stderr)
    sys.exit(65)
if not parent.exists() or not parent.is_dir():
    print("ERROR: production fingerprint record output parent must be an existing directory", file=sys.stderr)
    sys.exit(65)
parent_resolved = parent.resolve(strict=True)
try:
    resolved.relative_to(repo_dir)
except ValueError:
    pass
else:
    print("ERROR: production fingerprint record output must not point inside the repository", file=sys.stderr)
    sys.exit(65)
try:
    parent_resolved.relative_to(repo_dir)
except ValueError:
    pass
else:
    print("ERROR: production fingerprint record output parent must not be inside the repository", file=sys.stderr)
    sys.exit(65)
try:
    parent_resolved.relative_to(out_root)
except ValueError:
    pass
else:
    print("ERROR: production fingerprint record output parent must be outside the evidence bundle", file=sys.stderr)
    sys.exit(65)
print(resolved)
PY
)"
else
  FINGERPRINT_RECORD_OUTPUT_RESOLVED=""
fi

MANIFEST_PATH="$(cd "$(dirname "${MANIFEST}")" && pwd)/$(basename "${MANIFEST}")"
MANIFEST_PATH="$("${PYTHON}" - "${MANIFEST_PATH}" "${REPO_DIR}" <<'PY'
from pathlib import Path
import sys

manifest_path = Path(sys.argv[1]).expanduser().resolve(strict=True)
repo_dir = Path(sys.argv[2]).resolve()
try:
    manifest_path.relative_to(repo_dir)
except ValueError:
    print(manifest_path)
else:
    print(
        f"ERROR: refusing to use production soak manifest inside the repository: {manifest_path}",
        file=sys.stderr,
    )
    print(
        "Render the manifest to an external custody path such as /secure/path/to/production-soak-manifest.json.",
        file=sys.stderr,
    )
    sys.exit(65)
PY
)"

if [ -n "${ENV_FILE}" ]; then
  ENV_FILE_RESOLVED="$("${PYTHON}" - "${ENV_FILE}" "${REPO_DIR}" <<'PY'
from pathlib import Path
import sys

env_file = Path(sys.argv[1]).expanduser()
repo_dir = Path(sys.argv[2]).resolve()
if not env_file.is_absolute():
    print("ERROR: production capture --env-file must be an absolute external path", file=sys.stderr)
    sys.exit(65)
if env_file.is_symlink():
    print("ERROR: production capture --env-file must not be a symlink", file=sys.stderr)
    sys.exit(65)
try:
    env_file.relative_to(repo_dir)
except ValueError:
    pass
else:
    print("ERROR: production capture --env-file must not point inside the repository", file=sys.stderr)
    sys.exit(65)
resolved = env_file.resolve(strict=False)
try:
    resolved.relative_to(repo_dir)
except ValueError:
    print(resolved)
else:
    print("ERROR: production capture --env-file must not resolve inside the repository", file=sys.stderr)
    sys.exit(65)
PY
)"
  ENV_ALLOWED_KEYS=()
  while IFS= read -r key; do
    if [ -n "${key}" ]; then
      ENV_ALLOWED_KEYS+=("${key}")
    fi
  done < <("${PYTHON}" - "${REPO_DIR}" "${MANIFEST_PATH}" <<'PY'
import json
import re
import sys
from pathlib import Path

repo_dir = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
allowed: set[str] = set()
inventory = repo_dir / "infra" / "templates" / "production-operator-env.inventory.md"
for line in inventory.read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"- `([A-Z][A-Z0-9_]*)`", line.strip())
    if match:
        allowed.add(match.group(1))
try:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
except Exception:
    payload = {}


def collect_env_refs(value: object) -> None:
    if isinstance(value, dict):
        if set(value) == {"env"} and isinstance(value.get("env"), str):
            allowed.add(str(value["env"]))
        for item in value.values():
            collect_env_refs(item)
    elif isinstance(value, list):
        for item in value:
            collect_env_refs(item)


collect_env_refs(payload)
for key in sorted(allowed):
    print(key)
PY
)
  if [ "${#ENV_ALLOWED_KEYS[@]}" -eq 0 ]; then
    echo "ERROR: production capture --env-file allowlist is empty" >&2
    exit 65
  fi
  ENV_LOADED_ASSIGNMENTS="$("${PYTHON}" "${REPO_DIR}/infra/scripts/load-env.py" --allow-missing "${ENV_FILE_RESOLVED}" "${ENV_ALLOWED_KEYS[@]}")"
  while IFS='=' read -r key value; do
    if [ -n "${key}" ]; then
      export "${key}=${value}"
    fi
  done <<< "${ENV_LOADED_ASSIGNMENTS}"
  unset ENV_LOADED_ASSIGNMENTS
fi
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export MANIFEST_PATH OUT_ROOT REPO_DIR STARTED_AT PREFLIGHT_ONLY PYTHON FINGERPRINT_RECORD_OUTPUT_RESOLVED

"${PYTHON}" - <<'PY'
import json
import hashlib
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

repo_dir = Path(os.environ["REPO_DIR"])
sys.path.insert(0, str(repo_dir / "src"))

from mnemosyne.cli import (  # noqa: E402
    PRODUCTION_RELEASE_REQUIRED_COMMANDS,
    PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS,
)
from mnemosyne.evidence_redaction import (  # noqa: E402
    manifest_argument_secret_errors,
    redaction_findings,
    scan_evidence_paths,
    write_redaction_scan,
)
from mnemosyne.production_parity import (  # noqa: E402
    annotate_artifact_routes,
    build_parity_row_readiness,
    parity_lanes_for_command,
)


manifest_path = Path(os.environ["MANIFEST_PATH"])
out_root = Path(os.environ["OUT_ROOT"])
try:
    manifest_text = manifest_path.read_text(encoding="utf-8")
except (OSError, UnicodeDecodeError) as exc:
    print(f"ERROR: production soak manifest cannot be read: {exc}", file=sys.stderr)
    sys.exit(65)
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

try:
    manifest = json.loads(manifest_text)
except json.JSONDecodeError as exc:
    print(f"ERROR: production soak manifest is not valid JSON: {exc}", file=sys.stderr)
    sys.exit(65)

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
required_artifacts: dict[str, dict[str, object]] = {}
artifact_occurrences: list[dict[str, object]] = []
executable_tool_references: dict[str, dict[str, object]] = {}
suite_case_artifact_rewrites: dict[str, list[dict[str, object]]] = {}
file_suffixes = {
    ".csv",
    ".crt",
    ".cer",
    ".html",
    ".json",
    ".jsonl",
    ".pem",
    ".txt",
    ".yaml",
    ".yml",
    ".zip",
}
executable_path_options = {
    "--c2pa-tool",
}

def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)

def _looks_like_file_path(value: str) -> bool:
    if not value or value.startswith("-") or _is_url(value):
        return False
    if value.startswith(("/", "./", "../", "~")):
        return True
    path = Path(value)
    return path.suffix.lower() in file_suffixes or value in {
        "dashboard-package",
    }

def _resolve_checked(path: Path, *, label: str, strict: bool = False) -> Path | None:
    try:
        return path.resolve(strict=strict)
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} contains invalid path {path}: {exc}")
        return None

def _path_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()

def _reject_symlinked_input_path(path: Path, *, label: str) -> bool:
    try:
        is_symlink = path.is_symlink()
    except (OSError, RuntimeError, ValueError) as exc:
        errors.append(f"{label} contains invalid path {path}: {exc}")
        return True
    if is_symlink:
        errors.append(f"{label} points to a symlinked input artifact path: {path}; use a regular external file or directory")
        return True
    return False

def _record_required_artifact(
    resolved: Path,
    *,
    label: str,
    check_metadata: dict[str, object] | None = None,
    occurrence: dict[str, object] | None = None,
    source_value: str | None = None,
) -> None:
    artifact = required_artifacts.setdefault(
        str(resolved),
        {
            "path": str(resolved),
            "labels": [],
            "checks": [],
            "source_values": [],
        },
    )
    artifact["labels"].append(label)
    if source_value is not None and source_value:
        artifact["source_values"].append(source_value)
    if check_metadata is not None:
        artifact["checks"].append(check_metadata)
    if occurrence is not None:
        artifact_occurrences.append(occurrence)

def _check_metadata(command: str, check_name: str, option: str) -> dict[str, object]:
    return {
        "name": check_name,
        "command": command,
        "option": option,
        "parity_lanes": parity_lanes_for_command(command),
    }

def _dedupe_checks(checks: object) -> list[dict[str, object]]:
    if not isinstance(checks, list):
        return []
    deduped: dict[tuple[str, str, str], dict[str, object]] = {}
    for check in checks:
        if not isinstance(check, dict):
            continue
        name = check.get("name")
        command = check.get("command")
        option = check.get("option")
        lanes = check.get("parity_lanes")
        if not all(isinstance(value, str) for value in (name, command, option)):
            continue
        if not isinstance(lanes, list) or not all(isinstance(lane, str) for lane in lanes):
            lanes = []
        deduped[(name, command, option)] = {
            "name": name,
            "command": command,
            "option": option,
            "parity_lanes": sorted(set(lanes)),
        }
    return sorted(
        deduped.values(),
        key=lambda item: (str(item["command"]), str(item["name"]), str(item["option"])),
    )

def _validate_external_file_path(
    value: str,
    *,
    check_index: int,
    command: str,
    check_name: str,
    field: str,
    value_index: int,
    label: str,
    option: str,
    replacement_prefix: str | None = None,
) -> None:
    if not _looks_like_file_path(value):
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        errors.append(f"{label} contains relative production artifact path {value}; use an absolute external path")
        return
    if _reject_symlinked_input_path(path, label=label):
        return
    resolved = _resolve_checked(path, label=label)
    if resolved is None:
        return
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        _record_required_artifact(
            resolved,
            label=label,
            check_metadata=_check_metadata(command, check_name, option),
            source_value=value,
            occurrence={
                "path": str(resolved),
                "check_index": check_index,
                "field": field,
                "value_index": value_index,
                "label": label,
                "replacement_prefix": replacement_prefix,
            },
        )
        return
    errors.append(f"{label} points inside the repository: {resolved}; use an external custody path")

def _validate_nested_input_artifact_path(value: object, *, label: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be a non-empty absolute external path")
        return None
    if _is_url(value):
        errors.append(f"{label} contains URL input artifact path; use an absolute external path")
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        errors.append(f"{label} contains relative input artifact path {value}; use an absolute external path")
        return None
    if _reject_symlinked_input_path(path, label=label):
        return None
    resolved = _resolve_checked(path, label=label)
    if resolved is None:
        return None
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        return resolved
    errors.append(f"{label} points inside the repository: {resolved}; use an external custody path")
    return None

def _validate_manifest_input_artifact_path(
    value: object,
    *,
    check_index: int,
    command: str,
    check_name: str,
    value_index: int,
    label: str,
) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must contain non-empty absolute external paths")
        return
    if _is_url(value):
        errors.append(f"{label} contains URL input artifact path; use an absolute external path")
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        errors.append(f"{label} contains relative input artifact path {value}; use an absolute external path")
        return
    if _reject_symlinked_input_path(path, label=label):
        return
    resolved = _resolve_checked(path, label=label)
    if resolved is None:
        return
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        _record_required_artifact(
            resolved,
            label=label,
            check_metadata=_check_metadata(
                command,
                check_name,
                f"input_artifacts[{value_index}]",
            ),
            source_value=value,
            occurrence={
                "path": str(resolved),
                "check_index": check_index,
                "field": "input_artifacts",
                "value_index": value_index,
                "label": label,
            },
        )
        return
    errors.append(f"{label} points inside the repository: {resolved}; use an external custody path")

def _validate_executable_tool_path(
    value: str,
    *,
    option_name: str,
    label: str,
) -> None:
    if not value:
        errors.append(f"{label} contains empty executable path for {option_name}")
        return
    if _is_url(value):
        errors.append(f"{label} contains URL executable path for {option_name}; use an absolute local path")
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        errors.append(f"{label} contains relative executable path for {option_name}; use an absolute external path")
        return
    resolved = _resolve_checked(path, label=label)
    if resolved is None:
        return
    lexical_path = Path(os.path.abspath(os.fspath(path)))
    if lexical_path != resolved:
        errors.append(
            f"{label} executable path for {option_name} points through a symlink or non-canonical path: "
            f"{path}; use the resolved deployed external tool path"
        )
        return
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        pass
    else:
        errors.append(f"{label} executable path points inside the repository: {resolved}; use a deployed external tool path")
        return
    if not resolved.exists():
        errors.append(f"{label} executable path for {option_name} does not exist: {resolved}")
        return
    if not resolved.is_file():
        errors.append(f"{label} executable path for {option_name} is not a file: {resolved}")
        return
    if not os.access(resolved, os.X_OK):
        errors.append(f"{label} executable path for {option_name} is not executable: {resolved}")
        return
    key = f"{option_name}:{resolved}"
    reference = executable_tool_references.setdefault(
        key,
        {
            "option": option_name,
            "path": str(resolved),
            "size_bytes": resolved.stat().st_size,
            "sha256": _path_sha256(resolved),
            "labels": [],
        },
    )
    reference["labels"].append(label)


def _validate_provider_command_arguments(command_parts: list[str], *, label: str) -> None:
    if len(command_parts) > 1:
        errors.append(
            f"{label} provider-manifest.command must be a single external executable "
            "with no arguments after argv[0]; put provider implementation/config in "
            "the deployed wrapper or an explicit production input artifact"
        )


def _manifest_ref_value(value: object, *, label: str) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"env"} and isinstance(value.get("env"), str):
        env_name = str(value["env"])
        env_value = os.environ.get(env_name)
        if env_value is None or not env_value.strip():
            errors.append(f"{label} references unset environment variable {env_name}")
            return None
        return env_value
    errors.append(f"{label} command must be a string or {{\"env\": \"...\"}} reference")
    return None


def _provider_manifest_command_entries(value: object, *, path: str) -> list[tuple[str, object]]:
    entries: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "command":
                entries.append((child_path, item))
            entries.extend(_provider_manifest_command_entries(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            entries.extend(_provider_manifest_command_entries(item, path=f"{path}[{index}]"))
    return entries


def _validate_provider_manifest(value: str, *, label: str) -> None:
    if not value:
        return
    manifest_path = Path(value).expanduser()
    try:
        resolved_manifest = manifest_path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return
    try:
        payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} provider manifest cannot be inspected for preflight validation: {exc}")
        return
    if not isinstance(payload, dict):
        errors.append(f"{label} provider manifest must be a JSON object for preflight validation")
        return
    if payload.get("forbid_local") is not True:
        errors.append(f"{label} provider manifest must set forbid_local=true")
    required_checks = payload.get("required_checks")
    expected_checks = set(PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS)
    if not isinstance(required_checks, list) or not all(
        isinstance(item, str) for item in required_checks
    ):
        errors.append(f"{label} provider manifest required_checks must be a string array")
    else:
        actual_checks = set(required_checks)
        missing_checks = sorted(expected_checks - actual_checks)
        extra_checks = sorted(actual_checks - expected_checks)
        if missing_checks:
            errors.append(
                f"{label} provider manifest missing production provider checks: "
                + ", ".join(missing_checks)
            )
        if extra_checks:
            errors.append(
                f"{label} provider manifest contains unsupported provider checks: "
                + ", ".join(extra_checks)
            )
    if not isinstance(payload.get("providers"), dict):
        errors.append(f"{label} provider manifest providers must be an object")
    for command_path, raw_command in _provider_manifest_command_entries(
        payload,
        path="provider-manifest.production.json",
    ):
        command_value = _manifest_ref_value(raw_command, label=command_path)
        if command_value is None:
            continue
        try:
            command_parts = shlex.split(command_value)
        except ValueError as exc:
            errors.append(f"{command_path} command cannot be parsed: {exc}")
            continue
        if not command_parts:
            errors.append(f"{command_path} command must include an executable path")
            continue
        _validate_executable_tool_path(
            command_parts[0],
            option_name="provider-manifest.command",
            label=command_path,
        )
        _validate_provider_command_arguments(command_parts, label=command_path)


def _extract_option_values(values: list[str], option_name: str, *, label: str) -> tuple[list[str], int]:
    extracted: list[str] = []
    occurrences = 0
    for option_index, item in enumerate(values):
        if item == option_name:
            occurrences += 1
            if option_index + 1 >= len(values) or not values[option_index + 1] or values[option_index + 1].startswith("--"):
                errors.append(f"{label} option {option_name} requires a non-empty value")
            else:
                extracted.append(values[option_index + 1])
        elif item.startswith(option_name + "="):
            occurrences += 1
            option_value = item.split("=", 1)[1]
            if not option_value:
                errors.append(f"{label} option {option_name} requires a non-empty value")
            else:
                extracted.append(option_value)
    return extracted, occurrences

def _parse_provenance_suite_path(suite_value: str, *, label: str) -> tuple[Path, dict[str, object]] | None:
    if not suite_value or not suite_value.strip():
        errors.append(f"{label} provenance trust suite path must be non-empty")
        return None
    if _is_url(suite_value):
        errors.append(f"{label} provenance trust suite path must be an absolute external file path, not a URL")
        return None
    path = Path(suite_value).expanduser()
    if not path.is_absolute():
        errors.append(f"{label} contains relative provenance trust suite path {suite_value}; use an absolute external path")
        return None
    if _reject_symlinked_input_path(path, label=label):
        return None
    resolved = _resolve_checked(path, label=label)
    if resolved is None:
        return None
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        pass
    else:
        errors.append(f"{label} provenance trust suite points inside the repository: {resolved}; use an external custody path")
        return None
    if not resolved.exists():
        errors.append(f"{label} provenance trust suite does not exist: {resolved}")
        return None
    if not resolved.is_file():
        errors.append(f"{label} provenance trust suite is not a file: {resolved}")
        return None
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} provenance trust suite denied: {exc}")
        return None
    if not isinstance(data, dict):
        errors.append(f"{label} provenance trust suite must be a JSON object")
        return None
    return resolved, data

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
        command = ""
    check_name = check.get("name")
    if not isinstance(check_name, str) or not check_name:
        check_name = command
    check_args = check.get("args", [])
    check_global_args = check.get("global_args", [])
    input_artifacts = check.get("input_artifacts", [])
    if "input_artifacts" in check:
        if not isinstance(input_artifacts, list) or not all(isinstance(v, str) for v in input_artifacts):
            errors.append(f"checks[{index}].input_artifacts must be an array of strings")
        else:
            for value_index, value in enumerate(input_artifacts):
                _validate_manifest_input_artifact_path(
                    value,
                    check_index=index - 1,
                    command=command,
                    check_name=check_name,
                    value_index=value_index,
                    label=f"checks[{index}].input_artifacts",
                )
    for field in ("args", "global_args"):
        values = check.get(field, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            errors.append(f"checks[{index}].{field} must be an array of strings")
            continue
        for value_index, value in enumerate(values):
            option_name, separator, option_value = value.partition("=")
            if command == "ops-report" and option_name in {"--dashboard-html", "--dashboard-package-dir"}:
                errors.append(
                    f"checks[{index}].{field} contains ops-report output option "
                    f"{option_name}; production capture must not write "
                    "generated dashboard artifacts into input-artifact custody"
                )
            if option_name in executable_path_options and separator:
                _validate_executable_tool_path(
                    option_value,
                    option_name=option_name,
                    label=f"checks[{index}].{field}",
                )
                continue
            if command == "provenance-trust-check" and option_name == "--suite" and separator:
                _validate_external_file_path(
                    option_value,
                    check_index=index - 1,
                    command=command,
                    check_name=check_name,
                    field=field,
                    value_index=value_index,
                    label=f"checks[{index}].{field}",
                    option=option_name,
                    replacement_prefix=f"{option_name}=",
                )
                continue
            if separator:
                _validate_external_file_path(
                    option_value,
                    check_index=index - 1,
                    command=command,
                    check_name=check_name,
                    field=field,
                    value_index=value_index,
                    label=f"checks[{index}].{field}",
                    option=option_name,
                    replacement_prefix=f"{option_name}=",
                )
                if option_name == "--provider-manifest":
                    _validate_provider_manifest(
                        option_value,
                        label=f"checks[{index}].{field} {option_name}",
                    )
                continue
            previous_option = None
            if value_index > 0:
                previous_value = values[value_index - 1]
                if previous_value.startswith("--") and "=" not in previous_value:
                    previous_option = previous_value
            if command == "ops-report" and previous_option == "--dashboard-package-dir":
                errors.append(
                    f"checks[{index}].{field} contains ops-report output option "
                    "--dashboard-package-dir; production capture must not write "
                    "generated dashboard packages into input-artifact custody"
                )
                continue
            if previous_option in executable_path_options:
                _validate_executable_tool_path(
                    value,
                    option_name=previous_option,
                    label=f"checks[{index}].{field}",
                )
                continue
            _validate_external_file_path(
                value,
                check_index=index - 1,
                command=command,
                check_name=check_name,
                field=field,
                value_index=value_index,
                label=f"checks[{index}].{field}",
                option=previous_option or field,
            )
            if previous_option == "--provider-manifest":
                _validate_provider_manifest(
                    value,
                    label=f"checks[{index}].{field} {previous_option}",
                )
    provenance_args: list[str] = []
    provenance_global_args: list[str] = []
    if command == "provenance-trust-check":
        if isinstance(check_args, list) and all(isinstance(v, str) for v in check_args):
            provenance_args.extend(check_args)
        if isinstance(check_global_args, list) and all(isinstance(v, str) for v in check_global_args):
            provenance_global_args.extend(check_global_args)
    if command == "provenance-trust-check" and (provenance_args or provenance_global_args):
        _global_suite_values, global_suite_occurrences = _extract_option_values(
            provenance_global_args,
            "--suite",
            label=f"checks[{index}].global_args",
        )
        _global_suite_json_values, global_suite_json_occurrences = _extract_option_values(
            provenance_global_args,
            "--suite-json",
            label=f"checks[{index}].global_args",
        )
        _global_c2pa_tool_values, global_c2pa_tool_occurrences = _extract_option_values(
            provenance_global_args,
            "--c2pa-tool",
            label=f"checks[{index}].global_args",
        )
        if global_suite_occurrences or global_suite_json_occurrences or global_c2pa_tool_occurrences:
            errors.append(
                f"checks[{index}].global_args contains provenance-trust-check command options; "
                "put --suite and --c2pa-tool in args so deployment-soak passes them after the child command"
            )
        suite_json_values, suite_json_occurrences = _extract_option_values(
            provenance_args,
            "--suite-json",
            label=f"checks[{index}].args",
        )
        suite_values, suite_occurrences = _extract_option_values(
            provenance_args,
            "--suite",
            label=f"checks[{index}].args",
        )
        if suite_json_occurrences:
            errors.append(
                f"checks[{index}].args uses --suite-json; production capture requires --suite "
                "with an external JSON file so nested asset paths can be snapshotted"
            )
        if not suite_values and not suite_json_occurrences and not suite_occurrences:
            continue
        if suite_occurrences != 1 or len(suite_values) != 1:
            errors.append(f"checks[{index}].args must include exactly one --suite path")
            suite_values = []
        direct_tools, _direct_tool_occurrences = _extract_option_values(
            provenance_args,
            "--c2pa-tool",
            label=f"checks[{index}].args",
        )
        suite_tool_seen = False
        for suite_value in suite_values:
            parsed_suite = _parse_provenance_suite_path(
                suite_value,
                label=f"checks[{index}].args",
            )
            if parsed_suite is None:
                continue
            suite_path, suite_data = parsed_suite
            suite_rewrites = suite_case_artifact_rewrites.setdefault(str(suite_path), [])
            for tool_field in ("tool", "c2pa_tool"):
                tool_value = suite_data.get(tool_field)
                if isinstance(tool_value, str) and tool_value.strip():
                    suite_tool_seen = True
                    _validate_executable_tool_path(
                        tool_value,
                        option_name=f"suite.{tool_field}",
                        label=f"checks[{index}].args {tool_field}",
                    )
            cases = suite_data.get("cases")
            if not isinstance(cases, list):
                errors.append(f"checks[{index}].args provenance trust suite cases must be an array")
                continue
            for case_index, case in enumerate(cases):
                if not isinstance(case, dict):
                    errors.append(f"checks[{index}].args suite cases[{case_index}] must be an object")
                    continue
                for asset_field in ("asset_path", "c2pa_asset_path"):
                    if asset_field not in case:
                        continue
                    asset_path = _validate_nested_input_artifact_path(
                        case.get(asset_field),
                        label=f"checks[{index}].args suite cases[{case_index}].{asset_field}",
                    )
                    if asset_path is not None:
                        _record_required_artifact(
                            asset_path,
                            label=f"checks[{index}].args suite cases[{case_index}].{asset_field}",
                            check_metadata=_check_metadata(
                                command,
                                check_name,
                                f"cases[{case_index}].{asset_field}",
                            ),
                            source_value=case.get(asset_field),
                        )
                        suite_rewrites.append(
                            {
                                "case_index": case_index,
                                "field": asset_field,
                                "path": str(asset_path),
                            }
                        )
        if not direct_tools and not suite_tool_seen:
            env_tool = os.environ.get("MNEMOSYNE_C2PA_TOOL", "")
            if env_tool:
                _validate_executable_tool_path(
                    env_tool,
                    option_name="MNEMOSYNE_C2PA_TOOL",
                    label="environment.MNEMOSYNE_C2PA_TOOL",
                )
            else:
                errors.append(
                    f"checks[{index}].args requires --c2pa-tool, suite tool/c2pa_tool, "
                    "or MNEMOSYNE_C2PA_TOOL"
                )

required_commands = set(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
errors.extend(manifest_argument_secret_errors(manifest))
missing = sorted(required_commands - commands)
if missing:
    errors.append("manifest is missing production release commands: " + ", ".join(missing))
extra = sorted(commands - required_commands)
if extra:
    errors.append("manifest contains unknown production release commands: " + ", ".join(extra))
duplicates = sorted({command for command in command_list if command_list.count(command) > 1})
if duplicates:
    errors.append("manifest contains duplicate production release commands: " + ", ".join(duplicates))

for artifact in required_artifacts.values():
    artifact_path = Path(str(artifact["path"]))
    labels = ", ".join(str(label) for label in artifact["labels"])
    if not artifact_path.exists():
        errors.append(
            f"required production input artifact does not exist: {artifact_path} ({labels})"
        )
    elif not artifact_path.is_file() and not artifact_path.is_dir():
        errors.append(
            f"required production input artifact is not a file or directory: {artifact_path} ({labels})"
        )

if not required_artifacts:
    errors.append(
        "production capture requires at least one retained production input artifact; "
        "provide manifest-referenced evidence such as a provenance trust suite, "
        "provider manifest, or row-specific production artifact"
    )

c2pa_reference_options = {
    "--c2pa-tool",
    "suite.tool",
    "suite.c2pa_tool",
    "MNEMOSYNE_C2PA_TOOL",
}
if "provenance-trust-check" in commands and not any(
    str(reference.get("option")) in c2pa_reference_options
    for reference in executable_tool_references.values()
):
    errors.append(
        "production capture requires retained C2PA executable metadata for "
        "provenance-trust-check; provide --suite with a suite tool/c2pa_tool, "
        "--c2pa-tool, or MNEMOSYNE_C2PA_TOOL"
    )

if errors:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(65)

input_scan = scan_evidence_paths(
    [Path(str(artifact["path"])) for artifact in required_artifacts.values()],
    scope="preflight-inputs",
    forbidden_roots=[repo_dir],
    reject_symlinks=True,
)
input_findings = input_scan.get("findings", [])
input_skipped = input_scan.get("skipped_files", [])
if input_findings:
    print(
        "ERROR: high-confidence secret material found in production input artifacts:",
        file=sys.stderr,
    )
    for finding in input_findings:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
    print(
        "Redact the input artifact or move secrets to environment, files, or "
        "command providers before capture.",
        file=sys.stderr,
    )
    sys.exit(65)
if input_skipped:
    print(
        "ERROR: production input artifacts include unscanned files:",
        file=sys.stderr,
    )
    for skipped in input_skipped:
        print(f"  - {skipped['path']}: {skipped['reason']}", file=sys.stderr)
    print(
        "Use UTF-8 text evidence within the scan limit, or replace binary/large "
        "inputs with redacted manifests before capture.",
        file=sys.stderr,
    )
    sys.exit(65)

def _artifact_snapshot_name(index: int, source_path: Path) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_path.name).strip("-")
    if not safe_name:
        safe_name = "artifact"
    return f"{index:04d}-{safe_name}"

def _tool_snapshot_name(index: int, reference: dict[str, object]) -> str:
    source_path = Path(str(reference["path"]))
    safe_option = re.sub(r"[^A-Za-z0-9._-]+", "-", str(reference["option"])).strip("-")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_path.name).strip("-")
    if not safe_option:
        safe_option = "tool"
    if not safe_name:
        safe_name = "executable"
    digest = str(reference["sha256"]).split(":", 1)[-1][:12]
    return f"{index:04d}-{safe_option}-{safe_name}-{digest}"

def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()

def _snapshot_file_entries(original_root: Path, snapshot_root: Path) -> list[dict[str, object]]:
    if snapshot_root.is_symlink():
        return []
    if snapshot_root.is_file():
        return [
            {
                "source_path": str(original_root.resolve(strict=True)),
                "snapshot_path": str(snapshot_root.resolve(strict=True)),
                "relative_path": snapshot_root.name,
                "size_bytes": snapshot_root.stat().st_size,
                "sha256": _sha256_path(snapshot_root),
            }
        ]
    files: list[dict[str, object]] = []
    for snapshot_file in sorted(path for path in snapshot_root.rglob("*") if path.is_file()):
        if snapshot_file.is_symlink():
            continue
        relative = snapshot_file.relative_to(snapshot_root)
        source_file = original_root / relative
        files.append(
            {
                "source_path": str(source_file.resolve(strict=True)),
                "snapshot_path": str(snapshot_file.resolve(strict=True)),
                "relative_path": relative.as_posix(),
                "size_bytes": snapshot_file.stat().st_size,
                "sha256": _sha256_path(snapshot_file),
            }
        )
    return files

try:
    out_root.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    out_root.mkdir(mode=0o700, exist_ok=False)
except FileExistsError:
    print(
        f"ERROR: production evidence output root must not already exist: {out_root}",
        file=sys.stderr,
    )
    sys.exit(65)
except OSError as exc:
    print(
        f"ERROR: failed to create production evidence output root {out_root}: {exc}",
        file=sys.stderr,
    )
    sys.exit(65)
if out_root.is_symlink() or not out_root.is_dir():
    print(
        f"ERROR: production evidence output root is not a regular directory: {out_root}",
        file=sys.stderr,
    )
    sys.exit(65)
out_root.chmod(0o700)
snapshot_root = out_root / "input-artifacts"
snapshot_root.mkdir(mode=0o700, exist_ok=True)
artifact_metadata: list[dict[str, object]] = []
path_rewrites: dict[str, str] = {}
for artifact_index, artifact in enumerate(
    sorted(required_artifacts.values(), key=lambda item: str(item["path"])),
    start=1,
):
    source_path = Path(str(artifact["path"]))
    snapshot_path = snapshot_root / _artifact_snapshot_name(artifact_index, source_path)
    if source_path.is_dir():
        shutil.copytree(source_path, snapshot_path, symlinks=True)
        kind = "directory"
    else:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, snapshot_path, follow_symlinks=False)
        kind = "file"
    if not snapshot_path.is_symlink():
        snapshot_path.chmod(0o600 if snapshot_path.is_file() else 0o700)
    path_rewrites[str(source_path.resolve(strict=False))] = str(snapshot_path.resolve(strict=True))
    metadata = {
        "path": str(source_path.resolve(strict=True)),
        "snapshot_path": str(snapshot_path.resolve(strict=True)),
        "kind": kind,
        "labels": sorted(set(str(label) for label in artifact["labels"])),
        "source_values": sorted(
            set(
                str(source_value)
                for source_value in artifact.get("source_values", [])
                if isinstance(source_value, str) and source_value
            )
        ),
        "checks": _dedupe_checks(artifact.get("checks")),
        "files": _snapshot_file_entries(source_path, snapshot_path),
    }
    annotate_artifact_routes(metadata)
    artifact_metadata.append(metadata)

for suite_source, rewrites in suite_case_artifact_rewrites.items():
    suite_snapshot_path = Path(path_rewrites[str(Path(suite_source).resolve(strict=False))])
    suite_data = json.loads(suite_snapshot_path.read_text(encoding="utf-8"))
    cases = suite_data.get("cases", [])
    if isinstance(cases, list):
        for rewrite in rewrites:
            case_index = int(rewrite["case_index"])
            field = str(rewrite["field"])
            original_path = str(Path(str(rewrite["path"])).resolve(strict=False))
            if 0 <= case_index < len(cases) and isinstance(cases[case_index], dict):
                cases[case_index][field] = path_rewrites[original_path]
    suite_snapshot_path.write_text(json.dumps(suite_data, indent=2, sort_keys=True), encoding="utf-8")

for artifact in artifact_metadata:
    artifact["files"] = _snapshot_file_entries(
        Path(str(artifact["path"])),
        Path(str(artifact["snapshot_path"])),
    )

tool_snapshot_root = out_root / "tool-artifacts"
tool_references = sorted(
    executable_tool_references.values(),
    key=lambda item: (str(item["option"]), str(item["path"])),
)
if tool_references:
    tool_snapshot_root.mkdir(mode=0o700, exist_ok=True)
for tool_index, reference in enumerate(tool_references, start=1):
    source_path = Path(str(reference["path"]))
    expected_sha256 = str(reference["sha256"])
    expected_size = int(reference["size_bytes"])
    if source_path.is_symlink() or not source_path.is_file():
        print(
            f"ERROR: executable tool changed before custody snapshot: {source_path}",
            file=sys.stderr,
        )
        sys.exit(65)
    before_sha256 = _sha256_path(source_path)
    before_size = source_path.stat().st_size
    if before_sha256 != expected_sha256 or before_size != expected_size:
        print(
            f"ERROR: executable tool bytes changed before custody snapshot: {source_path}",
            file=sys.stderr,
        )
        sys.exit(65)
    snapshot_path = tool_snapshot_root / _tool_snapshot_name(tool_index, reference)
    shutil.copy2(source_path, snapshot_path, follow_symlinks=False)
    snapshot_path.chmod(0o500)
    snapshot_sha256 = _sha256_path(snapshot_path)
    after_sha256 = _sha256_path(source_path)
    if snapshot_sha256 != expected_sha256 or after_sha256 != expected_sha256:
        print(
            f"ERROR: executable tool custody snapshot mismatch: {source_path}",
            file=sys.stderr,
        )
        sys.exit(65)
    reference["snapshot_path"] = str(snapshot_path.resolve(strict=True))
    reference["snapshot_relative_path"] = snapshot_path.relative_to(out_root).as_posix()
    reference["snapshot_size_bytes"] = snapshot_path.stat().st_size
    reference["snapshot_sha256"] = snapshot_sha256

tool_path_rewrites: dict[str, str] = {}
tool_env_overrides: dict[str, str] = {}
for reference in tool_references:
    retained_path = str(Path(str(reference["snapshot_path"])).resolve(strict=True))
    source_path = Path(str(reference["path"])).expanduser()
    for key in {str(source_path), str(source_path.resolve(strict=False))}:
        tool_path_rewrites[key] = retained_path
    if reference.get("option") == "MNEMOSYNE_C2PA_TOOL":
        tool_env_overrides["MNEMOSYNE_C2PA_TOOL"] = retained_path

tool_env_path = out_root / "tool-env.sh"
if tool_env_overrides:
    tool_env_path.write_text(
        "# Generated by capture-production-evidence.sh; contains retained tool paths only.\n"
        + "\n".join(
            f"export {name}={shlex.quote(value)}"
            for name, value in sorted(tool_env_overrides.items())
        )
        + "\n",
        encoding="utf-8",
    )
    tool_env_path.chmod(0o600)

def _retained_tool_path(value: str) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    candidates = [value, str(path)]
    try:
        candidates.append(str(path.resolve(strict=False)))
    except (OSError, RuntimeError, ValueError):
        pass
    for candidate in candidates:
        retained = tool_path_rewrites.get(candidate)
        if retained is not None:
            return retained
    return None

def _rewrite_operator_tool_value(value: object) -> object:
    if isinstance(value, str):
        if value.startswith("--c2pa-tool="):
            option, option_value = value.split("=", 1)
            retained = _retained_tool_path(option_value)
            if retained is not None:
                return option + "=" + retained
            return value
        retained = _retained_tool_path(value)
        return retained if retained is not None else value
    if isinstance(value, list):
        return [_rewrite_operator_tool_value(item) for item in value]
    if isinstance(value, dict):
        for key, item in list(value.items()):
            value[key] = _rewrite_operator_tool_value(item)
        return value
    return value

def _rewrite_command_to_retained_tool(raw_command: object, *, label: str) -> str | None:
    command_value = _manifest_ref_value(raw_command, label=label)
    if command_value is None:
        return None
    try:
        command_parts = shlex.split(command_value)
    except ValueError as exc:
        print(f"ERROR: {label} command cannot be parsed during custody rewrite: {exc}", file=sys.stderr)
        sys.exit(65)
    if not command_parts:
        print(f"ERROR: {label} command is empty during custody rewrite", file=sys.stderr)
        sys.exit(65)
    if len(command_parts) > 1:
        print(
            f"ERROR: {label} provider-manifest.command must be a single retained "
            "executable with no arguments after argv[0]",
            file=sys.stderr,
        )
        sys.exit(65)
    retained = _retained_tool_path(command_parts[0])
    if retained is None:
        print(
            f"ERROR: {label} command executable was not retained in tool-artifacts: {command_parts[0]}",
            file=sys.stderr,
        )
        sys.exit(65)
    command_parts[0] = retained
    return shlex.join(command_parts)

def _rewrite_provider_manifest_commands(value: object, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            child_path = f"{path}.{key}" if path else str(key)
            if key == "command":
                value[key] = _rewrite_command_to_retained_tool(item, label=child_path)
            else:
                _rewrite_provider_manifest_commands(item, path=child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _rewrite_provider_manifest_commands(item, path=f"{path}[{index}]")

def _rewrite_retained_input_tool_paths() -> None:
    for suite_source in sorted(suite_case_artifact_rewrites):
        suite_snapshot_path = Path(path_rewrites[str(Path(suite_source).resolve(strict=False))])
        suite_data = json.loads(suite_snapshot_path.read_text(encoding="utf-8"))
        changed = False
        if isinstance(suite_data, dict):
            for field in ("tool", "c2pa_tool"):
                tool_value = suite_data.get(field)
                if isinstance(tool_value, str) and tool_value.strip():
                    retained = _retained_tool_path(tool_value)
                    if retained is not None:
                        suite_data[field] = retained
                        changed = True
        if changed:
            suite_snapshot_path.write_text(json.dumps(suite_data, indent=2, sort_keys=True), encoding="utf-8")
    for artifact in artifact_metadata:
        snapshot_path = Path(str(artifact["snapshot_path"]))
        labels = artifact.get("labels", [])
        if not snapshot_path.is_file():
            continue
        if "provider-manifest" not in snapshot_path.name and not (
            isinstance(labels, list)
            and any("--provider-manifest" in str(label) for label in labels)
        ):
            continue
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        _rewrite_provider_manifest_commands(
            payload,
            path="provider-manifest.production.json",
        )
        snapshot_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

_rewrite_operator_tool_value(manifest)
_rewrite_retained_input_tool_paths()
for artifact in artifact_metadata:
    artifact["files"] = _snapshot_file_entries(
        Path(str(artifact["path"])),
        Path(str(artifact["snapshot_path"])),
    )

def _retained_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        return Path(value).resolve(strict=False).relative_to(out_root).as_posix()
    except (OSError, ValueError):
        return Path(value).name

preflight_row_readiness = build_parity_row_readiness(
    [
        {
            "relative_path": _retained_relative_path(artifact.get("snapshot_path")),
            "checks": artifact.get("checks", []),
            "parity_routes": artifact.get("parity_routes", []),
            "exists": True,
        }
        for artifact in artifact_metadata
    ]
)

snapshot_scan = scan_evidence_paths(
    [Path(str(artifact["snapshot_path"])) for artifact in artifact_metadata],
    scope="preflight-input-snapshots",
    forbidden_roots=[repo_dir],
    reject_symlinks=True,
)
snapshot_findings = snapshot_scan.get("findings", [])
snapshot_skipped = snapshot_scan.get("skipped_files", [])
if snapshot_findings:
    print(
        "ERROR: high-confidence secret material found in staged production input artifacts:",
        file=sys.stderr,
    )
    for finding in snapshot_findings:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
    sys.exit(65)
if snapshot_skipped:
    print(
        "ERROR: staged production input artifacts include unscanned files:",
        file=sys.stderr,
    )
    for skipped in snapshot_skipped:
        print(f"  - {skipped['path']}: {skipped['reason']}", file=sys.stderr)
    sys.exit(65)

for occurrence in artifact_occurrences:
    check = checks[int(occurrence["check_index"])]
    values = check[str(occurrence["field"])]
    original_path = str(Path(str(occurrence["path"])).resolve(strict=False))
    replacement_prefix = occurrence.get("replacement_prefix")
    rewritten_path = path_rewrites[original_path]
    if isinstance(replacement_prefix, str) and replacement_prefix:
        values[int(occurrence["value_index"])] = replacement_prefix + rewritten_path
    else:
        values[int(occurrence["value_index"])] = rewritten_path

(out_root / "source-soak-manifest.json").write_text(
    manifest_text,
    encoding="utf-8",
)
(out_root / "operator-soak-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True),
    encoding="utf-8",
)
redaction_scan_path = out_root / "redaction-scan.json"
preflight_path = out_root / "preflight.json"
preflight = {
    "ok": True,
    "preflight_only": os.environ.get("PREFLIGHT_ONLY") == "1",
    "source_manifest": str(manifest_path),
    "source_manifest_copy": str(out_root / "source-soak-manifest.json"),
    "copied_manifest": str(out_root / "operator-soak-manifest.json"),
    "redaction_scan": str(redaction_scan_path),
    "started_at": os.environ["STARTED_AT"],
    "required_commands": list(PRODUCTION_RELEASE_REQUIRED_COMMANDS),
    "provided_commands": sorted(commands),
    "required_input_artifacts": artifact_metadata,
    "parity_row_readiness": preflight_row_readiness,
    "executable_tool_references": tool_references,
    "tool_env_overrides": sorted(tool_env_overrides),
}
preflight_path.write_text(json.dumps(preflight, indent=2), encoding="utf-8")
retained_preflight_paths = [
    out_root / "source-soak-manifest.json",
    out_root / "operator-soak-manifest.json",
    preflight_path,
    *[Path(str(artifact["snapshot_path"])) for artifact in artifact_metadata],
]
if tool_env_overrides:
    retained_preflight_paths.append(tool_env_path)
retained_preflight_scan = scan_evidence_paths(
    retained_preflight_paths,
    scope="preflight",
    forbidden_roots=[repo_dir],
    reject_symlinks=True,
)
retained_preflight_findings = retained_preflight_scan.get("findings", [])
retained_preflight_skipped = retained_preflight_scan.get("skipped_files", [])
if retained_preflight_findings:
    print(
        "ERROR: high-confidence secret material found in retained preflight evidence:",
        file=sys.stderr,
    )
    for finding in retained_preflight_findings:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
    sys.exit(65)
if retained_preflight_skipped:
    print(
        "ERROR: retained preflight evidence includes unscanned files:",
        file=sys.stderr,
    )
    for skipped in retained_preflight_skipped:
        print(f"  - {skipped['path']}: {skipped['reason']}", file=sys.stderr)
    sys.exit(65)
write_redaction_scan(
    redaction_scan_path,
    scope="preflight",
    scanned_files=list(retained_preflight_scan.get("scanned_files", [])),
    findings=[],
    skipped_files=[],
)
PY

if [ "${PREFLIGHT_ONLY}" = "1" ]; then
  cat "${OUT_ROOT}/preflight.json"
  exit 0
fi

cd "${REPO_DIR}"
if [ -f "${OUT_ROOT}/tool-env.sh" ]; then
  # shellcheck disable=SC1091
  . "${OUT_ROOT}/tool-env.sh"
fi
"${PYTHON}" -m mnemosyne.cli \
  --store "${OUT_ROOT}/store.json" \
  deployment-soak \
  --soak-manifest "${OUT_ROOT}/operator-soak-manifest.json" \
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

from mnemosyne.evidence_redaction import scan_evidence_paths, scan_evidence_tree  # noqa: E402


out_root = Path(os.environ["OUT_ROOT"])
soak = json.loads((out_root / "deployment-soak.stdout.json").read_text(encoding="utf-8"))
audit = json.loads((out_root / "release-audit.json").read_text(encoding="utf-8"))
preflight = json.loads((out_root / "preflight.json").read_text(encoding="utf-8"))
redaction_scan = scan_evidence_tree(
    out_root,
    binary_custody_roots=[out_root / "tool-artifacts"],
)
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
if out_root.is_symlink():
    print(
        f"ERROR: production evidence output root cannot be a symlink: {out_root}",
        file=sys.stderr,
    )
    sys.exit(65)
for file_path in sorted(out_root.rglob("*")):
    if file_path.is_symlink():
        print(
            f"ERROR: production evidence bundle contains a symlink: {file_path}",
            file=sys.stderr,
        )
        sys.exit(65)
    if not file_path.is_file():
        continue
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

completed_at = __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat()
summary = {
    "out_root": str(out_root),
    "operator_manifest": str(out_root / "operator-soak-manifest.json"),
    "evidence_manifest": str(out_root / "evidence/manifest.json"),
    "redaction_scan": str(out_root / "redaction-scan.json"),
    "bundle_manifest": str(out_root / "bundle-manifest.json"),
    "bundle_fingerprint": bundle_fingerprint,
    "parity_row_readiness": preflight.get("parity_row_readiness", []),
    "row_review_source": "preflight.json.parity_row_readiness",
    "redaction_scan_ok": redaction_scan["ok"],
    "deployment_soak_ok": soak.get("ok") is True,
    "release_audit_ok": audit.get("ok") is True,
    "release_audit_fingerprint": audit.get("fingerprint"),
    "release_audit_findings": audit.get("findings", []),
    "completed_at": completed_at,
    "offline_verify": {
        "bundle_dir": str(out_root),
        "expected_bundle_fingerprint_source": "out-of-band-capture-record",
        "argv": [
            os.environ["PYTHON"],
            "-m",
            "mnemosyne.cli",
            "production-evidence-verify",
            str(out_root),
            "--expected-bundle-fingerprint",
            "<out-of-band-bundle-fingerprint>",
            "--report-output",
            "<external-review-report-json>",
        ],
        "note": (
            "Custody review only; does not rerun production checks or flip audit rows. "
            "Expected fingerprint must come from an independently retained out-of-band fingerprint record."
        ),
    },
}
(out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
metadata_scan = scan_evidence_paths(
    [out_root / "bundle-manifest.json", out_root / "summary.json"],
    scope="final-metadata",
    reject_symlinks=True,
)
if not metadata_scan["ok"]:
    print(
        "ERROR: high-confidence secret material found in production evidence metadata:",
        file=sys.stderr,
    )
    for finding in metadata_scan["findings"]:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
    for skipped in metadata_scan.get("skipped_files", []):
        print(
            f"  - {skipped['path']}: {skipped['reason']}",
            file=sys.stderr,
        )
    sys.exit(65)
fingerprint_record_output = os.environ.get("FINGERPRINT_RECORD_OUTPUT_RESOLVED", "")
if fingerprint_record_output:
    fingerprint_record_path = Path(fingerprint_record_output)
    fingerprint_record = {
        "schema": "mnemosyne.production-evidence-fingerprint-record.v1",
        "record_kind": "out-of-band-bundle-fingerprint",
        "bundle_dir": str(out_root),
        "bundle_manifest": str(out_root / "bundle-manifest.json"),
        "summary": str(out_root / "summary.json"),
        "bundle_fingerprint": bundle_fingerprint,
        "artifact_count": len(bundle_files),
        "captured_at": completed_at,
        "created_by": "infra/scripts/capture-production-evidence.sh",
        "verification_hint": {
            "command": "python -m mnemosyne.cli production-evidence-verify",
            "expected_bundle_fingerprint_argument": bundle_fingerprint,
            "report_output_required": True,
        },
        "note": (
            "Retain this file outside the evidence bundle and use bundle_fingerprint "
            "as --expected-bundle-fingerprint during offline custody review."
        ),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(fingerprint_record_path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(fingerprint_record, handle, indent=2)
            handle.write("\n")
    except FileExistsError:
        print(
            f"ERROR: production fingerprint record output already exists: {fingerprint_record_path}",
            file=sys.stderr,
        )
        sys.exit(65)
    except OSError as exc:
        print(
            f"ERROR: production fingerprint record output could not be written: {exc}",
            file=sys.stderr,
        )
        sys.exit(65)
print(json.dumps(summary, indent=2))
PY
