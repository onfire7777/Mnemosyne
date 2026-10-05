"""Bounded public subprocess seam for the M16 development cassette."""

from __future__ import annotations

import json
import secrets
import queue
import threading
import subprocess
import time
from pathlib import Path

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import mint_session_token

COMMANDS = {
    "capture": "capture",
    "get": "get",
    "search": "search",
    "correct": "correct",
    "forget": "forget",
    "schedule_intention": "intention-schedule",
    "update_intention": "intention-update",
    "evaluate_intentions": "intention-evaluate",
    "list_intentions": "intention-list",
    "working_seed": "working-seed",
    "working_query": "working-query",
}


class TransportError(RuntimeError):
    pass


class CallError(RuntimeError):
    pass


class BoundedChild:
    """Drain both pipes with bounded buffers, including on a stalled child."""

    def __init__(self, argv, *, env=None, timeout=30):
        self.timeout = timeout
        self.process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.events = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.output = bytearray()
        self.errors = bytearray()
        self.eof = set()
        self.readers = []
        for name in ("stdout", "stderr"):
            thread = threading.Thread(target=self._drain, args=(name,), daemon=True)
            thread.start()
            self.readers.append(thread)

    def _drain(self, name):
        pipe = getattr(self.process, name)
        while not self.stop.is_set():
            block = pipe.read1(8192)
            while not self.stop.is_set():
                try:
                    self.events.put((name, block), timeout=0.1)
                    break
                except queue.Full:
                    continue
            if not block:
                return

    def receive(self, *, line=False):
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                if line and b"\n" in self.output:
                    value, _, rest = self.output.partition(b"\n")
                    self.output = bytearray(rest)
                    return value.decode("utf-8")
                if self.eof == {"stdout", "stderr"}:
                    if line:
                        raise TransportError("child exited without a response")
                    self.process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    return self.output.decode("utf-8"), self.errors.decode("utf-8")
                name, block = self.events.get(
                    timeout=max(0.001, deadline - time.monotonic())
                )
                if not block:
                    self.eof.add(name)
                else:
                    target = self.output if name == "stdout" else self.errors
                    target.extend(block)
                    if len(self.output) + len(self.errors) > 1024 * 1024:
                        raise TransportError("response exceeded 1 MiB")
                if time.monotonic() >= deadline:
                    raise TransportError("operation timed out")
        except (queue.Empty, UnicodeError, subprocess.TimeoutExpired) as exc:
            self.close()
            raise TransportError("invalid or timed-out response") from exc
        except TransportError:
            self.close()
            raise

    def send(self, value):
        try:
            self.process.stdin.write(json.dumps(value).encode() + b"\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.close()
            raise TransportError("child input closed") from exc

    def close(self):
        self.stop.set()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        for thread in self.readers:
            thread.join(timeout=1)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            pipe.close()


class PublicPair:
    def __init__(self, pair: str, root: Path, *, deadline=None):
        self.backend, self.transport = pair.split("/")
        if self.backend not in {"local", "sqlite"} or self.transport not in {
            "cli",
            "mcp-stdio",
        }:
            raise ValueError("unadmitted pair")
        self.root = root
        self.deadline = deadline if deadline is not None else time.monotonic() + 900
        self.call_count = 0
        root.mkdir(parents=True, exist_ok=False)
        self.secret = secrets.token_hex(32)
        self.tokens: list[str] = []
        self.raw: list[dict] = []
        self.mnemo = MnemoCLI(
            store=str(root / "store.json"),
            backend=self.backend,
            global_flags=["--store", str(root / "store")]
            if self.backend == "sqlite"
            else [],
            env={
                "MNEMOSYNE_SESSION_SECRET": self.secret,
                "MNEMOSYNE_MCP_SESSION_SECRET": self.secret,
            },
            timeout_s=30,
        )
        self.env = {
            k: v
            for k, v in self.mnemo._environ().items()
            if not k.startswith("MNEMOSYNE_")
        }
        self.env.update(self.mnemo.env)
        self.child = None
        self.request_id = 0

    def call(self, name: str, arguments: dict, *, identity: dict | None = None) -> dict:
        self.call_count += 1
        remaining = self.deadline - time.monotonic()
        if self.call_count > 32 or remaining <= 0:
            raise TransportError("cassette operation or time budget exhausted")
        timeout = min(30, remaining)
        principal = dict(
            tenant_id="m16",
            user_id="owner",
            agent_id="agent",
            session_id="session",
            role="operator",
        )
        principal.update(identity or {})
        token = mint_session_token(
            **principal,
            capabilities=("prospective:evaluate",) if name == "evaluate_intentions" else (),
            secret=self.secret,
        )
        self.tokens.append(token)
        aliases = {
            "tenant_id": "tenant",
            "user_id": "user",
            "object_value": "object",
            "correction_text": "correction",
        }
        flags = []
        for key, value in arguments.items():
            flag = aliases.get(key, key.replace("_", "-"))
            if key == "agent_id" and not name.startswith("working_"):
                flag = "agent"
            if key == "evidence_ids":
                for cid in value:
                    flags += ["--evidence-cid", cid]
            else:
                flags += [
                    "--" + flag,
                    json.dumps(value)
                    if isinstance(value, (dict, list, bool))
                    else str(value),
                ]
        started = time.monotonic()
        if self.transport == "cli":
            argv = self.mnemo._base_argv() + [
                "--session-token",
                token,
                COMMANDS[name],
                *flags,
            ]
            child = BoundedChild(argv, env=self.env, timeout=timeout)
            try:
                stdout, stderr = child.receive()
                code = child.process.returncode
            finally:
                child.close()
            raw = {"returncode": code, "stdout": stdout, "stderr": stderr}
            error = stderr if code else None
            try:
                result = json.loads(stdout) if not code else None
            except json.JSONDecodeError as exc:
                raise TransportError("invalid CLI JSON response") from exc
        else:
            if self.child is None:
                store = self.root / (
                    "store.json" if self.backend == "local" else "store"
                )
                argv = [
                    self.mnemo.python,
                    "-m",
                    "mnemosyne.mcp_server",
                    "--backend",
                    self.backend,
                    "--store",
                    str(store),
                    "--require-session",
                ]
                self.child = BoundedChild(argv, env=self.env, timeout=timeout)
                self._rpc("initialize", {})
                self.child.send(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"}
                )
            self.child.timeout = min(30, max(0.001, self.deadline - time.monotonic()))
            arguments = dict(arguments)
            if name == "capture" and "turn_index" in arguments:
                # CLI episode flags are encoded as MCP capture metadata.
                arguments["metadata"] = {
                    "episode": {
                        "session_id": arguments["session_id"],
                        "source_identity": arguments["source_identity"],
                        "turn_index": arguments.pop("turn_index"),
                    }
                }
            raw = self._rpc(
                "tools/call",
                {"name": name, "arguments": arguments, "session_token": token},
            )
            payload = raw.get("result")
            if (
                not isinstance(payload, dict)
                or type(payload.get("isError")) is not bool
            ):
                raise TransportError("invalid MCP tool envelope")
            error = json.dumps(payload.get("content")) if payload["isError"] else None
            result = payload.get("structuredContent")
        encoded = json.dumps(raw)
        for private in [self.secret, *self.tokens]:
            encoded = encoded.replace(private, "[redacted]")
        if len(encoded.encode()) > 1024 * 1024:
            raise TransportError("response exceeded 1 MiB")
        self.raw.append(
            {
                "operation": name,
                "wall_ms": (time.monotonic() - started) * 1000,
                "response": json.loads(encoded),
            }
        )
        if error:
            for private in [self.secret, *self.tokens]:
                error = error.replace(private, "[redacted]")
            raise CallError(error)
        if not isinstance(result, dict):
            raise TransportError("response is not an object")
        return result

    def _rpc(self, method, params):
        self.request_id += 1
        self.child.send(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params,
            }
        )
        try:
            response = json.loads(self.child.receive(line=True))
        except json.JSONDecodeError as exc:
            self.child.close()
            raise TransportError("invalid MCP JSON response") from exc
        if (
            not isinstance(response, dict)
            or response.get("id") != self.request_id
            or "error" in response
        ):
            self.child.close()
            raise TransportError("invalid MCP response identity")
        return response

    def close(self):
        if self.child is not None:
            self.child.close()
