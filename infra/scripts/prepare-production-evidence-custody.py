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


def _resolve_new_external_root(raw: str, *, repo_dir: Path) -> Path:
    root = Path(raw).expanduser()
    if not root.is_absolute():
        _fail("custody root must be an absolute external path")
    if root.exists():
        _fail("custody root must not already exist")
    parent = root.parent.resolve()
    repo_resolved = repo_dir.resolve()
    if _is_inside(parent, repo_resolved):
        _fail("refusing to prepare production custody packet inside the repository")
    return root


def _copy_readonly(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(0o600)


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


def _run_renderer(repo_dir: Path, input_dir: Path) -> tuple[int, dict[str, Any], str]:
    renderer = repo_dir / "infra" / "scripts" / "render-production-soak-manifest.sh"
    env = os.environ.copy()
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(input_dir)
    proc = subprocess.run(
        ["/bin/bash", str(renderer), "--check-environment"],
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
        lane for lane in SHARED_PROVIDER_LANES if not by_lane.get(lane, {}).get("ready_for_capture")
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
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)


def _write_readme(root: Path, report: dict[str, Any]) -> None:
    readme = root / "README.md"
    content = f"""# Mnemosyne Tier-B Production Evidence Custody Packet

This packet is a no-secret operator workspace. It is not production evidence.

## Fill These First

1. Edit `production-render.env` outside the repo with non-secret `MNEMOSYNE_PROD_*` values.
2. Fill `input-artifacts/provider-manifest.production.json` with production provider references.
3. Add the remaining row artifacts under `input-artifacts/`.
4. Re-run `reports/tier-b-gap-report.json` generation with:

```bash
infra/scripts/prepare-production-evidence-custody.py {root}
```

The command above intentionally refuses existing roots. For refreshes, create a
new sibling packet so earlier custody reports remain immutable.

## Current Report

- JSON: `reports/tier-b-gap-report.json`
- Markdown: `reports/tier-b-gap-report.md`
- Ready for capture: `{str(report["ready_for_capture"]).lower()}`

## Capture Boundary

When the report is ready, render the soak manifest to a separate external path
and capture into a new external output root. Do not use this packet root as the
capture output root.
"""
    readme.write_text(content, encoding="utf-8")
    readme.chmod(0o600)


def prepare(root: Path, *, repo_dir: Path) -> dict[str, Any]:
    os.umask(0o077)
    docs_dir = root / "docs"
    input_dir = root / "input-artifacts"
    reports_dir = root / "reports"
    manifests_dir = root / "manifests"
    for directory in (root, docs_dir, input_dir, reports_dir, manifests_dir):
        directory.mkdir(parents=True, exist_ok=False if directory == root else True)
        directory.chmod(0o700)

    _copy_readonly(
        repo_dir / "infra" / "templates" / "production-render.env.example",
        root / "production-render.env",
    )
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

    renderer_code, renderer_payload, renderer_stderr = _run_renderer(repo_dir, input_dir)
    template_manifest = _load_json(
        repo_dir / "infra" / "templates" / "production-soak-manifest.template.json"
    )
    provider_manifest = _load_json(input_dir / "provider-manifest.production.json")
    provider_env_refs = sorted(_collect_env_refs(provider_manifest))
    missing_provider_env_refs = sorted(
        ref for ref in provider_env_refs if not os.environ.get(ref)
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
    report = {
        "schema": "mnemosyne.tier-b-custody-gap-report.v1",
        "report_is_evidence": False,
        "custody_root": str(root),
        "input_artifacts_dir": str(input_dir),
        "renderer_returncode": renderer_code,
        "renderer_blocked_reason": renderer_payload.get("blocked_reason"),
        "renderer_stderr": renderer_stderr.strip(),
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
        "operator_readiness_files": renderer_payload.get("operator_readiness_files", {}),
        "next_commands": [
            f"set -a && source {root / 'production-render.env'} && set +a",
            "infra/scripts/render-production-soak-manifest.sh --check-environment",
            f"infra/scripts/render-production-soak-manifest.sh --output {manifests_dir / 'production-soak-manifest.json'}",
            f"infra/scripts/capture-production-evidence.sh --preflight-only {manifests_dir / 'production-soak-manifest.json'} {root.parent / (root.name + '-preflight')}",
            f"infra/scripts/capture-production-evidence.sh {manifests_dir / 'production-soak-manifest.json'} {root.parent / (root.name + '-capture')}",
        ],
    }
    report_json = reports_dir / "tier-b-gap-report.json"
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_json.chmod(0o600)
    _write_markdown(report, reports_dir / "tier-b-gap-report.md")
    _write_readme(root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a no-secret external custody packet for Tier-B production evidence.",
    )
    parser.add_argument("custody_root", help="New absolute external packet directory")
    args = parser.parse_args(argv)

    repo_dir = _repo_dir()
    root = _resolve_new_external_root(args.custody_root, repo_dir=repo_dir)
    report = prepare(root, repo_dir=repo_dir)
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
