#!/usr/bin/env python3
"""Prepare a no-secret Tier-B production evidence custody packet."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SHARED_PROVIDER_LANES = {"B1", "B2", "B4", "B6", "B7", "B9", "B10"}
PLACEHOLDER_RE = re.compile(r"MNEMOSYNE_PROD_[A-Z0-9_]+")
BLOCKED_EXIT = 78


def _repo_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _fail(message: str, code: int = 65) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


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


def _collect_render_placeholders_by_lane(
    template_manifest: dict[str, Any],
) -> tuple[dict[str, set[str]], set[str]]:
    repo_dir = _repo_dir()
    sys.path.insert(0, str(repo_dir / "src"))
    from mnemosyne.production_parity import parity_lanes_for_command  # noqa: PLC0415

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
        "",
        "## Highest-Leverage Order",
        "",
    ]
    for phase in report["phase_plan"]:
        lines.append(
            f"- Phase {phase['phase']} - {phase['title']}: `{phase['status']}`"
        )
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
    lines.extend(f"```bash\n{command}\n```" for command in report["next_commands"])
    lines.extend(
        [
            "",
            "## Post-Capture Custody Verification",
            "",
            "Run this after full capture completes. The expected fingerprint is read",
            "from the external fingerprint record, not from the evidence bundle under",
            "review.",
            "",
            f"```bash\n{report['post_capture_verify_script']}\n```",
        ]
    )
    _atomic_write_text(path, "\n".join(lines).rstrip() + "\n")


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
infra/scripts/prepare-production-evidence-custody.py \\
  --runtime-env-file /secure/path/to/mnemosyne-production-runtime.env \\
  --refresh \\
  {root}
```

Refresh mode updates only `reports/tier-b-gap-report.json`,
`reports/tier-b-gap-report.md`; this README remains static guidance. It does
not overwrite `production-render.env`, `input-artifacts/`, copied operator docs,
or `manifests/`.

## Current Report

- JSON: `reports/tier-b-gap-report.json`
- Markdown: `reports/tier-b-gap-report.md`

This README is static guidance and does not carry current readiness status.
After each refresh, read `reports/tier-b-gap-report.md` or
`reports/tier-b-gap-report.json` for the current `ready_for_capture` value.

## Capture Boundary

When the report is ready, render the soak manifest to a separate external path
with `render-production-soak-manifest.sh --env-file {root / 'production-render.env'}`
and `--runtime-env-file /secure/path/to/mnemosyne-production-runtime.env`, then
capture into a new external output root. Do not use this packet root as the
capture output root. Pass secret-bearing runtime/provider values through
`capture-production-evidence.sh --env-file /secure/path/to/mnemosyne-production-runtime.env`
instead of shell-sourcing them.

After full capture, run the post-capture custody verification script from
`reports/tier-b-gap-report.md`. It reads the expected fingerprint from the
external fingerprint record and writes the verifier report outside the evidence
bundle.
"""
    _atomic_write_text(readme, content)


def _atomic_write_text(path: Path, text: str) -> None:
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
    tmp_path.chmod(0o600)
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
    docs_dir = root / "docs"
    runbooks_dir = docs_dir / "runbooks"
    input_dir = root / "input-artifacts"
    reports_dir = root / "reports"
    manifests_dir = root / "manifests"
    for directory in (
        root,
        docs_dir,
        runbooks_dir,
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
    for relative in (
        "infra/PRODUCTION-EVIDENCE.md",
        "infra/templates/production-operator-env.inventory.md",
        "infra/templates/production-input-artifacts.checklist.md",
        "infra/templates/production-soak-manifest.template.json",
    ):
        _copy_readonly(repo_dir / relative, docs_dir / Path(relative).name)
    for relative in (
        ".planning/OPS-HANDOFF-AND-OWNERSHIP.md",
        ".planning/ENV-AND-SECRETS.md",
        ".planning/ROLLBACK.md",
    ):
        _copy_readonly(repo_dir / relative, docs_dir / Path(relative).name)
    for runbook in sorted((repo_dir / ".planning" / "runbooks").glob("*.md")):
        _copy_readonly(runbook, runbooks_dir / runbook.name)


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
    fingerprint_record_output = root.parent / (
        root.name + "-bundle-fingerprint.json"
    )
    capture_output_root = root.parent / (root.name + "-capture")
    verify_report_output = root.parent / (root.name + "-production-evidence-verify.json")
    post_capture_verify_script = "\n".join(
        [
            'PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf \'%s\' .venv/bin/python; else command -v python3; fi)}"',
            f"BUNDLE_DIR={capture_output_root}",
            f"FINGERPRINT_RECORD={fingerprint_record_output}",
            (
                'EXPECTED_BUNDLE_FINGERPRINT="$("$PYTHON" -c '
                '\'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["bundle_fingerprint"])\' '
                '"$FINGERPRINT_RECORD")"'
            ),
            f"VERIFY_REPORT={verify_report_output}",
            '"$PYTHON" -m mnemosyne.cli production-evidence-verify "$BUNDLE_DIR" \\',
            '  --expected-bundle-fingerprint "$EXPECTED_BUNDLE_FINGERPRINT" \\',
            '  --report-output "$VERIFY_REPORT"',
        ]
    )
    report = {
        "schema": "mnemosyne.tier-b-custody-gap-report.v1",
        "report_is_evidence": False,
        "custody_root": str(root),
        "input_artifacts_dir": str(input_dir),
        "production_render_env": str(root / "production-render.env"),
        "production_render_env_loaded": True,
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
        "rows": rows,
        "phase_plan": _phase_plan(rows),
        "post_capture_verify_report": str(verify_report_output),
        "post_capture_verify_script": post_capture_verify_script,
        "operator_readiness_files": renderer_payload.get("operator_readiness_files", {}),
        "next_commands": [
            f"infra/scripts/render-production-soak-manifest.sh --env-file {root / 'production-render.env'} --runtime-env-file {runtime_env_placeholder} --check-environment",
            f"infra/scripts/render-production-soak-manifest.sh --env-file {root / 'production-render.env'} --runtime-env-file {runtime_env_placeholder} --output {manifests_dir / 'production-soak-manifest.json'}",
            f"infra/scripts/capture-production-evidence.sh --env-file {runtime_env_placeholder} --preflight-only {manifests_dir / 'production-soak-manifest.json'} {root.parent / (root.name + '-preflight')}",
            f"infra/scripts/capture-production-evidence.sh --env-file {runtime_env_placeholder} --fingerprint-record-output {fingerprint_record_output} {manifests_dir / 'production-soak-manifest.json'} {capture_output_root}",
        ],
    }
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
        "custody_root": report["custody_root"],
        "report": str(Path(report["custody_root"]) / "reports" / "tier-b-gap-report.json"),
        "markdown": str(Path(report["custody_root"]) / "reports" / "tier-b-gap-report.md"),
        "missing_render_environment": len(report["missing_render_environment"]),
        "missing_provider_manifest_env_refs": len(report["missing_provider_manifest_env_refs"]),
        "missing_input_artifacts": report["missing_input_artifact_count"],
        "next": "Fill production-render.env and input-artifacts/, then render and capture from external paths.",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["ready_for_capture"] else BLOCKED_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
