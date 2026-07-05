#!/usr/bin/env python3
"""HTTPS role provider service for Mnemosyne (self-hosted profile).

A thin stdlib ``http.server`` that fronts the exact same role dispatch as
``role-llm.py`` (Ollama-backed, byte-identical request/response contract) over
HTTP so the engine's ``Http*`` role adapters and ``hosted-llm-check`` can reach
it as a hosted provider. TLS is terminated by Caddy at ``roles.mnemo.local``;
this process listens plaintext on the internal docker network only.

Endpoint:
    POST /v1/role   body = the same JSON the Command* adapters send on stdin
                    (``prompt_boundary.role`` selects the role). Responds with
                    the role JSON on 200; fails closed (4xx/5xx + error) rather
                    than emitting fabricated structure.
    GET  /healthz   liveness probe -> {"ok": true}

Role names accepted mirror ``role-llm.ROLES`` plus the ``hosted-llm-check`` alias
``summarizer`` -> ``evidence_summarizer``.

Environment:
    ROLE_HTTP_HOST   bind host (default 0.0.0.0)
    ROLE_HTTP_PORT   bind port (default 8791)
    plus every variable consumed by role-llm.py (OLLAMA_URL, OLLAMA_MODEL, ...).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Reuse the byte-identical role dispatch from role-llm. The source lives next to
# this file as ``role-llm.py`` in the repo but is COPY'd into the container image
# as ``role-llm`` (no extension), so load it by explicit source-file loader and
# accept either name. role-llm imports mnemosyne.network_safety, so mnemosyne
# must be importable (installed in the image, or PYTHONPATH=/…/src).
_HERE = pathlib.Path(__file__).resolve().parent
_ROLE_LLM_PATH = next(
    (_HERE / name for name in ("role-llm.py", "role-llm") if (_HERE / name).is_file()),
    None,
)
if _ROLE_LLM_PATH is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot locate role-llm dispatch next to {__file__}")
_loader = importlib.machinery.SourceFileLoader("mnemosyne_role_llm", str(_ROLE_LLM_PATH))
_spec = importlib.util.spec_from_loader("mnemosyne_role_llm", _loader)
role_llm = importlib.util.module_from_spec(_spec)
_loader.exec_module(role_llm)

ROLES = role_llm.ROLES
# hosted-llm-check validates the role name "summarizer"; the underlying handler
# is registered under "evidence_summarizer".
ROLE_ALIASES = {"summarizer": "evidence_summarizer"}

HOST = os.environ.get("ROLE_HTTP_HOST", "0.0.0.0")
PORT = int(os.environ.get("ROLE_HTTP_PORT", "8791"))
MAX_BODY_BYTES = int(os.environ.get("ROLE_HTTP_MAX_BODY_BYTES", str(1 << 20)))


def _resolve_role(role: str):
    return ROLES.get(ROLE_ALIASES.get(role, role))


class RoleHandler(BaseHTTPRequestHandler):
    server_version = "mnemosyne-role-http/1"

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if self.path.rstrip("/") in ("/healthz", "/health"):
            self._send_json(200, {"ok": True, "roles": sorted(ROLES)})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        if self.path.rstrip("/") not in ("/v1/role", "/v1/roles"):
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"ok": False, "error": "invalid content-length"})
            return
        raw = self.rfile.read(length)
        try:
            request = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"ok": False, "error": "request body must be JSON"})
            return
        if not isinstance(request, dict):
            self._send_json(400, {"ok": False, "error": "request body must be a JSON object"})
            return
        role = str((request.get("prompt_boundary") or {}).get("role") or "").strip()
        handler = _resolve_role(role)
        if handler is None:
            self._send_json(400, {"ok": False, "error": f"unknown provider role {role!r}"})
            return
        try:
            result = handler(request)
        except Exception as exc:  # fail closed: no fabricated structure on model failure
            self._send_json(502, {"ok": False, "error": f"{role} failed: {exc}"})
            return
        self._send_json(200, result)

    def log_message(self, fmt: str, *args) -> None:  # keep logs quiet + PII-free
        sys.stderr.write("role-http %s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    httpd = ThreadingHTTPServer((HOST, PORT), RoleHandler)
    sys.stderr.write(f"role-http listening on {HOST}:{PORT} roles={sorted(ROLES)}\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
