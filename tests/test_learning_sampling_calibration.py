"""Regression tests for outcome-backed calibration and trial scheduling."""

from copy import deepcopy

import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.receipts import digest


def test_calibration_learns_the_raw_input_bucket_after_adjusting_a_prediction():
    runtime = LearningRuntime(LocalMemoryEngine())
    # A stable input score has externally observed failures. Calibration changes
    # the emitted prediction, but all later outcomes still belong to that input.
    for index in range(24):
        context = runtime.prepare_context(
            "t", "u", f"s-{index}", "unseen task", task_type=f"task-{index}"
        )
        receipt = runtime.writer.read("t")["receipts"][context["receipt_id"]]
        if index >= 20:
            assert context["prediction"] < 0.5
        episode = runtime.observe_turn(
            "t",
            "u",
            f"s-{index}",
            "unseen task",
            "done",
            receipt_ids=[context["receipt_id"]],
        )
        runtime.record_signal(
            "t",
            episode_id=episode["episode_id"],
            kind="verifier",
            value=False,
            final=True,
        )
        assert runtime.writer.read("t")["receipts"][context["receipt_id"]][
            "prediction_hash"
        ] == digest(receipt["prediction"])
    state = runtime.writer.read("t")
    for episode in state["episodes"].values():
        receipt = state["receipts"][episode["receipt_ids"][-1]]
        assert receipt["raw_prediction"] == 0.5
    assert state["policy"]["calibration_bins"] == {"5": {"n": 24, "successes": 0.0}}


def test_legacy_calibration_bins_are_not_reused_as_raw_score_observations():
    runtime = LearningRuntime(LocalMemoryEngine())
    runtime.writer.apply(
        "t",
        "legacy_calibration_fixture",
        lambda state: state["policy"].update(
            calibration_bins={"5": {"n": 30, "successes": 0}}
        ),
    )
    before = deepcopy(runtime.writer.read("t"))
    context = runtime.prepare_context("t", "u", "s", "new task", task_type="task")
    assert context["prediction"] == 0.5
    assert (
        runtime.writer.read("t")["policy"]["calibration_bins"]
        == before["policy"]["calibration_bins"]
    )
    episode = runtime.observe_turn(
        "t", "u", "s", "new task", "done", receipt_ids=[context["receipt_id"]]
    )
    runtime.record_signal(
        "t", episode_id=episode["episode_id"], kind="verifier", value=True, final=True
    )
    assert runtime.writer.read("t")["policy"]["calibration_bins"] == {
        "5": {"n": 1, "successes": 1.0}
    }


def _import_probation(runtime, identifier="deployment-skill"):
    from mnemosyne.experience.candidates import register_import
    from mnemosyne.models import Evidence

    content = "Inspect the deployment logs"
    cid = runtime.engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="skill",
            content=content,
            access_policy={"tenant": "t", "allow_principals": ["u"]},
        )
    )
    return register_import(
        runtime,
        "t",
        {
            "id": identifier,
            "revision": 1,
            "task_class": "deploy",
            "content": content,
            "steps": [content],
            "source_cids": [cid],
            "source_origin": {"tenant_id": "t", "user_id": "u", "source_sha": "sha"},
        },
    )


def test_probation_collects_balanced_real_trials_without_promoting_unobserved_outcomes():
    runtime = LearningRuntime(LocalMemoryEngine())
    artifact = _import_probation(runtime)
    served = []
    for index in range(24):
        context = runtime.prepare_context(
            "t", "u", str(index), "deploy", task_type="deploy"
        )
        served.append(any(row["id"] == artifact["id"] for row in context["skills"]))
    assert sum(served) == 12
    assert all(sum(served[start : start + 2]) == 1 for start in range(0, 24, 2))
    state = runtime.writer.read("t")
    assert state["artifacts"][artifact["id"]]["state"] == "probation"
    assert not state["credit"]
    assert all(
        receipt["probation_trial"]["candidate_id"] == artifact["id"]
        for receipt in state["receipts"].values()
    )


def test_probation_trials_keep_high_risk_requests_on_the_nonexperimental_path():
    runtime = LearningRuntime(LocalMemoryEngine())
    _import_probation(runtime)
    for index in range(8):
        context = runtime.prepare_context(
            "t", "u", str(index), "deploy", task_type="deploy", risk_level="high"
        )
        assert not context["skills"]
        receipt = runtime.writer.read("t")["receipts"][context["receipt_id"]]
        assert not receipt.get("probation_trial")
        assert not receipt["exploration"]


@pytest.mark.parametrize(
    "metadata", [{"must_keep": True}, {"lifecycle": {"must_keep": True}}]
)
def test_exploratory_withholding_preserves_must_keep_evidence(metadata):
    from mnemosyne.models import Evidence

    engine = LocalMemoryEngine()
    engine.policy.learning_exploration_rate = 1.0
    runtime = LearningRuntime(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="note",
            content="The emergency station code is sapphire.",
            metadata=metadata,
            access_policy={"tenant": "t", "allow_principals": ["u"]},
        )
    )
    for index in range(4):
        context = runtime.prepare_context(
            "t", "u", str(index), "emergency station code sapphire", task_type="lookup"
        )
        assert cid in {hit["id"] for hit in context["hits"]}


def test_probation_promotes_only_after_real_served_and_control_outcomes():
    from mnemosyne.experience.runtime import stat_key

    runtime = LearningRuntime(LocalMemoryEngine())
    artifact = _import_probation(runtime)
    for index in range(24):
        context = runtime.prepare_context(
            "t", "u", str(index), "deploy", task_type="deploy"
        )
        served = any(row["id"] == artifact["id"] for row in context["skills"])
        observed = runtime.observe_turn(
            "t",
            "u",
            str(index),
            "deploy",
            "done" if served else "unknown",
            receipt_ids=[context["receipt_id"]],
        )
        runtime.record_signal(
            "t",
            episode_id=observed["episode_id"],
            kind="verifier",
            value=served,
            final=True,
        )
    state = runtime.writer.read("t")
    stats = state["stats"][stat_key("skill", artifact["id"], 1, "deploy")]
    assert stats["verified_n"] == stats["served_n"] == 12
    assert stats["control_n"] == 12
    assert state["artifacts"][artifact["id"]]["state"] == "probation"
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"][artifact["id"]]["state"] == "active"
    _import_probation(runtime, "second-deployment-skill")
    for index in range(24, 28):
        context = runtime.prepare_context(
            "t", "u", str(index), "deploy", task_type="deploy"
        )
        receipt = runtime.writer.read("t")["receipts"][context["receipt_id"]]
        assert receipt["probation_trial"] is None


def test_probation_without_external_outcomes_cannot_promote_after_trials():
    runtime = LearningRuntime(LocalMemoryEngine())
    artifact = _import_probation(runtime)
    for index in range(24):
        runtime.prepare_context("t", "u", str(index), "deploy", task_type="deploy")
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"][artifact["id"]]["state"] == "probation"


def test_explicit_full_exploration_configuration_retains_serving_behavior():
    engine = LocalMemoryEngine()
    engine.policy.learning_exploration_rate = 1.0
    runtime = LearningRuntime(engine)
    artifact = _import_probation(runtime)
    for index in range(4):
        context = runtime.prepare_context(
            "t", "u", str(index), "deploy", task_type="deploy"
        )
        assert any(row["id"] == artifact["id"] for row in context["skills"])


@pytest.mark.parametrize("lifecycle", [None, 7, "legacy"])
def test_protected_projection_checks_source_cids_and_handles_missing_sources(
    monkeypatch,
    lifecycle,
):
    from types import SimpleNamespace
    from mnemosyne.models import Evidence, Hit

    engine = LocalMemoryEngine()
    engine.policy.learning_exploration_rate = 1.0
    runtime = LearningRuntime(engine)
    cid = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="note",
            content="Protected fact",
            metadata={"lifecycle": lifecycle},
            access_policy={"tenant": "t", "allow_principals": ["u"]},
        )
    )
    runtime.writer.apply(
        "t",
        "protected_source_fixture",
        lambda state: state["policy"].update(
            protected_cases={"case": {"source_cids": [cid], "user_id": "u"}}
        ),
    )
    original = engine.get_evidence
    probes = []

    def source(tenant, key, branch="main"):
        assert key != "assertion-id"
        probes.append(key)
        return original(tenant, key, branch)

    monkeypatch.setattr(engine, "get_evidence", source)
    monkeypatch.setattr(
        engine,
        "retrieve",
        lambda *args, **kwargs: SimpleNamespace(
            hits=[
                Hit(
                    id="assertion-id",
                    kind="assertion",
                    tenant_id="t",
                    branch="main",
                    text="Protected fact",
                    score=1,
                    channel="graph_ppr",
                    provenance=[cid, "missing-source"],
                )
            ]
        ),
    )
    context = runtime.prepare_context(
        "t", "u", "s", "Protected fact", task_type="lookup"
    )
    assert [hit["id"] for hit in context["hits"]] == ["assertion-id"]
    assert set(probes) == {cid, "missing-source"}


def test_legacy_receipt_can_resolve_without_reclassifying_calibration_inputs():
    from datetime import UTC, datetime
    from mnemosyne.experience.receipts import ContextReceipt

    runtime = LearningRuntime(LocalMemoryEngine())
    receipt = ContextReceipt(
        "old",
        "t",
        "u",
        "s",
        "task",
        0.5,
        "old-policy",
        datetime.now(UTC).isoformat(),
        0,
    ).to_dict()
    runtime.writer.apply(
        "t", "capture", lambda state: state["receipts"].update(old=receipt)
    )
    observed = runtime.observe_turn(
        "t", "u", "s", "query", "response", receipt_ids=["old"]
    )
    runtime.record_signal(
        "t", episode_id=observed["episode_id"], kind="verifier", value=True, final=True
    )
    state = runtime.writer.read("t")
    assert state["receipts"]["old"] == receipt
    assert state["episodes"][observed["episode_id"]]["reward"] == 1
    assert not state["policy"].get("calibration_bins")


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_probation_trial_allocation_survives_backend_reload(tmp_path, backend):
    from mnemosyne.sqlite_engine import SqliteEngine

    factory = LocalMemoryEngine if backend == "local" else SqliteEngine
    path = tmp_path / ("store.json" if backend == "local" else "store")
    engine = factory(path)
    runtime = LearningRuntime(engine)
    artifact = _import_probation(runtime)
    first = runtime.prepare_context("t", "u", "first", "deploy", task_type="deploy")
    first_served = any(row["id"] == artifact["id"] for row in first["skills"])
    if hasattr(engine, "close"):
        engine.close()
    reloaded = factory(path)
    runtime = LearningRuntime(reloaded)
    second = runtime.prepare_context("t", "u", "second", "deploy", task_type="deploy")
    second_served = any(row["id"] == artifact["id"] for row in second["skills"])
    assert first_served != second_served
    assert (
        runtime.writer.read("t")["receipts"][first["receipt_id"]]["raw_prediction"]
        == 0.5
    )
    if hasattr(reloaded, "close"):
        reloaded.close()


@pytest.mark.parametrize("revocation", ["expiry", "quarantine"])
def test_learning_source_liveness_rechecks_transitive_custody(monkeypatch, revocation):
    from datetime import UTC, datetime, timedelta
    from mnemosyne import access_policy
    from mnemosyne.models import Evidence

    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    clock = [datetime.now(UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(access_policy, "datetime", Clock)
    root = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="note",
            content="Source task steps",
            access_policy={
                "tenant": "t",
                "allow_principals": ["u"],
                "expires_at": (clock[0] + timedelta(minutes=1)).isoformat(),
            },
        )
    )
    summary = engine.append_evidence(
        Evidence(
            tenant_id="t",
            user_id="u",
            actor="user",
            source_type="consolidation-summary",
            content="Summary task steps",
            metadata={"summary": {"source_evidence_cids": [root]}},
            access_policy={"tenant": "t", "allow_principals": ["u"]},
        )
    )
    assert runtime._sources_live("t", [summary], "u")
    assert not runtime._sources_live("t", [], "u")
    assert not runtime._sources_live("t", summary, "u")
    if revocation == "expiry":
        clock[0] += timedelta(minutes=2)
    else:
        engine.update_evidence_metadata(
            "t", root, {"quarantine_reason": "source review"}
        )
    assert not runtime._sources_live("t", [summary], "u")


@pytest.mark.parametrize("backend", ["local", "sqlite"])
def test_concurrent_probation_prepares_allocate_distinct_balanced_receipts(
    tmp_path, monkeypatch, backend
):
    from concurrent.futures import ThreadPoolExecutor
    import math
    import threading
    from mnemosyne.sqlite_engine import SqliteEngine

    path = tmp_path / "concurrent-store"
    first = LocalMemoryEngine() if backend == "local" else SqliteEngine(path)
    artifact = _import_probation(LearningRuntime(first))
    episodes_before = LearningRuntime(first).writer.read("t")["episodes"]
    engines = (
        [first] * 4
        if backend == "local"
        else [first, *(SqliteEngine(path) for _ in range(3))]
    )
    runtimes = [LearningRuntime(engine) for engine in engines]
    barrier = threading.Barrier(4)
    for engine in {id(engine): engine for engine in engines}.values():
        original = engine.retrieve

        def overlapping_retrieve(*args, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(engine, "retrieve", overlapping_retrieve)

    def prepare(index):
        return runtimes[index].prepare_context(
            "t", "u", f"parallel-{index}", "deploy", task_type="deploy"
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        contexts = list(executor.map(prepare, range(4)))
    state = runtimes[0].writer.read("t")
    receipts = [state["receipts"][context["receipt_id"]] for context in contexts]
    assert (
        sum(receipt["probation_trial"]["arm"] == "served" for receipt in receipts) == 2
    )
    assert {receipt["probation_trial"]["index"] for receipt in receipts} == {0, 1, 2, 3}
    for context, receipt in zip(contexts, receipts, strict=True):
        selected = context["skills"]
        assert {
            item["item_id"] for item in receipt["items"] if item["kind"] == "skill"
        } == {item["id"] for item in selected}
        assert receipt["prediction"] == context["prediction"]
        expected = selected[0]["confidence"] if selected else 0.5
        assert math.isclose(receipt["raw_prediction"], expected)
        assert (receipt["probation_trial"]["arm"] == "served") == bool(selected)
    assert state["artifacts"][artifact["id"]]["state"] == "probation"
    assert state["episodes"] == episodes_before
    assert not state["credit"]
    for engine in {id(engine): engine for engine in engines}.values():
        if hasattr(engine, "close"):
            engine.close()


def test_probation_rechecks_source_expiry_after_real_retrieval(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from mnemosyne import access_policy

    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    artifact = _import_probation(runtime)
    # Reach a recorded control-first pair so the next allocation would serve.
    for index in range(20):
        context = runtime.prepare_context(
            "t", "u", str(index), "deploy", task_type="deploy"
        )
        trial = runtime.writer.read("t")["receipts"][context["receipt_id"]][
            "probation_trial"
        ]
        if trial["index"] % 2 == 0 and trial["arm"] == "control":
            break
    else:
        pytest.fail("Fixture did not reach a control-first pair")
    clock = [datetime.now(UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)

    monkeypatch.setattr(access_policy, "datetime", Clock)
    cid = artifact["source_cids"][0]
    source = engine.evidence[engine._evidence_key("t", "main", cid)]
    source.access_policy = {
        **source.access_policy,
        "expires_at": (clock[0] + timedelta(minutes=1)).isoformat(),
    }
    original = engine.retrieve

    def expire_during_retrieval(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += timedelta(minutes=2)
        return result

    monkeypatch.setattr(engine, "retrieve", expire_during_retrieval)
    context = runtime.prepare_context("t", "u", "expiry", "deploy", task_type="deploy")
    assert context["skills"] == []
    receipt = runtime.writer.read("t")["receipts"][context["receipt_id"]]
    assert receipt["probation_trial"] is None
    assert all(item["item_id"] != artifact["id"] for item in receipt["items"])
