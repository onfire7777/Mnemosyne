from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest

from mnemosyne.consolidation import ConsolidationWorker
from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience import integration
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.frameworks import AutoMemorySession
from mnemosyne.gate import RegressionCase
from mnemosyne.hosts.hermes import HermesAdapter
from mnemosyne.jobs import RuntimeJobHandlers
from mnemosyne.learning import LearningSystem
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.models import Evidence
from mnemosyne.queue import InProcessQueue


@pytest.mark.parametrize("host", ["sdk", "mcp", "hermes"])
def test_hosts_resolve_verified_turn_before_session_end(host, monkeypatch):
    engine = LocalMemoryEngine()
    calls = []
    monkeypatch.setattr(LearningRuntime, "consolidate", lambda self, tenant: calls.append(tenant) or {})
    if host == "sdk":
        session = AutoMemorySession(engine, "t", "u", session_id="s")
        result = session.post_turn_capture("check", "done", tool_events=[{"verdict": False}])["learning_episode"]
        runtime = session.learning_runtime
    elif host == "mcp":
        tools = MemoryTools(engine)
        result = tools.observe_turn("t", "u", "s", "check", "done", tool_events=[{"verdict": False}])
        runtime = tools._learning_runtime()
    else:
        runtime = LearningRuntime(engine)
        adapter = HermesAdapter(runtime, tenant_id="t", user_id="u")
        adapter.initialize("s")
        result = adapter.sync_turn("check", "done", messages=[{"role": "tool", "content": {"verdict": False}}])
    episode = runtime.episode("t", result["episode_id"])
    assert episode["status"] == "resolved"
    assert episode["reward"] == -1
    assert calls == ["t"]


def test_all_runtime_factories_share_dependencies_and_protected_case_filter():
    engine = LocalMemoryEngine()
    lesson_provider, procedure_provider = object(), object()
    valid = RegressionCase("keep", "s", "q", "a", protected=True)
    cases = [valid, RegressionCase("unprotected", "s", "q", "a"),
             RegressionCase("shadow", "s", "q", "a", protected=True, mode="shadow")]
    library = SimpleNamespace()
    _tools = MemoryTools(engine, skill_store=library, lesson_distiller=lesson_provider,
                         procedure_inducer=procedure_provider, protected_cases=cases)
    session = AutoMemorySession(engine, "t", "u")
    worker = RuntimeJobHandlers(engine, InProcessQueue()).consolidator
    for runtime in (session.learning_runtime, worker._learning_runtime(), integration.build_learning_runtime(engine)):
        assert runtime.skill_store is library
        assert runtime.lesson_distiller is lesson_provider
        assert runtime.procedure_inducer is procedure_provider
        assert runtime.protected_cases == [valid]


def test_automatic_consolidation_retries_failures_but_not_completed_signals(monkeypatch):
    tools = MemoryTools(LocalMemoryEngine())
    episode = tools.observe_turn("t", "u", "s", "check", "done")["episode_id"]
    calls = []

    def consolidate(self, tenant):
        calls.append(tenant)
        if len(calls) == 1:
            raise RuntimeError("temporary provider failure")
        return {}

    monkeypatch.setattr(LearningRuntime, "consolidate", consolidate)
    signal = dict(episode_id=episode, final=True, evidence="external failure")
    with pytest.raises(RuntimeError, match="temporary"):
        tools.record_signal("t", "u", "s", "verifier", -1, **signal)
    tools.record_signal("t", "u", "s", "verifier", -1, **signal)
    runtime = tools._learning_runtime()
    revision = runtime.writer.read("t")["policy"]["revision"]
    audits = runtime.writer.store.history("t")
    tools.record_signal("t", "u", "s", "verifier", -1, **signal)
    assert calls == ["t", "t"]
    assert runtime.writer.read("t")["policy"]["revision"] == revision
    assert runtime.writer.store.history("t") == audits


def test_concurrent_completed_signals_claim_one_automatic_pass(monkeypatch):
    tools = MemoryTools(LocalMemoryEngine())
    episode = tools.observe_turn("t", "u", "s", "check", "done")["episode_id"]
    started, release = Event(), Event()
    calls = []

    def consolidate(self, tenant):
        calls.append(tenant)
        started.set()
        assert release.wait(5)
        return {}

    monkeypatch.setattr(LearningRuntime, "consolidate", consolidate)
    def complete():
        return tools.record_signal("t", "u", "s", "verifier", -1, episode_id=episode, final=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(complete)
        try:
            assert started.wait(5)
            assert pool.submit(complete).result(timeout=5)["status"] == "resolved"
        finally:
            release.set()
        assert first.result(timeout=5)["status"] == "resolved"
    assert calls == ["t"]


def test_expired_automatic_claim_is_retryable_without_waiting(monkeypatch):
    runtime = LearningRuntime(LocalMemoryEngine())
    episode = runtime.observe_turn("t", "u", "s", "check", "done")["episode_id"]
    runtime.record_signal("t", episode_id=episode, value=-1, final=True)
    clock = integration.now()
    runtime.writer.apply("t", "seed_claim", lambda state: state["policy"].update(
        host_consolidation={"u": {"pending": {"token": "crashed", "triggers": ["failure:" + episode],
                                              "expires_at": (clock + timedelta(minutes=10)).isoformat()}}}))
    calls = []
    monkeypatch.setattr(runtime, "consolidate", lambda tenant: calls.append(tenant) or {})
    monkeypatch.setattr(integration, "now", lambda: clock)
    assert integration._after_outcomes(runtime, "t", "u") is None
    monkeypatch.setattr(integration, "now", lambda: clock + timedelta(minutes=11))
    assert integration._after_outcomes(runtime, "t", "u") == {}
    assert calls == ["t"]


def test_success_cadence_is_scoped_to_user_and_external_outcomes(monkeypatch):
    runtime = LearningRuntime(LocalMemoryEngine())
    calls = []
    monkeypatch.setattr(runtime, "consolidate", lambda tenant: calls.append(tenant) or {})
    for user, count in (("a", 9), ("b", 1)):
        for index in range(count):
            integration.observe_completed_turn(runtime, "t", user, user, f"check {index}", "done", tool_events=[{"verdict": True}])
    assert not calls
    integration.observe_completed_turn(runtime, "t", "a", "a", "self grade", "success", tool_events=[{"source": "assistant", "verdict": True}])
    assert not calls
    integration.observe_completed_turn(runtime, "t", "a", "a", "check final", "done", tool_events=[{"verdict": True}])
    assert calls == ["t"]


def test_session_end_runs_one_maintenance_pass_without_new_outcomes(monkeypatch):
    runtime = LearningRuntime(LocalMemoryEngine())
    calls = []
    monkeypatch.setattr(runtime, "consolidate", lambda tenant: calls.append(tenant) or {"maintenance": True})
    assert integration.end_learning_session(runtime, "t", "u", "s")["consolidation"] == {"maintenance": True}
    assert calls == ["t"]


def test_sdk_close_runs_learning_consolidation_once(monkeypatch):
    session = AutoMemorySession(LocalMemoryEngine(), "t", "u")
    calls = []
    monkeypatch.setattr(session.learning_runtime, "consolidate", lambda tenant: calls.append(tenant) or {})
    assert session.close()["consolidated"] is True
    assert session.close() == {"closed": True}
    assert calls == ["t"]


def test_native_episode_sources_have_one_induction_owner():
    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    observed = runtime.observe_turn("t", "u", "s", "check", "done")
    cid = runtime.episode("t", observed["episode_id"])["source_cids"][0]
    worker = ConsolidationWorker(engine, [], learning=LearningSystem(engine))
    native = {"source_evidence_cids": [cid]}
    legacy = {"source_evidence_cids": ["old-source"]}
    assert worker._legacy_learning_candidates("t", [native, legacy]) == [legacy]
    assert worker._legacy_learning_candidates("other", [native, legacy]) == [native, legacy]
    assert worker._legacy_learning_candidates("t", [native, legacy], branch="canary") == [native, legacy]


def test_background_and_explicit_reflection_use_same_runtime_configuration(monkeypatch):
    engine = LocalMemoryEngine()
    lesson, procedure = object(), object()
    case = RegressionCase("guard", "s", "q", "a", protected=True)
    MemoryTools(engine, lesson_distiller=lesson, procedure_inducer=procedure, protected_cases=[case])
    handlers = RuntimeJobHandlers(engine, InProcessQueue())
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="test", content="read the source"))
    calls = []

    def consolidate(runtime, tenant):
        calls.append((runtime.lesson_distiller, runtime.procedure_inducer, runtime.protected_cases))
        return {"replayed": 0}

    monkeypatch.setattr(LearningRuntime, "consolidate", consolidate)
    handlers.run_learning_consolidation({"tenant_id": "t"})
    handlers.consolidator.run_queue_payload({"tenant_id": "t", "source_evidence_cids": [cid], "passes": ["learning_reflect"]})
    assert calls == [(lesson, procedure, [case]), (lesson, procedure, [case])]


def test_managed_skill_tools_use_canonical_lifecycle_without_duplicate_trajectory(tmp_path):
    from mnemosyne.skills import SkillStore

    engine = LocalMemoryEngine()
    cid = engine.append_evidence(Evidence(tenant_id="t", user_id="u", actor="user", source_type="import", content="Read the release checklist."))
    path = tmp_path / "release.md"
    path.write_text("---\nname: release-guide\n---\nRead the release checklist.")
    store = SkillStore(str(tmp_path / "skills.sqlite"))
    imported = store.import_skill(str(path), "", memory={"tenant": "t", "user": "u", "cids": [cid]})
    tools = MemoryTools(engine, skill_store=store)
    tools.prepare_context("t", "u", "s", "release-guide")
    runtime = tools._learning_runtime()
    assert runtime.writer.read("t")["artifacts"]
    episodes = runtime.writer.read("t")["episodes"]
    outcome = tools.skill_outcome("t", "u", imported["skill_id"], 1, True, "external check")
    assert outcome["recorded"] is False
    assert runtime.writer.read("t")["episodes"] == episodes
    with pytest.raises(PermissionError):
        tools.skill_set_state(imported["skill_id"], "retired", role="agent", source_trust_tier=0)
    result = tools.skill_set_state(imported["skill_id"], "retired", role="operator", source_trust_tier=0)
    assert result["state"] == "retired"
    assert all(item["state"] == "retired" for item in runtime.writer.read("t")["artifacts"].values())


def _learning_checkpoint(tmp_path):
    from mnemosyne.runtime_state import RuntimeState

    engine = LocalMemoryEngine()
    runtime = LearningRuntime(engine)
    observed = runtime.observe_turn("t", "u", "s", "check saved source", "checked", tool_events=[{"verdict": True}])
    runtime.resolve("t", observed["episode_id"])
    learning = LearningSystem(engine)
    learning.load_native(["t"])
    side = RuntimeState(tmp_path / "runtime.json")
    side.save_learning(learning)
    return side.path, observed["episode_id"]


def test_checkpoint_reload_shares_one_engine_across_all_memory_tools(tmp_path):
    from mnemosyne.runtime_state import RuntimeState

    path, episode_id = _learning_checkpoint(tmp_path)
    abandoned = LocalMemoryEngine()
    tools = MemoryTools(abandoned, runtime_state=RuntimeState(path))
    owner = tools.learning.engine
    assert owner is not abandoned
    assert tools.engine is tools.ingestion.engine is tools.prefetcher.engine is owner
    assert tools._learning_runtime().episode("t", episode_id)["status"] == "resolved"
    receipt = tools.prepare_context("t", "u", "next", "check next source")
    next_episode = tools.observe_turn("t", "u", "next", "check next source", "done", receipt_ids=[receipt["receipt_id"]])
    assert len(LearningRuntime(owner).writer.read("t")["episodes"]) == 2
    assert not LearningRuntime(abandoned).writer.read("t")["episodes"]
    assert LearningRuntime(owner).episode("t", next_episode["episode_id"])["source_cids"]


@pytest.mark.parametrize("component", ["ingestion", "prefetcher"])
def test_checkpoint_reload_rejects_mismatched_custom_dependency_without_mutating_it(tmp_path, component):
    from mnemosyne.ingestion import IngestionPipeline
    from mnemosyne.prefetch import AnticipatoryPrefetcher
    from mnemosyne.runtime_state import RuntimeState

    path, _ = _learning_checkpoint(tmp_path)
    abandoned = LocalMemoryEngine()
    dependency = IngestionPipeline(abandoned) if component == "ingestion" else AnticipatoryPrefetcher(abandoned)
    with pytest.raises(ValueError, match=f"{component} must use the restored learning engine"):
        MemoryTools(abandoned, runtime_state=RuntimeState(path), **{component: dependency})
    assert dependency.engine is abandoned


def test_sdk_adopts_existing_tools_restored_owner(tmp_path):
    import weakref
    from mnemosyne.runtime_state import RuntimeState

    path, episode_id = _learning_checkpoint(tmp_path)
    abandoned = LocalMemoryEngine()
    tools = MemoryTools(abandoned, runtime_state=RuntimeState(path))
    abandoned._learning_tools = weakref.ref(tools)
    session = AutoMemorySession(abandoned, "t", "u", session_id="new-session")
    assert session.engine is session.learning_runtime.engine is tools.engine
    assert session.learning_runtime.episode("t", episode_id)["status"] == "resolved"
    captured = session.post_turn_capture("next request", "next response")
    assert tools.engine.get_evidence("t", captured["user_cid"]) is not None
    assert not abandoned.evidence
