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
