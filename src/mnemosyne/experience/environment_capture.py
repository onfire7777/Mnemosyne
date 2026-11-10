"""Snapshot a just-observed Python test failure without rewriting its history."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import re
import time


def _test_selection(tokens, runner, root, deadline):
    """Expand explicit files, modules or bounded discovery, never arbitrary flags."""
    args = tokens[3:] if len(tokens) > 2 and tokens[1] == "-m" else tokens[1:]
    selections, pattern, start = [], "test*.py", "."
    index = 0
    takes_value = {"-k", "-m", "--maxfail", "--tb", "--color", "--durations"}
    while index < len(args):
        token = args[index]
        if runner == "unittest" and token == "discover":
            index += 1
            continue
        if runner == "unittest" and token in {"-s", "--start-directory", "-p", "--pattern", "-t", "--top-level-directory"}:
            if index + 1 >= len(args):
                return None
            value = args[index + 1]
            if token in {"-p", "--pattern"}:
                if value not in {"test*.py", "test_*.py", "*_test.py"}:
                    return None
                pattern = value
            elif token in {"-s", "--start-directory"}:
                start = value
            elif Path(value).resolve() != root and (root / value).resolve() != root:
                return None
            index += 2
            continue
        if token in takes_value:
            if index + 1 >= len(args):
                return None
            index += 2
            continue
        if token.startswith("-"):
            if not (token in {"-q", "-qq", "-v", "-vv", "-s", "-x", "-b", "-f", "-c", "--disable-warnings", "--strict-markers", "--strict-config"}
                    or any(token.startswith(option + "=") for option in takes_value if option.startswith("--"))):
                return None
            index += 1
            continue
        selections.append(token)
        index += 1
    selections = selections or [start]
    tests = []
    for selection in selections:
        name, *selector = selection.split("::")
        path = Path(name) if Path(name).is_absolute() else root / name
        if runner == "unittest" and not path.exists():
            # A test/class/method name resolves only to an existing local module.
            parts = name.split(".")
            for boundary in range(len(parts), 0, -1):
                candidate = root.joinpath(*parts[:boundary]).with_suffix(".py")
                if candidate.is_file():
                    path = candidate
                    break
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            return None
        if path.is_dir():
            for directory, dirs, files in os.walk(path, followlinks=False):
                if time.monotonic() > deadline:
                    return None
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {
                    "__pycache__", "node_modules", "venv", "env", "site-packages"}
                    and not (Path(directory) / d).is_symlink())
                for filename in sorted(files):
                    if Path(filename).match(pattern) or runner == "pytest" and Path(filename).match("*_test.py"):
                        tests.append((Path(directory) / filename).relative_to(root).as_posix())
                        if len(tests) > 64:
                            return None
        elif path.is_file() and path.suffix == ".py":
            tests.append(relative.as_posix() + ("::" + "::".join(selector) if selector and runner == "pytest" else ""))
        else:
            return None
    return sorted(set(tests)) if tests and len(tests) <= 64 else None


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
    runner = event.get("runner")
    if event.get("source") != "tool" or runner not in {"pytest", "unittest"} or event.get("failed", 0) <= 0:
        return None
    tokens = _pytest_invocation(event.get("command"), runner=runner)
    location = normalize_workspace(event.get("cwd") or workspace)
    if not tokens or location is None:
        return None
    root = Path(location).resolve()
    if not root.is_dir() or root == Path(root.anchor):
        return None
    tests = _test_selection(tokens, runner, root, deadline)
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
    output = str(event.get("output", ""))
    failures = (re.findall(r"(?m)^FAILED\s+([^\s]+)", output) if runner == "pytest" else
                re.findall(r"(?m)^(?:FAIL|ERROR):\s+\S+\s+\(([^)]+)\)", output))
    environment = {"version": 1, "kind": "python", "runner": runner, "files": files,
                   "tests": sorted(set(tests)), "original_failed_tests": sorted(set(failures)),
                   "captured_at": datetime.now(UTC).isoformat(), "source_workspace": str(root),
                   "source_hashes": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()},
                   "source_call_id": event.get("call_id"), "baseline_exit_code": event.get("exit_code")}
    return environment if valid_environment(environment) else None
