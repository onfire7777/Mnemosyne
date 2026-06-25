from __future__ import annotations

from mnemosyne.evidence_redaction import redaction_findings


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
