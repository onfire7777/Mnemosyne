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
    values = {
        "MNEMOSYNE_PROD_C2PA_TOOL": "c2patool",
        "MNEMOSYNE_PROD_CHANGE_TICKET": "CHG-12345",
        "MNEMOSYNE_PROD_DASHBOARD_URL": "https://mnemosyne.example.com/dashboards/ops",
        "MNEMOSYNE_PROD_EVIDENCE_DIR": str(tmp_path / "production-input-artifacts"),
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
