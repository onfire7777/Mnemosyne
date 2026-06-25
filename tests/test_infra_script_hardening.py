from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_production_and_local_evidence_capture_reject_repo_local_outputs() -> None:
    production = _read("infra/scripts/capture-production-evidence.sh")
    local = _read("infra/scripts/capture-local-evidence.sh")

    assert "umask 077" in production
    assert "refusing to write production evidence inside the repository" in production
    assert "out_root.chmod(0o700)" in production

    assert "umask 077" in local
    assert "refusing to write local-staging evidence inside the repository" in local
    assert 'chmod 700 "${OUT_ROOT}"' in local


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
