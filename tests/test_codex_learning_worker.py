from copy import deepcopy
from types import SimpleNamespace

import pytest

from mnemosyne.gate import RegressionCase
from mnemosyne.hosts.codex_learning import advance


def host():
    state = {"episodes": {}, "artifacts": {}, "policy": {}}
    cases = []
    calls = []

    def consolidate(tenant):
        calls.append(tenant)
        return {"replayed": 0}

    runtime = SimpleNamespace(
        writer=SimpleNamespace(read=lambda tenant: deepcopy(state)),
        status=lambda tenant: {"modes": {}, "enabled": True,
                               "frozen": state["policy"].get("frozen", False)},
        consolidate=consolidate,
        _enabled=lambda state, component: not state["policy"].get("dreamer_off"),
    )
    facade = SimpleNamespace(
        runtime_state=SimpleNamespace(load_gate_cases=lambda: list(cases)),
        tools=SimpleNamespace(
            _learning_runtime=lambda: runtime,
            learning=SimpleNamespace(load_native=lambda tenants: None, lessons={}, procedures={}),
            parametric=SimpleNamespace(_eligible_source=lambda *args: False),
        ),
    )
    return facade, runtime, state, cases, calls


def test_protected_cases_and_existing_outcome_changes_reconsider_learning(tmp_path):
    facade, _, state, cases, calls = host()
    path = tmp_path / "worker.json"
    advance(facade, "t", path)
    advance(facade, "t", path)
    assert calls == ["t"]
    cases.append(RegressionCase("one", "one", "query", "answer", protected=True))
    advance(facade, "t", path)
    state["episodes"]["episode"] = {"id": "episode", "status": "resolved", "reward": -1}
    advance(facade, "t", path)
    state["episodes"]["episode"]["reward"] = 1
    advance(facade, "t", path)
    assert calls == ["t"] * 4


def test_captured_failure_wakes_learning_before_task_resolution(tmp_path):
    facade, _, state, _, calls = host()
    path = tmp_path / "worker.json"
    advance(facade, "t", path)
    state["episodes"]["pending"] = {
        "id": "pending", "status": "open", "source_cids": ["source"],
        "tool_events": [{"source": "tool", "experiment_environment": {"kind": "python"}}],
    }
    advance(facade, "t", path)
    advance(facade, "t", path)
    assert calls == ["t", "t"]


def test_unproposed_real_failure_retries_without_a_new_task(tmp_path, monkeypatch):
    from mnemosyne.hosts import codex_learning

    facade, _, state, _, calls = host()
    clock = [1000.0]
    monkeypatch.setattr(codex_learning.time, "time", lambda: clock[0])
    environment = {"version": 1, "kind": "sqlite", "setup": ["CREATE TABLE x(v)"],
                   "baseline": ["INSERT INTO x VALUES(0)"],
                   "checks": [{"query": "SELECT v FROM x", "expected_rows": [[1]]}]}
    state["episodes"]["pending"] = {
        "id": "pending", "status": "open", "source_cids": ["source"], "user_id": "u",
        "tool_events": [{"source": "tool", "verdict": False,
                         "experiment_environment": environment}],
    }
    path = tmp_path / "worker.json"
    assert advance(facade, "t", path)["retry_after"] == 1300
    advance(facade, "t", path)
    assert calls == ["t"]
    clock[0] = 1301
    advance(facade, "t", path)
    assert calls == ["t", "t"]
    state["policy"]["hypotheses"] = {"h": {
        "user_id": "u", "environment_cohort": "cohort", "status": "inconclusive",
        "review_complete": True, "source_cids": ["source"],
        "prediction_candidate_status": "probation",
        "review_contract": {"sandbox_check": {"environment": environment}},
        "environment_result": {"status": "improved"},
    }}
    report = advance(facade, "t", path)
    assert calls == ["t", "t", "t"]
    assert "retry_after" not in report


def test_failure_retry_follows_recorded_backoff_and_then_stops(tmp_path, monkeypatch):
    from mnemosyne.experience.environment_experiments import MAX_MISSES, _miss_key
    from mnemosyne.hosts import codex_learning

    facade, _, state, _, _ = host()
    monkeypatch.setattr(codex_learning.time, "time", lambda: 1000.0)
    environment = {"version": 1, "kind": "sqlite", "setup": ["CREATE TABLE x(v)"],
                   "baseline": ["INSERT INTO x VALUES(0)"],
                   "checks": [{"query": "SELECT v FROM x", "expected_rows": [[1]]}]}
    episode = {"id": "pending", "status": "open", "source_cids": ["source"], "user_id": "u",
               "tool_events": [{"source": "tool", "verdict": False,
                                "experiment_environment": environment}]}
    state["episodes"]["pending"] = episode
    misses = state["policy"]["environment_proposal_misses"] = {
        _miss_key(episode, environment): {"n": 2, "next_attempt": 5000.0}}
    assert advance(facade, "t", tmp_path / "backoff.json")["retry_after"] == 5000.0
    state["policy"]["dreamer_off"] = True
    assert "retry_after" not in advance(facade, "t", tmp_path / "off.json")
    del state["policy"]["dreamer_off"]
    next(iter(misses.values()))["n"] = MAX_MISSES
    assert "retry_after" not in advance(facade, "t", tmp_path / "exhausted.json")


def test_legacy_outcomes_repaired_before_consolidation(tmp_path):
    from mnemosyne.experience.signals import OUTCOME_VERSION

    facade, runtime, state, _, calls = host()
    state["episodes"]["old"] = {
        "id": "old", "status": "resolved", "outcome_version": 2, "reward": 0.8,
    }

    def repair(tenant):
        calls.append("repair")
        state["episodes"]["old"].update(outcome_version=OUTCOME_VERSION, reward=-1)
        return {"reprocessed": 1, "episode_ids": ["old"]}

    runtime.reprocess_outcomes = repair
    report = advance(facade, "t", tmp_path / "worker.json")
    assert calls == ["repair", "t"]
    assert report["outcome_repair"] == {"reprocessed": 1}
    assert report["progress"]["stage"] == "awaiting_memory_use"
    advance(facade, "t", tmp_path / "worker.json")
    assert calls == ["repair", "t"]


def test_progress_distinguishes_captured_used_verified_and_learned():
    from mnemosyne.hosts.codex_learning import learning_progress

    state = {"episodes": {"forgotten": {"status": "erased"},
                          "task": {"status": "resolved"}}, "credit": {}}
    assert learning_progress(state)["captured_episodes"] == 1
    assert learning_progress(state)["stage"] == "awaiting_memory_use"
    state["episodes"]["task"]["cited_cids"] = ["actually-used"]
    assert learning_progress(state)["stage"] == "awaiting_target_verification"
    state["episodes"]["task"]["target_outcomes"] = {"actually-used": {"value": 1}}
    assert learning_progress(state)["stage"] == "collecting_controlled_evidence"
    state["credit"]["observed"] = {"target_id": "actually-used"}
    assert learning_progress(state)["stage"] == "learning_from_verified_use"


def test_checkpoint_tracks_post_consolidation_state_and_retries_failure(tmp_path):
    facade, runtime, state, _, calls = host()
    path = tmp_path / "worker.json"

    def consolidate(tenant):
        calls.append(tenant)
        state["artifacts"]["candidate"] = {"state": "candidate"}
        return {"candidates": 1}

    runtime.consolidate = consolidate
    advance(facade, "t", path)
    original = path.read_bytes()
    advance(facade, "t", path)
    assert calls == ["t"]
    state["policy"]["frozen"] = True

    def fail(tenant):
        raise RuntimeError("temporary store failure")

    runtime.consolidate = fail
    with pytest.raises(RuntimeError, match="temporary store failure"):
        advance(facade, "t", path)
    assert path.read_bytes() == original
    runtime.consolidate = consolidate
    advance(facade, "t", path)
    assert calls == ["t", "t"]


def test_paused_host_does_not_train_an_eligible_artifact(tmp_path):
    facade, _, state, _, _ = host()
    state["policy"]["frozen"] = True
    facade.tools.learning.lessons["one"] = object()
    facade.tools.parametric._eligible_source = lambda *args: True
    facade.tools.parametric.propose_from_lessons = lambda *args: pytest.fail("paused training")
    report = advance(facade, "t", tmp_path / "worker.json")
    assert report["eligible_training_sources"] == 1
    assert report["training"]["status"] == "paused"


def test_trainer_validation_error_can_recover_without_new_outcomes(tmp_path):
    facade, _, _, _, _ = host()
    facade.tools.learning.lessons["one"] = object()
    facade.tools.parametric._eligible_source = lambda *args: True
    attempts = []

    def train(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("temporary provider response failure")
        return SimpleNamespace(status="shadow", id="trained", metrics={})

    facade.tools.parametric.propose_from_lessons = train
    facade.tools.parametric.evaluate_measured = lambda *args: SimpleNamespace(reason="measured evaluator unavailable", promoted=False)
    path = tmp_path / "worker.json"
    assert advance(facade, "t", path)["training"]["status"] == "waiting_for_evidence"
    assert advance(facade, "t", path)["training"]["status"] == "shadow"
    advance(facade, "t", path)
    assert len(attempts) == 2


def test_shadow_evaluation_retries_when_memory_changes_without_new_episode(tmp_path, monkeypatch):
    from mnemosyne.hosts import codex_learning

    facade, _, _, _, _ = host()
    facade.tools.learning.lessons['one'] = object()
    facade.tools.parametric._eligible_source = lambda *args: True
    calls = []
    facade.tools.parametric.propose_from_lessons = lambda *args: (
        calls.append(1) or SimpleNamespace(status='shadow', id='trained', metrics={}))
    facade.tools.parametric.evaluate_measured = lambda *args: SimpleNamespace(reason='protected case missing', promoted=False)
    clock = [1000]
    monkeypatch.setattr(codex_learning.time, 'time', lambda: clock[0])
    path = tmp_path / 'worker.json'
    advance(facade, 't', path)
    advance(facade, 't', path)
    assert len(calls) == 1
    clock[0] += 301
    advance(facade, 't', path)
    assert len(calls) == 2


def test_pending_hypothesis_review_retries_without_new_outcomes(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from mnemosyne.hosts import codex_learning

    facade, _, state, _, calls = host()
    clock = [1000.0]
    monkeypatch.setattr(codex_learning.time, "time", lambda: clock[0])
    state["policy"]["hypotheses"] = {"pending": {
        "status": "inconclusive", "next_review_at": datetime.fromtimestamp(1120, UTC).isoformat()}}
    path = tmp_path / "worker.json"
    assert advance(facade, "t", path)["retry_after"] == 1120
    advance(facade, "t", path)
    assert len(calls) == 1
    clock[0] = 1121
    advance(facade, "t", path)
    assert len(calls) == 2
