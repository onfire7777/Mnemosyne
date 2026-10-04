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


def test_schema_attempt_preserves_all_completed_prefix_cases_and_quality_failures():
    from eval.public.action_formation_scoring import score_case
    from eval.public.action_formation_timing import score_observations

    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-formation-schema-attempt-2026-10-04'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        raw = (root / name).read_bytes()
        assert expected == {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    rows = [json.loads(line) for line in (root / 'workload/operations.jsonl').read_text().splitlines()]
    report = json.loads((root / 'partial-diagnostics.json').read_text())
    assert manifest['complete_benchmark'] is report['complete_benchmark'] is False
    assert manifest['completed_cases'] == len(report['cases']) == 21
    corpus = make_corpus()['cases']
    assert [r['case_id'] for r in report['cases']] == [c['public']['case_id'] for c in corpus[:21]]
    for case, retained in zip(corpus[:21], report['cases'], strict=True):
        records = [r for r in rows if r['case_id'] == case['public']['case_id']]
        assert retained['state'] == score_case(case, [r for r in records if r['stage'] == 'turn_completed'])
        ticks = [r['response'] for r in records if r['stage'] == 'observation_response' and r['command'] == 'intention.observe']
        assert retained['timing'] == score_observations(case, {'case_id': case['public']['case_id'], 'ticks': ticks})
    assert sum(r['timing']['metrics']['false_negatives'] for r in report['cases']) == 17
    assert sum(r['timing']['metrics']['true_positives'] for r in report['cases']) == 0
    assert not any(r.get('command') in ('task.create', 'task.update') for r in rows)
    outputs = [r for r in rows if r['stage'] == 'formation_response' and r['returncode'] == 0]
    assert len(outputs) == manifest['model_responses'] == 25
    for row in outputs:
        value = json.loads(base64.b64decode(row['stdout_base64']))
        assert value['operations'] == [] and value['clarification']
    status = json.loads((root / 'workload/status.json').read_text())
    assert status['status'] == 'failed' and status['completed_cases'] == 21
    assert rows[-1]['stage'] == 'formation_error'
    assert rows[-1]['case_id'] == corpus[21]['public']['case_id']


def test_wire_diagnostic_keeps_semantic_inputs_fixed_and_does_not_claim_success():
    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-formation-wire-diagnostic-2026-10-04'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        raw = (root / name).read_bytes()
        assert expected == {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    assert manifest['task_execution'] is manifest['ranking_eligible'] is manifest['publishable'] is False
    request = json.loads((root / 'matrix/input.json').read_text())
    case = next(c for c in make_corpus()['cases'] if c['public']['case_id'] == request['conversation']['case_id'])
    assert case['gold']['turns'][0]['active_schedules'][0]['trigger']['type'] == 'event'
    semantic = []
    for index in range(4):
        records = [json.loads(line) for p in (root / f'matrix/{index}').glob('*.jsonl') for line in p.read_text().splitlines()]
        sent = next(r for r in records if r['stage'] == 'chat_request')
        wire = base64.b64decode(sent['request_body_base64'])
        assert hashlib.sha256(wire).hexdigest() == sent['request_body_sha256']
        body = json.loads(wire)
        assert body == sent['body']
        assert json.loads(body['messages'][1]['content']) == request
        properties = body['format']['oneOf'][0]['properties']
        assert next(iter(properties)) == ('clarification' if index % 2 == 0 else 'operations')
        body.pop('model')
        semantic.append(body)
        output = json.loads((root / f'matrix/output-{index}.txt').read_text())
        if index % 2 == 0:
            assert output['operations'] == [] and output['clarification']
        else:
            assert len(output['operations']) == 1 and output['clarification'] is None
            assert output['operations'][0]['payload']['trigger']['type'] == 'exact_time'
    assert all(value == semantic[0] for value in semantic)
