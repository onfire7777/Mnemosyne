"""Exercise malformed request handling on the actual stdlib HTTP transport."""

import errno
import http.client
import importlib.util
import json
import socket
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def service_address():
    path = Path(__file__).resolve().parents[1] / "services" / "embedding" / "app.py"
    spec = importlib.util.spec_from_file_location("embedding_http_error_test", path)
    service = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = service
    spec.loader.exec_module(service)
    service.FORCE_FALLBACK = True
    service.BACKEND = service.Backend(dims=8)
    server = ThreadingHTTPServer(("127.0.0.1", 0), service._make_stdlib_handler())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        sys.modules.pop(spec.name, None)


def _post(address, body, length):
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        connection.request("POST", "/embed", body=body, headers={"Content-Length": length})
        # A negative length previously read until EOF; close only our write
        # half so the regression cannot hang while the response remains readable.
        try:
            connection.sock.shutdown(socket.SHUT_WR)
        except OSError as exc:
            # An invalid header can be rejected and closed before this
            # half-close. Still read and assert the server's HTTP response.
            if exc.errno != errno.ENOTCONN:
                raise
        try:
            response = connection.getresponse()
        except http.client.RemoteDisconnected:
            return None, b""
        return response.status, response.read()
    finally:
        connection.close()


@pytest.mark.parametrize(
    "body,length",
    [
        (b'{"input":"private-marker"}', "abc"),
        (b'{"input":"private-marker"}', "-1"),
        (b'\xffprivate-marker', "15"),
        (b"{}", str(sys.maxsize + 1)),
    ],
)
def test_malformed_requests_return_safe_http400(service_address, body, length):
    status, response = _post(service_address, body, length)
    assert status == 400
    assert isinstance(json.loads(response)["error"], str)
    assert b"private-marker" not in response


@pytest.mark.parametrize("body", [b"null", b"[]", b"42", b'"private-marker"'])
def test_nonobject_json_returns_controlled_http400(service_address, body):
    status, response = _post(service_address, body, str(len(body)))
    assert status == 400
    assert isinstance(json.loads(response)["error"], str)
    assert b"private-marker" not in response


def test_valid_request_still_returns_embedding(service_address):
    body = b'{"input":"valid control"}'
    status, response = _post(service_address, body, str(len(body)))
    assert status == 200
    assert len(json.loads(response)["embedding"]) == 8
