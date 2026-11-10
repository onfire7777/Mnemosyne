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
