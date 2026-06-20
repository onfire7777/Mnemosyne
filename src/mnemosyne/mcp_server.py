"""Minimal stdio JSON-RPC server for the Mnemosyne MCP facade."""

from __future__ import annotations

import argparse
import asyncio
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
from mnemosyne.parametric import CommandParametricTrainer, ParametricArtifactStore, ParametricTier
from mnemosyne.queue import InProcessQueue, PostgresQueue
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.storage import CommandKeyManager, EncryptedLocalObjectStore, JsonKeyManager, LocalObjectStore


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
        parametric_provider: str | None = None,
        parametric_command: str | None = None,
        parametric_adapter_kind: str | None = None,
        parametric_timeout: float | None = None,
        stateless: bool = False,
        object_store: str | os.PathLike[str] | None = None,
        object_store_encryption: str | None = None,
        object_key_store: str | os.PathLike[str] | None = None,
        object_key_provider: str | None = None,
        object_key_command: str | None = None,
        object_key_timeout: float | None = None,
        allowed_residencies: tuple[str, ...] | None = None,
        queue_backend: str | None = None,
        queue_tenant: str | None = None,
    ):
        if backend not in {"local", "postgres"}:
            raise ValueError(f"Unsupported MCP backend: {backend}")
        resolved_queue_backend = (
            queue_backend
            or os.environ.get("MNEMOSYNE_MCP_QUEUE_BACKEND")
            or os.environ.get("MNEMOSYNE_QUEUE_BACKEND")
            or ("postgres" if backend == "postgres" else "local")
        )
        if resolved_queue_backend not in {"local", "postgres"}:
            raise ValueError(f"Unsupported MCP queue backend: {resolved_queue_backend}")
        if stateless and backend == "local" and not store_path:
            raise ValueError("Stateless local MCP mode requires a durable store_path.")
        self.store_path = store_path
        self.backend = backend
        self.postgres_dsn = postgres_dsn
        self.queue_backend = resolved_queue_backend
        self.queue_tenant = (
            queue_tenant
            or os.environ.get("MNEMOSYNE_MCP_QUEUE_TENANT")
            or os.environ.get("MNEMOSYNE_QUEUE_TENANT")
            or "system"
        )
        self.parametric_artifact_store = parametric_artifact_store
        self.parametric_provider = parametric_provider or os.environ.get("MNEMOSYNE_PARAMETRIC_PROVIDER", "local")
        self.parametric_command = parametric_command or os.environ.get("MNEMOSYNE_PARAMETRIC_COMMAND")
        self.parametric_adapter_kind = parametric_adapter_kind or os.environ.get(
            "MNEMOSYNE_PARAMETRIC_ADAPTER_KIND", "command-parametric-adapter"
        )
        self.parametric_timeout = parametric_timeout or float(os.environ.get("MNEMOSYNE_PARAMETRIC_TIMEOUT", "300"))
        self.object_store = object_store or os.environ.get("MNEMOSYNE_OBJECT_STORE") or ".mnemosyne/objects"
        self.object_store_encryption = object_store_encryption or os.environ.get("MNEMOSYNE_OBJECT_STORE_ENCRYPTION", "none")
        self.object_key_store = object_key_store or os.environ.get("MNEMOSYNE_OBJECT_KEY_STORE")
        self.object_key_provider = object_key_provider or _default_object_key_provider()
        self.object_key_command = object_key_command or os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND")
        self.object_key_timeout = object_key_timeout or float(os.environ.get("MNEMOSYNE_OBJECT_KEY_TIMEOUT", "30"))
        self.allowed_residencies = allowed_residencies or _default_allowed_residencies()
        self.stateless = stateless
        self.auth_token = auth_token if auth_token is not None else os.environ.get("MNEMOSYNE_MCP_TOKEN")
        self.tool_names = {item["name"] for item in TOOL_SPEC}
        if not self.stateless:
            self.engine, self.queue, self.runtime_state, self.tools = self._build_tools()

    def _build_tools(self, queue_tenant: str | None = None) -> tuple[Any, Any, RuntimeState | None, MemoryTools]:
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
        if self.queue_backend == "postgres":
            dsn = self.postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
            if not dsn:
                raise ValueError("Postgres MCP queue backend requires postgres_dsn or MNEMOSYNE_POSTGRES_DSN.")
            queue = PostgresQueue(dsn, tenant_id=queue_tenant or self.queue_tenant)
        else:
            queue = runtime_state.load_queue() if runtime_state else InProcessQueue()
        ingestion = IngestionPipeline(
            engine,
            object_store=_load_object_store(
                self.object_store,
                self.object_store_encryption,
                self.object_key_store,
                self.object_key_provider,
                self.object_key_command,
                self.object_key_timeout,
            ),
            queue=queue,
            allowed_residencies=self.allowed_residencies,
        )
        parametric = ParametricTier(
            ParametricArtifactStore(_parametric_store_path(self.store_path, self.parametric_artifact_store)),
            trainer=_load_parametric_trainer(
                self.parametric_provider,
                self.parametric_command,
                self.parametric_adapter_kind,
                self.parametric_timeout,
            ),
        )
        tools = MemoryTools(engine, ingestion=ingestion, runtime_state=runtime_state, parametric=parametric)
        return engine, queue, runtime_state, tools

    @staticmethod
    def _save_queue(runtime_state: RuntimeState | None, queue: Any) -> None:
        if runtime_state and isinstance(queue, InProcessQueue):
            runtime_state.save_queue(queue)


    @staticmethod
    def _queue_tenant_from_arguments(arguments: dict[str, Any]) -> str | None:
        for key in ("tenant_id", "tenant"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                return value
        return None


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
            _, queue, runtime_state, tools = self._build_tools(self._queue_tenant_from_arguments(arguments))
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


def build_sdk_server(**kwargs: Any) -> Any:
    """Build an official MCP SDK server around the Mnemosyne tool facade."""

    try:
        import jsonschema
        from mcp import types
        from mcp.server.lowlevel import Server
    except ImportError as exc:  # pragma: no cover - exercised when optional extra is absent.
        raise RuntimeError("Official MCP SDK mode requires `mnemosyne-memory[mcp]`.") from exc

    facade = MnemosyneMcpServer(**kwargs)
    tool_specs = [_to_mcp_tool_spec(item) for item in TOOL_SPEC]
    schemas_by_name = {item["name"]: item["inputSchema"] for item in tool_specs}
    server = Server("mnemosyne-memory", version="0.1.0")

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return [types.Tool(**item) for item in tool_specs]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any] | Any:
        raw_arguments = dict(arguments or {})
        auth_params: dict[str, Any] = {}
        if "auth_token" in raw_arguments:
            auth_params["auth_token"] = raw_arguments.pop("auth_token")
        meta = raw_arguments.pop("_meta", None)
        if isinstance(meta, dict):
            auth_params["_meta"] = meta
        if not facade._authorized(auth_params):
            return _sdk_tool_error(types, "unauthorized: valid MCP auth token required")
        schema = schemas_by_name.get(name)
        if schema is None:
            return _sdk_tool_error(types, f"Unknown tool: {name}")
        try:
            jsonschema.validate(instance=raw_arguments, schema=schema)
        except jsonschema.ValidationError as exc:
            return _sdk_tool_error(types, f"Input validation error: {exc.message}")
        try:
            return facade.call_tool(name, raw_arguments)
        except Exception as exc:  # noqa: BLE001 - SDK tool calls report failures as tool results.
            return _sdk_tool_error(types, str(exc))

    return server


def _sdk_tool_error(types_module: Any, message: str) -> Any:
    return types_module.CallToolResult(
        content=[types_module.TextContent(type="text", text=message)],
        isError=True,
    )


async def _serve_sdk_stdio(server: Any) -> None:
    try:
        from mcp.server.stdio import stdio_server
    except ImportError as exc:  # pragma: no cover - exercised when optional extra is absent.
        raise RuntimeError("Official MCP SDK mode requires `mnemosyne-memory[mcp]`.") from exc

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve_sdk_stdio(**kwargs: Any) -> None:
    asyncio.run(_serve_sdk_stdio(build_sdk_server(**kwargs)))


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


def _load_parametric_trainer(
    provider: str,
    command: str | None,
    adapter_kind: str,
    timeout: float,
) -> CommandParametricTrainer | None:
    if provider == "local":
        return None
    if provider == "command":
        if not command:
            raise ValueError("parametric provider command requires parametric_command.")
        return CommandParametricTrainer(command, adapter_kind=adapter_kind, timeout_seconds=timeout)
    raise ValueError(f"Unsupported parametric provider: {provider}")


def _default_allowed_residencies() -> tuple[str, ...]:
    raw = os.environ.get("MNEMOSYNE_ALLOWED_RESIDENCIES", "local")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _default_object_key_provider() -> str:
    return os.environ.get("MNEMOSYNE_OBJECT_KEY_PROVIDER") or (
        "command" if os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND") else "json"
    )


def _load_object_store(
    root: str | os.PathLike[str],
    encryption: str,
    key_store: str | os.PathLike[str] | None,
    key_provider: str,
    key_command: str | None,
    key_timeout: float,
) -> LocalObjectStore:
    if encryption == "aesgcm":
        if key_provider == "command":
            if not key_command:
                raise ValueError("object key provider command requires object_key_command.")
            return EncryptedLocalObjectStore(
                Path(root),
                CommandKeyManager(key_command, timeout_seconds=key_timeout),
            )
        if key_provider != "json":
            raise ValueError(f"Unsupported object key provider: {key_provider}")
        keys = Path(key_store).expanduser() if key_store else Path(root).expanduser() / ".keys.json"
        return EncryptedLocalObjectStore(Path(root), JsonKeyManager(keys))
    if encryption != "none":
        raise ValueError(f"Unsupported object-store encryption: {encryption}")
    return LocalObjectStore(Path(root))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mneme-mcp", description="Run the Mnemosyne stdio MCP server")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--backend", choices=["local", "postgres"], default=default_backend(), help="Storage backend for MCP tools")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="Postgres DSN for --backend postgres")
    parser.add_argument("--object-store", default=os.environ.get("MNEMOSYNE_OBJECT_STORE", ".mnemosyne/objects"))
    parser.add_argument(
        "--object-store-encryption",
        choices=["none", "aesgcm"],
        default=os.environ.get("MNEMOSYNE_OBJECT_STORE_ENCRYPTION", "none"),
    )
    parser.add_argument("--object-key-store", default=os.environ.get("MNEMOSYNE_OBJECT_KEY_STORE"))
    parser.add_argument(
        "--object-key-provider",
        choices=["json", "command"],
        default=_default_object_key_provider(),
        help="Envelope-key manager for encrypted MCP object storage",
    )
    parser.add_argument(
        "--object-key-command",
        default=os.environ.get("MNEMOSYNE_OBJECT_KEY_COMMAND"),
        help="Command key provider invoked as '<command> <action>' with JSON stdin",
    )
    parser.add_argument(
        "--object-key-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_OBJECT_KEY_TIMEOUT", "30")),
        help="Timeout in seconds for --object-key-provider command",
    )
    parser.add_argument(
        "--allowed-residency",
        action="append",
        default=list(_default_allowed_residencies()),
        help="Allowed data residency label for MCP ingestion; repeat or use MNEMOSYNE_ALLOWED_RESIDENCIES",
    )
    parser.add_argument("--parametric-artifact-store", default=os.environ.get("MNEMOSYNE_PARAMETRIC_ARTIFACT_STORE"))
    parser.add_argument(
        "--parametric-provider",
        choices=["local", "command"],
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_PROVIDER", "local"),
        help="Parametric-tier provider for LoRA/test-time-training adapter artifacts",
    )
    parser.add_argument(
        "--parametric-command",
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_COMMAND"),
        help="Command provider invoked as '<command> <action>' with JSON stdin",
    )
    parser.add_argument(
        "--parametric-adapter-kind",
        default=os.environ.get("MNEMOSYNE_PARAMETRIC_ADAPTER_KIND", "command-parametric-adapter"),
        help="Adapter kind label for --parametric-provider command",
    )
    parser.add_argument(
        "--parametric-timeout",
        type=float,
        default=float(os.environ.get("MNEMOSYNE_PARAMETRIC_TIMEOUT", "300")),
        help="Timeout in seconds for --parametric-provider command",
    )
    parser.add_argument(
        "--queue-backend",
        choices=["local", "postgres"],
        default=os.environ.get("MNEMOSYNE_MCP_QUEUE_BACKEND") or os.environ.get("MNEMOSYNE_QUEUE_BACKEND"),
        help="Runtime job queue backend for MCP ingestion",
    )
    parser.add_argument(
        "--queue-tenant",
        default=os.environ.get("MNEMOSYNE_MCP_QUEUE_TENANT") or os.environ.get("MNEMOSYNE_QUEUE_TENANT"),
        help="Fallback tenant scope for MCP Postgres queue jobs",
    )
    parser.add_argument("--stateless", action="store_true", help="Rebuild engine and tool state for each JSON-RPC tool call")
    parser.add_argument("--sdk", action="store_true", help="Use the official MCP Python SDK stdio transport")
    parser.add_argument("--auth-token", default=os.environ.get("MNEMOSYNE_MCP_TOKEN"), help="Require this token for tools/call")
    args = parser.parse_args(argv)
    config = {
        "store_path": args.store,
        "auth_token": args.auth_token,
        "backend": args.backend,
        "postgres_dsn": args.postgres_dsn,
        "object_store": args.object_store,
        "object_store_encryption": args.object_store_encryption,
        "object_key_store": args.object_key_store,
        "object_key_provider": args.object_key_provider,
        "object_key_command": args.object_key_command,
        "object_key_timeout": args.object_key_timeout,
        "allowed_residencies": tuple(args.allowed_residency),
        "parametric_artifact_store": args.parametric_artifact_store,
        "parametric_provider": args.parametric_provider,
        "parametric_command": args.parametric_command,
        "parametric_adapter_kind": args.parametric_adapter_kind,
        "parametric_timeout": args.parametric_timeout,
        "queue_backend": args.queue_backend,
        "queue_tenant": args.queue_tenant,
        "stateless": args.stateless,
    }
    if args.sdk:
        serve_sdk_stdio(**config)
    else:
        MnemosyneMcpServer(**config).serve()


if __name__ == "__main__":
    main()
