#!/usr/bin/env python3
"""Minimal self-hosted alert receiver for the self-hosted profile (B8 core).

vmalert POSTs firing alerts (Alertmanager v2 JSON) to ``/api/v2/alerts``; this
receiver records them in memory and exposes them at ``/alerts`` so a subscriber
can verify real end-to-end delivery (vmalert -> notifier route -> sink) without
a human/pager. Replaces the ``-notifier.blackhole`` no-op so the consolidation /
ops deployments have a genuinely delivering, verifiable alert route.

Stdlib only; no disk writes (read-only rootfs friendly).
"""
from __future__ import annotations

import json
import os
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("ALERT_SINK_HOST", "0.0.0.0")
PORT = int(os.environ.get("ALERT_SINK_PORT", "9099"))
_LOCK = threading.Lock()
_RECEIVED: deque[dict] = deque(maxlen=1000)


class Handler(BaseHTTPRequestHandler):
    server_version = "mnemosyne-alert-sink/1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path in ("/healthz", "/health"):
            self._json(200, {"ok": True})
            return
        if path == "/alerts":
            with _LOCK:
                items = list(_RECEIVED)
            names = sorted({a.get("labels", {}).get("alertname", "") for a in items})
            self._json(200, {"count": len(items), "alertnames": names, "alerts": items})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b"[]"
        try:
            alerts = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "body must be JSON"})
            return
        if isinstance(alerts, dict):
            alerts = alerts.get("alerts", [alerts])
        if not isinstance(alerts, list):
            alerts = []
        with _LOCK:
            for a in alerts:
                if isinstance(a, dict):
                    _RECEIVED.append(a)
                    name = a.get("labels", {}).get("alertname", "?")
                    status = a.get("status", "firing")
                    sys.stderr.write(f"alert-sink received alert={name} status={status}\n")
        sys.stderr.flush()
        self._json(200, {"ok": True, "received": len(alerts)})

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> int:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(f"alert-sink listening on {HOST}:{PORT}\n")
    sys.stderr.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
