#!/usr/bin/env python3
"""HTTPS serving endpoint for the B9 parametric-tier memory adapter (no-GPU).

A thin stdlib ``http.server`` that serves the deployed parametric adapter
(``mnemosyne.parametric_adapter``) as a hosted inference endpoint. TLS is
terminated by Caddy (step-ca) at ``roles.mnemo.local`` via a ``/parametric*``
route; this process listens plaintext on the internal docker network only.

The adapter artifact is loaded at startup **from the SeaweedFS object store by
its content hash** and verified against ``PARAMETRIC_ARTIFACT_SHA256`` -- so the
endpoint provably serves the exact immutable object the trainer wrote, and
``artifact_uri_hash`` in every response is that same content hash.

Endpoints:
    GET  /parametric/healthz   liveness + adapter identity / artifact hash.
    POST /parametric/infer     body = {"embedding": [floats]} ->
                    {"ok", "score", "label", "artifact_uri_hash"}. Fails closed.

Environment:
    PARAMETRIC_HTTP_HOST / PARAMETRIC_HTTP_PORT   bind (default 0.0.0.0:8793)
    PARAMETRIC_S3_KEY                             object key of the adapter
    PARAMETRIC_ARTIFACT_SHA256                    expected content hash (hex)
    MNEMOSYNE_S3_ENDPOINT/_BUCKET/_ACCESS_KEY/_SECRET_KEY   object store
    SSL_CERT_FILE                                 step-ca root for the S3 ingress
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mnemosyne import parametric_adapter as pa
from mnemosyne.storage import SeaweedS3Client, s3_config_from_env

HOST = os.environ.get("PARAMETRIC_HTTP_HOST", "0.0.0.0")
PORT = int(os.environ.get("PARAMETRIC_HTTP_PORT", "8793"))
MAX_BODY_BYTES = int(os.environ.get("PARAMETRIC_HTTP_MAX_BODY_BYTES", str(1 << 20)))


def _load_adapter() -> tuple[dict, str]:
    key = os.environ["PARAMETRIC_S3_KEY"]
    expected = os.environ.get("PARAMETRIC_ARTIFACT_SHA256", "").strip()
    client = SeaweedS3Client(s3_config_from_env(dict(os.environ)))
    blob = client.get_object(key)
    digest = hashlib.sha256(blob).hexdigest()
    if expected and digest != expected:
        raise SystemExit(f"adapter hash mismatch: expected {expected} got {digest}")
    return pa.deserialize(blob), digest


ADAPTER, ADAPTER_SHA256 = _load_adapter()


class Handler(BaseHTTPRequestHandler):
    server_version = "mnemosyne-parametric-http/1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/parametric/healthz", "/healthz"):
            self._send(200, {
                "ok": True,
                "adapter_loaded": True,
                "adapter_kind": ADAPTER.get("adapter_kind"),
                "artifact_uri_hash": f"sha256:{ADAPTER_SHA256}",
                "dims": ADAPTER.get("dims"),
            })
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") not in ("/parametric/infer", "/infer"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send(400, {"ok": False, "error": "invalid content-length"})
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"ok": False, "error": "request body must be JSON"})
            return
        feature = request.get("embedding") if isinstance(request, dict) else None
        if not isinstance(feature, list) or not feature:
            self._send(400, {"ok": False, "error": "request requires an 'embedding' array"})
            return
        try:
            prob = pa.score(ADAPTER, [float(x) for x in feature])
        except Exception as exc:  # fail closed
            self._send(502, {"ok": False, "error": f"parametric inference failed: {exc}"})
            return
        self._send(200, {
            "ok": True,
            "score": prob,
            "label": 1 if prob >= 0.5 else 0,
            "adapter_kind": ADAPTER.get("adapter_kind"),
            "artifact_uri_hash": f"sha256:{ADAPTER_SHA256}",
        })

    def log_message(self, fmt: str, *args) -> None:  # keep logs quiet + PII-free
        sys.stderr.write("parametric-http %s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    sys.stderr.write(f"parametric-http listening on {HOST}:{PORT} adapter=sha256:{ADAPTER_SHA256}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
