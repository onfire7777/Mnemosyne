"""Snapshot a just-observed failed pytest check without rewriting its history."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
import time


def capture_failed_python_environment(event, workspace=None):
    """Call only at current PostToolUse, never during retained-log reparsing.

    The command chooses the tests; imports choose source files. No broad home
    scan, symlink traversal, secret/config capture, or historical reconstruction.
    Oversized or ambiguous environments decline automatic capture.
    """
    from mnemosyne.hosts.codex import _pytest_invocation
    from mnemosyne.local_paths import normalize_workspace
    from .environment_experiments import valid_environment
    deadline = time.monotonic() + 2
    if event.get("source") != "tool" or event.get("runner") != "pytest" or event.get("failed", 0) <= 0:
        return None
    tokens = _pytest_invocation(event.get("command"))
    location = normalize_workspace(event.get("cwd") or workspace)
    if not tokens or location is None:
        return None
    root = Path(location).resolve()
    if not root.is_dir() or root == Path(root.anchor):
        return None
    tests = []
    for token in tokens:
        filename, *selector = token.split("::")
        if not filename.endswith(".py") or filename.startswith("-"):
            continue
        path = Path(filename) if Path(filename).is_absolute() else root / filename
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError:
            return None
        tests.append(relative + ("::" + "::".join(selector) if selector else ""))
    if not tests:
        return None
    files, queue, seen, stamps = {}, [test.split("::")[0] for test in tests], set(), {}
    bases = [root, root / "src"]
    total = 0
    def local_module(parts):
        if not parts:
            return None
        stem = Path(*parts) if parts else Path()
        for base in bases:
            for target in (base / stem.with_suffix(".py"), base / stem / "__init__.py"):
                if target.is_file():
                    return target.relative_to(root).as_posix()
        return None
    while queue:
        if time.monotonic() > deadline:
            return None
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = root / name
        if (any(part.startswith(".") for part in Path(name).parts) or path.is_symlink()
                or any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents)):
            return None
        try:
            before = path.stat()
            content = path.read_text()
            after = path.stat()
        except (OSError, UnicodeError):
            return None
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            return None
        total += len(content)
        if total > 2097152 or len(files) >= 128 or len(content) > 131072:
            return None
        files[name] = content
        stamps[name] = (after.st_mtime_ns, after.st_size)
        for parent in path.parents:
            if parent == root or root not in parent.parents:
                break
            for suffix in ("__init__.py", "conftest.py"):
                candidate = parent / suffix
                if candidate.is_file():
                    queue.append(candidate.relative_to(root).as_posix())
        if (root / "conftest.py").is_file():
            queue.append("conftest.py")
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue  # Syntax failures are valid reproducible environments.
        module = list(Path(name).with_suffix("").parts)
        if module[:1] == ["src"]:
            module = module[1:]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".") for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = module[:-node.level] if node.level else []
                imported = prefix + (node.module.split(".") if node.module else [])
                modules = [imported, *[imported + [alias.name] for alias in node.names if alias.name != "*"]]
            else:
                continue
            for parts in modules:
                found = local_module(parts)
                if found:
                    queue.append(found)
    try:
        if any((stat.st_mtime_ns, stat.st_size) != stamps[name]
               for name in files for stat in [(root / name).stat()]):
            return None
    except OSError:
        return None
    failures = re.findall(r"(?m)^FAILED\s+([^\s]+)", str(event.get("output", "")))
    environment = {"version": 1, "kind": "python", "runner": "pytest", "files": files,
                   "tests": sorted(set(tests)), "original_failed_tests": sorted(set(failures)),
                   "captured_at": datetime.now(UTC).isoformat(), "source_workspace": str(root),
                   "source_hashes": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()},
                   "source_call_id": event.get("call_id"), "baseline_exit_code": event.get("exit_code")}
    return environment if valid_environment(environment) else None
