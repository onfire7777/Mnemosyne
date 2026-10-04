"""Comparison populations must match declared methods, not just metric labels."""
import copy
from hashlib import sha256
import json

import pytest

from leaderboard.grouping import CONTEXT_VERSION, build_comparison_index
from leaderboard.validate import DIGEST_PAYLOAD_NAMES
from tests.test_leaderboard_result_contract import _v2_development_record, _v2_official_record


def _input(system='one'):
    record = _v2_development_record()
    record['record_id'] = system
    record['system'] = system
    record['identity']['system_id'] = system
    context = {'schema_version': CONTEXT_VERSION, **{key: 'sha256:' + 'c' * 64 for key in (
        'dataset_digest', 'protocol_digest', 'preprocessing_digest', 'scorer_digest', 'model_policy_digest')}}
    payloads = {name: b'{}' for name in DIGEST_PAYLOAD_NAMES.values()}
    payloads['config.json'] = json.dumps({'comparison_context': context}).encode()
    _bind(record, payloads)
    return record, payloads


def _bind(record, payloads):
    for field, name in DIGEST_PAYLOAD_NAMES.items():
        record[field] = 'sha256:' + sha256(payloads[name]).hexdigest()


def test_grouping_is_order_independent_and_never_a_ranking():
    a, ap = _input('a')
    b, bp = _input('b')
    artifacts = {'a': ap, 'b': bp}
    result = build_comparison_index([a, b], artifacts)
    assert result == build_comparison_index([b, a], artifacts)
    assert len(result['groups']) == 1
    assert result['groups'][0]['multi_system'] is True
    assert result['ranking'] is None
    assert result['publication_authorized'] is False
    assert result['exclusions'] == []


@pytest.mark.parametrize('field', ['dataset_split_digest', 'resource_profile', 'model_policy_id'])
def test_different_atomic_conditions_split_groups(field):
    a, ap = _input('a')
    b, bp = _input('b')
    b['identity'][field] = 'sha256:' + 'd' * 64 if field.endswith('digest') else 'different'
    if field == 'resource_profile':
        b['run_profile']['profile_id'] = 'different'
    result = build_comparison_index([a, b], {'a': ap, 'b': bp})
    assert len(result['groups']) == 2
    assert result['exclusions'] == []


@pytest.mark.parametrize('field', ['dataset_digest', 'protocol_digest', 'preprocessing_digest',
                                    'scorer_digest', 'model_policy_digest'])
def test_same_named_metric_with_different_methods_splits_groups(field):
    a, ap = _input('a')
    b, bp = _input('b')
    config = json.loads(bp['config.json'])
    config['comparison_context'][field] = 'sha256:' + 'd' * 64
    bp['config.json'] = json.dumps(config).encode()
    _bind(b, bp)
    result = build_comparison_index([a, b], {'a': ap, 'b': bp})
    assert len(result['groups']) == 2


@pytest.mark.parametrize(('change', 'reason'), [
    ('missing', 'comparison-context-unavailable'),
    ('tampered', 'unverified-artifacts'),
    ('unknown', 'invalid-comparison-context'),
    ('duplicate_json', 'invalid-config'),
    ('safety', 'safety-gates-not-passed'),
    ('not_measured', 'attempt-not-measured'),
])
def test_unavailable_or_bad_evidence_remains_visible(change, reason):
    record, payloads = _input()
    if change == 'missing':
        payloads['config.json'] = b'{}'
    elif change == 'tampered':
        payloads['traces.jsonl'] = b'tampered'
    elif change == 'unknown':
        payloads['config.json'] = b'{"comparison_context":{"schema_version":"future"}}'
    elif change == 'duplicate_json':
        payloads['config.json'] = b'{"comparison_context":null,"comparison_context":{}}'
    elif change == 'safety':
        record['safety_gates'][0]['status'] = 'failed'
    elif change == 'not_measured':
        record['attempt_outcome'] = 'not-measured'
    if change != 'tampered':
        _bind(record, payloads)
    result = build_comparison_index([record], {'one': payloads})
    assert result['groups'] == []
    assert result['exclusions'] == [{'record_id': 'one', 'reason': reason}]


def test_duplicate_attempt_cannot_count_twice_under_new_record_id():
    a, ap = _input()
    b = copy.deepcopy(a)
    b['record_id'] = 'copy'
    result = build_comparison_index([a, b], {'one': ap, 'copy': ap})
    assert result['groups'] == []
    assert len(result['exclusions']) == 2
    assert {row['reason'] for row in result['exclusions']} == {'ambiguous-duplicate-attempt'}


def test_hardware_and_backend_differences_disclosed_for_quality():
    a, ap = _input('a')
    b, bp = _input('b')
    b['identity'].update(hardware_fingerprint='sha256:' + 'd' * 64, backend_id='remote')
    result = build_comparison_index([a, b], {'a': ap, 'b': bp})
    assert len(result['groups']) == 1
    rows = result['groups'][0]['rows']
    assert rows[0]['identity']['backend_id'] != rows[1]['identity']['backend_id']


def test_hardware_and_backend_split_efficiency_groups():
    a, ap = _input('a')
    b, bp = _input('b')
    for record in (a, b):
        record['metrics'] = [{'name':'latency', 'family':'performance', 'value':1,
                              'unit':'ms', 'confidence_interval':{'low':1,'high':1}}]
    b['identity']['hardware_fingerprint'] = 'sha256:' + 'd' * 64
    result = build_comparison_index([a, b], {'a': ap, 'b': bp})
    assert len(result['groups']) == 2
    assert result['exclusions'] == []


def test_judge_prompt_differences_split_qa_groups():
    a, ap = _input('a')
    b, bp = _input('b')
    for record in (a, b):
        record['metrics'] = [{'name':'qa_accuracy', 'family':'judged_qa', 'value':0.5,
                              'unit':'ratio', 'confidence_interval':{'low':0.4,'high':0.6},
                              'judge':{'model':'judge-v1', 'prompt_digest':'sha256:'+'a'*64,
                                       'config_digest':'sha256:'+'b'*64}}]
    b['metrics'][0]['judge']['prompt_digest'] = 'sha256:' + 'd' * 64
    result = build_comparison_index([a, b], {'a': ap, 'b': bp})
    assert len(result['groups']) == 2
    assert result['exclusions'] == []


def test_context_cannot_override_lineage():
    record, payloads = _input()
    record = _v2_official_record()
    record['record_id'] = 'one'
    _bind(record, payloads)
    result = build_comparison_index([record], {'one': payloads})
    assert result['groups'] == []
    assert result['exclusions'][0]['reason'] == 'comparison-context-lineage-mismatch'


def test_renderer_exports_empty_index_without_inventing_comparison(tmp_path):
    from leaderboard.render import render_site
    path = tmp_path / 'results.json'
    path.write_text('[]')
    render_site(path, {}, tmp_path / 'site')
    index = json.loads((tmp_path / 'site/data/comparison-index.json').read_text())
    assert index['groups'] == index['exclusions'] == index['source_record_ids'] == []
    assert index['ranking'] is None


def test_duplicate_metric_cannot_inflate_group_rows():
    record, payloads = _input()
    record['metrics'].append(copy.deepcopy(record['metrics'][0]))
    result = build_comparison_index([record], {'one':payloads})
    assert result['groups'] == []
    assert result['exclusions'][0]['reason'] == 'ambiguous-duplicate-metric'


@pytest.mark.parametrize('field', ['seed', 'module_id'])
def test_distinct_atomic_cells_are_not_duplicate_attempts(field):
    a, ap = _input()
    b = copy.deepcopy(a)
    b['record_id'] = 'distinct-cell'
    b['identity'][field] = 2 if field == 'seed' else 'M02'
    if field == 'module_id':
        b['module_id'] = 'M02'
    else:
        b['run_profile']['seeds'] = [2]
    result = build_comparison_index([a, b], {'one':ap, 'distinct-cell':ap})
    assert result['exclusions'] == []
    assert sum(len(group['rows']) for group in result['groups']) == 2
    assert all(not group['multi_system'] for group in result['groups'])
