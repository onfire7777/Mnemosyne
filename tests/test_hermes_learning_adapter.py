import json

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.hosts.hermes import HermesAdapter


def test_host_forwards_actual_tool_events_to_the_engine():
    runtime = LearningRuntime(LocalMemoryEngine())
    adapter = HermesAdapter(runtime, tenant_id="t", user_id="u")
    adapter.initialize("s")
    assert (
        json.loads(adapter.prefetch("compute value"))["instruction_authority"] == "none"
    )
    observed = adapter.sync_turn(
        "compute value",
        "done",
        messages=[
            {"role": "user", "content": "compute value"},
            {"role": "tool", "name": "pytest", "content": '{"passed":2,"failed":0}'},
        ],
    )
    adapter.on_session_end([])
    assert runtime.episode("t", observed["episode_id"])["reward"] == 1
    adapter.shutdown()


def test_profile_scopes_are_separate_and_missing_scope_rejected(tmp_path):
    import pytest

    adapter = HermesAdapter()
    with pytest.raises(ValueError):
        adapter.initialize("s")
    adapter.initialize("s", hermes_home=tmp_path / "profile-a", user_id="a")
    other = HermesAdapter()
    other.initialize("s", hermes_home=tmp_path / "profile-b", user_id="b")
    assert adapter.tenant_id != other.tenant_id
    adapter.shutdown()
    other.shutdown()
