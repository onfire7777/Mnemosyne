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

import contextlib
import json
import os
import socketserver
import socket
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataclasses import replace  # noqa: E402

import runtime as _runtime  # noqa: E402
from runtime import AGENT, ROOT, STATE, configure_retrieval, invoke, open_facade  # noqa: E402

TENANT = getattr(_runtime, 'TENANT', os.environ.get('MNEMOSYNE_TENANT', 'personal'))
USER = getattr(_runtime, 'USER', os.environ.get('MNEMOSYNE_USER', 'jake'))

SOCKET = STATE / 'recall.sock'
# The query-embedding provider (OpenRouter/SiliconFlow) typically answers in ~0.8–1.2 s
# with occasional 2–3 s tail latency. With local recall work now ~0.2 s, a 4.0 s budget
# avoids premature fallback to local-only mode while staying well under the 6.5–8 s hook
# deadlines. Hedging at 1.4 s avoids duplicate requests on normal responses while still
# rescuing stalled upstream connections.
EMBED_TIMEOUT = float(os.environ.get('MNEMOSYNE_RECALL_EMBED_TIMEOUT', '4.0'))
EMBED_HEDGE_AFTER = float(os.environ.get('MNEMOSYNE_RECALL_EMBED_HEDGE_AFTER', '1.4'))
READ_TOOLS = {'prepare_context', 'search', 'deep_search'}
CODEX_PROMPT_TOOL = 'codex_user_prompt'
HOST_AGENTS = {'claude', 'codex'}
MAX_EMBED_DEADLINE = 8.0
WATCHED = [ROOT / 'codex/runtime.py', ROOT / 'codex/active-release.json', Path(__file__).resolve()]
MAX_REQUEST = 1 << 20


def configure_warm_server_env(env=None):
    """Enable opt-in warm-daemon SQLite flags strictly inside warm recall_server.py."""
    target = os.environ if env is None else env
    target.setdefault('MNEMOSYNE_INTERACTIVE_READ', '1')  # provider calls use interactive timeouts
    target.setdefault('MNEMOSYNE_SQLITE_SYNCHRONOUS', 'NORMAL')
    target.setdefault('MNEMOSYNE_ASYNC_ACCESS_TRACKING', '1')
    return target


class _ClientAbandoned(Exception):
    """Internal control flow signal when a client disconnects before reply."""


def fingerprint():
    return [path.stat().st_mtime_ns if path.exists() else None for path in WATCHED]


class HedgedEmbedder:
    """The query-embedding provider, with a hedged second request and an overall deadline."""

    def __init__(self, base, hedge_after, deadline):
        self.base, self.hedge_after = base, hedge_after
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='embed')
        self._local = threading.local()
        self.set_deadline(deadline)

    def set_deadline(self, seconds):
        """Set default deadline; concurrent requests should prefer request_deadline()."""
        self.deadline = seconds
        self.inner = replace(self.base, timeout_seconds=seconds)

    @contextlib.contextmanager
    def request_deadline(self, seconds):
        """Thread-local per-request deadline so concurrent prefetch never races."""
        prev_deadline = getattr(self._local, 'deadline', None)
        prev_inner = getattr(self._local, 'inner', None)
        self._local.deadline = seconds
        self._local.inner = replace(self.base, timeout_seconds=seconds)
        try:
            yield
        finally:
            self._local.deadline = prev_deadline
            self._local.inner = prev_inner

    def _current(self):
        inner = getattr(self._local, 'inner', None) or self.inner
        deadline = getattr(self._local, 'deadline', None)
        if deadline is None:
            deadline = self.deadline
        return inner, deadline

    def __getattr__(self, name):
        inner = getattr(self._local, 'inner', None) or self.inner
        return getattr(inner, name)

    def _hedged(self, method, text):
        """A second request once the first is slow, a fresh one when a request fails, at most
        three in all; the first success wins."""
        inner, deadline = self._current()
        call = getattr(inner, method)
        start = time.monotonic()
        end, hedge_at = start + deadline, start + self.hedge_after
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


def _deadline_context(embedder, deadline):
    if hasattr(embedder, 'request_deadline'):
        return embedder.request_deadline(deadline)
    if embedder is not None and hasattr(embedder, 'set_deadline'):
        embedder.set_deadline(deadline)
    return contextlib.nullcontext()


def _execute_recall(server, tool, arguments, session_id, agent, deadline, connection=None):
    """Prefetch remote query embedding outside server.lock so network waits never block local reads."""
    args = dict(arguments) if isinstance(arguments, dict) else {}
    query = args.get('query')
    prefetch_error = None
    scoped = getattr(server, 'scoped_embedder', None)
    if (
        isinstance(query, str)
        and query.strip()
        and scoped is not None
        and os.environ.get('MNEMOSYNE_LOCAL_RECALL') != '1'
    ):
        if connection is not None and client_gone(connection):
            raise _ClientAbandoned()
        with _deadline_context(getattr(server, 'embedder', None), deadline):
            try:
                scoped.embed_query(query)
            except PermissionError:
                raise
            except Exception as error:
                prefetch_error = error
    with server.lock:
        if connection is not None and client_gone(connection):
            raise _ClientAbandoned()
        if prefetch_error is not None:
            print(
                f'provider recall failed ({type(prefetch_error).__name__}); answering by local recall',
                file=sys.stderr,
                flush=True,
            )
            return local_invoke(server.facade, tool, args, session_id, agent), 'local'
        with _deadline_context(getattr(server, 'embedder', None), deadline):
            return recall(server.facade, tool, args, session_id, agent)


def _handle_codex_user_prompt(server, payload, deadline, connection=None):
    """Run CodexAdapter UserPromptSubmit bookkeeping in-process against the warm facade."""
    if not isinstance(payload, dict) or payload.get('hook_event_name') != 'UserPromptSubmit':
        raise PermissionError('codex_user_prompt serves UserPromptSubmit only')
    from mnemosyne.hosts.codex import CodexAdapter

    mode_box = ['provider']

    def warm_adapter_invoke(facade, name, arguments, session_id=None):
        if name != 'prepare_context':
            raise PermissionError('codex_user_prompt invokes prepare_context only')
        result, mode = _execute_recall(
            server, name, arguments, session_id, 'codex', deadline, connection=connection,
        )
        mode_box[0] = mode
        return result

    hook_script = getattr(server, 'hook_script', None) or Path(__file__).resolve().with_name('hook.py')
    state_dir = getattr(server, 'state_dir', STATE)
    tenant_id = getattr(server, 'tenant_id', TENANT)
    user_id = getattr(server, 'user_id', USER)
    codex_adapter = CodexAdapter(
        state_dir=state_dir,
        tenant_id=tenant_id,
        user_id=user_id,
        open_facade=lambda: contextlib.nullcontext(server.facade),
        locked=contextlib.nullcontext,
        invoke=warm_adapter_invoke,
        require_delivery_confirmation=True,
        report_command=[sys.executable, str(hook_script), '--report-use'],
    )
    output = codex_adapter.handle(payload)
    if isinstance(output, dict) and isinstance(output.get('_mnemosyne_delivery'), dict):
        output['_mnemosyne_delivery']['degraded'] = (mode_box[0] == 'local')
    return output, mode_box[0]


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server = self.server
        try:
            request = json.loads(self.rfile.readline(MAX_REQUEST))
            tool = request.get('tool')
            agent = request.get('agent_id') or AGENT
            if agent not in HOST_AGENTS:
                raise PermissionError('unknown host agent')
            deadline = min(max(float(request.get('embed_deadline') or EMBED_TIMEOUT), 0.5), MAX_EMBED_DEADLINE)
            if tool == CODEX_PROMPT_TOOL:
                if agent != 'codex':
                    raise PermissionError('codex_user_prompt requires codex host agent')
                result, mode = _handle_codex_user_prompt(
                    server, request.get('payload'), deadline, connection=self.connection,
                )
            elif tool in READ_TOOLS:
                result, mode = _execute_recall(
                    server, tool, request.get('arguments') or {},
                    request.get('session_id'), agent, deadline, connection=self.connection,
                )
            else:
                raise PermissionError('recall server serves read tools only')
            reply = {'result': result, 'mode': mode}
        except _ClientAbandoned:
            return
        except Exception as error:  # the error type only: messages can carry private query text
            reply = {'error': type(error).__name__}
        try:
            self.wfile.write((json.dumps(reply, default=str) + '\n').encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client timed out and closed the socket before the reply finished.


def exit_on_redeploy(server):
    """Stop serving soon after the runtime/release/this file changes; launchd restarts on new code."""
    while not server.stopping.wait(2.0):
        if fingerprint() != server.started_with:
            server.shutdown()
            return


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    configure_warm_server_env()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    SOCKET.unlink(missing_ok=True)
    started_with = fingerprint()
    with open_facade() as facade:
        scoped = facade.engine.adapters.embedding  # ScopedQueryEmbeddingProvider around the HTTP provider
        embedder = scoped.provider = HedgedEmbedder(scoped.provider, EMBED_HEDGE_AFTER, EMBED_TIMEOUT)
        facade.engine.adapters = replace(facade.engine.adapters,
                                         reranker=RetryingReranker(facade.engine.adapters.reranker))
        # Warm the fast retrieval, learning, and knowledge-page caches before accepting
        # requests. `search` records no learning receipt.
        try:
            invoke(facade, 'search', {'tenant_id': 'personal', 'query': 'recent work'}, 'recall-server-warmup')
        except Exception:  # a cold cache is slower, not broken; never crash-loop on warm-up
            pass
        try:
            facade.tools._learning_runtime().writer.read('personal')
        except Exception:
            pass
        try:
            from mnemosyne.knowledge_maintenance import _cached_knowledge_pages
            _cached_knowledge_pages(facade.engine, 'personal', 'main')
        except Exception:
            pass
        try:
            import mnemosyne.hosts.codex  # noqa: F401 - warm adapter import before first prompt
        except Exception:
            pass
        old_umask = os.umask(0o177)  # socket file is user-only (0600)
        try:
            server = Server(str(SOCKET), Handler)
        finally:
            os.umask(old_umask)
        server.facade, server.lock, server.started_with = facade, threading.Lock(), started_with
        server.embedder = embedder
        server.scoped_embedder = scoped
        server.stopping = threading.Event()

        def warm_passages():
            warmup_query = 'what did we discuss yesterday about recent work'
            try:
                if hasattr(scoped, 'embed_query'):
                    scoped.embed_query(warmup_query)
            except Exception:
                pass
            with server.lock:
                if server.stopping.is_set():
                    return
                try:
                    invoke(
                        facade,
                        'search',
                        {'tenant_id': 'personal', 'query': warmup_query},
                        'recall-server-warmup',
                    )
                except Exception:
                    pass

        threading.Thread(target=warm_passages, daemon=True).start()
        threading.Thread(target=exit_on_redeploy, args=(server,), daemon=True).start()
        try:
            server.serve_forever()
        finally:
            server.stopping.set()
            if hasattr(facade.engine, 'flush_access_tracking'):
                try:
                    facade.engine.flush_access_tracking()
                except Exception:
                    pass
            server.server_close()
            SOCKET.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
