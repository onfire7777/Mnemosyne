import base64
import hashlib
import json
from pathlib import Path

import pytest

from eval.public.action_formation import validate_response
from eval.public.action_implicit_plan import make_corpus, public_case


def test_retained_small_model_failure_is_not_a_completed_benchmark():
    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-formation-feasibility-2026-10-04'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        raw = (root / name).read_bytes()
        assert expected == {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    assert manifest['completed_cases'] == manifest['task_writes'] == 0
    assert manifest['benchmark_completed'] is manifest['publishable'] is manifest['rank_eligible'] is False
    assert manifest['resource_admission'] is False
    records = [json.loads(line) for line in (root / 'workload/operations.jsonl').read_text().splitlines()]
    assert len(records) == 7
    requests = [r for r in records if r['stage'] == 'formation_request']
    assert len(requests) == 1
    assert requests[0]['request']['conversation'] == public_case(make_corpus()['cases'][0])
    outputs = [r for r in records if r['stage'] == 'formation_response']
    assert len(outputs) == manifest['model_responses'] == 1
    assert not any(r.get('command') in ('task.create', 'task.update') for r in records)
    raw = base64.b64decode(outputs[0]['stdout_base64'])
    with pytest.raises(ValueError, match='clarification cannot also perform writes'):
        validate_response(raw, allowed_actions={a['action_id'] for a in requests[0]['request']['conversation']['actions']},
                          existing_tasks=set())
    status = json.loads((root / 'workload/status.json').read_text())
    assert status['status'] == 'failed' and status['completed_cases'] == 0
    assert not (root / 'workload/execution.json').exists()
    cleanup = json.loads((root / 'cleanup.json').read_text())
    assert cleanup['after']['models'] == []
    http = [json.loads(line) for p in (root / 'workload/provider-http').glob('*.jsonl')
            for line in p.read_text().splitlines()]
    chat = json.loads(base64.b64decode(next(r for r in http if r['stage'] == 'chat_response')['raw_base64']))
    assert chat['message']['content'].encode() == raw
    assert chat['prompt_eval_count'] == manifest['model_reported_prompt_tokens'] == 726
    assert chat['eval_count'] == manifest['model_reported_output_tokens'] == 140
    assert chat['total_duration'] == manifest['model_reported_total_duration_ns']
    source = json.loads((root / 'workload/source.json').read_text())
    assert source['source_commit'] == manifest['source_commit']
    assert source['source_dirty'] is False
    pressure = [json.loads(line) for line in (root / 'monitor/pressure.jsonl').read_text().splitlines()]
    assert len(pressure) == manifest['normal_pressure_samples'] == 3
    assert all(row['pressure'] == 1 for row in pressure)
