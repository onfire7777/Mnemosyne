"""Collector-only evidence-bundle signing and release-audit verification."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from mnemosyne.evidence_signing import (
    EvidenceSignatureError,
    default_signature_path,
    generate_collector_keypair,
    sign_evidence_manifest,
    verify_evidence_manifest_signature,
)


def make_keypair(tmp_path: Path, name: str = "collector") -> tuple[Path, Path]:
    private_key = tmp_path / f"{name}.key.pem"
    public_key = tmp_path / f"{name}.pub.pem"
    generate_collector_keypair(private_key, public_key)
    return private_key, public_key


def test_keygen_writes_private_key_with_owner_only_permissions(tmp_path: Path) -> None:
    private_key, public_key = make_keypair(tmp_path)

    assert private_key.is_file()
    assert public_key.is_file()
    mode = stat.S_IMODE(private_key.stat().st_mode)
    assert mode == 0o600
    with pytest.raises(EvidenceSignatureError, match="already exists"):
        generate_collector_keypair(private_key, public_key)


def test_sign_and_verify_round_trip(tmp_path: Path) -> None:
    private_key, public_key = make_keypair(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"kind": "mnemosyne.deployment_soak_evidence"}), encoding="utf-8")

    signed = sign_evidence_manifest(manifest, private_key)
    assert signed["algorithm"] == "ed25519"
    assert signed["manifest_sha256"].startswith("sha256:")
    assert Path(signed["signature_path"]) == default_signature_path(manifest)

    verified = verify_evidence_manifest_signature(manifest, public_key)
    assert verified["verified"] is True
    assert verified["manifest_sha256"] == signed["manifest_sha256"]
    assert verified["public_key_sha256"] == signed["public_key_sha256"]


def test_verify_rejects_tampered_manifest(tmp_path: Path) -> None:
    private_key, public_key = make_keypair(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"checks": [1]}), encoding="utf-8")
    sign_evidence_manifest(manifest, private_key)

    manifest.write_text(json.dumps({"checks": [1, 2]}), encoding="utf-8")

    with pytest.raises(EvidenceSignatureError, match="does not match the manifest digest"):
        verify_evidence_manifest_signature(manifest, public_key)


def test_verify_rejects_wrong_collector_key(tmp_path: Path) -> None:
    private_key, _ = make_keypair(tmp_path, "collector")
    _, other_public = make_keypair(tmp_path, "other")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    sign_evidence_manifest(manifest, private_key)

    with pytest.raises(EvidenceSignatureError, match="not produced by the configured collector key"):
        verify_evidence_manifest_signature(manifest, other_public)


def test_verify_rejects_forged_signature_document(tmp_path: Path) -> None:
    private_key, public_key = make_keypair(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    signed = sign_evidence_manifest(manifest, private_key)

    signature_path = Path(signed["signature_path"])
    document = json.loads(signature_path.read_text(encoding="utf-8"))
    document["signature_b64"] = document["signature_b64"][:-4] + "AAAA"
    signature_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(EvidenceSignatureError, match="invalid for the manifest bytes"):
        verify_evidence_manifest_signature(manifest, public_key)


def test_verify_rejects_missing_signature_file(tmp_path: Path) -> None:
    _, public_key = make_keypair(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    with pytest.raises(EvidenceSignatureError, match="signature file is missing"):
        verify_evidence_manifest_signature(manifest, public_key)
