from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


REPO = Path(__file__).resolve().parents[1]
ROTATOR = REPO / "infra" / "scripts" / "rotate-production-mcp-client-cert.sh"
DIAGNOSTIC = (
    REPO / "infra" / "validate" / "diagnose-production-mcp-client-tls-for-rotation.sh"
)
COMPOSE = REPO / "infra" / "docker-compose.prod.yml"
IMAGE = (
    "smallstep/step-ca:0.28.4@sha256:"
    "0f88382ac5af5c6b7bbba0c6e8fcefef52aee6f22ea364df8e02a09ffd0d22f3"
)


@dataclass(frozen=True)
class TlsFixture:
    secrets: Path
    root: Path
    bundle: Path
    key: Path
    password: Path
    root_key: ec.EllipticCurvePrivateKey
    root_cert: x509.Certificate
    intermediate_key: ec.EllipticCurvePrivateKey
    intermediate_cert: x509.Certificate


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(
    *,
    subject: x509.Name,
    issuer: x509.Name,
    public_key: ec.EllipticCurvePublicKey,
    issuer_key: ec.EllipticCurvePrivateKey,
    is_ca: bool,
    not_before: dt.datetime,
    not_after: dt.datetime,
    hostname: str = "mcp-client.mnemo.local",
    eku: ExtendedKeyUsageOID = ExtendedKeyUsageOID.CLIENT_AUTH,
) -> x509.Certificate:
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if not is_ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]),
            critical=False,
        ).add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


def _tls_fixture(
    tmp_path: Path,
    *,
    remaining: dt.timedelta = dt.timedelta(hours=13),
    stem: str = "current",
    expired: bool = False,
    not_yet_valid: bool = False,
    hostname: str = "mcp-client.mnemo.local",
    eku: ExtendedKeyUsageOID = ExtendedKeyUsageOID.CLIENT_AUTH,
    issuer: TlsFixture | None = None,
    intermediate_remaining: dt.timedelta = dt.timedelta(days=30),
    intermediate_starts_in: dt.timedelta = dt.timedelta(days=-2),
    leaf_started: dt.timedelta = dt.timedelta(minutes=-1),
) -> TlsFixture:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    root_key = issuer.root_key if issuer else ec.generate_private_key(ec.SECP256R1())
    intermediate_key = (
        issuer.intermediate_key if issuer else ec.generate_private_key(ec.SECP256R1())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    root_name = issuer.root_cert.subject if issuer else _name(f"{stem} root")
    intermediate_name = (
        issuer.intermediate_cert.subject if issuer else _name(f"{stem} intermediate")
    )
    leaf_name = _name(hostname)
    ca_before = now - dt.timedelta(days=2)
    intermediate_before = now + intermediate_starts_in
    root_after = now + dt.timedelta(days=30)
    intermediate_after = now + intermediate_remaining
    if expired:
        leaf_before = now - dt.timedelta(hours=2)
        leaf_after = now - dt.timedelta(hours=1)
    elif not_yet_valid:
        leaf_before = now + dt.timedelta(hours=1)
        leaf_after = now + dt.timedelta(hours=2)
    else:
        leaf_before = now + leaf_started
        leaf_after = now + remaining
    root = (
        issuer.root_cert
        if issuer
        else _certificate(
            subject=root_name,
            issuer=root_name,
            public_key=root_key.public_key(),
            issuer_key=root_key,
            is_ca=True,
            not_before=ca_before,
            not_after=root_after,
        )
    )
    intermediate = (
        issuer.intermediate_cert
        if issuer
        else _certificate(
            subject=intermediate_name,
            issuer=root_name,
            public_key=intermediate_key.public_key(),
            issuer_key=root_key,
            is_ca=True,
            not_before=intermediate_before,
            not_after=intermediate_after,
        )
    )
    leaf = _certificate(
        subject=leaf_name,
        issuer=intermediate_name,
        public_key=leaf_key.public_key(),
        issuer_key=intermediate_key,
        is_ca=False,
        not_before=leaf_before,
        not_after=leaf_after,
        hostname=hostname,
        eku=eku,
    )
    secrets = tmp_path / stem / "secrets"
    secrets.mkdir(parents=True)
    root_path = secrets / "stepca-acme-root.crt"
    bundle_path = secrets / "mcp-client.crt"
    key_path = secrets / "mcp-client.key"
    password_path = secrets / "step-ca-jwk-provisioner-password"
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
    password_path.write_text("provisioner-canary-must-never-leak\n", encoding="utf-8")
    password_path.chmod(0o600)
    return TlsFixture(
        secrets,
        root_path,
        bundle_path,
        key_path,
        password_path,
        root_key,
        root,
        intermediate_key,
        intermediate,
    )


def _write_fake_docker(
    tmp_path: Path,
    staged: TlsFixture,
    *,
    fail_issuance: bool = False,
    child_canary: str = "",
    context: str = "colima",
    network_project: str = "infra",
    network_name: str = "internal",
    image_present: bool = True,
    cli_version: str = "Smallstep CLI/0.28.7",
    staged_cert_mode: int = 0o644,
) -> tuple[Path, Path]:
    record = tmp_path / "docker-record.json"
    docker = tmp_path / "fake-docker"
    docker.write_text(
        f"""#!{sys.executable}
import json
import os
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
record = Path({str(record)!r})
# macOS injects this after exec into Python processes; the Docker binary does not.
os.environ.pop("__CF_USER_TEXT_ENCODING", None)
if args == ["context", "show"]:
    print({context!r})
    raise SystemExit(0)
if args[:5] == ["--context", "colima", "network", "inspect", "infra_internal"]:
    print(json.dumps({{
        "Name": "infra_internal",
        "Internal": True,
        "Labels": {{
            "com.docker.compose.project": {network_project!r},
            "com.docker.compose.network": {network_name!r},
        }},
    }}))
    raise SystemExit(0)
if args[:4] == ["--context", "colima", "image", "inspect"]:
    raise SystemExit(0 if {image_present!r} and args[4] == {IMAGE!r} else 1)
if "run" not in args:
    raise SystemExit(97)
if args[-1] == "version":
    print({cli_version!r})
    raise SystemExit(0)
record.write_text(json.dumps({{"argv": args, "env": dict(os.environ)}}))
if {child_canary!r}:
    print({child_canary!r}, file=sys.stderr)
if {fail_issuance!r}:
    raise SystemExit(42)
stage = None
for index, value in enumerate(args):
    if value == "--mount" and index + 1 < len(args):
        mount = args[index + 1]
        if "dst=/work" in mount:
            stage = mount.split("src=", 1)[1].split(",dst=", 1)[0]
if stage is None:
    raise SystemExit(98)
stage_path = Path(stage)
shutil.copyfile({str(staged.bundle)!r}, stage_path / "mcp-client.crt")
shutil.copyfile({str(staged.key)!r}, stage_path / "mcp-client.key")
(stage_path / "mcp-client.crt").chmod({staged_cert_mode!r})
(stage_path / "mcp-client.key").chmod(0o600)
""",
        encoding="utf-8",
    )
    docker.chmod(0o700)
    return docker, record


def _rotator_env(fixture: TlsFixture, docker: Path, stage: Path) -> dict[str, str]:
    return {
        **os.environ,
        "AWS_SECRET_ACCESS_KEY": "ambient-env-canary-must-not-leak",
        "MNEMO_SECRETS_DIR": str(fixture.secrets),
        "MCP_CLIENT_ROTATOR_COMPOSE_FILE": str(COMPOSE),
        "MCP_CLIENT_ROTATOR_DOCKER_BIN": str(docker),
        "MCP_CLIENT_ROTATOR_STAGE_DIR": str(stage),
    }


def _stage_path(fixture: TlsFixture, name: str = "stage") -> Path:
    rotation = fixture.secrets / ".mcp-client-rotation"
    rotation.mkdir(exist_ok=True)
    rotation.chmod(0o700)
    return rotation / name


def _run_rotator(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROTATOR), *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )


def _run_diagnostic(
    fixture: TlsFixture,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MCP_CLIENT_TLS_HOSTNAME": "hostile-ambient.invalid",
        "MNEMO_SECRETS_DIR": str(fixture.secrets),
    }
    env.update(extra_env or {})
    return subprocess.run(
        [str(DIAGNOSTIC), str(fixture.root), str(fixture.bundle), str(fixture.key)],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (43_201, "healthy"),
        (43_200, "renewal_due"),
        (21_601, "renewal_due"),
        (21_600, "hard_floor"),
        (7_201, "hard_floor"),
        (7_200, "emergency"),
        (1, "emergency"),
        (0, "emergency"),
        (-1, "expired"),
    ],
)
def test_lifetime_boundaries_use_exact_seconds(seconds: int, expected: str) -> None:
    proc = _run_rotator(os.environ.copy(), "--classify-remaining", str(seconds))

    assert proc.returncode == 0
    assert proc.stdout == f"mcp-client-rotation renewal_state={expected}\n"
    assert proc.stderr == ""


def test_renewal_above_twelve_hours_is_noop_without_docker(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=13))
    stage = tmp_path / "unused-stage"
    env = _rotator_env(current, tmp_path / "missing-docker", stage)

    proc = _run_rotator(env)

    assert proc.returncode == 0
    assert proc.stdout == "mcp-client-rotation result=healthy_noop\n"
    assert proc.stderr == ""
    assert not stage.exists()


@pytest.mark.parametrize(
    ("remaining", "expired"),
    [
        (dt.timedelta(hours=8), False),
        (dt.timedelta(hours=5), False),
        (dt.timedelta(hours=1), False),
        (dt.timedelta(), True),
    ],
)
def test_renewal_stages_valid_replacement_with_hardened_exact_argv(
    tmp_path: Path,
    remaining: dt.timedelta,
    expired: bool,
) -> None:
    current = _tls_fixture(
        tmp_path, remaining=remaining, expired=expired, stem="current"
    )
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(tmp_path, staged)
    stage = _stage_path(current, "issued-stage")

    proc = _run_rotator(_rotator_env(current, docker, stage))

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "mcp-client-rotation result=staged_only\n"
    assert proc.stderr == ""
    payload = json.loads(record.read_text(encoding="utf-8"))
    argv = payload["argv"]
    assert argv == [
        "--context",
        "colima",
        "run",
        "--rm",
        "--pull",
        "never",
        "--read-only",
        "--user",
        "1000:1000",
        "--pids-limit",
        "64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--network",
        "infra_internal",
        "--entrypoint",
        "/usr/local/bin/step",
        "--mount",
        f"type=bind,src={current.root},dst=/run/mnemo/root.crt,readonly",
        "--mount",
        (
            f"type=bind,src={current.password},"
            "dst=/run/mnemo/provisioner-password,readonly"
        ),
        "--mount",
        f"type=bind,src={stage},dst=/work",
        IMAGE,
        "ca",
        "certificate",
        "--ca-url",
        "https://ca.mnemo.local:9000",
        "--root",
        "/run/mnemo/root.crt",
        "--provisioner",
        "admin",
        "--provisioner-password-file",
        "/run/mnemo/provisioner-password",
        "--san",
        "mcp-client.mnemo.local",
        "--not-after",
        "24h",
        "mcp-client.mnemo.local",
        "/work/mcp-client.crt",
        "/work/mcp-client.key",
    ]
    output = proc.stdout + proc.stderr + json.dumps(payload)
    assert "provisioner-canary-must-never-leak" not in output
    assert "ambient-env-canary-must-not-leak" not in output
    assert set(payload["env"]) <= {"HOME", "LC_ALL", "PATH", "TMPDIR"}


def test_issuance_failure_redacts_child_output_and_uses_fixed_exit(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    child_canary = "child-output-canary-must-not-leak"
    docker, _ = _write_fake_docker(
        tmp_path, staged, fail_issuance=True, child_canary=child_canary
    )

    proc = _run_rotator(
        _rotator_env(current, docker, _stage_path(current, "failed-issuance-stage"))
    )

    assert proc.returncode == 70
    assert proc.stdout == "mcp-client-rotation result=issuance_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: staged issuance failed\n"
    assert child_canary not in proc.stdout + proc.stderr


def test_preflight_missing_docker_is_runtime_unavailable(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))

    proc = _run_rotator(
        _rotator_env(
            current,
            tmp_path / "missing-docker",
            _stage_path(current),
        )
    )

    assert proc.returncode == 69
    assert proc.stdout == "mcp-client-rotation result=runtime_unavailable\n"
    assert proc.stderr == "mcp-client-rotation failed: Docker is unavailable\n"


@pytest.mark.parametrize(
    ("context", "network_project", "image_present", "cli_version"),
    [
        ("desktop-linux", "infra", True, "Smallstep CLI/0.28.7"),
        ("colima", "foreign", True, "Smallstep CLI/0.28.7"),
        ("colima", "infra", False, "Smallstep CLI/0.28.7"),
        ("colima", "infra", True, "Smallstep CLI/0.28.6"),
    ],
    ids=["ambient-context", "foreign-network", "missing-image", "wrong-cli"],
)
def test_preflight_rejects_untrusted_docker_runtime_without_issuance(
    tmp_path: Path,
    context: str,
    network_project: str,
    image_present: bool,
    cli_version: str,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(
        tmp_path,
        staged,
        context=context,
        network_project=network_project,
        image_present=image_present,
        cli_version=cli_version,
    )

    proc = _run_rotator(_rotator_env(current, docker, _stage_path(current)))

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert not record.exists()


@pytest.mark.parametrize("remaining", [dt.timedelta(hours=5), dt.timedelta(hours=1)])
def test_renewal_rotation_diagnostic_accepts_only_near_expiry_source(
    tmp_path: Path, remaining: dt.timedelta
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=remaining)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "production MCP client TLS rotation source verified\n"
    assert proc.stderr == ""


def test_renewal_rotation_diagnostic_accepts_structurally_valid_expired_source(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, expired=True)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 0, proc.stderr


def test_renewal_rotation_diagnostic_rejects_source_normal_validator_accepts(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert "normal validator still accepts source pair" in proc.stderr


def test_preflight_rotation_diagnostic_rejects_non_leaf_horizon_failure(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=13),
        intermediate_remaining=dt.timedelta(hours=5),
    )

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


@pytest.mark.parametrize(
    ("intermediate_remaining", "intermediate_starts_in", "leaf_started"),
    [
        (
            dt.timedelta(minutes=-30),
            dt.timedelta(days=-2),
            dt.timedelta(hours=-2),
        ),
        (
            dt.timedelta(hours=4),
            dt.timedelta(minutes=30),
            dt.timedelta(minutes=-1),
        ),
    ],
    ids=["expired-intermediate", "future-intermediate"],
)
def test_preflight_rotation_diagnostic_requires_current_chain_for_live_leaf(
    tmp_path: Path,
    intermediate_remaining: dt.timedelta,
    intermediate_starts_in: dt.timedelta,
    leaf_started: dt.timedelta,
) -> None:
    fixture = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=5),
        intermediate_remaining=intermediate_remaining,
        intermediate_starts_in=intermediate_starts_in,
        leaf_started=leaf_started,
    )

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_requires_checkend_capability(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    real_openssl = shutil.which("openssl")
    assert real_openssl
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_openssl = fake_bin / "openssl"
    fake_openssl.write_text(
        f"""#!{sys.executable}
import os
import sys

if sys.argv[1:] == ["x509", "-help"]:
    print("x509 help without required capability", file=sys.stderr)
    raise SystemExit(0)
os.execv({real_openssl!r}, [{real_openssl!r}, *sys.argv[1:]])
""",
        encoding="utf-8",
    )
    fake_openssl.chmod(0o700)

    proc = _run_diagnostic(
        fixture,
        extra_env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_copied_source_paths(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    outside = tmp_path / "outside"
    outside.mkdir()
    copied_bundle = outside / fixture.bundle.name
    copied_key = outside / fixture.key.name
    shutil.copyfile(fixture.bundle, copied_bundle)
    shutil.copyfile(fixture.key, copied_key)
    copied_key.chmod(0o600)

    proc = subprocess.run(
        [str(DIAGNOSTIC), str(fixture.root), str(copied_bundle), str(copied_key)],
        cwd=REPO,
        env={**os.environ, "MNEMO_SECRETS_DIR": str(fixture.secrets)},
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 65
    assert proc.stdout == ""


@pytest.mark.parametrize("case", ["wrong-key", "malformed-chain", "encrypted"])
def test_preflight_rotation_diagnostic_rejects_non_time_failures(
    tmp_path: Path, case: str
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    if case == "wrong-key":
        other = ec.generate_private_key(ec.SECP256R1())
        fixture.key.write_bytes(
            other.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    elif case == "malformed-chain":
        leaf = x509.load_pem_x509_certificate(fixture.bundle.read_bytes())
        fixture.bundle.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    else:
        private_key = serialization.load_pem_private_key(
            fixture.key.read_bytes(), password=None
        )
        fixture.key.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(b"encrypted-canary"),
            )
        )
    fixture.key.chmod(0o600)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_wrong_root_only(tmp_path: Path) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    wrong_root = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=1),
        stem="wrong-root",
    )
    fixture.root.write_bytes(wrong_root.root.read_bytes())

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_wrong_eku_only(tmp_path: Path) -> None:
    fixture = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=1),
        eku=ExtendedKeyUsageOID.SERVER_AUTH,
    )

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_unsafe_key_mode(tmp_path: Path) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    fixture.key.chmod(0o644)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_final_key_symlink(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    target = fixture.secrets / "mcp-client-real.key"
    fixture.key.rename(target)
    fixture.key.symlink_to(target.name)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert proc.stdout == ""


def test_preflight_rotation_diagnostic_rejects_not_yet_valid_source(
    tmp_path: Path,
) -> None:
    fixture = _tls_fixture(tmp_path, not_yet_valid=True)

    proc = _run_diagnostic(fixture)

    assert proc.returncode == 65
    assert "source certificate is not yet valid" in proc.stderr


def test_preflight_rotation_diagnostic_rejects_symlinked_parent(tmp_path: Path) -> None:
    fixture = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=1))
    linked = tmp_path / "linked-secrets"
    linked.symlink_to(fixture.secrets, target_is_directory=True)
    linked_fixture = TlsFixture(
        linked,
        linked / fixture.root.name,
        linked / fixture.bundle.name,
        linked / fixture.key.name,
        linked / fixture.password.name,
        fixture.root_key,
        fixture.root_cert,
        fixture.intermediate_key,
        fixture.intermediate_cert,
    )

    proc = _run_diagnostic(linked_fixture)

    assert proc.returncode == 65
    assert "path components must not be symlinks" in proc.stderr


def test_preflight_staged_validator_failure_is_issuance_failure(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    invalid = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=1),
        stem="invalid-stage",
        issuer=current,
    )
    docker, _ = _write_fake_docker(tmp_path, invalid)

    proc = _run_rotator(_rotator_env(current, docker, _stage_path(current)))

    assert proc.returncode == 70
    assert proc.stdout == "mcp-client-rotation result=issuance_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: staged validation failed\n"


def test_preflight_staged_certificate_unsafe_mode_is_issuance_failure(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, _ = _write_fake_docker(tmp_path, staged, staged_cert_mode=0o666)

    proc = _run_rotator(_rotator_env(current, docker, _stage_path(current)))

    assert proc.returncode == 70
    assert proc.stdout == "mcp-client-rotation result=issuance_failed\n"
    assert proc.stderr == "mcp-client-rotation failed: staged validation failed\n"


def test_preflight_stage_must_be_inside_canonical_rotation_directory(
    tmp_path: Path,
) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8), stem="current")
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(tmp_path, staged)

    proc = _run_rotator(_rotator_env(current, docker, tmp_path / "outside-stage"))

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert not record.exists()


def test_preflight_existing_stage_is_never_overwritten(tmp_path: Path) -> None:
    current = _tls_fixture(tmp_path, remaining=dt.timedelta(hours=8))
    staged = _tls_fixture(
        tmp_path,
        remaining=dt.timedelta(hours=24),
        stem="staged",
        issuer=current,
    )
    docker, record = _write_fake_docker(tmp_path, staged)
    stage = _stage_path(current, "existing-stage")
    stage.mkdir()
    sentinel = stage / "sentinel"
    sentinel.write_text("owned", encoding="utf-8")

    proc = _run_rotator(_rotator_env(current, docker, stage))

    assert proc.returncode == 65
    assert proc.stdout == "mcp-client-rotation result=preflight_failed\n"
    assert sentinel.read_text(encoding="utf-8") == "owned"
    assert not record.exists()


def test_preflight_validator_source_is_unchanged() -> None:
    validator = REPO / "infra" / "validate" / "validate-production-mcp-client-tls.sh"
    assert shutil.which("openssl")
    assert "may not weaken the 21600-second floor" in validator.read_text(
        encoding="utf-8"
    )
