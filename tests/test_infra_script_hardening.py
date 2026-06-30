from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


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

    assert proc.returncode == 78
    assert summary["ok"] is False
    assert summary["ready_for_capture"] is False
    assert summary["report"] == str(report_path)
    assert summary["post_capture_verify_report"] == report["post_capture_verify_report"]
    assert report["schema"] == "mnemosyne.tier-b-custody-gap-report.v1"
    assert report["report_is_evidence"] is False
    assert report["ready_for_capture"] is False
    assert report["packet_docs_complete"] is True
    assert report["packet_docs_added"] == []
    assert report["packet_docs_missing"] == []
    assert len(report["missing_render_environment"]) == 18
    assert "MNEMOSYNE_PROD_EVIDENCE_DIR" not in report["missing_render_environment"]
    assert "MNEMOSYNE_EMBEDDING_URL" in report["missing_provider_manifest_env_refs"]
    assert report["missing_input_artifact_count"] == 23
    assert "provider-manifest.production.json" not in report["missing_input_artifacts"]
    inventory = report["operator_input_inventory"]
    assert set(inventory) == {
        "input_artifacts",
        "production_render_env",
        "runtime_env_file",
    }
    assert inventory["production_render_env"]["path"] == str(
        packet_root / "production-render.env"
    )
    assert inventory["production_render_env"]["missing_count"] == 18
    assert (
        "MNEMOSYNE_PROD_EVIDENCE_DIR"
        not in inventory["production_render_env"]["missing"]
    )
    assert inventory["runtime_env_file"]["path_placeholder"] == (
        "/secure/path/to/mnemosyne-production-runtime.env"
    )
    assert inventory["runtime_env_file"]["missing_count"] == 24
    assert inventory["runtime_env_file"]["values_redacted"] is True
    assert inventory["input_artifacts"]["directory"] == str(
        packet_root / "input-artifacts"
    )
    assert inventory["input_artifacts"]["missing_count"] == 23
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
    assert "--refresh" in readme
    assert "--env-file /secure/path/to/mnemosyne-production-runtime.env" in readme
    assert "Ready for capture: `false`" not in readme
    assert "does not carry current readiness status" in readme
    assert "docs/runbooks/" in readme
    assert "missing read-only packet guidance docs" in readme
    assert "Post-Capture Custody Verification" in markdown
    assert "Operator Input Inventory" in markdown
    assert "### production-render.env" in markdown
    assert "### Runtime Env File" in markdown
    assert "### Input Artifacts" in markdown
    assert "Packet docs complete: `true`" in markdown
    assert (
        "Packet runbook: `docs/runbooks/row-01-production-postgres-retrieval.md`"
        in markdown
    )
    assert "production-evidence-verify" in report["post_capture_verify_script"]
    assert "--expected-bundle-fingerprint" in report["post_capture_verify_script"]
    assert "--report-output" in report["post_capture_verify_script"]
    assert report["post_capture_verify_report"] == str(
        packet_root.parent
        / f"{packet_root.name}-production-evidence-verify.json"
    )
    assert any(
        "--env-file /secure/path/to/mnemosyne-production-runtime.env" in command
        for command in report["next_commands"]
    )
    assert any("--fingerprint-record-output" in command for command in report["next_commands"])
    assert summary["next_commands"] == report["next_commands"]
    assert summary["next"].endswith("run next_commands in order.")

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
    assert summary["missing_render_environment"] == 17
    assert "MNEMOSYNE_PROD_TENANT" not in report["missing_render_environment"]
    assert report["production_render_env"] == str(env_file)
    assert report["production_render_env_loaded"] is True
    assert provider_manifest.read_bytes() == provider_before


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
    inventory = report["operator_input_inventory"]
    assert inventory["runtime_env_file"]["loaded_for_readiness"] is True
    assert (
        "MNEMOSYNE_EMBEDDING_URL"
        not in inventory["runtime_env_file"]["missing_provider_manifest_env_refs"]
    )
    assert inventory["runtime_env_file"]["path_placeholder"] == (
        "/secure/path/to/mnemosyne-production-runtime.env"
    )
    assert provider_sentinel not in combined
    assert str(runtime_env_file) not in combined
    assert "--runtime-env-file /secure/path/to/mnemosyne-production-runtime.env" in report_text


def test_prepare_production_evidence_custody_rejects_repo_local_root(
    tmp_path: Path,
) -> None:
    repo_local_root = REPO / f".tmp-tier-b-packet-{tmp_path.name}"

    proc = subprocess.run(
        [
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
