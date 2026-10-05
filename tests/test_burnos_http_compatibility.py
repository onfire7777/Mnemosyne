"""BurnOS's HTTP wire contract, independent of the Python MCP client.

Source: onfire7777/Burnos@a195ea724986114e9ca682bd7689d853264ea5ca,
mcp.cpp (transport/token) and agent.cpp (memory requests). This is a server
compatibility regression, not a Windows application end-to-end test.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from mnemosyne.mcp_server import build_sdk_streamable_http_app


def test_burnos_http_conversation_contract(tmp_path) -> None:
    pytest.importorskip("mcp")
    httpx = pytest.importorskip("httpx")
    secret = "burnos-wire-test-secret"
    now = datetime.now(UTC)
    scope = {
        "tenant_id": "burnos-wire-tenant",
        "user_id": "burnos-wire-user",
        "agent_id": "burnos",
        "session_id": "voice",
    }
    # BurnOS signs compact, base64url JSON bytes with HMAC-SHA256. Do not use
    # our signer here: the client/server agreement is what this test checks.
    claims = {
        **scope,
        "role": "agent",
        "source_trust_tier": 0,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    ).rstrip(b"=")
    token = (payload + b"." + signature).decode()
    app = build_sdk_streamable_http_app(
        backend="sqlite",
        store_path=tmp_path / "memory",
        session_secret=secret,
    )

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2024-11-05",
                },
            ) as client:
                request_id = 0

                async def rpc(method, params):
                    nonlocal request_id
                    request_id += 1
                    response = await client.post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": method,
                            "params": params,
                        },
                    )
                    assert response.status_code == 200, response.text
                    message = response.json()
                    assert message["id"] == request_id
                    assert "error" not in message, message
                    return message["result"]

                async def call(name, arguments):
                    result = await rpc(
                        "tools/call", {"name": name, "arguments": arguments}
                    )
                    assert not result.get("isError"), result
                    return result["structuredContent"]

                hello = await rpc(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "Burnos", "version": "0.4"},
                    },
                )
                assert hello["protocolVersion"] == "2024-11-05"
                notified = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                )
                assert notified.status_code == 202
                schemas = {
                    tool["name"]: tool["inputSchema"]["properties"]
                    for tool in (await rpc("tools/list", {}))["tools"]
                }
                assert {"session_id", "token_budget", "lean"} <= schemas[
                    "search"
                ].keys()
                assert {"limit", "kinds"} <= schemas["working_query"].keys()
                captured = await call(
                    "capture",
                    {
                        "tenant_id": scope["tenant_id"],
                        "user_id": scope["user_id"],
                        "actor": "user",
                        "trust_tier": 0,
                        "source_type": "conversation",
                        "content": "The kayak budget is four hundred dollars.",
                        "session_id": scope["session_id"],
                    },
                )
                working = {
                    **scope,
                    "task_id": "talk",
                    "branch": "main",
                    "session_token": token,
                }
                content = "user: The kayak budget is four hundred dollars."
                await call(
                    "working_seed",
                    {
                        **working,
                        "item_id": captured["cid"],
                        "kind": "conversation_turn",
                        "content": content,
                        "evidence_ids": [captured["cid"]],
                        "ttl_seconds": 600,
                        "created_at": now.isoformat(),
                    },
                )
                queried = await call(
                    "working_query",
                    {
                        **working,
                        "as_of": now.isoformat(),
                        "limit": 20,
                        "kinds": ["conversation_turn"],
                    },
                )
                assert [item["content"] for item in queried["items"]] == [content]
                search = {
                    "tenant_id": scope["tenant_id"],
                    "user_id": scope["user_id"],
                    "session_id": scope["session_id"],
                    "session_token": token,
                    "query": "kayak budget",
                    "token_budget": 200,
                    "lean": True,
                }
                found = await call("search", search)
                assert found["hits"] and found["used_tokens"] <= 200
                assert "explain" not in found
                assert "four hundred" in json.dumps(found["hits"])
                refused = await rpc(
                    "tools/call",
                    {
                        "name": "search",
                        "arguments": {
                            **search,
                            "session_id": "another-session",
                        },
                    },
                )
                assert refused["isError"] is True

    asyncio.run(exercise())
