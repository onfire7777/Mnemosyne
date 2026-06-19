"""Minimal stdio JSON-RPC server for the Mnemosyne MCP facade."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_tools import MemoryTools, TOOL_SPEC
from mnemosyne.runtime_state import RuntimeState


PROTOCOL_VERSION = "2024-11-05"


class MnemosyneMcpServer:
    """Small JSON-RPC shim around MemoryTools.

    It intentionally keeps the transport simple and deterministic. The exposed
    methods mirror the common MCP handshake shape: initialize, tools/list, and
    tools/call.
    """

    def __init__(self, store_path: str | os.PathLike[str] | None = None):
        self.engine = LocalMemoryEngine(store_path=store_path)
        self.tools = MemoryTools(self.engine, runtime_state=RuntimeState.from_store_path(store_path))

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
                    result = _tool_result(self.call_tool(str(params.get("name")), params.get("arguments") or {}))
                except Exception as exc:  # noqa: BLE001 - tool errors are MCP results, not transport failures.
                    result = _tool_error(str(exc))
            else:
                return _error(request_id, -32601, f"Unknown method: {method}")
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001 - JSON-RPC must marshal failures.
            return _error(request_id, -32000, str(exc))

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
        if name == "correct":
            return self.tools.correct(**arguments)
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
        if name == "prefetch":
            return self.tools.prefetch(**arguments)
        if name == "graph_neighbors":
            return self.tools.graph_neighbors(**arguments)
        if name == "trajectory_log":
            return self.tools.trajectory_log(**arguments)
        if name == "trajectory_attribute":
            return self.tools.trajectory_attribute(**arguments)
        if name == "lesson_induce":
            return self.tools.lesson_induce(**arguments)
        if name == "procedure_induce":
            return self.tools.procedure_induce(**arguments)
        if name == "lesson_promote":
            return self.tools.lesson_promote(**arguments)
        if name == "procedure_validate":
            return self.tools.procedure_validate(**arguments)
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
    properties = {arg: {"type": "string"} for arg in spec["arguments"]}
    return {
        "name": spec["name"],
        "description": spec["description"],
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(spec["arguments"]),
            "additionalProperties": True,
        },
    }


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mneme-mcp", description="Run the Mnemosyne stdio MCP server")
    parser.add_argument("--store", default=str(default_store()), help="Path to local JSON store")
    args = parser.parse_args(argv)
    MnemosyneMcpServer(store_path=args.store).serve()


if __name__ == "__main__":
    main()
