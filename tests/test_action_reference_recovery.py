import json

import pytest

from eval.public import action_reference_recovery as recovery


def test_full_durable_reference_recovery_replays_with_sink(tmp_path):
    output = tmp_path / 'run'
    result = recovery.run_development(output)
    assert recovery.recompute(output) == result
    assert result['publishable'] is result['baseline_admitted'] is False
    cases = result['workload']['cases']
    assert sum(c['injected_response_losses'] for c in cases) == 50
    assert sum(c['adapter_resets'] for c in cases) == 50
    assert sum(c['report']['metrics']['true_positives'] for c in cases) == 10
    assert all(c['report']['metrics']['false_positives'] == c['report']['metrics']['false_negatives'] == 0 for c in cases)
    assert json.loads((output / 'status.json').read_text())['completed_operations'] == 360
    annex = json.loads((output / 'sink.json').read_text())
    assert sum(len(c['snapshot']['receipts']) for c in annex['cases']) == 10
    assert sum(len(c['snapshot']['attempts']) for c in annex['cases']) == 20
    records = [json.loads(line) for line in (output / 'operations.jsonl').read_text().splitlines()]
    row = next(r for r in records if r['command'] == 'task.update' and 'expected_revision' in r['resolved_payload'])
    row['resolved_payload']['expected_revision'] = '0' * 64
    (output / 'operations.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
    with pytest.raises(ValueError):
        recovery.recompute(output)


def test_sink_failure_cannot_be_reported_as_success(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError('sensitive-reason')
    monkeypatch.setattr(recovery, '_deliver', fail)
    output = tmp_path / 'failed'
    with pytest.raises(RuntimeError):
        recovery.run_development(output)
    status = json.loads((output / 'status.json').read_text())
    assert status['status'] == 'failed'
    assert status['completed_operations'] > 0
    assert status['exception_type'] == 'RuntimeError'
    assert 'sensitive-reason' not in (output / 'status.json').read_text()
    assert not (output / 'reports.json').exists()


def test_reference_recovery_requires_distinct_identity_and_sink(tmp_path):
    output = tmp_path / 'run'
    recovery.run_development(output)
    path = output / 'source.json'
    source = json.loads(path.read_text())
    source['sink_enabled'] = False
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match='identity and sink'):
        recovery.recompute(output)


def test_retained_committed_reference_recovery_capture_replays():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / 'eval/reports/m12-reference-recovery-development-2026-10-04'
    result = recovery.recompute(root)
    cases = result['workload']['cases']
    assert sum(c['injected_response_losses'] for c in cases) == 50
    assert sum(c['adapter_resets'] for c in cases) == 50
    assert sum(c['report']['metrics']['true_positives'] for c in cases) == 10
    assert all(c['report']['metrics']['false_positives'] == c['report']['metrics']['false_negatives'] == 0 for c in cases)
    assert result['baseline_admitted'] is result['publishable'] is False
