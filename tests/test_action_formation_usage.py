import base64
import json
from pathlib import Path

import pytest

from eval.public.action_formation_usage import summarize

ROOT = Path(__file__).resolve().parents[1] / 'eval/reports/m12-formation-semantic-diagnostic-2026-10-04'


def test_retained_real_provider_usage_includes_all_22_calls():
    paths = sorted(ROOT.glob('*/*.jsonl'))
    paths = [p for p in paths if p.parent.name != 'monitor']
    result = summarize(paths)
    assert result['invocations'] == 22
    for name in ('prompt_eval_count', 'eval_count', 'total_duration'):
        values = []
        for path in paths:
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            response = next(r for r in rows if r['stage'] == 'chat_response')
            values.append(json.loads(base64.b64decode(response['raw_base64']))[name])
        assert result['totals'][name]['complete_total'] == sum(values)
        assert result['totals'][name]['missing_calls'] == 0
    assert result['monetary_cost'] is result['wall_elapsed_seconds'] is None
    assert result['ranking_eligible'] is result['resource_admission_verified'] is False


def write_log(tmp_path, response):
    rows = [{'stage': 'configuration', 'schema': 'm12-ollama-formation-attempt/v1', 'model': 'test'}]
    if response is not None:
        rows.append({'stage': 'chat_response', 'raw_base64': base64.b64encode(json.dumps(response).encode()).decode()})
    rows.append({'stage': 'failed'})
    path = tmp_path / 'log.jsonl'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return path


@pytest.mark.parametrize('response', [None, {'model': 'test'}])
def test_missing_usage_is_unknown_even_for_failed_attempt(tmp_path, response):
    result = summarize([write_log(tmp_path, response)])
    assert result['totals']['eval_count'] == {
        'known_sum': 0, 'known_calls': 0, 'missing_calls': 1, 'complete_total': None}


@pytest.mark.parametrize('value', [True, -1, 1.5, '100'])
def test_invalid_counters_are_not_coerced(tmp_path, value):
    with pytest.raises(ValueError, match='counter'):
        summarize([write_log(tmp_path, {'model': 'test', 'eval_count': value})])


def test_failed_call_with_valid_response_still_counts_consumed_tokens(tmp_path):
    path = write_log(tmp_path, {'model': 'test', 'eval_count': 10})
    result = summarize([path])
    assert result['calls'][0]['terminal_stage'] == 'failed'
    assert result['totals']['eval_count']['complete_total'] == 10
    with pytest.raises(ValueError, match='duplicate'):
        summarize([path, path])
