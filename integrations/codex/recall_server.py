"""Warm read-only recall server for local hosts (Claude Code hooks).

Each `runtime.py call` read starts a cold process whose caches are rebuilt on
every prompt (~6 s). This process keeps one facade open, so a recall costs only
the retrieval itself (~2.5 s). It serves read tools only, over a Unix socket in
the private state directory. Engine caches key on PRAGMA data_version, so
commits by Codex, the worker or any other process are visible without a restart.

It exits after replying once the deployed runtime or release changes, so launchd
restarts it on the new code. Requests are served one at a time; clients set
their own deadlines and fall back to the cold path when the socket is absent.

Protocol: one JSON line {"tool", "arguments", "session_id"} in, one JSON line out:
{"result": ...} or {"error": "<exception type>"}.
"""

import json
import os
import socketserver
import sys
import threading
from pathlib import Path

os.environ.setdefault('MNEMOSYNE_INTERACTIVE_READ', '1')  # provider calls use the interactive (short) timeouts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataclasses import replace  # noqa: E402

from runtime import ROOT, STATE, configure_retrieval, invoke, open_facade  # noqa: E402

SOCKET = STATE / 'recall.sock'
# The query-embedding provider usually answers in <1 s but sometimes stalls for ~9 s. Past this
# deadline the request is answered by local recall (lexical/graph/working memory, no vectors),
# the same fallback the cold path's bounded read uses.
EMBED_TIMEOUT = float(os.environ.get('MNEMOSYNE_RECALL_EMBED_TIMEOUT', '2.0'))
READ_TOOLS = {'prepare_context', 'search', 'deep_search'}
WATCHED = [ROOT / 'codex/runtime.py', ROOT / 'codex/active-release.json', Path(__file__).resolve()]
MAX_REQUEST = 1 << 20


def fingerprint():
    return [path.stat().st_mtime_ns if path.exists() else None for path in WATCHED]


def local_invoke(facade, tool, arguments, session_id):
    """Run one request in the runtime's local-recall mode, then restore provider retrieval."""
    engine, saved = facade.engine, facade.engine.adapters
    os.environ['MNEMOSYNE_LOCAL_RECALL'] = '1'
    try:
        configure_retrieval(facade)
        return invoke(facade, tool, arguments, session_id)
    finally:
        os.environ.pop('MNEMOSYNE_LOCAL_RECALL', None)
        engine.__dict__.pop('vector_search', None)  # local mode shadows the method on the instance
        engine.adapters = saved


def recall(facade, tool, arguments, session_id):
    try:
        return invoke(facade, tool, dict(arguments), session_id), 'provider'
    except PermissionError:
        raise
    except Exception:
        return local_invoke(facade, tool, dict(arguments), session_id), 'local'


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server
        try:
            request = json.loads(self.rfile.readline(MAX_REQUEST))
            tool = request.get('tool')
            if tool not in READ_TOOLS:
                raise PermissionError('recall server serves read tools only')
            with server.lock:
                result, mode = recall(server.facade, tool, request.get('arguments') or {}, request.get('session_id'))
            reply = {'result': result, 'mode': mode}
        except Exception as error:  # the error type only: messages can carry private query text
            reply = {'error': type(error).__name__}
        self.wfile.write((json.dumps(reply, default=str) + '\n').encode())
        self.wfile.flush()


def exit_on_redeploy(server):
    """Stop serving soon after the runtime/release/this file changes; launchd restarts on new code."""
    while not server.stopping.wait(2.0):
        if fingerprint() != server.started_with:
            server.shutdown()
            return


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    SOCKET.unlink(missing_ok=True)
    started_with = fingerprint()
    with open_facade() as facade:
        scoped = facade.engine.adapters.embedding  # ScopedQueryEmbeddingProvider around the HTTP provider
        scoped.provider = replace(scoped.provider, timeout_seconds=EMBED_TIMEOUT)
        # Warm the retrieval caches before accepting requests. `search` records no learning receipt.
        # The time-window question builds the passage index once (~30 s on a large store);
        # without it the first dated question a user asks pays that build.
        for query in ('recent work', 'what did we discuss yesterday about recent work'):
            try:
                invoke(facade, 'search', {'tenant_id': 'personal', 'query': query}, 'recall-server-warmup')
            except Exception:  # a cold cache is slower, not broken; never crash-loop on warm-up
                pass
        old_umask = os.umask(0o177)  # socket file is user-only (0600)
        try:
            server = Server(str(SOCKET), Handler)
        finally:
            os.umask(old_umask)
        server.facade, server.lock, server.started_with = facade, threading.Lock(), started_with
        server.stopping = threading.Event()
        threading.Thread(target=exit_on_redeploy, args=(server,), daemon=True).start()
        try:
            server.serve_forever()
        finally:
            server.stopping.set()
            server.server_close()
            SOCKET.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
