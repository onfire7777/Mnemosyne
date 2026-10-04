import hashlib
import json
from pathlib import Path

from eval.public.action_dependency_plan import make_corpus
from eval.public.action_dependency_scoring import score_case
from eval.public.action_dependency_observe import score_observations


def test_failed_real_attempt_retains_all_raw_evidence_and_partial_failures():
    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-dependency-attempt-2026-10-04'
    manifest = json.loads((root / 'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    status = json.loads((root / 'workload/status.json').read_text())
    assert status['status'] == 'failed' and status['completed_cases'] == 1
    assert status['exception_type'] == 'ActionCLIError'
    rows = [json.loads(line) for line in (root / 'workload/operations.jsonl').read_text().splitlines()]
    assert len(rows) == status['retained_records'] == 69
    assert sum(r['stage'] == 'formation_response' for r in rows) == 4
    assert rows[-1]['stage'] == 'action_error'
    case = make_corpus()['cases'][0]
    completed = [r for r in rows if r['case_id'] == case['public']['case_id']]
    partial = json.loads((root / 'partial-diagnostics.json').read_text())
    assert partial['state'] == [score_case(case, [r for r in completed if r['stage'] == 'turn_completed'])]
    timing = score_observations(case, {'case_id':case['public']['case_id'], 'ticks':[
        r['response'] for r in completed if r['stage'] == 'observation_response' and r['command'] == 'intention.observe']})
    assert partial['timing'] == [timing]
    assert timing['metrics']['false_negatives'] == 1
    assert partial['full_corpus_score'] is None
    assert not (root / 'workload/execution.json').exists()
    assert json.loads((root / 'cleanup.json').read_text())['models'] == []
