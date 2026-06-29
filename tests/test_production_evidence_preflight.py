from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

import pytest

from mnemosyne.cli import PRODUCTION_RELEASE_REQUIRED_COMMANDS
from mnemosyne.evidence_redaction import scan_evidence_paths, scan_evidence_tree
from mnemosyne.production_parity import build_parity_row_readiness


REPO = Path(__file__).resolve().parents[1]
CAPTURE_SCRIPT = REPO / "infra" / "scripts" / "capture-production-evidence.sh"


def _preflight_rows_by_lane(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload["parity_row_readiness"]
    assert isinstance(rows, list)
    return {str(row["lane"]): row for row in rows if isinstance(row, dict)}


def _retained_input_path(out_root: Path, artifact: dict[str, Any]) -> str:
    return Path(str(artifact["snapshot_path"])).relative_to(out_root).as_posix()


def _expected_preflight_row_readiness(
    out_root: Path,
    input_artifacts: list[dict[str, Any]],
) -> list[dict[str, object]]:
    return build_parity_row_readiness(
        [
            {
                "relative_path": _retained_input_path(out_root, artifact),
                "checks": artifact["checks"],
                "parity_routes": artifact["parity_routes"],
                "exists": True,
            }
            for artifact in input_artifacts
        ]
    )


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


def test_redaction_scan_rejects_symlinked_tree_root(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / "operator-note.txt").write_text(
        "non-secret operator note\n", encoding="utf-8"
    )
    linked_root = tmp_path / "linked-root"
    try:
        linked_root.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    scan = scan_evidence_paths(
        [linked_root],
        scope="preflight",
        reject_symlinks=True,
    )

    assert scan["ok"] is False
    assert scan["findings"] == []
    assert scan["scanned_files"] == []
    assert scan["skipped_files"] == [
        {"path": str(linked_root), "reason": "symlink not allowed"}
    ]


def test_redaction_tree_scan_rejects_symlinked_output_root(tmp_path: Path) -> None:
    external = tmp_path / "external-output-root"
    external.mkdir()
    (external / "retained-artifact.txt").write_text(
        "retained artifact\n", encoding="utf-8"
    )
    out_root = tmp_path / "linked-output-root"
    try:
        out_root.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    scan = scan_evidence_tree(out_root)

    assert scan["ok"] is False
    assert scan["findings"] == []
    assert scan["scanned_files"] == []
    assert scan["skipped_files"] == [
        {"path": str(out_root), "reason": "symlink not allowed"}
    ]


def test_redaction_tree_scan_scans_nested_redaction_scan_files(tmp_path: Path) -> None:
    out_root = tmp_path / "capture"
    nested = out_root / "input-artifacts" / "redaction-scan.json"
    root_scan = out_root / "redaction-scan.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("nested retained artifact\n", encoding="utf-8")
    root_scan.write_text('{"ok": true}\n', encoding="utf-8")

    scan = scan_evidence_tree(out_root)

    assert scan["ok"] is True
    assert str(nested) in scan["scanned_files"]
    assert str(root_scan) not in scan["scanned_files"]


def test_redaction_scan_detects_dsn_vault_and_bearer_secret_shapes(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.txt"
    evidence.write_text(
        "\n".join(
            [
                "database=postgresql://mnemosyne:secret-password@db.example.invalid/prod",
                "vault_token=hvs.abcdefghijklmnopqrstuvwxyz0123456789",
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    scan = scan_evidence_paths([evidence], scope="test")
    kinds = {finding["kind"] for finding in scan["findings"]}

    assert scan["ok"] is False
    assert {"url_userinfo", "vault_token", "authorization_bearer"} <= kinds


def test_capture_production_evidence_preflight_only_stops_before_soak(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )
    copied_manifest = json.loads(
        (out_root / "operator-soak-manifest.json").read_text(encoding="utf-8")
    )

    assert stdout["ok"] is True
    assert stdout["preflight_only"] is True
    assert preflight == stdout
    assert copied_manifest["validation_scope"]["target_environment"] == "production"
    assert stdout["redaction_scan"] == str(out_root / "redaction-scan.json")
    assert redaction_scan["ok"] is True
    assert redaction_scan["scope"] == "preflight"
    assert redaction_scan["findings"] == []
    assert sorted(preflight["provided_commands"]) == sorted(
        PRODUCTION_RELEASE_REQUIRED_COMMANDS
    )
    assert not (out_root / "evidence").exists()
    assert not (out_root / "deployment-soak.stdout.json").exists()
    assert not (out_root / "release-audit.json").exists()
    assert out_root.stat().st_mode & 0o777 == 0o700


def test_capture_production_evidence_full_capture_requires_explicit_output_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            str(manifest),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 64
    assert "production evidence output root is required" in proc.stderr
    assert proc.stdout == ""


def test_capture_production_evidence_preflight_requires_explicit_output_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 64
    assert "production evidence output root is required" in proc.stderr
    assert "explicit absolute external OUT_ROOT" in proc.stderr
    assert proc.stdout == ""


def test_capture_production_evidence_rejects_relative_manifest_path(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            manifest.name,
            str(out_root),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "production soak manifest path must be absolute" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_rejects_relative_output_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            "capture",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "production evidence output root must be absolute" in proc.stderr
    assert not (tmp_path / "capture").exists()


def test_capture_production_evidence_rejects_malformed_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    manifest.write_text("{", encoding="utf-8")

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "ERROR: production soak manifest is not valid JSON" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_rejects_repo_local_output_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = REPO / ".tmp-production-evidence-repo-local"
    _minimal_production_manifest(manifest)
    if out_root.exists():
        shutil.rmtree(out_root)

    try:
        proc = subprocess.run(
            [
                "/bin/bash",
                str(CAPTURE_SCRIPT),
                "--preflight-only",
                str(manifest),
                str(out_root),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )

        assert proc.returncode == 65
        assert (
            "refusing to write production evidence inside the repository" in proc.stderr
        )
        assert not out_root.exists()
    finally:
        if out_root.exists():
            shutil.rmtree(out_root)


def test_capture_production_evidence_rejects_symlinked_output_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    target_root = tmp_path / "real-capture"
    out_root = tmp_path / "linked-capture"
    target_root.mkdir()
    try:
        out_root.symlink_to(target_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "production evidence output root cannot be a symlink" in proc.stderr
    assert not (target_root / "preflight.json").exists()


def test_capture_production_evidence_rejects_repo_local_soak_manifest(
    tmp_path: Path,
) -> None:
    manifest = REPO / ".tmp-production-soak-manifest.json"
    out_root = tmp_path / "capture"
    _minimal_production_manifest(manifest)

    try:
        proc = subprocess.run(
            [
                "/bin/bash",
                str(CAPTURE_SCRIPT),
                "--preflight-only",
                str(manifest),
                str(out_root),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )

        assert proc.returncode == 65
        assert (
            "refusing to use production soak manifest inside the repository"
            in proc.stderr
        )
        assert not out_root.exists()
    finally:
        if manifest.exists():
            manifest.unlink()


def test_capture_production_evidence_preflight_rejects_unrendered_template(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak-manifest.template.json"
    manifest.write_text(
        (
            REPO / "infra" / "templates" / "production-soak-manifest.template.json"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out_root = tmp_path / "capture"
    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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


def test_capture_production_evidence_rejects_existing_output_root(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    out_root.mkdir()
    (out_root / "stale.txt").write_text("stale previous evidence", encoding="utf-8")
    _minimal_production_manifest(manifest)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "output root must not already exist" in proc.stderr
    assert not (out_root / "preflight.json").exists()
    assert not (out_root / "redaction-scan.json").exists()


def test_capture_production_evidence_preflight_rejects_secret_option_name(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_secret_option(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--access-token", "from-env-instead"]

    _minimal_production_manifest(manifest, mutate=add_secret_option)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "secret-bearing option --access-token" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_secret_option_equals_form(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_secret_option(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--api-token=from-env-instead"]

    _minimal_production_manifest(manifest, mutate=add_secret_option)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "secret-bearing option --api-token" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_dsn_secret_option(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_secret_option(payload: dict[str, Any]) -> None:
        payload["checks"][0]["global_args"] = ["--postgres-dsn=from-env-instead"]

    _minimal_production_manifest(manifest, mutate=add_secret_option)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "secret-bearing option --postgres-dsn" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_url_userinfo(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_url_userinfo(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = [
            "--cases=https://operator:secret@example.invalid/cases.json"
        ]

    _minimal_production_manifest(manifest, mutate=add_url_userinfo)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "url_userinfo" in proc.stderr
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    assert input_artifacts[0]["source_values"] == [str(artifact)]
    assert input_artifacts[0]["kind"] == "file"
    assert input_artifacts[0]["labels"] == ["checks[1].args"]
    assert input_artifacts[0]["checks"] == [
        {
            "name": "belief-revision-check",
            "command": "belief-revision-check",
            "option": "--cases",
            "parity_lanes": ["B10"],
        }
    ]
    assert input_artifacts[0]["parity_routes"] == [
        {
            "lane": "B10",
            "row": 10,
            "title": "Live parity suite",
            "runbook": ".planning/runbooks/row-10-live-parity-suite.md",
        }
    ]
    assert input_artifacts[0]["snapshot_path"].startswith(
        str(out_root / "input-artifacts")
    )
    assert input_artifacts[0]["files"][0]["source_path"] == str(artifact)
    assert (
        input_artifacts[0]["files"][0]["snapshot_path"]
        == input_artifacts[0]["snapshot_path"]
    )
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
    assert (
        str(out_root / "source-soak-manifest.json") in redaction_scan["scanned_files"]
    )
    assert (
        str(out_root / "operator-soak-manifest.json") in redaction_scan["scanned_files"]
    )
    assert str(out_root / "preflight.json") in redaction_scan["scanned_files"]
    assert str(manifest) not in redaction_scan["scanned_files"]
    assert input_artifacts[0]["snapshot_path"] in redaction_scan["scanned_files"]
    assert redaction_scan["skipped_files"] == []
    assert stdout["parity_row_readiness"] == _expected_preflight_row_readiness(
        out_root,
        input_artifacts,
    )
    rows = _preflight_rows_by_lane(stdout)
    assert rows["B10"]["required_input_artifacts"] == [
        _retained_input_path(out_root, input_artifacts[0])
    ]
    assert rows["B10"]["input_artifacts_complete"] is True


def test_capture_production_evidence_preflight_rejects_symlinked_argument_artifact(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "cases.json"
    linked_artifact = tmp_path / "production-inputs" / "linked-cases.json"
    artifact.parent.mkdir()
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    try:
        linked_artifact.symlink_to(artifact)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    def add_external_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(linked_artifact)]

    _minimal_production_manifest(manifest, mutate=add_external_artifact_path)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "symlinked input artifact path" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_symlinked_manifest_artifact(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact_dir = tmp_path / "production-inputs" / "gate-suite"
    linked_dir = tmp_path / "production-inputs" / "linked-gate-suite"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "cases.json").write_text('{"ok": true}\n', encoding="utf-8")
    try:
        linked_dir.symlink_to(artifact_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    def add_manifest_input_artifact(payload: dict[str, Any]) -> None:
        payload["checks"][0]["input_artifacts"] = [str(linked_dir)]

    _minimal_production_manifest(manifest, mutate=add_manifest_input_artifact)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "symlinked input artifact path" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_ops_report_package_output(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"

    def add_ops_report_package_output(payload: dict[str, Any]) -> None:
        check = next(
            item for item in payload["checks"] if item["command"] == "ops-report"
        )
        check["args"] = [
            "--tenant",
            "tenant-prod",
            "--dashboard-package-dir",
            str(tmp_path / "production-inputs" / "dashboard-package"),
        ]

    _minimal_production_manifest(manifest, mutate=add_ops_report_package_output)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "ops-report output option --dashboard-package-dir" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_records_manifest_input_artifacts(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "row-10-full-suite-evidence.json"
    artifact.parent.mkdir()
    artifact.write_text('{"full_suite": true}\n', encoding="utf-8")

    def add_manifest_input_artifact(payload: dict[str, Any]) -> None:
        payload["checks"][0]["input_artifacts"] = [str(artifact)]

    _minimal_production_manifest(manifest, mutate=add_manifest_input_artifact)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    input_artifacts = stdout["required_input_artifacts"]

    assert len(input_artifacts) == 1
    assert input_artifacts[0]["path"] == str(artifact)
    assert input_artifacts[0]["source_values"] == [str(artifact)]
    assert input_artifacts[0]["kind"] == "file"
    assert input_artifacts[0]["labels"] == ["checks[1].input_artifacts"]
    assert input_artifacts[0]["checks"] == [
        {
            "name": "belief-revision-check",
            "command": "belief-revision-check",
            "option": "input_artifacts[0]",
            "parity_lanes": ["B10"],
        }
    ]
    assert copied_manifest["checks"][0]["input_artifacts"] == [
        input_artifacts[0]["snapshot_path"]
    ]
    assert copied_manifest["checks"][0]["args"] == []
    assert input_artifacts[0]["snapshot_path"] in redaction_scan["scanned_files"]
    assert stdout["parity_row_readiness"] == _expected_preflight_row_readiness(
        out_root,
        input_artifacts,
    )


def test_capture_production_evidence_preflight_records_equals_form_input_artifacts(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    artifact = tmp_path / "production-inputs" / "cases.json"
    artifact.parent.mkdir()
    artifact.write_text('{"ok": true}\n', encoding="utf-8")

    def add_external_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = [f"--cases={artifact}"]

    _minimal_production_manifest(manifest, mutate=add_external_artifact_path)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    input_artifact = stdout["required_input_artifacts"][0]

    assert input_artifact["path"] == str(artifact)
    assert input_artifact["source_values"] == [str(artifact)]
    assert input_artifact["snapshot_path"].startswith(str(out_root / "input-artifacts"))
    assert input_artifact["checks"] == [
        {
            "name": "belief-revision-check",
            "command": "belief-revision-check",
            "option": "--cases",
            "parity_lanes": ["B10"],
        }
    ]
    assert copied_manifest["checks"][0]["args"] == [
        f"--cases={input_artifact['snapshot_path']}"
    ]


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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    assert stdout["parity_row_readiness"] == []
    assert stdout["executable_tool_references"] == [
        {
            "option": "--c2pa-tool",
            "path": str(tool),
            "labels": ["checks[9].args"],
        }
    ]
    assert (
        str(out_root / "source-soak-manifest.json") in redaction_scan["scanned_files"]
    )
    assert (
        str(out_root / "operator-soak-manifest.json") in redaction_scan["scanned_files"]
    )
    assert str(manifest) not in redaction_scan["scanned_files"]
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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


def test_capture_production_evidence_preflight_rejects_symlinked_tool_executable(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool-real"
    link = tmp_path / "bin" / "c2patool-link"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    try:
        link.symlink_to(tool)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    def add_symlinked_tool_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--c2pa-tool", str(link)]

    _minimal_production_manifest(manifest, mutate=add_symlinked_tool_path)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "points through a symlink or non-canonical path" in proc.stderr
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
        check["args"] = [
            "--c2pa-tool",
            str(REPO / "infra" / "c2pa" / "c2pa-verify-host.sh"),
        ]

    _minimal_production_manifest(manifest, mutate=add_repo_local_tool_path)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    artifact_by_name = {
        Path(item["path"]).name: item for item in stdout["required_input_artifacts"]
    }
    asset_metadata = artifact_by_name["asset.json"]
    suite_metadata = artifact_by_name["provenance-trust-suite.json"]

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
    assert asset_metadata["source_values"] == [str(asset)]
    assert suite_metadata["source_values"] == [str(suite)]
    assert asset_metadata["checks"] == [
        {
            "name": "provenance-trust-check",
            "command": "provenance-trust-check",
            "option": "cases[0].asset_path",
            "parity_lanes": ["B5"],
        }
    ]
    assert suite_metadata["checks"] == [
        {
            "name": "provenance-trust-check",
            "command": "provenance-trust-check",
            "option": "--suite",
            "parity_lanes": ["B5"],
        }
    ]
    assert suite_metadata["files"][0]["snapshot_path"] == str(suite_snapshot)
    assert suite_metadata["files"][0]["size_bytes"] == suite_snapshot.stat().st_size
    assert (
        suite_metadata["files"][0]["sha256"]
        == "sha256:" + sha256(suite_snapshot.read_bytes()).hexdigest()
    )
    assert {Path(item["path"]).name for item in stdout["required_input_artifacts"]} == {
        "asset.json",
        "provenance-trust-suite.json",
    }
    assert stdout["parity_row_readiness"] == _expected_preflight_row_readiness(
        out_root,
        stdout["required_input_artifacts"],
    )
    rows = _preflight_rows_by_lane(stdout)
    assert rows["B5"]["required_input_artifacts"] == sorted(
        [
            _retained_input_path(out_root, asset_metadata),
            _retained_input_path(out_root, suite_metadata),
        ]
    )
    assert rows["B5"]["input_artifacts_complete"] is True


def test_capture_production_evidence_preflight_rejects_symlinked_provenance_suite(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    linked_suite = tmp_path / "production-inputs" / "linked-suite.json"
    suite.parent.mkdir()
    suite.write_text('{"cases": []}\n', encoding="utf-8")
    try:
        linked_suite.symlink_to(suite)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    def add_suite_path(payload: dict[str, Any]) -> None:
        check = next(
            item
            for item in payload["checks"]
            if item["command"] == "provenance-trust-check"
        )
        check["args"] = ["--suite", str(linked_suite)]

    _minimal_production_manifest(manifest, mutate=add_suite_path)

    proc = subprocess.run(
        [
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "symlinked input artifact path" in proc.stderr
    assert not out_root.exists()


def test_capture_production_evidence_preflight_rejects_symlinked_suite_asset(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    tool = tmp_path / "bin" / "c2patool"
    asset = tmp_path / "production-inputs" / "asset.json"
    linked_asset = tmp_path / "production-inputs" / "linked-asset.json"
    suite = tmp_path / "production-inputs" / "provenance-trust-suite.json"
    tool.parent.mkdir()
    asset.parent.mkdir()
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    asset.write_text('{"asset":"redacted-c2pa-fixture"}\n', encoding="utf-8")
    try:
        linked_asset.symlink_to(asset)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")
    suite.write_text(
        json.dumps(
            {
                "name": "production-c2pa",
                "tool": str(tool),
                "cases": [{"id": "asset-bound", "asset_path": str(linked_asset)}],
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            "--preflight-only",
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 65
    assert "symlinked input artifact path" in proc.stderr
    assert not out_root.exists()


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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    artifact_by_name = {
        Path(item["path"]).name: item for item in stdout["required_input_artifacts"]
    }

    assert rewritten_arg.startswith("--suite=")
    assert suite_snapshot.is_relative_to(out_root / "input-artifacts")
    assert Path(rewritten_suite["cases"][0]["asset_path"]).is_relative_to(
        out_root / "input-artifacts"
    )
    assert artifact_by_name["asset.json"]["source_values"] == [str(asset)]
    assert artifact_by_name["provenance-trust-suite.json"]["source_values"] == [
        str(suite)
    ]
    assert artifact_by_name["provenance-trust-suite.json"]["checks"] == [
        {
            "name": "provenance-trust-check",
            "command": "provenance-trust-check",
            "option": "--suite",
            "parity_lanes": ["B5"],
        }
    ]
    assert {Path(item["path"]).name for item in stdout["required_input_artifacts"]} == {
        "asset.json",
        "provenance-trust-suite.json",
    }
    assert stdout["parity_row_readiness"] == _expected_preflight_row_readiness(
        out_root,
        stdout["required_input_artifacts"],
    )


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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
                "cases": [
                    {"id": "asset-bound", "asset_path": f"{tmp_path}\u0000asset.json"}
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    linked_input_root = tmp_path / "linked-production-inputs"
    fake_python = tmp_path / "fake-python"
    source_artifact.parent.mkdir()
    source_artifact.write_text('{"value": "original"}\n', encoding="utf-8")
    try:
        linked_input_root.symlink_to(source_artifact.parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")
    manifest_artifact = linked_input_root / source_artifact.name

    def add_external_artifact_path(payload: dict[str, Any]) -> None:
        payload["checks"][0]["args"] = ["--cases", str(manifest_artifact)]

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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    preflight = json.loads((out_root / "preflight.json").read_text(encoding="utf-8"))
    used_input = (out_root / "evidence" / "used-input.json").read_text(encoding="utf-8")
    snapshot_path = copied_manifest["checks"][0]["args"][1]
    input_artifact = preflight["required_input_artifacts"][0]

    assert json.loads(proc.stdout)["release_audit_ok"] is True
    assert input_artifact["path"] == str(source_artifact.resolve(strict=True))
    assert input_artifact["source_values"] == [str(manifest_artifact)]
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )
    assert proc.returncode == 65
    assert (
        "high-confidence secret material found in the production evidence bundle"
        in proc.stderr
    )
    assert "jwt" in proc.stderr
    assert redaction_scan["ok"] is False
    assert redaction_scan["findings"][0]["kind"] == "jwt"
    assert not (out_root / "summary.json").exists()


def test_capture_production_evidence_scans_nested_redaction_scan_artifact(
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
    while [ "$#" -gt 0 ]; do
      case "$1" in
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
    cat > "$evidence_dir/manifest.json" <<'JSON'
{{"ok": true, "validation_scope": {{"production_validated": true, "target_environment": "production", "operator_asserted": true}}, "checks": []}}
JSON
    cat > "$evidence_dir/redaction-scan.json" <<'JSON'
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )
    assert proc.returncode == 65
    assert (
        "high-confidence secret material found in the production evidence bundle"
        in proc.stderr
    )
    assert redaction_scan["ok"] is False
    assert redaction_scan["findings"][0]["source"].endswith(
        "evidence/redaction-scan.json"
    )
    assert redaction_scan["findings"][0]["kind"] == "jwt"
    assert not (out_root / "summary.json").exists()


def test_capture_production_evidence_fails_if_generated_bundle_contains_symlink(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "production-soak.json"
    out_root = tmp_path / "capture"
    fake_python = tmp_path / "fake-python"
    outside = tmp_path / "outside-generated-artifact.txt"
    outside.write_text("outside generated artifact\n", encoding="utf-8")
    probe = tmp_path / "symlink-probe"
    try:
        probe.symlink_to(outside)
        probe.unlink()
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")
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
    ln -s {json.dumps(str(outside))} "$evidence_dir/escaped-generated-artifact.txt"
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )
    assert proc.returncode == 65
    assert "production evidence bundle contains unscanned files" in proc.stderr
    assert "escaped-generated-artifact.txt" in proc.stderr
    assert redaction_scan["ok"] is False
    assert redaction_scan["findings"] == []
    skipped_symlink = next(
        skipped
        for skipped in redaction_scan["skipped_files"]
        if skipped["path"].endswith("escaped-generated-artifact.txt")
    )
    assert skipped_symlink["reason"] == "symlink not allowed"
    assert not (out_root / "summary.json").exists()
    assert not (out_root / "bundle-manifest.json").exists()


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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
            str(manifest),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "MNEMOSYNE_PYTHON": str(fake_python)},
    )

    redaction_scan = json.loads(
        (out_root / "redaction-scan.json").read_text(encoding="utf-8")
    )
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
            "/bin/bash",
            str(CAPTURE_SCRIPT),
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
    bundle_manifest = json.loads(
        (out_root / "bundle-manifest.json").read_text(encoding="utf-8")
    )
    bundle_paths = {item["path"] for item in bundle_manifest["files"]}

    assert stdout == summary
    assert summary["bundle_manifest"] == str(out_root / "bundle-manifest.json")
    assert summary["bundle_fingerprint"].startswith("sha256:")
    assert summary["offline_verify"] == {
        "bundle_dir": str(out_root),
        "expected_bundle_fingerprint": summary["bundle_fingerprint"],
        "argv": [
            str(fake_python),
            "-m",
            "mnemosyne.cli",
            "production-evidence-verify",
            str(out_root),
            "--expected-bundle-fingerprint",
            summary["bundle_fingerprint"],
        ],
        "note": "Custody review only; does not rerun production checks or flip audit rows.",
    }
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
    assert all(
        item["sha256"].startswith("sha256:") for item in bundle_manifest["files"]
    )
    assert (out_root / "evidence" / "soak-manifest-path.txt").read_text(
        encoding="utf-8"
    ).strip() == str(out_root / "operator-soak-manifest.json")
