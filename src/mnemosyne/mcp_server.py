"""Minimal stdio JSON-RPC server for the Mnemosyne MCP facade."""

from __future__ import annotations

import argparse
import hmac
import inspect
import json
import os
import sys
from pathlib import Path
from types import UnionType
from typing import Any, Literal, TextIO, Union, get_args, get_origin, get_type_hints

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.ingestion import IngestionPipeline
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.parametric import ParametricArtifactStore, ParametricTier
from mnemosyne.queue import InProcessQueue
from mnemosyne.runtime_state import RuntimeState


PROTOCOL_VERSION = "2024-11-05"


class MnemosyneMcpServer:
    """Small JSON-RPC shim around MemoryTools.

    It intentionally keeps the transport simple and deterministic. The exposed
    methods mirror the common MCP handshake shape: initialize, tools/list, and
    tools/call.
    """

    def __init__(
        self,
        store_path: str | os.PathLike[str] | None = None,
        auth_token: str | None = None,
        backend: str = "local",
        postgres_dsn: str | None = None,
        parametric_artifact_store: str | os.PathLike[str] | None = None,
        stateless: bool = False,
    ):
        if backend not in {"local", "postgres"}:
            raise ValueError(f"Unsupported MCP backend: {backend}")
        if stateless and backend == "local" and not store_path:
            raise ValueError("Stateless local MCP mode requires a durable store_path.")
        self.store_path = store_path
        self.backend = backend
        self.postgres_dsn = postgres_dsn
        self.parametric_artifact_store = parametric_artifact_store
        self.stateless = stateless
        self.auth_token = auth_token if auth_token is not None else os.environ.get("MNEMOSYNE_MCP_TOKEN")
        self.tool_names = {item["name"] for item in TOOL_SPEC}
        if not self.stateless:
            self.engine, self.queue, self.runtime_state, self.tools = self._build_tools()

    def _build_tools(self) -> tuple[Any, InProcessQueue, RuntimeState | None, MemoryTools]:
        if self.backend == "postgres":
            dsn = self.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
            if not dsn:
                raise ValueError("Postgres MCP backend requires postgres_dsn or MNEMOSYNE_POSTGRES_DSN.")
            try:
                from mnemosyne.postgres_engine import PostgresEngine
            except ImportError as exc:  # pragma: no cover - defensive for broken installs.
                raise ValueError("Postgres MCP backend requires mnemosyne-memory[postgres].") from exc
            engine = PostgresEngine(dsn)
            runtime_state = None
        else:
            engine = LocalMemoryEngine(store_path=self.store_path)
            runtime_state = RuntimeState.from_store_path(self.store_path)
        queue = runtime_state.load_queue() if runtime_state else InProcessQueue()
        ingestion = IngestionPipeline(engine, queue=queue)
        parametric = ParametricTier(
            ParametricArtifactStore(_parametric_store_path(self.store_path, self.parametric_artifact_store))
        )
        tools = MemoryTools(engine, ingestion=ingestion, runtime_state=runtime_state, parametric=parametric)
        return engine, queue, runtime_state, tools

    @staticmethod
    def _save_queue(runtime_state: RuntimeState | None, queue: InProcessQueue) -> None:
        if runtime_state:
            runtime_state.save_queue(queue)

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            return None
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": "mnemosyne-memory", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                result = {"tools": [_to_mcp_tool_spec(item) for item in TOOL_SPEC]}
            elif method == "tools/call":
                params = request.get("params") or {}
                try:
                    if not isinstance(params, dict):
                        result = _tool_error("Tool params must be a JSON object")
                    elif not self._authorized(params):
                        result = _tool_error("unauthorized: valid MCP auth token required")
                    else:
                        arguments = params["arguments"] if "arguments" in params else {}
                        result = _tool_result(self.call_tool(str(params.get("name")), arguments))
                except Exception as exc:  # noqa: BLE001 - tool errors are MCP results, not transport failures.
                    result = _tool_error(str(exc))
            else:
                return _error(request_id, -32601, f"Unknown method: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - JSON-RPC must marshal failures.
            return _error(request_id, -32000, str(exc))

    def _authorized(self, params: dict[str, Any]) -> bool:
        if not self.auth_token:
            return True
        supplied = params.get("auth_token")
        meta = params.get("_meta")
        if supplied is None and isinstance(meta, dict):
            supplied = meta.get("auth_token")
        return isinstance(supplied, str) and hmac.compare_digest(supplied, self.auth_token)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.tool_names:
            raise ValueError(f"Unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        if self.stateless:
            _, queue, runtime_state, tools = self._build_tools()
            result = getattr(tools, name)(**arguments)
            self._save_queue(runtime_state, queue)
            return result
        result = getattr(self.tools, name)(**arguments)
        self._save_queue(self.runtime_state, self.queue)
        return result

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle(request)
            except json.JSONDecodeError as exc:
                response = _error(None, -32700, f"Invalid JSON: {exc.msg}")
            if response is not None:
                stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                stdout.flush()


def _to_mcp_tool_spec(spec: dict[str, Any]) -> dict[str, Any]:
    method = getattr(MemoryTools, spec["name"], None)
    if method is None:
        properties = {arg: {"type": "string"} for arg in spec["arguments"]}
        required = list(spec["arguments"])
    else:
        signature = inspect.signature(method)
        hints = get_type_hints(method)
        properties = {}
        required = []
        for name, parameter in signature.parameters.items():
            if name == "self":
                continue
            schema = _schema_for_type(hints.get(name, parameter.annotation))
            if parameter.default is not inspect.Parameter.empty:
                schema["default"] = parameter.default
            else:
                required.append(name)
            properties[name] = schema
    return {
        "name": spec["name"],
        "description": spec["description"],
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _schema_for_type(annotation: Any) -> dict[str, Any]:
    if annotation in {inspect.Parameter.empty, Any}:
        return {}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in {Union, UnionType}:
        non_null = [arg for arg in args if arg is not type(None)]
        if len(non_null) == 1:
            return _schema_for_type(non_null[0])
        return {"anyOf": [_schema_for_type(arg) for arg in non_null]}
    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        if values:
            schema.update(_schema_for_type(type(values[0])))
        return schema
    if origin is list:
        item_type = args[0] if args else Any
        return {"type": "array", "items": _schema_for_type(item_type)}
    if origin is dict:
        return {"type": "object", "additionalProperties": True}
    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is bytes:
        return {"type": "string", "contentEncoding": "base64"}
    return {}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def default_store() -> Path:
    return Path(os.environ.get("MNEME_STORE", ".mnemosyne/mcp-store.json"))


def default_backend() -> str:
    return os.environ.get("MNEME_BACKEND", "local")


def default_postgres_dsn() -> str | None:
    return os.environ.get("MNEMOSYNE_POSTGRES_DSN")


def _parametric_store_path(
    store_path: str | os.PathLike[str] | None,
    configured_path: str | os.PathLike[str] | None,
) -> Path:
    env_path = os.environ.get("MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE")
    if configured_path:
        return Path(configured_path).expanduser()
    if env_path:
        return Path(env_path).expanduser()
    if store_path:
        path = Path(store_path).expanduser()
        return path.with_suffix(path.suffix + ".parametric")
    return Path(".mnemosyne/mcp-parametric")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mneme-mcp", description="Run the Mnemosyne stdio MCP server")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--backend", choices=["local", "postgres"], default=default_backend(), help="Storage backend for MCP tools")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="Postgres DSN for --backend postgres")
    parser.add_argument("--parametric-artifact-store", default=os.environ.get("MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE"))
    parser.add_argument("--stateless", action="store_true", help="Rebuild engine and tool state for each JSON-RPC tool call")
    args = parser.parse_args(argv)
    MnemosyneMcpServer(
        store_path=args.store,
        backend=args.backend,
        postgres_dsn=args.postgres_dsn,
        parametric_artifact_store=args.parametric_artifact_store,
        stateless=args.stateless,
    ).serve()


if __name__ == "__main__":
    main()
