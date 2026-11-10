from copy import deepcopy

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.runtime import LearningRuntime


def test_parser_repair_preserves_sources_receipts_and_completed_observations():
    runtime = LearningRuntime(LocalMemoryEngine())
    receipt = runtime.prepare_context('t', 'u', 's', 'check operation')
    raw = {'name': 'exec_command', 'source': 'tool', 'command': 'uv run pytest -q',
           'output': '3 passed in 122.78s (0:02:02)', 'exit_code': 0, 'call_id': 'real-call'}
    episode = runtime.observe_turn('t', 'u', 's', 'check operation', 'done',
        receipt_ids=[receipt['receipt_id']], tool_events=[raw])
    runtime.end_session('t', 's')
    before = runtime.writer.read('t')
    assert before['episodes'][episode['episode_id']]['status'] == 'unknown'
    sources = deepcopy(runtime.engine.export_tenant('t')['evidence'])
    report = runtime.reprocess_outcomes('t')
    assert report['episode_ids'] == [episode['episode_id']]
    after = runtime.writer.read('t')
    result = after['episodes'][episode['episode_id']]
    assert result['status'] == 'resolved' and result['reward'] == 1
    assert result['tool_events'] == before['episodes'][episode['episode_id']]['tool_events']
    assert after['receipts'] == before['receipts']
    assert runtime.engine.export_tenant('t')['evidence'] == sources
    assert result['target_outcomes'] == {}
    assert runtime.reprocess_outcomes('t')['reprocessed'] == 0
