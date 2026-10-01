"""Session-aware reads (M1) and the profile entries a client can rely on.

A dialogue agent keeps its whole conversation in Mnemosyne: each line goes to
the ledger and, citing that record, to the session's working memory. These
tests pin what such a client reads back - on every backend, because the
behaviour lives in the shared pipeline and engine layer:

* ``working_query`` narrowed by ``limit`` and ``kinds``;
* ``search`` / ``deep_search`` ranking a session's working items with long-term
  memory, on proof of that session only, one hit per turn;
* hits that say which plane they are from and when they were made;
* a smaller answer on request (``token_budget``, ``lean``);
* the build the server reports;
* profile entries that can be corrected, taken back, and forgotten.

Everything is additive: a call that does not use the new arguments takes the
long-term path it always took.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from mnemosyne import buildinfo
from mnemosyne.engine import LocalMemoryEngine, select_working_items
from mnemosyne.mcp_server import MnemosyneMcpServer, build_sdk_server
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Hit
from mnemosyne.pipeline import (
    LEAN_HIT_DIAGNOSTIC_KEYS,
    _collapse_session_duplicates,
    _same_words,
    lean_retrieval_payload,
    requested_token_budget,
)
from mnemosyne.policy import OperatingPolicy
from mnemosyne.postgres_engine import PostgresEngine
from mnemosyne.security import SessionIdentity, SessionTokenVerifier
from mnemosyne.runtime_state import RuntimeState
from mnemosyne.sqlite_engine import SqliteEngine
from mnemosyne.user_model import ERASED_STATEMENT, UserMemoryKind, UserModel, UserModelEntry

SESSION = "voice"
AGENT = "burnos"
SECRET = "session-aware-reads-secret"
WORDS = ["amber", "birch", "cobalt", "dune", "ember", "fjord"]
NOTE = "Notes: the agreed budget for the kayak is four hundred dollars."
KAYAK = "what is the agreed budget for the kayak"
WIDE = "Session turn number the harness said the word"


@pytest.fixture(params=["local", "postgres", "sqlite"])
def engine_bundle(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Any, str, str]:
    tenant = f"tenant-session-{request.param}-{uuid4()}"
    user = f"user-session-{request.param}"
    if request.param == "local":
        return LocalMemoryEngine(store_path=tmp_path / "local-store.json"), tenant, user
    if request.param == "sqlite":
        return SqliteEngine(tmp_path / "sqlite-store"), tenant, user
    dsn = os.environ.get("MNEMOSYNE_POSTGRES_DSN")
    if not dsn:
        pytest.skip("MNEMOSYNE_POSTGRES_DSN is not set")
    pytest.importorskip("psycopg")
    return PostgresEngine(dsn), tenant, user


def _identity(tenant: str, user: str, session: str = SESSION, agent: str | None = AGENT) -> SessionIdentity:
    return SessionIdentity(
        tenant_id=tenant,
        user_id=user,
        role="agent",
        source_trust_tier=0,
        agent_id=agent,
        session_id=session,
    )


def _scope(tenant: str, user: str, identity: SessionIdentity) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "session_id": identity.session_id,
        "user_id": user,
        "agent_id": identity.agent_id,
        "task_id": "talk",
        "branch": "main",
        "session_identity": identity,
    }


def _seed_conversation(tools: MemoryTools, tenant: str, user: str) -> tuple[SessionIdentity, list[str]]:
    """Six spoken turns in both planes, and one note that lives only in working memory."""

    identity = _identity(tenant, user)
    scope = _scope(tenant, user, identity)
    base = datetime.now(UTC) - timedelta(seconds=120)
    cids: list[str] = []
    for index, word in enumerate(WORDS):
        text = f"Session turn number {index}: the harness said the word {word}."
        captured = tools.capture(
            tenant_id=tenant,
            user_id=user,
            actor="user",
            source_type="conversation",
            content=text,
            session_id=SESSION,
        )
        cids.append(captured["cid"])
        tools.working_seed(
            **scope,
            kind="conversation_turn",
            content="user: " + text,
            evidence_ids=[captured["cid"]],
            ttl_seconds=3600,
            created_at=(base + timedelta(seconds=index)).isoformat(),
        )
    tools.working_seed(
        **scope,
        kind="intermediate_conclusion",
        content=NOTE,
        evidence_ids=[cids[0]],
        ttl_seconds=3600,
        created_at=(base + timedelta(seconds=30)).isoformat(),
    )
    return identity, cids


def _texts(result: dict[str, Any]) -> str:
    return " | ".join(hit["text"] for hit in result["hits"]).lower()


# ---------------------------------------------------------------------------
# 1. working_query: limit and kinds
# ---------------------------------------------------------------------------


def test_select_working_items_narrows_a_newest_first_list() -> None:
    items = [
        SimpleNamespace(kind="conversation_turn", content="newest"),
        SimpleNamespace(kind="intermediate_conclusion", content="note"),
        SimpleNamespace(kind="conversation_turn", content="oldest"),
    ]

    assert select_working_items(items) == items
    assert [item.content for item in select_working_items(items, limit=2)] == ["newest", "note"]
    assert [item.content for item in select_working_items(items, kinds=["conversation_turn"])] == ["newest", "oldest"]
    assert [item.content for item in select_working_items(items, kinds=["conversation_turn"], limit=1)] == ["newest"]
    assert select_working_items(items, kinds=[]) == []


@pytest.mark.parametrize("limit", [0, -1, True, 2.0, "3"])
def test_select_working_items_refuses_a_limit_that_is_not_a_positive_integer(limit: Any) -> None:
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        select_working_items([], limit=limit)


@pytest.mark.parametrize("kinds", ["conversation_turn", ["no_such_kind"], [1]])
def test_select_working_items_refuses_unknown_kinds(kinds: Any) -> None:
    with pytest.raises(ValueError):
        select_working_items([], kinds=kinds)


def test_working_query_limit_and_kinds(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    identity, _ = _seed_conversation(tools, tenant, user)
    scope = _scope(tenant, user, identity)
    now = datetime.now(UTC).isoformat()

    everything = tools.working_query(**scope, as_of=now)["items"]
    newest = tools.working_query(**scope, as_of=now, limit=3, kinds=["conversation_turn"])["items"]
    notes = tools.working_query(**scope, as_of=now, kinds=["intermediate_conclusion"])["items"]
    capped = tools.working_query(**scope, as_of=now, limit=2)["items"]

    assert len(everything) == 7
    assert [item["content"].rsplit(" ", 1)[-1] for item in newest] == ["fjord.", "ember.", "dune."]
    assert [item["kind"] for item in notes] == ["intermediate_conclusion"]
    assert capped == everything[:2]
    with pytest.raises(ValueError, match="limit must be a positive integer"):
        tools.working_query(**scope, as_of=now, limit=0)


# ---------------------------------------------------------------------------
# 2 and 3. search with the session: one ranked list, one hit per turn, dated
# ---------------------------------------------------------------------------


def test_search_ranks_the_sessions_working_memory_with_long_term_memory(
    engine_bundle: tuple[Any, str, str],
) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    identity, cids = _seed_conversation(tools, tenant, user)

    with_session = tools.search(
        tenant_id=tenant, query=KAYAK, user_id=user, role="agent",
        session_id=SESSION, session_identity=identity,
    )
    without = tools.search(tenant_id=tenant, query=KAYAK, user_id=user, role="agent")

    assert "four hundred" in _texts(with_session)
    assert "four hundred" not in _texts(without)
    assert with_session["explain"]["working_memory"]["status"] == "applied"
    # Without the session nothing is asked of the working store at all.
    assert "working_memory" not in without["explain"]
    assert all(hit["kind"] != "working" for hit in without["hits"])

    for hit in with_session["hits"]:
        metadata = hit["metadata"]
        assert metadata["memory_type"] == ("working" if hit["kind"] == "working" else hit["kind"])
        assert datetime.fromisoformat(metadata["created_at"]).tzinfo is not None
        assert metadata["created_at_source"] in {"record", "source_evidence"}
    note = next(hit for hit in with_session["hits"] if "four hundred" in hit["text"])
    assert note["kind"] == "working"
    assert note["metadata"]["working_kind"] == "intermediate_conclusion"
    assert note["metadata"]["evidence_ids"] == [cids[0]]
    assert note["provenance"] == [cids[0]]
    # Evidence hits are dated too, without the session.
    assert all(hit["metadata"].get("created_at") for hit in without["hits"])


def test_a_turn_held_in_both_planes_comes_back_once(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    identity, cids = _seed_conversation(tools, tenant, user)

    result = tools.deep_search(
        tenant_id=tenant, query="which turn said the word cobalt", user_id=user, role="agent",
        session_id=SESSION, session_identity=identity,
    )

    cobalt = [hit for hit in result["hits"] if "cobalt" in hit["text"].lower()]
    assert len(cobalt) == 1
    # The durable record survives, carrying the cid, and names the working copy.
    assert cobalt[0]["kind"] == "evidence"
    assert cobalt[0]["id"] == cids[2]
    assert len(cobalt[0]["metadata"]["working_item_ids"]) == 1
    assert cobalt[0]["metadata"]["working_session_id"] == SESSION
    assert "working_memory" in cobalt[0]["channel"].split("+")
    assert result["explain"]["working_memory"]["collapsed_count"] >= 1


def test_a_session_search_is_never_served_from_the_result_cache(
    engine_bundle: tuple[Any, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MNEMOSYNE_RETRIEVAL_RESULT_CACHE_SIZE", "8")
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    identity, cids = _seed_conversation(tools, tenant, user)
    ask = {
        "tenant_id": tenant, "query": "what is the budget for the paddle", "user_id": user, "role": "agent",
        "session_id": SESSION, "session_identity": identity,
    }

    before = tools.search(**ask)
    assert "retrieval_result_cache" not in before["explain"]
    assert "ninety dollars" not in _texts(before)

    # Seeded after the first answer, and gone two seconds later - by the clock alone.
    tools.working_seed(
        **_scope(tenant, user, identity),
        kind="intermediate_conclusion",
        content="Notes: the budget for the paddle is ninety dollars.",
        evidence_ids=[cids[1]],
        ttl_seconds=2,
        created_at=datetime.now(UTC).isoformat(),
    )
    assert "ninety dollars" in _texts(tools.search(**ask))
    time.sleep(2.2)
    after = tools.search(**ask)
    assert "ninety dollars" not in _texts(after)
    assert "retrieval_result_cache" not in after["explain"]


def test_session_search_is_refused_without_proof_of_that_session(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    _seed_conversation(tools, tenant, user)

    with pytest.raises(PermissionError, match="verified session identity is required"):
        tools.search(tenant_id=tenant, query=KAYAK, user_id=user, session_id=SESSION)
    with pytest.raises(PermissionError, match="session mismatch"):
        tools.search(
            tenant_id=tenant, query=KAYAK, user_id=user, session_id=SESSION,
            session_identity=_identity(tenant, user, session="another-session"),
        )
    with pytest.raises(PermissionError):
        tools.deep_search(
            tenant_id=tenant, query=KAYAK, user_id=user, session_id=SESSION,
            session_identity=_identity(tenant, "somebody-else"),
        )
    with pytest.raises(PermissionError, match="agent mismatch"):
        tools.search(
            tenant_id=tenant, query=KAYAK, user_id=user, session_id=SESSION,
            session_identity=_identity(tenant, user, agent=None),
        )
    with pytest.raises(ValueError, match="session_id must be a non-empty string"):
        tools.search(
            tenant_id=tenant, query=KAYAK, user_id=user, session_id="  ",
            session_identity=_identity(tenant, user),
        )


def test_session_search_shows_only_the_token_subjects_items(engine_bundle: tuple[Any, str, str]) -> None:
    """Another agent's items in the same session never reach this token's holder."""

    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    _seed_conversation(tools, tenant, user)

    other_agent = _identity(tenant, user, agent="another-agent")
    result = tools.search(
        tenant_id=tenant, query=KAYAK, user_id=user, role="agent",
        session_id=SESSION, session_identity=other_agent,
    )

    assert "four hundred" not in _texts(result)
    assert all(hit["kind"] != "working" for hit in result["hits"])


def test_same_words_is_about_the_line_not_its_labels() -> None:
    line = "remember that my favourite colour is green"

    assert _same_words("user: " + line, "[2026-09-30 12:08:46] User: " + line, spoken=True)
    assert _same_words("assistant: Got it.", "[2026-09-30 12:08:49] Burnos: Got it.", spoken=True)
    assert _same_words("user: yes", "[2026-10-01 09:00:00] User: yes", spoken=True)
    # Either copy may carry the label, and only one label is ever set aside.
    assert _same_words("user: Rumour: the gate moved", "Rumour: the gate moved", spoken=True)
    assert not _same_words("user: Rumour: the gate moved", "the gate moved", spoken=True)
    assert not _same_words(NOTE, "Session turn number 0: the harness said the word amber.", spoken=True)
    assert not _same_words("", "anything", spoken=True)
    # A shorter line is a different memory, even when every token of it sits inside the longer one.
    assert not _same_words("4411", "the old gate code is 4411", spoken=True)
    assert not _same_words("[note] the gate code is 4411", "the gate code is 4411")
    assert _same_words("[2026-10-01 09:00:00] the gate code is 4411", "the gate code is 4411")


def test_a_speaker_label_is_only_set_aside_for_a_line_of_conversation() -> None:
    assert _same_words("user: the gate code is 4411", "the gate code is 4411", spoken=True)
    # Outside a conversation the first word and its colon are part of what the note says.
    assert not _same_words("Rumour: the gate code is 4411", "the gate code is 4411")
    assert not _same_words("user: the gate code is 4411", "the gate code is 4411")
    # A bracket that is not a timestamp is part of the line in a conversation too.
    for spoken in (False, True):
        assert not _same_words("[unconfirmed] the gate code is 4411", "the gate code is 4411", spoken=spoken)
        assert not _same_words("[draft] User: the gate code is 4411", "user: the gate code is 4411", spoken=spoken)


def test_collapse_keeps_a_working_item_that_says_something_else() -> None:
    def hit(kind: str, id: str, text: str, score: float, working_kind: str = "conversation_turn") -> Hit:
        return Hit(id=id, kind=kind, tenant_id="t", branch="main", text=text, score=score,
                   channel="working_memory" if kind == "working" else "lexical", provenance=["cid-1"],
                   metadata={"session_id": SESSION, "working_kind": working_kind} if kind == "working" else {})

    record = hit("evidence", "cid-1", "[2026-10-01 09:00:00] the gate code is 4411", 0.02)
    turn = hit("working", "item-1", "user: the gate code is 4411", 0.03)
    note = hit("working", "item-2", "Notes: buy a new padlock", 0.01, "intermediate_conclusion")
    # A note ABOUT the line - the same words behind a qualifier - is not a copy of it.
    doubt = hit("working", "item-3", "Unconfirmed: the gate code is 4411", 0.01, "intermediate_conclusion")
    hits = [turn, record, note, doubt]

    collapsed, count = _collapse_session_duplicates(hits)

    assert count == 1
    assert [item.id for item in collapsed] == ["cid-1", "item-2", "item-3"]
    assert collapsed[0].score == pytest.approx(0.05)
    assert collapsed[0].metadata["working_item_ids"] == ["item-1"]
    # The caller's own hit objects are never written into.
    assert "working_item_ids" not in record.metadata and record.score == 0.02
    assert _collapse_session_duplicates([turn, note]) == ([turn, note], 0)


# ---------------------------------------------------------------------------
# 4. a smaller answer on request
# ---------------------------------------------------------------------------


def test_token_budget_fits_the_hits_and_never_exceeds_the_policy(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    _seed_conversation(tools, tenant, user)
    policy_budget = engine.policy.token_budget

    small = tools.search(tenant_id=tenant, query=WIDE, user_id=user, token_budget=40)
    huge = tools.search(tenant_id=tenant, query=WIDE, user_id=user, token_budget=policy_budget * 25)
    plain = tools.search(tenant_id=tenant, query=WIDE, user_id=user)
    deep = tools.deep_search(tenant_id=tenant, query=WIDE, user_id=user, token_budget=40)

    assert small["hits"] and small["used_tokens"] <= 40 and small["token_budget"] == 40
    assert deep["hits"] and deep["used_tokens"] <= 40 and deep["token_budget"] == 40
    assert len(small["hits"]) < len(plain["hits"])
    # Above the policy the request is clamped, not refused.
    assert huge["token_budget"] == policy_budget == plain["token_budget"]
    for bad in (0, -5, True):
        with pytest.raises(ValueError, match="token_budget must be a positive integer"):
            tools.search(tenant_id=tenant, query=WIDE, user_id=user, token_budget=bad)


def test_requested_token_budget_rules() -> None:
    policy = OperatingPolicy()

    assert requested_token_budget({}, policy) == policy.token_budget
    assert requested_token_budget({"token_budget": 40}, policy) == 40
    assert requested_token_budget({"token_budget": policy.token_budget + 1}, policy) == policy.token_budget
    for bad in (0, -1, 1.5, "40", False):
        with pytest.raises(ValueError):
            requested_token_budget({"token_budget": bad}, policy)


def test_lean_leaves_out_explain_and_diagnostics_and_nothing_else(engine_bundle: tuple[Any, str, str]) -> None:
    engine, tenant, user = engine_bundle
    tools = MemoryTools(engine)
    identity, _ = _seed_conversation(tools, tenant, user)
    ask = {"tenant_id": tenant, "query": KAYAK, "user_id": user, "role": "agent",
           "session_id": SESSION, "session_identity": identity}

    full = tools.search(**ask)
    lean = tools.search(**ask, lean=True)

    assert "explain" in full and "explain" not in lean
    assert {hit["id"] for hit in lean["hits"]} == {hit["id"] for hit in full["hits"]}
    for key in ("query", "abstained", "uncertainty_note", "token_budget", "used_tokens"):
        assert lean[key] == full[key]
    assert any(set(LEAN_HIT_DIAGNOSTIC_KEYS) & set(hit["metadata"]) for hit in full["hits"])
    for hit in lean["hits"]:
        assert not set(LEAN_HIT_DIAGNOSTIC_KEYS) & set(hit["metadata"])
        assert {"memory_type", "created_at"} <= set(hit["metadata"])
        assert {"id", "kind", "text", "score", "channel", "trust_tier", "provenance"} <= set(hit)
    assert len(json.dumps(lean)) * 3 <= len(json.dumps(full))


def test_lean_payload_does_not_touch_the_payload_it_is_given() -> None:
    payload = {"query": "q", "explain": {"rails": {}}, "hits": [{"id": "a", "metadata": {"standing": {}, "actor": "user"}}]}

    lean = lean_retrieval_payload(payload)

    assert lean == {"query": "q", "hits": [{"id": "a", "metadata": {"actor": "user"}}]}
    assert payload["hits"][0]["metadata"] == {"standing": {}, "actor": "user"} and "explain" in payload


# ---------------------------------------------------------------------------
# The transport: declared arguments, a token that proves but never requests
# ---------------------------------------------------------------------------


def _rpc(server: MnemosyneMcpServer, name: str, arguments: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    response = server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    assert response is not None
    result = response["result"]
    text = " ".join(part.get("text", "") for part in result.get("content", []))
    payload = result.get("structuredContent")
    if not isinstance(payload, dict):
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {}
    return bool(result.get("isError")), payload if isinstance(payload, dict) else {}, text


def _seed_over_rpc(server: MnemosyneMcpServer, tenant: str, user: str, token: str) -> None:
    failed, captured, text = _rpc(server, "capture", {
        "tenant_id": tenant, "user_id": user, "actor": "user", "source_type": "conversation",
        "content": "The kayak is stored in the blue shed.", "session_id": SESSION,
    })
    assert not failed, text
    failed, _, text = _rpc(server, "working_seed", {
        "session_token": token, "tenant_id": tenant, "session_id": SESSION, "user_id": user,
        "agent_id": AGENT, "task_id": "talk", "branch": "main", "kind": "intermediate_conclusion",
        "content": NOTE, "evidence_ids": [captured["cid"]], "ttl_seconds": 600,
        "created_at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
    })
    assert not failed, text


def test_transport_token_proves_the_session_but_never_requests_it(tmp_path: Path) -> None:
    tenant, user = "tenant-transport", "user-transport"
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", session_secret=SECRET)
    verifier = SessionTokenVerifier(SECRET)
    token = verifier.sign(_identity(tenant, user))
    try:
        _seed_over_rpc(server, tenant, user, token)
        ask = {"tenant_id": tenant, "user_id": user, "query": KAYAK}

        failed, signed_only, text = _rpc(server, "search", {**ask, "session_token": token})
        assert not failed, text
        # A signed search that does not name a session answers as it always has.
        assert "working_memory" not in signed_only["explain"]
        assert "four hundred" not in _texts(signed_only)

        failed, named, text = _rpc(server, "search", {**ask, "session_id": SESSION, "session_token": token})
        assert not failed, text
        assert "four hundred" in _texts(named)

        failed, _, text = _rpc(server, "search", {**ask, "session_id": SESSION})
        assert failed and "verified session identity is required" in text

        failed, _, text = _rpc(server, "search", {**ask, "session_id": "another-session", "session_token": token})
        assert failed and "session mismatch" in text

        failed, _, text = _rpc(server, "deep_search", {**ask, "token_budget": 0})
        # Refused by the published schema, whichever validator is installed.
        assert failed and ("minimum" in text or "must be >=" in text)

        failed, lean, text = _rpc(server, "deep_search", {**ask, "lean": True, "token_budget": 50})
        assert not failed, text
        assert "explain" not in lean and lean["used_tokens"] <= 50
    finally:
        server.close()


def test_the_new_arguments_are_declared_in_closed_schemas(tmp_path: Path) -> None:
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json")
    try:
        listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        init = server.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
    finally:
        server.close()
    assert listed is not None and init is not None
    schemas = {tool["name"]: tool["inputSchema"] for tool in listed["result"]["tools"]}

    working = schemas["working_query"]
    assert working["additionalProperties"] is False
    assert working["properties"]["limit"]["minimum"] == 1
    assert {"type": "array", "items": {"type": "string"}} in working["properties"]["kinds"]["anyOf"]
    assert not {"limit", "kinds", "session_identity"} & set(working["required"])
    for name in ("search", "deep_search"):
        schema = schemas[name]
        assert schema["additionalProperties"] is False
        assert {"session_id", "token_budget", "lean"} <= set(schema["properties"])
        assert "session_identity" not in schema["properties"]
        assert schema["properties"]["token_budget"]["minimum"] == 1
        assert "clamped" in schema["properties"]["token_budget"]["description"]
        assert schema["properties"]["lean"]["default"] is False
        assert not {"session_id", "token_budget", "lean"} & set(schema["required"])
    retire = schemas["profile_retire"]
    assert set(retire["required"]) == {"tenant_id", "user_id", "id"}
    assert {"role", "source_trust_tier"} <= set(retire["properties"])
    assert not {"role", "source_trust_tier"} & set(retire["required"])
    assert init["result"]["serverInfo"]["version"] == buildinfo.build_version()


def test_sdk_adapter_serves_a_session_search(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp import types

    tenant, user = "tenant-sdk", "user-sdk"
    server = build_sdk_server(store_path=tmp_path / "sdk-store.json", session_secret=SECRET)
    token = SessionTokenVerifier(SECRET).sign(_identity(tenant, user))

    async def call(name: str, arguments: dict[str, Any]) -> Any:
        handler = server.request_handlers[types.CallToolRequest]
        return (await handler(types.CallToolRequest(params={"name": name, "arguments": arguments}))).root

    async def exercise() -> tuple[Any, Any, Any]:
        captured = await call("capture", {
            "tenant_id": tenant, "user_id": user, "actor": "user", "source_type": "conversation",
            "content": "The kayak is stored in the blue shed.", "session_id": SESSION,
        })
        seeded = await call("working_seed", {
            "session_token": token, "tenant_id": tenant, "session_id": SESSION, "user_id": user,
            "agent_id": AGENT, "task_id": "talk", "branch": "main", "kind": "intermediate_conclusion",
            "content": NOTE, "evidence_ids": [captured.structuredContent["cid"]], "ttl_seconds": 600,
            "created_at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
        })
        found = await call("search", {
            "tenant_id": tenant, "user_id": user, "query": KAYAK,
            "session_id": SESSION, "session_token": token, "lean": True, "token_budget": 200,
        })
        refused = await call("search", {"tenant_id": tenant, "user_id": user, "query": KAYAK, "session_id": SESSION})
        return seeded, found, refused

    try:
        seeded, found, refused = asyncio.run(exercise())
    finally:
        server.mnemosyne_mcp_facade.close()

    assert seeded.isError is False, seeded.content[0].text
    assert found.isError is False, found.content[0].text
    assert "explain" not in found.structuredContent
    assert any("four hundred" in hit["text"] for hit in found.structuredContent["hits"])
    assert refused.isError is True and "verified session identity is required" in refused.content[0].text


# ---------------------------------------------------------------------------
# 5. which build is running
# ---------------------------------------------------------------------------

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _checkout(root: Path) -> Path:
    package = root / "src" / "mnemosyne"
    package.mkdir(parents=True)
    return package


def test_build_commit_from_a_checkouts_loose_ref(tmp_path: Path) -> None:
    package = _checkout(tmp_path)
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text(COMMIT + "\n", encoding="utf-8")

    assert buildinfo._git_commit(package) == COMMIT[:8]


def test_build_commit_from_packed_refs_and_a_detached_head(tmp_path: Path) -> None:
    package = _checkout(tmp_path)
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    (git / "packed-refs").write_text(f"# pack-refs\n{COMMIT} refs/heads/feature\n", encoding="utf-8")
    assert buildinfo._git_commit(package) == COMMIT[:8]

    (git / "HEAD").write_text(COMMIT.upper() + "\n", encoding="utf-8")
    assert buildinfo._git_commit(package) == COMMIT[:8]


def test_build_commit_from_a_linked_worktree(tmp_path: Path) -> None:
    main_git = tmp_path / "main" / ".git"
    worktree_git = main_git / "worktrees" / "lane"
    (main_git / "refs" / "heads").mkdir(parents=True)
    worktree_git.mkdir(parents=True)
    (main_git / "refs" / "heads" / "lane").write_text(COMMIT + "\n", encoding="utf-8")
    (worktree_git / "HEAD").write_text("ref: refs/heads/lane\n", encoding="utf-8")
    (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")
    package = _checkout(tmp_path / "lane")
    (tmp_path / "lane" / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")

    assert buildinfo._git_commit(package) == COMMIT[:8]


def test_an_installed_copy_never_reports_an_enclosing_projects_commit(tmp_path: Path) -> None:
    """A copy in a venv that sits inside another repository is not that repository's build."""

    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text(COMMIT + "\n", encoding="utf-8")
    installed = tmp_path / ".venv" / "Lib" / "site-packages" / "mnemosyne"
    installed.mkdir(parents=True)

    assert buildinfo._git_commit(installed) is None


def test_build_version_prefers_the_environment_and_ignores_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_BUILD_COMMIT", "ABCDEF1234567890")
    buildinfo.build_commit.cache_clear()
    try:
        assert buildinfo.build_commit() == "abcdef12"
        assert buildinfo.build_version() == f"{buildinfo.package_version()}+abcdef12"
    finally:
        buildinfo.build_commit.cache_clear()
    assert buildinfo._clean_commit("not a commit") is None
    assert buildinfo._clean_commit("abc") is None
    assert buildinfo._clean_commit(None) is None


# ---------------------------------------------------------------------------
# 6. profile entries a client can rely on
# ---------------------------------------------------------------------------


def _statements(tools: MemoryTools, tenant: str, user: str) -> list[str]:
    return [entry["statement"] for entry in tools.profile_context(tenant, user)["authoritative"]]


def test_profile_correct_replaces_the_entry_it_corrects() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    old = tools.profile_record_explicit("t", "u", "Prefers temperatures in Celsius.")

    fixed = tools.profile_correct("t", "u", old["id"], "Prefers temperatures in Fahrenheit.")

    assert _statements(tools, "t", "u") == ["Prefers temperatures in Fahrenheit."]
    assert fixed["corrects"] == old["id"] and fixed["superseded"] is True
    corrected = tools.user_model.entries[old["id"]]
    assert corrected.status == "superseded"
    assert corrected.valid_to == tools.user_model.entries[fixed["id"]].valid_from
    with pytest.raises(ValueError, match="profile entry not found"):
        tools.profile_correct("t", "u", "no-such-entry", "ghost")
    assert "ghost" not in _statements(tools, "t", "u")


def test_profile_retire_uses_the_callers_authority_and_the_entrys_sink() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    preference = tools.profile_add(
        "t", "u", "explicit_preference", "Likes the window seat.",
        role="operator", source_trust_tier=0,
    )
    instruction = tools.profile_add(
        "t", "u", "hard_instruction", "Never invent a gate code.",
        role="operator", source_trust_tier=0,
    )

    with pytest.raises(PermissionError, match="profile_retire denied"):
        tools.profile_retire("t", "u", preference["id"], role="reader", source_trust_tier=0)
    assert tools.user_model.entries[preference["id"]].status == "active"

    with pytest.raises(PermissionError, match="policy"):
        tools.profile_retire("t", "u", instruction["id"], role="agent", source_trust_tier=0)
    assert tools.user_model.entries[instruction["id"]].status == "active"

    retired = tools.profile_retire("t", "u", instruction["id"], role="operator", source_trust_tier=0)
    assert retired["retired"] is True and retired["security"]["allowed"] is True
    assert tools.user_model.entries[instruction["id"]].status == "retracted"


def test_a_reader_session_cannot_retire_a_profile_entry(tmp_path: Path) -> None:
    tenant, user = "tenant-retire", "user-retire"
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", session_secret=SECRET)
    try:
        preference = server.tools.profile_add(
            tenant, user, "explicit_preference", "Likes the window seat.",
            role="operator", source_trust_tier=0,
        )
        instruction = server.tools.profile_add(
            tenant, user, "hard_instruction", "Never invent a gate code.",
            role="operator", source_trust_tier=0,
        )
        verifier = SessionTokenVerifier(SECRET)
        reader = SessionIdentity(
            tenant_id=tenant, user_id=user, role="reader", source_trust_tier=0,
            agent_id=AGENT, session_id=SESSION,
        )
        failed, _, text = _rpc(server, "profile_retire", {
            "tenant_id": tenant, "user_id": user, "id": preference["id"],
            "role": "operator", "source_trust_tier": 0, "session_token": verifier.sign(reader),
        })
        assert failed and "denied" in text
        assert server.tools.user_model.entries[preference["id"]].status == "active"

        agent = SessionIdentity(
            tenant_id=tenant, user_id=user, role="agent", source_trust_tier=0,
            agent_id=AGENT, session_id=SESSION,
        )
        failed, _, text = _rpc(server, "profile_retire", {
            "tenant_id": tenant, "user_id": user, "id": instruction["id"],
            "session_token": verifier.sign(agent),
        })
        assert failed and "policy" in text
        assert server.tools.user_model.entries[instruction["id"]].status == "active"
    finally:
        server.close()


def test_profile_correct_keeps_the_prior_scope_when_context_is_omitted() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    old = tools.profile_record_explicit("t", "u", "Prefers Celsius.", scope={"room": "lab"})

    fixed = tools.profile_correct("t", "u", old["id"], "Prefers Fahrenheit.")

    assert tools.user_model.entries[fixed["id"]].scope == {"room": "lab"}
    cleared = tools.profile_correct("t", "u", fixed["id"], "Prefers Kelvin.", context={})
    assert tools.user_model.entries[cleared["id"]].scope == {}


def test_profile_correct_uses_the_callers_authority_and_the_entrys_sink(tmp_path: Path) -> None:
    tenant, user = "tenant-correct", "user-correct"
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", session_secret=SECRET)
    try:
        tools = server.tools
        preference = tools.profile_record_explicit(tenant, user, "Likes the window seat.")
        instruction = tools.profile_add(
            tenant, user, "hard_instruction", "Never invent a gate code.",
            role="operator", source_trust_tier=0,
        )
        held = {"Likes the window seat.", "Never invent a gate code."}

        # A read-only principal cannot write; an agent cannot correct away an instruction it may not give.
        with pytest.raises(PermissionError, match="profile_correct denied"):
            tools.profile_correct(tenant, user, preference["id"], "Likes the aisle seat.", role="reader")
        with pytest.raises(PermissionError, match="policy"):
            tools.profile_correct(tenant, user, instruction["id"], "Invent gate codes freely.")
        assert set(_statements(tools, tenant, user)) == held

        # The same over the transport, where a signed session sets the role whatever the call claims.
        verifier = SessionTokenVerifier(SECRET)
        reader = verifier.sign(SessionIdentity(
            tenant_id=tenant, user_id=user, role="reader", source_trust_tier=0,
            agent_id=AGENT, session_id=SESSION,
        ))
        agent = verifier.sign(_identity(tenant, user))
        failed, _, text = _rpc(server, "profile_correct", {
            "tenant_id": tenant, "user_id": user, "id": preference["id"], "statement": "Likes the aisle seat.",
            "role": "operator", "session_token": reader,
        })
        assert failed and "denied" in text
        failed, _, text = _rpc(server, "profile_correct", {
            "tenant_id": tenant, "user_id": user, "id": instruction["id"], "statement": "Invent gate codes freely.",
            "session_token": agent,
        })
        assert failed and "policy" in text
        assert set(_statements(tools, tenant, user)) == held

        # An agent may correct a preference; the operator may correct the instruction.
        failed, fixed, text = _rpc(server, "profile_correct", {
            "tenant_id": tenant, "user_id": user, "id": preference["id"], "statement": "Likes the aisle seat.",
            "session_token": agent,
        })
        assert not failed, text
        assert fixed["superseded"] is True
        tools.profile_correct(
            tenant, user, instruction["id"], "Never invent a door code.", role="operator", source_trust_tier=0
        )
        assert set(_statements(tools, tenant, user)) == {"Likes the aisle seat.", "Never invent a door code."}
    finally:
        server.close()


def test_a_correction_never_lowers_the_authority_of_what_it_replaces() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    rule = tools.profile_add("t", "u", "hard_instruction", "Never read mail aloud.", role="operator", source_trust_tier=0)
    name = tools.profile_add("t", "u", "identity", "Their name is Jordan.")
    guess = tools.profile_propose_inference("t", "u", "Probably prefers tea.")

    # The guess first: an inference yields to any stated entry that is added beside it.
    fixed_guess = tools.profile_correct("t", "u", guess["id"], "Prefers coffee.")
    fixed_rule = tools.profile_correct(
        "t", "u", rule["id"], "Never read mail aloud after ten.", role="operator", source_trust_tier=0
    )
    fixed_name = tools.profile_correct("t", "u", name["id"], "Their name is Jordon.")

    def kind(made: dict[str, Any]) -> UserMemoryKind:
        return tools.user_model.entries[made["id"]].kind

    # An instruction stays an instruction and an identity an identity ...
    assert kind(fixed_rule) is UserMemoryKind.HARD_INSTRUCTION
    assert kind(fixed_name) is UserMemoryKind.IDENTITY
    # ... and a guess the user corrects becomes what they said outright.
    assert kind(fixed_guess) is UserMemoryKind.EXPLICIT_PREFERENCE
    assert all(fixed["superseded"] is True for fixed in (fixed_guess, fixed_rule, fixed_name))
    assert set(_statements(tools, "t", "u")) == {
        "Never read mail aloud after ten.",
        "Their name is Jordon.",
        "Prefers coffee.",
    }
    assert tools.profile_context("t", "u")["inferred"] == []


def test_profile_retire_takes_an_entry_back() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    kept = tools.profile_record_explicit("t", "u", "Wants to be called Captain.")
    extra = tools.profile_record_explicit("t", "u", "Likes the window seat.")

    retired = tools.profile_retire("t", "u", extra["id"])
    again = tools.profile_retire("t", "u", extra["id"])

    assert retired["retired"] is True and retired["status"] == "retracted"
    assert again["retired"] is False and again["status"] == "retracted"
    assert _statements(tools, "t", "u") == ["Wants to be called Captain."]
    # The record is kept: it was once held.
    assert tools.user_model.entries[extra["id"]].statement == "Likes the window seat."
    for tenant, user, entry_id in (("t", "u", "no-such-entry"), ("other", "u", kept["id"]), ("t", "someone-else", kept["id"])):
        with pytest.raises(ValueError, match="profile entry not found"):
            tools.profile_retire(tenant, user, entry_id)
    assert _statements(tools, "t", "u") == ["Wants to be called Captain."]


def test_forget_retracts_the_profile_entry_built_on_the_erased_line(tmp_path: Path) -> None:
    tools = MemoryTools(LocalMemoryEngine(store_path=tmp_path / "store.json"))
    line = tools.capture("t", "u", "user", "conversation", "From now on, always call me Captain.")
    other = tools.capture("t", "u", "user", "conversation", "I take my coffee black.")
    built = tools.profile_record_explicit("t", "u", "Wants to be called Captain.", source_evidence_cids=[line["cid"]])
    tools.profile_record_explicit("t", "u", "Takes coffee black.", source_evidence_cids=[other["cid"]])

    forgotten = tools.forget("t", line["cid"])

    assert forgotten["erased"] is True
    assert forgotten["propagated"]["profile_entries"] == 1
    assert forgotten["retracted_profile_entries"] == [built["id"]]
    assert _statements(tools, "t", "u") == ["Takes coffee black."]
    entry = tools.user_model.entries[built["id"]]
    # The forgotten words do not live on in the profile.
    assert entry.status == "retracted" and entry.statement == ERASED_STATEMENT
    # A forget that touches no profile entry reports as it always did.
    unrelated = tools.capture("t", "u", "user", "conversation", "The wall is green.")
    assert "profile_entries" not in (tools.forget("t", unrelated["cid"]).get("propagated") or {})


def test_forget_retracts_corrections_that_depend_on_the_erased_evidence(tmp_path: Path) -> None:
    """A correction cites the entry it replaced; erasure must still reach the live one."""

    state_path = tmp_path / "runtime.json"
    tools = MemoryTools(
        LocalMemoryEngine(store_path=tmp_path / "store.json"),
        runtime_state=RuntimeState(state_path),
    )
    line = tools.capture("t", "u", "user", "conversation", "From now on, always call me Captain.")
    built = tools.profile_record_explicit(
        "t", "u", "Wants to be called Captain.", source_evidence_cids=[line["cid"]]
    )
    once = tools.profile_correct("t", "u", built["id"], "Wants to be called Skipper.")
    twice = tools.profile_correct("t", "u", once["id"], "Wants to be called Chief.")

    active = tools.user_model.entries[twice["id"]]
    assert line["cid"] in active.source_evidence_cids
    assert built["id"] not in active.source_evidence_cids

    forgotten = tools.forget("t", line["cid"])

    assert forgotten["erased"] is True
    assert _statements(tools, "t", "u") == []
    for entry_id in (built["id"], once["id"], twice["id"]):
        entry = tools.user_model.entries[entry_id]
        assert entry.status != "active"
        assert entry.statement == ERASED_STATEMENT
    reloaded = MemoryTools(LocalMemoryEngine(), runtime_state=RuntimeState(state_path))
    assert _statements(reloaded, "t", "u") == []
    assert reloaded.user_model.entries[twice["id"]].statement == ERASED_STATEMENT


def test_retract_citing_follows_profile_entry_lineage() -> None:
    model = UserModel()
    original = UserModelEntry(
        tenant_id="t", user_id="u", kind=UserMemoryKind.EXPLICIT_PREFERENCE,
        statement="Call me Captain.", source_evidence_cids=["evidence-1"], status="superseded",
    )
    corrected = UserModelEntry(
        tenant_id="t", user_id="u", kind=UserMemoryKind.EXPLICIT_PREFERENCE,
        statement="Call me Skipper.", source_evidence_cids=[original.id],
    )
    again = UserModelEntry(
        tenant_id="t", user_id="u", kind=UserMemoryKind.EXPLICIT_PREFERENCE,
        statement="Call me Chief.", source_evidence_cids=[corrected.id],
    )
    for entry in (original, corrected, again):
        model.entries[entry.id] = entry

    retracted = model.retract_citing("t", "evidence-1")

    assert set(retracted) == {original.id, corrected.id, again.id}
    assert _no_active_forgotten_text(model)


def test_closed_entry_blanking_is_persisted(tmp_path: Path) -> None:
    state_path = tmp_path / "runtime.json"
    tools = MemoryTools(
        LocalMemoryEngine(store_path=tmp_path / "store.json"),
        runtime_state=RuntimeState(state_path),
    )
    line = tools.capture("t", "u", "user", "conversation", "From now on, always call me Captain.")
    built = tools.profile_record_explicit(
        "t", "u", "Wants to be called Captain.", source_evidence_cids=[line["cid"]]
    )
    tools.profile_retire("t", "u", built["id"])

    forgotten = tools.forget("t", line["cid"])

    assert built["id"] in forgotten["retracted_profile_entries"]
    reloaded = MemoryTools(LocalMemoryEngine(), runtime_state=RuntimeState(state_path))
    assert reloaded.user_model.entries[built["id"]].statement == ERASED_STATEMENT


def test_profile_correct_rejects_an_entry_that_is_not_active() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    old = tools.profile_record_explicit("t", "u", "Prefers temperatures in Celsius.")
    tools.profile_retire("t", "u", old["id"])

    with pytest.raises(ValueError, match="not active"):
        tools.profile_correct("t", "u", old["id"], "Prefers temperatures in Fahrenheit.")

    assert _statements(tools, "t", "u") == []
    assert tools.user_model.entries[old["id"]].statement == "Prefers temperatures in Celsius."


def _no_active_forgotten_text(model: UserModel) -> bool:
    return all(
        entry.status != "active" and entry.statement == ERASED_STATEMENT
        for entry in model.entries.values()
    )


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_a_derived_hit_that_cites_no_evidence_is_still_dated(backend: str, tmp_path: Path) -> None:
    """An assertion or a preference may cite nothing; its own record time dates the hit.

    Dating a derived hit only through the evidence it cites left one with an
    empty provenance list carrying no ``created_at`` at all.
    """

    engine: Any = LocalMemoryEngine() if backend == "local" else SqliteEngine(tmp_path / "sqlite-store")
    tools = MemoryTools(engine)
    tools.assert_fact("t", "owner", "lives_in", "Lisbon", [], user_id="u")
    tools.preference("t", "u", "travel", "Prefers morning flights.", explicit=True)

    result = tools.search("t", "owner lives in Lisbon and prefers morning flights", user_id="u")

    undated_before = [hit for hit in result["hits"] if hit["kind"] in {"assertion", "preference"}]
    assert {hit["kind"] for hit in undated_before} == {"assertion", "preference"}
    for hit in result["hits"]:
        assert datetime.fromisoformat(hit["metadata"]["created_at"]).tzinfo is not None
        assert hit["metadata"]["created_at_source"] == "record"
        assert hit["metadata"]["memory_type"] == hit["kind"]


def test_a_stated_entry_is_not_retired_by_another_statement_that_merely_differs() -> None:
    tools = MemoryTools(LocalMemoryEngine())
    tools.profile_record_explicit("t", "u", "Prefers temperatures in Celsius.")
    guess = tools.profile_propose_inference("t", "u", "Probably likes short answers.")

    tools.profile_add("t", "u", "identity", "Their name is Jordan.")

    assert set(_statements(tools, "t", "u")) == {"Their name is Jordan.", "Prefers temperatures in Celsius."}
    # An inference still yields to a higher-authority statement in its scope.
    assert tools.user_model.entries[guess["id"]].status == "superseded"
