"""Blueprint §30.7 agent-facing API (the MCP linker/ABI) parity tests.

These tests pin the MCP tool surface — ``src/mnemosyne/mcp_tools.py``
(:data:`TOOL_SPEC` + :class:`MemoryTools`) and the JSON-RPC facade in
``src/mnemosyne/mcp_server.py`` — to the canonical agent-facing API defined in
the *Mnemosyne v2 Build Blueprint* §30.7 and to the FR-9 acceptance criterion
(*"Given an MCP-compatible agent, then it can capture/search/deep_search/
explain/correct/forget without knowing internals"*).

They are deliberately **complementary** to ``tests/test_runtime_surfaces.py``,
which exercises transport mechanics (stdio / HTTP / TLS / official SDK /
residency / encryption). Here we guard *1:1 blueprint parity* of the exposed
operations and the contract of the generated tool schemas: if a future change
drops, renames, or re-signatures a blueprint operation, exactly one of these
tests fails and names the gap.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from mnemosyne.mcp_server import (
    PROTOCOL_VERSION,
    MnemosyneMcpServer,
    _schema_for_type,
    _to_mcp_tool_spec,
)
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools


# --- Blueprint §30.7 — "Agent-facing API / MCP tools (the linker/ABI)" --------
#
# Each dotted blueprint operation is mapped to the MCP tool name that implements
# it. This table is the executable transcription of the blueprint's ABI block;
# it is the single source of truth the parity tests below assert against.
BLUEPRINT_ABI: dict[str, str] = {
    # memory.* — episodic/semantic ledger + speculative-reasoning branches
    "memory.capture": "capture",
    "memory.search": "search",
    "memory.deep_search": "deep_search",
    "memory.get": "get",
    "memory.explain": "explain",
    "memory.propose": "propose",
    "memory.confirm": "confirm",
    "memory.correct": "correct",
    "memory.supersede": "supersede",
    "memory.forget": "forget",
    "memory.export": "export",
    "memory.branch": "branch",
    "memory.merge": "merge",
    "memory.discard": "discard",
    # profile.* — six-category user model
    "profile.get_relevant": "profile_get_relevant",
    "profile.record_explicit": "profile_record_explicit",
    "profile.propose_inference": "profile_propose_inference",
    "profile.correct": "profile_correct",
    # graph.* — temporal entity graph
    "graph.query": "graph_query",
    "graph.timeline": "graph_timeline",
    "graph.as_of": "graph_as_of",
    # procedure.* / lesson.* — procedural & corrective learning loop
    "procedure.search": "procedure_search",
    "procedure.propose": "procedure_propose",
    "procedure.validate": "procedure_validate",
    "procedure.promote": "procedure_promote",
    "procedure.rollback": "procedure_rollback",
    "lesson.propose": "lesson_propose",
    "lesson.search": "lesson_search",
    # trajectory.record / outcome.evaluate — feed the learning loop
    "trajectory.record": "trajectory_record",
    "outcome.evaluate": "outcome_evaluate",
}


# --- helpers -----------------------------------------------------------------


def _server(tmp_path: Path) -> MnemosyneMcpServer:
    return MnemosyneMcpServer(store_path=tmp_path / "store.json")


def _call(server: MnemosyneMcpServer, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Drive one ``tools/call`` through the JSON-RPC facade and return the result."""

    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response is not None
    return response["result"]


def _method_parameters(name: str) -> list[str]:
    return [key for key in inspect.signature(getattr(MemoryTools, name)).parameters if key != "self"]


def _required_parameters(name: str) -> list[str]:
    signature = inspect.signature(getattr(MemoryTools, name))
    return [
        key
        for key, parameter in signature.parameters.items()
        if key != "self" and parameter.default is inspect.Parameter.empty
    ]


# --- blueprint ABI parity ----------------------------------------------------


def test_blueprint_3070_abi_is_fully_exposed_in_tool_spec() -> None:
    """Every §30.7 operation is backed by a TOOL_SPEC tool + a MemoryTools method."""

    tool_names = {item["name"] for item in TOOL_SPEC}
    missing = {op: tool for op, tool in BLUEPRINT_ABI.items() if tool not in tool_names}
    assert not missing, f"blueprint §30.7 operations absent from TOOL_SPEC: {missing}"

    not_backed = {
        op: tool for op, tool in BLUEPRINT_ABI.items() if not callable(getattr(MemoryTools, tool, None))
    }
    assert not not_backed, f"blueprint operations without a MemoryTools method: {not_backed}"


def test_tools_list_advertises_every_blueprint_operation_with_valid_schema(tmp_path: Path) -> None:
    """``tools/list`` advertises each §30.7 operation with a well-formed input schema."""

    server = _server(tmp_path)
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed is not None
    tools_by_name = {tool["name"]: tool for tool in listed["result"]["tools"]}

    for op, tool in BLUEPRINT_ABI.items():
        assert tool in tools_by_name, f"{op} -> {tool} not advertised by tools/list"
        schema = tools_by_name[tool]["inputSchema"]
        assert schema["type"] == "object", op
        assert schema["additionalProperties"] is False, op
        assert set(schema["required"]).issubset(schema["properties"]), op


def test_every_tool_spec_entry_resolves_to_a_memory_tool() -> None:
    """No TOOL_SPEC tool is advertised without a concrete MemoryTools implementation."""

    orphan = [item["name"] for item in TOOL_SPEC if not callable(getattr(MemoryTools, item["name"], None))]
    assert not orphan, f"TOOL_SPEC advertises tools with no MemoryTools method: {orphan}"


# --- tool-schema generation parity ------------------------------------------


def test_tool_spec_documents_only_real_method_parameters() -> None:
    """Each TOOL_SPEC ``arguments`` hint must name a real parameter (no doc drift)."""

    drift: dict[str, list[str]] = {}
    for item in TOOL_SPEC:
        params = set(_method_parameters(item["name"]))
        unknown = [argument for argument in item["arguments"] if argument not in params]
        if unknown:
            drift[item["name"]] = unknown
    assert not drift, f"TOOL_SPEC documents arguments that are not parameters: {drift}"


def test_generated_input_schema_required_matches_method_signature() -> None:
    """The generated JSON schema mirrors the method signature exactly.

    ``required`` must equal the parameters with no default and ``properties``
    must cover every parameter — this is what keeps the advertised MCP contract
    faithful to the Python implementation as signatures evolve.
    """

    for item in TOOL_SPEC:
        spec = _to_mcp_tool_spec(item)
        schema = spec["inputSchema"]
        name = item["name"]
        assert sorted(schema["required"]) == sorted(_required_parameters(name)), name
        assert sorted(schema["properties"]) == sorted(_method_parameters(name)), name
        assert set(schema["required"]).issubset(schema["properties"]), name
        assert schema["type"] == "object", name
        assert schema["additionalProperties"] is False, name


def test_caller_context_schema_is_optional_and_reader_defaulted() -> None:
    expected = {
        "role",
        "user_id",
        "max_sensitivity",
        "capability_tags",
        "purpose",
        "residency",
        "region",
        "break_glass",
        "lawful_basis",
    }
    specs = {item["name"]: _to_mcp_tool_spec(item) for item in TOOL_SPEC}

    for name in ("search", "deep_search", "explain"):
        schema = specs[name]["inputSchema"]
        assert expected.issubset(schema["properties"])
        assert expected.isdisjoint(schema["required"])
        assert schema["properties"]["role"]["default"] == "reader"


def test_schema_for_type_maps_python_annotations_to_json_schema() -> None:
    """Primitive and container annotations map to the documented JSON-schema shapes."""

    assert _schema_for_type(str) == {"type": "string"}
    assert _schema_for_type(int) == {"type": "integer"}
    assert _schema_for_type(float) == {"type": "number"}
    assert _schema_for_type(bool) == {"type": "boolean"}
    assert _schema_for_type(bytes) == {"type": "string", "contentEncoding": "base64"}
    assert _schema_for_type(list[str]) == {"type": "array", "items": {"type": "string"}}

    optional = _schema_for_type(str | None)
    assert "anyOf" in optional
    assert {"type": "string"} in optional["anyOf"]
    assert {"type": "null"} in optional["anyOf"]


def test_ingest_schema_encodes_binary_and_list_parameters() -> None:
    """The multimodal ``ingest`` tool advertises base64 bytes and string-array tags."""

    ingest_spec = next(_to_mcp_tool_spec(item) for item in TOOL_SPEC if item["name"] == "ingest")
    properties = ingest_spec["inputSchema"]["properties"]

    assert {"type": "string", "contentEncoding": "base64"} in properties["data"]["anyOf"]
    assert {"type": "array", "items": {"type": "string"}} in properties["capability_tags"]["anyOf"]


# --- FR-9 acceptance criterion ----------------------------------------------


def test_fr9_capture_search_explain_correct_forget_lifecycle(tmp_path: Path) -> None:
    """FR-9 AC: an MCP agent runs the full memory lifecycle through tools/call only.

    The blueprint requires capture/search/deep_search/explain/correct/forget to
    work *without the agent knowing internals* — i.e. purely over the JSON-RPC
    tool envelope. Every step must return a non-error structured result.
    """

    server = _server(tmp_path)

    captured = _call(
        server,
        "capture",
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "actor": "user",
            "source_type": "chat",
            "content": "Pluto was reclassified as a dwarf planet in 2006.",
        },
    )
    assert captured["isError"] is False, captured["content"]
    cid = captured["structuredContent"]["cid"]
    assert cid

    searched = _call(server, "search", {"tenant_id": "t1", "query": "Pluto dwarf planet"})
    assert searched["isError"] is False
    assert searched["structuredContent"]["hits"][0]["provenance"] == [cid]

    for tool in ("deep_search", "explain"):
        result = _call(server, tool, {"tenant_id": "t1", "query": "Pluto dwarf planet"})
        assert result["isError"] is False, (tool, result["content"])
        assert "hits" in result["structuredContent"], tool

    # correct() defaults to role=agent with user-authored trust → belief_correction allowed.
    corrected = _call(
        server,
        "correct",
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "subject": "Pluto",
            "predicate": "classification",
            "object_value": "dwarf planet",
            "correction_text": "Per the 2006 IAU resolution.",
        },
    )
    assert corrected["isError"] is False, corrected["content"]

    # forget() defaults to role=operator (mediated destructive authority) → allowed.
    forgotten = _call(server, "forget", {"tenant_id": "t1", "cid": cid})
    assert forgotten["isError"] is False, forgotten["content"]
    assert forgotten["structuredContent"].get("erased") is not None


# --- JSON-RPC envelope contract ---------------------------------------------


def test_jsonrpc_initialize_and_method_contract(tmp_path: Path) -> None:
    """initialize advertises the protocol handshake; unknown/notification methods behave."""

    server = _server(tmp_path)

    initialized = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert initialized is not None
    result = initialized["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "mnemosyne-memory"
    assert "tools" in result["capabilities"]

    # notifications carry no response (JSON-RPC notification semantics).
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    unknown = server.handle({"jsonrpc": "2.0", "id": 2, "method": "does/not/exist"})
    assert unknown is not None
    assert unknown["error"]["code"] == -32601


def test_tool_call_error_envelope_for_unknown_tool_and_bad_arguments(tmp_path: Path) -> None:
    """Tool-layer failures surface as ``isError`` results, not JSON-RPC transport errors."""

    server = _server(tmp_path)

    unknown_tool = _call(server, "no_such_tool", {})
    assert unknown_tool["isError"] is True
    assert unknown_tool["content"][0]["type"] == "text"

    # Non-object ``arguments`` is a tool error, not a crash.
    bad_args = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search", "arguments": ["not", "an", "object"]},
        }
    )
    assert bad_args is not None
    assert bad_args["result"]["isError"] is True


def test_successful_tool_result_envelope_shape(tmp_path: Path) -> None:
    """A successful tool result carries text content + structuredContent + isError=False."""

    server = _server(tmp_path)
    result = _call(server, "residency_policy", {})
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert isinstance(result["structuredContent"], dict)


# --- blueprint alias parity --------------------------------------------------


def test_blueprint_alias_tools_match_canonical_results(tmp_path: Path) -> None:
    """Blueprint-named alias tools delegate to their canonical implementations."""

    server = _server(tmp_path)

    # graph.query is the blueprint alias for the canonical graph_neighbors tool.
    neighbors = _call(server, "graph_neighbors", {"tenant_id": "t1", "seeds": ["alpha"]})
    queried = _call(server, "graph_query", {"tenant_id": "t1", "seeds": ["alpha"]})
    assert neighbors["isError"] is False and queried["isError"] is False
    assert queried["structuredContent"]["hits"] == neighbors["structuredContent"]["hits"]
    assert queried["structuredContent"]["hops"] == 1

    # profile.get_relevant is the blueprint alias for profile_context.
    context = _call(server, "profile_context", {"tenant_id": "t1", "user_id": "u1"})
    relevant = _call(server, "profile_get_relevant", {"tenant_id": "t1", "user_id": "u1"})
    assert context["isError"] is False and relevant["isError"] is False
    assert relevant["structuredContent"] == context["structuredContent"]
