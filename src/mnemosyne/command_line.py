"""Cross-platform parsing for configured external command adapters."""

from __future__ import annotations

import os
import shlex


def split_command(command: str) -> list[str]:
    """Split a configured command using the host platform's quoting rules."""
    parts = shlex.split(command, posix=os.name != "nt")
    if os.name != "nt":
        return parts
    return [
        part[1:-1]
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"}
        else part
        for part in parts
    ]
