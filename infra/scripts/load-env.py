#!/usr/bin/env python3
from __future__ import annotations

import re
import shlex
import stat
import sys
from pathlib import Path


KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
UNSAFE_VALUE_MARKERS = ("$(", "`", "\x00", "\n", "\r")


def _deny(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(65)


def _parse_assignment(line: str, *, line_number: int) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        parts = shlex.split(stripped, comments=False, posix=True)
    except ValueError as exc:
        _deny(f"invalid dotenv syntax on line {line_number}: {exc}")
    if len(parts) == 2 and parts[0] == "export":
        assignment = parts[1]
    elif len(parts) == 1:
        assignment = parts[0]
        if assignment.startswith("export "):
            assignment = assignment[len("export ") :]
    else:
        _deny(f"unsupported dotenv syntax on line {line_number}")
    key, separator, value = assignment.partition("=")
    if separator != "=" or not key:
        _deny(f"missing KEY=value assignment on line {line_number}")
    if not KEY_RE.fullmatch(key):
        _deny(f"invalid dotenv key {key!r} on line {line_number}")
    if any(marker in value for marker in UNSAFE_VALUE_MARKERS):
        _deny(f"unsafe dotenv value for {key} on line {line_number}")
    return key, value


def main(argv: list[str]) -> int:
    args = argv[1:]
    allow_missing = False
    if args and args[0] == "--allow-missing":
        allow_missing = True
        args = args[1:]
    if len(args) < 2:
        print(
            "Usage: load-env.py [--allow-missing] ENV_FILE REQUIRED_KEY [REQUIRED_KEY ...]",
            file=sys.stderr,
        )
        return 64
    env_path = Path(args[0]).expanduser()
    required = list(dict.fromkeys(args[1:]))
    allowed = set(required)
    if any(not KEY_RE.fullmatch(key) for key in required):
        _deny("required keys must be uppercase environment variable names")
    if env_path.is_symlink():
        _deny(f"refusing to load symlinked env file: {env_path}")
    try:
        file_stat = env_path.stat()
    except OSError as exc:
        _deny(f"cannot stat env file {env_path}: {exc}")
    if not stat.S_ISREG(file_stat.st_mode):
        _deny(f"env file is not a regular file: {env_path}")
    mode = stat.S_IMODE(file_stat.st_mode)
    if mode & 0o077:
        _deny(f"env file must not be group/world accessible: {env_path}")
    try:
        text = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _deny(f"cannot read env file {env_path}: {exc}")

    values: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        parsed = _parse_assignment(line, line_number=line_number)
        if parsed is None:
            continue
        key, value = parsed
        if key not in allowed:
            _deny(f"unexpected dotenv key {key!r} on line {line_number}")
        values[key] = value

    missing = [key for key in required if key not in values]
    if missing and not allow_missing:
        _deny("env file is missing required keys: " + ", ".join(missing))
    for key in required:
        if key in values:
            print(f"{key}={values[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
