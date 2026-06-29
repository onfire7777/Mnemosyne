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
RENDERER_CMD = ["/bin/bash", str(RENDERER)]
ENV_EXAMPLE = REPO / "infra" / "templates" / "production-render.env.example"
ENV_GUIDE = REPO / ".planning" / "ENV-AND-SECRETS.md"
REQUIRED_PRODUCTION_INPUT_ARTIFACTS = [
    "auth-ops-bundle.json",
    "belief-revision-cases.json",
    "calibration-dataset.json",
    "consolidation-ops-bundle.json",
    "forgetting-policy-cases.json",
    "hosted-llm-manifest.json",
    "idp-authz-policy-simulation.json",
    "idp-authz-policy.candidate.json",
    "idp-authz-policy.current.json",
    "mcp-ops-bundle.json",
    "multimodal-ops-bundle.json",
    "ops-dashboard-bundle.json",
    "parametric-trainer-bundle.json",
    "policy-ops-bundle.json",
    "privacy-ops-bundle.json",
    "provider-manifest.production.json",
    "provenance-ops-bundle.json",
    "provenance-trust-suite.json",
    "retrieval-ops-bundle.json",
    "row-10-full-suite-evidence.json",
    "tls-candidate.pem",
    "tls-current.pem",
    "tls-lifecycle-bundle.json",
    "worker-ops-bundle.json",
]
REQUIRED_PARITY_LANES = [f"B{index}" for index in range(1, 11)]


def _detail_by_path(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    details = payload["required_input_artifacts_detail"]
    assert isinstance(details, list)
    return {
        str(item["relative_path"]): item for item in details if isinstance(item, dict)
    }


def _row_readiness_by_lane(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = payload["parity_row_readiness"]
    assert isinstance(rows, list)
    return {str(item["lane"]): item for item in rows if isinstance(item, dict)}


def _assert_parity_routes_shape(routes: object) -> None:
    assert isinstance(routes, list)
    assert routes
    for route in routes:
        assert isinstance(route, dict)
        assert set(route) == {"lane", "row", "title", "runbook"}
        assert isinstance(route["lane"], str)
        assert route["lane"].startswith("B")
        assert isinstance(route["row"], int)
        assert 1 <= route["row"] <= 10
        assert isinstance(route["title"], str)
        assert route["title"]
        assert isinstance(route["runbook"], str)
        assert route["runbook"].startswith(".planning/runbooks/row-")


def _assert_row_readiness_shape(item: dict[str, object], *, has_exists: bool) -> None:
    expected_keys = {
        "lane",
        "row",
        "title",
        "runbook",
        "required_input_artifacts",
        "required_input_artifact_count",
        "checks",
    }
    if has_exists:
        expected_keys |= {
            "missing_input_artifacts",
            "input_artifact_errors",
            "input_artifacts_complete",
        }
    assert set(item) == expected_keys
    assert isinstance(item["lane"], str)
    assert item["lane"].startswith("B")
    assert isinstance(item["row"], int)
    assert 1 <= item["row"] <= 10
    assert isinstance(item["title"], str)
    assert item["title"]
    assert isinstance(item["runbook"], str)
    assert item["runbook"].startswith(".planning/runbooks/row-")
    assert isinstance(item["required_input_artifacts"], list)
    assert item["required_input_artifacts"]
    assert item["required_input_artifact_count"] == len(
        item["required_input_artifacts"]
    )
    assert all(isinstance(path, str) for path in item["required_input_artifacts"])
    assert all(
        not Path(path).is_absolute() for path in item["required_input_artifacts"]
    )
    assert isinstance(item["checks"], list)
    assert item["checks"]
    for check in item["checks"]:
        assert isinstance(check, dict)
        assert set(check) == {"name", "command", "option"}
        assert all(isinstance(check[key], str) for key in ("name", "command", "option"))
    if has_exists:
        assert isinstance(item["missing_input_artifacts"], list)
        assert all(isinstance(path, str) for path in item["missing_input_artifacts"])
        assert all(
            not Path(path).is_absolute() for path in item["missing_input_artifacts"]
        )
        assert isinstance(item["input_artifact_errors"], list)
        assert all(isinstance(error, str) for error in item["input_artifact_errors"])
        assert isinstance(item["input_artifacts_complete"], bool)


def _assert_artifact_detail_shape(item: dict[str, object]) -> None:
    assert set(item) == {"relative_path", "checks", "exists", "parity_routes"}
    assert isinstance(item["relative_path"], str)
    assert item["relative_path"]
    assert not Path(item["relative_path"]).is_absolute()
    assert isinstance(item["exists"], bool)
    _assert_parity_routes_shape(item["parity_routes"])
    assert isinstance(item["checks"], list)
    assert item["checks"]
    for check in item["checks"]:
        assert isinstance(check, dict)
        assert set(check) == {"name", "command", "option", "parity_lanes"}
        assert all(isinstance(check[key], str) for key in ("name", "command", "option"))
        assert isinstance(check["parity_lanes"], list)
        assert check["parity_lanes"]
        assert all(
            isinstance(lane, str) and lane.startswith("B")
            for lane in check["parity_lanes"]
        )


def _assert_artifact_plan_shape(item: dict[str, object]) -> None:
    assert set(item) == {"relative_path", "checks", "parity_routes"}
    assert isinstance(item["relative_path"], str)
    assert item["relative_path"]
    assert not Path(item["relative_path"]).is_absolute()
    _assert_parity_routes_shape(item["parity_routes"])
    assert isinstance(item["checks"], list)
    assert item["checks"]
    for check in item["checks"]:
        assert isinstance(check, dict)
        assert set(check) == {"name", "command", "option", "parity_lanes"}
        assert all(isinstance(check[key], str) for key in ("name", "command", "option"))
        assert isinstance(check["parity_lanes"], list)
        assert check["parity_lanes"]
        assert all(
            isinstance(lane, str) and lane.startswith("B")
            for lane in check["parity_lanes"]
        )


def _assert_check_environment_value_error(
    proc: subprocess.CompletedProcess[str],
    *,
    name: str,
    code: str,
    message_fragment: str,
    redacted_value: str,
) -> dict[str, object]:
    assert proc.returncode == 78
    assert proc.stderr == ""
    payload = json.loads(proc.stdout)
    if Path(redacted_value).is_absolute():
        assert redacted_value not in proc.stdout
    assert payload["ok"] is False
    assert payload["blocked_reason"] == "invalid_required_environment"
    assert payload["values_redacted"] is True
    assert payload["missing"] == []
    assert payload["required_input_artifact_count"] == len(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert sorted(payload["required_input_artifacts"]) == sorted(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert payload["environment_errors"] == [
        {
            "name": name,
            "code": code,
            "message": message_fragment,
        }
    ]
    assert redacted_value not in json.dumps(payload["environment_errors"])
    return payload


def _renderer_base_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "MNEMOSYNE_PYTHON": sys.executable,
    }


def _placeholders() -> list[str]:
    proc = subprocess.run(
        [*RENDERER_CMD, "--list-placeholders"],
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


def _populate_required_input_artifacts(
    env: dict[str, str], *, suite_payload: str = '{"cases": []}\n'
) -> None:
    evidence_dir = Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"])
    for relative_path in REQUIRED_PRODUCTION_INPUT_ARTIFACTS:
        path = evidence_dir / relative_path
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
    guide_vars = sorted(
        set(re.findall(r"`(MNEMOSYNE_PROD_[A-Z0-9_]+)`", ENV_GUIDE.read_text()))
    )

    assert placeholders == example_vars
    assert placeholders == guide_vars


def test_renderer_list_placeholders_includes_static_artifact_inventory() -> None:
    proc = subprocess.run(
        [*RENDERER_CMD, "--list-placeholders"],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout)

    assert payload["required_input_artifact_count"] == len(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert sorted(payload["required_input_artifacts"]) == sorted(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    plan_by_path = {
        str(item["relative_path"]): item
        for item in payload["required_input_artifacts_plan"]
        if isinstance(item, dict)
    }
    assert sorted(plan_by_path) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    for item in plan_by_path.values():
        _assert_artifact_plan_shape(item)
    rows = _row_readiness_by_lane(payload)
    assert set(rows) == set(REQUIRED_PARITY_LANES)
    for lane in REQUIRED_PARITY_LANES:
        _assert_row_readiness_shape(rows[lane], has_exists=False)
        assert rows[lane]["row"] == int(lane.removeprefix("B"))
        assert "missing_input_artifacts" not in rows[lane]
    assert plan_by_path["row-10-full-suite-evidence.json"]["parity_routes"] == [
        {
            "lane": "B10",
            "row": 10,
            "title": "Live parity suite",
            "runbook": ".planning/runbooks/row-10-live-parity-suite.md",
        }
    ]
    assert "row-10-full-suite-evidence.json" in rows["B10"]["required_input_artifacts"]
    assert rows["B10"]["runbook"] == ".planning/runbooks/row-10-live-parity-suite.md"


def test_renderer_requires_all_production_env_values(tmp_path: Path) -> None:
    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(tmp_path / "manifest.json")],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert (
        "missing required production placeholder environment variables" in proc.stderr
    )
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR" in proc.stderr


def test_renderer_check_environment_reports_missing_without_output() -> None:
    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
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
    assert any(
        "production-render.env.example" in step for step in payload["next_steps"]
    )
    assert any("production-evidence-verify" in step for step in payload["next_steps"])
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR" in payload["missing"]
    assert payload["present"] == []
    assert payload["operator_readiness_files"] == {
        "env_template": "infra/templates/production-render.env.example",
        "input_artifacts_checklist": "infra/templates/production-input-artifacts.checklist.md",
        "production_evidence_runbook": "infra/PRODUCTION-EVIDENCE.md",
    }
    assert payload["required_input_artifact_count"] == len(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert sorted(payload["required_input_artifacts"]) == sorted(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    plan_by_path = {
        str(item["relative_path"]): item
        for item in payload["required_input_artifacts_plan"]
        if isinstance(item, dict)
    }
    assert sorted(plan_by_path) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    for item in plan_by_path.values():
        _assert_artifact_plan_shape(item)
        assert "exists" not in item
    rows = _row_readiness_by_lane(payload)
    assert set(rows) == set(REQUIRED_PARITY_LANES)
    for lane in REQUIRED_PARITY_LANES:
        _assert_row_readiness_shape(rows[lane], has_exists=False)
        assert "input_artifacts_complete" not in rows[lane]
    assert {
        "name": "belief-revision",
        "command": "belief-revision-check",
        "option": "input_artifacts[0]",
        "parity_lanes": ["B10"],
    } in plan_by_path["row-10-full-suite-evidence.json"]["checks"]
    assert proc.stderr == ""


def test_renderer_check_environment_passes_without_writing_manifest(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
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
    assert any(
        "capture-production-evidence.sh" in step for step in payload["next_steps"]
    )
    assert payload["missing_input_artifacts"] == []
    assert payload["missing_input_artifacts_detail"] == []
    assert payload["input_artifact_errors"] == []
    assert payload["required_input_artifact_count"] == len(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert sorted(payload["required_input_artifacts"]) == sorted(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    details = _detail_by_path(payload)
    assert sorted(details) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    for detail in details.values():
        _assert_artifact_detail_shape(detail)
        assert detail["exists"] is True
    rows = _row_readiness_by_lane(payload)
    assert set(rows) == set(REQUIRED_PARITY_LANES)
    for lane in REQUIRED_PARITY_LANES:
        _assert_row_readiness_shape(rows[lane], has_exists=True)
        assert rows[lane]["input_artifacts_complete"] is True
        assert rows[lane]["missing_input_artifacts"] == []
        assert rows[lane]["input_artifact_errors"] == []
    assert {
        "name": "belief-revision",
        "command": "belief-revision-check",
        "option": "input_artifacts[0]",
        "parity_lanes": ["B10"],
    } in details["row-10-full-suite-evidence.json"]["checks"]
    assert details["provider-manifest.production.json"]["parity_routes"] == [
        {
            "lane": "B1",
            "row": 1,
            "title": "Production Postgres retrieval",
            "runbook": ".planning/runbooks/row-01-production-postgres-retrieval.md",
        },
        {
            "lane": "B4",
            "row": 4,
            "title": "Consolidation role pipeline",
            "runbook": ".planning/runbooks/row-04-consolidation-role-pipeline.md",
        },
        {
            "lane": "B6",
            "row": 6,
            "title": "Multimodal retrieval",
            "runbook": ".planning/runbooks/row-06-multimodal-retrieval.md",
        },
        {
            "lane": "B9",
            "row": 9,
            "title": "Parametric tier",
            "runbook": ".planning/runbooks/row-09-parametric-tier.md",
        },
        {
            "lane": "B10",
            "row": 10,
            "title": "Live parity suite",
            "runbook": ".planning/runbooks/row-10-live-parity-suite.md",
        },
    ]
    assert sorted(payload["present"]) == _placeholders()
    assert not list(tmp_path.glob("*.json"))


def test_renderer_check_environment_fails_on_missing_input_artifacts(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
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
    assert sorted(payload["missing_input_artifacts"]) == sorted(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert payload["input_artifact_errors"] == []
    assert payload["required_input_artifact_count"] == len(
        REQUIRED_PRODUCTION_INPUT_ARTIFACTS
    )
    assert sorted(
        item["relative_path"] for item in payload["missing_input_artifacts_detail"]
    ) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    details = _detail_by_path(payload)
    assert sorted(details) == sorted(REQUIRED_PRODUCTION_INPUT_ARTIFACTS)
    for detail in details.values():
        _assert_artifact_detail_shape(detail)
        assert detail["exists"] is False
    rows = _row_readiness_by_lane(payload)
    assert set(rows) == set(REQUIRED_PARITY_LANES)
    for lane in REQUIRED_PARITY_LANES:
        _assert_row_readiness_shape(rows[lane], has_exists=True)
        assert rows[lane]["input_artifacts_complete"] is False
        assert rows[lane]["missing_input_artifacts"]
        assert rows[lane]["input_artifact_errors"] == []
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout
    assert proc.stderr == ""


def test_renderer_check_environment_row_readiness_scopes_single_missing_artifact(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    (Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"]) / "auth-ops-bundle.json").unlink()

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)

    assert proc.returncode == 78
    assert payload["ok"] is False
    rows = _row_readiness_by_lane(payload)
    assert set(rows) == set(REQUIRED_PARITY_LANES)
    for lane in REQUIRED_PARITY_LANES:
        _assert_row_readiness_shape(rows[lane], has_exists=True)
    assert rows["B2"]["missing_input_artifacts"] == ["auth-ops-bundle.json"]
    assert rows["B2"]["input_artifacts_complete"] is False
    for lane in set(REQUIRED_PARITY_LANES) - {"B2"}:
        assert rows[lane]["missing_input_artifacts"] == []
        assert rows[lane]["input_artifact_errors"] == []
        assert rows[lane]["input_artifacts_complete"] is True
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout


def test_renderer_check_environment_row_readiness_scopes_shared_provider_artifact(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    shared_artifact = "provider-manifest.production.json"
    (Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"]) / shared_artifact).unlink()

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(proc.stdout)

    assert proc.returncode == 78
    assert payload["ok"] is False
    rows = _row_readiness_by_lane(payload)
    missing_lanes = {"B1", "B4", "B6", "B9", "B10"}
    assert set(rows) == set(REQUIRED_PARITY_LANES)
    for lane in REQUIRED_PARITY_LANES:
        _assert_row_readiness_shape(rows[lane], has_exists=True)
        if lane in missing_lanes:
            assert rows[lane]["missing_input_artifacts"] == [shared_artifact]
            assert rows[lane]["input_artifacts_complete"] is False
        else:
            assert rows[lane]["missing_input_artifacts"] == []
            assert rows[lane]["input_artifacts_complete"] is True
        assert rows[lane]["input_artifact_errors"] == []
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout


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
        [*RENDERER_CMD, "--check-environment"],
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
    detail = _detail_by_path(payload)["missing-suite-asset.txt"]
    _assert_artifact_detail_shape(detail)
    assert detail["exists"] is False
    assert {
        "name": "provenance-trust",
        "command": "provenance-trust-check",
        "option": "cases[0].asset_path",
        "parity_lanes": ["B5"],
    } in detail["checks"]
    assert payload["missing_input_artifacts_detail"] == [detail]
    assert payload["input_artifact_errors"] == []
    rows = _row_readiness_by_lane(payload)
    _assert_row_readiness_shape(rows["B5"], has_exists=True)
    assert rows["B5"]["missing_input_artifacts"] == ["missing-suite-asset.txt"]
    assert rows["B5"]["input_artifact_errors"] == []
    assert rows["B5"]["input_artifacts_complete"] is False
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout
    assert proc.stderr == ""


def test_renderer_check_environment_fails_on_invalid_provenance_suite_asset_path(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    outside_asset = tmp_path / "outside-suite-asset.txt"
    outside_asset.write_text("asset\n", encoding="utf-8")
    _populate_required_input_artifacts(
        env,
        suite_payload=json.dumps({"cases": [{"asset_path": str(outside_asset)}]})
        + "\n",
    )

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
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
    assert payload["missing_input_artifacts"] == []
    assert payload["missing_input_artifacts_detail"] == []
    assert payload["input_artifact_errors"] == [
        "provenance-trust-suite.json cases[0].asset_path must live under "
        "MNEMOSYNE_PROD_EVIDENCE_DIR"
    ]
    rows = _row_readiness_by_lane(payload)
    _assert_row_readiness_shape(rows["B5"], has_exists=True)
    assert rows["B5"]["missing_input_artifacts"] == []
    assert rows["B5"]["input_artifact_errors"] == payload["input_artifact_errors"]
    assert rows["B5"]["input_artifacts_complete"] is False
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout
    assert proc.stderr == ""


def test_renderer_check_environment_rejects_escaped_manifest_artifact_path(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    outside_artifact = (
        Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"]).parent / "outside-auth-ops-bundle.json"
    )
    outside_artifact.write_text("{}\n", encoding="utf-8")
    template = tmp_path / "production-soak-manifest.template.json"
    template.write_text(
        (REPO / "infra" / "templates" / "production-soak-manifest.template.json")
        .read_text(encoding="utf-8")
        .replace(
            "MNEMOSYNE_PROD_EVIDENCE_DIR/auth-ops-bundle.json",
            "MNEMOSYNE_PROD_EVIDENCE_DIR/../outside-auth-ops-bundle.json",
            1,
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment", "--template", str(template)],
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
    assert any(
        "must not contain '..' path segments" in error
        for error in payload["input_artifact_errors"]
    )


def test_renderer_check_environment_rejects_escaped_provenance_suite_asset_path(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    evidence_dir = Path(env["MNEMOSYNE_PROD_EVIDENCE_DIR"])
    outside_asset = evidence_dir.parent / "outside-suite-asset.txt"
    outside_asset.write_text("asset\n", encoding="utf-8")
    _populate_required_input_artifacts(
        env,
        suite_payload=json.dumps(
            {"cases": [{"asset_path": str(evidence_dir / ".." / outside_asset.name)}]}
        )
        + "\n",
    )

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
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
    assert payload["input_artifact_errors"] == [
        "provenance-trust-suite.json cases[0].asset_path must not contain '..' path segments"
    ]
    rows = _row_readiness_by_lane(payload)
    _assert_row_readiness_shape(rows["B5"], has_exists=True)
    assert rows["B5"]["missing_input_artifacts"] == []
    assert rows["B5"]["input_artifact_errors"] == payload["input_artifact_errors"]
    assert rows["B5"]["input_artifacts_complete"] is False


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
        [*RENDERER_CMD, "--check-environment"],
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
    details = _detail_by_path(payload)
    for relative_path, option in (
        ("suite-asset.txt", "cases[0].asset_path"),
        ("suite-c2pa-asset.txt", "cases[0].c2pa_asset_path"),
    ):
        detail = details[relative_path]
        _assert_artifact_detail_shape(detail)
        assert detail["exists"] is True
        assert {
            "name": "provenance-trust",
            "command": "provenance-trust-check",
            "option": option,
            "parity_lanes": ["B5"],
        } in detail["checks"]
    rows = _row_readiness_by_lane(payload)
    _assert_row_readiness_shape(rows["B5"], has_exists=True)
    assert rows["B5"]["input_artifacts_complete"] is True
    assert rows["B5"]["missing_input_artifacts"] == []
    assert rows["B5"]["input_artifact_errors"] == []
    assert "suite-asset.txt" in rows["B5"]["required_input_artifacts"]
    assert "suite-c2pa-asset.txt" in rows["B5"]["required_input_artifacts"]
    assert (
        payload["required_input_artifact_count"]
        == len(REQUIRED_PRODUCTION_INPUT_ARTIFACTS) + 2
    )
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stdout
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stdout


def test_renderer_check_environment_rejects_repo_local_input_dir(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(REPO / "production-input-artifacts")

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    _assert_check_environment_value_error(
        proc,
        name="MNEMOSYNE_PROD_EVIDENCE_DIR",
        code="evidence_dir_repo_local",
        message_fragment="MNEMOSYNE_PROD_EVIDENCE_DIR must not point inside the repository",
        redacted_value=env["MNEMOSYNE_PROD_EVIDENCE_DIR"],
    )


def test_renderer_check_environment_rejects_relative_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = "production-input-artifacts"

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    _assert_check_environment_value_error(
        proc,
        name="MNEMOSYNE_PROD_EVIDENCE_DIR",
        code="evidence_dir_not_absolute",
        message_fragment="MNEMOSYNE_PROD_EVIDENCE_DIR must be an absolute external production input-artifact path",
        redacted_value=env["MNEMOSYNE_PROD_EVIDENCE_DIR"],
    )


def test_renderer_check_environment_rejects_missing_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    missing_dir = tmp_path / "missing-production-input-artifacts"
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(missing_dir)

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    _assert_check_environment_value_error(
        proc,
        name="MNEMOSYNE_PROD_EVIDENCE_DIR",
        code="evidence_dir_missing",
        message_fragment=(
            "MNEMOSYNE_PROD_EVIDENCE_DIR must exist as an external directory "
            "before --check-environment can pass"
        ),
        redacted_value=env["MNEMOSYNE_PROD_EVIDENCE_DIR"],
    )


def test_renderer_check_environment_rejects_relative_c2pa_tool(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = "c2patool"

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    _assert_check_environment_value_error(
        proc,
        name="MNEMOSYNE_PROD_C2PA_TOOL",
        code="c2pa_tool_not_absolute",
        message_fragment="MNEMOSYNE_PROD_C2PA_TOOL must be an absolute external executable path",
        redacted_value=env["MNEMOSYNE_PROD_C2PA_TOOL"],
    )


def test_renderer_output_rejects_relative_c2pa_tool(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = "c2patool"

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert not output.exists()
    assert (
        "MNEMOSYNE_PROD_C2PA_TOOL must be an absolute external executable path"
        in proc.stderr
    )
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_check_environment_rejects_non_executable_c2pa_tool(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    tool = tmp_path / "bin" / "not-executable-c2patool"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o600)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = str(tool)

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    _assert_check_environment_value_error(
        proc,
        name="MNEMOSYNE_PROD_C2PA_TOOL",
        code="c2pa_tool_not_executable",
        message_fragment="MNEMOSYNE_PROD_C2PA_TOOL must be executable",
        redacted_value=env["MNEMOSYNE_PROD_C2PA_TOOL"],
    )


def test_renderer_output_rejects_non_executable_c2pa_tool(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    tool = tmp_path / "bin" / "not-executable-c2patool"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o600)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = str(tool)

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert not output.exists()
    assert "MNEMOSYNE_PROD_C2PA_TOOL must be executable" in proc.stderr
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_check_environment_rejects_repo_local_c2pa_tool(
    tmp_path: Path,
) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = str(RENDERER)

    proc = subprocess.run(
        [*RENDERER_CMD, "--check-environment"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    _assert_check_environment_value_error(
        proc,
        name="MNEMOSYNE_PROD_C2PA_TOOL",
        code="c2pa_tool_repo_local",
        message_fragment="MNEMOSYNE_PROD_C2PA_TOOL must not point inside the repository",
        redacted_value=env["MNEMOSYNE_PROD_C2PA_TOOL"],
    )


def test_renderer_output_rejects_repo_local_c2pa_tool(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    env["MNEMOSYNE_PROD_C2PA_TOOL"] = str(RENDERER)

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert not output.exists()
    assert (
        "MNEMOSYNE_PROD_C2PA_TOOL must not point inside the repository" in proc.stderr
    )
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_refuses_repo_local_output() -> None:
    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(REPO / "production-soak-manifest.json")],
        cwd=REPO,
        env=_renderer_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 73
    assert "refusing to write production manifest inside the repository" in proc.stderr


def test_renderer_refuses_relative_output(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", "production-soak-manifest.json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 73
    assert "output must be an absolute external custody path" in proc.stderr


def test_renderer_rejects_secret_bearing_manifest_args(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    template = tmp_path / "production-soak-manifest.template.json"
    payload = json.loads(
        (
            REPO / "infra" / "templates" / "production-soak-manifest.template.json"
        ).read_text(encoding="utf-8")
    )
    payload["checks"][0]["global_args"] = ["--postgres-dsn", "postgresql://db/prod"]
    template.write_text(json.dumps(payload), encoding="utf-8")

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output), "--template", str(template)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert not output.exists()
    assert "secret-bearing option --postgres-dsn" in proc.stderr


def test_renderer_rejects_token_suffix_manifest_args(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)
    template = tmp_path / "production-soak-manifest.template.json"
    payload = json.loads(
        (
            REPO / "infra" / "templates" / "production-soak-manifest.template.json"
        ).read_text(encoding="utf-8")
    )
    payload["checks"][0]["args"] = ["--github-token", "from-env-instead"]
    template.write_text(json.dumps(payload), encoding="utf-8")

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output), "--template", str(template)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert not output.exists()
    assert "secret-bearing option --github-token" in proc.stderr


def test_renderer_refuses_repo_local_production_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = str(REPO / "production-input-artifacts")

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(tmp_path / "production-soak-manifest.json")],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert (
        "MNEMOSYNE_PROD_EVIDENCE_DIR must not point inside the repository"
        in proc.stderr
    )


def test_renderer_refuses_relative_production_input_dir(tmp_path: Path) -> None:
    env = _filled_render_env(tmp_path)
    env["MNEMOSYNE_PROD_EVIDENCE_DIR"] = "production-input-artifacts"

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(tmp_path / "production-soak-manifest.json")],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR must be an absolute external" in proc.stderr


def test_renderer_output_fails_on_missing_input_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 78
    assert not output.exists()
    assert "refusing to write production soak manifest" in proc.stderr
    assert "missing input artifact: retrieval-ops-bundle.json" in proc.stderr
    assert env["MNEMOSYNE_PROD_EVIDENCE_DIR"] not in proc.stderr
    assert env["MNEMOSYNE_PROD_C2PA_TOOL"] not in proc.stderr


def test_renderer_writes_private_valid_manifest_outside_repo(tmp_path: Path) -> None:
    output = tmp_path / "secure" / "production-soak-manifest.json"
    env = _filled_render_env(tmp_path)
    _populate_required_input_artifacts(env)

    proc = subprocess.run(
        [*RENDERER_CMD, "--output", str(output)],
        cwd=REPO,
        env=env,
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
    flattened_tokens = [
        token
        for check in manifest["checks"]
        for field in ("global_args", "args")
        for token in check.get(field, [])
    ]
    assert "--runtime-state" not in flattened_tokens
    gate_suite = next(
        check for check in manifest["checks"] if check["command"] == "gate-suite-check"
    )
    assert gate_suite["global_args"] == [
        "--backend",
        "postgres",
        "--queue-tenant",
        env["MNEMOSYNE_PROD_TENANT"],
    ]
    assert gate_suite["args"] == [
        "--include-cases",
        "--min-cases",
        "30",
        "--min-protected",
        "20",
    ]
    worker_run = next(
        check for check in manifest["checks"] if check["command"] == "worker-run"
    )
    assert worker_run["global_args"] == [
        "--backend",
        "postgres",
        "--queue-backend",
        "postgres",
        "--queue-tenant",
        env["MNEMOSYNE_PROD_TENANT"],
    ]
    ops_dashboard = next(
        check
        for check in manifest["checks"]
        if check["command"] == "ops-dashboard-check"
    )
    assert "--dashboard-url" in ops_dashboard["args"]
    assert "--ops-bundle" in ops_dashboard["args"]
    assert (
        f"{env['MNEMOSYNE_PROD_EVIDENCE_DIR']}/ops-dashboard-bundle.json"
        in ops_dashboard["args"]
    )
    assert "--dashboard-package-dir" not in ops_dashboard["args"]
    ops_report = next(
        check for check in manifest["checks"] if check["command"] == "ops-report"
    )
    assert ops_report["args"] == ["--tenant", env["MNEMOSYNE_PROD_TENANT"]]
