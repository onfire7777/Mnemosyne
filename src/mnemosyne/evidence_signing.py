"""Collector-only Ed25519 signing for captured evidence bundles.

The evidence collector (the operator machine that runs
``capture-production-evidence.sh``) holds the only private key. It signs the
bundle's ``manifest.json`` — which digest-binds the report and every retained
check file — so ``release-audit`` can verify that the bundle it audits is the
bundle the collector captured, not one assembled or edited afterwards.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

EVIDENCE_SIGNATURE_SCHEMA = "mnemosyne.evidence_signature.v1"
EVIDENCE_SIGNATURE_ALGORITHM = "ed25519"
EVIDENCE_SIGNATURE_SUFFIX = ".sig.json"


class EvidenceSignatureError(ValueError):
    """Raised when signing input or signature verification fails closed."""


def default_signature_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(manifest_path.name + EVIDENCE_SIGNATURE_SUFFIX)


def _public_key_sha256(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "sha256:" + sha256(raw).hexdigest()


def generate_collector_keypair(private_key_path: Path, public_key_path: Path) -> dict[str, Any]:
    """Write a fresh collector keypair; the private key never leaves the collector."""
    if private_key_path.exists():
        raise EvidenceSignatureError(f"collector private key already exists: {private_key_path}")
    if public_key_path.exists():
        raise EvidenceSignatureError(f"collector public key already exists: {public_key_path}")
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(private_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, private_pem)
    finally:
        os.close(fd)
    public_key_path.write_bytes(public_pem)
    return {
        "algorithm": EVIDENCE_SIGNATURE_ALGORITHM,
        "private_key": str(private_key_path),
        "public_key": str(public_key_path),
        "public_key_sha256": _public_key_sha256(private_key.public_key()),
    }


def load_private_key(private_key_path: Path) -> Ed25519PrivateKey:
    try:
        loaded = serialization.load_pem_private_key(private_key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise EvidenceSignatureError(f"collector private key could not be loaded: {exc}") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise EvidenceSignatureError("collector private key must be an Ed25519 key")
    return loaded


def load_public_key(public_key_path: Path) -> Ed25519PublicKey:
    try:
        loaded = serialization.load_pem_public_key(public_key_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise EvidenceSignatureError(f"collector public key could not be loaded: {exc}") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise EvidenceSignatureError("collector public key must be an Ed25519 key")
    return loaded


def sign_evidence_manifest(
    manifest_path: Path,
    private_key_path: Path,
    *,
    signature_path: Path | None = None,
) -> dict[str, Any]:
    """Sign the raw manifest bytes and write a detached signature document."""
    private_key = load_private_key(private_key_path)
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise EvidenceSignatureError(f"evidence manifest could not be read: {exc}") from exc
    signature = private_key.sign(manifest_bytes)
    document = {
        "schema": EVIDENCE_SIGNATURE_SCHEMA,
        "algorithm": EVIDENCE_SIGNATURE_ALGORITHM,
        "manifest": manifest_path.name,
        "manifest_sha256": "sha256:" + sha256(manifest_bytes).hexdigest(),
        "public_key_sha256": _public_key_sha256(private_key.public_key()),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }
    target = signature_path or default_signature_path(manifest_path)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**document, "signature_path": str(target)}


def verify_evidence_manifest_signature(
    manifest_path: Path,
    public_key_path: Path,
    *,
    signature_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the detached collector signature over the raw manifest bytes.

    Every failure raises ``EvidenceSignatureError`` so the caller can only
    treat the bundle as collector-signed when all checks hold."""
    public_key = load_public_key(public_key_path)
    target = signature_path or default_signature_path(manifest_path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceSignatureError(f"evidence signature file is missing: {target}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceSignatureError(f"evidence signature file could not be read: {exc}") from exc
    if not isinstance(document, dict):
        raise EvidenceSignatureError("evidence signature file must be a JSON object")
    if document.get("schema") != EVIDENCE_SIGNATURE_SCHEMA:
        raise EvidenceSignatureError("evidence signature schema is unsupported")
    if document.get("algorithm") != EVIDENCE_SIGNATURE_ALGORITHM:
        raise EvidenceSignatureError("evidence signature algorithm is unsupported")
    expected_key_sha256 = _public_key_sha256(public_key)
    if document.get("public_key_sha256") != expected_key_sha256:
        raise EvidenceSignatureError("evidence signature was not produced by the configured collector key")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise EvidenceSignatureError(f"evidence manifest could not be read: {exc}") from exc
    manifest_sha256 = "sha256:" + sha256(manifest_bytes).hexdigest()
    if document.get("manifest_sha256") != manifest_sha256:
        raise EvidenceSignatureError("evidence signature does not match the manifest digest")
    try:
        signature = base64.b64decode(str(document.get("signature_b64") or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EvidenceSignatureError("evidence signature encoding is invalid") from exc
    try:
        public_key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise EvidenceSignatureError("evidence signature is invalid for the manifest bytes") from exc
    return {
        "schema": EVIDENCE_SIGNATURE_SCHEMA,
        "algorithm": EVIDENCE_SIGNATURE_ALGORITHM,
        "manifest_sha256": manifest_sha256,
        "public_key_sha256": expected_key_sha256,
        "signature_path": str(target),
        "verified": True,
    }
