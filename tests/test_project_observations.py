"""Actual tool knowledge stays grounded, scoped, and separate from user facts."""

from datetime import timedelta
import json

import pytest

from mnemosyne.answering import AnswerReadContext
from mnemosyne.consolidation import ConsolidationJob, _PreparedFact
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker, read_knowledge_context
from mnemosyne.models import Assertion, Evidence, utc_now
from mnemosyne.project_observations import project_grounded_synthesis, project_observed_memory
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.fixture(params=["local", "sqlite"])
def engine(request, tmp_path):
    store = LocalMemoryEngine() if request.param == "local" else SqliteEngine(tmp_path / "store")
    yield store
    store.close()


def capture(engine, content, *, command="cat README.md", user="alice", minute=0, code=0,
            cwd="/work/Atlas", event=None, policy=None, actor="tool"):
    event = event or {"name": "exec_command", "source": "tool", "command": command,
                      "cwd": cwd, "exit_code": code, "status": "completed", "output": content}
    source = Evidence("t", user, actor, "learning_tool_result" if actor == "tool" else "chat", content,
                      trust_tier=3 if actor == "tool" else 5, created_at=utc_now() - timedelta(minutes=10-minute),
                      metadata={"tool_observation": event} if actor == "tool" else {},
                      access_policy=policy or {"allow_principals": [user]})
    return engine.append_evidence(source)


def rows(engine):
    return engine.export_tenant("t")["assertions"]


def context(user="alice"):
    return AnswerReadContext("t", user_id=user, role="agent", source_trust_tier=3)


@pytest.mark.parametrize("path,content,expected", [
    ("package.json", '{"name":"atlas","scripts":{"test":"vitest run"},"api_key":"do-not-retain"}', "vitest run"),
    ("pyproject.toml", '[project]\nname = "atlas"\ndependencies = ["starlette", "uvicorn"]', '["starlette", "uvicorn"]'),
    ("settings.yaml", 'database:\n  engine: postgres\n  password: do-not-retain', "postgres"),
    ("settings.ini", '[database]\nengine = postgres\npassword = do-not-retain', "postgres"),
])
def test_configuration_to_owned_wiki_with_contracts(engine, path, content, expected):
    cid = capture(engine, content, command="cat " + path)
    result = project_observed_memory(engine, "t", cid)
    assert result["created_count"]
    assert all(row["user_id"] == "alice" and row["trust_tier"] == 3 for row in rows(engine))
    assert all(row["calibration"]["epistemic_class"] == "observed_tool" for row in rows(engine))
    assert not any("do-not-retain" in row["object"] for row in rows(engine))
    assert not any(row["predicate"] == "command_exit_code" for row in rows(engine))
    result = KnowledgeMaintenanceWorker(engine, context()).run_once()
    assert result["created"] == 1
    [page] = read_knowledge_context(engine, context(), "Atlas configuration")
    assert expected in page["text"] and "Observed configuration" in page["text"]
    assert all(claim["verification_contract"]["kind"] == "structured_observation" for claim in page["claims"])
    assert read_knowledge_context(engine, context("bob"), "Atlas configuration") == []
    engine.forget("t", cid)
    assert not read_knowledge_context(engine, context(), "Atlas configuration")


def test_checks_keep_actual_failure_and_skip_console_facts(engine):
    cid = capture(engine, "PASSED: Atlas runs Debian.", command=".venv/bin/python -m pytest tests/test_x.py", code=1)
    project_observed_memory(engine, "t", cid)
    [row] = rows(engine)
    assert (row["predicate"], row["object"]) == ("command_exit_code", "1")
    assert row["calibration"]["verification_contract"] == {
        "kind": "command_observation", "argv": [".venv/bin/python", "-m", "pytest", "tests/test_x.py"],
        "cwd": "/work/Atlas", "expected_exit_code": 1, "source_cid": cid}


@pytest.mark.parametrize("command", ["echo 'Atlas runs Debian.'", "printf 'Atlas runs Debian.'",
    'python -c "print(\'Atlas runs Debian.\')"', "git status", "ls", "pytest; echo passed",
    "pytest $(echo tests)", "pytest && echo passed", "bash -lc 'pytest'"])
def test_synthetic_console_or_operational_output_does_not_become_knowledge(engine, command):
    cid = capture(engine, "Atlas runs Debian.", command=command)
    assert project_observed_memory(engine, "t", cid, proposer=lambda _: pytest.fail("operational provider call"))["created_count"] == 0
    assert rows(engine) == []


def test_external_typed_fact_cannot_be_spoofed_by_printed_json(engine):
    observation = {"subject": "Atlas", "predicate": "runs", "object": "Debian"}
    content = json.dumps({"observations": [observation]})
    event = {"name": "deployment_inventory", "source": "tool", "observations": [observation], "output": content}
    cid = capture(engine, content, event=event)
    assert project_observed_memory(engine, "t", cid)["created_count"] == 1
    cid = capture(engine, content, event={**event, "name": "python", "command": "python -c print(...)"})
    assert project_observed_memory(engine, "t", cid)["created_count"] == 0


def test_current_observations_refresh_then_correct_without_reviving_old_values(engine):
    first = capture(engine, '{"engine":"sqlite"}', command="cat settings.json")
    project_observed_memory(engine, "t", first)
    repeat = capture(engine, '{"engine":"sqlite"}', command="cat settings.json", minute=1)
    project_observed_memory(engine, "t", repeat)
    active = [row for row in rows(engine) if row["status"] == "active"]
    assert len(active) == 1 and active[0]["source_evidence_cids"] == [repeat]
    new = capture(engine, '{"engine":"postgres"}', command="cat settings.json", minute=2)
    project_observed_memory(engine, "t", new)
    project_observed_memory(engine, "t", first)
    active = [row for row in rows(engine) if row["status"] == "active"]
    assert len(active) == 1 and active[0]["object"] == "postgres"
    KnowledgeMaintenanceWorker(engine, context()).run_once()
    [page] = read_knowledge_context(engine, context(), "Atlas database engine")
    assert "postgres" in page["text"] and "sqlite" not in page["text"]


def test_complete_configuration_retracts_removed_keys_and_closes_relations(engine):
    first = capture(engine, '{"engine":"sqlite","obsolete_feature":true}', command="cat settings.json")
    project_observed_memory(engine, "t", first)
    newer = capture(engine, '{"engine":"postgres"}', command="cat settings.json", minute=1)
    report = project_observed_memory(engine, "t", newer)
    old = next(row for row in rows(engine) if row["predicate"] == "configuration.obsolete_feature")
    assert old["status"] == "superseded" and old["valid_to"]
    assert old["id"] in report["withdrawn_assertion_ids"]
    relations = engine.export_tenant("t")["relations"]
    assert all(row["valid_to"] for row in relations if row["predicate"] == "configuration.obsolete_feature")
    project_observed_memory(engine, "t", first)
    assert [row["object"] for row in rows(engine) if row["status"] == "active"] == ["postgres"]


def test_empty_new_snapshot_prevents_late_old_source_resurrection(engine):
    first = capture(engine, '{"obsolete_feature":true}', command="cat settings.json")
    empty = capture(engine, '{}', command="cat settings.json", minute=1)
    project_observed_memory(engine, "t", empty)
    assert project_observed_memory(engine, "t", first)["created_count"] == 0
    assert not any(row["status"] == "active" for row in rows(engine))


@pytest.mark.parametrize("partial", ["head", "flag", "bounded_read", "malformed", "host_marker", "two_files"])
def test_partial_configuration_cannot_remove_unseen_keys(engine, partial):
    first = capture(engine, '{"engine":"sqlite","obsolete_feature":true}', command="cat settings.json")
    project_observed_memory(engine, "t", first)
    event = {"name": "exec_command", "source": "tool", "command": "cat settings.json",
             "cwd": "/work/Atlas", "exit_code": 0, "output": '{"engine":"postgres"}'}
    if partial == "head":
        event["command"] = "head settings.json"
    elif partial == "flag":
        event["output_truncated"] = True
    elif partial == "bounded_read":
        event = {"name": "read_file", "path": "settings.json", "cwd": "/work/Atlas",
                 "arguments": {"limit": 10}, "output": '{"engine":"postgres"}'}
    elif partial == "malformed":
        event["output"] = '{"engine":"postgres"'
    elif partial == "host_marker":
        event.update(command="cat settings.yaml", output="engine: postgres\n…120 tokens truncated…\nmode: fast")
    else:
        event["command"] = "cat settings.json other.json"
    newer = capture(engine, event["output"], event=event, minute=1)
    project_observed_memory(engine, "t", newer)
    assert next(row for row in rows(engine) if row["predicate"] == "configuration.obsolete_feature")["status"] == "active"


def test_shortened_capture_is_marked_and_cannot_remove_unseen_keys(engine):
    from mnemosyne.hosts.codex import _tool_event
    first = capture(engine, "engine: sqlite\nobsolete_feature: true", command="cat settings.yaml")
    project_observed_memory(engine, "t", first)
    lines = [f"key_{i}: {i}" for i in range(4000)]
    event = _tool_event("exec_command", {"exit_code": 0, "output": "\n".join(lines)},
                        command="cat settings.yaml", cwd="/work/Atlas", tool_id="long")
    assert event["output_truncated"] is True and len(event["output"]) == 32000
    project_observed_memory(engine, "t", capture(engine, event["output"], event=event, minute=1))
    assert next(row for row in rows(engine) if row["predicate"] == "configuration.obsolete_feature")["status"] == "active"
    short = _tool_event("exec_command", {"exit_code": 0, "output": "engine: sqlite"},
                        command="cat settings.yaml", cwd="/work/Atlas", tool_id="short")
    assert "output_truncated" not in short


def test_reread_of_the_same_file_checks_an_applied_configuration_memory(engine):
    from mnemosyne.hosts.codex import _tool_event
    from mnemosyne.hosts.memory_checks import _check
    project_observed_memory(engine, "t", capture(engine, '{"engine":"sqlite"}', command="cat settings.json"))
    [row] = [row for row in rows(engine) if row["status"] == "active"]
    contract = row["calibration"]["verification_contract"]
    assert contract["file"] == "/work/Atlas/settings.json"
    KnowledgeMaintenanceWorker(engine, context()).run_once()
    [page] = read_knowledge_context(engine, context(), "Atlas configuration")
    assert "sqlite" in page["text"] and "snapshot" not in page["text"]  # the watermark stays internal
    def reread(output, command="cat settings.json", cwd="/work/Atlas"):
        return _check(contract, _tool_event("exec_command", {"exit_code": 0, "output": output},
                                            command=command, cwd=cwd, tool_id="reread"))
    assert reread('{"engine":"sqlite"}') is True
    assert reread('{"engine":"postgres"}') is False
    assert reread('{"mode":"fast"}') is False  # a complete read proves the key is gone
    assert reread('{"mode":"fast"}', command="head settings.json") is None
    assert reread('{"engine":"sqlite"}', command="cat other.json") is None
    assert reread('{"engine":"sqlite"}', cwd="/work/Other") is None


def test_configuration_reconciliation_respects_owner_and_file_scope(engine):
    for user, cwd in (("alice", "/work/Atlas"), ("bob", "/work/Atlas"), ("alice", "/other/Atlas")):
        cid = capture(engine, json.dumps({"feature": True, "owner": user + cwd}),
                      command="cat settings.json", user=user, cwd=cwd)
        project_observed_memory(engine, "t", cid)
    new = capture(engine, '{}', command="cat settings.json", minute=1)
    project_observed_memory(engine, "t", new)
    active = [row for row in rows(engine) if row["status"] == "active"]
    assert {(row["user_id"], row["scope"]["workspace"]) for row in active} == {
        ("bob", "/work/Atlas"), ("alice", "/other/Atlas")}


def test_large_configuration_projects_every_supported_leaf(engine):
    content = json.dumps({f"feature_{i}": i for i in range(160)})
    cid = capture(engine, content, command="cat settings.json")
    assert project_observed_memory(engine, "t", cid)["created_count"] == 160
    assert len([row for row in rows(engine) if row["status"] == "active"]) == 160
    assert project_observed_memory(engine, "t", cid)["created_count"] == 0


def test_rich_source_coverage_reaches_beyond_first_provider_window(engine):
    text = "\n\n".join(f"Component{i}:\n  storage: SQLite\n  rationale: " + "durable ".strip() * 70 for i in range(40))
    cid = capture(engine, text)
    windows = []
    def inspect(payload):
        windows.extend(payload["clauses"])
        return {"claims": [], "coverage_complete": True}
    cursor = None
    for _ in range(10):
        result = project_observed_memory(engine, "t", cid, proposer=inspect, reviewer=review, provider_cursor=cursor)
        cursor = result.get("provider_cursor")
        if not result.get("provider_pending"):
            break
    assert result["coverage_complete"]
    assert windows[-1]["end"] == len(text)
    assert len(windows) == 40
    assert len({(span["start"], span["end"]) for span in windows}) == 40


def test_saturated_provider_window_requests_remaining_distinct_claims(engine):
    text = "Worker:\n  storage: SQLite\n  rationale: transactional durable records"
    cid = capture(engine, text)
    def saturated(payload):
        assert not payload["coverage"]["already_proposed"]
        return {"claims": [proposal(payload)["claims"][0]] * 4}
    first = project_observed_memory(engine, "t", cid, proposer=saturated, reviewer=review)
    assert first["provider_pending"] and first["provider_cursor"]["offset"] == 0
    def finish(payload):
        assert payload["coverage"]["already_proposed"][0]["object"] == "SQLite"
        return {"claims": [], "coverage_complete": True}
    last = project_observed_memory(engine, "t", cid, proposer=finish, reviewer=review,
                                   provider_cursor=first["provider_cursor"])
    assert not last["provider_pending"] and last["coverage_complete"]


def test_workspace_scope_and_source_expiry(engine):
    a = capture(engine, '{"engine":"sqlite"}', command="cat settings.json")
    b = capture(engine, '{"engine":"postgres"}', command="cat settings.json", cwd="/other/Atlas")
    old = capture(engine, "Atlas runs Debian.", policy={"expires_at": "2020-01-01T00:00:00+00:00"})
    for cid in (a, b, old):
        project_observed_memory(engine, "t", cid)
    assert len([row for row in rows(engine) if row["status"] == "active"]) == 2
    assert {row["scope"]["workspace"] for row in rows(engine)} == {"/work/Atlas", "/other/Atlas"}


def test_assistant_can_select_but_not_supply_factual_authority(engine):
    source = capture(engine, "Atlas runs Debian. Atlas uses Postgres.")
    assistant = capture(engine, "Atlas runs Debian. Atlas uses Redis.", actor="assistant")
    result = project_grounded_synthesis(engine, "t", assistant, [source])
    assert len(result["accepted"]) == 1 and len(result["rejected"]) == 1
    assert all(row["source_evidence_cids"] == [source] for row in rows(engine))
    assert not any(row["object"] == "Redis" for row in rows(engine))
    assert not project_grounded_synthesis(engine, "t", assistant, [])["accepted"]


def proposal(payload):
    return {"claims": [{"span": payload["clauses"][0], "subject": "Worker", "predicate": "depends_on", "object": "SQLite",
                        "subject_quote": "Worker", "predicate_quote": "storage", "object_quote": "SQLite", "epistemic_class": "observed_tool"}]}


def review(payload):
    return {"entailed": True, "preserves_negation": True, "preserves_time": True, "preserves_attribution": True,
            "no_added_detail": True, "support_spans": payload["source_spans"]}


def test_rich_observed_knowledge_requires_separate_entailment_review(engine):
    text = "Worker:\n  storage: SQLite\n  rationale: transactional durable records"
    cid = capture(engine, text)
    rejected = project_observed_memory(engine, "t", cid, proposer=proposal)
    assert rejected["created_count"] == 0 and rejected["rejected"]
    result = project_observed_memory(engine, "t", cid, proposer=proposal, reviewer=review)
    assert result["created_count"] == 1
    [row] = rows(engine)
    assert row["calibration"]["entailment_review"]["method"] == "independent_entailment_review"
    # One grounded architecture claim is useful when another complementary fact exists.
    extra = capture(engine, "Worker runs Linux.", minute=1)
    project_observed_memory(engine, "t", extra)
    KnowledgeMaintenanceWorker(engine, context()).run_once()
    [page] = read_knowledge_context(engine, context(), "Worker storage")
    assert "Worker depends on SQLite" in page["text"]
    assert all(claim["epistemic_class"] == "observed_tool" for claim in page["claims"])


def test_provider_cannot_rewrite_an_anchor_or_inject_uncited_source(engine):
    cid = capture(engine, "Worker:\n  storage: SQLite\n  rationale: transactional durable records")
    def fabricated(payload):
        result = proposal(payload)
        result["claims"][0]["object"] = "Postgres"
        return result
    result = project_observed_memory(engine, "t", cid, proposer=fabricated, reviewer=review)
    assert result["created_count"] == 0 and result["rejected"]


def test_provider_can_enrich_after_deterministic_phase(engine):
    cid = capture(engine, "Worker runs Linux.\n\nWorker:\n  storage: SQLite\n  rationale: transactional durable records")
    assert project_observed_memory(engine, "t", cid)["created_count"] == 1
    def propose(payload):
        payload = {**payload, "clauses": [payload["clauses"][1]]}
        return proposal(payload)
    result = project_observed_memory(engine, "t", cid, proposer=propose, reviewer=review)
    assert result["created_count"] == 1
    assert {row["object"] for row in rows(engine)} == {"Linux", "SQLite"}


def test_consolidation_preserves_owner_and_span_metadata(engine):
    cid = capture(engine, "Atlas runs Debian.")
    job = ConsolidationJob("t", "signature", "Atlas operating system", "Atlas", "runs", "Debian", [cid], trust_tier=3)
    _PreparedFact(job, None, {"allow_principals": ["alice"]}).apply(engine, "main")
    [row] = rows(engine)
    assert row["user_id"] == "alice"
    assert row["calibration"]["epistemic_class"] == "consolidated_evidence"
    assert row["calibration"]["source_spans"][0]["quote"] == "Atlas runs Debian."
    assert row["calibration"]["verification_contract"]["object"] == "Debian"
    assert row["scope"]["workspace"] == "/work/Atlas"


def test_consolidation_revises_an_existing_tenant_level_fact(engine):
    # An owned fact would sit beside the unowned one instead of revising it.
    engine.upsert_assertion(Assertion(
        tenant_id="t", subject="Atlas", predicate="runs", object="Fedora", status="active",
        trust_tier=3, valid_from=utc_now() - timedelta(days=1), access_policy={"tenant": "t"},
    ))
    cid = capture(engine, "Atlas runs Debian.")
    job = ConsolidationJob("t", "signature", "Atlas operating system", "Atlas", "runs", "Debian", [cid], trust_tier=3)
    _PreparedFact(job, None, {"allow_principals": ["alice"]}).apply(engine, "main")
    state = {row["object"]: row for row in rows(engine)}
    assert state["Fedora"]["status"] == "superseded"
    assert state["Debian"]["status"] == "active"
    assert state["Debian"]["user_id"] is None


def test_unentailed_consolidation_is_not_advertised_as_observed_knowledge(engine):
    cid = capture(engine, "Atlas runs Debian.")
    job = ConsolidationJob("t", "signature", "Atlas operating system", "Atlas", "runs", "Fedora", [cid], trust_tier=3)
    _PreparedFact(job, None, {"allow_principals": ["alice"]}).apply(engine, "main")
    assert rows(engine)[0]["calibration"]["epistemic_class"] == "inferred_proposal"
    assert KnowledgeMaintenanceWorker(engine, context()).run_once()["created"] == 0


def test_rich_assistant_nomination_uses_actual_multiline_source(engine):
    cid = capture(engine, "Worker:\n  storage: SQLite\n  rationale: transactional durable records")
    assistant = capture(engine, "The Worker architecture relies on SQLite for durable records.", actor="assistant")
    result = project_grounded_synthesis(engine, "t", assistant, [cid], proposer=proposal, reviewer=review)
    assert len(result["accepted"]) == 1
    [row] = rows(engine)
    assert row["source_evidence_cids"] == [cid]
    assert row["calibration"]["epistemic_class"] == "observed_tool"
    engine.forget("t", cid)
    assert not project_grounded_synthesis(engine, "t", assistant, [cid], proposer=proposal, reviewer=review)["accepted"]


def test_provider_never_receives_secret_assignment_lines(engine):
    cid = capture(engine, 'Worker:\n  storage: SQLite\n  rationale: durable state\nAPI_KEY="do-not-disclose"')
    def inspect(payload):
        assert "do-not-disclose" not in json.dumps(payload)
        return {"claims": []}
    project_observed_memory(engine, "t", cid, proposer=inspect)


def test_restricted_assistant_nomination_never_reaches_provider(engine):
    cid = capture(engine, "Worker:\n  storage: SQLite\n  rationale: durable state")
    assistant = capture(engine, "Private design analysis", actor="assistant", policy={"restricted": True})
    result = project_grounded_synthesis(engine, "t", assistant, [cid],
        proposer=lambda _: pytest.fail("restricted nomination disclosed"), reviewer=review)
    assert result["accepted"] == [] and rows(engine) == []


def test_live_capture_projects_tool_memory_and_freezes_wiki_contracts(engine):
    from mnemosyne.experience.runtime import LearningRuntime
    from mnemosyne.mcp_tools import MemoryTools

    runtime = LearningRuntime(engine)
    output = '{"database":"postgres","framework":"starlette"}'
    result = runtime.observe_turn("t", "alice", "session", "Inspect the project configuration.",
        "Atlas uses Redis.", tool_events=[{"name": "exec_command", "source": "tool", "call_id": "read",
            "check_id": "read-config", "command": "cat settings.json", "cwd": "/work/Atlas", "exit_code": 0,
            "status": "completed", "output": output}])
    assert any(row.get("created_count", 0) for row in result["memory_formation"])
    actual = [row for row in rows(engine) if row.get("calibration", {}).get("projection_kind") == "project_observation"]
    assert len(actual) == 2 and all(row["object"] != "Redis" for row in actual)
    user_context = AnswerReadContext("t", user_id="alice", role="agent", source_trust_tier=1)
    assert KnowledgeMaintenanceWorker(engine, user_context).run_once()["created"] == 1
    prepared = MemoryTools(engine).prepare_context("t", "alice", "next-session", "Atlas project database framework configuration")
    [page] = prepared["knowledge_pages"]
    receipt = runtime.writer.read("t")["receipts"][prepared["receipt_id"]]
    contracts = receipt["item_verification_contracts"][page["page_id"]]
    assert {contract["object"] for contract in contracts} == {"postgres", "starlette"}
    engine.forget("t", actual[0]["source_evidence_cids"][0])
    assert read_knowledge_context(engine, user_context, "Atlas configuration") == []


def test_operational_sources_skip_projection_scans(engine, monkeypatch):
    cid = capture(engine, "working tree clean", command="git status")
    monkeypatch.setattr(engine, "export_tenant", lambda *a, **kw: pytest.fail("whole archive export"))
    monkeypatch.setattr(engine, "knowledge_source_batch", lambda *a, **kw: pytest.fail("irrelevant projection scan"))
    result = project_observed_memory(engine, "t", cid, proposer=lambda _: pytest.fail("irrelevant model call"))
    assert result["created_count"] == 0


def test_project_projection_never_exports_raw_archive(engine, monkeypatch):
    cid = capture(engine, '{"database":"postgres"}', command="cat config.json")
    monkeypatch.setattr(engine, "export_tenant", lambda *a, **kw: pytest.fail("whole archive export"))
    assert project_observed_memory(engine, "t", cid)["created_count"] == 1


def test_synthesis_reuses_same_turn_projection_without_reparsing_or_provider(engine, monkeypatch):
    import mnemosyne.project_observations as module
    cid = capture(engine, "Atlas runs Debian.")
    project_observed_memory(engine, "t", cid)
    assistant = capture(engine, "Atlas runs Debian.", actor="assistant")
    monkeypatch.setattr(module, "extract_observed_claims", lambda *a, **kw: pytest.fail("repeated extraction"))
    result = project_grounded_synthesis(engine, "t", assistant, [cid], projected_sources=[cid],
        proposer=lambda _: pytest.fail("repeated provider work"), reviewer=review)
    assert len(result["accepted"]) == 1 and result["created_count"] == 0


def test_file_uri_workspace_keeps_legacy_check_observation_usable(engine):
    cid = capture(engine, "compiled", command="python -m compileall src", cwd="file:///work/Atlas%20App")
    project_observed_memory(engine, "t", cid)
    [row] = rows(engine)
    assert row["scope"]["workspace"] == "/work/Atlas App"
    assert row["calibration"]["verification_contract"]["cwd"] == "/work/Atlas App"
