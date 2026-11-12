"""Exercise the public learning loop across generated operation sequences."""

from copy import deepcopy
from tempfile import TemporaryDirectory

from hypothesis import example, given, settings, strategies as st
import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.guards import validate
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.models import Evidence
from mnemosyne.sqlite_engine import SqliteEngine


@pytest.mark.parametrize("backend", ["local", "sqlite"])
@settings(max_examples=20, deadline=None)
@example(operations=["pause", "failure"])
@example(operations=["success", "erase", "failure", "read", "resume"])
@given(
    st.lists(
        st.sampled_from(["read", "success", "failure", "pause", "resume", "erase"]),
        min_size=1,
        max_size=15,
    )
)
def test_generated_learning_sequences_preserve_guards_and_erasure(backend, operations):
    with TemporaryDirectory() as directory:
        engine = LocalMemoryEngine() if backend == "local" else SqliteEngine(directory)
        runtime = LearningRuntime(engine)
        cid = engine.append_evidence(
            Evidence(
                tenant_id="t",
                user_id="u",
                actor="user",
                source_type="note",
                content="The Zephyr launch code is cobalt.",
                access_policy={"tenant": "t"},
            )
        )
        erased = False
        try:
            for index, operation in enumerate(operations):
                if operation == "pause":
                    runtime.pause("t")
                elif operation == "resume":
                    runtime.resume("t")
                elif operation == "erase":
                    if not erased:
                        engine.forget("t", cid)
                        erased = True
                else:
                    before = runtime.writer.read("t")
                    context = runtime.prepare_context(
                        "t", "u", f"s-{index}", "Zephyr launch code", task_type="lookup"
                    )
                    if operation != "read":
                        observed = runtime.observe_turn(
                            "t",
                            "u",
                            f"s-{index}",
                            "Zephyr launch code",
                            "cobalt",
                            receipt_ids=[context["receipt_id"]],
                        )
                        runtime.record_signal(
                            "t",
                            episode_id=observed["episode_id"],
                            kind="verifier",
                            value=1 if operation == "success" else -1,
                            evidence="Independent test result",
                            final=True,
                        )
                    after = runtime.writer.read("t")
                    if not before["policy"].get("enabled", True) or operation == "read":
                        assert after["stats"] == before["stats"]
                        assert after["credit"] == before["credit"]
                        for field in (
                            "routes",
                            "surprised",
                            "last_good",
                            "breaker",
                            "active_policy_variants",
                        ):
                            assert after["policy"].get(field) == before["policy"].get(
                                field
                            )
                state = runtime.writer.read("t")
                validate(
                    state,
                    deepcopy(state),
                    "monitor",
                    source_lookup=lambda key: engine.get_evidence("t", key),
                )
                assert not state["defects"]
                if erased:
                    assert all(
                        cid not in row.get("source_cids", [])
                        for row in state["episodes"].values()
                    )
                    assert all(
                        item["item_id"] != cid
                        for receipt in state["receipts"].values()
                        for item in receipt["items"]
                    )
        finally:
            engine.close()


def test_forgetting_a_candidate_only_note_keeps_other_learning():
    import dataclasses

    engine = LocalMemoryEngine()
    engine.policy = dataclasses.replace(engine.policy, learning_exploration_rate=0.5)
    runtime = LearningRuntime(engine)

    def note(text):
        return engine.append_evidence(Evidence(
            tenant_id="t", user_id="u", actor="user", source_type="note", content=text,
            trust_tier=1, access_policy={"tenant": "t", "allow_principals": ["u"]}))

    used = note("The deploy command for the billing service is make ship-billing.")
    other = note("My favourite pizza topping is mushrooms.")
    query = "what is the deploy command for the billing service"
    for index in range(60):
        context = runtime.prepare_context("t", "u", f"s{index}", query)
        served = any(hit["id"] == used for hit in context["hits"])
        event = {"name": "checker", "source": "tool", "verdict": "pass" if served else "fail",
                 "output": "checked", "check_id": f"c{index}"}
        if served:
            event.update(receipt_id=context["receipt_id"], target_ids=[used], claims=[{"evidence_cids": [used]}])
        observed = runtime.observe_turn("t", "u", f"s{index}", query, "answer", tool_events=[event],
                                        receipt_ids=[context["receipt_id"]], observation_id=f"o{index}")
        runtime.resolve("t", observed["episode_id"])
        if len(runtime.writer.read("t")["credit"]) >= 2:
            break
    before = runtime.writer.read("t")
    assert len(before["credit"]) == 2 and before["policy"]["routes"]
    receipts = before["receipts"].values()
    assert any(item["item_id"] == other for row in receipts for item in row["eligible_targets"])
    assert not any(item["item_id"] == other for row in receipts for item in row["items"])

    # Used to raise LearningGuardError X3, or to retract every turn that merely listed the note.
    assert engine.forget("t", other)["erased"]

    after = runtime.writer.read("t")
    assert other not in str(after)
    assert after["credit"] == before["credit"]
    assert {row["status"] for row in after["episodes"].values()} == {"resolved"}
    assert after["policy"]["routes"] == before["policy"]["routes"]
