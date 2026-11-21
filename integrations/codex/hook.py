"""Authenticated Codex lifecycle adapter with a hard, process-bounded deadline."""

import hashlib
import json
import os
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


# The warm recall server (recall_server.py) answers prompt recall without the cold facade
# open (~6 s) and without importing runtime/mnemosyne in the hook process (~18 ms vs ~442 ms).
# When it is missing or fails, the hook lazily loads runtime/mnemosyne and uses the bounded cold path.
def _resolve_state():
    runtime_mod = sys.modules.get("runtime")
    if runtime_mod is not None and hasattr(runtime_mod, "STATE"):
        return Path(runtime_mod.STATE)
    return Path(os.environ.get("MNEMOSYNE_HOST_STATE", Path.home() / ".local/state/mnemosyne"))


STATE = _resolve_state()
RECALL_SOCKET = STATE / "recall.sock"
WARM_TIMEOUT = 6.5  # inside supervise()'s 8 s child deadline
WARM_EMBED_DEADLINE = 4.0  # query embedding; past it the server answers by local recall


def _runtime():
    """Lazily load runtime.py only when the pure-stdlib warm socket fast-path is not used."""
    global STATE, RECALL_SOCKET
    import runtime as runtime_mod
    if hasattr(runtime_mod, "STATE"):
        STATE = Path(runtime_mod.STATE)
        RECALL_SOCKET = STATE / "recall.sock"
    return runtime_mod


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _is_subagent_fast(metadata):
    source = metadata.get("source")
    return bool(
        metadata.get("parent_thread_id")
        or source == "subagent"
        or isinstance(source, dict)
        and ("subagent" in source or source.get("parent_thread_id"))
    )


def _redact_error(text):
    try:
        from mnemosyne.hosts.codex import redact
        return redact(text)
    except Exception:
        import re
        cleaned = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer [REDACTED]", str(text))
        cleaned = re.sub(r"\b(?:sk-|ghp_|github_pat_|gbrain_at_)[A-Za-z0-9_-]{12,}", "[REDACTED]", cleaned)
        return re.sub(
            r"""(?i)((?:password|secret|api[_-]?key|access[_-]?token)["']?\s*[=:]\s*["']?)[^\s"',}]{8,}""",
            r"\1[REDACTED]",
            cleaned,
        )


def _can_use_fast_socket():
    """Enable pure-stdlib socket dispatch for installed hooks or explicit MNEMOSYNE_HOST_STATE."""
    if os.environ.get("MNEMOSYNE_HOST_STATE"):
        return True
    installed_dir = (Path(os.environ.get("MNEMOSYNE_HOST_ROOT", Path.home() / ".local/share/mnemosyne")) / "codex").resolve()
    try:
        return Path(__file__).resolve().parent == installed_dir
    except OSError:
        return False


class LazyFacade:
    """open_facade() that opens only when something touches the facade."""

    def __init__(self):
        self._real = None

    def _open(self):
        if self._real is None:
            self._context = _runtime().open_facade()
            self._real = self._context.__enter__()
        return self._real

    def __getattr__(self, name):
        return getattr(self._open(), name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._context.__exit__(*exc) if self._real is not None else None


def fast_user_prompt(payload):
    """Pure-stdlib UserPromptSubmit fast-path directly over recall.sock.

    Returns (output_dict, False) on hit, (None, True) on warm timeout, or
    (None, False) when the warm server is absent/unsupported so supervise() runs.
    """
    session = str(payload.get("session_id") or "")
    if not session or os.environ.get("MNEMOSYNE_INTERNAL") == "1" or _is_subagent_fast(payload):
        return {}, False
    if os.environ.get("MNEMOSYNE_LOCAL_RECALL") == "1" or not RECALL_SOCKET.exists():
        return None, False
    request = {
        "tool": "codex_user_prompt",
        "payload": payload,
        "agent_id": "codex",
        "embed_deadline": WARM_EMBED_DEADLINE,
    }
    start = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(WARM_TIMEOUT)
        try:
            client.connect(str(RECALL_SOCKET))
            client.sendall((json.dumps(request, default=str) + "\n").encode())
            raw = client.makefile("rb").readline()
        except TimeoutError:
            return None, True
        except OSError:
            return None, False
    if not raw:
        return None, False
    try:
        reply = json.loads(raw)
    except ValueError:
        return None, False
    if not isinstance(reply, dict) or not isinstance(reply.get("result"), dict):
        return None, False
    elapsed = round(time.monotonic() - start, 3)
    mode = reply.get("mode", "provider")
    output = dict(reply["result"])
    if isinstance(output.get("_mnemosyne_delivery"), dict):
        output["_mnemosyne_delivery"]["retrieval_execution"] = {
            "degraded": mode == "local",
            "attempts": [{
                "mode": mode,
                "deadline_seconds": WARM_TIMEOUT,
                "status": "returned",
                "seconds": elapsed,
            }],
            "provider_deadline_seconds": WARM_TIMEOUT,
        }
    return output, False


def warm_prepare(arguments, session_id):
    """The server's reply, or None when it is unavailable. A slow reply raises TimeoutError
    so supervise() moves on to its local retry instead of a cold open it cannot finish."""
    request = {"tool": "prepare_context", "arguments": arguments, "session_id": session_id,
               "agent_id": "codex", "embed_deadline": WARM_EMBED_DEADLINE}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(WARM_TIMEOUT)
        try:
            client.connect(str(RECALL_SOCKET))
            client.sendall((json.dumps(request, default=str) + "\n").encode())
            reply = client.makefile("rb").readline()
        except TimeoutError:
            raise
        except OSError:  # no server, refused, or closed by a restart
            return None
    reply = json.loads(reply) if reply else {}
    return reply if "result" in reply else None


def warm_invoke(facade, name, arguments, session_id=None):
    if (name == "prepare_context" and isinstance(facade, LazyFacade) and facade._real is None
            and os.environ.get("MNEMOSYNE_LOCAL_RECALL") != "1"):
        reply = warm_prepare(arguments, session_id)
        if reply is not None:
            if reply.get("mode") == "local":
                # The adapter reports a local-recall answer as a degraded delivery.
                os.environ["MNEMOSYNE_LOCAL_RECALL"] = "1"
            return reply["result"]
    return _runtime().invoke(facade, name, arguments, session_id)


def adapter(stage_callback=None):
    rt = _runtime()
    from mnemosyne.hosts.codex import CodexAdapter
    return CodexAdapter(state_dir=STATE, tenant_id=rt.TENANT, user_id=rt.USER,
        open_facade=LazyFacade, locked=rt.locked, invoke=warm_invoke, require_delivery_confirmation=True,
        report_command=[sys.executable, str(Path(__file__).resolve()), "--report-use"],
        stage_callback=stage_callback)


def _diagnostic_identity(value):
    import re
    value = str(value or "")
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else hashlib.sha256(value.encode()).hexdigest()


def _stage_path(payload):
    import re
    identity = payload.get("_hook_diagnostic_id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
        return None
    return STATE / ("hook-stage-" + identity + ".json")


def _write_stage(payload, stage, session, turn_id):
    path = _stage_path(payload)
    if path is None:
        return
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    row = {"stage": stage, "session_id": _diagnostic_identity(session),
           "turn_id": _diagnostic_identity(turn_id), "pid": os.getpid(),
           "at": datetime.now(UTC).isoformat()}
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        temporary.chmod(0o600)
        json.dump(row, stream)
    temporary.replace(path)


def handle(payload):
    return adapter(lambda stage, session, turn: _write_stage(payload, stage, session, turn)).handle(payload)


def _run_local_fallback(command, payload):
    """Run local-only bounded child directly after a warm socket timeout."""
    import subprocess
    environment = dict(os.environ, MNEMOSYNE_INTERACTIVE_READ="1",
                       MNEMOSYNE_PROVIDER_TIMEOUT="2.5", MNEMOSYNE_LOCAL_RECALL="1")
    attempts = [{"mode": "provider", "deadline_seconds": WARM_TIMEOUT, "status": "timeout", "seconds": WARM_TIMEOUT}]
    start = time.monotonic()
    attempt = {"mode": "local", "deadline_seconds": 5.0}
    try:
        result = subprocess.run(command, input=json.dumps(payload), text=True,
                                capture_output=True, timeout=5.0, env=environment, check=True)
        response = json.loads(result.stdout)
        if not isinstance(response, dict):
            raise ValueError("host response must be an object")
        attempt["status"] = "returned"
        attempt["seconds"] = round(time.monotonic() - start, 3)
        attempts.append(attempt)
        return response, {"degraded": True, "attempts": attempts, "provider_deadline_seconds": WARM_TIMEOUT}
    except subprocess.TimeoutExpired:
        attempt["status"] = "timeout"
    except subprocess.CalledProcessError as error:
        attempt.update(status="process_error", returncode=error.returncode)
    except (json.JSONDecodeError, ValueError):
        attempt["status"] = "invalid_response"
    attempt["seconds"] = round(time.monotonic() - start, 3)
    attempts.append(attempt)
    return None, {"degraded": True, "attempts": attempts, "provider_deadline_seconds": WARM_TIMEOUT}


def supervise(payload, *, local_only=False):
    """Kill a stuck provider process, then retry recall using only local sources.

    Capture retries are recovered from saved state/transcripts by maintenance;
    they never pretend a timed-out observation completed successfully.
    """
    from uuid import uuid4
    _runtime()
    payload = {**payload, "_hook_diagnostic_id": uuid4().hex}
    command = [sys.executable, str(Path(__file__).resolve()), "--child"]
    event = payload.get("hook_event_name")
    deadline = 1.8 if event == "SessionEnd" else 8.0
    if local_only and event in {"UserPromptSubmit", "HostCapabilities"}:
        response, execution = _run_local_fallback(command, payload)
    else:
        from mnemosyne.hosts.deadlines import run_bounded
        response, execution = run_bounded(command, payload, primary_timeout=deadline,
            allow_local=event in {"UserPromptSubmit", "HostCapabilities"})
    stage_path = _stage_path(payload)
    try:
        stage = json.loads(stage_path.read_text())
    except (OSError, ValueError):
        stage = {}
    finally:
        stage_path.unlink(missing_ok=True)
    if response is not None:
        if response.get('_mnemosyne_delivery'):
            response['_mnemosyne_delivery']['retrieval_execution'] = execution
        return response
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(STATE / 'host-attempts.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        record = {"event": event, "session_id": _diagnostic_identity(payload.get("session_id")),
                  "turn_id": _diagnostic_identity(payload.get("turn_id")),
                  "at": datetime.now(UTC).isoformat(), "last_stage": stage, **execution}
        os.write(descriptor, (json.dumps(record) + '\n').encode())
    finally:
        os.close(descriptor)
    if event in {"UserPromptSubmit", "HostCapabilities"}:
        return {"systemMessage": "Memory recall could not complete; this turn has no injected memory."}
    return {"systemMessage": "Memory capture is pending recovery from the retained transcript."}


def _log_delivery(delivery):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STATE / 'deliveries.jsonl'
    record = {**delivery, 'status': 'returned', 'acknowledged': None, 'applied': None,
              'returned_at': datetime.now(UTC).isoformat()}
    directory = STATE / 'deliveries'
    directory.mkdir(exist_ok=True, mode=0o700)
    marker = directory / (_digest(delivery['receipt_id']) + '.json')
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.chmod(0o600)
    temporary.replace(marker)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(record) + '\n').encode())
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    child_failed = False
    try:
        payload = json.load(sys.stdin)
        arguments = sys.argv[1:]
        if arguments == ["--report-use"]:
            payload["hook_event_name"] = "MemoryUse"
        elif arguments == ["--report-capabilities"]:
            payload["hook_event_name"] = "HostCapabilities"
        elif arguments not in ([], ["--child"]):
            raise ValueError("unsupported lifecycle hook arguments")
        if arguments == [] and payload.get("hook_event_name") == "UserPromptSubmit" and _can_use_fast_socket():
            output, timed_out = fast_user_prompt(payload)
            if output is None:
                output = supervise(payload, local_only=timed_out)
        else:
            output = handle(payload) if arguments == ["--child"] else supervise(payload)
    except Exception as error:
        import traceback
        child_failed = True
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (STATE / "hook-errors.log").open("a") as log:
            (STATE / "hook-errors.log").chmod(0o600)
            log.write(datetime.now(UTC).isoformat() + " " + type(error).__name__ + "\n")
            log.write(_redact_error("".join(traceback.format_exception(error))) + "\n")
        output = {"systemMessage": "Mnemosyne lifecycle capture needs attention. Check the local hook error log."}
    delivery = output.pop('_mnemosyne_delivery', None) if sys.argv[1:] != ['--child'] else None
    print(json.dumps(output, ensure_ascii=False, default=str), flush=True)
    if delivery:
        _log_delivery(delivery)
    if child_failed and sys.argv[1:] == ["--child"]:
        raise SystemExit(1)
