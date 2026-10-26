"""Book CLI waits for the exact queued revision without starting another worker."""
from types import SimpleNamespace

import pytest

from mnemosyne import cli


@pytest.mark.parametrize('command', ['framework-import', 'skill-make-burnskill'])
def test_wait_flag_parses_for_conversion_commands(command):
    target = ['--path', 'book.epub'] if command == 'framework-import' else ['--skill-id', 'book']
    args = cli.build_parser().parse_args([command, *target, '--wait'])
    assert args.wait is True


def test_wait_reuses_tools_and_emits_terminal_result_only(monkeypatch, capsys):
    statuses = iter([
        {'conversion': 'converting', 'progress': 'chapter 1'},
        {'conversion': 'converting', 'progress': 'chapter 1'},
        {'conversion': 'completed', 'progress': 'done', 'coverage': {'complete': True}},
    ])
    calls, emitted, sleeps = [], [], []
    def status(skill_id, revision):
        calls.append((skill_id, revision))
        return next(statuses)
    monkeypatch.setattr(cli, 'emit', emitted.append)
    monkeypatch.setattr(cli.time, 'sleep', sleeps.append)
    cli._emit_framework_job(SimpleNamespace(framework_status=status),
        {'status': 'converting', 'skill_id': 'book', 'revision': 4}, wait_for_completion=True)
    assert calls == [('book', 4)] * 3
    assert sleeps == [1, 1]
    assert len(emitted) == 1 and emitted[0]['conversion'] == 'completed'
    assert capsys.readouterr().err == 'chapter 1\ndone\n'


@pytest.mark.parametrize('outcome', ['incomplete', 'failed', 'unknown'])
def test_wait_fails_closed_with_terminal_diagnostics(monkeypatch, outcome):
    emitted = []
    monkeypatch.setattr(cli, 'emit', emitted.append)
    status = {'conversion': outcome, 'error': 'source units unresolved'}
    with pytest.raises(SystemExit) as exc:
        cli._emit_framework_job(SimpleNamespace(framework_status=lambda *a, **k: status),
            {'status': 'converting', 'skill_id': 'book', 'revision': 4}, wait_for_completion=True)
    assert exc.value.code == 1 and emitted == [status]


def test_nonblocking_mode_keeps_existing_behavior(monkeypatch):
    emitted = []
    monkeypatch.setattr(cli, 'emit', emitted.append)
    result = {'status': 'converting'}
    cli._emit_framework_job(SimpleNamespace(), result, wait_for_completion=False)
    assert emitted == [result]


@pytest.mark.parametrize('outcome', ['incomplete', 'failed', 'unknown', None])
def test_wait_rejects_immediate_incomplete_or_unknown_result(monkeypatch, outcome):
    emitted = []
    monkeypatch.setattr(cli, 'emit', emitted.append)
    result = {'status': outcome, 'error': 'import did not produce a usable framework'}
    with pytest.raises(SystemExit) as exc:
        cli._emit_framework_job(SimpleNamespace(), result, wait_for_completion=True)
    assert exc.value.code == 1 and emitted == [result]


def test_wait_accepts_immediately_ready_result(monkeypatch):
    emitted = []
    monkeypatch.setattr(cli, 'emit', emitted.append)
    result = {'status': 'ready', 'unchanged': True}
    cli._emit_framework_job(SimpleNamespace(), result, wait_for_completion=True)
    assert emitted == [result]
