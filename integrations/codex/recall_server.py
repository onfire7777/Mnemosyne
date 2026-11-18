"""Warm read-only recall server for local hosts (Claude Code hooks).

Each `runtime.py call` read starts a cold process whose caches are rebuilt on
every prompt (~6 s). This process keeps one facade open, so a recall costs only
the retrieval itself (~2.5 s). It serves read tools only, over a Unix socket in
the private state directory. Engine caches key on PRAGMA data_version, so
commits by Codex, the worker or any other process are visible without a restart.

It exits after replying once the deployed runtime or release changes, so launchd
restarts it on the new code. Requests are served one at a time; clients set
their own deadlines and fall back to the cold path when the socket is absent.

Protocol: one JSON line {"tool", "arguments", "session_id", optional "agent_id" (a local host:
codex or claude) and "embed_deadline" (seconds)} in, one JSON line out:
{"result": ..., "mode": "provider"|"local"} or {"error": "<exception type>"}.
"""

import json
import os
import socketserver
import socket
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

os.environ.setdefault('MNEMOSYNE_INTERACTIVE_READ', '1')  # provider calls use the interactive (short) timeouts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataclasses import replace  # noqa: E402

from runtime import AGENT, ROOT, STATE, configure_retrieval, invoke, open_facade  # noqa: E402

SOCKET = STATE / 'recall.sock'
# The query-embedding provider usually answers in <1 s but sometimes stalls for ~9 s. Past this
# deadline the request is answered by local recall (lexical/graph/working memory, no vectors),
# the same fallback the cold path's bounded read uses.
EMBED_TIMEOUT = float(os.environ.get('MNEMOSYNE_RECALL_EMBED_TIMEOUT', '2.0'))
# Slow provider replies are per request (most answer in <1 s); a second identical request
# after this delay usually wins. Same provider, same vectors; the extra cost is one cheap call.
EMBED_HEDGE_AFTER = float(os.environ.get('MNEMOSYNE_RECALL_EMBED_HEDGE_AFTER', '0.6'))
READ_TOOLS = {'prepare_context', 'search', 'deep_search'}
HOST_AGENTS = {'claude', 'codex'}
MAX_EMBED_DEADLINE = 8.0
WATCHED = [ROOT / 'codex/runtime.py', ROOT / 'codex/active-release.json', Path(__file__).resolve()]
MAX_REQUEST = 1 << 20


def fingerprint():
    return [path.stat().st_mtime_ns if path.exists() else None for path in WATCHED]


class HedgedEmbedder:
    """The query-embedding provider, with a hedged second request and an overall deadline."""

    def __init__(self, base, hedge_after, deadline):
        self.base, self.hedge_after = base, hedge_after
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='embed')
        self.set_deadline(deadline)

    def set_deadline(self, seconds):
        """Per request (requests are serialized); each HTTP attempt gets the same timeout."""
        self.deadline = seconds
        self.inner = replace(self.base, timeout_seconds=seconds)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _hedged(self, method, text):
        """A second request once the first is slow, a fresh one when a request fails, at most
        three in all; the first success wins."""
        call = getattr(self.inner, method)
        start = time.monotonic()
        end, hedge_at = start + self.deadline, start + self.hedge_after
        pending, attempts, error = {self.pool.submit(call, text)}, 1, None
        while pending and time.monotonic() < end:
            now = time.monotonic()
            timeout = end - now if attempts > 1 else max(0.0, min(end, hedge_at) - now)
            done, pending = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
            for future in done:
                if future.exception() is None:
                    return future.result()
                error = future.exception()
            if attempts < 3 and (done or (attempts == 1 and time.monotonic() >= hedge_at)):
                pending.add(self.pool.submit(call, text))
                attempts += 1
        raise error or TimeoutError('query embedding exceeded its deadline')

    def embed(self, text):
        return self._hedged('embed', text)

    def embed_sensitive(self, text):
        return self._hedged('embed_sensitive', text)


class RetryingReranker:
    """The local cross-encoder sometimes misses its 1.5 s timeout on a cold or busy batch. Its
    failure would send the whole request to local recall (no vectors); one retry returns the
    same scores."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def rerank(self, query, hits, k):
        try:
            return self.inner.rerank(query, hits, k)
        except OSError:  # timeouts and refused connections (a restarting service)
            return self.inner.rerank(query, hits, k)


def client_gone(connection):
    """True when the hook already gave up (closed its end), so its request is not worth running."""
    try:
        connection.setblocking(False)
        return connection.recv(1, socket.MSG_PEEK) == b''
    except BlockingIOError:
        return False
    except OSError:
        return True
    finally:
        connection.setblocking(True)


def local_invoke(facade, tool, arguments, session_id, agent):
    """Run one request in the runtime's local-recall mode, then restore provider retrieval."""
    engine, saved = facade.engine, facade.engine.adapters
    os.environ['MNEMOSYNE_LOCAL_RECALL'] = '1'
    try:
        configure_retrieval(facade)
        return invoke(facade, tool, arguments, session_id, agent)
    finally:
        os.environ.pop('MNEMOSYNE_LOCAL_RECALL', None)
        engine.__dict__.pop('vector_search', None)  # local mode shadows the method on the instance
        engine.adapters = saved


def recall(facade, tool, arguments, session_id, agent):
    try:
        return invoke(facade, tool, dict(arguments), session_id, agent), 'provider'
    except PermissionError:
        raise
    except Exception as error:  # the type only: messages can carry private query text
        print(f'provider recall failed ({type(error).__name__}); answering by local recall', file=sys.stderr, flush=True)
        return local_invoke(facade, tool, dict(arguments), session_id, agent), 'local'


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server
        try:
            request = json.loads(self.rfile.readline(MAX_REQUEST))
            tool = request.get('tool')
            if tool not in READ_TOOLS:
                raise PermissionError('recall server serves read tools only')
            agent = request.get('agent_id') or AGENT
            if agent not in HOST_AGENTS:
                raise PermissionError('unknown host agent')
            deadline = min(max(float(request.get('embed_deadline') or EMBED_TIMEOUT), 0.5), MAX_EMBED_DEADLINE)
            with server.lock:
                # Requests are served one at a time; one the client abandoned while queued
                # would only delay the prompts behind it.
                if client_gone(self.connection):
                    return
                server.embedder.set_deadline(deadline)
                result, mode = recall(server.facade, tool, request.get('arguments') or {},
                                      request.get('session_id'), agent)
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
        embedder = scoped.provider = HedgedEmbedder(scoped.provider, EMBED_HEDGE_AFTER, EMBED_TIMEOUT)
        facade.engine.adapters = replace(facade.engine.adapters,
                                         reranker=RetryingReranker(facade.engine.adapters.reranker))
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
        server.embedder = embedder
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
