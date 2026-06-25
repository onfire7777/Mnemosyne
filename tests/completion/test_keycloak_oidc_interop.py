"""Real-Keycloak OIDC interop evidence (INFRA E2E completion run).

This is a *net-new* completion test (it does not touch the Codex `src/mnemosyne`
surface). It re-proves, against the live Keycloak provider stack, that a real
RS256 ID token minted by Keycloak verifies through Mnemosyne's
`OidcSessionVerifier` and round-trips the claim mapping
(tenant-a / agent / trust-tier 3) into a Mnemosyne session.

It is skipped automatically unless the live stack + setup outputs are present:

    docker compose -f infra/docker-compose.providers.yml up -d keycloak vault
    ./infra/scripts/setup-keycloak.sh
    pytest tests/completion/test_keycloak_oidc_interop.py

REGRESSION NOTE
---------------
A standard Keycloak realm publishes an RS256 ``sig`` key for ID-token signing
and an RSA-OAEP ``enc`` key for encryption. Mnemosyne must skip the non-signing
``enc`` key while still verifying the real token against the published signing
key. The full-JWKS test below guards that interop path.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KC_OUT = REPO / "infra" / "keycloak" / "out"
ISSUER = "http://localhost:8089/realms/mnemosyne"
AUDIENCE = "mnemosyne"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"


def _keycloak_up() -> bool:
    try:
        with urllib.request.urlopen(JWKS_URL, timeout=3) as resp:  # noqa: S310 - local dev provider
            return resp.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _keycloak_up() or not (KC_OUT / "oidc.env").exists(),
    reason="live Keycloak provider stack + setup-keycloak.sh outputs required",
)


def _mint_token() -> str:
    data = "&".join(
        [
            "grant_type=password",
            "client_id=mnemosyne-cli",
            "client_secret=mnemosyne-cli-secret",
            "username=agent-a",
            "password=agent-a-password",
            "scope=openid mnemosyne",
        ]
    ).encode()
    req = urllib.request.Request(  # noqa: S310 - local dev provider
        TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read())["id_token"]


def _sig_only_jwks(tmp_path: Path) -> Path:
    with urllib.request.urlopen(JWKS_URL, timeout=10) as resp:  # noqa: S310
        jwks = json.loads(resp.read())
    sig = {"keys": [k for k in jwks["keys"] if k.get("use") == "sig"]}
    assert sig["keys"], "Keycloak JWKS unexpectedly has no sig key"
    path = tmp_path / "jwks.sig-only.json"
    path.write_text(json.dumps(sig))
    return path


def _run_cli(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("MNEMOSYNE_IDP_")}
    full_env.update(env)
    return subprocess.run(
        [str(REPO / ".venv" / "bin" / "python"), "-m", "mnemosyne.cli", *args],
        cwd=REPO,
        env=full_env,
        capture_output=True,
        text=True,
    )


def test_real_keycloak_token_round_trips_into_session(tmp_path):
    token = _mint_token()
    jwks_file = _sig_only_jwks(tmp_path)

    proc = _run_cli(
        [
            "--session-secret",
            "mnemosyne-local-session-secret",
            "session-exchange",
            "--idp-token",
            token,
            "--idp-jwks-file",
            str(jwks_file),
            "--idp-issuer",
            ISSUER,
            "--idp-audience",
            AUDIENCE,
            "--idp-algorithm",
            "RS256",
        ],
        env={},
    )
    assert proc.returncode == 0, f"session-exchange failed: {proc.stdout}\n{proc.stderr}"
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["identity"]["tenant_id"] == "tenant-a"
    assert result["identity"]["role"] == "agent"
    assert result["identity"]["source_trust_tier"] == 3
    assert isinstance(result["session_token"], str) and result["session_token"]


def test_wrong_audience_is_rejected(tmp_path):
    token = _mint_token()
    jwks_file = _sig_only_jwks(tmp_path)
    proc = _run_cli(
        [
            "--session-secret",
            "mnemosyne-local-session-secret",
            "session-exchange",
            "--idp-token",
            token,
            "--idp-jwks-file",
            str(jwks_file),
            "--idp-issuer",
            ISSUER,
            "--idp-audience",
            "wrong-audience",
            "--idp-algorithm",
            "RS256",
        ],
        env={},
    )
    assert proc.returncode != 0, "wrong audience must be rejected (fail-closed)"


def test_full_jwks_skips_enc_key_and_succeeds(tmp_path):
    """Reconciliation tripwire (now GREEN): the unfiltered Keycloak JWKS — which
    includes an `enc` key alongside the `sig` key — must be ACCEPTED because
    src/mnemosyne/security.py now skips non-signing keys instead of rejecting the
    whole key set.

    Flipped from the former ``test_full_jwks_currently_blocks_on_enc_key`` bug
    characterization per that test's own instruction. Asserts the full
    session-exchange success shape (not just exit code) so a silent/empty
    acceptance cannot pass.
    """
    token = _mint_token()
    with urllib.request.urlopen(JWKS_URL, timeout=10) as resp:  # noqa: S310
        full = resp.read()
    jwks_file = tmp_path / "jwks.full.json"
    jwks_file.write_bytes(full)
    proc = _run_cli(
        [
            "--session-secret",
            "mnemosyne-local-session-secret",
            "session-exchange",
            "--idp-token",
            token,
            "--idp-jwks-file",
            str(jwks_file),
            "--idp-issuer",
            ISSUER,
            "--idp-audience",
            AUDIENCE,
            "--idp-algorithm",
            "RS256",
        ],
        env={},
    )
    # Fixed behavior: enc keys are skipped, the sig key verifies the token.
    assert proc.returncode == 0, (
        f"full Keycloak JWKS must be accepted (enc key skipped): "
        f"{proc.stdout}\n{proc.stderr}"
    )
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["identity"]["tenant_id"] == "tenant-a"
    assert result["identity"]["role"] == "agent"
    assert result["identity"]["source_trust_tier"] == 3
    assert isinstance(result["session_token"], str) and result["session_token"]
