"""Ordinary memory use survives the real host path without manufacturing outcomes."""

import json
from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime, stat_key
from mnemosyne.experience.utility import cited_memory_ids, selection_utility
from mnemosyne.hosts.codex import _bound_verifications, _tool_event, _tool_manifest
from mnemosyne.models import Evidence
from tests.test_codex_lifecycle import LocalHost, write_transcript


def _memory_host(tmp_path):
    host = LocalHost(tmp_path)
    host.engine.policy.learning_modes["exploration"] = "off"
    host.engine.policy.token_budget = 16000
    cid = host.engine.append_evidence(Evidence(
        tenant_id="t", user_id="u", actor="user", source_type="note",
        content="The Zephyr launch code is cobalt.",
        access_policy={"tenant": "t", "allow_principals": ["u"]}))
    output = host.event("UserPromptSubmit", turn_id="turn", prompt="Zephyr launch code")
    context = json.loads(output["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    assert cid in {row["id"] for row in context["hits"]}
    return host, context, cid


@pytest.mark.parametrize("value", ["cobalt", "silver"])
@pytest.mark.parametrize("declaration", [False, True])
def test_item_application_and_independent_outcome_survive_host_and_reload(tmp_path, value, declaration):
    host, context, cid = _memory_host(tmp_path)
    if declaration:
        result = host.event("MemoryUse", receipt_id=context["receipt_id"], used_items=[cid])
        assert result["used_items"] == [cid] and result["verified"] is False
    # A checker compares against its independent reference, not assistant confidence.
    result = {"verdict": value == "cobalt", "check_id": "launch-code",
              "target_ids": [cid], "receipt_id": context["receipt_id"]}
    if not declaration:
        result["claims"] = [{"evidence_cids": [cid]}]
    host.event("PostToolUse", tool_name="launch_code_checker", tool_use_id="check", tool_response={"structuredContent": result})
    host.event("Stop", last_assistant_message=value)
    episode = host.episodes()[-1]
    assert episode["cited_cids"] == [cid]
    assert episode["target_outcomes"][cid]["value"] == (1 if value == "cobalt" else -1)
    state = host.runtime.writer.read("t")
    assert state["stats"][stat_key("item", cid, 1, episode["task_class"])]["applied_n"] == 1
    # One deterministic observation is not enough for causal utility credit.
    assert not state["credit"]
    host.engine.close()
    restored = LocalMemoryEngine(store_path=tmp_path / "memory.json")
    assert LearningRuntime(restored).episode("t", episode["id"]) == episode
    restored.close()


def test_item_use_survives_missed_stop_and_next_prompt(tmp_path):
    host, context, cid = _memory_host(tmp_path)
    host.event("MemoryUse", receipt_id=context["receipt_id"], used_items=[cid])
    checker = {"type": "McpToolCall", "id": "check", "server": "checks", "tool": "launch_code_checker",
               "status": "completed", "result": {"verdict": True, "check_id": "launch-code",
               "receipt_id": context["receipt_id"], "target_ids": [cid]}}
    transcript = write_transcript(tmp_path, [("turn", "Zephyr launch code", [checker], "cobalt")])
    host.event("UserPromptSubmit", turn_id="next", prompt="Another request", transcript_path=str(transcript))
    host.event("Stop", transcript_path=str(transcript))
    assert host.episodes()[0]["cited_cids"] == [cid]
    assert host.episodes()[0]["target_outcomes"][cid]["value"] == 1


@pytest.mark.parametrize("mutation", ["no_use", "wrong_receipt", "self_grade", "printed_claims"])
def test_exposure_unbound_claims_and_self_grades_never_become_applied_memory(tmp_path, mutation):
    host, context, cid = _memory_host(tmp_path)
    result = {"verdict": True, "check_id": "launch-code", "target_ids": [cid],
              "receipt_id": context["receipt_id"], "claims": [{"evidence_cids": [cid]}]}
    if mutation == "no_use":
        result.pop("claims")
    elif mutation == "wrong_receipt":
        result["receipt_id"] = "another-receipt"
    elif mutation == "self_grade":
        result["source"] = "provider_self_grade"
    else:
        result = {"content": [{"type": "text", "text": json.dumps(result)}]}
    host.event("PostToolUse", tool_name="launch_code_checker", tool_use_id="check", tool_response=result)
    host.event("Stop", last_assistant_message="This memory helped me; I verified it.")
    assert host.episodes()[0]["cited_cids"] == []
    assert not host.runtime.writer.read("t")["credit"]


def test_unserved_items_and_declared_grades_are_rejected(tmp_path):
    host, context, cid = _memory_host(tmp_path)
    for extra in ({"used_items": ["unserved"]}, {"receipt_id": "old"},
                  {"verifications": [{"item_id": cid, "verdict": True}]}):
        with pytest.raises(ValueError):
            host.event("MemoryUse", **{"receipt_id": context["receipt_id"], "used_items": [cid], **extra})


def test_explicit_item_verification_reference_must_match_the_checker(tmp_path):
    host, context, cid = _memory_host(tmp_path)
    host.event("MemoryUse", receipt_id=context["receipt_id"], used_items=[cid],
               verifications=[{"item_id": cid, "call_id": "expected", "check_id": "code"}])
    host.event("PostToolUse", tool_name="checker", tool_use_id="another",
               tool_response={"verdict": True, "check_id": "code", "receipt_id": context["receipt_id"], "target_ids": [cid]})
    host.event("Stop", last_assistant_message="cobalt")
    assert host.episodes()[0]["cited_cids"] == [cid]
    assert cid not in host.episodes()[0].get("target_outcomes", {})


def test_typed_claim_parser_keeps_only_valid_references():
    event = _tool_event("checker", {"claims": [{"evidence_cids": ["one", "one"]},
                                                 {"evidence_cids": "one"}, None]})
    assert event["claims"] == [{"evidence_cids": ["one"]}]
    assert "claims" not in _tool_event("functions.exec", {"claims": [{"evidence_cids": ["one"]}]})


def test_derived_item_credit_requires_frozen_live_sources():
    receipt = {"id": "r", "items": [{"kind": "item", "item_id": "assertion"}],
               "item_sources": {"assertion": ["owned-source"]}}
    event = {"source": "tool", "receipt_id": "r", "claims": [{"evidence_cids": ["assertion", "foreign"]}]}
    assert cited_memory_ids([event], [receipt], lambda sources: sources == ["owned-source"]) == ["assertion"]
    assert cited_memory_ids([event], [receipt], lambda sources: False) == []
    assert cited_memory_ids([{**event, "receipt_id": "stale"}], [receipt], lambda sources: True) == []


def test_current_capabilities_refresh_context_before_use_and_are_turn_bound(tmp_path):
    host, context, cid = _memory_host(tmp_path)
    result = host.event("HostCapabilities", receipt_id=context["receipt_id"], turn_id="turn",
                        tools=[{"name": "checker"}, {"type": "function", "function": {"name": "exec"}}])
    assert result["receipt_id"] != context["receipt_id"]
    assert result["available_tools"] == ["checker", "exec"]
    receipt = host.runtime.writer.read("t")["receipts"][result["receipt_id"]]
    assert receipt["available_tools"] == ["checker", "exec"]
    assert result["_mnemosyne_delivery"]["receipt_id"] == result["receipt_id"]
    with pytest.raises(ValueError):
        host.event("HostCapabilities", receipt_id=context["receipt_id"], available_tools=[])
    host.event("MemoryUse", receipt_id=result["receipt_id"], used_items=[cid])
    with pytest.raises(ValueError):
        host.event("HostCapabilities", receipt_id=result["receipt_id"], available_tools=[])
    host.event("UserPromptSubmit", turn_id="next", prompt="Another request")
    state = json.loads(next((tmp_path / "state").glob("session-*.json")).read_text())
    assert state["capabilities_status"] == "unknown" and state["available_tools"] == []


def test_malformed_manifests_do_not_become_current_capabilities():
    assert _tool_manifest({"tools": [{"name": ""}]}) is None
    assert _tool_manifest({"tools": ["exec", {}]}) is None
    assert _tool_manifest({"tools": []}) == []


def test_capability_refresh_retries_after_interrupted_preparation(tmp_path):
    host, context, _ = _memory_host(tmp_path)
    invoke = host.adapter.invoke
    def interrupted(*args, **kwargs):
        raise TimeoutError("provider stopped before returning the new context")
    host.adapter.invoke = interrupted
    request = {"receipt_id": context["receipt_id"], "turn_id": "turn", "available_tools": ["checker"]}
    with pytest.raises(TimeoutError):
        host.event("HostCapabilities", **request)
    host.adapter.invoke = invoke
    result = host.event("HostCapabilities", **request)
    assert result["refreshed"] is True and result["receipt_id"] != context["receipt_id"]
    assert result["available_tools"] == ["checker"]


@pytest.mark.parametrize("effect", [1, -1])
@pytest.mark.parametrize("applied", [True, False])
def test_qualifying_applied_randomized_outcomes_can_change_utility_without_lowering_gates(effect, applied):
    """Exercise the guarded credit mechanism with a complete, labeled trial."""
    runtime = LearningRuntime(LocalMemoryEngine())
    state = runtime.writer.read("t")
    from mnemosyne.experience.guards import _validate_credit, LearningGuardError
    for index in range(36):
        before = {"credit": deepcopy(state["credit"])}
        served = index % 2 == 1
        outcome = effect if served else -effect
        item = {"kind": "item", "item_id": "memory", "revision": 1, "routes": []}
        rid = f"r{index}"
        state["receipts"][rid] = {"id": rid, "created_at": "2026-11-10T00:00:00+00:00", "turn_index": index,
            "items": [item] if served else [], "eligible_targets": [item],
            "selection_exposures": [{**item, "served": served, "propensity": 0.5}]}
        episode = {"id": str(index), "tenant_id": "t", "user_id": "u", "session_id": "s", "task_class": "task",
            "status": "resolved", "reward": outcome, "rpe": outcome,
            "receipt_ids": [rid], "turn_index": index, "resolved_turn_index": index + 1,
            "resolved_at": "2026-11-10T00:00:01+00:00", "outcome_version": 2,
            "target_outcomes": {"memory": {"value": effect, "rpe": effect}} if served else {},
            "cited_cids": ["memory"] if served and applied else [], "signals": [{"kind": "verifier", "value": outcome}]}
        state["episodes"][str(index)] = episode
        runtime._credit(state, episode)
        _validate_credit(before, state, "resolve")
        if index < 15:
            assert not state["credit"]
    if applied:
        assert state["credit"]
        assert (selection_utility(state, "item", "memory", 1, "task", user_id="u") - 1) * effect > 0
        forged = deepcopy(state)
        latest = list(forged["credit"].values())[-1]
        latest["contingency_direction"] = "harmful" if effect > 0 else "beneficial"
        with pytest.raises(LearningGuardError):
            _validate_credit(before, forged, "resolve")
    else:
        assert not state["credit"]
        assert selection_utility(state, "item", "memory", 1, "task", user_id="u") == 1
    assert selection_utility(state, "item", "memory", 1, "task", user_id="other") == 1


@pytest.mark.parametrize("recalled_value", ["cobalt", "silver"])
def test_full_runtime_learns_helpful_and_harmful_item_use_with_unchanged_gates(recalled_value):
    engine = LocalMemoryEngine()
    engine.policy.token_budget = 16000
    engine.policy.learning_exploration_rate = 0.5
    runtime = LearningRuntime(engine)
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="note",
        content=f"The Zephyr launch code is {recalled_value}.", access_policy={"tenant": "t"}))
    for index in range(48):
        session, query = f"trial-{index}", "Zephyr launch code"
        context = runtime.prepare_context("t", "u", session, query)
        served = cid in {item["id"] for item in context["hits"]}
        # The checker has its own reference. The answer follows memory only
        # on the served arm; the control has the opposite result in this fixture.
        answer = recalled_value if served else ("silver" if recalled_value == "cobalt" else "cobalt")
        event = _tool_event("reference_checker", {"verdict": answer == "cobalt", "check_id": "code",
            "target_ids": [cid] if served else [], "receipt_id": context["receipt_id"],
            "claims": [{"evidence_cids": [cid]}] if served else []}, tool_id=f"check-{index}")
        events = _bound_verifications([event], [], context["receipt_id"], [], [], [cid] if served else [])
        observed = runtime.observe_turn("t", "u", session, query, answer,
            receipt_ids=[context["receipt_id"]], tool_events=events)
        runtime.resolve("t", observed["episode_id"])
    state = runtime.writer.read("t")
    records = [row for row in state["credit"].values() if row["target_id"] == cid]
    assert records
    assert all(min(row["served_n"], row["control_n"]) >= 8 for row in records)
    utility = selection_utility(state, "item", cid, 1, context["task_class"], user_id="u")
    assert (utility - 1) * (1 if recalled_value == "cobalt" else -1) > 0
    engine.close()
