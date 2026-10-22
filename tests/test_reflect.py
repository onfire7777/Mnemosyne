from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.mcp_server import MnemosyneMcpServer, _to_mcp_tool_spec
from mnemosyne.mcp_tools import TOOL_SPEC, MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.providers.extractive_decomposer import ExtractiveQueryDecomposer
from mnemosyne.providers.grounded_reader import CommandGroundedProvider
from mnemosyne.security import SessionIdentity, SessionTokenVerifier


class FixtureProvider:
    def __init__(self, response: Any = None):
        self.response = response
        self.reads: list[dict[str, Any]] = []
        self.disclosure = {
            "query_decomposer": {"model": "test-extractive"},
            "grounded_reader": {"model": "test-reader"},
        }

    def decompose(self, payload):
        return ExtractiveQueryDecomposer().decompose(payload)

    def read(self, payload):
        self.reads.append(copy.deepcopy(payload))
        if isinstance(self.response, Exception):
            raise self.response
        if self.response is not None:
            return self.response
        for row in payload["evidence"]:
            if "Friday" in row["content"]:
                return {"claims": [{"spans": [{"cid": row["cid"], "quote": "Friday"}]}],
                        "unresolved": False}
        return {"claims": [], "unresolved": True}


def seed(engine, content, *, tenant="tenant-a", user="user-a", branch="main", trust=0):
    return engine.append_evidence(Evidence(
        tenant_id=tenant, user_id=user, actor="user", source_type="chat",
        content=content, branch=branch, trust_tier=trust,
        access_policy={"tenant": tenant, "allow_principals": [user]},
    ))


def seeded_engine(path=None):
    engine = LocalMemoryEngine(store_path=path)
    seed(engine, "Ada owns project Zephyr.")
    seed(engine, "Project Zephyr launches Friday.")
    seed(engine, "Ada's SECRET project launches Monday.", tenant="tenant-b")
    seed(engine, "Ada's PRIVATE project launches Tuesday.", user="user-b")
    return engine


def test_reflect_follows_evidence_and_returns_citations_without_writing(tmp_path):
    path = tmp_path / "memory.json"
    engine = seeded_engine(path)
    before = copy.deepcopy(engine.export_all())
    before_bytes = path.read_bytes()
    provider = FixtureProvider()
    tools = MemoryTools(engine, grounded_provider_factory=lambda: provider)

    result = tools.reflect("tenant-a", "When does Ada's project launch?", user_id="user-a")

    assert result["abstained"] is False
    assert result["answer"] == "Friday"
    assert len(result["hops"]) >= 2
    assert any("Zephyr" in query for hop in result["hops"][1:] for query in hop["queries"])
    assert "SECRET" not in str(provider.reads)
    assert "PRIVATE" not in str(provider.reads)
    claim = result["claims"][0]
    assert claim["derivation"]["kind"] == "quotation"
    span = claim["spans"][0]
    source = engine.get_evidence("tenant-a", span["cid"], "main").content
    assert source[span["start"]:span["end"]] == "Friday"
    assert span["slice_sha256"] == hashlib.sha256(b"Friday").hexdigest()
    assert claim["evidence_cids"] == [span["cid"]]
    assert engine.export_all() == before
    assert path.read_bytes() == before_bytes


def test_reflect_preserves_deterministic_synthesis_provenance():
    engine = LocalMemoryEngine()
    cid = seed(engine, "Invoice Zephyr charges are 1.20 and 2.80.")
    provider = FixtureProvider({
        "claims": [{"synthesis": {"operation": "add", "spans": [
            {"cid": cid, "quote": "1.20"}, {"cid": cid, "quote": "2.80"},
        ]}}], "unresolved": False,
    })
    result = MemoryTools(engine, grounded_provider_factory=lambda: provider).reflect(
        "tenant-a", "What are Invoice Zephyr charges?", user_id="user-a",
    )
    assert result["answer"] == "4"
    assert result["claims"][0]["derivation"] == {
        "schema_version": "mnemosyne.claim-derivation/v1",
        "kind": "synthesis", "operation": "add",
    }
    assert len(result["claims"][0]["spans"]) == 2


def test_reflect_uses_sqlite_engine_without_creating_generated_records(tmp_path):
    from mnemosyne.sqlite_engine import SqliteEngine

    engine = SqliteEngine(tmp_path / "sqlite")
    try:
        seed(engine, "Ada owns project Zephyr.")
        seed(engine, "Project Zephyr launches Friday.")
        before = copy.deepcopy(engine.export_all())
        result = MemoryTools(engine, grounded_provider_factory=FixtureProvider).reflect(
            "tenant-a", "When does Ada's project launch?", user_id="user-a",
        )
        assert result["answer"] == "Friday"
        assert engine.export_all() == before
    finally:
        engine.close()


@pytest.mark.parametrize("response", [
    {"claims": [{"spans": [{"cid": "forged", "quote": "Friday"}]}], "unresolved": False},
    {"claims": [{"text": "Invented advice", "evidence_cids": []}], "unresolved": False},
    RuntimeError("private provider diagnostic"),
])
def test_reflect_fails_closed_on_ungrounded_or_failed_reader(response):
    provider = FixtureProvider(response)
    result = MemoryTools(seeded_engine(), grounded_provider_factory=lambda: provider).reflect(
        "tenant-a", "When does Ada's project launch?", user_id="user-a",
    )
    assert result["abstained"] is True
    assert result["answer"] == ""
    assert result["claims"] == []
    assert "private provider diagnostic" not in str(result)


def test_reflect_does_not_call_reader_when_scope_has_no_evidence():
    provider = FixtureProvider()
    result = MemoryTools(seeded_engine(), grounded_provider_factory=lambda: provider).reflect(
        "tenant-absent", "When does Ada's project launch?", user_id="user-a",
    )
    assert result["abstained"] is True
    assert result["hops"] == []
    assert provider.reads == []


def test_default_provider_is_loaded_lazily_and_fresh_for_each_call(monkeypatch):
    created = []

    def factory(cls):
        provider = FixtureProvider()
        created.append(provider)
        return provider

    monkeypatch.setattr(CommandGroundedProvider, "from_environment", classmethod(factory))
    tools = MemoryTools(seeded_engine())
    assert created == []
    for _ in range(2):
        assert tools.reflect("tenant-a", "When does Ada's project launch?", user_id="user-a")["answer"] == "Friday"
    assert len(created) == 2
    assert all(len(provider.reads) == 1 for provider in created)


def test_missing_provider_configuration_is_an_actionable_error(monkeypatch):
    for key in ("MNEMOSYNE_QUERY_DECOMPOSER_COMMAND", "MNEMOSYNE_GROUNDED_READER_COMMAND",
                "MNEMOSYNE_GROUNDED_READER_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="reflect.*provider.*configur"):
        MemoryTools(seeded_engine()).reflect("tenant-a", "Ada", user_id="user-a")


@pytest.mark.parametrize("changes", [
    {"question": " "}, {"question": "x" * 2001}, {"tenant_id": " "},
    {"branch": " "}, {"role": "administrator"}, {"max_trust_tier": 6},
    {"source_trust_tier": True}, {"as_of": "2026-10-22"}, {"break_glass": "yes"},
])
def test_reflect_validates_scope_and_budget_before_loading_provider(changes):
    def forbidden():
        pytest.fail("invalid request must not load a provider")

    arguments = {"tenant_id": "tenant-a", "question": "Ada", **changes}
    with pytest.raises(ValueError):
        MemoryTools(seeded_engine(), grounded_provider_factory=forbidden).reflect(**arguments)


def test_reflect_tool_schema_keeps_configuration_and_limits_server_side():
    schema = _to_mcp_tool_spec(next(item for item in TOOL_SPEC if item["name"] == "reflect"))["inputSchema"]
    assert set(schema["required"]) == {"tenant_id", "question"}
    assert schema["additionalProperties"] is False
    assert {"tenant_id", "user_id", "role", "source_trust_tier"} <= set(schema["properties"])
    assert not {"context", "provider", "command", "model", "max_hops", "session_id", "source_identity"} & set(schema["properties"])


def test_cli_reflect_runs_the_normal_persisted_memory_path(tmp_path, monkeypatch, capsys):
    from mnemosyne import cli

    path = tmp_path / "store.json"
    seeded_engine(path)
    before = path.read_bytes()
    monkeypatch.setattr(CommandGroundedProvider, "from_environment", classmethod(lambda cls: FixtureProvider()))
    assert cli.main(["--store", str(path), "reflect", "--tenant", "tenant-a", "--user", "user-a",
                     "--question", "When does Ada's project launch?"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["answer"] == "Friday"
    assert result["claims"][0]["derivation"]["kind"] == "quotation"
    assert path.read_bytes() == before


def call_reflect(server, arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "reflect", "arguments": arguments}})
    return response["result"]


def test_signed_mcp_reflect_binds_scope_role_and_trust_before_every_hop(tmp_path, monkeypatch):
    secret = "reflect-test-session-key"
    server = MnemosyneMcpServer(store_path=tmp_path / "store.json", session_secret=secret,
                               require_session=True, object_store=str(tmp_path / "objects"))
    try:
        seed(server.engine, "Ada owns project Zephyr.")
        seed(server.engine, "Project Zephyr launches Friday.")
        seed(server.engine, "Ada's SECRET launches Monday.", tenant="tenant-b")
        seed(server.engine, "Ada's PRIVATE launches Tuesday.", user="user-b")
        seed(server.engine, "Ada's UNTRUSTED launches Wednesday.", trust=5)
        provider = FixtureProvider()
        server.tools = MemoryTools(server.engine, grounded_provider_factory=lambda: provider)
        captured = []
        original = server.engine.retrieve

        def retrieve(*args, **kwargs):
            captured.append(copy.deepcopy(kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(server.engine, "retrieve", retrieve)
        token = SessionTokenVerifier(secret).sign(SessionIdentity(
            tenant_id="tenant-a", user_id="user-a", role="reader", source_trust_tier=0,
            session_id="current-session",
        ))
        args = {"session_token": token, "question": "When does Ada's project launch?",
                "role": "operator", "source_trust_tier": 5}
        response = call_reflect(server, args)
        assert response.get("isError", False) is False, response
        assert response["structuredContent"]["answer"] == "Friday"
        assert captured
        for kwargs in captured:
            assert kwargs["tenant_id"] == "tenant-a"
            assert kwargs["filt"]["user_id"] == "user-a"
            assert kwargs["filt"]["role"] == "reader"
            assert kwargs["filt"]["max_trust_tier"] == 0
            assert kwargs["record_access"] is False
        assert all(word not in str(provider.reads) for word in ("SECRET", "PRIVATE", "UNTRUSTED"))
        read_count = len(provider.reads)
        for changes in ({"tenant_id": "tenant-b"}, {"user_id": "user-b"},
                        {"command": "attacker-command"}, {"context": {"role": "operator"}}):
            assert call_reflect(server, {**args, **changes})["isError"] is True
        assert len(provider.reads) == read_count
        assert call_reflect(server, {"question": "Ada"})["isError"] is True
    finally:
        server.close()
