"""Provider recovery is source-bounded and durable across interruption."""

import json
from types import SimpleNamespace

import pytest

from mnemosyne.hosts import project_memory


def runtime_for(project, *, count=84):
    episode = {'id': 'episode', 'user_id': 'owner', 'status': 'open',
               'source_cids': [f'source-{i:03}' for i in range(count)]}
    return SimpleNamespace(writer=SimpleNamespace(read=lambda _: {'episodes': {'episode': episode}}),
                           _project_episode_memory=project), episode


def test_large_episode_is_checkpointed_before_two_source_provider_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(project_memory.time, 'time', lambda: 100)
    path = tmp_path / 'checkpoint.json'
    calls = []
    def project(tenant, row, *, provider_cids):
        calls.append(set(provider_cids))
        if not provider_cids:
            return [{'source_cid': cid, 'provider_pending': True, 'created_count': 1} for cid in row['source_cids']]
        checkpoint = json.loads(path.read_text())
        assert checkpoint['completed'] and checkpoint['provider_queue']
        assert len(provider_cids) == 1
        return [{'source_cid': next(iter(provider_cids)), 'created_count': 1}]
    runtime, _ = runtime_for(project)
    first = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert first['processed'] == 1 and first['pending'] == 0
    assert first['created'] == 86 and first['provider_processed'] == 2 and first['provider_pending'] == 82
    second = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert second['processed'] == 0 and second['provider_pending'] == 80
    assert calls == [set(), {'source-000'}, {'source-001'}, {'source-002'}, {'source-003'}]


def test_interrupted_source_attempt_is_durable_without_replaying_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(project_memory.time, 'time', lambda: 100)
    path = tmp_path / 'checkpoint.json'
    calls = []
    def project(tenant, row, *, provider_cids):
        calls.append(set(provider_cids))
        if not provider_cids:
            return [{'source_cid': cid, 'provider_pending': True} for cid in row['source_cids']]
        if len(calls) == 2:
            raise KeyboardInterrupt('worker interrupted')
        return []
    runtime, _ = runtime_for(project, count=3)
    with pytest.raises(KeyboardInterrupt):
        project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    checkpoint = json.loads(path.read_text())
    assert checkpoint['completed'] and len(checkpoint['provider_queue']) == 3
    retry = next(item for item in checkpoint['provider_queue'].values() if item['source_cid'] == 'source-000')
    assert retry['attempts'] == 1 and retry['next_attempt'] > 100
    result = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert result['processed'] == 0 and result['provider_pending'] == 1 and result['provider_deferred'] == 1
    assert calls == [set(), {'source-000'}, {'source-001'}, {'source-002'}]
    monkeypatch.setattr(project_memory.time, 'time', lambda: 140)
    assert project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)['provider_pending'] == 0


def test_failed_source_does_not_starve_unattempted_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(project_memory.time, 'time', lambda: 100)
    calls = []
    def project(tenant, row, *, provider_cids):
        if not provider_cids:
            return [{'source_cid': cid, 'provider_pending': True} for cid in row['source_cids']]
        calls.append(next(iter(provider_cids)))
        return [{'rejected': [{'reason': 'provider_unavailable'}]}] if provider_cids == {'source-000'} else []
    runtime, _ = runtime_for(project, count=4)
    path = tmp_path / 'checkpoint.json'
    first = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert first['provider_pending'] == 3
    second = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert second['provider_pending'] == 1
    assert calls == ['source-000', 'source-001', 'source-002', 'source-003']
    saved = json.loads(path.read_text())
    assert len(saved['provider_completed']) == 3 and len(saved['provider_queue']) == 1


def test_removed_source_and_changed_scope_do_not_execute_old_queue(tmp_path):
    calls = []
    def project(tenant, row, *, provider_cids):
        calls.append(set(provider_cids))
        return [{'source_cid': cid, 'provider_pending': True} for cid in row['source_cids']] if not provider_cids else []
    runtime, row = runtime_for(project, count=2)
    path = tmp_path / 'checkpoint.json'
    project_memory.advance_project_memory(runtime, 'tenant', 'owner', path, provider_limit=0)
    row['source_cids'] = ['source-001']
    result = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert result['provider_pending'] == 0
    assert calls == [set(), set(), {'source-001'}]
    # Reusing a checkpoint path for another owner cannot resurrect its jobs.
    result = project_memory.advance_project_memory(runtime, 'tenant', 'different-owner', path)
    assert result['processed'] == result['provider_processed'] == 0
    assert json.loads(path.read_text())['provider_completed'] == {}


def test_legacy_checkpoint_revisits_finished_episodes_once_and_preserves_backoff(tmp_path, monkeypatch):
    monkeypatch.setattr(project_memory.time, 'time', lambda: 100)
    calls = []
    def project(tenant, row, *, provider_cids):
        calls.append(set(provider_cids))
        return [{'source_cid': 'source-000', 'provider_pending': True}] if not provider_cids else []
    runtime, row = runtime_for(project, count=1)
    fingerprint = project_memory.digest([row['source_cids'], []])
    path = tmp_path / 'checkpoint.json'
    path.write_text(json.dumps({'version': 1, 'completed': {'episode': fingerprint}, 'retries': {}}))
    assert project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)['processed'] == 1
    assert json.loads(path.read_text())['version'] == 3
    assert project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)['processed'] == 0
    assert calls == [set(), {'source-000'}]
    path.write_text(json.dumps({'version': 1, 'completed': {}, 'retries': {
        'episode': {'attempts': 2, 'last_attempt': 90, 'next_attempt': 150}}}))
    result = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert result['processed'] == 0 and result['deferred'] == 1
    assert json.loads(path.read_text())['retries']['episode']['attempts'] == 2


def test_unsupported_provider_result_is_finished_without_claiming_success(tmp_path):
    def project(tenant, row, *, provider_cids):
        return ([{'source_cid': 'source-000', 'provider_pending': True}] if not provider_cids
                else [{'rejected': [{'reason': 'not_entailed'}], 'created_count': 0}])
    runtime, _ = runtime_for(project, count=1)
    result = project_memory.advance_project_memory(runtime, 'tenant', 'owner', tmp_path / 'checkpoint.json')
    assert result['provider_pending'] == 0 and result['created'] == 0


def test_provider_source_stays_queued_until_all_chunks_complete(tmp_path):
    calls = []
    def project(tenant, row, *, provider_cids, provider_cursors=None):
        if not provider_cids:
            return [{'source_cid': 'source-000', 'provider_pending': True}]
        calls.append(provider_cursors)
        cursor = (provider_cursors or {}).get('source-000', {})
        if not cursor:
            return [{'source_cid': 'source-000', 'provider_pending': True,
                     'provider_cursor': {'offset': 12000, 'already_proposed': []}}]
        assert cursor['offset'] == 12000
        return [{'source_cid': 'source-000', 'provider_pending': False, 'coverage_complete': True}]
    runtime, _ = runtime_for(project, count=1)
    path = tmp_path / 'checkpoint.json'
    first = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert first['provider_pending'] == 1
    assert not json.loads(path.read_text())['provider_completed']
    second = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path)
    assert second['provider_pending'] == 0
    assert len(calls) == 2


def test_previous_version_completed_sources_are_reopened_for_coverage(tmp_path):
    runtime, row = runtime_for(lambda *a, **k: [{'source_cid': 'source-000', 'provider_pending': True}], count=1)
    fingerprint = project_memory.digest([row['source_cids'], []])
    path = tmp_path / 'checkpoint.json'
    path.write_text(json.dumps({'version': 2, 'scope': {'tenant_id': 'tenant', 'user_id': 'owner'},
        'completed': {'episode': fingerprint}, 'provider_completed': {'old': {
            'episode_id': 'episode', 'source_cid': 'source-000', 'fingerprint': fingerprint}}}))
    result = project_memory.advance_project_memory(runtime, 'tenant', 'owner', path, provider_limit=0)
    assert result['processed'] == result['provider_pending'] == 1
    assert json.loads(path.read_text())['provider_completed'] == {}
