from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from eval.public.action_reference_store import DurableActionReference


def store(path, tenant='one'):
    return DurableActionReference(path, run_id='run', case_id='case', tenant_id=tenant, session_id='session')


def task():
    return {'task_id': 'a', 'action_id': 'original', 'idempotency_key': 'create',
            'trigger': {'type': 'exact_time', 'payload': {'at': '2030-01-01T00:00:00Z'}}}


def test_reopen_after_lost_mutation_response_preserves_retry_and_final_state(tmp_path):
    path = tmp_path / 'reference.sqlite3'
    store(path).run('task.create', task())
    before = store(path).run('task.inspect', {'task_id': 'a'})
    update = {'type': 'override', 'task_id': 'a', 'action_id': 'revised',
              'expected_revision': before['revision'], 'idempotency_key': 'update'}
    store(path).run('task.update', update)  # committed response deliberately discarded
    store(path).run('task.create', task())
    assert store(path).run('task.update', update) == {}
    store(path).run('clock.inject', {'now': '2030-01-01T00:00:00Z'})
    fired = store(path).run('intention.observe', {})
    assert fired['firing_observations'][0]['action_id'] == 'revised'
    store(path).run('task.update', update)
    assert store(path).run('intention.observe', {})['firing_observations'] == []
    assert store(path).run('task.inspect', {'task_id': 'a'})['status'] == 'fired'
    with pytest.raises(ValueError, match='unknown task'):
        store(path, tenant='other').run('task.inspect', {'task_id': 'a'})


def test_concurrent_identical_creation_and_observation_are_serialized(tmp_path):
    path = tmp_path / 'reference.sqlite3'
    store(path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: store(path).run('task.create', task()), range(2))) == [{}, {}]
    store(path).run('clock.inject', {'now': '2030-01-01T00:00:00Z'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: store(path).run('intention.observe', {}), range(2)))
    assert sum(len(r['firing_observations']) for r in replies) == 1


def test_invalid_command_rolls_back_and_tampering_is_detected(tmp_path):
    path = tmp_path / 'reference.sqlite3'
    store(path).run('task.create', task())
    with pytest.raises(ValueError):
        store(path).run('unsupported', {})
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM journal').fetchone()[0] == 1
        db.execute("UPDATE journal SET response=?", (b'{"forged":true}',))
    with pytest.raises(ValueError, match='does not replay'):
        store(path).run('task.inspect', {'task_id': 'a'})


def test_foreign_database_is_not_modified(tmp_path):
    path = tmp_path / 'foreign.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE user_data(value TEXT)')
        db.execute("INSERT INTO user_data VALUES ('keep')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match='not a supported'):
        store(path)
    assert path.read_bytes() == before


def test_fresh_process_recovers_committed_creation(tmp_path):
    import json
    import subprocess
    import sys

    path = tmp_path / 'reference.sqlite3'
    program = (
        'import json,sys; from eval.public.action_reference_store import DurableActionReference; '
        'request=json.load(sys.stdin); '
        'store=DurableActionReference(sys.argv[1],run_id="run",case_id="case",tenant_id="one",session_id="session"); '
        'print(json.dumps(store.run(request["command"],request["payload"])))'
    )
    subprocess.run([sys.executable, '-c', program, str(path)],
                   input=json.dumps({'command': 'task.create', 'payload': task()}),
                   text=True, capture_output=True, check=True, timeout=10)
    recovered = subprocess.run([sys.executable, '-c', program, str(path)],
                              input=json.dumps({'command': 'task.inspect', 'payload': {'task_id': 'a'}}),
                              text=True, capture_output=True, check=True, timeout=10)
    assert json.loads(recovered.stdout)['action_id'] == 'original'
    assert json.loads(recovered.stdout)['status'] == 'scheduled'


def test_moving_journal_rows_between_scopes_breaks_integrity_check(tmp_path):
    path = tmp_path / 'reference.sqlite3'
    first, other = store(path), store(path, tenant='other')
    first.run('task.create', task())
    with sqlite3.connect(path) as db:
        db.execute('UPDATE journal SET scope=?', (other.scope,))
    with pytest.raises(ValueError, match='does not replay'):
        other.run('task.inspect', {'task_id': 'a'})
