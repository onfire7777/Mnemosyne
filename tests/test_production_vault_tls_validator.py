from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "infra" / "validate" / "validate-production-vault-tls.sh"


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(
    *,
    subject: x509.Name,
    issuer: x509.Name,
    public_key: ec.EllipticCurvePublicKey,
    issuer_key: ec.EllipticCurvePrivateKey,
    is_ca: bool,
) -> x509.Certificate:
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if not is_ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("vault.mnemo.local")]),
            critical=False,
        ).add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root_key = ec.generate_private_key(ec.SECP256R1())
    intermediate_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    root_name = _name("Mnemosyne Test Root")
    intermediate_name = _name("Mnemosyne Test Intermediate")
    leaf_name = _name("vault.mnemo.local")
    root = _certificate(
        subject=root_name,
        issuer=root_name,
        public_key=root_key.public_key(),
        issuer_key=root_key,
        is_ca=True,
    )
    intermediate = _certificate(
        subject=intermediate_name,
        issuer=root_name,
        public_key=intermediate_key.public_key(),
        issuer_key=root_key,
        is_ca=True,
    )
    leaf = _certificate(
        subject=leaf_name,
        issuer=intermediate_name,
        public_key=leaf_key.public_key(),
        issuer_key=intermediate_key,
        is_ca=False,
    )
    root_path = tmp_path / "root.crt"
    bundle_path = tmp_path / "vault.crt"
    key_path = tmp_path / "vault.key"
    root_path.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    bundle_path.write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM)
        + intermediate.public_bytes(serialization.Encoding.PEM)
    )
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return root_path, bundle_path, key_path


def _run(root: Path, bundle: Path, key: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VALIDATOR), str(root), str(bundle), str(key)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_vault_tls_validator_accepts_matching_bundle(tmp_path: Path) -> None:
    root, bundle, key = _fixture(tmp_path)

    proc = _run(root, bundle, key)

    assert proc.returncode == 0
    assert proc.stdout == "production Vault TLS chain verified\n"
    assert proc.stderr == ""


def test_production_vault_tls_validator_rejects_stale_root(tmp_path: Path) -> None:
    _, bundle, key = _fixture(tmp_path)
    stale_key = ec.generate_private_key(ec.SECP256R1())
    stale_name = _name("Stale Root")
    stale_root = _certificate(
        subject=stale_name,
        issuer=stale_name,
        public_key=stale_key.public_key(),
        issuer_key=stale_key,
        is_ca=True,
    )
    stale_path = tmp_path / "stale-root.crt"
    stale_path.write_bytes(stale_root.public_bytes(serialization.Encoding.PEM))

    proc = _run(stale_path, bundle, key)

    assert proc.returncode == 65
    assert "does not validate against the current root CA" in proc.stderr


def test_production_vault_tls_validator_rejects_wrong_key(tmp_path: Path) -> None:
    root, bundle, _ = _fixture(tmp_path)
    wrong_key = ec.generate_private_key(ec.SECP256R1())
    wrong_path = tmp_path / "wrong.key"
    wrong_path.write_bytes(
        wrong_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    wrong_path.chmod(0o600)

    proc = _run(root, bundle, wrong_path)

    assert proc.returncode == 65
    assert "does not match the Vault leaf certificate" in proc.stderr
