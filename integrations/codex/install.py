"""Atomically update an already configured local Codex host; keep credentials external."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime

FILES = {"runtime_template.py": "runtime.py", "cli.py": "cli.py", "hook.py": "hook.py", "worker.py": "worker.py",
         "automatic_learning.py": "automatic_learning.py", "parametric.py": "parametric.py",
         "backfill.py": "backfill.py", "recall_server.py": "recall_server.py",
         "embedding_service.py": "embedding_service.py"}


def _atomic_write_bytes(destination: Path, path: Path, content: bytes) -> str:
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=destination)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(content).hexdigest()


def _load_sibling_module(filename: str, module_name: str):
    import importlib.util

    source = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load sibling module {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_release(destination, wheel):
    """Unpack a built package before atomically activating its content hash."""
    wheel = Path(wheel)
    fingerprint = hashlib.sha256(wheel.read_bytes()).hexdigest()
    releases = destination.parent / 'releases'
    releases.mkdir(parents=True, exist_ok=True, mode=0o700)
    release = releases / fingerprint
    if not release.exists():
        with tempfile.TemporaryDirectory(prefix='.install-', dir=releases) as temporary:
            stage = Path(temporary) / 'package'
            stage.mkdir()
            with zipfile.ZipFile(wheel) as archive:
                for member in archive.infolist():
                    target = (stage / member.filename).resolve()
                    if not target.is_relative_to(stage.resolve()):
                        raise ValueError('wheel contains an invalid member path')
                    if member.filename.startswith('mnemosyne/') or '.dist-info/' in member.filename:
                        archive.extract(member, stage)
            if not (stage / 'mnemosyne/__init__.py').is_file():
                raise ValueError('wheel does not contain the memory package')
            stage.rename(release)
    manifest = {'path': str(release.resolve()), 'wheel_sha256': fingerprint}
    descriptor, temporary = tempfile.mkstemp(prefix='active-release.', dir=destination)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(manifest, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination / 'active-release.json')
    return manifest


def install(
    destination,
    backup,
    *,
    wheel=None,
    render_reranker=False,
    embedding_mode="keep",
    embedding_model=None,
    embedding_dims=None,
    confirm_vector_space_switch=False,
):
    destination, backup = Path(destination), Path(backup)
    if not (destination / "reader.json").is_file() or not (destination / "retrieval_config.py").is_file():
        raise ValueError("configure reader.json and retrieval_config.py before installing the host")
    if embedding_mode not in {"keep", "openrouter-4096", "openrouter-1024", "local"}:
        raise ValueError(f"unsupported embedding_mode: {embedding_mode!r}")
    if embedding_mode != "keep" and not confirm_vector_space_switch:
        raise ValueError(
            "switching retrieval_config.py requires confirm_vector_space_switch=True "
            "(and matching offline re-embed so vector spaces are never mixed)"
        )
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    if (destination / 'active-release.json').exists():
        shutil.copy2(destination / 'active-release.json', backup / 'active-release.json')
    manifest = {"installed_at": datetime.now(UTC).isoformat(), "files": {}}
    for source, name in FILES.items():
        path = destination / name
        if path.exists():
            shutil.copy2(path, backup / name)
        content = Path(__file__).with_name(source).read_bytes()
        manifest["files"][name] = _atomic_write_bytes(destination, path, content)
    if render_reranker:
        rt_mod = _load_sibling_module("runtime_template.py", "_mnemosyne_install_runtime_template")
        reranker_path = destination / "reranker_service.py"
        if reranker_path.exists():
            shutil.copy2(reranker_path, backup / "reranker_service.py")
        reranker_bytes = rt_mod.render_reranker_service().encode("utf-8")
        manifest["files"]["reranker_service.py"] = _atomic_write_bytes(destination, reranker_path, reranker_bytes)
    if embedding_mode != "keep":
        emb_mod = _load_sibling_module("embedding_service.py", "_mnemosyne_install_embedding_service")
        config_path = destination / "retrieval_config.py"
        if config_path.exists():
            shutil.copy2(config_path, backup / "retrieval_config.py")
        if embedding_mode == "local":
            rendered = emb_mod.render_retrieval_config(
                mode="local", model=embedding_model, dims=embedding_dims, root=destination.parent,
            )
        else:
            dims = 1024 if embedding_mode == "openrouter-1024" else 4096
            rendered = emb_mod.render_retrieval_config(
                mode="openrouter", model=embedding_model, dims=dims if embedding_dims is None else embedding_dims,
                root=destination.parent,
            )
        manifest["files"]["retrieval_config.py"] = _atomic_write_bytes(
            destination, config_path, rendered.encode("utf-8")
        )
        manifest["embedding_mode"] = embedding_mode
    if wheel is not None:
        manifest['release'] = install_release(destination, wheel)
    (backup / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path.home() / ".local/share/mnemosyne/codex")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, help="activate an isolated built package snapshot")
    parser.add_argument("--render-reranker-service", action="store_true",
                        help="atomically update reranker_service.py from runtime_template.py")
    parser.add_argument("--embedding-mode", choices=["keep", "openrouter-4096", "openrouter-1024", "local"],
                        default="keep", help="optional retrieval_config.py vector-space mode (default: keep)")
    parser.add_argument("--embedding-model", type=str, default=None)
    parser.add_argument("--embedding-dims", type=int, default=None)
    parser.add_argument("--confirm-vector-space-switch", action="store_true",
                        help="required when changing --embedding-mode away from keep")
    args = parser.parse_args()
    print(json.dumps(install(
        args.destination, args.backup, wheel=args.wheel,
        render_reranker=args.render_reranker_service,
        embedding_mode=args.embedding_mode,
        embedding_model=args.embedding_model,
        embedding_dims=args.embedding_dims,
        confirm_vector_space_switch=args.confirm_vector_space_switch,
    ), indent=2))
