from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from mnemosyne.cli import PRODUCTION_RELEASE_REQUIRED_COMMANDS


REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "infra" / "scripts" / "render-production-soak-manifest.sh"
ENV_EXAMPLE = REPO / "infra" / "templates" / "production-render.env.example"
ENV_GUIDE = REPO / ".planning" / "ENV-AND-SECRETS.md"
REQUIRED_PRODUCTION_INPUT_ARTIFACTS = [
    "auth-ops-bundle.json",
    "belief-revision-cases.json",
    "calibration-dataset.json",
    "consolidation-ops-bundle.json",
    "dashboard-package",
    "forgetting-policy-cases.json",
    "hosted-llm-manifest.json",
    "idp-authz-policy-simulation.json",
    "idp-authz-policy.candidate.json",
    "idp-authz-policy.current.json",
    "mcp-ops-bundle.json",
    "multimodal-ops-bundle.json",
    "parametric-trainer-bundle.json",
    "policy-ops-bundle.json",
    "privacy-ops-bundle.json",
    "protected-gate-cases.json",
    "provider-manifest.production.json",
    "provenance-ops-bundle.json",
    "provenance-trust-suite.json",
    "retrieval-ops-bundle.json",
    "tls-candidate.pem",
    "tls-current.pem",
    "tls-lifecycle-bundle.json",
    "worker-ops-bundle.json",
]


def _renderer_base_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "MNEMOSYNE_PYTHON": sys.executable,
    }


def _placeholders() -> list[str]:
    proc = subprocess.run(
        [str(RENDERER), "--list-placeholders"],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    return sorted(payload["placeholders"])


def _filled_render_env(tmp_path: Path) -> dict[str, str]:
    evidence_dir = tmp_path / "production-input-artifacts"
    evidence_dir.mkdir(exist_ok=True)
    c2pa_tool = tmp_path / "bin" / "c2patool"
    c2pa_tool.parent.mkdir(exist_ok=True)
    c2pa_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    c2pa_tool.chmod(0o755)
    values = {
        "MNEMOSYNE_PROD_C2PA_TOOL": str(c2pa_tool),
        "MNEMOSYNE_PROD_CHANGE_TICKET": "CHG-12345",
        "MNEMOSYNE_PROD_DASHBOARD_URL": "https://mnemosyne.example.com/dashboards/ops",
        "MNEMOSYNE_PROD_EVIDENCE_DIR": str(evidence_dir),
        "MNEMOSYNE_PROD_IDP_AUDIENCE": "mnemosyne",
        "MNEMOSYNE_PROD_IDP_ISSUER": "https://idp.example.com/realms/mnemosyne",
        "MNEMOSYNE_PROD_IDP_JWKS_URL": (
            "https://idp.example.com/realms/mnemosyne/protocol/openid-connect/certs"
        ),
        "MNEMOSYNE_PROD_MCP_HTTP_BASE_URL": "https://mnemosyne.example.com/mcp",
        "MNEMOSYNE_PROD_MCP_HTTP_HEALTH_URL": "https://mnemosyne.example.com/mcp/health",
        "MNEMOSYNE_PROD_MCP_HTTP_RPC_URL": "https://mnemosyne.example.com/mcp/rpc",
        "MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_BASE_URL": "https://mnemosyne.example.com/mcp-stream",
        "MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_HEALTH_URL": (
            "https://mnemosyne.example.com/mcp-stream/health"
        ),
        "MNEMOSYNE_PROD_MCP_STREAMABLE_HTTP_URL": "https://mnemosyne.example.com/mcp-stream",
        "MNEMOSYNE_PROD_OPERATOR_NAME": "Production Operator",
        "MNEMOSYNE_PROD_OPERATOR_USER": "operator@example.invalid",
        "MNEMOSYNE_PROD_RECOMPUTE_CID": "cid-production-recompute-probe",
        "MNEMOSYNE_PROD_TENANT": "tenant-prod",
        "MNEMOSYNE_PROD_TLS_HOSTNAME": "mnemosyne.example.com",
        "MNEMOSYNE_PROD_TLS_URL": "https://mnemosyne.example.com",
    }
    env = _renderer_base_env()
    env.update(values)
    return env


def _populate_required_input_artifacts(env: dict[str, str], *, suite_payload: str = '{"cases": []}\n') -> None:
    evidence_dir = Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"])
    for relative_path in REQUIRED_PRODUCTION_INPUT_ARTIFACTS:
        path = evidence_dir / relative_path
        if relative_path == "dashboard-package":
            path.mkdir(parents=True, exist_ok=True)
            (path / "manifest.json").write_text("{}\n", encoding="utf-8")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == "provenance-trust-suite.json":
            path.write_text(suite_payload, encoding="utf-8")
        else:
            path.write_text("{}\n", encoding="utf-8")


def test_renderer_placeholders_match_env_example_and_env_guide() -> None:
    placeholders = _placeholders()
    example_vars = sorted(
        set(re.findall(r"export (MNEMOSYNE_PROD_[A-Z0-9_]+)=", ENV_EXAMPLE.read_text()))
    )
    guide_vars = sorted(set(re.findall(r"`(MNEMOSYNE_PROD_[A-Z0-9_]+)`", ENV_GUIDE.read_text())))

    assert placeholders == example_vars
    assert placeholders == guide_vars


def test_renderer_requires_all_production_env_values(tmp_path: Path) -> None:
    proc = subprocess.run(
        [str(RENDERER), "--output", str(tmp_path / "manifest.json")],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert "missing required production placeholder environment variables" in proc.stderr
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR" in proc.stderr


def test_renderer_check_environment_reports_missing_without_output() -> None:
    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)

    assert proc.returncode == 78
    assert payload["ok"] is False
    assert payload["values_redacted"] is True
    assert payload["blocked_reason"] == "missing_required_environment"
    assert "required_placeholders_present" in payload["validation_categories"]
    assert "external_input_artifact_custody" in payload["validation_categories"]
    assert any("production-render.env.example" in step for step in payload["next_steps"])
    assert any("production-evidence-verify" in step for step in payload["next_steps"])
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR" in payload["missing"]
    assert payload["present"] == []
    assert proc.stderr == ""


def test_renderer_check_environment_passes_without_writing_manifest(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(proc.stdout)

    assert payload["ok"] is True
    assert payload["values_redacted"] is True
    assert payload["evidence_dir_external"] is True
    assert payload["c2pa_tool_external"] is True
    assert payload["missing"] == []
    assert payload["input_artifacts_complete"] is True
    assert "operator_capture_and_offline_verify" in payload["validation_categories"]
    assert any("capture-production-evidence.sh" in step for step in payload["next_steps"])
    assert payload["missing_input_artifacts"] == []
    assert payload["input_artifact_errors"] == []
    assert payload["required_input_artifact_count"] == len(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    assert sorted(payload["required_input_artifacts"]) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    assert sorted(payload["present"]) == _placeholders()
    assert not list(tmp_path.glob("*.json"))


def test_renderer_check_environment_fails_on_missing_input_artifacts(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)

    assert proc.returncode == 78
    assert payload["ok"] is False
    assert payload["blocked_reason"] == "missing_or_invalid_input_artifacts"
    assert payload["input_artifacts_complete"] is False
    assert sorted(payload["missing_input_artifacts"]) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    assert payload["input_artifact_errors"] == []
    assert payload["required_input_artifact_count"] == len(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout
    assert proc.stderr == ""


def test_renderer_check_environment_fails_on_missing_provenance_suite_asset(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    nested_asset = Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"]) / "missing-suite-asset.txt"
    _populate_required_input_artifacts(
        env,
        suite_payload=json.dumps({"cases": [{"asset_path": str(nested_asset)}]}) + "\n",
    )

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)

    assert proc.returncode == 78
    assert payload["ok"] is False
    assert payload["input_artifacts_complete"] is False
    assert "missing-suite-asset.txt" in payload["missing_input_artifacts"]
    assert "missing-suite-asset.txt" in payload["required_input_artifacts"]
    assert payload["input_artifact_errors"] == []
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout
    assert proc.stderr == ""


def test_renderer_check_environment_accepts_provenance_suite_assets(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    evidence_dir = Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"])
    asset = evidence_dir / "suite-asset.txt"
    c2pa_asset = evidence_dir / "suite-c2pa-asset.txt"
    asset.write_text("asset\n", encoding="utf-8")
    c2pa_asset.write_text("c2pa asset\n", encoding="utf-8")
    _populate_required_input_artifacts(
        env,
        suite_payload=json.dumps(
            {
                "cases": [
                    {
                        "asset_path": str(asset),
                        "c2pa_asset_path": str(c2pa_asset),
                    }
                ]
            }
        )
        + "\n",
    )

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(proc.stdout)

    assert payload["ok"] is True
    assert payload["input_artifacts_complete"] is True
    assert payload["missing_input_artifacts"] == []
    assert payload["input_artifact_errors"] == []
    assert "suite-asset.txt" in payload["required_input_artifacts"]
    assert "suite-c2pa-asset.txt" in payload["required_input_artifacts"]
    assert payload["required_input_artifact_count"] == len(REQUIRED_PRODUCTION_INPUT_ARTIFACTS) + 2
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout


def test_renderer_check_environment_rejects_repo_local_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(REPO / "production-input-artifacts")

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR must not point inside the repository" in proc.stderr
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stderr


def test_renderer_check_environment_rejects_relative_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = "production-input-artifacts"

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR must be an absolute external" in proc.stderr
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stderr


def test_renderer_check_environment_rejects_missing_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    missing_dir = tmp_path / "missing-production-input-artifacts"
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(missing_dir)

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR must exist as an external directory" in proc.stderr
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stderr


def test_renderer_check_environment_rejects_relative_c2pa_tool(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = "c2patool"

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "MNEMOSYNE_PROD_C2PA_TOOL must be an absolute external executable path" in proc.stderr
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_check_environment_rejects_non_executable_c2pa_tool(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    tool = tmp_path / "bin" / "not-executable-c2patool"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o600)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = str(tool)

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "MNEMOSYNE_PROD_C2PA_TOOL must be executable" in proc.stderr
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_check_environment_rejects_repo_local_c2pa_tool(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = str(RENDERER)

    proc = subprocess.run(
        [str(RENDERER), "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert proc.stdout == ""
    assert "MNEMOSYNE_PROD_C2PA_TOOL must not point inside the repository" in proc.stderr
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_refuses_repo_local_output() -> None:
    proc = subprocess.run(
        [str(RENDERER), "--output", str(REPO / "production-soak-manifest.json")],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 73
    assert "refusing to write production manifest inside the repository" in proc.stderr


def test_renderer_refuses_repo_local_production_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(REPO / "production-input-artifacts")

    proc = subprocess.run(
        [str(RENDERER), "--output", str(tmp_path / "production-soak-manifest.json")],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR must not point inside the repository" in proc.stderr


def test_renderer_refuses_relative_production_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = "production-input-artifacts"

    proc = subprocess.run(
        [str(RENDERER), "--output", str(tmp_path / "production-soak-manifest.json")],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR must be an absolute external" in proc.stderr


def test_renderer_writes_private_valid_manifest_outside_repo(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    proc = subprocess.run(
        [str(RENDERER), "--output", str(output)],
        cwd=REPO,
        env=_filled_render_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    )

    stdout = json.loads(proc.stdout)
    manifest = json.loads(output.read_text(encoding="utf-8"))

    assert stdout["ok"] is True
    assert stdout["values_redacted"] is True
    assert stdout["placeholder_count"] == len(_placeholders())
    assert stdout["command_count"] == len(PRODUCTION_RELEASE_REQUIRED_COMMANDS)
    assert "MNEMOSYNE_PROD_" not in output.read_text(encoding="utf-8")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700

    scope = manifest["validation_scope"]
    assert scope["production_validated"] is True
    assert scope["target_environment"] == "production"
    assert scope["operator_asserted"] is True
    assert {check["command"] for check in manifest["checks"]} == set(
        PRODUCTION_RELEASE_REQUIRED_COMMANDS
    )
