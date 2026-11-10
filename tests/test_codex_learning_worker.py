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
