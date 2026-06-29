from __future__ import annotations

import json

from mnemosyne.evidence_redaction import redaction_findings, redaction_scan


def test_redaction_findings_ignores_secret_custody_words_without_secret_shapes() -> None:
    text = (
        "Use MNEMOSYNE_IDP_TOKEN from the environment. "
        "Do not put password, token, secret, or private-key material in docs."
    )

    assert redaction_findings("runbook.md", text) == []


def test_redaction_findings_reports_anthropic_key_once() -> None:
    text = "api_key=sk-ant-1234567890abcdefghijklmnopqrstuvwxyz"

    assert redaction_findings("evidence.json", text) == [
        {
            "source": "evidence.json",
            "line": 1,
            "kind": "anthropic_api_key",
        }
    ]


def test_redaction_findings_reports_short_opaque_secret_json_fields() -> None:
    text = '{"api_key": "short-prod-token", "client_secret": "opaque-value", "api_key_env": "KEY_ENV"}'

    findings = redaction_findings("hosted-llm-manifest.json", text)

    assert [
        {key: finding[key] for key in ("source", "line", "kind", "path")}
        for finding in findings
    ] == [
        {
            "source": "hosted-llm-manifest.json",
            "line": 1,
            "kind": "structured_secret_key",
            "path": "$.api_key",
        },
        {
            "source": "hosted-llm-manifest.json",
            "line": 1,
            "kind": "structured_secret_key",
            "path": "$.client_secret",
        },
    ]


def test_redaction_findings_allows_redaction_proof_flags() -> None:
    text = '{"raw_credentials_omitted": true, "secret_source": "vault", "token_sha256": "abc123"}'

    assert redaction_findings("ops-report.json", text) == []


def test_redaction_findings_allows_structured_secret_proof_objects() -> None:
    text = json.dumps(
        {
            "session_secret": {
                "active_key_id_present": True,
                "key_count": 2,
                "roundtrip_verified": True,
                "source": "keyring",
            },
            "token": {
                "claims_hash": "sha256:" + ("1" * 64),
            },
        }
    )

    assert redaction_findings("production-evidence.json", text) == []


def test_redaction_scan_fails_closed_on_skipped_files() -> None:
    scan = redaction_scan(
        scope="capture",
        scanned_files=["evidence/manifest.json"],
        findings=[],
        skipped_files=[{"path": "evidence/blob.bin", "reason": "not utf-8 text"}],
    )

    assert scan["ok"] is False
    assert scan["skipped_files"] == [{"path": "evidence/blob.bin", "reason": "not utf-8 text"}]
