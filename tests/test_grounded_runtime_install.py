from __future__ import annotations

import importlib.util
import hashlib
import json
import stat
import subprocess
import os
from pathlib import Path

import pytest

from eval.public.runtime_custody import grounded_runtime_environment
from mnemosyne.providers.grounded_protocol import MODEL_CONTENT_SHA256
from mnemosyne.providers.extractive_decomposer import SELECTOR

pytestmark = pytest.mark.skipif(os.name == "nt", reason="grounded runtime installer targets POSIX hosts")


INSTALLER = Path(__file__).parents[1] / "infra/providers/install-grounded-runtime.py"


def _module():
    spec = importlib.util.spec_from_file_location("grounded_runtime_installer", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(path: Path) -> str:
    (path / "src/mnemosyne").mkdir(parents=True)
    (path / "src/mnemosyne/__init__.py").write_text("")
    (path / "src/mnemosyne/providers").mkdir()
    for name in (
        "bounded_command.py",
        "extractive_decomposer.py",
        "grounded_protocol.py",
        "grounded_reader.py",
    ):
        (path / "src/mnemosyne/providers" / name).write_text(f"# {name}\n")
    (path / "infra/providers").mkdir(parents=True)
    for name in ("role-llm.py", "role-ladder.py"):
        (path / "infra/providers" / name).write_text("print('ok')\n")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()


def _candidate(repo: Path, commit: str) -> dict[str, str]:
    return {
        "git_sha": commit,
        "model_content_sha256": MODEL_CONTENT_SHA256,
        "decomposer_implementation_sha256": hashlib.sha256(
            (repo / "src/mnemosyne/providers/extractive_decomposer.py").read_bytes()
        ).hexdigest(),
    }


def test_runtime_install_is_commit_addressed_immutable_and_no_symlink(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    destination = _module().install(repo, tmp_path / "runtime")
    assert destination.name == commit
    assert not any(path.is_symlink() for path in destination.rglob("*"))
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["commit"] == commit and manifest["schema"] == "grounded-runtime-v1"
    assert stat.S_IMODE((destination / "bin/role-llm").stat().st_mode) == 0o500
    with pytest.raises(FileExistsError):
        _module().install(repo, tmp_path / "runtime")


def test_runtime_install_rejects_dirty_tracked_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    (repo / "src/mnemosyne/__init__.py").write_text("dirty = True\n")
    with pytest.raises(ValueError, match="clean committed"):
        _module().install(repo, tmp_path / "runtime")


def test_runtime_install_rejects_untracked_source_injection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    (repo / "src/mnemosyne/injected.py").write_text("payload = True\n")
    with pytest.raises(ValueError, match="clean committed"):
        _module().install(repo, tmp_path / "runtime")


def test_runtime_verifier_rejects_forged_tree_and_fresh_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    destination = _module().install(repo, tmp_path / "runtime")
    target = destination / "lib/mnemosyne/providers/grounded_reader.py"
    destination.chmod(0o700)
    target.chmod(0o600)
    target.write_text("# forged\n")
    manifest_path = destination / "manifest.json"
    manifest_path.chmod(0o600)
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["lib/mnemosyne/providers/grounded_reader.py"] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="candidate git custody"):
        grounded_runtime_environment(
            manifest_path,
            _candidate(repo, commit),
            "http://127.0.0.1:11434",
            repo_root=repo,
        )


def test_runtime_execution_cannot_drift_installed_tree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit = _repo(repo)
    destination = _module().install(repo, tmp_path / "runtime")
    before = sorted(path.relative_to(destination) for path in destination.rglob("*"))
    subprocess.run(
        [destination / "bin/role-llm"],
        env={**os.environ, "PYTHONPATH": str(destination / "lib")},
        check=True,
        capture_output=True,
    )
    after = sorted(path.relative_to(destination) for path in destination.rglob("*"))
    assert after == before
    environment = grounded_runtime_environment(
        destination / "manifest.json",
        _candidate(repo, commit),
        "http://127.0.0.1:11434",
        repo_root=repo,
    )
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["MNEMOSYNE_QUERY_DECOMPOSER_SELECTOR"] == SELECTOR
    assert environment["MNEMOSYNE_QUERY_DECOMPOSER_CONTENT_SHA256"] == _candidate(
        repo, commit
    )["decomposer_implementation_sha256"]
    assert all(
        stat.S_IMODE(path.stat().st_mode) & stat.S_IWUSR == 0
        for path in (destination, *(item for item in destination.rglob("*") if item.is_dir()))
    )


def test_native_artifacts_bind_candidate_files_without_claiming_execution(tmp_path: Path, monkeypatch) -> None:
    from copy import deepcopy
    from eval.harness.cli_driver import MnemoCLI
    from eval.public.adapters.locomo_config import build_native_run_config, verify_native_artifacts
    from eval.public.adapters import locomo_replay
    from eval.public.reader_policy import candidate_reader_policy
    from eval.public.runner import build_candidate_manifest

    repo = tmp_path / "native-repo"
    repo.mkdir()
    _repo(repo)
    # Keep the real protocol's decomposer content pin; the other runtime files
    # are synthetic Git-owned fixtures and are never executed by this test.
    decomposer = repo / "src/mnemosyne/providers/extractive_decomposer.py"
    decomposer.write_bytes((INSTALLER.parents[2] / "src/mnemosyne/providers/extractive_decomposer.py").read_bytes())
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bind decomposer fixture"], cwd=repo, check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                            check=True, capture_output=True, text=True).stdout.strip()
    runtime = _module().install(repo, tmp_path / "native-runtime")
    candidate = build_candidate_manifest(model_content_sha256=MODEL_CONTENT_SHA256,
                    git_sha=commit, created_at_utc="2026-10-04T00:00:00Z")
    candidate_path, resource_path = tmp_path / "candidate.json", tmp_path / "resource.json"
    candidate_path.write_bytes((json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n").encode())
    # A hash-matched failed resource artifact must never become a passing gate.
    resource_path.write_bytes(b'{"synthetic":true,"preflight_passed":false}\n')
    artifacts = {"candidate": candidate_path, "runtime": runtime / "manifest.json", "resource": resource_path}
    source = [{"sample_id": "synthetic", "conversation": {"session_1_date_time": "Synthetic date",
        "session_1": [{"speaker": "A", "text": "synthetic", "dia_id": "D1:1"}]},
        "qa": [{"question": "Synthetic?", "answer": "unused", "category": 4, "evidence": []}]}]
    config = build_native_run_config(source, MnemoCLI(store="unused"), caption_policy="exclude-caption",
                choice_draws={}, reader_policy=candidate_reader_policy(candidate),
                runtime_manifest_sha256=hashlib.sha256(artifacts["runtime"].read_bytes()).hexdigest(),
                resource_manifest_sha256=hashlib.sha256(resource_path.read_bytes()).hexdigest())
    verified = verify_native_artifacts(config, artifacts, repo_root=repo)
    assert verified["runtime_files_verified"] and verified["resource_artifact_hash_verified"]
    assert not verified["resource_preflight_verified"] and not verified["model_execution_verified"]
    assert not verified["publication_authorized"]

    raw_resource = resource_path.read_bytes()
    resource_path.write_bytes(b'{"synthetic":"changed"}\n')
    with pytest.raises(ValueError, match="configuration references"):
        verify_native_artifacts(config, artifacts, repo_root=repo)
    resource_path.write_bytes(raw_resource)
    link = tmp_path / "resource-link.json"
    link.symlink_to(resource_path)
    with pytest.raises(ValueError, match="symlink"):
        verify_native_artifacts(config, {**artifacts, "resource": link}, repo_root=repo)
    original = decomposer.read_bytes()
    decomposer.write_bytes(original + b"\n# dirty\n")
    with pytest.raises(ValueError, match="clean exact HEAD"):
        verify_native_artifacts(config, artifacts, repo_root=repo)
    decomposer.write_bytes(original)

    # Fresh hashes cannot bless a runtime that differs from its committed source.
    runtime.chmod(0o700)
    target = runtime / "lib/mnemosyne/providers/grounded_reader.py"
    target.chmod(0o600)
    target.write_bytes(b"# forged runtime\n")
    manifest_path = artifacts["runtime"]
    manifest_path.chmod(0o600)
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["lib/mnemosyne/providers/grounded_reader.py"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode())
    forged = deepcopy(config)
    forged["runtime_manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="candidate git custody"):
        verify_native_artifacts(forged, artifacts, repo_root=repo)

    # The public saved-report path rejects artifacts before invoking the scorer.
    def forbidden(*args, **kwargs):
        pytest.fail("invalid artifacts must fail before scorer execution")

    monkeypatch.setattr(locomo_replay, "replay_in_environment", forbidden)
    with pytest.raises(ValueError, match="configuration references"):
        locomo_replay.verify_report_in_environment({}, source, [], caption_policy="exclude-caption",
            choice_draws={}, python="unused", run_config=config, runtime_artifacts=artifacts)
