#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'USAGE'
Usage:
  infra/scripts/capture-production-evidence.sh [--preflight-only] SOAK_MANIFEST [OUT_ROOT]

Runs the existing production evidence path:
  1. Validate that SOAK_MANIFEST is explicitly production-scoped.
  2. Run deployment-soak with --evidence-dir.
  3. Run release-audit with --require-production-validated and
     --require-provider-forbid-local.
  4. Redaction-scan generated evidence and fail on findings or skipped files.
  5. Write bundle-manifest.json and summary.json with bundle_fingerprint.

Reviewers can recheck a completed bundle offline with:
  PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; else command -v python3; fi)}"
  BUNDLE_DIR=OUT_ROOT
  EXPECTED_BUNDLE_FINGERPRINT="$("$PYTHON" -c 'import json, pathlib, sys; print(json.loads((pathlib.Path(sys.argv[1]) / "summary.json").read_text())["bundle_fingerprint"])' "$BUNDLE_DIR")"
  "$PYTHON" -m mnemosyne.cli production-evidence-verify "$BUNDLE_DIR" \
    --expected-bundle-fingerprint "$EXPECTED_BUNDLE_FINGERPRINT"
This is custody review only; it does not rerun production checks or flip rows.

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
OUT_ROOT_RAW="${2:-/tmp/mnemosyne-tierb-production-evidence-${STAMP}}"

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

out_root = Path(sys.argv[1]).expanduser().resolve(strict=False)
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
STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export MANIFEST_PATH OUT_ROOT REPO_DIR STARTED_AT PREFLIGHT_ONLY

"${PYTHON}" - <<'PY'
import json
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

repo_dir = Path(os.environ["REPO_DIR"])
sys.path.insert(0, str(repo_dir / "src"))

from mnemosyne.cli import (  # noqa: E402
    PRODUCTION_RELEASE_REQUIRED_COMMANDS,
)
from mnemosyne.evidence_redaction import (  # noqa: E402
    redaction_findings,
    scan_evidence_paths,
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
required_artifacts: dict[str, dict[str, object]] = {}
artifact_occurrences: list[dict[str, object]] = []
executable_tool_references: dict[str, dict[str, object]] = {}
suite_case_artifact_rewrites: dict[str, list[dict[str, object]]] = {}
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

def _record_required_artifact(
    resolved: Path,
    *,
    label: str,
    occurrence: dict[str, object] | None = None,
) -> None:
    artifact = required_artifacts.setdefault(
        str(resolved),
        {
            "path": str(resolved),
            "labels": [],
        },
    )
    artifact["labels"].append(label)
    if occurrence is not None:
        artifact_occurrences.append(occurrence)

def _validate_external_file_path(
    value: str,
    *,
    check_index: int,
    field: str,
    value_index: int,
    label: str,
    replacement_prefix: str | None = None,
) -> None:
    if not _looks_like_file_path(value):
        return
    path = Path(value).expanduser()
    if not path.is_absolute():
        errors.append(f"{label} contains relative production artifact path {value}; use an absolute external path")
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
    resolved = _resolve_checked(path, label=label)
    if resolved is None:
        return None
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        _record_required_artifact(resolved, label=label)
        return resolved
    errors.append(f"{label} points inside the repository: {resolved}; use an external custody path")
    return None

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
            "labels": [],
        },
    )
    reference["labels"].append(label)

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
    check_args = check.get("args", [])
    check_global_args = check.get("global_args", [])
    for field in ("args", "global_args"):
        values = check.get(field, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            errors.append(f"checks[{index}].{field} must be an array of strings")
            continue
        for value_index, value in enumerate(values):
            option_name, separator, option_value = value.partition("=")
            if option_name in sensitive_options:
                errors.append(
                    f"checks[{index}].{field} contains secret-bearing option {option_name}; "
                    "use environment, files, or command providers instead"
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
                    field=field,
                    value_index=value_index,
                    label=f"checks[{index}].{field}",
                    replacement_prefix=f"{option_name}=",
                )
                continue
            previous_option = None
            if value_index > 0:
                previous_value = values[value_index - 1]
                if previous_value.startswith("--") and "=" not in previous_value:
                    previous_option = previous_value
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
                field=field,
                value_index=value_index,
                label=f"checks[{index}].{field}",
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
            for case_index, case in enumerate(cases, start=1):
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
                        suite_rewrites.append(
                            {
                                "case_index": case_index - 1,
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

out_root.mkdir(parents=True, exist_ok=True)
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
    artifact_metadata.append(
        {
            "path": str(source_path.resolve(strict=True)),
            "snapshot_path": str(snapshot_path.resolve(strict=True)),
            "kind": kind,
            "labels": sorted(set(str(label) for label in artifact["labels"])),
            "files": _snapshot_file_entries(source_path, snapshot_path),
        }
    )

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
preflight_scanned_files = [str(manifest_path)] + list(snapshot_scan.get("scanned_files", []))
write_redaction_scan(
    redaction_scan_path,
    scope="preflight",
    scanned_files=preflight_scanned_files,
    findings=[],
    skipped_files=[],
)
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
    "executable_tool_references": sorted(
        executable_tool_references.values(),
        key=lambda item: (str(item["option"]), str(item["path"])),
    ),
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
