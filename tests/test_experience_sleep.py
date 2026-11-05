from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime


def test_failed_external_verifier_can_create_only_scoped_probation_candidate():
    runtime = LearningRuntime(LocalMemoryEngine())
    receipt = runtime.prepare_context(
        "t", "u", "s", "Deploy inventory", task_type="deploy"
    )
    episode = runtime.observe_turn(
        "t",
        "u",
        "s",
        "Deploy inventory",
        "ran upload",
        receipt_ids=[receipt["receipt_id"]],
        tool_events=[
            {
                "name": "benchmark_verifier",
                "success": False,
                "expected_steps": ["validate", "upload"],
                "output": "validate then upload",
            }
        ],
    )
    runtime.record_signal(
        "t", episode_id=episode["episode_id"], kind="verifier", value=-1, final=True
    )
    result = runtime.consolidate("t")
    artifacts = list(runtime.writer.read("t")["artifacts"].values())
    assert result["replayed"] == 1
    assert len(artifacts) == 1
    assert artifacts[0]["state"] == "probation"
    assert artifacts[0]["steps"] == ["validate", "upload"]
    assert artifacts[0]["task_class"] == "deploy"
    assert runtime.consolidate("t")["replayed"] == 0
    assert (
        runtime.prepare_context("t", "u", "s", "similar deploy", task_type="other")[
            "procedures"
        ]
        == []
    )


def test_self_generated_verifier_cannot_supply_a_candidate():
    runtime = LearningRuntime(LocalMemoryEngine())
    episode = runtime.observe_turn(
        "t",
        "u",
        "s",
        "x",
        "x",
        tool_events=[
            {
                "source": "assistant",
                "name": "benchmark_verifier",
                "success": False,
                "expected_steps": ["invented"],
            }
        ],
    )
    runtime.record_signal(
        "t", episode_id=episode["episode_id"], kind="verifier", value=-1, final=True
    )
    runtime.consolidate("t")
    assert runtime.writer.read("t")["artifacts"] == {}


def test_retirement_rollback_restores_new_candidate_without_reviving_retired_revision():
    runtime = LearningRuntime(LocalMemoryEngine())
    context = runtime.prepare_context('t','u','s','apply procedure',task_type='apply')
    observed = runtime.observe_turn('t','u','s','apply procedure','failed',
        receipt_ids=[context['receipt_id']],tool_events=[{'name':'validator','source':'tool',
            'verdict':False,'expected_steps':['check'],'output':'check'}])
    runtime.record_signal('t',episode_id=observed['episode_id'],kind='verifier',value=-1,final=True)
    runtime.consolidate('t')
    original = next(iter(runtime.writer.read('t')['artifacts']))
    runtime.writer.apply('t','retire',lambda state: state['artifacts'][original].update(state='retired'))
    audit_id = runtime.writer.store.history('t')[-1]['id']
    result = runtime.rollback('t',audit_id)
    state = runtime.writer.read('t')
    assert state['artifacts'][original]['state'] == 'retired'
    assert len(result['restored_candidates']) == 1
    assert state['artifacts'][result['restored_candidates'][0]]['state'] == 'candidate'
