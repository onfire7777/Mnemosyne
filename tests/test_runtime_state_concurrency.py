"""Focused checks for independent runtime writers and erase/update races."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import stat

import pytest

from mnemosyne.runtime_state import RuntimeState


def test_independent_writers_preserve_distinct_new_keys_and_profile_rows(tmp_path):
    path = tmp_path / 'state.json'
    RuntimeState(path).save()
    first, second = RuntimeState(path), RuntimeState(path)
    first.data['metrics']['counters']['first'] = 1
    second.data['metrics']['counters']['second'] = 2
    first.data['user_model']['entries'].append({'id': 'one', 'statement': 'first'})
    second.data['user_model']['entries'].append({'id': 'two', 'statement': 'second'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda state: state.save(), [first, second]))
    saved = RuntimeState(path).data
    assert saved['metrics']['counters'] == {'first': 1, 'second': 2}
    assert {row['id'] for row in saved['user_model']['entries']} == {'one', 'two'}


def test_same_key_divergent_updates_fail_without_clobbering(tmp_path):
    path = tmp_path / 'state.json'
    state = RuntimeState(path)
    state.data['metrics']['counters']['shared'] = 1
    state.save()
    first, second = RuntimeState(path), RuntimeState(path)
    first.data['metrics']['counters']['shared'] = 2
    second.data['metrics']['counters']['shared'] = 3
    first.save()
    with pytest.raises(ValueError, match='conflict'):
        second.save()
    assert RuntimeState(path).data['metrics']['counters']['shared'] == 2


def test_same_key_identical_updates_are_idempotent(tmp_path):
    path = tmp_path / 'state.json'
    RuntimeState(path).save()
    first, second = RuntimeState(path), RuntimeState(path)
    first.data['metrics']['counters']['shared'] = 2
    second.data['metrics']['counters']['shared'] = 2
    first.save()
    second.save()
    assert RuntimeState(path).data['metrics']['counters']['shared'] == 2


def test_concurrent_profile_delete_rejects_stale_update_without_resurrection(tmp_path):
    path = tmp_path / 'state.json'
    initial = RuntimeState(path)
    initial.data['user_model']['entries'] = [{'id': 'private', 'statement': 'before'}]
    initial.save()
    eraser, stale = RuntimeState(path), RuntimeState(path)
    eraser.data['user_model']['entries'] = []
    stale.data['user_model']['entries'][0]['statement'] = 'after'
    eraser.save()
    with pytest.raises(ValueError, match='conflict'):
        stale.save()
    assert RuntimeState(path).data['user_model']['entries'] == []


def test_unrelated_stale_write_does_not_resurrect_deleted_profile(tmp_path):
    path = tmp_path / 'state.json'
    initial = RuntimeState(path)
    initial.data['user_model']['entries'] = [{'id': 'private', 'statement': 'before'}]
    initial.save()
    eraser, stale = RuntimeState(path), RuntimeState(path)
    eraser.data['user_model']['entries'] = []
    stale.data['metrics']['counters']['independent'] = 1
    eraser.save()
    stale.save()
    assert RuntimeState(path).data['user_model']['entries'] == []
    assert RuntimeState(path).data['metrics']['counters']['independent'] == 1


def test_persist_is_private_atomic_and_cleans_failed_temporary(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    state = RuntimeState(path)
    state.save()
    if os.name != 'nt':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    original = path.read_bytes()
    state.data['metrics']['counters']['new'] = 1

    def failed_replace(*args):
        raise OSError('simulated interrupted publication')

    monkeypatch.setattr('mnemosyne.runtime_state.os.replace', failed_replace)
    with pytest.raises(OSError, match='interrupted'):
        state.save()
    assert path.read_bytes() == original
    json.loads(path.read_text())
    assert sorted(p.name for p in tmp_path.iterdir()) == ['state.json', 'state.json.lock']


def test_long_lived_process_keeps_jobs_and_profile_rows_written_by_others(tmp_path):
    from mnemosyne.user_model import UserMemoryKind, UserModelEntry

    path = tmp_path / 'state.json'
    path.write_text('{}')  # a file without the default sections still saves
    server = RuntimeState(path)
    queue, model = server.load_queue(), server.load_user_model()
    server.save_queue(queue)
    other = RuntimeState(path)
    other_queue, other_model = other.load_queue(), other.load_user_model()
    theirs = other_queue.enqueue('work', {})
    other.save_queue(other_queue)
    other_model.add_entry(UserModelEntry('t', 'u', UserMemoryKind.EXPLICIT_PREFERENCE, 'theirs'))
    other.save_user_model(other_model)
    queue.enqueue('work', {})  # both sides enqueued: this save used to raise a conflict
    for _ in range(2):  # the second save used to delete what the other process wrote
        server.save_queue(queue)
        server.save_user_model(model)
    assert queue.lease().id == theirs.id  # and the long-lived queue can run the other side's job
    queue.complete(theirs.id)
    server.save_queue(queue)
    saved = RuntimeState(path)
    assert [job.status for job in saved.load_queue().jobs.values()] == ['queued']  # finished jobs are not kept
    assert [entry.statement for entry in saved.load_user_model().entries.values()] == ['theirs']
    other.data['learning'] = {'engine_tenants': ['a']}
    other.save()
    server.data['learning'] = {'engine_tenants': ['b']}  # first learning save on both sides used to conflict
    server.save()
    assert RuntimeState(path).data['learning'] == {'engine_tenants': ['a', 'b']}


def test_profile_correction_from_another_process_is_served_and_survives_a_write(tmp_path):
    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.mcp_tools import MemoryTools

    def process():
        return MemoryTools(LocalMemoryEngine(), runtime_state=RuntimeState(tmp_path / 'state.json'))

    def statements(tools):
        return sorted(row['statement'] for row in tools.profile_context('t', 'u')['authoritative'])

    old = process().profile_add('t', 'u', 'explicit_preference', 'Region is eu-west-1')['id']
    server = process()
    assert statements(server) == ['Region is eu-west-1']
    process().profile_correct('t', 'u', old, 'Region is us-east-2')
    assert statements(server) == ['Region is us-east-2']
    server.profile_add('t', 'u', 'explicit_preference', 'Prefers Celsius')
    assert statements(process()) == ['Prefers Celsius', 'Region is us-east-2']
