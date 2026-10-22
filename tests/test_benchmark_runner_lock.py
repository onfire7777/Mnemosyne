"""No model/database calls; local processes exercise exclusive runner ownership."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace

import pytest

from eval import controlled_comparison as runner
from eval.hindsight_adapter import runner as native
from eval import runner_lock
from eval.runner_lock import RunnerBusy, exclusive_runner


def _files(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file()}


@pytest.fixture
def fake_run(monkeypatch, tmp_path):
    manifest = {"manifest_sha256": "a" * 64}
    row = {"question_id": "fixture", "question": "When?", "question_date": "2026-10-22T00:00:00Z"}
    monkeypatch.setattr(runner, "check_frozen", lambda *args: (manifest, [row]))
    monkeypatch.setattr(runner, "check_local_runtime", lambda *args: None)
    monkeypatch.setattr(runner, "dataset", lambda *args: [row])
    context = {"question_id": "fixture", "arm": "mnemosyne", "status": "completed",
               "manifest_sha256": manifest["manifest_sha256"], "candidate_texts": ["Friday"]}
    return tmp_path / "run", tmp_path / "contexts", context


def test_second_answer_runner_cannot_finalize_active_claim(monkeypatch, tmp_path, fake_run):
    run, contexts, context = fake_run
    runner.write_new(contexts / "mnemosyne/fixture.json", context)
    entered, release = Event(), Event()
    calls = []

    def answer(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return {key: context[key] for key in ("question_id", "arm", "status", "manifest_sha256")}

    monkeypatch.setattr(runner, "answer_one", answer)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(runner.run_answers, tmp_path, run, tmp_path, contexts)
        try:
            assert entered.wait(5)
            before = _files(run)
            with pytest.raises(RunnerBusy):
                runner.run_answers(tmp_path, run, tmp_path, contexts)
            assert _files(run) == before
        finally:
            release.set()
        active.result(timeout=10)
    assert len(calls) == 1
    assert json.loads((run / "answers/fixture-mnemosyne.json").read_text())["status"] == "completed"


def test_second_mnemosyne_runner_cannot_finalize_active_claim(monkeypatch, tmp_path, fake_run):
    run, contexts, context = fake_run
    entered, release = Event(), Event()

    def retrieve(row):
        entered.set()
        assert release.wait(10)
        return dict(context)

    monkeypatch.setattr(runner, "mnemosyne_context", retrieve)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(runner.run_mnemosyne, run, tmp_path, contexts)
        try:
            assert entered.wait(5)
            before = _files(contexts)
            with pytest.raises(RunnerBusy):
                # A different --run must not bypass ownership of the same outputs.
                runner.run_mnemosyne(tmp_path / "other-run", tmp_path, contexts)
            assert _files(contexts) == before
        finally:
            release.set()
        active.result(timeout=10)
    assert json.loads((contexts / "mnemosyne/fixture.json").read_text())["status"] == "completed"


@pytest.mark.parametrize("resource", ["output_dir", "receipt_dir", "runtime_dir"])
def test_native_runner_checks_every_shared_resource_before_configuration(monkeypatch, tmp_path, resource):
    args = SimpleNamespace(output_dir=tmp_path / "outputs", receipt_dir=tmp_path / "receipts",
                           runtime_dir=tmp_path / "runtime")
    monkeypatch.setattr(native, "configure", lambda *args: pytest.fail("configuration or DB initialization started"))
    with exclusive_runner(getattr(args, resource)):
        with pytest.raises(RunnerBusy):
            asyncio.run(native.run(args))
    assert not list(tmp_path.rglob("*.json"))


def test_process_crash_releases_lock_without_deleting_lock_file(tmp_path):
    resource, ready = tmp_path / "resource", tmp_path / "ready"
    script = (
        "from pathlib import Path; import sys; from eval.runner_lock import exclusive_runner\n"
        "with exclusive_runner(Path(sys.argv[1])):\n"
        " Path(sys.argv[2]).write_text('ready')\n"
        " sys.stdin.buffer.read(1)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script, str(resource), str(ready)],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), child.poll()
        lock = resource / ".benchmark-runner.lock"
        identity = (lock.stat().st_dev, lock.stat().st_ino)
        with pytest.raises(RunnerBusy):
            with exclusive_runner(resource):
                pytest.fail("second process acquired live lock")
        child.kill()
        child.wait(timeout=5)
        with exclusive_runner(resource):
            assert (lock.stat().st_dev, lock.stat().st_ino) == identity
        assert lock.exists()
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_native_async_cancellation_releases_all_owned_resources(monkeypatch, tmp_path):
    args = SimpleNamespace(output_dir=tmp_path / "outputs", receipt_dir=tmp_path / "receipts",
                           runtime_dir=tmp_path / "runtime")

    async def exercise():
        entered = asyncio.Event()

        async def pending(unused):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(native, "_run", pending)
        task = asyncio.create_task(native.run(args))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            for resource in (args.output_dir, args.receipt_dir, args.runtime_dir):
                with pytest.raises(RunnerBusy):
                    with exclusive_runner(resource):
                        pytest.fail("native async runner released ownership before exit")
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        with exclusive_runner(args.output_dir, args.receipt_dir, args.runtime_dir):
            pass

    asyncio.run(exercise())


def test_partial_acquisition_and_keyboard_interrupt_release_locks(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    with exclusive_runner(b):
        with pytest.raises(RunnerBusy):
            with exclusive_runner(a, b):
                pytest.fail("partial acquisition entered body")
        with exclusive_runner(a):
            pass
    with pytest.raises(KeyboardInterrupt):
        with exclusive_runner(a, b):
            raise KeyboardInterrupt
    with exclusive_runner(a, b):
        pass


def test_canonical_path_alias_and_duplicate_resources(tmp_path):
    resource = tmp_path / "resource"
    with exclusive_runner(resource, resource):
        with pytest.raises(RunnerBusy):
            with exclusive_runner(resource / ".." / "resource"):
                pytest.fail("path alias bypassed ownership")


@pytest.mark.parametrize("code", [errno.EACCES, errno.EAGAIN, errno.EPERM])
def test_windows_nonblocking_byte_lock_and_errors(monkeypatch, tmp_path, code):
    calls = []
    failing = [False]

    def locking(fd, mode, length):
        assert length == 1 and os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert os.get_inheritable(fd) is False
        calls.append(mode)
        if failing[0]:
            raise OSError(code, "fixture lock error")

    monkeypatch.setattr(runner_lock.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(locking=locking, LK_NBLCK=2, LK_UNLCK=0))
    with exclusive_runner(tmp_path):
        assert calls == [2]
    assert calls == [2, 0]
    assert (tmp_path / ".benchmark-runner.lock").stat().st_size == 0
    failing[0] = True
    expected = RunnerBusy if code in {errno.EACCES, errno.EAGAIN} else OSError
    with pytest.raises(expected):
        with exclusive_runner(tmp_path):
            pytest.fail("failed lock admitted runner")
    assert calls == [2, 0, 2]


def test_lock_helper_is_in_frozen_source_manifest(monkeypatch, tmp_path):
    names = ["codex_reader.py", "codex_bridge.py", "comparison_protocol.py", "controlled_comparison.py",
             "runner_lock.py", "longmemeval_recall.py", "longmemeval_s/run_bench_LongMemEval.py", "harness/metrics.py"]
    for name in names:
        path = tmp_path / "eval" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    assert "eval/runner_lock.py" in runner.source_hashes()
