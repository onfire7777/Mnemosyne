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
    ):
        if backend == "postgres":
            dsn = postgres_dsn or os.environ.get("MNEMOSYNE_POSTGRES_DSN")
            if not dsn:
                raise ValueError("Postgres MCP backend requires postgres_dsn or MNEMOSYNE_POSTGRES_DSN.")
            try:
                from mnemosyne.postgres_engine import PostgresEngine
            except ImportError as exc:  # pragma: no cover - defensive for broken installs.
                raise ValueError("Postgres MCP backend requires mnemosyne-memory[postgres].") from exc
            self.engine = PostgresEngine(dsn)
            runtime_state = None
        elif backend == "local":
            self.engine = LocalMemoryEngine(store_path=store_path)
            runtime_state = RuntimeState.from_store_path(store_path)
        else:
            raise ValueError(f"Unsupported MCP backend: {backend}")
        self.queue = InProcessQueue()
        self.auth_token = auth_token if auth_token is not None else os.environ.get("MNEMOSYNE_MCP_TOKEN")
        ingestion = IngestionPipeline(self.engine, queue=self.queue)
        self.tools = MemoryTools(self.engine, ingestion=ingestion, runtime_state=runtime_state)

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
                    if not self._authorized(params):
                        result = _tool_error("unauthorized: valid MCP auth token required")
                    else:
                        result = _tool_result(self.call_tool(str(params.get("name")), params.get("arguments") or {}))
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
        if name == "capture":
            return self.tools.capture(**arguments)
        if name == "ingest":
            return self.tools.ingest(**arguments)
        if name == "assert_fact":
            return self.tools.assert_fact(**arguments)
        if name == "relation":
            return self.tools.relation(**arguments)
        if name == "preference":
            return self.tools.preference(**arguments)
        if name == "search":
            return self.tools.search(**arguments)
        if name == "deep_search":
            return self.tools.deep_search(**arguments)
        if name == "explain":
            return self.tools.explain(**arguments)
        if name == "get":
            return self.tools.get(**arguments)
        if name == "propose":
            return self.tools.propose(**arguments)
        if name == "confirm":
            return self.tools.confirm(**arguments)
        if name == "correct":
            return self.tools.correct(**arguments)
        if name == "supersede":
            return self.tools.supersede(**arguments)
        if name == "forget":
            return self.tools.forget(**arguments)
        if name == "export":
            return self.tools.export(**arguments)
        if name == "branch":
            return self.tools.branch(**arguments)
        if name == "merge":
            return self.tools.merge(**arguments)
        if name == "discard":
            return self.tools.discard(**arguments)
        if name == "profile_add":
            return self.tools.profile_add(**arguments)
        if name == "profile_context":
            return self.tools.profile_context(**arguments)
        if name == "profile_get_relevant":
            return self.tools.profile_get_relevant(**arguments)
        if name == "profile_record_explicit":
            return self.tools.profile_record_explicit(**arguments)
        if name == "profile_propose_inference":
            return self.tools.profile_propose_inference(**arguments)
        if name == "profile_correct":
            return self.tools.profile_correct(**arguments)
        if name == "prefetch":
            return self.tools.prefetch(**arguments)
        if name == "graph_neighbors":
            return self.tools.graph_neighbors(**arguments)
        if name == "graph_query":
            return self.tools.graph_query(**arguments)
        if name == "graph_timeline":
            return self.tools.graph_timeline(**arguments)
        if name == "graph_as_of":
            return self.tools.graph_as_of(**arguments)
        if name == "trajectory_log":
            return self.tools.trajectory_log(**arguments)
        if name == "trajectory_record":
            return self.tools.trajectory_record(**arguments)
        if name == "trajectory_attribute":
            return self.tools.trajectory_attribute(**arguments)
        if name == "lesson_induce":
            return self.tools.lesson_induce(**arguments)
        if name == "lesson_propose":
            return self.tools.lesson_propose(**arguments)
        if name == "procedure_induce":
            return self.tools.procedure_induce(**arguments)
        if name == "procedure_propose":
            return self.tools.procedure_propose(**arguments)
        if name == "lesson_promote":
            return self.tools.lesson_promote(**arguments)
        if name == "procedure_validate":
            return self.tools.procedure_validate(**arguments)
        if name == "procedure_promote":
            return self.tools.procedure_promote(**arguments)
        if name == "procedure_search":
            return self.tools.procedure_search(**arguments)
        if name == "procedure_rollback":
            return self.tools.procedure_rollback(**arguments)
        if name == "lesson_search":
            return self.tools.lesson_search(**arguments)
        if name == "outcome_evaluate":
            return self.tools.outcome_evaluate(**arguments)
        if name == "parametric_propose":
            return self.tools.parametric_propose(**arguments)
        if name == "parametric_evaluate":
            return self.tools.parametric_evaluate(**arguments)
        raise ValueError(f"Unknown tool: {name}")

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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mneme-mcp", description="Run the Mnemosyne stdio MCP server")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    parser.add_argument("--backend", choices=["local", "postgres"], default=default_backend(), help="Storage backend for MCP tools")
    parser.add_argument("--postgres-dsn", default=default_postgres_dsn(), help="Postgres DSN for --backend postgres")
    args = parser.parse_args(argv)
    MnemosyneMcpServer(store_path=args.store, backend=args.backend, postgres_dsn=args.postgres_dsn).serve()


if __name__ == "__main__":
    main()
