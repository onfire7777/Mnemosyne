"""Verify an external immutable grounded-role runtime and derive exact env."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from mnemosyne.providers.grounded_protocol import MODEL_CONTENT_SHA256, MODEL_SELECTOR


def grounded_runtime_environment(
    path: Path, candidate: Mapping[str, Any], ollama_url: str, *, repo_root: Path
) -> dict[str, str]:
    if candidate.get("model_content_sha256") != MODEL_CONTENT_SHA256:
        raise ValueError("candidate model content digest does not match preregistration")
    if path.is_symlink() or not path.is_file():
        raise ValueError("runtime manifest must be a real external file")
    root = path.resolve().parent
    repo_root = repo_root.resolve()
    if root == repo_root or repo_root in root.parents:
        raise ValueError("runtime manifest must be external to the repository")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "grounded-runtime-v1" or manifest.get("commit") != candidate["git_sha"]:
        raise ValueError("runtime manifest does not match candidate commit")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("runtime manifest file custody is missing")
    required = {"bin/role-ladder", "bin/role-llm", "libexec/role-ladder.py", "libexec/role-llm.py", "lib/mnemosyne/providers/bounded_command.py", "lib/mnemosyne/providers/grounded_protocol.py", "lib/mnemosyne/providers/grounded_reader.py"}
    if not required <= set(files):
        raise ValueError("runtime manifest is missing required files")
    discovered: set[str] = set()
    for target in root.rglob("*"):
        if target == path.resolve():
            continue
        if target.is_symlink():
            raise ValueError("runtime custody must not contain symlinks")
        if target.is_file():
            discovered.add(target.relative_to(root).as_posix())
    if discovered != set(files):
        raise ValueError("runtime manifest does not cover the exact runtime tree")
    for relative, digest in files.items():
        key = PurePosixPath(relative)
        if key.is_absolute() or ".." in key.parts or key.as_posix() != relative:
            raise ValueError("runtime manifest contains an unsafe path")
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError("runtime manifest path escapes runtime root")
        if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("runtime manifest file custody mismatch")
        expected = _candidate_file(repo_root, candidate["git_sha"], relative)
        if expected is None or target.read_bytes() != expected:
            raise ValueError("runtime file does not match candidate git custody")
    role_llm, role_ladder = root / "bin/role-llm", root / "bin/role-ladder"
    if not os.access(role_llm, os.X_OK) or not os.access(role_ladder, os.X_OK):
        raise ValueError("runtime role commands are not executable")
    return {
        "MNEMOSYNE_QUERY_DECOMPOSER_PROVIDER": "command",
        "MNEMOSYNE_QUERY_DECOMPOSER_COMMAND": str(role_ladder),
        "MNEMOSYNE_GROUNDED_READER_PROVIDER": "command",
        "MNEMOSYNE_GROUNDED_READER_COMMAND": str(role_ladder),
        "MNEMOSYNE_GROUNDED_MODEL_SELECTOR": MODEL_SELECTOR,
        "MNEMOSYNE_GROUNDED_MODEL_CONTENT_SHA256": candidate["model_content_sha256"],
        "MNEMOSYNE_GROUNDED_PROVIDER_TIMEOUT": "320",
        "MNEMOSYNE_ROLE_LADDER_LOCAL_COMMAND": str(role_llm),
        "MNEMOSYNE_ROLE_LADDER_TIMEOUT": "300",
        "MNEMOSYNE_ROLE_LADDER_LOCAL_TIMEOUT": "280",
        "MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OLLAMA_MODEL": MODEL_SELECTOR,
        "OLLAMA_TIMEOUT": "280",
        "OLLAMA_URL": ollama_url,
    }


def _candidate_file(repo: Path, commit: str, relative: str) -> bytes | None:
    if relative.startswith("lib/mnemosyne/"):
        source = "src/" + relative.removeprefix("lib/")
    elif relative.startswith("libexec/") and relative.endswith(".py"):
        source = "infra/providers/" + relative.removeprefix("libexec/")
    elif relative in {"bin/role-llm", "bin/role-ladder"}:
        name = relative.removeprefix("bin/")
        return (
            "#!/usr/bin/env python3\n"
            "import runpy,sys\n"
            "sys.dont_write_bytecode=True\n"
            "from pathlib import Path\n"
            "root=Path(__file__).resolve().parents[1]\n"
            "sys.path.insert(0,str(root/'lib'))\n"
            f"runpy.run_path(str(root/'libexec'/'{name}.py'),run_name='__main__')\n"
        ).encode()
    else:
        return None
    result = subprocess.run(
        ["git", "show", f"{commit}:{source}"], cwd=repo,
        capture_output=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None
