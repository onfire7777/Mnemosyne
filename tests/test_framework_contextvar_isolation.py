"""Verification of ContextVar isolation and zero cache token leaks in frameworks.py."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

from mnemosyne import frameworks as fx


def test_sequential_cache_scope_restores_clean_default(tmp_path: Path):
    assert fx.CACHE.get() == ""
    path1 = str(tmp_path / "c1")
    path2 = str(tmp_path / "c2")

    with fx.cache_scope(path1):
        assert fx.CACHE.get() == path1
    assert fx.CACHE.get() == ""

    with fx.cache_scope(path2):
        assert fx.CACHE.get() == path2
    assert fx.CACHE.get() == ""


def test_exception_in_cache_scope_resets_token(tmp_path: Path):
    assert fx.CACHE.get() == ""
    path = str(tmp_path / "error_cache")

    with pytest.raises(RuntimeError, match="deliberate failure"):
        with fx.cache_scope(path):
            assert fx.CACHE.get() == path
            raise RuntimeError("deliberate failure")

    assert fx.CACHE.get() == ""


def test_nested_cache_scopes_restore_parent_and_default(tmp_path: Path):
    assert fx.CACHE.get() == ""
    outer = str(tmp_path / "outer")
    inner = str(tmp_path / "inner")

    with fx.cache_scope(outer):
        assert fx.CACHE.get() == outer
        with fx.cache_scope(inner):
            assert fx.CACHE.get() == inner
        assert fx.CACHE.get() == outer

    assert fx.CACHE.get() == ""


def test_framework_context_multi_var_isolation(tmp_path: Path):
    assert fx.CACHE.get() == ""
    assert fx.MODEL.get() == ""
    assert fx.STATS.get() is None

    cache_path = str(tmp_path / "multi")
    stats_dict = {"calls": 1.0}

    with fx.framework_context(cache=cache_path, model="custom/model", stats=stats_dict):
        assert fx.CACHE.get() == cache_path
        assert fx.MODEL.get() == "custom/model"
        assert fx.STATS.get() == stats_dict

    assert fx.CACHE.get() == ""
    assert fx.MODEL.get() == ""
    assert fx.STATS.get() is None

    # Exception path
    with pytest.raises(ValueError, match="boom"):
        with fx.framework_context(cache=cache_path, model="custom/model", stats=stats_dict):
            raise ValueError("boom")

    assert fx.CACHE.get() == ""
    assert fx.MODEL.get() == ""
    assert fx.STATS.get() is None


def test_concurrent_threads_contextvar_isolation(tmp_path: Path):
    assert fx.CACHE.get() == ""
    errors: list[str] = []

    def worker(worker_id: int):
        expected_cache = str(tmp_path / f"thread_{worker_id}")
        for _ in range(10):
            if fx.CACHE.get() != "":
                errors.append(f"worker {worker_id} leaked cache before scope: {fx.CACHE.get()}")
            with fx.cache_scope(expected_cache):
                current = fx.CACHE.get()
                if current != expected_cache:
                    errors.append(f"worker {worker_id} saw {current} instead of {expected_cache}")
            if fx.CACHE.get() != "":
                errors.append(f"worker {worker_id} leaked cache after scope: {fx.CACHE.get()}")

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(worker, i) for i in range(32)]
        for f in futures:
            f.result()

    assert not errors, f"Thread isolation errors: {errors}"
    assert fx.CACHE.get() == ""


def test_asyncio_coroutines_contextvar_isolation(tmp_path: Path):
    assert fx.CACHE.get() == ""
    errors: list[str] = []

    async def async_worker(worker_id: int):
        expected_cache = str(tmp_path / f"task_{worker_id}")
        for _ in range(5):
            if fx.CACHE.get() != "":
                errors.append(f"task {worker_id} leaked cache before scope: {fx.CACHE.get()}")
            with fx.cache_scope(expected_cache):
                await asyncio.sleep(0.005)
                current = fx.CACHE.get()
                if current != expected_cache:
                    errors.append(f"task {worker_id} saw {current} instead of {expected_cache}")
                await asyncio.sleep(0.005)
            if fx.CACHE.get() != "":
                errors.append(f"task {worker_id} leaked cache after scope: {fx.CACHE.get()}")

    async def main():
        tasks = [asyncio.create_task(async_worker(i)) for i in range(20)]
        await asyncio.gather(*tasks)

    asyncio.run(main())
    assert not errors, f"Asyncio isolation errors: {errors}"
    assert fx.CACHE.get() == ""


def test_chat_json_scoped_cache_parameter(monkeypatch, tmp_path: Path):
    assert fx.CACHE.get() == ""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(fx, "_post", lambda body, key: {"choices": [{"message": {"content": '{"ok": true}'}}]})

    cache_dir = str(tmp_path / "chat_cache")
    result = fx.chat_json("sys", "user", 0, "task", cache=cache_dir)
    assert result == {"ok": True}
    assert fx.CACHE.get() == ""

    # Exception inside chat_json resets cache (use fresh prompt so cache is bypassed)
    monkeypatch.setattr(fx, "_post", lambda body, key: (_ for _ in ()).throw(RuntimeError("api error")))
    with pytest.raises(RuntimeError, match="api error"):
        fx.chat_json("sys_different", "user_different", 0, "task", cache=cache_dir)
    assert fx.CACHE.get() == ""


def test_build_scoped_cache_parameter(monkeypatch, tmp_path: Path):
    assert fx.CACHE.get() == ""
    fake_fw = {
        "nodes": [{"id": 0, "type": "section", "title": "S", "content": "c", "parent": None, "depends_on": None, "units": [1], "fields": {}}],
        "numbers": [1],
        "coverage": {"complete": True, "unresolved": []},
        "mechanical": {"passed": True, "failures": [], "repairs": []},
        "logic": {"graph_issues": [], "logic_issues": [], "logic_warnings": []},
        "judgment": {"warrants_reextract": False, "findings": []},
        "document": "doc",
        "approved": True,
    }
    monkeypatch.setattr(fx, "_build", lambda *a, **k: fake_fw)

    cache_dir = str(tmp_path / "build_cache")
    res = fx.build("Skill", ["line 1"], cache=cache_dir)
    assert res["approved"] is True
    assert fx.CACHE.get() == ""

    # Exception in _build still cleans up CACHE
    monkeypatch.setattr(fx, "_build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("build failed")))
    with pytest.raises(RuntimeError, match="build failed"):
        fx.build("Skill", ["line 1"], cache=cache_dir)
    assert fx.CACHE.get() == ""


def test_ask_scoped_cache_parameter(monkeypatch, tmp_path: Path):
    assert fx.CACHE.get() == ""
    monkeypatch.setattr(fx, "chat_json", lambda sys, usr, *a, **k: {"answer": "A", "units": [1], "answered": True})

    cache_dir = str(tmp_path / "ask_cache")
    res = fx.ask({"document": "doc", "nodes": []}, ["line 1"], "What?", cache=cache_dir)
    assert res["answer"] == "A"
    assert fx.CACHE.get() == ""
