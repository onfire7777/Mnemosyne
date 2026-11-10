"""Cited wiki claims must survive composition and actual-use attribution."""

import json

from mnemosyne.answering import AnswerReadContext
from mnemosyne.context_composer import compose_context, token_bound
from mnemosyne.experience.runtime import stat_key
from mnemosyne.knowledge_maintenance import KnowledgeMaintenanceWorker, read_knowledge_context
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Assertion, Evidence
from tests.test_codex_lifecycle import LocalHost


def seed(engine, count=12):
    for n in range(count):
        text = f"Atlas component {n} uses the configured durable storage system for its application records."
        cid = engine.append_evidence(Evidence("t", "u", "user", "chat", text, trust_tier=1))
        engine.upsert_assertion(Assertion("t", "Atlas", f"component_{n}", "durable storage",
            user_id="u", status="active", source_evidence_cids=[cid], trust_tier=1,
            calibration={"projection_kind": "direct_user", "epistemic_class": "direct_user",
                "source_spans": [{"cid": cid, "start": 0, "end": len(text), "quote": text}]}))
    context = AnswerReadContext("t", user_id="u", role="agent", source_trust_tier=1)
    assert KnowledgeMaintenanceWorker(engine, context).run_once()["created"] == 1
    return context


def test_large_wiki_fits_final_envelope_by_complete_claims(tmp_path):
    host = LocalHost(tmp_path)
    context = seed(host.engine)
    [original] = read_knowledge_context(host.engine, context, "What storage does Atlas use?")
    envelope = {"memory_use_reporting": {"command": ["python", "hook.py", "--report-use"],
        "session_id": "session", "turn_id": "turn"}}
    result = compose_context("What storage does Atlas use?", {"knowledge_pages": [original],
        "receipt_id": "r", "task_class": "task", "prediction": .5, "mode": "deliberate"}, 4096, envelope=envelope)
    [delivered] = result["packet"]["knowledge_pages"]
    assert token_bound(result["text"]) <= 4096
    assert delivered["omitted_claims"] > 0
    assert delivered["version"] == original["version"]
    for claim in original["claims"]:
        admitted = bool(set(claim["source_evidence_cids"]) & set(delivered["source_evidence_cids"]))
        for span in claim["spans"]:
            assert (span["quote"] in delivered["text"]) == admitted
            if admitted:
                assert f"[source:{span['cid']}:{span['start']}-{span['end']}]" in delivered["text"]


def _host(tmp_path):
    host = LocalHost(tmp_path)
    seed(host.engine, count=2)
    host.engine.policy.learning_modes["exploration"] = "off"
    tools = MemoryTools(host.engine)
    invoke = host.adapter.invoke
    def dispatch(facade, name, arguments, session_id):
        if name == "prepare_context":
            return tools.prepare_context("t", "u", **arguments)
        return invoke(facade, name, arguments, session_id)
    host.adapter.invoke = dispatch
    output = host.event("UserPromptSubmit", turn_id="turn", prompt="What storage does Atlas use?")
    packet = json.loads(output["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
    return host, packet


def test_native_prepare_and_memory_use_attribute_served_wiki_version(tmp_path):
    host, packet = _host(tmp_path)
    [page] = packet["knowledge_pages"]
    identifier = page["page_id"]
    receipt = host.runtime.writer.read("t")["receipts"][packet["receipt_id"]]
    served = next(row for row in receipt["items"] if row["item_id"] == identifier)
    assert served["kind"] == "item" and served["revision"] == page["version"]
    assert receipt["item_sources"][identifier] == page["source_evidence_cids"]
    host.event("MemoryUse", receipt_id=packet["receipt_id"], used_items=[identifier])
    host.event("PostToolUse", tool_name="storage_checker", tool_use_id="check",
        tool_response={"verdict": True, "check_id": "storage", "target_ids": [identifier],
                       "receipt_id": packet["receipt_id"]})
    host.event("Stop", last_assistant_message="Atlas uses durable storage.")
    episode = host.episodes()[-1]
    assert identifier in episode["cited_cids"]
    assert episode["target_outcomes"][identifier]["value"] == 1
    state = host.runtime.writer.read("t")
    assert state["stats"][stat_key("item", identifier, page["version"], episode["task_class"])]["applied_n"] == 1
    assert not state["credit"]  # One use is not a randomized effectiveness result.


def test_erased_wiki_source_invalidates_prepared_item_and_its_attribution(tmp_path):
    host, packet = _host(tmp_path)
    [page] = packet["knowledge_pages"]
    identifier = page["page_id"]
    host.engine.forget("t", page["source_evidence_cids"][0])
    receipt = host.runtime.writer.read("t")["receipts"][packet["receipt_id"]]
    assert identifier not in receipt["item_sources"]
    assert not any(row["item_id"] == identifier for row in receipt["items"])
    assert not any(row["item_id"] == identifier for row in receipt["eligible_targets"])
