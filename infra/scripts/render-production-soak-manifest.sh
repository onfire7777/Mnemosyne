#!/usr/bin/env bash
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'USAGE'
Usage:
  infra/scripts/render-production-soak-manifest.sh --output OUT [--template TEMPLATE] [--env-file ENV] [--force]
  infra/scripts/render-production-soak-manifest.sh --list-placeholders [--template TEMPLATE]
  infra/scripts/render-production-soak-manifest.sh --check-environment [--template TEMPLATE] [--env-file ENV]

Renders infra/templates/production-soak-manifest.template.json by replacing every
MNEMOSYNE_PROD_* placeholder from a strict external env file or the current
environment. The rendered manifest is validated for production scope and full
release-command coverage. Secret values still belong in environment variables,
mounted files, Vault/KMS, or command providers; do not put raw secrets in
MNEMOSYNE_PROD_* placeholders.

Options:
  --template PATH       Template path. Defaults to infra/templates/production-soak-manifest.template.json.
  --env-file PATH       Strict dotenv file containing every MNEMOSYNE_PROD_* placeholder.
                        Must be absolute, external, non-symlinked, mode 0600,
                        and parsed by infra/scripts/load-env.py.
  --output PATH         Destination manifest path. Required unless --list-placeholders or --check-environment is used.
  --force              Overwrite OUT if it already exists.
  --list-placeholders  Print required MNEMOSYNE_PROD_* placeholder names as JSON.
  --check-environment  Validate required MNEMOSYNE_PROD_* keys without writing a manifest.
                       Reports readiness docs, provider env refs, and input artifacts.
  -h, --help           Show this help text.
USAGE
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${HERE}/.." && pwd)"
REPO_DIR="$(cd "${INFRA_DIR}/.." && pwd)"

TEMPLATE="${REPO_DIR}/infra/templates/production-soak-manifest.template.json"
ENV_FILE=""
OUTPUT=""
FORCE=0
LIST_PLACEHOLDERS=0
CHECK_ENVIRONMENT=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --template)
      TEMPLATE="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
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
    --list-placeholders)
      LIST_PLACEHOLDERS=1
      shift
      ;;
    --check-environment)
      CHECK_ENVIRONMENT=1
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

export TEMPLATE ENV_FILE OUTPUT FORCE LIST_PLACEHOLDERS CHECK_ENVIRONMENT REPO_DIR

"${PYTHON}" - <<'PY'
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

repo_dir = Path(os.environ["REPO_DIR"]).resolve()
sys.path.insert(0, str(repo_dir / "src"))

from mnemosyne.cli import (  # noqa: E402
    PRODUCTION_RELEASE_REQUIRED_COMMANDS,
    PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS,
)
from mnemosyne.evidence_redaction import (  # noqa: E402
    manifest_argument_secret_errors,
    redaction_findings,
)
from mnemosyne.production_parity import (  # noqa: E402
    annotate_artifact_routes,
    build_parity_row_readiness,
    parity_lanes_for_command,
)

template_path = Path(os.environ["TEMPLATE"]).expanduser().resolve()
output_raw = os.environ.get("OUTPUT", "")
force = os.environ.get("FORCE") == "1"
list_placeholders = os.environ.get("LIST_PLACEHOLDERS") == "1"
check_environment = os.environ.get("CHECK_ENVIRONMENT") == "1"
placeholder_re = re.compile(r"MNEMOSYNE_PROD_[A-Z0-9_]+")

if not template_path.is_file():
    print(f"ERROR: template not found: {template_path}", file=sys.stderr)
    raise SystemExit(66)

template_text = template_path.read_text(encoding="utf-8")
required = sorted(set(placeholder_re.findall(template_text)))
validation_categories = [
    "required_placeholders_present",
    "rendered_manifest_has_no_unresolved_placeholders",
    "production_validation_scope",
    "frozen_command_profile",
    "external_input_artifact_custody",
    "provider_manifest_env_refs",
    "external_c2pa_tool",
    "operator_capture_and_offline_verify",
]
operator_readiness_files = {
    "env_template": "infra/templates/production-render.env.example",
    "input_artifacts_checklist": "infra/templates/production-input-artifacts.checklist.md",
    "operator_env_inventory": "infra/templates/production-operator-env.inventory.md",
    "provider_manifest_template": "infra/templates/provider-manifest.production.template.json",
    "production_evidence_runbook": "infra/PRODUCTION-EVIDENCE.md",
}
next_steps = [
    "Review infra/templates/production-operator-env.inventory.md for the full no-secret operator env name inventory.",
    "Create a Tier-B custody packet and fill its production-render.env with every MNEMOSYNE_PROD_* value.",
    "Set MNEMOSYNE_PROD_EVIDENCE_DIR to an absolute external directory containing the listed production input artifacts.",
    "Re-run infra/scripts/render-production-soak-manifest.sh --env-file <packet>/production-render.env --check-environment until ok=true.",
    "Render with --output to an external path, run infra/scripts/capture-production-evidence.sh, then verify the bundle with production-evidence-verify.",
]


template_manifest = json.loads(template_text)
env_file_raw = os.environ.get("ENV_FILE", "")


def fail_env_file(message: str, *, code: int = 65) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def load_env_file(path_raw: str, required_keys: list[str]) -> None:
    if not path_raw:
        return
    env_path = Path(path_raw).expanduser()
    if not env_path.is_absolute():
        fail_env_file("--env-file must be an absolute external path")
    if env_path.is_symlink():
        fail_env_file("--env-file must not be a symlink")
    repo_resolved = repo_dir.resolve()
    try:
        env_path.relative_to(repo_resolved)
    except ValueError:
        pass
    else:
        fail_env_file("--env-file must not point inside the repository")
    resolved = env_path.resolve(strict=False)
    try:
        resolved.relative_to(repo_resolved)
    except ValueError:
        pass
    else:
        fail_env_file("--env-file must not resolve inside the repository")
    loader = repo_dir / "infra" / "scripts" / "load-env.py"
    proc = subprocess.run(
        [str(loader), str(env_path), *required_keys],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        fail_env_file(f"--env-file failed strict loading: {stderr}", code=proc.returncode)
    for line in proc.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            os.environ[key] = value


def collect_template_input_artifact_plan(manifest_payload: dict[str, Any]) -> list[dict[str, object]]:
    artifacts: dict[str, dict[str, object]] = {}
    marker = "MNEMOSYNE_PROD_EVIDENCE_DIR/"

    def record(value: str, *, check_name: str, command: str, option: str) -> None:
        if marker not in value:
            return
        relative_path = value.split(marker, 1)[1]
        if not relative_path or relative_path.startswith("/") or ".." in Path(relative_path).parts:
            return
        artifact = artifacts.setdefault(
            relative_path,
            {
                "relative_path": relative_path,
                "checks": [],
            },
        )
        artifact["checks"].append(
            {
                "name": check_name,
                "command": command,
                "option": option,
                "parity_lanes": parity_lanes_for_command(command),
            }
        )

    checks_payload = manifest_payload.get("checks", [])
    if not isinstance(checks_payload, list):
        return []
    for check in checks_payload:
        if not isinstance(check, dict):
            continue
        command = check.get("command")
        check_name = check.get("name")
        if not isinstance(command, str):
            command = ""
        if not isinstance(check_name, str):
            check_name = command
        for field in ("args", "global_args"):
            values = check.get(field, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                continue
            for index, value in enumerate(values):
                previous = values[index - 1] if index > 0 else ""
                if previous == "--c2pa-tool":
                    continue
                option = previous if previous.startswith("--") and "=" not in previous else field
                if value.startswith("--"):
                    option_name, separator, option_value = value.partition("=")
                    if separator and option_name != "--c2pa-tool":
                        record(
                            option_value,
                            check_name=check_name,
                            command=command,
                            option=option_name,
                        )
                    continue
                record(value, check_name=check_name, command=command, option=option)
        input_artifacts = check.get("input_artifacts", [])
        if isinstance(input_artifacts, list) and all(isinstance(v, str) for v in input_artifacts):
            for index, value in enumerate(input_artifacts):
                record(
                    value,
                    check_name=check_name,
                    command=command,
                    option=f"input_artifacts[{index}]",
                )
    for artifact in artifacts.values():
        annotate_artifact_routes(artifact)
    return sorted(artifacts.values(), key=lambda item: str(item["relative_path"]))


template_input_artifact_plan = collect_template_input_artifact_plan(template_manifest)
template_input_artifact_names = [
    str(artifact["relative_path"]) for artifact in template_input_artifact_plan
]
template_parity_row_readiness = build_parity_row_readiness(template_input_artifact_plan)
shared_provider_lanes = {"B1", "B2", "B4", "B6", "B7", "B9", "B10"}


def collect_template_render_placeholders_by_lane(
    manifest_payload: dict[str, Any],
) -> dict[str, set[str]]:
    by_lane: dict[str, set[str]] = {}
    checks_payload = manifest_payload.get("checks", [])
    if not isinstance(checks_payload, list):
        return by_lane
    for check in checks_payload:
        if not isinstance(check, dict):
            continue
        command = check.get("command")
        if not isinstance(command, str):
            continue
        lanes = parity_lanes_for_command(command)
        if not lanes:
            continue
        placeholders = set(placeholder_re.findall(json.dumps(check, sort_keys=True)))
        for lane in lanes:
            by_lane.setdefault(lane, set()).update(placeholders)
    return by_lane


template_render_placeholders_by_lane = collect_template_render_placeholders_by_lane(
    template_manifest
)


def enrich_renderer_row_readiness(
    rows: list[dict[str, object]],
    *,
    missing_render_environment: list[str],
    missing_provider_environment: list[str] | None = None,
) -> list[dict[str, object]]:
    missing_render_set = set(missing_render_environment)
    missing_provider = sorted(missing_provider_environment or [])
    enriched: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        lane = str(item.get("lane", ""))
        row_missing_render = sorted(
            template_render_placeholders_by_lane.get(lane, set()) & missing_render_set
        )
        item["missing_render_environment"] = row_missing_render
        item["render_environment_complete"] = not row_missing_render
        if missing_provider_environment is not None:
            row_missing_provider = missing_provider if lane in shared_provider_lanes else []
            item["missing_provider_manifest_env_refs"] = row_missing_provider
            item["provider_manifest_environment_complete"] = not row_missing_provider
        if "input_artifacts_complete" in item:
            item["ready_for_capture"] = (
                bool(item.get("input_artifacts_complete"))
                and bool(item["render_environment_complete"])
                and bool(item.get("provider_manifest_environment_complete", True))
            )
        enriched.append(item)
    return enriched

if list_placeholders:
    print(
        json.dumps(
            {
                "template": str(template_path),
                "placeholders": required,
                "required_input_artifact_count": len(template_input_artifact_names),
                "required_input_artifacts": template_input_artifact_names,
                "required_input_artifacts_plan": template_input_artifact_plan,
                "parity_row_readiness": enrich_renderer_row_readiness(
                    template_parity_row_readiness,
                    missing_render_environment=[],
                ),
            },
            indent=2,
        )
    )
    raise SystemExit(0)

load_env_file(env_file_raw, required)

missing = [name for name in required if not os.environ.get(name)]
present = [name for name in required if os.environ.get(name)]
readiness_payload: dict[str, object] | None = None
if check_environment:
    readiness_payload = {
        "ok": not missing,
        "template": str(template_path),
        "placeholder_count": len(required),
        "present": present,
        "missing": missing,
        "present_environment": present,
        "present_environment_count": len(present),
        "missing_environment": missing,
        "missing_environment_count": len(missing),
        "values_redacted": True,
        "validation_categories": validation_categories,
        "operator_readiness_files": operator_readiness_files,
        "required_input_artifact_count": len(template_input_artifact_names),
        "required_input_artifacts": template_input_artifact_names,
        "required_input_artifacts_plan": template_input_artifact_plan,
        "parity_row_readiness": enrich_renderer_row_readiness(
            template_parity_row_readiness,
            missing_render_environment=missing,
        ),
        "render_environment_complete": not missing,
        "next_steps": next_steps,
    }
    if missing:
        readiness_payload["blocked_reason"] = "missing_required_environment"
        print(json.dumps(readiness_payload, indent=2))
        raise SystemExit(78)


def fail_environment_value(name: str, code: str, message: str) -> None:
    if check_environment:
        assert readiness_payload is not None
        payload = dict(readiness_payload)
        payload["ok"] = False
        payload["blocked_reason"] = "invalid_required_environment"
        payload["environment_errors"] = [
            {
                "name": name,
                "code": code,
                "message": message,
            }
        ]
        print(json.dumps(payload, indent=2))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(78)

if not check_environment:
    if not output_raw:
        print("ERROR: --output is required unless --list-placeholders or --check-environment is used", file=sys.stderr)
        raise SystemExit(64)

    output_candidate = Path(output_raw).expanduser()
    if not output_candidate.is_absolute():
        print(
            "ERROR: --output must be an absolute external custody path",
            file=sys.stderr,
        )
        raise SystemExit(73)
    output_path = output_candidate.resolve()
    try:
        output_path.relative_to(repo_dir)
        inside_repo = True
    except ValueError:
        inside_repo = False

    if inside_repo:
        print(
            "ERROR: refusing to write production manifest inside the repository; "
            "choose an external custody path",
            file=sys.stderr,
        )
        raise SystemExit(73)

    if output_path.exists() and not force:
        print(f"ERROR: output already exists: {output_path} (pass --force to overwrite)", file=sys.stderr)
        raise SystemExit(73)

if missing:
    print("ERROR: missing required production placeholder environment variables:", file=sys.stderr)
    for name in missing:
        print(f"  - {name}", file=sys.stderr)
    raise SystemExit(78)

evidence_dir_raw = os.environ.get("MNEMOSYNE_PROD_EVIDENCE_DIR", "")
evidence_dir = Path(evidence_dir_raw).expanduser()
if not evidence_dir.is_absolute():
    fail_environment_value(
        "MNEMOSYNE_PROD_EVIDENCE_DIR",
        "evidence_dir_not_absolute",
        "MNEMOSYNE_PROD_EVIDENCE_DIR must be an absolute external production input-artifact path",
    )
try:
    evidence_dir.relative_to(repo_dir)
except ValueError:
    pass
else:
    fail_environment_value(
        "MNEMOSYNE_PROD_EVIDENCE_DIR",
        "evidence_dir_repo_local",
        "MNEMOSYNE_PROD_EVIDENCE_DIR must not point inside the repository",
    )
evidence_dir_resolved = evidence_dir.resolve(strict=False)
try:
    evidence_dir_resolved.relative_to(repo_dir)
except ValueError:
    pass
else:
    fail_environment_value(
        "MNEMOSYNE_PROD_EVIDENCE_DIR",
        "evidence_dir_resolves_repo_local",
        "MNEMOSYNE_PROD_EVIDENCE_DIR must not resolve inside the repository",
    )

c2pa_tool_raw = os.environ.get("MNEMOSYNE_PROD_C2PA_TOOL", "")
c2pa_tool = Path(c2pa_tool_raw).expanduser()
if not c2pa_tool.is_absolute():
    fail_environment_value(
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "c2pa_tool_not_absolute",
        "MNEMOSYNE_PROD_C2PA_TOOL must be an absolute external executable path",
    )
try:
    c2pa_tool.relative_to(repo_dir)
except ValueError:
    pass
else:
    fail_environment_value(
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "c2pa_tool_repo_local",
        "MNEMOSYNE_PROD_C2PA_TOOL must not point inside the repository",
    )
if c2pa_tool.is_symlink():
    fail_environment_value(
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "c2pa_tool_symlink",
        "MNEMOSYNE_PROD_C2PA_TOOL must not be a symlink",
    )
c2pa_tool_resolved = c2pa_tool.resolve(strict=False)
try:
    c2pa_tool_resolved.relative_to(repo_dir)
except ValueError:
    pass
else:
    fail_environment_value(
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "c2pa_tool_resolves_repo_local",
        "MNEMOSYNE_PROD_C2PA_TOOL must not point inside the repository",
    )
if not c2pa_tool_resolved.exists() or not c2pa_tool_resolved.is_file():
    fail_environment_value(
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "c2pa_tool_missing",
        "MNEMOSYNE_PROD_C2PA_TOOL must exist as an external executable file",
    )
if not os.access(c2pa_tool_resolved, os.X_OK):
    fail_environment_value(
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "c2pa_tool_not_executable",
        "MNEMOSYNE_PROD_C2PA_TOOL must be executable",
    )

if check_environment:
    if not evidence_dir_resolved.exists() or not evidence_dir_resolved.is_dir():
        fail_environment_value(
            "MNEMOSYNE_PROD_EVIDENCE_DIR",
            "evidence_dir_missing",
            "MNEMOSYNE_PROD_EVIDENCE_DIR must exist as an external directory "
            "before --check-environment can pass",
        )

manifest = template_manifest

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

manifest_findings = redaction_findings(str(template_path), rendered_text)
manifest_secret_errors = manifest_argument_secret_errors(rendered_manifest)
if manifest_findings or manifest_secret_errors:
    print("ERROR: rendered production manifest contains secret-bearing material:", file=sys.stderr)
    for finding in manifest_findings:
        print(
            f"  - {finding['source']}:{finding['line']} {finding['kind']}",
            file=sys.stderr,
        )
    for error in manifest_secret_errors:
        print(f"  - {error}", file=sys.stderr)
    print(
        "Move credentials to environment variables, mounted files, Vault/KMS, or "
        "command providers before rendering.",
        file=sys.stderr,
    )
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

def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)

input_artifact_errors: list[str] = []
input_artifact_row_errors: dict[str, list[str]] = {}


def add_input_artifact_error(message: str, *, lane: str | None = None) -> None:
    input_artifact_errors.append(message)
    if lane:
        input_artifact_row_errors.setdefault(lane, []).append(message)


def evidence_relative_path(value: str, *, label: str) -> tuple[Path, str] | None:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None
    if candidate.is_symlink():
        add_input_artifact_error(f"{label} must not be a symlinked input artifact")
        return None
    resolved = candidate.resolve(strict=False)
    try:
        lexical_relative = candidate.relative_to(evidence_dir)
    except ValueError:
        lexical_relative = None
    if lexical_relative is not None and ".." in lexical_relative.parts:
        add_input_artifact_error(f"{label} must not contain '..' path segments")
        return None
    try:
        relative = resolved.relative_to(evidence_dir_resolved)
    except ValueError:
        if lexical_relative is not None:
            add_input_artifact_error(f"{label} must resolve under MNEMOSYNE_PROD_EVIDENCE_DIR")
        else:
            add_input_artifact_error(f"{label} must live under MNEMOSYNE_PROD_EVIDENCE_DIR")
        return None
    return resolved, relative.as_posix()

def collect_manifest_input_artifacts(manifest_payload: dict[str, Any]) -> list[dict[str, object]]:
    artifacts: dict[str, dict[str, object]] = {}
    if not isinstance(evidence_dir_resolved, Path):
        return []

    def record(value: str, *, check_name: str, command: str, option: str) -> None:
        if not value or is_url(value):
            return
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            return
        error_count = len(input_artifact_errors)
        relative_result = evidence_relative_path(value, label=f"{check_name} {option}")
        if relative_result is None:
            if len(input_artifact_errors) > error_count:
                for lane in parity_lanes_for_command(command):
                    input_artifact_row_errors.setdefault(lane, []).extend(
                        input_artifact_errors[error_count:]
                    )
            return
        resolved, relative_name = relative_result
        artifact = artifacts.setdefault(
            str(resolved),
            {
                "relative_path": relative_name,
                "checks": [],
                "exists": resolved.exists(),
            },
        )
        artifact["checks"].append(
            {
                "name": check_name,
                "command": command,
                "option": option,
                "parity_lanes": parity_lanes_for_command(command),
            }
        )

    checks_payload = manifest_payload.get("checks", [])
    if not isinstance(checks_payload, list):
        return []
    for check in checks_payload:
        if not isinstance(check, dict):
            continue
        command = check.get("command")
        check_name = check.get("name")
        if not isinstance(command, str):
            command = ""
        if not isinstance(check_name, str):
            check_name = command
        for field in ("args", "global_args"):
            values = check.get(field, [])
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                continue
            for index, value in enumerate(values):
                previous = values[index - 1] if index > 0 else ""
                if previous == "--c2pa-tool":
                    continue
                option = previous if previous.startswith("--") and "=" not in previous else field
                if value.startswith("--"):
                    option_name, separator, option_value = value.partition("=")
                    if separator and option_name != "--c2pa-tool":
                        record(
                            option_value,
                            check_name=check_name,
                            command=command,
                            option=option_name,
                        )
                    continue
                record(value, check_name=check_name, command=command, option=option)
        input_artifacts = check.get("input_artifacts", [])
        if isinstance(input_artifacts, list) and all(isinstance(v, str) for v in input_artifacts):
            for index, value in enumerate(input_artifacts):
                record(
                    value,
                    check_name=check_name,
                    command=command,
                    option=f"input_artifacts[{index}]",
                )
    for artifact in artifacts.values():
        annotate_artifact_routes(artifact)
    return sorted(artifacts.values(), key=lambda item: str(item["relative_path"]))

input_artifacts = collect_manifest_input_artifacts(rendered_manifest)

provider_manifest_env_refs: list[str] = []
missing_provider_manifest_env_refs: list[str] = []


def provider_manifest_error(message: str) -> None:
    add_input_artifact_error(message)
    for lane in parity_lanes_for_command("provider-check"):
        input_artifact_row_errors.setdefault(lane, []).append(message)


def collect_env_refs(value: object) -> set[str]:
    if isinstance(value, dict):
        if set(value) == {"env"} and isinstance(value.get("env"), str):
            return {str(value["env"])}
        refs: set[str] = set()
        for item in value.values():
            refs.update(collect_env_refs(item))
        return refs
    if isinstance(value, list):
        refs = set()
        for item in value:
            refs.update(collect_env_refs(item))
        return refs
    return set()


def collect_provider_command_entries(value: object, *, path: str) -> list[tuple[str, object]]:
    entries: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "command":
                entries.append((child_path, item))
            entries.extend(collect_provider_command_entries(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            entries.extend(collect_provider_command_entries(item, path=f"{path}[{index}]"))
    return entries


def provider_command_value(value: object, *, label: str) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"env"} and isinstance(value.get("env"), str):
        env_name = str(value["env"])
        env_value = os.environ.get(env_name)
        if env_value is None or not env_value.strip():
            provider_manifest_error(f"{label} references unset environment variable {env_name}")
            return None
        return env_value
    provider_manifest_error(f"{label} command must be a string or {{\"env\": \"...\"}} reference")
    return None


def validate_provider_command_arguments(parts: list[str], *, label: str) -> None:
    if len(parts) > 1:
        provider_manifest_error(
            f"{label} provider-manifest.command must be a single external executable "
            "with no arguments after argv[0]; put provider implementation/config in "
            "the deployed wrapper or an explicit production input artifact"
        )


def validate_provider_command(value: str, *, label: str) -> None:
    try:
        parts = shlex.split(value)
    except ValueError as exc:
        provider_manifest_error(f"{label} command cannot be parsed: {exc}")
        return
    if not parts:
        provider_manifest_error(f"{label} command must include an executable path")
        return
    executable = Path(parts[0]).expanduser()
    if not executable.is_absolute():
        provider_manifest_error(
            f"{label} contains relative executable path for provider-manifest.command; "
            "use an absolute external executable path"
        )
        return
    try:
        executable.relative_to(repo_dir)
    except ValueError:
        pass
    else:
        provider_manifest_error(
            f"{label} provider-manifest.command must point outside the repository"
        )
        return
    if executable.is_symlink():
        provider_manifest_error(
            f"{label} provider-manifest.command executable must not be a symlink"
        )
        return
    resolved = executable.resolve(strict=False)
    try:
        resolved.relative_to(repo_dir)
    except ValueError:
        pass
    else:
        provider_manifest_error(
            f"{label} provider-manifest.command executable must not resolve inside the repository"
        )
        return
    if not resolved.exists() or not resolved.is_file():
        provider_manifest_error(
            f"{label} provider-manifest.command executable must exist as an external file"
        )
        return
    if not os.access(resolved, os.X_OK):
        provider_manifest_error(
            f"{label} provider-manifest.command executable must be executable"
        )
        return
    validate_provider_command_arguments(parts, label=label)


def inspect_provider_manifest() -> None:
    global provider_manifest_env_refs, missing_provider_manifest_env_refs
    provider_manifest = evidence_dir_resolved / "provider-manifest.production.json"
    if not provider_manifest.exists():
        return
    if not provider_manifest.is_file():
        provider_manifest_error("provider-manifest.production.json must be a file")
        return
    try:
        payload = json.loads(provider_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        provider_manifest_error("provider-manifest.production.json must be readable UTF-8 JSON")
        return
    if not isinstance(payload, dict):
        provider_manifest_error("provider-manifest.production.json must be a JSON object")
        return
    if payload.get("forbid_local") is not True:
        provider_manifest_error("provider-manifest.production.json must set forbid_local=true")
    required_checks = payload.get("required_checks")
    expected_checks = set(PRODUCTION_RELEASE_REQUIRED_PROVIDER_CHECKS)
    if not isinstance(required_checks, list) or not all(isinstance(item, str) for item in required_checks):
        provider_manifest_error(
            "provider-manifest.production.json required_checks must be a string array"
        )
    else:
        actual_checks = set(required_checks)
        missing_checks = sorted(expected_checks - actual_checks)
        extra_checks = sorted(actual_checks - expected_checks)
        if missing_checks:
            provider_manifest_error(
                "provider-manifest.production.json missing production provider checks: "
                + ", ".join(missing_checks)
            )
        if extra_checks:
            provider_manifest_error(
                "provider-manifest.production.json contains unsupported provider checks: "
                + ", ".join(extra_checks)
            )
    if not isinstance(payload.get("providers"), dict):
        provider_manifest_error("provider-manifest.production.json providers must be an object")
    provider_manifest_env_refs = sorted(collect_env_refs(payload))
    missing_provider_manifest_env_refs = [
        name for name in provider_manifest_env_refs if not os.environ.get(name)
    ]
    if missing_provider_manifest_env_refs:
        provider_manifest_error(
            "provider-manifest.production.json references unset environment variables: "
            + ", ".join(missing_provider_manifest_env_refs)
        )
    for label, raw_command in collect_provider_command_entries(
        payload,
        path="provider-manifest.production.json",
    ):
        command_value = provider_command_value(raw_command, label=label)
        if command_value is not None:
            validate_provider_command(command_value, label=label)

def artifact_relative_name(value: str) -> str:
    candidate = Path(value).expanduser()
    resolved = candidate.resolve(strict=False)
    try:
        return candidate.relative_to(evidence_dir).as_posix()
    except ValueError:
        try:
            return resolved.relative_to(evidence_dir_resolved).as_posix()
        except ValueError:
            return candidate.name or "artifact"

def record_suite_nested_artifact(value: object, *, suite_name: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or is_url(value):
        add_input_artifact_error(
            f"{suite_name} {field} must be an absolute external path",
            lane="B5",
        )
        return
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        add_input_artifact_error(
            f"{suite_name} {field} must be an absolute external path",
            lane="B5",
        )
        return
    error_count = len(input_artifact_errors)
    relative_result = evidence_relative_path(
        str(candidate),
        label=f"{suite_name} {field}",
    )
    if relative_result is None:
        if len(input_artifact_errors) == error_count:
            add_input_artifact_error(
                f"{suite_name} {field} must live under MNEMOSYNE_PROD_EVIDENCE_DIR",
                lane="B5",
            )
        else:
            input_artifact_row_errors.setdefault("B5", []).extend(
                input_artifact_errors[error_count:]
            )
        return
    resolved, relative_name = relative_result
    artifact = {
        "relative_path": relative_name,
        "checks": [
            {
                "name": "provenance-trust",
                "command": "provenance-trust-check",
                "option": field,
                "parity_lanes": parity_lanes_for_command("provenance-trust-check"),
            }
        ],
        "exists": resolved.exists(),
    }
    annotate_artifact_routes(artifact)
    existing = next(
        (item for item in input_artifacts if item.get("relative_path") == relative_name),
        None,
    )
    if existing is None:
        input_artifacts.append(artifact)
    else:
        existing.setdefault("checks", []).extend(artifact["checks"])
        annotate_artifact_routes(existing)

def inspect_provenance_suites(manifest_payload: dict[str, Any]) -> None:
    checks_payload = manifest_payload.get("checks", [])
    if not isinstance(checks_payload, list):
        return
    for check in checks_payload:
        if not isinstance(check, dict) or check.get("command") != "provenance-trust-check":
            continue
        values = check.get("args", [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            continue
        suite_values: list[str] = []
        for index, value in enumerate(values):
            if value == "--suite" and index + 1 < len(values):
                suite_values.append(values[index + 1])
            elif value.startswith("--suite="):
                suite_values.append(value.split("=", 1)[1])
        for suite_value in suite_values:
            suite_name = artifact_relative_name(suite_value)
            suite_path = Path(suite_value).expanduser()
            if not suite_path.is_absolute():
                add_input_artifact_error(
                    f"{suite_name} must be an absolute external path",
                    lane="B5",
                )
                continue
            suite_resolved = suite_path.resolve(strict=False)
            if not suite_resolved.exists() or not suite_resolved.is_file():
                continue
            try:
                suite_payload = json.loads(suite_resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                add_input_artifact_error(
                    f"{suite_name} must be readable UTF-8 JSON",
                    lane="B5",
                )
                continue
            if not isinstance(suite_payload, dict):
                add_input_artifact_error(
                    f"{suite_name} must be a JSON object",
                    lane="B5",
                )
                continue
            cases = suite_payload.get("cases")
            if not isinstance(cases, list):
                add_input_artifact_error(
                    f"{suite_name} cases must be an array",
                    lane="B5",
                )
                continue
            for case_index, case in enumerate(cases):
                if not isinstance(case, dict):
                    add_input_artifact_error(
                        f"{suite_name} cases[{case_index}] must be an object",
                        lane="B5",
                    )
                    continue
                for field in ("asset_path", "c2pa_asset_path"):
                    if field in case:
                        record_suite_nested_artifact(
                            case.get(field),
                            suite_name=suite_name,
                            field=f"cases[{case_index}].{field}",
                        )

inspect_provenance_suites(rendered_manifest)
inspect_provider_manifest()
for artifact in input_artifacts:
    annotate_artifact_routes(artifact)
input_artifacts = sorted(input_artifacts, key=lambda item: str(item["relative_path"]))
parity_row_readiness = build_parity_row_readiness(
    input_artifacts,
    row_errors=input_artifact_row_errors,
)
missing_input_artifacts = [
    str(artifact["relative_path"])
    for artifact in input_artifacts
    if not bool(artifact.get("exists"))
]
missing_input_artifact_details = [
    artifact
    for artifact in input_artifacts
    if not bool(artifact.get("exists"))
]

if check_environment:
    enriched_parity_row_readiness = enrich_renderer_row_readiness(
        parity_row_readiness,
        missing_render_environment=[],
        missing_provider_environment=missing_provider_manifest_env_refs,
    )
    payload = {
        "ok": not missing_input_artifacts and not input_artifact_errors,
        "template": str(template_path),
        "placeholder_count": len(required),
        "present": present,
        "missing": [],
        "present_environment": present,
        "present_environment_count": len(present),
        "missing_environment": [],
        "missing_environment_count": 0,
        "values_redacted": True,
        "evidence_dir_external": True,
        "c2pa_tool_external": True,
        "required_input_artifact_count": len(input_artifacts),
        "required_input_artifacts": [
            str(artifact["relative_path"]) for artifact in input_artifacts
        ],
        "required_input_artifacts_detail": input_artifacts,
        "missing_input_artifacts": missing_input_artifacts,
        "missing_input_artifacts_detail": missing_input_artifact_details,
        "provider_manifest_env_refs": provider_manifest_env_refs,
        "missing_provider_manifest_env_refs": missing_provider_manifest_env_refs,
        "parity_row_readiness": enriched_parity_row_readiness,
        "input_artifact_errors": input_artifact_errors,
        "render_environment_complete": True,
        "provider_manifest_environment_complete": not missing_provider_manifest_env_refs,
        "input_artifacts_complete": not missing_input_artifacts and not input_artifact_errors,
        "ready_for_capture": (
            not missing_input_artifacts
            and not input_artifact_errors
            and not missing_provider_manifest_env_refs
        ),
        "validation_categories": validation_categories,
        "next_steps": next_steps,
    }
    if missing_input_artifacts or input_artifact_errors:
        payload["blocked_reason"] = "missing_or_invalid_input_artifacts"
    print(json.dumps(payload, indent=2))
    if missing_input_artifacts or input_artifact_errors:
        raise SystemExit(78)
    raise SystemExit(0)

if missing_input_artifacts or input_artifact_errors:
    print(
        "ERROR: refusing to write production soak manifest with missing or invalid input artifacts",
        file=sys.stderr,
    )
    for relative_path in missing_input_artifacts:
        print(f"  - missing input artifact: {relative_path}", file=sys.stderr)
    for error in input_artifact_errors:
        print(f"  - invalid input artifact: {error}", file=sys.stderr)
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
