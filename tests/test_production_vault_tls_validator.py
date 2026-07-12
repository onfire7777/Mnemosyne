from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "infra" / "validate" / "validate-production-vault-tls.sh"
MCP_VALIDATOR = REPO / "infra" / "validate" / "validate-production-mcp-client-tls.sh"


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(
    *,
    subject: x509.Name,
    issuer: x509.Name,
    public_key: ec.EllipticCurvePublicKey,
    issuer_key: ec.EllipticCurvePrivateKey,
    is_ca: bool,
    hostname: str = "vault.mnemo.local",
    extended_key_usage: ExtendedKeyUsageOID = ExtendedKeyUsageOID.SERVER_AUTH,
    valid_for: dt.timedelta = dt.timedelta(days=30),
) -> x509.Certificate:
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + valid_for)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if not is_ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]),
            critical=False,
        ).add_extension(
            x509.ExtendedKeyUsage([extended_key_usage]),
            critical=False,
        )
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


def _fixture(
    tmp_path: Path,
    *,
    hostname: str = "vault.mnemo.local",
    extended_key_usage: ExtendedKeyUsageOID = ExtendedKeyUsageOID.SERVER_AUTH,
    valid_for: dt.timedelta = dt.timedelta(days=30),
    intermediate_valid_for: dt.timedelta = dt.timedelta(days=30),
    stem: str = "vault",
) -> tuple[Path, Path, Path]:
    root_key = ec.generate_private_key(ec.SECP256R1())
    intermediate_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    root_name = _name("Mnemosyne Test Root")
    intermediate_name = _name("Mnemosyne Test Intermediate")
    leaf_name = _name(hostname)
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
        valid_for=intermediate_valid_for,
    )
    leaf = _certificate(
        subject=leaf_name,
        issuer=intermediate_name,
        public_key=leaf_key.public_key(),
        issuer_key=intermediate_key,
        is_ca=False,
        hostname=hostname,
        extended_key_usage=extended_key_usage,
        valid_for=valid_for,
    )
    root_path = tmp_path / f"{stem}-root.crt"
    bundle_path = tmp_path / f"{stem}.crt"
    key_path = tmp_path / f"{stem}.key"
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


def _run(
    root: Path,
    bundle: Path,
    key: Path,
    *,
    validator: Path = VALIDATOR,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: float = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(validator), str(root), str(bundle), str(key)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        input=stdin,
        timeout=timeout,
    )


def _mcp_env(
    tmp_path: Path,
    canonical_root: Path,
    **overrides: str,
) -> dict[str, str]:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    (secrets_dir / "stepca-acme-root.crt").write_bytes(canonical_root.read_bytes())
    return {
        **os.environ,
        "MNEMO_SECRETS_DIR": str(secrets_dir),
        **overrides,
    }


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
    assert "does not match the leaf certificate" in proc.stderr


def test_production_tls_validator_rejects_symlinked_private_key(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(tmp_path)
    linked_key = tmp_path / "linked.key"
    linked_key.symlink_to(key)

    proc = _run(root, bundle, linked_key)

    assert proc.returncode == 65
    assert "must not be symlinks" in proc.stderr


def test_production_tls_validator_rejects_group_readable_private_key(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(tmp_path)
    key.chmod(0o640)

    proc = _run(root, bundle, key)

    assert proc.returncode == 65
    assert "private key must not be group/world accessible" in proc.stderr


def test_production_tls_validator_rejects_missing_openssl_capabilities(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(tmp_path)
    real_openssl = shutil.which("openssl")
    assert real_openssl is not None
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_openssl = fake_bin / "openssl"
    fake_openssl.write_text(
        """#!/bin/sh
if [ "$#" -ge 2 ] && [ "$2" = "-help" ]; then
  printf 'Usage: %s\\n' "$1" >&2
  exit 0
fi
exec "$REAL_OPENSSL" "$@"
""",
        encoding="utf-8",
    )
    fake_openssl.chmod(0o755)

    proc = _run(
        root,
        bundle,
        key,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "REAL_OPENSSL": real_openssl,
        },
    )

    assert proc.returncode == 65
    assert "openssl is missing required capabilities" in proc.stderr
    assert "verify -verify_hostname" in proc.stderr
    assert "verify -attime" in proc.stderr
    assert "x509 -checkend" in proc.stderr


def test_production_tls_validator_rejects_encrypted_private_key_without_prompt(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(tmp_path)
    passphrase = b"fixture-passphrase-must-not-leak"
    private_key = serialization.load_pem_private_key(key.read_bytes(), password=None)
    encrypted_key = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase),
    )
    key.write_bytes(encrypted_key)
    key.chmod(0o600)

    proc = _run(
        root,
        bundle,
        key,
        stdin=f"{passphrase.decode()}\n",
        timeout=3,
    )

    output = proc.stdout + proc.stderr
    assert proc.returncode == 65
    assert "private key could not be read" in proc.stderr
    assert passphrase.decode() not in output
    assert encrypted_key.decode() not in output


def test_production_mcp_client_tls_validator_accepts_matching_bundle(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(tmp_path, root),
    )

    assert proc.returncode == 0
    assert proc.stdout == "production MCP client TLS chain verified\n"
    assert proc.stderr == ""


def test_production_mcp_client_tls_validator_rejects_server_only_bundle(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(tmp_path, root),
    )

    assert proc.returncode == 65
    assert "hostname, and purpose" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_near_expiry(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        valid_for=dt.timedelta(minutes=30),
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(tmp_path, root),
    )

    assert proc.returncode == 65
    assert "inside the minimum validity window" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_future_chain_expiry(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        intermediate_valid_for=dt.timedelta(minutes=30),
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(tmp_path, root),
    )

    assert proc.returncode == 65
    assert "chain is not valid through the minimum validity window" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_wrong_hostname(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="other-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(tmp_path, root),
    )

    assert proc.returncode == 65
    assert "hostname, and purpose" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_invalid_expiry_floor(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(
            tmp_path,
            root,
            MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS="six-hours",
        ),
    )

    assert proc.returncode == 65
    assert "must be an integer of at least 21600" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_weakened_expiry_floor(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(
            tmp_path,
            root,
            MCP_CLIENT_TLS_MIN_VALIDITY_SECONDS="0",
        ),
    )

    assert proc.returncode == 65
    assert "may not weaken the 21600-second floor" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_dual_root_trust_pool(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )
    other_root, _, _ = _fixture(tmp_path, stem="other")
    env = _mcp_env(tmp_path, root)
    canonical_root = Path(env["MNEMO_SECRETS_DIR"]) / "stepca-acme-root.crt"
    canonical_root.write_bytes(canonical_root.read_bytes() + other_root.read_bytes())

    proc = _run(
        canonical_root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=env,
    )

    assert proc.returncode == 65
    assert "canonical Caddy client-auth root must contain exactly one certificate" in (
        proc.stderr
    )


def test_production_mcp_client_tls_validator_rejects_noncanonical_caller_root(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )
    canonical_root, _, _ = _fixture(tmp_path, stem="canonical")

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env=_mcp_env(tmp_path, canonical_root),
    )

    assert proc.returncode == 65
    assert "caller root must match the canonical Caddy client-auth root" in proc.stderr


def test_production_mcp_client_tls_validator_rejects_symlinked_canonical_root(
    tmp_path: Path,
) -> None:
    root, bundle, key = _fixture(
        tmp_path,
        hostname="mcp-client.mnemo.local",
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
        stem="mcp-client",
    )
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "stepca-acme-root.crt").symlink_to(root)

    proc = _run(
        root,
        bundle,
        key,
        validator=MCP_VALIDATOR,
        env={**os.environ, "MNEMO_SECRETS_DIR": str(secrets_dir)},
    )

    assert proc.returncode == 65
    assert "canonical Caddy client-auth root must be a regular non-symlink file" in (
        proc.stderr
    )
