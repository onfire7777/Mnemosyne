#!/usr/bin/env python3
"""Prepare a no-secret Tier-B production evidence custody packet."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SHARED_PROVIDER_LANES = {"B1", "B2", "B4", "B6", "B7", "B9", "B10"}
PLACEHOLDER_RE = re.compile(r"MNEMOSYNE_PROD_[A-Z0-9_]+")
BLOCKED_EXIT = 78
VALIDATOR_SECTION_HINTS_BY_COMMAND: dict[str, tuple[str, ...]] = {
    "auth-ops-check": (
        "idp_jwks",
        "authz_rollout",
        "session_secret",
        "tls",
        "tenant_isolation",
        "redaction",
    ),
    "consolidation-ops-check": (
        "validation_scope",
        "worker",
        "provider_check",
        "hosted_providers",
        "projection_recompute",
        "protected_suite",
        "embedding",
        "consolidation_run",
        "calibration",
        "lifecycle",
        "ops_report",
        "deployment",
        "redaction",
    ),
    "mcp-ops-check": (
        "http_json_rpc",
        "streamable_http",
        "tls",
        "redaction",
    ),
    "multimodal-ops-check": (
        "validation_scope",
        "provider_check",
        "object_store",
        "extraction",
        "media_embedding",
        "retrieval",
        "media_jobs",
        "deployment",
        "redaction",
    ),
    "ops-dashboard-check": (
        "hosted_dashboard",
        "dashboard_operations_scope",
        "dashboard_refresh",
        "dashboard_access_control",
        "dashboard_alerts",
        "dashboard_operations_redaction",
    ),
    "parametric-trainer-check": (
        "trainer",
        "protected_suite",
        "gate",
        "rollback",
        "deployment",
        "rail_report",
        "metrics",
        "redaction",
    ),
    "privacy-ops-check": ("kms", "residency", "erasure", "redaction"),
    "provenance-ops-check": (
        "validation_scope",
        "c2pa_verifier",
        "trust_roots",
        "provenance_trust",
        "asset_bound_cases",
        "quarantine",
        "ingestion",
        "deployment",
        "redaction",
    ),
    "retrieval-ops-check": (
        "provider_check",
        "retrieval",
        "adapter_probes",
        "calibration",
        "redaction",
    ),
    "tls-lifecycle-ops-check": (
        "validation_scope",
        "issuance",
        "renewal",
        "deployment",
        "secret_distribution",
        "monitoring",
        "redaction",
    ),
    "worker-ops-check": (
        "deployment_scope",
        "supervisor",
        "heartbeat",
        "queue",
        "jobs",
        "observability",
        "redaction",
    ),
}


def _lane_sort_key(lane: str) -> tuple[int, str]:
    if lane.startswith("B") and lane[1:].isdigit():
        return int(lane[1:]), lane
    return 10_000, lane


def _repo_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _fail(message: str, code: int = 65) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def _shell_quote(value: Path | str) -> str:
    return shlex.quote(str(value))


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_external_root(raw: str, *, repo_dir: Path, must_exist: bool) -> Path:
    root = Path(raw).expanduser()
    if not root.is_absolute():
        _fail("custody root must be an absolute external path")
    if root.is_symlink():
        _fail("custody root must not be a symlink")
    parent = root.parent.resolve()
    repo_resolved = repo_dir.resolve()
    if _is_inside(parent, repo_resolved):
        _fail("refusing to prepare production custody packet inside the repository")
    if must_exist:
        if not root.is_dir():
            _fail("custody root must be an existing external packet directory")
    elif root.exists():
        _fail("custody root must not already exist")
    return root


def _copy_readonly(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(0o600)


def _ensure_packet_dir(path: Path, *, label: str) -> None:
    if path.is_symlink():
        _fail(f"{label} must not be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def _copy_readonly_if_missing(src: Path, dst: Path) -> bool:
    if dst.is_symlink():
        _fail(f"packet doc must not be a symlink: {dst}")
    if dst.exists():
        if not dst.is_file():
            _fail(f"packet doc must be a regular file: {dst}")
        return False
    _copy_readonly(src, dst)
    return True


def _packet_doc_sources(repo_dir: Path) -> list[tuple[Path, Path]]:
    docs = [
        "infra/PRODUCTION-EVIDENCE.md",
        "infra/templates/production-operator-env.inventory.md",
        "infra/templates/production-input-artifacts.checklist.md",
        "infra/templates/production-soak-manifest.template.json",
        ".planning/OPS-HANDOFF-AND-OWNERSHIP.md",
        ".planning/ENV-AND-SECRETS.md",
        ".planning/ROLLBACK.md",
    ]
    sources = [
        (repo_dir / relative, Path("docs") / Path(relative).name)
        for relative in docs
    ]
    sources.extend(
        (runbook, Path("docs") / "runbooks" / runbook.name)
        for runbook in sorted((repo_dir / ".planning" / "runbooks").glob("*.md"))
    )
    return sources


def _sync_packet_docs(root: Path, *, repo_dir: Path) -> dict[str, Any]:
    _ensure_packet_dir(root / "docs", label="packet docs directory")
    _ensure_packet_dir(root / "docs" / "runbooks", label="packet runbooks directory")
    added: list[str] = []
    missing: list[str] = []
    for src, dst_relative in _packet_doc_sources(repo_dir):
        dst = root / dst_relative
        if not src.is_file():
            missing.append(str(dst_relative))
            continue
        if _copy_readonly_if_missing(src, dst):
            added.append(str(dst_relative))
    return {
        "complete": not missing,
        "added": added,
        "missing": missing,
    }


def _packet_runbook_path(runbook: Any) -> str | None:
    if not isinstance(runbook, str) or not runbook:
        return None
    prefix = ".planning/runbooks/"
    if not runbook.startswith(prefix):
        return None
    return f"docs/runbooks/{Path(runbook).name}"


def _seed_packet_render_env(env_file: Path, input_dir: Path) -> None:
    text = env_file.read_text(encoding="utf-8")
    seeded = text.replace(
        'export MNEMOSYNE_PROD_EVIDENCE_DIR=""',
        f'export MNEMOSYNE_PROD_EVIDENCE_DIR="{input_dir}"',
    )
    if seeded == text:
        _fail("production-render.env template is missing MNEMOSYNE_PROD_EVIDENCE_DIR")
    _atomic_write_text(env_file, seeded)
    env_file.chmod(0o600)


def _require_real_directory(path: Path, *, label: str) -> None:
    if path.is_symlink():
        _fail(f"{label} must not be a symlink: {path}")
    if not path.is_dir():
        _fail(f"{label} must be an existing directory: {path}")


def _require_real_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        _fail(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        _fail(f"{label} must be an existing file: {path}")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        _fail(f"{path} must contain a JSON object")
    return payload


def _release_audit_required_output_keys(repo_dir: Path) -> dict[str, list[str]]:
    """Read the release-audit output-shape contract without importing the CLI."""
    cli_path = repo_dir / "src" / "mnemosyne" / "cli.py"
    tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))
    target_node: ast.AST | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS":
                target_node = node.value
                break
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id == "RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS"
                for target in node.targets
            ):
                target_node = node.value
                break
    if target_node is None:
        _fail("cli.py is missing RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS")
    try:
        raw = ast.literal_eval(target_node)
    except (ValueError, SyntaxError) as exc:
        _fail(f"could not parse RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS: {exc}")
    if not isinstance(raw, dict):
        _fail("RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS must be a dict")
    contract: dict[str, list[str]] = {}
    for command, keys in raw.items():
        if not isinstance(command, str) or not isinstance(keys, tuple):
            _fail("RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS must map str to tuple[str, ...]")
        normalized: list[str] = []
        for key in keys:
            if not isinstance(key, str):
                _fail("RELEASE_AUDIT_REQUIRED_OUTPUT_KEYS contains a non-string key")
            normalized.append(key)
        contract[command] = normalized
    return contract


def _collect_env_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        env = value.get("env")
        if isinstance(env, str) and env:
            refs.add(env)
        for nested in value.values():
            refs.update(_collect_env_refs(nested))
    elif isinstance(value, list):
        for item in value:
            refs.update(_collect_env_refs(item))
    return refs


def _json_pointer(path: tuple[str, ...]) -> str:
    if not path:
        return "/"
    escaped = [
        segment.replace("~", "~0").replace("/", "~1")
        for segment in path
    ]
    return "/" + "/".join(escaped)


def _collect_provider_env_ref_details(
    value: Any,
    path: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    if isinstance(value, dict):
        env = value.get("env")
        if isinstance(env, str) and env:
            setting_name = path[-1] if path else "env"
            provider_segments = path[1:-1] if path[:1] == ("providers",) else path[:-1]
            provider_path = ".".join(provider_segments) or ".".join(path) or "manifest"
            details.append(
                {
                    "env": env,
                    "manifest_path": _json_pointer((*path, "env")),
                    "setting_path": _json_pointer(path),
                    "provider_path": provider_path,
                    "setting_name": setting_name,
                    "provider_check": _provider_check_name_for_manifest_path(path),
                }
            )
        for key, nested in value.items():
            details.extend(
                _collect_provider_env_ref_details(nested, (*path, str(key)))
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            details.extend(
                _collect_provider_env_ref_details(item, (*path, str(index)))
            )
    return details


def _provider_check_name_for_manifest_path(path: tuple[str, ...]) -> str | None:
    if path[:1] != ("providers",) or len(path) < 2:
        return None
    provider_segments = path[1:]
    provider = provider_segments[0]
    if provider == "retrieval" and len(provider_segments) >= 2:
        retrieval_provider = provider_segments[1]
        if retrieval_provider in {"embedding", "reranker"}:
            return retrieval_provider
        if retrieval_provider in {"lexical", "graph"}:
            return "retrieval_backends"
    if provider == "media" and len(provider_segments) >= 2:
        media_provider = provider_segments[1]
        if media_provider == "extractor":
            return "media_extractor"
        if media_provider == "embedding":
            return "media_embedding"
    if provider == "object_key":
        return "object_key_manager"
    return provider


def _provider_check_requirement_routes(
    template_manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    repo_dir = _repo_dir()
    parity_path = repo_dir / "src" / "mnemosyne" / "production_parity.py"
    spec = importlib.util.spec_from_file_location(
        "_mnemosyne_production_parity_for_provider_plan",
        parity_path,
    )
    if spec is None or spec.loader is None:
        _fail(f"cannot load production parity metadata: {parity_path}")
    parity_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity_module)
    parity_lanes_for_command = getattr(parity_module, "parity_lanes_for_command", None)
    if not callable(parity_lanes_for_command):
        _fail("production parity metadata is missing parity_lanes_for_command")

    routes: dict[str, dict[str, Any]] = {}
    checks = template_manifest.get("checks", [])
    if not isinstance(checks, list):
        return routes
    for check in checks:
        if not isinstance(check, dict):
            continue
        command = check.get("command")
        if not isinstance(command, str):
            continue
        lanes = parity_lanes_for_command(command)
        global_args = check.get("global_args", [])
        if not isinstance(global_args, list):
            global_args = []
        check_args = check.get("args", [])
        if not isinstance(check_args, list):
            check_args = []
        args = [
            str(arg)
            for arg in [
                *global_args,
                *check_args,
            ]
            if isinstance(arg, str)
        ]
        for index, arg in enumerate(args[:-1]):
            if arg != "--require-provider-check":
                continue
            provider_check = args[index + 1]
            route = routes.setdefault(
                provider_check,
                {
                    "provider_check": provider_check,
                    "lanes": set(),
                    "commands": set(),
                },
            )
            route["lanes"].update(lanes)
            route["commands"].add(command)
    return {
        name: {
            "provider_check": name,
            "lanes": sorted(route["lanes"], key=_lane_sort_key),
            "commands": sorted(route["commands"]),
        }
        for name, route in routes.items()
    }


def _provider_env_action_plan(
    *,
    provider_manifest: dict[str, Any],
    template_manifest: dict[str, Any],
    missing_provider_env_refs: list[str],
) -> list[dict[str, Any]]:
    details_by_env: dict[str, list[dict[str, Any]]] = {}
    for detail in _collect_provider_env_ref_details(provider_manifest):
        env = detail.get("env")
        if isinstance(env, str) and env:
            details_by_env.setdefault(env, []).append(detail)

    requirement_routes = _provider_check_requirement_routes(template_manifest)
    missing = set(missing_provider_env_refs)
    shared_lanes = sorted(SHARED_PROVIDER_LANES, key=_lane_sort_key)
    plan: list[dict[str, Any]] = []
    for env in sorted(details_by_env):
        env_details = sorted(
            details_by_env[env],
            key=lambda detail: str(detail.get("manifest_path", "")),
        )
        provider_checks = sorted(
            {
                str(detail["provider_check"])
                for detail in env_details
                if isinstance(detail.get("provider_check"), str)
            }
        )
        primary_rows = sorted(
            {
                lane
                for provider_check in provider_checks
                for lane in requirement_routes.get(provider_check, {}).get("lanes", [])
                if isinstance(lane, str)
            },
            key=_lane_sort_key,
        )
        affected_rows = list(shared_lanes)
        plan.append(
            {
                "env": env,
                "status": "missing" if env in missing else "present_for_readiness",
                "missing": env in missing,
                "values_redacted": True,
                "value_source_recorded": False,
                "affected_rows": affected_rows,
                "primary_rows": primary_rows,
                "provider_checks": provider_checks,
                "provider_check_routes": [
                    requirement_routes[provider_check]
                    for provider_check in provider_checks
                    if provider_check in requirement_routes
                ],
                "provider_manifest_paths": [
                    str(detail["manifest_path"]) for detail in env_details
                ],
                "provider_settings": [
                    {
                        "provider_path": detail.get("provider_path"),
                        "setting_name": detail.get("setting_name"),
                        "setting_path": detail.get("setting_path"),
                    }
                    for detail in env_details
                ],
                "next_action": (
                    "Set this name in the external runtime env file and refresh."
                    if env in missing
                    else "No action for this name on the current readiness refresh."
                ),
                "report_is_evidence": False,
            }
        )
    return plan


def _collect_render_placeholders_by_lane(
    template_manifest: dict[str, Any],
) -> tuple[dict[str, set[str]], set[str]]:
    repo_dir = _repo_dir()
    parity_path = repo_dir / "src" / "mnemosyne" / "production_parity.py"
    spec = importlib.util.spec_from_file_location(
        "_mnemosyne_production_parity_for_custody",
        parity_path,
    )
    if spec is None or spec.loader is None:
        _fail(f"cannot load production parity metadata: {parity_path}")
    parity_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity_module)
    parity_lanes_for_command = getattr(parity_module, "parity_lanes_for_command", None)
    if not callable(parity_lanes_for_command):
        _fail("production parity metadata is missing parity_lanes_for_command")

    by_lane: dict[str, set[str]] = {}
    routed: set[str] = set()
    checks = template_manifest.get("checks", [])
    if not isinstance(checks, list):
        return by_lane, routed
    for check in checks:
        if not isinstance(check, dict):
            continue
        command = check.get("command")
        if not isinstance(command, str):
            continue
        lanes = parity_lanes_for_command(command)
        if not lanes:
            continue
        text = json.dumps(check, sort_keys=True)
        placeholders = set(PLACEHOLDER_RE.findall(text))
        routed.update(placeholders)
        for lane in lanes:
            by_lane.setdefault(lane, set()).update(placeholders)
    return by_lane, routed


def _load_packet_render_env(
    root: Path,
    *,
    repo_dir: Path,
    template_manifest: dict[str, Any],
) -> dict[str, str]:
    env_file = root / "production-render.env"
    _require_real_file(env_file, label="production-render.env")
    placeholders = sorted(set(PLACEHOLDER_RE.findall(json.dumps(template_manifest))))
    loader = repo_dir / "infra" / "scripts" / "load-env.py"
    proc = subprocess.run(
        [str(loader), str(env_file), *placeholders],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        _fail(f"production-render.env failed strict loading: {stderr}")
    values: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def _run_renderer(
    repo_dir: Path,
    input_dir: Path,
    *,
    env_overrides: dict[str, str],
    runtime_env_file: Path | None,
) -> tuple[int, dict[str, Any], str]:
    renderer = repo_dir / "infra" / "scripts" / "render-production-soak-manifest.sh"
    env = os.environ.copy()
    env.update(env_overrides)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(input_dir)
    command = ["/bin/bash", str(renderer), "--check-environment"]
    if runtime_env_file is not None:
        command.extend(["--runtime-env-file", str(runtime_env_file)])
    proc = subprocess.run(
        command,
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        _fail(f"renderer did not emit JSON: {exc}; stderr={proc.stderr.strip()!r}")
    if not isinstance(payload, dict):
        _fail("renderer readiness payload must be a JSON object")
    return proc.returncode, payload, proc.stderr


def _row_report(
    renderer_payload: dict[str, Any],
    *,
    input_dir: Path,
    missing_render_env: set[str],
    missing_provider_env_refs: set[str],
    placeholders_by_lane: dict[str, set[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_rows = renderer_payload.get("parity_row_readiness", [])
    if not isinstance(raw_rows, list):
        return rows
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        lane = str(raw.get("lane", ""))
        required = [
            str(item)
            for item in raw.get("required_input_artifacts", [])
            if isinstance(item, str)
        ]
        missing_artifacts = [
            relative for relative in required if not (input_dir / relative).exists()
        ]
        row_missing_render_env = sorted(
            placeholders_by_lane.get(lane, set()) & missing_render_env
        )
        row_missing_provider_env = (
            sorted(missing_provider_env_refs) if lane in SHARED_PROVIDER_LANES else []
        )
        checks = raw.get("checks", [])
        if not isinstance(checks, list):
            checks = []
        rows.append(
            {
                "lane": lane,
                "row": raw.get("row"),
                "title": raw.get("title"),
                "runbook": raw.get("runbook"),
                "packet_runbook": _packet_runbook_path(raw.get("runbook")),
                "required_input_artifacts": required,
                "missing_input_artifacts": missing_artifacts,
                "missing_render_environment": row_missing_render_env,
                "missing_provider_manifest_env_refs": row_missing_provider_env,
                "checks": checks,
                "input_artifacts_complete": not missing_artifacts,
                "render_environment_complete": not row_missing_render_env,
                "provider_manifest_environment_complete": not row_missing_provider_env,
                "ready_for_capture": (
                    not missing_artifacts
                    and not row_missing_render_env
                    and not row_missing_provider_env
                ),
            }
        )
    return rows


def _phase_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_lane = {str(row["lane"]): row for row in rows if row.get("lane")}
    shared_missing = sorted(
        lane
        for lane in SHARED_PROVIDER_LANES
        if not by_lane.get(lane, {}).get("provider_manifest_environment_complete")
    )
    return [
        {
            "phase": "0",
            "title": "External custody packet",
            "status": "prepared",
            "purpose": "No-secret workspace for render env, input artifacts, and gap reports.",
        },
        {
            "phase": "1",
            "title": "Shared provider stack",
            "status": "blocked" if shared_missing else "ready",
            "lanes_unblocked_when_done": sorted(SHARED_PROVIDER_LANES),
            "currently_blocked_lanes": shared_missing,
            "purpose": "Provider manifest shared by B1, B2, B4, B6, B7, B9, and B10.",
        },
        {
            "phase": "2",
            "title": "Keystone rows",
            "status": "blocked"
            if any(not by_lane.get(lane, {}).get("ready_for_capture") for lane in ("B1", "B2"))
            else "ready",
            "lanes": ["B1", "B2"],
        },
        {
            "phase": "3",
            "title": "Remaining row bundles",
            "status": "blocked"
            if any(
                not by_lane.get(lane, {}).get("ready_for_capture")
                for lane in ("B3", "B4", "B5", "B6", "B7", "B8", "B9")
            )
            else "ready",
            "lanes": ["B3", "B4", "B5", "B6", "B7", "B8", "B9"],
        },
        {
            "phase": "4",
            "title": "Live parity suite",
            "status": "blocked" if not by_lane.get("B10", {}).get("ready_for_capture") else "ready",
            "lanes": ["B10"],
        },
    ]


def _capture_blockers(
    *,
    rows: list[dict[str, Any]],
    missing_render_env: set[str],
    global_missing_render_env: list[str],
    missing_provider_env_refs: list[str],
    missing_input_artifacts: list[str],
    packet_docs_missing: list[str],
) -> dict[str, Any]:
    blocked_lanes = sorted(
        str(row["lane"])
        for row in rows
        if row.get("lane") and not row.get("ready_for_capture")
    )
    ready_lanes = sorted(
        str(row["lane"])
        for row in rows
        if row.get("lane") and row.get("ready_for_capture")
    )

    render_blocked_lanes = sorted(
        str(row["lane"])
        for row in rows
        if row.get("lane") and row.get("missing_render_environment")
    )
    if global_missing_render_env:
        render_blocked_lanes = blocked_lanes

    provider_blocked_lanes = sorted(
        str(row["lane"])
        for row in rows
        if row.get("lane") and row.get("missing_provider_manifest_env_refs")
    )
    artifact_blocked_lanes = sorted(
        str(row["lane"])
        for row in rows
        if row.get("lane") and row.get("missing_input_artifacts")
    )

    blocker_types: dict[str, dict[str, Any]] = {
        "render_environment": {
            "missing_count": len(missing_render_env),
            "blocked_lanes": render_blocked_lanes,
            "global_missing": global_missing_render_env,
            "values_redacted": True,
        },
        "provider_manifest_environment": {
            "missing_count": len(missing_provider_env_refs),
            "blocked_lanes": provider_blocked_lanes,
            "values_redacted": True,
        },
        "input_artifacts": {
            "missing_count": len(missing_input_artifacts),
            "blocked_lanes": artifact_blocked_lanes,
            "values_redacted": False,
        },
        "packet_docs": {
            "missing_count": len(packet_docs_missing),
            "blocked_lanes": blocked_lanes if packet_docs_missing else [],
            "values_redacted": False,
        },
    }
    recommended_order = [
        {"kind": kind, **details}
        for kind, details in blocker_types.items()
        if details["missing_count"]
    ]
    return {
        "report_is_evidence": False,
        "ready_lanes": ready_lanes,
        "blocked_lanes": blocked_lanes,
        "blocked_lane_count": len(blocked_lanes),
        "types": blocker_types,
        "recommended_order": recommended_order,
    }


def _operator_input_inventory(
    *,
    input_dir: Path,
    render_env_file: Path,
    runtime_env_placeholder: str,
    runtime_env_example: Path,
    missing_render_env: set[str],
    provider_env_refs: list[str],
    missing_provider_env_refs: list[str],
    missing_input_artifacts: list[str],
    runtime_env_file_loaded: bool,
) -> dict[str, Any]:
    return {
        "production_render_env": {
            "path": str(render_env_file),
            "purpose": "Non-secret MNEMOSYNE_PROD_* render placeholders.",
            "missing": sorted(missing_render_env),
            "missing_count": len(missing_render_env),
            "values_may_be_recorded": False,
        },
        "runtime_env_file": {
            "path_placeholder": runtime_env_placeholder,
            "example_path": str(runtime_env_example),
            "purpose": "Secret-bearing runtime/provider values for readiness and capture.",
            "provider_manifest_env_refs": provider_env_refs,
            "missing_provider_manifest_env_refs": missing_provider_env_refs,
            "missing_count": len(missing_provider_env_refs),
            "loaded_for_readiness": runtime_env_file_loaded,
            "values_redacted": True,
        },
        "input_artifacts": {
            "directory": str(input_dir),
            "purpose": "No-secret production evidence input artifacts retained by capture.",
            "missing": missing_input_artifacts,
            "missing_count": len(missing_input_artifacts),
            "checklist": "docs/production-input-artifacts.checklist.md",
        },
    }


def _normalize_check(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, Any] = {}
    for key in ("name", "command", "option"):
        item = value.get(key)
        if isinstance(item, str) and item:
            normalized[key] = item
    lanes = value.get("parity_lanes")
    if isinstance(lanes, list):
        normalized["parity_lanes"] = sorted(
            str(lane) for lane in lanes if isinstance(lane, str)
        )
    return normalized or None


def _normalize_artifact_route(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    lane = value.get("lane")
    if not isinstance(lane, str) or not lane:
        return None
    return {
        "lane": lane,
        "row": value.get("row"),
        "title": value.get("title"),
        "runbook": value.get("runbook"),
        "packet_runbook": _packet_runbook_path(value.get("runbook")),
    }


def _artifact_relative_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = "MNEMOSYNE_PROD_EVIDENCE_DIR/"
    if not value.startswith(prefix):
        return None
    relative_path = value.removeprefix(prefix)
    return relative_path or None


def _template_env_placeholder(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value == "MNEMOSYNE_PROD_EVIDENCE_DIR":
        return None
    if re.fullmatch(r"MNEMOSYNE_PROD_[A-Z0-9_]+", value):
        return value
    return None


def _input_artifact_worklist(
    *,
    input_dir: Path,
    renderer_payload: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build an artifact-first operator worklist without creating placeholders."""
    artifacts: dict[str, dict[str, Any]] = {}
    plan_items = renderer_payload.get("required_input_artifacts_plan", [])
    if isinstance(plan_items, list):
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            relative_path = item.get("relative_path")
            if not isinstance(relative_path, str) or not relative_path:
                continue
            artifacts.setdefault(
                relative_path,
                {
                    "relative_path": relative_path,
                    "checks": [],
                    "routes": [],
                },
            )
            checks = item.get("checks", [])
            if isinstance(checks, list):
                artifacts[relative_path]["checks"].extend(
                    check
                    for check in (_normalize_check(check) for check in checks)
                    if check is not None
                )
            routes = item.get("parity_routes", [])
            if isinstance(routes, list):
                artifacts[relative_path]["routes"].extend(
                    route
                    for route in (_normalize_artifact_route(route) for route in routes)
                    if route is not None
                )

    for row in rows:
        route = _normalize_artifact_route(row)
        checks = [
            check
            for check in (_normalize_check(check) for check in row.get("checks", []))
            if check is not None
        ]
        for relative_path in row.get("required_input_artifacts", []):
            if not isinstance(relative_path, str) or not relative_path:
                continue
            entry = artifacts.setdefault(
                relative_path,
                {
                    "relative_path": relative_path,
                    "checks": [],
                    "routes": [],
                },
            )
            if route is not None:
                entry["routes"].append(route)
            if not entry["checks"]:
                entry["checks"].extend(checks)

    worklist: list[dict[str, Any]] = []
    for relative_path in sorted(artifacts):
        path = input_dir / relative_path
        if path.is_symlink():
            status = "invalid_symlink"
            present = False
        elif path.exists() and not path.is_file():
            status = "invalid_not_file"
            present = False
        elif path.is_file():
            status = "present"
            present = True
        else:
            status = "missing"
            present = False

        checks = {
            json.dumps(check, sort_keys=True): check
            for check in artifacts[relative_path]["checks"]
        }
        routes = {
            json.dumps(route, sort_keys=True): route
            for route in artifacts[relative_path]["routes"]
        }
        worklist.append(
            {
                "relative_path": relative_path,
                "packet_path": str(path),
                "status": status,
                "present": present,
                "rows": sorted(
                    routes.values(),
                    key=lambda route: (str(route.get("lane", "")), str(route.get("row", ""))),
                ),
                "checks": sorted(
                    checks.values(),
                    key=lambda check: (
                        str(check.get("command", "")),
                        str(check.get("option", "")),
                        str(check.get("name", "")),
                    ),
                ),
            }
        )
    return worklist


def _input_artifact_validation_plan(
    *,
    input_dir: Path,
    template_manifest: dict[str, Any],
    worklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build artifact validator commands from the production command profile."""
    required_artifacts = {
        artifact["relative_path"]
        for artifact in worklist
        if isinstance(artifact.get("relative_path"), str)
    }
    artifact_rows = {
        str(artifact["relative_path"]): [
            row
            for row in artifact.get("rows", [])
            if isinstance(row, dict) and isinstance(row.get("lane"), str)
        ]
        for artifact in worklist
        if isinstance(artifact.get("relative_path"), str)
    }
    commands: list[dict[str, Any]] = []
    checks = template_manifest.get("checks", [])
    if not isinstance(checks, list):
        return commands
    for check in checks:
        if not isinstance(check, dict):
            continue
        command = check.get("command")
        if not isinstance(command, str) or not command:
            continue
        global_args = check.get("global_args", [])
        if not isinstance(global_args, list):
            global_args = []
        check_args = check.get("args", [])
        if not isinstance(check_args, list):
            check_args = []
        args = [str(arg) for arg in [*global_args, *check_args] if isinstance(arg, (str, int, float))]
        input_artifacts = [
            str(item)
            for item in check.get("input_artifacts", [])
            if isinstance(item, str)
        ]
        artifact_refs = sorted(
            {
                relative_path
                for relative_path in (
                    _artifact_relative_path(value) for value in [*args, *input_artifacts]
                )
                if relative_path in required_artifacts
            }
        )
        if not artifact_refs:
            continue
        rows = {
            json.dumps(row, sort_keys=True): row
            for relative_path in artifact_refs
            for row in artifact_rows.get(relative_path, [])
        }
        sorted_rows = sorted(
            rows.values(),
            key=lambda row: (str(row.get("lane", "")), str(row.get("row", ""))),
        )
        env_placeholders = sorted(
            {
                name
                for name in (_template_env_placeholder(value) for value in args)
                if name is not None
            }
        )
        argv = [command]
        for arg in args:
            relative_path = _artifact_relative_path(arg)
            if relative_path is not None:
                argv.append(str(input_dir / relative_path))
            else:
                argv.append(arg)
        commands.append(
            {
                "name": check.get("name") if isinstance(check.get("name"), str) else command,
                "command": command,
                "required_input_artifacts": artifact_refs,
                "env_placeholders": env_placeholders,
                "lanes": sorted(
                    {
                        str(row["lane"])
                        for row in sorted_rows
                        if isinstance(row.get("lane"), str)
                    }
                ),
                "rows": sorted_rows,
                "argv": argv,
            }
        )
    return sorted(
        commands,
        key=lambda item: (str(item.get("command", "")), str(item.get("name", ""))),
    )


def _write_runtime_env_example(path: Path, *, provider_env_refs: list[str]) -> None:
    lines = [
        "# Mnemosyne production runtime env example.",
        "#",
        "# Copy this generated no-secret example to an external mode-0600 path,",
        "# fill real values there, then pass that file with:",
        "#",
        "#   export RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env",
        '#   render-production-soak-manifest.sh --runtime-env-file "$RUNTIME_ENV_FILE"',
        '#   capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE"',
        "#",
        "# Do not pass this example directly until every required value is filled.",
        "# Refresh the Tier-B packet after editing provider-manifest.production.json",
        "# so this example follows the current provider env refs.",
        "",
    ]
    if provider_env_refs:
        lines.extend(
            [
                "# Provider-manifest env refs required by input-artifacts/provider-manifest.production.json.",
                "",
            ]
        )
        lines.extend(f'export {name}=""' for name in provider_env_refs)
    else:
        lines.append("# No provider-manifest env refs were found.")
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def _inventory_env_names(repo_dir: Path) -> set[str]:
    inventory = repo_dir / "infra" / "templates" / "production-operator-env.inventory.md"
    names: set[str] = set()
    pattern = re.compile(r"- `([A-Z][A-Z0-9_]*)`")
    for line in inventory.read_text(encoding="utf-8").splitlines():
        match = pattern.fullmatch(line.strip())
        if match:
            names.add(match.group(1))
    return names


def _runtime_env_values(
    path: Path | None,
    *,
    repo_dir: Path,
    provider_env_refs: list[str],
) -> dict[str, str]:
    if path is None:
        return {}
    allowed = sorted(_inventory_env_names(repo_dir) | set(provider_env_refs))
    loader = repo_dir / "infra" / "scripts" / "load-env.py"
    proc = subprocess.run(
        [str(loader), "--allow-missing", str(path), *allowed],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        _fail(f"runtime env file failed strict loading: {stderr}", code=proc.returncode)
    values: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def _resolve_runtime_env_file(raw: str | None, *, repo_dir: Path) -> Path | None:
    if not raw:
        return None
    env_file = Path(raw).expanduser()
    if not env_file.is_absolute():
        _fail("runtime env file must be an absolute external path")
    if env_file.is_symlink():
        _fail("runtime env file must not be a symlink")
    try:
        env_file.relative_to(repo_dir.resolve())
    except ValueError:
        pass
    else:
        _fail("runtime env file must not point inside the repository")
    resolved = env_file.resolve(strict=False)
    try:
        resolved.relative_to(repo_dir.resolve())
    except ValueError:
        return resolved
    _fail("runtime env file must not resolve inside the repository")


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Mnemosyne Tier-B Production Evidence Gap Report",
        "",
        "This report is an operator worklist, not production evidence.",
        "",
        f"- Custody root: `{report['custody_root']}`",
        f"- Input artifact directory: `{report['input_artifacts_dir']}`",
        f"- Ready for capture: `{str(report['ready_for_capture']).lower()}`",
        f"- Missing render env vars: `{len(report['missing_render_environment'])}`",
        f"- Missing provider-manifest env refs: `{len(report['missing_provider_manifest_env_refs'])}`",
        f"- Missing input artifacts: `{report['missing_input_artifact_count']}`",
        f"- Packet docs complete: `{str(report['packet_docs_complete']).lower()}`",
        "",
        "## Highest-Leverage Order",
        "",
    ]
    for phase in report["phase_plan"]:
        lines.append(
            f"- Phase {phase['phase']} - {phase['title']}: `{phase['status']}`"
        )
    blockers = report["capture_blockers"]
    lines.extend(
        [
            "",
            "## Capture Blockers",
            "",
            f"- Blocked lanes: `{blockers['blocked_lane_count']}`",
        ]
    )
    if blockers["blocked_lanes"]:
        lines.extend(f"- `{lane}`" for lane in blockers["blocked_lanes"])
    else:
        lines.append("- None")
    lines.extend(["", "### Recommended Order", ""])
    if blockers["recommended_order"]:
        for item in blockers["recommended_order"]:
            lines.append(
                f"- `{item['kind']}`: `{item['missing_count']}` missing"
            )
            if item["blocked_lanes"]:
                lanes = ", ".join(f"`{lane}`" for lane in item["blocked_lanes"])
                lines.append(f"  - Blocked lanes: {lanes}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Missing Render Environment",
            "",
        ]
    )
    if report["missing_render_environment"]:
        lines.extend(f"- `{name}`" for name in report["missing_render_environment"])
    else:
        lines.append("- None")
    lines.extend(["", "## Missing Provider Manifest Env Refs", ""])
    if report["missing_provider_manifest_env_refs"]:
        lines.extend(f"- `{name}`" for name in report["missing_provider_manifest_env_refs"])
    else:
        lines.append("- None")
    lines.extend(["", "## Packet Guidance Docs", ""])
    if report["packet_docs_added"]:
        lines.append("Added missing packet docs during this refresh:")
        lines.extend(f"- `{name}`" for name in report["packet_docs_added"])
    else:
        lines.append("- No missing packet docs were added during this refresh.")
    if report["packet_docs_missing"]:
        lines.append("- Missing packet docs:")
        lines.extend(f"  - `{name}`" for name in report["packet_docs_missing"])
    else:
        lines.append("- Missing packet docs: `0`")
    inventory = report["operator_input_inventory"]
    lines.extend(
        [
            "",
            "## Operator Input Inventory",
            "",
            "These are edit targets, not evidence.",
            "",
            "### production-render.env",
            "",
            f"- Path: `{inventory['production_render_env']['path']}`",
            f"- Missing values: `{inventory['production_render_env']['missing_count']}`",
        ]
    )
    if inventory["production_render_env"]["missing"]:
        lines.extend(
            f"- `{name}`" for name in inventory["production_render_env"]["missing"]
        )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "### Runtime Env File",
            "",
            f"- Placeholder path: `{inventory['runtime_env_file']['path_placeholder']}`",
            f"- Generated example: `{inventory['runtime_env_file']['example_path']}`",
            f"- Loaded for readiness: `{str(inventory['runtime_env_file']['loaded_for_readiness']).lower()}`",
            f"- Missing provider refs: `{inventory['runtime_env_file']['missing_count']}`",
            f"- Provider env action plan: `{report['provider_env_action_plan_markdown']}`",
        ]
    )
    if inventory["runtime_env_file"]["missing_provider_manifest_env_refs"]:
        lines.extend(
            f"- `{name}`"
            for name in inventory["runtime_env_file"][
                "missing_provider_manifest_env_refs"
            ]
        )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "### Input Artifacts",
            "",
            f"- Directory: `{inventory['input_artifacts']['directory']}`",
            f"- Checklist: `{inventory['input_artifacts']['checklist']}`",
            f"- Missing artifacts: `{inventory['input_artifacts']['missing_count']}`",
        ]
    )
    if inventory["input_artifacts"]["missing"]:
        lines.extend(f"- `{name}`" for name in inventory["input_artifacts"]["missing"])
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Input Artifact Worklist",
            "",
            "This artifact-first list is generated from the production soak manifest",
            "routing. It is a preparation aid only; do not create placeholder JSON",
            "files to make readiness pass.",
            "",
            f"- Markdown: `{report['input_artifact_worklist_markdown']}`",
            f"- JSON: `{report['input_artifact_worklist_json']}`",
            f"- Artifact contracts: `{report['input_artifact_contracts_markdown']}`",
            f"- Provider env action plan: `{report['provider_env_action_plan_markdown']}`",
            f"- Validation script: `{report['input_artifact_validation_script']}`",
            f"- Run every artifact validator: `{report['input_artifact_validation_script']}`",
            f"- Run one Tier-B row: `{report['input_artifact_validation_script']} B1`",
            f"- Row action plan: `{report['row_action_plan_markdown']}`",
            "",
        ]
    )
    for artifact in report["input_artifact_worklist"]:
        rows = ", ".join(f"`{row['lane']}`" for row in artifact["rows"]) or "`unrouted`"
        checks = ", ".join(
            f"`{check.get('command', check.get('name', 'unknown'))}`"
            for check in artifact["checks"]
        ) or "`unknown`"
        lines.extend(
            [
                f"- `{artifact['relative_path']}` - `{artifact['status']}`",
                f"  - Rows: {rows}",
                f"  - Checks: {checks}",
            ]
        )
    lines.extend(["", "## Rows", ""])
    for row in report["rows"]:
        lines.extend(
            [
                f"### {row['lane']} - {row['title']}",
                "",
                f"- Runbook: `{row['runbook']}`",
                f"- Packet runbook: `{row['packet_runbook'] or 'not bundled'}`",
                f"- Ready for capture: `{str(row['ready_for_capture']).lower()}`",
                f"- Missing artifacts: `{len(row['missing_input_artifacts'])}`",
                f"- Missing render env: `{len(row['missing_render_environment'])}`",
                f"- Missing provider env refs: `{len(row['missing_provider_manifest_env_refs'])}`",
            ]
        )
        if row["missing_input_artifacts"]:
            lines.append("- Artifact work:")
            lines.extend(f"  - `{item}`" for item in row["missing_input_artifacts"])
        if row["missing_render_environment"]:
            lines.append("- Render env work:")
            lines.extend(f"  - `{item}`" for item in row["missing_render_environment"])
        if row["missing_provider_manifest_env_refs"]:
            lines.append("- Provider-manifest env work:")
            lines.extend(f"  - `{item}`" for item in row["missing_provider_manifest_env_refs"])
        lines.append("")
    lines.extend(["## Next Commands", ""])
    if report.get("next_commands_script"):
        lines.extend(
            [
                f"- Script: `{report['next_commands_script']}`",
                "",
            ]
        )
    lines.extend(f"```bash\n{command}\n```" for command in report["next_commands"])
    lines.extend(
        [
            "",
            "## Post-Capture Custody Verification",
            "",
            "Run this after full capture completes. Pass the external fingerprint",
            "record directly to the verifier; do not read the expected fingerprint",
            "from the evidence bundle under review.",
            "",
            f"```bash\n{report['post_capture_verify_script']}\n```",
        ]
    )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def _write_input_artifact_worklist_markdown(
    worklist: list[dict[str, Any]],
    path: Path,
) -> None:
    lines = [
        "# Mnemosyne Tier-B Input Artifact Worklist",
        "",
        "This report is an operator preparation aid, not production evidence.",
        "Do not create placeholder JSON, PEM, or bundle files to make readiness pass.",
        "",
        "| Artifact | Status | Rows | Checks | Packet path |",
        "|---|---|---|---|---|",
    ]
    for artifact in worklist:
        rows = "<br>".join(
            f"`{row['lane']}` {row.get('title') or ''}".strip()
            for row in artifact["rows"]
        ) or "`unrouted`"
        checks = "<br>".join(
            f"`{check.get('command', check.get('name', 'unknown'))}`"
            for check in artifact["checks"]
        ) or "`unknown`"
        lines.append(
            "| "
            f"`{artifact['relative_path']}` | "
            f"`{artifact['status']}` | "
            f"{rows} | "
            f"{checks} | "
            f"`{artifact['packet_path']}` |"
        )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def _artifact_kind(relative_path: str) -> str:
    name = Path(relative_path).name
    if name.endswith(".pem"):
        return "pem_certificate_or_trust_anchor"
    if name == "provider-manifest.production.json":
        return "provider_manifest_json"
    if name == "provenance-trust-suite.json":
        return "provenance_trust_suite_json"
    if name.endswith("-bundle.json"):
        return "ops_bundle_json"
    if name.endswith("-evidence.json"):
        return "production_evidence_json"
    if name.endswith("-suite.json"):
        return "gate_suite_json"
    if name.endswith("-dataset.json") or name.endswith("-cases.json"):
        return "validator_dataset_json"
    if name.endswith("-config.json"):
        return "service_config_json"
    if name.endswith("-target.json"):
        return "service_target_json"
    if name.endswith(".json"):
        return "json_object"
    return "file"


def _artifact_contract_notes(
    *,
    relative_path: str,
    kind: str,
    release_output_keys: list[dict[str, Any]],
) -> list[str]:
    notes = [
        "Retain a real production artifact captured by the row runbook; do not synthesize a placeholder.",
        "Keep secrets, credentials, raw private data, and placeholder markers out of the retained artifact.",
        "Pass every consuming validator listed in this contract before full capture.",
    ]
    if release_output_keys:
        notes.append(
            "The retained command output must satisfy the release-audit output-key contract listed here."
        )
    if kind == "provider_manifest_json":
        notes.extend(
            [
                "Keep forbid_local true and configure production provider endpoints or env references only.",
                "Resolve provider env references through the external runtime env file; do not retain values in reports.",
            ]
        )
    elif kind == "pem_certificate_or_trust_anchor":
        notes.append("Retain public certificate or trust-anchor PEM only; private keys do not belong in the packet.")
    elif kind == "provenance_trust_suite_json":
        notes.append("Include the C2PA trust-suite assets and required case identifiers consumed by provenance-trust-check.")
    elif kind == "ops_bundle_json":
        notes.append("Use the row-specific ops-check bundle produced from deployed infrastructure, with empty findings.")
        notes.append(
            "Use the validator section hints below as a production-evidence population checklist; they are advisory, not generated schema or sample data."
        )
    elif kind == "validator_dataset_json":
        notes.append("Use the production calibration/case dataset referenced by the runbook and consuming validator.")
    elif kind == "service_target_json":
        notes.append("Point only at the production hosted endpoint or service target for the named check.")
    elif kind == "service_config_json":
        notes.append("Retain non-secret production configuration needed by the named check.")
    elif kind == "production_evidence_json":
        notes.append("Retain production evidence output from the upstream row gate, not local fixture output.")
    if relative_path == "row-10-full-suite-evidence.json":
        notes.append("Use this only after B1-B9 evidence is captured; B10 is the final live parity sweep.")
    return notes


def _input_artifact_contracts(
    *,
    worklist: list[dict[str, Any]],
    validation_plan: list[dict[str, Any]],
    release_audit_output_keys: dict[str, list[str]],
) -> list[dict[str, Any]]:
    validators_by_artifact: dict[str, list[dict[str, Any]]] = {}
    for validator in validation_plan:
        command = validator.get("command")
        release_keys = release_audit_output_keys.get(command, []) if isinstance(command, str) else []
        section_hints = (
            list(VALIDATOR_SECTION_HINTS_BY_COMMAND.get(command, ()))
            if isinstance(command, str)
            else []
        )
        compact = {
            "name": validator.get("name"),
            "command": command,
            "lanes": validator.get("lanes", []),
            "rows": validator.get("rows", []),
            "env_placeholders": validator.get("env_placeholders", []),
            "validator_section_hints": section_hints,
            "release_audit_output_keys": release_keys,
        }
        for artifact in validator.get("required_input_artifacts", []):
            if isinstance(artifact, str) and artifact:
                validators_by_artifact.setdefault(artifact, []).append(compact)

    contracts: list[dict[str, Any]] = []
    for artifact in worklist:
        relative_path = artifact.get("relative_path")
        if not isinstance(relative_path, str) or not relative_path:
            continue
        validators = sorted(
            validators_by_artifact.get(relative_path, []),
            key=lambda item: (str(item.get("command", "")), str(item.get("name", ""))),
        )
        release_keys_by_command = [
            {
                "command": validator.get("command"),
                "keys": validator.get("release_audit_output_keys", []),
            }
            for validator in validators
            if validator.get("release_audit_output_keys")
        ]
        section_hints_by_command = [
            {
                "command": validator.get("command"),
                "sections": validator.get("validator_section_hints", []),
            }
            for validator in validators
            if validator.get("validator_section_hints")
        ]
        kind = _artifact_kind(relative_path)
        contracts.append(
            {
                "relative_path": relative_path,
                "packet_path": artifact.get("packet_path"),
                "status": artifact.get("status"),
                "present": artifact.get("present") is True,
                "artifact_kind": kind,
                "rows": artifact.get("rows", []),
                "checks": artifact.get("checks", []),
                "consuming_validators": validators,
                "validator_section_hints_by_command": section_hints_by_command,
                "release_audit_output_keys_by_command": release_keys_by_command,
                "minimum_operator_contract": _artifact_contract_notes(
                    relative_path=relative_path,
                    kind=kind,
                    release_output_keys=release_keys_by_command,
                ),
                "report_is_evidence": False,
            }
        )
    return contracts


def _write_input_artifact_contracts_markdown(
    contracts: list[dict[str, Any]],
    path: Path,
) -> None:
    lines = [
        "# Mnemosyne Tier-B Input Artifact Contracts",
        "",
        "This report is an operator preparation aid, not production evidence.",
        "It records what each manifest-referenced artifact must satisfy before",
        "the full production capture path runs. It does not provide samples,",
        "fixtures, placeholder JSON, PEM material, or secret values.",
        "",
        "| Artifact | Kind | Status | Rows | Validators | Section hints | Release output keys |",
        "|---|---|---|---|---|---|---|",
    ]
    for contract in contracts:
        rows = "<br>".join(
            f"`{row['lane']}` {row.get('title') or ''}".strip()
            for row in contract["rows"]
        ) or "`unrouted`"
        validators = "<br>".join(
            f"`{validator.get('name')}`"
            for validator in contract["consuming_validators"]
        ) or "`none`"
        release_keys = "<br>".join(
            f"`{item.get('command')}`: "
            + ", ".join(f"`{key}`" for key in item.get("keys", []))
            for item in contract["release_audit_output_keys_by_command"]
        ) or "`unmapped`"
        section_hints = "<br>".join(
            f"`{item.get('command')}`: "
            + ", ".join(f"`{section}`" for section in item.get("sections", []))
            for item in contract["validator_section_hints_by_command"]
        ) or "`none`"
        lines.append(
            "| "
            f"`{contract['relative_path']}` | "
            f"`{contract['artifact_kind']}` | "
            f"`{contract['status']}` | "
            f"{rows} | "
            f"{validators} | "
            f"{section_hints} | "
            f"{release_keys} |"
        )

    for contract in contracts:
        lines.extend(
            [
                "",
                f"## `{contract['relative_path']}`",
                "",
                f"- Kind: `{contract['artifact_kind']}`",
                f"- Status: `{contract['status']}`",
                f"- Packet path: `{contract.get('packet_path')}`",
                "- Minimum contract:",
            ]
        )
        lines.extend(
            f"  - {note}" for note in contract["minimum_operator_contract"]
        )
        if contract["consuming_validators"]:
            lines.append("- Consuming validators:")
            for validator in contract["consuming_validators"]:
                keys = validator.get("release_audit_output_keys", [])
                key_text = ", ".join(f"`{key}`" for key in keys) if keys else "`unmapped`"
                lines.append(
                    "  - "
                    f"`{validator.get('name')}` "
                    f"({validator.get('command')}), release keys: {key_text}"
                )
        if contract["validator_section_hints_by_command"]:
            lines.append("- Validator section hints (advisory, not schema):")
            for item in contract["validator_section_hints_by_command"]:
                sections = ", ".join(
                    f"`{section}`" for section in item.get("sections", [])
                )
                lines.append(f"  - `{item.get('command')}`: {sections}")
        if contract["rows"]:
            lines.append("- Rows:")
            for row in contract["rows"]:
                lines.append(
                    "  - "
                    f"`{row.get('lane')}` {row.get('title') or ''} "
                    f"runbook `{row.get('packet_runbook') or row.get('runbook')}`"
                )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def _row_action_plan(
    *,
    rows: list[dict[str, Any]],
    validation_plan: list[dict[str, Any]],
    input_artifact_validation_script: Path,
) -> list[dict[str, Any]]:
    validators_by_lane: dict[str, list[dict[str, Any]]] = {}
    for command in validation_plan:
        lanes = command.get("lanes", [])
        if not isinstance(lanes, list):
            continue
        compact = {
            "name": command.get("name"),
            "command": command.get("command"),
            "required_input_artifacts": command.get("required_input_artifacts", []),
            "env_placeholders": command.get("env_placeholders", []),
        }
        for lane in lanes:
            if isinstance(lane, str) and lane:
                validators_by_lane.setdefault(lane, []).append(compact)

    plan: list[dict[str, Any]] = []
    for row in rows:
        lane = row.get("lane")
        if not isinstance(lane, str) or not lane:
            continue
        missing_render = [
            item for item in row.get("missing_render_environment", [])
            if isinstance(item, str)
        ]
        missing_provider = [
            item for item in row.get("missing_provider_manifest_env_refs", [])
            if isinstance(item, str)
        ]
        missing_artifacts = [
            item for item in row.get("missing_input_artifacts", [])
            if isinstance(item, str)
        ]
        next_actions: list[str] = []
        if missing_render:
            next_actions.append("Fill row-scoped production-render.env placeholders.")
        if missing_provider:
            next_actions.append(
                "Fill provider-manifest refs through the external runtime env file."
            )
        if missing_artifacts:
            next_actions.append(
                "Capture real production input artifacts under input-artifacts/."
            )
        if not next_actions:
            next_actions.append(
                "Refresh the packet, run the row validator, then use full capture."
            )
        validators = sorted(
            validators_by_lane.get(lane, []),
            key=lambda item: (
                str(item.get("command", "")),
                str(item.get("name", "")),
            ),
        )
        plan.append(
            {
                "lane": lane,
                "row": row.get("row"),
                "title": row.get("title"),
                "runbook": row.get("runbook"),
                "packet_runbook": row.get("packet_runbook"),
                "ready_for_capture": row.get("ready_for_capture") is True,
                "blocker_counts": {
                    "render_environment": len(missing_render),
                    "provider_manifest_environment": len(missing_provider),
                    "input_artifacts": len(missing_artifacts),
                },
                "missing_render_environment": missing_render,
                "missing_provider_manifest_env_refs": missing_provider,
                "required_input_artifacts": row.get("required_input_artifacts", []),
                "missing_input_artifacts": missing_artifacts,
                "input_artifact_validation_command": (
                    f"{input_artifact_validation_script} {lane}"
                ),
                "validators": validators,
                "next_actions": next_actions,
                "report_is_evidence": False,
            }
        )
    return sorted(plan, key=lambda item: str(item["lane"]))


def _write_row_action_plan_markdown(
    plan: list[dict[str, Any]],
    path: Path,
) -> None:
    lines = [
        "# Mnemosyne Tier-B Row Action Plan",
        "",
        "This report is an operator preparation aid, not production evidence.",
        "It joins row readiness, packet runbooks, missing inputs, and row-scoped",
        "artifact validation commands so B1-B10 work can be assigned without",
        "manual report joins.",
        "",
        "| Row | Ready | Render | Provider refs | Artifacts | Validator |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in plan:
        counts = row["blocker_counts"]
        lines.append(
            "| "
            f"`{row['lane']}` {row.get('title') or ''} | "
            f"`{str(row['ready_for_capture']).lower()}` | "
            f"`{counts['render_environment']}` | "
            f"`{counts['provider_manifest_environment']}` | "
            f"`{counts['input_artifacts']}` | "
            f"`{row['input_artifact_validation_command']}` |"
        )
    for row in plan:
        lines.extend(
            [
                "",
                f"## {row['lane']} - {row.get('title') or 'Untitled'}",
                "",
                f"- Runbook: `{row.get('runbook')}`",
                f"- Packet runbook: `{row.get('packet_runbook') or 'not bundled'}`",
                f"- Ready for capture: `{str(row['ready_for_capture']).lower()}`",
                f"- Row validator: `{row['input_artifact_validation_command']}`",
                "- Next actions:",
            ]
        )
        lines.extend(f"  - {item}" for item in row["next_actions"])
        if row["missing_render_environment"]:
            lines.append("- Missing render env:")
            lines.extend(f"  - `{item}`" for item in row["missing_render_environment"])
        if row["missing_provider_manifest_env_refs"]:
            lines.append("- Missing provider-manifest env refs:")
            lines.extend(
                f"  - `{item}`" for item in row["missing_provider_manifest_env_refs"]
            )
        if row["missing_input_artifacts"]:
            lines.append("- Missing input artifacts:")
            lines.extend(f"  - `{item}`" for item in row["missing_input_artifacts"])
        if row["validators"]:
            lines.append("- Validators:")
            for validator in row["validators"]:
                lines.append(
                    "  - "
                    f"`{validator.get('name')}` "
                    f"({validator.get('command')})"
                )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def _write_provider_env_action_plan_markdown(
    plan: list[dict[str, Any]],
    path: Path,
) -> None:
    lines = [
        "# Mnemosyne Tier-B Provider Env Action Plan",
        "",
        "This report is an operator preparation aid, not production evidence.",
        "It is generated from `input-artifacts/provider-manifest.production.json`",
        "and the current readiness refresh. Values and runtime env-file paths are",
        "never retained.",
        "",
        "| Env var | Status | Primary rows | Affected rows | Provider checks | Paths |",
        "|---|---|---|---|---|---|",
    ]
    for item in plan:
        primary_rows = ", ".join(f"`{lane}`" for lane in item["primary_rows"]) or "-"
        affected_rows = ", ".join(f"`{lane}`" for lane in item["affected_rows"]) or "-"
        provider_checks = (
            ", ".join(f"`{check}`" for check in item["provider_checks"]) or "-"
        )
        paths = "<br>".join(
            f"`{manifest_path}`" for manifest_path in item["provider_manifest_paths"]
        )
        lines.append(
            "| "
            f"`{item['env']}` | "
            f"`{item['status']}` | "
            f"{primary_rows} | "
            f"{affected_rows} | "
            f"{provider_checks} | "
            f"{paths} |"
        )
    for item in plan:
        lines.extend(
            [
                "",
                f"## `{item['env']}`",
                "",
                f"- Status: `{item['status']}`",
                f"- Missing: `{str(item['missing']).lower()}`",
                f"- Values redacted: `{str(item['values_redacted']).lower()}`",
                f"- Value source recorded: `{str(item['value_source_recorded']).lower()}`",
                f"- Next action: {item['next_action']}",
                "- Provider settings:",
            ]
        )
        for setting in item["provider_settings"]:
            lines.append(
                "  - "
                f"`{setting.get('provider_path')}.{setting.get('setting_name')}` "
                f"at `{setting.get('setting_path')}`"
            )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


def _bash_double_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def _validation_script_arg(
    arg: str,
    *,
    input_dir_var: str,
    artifact_path_map: dict[str, str],
) -> str:
    mapped_relative_path = artifact_path_map.get(arg)
    if mapped_relative_path is not None:
        return _bash_double_quote(f"${{{input_dir_var}}}/{mapped_relative_path}")
    relative_path = _artifact_relative_path(arg)
    if relative_path is not None:
        return _bash_double_quote(f"${{{input_dir_var}}}/{relative_path}")
    env_name = _template_env_placeholder(arg)
    if env_name is not None:
        message = f"Set {env_name} in production-render.env or environment before validation"
        return _bash_double_quote(f"${{{env_name}:?{message}}}")
    return _shell_quote(arg)


def _write_input_artifact_validation_script(
    *,
    worklist: list[dict[str, Any]],
    validation_plan: list[dict[str, Any]],
    path: Path,
    repo_dir: Path,
) -> None:
    env_names = sorted(
        {
            str(name)
            for command in validation_plan
            for name in command.get("env_placeholders", [])
            if isinstance(name, str)
        }
    )
    artifact_names = sorted(
        {
            str(artifact["relative_path"])
            for artifact in worklist
            if isinstance(artifact.get("relative_path"), str)
        }
    )
    artifact_lane_map = {
        str(artifact["relative_path"]): sorted(
            {
                str(row["lane"])
                for row in artifact.get("rows", [])
                if isinstance(row, dict) and isinstance(row.get("lane"), str)
            }
        )
        for artifact in worklist
        if isinstance(artifact.get("relative_path"), str)
    }
    artifact_path_map = {
        str(artifact["packet_path"]): str(artifact["relative_path"])
        for artifact in worklist
        if isinstance(artifact.get("packet_path"), str)
        and isinstance(artifact.get("relative_path"), str)
    }
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by prepare-production-evidence-custody.py.",
        "# This validates supplied input artifacts; it is not production evidence.",
        "# It never creates placeholder JSON, PEM, or bundle files.",
        "",
        'REQUESTED_LANE="${1:-all}"',
        'case "$REQUESTED_LANE" in',
        "  all|B1|B2|B3|B4|B5|B6|B7|B8|B9|B10) ;;",
        "  *)",
        (
            '    echo "ERROR: usage: $0 [all|B1|B2|B3|B4|B5|B6|B7|B8|B9|B10]" >&2'
        ),
        "    exit 64",
        "    ;;",
        "esac",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'PACKET_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"',
        'INPUT_ARTIFACT_DIR="$PACKET_ROOT/input-artifacts"',
        f'REPO_DIR="${{MNEMOSYNE_REPO_DIR:-{repo_dir}}}"',
        (
            'PYTHON="${PYTHON:-$(if [ -x "$REPO_DIR/.venv/bin/python" ]; then '
            'printf \'%s\' "$REPO_DIR/.venv/bin/python"; else command -v python3; fi)}"'
        ),
        "",
        'if [ ! -f "$REPO_DIR/pyproject.toml" ]; then',
        '  echo "ERROR: set MNEMOSYNE_REPO_DIR to the Mnemosyne repository root" >&2',
        "  exit 65",
        "fi",
        "",
        "missing=0",
        "invalid=0",
        "selected_validators=0",
        "should_run_lanes() {",
        "  local lanes=\" $1 \"",
        '  if [ "$REQUESTED_LANE" = "all" ]; then',
        "    return 0",
        "  fi",
        '  [[ "$lanes" == *" $REQUESTED_LANE "* ]]',
        "}",
        "check_artifact() {",
        "  local rel=\"$1\"",
        "  local artifact=\"$INPUT_ARTIFACT_DIR/$rel\"",
        '  if [ -L "$artifact" ]; then',
        '    echo "INVALID symlink input artifact: $rel" >&2',
        "    invalid=1",
        '  elif [ ! -f "$artifact" ]; then',
        '    echo "MISSING input artifact: $rel" >&2',
        "    missing=1",
        "  fi",
        "}",
        "check_artifact_for_lanes() {",
        "  local rel=\"$1\"",
        "  local lanes=\"$2\"",
        '  if should_run_lanes "$lanes"; then',
        '    check_artifact "$rel"',
        "  fi",
        "}",
        "",
    ]
    for relative_path in artifact_names:
        lanes = " ".join(artifact_lane_map.get(relative_path, []))
        lines.append(
            f"check_artifact_for_lanes {_shell_quote(relative_path)} {_shell_quote(lanes)}"
        )
    lines.extend(
        [
            "",
            'if [ "$invalid" -ne 0 ]; then',
            "  exit 78",
            "fi",
            'if [ "$missing" -ne 0 ]; then',
            "  exit 78",
            "fi",
            "",
        ]
    )
    if env_names:
        env_args = " ".join(_shell_quote(name) for name in env_names)
        lines.extend(
            [
                "# Load non-secret render placeholders without shell-sourcing production-render.env.",
                'if [ -f "$PACKET_ROOT/production-render.env" ]; then',
                (
                    "  while IFS= read -r assignment; do\n"
                    '    if [ -n "$assignment" ]; then\n'
                    '      export "$assignment"\n'
                    "    fi\n"
                    f'  done < <("$PYTHON" "$REPO_DIR/infra/scripts/load-env.py" '
                    f'--allow-missing "$PACKET_ROOT/production-render.env" {env_args})'
                ),
                "fi",
                "",
            ]
        )
    lines.extend(
        [
            'cd "$REPO_DIR"',
            "",
            "run_validator_for_lanes() {",
            "  local label=\"$1\"",
            "  local lanes=\"$2\"",
            "  shift 2",
            '  if ! should_run_lanes "$lanes"; then',
            "    return 0",
            "  fi",
            "  selected_validators=$((selected_validators + 1))",
            '  echo "==> [$lanes] $label"',
            '  "$@"',
            "}",
            "",
        ]
    )
    for command in validation_plan:
        argv = command.get("argv", [])
        if not isinstance(argv, list) or not argv:
            continue
        label = str(command.get("name") or command.get("command") or "validator")
        lanes = " ".join(str(lane) for lane in command.get("lanes", []))
        rendered_args = [
            _validation_script_arg(
                str(arg),
                input_dir_var="INPUT_ARTIFACT_DIR",
                artifact_path_map=artifact_path_map,
            )
            for arg in argv
            if isinstance(arg, str)
        ]
        lines.extend(
            [
                f"run_validator_for_lanes {_shell_quote(label)} {_shell_quote(lanes)} \\",
                '  "$PYTHON" -m mnemosyne.cli \\',
                *[
                    f"  {arg} \\"
                    for arg in rendered_args[:-1]
                ],
                f"  {rendered_args[-1]}",
                "",
            ]
        )
    lines.extend(
        [
            'if [ "$selected_validators" -eq 0 ]; then',
            '  echo "ERROR: no validators matched $REQUESTED_LANE" >&2',
            "  exit 64",
            "fi",
            "",
        ]
    )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n", mode=0o700)


def _write_readme(root: Path, report: dict[str, Any]) -> None:
    readme = root / "README.md"
    content = f"""# Mnemosyne Tier-B Production Evidence Custody Packet

This packet is a no-secret operator workspace. It is not production evidence.
It includes packet-local row runbooks under `docs/runbooks/` so an external
operator can work from the packet without relying on a live repo checkout.

## Fill These First

1. Edit `production-render.env` outside the repo with non-secret `MNEMOSYNE_PROD_*` values.
2. Fill `input-artifacts/provider-manifest.production.json` with production provider references.
3. Add the remaining row artifacts under `input-artifacts/`.
4. Put secret-bearing runtime/provider values in a separate external mode-0600
   env file, for example `/secure/path/to/mnemosyne-production-runtime.env`.
5. Refresh `reports/tier-b-gap-report.json` generation with:

```bash
RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env
infra/scripts/prepare-production-evidence-custody.py \\
  --runtime-env-file "$RUNTIME_ENV_FILE" \\
  --refresh \\
  {root}
```

Refresh mode updates only `reports/tier-b-gap-report.json`,
`reports/tier-b-gap-report.md`, `reports/input-artifact-worklist.{{json,md}}`,
`reports/input-artifact-contracts.{{json,md}}`,
`reports/provider-env-action-plan.{{json,md}}`,
`reports/row-action-plan.{{json,md}}`,
`reports/input-artifact-validation-commands.sh`, `reports/next-commands.sh`,
and missing read-only packet guidance docs; this README remains static guidance.
It does not overwrite `production-render.env`, `input-artifacts/`, existing
copied operator docs, or `manifests/`.

## Current Report

- JSON: `reports/tier-b-gap-report.json`
- Markdown: `reports/tier-b-gap-report.md`
- Row action plan: `reports/row-action-plan.md`
- Provider env action plan: `reports/provider-env-action-plan.md`
- Input artifact worklist: `reports/input-artifact-worklist.md`
- Input artifact contracts: `reports/input-artifact-contracts.md`
- Input artifact validation: `reports/input-artifact-validation-commands.sh`
- Runnable command sequence: `reports/next-commands.sh`
- Runtime env example: `reports/mnemosyne-production-runtime.env.example`

This README is static guidance and does not carry current readiness status.
After each refresh, read `reports/tier-b-gap-report.md` or
`reports/tier-b-gap-report.json` for the current `ready_for_capture` value,
`capture_blockers`, and `operator_input_inventory`. Use
`reports/row-action-plan.md` to assign row-specific artifact, render-env, and
provider-env work, and use `reports/provider-env-action-plan.md` to route each
provider-manifest env name to its manifest path, primary rows, and shared
provider-check blast radius. Use `reports/input-artifact-contracts.md` to see
each artifact's kind, consuming validators, release-audit output-key contract,
advisory validator section/check hints, and minimum operator contract before
supplying files. Then copy
`reports/mnemosyne-production-runtime.env.example` to the external runtime env
path before filling secret-bearing values.

After adding real production files under `input-artifacts/`, run
`reports/input-artifact-validation-commands.sh` from anywhere to validate all
rows, or pass a specific row such as
`reports/input-artifact-validation-commands.sh B1`. It first refuses missing or
symlinked input artifacts scoped to that selection, then runs the
manifest-derived validator commands against the supplied files. It does not
create placeholders or replace the full capture/offline verification path.

## Capture Boundary

When the report is ready, render the soak manifest to a separate external path
with `render-production-soak-manifest.sh --env-file {root / 'production-render.env'}`
and `--runtime-env-file "$RUNTIME_ENV_FILE"`, then
capture into a new external output root. Do not use this packet root as the
capture output root. Pass secret-bearing runtime/provider values through
`capture-production-evidence.sh --env-file "$RUNTIME_ENV_FILE"`
instead of shell-sourcing them.

After refresh reports `ready_for_capture: true`, set
`RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env` and run
`reports/next-commands.sh` from the repository root, or export
`RUNTIME_ENV_FILE` and run the JSON `next_commands` values in order. The final
command passes the external fingerprint record directly to the verifier and
writes the verifier report outside the evidence bundle.
"""
    _atomic_write_text(readme, content)


def _write_next_commands_script(report: dict[str, Any], path: Path) -> None:
    runtime_env_placeholder = report["operator_input_inventory"]["runtime_env_file"][
        "path_placeholder"
    ]
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated by prepare-production-evidence-custody.py.",
        "# This is an operator convenience script, not production evidence.",
        f"# Review {path.parent / 'tier-b-gap-report.md'} before running.",
        "",
        'if [ ! -x "infra/scripts/render-production-soak-manifest.sh" ]; then',
        '  echo "ERROR: run this script from the Mnemosyne repository root" >&2',
        "  exit 65",
        "fi",
        "",
        f'RUNTIME_ENV_FILE="${{RUNTIME_ENV_FILE:-{runtime_env_placeholder}}}"',
        'if [ ! -f "$RUNTIME_ENV_FILE" ]; then',
        (
            '  echo "ERROR: set RUNTIME_ENV_FILE to the external mode-0600 '
            'runtime env file before running this script" >&2'
        ),
        "  exit 65",
        "fi",
        "",
    ]
    for command in report["next_commands"]:
        lines.extend([command, ""])
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n", mode=0o700)


def _atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        tmp_path = Path(handle.name)
    tmp_path.chmod(mode)
    os.replace(tmp_path, path)


def _validate_existing_packet(root: Path) -> None:
    _require_real_directory(root, label="custody root")
    _require_real_file(root / "production-render.env", label="production-render.env")
    _require_real_directory(root / "input-artifacts", label="input-artifacts")
    _require_real_directory(root / "reports", label="reports")
    _require_real_file(
        root / "input-artifacts" / "provider-manifest.production.json",
        label="provider-manifest.production.json",
    )


def _write_packet_skeleton(root: Path, *, repo_dir: Path) -> None:
    input_dir = root / "input-artifacts"
    reports_dir = root / "reports"
    manifests_dir = root / "manifests"
    for directory in (
        root,
        input_dir,
        reports_dir,
        manifests_dir,
    ):
        directory.mkdir(parents=True, exist_ok=False if directory == root else True)
        directory.chmod(0o700)

    _copy_readonly(
        repo_dir / "infra" / "templates" / "production-render.env.example",
        root / "production-render.env",
    )
    _seed_packet_render_env(root / "production-render.env", input_dir)
    _copy_readonly(
        repo_dir / "infra" / "templates" / "provider-manifest.production.template.json",
        input_dir / "provider-manifest.production.json",
    )
    _sync_packet_docs(root, repo_dir=repo_dir)


def refresh_report(
    root: Path,
    *,
    repo_dir: Path,
    runtime_env_file: Path | None = None,
) -> dict[str, Any]:
    os.umask(0o077)
    _validate_existing_packet(root)
    input_dir = root / "input-artifacts"
    reports_dir = root / "reports"
    manifests_dir = root / "manifests"
    packet_docs = _sync_packet_docs(root, repo_dir=repo_dir)
    template_manifest = _load_json(
        repo_dir / "infra" / "templates" / "production-soak-manifest.template.json"
    )
    env_overrides = _load_packet_render_env(
        root,
        repo_dir=repo_dir,
        template_manifest=template_manifest,
    )
    renderer_code, renderer_payload, renderer_stderr = _run_renderer(
        repo_dir,
        input_dir,
        env_overrides=env_overrides,
        runtime_env_file=runtime_env_file,
    )
    provider_manifest = _load_json(input_dir / "provider-manifest.production.json")
    provider_env_refs = sorted(_collect_env_refs(provider_manifest))
    runtime_env_values = _runtime_env_values(
        runtime_env_file,
        repo_dir=repo_dir,
        provider_env_refs=provider_env_refs,
    )
    missing_provider_env_refs = sorted(
        ref
        for ref in provider_env_refs
        if not os.environ.get(ref) and not runtime_env_values.get(ref)
    )
    placeholders_by_lane, routed_placeholders = _collect_render_placeholders_by_lane(
        template_manifest
    )
    missing_render_env = {
        str(name)
        for name in renderer_payload.get("missing_environment", [])
        if isinstance(name, str)
    }
    global_missing_render_env = sorted(missing_render_env - routed_placeholders)
    rows = _row_report(
        renderer_payload,
        input_dir=input_dir,
        missing_render_env=missing_render_env,
        missing_provider_env_refs=set(missing_provider_env_refs),
        placeholders_by_lane=placeholders_by_lane,
    )
    missing_input_artifacts = sorted(
        {
            item
            for row in rows
            for item in row.get("missing_input_artifacts", [])
            if isinstance(item, str)
        }
    )
    runtime_env_placeholder = "/secure/path/to/mnemosyne-production-runtime.env"
    runtime_env_command_arg = f'"${{RUNTIME_ENV_FILE:-{runtime_env_placeholder}}}"'
    fingerprint_record_output = root.parent / (
        root.name + "-bundle-fingerprint.json"
    )
    capture_output_root = root.parent / (root.name + "-capture")
    preflight_output_root = root.parent / (root.name + "-preflight")
    verify_report_output = root.parent / (root.name + "-production-evidence-verify.json")
    production_render_env = root / "production-render.env"
    production_soak_manifest = manifests_dir / "production-soak-manifest.json"
    runtime_env_example = reports_dir / "mnemosyne-production-runtime.env.example"
    next_commands_script = reports_dir / "next-commands.sh"
    input_artifact_worklist_json = reports_dir / "input-artifact-worklist.json"
    input_artifact_worklist_markdown = reports_dir / "input-artifact-worklist.md"
    input_artifact_contracts_json = reports_dir / "input-artifact-contracts.json"
    input_artifact_contracts_markdown = reports_dir / "input-artifact-contracts.md"
    provider_env_action_plan_json = reports_dir / "provider-env-action-plan.json"
    provider_env_action_plan_markdown = reports_dir / "provider-env-action-plan.md"
    row_action_plan_json = reports_dir / "row-action-plan.json"
    row_action_plan_markdown = reports_dir / "row-action-plan.md"
    input_artifact_validation_script = (
        reports_dir / "input-artifact-validation-commands.sh"
    )
    python_selector = (
        'PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf \'%s\' '
        ".venv/bin/python; else command -v python3; fi)}\""
    )
    post_capture_verify_script = "\n".join(
        [
            python_selector,
            f"BUNDLE_DIR={_shell_quote(capture_output_root)}",
            f"FINGERPRINT_RECORD={_shell_quote(fingerprint_record_output)}",
            f"VERIFY_REPORT={_shell_quote(verify_report_output)}",
            '"$PYTHON" -m mnemosyne.cli production-evidence-verify "$BUNDLE_DIR" \\',
            '  --fingerprint-record "$FINGERPRINT_RECORD" \\',
            '  --report-output "$VERIFY_REPORT"',
        ]
    )
    post_capture_verify_command = (
        f"{python_selector}; "
        f'"$PYTHON" -m mnemosyne.cli production-evidence-verify '
        f"{_shell_quote(capture_output_root)} "
        f"--fingerprint-record {_shell_quote(fingerprint_record_output)} "
        f"--report-output {_shell_quote(verify_report_output)}"
    )
    input_artifact_worklist = _input_artifact_worklist(
        input_dir=input_dir,
        renderer_payload=renderer_payload,
        rows=rows,
    )
    input_artifact_validation_plan = _input_artifact_validation_plan(
        input_dir=input_dir,
        template_manifest=template_manifest,
        worklist=input_artifact_worklist,
    )
    release_audit_output_keys = _release_audit_required_output_keys(repo_dir)
    input_artifact_contracts = _input_artifact_contracts(
        worklist=input_artifact_worklist,
        validation_plan=input_artifact_validation_plan,
        release_audit_output_keys=release_audit_output_keys,
    )
    row_action_plan = _row_action_plan(
        rows=rows,
        validation_plan=input_artifact_validation_plan,
        input_artifact_validation_script=input_artifact_validation_script,
    )
    provider_env_action_plan = _provider_env_action_plan(
        provider_manifest=provider_manifest,
        template_manifest=template_manifest,
        missing_provider_env_refs=missing_provider_env_refs,
    )
    report = {
        "schema": "mnemosyne.tier-b-custody-gap-report.v1",
        "report_is_evidence": False,
        "custody_root": str(root),
        "input_artifacts_dir": str(input_dir),
        "production_render_env": str(production_render_env),
        "production_render_env_loaded": True,
        "packet_docs_complete": packet_docs["complete"],
        "packet_docs_added": packet_docs["added"],
        "packet_docs_missing": packet_docs["missing"],
        "runtime_env_file_loaded": runtime_env_file is not None,
        "runtime_env_file_values_redacted": runtime_env_file is not None,
        "renderer_returncode": renderer_code,
        "renderer_blocked_reason": renderer_payload.get("blocked_reason"),
        "renderer_stderr_present": bool(renderer_stderr.strip()),
        "ready_for_capture": (
            not missing_render_env
            and not missing_provider_env_refs
            and not missing_input_artifacts
            and renderer_payload.get("ok") is True
        ),
        "missing_render_environment": sorted(missing_render_env),
        "global_missing_render_environment": global_missing_render_env,
        "provider_manifest_env_refs": provider_env_refs,
        "missing_provider_manifest_env_refs": missing_provider_env_refs,
        "missing_input_artifacts": missing_input_artifacts,
        "missing_input_artifact_count": len(missing_input_artifacts),
        "input_artifact_worklist_json": str(input_artifact_worklist_json),
        "input_artifact_worklist_markdown": str(input_artifact_worklist_markdown),
        "input_artifact_worklist": input_artifact_worklist,
        "input_artifact_contracts_json": str(input_artifact_contracts_json),
        "input_artifact_contracts_markdown": str(input_artifact_contracts_markdown),
        "input_artifact_contracts": input_artifact_contracts,
        "provider_env_action_plan_json": str(provider_env_action_plan_json),
        "provider_env_action_plan_markdown": str(provider_env_action_plan_markdown),
        "provider_env_action_plan": provider_env_action_plan,
        "row_action_plan_json": str(row_action_plan_json),
        "row_action_plan_markdown": str(row_action_plan_markdown),
        "row_action_plan": row_action_plan,
        "input_artifact_validation_script": str(input_artifact_validation_script),
        "input_artifact_validation_plan": input_artifact_validation_plan,
        "operator_input_inventory": _operator_input_inventory(
            input_dir=input_dir,
            render_env_file=production_render_env,
            runtime_env_placeholder=runtime_env_placeholder,
            runtime_env_example=runtime_env_example,
            missing_render_env=missing_render_env,
            provider_env_refs=provider_env_refs,
            missing_provider_env_refs=missing_provider_env_refs,
            missing_input_artifacts=missing_input_artifacts,
            runtime_env_file_loaded=runtime_env_file is not None,
        ),
        "capture_blockers": _capture_blockers(
            rows=rows,
            missing_render_env=missing_render_env,
            global_missing_render_env=global_missing_render_env,
            missing_provider_env_refs=missing_provider_env_refs,
            missing_input_artifacts=missing_input_artifacts,
            packet_docs_missing=packet_docs["missing"],
        ),
        "rows": rows,
        "phase_plan": _phase_plan(rows),
        "post_capture_verify_report": str(verify_report_output),
        "post_capture_verify_script": post_capture_verify_script,
        "next_commands_script": str(next_commands_script),
        "operator_readiness_files": renderer_payload.get("operator_readiness_files", {}),
        "next_commands": [
            f"infra/scripts/render-production-soak-manifest.sh --env-file {_shell_quote(production_render_env)} --runtime-env-file {runtime_env_command_arg} --check-environment",
            f"infra/scripts/render-production-soak-manifest.sh --env-file {_shell_quote(production_render_env)} --runtime-env-file {runtime_env_command_arg} --output {_shell_quote(production_soak_manifest)}",
            f"infra/scripts/capture-production-evidence.sh --env-file {runtime_env_command_arg} --preflight-only {_shell_quote(production_soak_manifest)} {_shell_quote(preflight_output_root)}",
            f"infra/scripts/capture-production-evidence.sh --env-file {runtime_env_command_arg} --fingerprint-record-output {_shell_quote(fingerprint_record_output)} {_shell_quote(production_soak_manifest)} {_shell_quote(capture_output_root)}",
            post_capture_verify_command,
        ],
    }
    _write_runtime_env_example(runtime_env_example, provider_env_refs=provider_env_refs)
    _write_next_commands_script(report, next_commands_script)
    _atomic_write_text(
        input_artifact_worklist_json,
        json.dumps(input_artifact_worklist, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(
        provider_env_action_plan_json,
        json.dumps(provider_env_action_plan, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(
        input_artifact_contracts_json,
        json.dumps(input_artifact_contracts, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write_text(
        row_action_plan_json,
        json.dumps(row_action_plan, indent=2, sort_keys=True) + "\n",
    )
    _write_input_artifact_worklist_markdown(
        input_artifact_worklist,
        input_artifact_worklist_markdown,
    )
    _write_provider_env_action_plan_markdown(
        provider_env_action_plan,
        provider_env_action_plan_markdown,
    )
    _write_input_artifact_contracts_markdown(
        input_artifact_contracts,
        input_artifact_contracts_markdown,
    )
    _write_row_action_plan_markdown(
        row_action_plan,
        row_action_plan_markdown,
    )
    _write_input_artifact_validation_script(
        worklist=input_artifact_worklist,
        validation_plan=input_artifact_validation_plan,
        path=input_artifact_validation_script,
        repo_dir=repo_dir,
    )
    report_json = reports_dir / "tier-b-gap-report.json"
    _atomic_write_text(report_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_markdown(report, reports_dir / "tier-b-gap-report.md")
    return report


def prepare(
    root: Path,
    *,
    repo_dir: Path,
    runtime_env_file: Path | None = None,
) -> dict[str, Any]:
    os.umask(0o077)
    _write_packet_skeleton(root, repo_dir=repo_dir)
    report = refresh_report(
        root,
        repo_dir=repo_dir,
        runtime_env_file=runtime_env_file,
    )
    _write_readme(root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a no-secret external custody packet for Tier-B production evidence.",
    )
    parser.add_argument(
        "--refresh",
        "--refresh-report",
        action="store_true",
        dest="refresh_report",
        help="Refresh reports in an existing packet without overwriting operator inputs",
    )
    parser.add_argument(
        "--runtime-env-file",
        help=(
            "Strict optional external env file for runtime/provider readiness values; "
            "values are loaded only for validation and are not written to reports"
        ),
    )
    parser.add_argument("custody_root", help="Absolute external packet directory")
    args = parser.parse_args(argv)

    repo_dir = _repo_dir()
    runtime_env_file = _resolve_runtime_env_file(args.runtime_env_file, repo_dir=repo_dir)
    root = _resolve_external_root(
        args.custody_root,
        repo_dir=repo_dir,
        must_exist=args.refresh_report,
    )
    report = (
        refresh_report(root, repo_dir=repo_dir, runtime_env_file=runtime_env_file)
        if args.refresh_report
        else prepare(root, repo_dir=repo_dir, runtime_env_file=runtime_env_file)
    )
    summary = {
        "ok": report["ready_for_capture"],
        "ready_for_capture": report["ready_for_capture"],
        "custody_root": report["custody_root"],
        "report": str(Path(report["custody_root"]) / "reports" / "tier-b-gap-report.json"),
        "markdown": str(Path(report["custody_root"]) / "reports" / "tier-b-gap-report.md"),
        "missing_render_environment": len(report["missing_render_environment"]),
        "missing_provider_manifest_env_refs": len(report["missing_provider_manifest_env_refs"]),
        "missing_input_artifacts": report["missing_input_artifact_count"],
        "packet_docs_complete": report["packet_docs_complete"],
        "packet_docs_added": len(report["packet_docs_added"]),
        "post_capture_verify_report": report["post_capture_verify_report"],
        "next_commands_script": report["next_commands_script"],
        "input_artifact_worklist": report["input_artifact_worklist_markdown"],
        "input_artifact_contracts": report["input_artifact_contracts_markdown"],
        "provider_env_action_plan": report["provider_env_action_plan_markdown"],
        "row_action_plan": report["row_action_plan_markdown"],
        "input_artifact_validation_script": report["input_artifact_validation_script"],
        "next_commands": report["next_commands"],
        "next": (
            "Fill production-render.env and input-artifacts/, then run "
            "next_commands_script or next_commands in order."
        ),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["ready_for_capture"] else BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
