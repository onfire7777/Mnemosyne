import json
from pathlib import Path
import shutil

import pytest

from eval.public.action_formation_failure import summarize

REPORTS = Path(__file__).resolve().parents[1] / 'eval/reports'


@pytest.mark.parametrize('name,complete,incomplete,unattempted', [
    ('m12-formation-feasibility-2026-10-04', 0, 1, 219),
    ('m12-formation-schema-attempt-2026-10-04', 21, 1, 198),
])
def test_all_planned_cases_remain_visible_after_failure(name, complete, incomplete, unattempted):
    result = summarize(REPORTS / name / 'workload')
    assert result['planned_cases'] == len(result['cases']) == 220
    assert result['completed_cases'] == complete
    assert result['incomplete_cases'] == incomplete
    assert result['not_attempted_cases'] == unattempted
    assert result['full_corpus_score'] is None
    assert result['ranking_eligible'] is result['trace_consistency_verified'] is False
    assert all(c['diagnostics'] is None for c in result['cases'][complete:])
    if complete:
        assert sum(c['timing']['metrics']['false_negatives'] for c in result['cases'][:complete]) == 17


@pytest.mark.parametrize('damage', ['count', 'source', 'inputs', 'probe', 'boolean_probe', 'order'])
def test_inconsistent_partial_evidence_is_rejected(tmp_path, damage):
    root = tmp_path / 'capture'
    shutil.copytree(REPORTS / 'm12-formation-schema-attempt-2026-10-04' / 'workload', root)
    if damage == 'count':
        path = root / 'status.json'
        value = json.loads(path.read_text())
        value['completed_cases'] = 20
    elif damage == 'source':
        path = root / 'source.json'
        value = json.loads(path.read_text())
        value['harness_files']['eval/public/action_timing.py'] = '0' * 64
    elif damage == 'inputs':
        path = root / 'inputs.json'
        value = json.loads(path.read_text())
        value['cases'].pop()
    else:
        path = root / 'operations.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if damage in ('probe', 'boolean_probe'):
            next(r for r in rows if r['stage'] == 'observation_response' and r['command'] == 'intention.observe')['probe'] = False if damage == 'boolean_probe' else 10
        else:
            rows.reverse()
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with pytest.raises(ValueError):
            summarize(root)
        return
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        summarize(root)
