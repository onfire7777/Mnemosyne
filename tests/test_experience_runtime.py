import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.models import Evidence
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.guards import LearningGuardError
from mnemosyne.experience.signals import tool_signals, user_signals
from mnemosyne.experience.stats import Posterior, contingency_lower_bound
from mnemosyne.experience.traces import trace


def engine_with_fact(path=None):
    engine = LocalMemoryEngine(store_path=path)
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
    return engine, cid


def turn(runtime, **kwargs):
    receipt = runtime.prepare_context(
        "t", "u", "s", "Zephyr launch code", task_type="lookup"
    )
    episode = runtime.observe_turn(
        "t",
        "u",
        "s",
        "Zephyr launch code",
        "cobalt",
        receipt_ids=[receipt["receipt_id"]],
        **kwargs,
    )
    return receipt, episode


def test_capture_resolve_and_prediction_are_durable(tmp_path):
    path = tmp_path / "memory.json"
    engine, _ = engine_with_fact(path)
    runtime = LearningRuntime(engine)
    receipt, episode = turn(runtime)
    assert runtime.status("t")["enabled"] is True
    result = runtime.record_signal(
        "t",
        episode_id=episode["episode_id"],
        kind="verifier",
        value=1,
        evidence="independent verifier",
        final=True,
    )
    assert result["status"] == "resolved"
    assert result["reward"] == 1
    assert result["prediction"] == receipt["prediction"]
    engine.close()
    reopened = LocalMemoryEngine(store_path=path)
    restored = LearningRuntime(reopened)
    assert restored.episode("t", episode["episode_id"]) == result
    assert restored.status("other")["episodes"] == 0
    reopened.close()


def test_unknown_and_untrusted_outcomes_do_not_learn():
    engine, _ = engine_with_fact()
    runtime = LearningRuntime(engine)
    _, episode = turn(runtime)
    with pytest.raises(ValueError):
        runtime.record_signal(
            "t", episode_id=episode["episode_id"], kind="assistant", value=1, final=True
        )
    runtime.end_session("t", "s")
    assert runtime.episode("t", episode["episode_id"])["status"] == "unknown"
    assert runtime.status("t")["credit_rows"] == 0


def test_receipt_cannot_cross_tenant_user_session_or_be_reused():
    runtime = LearningRuntime(engine_with_fact()[0])
    receipt, _ = turn(runtime)
    for tenant, user, session in [
        ("other", "u", "s"),
        ("t", "other", "s"),
        ("t", "u", "other"),
    ]:
        with pytest.raises((ValueError, KeyError)):
            runtime.observe_turn(
                tenant, user, session, "q", "a", receipt_ids=[receipt["receipt_id"]]
            )
    with pytest.raises(ValueError):
        runtime.observe_turn(
            "t", "u", "s", "q", "a", receipt_ids=[receipt["receipt_id"]]
        )


def test_resolution_is_idempotent_and_rejects_conflicting_signal():
    runtime = LearningRuntime(engine_with_fact()[0])
    _, episode = turn(runtime)
    first = runtime.record_signal(
        "t", episode_id=episode["episode_id"], kind="verifier", value=1, final=True
    )
    assert (
        runtime.record_signal(
            "t", episode_id=episode["episode_id"], kind="verifier", value=1, final=True
        )
        == first
    )
    with pytest.raises(ValueError):
        runtime.record_signal(
            "t", episode_id=episode["episode_id"], kind="verifier", value=-1, final=True
        )


def test_guard_blocks_learning_authority_and_records_defect():
    runtime = LearningRuntime(engine_with_fact()[0])
    with pytest.raises(LearningGuardError):
        runtime.writer.apply(
            "t", "test", lambda state: state["policy"].update(groundedness=1)
        )
    status = runtime.status("t")
    assert status["frozen"]
    assert len(runtime.defects("t")) == 1
    assert runtime.writer.read("t")["policy"].get("groundedness") is None


def test_reading_never_updates_statistics():
    runtime = LearningRuntime(engine_with_fact()[0])
    for _ in range(10):
        runtime.prepare_context("t", "u", "s", "Zephyr launch code", task_type="lookup")
    assert runtime.status("t")["credit_rows"] == 0
    assert runtime.writer.read("t")["stats"] == {}


def test_signal_weights_and_zero_exit_are_not_success():
    assert tool_signals([{"exit_code": 0}]) == []
    assert tool_signals([{"exit_code": 2}]) == []
    assert tool_signals([{"exit_code": 2, "outcome_scope": "task", "final": True}])[0]["value"] == -1
    assert tool_signals([{"passed": 3, "failed": 1}])[0]["value"] == 0.5
    assert user_signals("thanks")[0]["weight"] == 0.3
    assert user_signals("No, that is wrong.")[0]["value"] == -1


def test_statistics_are_order_invariant_and_contingency_needs_both_arms():
    a, b = Posterior(), Posterior()
    values = [1.0, 0.0, 0.5, 1.0, 0.0]
    for value in values:
        a.update(value)
    for value in reversed(values):
        b.update(value)
    assert a.to_dict() == b.to_dict()
    assert 0 < a.lower_bound < a.mean < 1
    assert contingency_lower_bound(8, 8, 0, 0) is None
    assert contingency_lower_bound(20, 20, 0, 20) > 0
    assert trace(1, 1, 30, 0.7, 30) == pytest.approx(0.7 / 2.718281828459045)


def test_erasure_retracts_receipts_credit_and_derived_artifacts():
    engine, cid = engine_with_fact()
    runtime = LearningRuntime(engine)
    receipt, episode = turn(runtime)
    runtime.record_signal(
        "t", episode_id=episode["episode_id"], kind="verifier", value=1, final=True
    )
    runtime.erase("t", cid)
    assert cid not in str(runtime.writer.read("t"))
    assert runtime.episode("t", episode["episode_id"])["status"] == "erased"


def test_erasure_scrubs_learning_audit_and_prevents_rollback_restoration():
    engine, cid = engine_with_fact()
    runtime = LearningRuntime(engine)
    receipt, episode = turn(runtime)
    runtime.record_signal(
        "t", episode_id=episode["episode_id"], kind="verifier", value=1, final=True
    )
    runtime.erase("t", cid)
    history = runtime.writer.store.history("t")
    assert cid not in str(history)
    assert "cobalt" not in str(history)
    for event in history:
        if event.get("erased"):
            with pytest.raises(ValueError):
                runtime.rollback("t", event["id"])


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_engine_erasure_cascades_learning_in_native_transaction(tmp_path, backend):
    if backend == "sqlite":
        from mnemosyne.sqlite_engine import SqliteEngine

        engine = SqliteEngine(tmp_path / "sqlite")
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
    else:
        engine, cid = engine_with_fact(tmp_path / "local.json")
    runtime = LearningRuntime(engine)
    _, episode = turn(runtime)
    engine.forget("t", cid)
    assert runtime.episode("t", episode["episode_id"])["status"] == "erased"
    assert cid not in str(runtime.writer.read("t"))
    engine.close()


def test_source_erasure_revokes_encrypted_audit_without_rewriting_events():
    import copy

    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    secret = "private Zinnia project statement"
    receipt = runtime.prepare_context("t", "u", "s", secret)
    observed = runtime.observe_turn(
        "t", "u", "s", secret, "response", receipt_ids=[receipt["receipt_id"]]
    )
    events = [row for row in engine.audit_log if row.get("source") == "experience"]
    retained_events = copy.deepcopy(events)
    assert secret not in str(events)
    cid = runtime.episode("t", observed["episode_id"])["source_cids"][0]
    engine.forget("t", cid)
    assert secret not in str(runtime.writer.read("t"))
    assert secret not in str(runtime.writer.store.history("t"))
    assert [row for row in engine.audit_log if row.get("source") == "experience"][
        : len(events)
    ] == retained_events


def test_external_claims_are_checked_by_local_critic_without_self_reward():
    claim = {"category": "math", "expression": "2+3", "expected": 5}
    assert tool_signals([{"source": "tool", "claim": claim}])[0]["value"] == 1
    assert tool_signals([{"source": "assistant", "claim": claim}]) == []


def test_learning_and_audit_continue_after_erasure_key_rotation():
    engine, cid = engine_with_fact()
    runtime = LearningRuntime(engine)
    _, first = turn(runtime)
    runtime.record_signal(
        "t", episode_id=first["episode_id"], kind="verifier", value=1, final=True
    )
    engine.forget("t", cid)
    receipt = runtime.prepare_context("t", "u", "s", "new task", task_type="new")
    second = runtime.observe_turn(
        "t", "u", "s", "new task", "done", receipt_ids=[receipt["receipt_id"]]
    )
    runtime.record_signal(
        "t", episode_id=second["episode_id"], kind="verifier", value=1, final=True
    )
    assert runtime.writer.store.history("t")
