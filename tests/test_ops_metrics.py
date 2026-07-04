"""Tests for the ops-report metrics exposition and guarded push path."""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading

import pytest

from mnemosyne.ops_metrics import (
    ops_report_fingerprint,
    ops_report_to_prometheus,
    push_ops_metrics,
)

SAMPLE_REPORT = {
    "tenant_id": "primary",
    "counts": {"evidence": 12, "assertions": 7, "deletions": 0, "audit_events": 44},
    "queue": {"pending": 2, "running": 0, "kind": "postgres"},
    "learning": {"lessons": 3, "procedures": 1, "lesson_diversity": 0.8},
    "tripwires": {"passed": True, "open_contradictions": 0},
}


def test_exposition_emits_tripwire_series_and_fingerprint() -> None:
    text = ops_report_to_prometheus(SAMPLE_REPORT, tenant_id="primary", now_seconds=1000.0)
    assert 'mnemosyne_ops_report_timestamp_seconds{tenant="primary"} 1000.000' in text
    assert 'mnemosyne_release_gate_open{tenant="primary"} 0' in text
    assert 'mnemosyne_tripwires_passed{tenant="primary"} 1' in text
    fingerprint = ops_report_fingerprint(SAMPLE_REPORT)
    assert len(fingerprint) == 64
    assert f'fingerprint="{fingerprint}"' in text
    assert 'mnemosyne_count{tenant="primary",kind="evidence"} 12' in text
    assert 'mnemosyne_queue_pending{tenant="primary"} 2' in text
    assert 'mnemosyne_learning_lesson_diversity{tenant="primary"} 0.8' in text
    # non-numeric queue fields never leak into the exposition
    assert "postgres" not in text


def test_exposition_opens_gate_when_tripwires_fail() -> None:
    failing = {**SAMPLE_REPORT, "tripwires": {"passed": False}}
    text = ops_report_to_prometheus(failing, tenant_id="primary", now_seconds=5.0)
    assert 'mnemosyne_release_gate_open{tenant="primary"} 1' in text
    assert 'mnemosyne_tripwires_passed{tenant="primary"} 0' in text


def test_exposition_sanitizes_label_values() -> None:
    text = ops_report_to_prometheus(
        SAMPLE_REPORT, tenant_id='ten"ant}\nx', now_seconds=1.0
    )
    assert '"' not in text.split("{", 1)[1].split("}", 1)[0].replace('="', "").replace('"', "")
    assert 'tenant="ten_ant__x"' in text


def test_push_rejects_internal_host_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_OPS_METRICS_ALLOWED_INTERNAL_HOSTS", raising=False)
    with pytest.raises(ValueError):
        push_ops_metrics("http://victoriametrics:8428/api/v1/import/prometheus", "x 1\n")


def test_push_posts_exposition_to_local_endpoint() -> None:
    received: dict[str, bytes] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            received["body"] = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/import/prometheus"
        status = push_ops_metrics(url, 'mnemosyne_release_gate_open{tenant="t"} 0\n')
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert status == 204
    assert b"mnemosyne_release_gate_open" in received["body"]


def test_cli_ops_metrics_push_requires_metrics_url(tmp_path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mnemosyne.cli",
            "--store",
            str(tmp_path / "mnemosyne.json"),
            "ops-metrics-push",
            "--tenant",
            "primary",
        ],
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "MNEMOSYNE_OPS_METRICS_URL" in result.stderr


def test_cli_ops_metrics_push_once_against_local_store(tmp_path) -> None:
    received: dict[str, bytes] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            received["body"] = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/import/prometheus"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mnemosyne.cli",
                "--store",
                str(tmp_path / "mnemosyne.json"),
                "ops-metrics-push",
                "--tenant",
                "primary",
                "--metrics-url",
                url,
                "--interval",
                "0",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["status"] == 204
    assert b"mnemosyne_ops_report_timestamp_seconds" in received["body"]
    assert b"mnemosyne_ops_report_info" in received["body"]
