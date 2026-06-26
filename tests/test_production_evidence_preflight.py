from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from mnemosyne.cli import PRODUCTION_RELEASE_REQUIRED_COMMANDS


REPO = Path(__file__).resolve().parents[1]


def _minimal_production_manifest(
    path: Path,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    manifest: dict[str, Any] = {
        "kind": "mnemosyne-production-soak-manifest",
        "validation_scope": {
            "production_validated": True,
            "target_environment": "production",
            "operator_asserted": True,
        },
        "operator": {
            "name": "test operator",
            "user": "operator@example.invalid",
        },
        "checks": [
            {
                "name": command,
                "command": command,
                "args": [],
            }
            for command in PRODUCTION_RELEASE_REQUIRED_COMMANDS
        ],
    }
    if mutate is not None:
        mutate(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_capture_production_evidence_preflight_only_stops_before_soak(tmp_path: Path) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    preflight = json.loads((out_root / "preflight.json").read_text(encoding="utf-8"))
    redaction_scan = json.loads((out_root / "redaction-scan.json").read_text(encoding="utf-8"))
    copied_manifest = json.loads((out_root / "operator-soak-manifest.json").read_text(encoding="utf-8"))

    assert stdout["ok"] is True
    assert stdout["preflight_only"] is True
    assert preflight == stdout
    assert copied_manifest["validation_scope"]["target_environment"] == "production"
    assert stdout["redaction_scan"] == str(out_root / "redaction-scan.json")
    assert redaction_scan["ok"] is True
    assert redaction_scan["scope"] == "preflight"
    assert redaction_scan["findings"] == []
    assert sorted(preflight["provided_commands"]) == sorted(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    assert not (out_root / "evidence").exists()
    assert not (out_root / "deployment-soak.stdout.json").exists()
    assert not (out_root / "release-audit.json").exists()
    assert out_root.stat().st_mode & 0o777 == 0o700


def test_capture_production_evidence_rejects_repo_local_output_root(tmp_path: Path) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = REPO / ".tmp-production-evidence-repo-local"
    _minimal_production_manifest(manifest)
    if out_root.exists():
        shutil.rmtree(out_root)

    try:
        proc = subprocess.run(
            [
                str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
                "--preflight-only",
                str(manifest),
                str(out_root),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )

        assert proc.returncode == 65
        assert "refusing to write production evidence inside the repository" in proc.stderr
        assert not out_root.exists()
    finally:
        if out_root.exists():
            shutil.rmtree(out_root)


def test_capture_production_evidence_rejects_repo_local_soak_manifest(tmp_path: Path) -> None:
    manifest = REPO / ".tmp-production-soak-manifest.json"
    out_root = tmp_path / "capture"
    _minimal_production_manifest(manifest)

    try:
        proc = subprocess.run(
            [
                str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
                "--preflight-only",
                str(manifest),
                str(out_root),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )

        assert proc.returncode == 65
        assert "refusing to use production soak manifest inside the repository" in proc.stderr
        assert not out_root.exists()
    finally:
        if manifest.exists():
            manifest.unlink()


def test_capture_production_evidence_preflight_rejects_unrendered_template(tmp_path: Path) -> None:
    manifest = tmp_path / "production-soak-manifest.template.json"
    manifest.write_text(
        (REPO / "infra" / "templates" / "production-soak-manifest.template.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out_root = tmp_path / "capture"
    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "unresolved production placeholders" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_rejects_nonempty_output_root(tmp_path: Path) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    out_root.mkdir()
    (out_root / "stale.txt").write_text("stale previous evidence", encoding="utf-8")
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "output directory must be empty" in proc.stderr
    assert not (out_root / "preflight.json").exists()
    assert not (out_root / "redaction-scan.json").exists()


def test_capture_production_evidence_preflight_rejects_secret_option_name(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_secret_option(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--idp-token", "from-env-instead"]

    _minimal_production_manifest(manifest, mutate=add_secret_option)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "secret-bearing option --idp-token" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_secret_option_equals_form(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_secret_option(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--auth-token=plain-placeholder-secret"]

    _minimal_production_manifest(manifest, mutate=add_secret_option)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "secret-bearing option --auth-token" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_repo_local_artifact_path(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_repo_local_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = [
            "--cases",
            str(REPO / "tests" / "fixtures" / "production-cases.json"),
        ]

    _minimal_production_manifest(manifest, mutate=add_repo_local_artifact_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "points inside the repository" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_relative_artifact_path(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_relative_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", "production-cases.json"]

    _minimal_production_manifest(manifest, mutate=add_relative_artifact_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "contains relative production artifact path" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_records_input_artifacts(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "cases.json"
    artifact.parent.mkdir()
    artifact.write_text('{"ok": true}\n', encoding="utf-8")

    def add_external_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(artifact)]

    _minimal_production_manifest(manifest, mutate=add_external_artifact_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )

    input_artifacts = stdout["required_input_artifacts"]
    assert len(input_artifacts) == 1
    assert input_artifacts[0]["path"] == str(artifact)
    assert input_artifacts[0]["kind"] == "file"
    assert input_artifacts[0]["labels"] == ["checks[1].args"]
    assert input_artifacts[0]["snapshot_path"].startswith(
        str(out_root / "input-artifacts")
    )
    assert input_artifacts[0]["files"][0]["source_path"] == str(artifact)
    assert input_artifacts[0]["files"][0]["snapshot_path"] == input_artifacts[0]["snapshot_path"]
    assert input_artifacts[0]["files"][0]["sha256"].startswith("sha256:")
    assert input_artifacts[0]["files"][0]["size_bytes"] == artifact.stat().st_size
    copied_manifest = json.loads(
        (out_root / "operator-soak-manifest.json").read_text(encoding="utf-8")
    )
    assert copied_manifest["checks"][0]["args"] == [
        "--cases",
        input_artifacts[0]["snapshot_path"],
    ]
    assert (out_root / "source-soak-manifest.json").exists()
    assert input_artifacts[0]["snapshot_path"] in redaction_scan["scanned_files"]
    assert redaction_scan["skipped_files"] == []


def test_capture_production_evidence_preflight_does_not_snapshot_tool_executable(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    tool.parent.mkdir()
    tool.write_bytes(b"\x00\x01not utf-8 executable bytes")
    tool.chmod(0o755)

    def add_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool", str(tool)]

    _minimal_production_manifest(manifest, mutate=add_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    copied_manifest = json.loads(
        (out_root / "operator-soak-manifest.json").read_text(encoding="utf-8")
    )
    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )

    assert stdout["required_input_artifacts"] == []
    assert stdout["executable_tool_references"] == [
        {
            "option": "--c2pa-tool",
            "path": str(tool),
            "labels": ["checks[9].args"],
        }
    ]
    provenance_check = next(
        item
        for item in copied_manifest["checks"]
        if item["command"] == "provenance-trust-check"
    )
    assert provenance_check["args"] == ["--c2pa-tool", str(tool)]
    assert str(tool) not in redaction_scan["scanned_files"]
    assert redaction_scan["skipped_files"] == []


def test_capture_production_evidence_preflight_rejects_relative_tool_executable(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_relative_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool", "c2patool"]

    _minimal_production_manifest(manifest, mutate=add_relative_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "relative executable path for --c2pa-tool" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_non_executable_tool(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    def add_non_executable_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = [f"--c2pa-tool={tool}"]

    _minimal_production_manifest(manifest, mutate=add_non_executable_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "executable path for --c2pa-tool is not executable" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_missing_tool_executable(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "missing-c2patool"

    def add_missing_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool", str(tool)]

    _minimal_production_manifest(manifest, mutate=add_missing_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "executable path for --c2pa-tool does not exist" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_repo_local_tool_executable(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_repo_local_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool", str(REPO / "infra" / "c2pa" / "c2pa-verify-host.sh")]

    _minimal_production_manifest(manifest, mutate=add_repo_local_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "executable path points inside the repository" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_url_tool_executable(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_url_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool=https://tools.example.invalid/c2patool"]

    _minimal_production_manifest(manifest, mutate=add_url_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "URL executable path for --c2pa-tool" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_snapshots_provenance_suite_assets(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    asset = tmp_path / "production-inputs" / "asset.json"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    tool.parent.mkdir()
    asset.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    asset.write_text('{"asset":"redacted-c2pa-fixture"}\n', encoding="utf-8")
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": str(tool),
                "cases": [
                    {
                        "id": "asset-bound",
                        "asset_path": str(asset),
                        "manifest": {"sha256": "fixture"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def add_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    copied_manifest = json.loads(
        (out_root / "operator-soak-manifest.json").read_text(encoding="utf-8")
    )
    provenance_check = next(
        item
        for item in copied_manifest["checks"]
        if item["command"] == "provenance-trust-check"
    )
    suite_snapshot = Path(provenance_check["args"][1])
    rewritten_suite = json.loads(suite_snapshot.read_text(encoding="utf-8"))
    rewritten_asset_path = rewritten_suite["cases"][0]["asset_path"]
    suite_metadata = next(
        item
        for item in stdout["required_input_artifacts"]
        if Path(item["path"]).name == "provenance-trust-suite.json"
    )

    assert stdout["executable_tool_references"] == [
        {
            "option": "suite.tool",
            "path": str(tool),
            "labels": ["checks[9].args tool"],
        }
    ]
    assert suite_snapshot.is_relative_to(out_root / "input-artifacts")
    assert Path(rewritten_asset_path).is_relative_to(out_root / "input-artifacts")
    assert rewritten_asset_path != str(asset)
    assert suite_metadata["files"][0]["snapshot_path"] == str(suite_snapshot)
    assert suite_metadata["files"][0]["size_bytes"] == suite_snapshot.stat().st_size
    assert suite_metadata["files"][0]["sha256"] == "sha256:" + sha256(
        suite_snapshot.read_bytes()
    ).hexdigest()
    assert {Path(item["path"]).name for item in stdout["required_input_artifacts"]} == {
        "asset.json",
        "provenance-trust-suite.json",
    }


def test_capture_production_evidence_preflight_rewrites_equals_form_suite_path(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    asset = tmp_path / "production-inputs" / "asset.json"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    tool.parent.mkdir()
    asset.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    asset.write_text('{"asset":"redacted-c2pa-fixture"}\n', encoding="utf-8")
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": str(tool),
                "cases": [{"id": "asset-bound", "asset_path": str(asset)}],
            }
        ),
        encoding="utf-8",
    )

    def add_equals_form_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = [f"--suite={suite}"]

    _minimal_production_manifest(manifest, mutate=add_equals_form_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    copied_manifest = json.loads(
        (out_root / "operator-soak-manifest.json").read_text(encoding="utf-8")
    )
    provenance_check = next(
        item
        for item in copied_manifest["checks"]
        if item["command"] == "provenance-trust-check"
    )
    rewritten_arg = provenance_check["args"][0]
    suite_snapshot = Path(rewritten_arg.split("=", 1)[1])
    rewritten_suite = json.loads(suite_snapshot.read_text(encoding="utf-8"))

    assert rewritten_arg.startswith("--suite=")
    assert suite_snapshot.is_relative_to(out_root / "input-artifacts")
    assert Path(rewritten_suite["cases"][0]["asset_path"]).is_relative_to(
        out_root / "input-artifacts"
    )
    assert {Path(item["path"]).name for item in stdout["required_input_artifacts"]} == {
        "asset.json",
        "provenance-trust-suite.json",
    }


def test_capture_production_evidence_preflight_rejects_suite_json(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_suite_json(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite-json", '{"cases": []}']

    _minimal_production_manifest(manifest, mutate=add_suite_json)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "uses --suite-json" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_bare_suite_json(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_bare_suite_json(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite-json"]

    _minimal_production_manifest(manifest, mutate=add_bare_suite_json)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "option --suite-json requires a non-empty value" in proc.stderr
    assert "uses --suite-json" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_bare_suite_option(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)

    def add_bare_suite(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", "--c2pa-tool", str(tool)]

    _minimal_production_manifest(manifest, mutate=add_bare_suite)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "option --suite requires a non-empty value" in proc.stderr
    assert "must include exactly one --suite path" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_relative_suite_path(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)

    def add_relative_suite(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", "suite", "--c2pa-tool", str(tool)]

    _minimal_production_manifest(manifest, mutate=add_relative_suite)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "contains relative provenance trust suite path suite" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_invalid_suite_path_bytes(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_invalid_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", f"{tmp_path}\u0000suite.json"]

    _minimal_production_manifest(manifest, mutate=add_invalid_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "contains invalid path" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_invalid_direct_tool_path_bytes(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_invalid_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool", f"{tmp_path}\u0000c2patool"]

    _minimal_production_manifest(manifest, mutate=add_invalid_tool_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "contains invalid path" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_suite_repo_local_tool(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    asset = tmp_path / "production-inputs" / "asset.json"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    asset.parent.mkdir()
    asset.write_text('{"asset":"redacted-c2pa-fixture"}\n', encoding="utf-8")
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": str(REPO / "infra" / "c2pa" / "c2pa-verify-host.sh"),
                "cases": [{"id": "asset-bound", "asset_path": str(asset)}],
            }
        ),
        encoding="utf-8",
    )

    def add_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "executable path points inside the repository" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_suite_repo_local_asset(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    tool.parent.mkdir()
    suite.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": str(tool),
                "cases": [
                    {
                        "id": "asset-bound",
                        "asset_path": str(REPO / "infra" / "c2pa" / "manifest.json"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def add_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "suite cases[0].asset_path points inside the repository" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_invalid_suite_tool_path_bytes(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    asset = tmp_path / "production-inputs" / "asset.json"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    asset.parent.mkdir()
    asset.write_text('{"asset":"redacted-c2pa-fixture"}\n', encoding="utf-8")
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": f"{tmp_path}\u0000c2patool",
                "cases": [{"id": "asset-bound", "asset_path": str(asset)}],
            }
        ),
        encoding="utf-8",
    )

    def add_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "contains invalid path" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_invalid_suite_asset_path_bytes(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    tool.parent.mkdir()
    suite.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": str(tool),
                "cases": [{"id": "asset-bound", "asset_path": f"{tmp_path}\u0000asset.json"}],
            }
        ),
        encoding="utf-8",
    )

    def add_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "contains invalid path" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_suite_in_global_args(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    suite.parent.mkdir()
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )

    def add_suite_global_args(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["global_args"] = ["--suite", str(suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_global_args)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "global_args contains provenance-trust-check command options" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_c2pa_tool_in_global_args(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    tool.parent.mkdir()
    suite.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    suite.write_text(
        json.dumps({"name": "production-c2pa", "cases": []}),
        encoding="utf-8",
    )

    def add_global_tool(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(suite)]
        check["global_args"] = ["--c2pa-tool", str(tool)]

    _minimal_production_manifest(manifest, mutate=add_global_tool)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "global_args contains provenance-trust-check command options" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_missing_input_artifact(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "missing.json"

    def add_missing_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(artifact)]

    _minimal_production_manifest(manifest, mutate=add_missing_artifact_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "required production input artifact does not exist" in proc.stderr
    assert str(artifact) in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_secret_input_artifact(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "cases.json"
    artifact.parent.mkdir()
    artifact.write_text(
        (
            '{"token": "'
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiJvcGVyYXRvciIsImlhdCI6MTcwMDAwMDAwMH0."
            'MDEyMzQ1Njc4OWFiY2RlZg"}'
        ),
        encoding="utf-8",
    )

    def add_secret_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(artifact)]

    _minimal_production_manifest(manifest, mutate=add_secret_artifact_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "production input artifacts" in proc.stderr
    assert "jwt" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_unscanned_input_artifact(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "cases.json"
    artifact.parent.mkdir()
    artifact.write_bytes(b"\xff\xfe")

    def add_binary_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(artifact)]

    _minimal_production_manifest(manifest, mutate=add_binary_artifact_path)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "production input artifacts include unscanned files" in proc.stderr
    assert "not utf-8 text" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_empty_input_directory(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact_dir = tmp_path / "production-inputs" / "dashboard-package"
    artifact_dir.mkdir(parents=True)

    def add_empty_artifact_dir(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--package-dir", str(artifact_dir)]

    _minimal_production_manifest(manifest, mutate=add_empty_artifact_dir)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "production input artifacts include unscanned files" in proc.stderr
    assert "empty directory" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_symlinked_input_artifact(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact_dir = tmp_path / "production-inputs" / "dashboard-package"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "repo-roadmap.md").symlink_to(REPO / "docs" / "ROADMAP-TO-100.md")

    def add_symlinked_artifact_dir(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--package-dir", str(artifact_dir)]

    _minimal_production_manifest(manifest, mutate=add_symlinked_artifact_dir)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "production input artifacts include unscanned files" in proc.stderr
    assert "symlink not allowed" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_duplicate_commands(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def duplicate_command(payload: dict[str, Any]) -> None:
        payload["checks"].append(dict(payload["checks"][0]))

    _minimal_production_manifest(manifest, mutate=duplicate_command)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "duplicate production release commands" in proc.stderr
    assert PRODUCTION_RELEASE_REQUIRED_COMMANDS[0] in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_uses_staged_input_snapshot_after_source_mutation(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    source_artifact = tmp_path / "production-inputs" / "cases.json"
    fake_python = tmp_path / "fake-python"
    source_artifact.parent.mkdir()
    source_artifact.write_text('{"value": "original"}\n', encoding="utf-8")

    def add_external_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(source_artifact)]

    _minimal_production_manifest(manifest, mutate=add_external_artifact_path)
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON={json.dumps(sys.executable)}
if [ "${{1:-}}" = "-" ]; then
  exec "$REAL_PYTHON" "$@"
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "mnemosyne.cli" ]; then
  shift 2
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --store)
        shift 2
        ;;
      deployment-soak)
        shift
        evidence_dir=""
        soak_manifest=""
        while [ "$#" -gt 0 ]; do
          case "$1" in
            --soak-manifest)
              soak_manifest="$2"
              shift 2
              ;;
            --evidence-dir)
              evidence_dir="$2"
              shift 2
              ;;
            *)
              shift
              ;;
          esac
        done
        mkdir -p "$evidence_dir"
        artifact_path="$("$REAL_PYTHON" - "$soak_manifest" <<'PY'
import json
import sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
args = manifest["checks"][0]["args"]
print(args[args.index("--cases") + 1])
PY
)"
        printf '%s\n' '{{"value": "mutated"}}' > "$SOURCE_ARTIFACT"
        cp "$artifact_path" "$evidence_dir/used-input.json"
        cat > "$evidence_dir/manifest.json" <<'JSON'
{{"ok": true, "validation_scope": {{"production_validated": true, "target_environment": "production", "operator_asserted": true}}, "checks": []}}
JSON
        printf '%s\\n' '{{"ok": true}}'
        exit 0
        ;;
      release-audit)
        printf '%s\\n' '{{"ok": true, "fingerprint": "fake-fingerprint", "findings": []}}'
        exit 0
        ;;
      *)
        shift
        ;;
    esac
  done
fi
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MNEMOSYNE_PYTHON": str(fake_python),
            "SOURCE_ARTIFACT": str(source_artifact),
        },
        check=True,
    )

    copied_manifest = json.loads(
        (out_root / "operator-soak-manifest.json").read_text(encoding="utf-8")
    )
    used_input = (out_root / "evidence" / "used-input.json").read_text(encoding="utf-8")
    snapshot_path = copied_manifest["checks"][0]["args"][1]

    assert json.loads(proc.stdout)["release_audit_ok"] is True
    assert snapshot_path.startswith(str(out_root / "input-artifacts"))
    assert used_input == '{"value": "original"}\n'
    assert source_artifact.read_text(encoding="utf-8") == '{"value": "mutated"}\n'


def test_capture_production_evidence_preflight_rejects_unknown_commands(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_unknown_command(payload: dict[str, Any]) -> None:
        payload["checks"].append(
            {
                "name": "custom-ops-check",
                "command": "custom-ops-check",
                "args": [],
            }
        )

    _minimal_production_manifest(manifest, mutate=add_unknown_command)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "unknown production release commands" in proc.stderr
    assert "custom-ops-check" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_jwt_in_manifest_args(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_jwt_argument(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = [
            "--operator-evidence-token",
            (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiJvcGVyYXRvciIsImlhdCI6MTcwMDAwMDAwMH0."
                "MDEyMzQ1Njc4OWFiY2RlZg"
            ),
        ]

    _minimal_production_manifest(manifest, mutate=add_jwt_argument)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "high-confidence secret material" in proc.stderr
    assert "jwt" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_private_key_in_manifest_args(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_private_key_argument(payload: dict[str, Any]) -> None:
        payload["checks"][0]["global_args"] = [
            "--operator-proof-file",
            "-----BEGIN OPENSSH PRIVATE KEY-----\nredacted-test\n-----END OPENSSH PRIVATE KEY-----",
        ]

    _minimal_production_manifest(manifest, mutate=add_private_key_argument)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "high-confidence secret material" in proc.stderr
    assert "private_key_block" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_fails_if_generated_bundle_contains_secret(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    fake_python = tmp_path / "fake-python"
    _minimal_production_manifest(manifest)
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON={json.dumps(sys.executable)}
if [ "${{1:-}}" = "-" ]; then
  exec "$REAL_PYTHON" "$@"
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "mnemosyne.cli" ]; then
  shift 2
  mode=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --store)
        shift 2
        ;;
      deployment-soak)
        mode="soak"
        shift
        break
        ;;
      release-audit)
        mode="audit"
        shift
        break
        ;;
      *)
        shift
        ;;
    esac
  done
  if [ "$mode" = "soak" ]; then
    evidence_dir=""
    soak_manifest=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --soak-manifest)
          soak_manifest="$2"
          shift 2
          ;;
        --evidence-dir)
          evidence_dir="$2"
          shift 2
          ;;
        *)
          shift
          ;;
      esac
    done
    mkdir -p "$evidence_dir"
    printf '%s\n' "$soak_manifest" > "$evidence_dir/soak-manifest-path.txt"
    cat > "$evidence_dir/manifest.json" <<'JSON'
{{"ok": true, "validation_scope": {{"production_validated": true, "target_environment": "production", "operator_asserted": true}}, "checks": []}}
JSON
    cat > "$evidence_dir/leaked-token.json" <<'JSON'
{{"token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvcGVyYXRvciIsImlhdCI6MTcwMDAwMDAwMH0.MDEyMzQ1Njc4OWFiY2RlZg"}}
JSON
    printf '%s\\n' '{{"ok": true}}'
    exit 0
  fi
  if [ "$mode" = "audit" ]; then
    printf '%s\\n' '{{"ok": true, "fingerprint": "fake-fingerprint", "findings": []}}'
    exit 0
  fi
fi
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    redaction_scan = json.loads((out_root / "redaction-scan.json").read_text(encoding="utf-8"))
    assert proc.returncode == 65
    assert "high-confidence secret material found in the production evidence bundle" in proc.stderr
    assert "jwt" in proc.stderr
    assert redaction_scan["ok"] is False
    assert redaction_scan["findings"][0]["kind"] == "jwt"
    assert not (out_root / "summary.json").exists()


def test_capture_production_evidence_fails_if_generated_bundle_contains_unscanned_file(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    fake_python = tmp_path / "fake-python"
    _minimal_production_manifest(manifest)
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON={json.dumps(sys.executable)}
if [ "${{1:-}}" = "-" ]; then
  exec "$REAL_PYTHON" "$@"
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "mnemosyne.cli" ]; then
  shift 2
  mode=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --store)
        shift 2
        ;;
      deployment-soak)
        mode="soak"
        shift
        break
        ;;
      release-audit)
        mode="audit"
        shift
        break
        ;;
      *)
        shift
        ;;
    esac
  done
  if [ "$mode" = "soak" ]; then
    evidence_dir=""
    soak_manifest=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --soak-manifest)
          soak_manifest="$2"
          shift 2
          ;;
        --evidence-dir)
          evidence_dir="$2"
          shift 2
          ;;
        *)
          shift
          ;;
      esac
    done
    mkdir -p "$evidence_dir"
    printf '%s\n' "$soak_manifest" > "$evidence_dir/soak-manifest-path.txt"
    cat > "$evidence_dir/manifest.json" <<'JSON'
{{"ok": true, "validation_scope": {{"production_validated": true, "target_environment": "production", "operator_asserted": true}}, "checks": []}}
JSON
    printf '\\xff\\xfe\\xfd' > "$evidence_dir/unscanned.bin"
    printf '%s\\n' '{{"ok": true}}'
    exit 0
  fi
  if [ "$mode" = "audit" ]; then
    printf '%s\\n' '{{"ok": true, "fingerprint": "fake-fingerprint", "findings": []}}'
    exit 0
  fi
fi
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    redaction_scan = json.loads((out_root / "redaction-scan.json").read_text(encoding="utf-8"))
    assert proc.returncode == 65
    assert "production evidence bundle contains unscanned files" in proc.stderr
    assert "unscanned.bin" in proc.stderr
    assert redaction_scan["ok"] is False
    assert redaction_scan["skipped_files"][0]["reason"] == "not utf-8 text"
    assert not (out_root / "summary.json").exists()
    assert not (out_root / "bundle-manifest.json").exists()


def test_capture_production_evidence_writes_bundle_manifest(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    fake_python = tmp_path / "fake-python"
    _minimal_production_manifest(manifest)
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON={json.dumps(sys.executable)}
if [ "${{1:-}}" = "-" ]; then
  exec "$REAL_PYTHON" "$@"
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "mnemosyne.cli" ]; then
  shift 2
  mode=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --store)
        shift 2
        ;;
      deployment-soak)
        mode="soak"
        shift
        break
        ;;
      release-audit)
        mode="audit"
        shift
        break
        ;;
      *)
        shift
        ;;
    esac
  done
  if [ "$mode" = "soak" ]; then
    evidence_dir=""
    soak_manifest=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --soak-manifest)
          soak_manifest="$2"
          shift 2
          ;;
        --evidence-dir)
          evidence_dir="$2"
          shift 2
          ;;
        *)
          shift
          ;;
      esac
    done
    mkdir -p "$evidence_dir"
    printf '%s\n' "$soak_manifest" > "$evidence_dir/soak-manifest-path.txt"
    cat > "$evidence_dir/manifest.json" <<'JSON'
{{"ok": true, "validation_scope": {{"production_validated": true, "target_environment": "production", "operator_asserted": true}}, "checks": []}}
JSON
    cat > "$evidence_dir/provider-output.json" <<'JSON'
{{"ok": true, "provider": "hosted"}}
JSON
    printf '%s\\n' '{{"ok": true}}'
    exit 0
  fi
  if [ "$mode" = "audit" ]; then
    printf '%s\\n' '{{"ok": true, "fingerprint": "fake-fingerprint", "findings": []}}'
    exit 0
  fi
fi
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-production-evidence.sh"),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    stdout = json.loads(proc.stdout)
    summary = json.loads((out_root / "summary.json").read_text(encoding="utf-8"))
    bundle_manifest = json.loads((out_root / "bundle-manifest.json").read_text(encoding="utf-8"))
    bundle_paths = {item["path"] for item in bundle_manifest["files"]}

    assert stdout == summary
    assert summary["bundle_manifest"] == str(out_root / "bundle-manifest.json")
    assert summary["bundle_fingerprint"].startswith("sha256:")
    assert bundle_manifest["schema"] == "mnemosyne.production-evidence-bundle.v1"
    assert bundle_manifest["artifact_count"] == len(bundle_manifest["files"])
    assert bundle_manifest["fingerprint"] == summary["bundle_fingerprint"]
    assert "operator-soak-manifest.json" in bundle_paths
    assert "preflight.json" in bundle_paths
    assert "deployment-soak.stdout.json" in bundle_paths
    assert "release-audit.json" in bundle_paths
    assert "redaction-scan.json" in bundle_paths
    assert "evidence/manifest.json" in bundle_paths
    assert "evidence/provider-output.json" in bundle_paths
    assert "evidence/soak-manifest-path.txt" in bundle_paths
    assert "bundle-manifest.json" not in bundle_paths
    assert "summary.json" not in bundle_paths
    assert all(item["sha256"].startswith("sha256:") for item in bundle_manifest["files"])
    assert (out_root / "evidence" / "soak-manifest-path.txt").read_text(
        encoding="utf-8"
    ).strip() == str(out_root / "operator-soak-manifest.json")
