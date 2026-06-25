from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _covered_by_dir_pattern(candidate: str, patterns: list[str]) -> bool:
    return any(candidate == pattern[:-1] or candidate.startswith(pattern) for pattern in patterns if pattern.endswith("/"))


def test_root_dockerignore_excludes_generated_provider_material() -> None:
    patterns = _patterns(REPO / ".dockerignore")

    assert _covered_by_dir_pattern("infra/keycloak/out/id_token.jwt", patterns)
    assert _covered_by_dir_pattern("infra/vault/out/vault.env", patterns)
    assert _covered_by_dir_pattern("infra/c2pa/out/root.key.pem", patterns)
    assert "**/wrapped-keys/" in patterns


def test_c2pa_dockerignore_excludes_generated_keys_and_artifacts() -> None:
    patterns = _patterns(REPO / "infra" / "c2pa" / ".dockerignore")

    assert _covered_by_dir_pattern("out/root.key.pem", patterns)
    assert _covered_by_dir_pattern("out/signer.key.pem", patterns)
    assert _covered_by_dir_pattern("out/provenance.env", patterns)
    assert "*.pem" in patterns
    assert "*.key" in patterns
