from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _run_cli(store: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "mnemosyne.cli", "--store", str(store), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def _command(tmp_path: Path, role: str, state: Path) -> str:
    script = tmp_path / "provider-role.py"
    script.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "role = sys.argv[1]",
                "state = pathlib.Path(sys.argv[2])",
                "request = json.loads(sys.stdin.read() or '{}')",
                "calls = json.loads(state.read_text()) if state.exists() else []",
                "calls.append({'role': role, 'request': request})",
                "state.write_text(json.dumps(calls, sort_keys=True))",
                "candidate = {",
                "    'signature': 'provider-health',",
                "    'query': 'provider health',",
                "    'candidate_subject': 'Provider Health',",
                "    'candidate_predicate': 'is',",
                "    'candidate_object': 'configured',",
                "    'entity_key': 'provider-health',",
                "}",
                "if role == 'retrieval':",
                "    request_role = request.get('role')",
                "    kind = 'relation' if request_role == 'graph_ppr' else 'evidence'",
                "    channel = 'external_graph' if request_role == 'graph_ppr' else 'external_lexical'",
                "    hit_id = 'graph-hit' if request_role == 'graph_ppr' else 'lexical-hit'",
                "    print(json.dumps({'hits': [{'id': hit_id, 'kind': kind, 'text': 'provider health configured', 'score': 0.91, 'channel': channel, 'provenance': ['sha256:provider-health']}]}))",
                "elif role == 'candidate_extractor':",
                "    print(json.dumps({'candidates': [candidate], 'metadata': {'source': 'phase3-test'}}))",
                "elif role == 'summarizer':",
                "    print(json.dumps({'summary': 'provider health summary', 'metadata': {'source': 'phase3-test'}}))",
                "elif role == 'entity_resolver':",
                "    print(json.dumps({'candidates': [{'signature': 'provider-health', 'entity_key': 'provider-health'}], 'entities': [{'key': 'provider-health', 'label': 'Provider Health', 'candidate_signatures': ['provider-health']}]}))",
                "elif role == 'lesson_distiller':",
                "    print(json.dumps({'lessons': [{'content': 'Provider health is configured.', 'failure_signature': 'provider-health', 'votes': 1}], 'metadata': {'source': 'phase3-test'}}))",
                "elif role == 'skill_inducer':",
                "    print(json.dumps({'procedures': [{'signature': {'name': 'provider-health'}, 'name': 'Provider health procedure', 'body': 'Check configured provider health.'}], 'metadata': {'source': 'phase3-test'}}))",
                "else:",
                "    raise SystemExit(f'unknown role {role}')",
            ]
        ),
        encoding="utf-8",
    )
    return " ".join(
        shlex.quote(item) for item in (sys.executable, str(script), role, str(state))
    )


def test_provider_manifest_runs_http_retrieval_and_all_consolidation_role_checks(
    tmp_path: Path,
) -> None:
    http_requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name.
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            http_requests.append(
                {
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "payload": payload,
                }
            )
            if self.path == "/embed":
                body = {"data": [{"embedding": [3.0, 4.0, 0.0]}]}
            else:
                body = {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                }
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature.
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    state = tmp_path / "role-calls.json"
    manifest = tmp_path / "provider-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "phase3-provider-manifest",
                "forbid_local": True,
                "required_checks": [
                    "embedding",
                    "reranker",
                    "retrieval_backends",
                    "candidate_extractor",
                    "summarizer",
                    "entity_resolver",
                    "lesson_distiller",
                    "skill_inducer",
                ],
                "providers": {
                    "retrieval": {
                        "embedding": {
                            "provider": "http",
                            "url": f"{base}/embed",
                            "model": "embed-health",
                            "api_key": "embed-secret",
                            "dims": 3,
                        },
                        "reranker": {
                            "provider": "http",
                            "url": f"{base}/rerank",
                            "model": "rerank-health",
                            "api_key": "rank-secret",
                        },
                        "lexical": {
                            "provider": "command",
                            "command": _command(tmp_path, "retrieval", state),
                            "backend": "paradedb-bm25",
                        },
                        "graph": {
                            "provider": "command",
                            "command": _command(tmp_path, "retrieval", state),
                            "backend": "apache-age",
                        },
                    },
                    "candidate_extractor": {
                        "provider": "command",
                        "command": _command(tmp_path, "candidate_extractor", state),
                    },
                    "summarizer": {
                        "provider": "command",
                        "command": _command(tmp_path, "summarizer", state),
                    },
                    "entity_resolver": {
                        "provider": "command",
                        "command": _command(tmp_path, "entity_resolver", state),
                    },
                    "lesson_distiller": {
                        "provider": "command",
                        "command": _command(tmp_path, "lesson_distiller", state),
                    },
                    "skill_inducer": {
                        "provider": "command",
                        "command": _command(tmp_path, "skill_inducer", state),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        report = _run_cli(
            tmp_path / "mnemosyne.json",
            "provider-check",
            "--provider-manifest",
            str(manifest),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert report["ok"] is True
    assert report["manifest"]["forbid_local"] is True
    for check in (
        "embedding",
        "reranker",
        "retrieval_backends",
        "candidate_extractor",
        "summarizer",
        "entity_resolver",
        "lesson_distiller",
        "skill_inducer",
    ):
        assert report["checks"][check]["ok"] is True
        assert not report["checks"][check].get("skipped", False)
    assert {request["auth"] for request in http_requests} == {
        "Bearer embed-secret",
        "Bearer rank-secret",
    }
    assert "embed-secret" not in json.dumps(report, sort_keys=True)
    assert "rank-secret" not in json.dumps(report, sort_keys=True)
    assert [call["role"] for call in json.loads(state.read_text(encoding="utf-8"))] == [
        "retrieval",
        "retrieval",
        "candidate_extractor",
        "summarizer",
        "entity_resolver",
        "lesson_distiller",
        "skill_inducer",
    ]
