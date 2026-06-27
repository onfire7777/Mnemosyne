from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_production_and_local_evidence_capture_reject_repo_local_outputs() -> None:
    production = _read("infra/scripts/capture-production-evidence.sh")
    local = _read("infra/scripts/capture-local-evidence.sh")
    keycloak_validate = _read("infra/validate/validate-keycloak.sh")
    vault_validate = _read("infra/validate/validate-vault.sh")
    c2pa_validate = _read("infra/validate/validate-c2pa.sh")

    assert "umask 077" in production
    assert "refusing to write production evidence inside the repository" in production
    assert "out_root.chmod(0o700)" in production

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
