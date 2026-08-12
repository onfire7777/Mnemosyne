"""Audit-log hash chaining: external HMAC anchor, tamper detection, CLI rail."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from mnemosyne.audit_chain import (
    LOCAL_HMAC_PROVIDER,
    VAULT_HMAC_PROVIDER,
    AuditChainError,
    build_audit_chain,
    canonical_entry_sha256,
    command_hmac_provider,
    local_hmac_provider,
    verify_audit_chain,
)

TENANT = "tenant-a"

ENTRIES = [
    {"tenant_id": TENANT, "operation": "capture", "actor": "user", "ts": "2026-07-04T00:00:00Z"},
    {"tenant_id": TENANT, "operation": "authorize", "actor": "agent", "decision": "allowed"},
    {"tenant_id": TENANT, "operation": "forget", "actor": "operator", "cid": "cid-1"},
]


def build_local_chain(entries: list[dict], secret: str = "dev-secret") -> dict:
    return build_audit_chain(
        entries,
        tenant_id=TENANT,
        provider_name=LOCAL_HMAC_PROVIDER,
        hmac_provider=local_hmac_provider(secret),
    )


def test_empty_audit_log_builds_and_verifies() -> None:
    # An audit log with zero entries must produce a verifiable (trivial) chain;
    # entry_count 0 is a real count, not a missing value.
    document = build_local_chain([])
    assert document["entry_count"] == 0
    assert document["head_link_sha256"] == "0" * 64
    result = verify_audit_chain(
        document,
        [],
        tenant_id=TENANT,
        hmac_provider=local_hmac_provider("dev-secret"),
    )
    assert result["verified"] is True
    assert result["entry_count"] == 0


def test_build_and_verify_round_trip_with_local_anchor() -> None:
    document = build_local_chain(ENTRIES)

    assert document["schema"] == "mnemosyne.audit_hash_chain.v1"
    assert document["provider"] == LOCAL_HMAC_PROVIDER
    assert document["non_production"] is True
    assert document["entry_count"] == 3
    assert len(document["links"]) == 3
    assert document["head_hmac"].startswith("local:")

    result = verify_audit_chain(
        document,
        ENTRIES,
        tenant_id=TENANT,
        hmac_provider=local_hmac_provider("dev-secret"),
    )
    assert result["verified"] is True
    assert result["entry_count"] == 3


def test_verify_detects_entry_tampering() -> None:
    document = build_local_chain(ENTRIES)
    tampered = [dict(entry) for entry in ENTRIES]
    tampered[1]["decision"] = "denied"

    with pytest.raises(AuditChainError, match="entry 1 does not match"):
        verify_audit_chain(document, tampered, tenant_id=TENANT, hmac_provider=local_hmac_provider("dev-secret"))


def test_verify_detects_truncation_and_unanchored_appends() -> None:
    document = build_local_chain(ENTRIES)

    with pytest.raises(AuditChainError, match="entry count mismatch"):
        verify_audit_chain(document, ENTRIES[:-1], tenant_id=TENANT, hmac_provider=local_hmac_provider("dev-secret"))
    with pytest.raises(AuditChainError, match="entry count mismatch"):
        verify_audit_chain(
            document,
            [*ENTRIES, {"tenant_id": TENANT, "operation": "late-insert"}],
            tenant_id=TENANT,
            hmac_provider=local_hmac_provider("dev-secret"),
        )


def test_verify_rejects_wrong_hmac_key_and_forged_head() -> None:
    document = build_local_chain(ENTRIES)

    with pytest.raises(AuditChainError, match="HMAC anchor does not verify"):
        verify_audit_chain(document, ENTRIES, tenant_id=TENANT, hmac_provider=local_hmac_provider("other-secret"))

    forged = dict(document)
    forged["head_hmac"] = "local:" + "0" * 64
    with pytest.raises(AuditChainError, match="HMAC anchor does not verify"):
        verify_audit_chain(forged, ENTRIES, tenant_id=TENANT, hmac_provider=local_hmac_provider("dev-secret"))


def test_verify_rejects_tenant_mismatch_and_bad_schema() -> None:
    document = build_local_chain(ENTRIES)

    with pytest.raises(AuditChainError, match="tenant does not match"):
        verify_audit_chain(document, ENTRIES, tenant_id="tenant-b", hmac_provider=local_hmac_provider("dev-secret"))
    with pytest.raises(AuditChainError, match="schema is unsupported"):
        verify_audit_chain({**document, "schema": "other"}, ENTRIES, tenant_id=TENANT, hmac_provider=local_hmac_provider("dev-secret"))


def test_canonical_entry_sha256_rejects_non_json_entries() -> None:
    with pytest.raises(AuditChainError, match="not canonical JSON"):
        canonical_entry_sha256({"bad": object()})


def vault_style_command() -> str:
    argv = [
        sys.executable,
        "-c",
        "import sys,hashlib,hmac;"
        "print('vault:v1:'+hmac.new(b'transit-key', sys.stdin.buffer.read(), hashlib.sha256).hexdigest())",
    ]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def test_command_hmac_provider_round_trip_and_failures() -> None:
    provider = command_hmac_provider(vault_style_command())
    document = build_audit_chain(
        ENTRIES,
        tenant_id=TENANT,
        provider_name=VAULT_HMAC_PROVIDER,
        hmac_provider=provider,
    )
    assert document["provider"] == VAULT_HMAC_PROVIDER
    assert document["non_production"] is False
    assert document["head_hmac"].startswith("vault:v1:")

    result = verify_audit_chain(document, ENTRIES, tenant_id=TENANT, hmac_provider=provider)
    assert result["verified"] is True

    failing = command_hmac_provider(shlex.join([sys.executable, "-c", "raise SystemExit(3)"]))
    with pytest.raises(AuditChainError, match="exited 3"):
        failing("deadbeef")
    silent = command_hmac_provider(shlex.join([sys.executable, "-c", "pass"]))
    with pytest.raises(AuditChainError, match="produced no output"):
        silent("deadbeef")


def run_raw_cli(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mnemosyne.cli", "--store", str(store), *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_cli_audit_chain_export_and_verify_round_trip(tmp_path: Path) -> None:
    store = tmp_path / "mnemosyne.json"
    capture = run_raw_cli(
        store,
        "capture",
        "--tenant",
        TENANT,
        "--user",
        "user-a",
        "--source-type",
        "chat",
        "--content",
        "audit chain fixture",
    )
    assert capture.returncode == 0, capture.stderr

    secret_file = tmp_path / "audit-hmac-secret"
    secret_file.write_text("dev-secret\n", encoding="utf-8")
    chain_file = tmp_path / "audit-chain.json"

    exported = run_raw_cli(
        store,
        "audit-chain-export",
        "--tenant",
        TENANT,
        "--output",
        str(chain_file),
        "--local-hmac-secret-file",
        str(secret_file),
    )
    assert exported.returncode == 0, exported.stderr
    summary = json.loads(exported.stdout)
    assert summary["ok"] is True
    assert summary["provider"] == LOCAL_HMAC_PROVIDER
    assert summary["non_production"] is True
    assert summary["entry_count"] >= 1

    verified = run_raw_cli(
        store,
        "audit-chain-verify",
        "--tenant",
        TENANT,
        "--chain-file",
        str(chain_file),
        "--local-hmac-secret-file",
        str(secret_file),
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["verified"] is True

    # Rewriting retained audit history must surface on verification.
    state = json.loads(store.read_text(encoding="utf-8"))
    assert state["audit_log"], "expected audit entries in the store"
    state["audit_log"][0]["operation"] = "rewritten"
    store.write_text(json.dumps(state), encoding="utf-8")

    tampered = run_raw_cli(
        store,
        "audit-chain-verify",
        "--tenant",
        TENANT,
        "--chain-file",
        str(chain_file),
        "--local-hmac-secret-file",
        str(secret_file),
    )
    assert tampered.returncode == 1
    assert "does not match" in json.loads(tampered.stdout)["error"]


def test_cli_audit_chain_requires_an_hmac_provider(tmp_path: Path) -> None:
    store = tmp_path / "mnemosyne.json"
    result = run_raw_cli(
        store,
        "audit-chain-export",
        "--tenant",
        TENANT,
        "--output",
        str(tmp_path / "chain.json"),
    )
    assert result.returncode != 0
    assert "requires --hmac-command" in result.stderr
