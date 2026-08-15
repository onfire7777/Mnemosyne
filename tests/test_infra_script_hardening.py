from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_posix_only = pytest.mark.skipif(os.name == "nt", reason="requires POSIX execution, mode bits, or symlink semantics")


REPO = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def _load_prepare_custody_module():
    module_path = REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"
    spec = importlib.util.spec_from_file_location(
        "prepare_production_evidence_custody",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_and_local_evidence_capture_reject_repo_local_outputs() -> None:
    production = _read("infra/scripts/capture-production-evidence.sh")
    local = _read("infra/scripts/capture-local-evidence.sh")
    keycloak_validate = _read("infra/validate/validate-keycloak.sh")
    vault_validate = _read("infra/validate/validate-vault.sh")
    c2pa_validate = _read("infra/validate/validate-c2pa.sh")

    assert "umask 077" in production
    assert "refusing to write production evidence inside the repository" in production
    assert "out_root.chmod(0o700)" in production
    assert "--fingerprint-record-output PATH SOAK_MANIFEST OUT_ROOT" in production
    assert "Required for full capture" in production
    assert "full production capture requires --fingerprint-record-output" in production

    assert "umask 077" in local
    assert "refusing to write local-staging evidence inside the repository" in local
    assert "local-staging evidence output root cannot be a symlink" in local
    assert "local-staging evidence output root must not already exist" in local
    assert 'chmod 700 "${OUT_ROOT}"' in local
    assert 'source "${INFRA_DIR}/keycloak/out/oidc.env"' not in local
    assert 'source "${INFRA_DIR}/vault/out/vault.env"' not in local
    assert 'source "${INFRA_DIR}/c2pa/out/provenance.env"' not in local
    assert "scripts/load-env.py" in local
    assert "scripts/load-env.py" in keycloak_validate
    assert "scripts/load-env.py" in vault_validate
    assert "scripts/load-env.py" in c2pa_validate


@_posix_only
def test_strict_env_loader_rejects_unexpected_keys_and_executable_values(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "unsafe.env"
    env_file.write_text(
        'export SAFE_KEY="ok"\nexport EVIL="$(touch /tmp/mnemosyne-pwned)"\n',
        encoding="utf-8",
    )
    env_file.chmod(0o600)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "load-env.py"),
            str(env_file),
            "SAFE_KEY",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "unsafe dotenv value for EVIL" in proc.stderr


@_posix_only
def test_strict_env_loader_rejects_unexpected_keys(tmp_path: Path) -> None:
    env_file = tmp_path / "unexpected.env"
    env_file.write_text('export SAFE_KEY="ok"\nexport EXTRA="nope"\n', encoding="utf-8")
    env_file.chmod(0o600)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "load-env.py"),
            str(env_file),
            "SAFE_KEY",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "unexpected dotenv key 'EXTRA'" in proc.stderr


@_posix_only
def test_strict_env_loader_rejects_group_accessible_files(tmp_path: Path) -> None:
    env_file = tmp_path / "group-readable.env"
    env_file.write_text('export SAFE_KEY="ok"\n', encoding="utf-8")
    env_file.chmod(0o640)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "load-env.py"),
            str(env_file),
            "SAFE_KEY",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "must not be group/world accessible" in proc.stderr


@_posix_only
def test_strict_env_loader_emits_allowlisted_assignments(tmp_path: Path) -> None:
    env_file = tmp_path / "safe.env"
    env_file.write_text('export SAFE_KEY="ok value"\nexport SECOND="two"\n', encoding="utf-8")
    env_file.chmod(0o600)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "load-env.py"),
            str(env_file),
            "SAFE_KEY",
            "SECOND",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    assert proc.stdout.splitlines() == ["SAFE_KEY=ok value", "SECOND=two"]


@_posix_only
def test_strict_env_loader_allow_missing_emits_present_allowed_keys(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "safe-optional.env"
    env_file.write_text('export SAFE_KEY="ok value"\n', encoding="utf-8")
    env_file.chmod(0o600)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "load-env.py"),
            "--allow-missing",
            str(env_file),
            "SAFE_KEY",
            "MISSING_KEY",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    assert proc.stdout.splitlines() == ["SAFE_KEY=ok value"]


@_posix_only
def test_capture_local_evidence_rejects_existing_output_root(tmp_path: Path) -> None:
    out_root = tmp_path / "existing-local-capture"
    out_root.mkdir()

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-local-evidence.sh"),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "local-staging evidence output root must not already exist" in proc.stderr
    assert not (out_root / "manifest.json").exists()


@_posix_only
def test_capture_local_evidence_rejects_symlinked_output_root(tmp_path: Path) -> None:
    target_root = tmp_path / "real-local-capture"
    out_root = tmp_path / "linked-local-capture"
    target_root.mkdir()
    try:
        out_root.symlink_to(target_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "capture-local-evidence.sh"),
            str(out_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "local-staging evidence output root cannot be a symlink" in proc.stderr
    assert not (target_root / "manifest.json").exists()


@_posix_only
def test_prepare_production_evidence_custody_writes_external_gap_packet(
    tmp_path: Path,
) -> None:
    packet_root = tmp_path / "mnemosyne-tier-b-packet"

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    summary = json.loads(proc.stdout)
    report_path = packet_root / "reports" / "tier-b-gap-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    next_commands_script = packet_root / "reports" / "next-commands.sh"
    artifact_worklist_markdown = (
        packet_root / "reports" / "input-artifact-worklist.md"
    )
    artifact_worklist_json = (
        packet_root / "reports" / "input-artifact-worklist.json"
    )
    artifact_contracts_markdown = (
        packet_root / "reports" / "input-artifact-contracts.md"
    )
    artifact_contracts_json = (
        packet_root / "reports" / "input-artifact-contracts.json"
    )
    provider_env_action_plan_markdown = (
        packet_root / "reports" / "provider-env-action-plan.md"
    )
    provider_env_action_plan_json = (
        packet_root / "reports" / "provider-env-action-plan.json"
    )
    render_env_action_plan_markdown = (
        packet_root / "reports" / "render-env-action-plan.md"
    )
    render_env_action_plan_json = (
        packet_root / "reports" / "render-env-action-plan.json"
    )
    row_action_plan_markdown = packet_root / "reports" / "row-action-plan.md"
    row_action_plan_json = packet_root / "reports" / "row-action-plan.json"
    artifact_validation_script = (
        packet_root / "reports" / "input-artifact-validation-commands.sh"
    )

    assert proc.returncode == 78
    assert summary["ok"] is False
    assert summary["ready_for_capture"] is False
    assert summary["report"] == str(report_path)
    assert summary["post_capture_verify_report"] == report["post_capture_verify_report"]
    assert summary["next_commands_script"] == str(next_commands_script)
    assert summary["input_artifact_worklist"] == str(artifact_worklist_markdown)
    assert summary["input_artifact_contracts"] == str(artifact_contracts_markdown)
    assert summary["provider_env_action_plan"] == str(
        provider_env_action_plan_markdown
    )
    assert summary["render_env_action_plan"] == str(render_env_action_plan_markdown)
    assert summary["row_action_plan"] == str(row_action_plan_markdown)
    assert summary["input_artifact_validation_script"] == str(
        artifact_validation_script
    )
    assert summary["runtime_env_file_placeholder"] == (
        "/secure/path/to/mnemosyne-production-runtime.env"
    )
    assert summary["runtime_env_example"] == str(
        packet_root / "reports" / "mnemosyne-production-runtime.env.example"
    )
    assert "external runtime env file provider refs" in summary["next"]
    assert "runtime_env_example" in summary["next"]
    assert report["schema"] == "mnemosyne.tier-b-custody-gap-report.v1"
    assert report["report_is_evidence"] is False
    assert report["ready_for_capture"] is False
    assert report["packet_docs_complete"] is True
    assert report["packet_docs_added"] == []
    assert report["packet_docs_missing"] == []
    assert len(report["missing_render_environment"]) == 19
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR" not in report["missing_render_environment"]
    assert "MNEMOSYNE_EMBEDDING_URL" in report["missing_provider_manifest_env_refs"]
    assert report["missing_input_artifact_count"] == 23
    assert "provider-manifest.production.json" not in report["missing_input_artifacts"]
    assert report["input_artifact_worklist_markdown"] == str(artifact_worklist_markdown)
    assert report["input_artifact_worklist_json"] == str(artifact_worklist_json)
    assert report["input_artifact_contracts_markdown"] == str(
        artifact_contracts_markdown
    )
    assert report["input_artifact_contracts_json"] == str(artifact_contracts_json)
    assert report["provider_env_action_plan_markdown"] == str(
        provider_env_action_plan_markdown
    )
    assert report["provider_env_action_plan_json"] == str(
        provider_env_action_plan_json
    )
    assert report["render_env_action_plan_markdown"] == str(
        render_env_action_plan_markdown
    )
    assert report["render_env_action_plan_json"] == str(render_env_action_plan_json)
    assert report["row_action_plan_markdown"] == str(row_action_plan_markdown)
    assert report["row_action_plan_json"] == str(row_action_plan_json)
    assert report["input_artifact_validation_script"] == str(
        artifact_validation_script
    )
    artifact_worklist = {
        item["relative_path"]: item for item in report["input_artifact_worklist"]
    }
    assert len(artifact_worklist) == 24
    assert artifact_worklist["provider-manifest.production.json"]["status"] == "present"
    assert artifact_worklist["provider-manifest.production.json"]["present"] is True
    assert artifact_worklist["retrieval-ops-bundle.json"]["status"] == "missing"
    assert artifact_worklist["retrieval-ops-bundle.json"]["present"] is False
    assert artifact_worklist["retrieval-ops-bundle.json"]["rows"][0]["lane"] == "B1"
    assert artifact_worklist["retrieval-ops-bundle.json"]["rows"][0]["packet_runbook"] == (
        "docs/runbooks/row-01-production-postgres-retrieval.md"
    )
    assert artifact_worklist["retrieval-ops-bundle.json"]["checks"][0]["command"] == (
        "retrieval-ops-check"
    )
    assert artifact_worklist["auth-ops-bundle.json"]["rows"][0]["lane"] == "B2"
    artifact_contracts = {
        item["relative_path"]: item for item in report["input_artifact_contracts"]
    }
    assert len(artifact_contracts) == 24
    retrieval_contract = artifact_contracts["retrieval-ops-bundle.json"]
    assert retrieval_contract["artifact_kind"] == "ops_bundle_json"
    assert retrieval_contract["status"] == "missing"
    assert retrieval_contract["report_is_evidence"] is False
    assert retrieval_contract["consuming_validators"][0]["command"] == (
        "retrieval-ops-check"
    )
    assert retrieval_contract["release_audit_output_keys_by_command"] == [
        {
            "command": "retrieval-ops-check",
            "keys": ["bundle", "requirements", "checks", "findings"],
        }
    ]
    assert retrieval_contract["validator_section_hints_by_command"] == [
        {
            "command": "retrieval-ops-check",
            "sections": [
                "provider_check",
                "retrieval",
                "adapter_probes",
                "calibration",
                "redaction",
            ],
        }
    ]
    assert retrieval_contract["consuming_validators"][0][
        "validator_section_hints"
    ] == [
        "provider_check",
        "retrieval",
        "adapter_probes",
        "calibration",
        "redaction",
    ]
    assert any(
        "real production artifact" in note
        for note in retrieval_contract["minimum_operator_contract"]
    )
    provider_manifest_contract = artifact_contracts[
        "provider-manifest.production.json"
    ]
    assert provider_manifest_contract["artifact_kind"] == "provider_manifest_json"
    assert {
        item["command"]
        for item in provider_manifest_contract["release_audit_output_keys_by_command"]
    } >= {"provider-check"}
    assert provider_manifest_contract["validator_section_hints_by_command"] == []
    assert any(
        "forbid_local true" in note
        for note in provider_manifest_contract["minimum_operator_contract"]
    )
    render_env_plan = {
        item["env"]: item for item in report["render_env_action_plan"]
    }
    assert len(render_env_plan) == 20
    assert render_env_plan["MNEMOSYNE_PROD_EVIDENCE_DIR"]["status"] == (
        "present_for_readiness"
    )
    assert render_env_plan["MNEMOSYNE_PROD_EVIDENCE_DIR"]["missing"] is False
    assert render_env_plan["MNEMOSYNE_PROD_EVIDENCE_DIR"]["values_recorded"] is False
    assert render_env_plan["MNEMOSYNE_PROD_C2PA_TOOL"]["status"] == "missing"
    assert render_env_plan["MNEMOSYNE_PROD_C2PA_TOOL"]["affected_rows"][0][
        "lane"
    ] == "B5"
    assert render_env_plan["MNEMOSYNE_PROD_C2PA_TOOL"]["report_is_evidence"] is False
    validation_plan = {
        item["name"]: item for item in report["input_artifact_validation_plan"]
    }
    assert validation_plan["retrieval-ops"]["argv"][:3] == [
        "retrieval-ops-check",
        "--bundle",
        str(packet_root / "input-artifacts" / "retrieval-ops-bundle.json"),
    ]
    assert validation_plan["retrieval-ops"]["lanes"] == ["B1"]
    assert validation_plan["retrieval-ops"]["rows"][0]["packet_runbook"] == (
        "docs/runbooks/row-01-production-postgres-retrieval.md"
    )
    assert validation_plan["retrieval-ops"]["argv"][3:] == [
        "--require-provider-check",
        "embedding",
        "--require-provider-check",
        "reranker",
        "--require-provider-check",
        "retrieval_backends",
    ]
    assert validation_plan["calibration-tune"]["env_placeholders"] == [
        "MNEMOSYNE_PROD_TENANT"
    ]
    assert "calibration-dataset.json" in validation_plan["calibration-tune"][
        "required_input_artifacts"
    ]
    assert set(validation_plan["ops-dashboard"]["env_placeholders"]) == {
        "MNEMOSYNE_PROD_DASHBOARD_URL",
        "MNEMOSYNE_PROD_TENANT",
    }
    assert "row-10-full-suite-evidence.json" in validation_plan["belief-revision"][
        "required_input_artifacts"
    ]
    row_action_plan = {item["lane"]: item for item in report["row_action_plan"]}
    assert set(row_action_plan) == {f"B{index}" for index in range(1, 11)}
    assert [item["lane"] for item in report["row_action_plan"]] == [
        f"B{index}" for index in range(1, 11)
    ]
    assert row_action_plan["B1"]["packet_runbook"] == (
        "docs/runbooks/row-01-production-postgres-retrieval.md"
    )
    assert row_action_plan["B1"]["input_artifact_validation_command"] == (
        f"{artifact_validation_script} B1"
    )
    assert row_action_plan["B1"]["blocker_counts"]["input_artifacts"] == 1
    assert row_action_plan["B1"]["blocker_counts"]["global_render_environment"] == 2
    assert row_action_plan["B1"]["blocker_counts"]["render_environment"] == 0
    assert row_action_plan["B1"]["global_missing_render_environment"] == [
        "MNEMOSYNE_PROD_CHANGE_TICKET",
        "MNEMOSYNE_PROD_OPERATOR_NAME",
    ]
    assert row_action_plan["B1"]["blocker_counts"][
        "primary_provider_manifest_environment"
    ] == 6
    assert row_action_plan["B1"]["missing_input_artifacts"] == [
        "retrieval-ops-bundle.json"
    ]
    assert row_action_plan["B1"]["primary_missing_provider_manifest_env_refs"] == [
        "MNEMOSYNE_EMBEDDING_API_KEY",
        "MNEMOSYNE_EMBEDDING_MODEL",
        "MNEMOSYNE_EMBEDDING_URL",
        "MNEMOSYNE_RERANKER_API_KEY",
        "MNEMOSYNE_RERANKER_MODEL",
        "MNEMOSYNE_RERANKER_URL",
    ]
    assert "MNEMOSYNE_PROVIDER_OIDC_ISSUER" in row_action_plan["B1"][
        "shared_missing_provider_manifest_env_refs"
    ]
    assert "MNEMOSYNE_PROVIDER_OIDC_ISSUER" not in row_action_plan["B1"][
        "primary_missing_provider_manifest_env_refs"
    ]
    assert {
        validator["name"] for validator in row_action_plan["B1"]["validators"]
    } >= {"provider-check", "retrieval-ops"}
    assert row_action_plan["B1"]["report_is_evidence"] is False
    assert "Capture real production input artifacts under input-artifacts/." in (
        row_action_plan["B1"]["next_actions"]
    )
    provider_env_plan = {
        item["env"]: item for item in report["provider_env_action_plan"]
    }
    assert len(provider_env_plan) == 24
    embedding_url_plan = provider_env_plan["MNEMOSYNE_EMBEDDING_URL"]
    assert embedding_url_plan["status"] == "missing"
    assert embedding_url_plan["missing"] is True
    assert embedding_url_plan["values_redacted"] is True
    assert embedding_url_plan["value_source_recorded"] is False
    assert embedding_url_plan["primary_rows"] == ["B1"]
    assert set(embedding_url_plan["affected_rows"]) == {
        "B1",
        "B2",
        "B4",
        "B6",
        "B7",
        "B9",
        "B10",
    }
    assert embedding_url_plan["provider_checks"] == ["embedding"]
    assert embedding_url_plan["provider_manifest_paths"] == [
        "/providers/retrieval/embedding/url/env"
    ]
    assert embedding_url_plan["report_is_evidence"] is False
    assert (
        embedding_url_plan["next_action"]
        == "Set this name in the external runtime env file and refresh."
    )
    assert provider_env_plan["MNEMOSYNE_PROVIDER_OIDC_ISSUER"]["primary_rows"] == [
        "B2"
    ]
    assert provider_env_plan["MNEMOSYNE_PROVIDER_OIDC_ISSUER"][
        "provider_check_routes"
    ] == [
        {
            "commands": [],
            "lanes": ["B2"],
            "provider_check": "oidc",
            "source": "row_runbook_provider_ownership",
        }
    ]
    assert provider_env_plan["MNEMOSYNE_SESSION_SECRET_COMMAND"]["primary_rows"] == [
        "B2"
    ]
    assert provider_env_plan["MNEMOSYNE_OBJECT_KEY_COMMAND"]["primary_rows"] == [
        "B7"
    ]
    assert provider_env_plan["MNEMOSYNE_RUNTIME_RESIDENCY"]["primary_rows"] == [
        "B7"
    ]
    assert provider_env_plan["MNEMOSYNE_RUNTIME_RESIDENCY"][
        "provider_check_routes"
    ] == [
        {
            "commands": [],
            "lanes": ["B7"],
            "provider_check": "residency_policy",
            "source": "row_runbook_provider_ownership",
        }
    ]
    assert provider_env_plan["MNEMOSYNE_PARAMETRIC_COMMAND"]["primary_rows"] == [
        "B9"
    ]
    blockers = report["capture_blockers"]
    assert blockers["report_is_evidence"] is False
    assert blockers["blocked_lane_count"] == len(blockers["blocked_lanes"])
    assert blockers["blocked_lanes"] == [f"B{index}" for index in range(1, 11)]
    assert set(blockers["blocked_lanes"]) == {
        str(row["lane"]) for row in report["rows"] if not row["ready_for_capture"]
    }
    assert blockers["ready_lanes"] == []
    assert blockers["types"]["render_environment"]["missing_count"] == 19
    assert blockers["types"]["provider_manifest_environment"]["missing_count"] == 24
    assert blockers["types"]["input_artifacts"]["missing_count"] == 23
    assert blockers["types"]["packet_docs"]["missing_count"] == 0
    assert [item["kind"] for item in blockers["recommended_order"]] == [
        "render_environment",
        "provider_manifest_environment",
        "input_artifacts",
    ]
    assert blockers["recommended_order"][0]["blocked_lanes"] == [
        f"B{index}" for index in range(1, 11)
    ]
    assert blockers["recommended_order"][1]["blocked_lanes"] == [
        "B1",
        "B2",
        "B4",
        "B6",
        "B7",
        "B9",
        "B10",
    ]
    inventory = report["operator_input_inventory"]
    assert set(inventory) == {
        "input_artifacts",
        "production_render_env",
        "runtime_env_file",
    }
    assert inventory["production_render_env"]["path"] == str(
        packet_root / "production-render.env"
    )
    assert inventory["production_render_env"]["missing_count"] == 19
    assert (
        "MNEMOSYNE_PROD_EVIDENCE_DIR"
        not in inventory["production_render_env"]["missing"]
    )
    assert inventory["production_render_env"]["global_missing"] == [
        "MNEMOSYNE_PROD_CHANGE_TICKET",
        "MNEMOSYNE_PROD_OPERATOR_NAME",
    ]
    assert inventory["production_render_env"]["missing_render_env_by_row"][
        "B1"
    ] == [
        "MNEMOSYNE_PROD_CHANGE_TICKET",
        "MNEMOSYNE_PROD_OPERATOR_NAME",
    ]
    assert inventory["production_render_env"]["missing_render_env_by_row"][
        "B5"
    ] == [
        "MNEMOSYNE_PROD_C2PA_TOOL",
        "MNEMOSYNE_PROD_CHANGE_TICKET",
        "MNEMOSYNE_PROD_OPERATOR_NAME",
    ]
    assert inventory["runtime_env_file"]["path_placeholder"] == (
        "/secure/path/to/mnemosyne-production-runtime.env"
    )
    assert inventory["runtime_env_file"]["example_path"] == str(
        packet_root / "reports" / "mnemosyne-production-runtime.env.example"
    )
    assert inventory["runtime_env_file"]["missing_count"] == 24
    assert inventory["runtime_env_file"]["values_redacted"] is True
    assert inventory["runtime_env_file"][
        "provider_manifest_env_refs_by_primary_row"
    ]["B1"] == [
        "MNEMOSYNE_EMBEDDING_API_KEY",
        "MNEMOSYNE_EMBEDDING_MODEL",
        "MNEMOSYNE_EMBEDDING_URL",
        "MNEMOSYNE_RERANKER_API_KEY",
        "MNEMOSYNE_RERANKER_MODEL",
        "MNEMOSYNE_RERANKER_URL",
    ]
    assert inventory["runtime_env_file"][
        "missing_provider_manifest_env_refs_by_primary_row"
    ]["B2"] == [
        "MNEMOSYNE_PROVIDER_OIDC_AUDIENCE",
        "MNEMOSYNE_PROVIDER_OIDC_AUTHZ_POLICY_FILE",
        "MNEMOSYNE_PROVIDER_OIDC_ISSUER",
        "MNEMOSYNE_PROVIDER_OIDC_JWKS_URL",
        "MNEMOSYNE_SESSION_SECRET_COMMAND",
    ]
    assert inventory["input_artifacts"]["directory"] == str(
        packet_root / "input-artifacts"
    )
    assert inventory["input_artifacts"]["missing_count"] == 23
    assert inventory["input_artifacts"]["missing_input_artifacts_by_row"][
        "B1"
    ] == ["retrieval-ops-bundle.json"]
    assert inventory["input_artifacts"]["missing_input_artifacts_by_row"][
        "B10"
    ] == [
        "belief-revision-cases.json",
        "row-10-full-suite-evidence.json",
    ]
    assert inventory["input_artifacts"]["checklist"] == (
        "docs/production-input-artifacts.checklist.md"
    )
    assert (packet_root / "input-artifacts" / "provider-manifest.production.json").is_file()
    assert (packet_root / "production-render.env").is_file()
    assert (
        f'export MNEMOSYNE_PROD_EVIDENCE_DIR="{packet_root / "input-artifacts"}"'
        in (packet_root / "production-render.env").read_text(encoding="utf-8")
    )
    assert (packet_root / "reports" / "tier-b-gap-report.md").is_file()
    assert artifact_worklist_markdown.is_file()
    assert artifact_worklist_json.is_file()
    assert json.loads(artifact_worklist_json.read_text(encoding="utf-8")) == report[
        "input_artifact_worklist"
    ]
    assert artifact_contracts_markdown.is_file()
    assert artifact_contracts_json.is_file()
    assert json.loads(artifact_contracts_json.read_text(encoding="utf-8")) == report[
        "input_artifact_contracts"
    ]
    assert row_action_plan_markdown.is_file()
    assert row_action_plan_json.is_file()
    assert json.loads(row_action_plan_json.read_text(encoding="utf-8")) == report[
        "row_action_plan"
    ]
    assert provider_env_action_plan_markdown.is_file()
    assert provider_env_action_plan_json.is_file()
    assert json.loads(
        provider_env_action_plan_json.read_text(encoding="utf-8")
    ) == report["provider_env_action_plan"]
    assert render_env_action_plan_markdown.is_file()
    assert render_env_action_plan_json.is_file()
    assert json.loads(
        render_env_action_plan_json.read_text(encoding="utf-8")
    ) == report["render_env_action_plan"]
    assert artifact_validation_script.is_file()
    assert os.access(artifact_validation_script, os.X_OK)
    assert next_commands_script.is_file()
    assert os.access(next_commands_script, os.X_OK)
    assert (packet_root / "docs" / "PRODUCTION-EVIDENCE.md").is_file()
    assert (packet_root / "docs" / "OPS-HANDOFF-AND-OWNERSHIP.md").is_file()
    assert (packet_root / "docs" / "runbooks" / "README.md").is_file()
    assert (
        packet_root / "docs" / "runbooks" / "row-01-production-postgres-retrieval.md"
    ).is_file()
    readme = (packet_root / "README.md").read_text(encoding="utf-8")
    markdown = (packet_root / "reports" / "tier-b-gap-report.md").read_text(
        encoding="utf-8"
    )
    runtime_example = (
        packet_root / "reports" / "mnemosyne-production-runtime.env.example"
    ).read_text(encoding="utf-8")
    assert "--refresh" in readme
    assert "RUNTIME_ENV_FILE=/secure/path/to/mnemosyne-production-runtime.env" in readme
    assert '--env-file "$RUNTIME_ENV_FILE"' in readme
    assert "Ready for capture: `false`" not in readme
    assert "does not carry current readiness status" in readme
    assert "docs/runbooks/" in readme
    assert "read-only packet guidance docs" in readme
    assert "reports/mnemosyne-production-runtime.env.example" in readme
    assert "reports/provider-env-action-plan.md" in readme
    assert "reports/render-env-action-plan.md" in readme
    assert "reports/row-action-plan.md" in readme
    assert "reports/input-artifact-worklist.md" in readme
    assert "reports/input-artifact-contracts.md" in readme
    assert "advisory validator section/check hints" in readme
    assert "reports/input-artifact-validation-commands.sh" in readme
    assert "reports/input-artifact-validation-commands.sh B1" in readme
    assert "symlinked input artifacts scoped to that selection" in readme
    assert "reports/next-commands.sh" in readme
    validation_script_text = artifact_validation_script.read_text(encoding="utf-8")
    assert validation_script_text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "validates supplied input artifacts; it is not production evidence" in (
        validation_script_text
    )
    assert "never creates placeholder JSON, PEM, or bundle files" in validation_script_text
    assert 'REQUESTED_LANE="${1:-all}"' in validation_script_text
    assert "usage: $0 [all|B1|B2|B3|B4|B5|B6|B7|B8|B9|B10]" in (
        validation_script_text
    )
    assert "check_artifact_for_lanes retrieval-ops-bundle.json B1" in (
        validation_script_text
    )
    assert "run_validator_for_lanes retrieval-ops B1 \\" in validation_script_text
    assert "MISSING input artifact" in validation_script_text
    assert "load-env.py" in validation_script_text
    assert "MNEMOSYNE_PROD_TENANT" in validation_script_text
    assert "MNEMOSYNE_PROD_DASHBOARD_URL" in validation_script_text
    assert "retrieval-ops-check" in validation_script_text
    assert "--bundle \\" in validation_script_text
    assert '"${INPUT_ARTIFACT_DIR}/retrieval-ops-bundle.json"' in (
        validation_script_text
    )
    validation_proc = subprocess.run(
        [str(artifact_validation_script)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation_proc.returncode == 78
    assert "MISSING input artifact: retrieval-ops-bundle.json" in (
        validation_proc.stderr
    )
    validation_b1_proc = subprocess.run(
        [str(artifact_validation_script), "B1"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation_b1_proc.returncode == 78
    assert "MISSING input artifact: retrieval-ops-bundle.json" in (
        validation_b1_proc.stderr
    )
    assert "MISSING input artifact: ops-dashboard-bundle.json" not in (
        validation_b1_proc.stderr
    )
    invalid_row_proc = subprocess.run(
        [str(artifact_validation_script), "B11"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert invalid_row_proc.returncode == 64
    assert "usage: " in invalid_row_proc.stderr
    script_text = next_commands_script.read_text(encoding="utf-8")
    assert script_text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "operator convenience script, not production evidence" in script_text
    assert str(packet_root / "reports" / "tier-b-gap-report.md") in script_text
    assert "run this script from the Mnemosyne repository root" in script_text
    assert (
        'RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-'
        "/secure/path/to/mnemosyne-production-runtime.env}\""
    ) in script_text
    assert "external mode-0600 runtime env file" in script_text
    assert "Post-Capture Custody Verification" in markdown
    assert "Capture Blockers" in markdown
    assert "`provider_manifest_environment`: `24` missing" in markdown
    assert "Operator Input Inventory" in markdown
    assert "### production-render.env" in markdown
    assert "Global render placeholders" in markdown
    assert "Missing render placeholders by row" in markdown
    assert "`B5`: `MNEMOSYNE_PROD_C2PA_TOOL`" in markdown
    assert "### Runtime Env File" in markdown
    assert "Missing provider refs by primary row" in markdown
    assert "`B1`: `MNEMOSYNE_EMBEDDING_API_KEY`" in markdown
    assert "### Input Artifacts" in markdown
    assert "Missing input artifacts by row" in markdown
    assert "`B10`: `belief-revision-cases.json`, `row-10-full-suite-evidence.json`" in (
        markdown
    )
    assert "Input Artifact Worklist" in markdown
    assert "input-artifact-contracts.md" in markdown
    assert "render-env-action-plan.md" in markdown
    assert "provider-env-action-plan.md" in markdown
    assert "row-action-plan.md" in markdown
    assert "input-artifact-validation-commands.sh" in markdown
    assert "input-artifact-validation-commands.sh B1" in markdown
    assert "do not create placeholder JSON" in markdown
    assert "retrieval-ops-bundle.json" in markdown
    assert "mnemosyne-production-runtime.env.example" in markdown
    artifact_worklist_text = artifact_worklist_markdown.read_text(encoding="utf-8")
    assert "operator preparation aid, not production evidence" in artifact_worklist_text
    assert "Do not create placeholder JSON, PEM, or bundle files" in artifact_worklist_text
    assert "`retrieval-ops-bundle.json`" in artifact_worklist_text
    assert "`retrieval-ops-check`" in artifact_worklist_text
    assert "`B1` Production Postgres retrieval" in artifact_worklist_text
    artifact_contracts_text = artifact_contracts_markdown.read_text(encoding="utf-8")
    assert "operator preparation aid, not production evidence" in artifact_contracts_text
    assert "`retrieval-ops-bundle.json`" in artifact_contracts_text
    assert "`ops_bundle_json`" in artifact_contracts_text
    assert "Validator section hints (advisory, not schema)" in artifact_contracts_text
    assert (
        "`retrieval-ops-check`: `provider_check`, `retrieval`, `adapter_probes`, "
        "`calibration`, `redaction`"
    ) in artifact_contracts_text
    assert "`retrieval-ops-check`: `bundle`, `requirements`, `checks`, `findings`" in (
        artifact_contracts_text
    )
    assert "Keep forbid_local true" in artifact_contracts_text
    row_action_plan_text = row_action_plan_markdown.read_text(encoding="utf-8")
    assert "operator preparation aid, not production evidence" in row_action_plan_text
    assert "## B1 - Production Postgres retrieval" in row_action_plan_text
    assert f"`{artifact_validation_script} B1`" in row_action_plan_text
    assert "`retrieval-ops-bundle.json`" in row_action_plan_text
    assert "Primary provider refs" in row_action_plan_text
    assert "| Row | Ready | Global render | Row render |" in row_action_plan_text
    assert "`B1` Production Postgres retrieval | `false` | `2` | `0`" in (
        row_action_plan_text
    )
    assert (
        row_action_plan_text.index("| `B2` Tenant isolation and auth")
        < row_action_plan_text.index("| `B10` Live parity suite")
    )
    assert "Fill global production-render.env placeholders shared by all rows" in (
        row_action_plan_text
    )
    assert "Global missing render env" in row_action_plan_text
    assert "Row-owned missing provider-manifest env refs" in row_action_plan_text
    assert "Shared provider-stack blockers owned by other rows" in row_action_plan_text
    provider_env_plan_text = provider_env_action_plan_markdown.read_text(
        encoding="utf-8"
    )
    assert "operator preparation aid, not production evidence" in provider_env_plan_text
    assert "`MNEMOSYNE_EMBEDDING_URL`" in provider_env_plan_text
    assert "/providers/retrieval/embedding/url/env" in provider_env_plan_text
    assert "Values and runtime env-file paths are" in provider_env_plan_text
    assert "`oidc: row_runbook_provider_ownership`" in provider_env_plan_text
    render_env_plan_text = render_env_action_plan_markdown.read_text(
        encoding="utf-8"
    )
    assert "operator preparation aid, not production evidence" in render_env_plan_text
    assert "`MNEMOSYNE_PROD_C2PA_TOOL`" in render_env_plan_text
    assert "`B5`" in render_env_plan_text
    assert "Render values are not retained" in render_env_plan_text
    assert str(next_commands_script) in markdown
    assert "Copy this generated no-secret example" in runtime_example
    assert 'export MNEMOSYNE_EMBEDDING_URL=""' in runtime_example
    assert 'export MNEMOSYNE_RERANKER_API_KEY=""' in runtime_example
    assert 'export MNEMOSYNE_SESSION_SECRET_COMMAND=""' in runtime_example
    assert "Packet docs complete: `true`" in markdown
    assert (
        "Packet runbook: `docs/runbooks/row-01-production-postgres-retrieval.md`"
        in markdown
    )
    assert "production-evidence-verify" in report["post_capture_verify_script"]
    assert report["next_commands_script"] == str(next_commands_script)
    assert "--fingerprint-record" in report["post_capture_verify_script"]
    assert "EXPECTED_BUNDLE_FINGERPRINT" not in report["post_capture_verify_script"]
    assert "--report-output" in report["post_capture_verify_script"]
    assert report["post_capture_verify_report"] == str(
        packet_root.parent
        / f"{packet_root.name}-production-evidence-verify.json"
    )
    runtime_env_arg = (
        '"${RUNTIME_ENV_FILE:-/secure/path/to/mnemosyne-production-runtime.env}"'
    )
    assert any(
        f"--runtime-env-file {runtime_env_arg}" in command
        for command in report["next_commands"]
    )
    assert any(
        f"--env-file {runtime_env_arg}" in command
        for command in report["next_commands"]
    )
    assert any(
        "--fingerprint-record-output" in command
        for command in report["next_commands"]
    )
    capture_command = report["next_commands"][-2]
    verify_command = report["next_commands"][-1]
    assert "--fingerprint-record-output" in capture_command
    assert "production-evidence-verify" in verify_command
    assert "--fingerprint-record" in verify_command
    assert "--report-output" in verify_command
    assert str(packet_root.parent / f"{packet_root.name}-capture") in verify_command
    assert (
        str(packet_root.parent / f"{packet_root.name}-bundle-fingerprint.json")
        in verify_command
    )
    assert (
        str(packet_root.parent / f"{packet_root.name}-production-evidence-verify.json")
        in verify_command
    )
    assert summary["next_commands"] == report["next_commands"]
    assert summary["next"].endswith("run next_commands_script or next_commands in order.")
    for command in report["next_commands"]:
        assert command in script_text

    rows = {row["lane"]: row for row in report["rows"]}
    assert rows["B1"]["packet_runbook"] == (
        "docs/runbooks/row-01-production-postgres-retrieval.md"
    )
    assert rows["B1"]["missing_input_artifacts"] == ["retrieval-ops-bundle.json"]
    assert "MNEMOSYNE_EMBEDDING_URL" in rows["B1"]["missing_provider_manifest_env_refs"]
    assert rows["B3"]["missing_provider_manifest_env_refs"] == []
    assert rows["B8"]["missing_provider_manifest_env_refs"] == []
    assert report["phase_plan"][1]["title"] == "Shared provider stack"
    assert set(report["phase_plan"][1]["lanes_unblocked_when_done"]) == {
        "B1",
        "B2",
        "B4",
        "B6",
        "B7",
        "B9",
        "B10",
    }


@_posix_only
def test_prepare_production_evidence_custody_refresh_repairs_missing_packet_docs(
    tmp_path: Path,
) -> None:
    packet_root = tmp_path / "mnemosyne-tier-b-packet"
    subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    preserved_doc = packet_root / "docs" / "PRODUCTION-EVIDENCE.md"
    preserved_doc.write_text("operator-local note\n", encoding="utf-8")
    missing_runbook = (
        packet_root / "docs" / "runbooks" / "row-01-production-postgres-retrieval.md"
    )
    missing_runbook.unlink()

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            "--refresh",
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    summary = json.loads(proc.stdout)
    report = json.loads(
        (packet_root / "reports" / "tier-b-gap-report.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = (packet_root / "reports" / "tier-b-gap-report.md").read_text(
        encoding="utf-8"
    )

    assert proc.returncode == 78
    assert summary["packet_docs_complete"] is True
    assert summary["packet_docs_added"] == 1
    assert report["packet_docs_complete"] is True
    assert report["packet_docs_added"] == [
        "docs/runbooks/row-01-production-postgres-retrieval.md"
    ]
    assert report["packet_docs_missing"] == []
    assert missing_runbook.is_file()
    assert preserved_doc.read_text(encoding="utf-8") == "operator-local note\n"
    assert "Added missing packet docs during this refresh" in markdown


def test_prepare_production_evidence_custody_phase_plan_scopes_provider_stack() -> None:
    module = _load_prepare_custody_module()
    rows = [
        {
            "lane": "B1",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
        {
            "lane": "B2",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": False,
        },
        {
            "lane": "B3",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
        {
            "lane": "B4",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
        {
            "lane": "B6",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
        {
            "lane": "B7",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
        {
            "lane": "B9",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
        {
            "lane": "B10",
            "ready_for_capture": False,
            "provider_manifest_environment_complete": True,
        },
    ]

    phase_plan = module._phase_plan(rows)

    assert phase_plan[1]["title"] == "Shared provider stack"
    assert phase_plan[1]["status"] == "blocked"
    assert phase_plan[1]["lanes_unblocked_when_done"] == [
        "B1",
        "B2",
        "B4",
        "B6",
        "B7",
        "B9",
        "B10",
    ]
    assert phase_plan[1]["currently_blocked_lanes"] == ["B2"]
    assert phase_plan[2]["title"] == "Keystone rows"
    assert phase_plan[2]["status"] == "blocked"

    for row in rows:
        if row["lane"] == "B2":
            row["provider_manifest_environment_complete"] = True
    phase_plan = module._phase_plan(rows)

    assert phase_plan[1]["status"] == "ready"
    assert phase_plan[1]["currently_blocked_lanes"] == []
    assert phase_plan[2]["status"] == "blocked"


@_posix_only
def test_prepare_production_evidence_custody_refresh_preserves_operator_inputs(
    tmp_path: Path,
) -> None:
    packet_root = tmp_path / "mnemosyne-tier-b-packet"
    create = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 78

    env_file = packet_root / "production-render.env"
    env_text = env_file.read_text(encoding="utf-8")
    env_file.write_text(
        env_text.replace(
            'export MNEMOSYNE_PROD_TENANT=""',
            'export MNEMOSYNE_PROD_TENANT="tenant-prod"',
        ),
        encoding="utf-8",
    )
    provider_manifest = packet_root / "input-artifacts" / "provider-manifest.production.json"
    provider_before = provider_manifest.read_bytes()

    refresh = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            "--refresh",
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = json.loads(refresh.stdout)
    report = json.loads(
        (packet_root / "reports" / "tier-b-gap-report.json").read_text(
            encoding="utf-8"
        )
    )

    assert refresh.returncode == 78
    assert summary["missing_render_environment"] == 18
    assert "MNEMOSYNE_PROD_TENANT" not in report["missing_render_environment"]
    assert report["production_render_env"] == str(env_file)
    assert report["production_render_env_loaded"] is True
    assert provider_manifest.read_bytes() == provider_before


@_posix_only
def test_prepare_production_evidence_custody_refresh_rejects_unsafe_packet_paths(
    tmp_path: Path,
) -> None:
    packet_root = tmp_path / "mnemosyne-tier-b-packet"
    create = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 78

    linked_root = tmp_path / "linked-packet"
    try:
        linked_root.symlink_to(packet_root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink setup unavailable: {exc}")
    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            "--refresh",
            str(linked_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 65
    assert "custody root must not be a symlink" in proc.stderr

    input_dir = packet_root / "input-artifacts"
    real_input_dir = packet_root / "real-input-artifacts"
    input_dir.rename(real_input_dir)
    input_dir.symlink_to(real_input_dir, target_is_directory=True)
    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            "--refresh",
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 65
    assert "input-artifacts must not be a symlink" in proc.stderr


@_posix_only
def test_prepare_production_evidence_custody_refresh_reports_no_values(
    tmp_path: Path,
) -> None:
    packet_root = tmp_path / "mnemosyne-tier-b-packet"
    create = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create.returncode == 78

    env_sentinel = "tenant-prod-secret-sentinel"
    provider_sentinel = "https://embedding-secret-sentinel.example.test"
    env_file = packet_root / "production-render.env"
    env_file.write_text(
        env_file.read_text(encoding="utf-8").replace(
            'export MNEMOSYNE_PROD_TENANT=""',
            f'export MNEMOSYNE_PROD_TENANT="{env_sentinel}"',
        ),
        encoding="utf-8",
    )
    proc_env = {**os.environ, "MNEMOSYNE_EMBEDDING_URL": provider_sentinel}
    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            "--refresh",
            str(packet_root),
        ],
        cwd=REPO,
        env=proc_env,
        capture_output=True,
        text=True,
        check=False,
    )
    report_text = (packet_root / "reports" / "tier-b-gap-report.json").read_text(
        encoding="utf-8"
    )
    markdown = (packet_root / "reports" / "tier-b-gap-report.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join([proc.stdout, proc.stderr, report_text, markdown])

    assert proc.returncode == 78
    assert env_sentinel not in combined
    assert provider_sentinel not in combined


@_posix_only
def test_prepare_production_evidence_custody_runtime_env_file_satisfies_refs_without_retention(
    tmp_path: Path,
) -> None:
    packet_root = tmp_path / "mnemosyne-tier-b-packet"
    runtime_env_file = tmp_path / "mnemosyne-production-runtime.env"
    provider_sentinel = "https://embedding-secret-sentinel.example.test"
    runtime_env_file.write_text(
        f'export MNEMOSYNE_EMBEDDING_URL="{provider_sentinel}"\n',
        encoding="utf-8",
    )
    runtime_env_file.chmod(0o600)

    proc = subprocess.run(
        [
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            "--runtime-env-file",
            str(runtime_env_file),
            str(packet_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    report_text = (packet_root / "reports" / "tier-b-gap-report.json").read_text(
        encoding="utf-8"
    )
    report = json.loads(report_text)
    markdown = (packet_root / "reports" / "tier-b-gap-report.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join([proc.stdout, proc.stderr, report_text, markdown])

    assert proc.returncode == 78
    assert report["runtime_env_file_loaded"] is True
    assert report["runtime_env_file_values_redacted"] is True
    assert "MNEMOSYNE_EMBEDDING_URL" not in report["missing_provider_manifest_env_refs"]
    provider_env_plan = {
        item["env"]: item for item in report["provider_env_action_plan"]
    }
    assert provider_env_plan["MNEMOSYNE_EMBEDDING_URL"]["status"] == (
        "present_for_readiness"
    )
    assert provider_env_plan["MNEMOSYNE_EMBEDDING_URL"]["missing"] is False
    assert (
        report["capture_blockers"]["types"]["provider_manifest_environment"][
            "missing_count"
        ]
        == len(report["missing_provider_manifest_env_refs"])
    )
    assert report["capture_blockers"]["types"]["provider_manifest_environment"][
        "missing_count"
    ] == 23
    inventory = report["operator_input_inventory"]
    assert inventory["runtime_env_file"]["loaded_for_readiness"] is True
    assert (
        "MNEMOSYNE_EMBEDDING_URL"
        not in inventory["runtime_env_file"]["missing_provider_manifest_env_refs"]
    )
    assert "MNEMOSYNE_EMBEDDING_URL" not in inventory["runtime_env_file"][
        "missing_provider_manifest_env_refs_by_primary_row"
    ].get("B1", [])
    assert "MNEMOSYNE_RERANKER_URL" in inventory["runtime_env_file"][
        "missing_provider_manifest_env_refs_by_primary_row"
    ]["B1"]
    assert inventory["runtime_env_file"]["path_placeholder"] == (
        "/secure/path/to/mnemosyne-production-runtime.env"
    )
    runtime_example = (
        packet_root / "reports" / "mnemosyne-production-runtime.env.example"
    ).read_text(encoding="utf-8")
    assert str(runtime_env_file) not in runtime_example
    assert provider_sentinel not in runtime_example
    assert provider_sentinel not in combined
    assert str(runtime_env_file) not in combined
    runtime_env_arg = (
        '"${RUNTIME_ENV_FILE:-/secure/path/to/mnemosyne-production-runtime.env}"'
    )
    assert any(
        f"--runtime-env-file {runtime_env_arg}" in command
        for command in report["next_commands"]
    )


def test_prepare_production_evidence_custody_rejects_repo_local_root(
    tmp_path: Path,
) -> None:
    repo_local_root = REPO / f".tmp-tier-b-packet-{tmp_path.name}"

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "infra" / "scripts" / "prepare-production-evidence-custody.py"),
            str(repo_local_root),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 65
    assert "inside the repository" in proc.stderr
    assert not repo_local_root.exists()


def test_generated_secret_material_uses_private_modes() -> None:
    keycloak = _read("infra/scripts/setup-keycloak.sh")
    vault = _read("infra/scripts/setup-vault.sh")
    c2pa = _read("infra/scripts/setup-c2pa.sh")

    assert "umask 077" in keycloak
    assert 'chmod 700 "${OUT_DIR}"' in keycloak
    assert 'chmod 600 "${OUT_DIR}/id_token.jwt"' in keycloak
    assert 'chmod 600 "${OUT_DIR}/oidc.env"' in keycloak

    assert "umask 077" in vault
    assert 'chmod 700 "${OUT_DIR}"' in vault
    assert 'chmod 600 "${OUT_DIR}/vault.env"' in vault

    assert "umask 077" in c2pa
    assert 'chmod 700 "${OUT_DIR}"' in c2pa


def test_c2pa_docker_invocation_uses_array_not_string_eval() -> None:
    c2pa = _read("infra/scripts/setup-c2pa.sh")

    assert "C2PA_RUN=(docker run" in c2pa
    assert "\nRUN=" not in c2pa
    assert "${RUN}" not in c2pa
    assert '"${C2PA_RUN[@]}" sh -c' in c2pa
    assert '"${C2PA_RUN[@]}" c2patool' in c2pa
