"""Cross-platform parsing for configured external command adapters."""

from __future__ import annotations

import os
import shlex


def _split_windows_command_line(command: str) -> list[str]:
    """Parse a command line using the Windows C runtime quoting rules."""
    arguments: list[str] = []
    cursor = 0
    length = len(command)
    while cursor < length:
        while cursor < length and command[cursor] in " \t":
            cursor += 1
        if cursor == length:
            break

        argument: list[str] = []
        in_quotes = False
        while cursor < length:
            backslashes = 0
            while cursor < length and command[cursor] == "\\":
                backslashes += 1
                cursor += 1

            if cursor < length and command[cursor] == '"':
                argument.extend("\\" * (backslashes // 2))
                if backslashes % 2:
                    argument.append('"')
                    cursor += 1
                else:
                    cursor += 1
                    if in_quotes and cursor < length and command[cursor] == '"':
                        argument.append('"')
                        cursor += 1
                    else:
                        in_quotes = not in_quotes
                continue

            argument.extend("\\" * backslashes)
            if cursor == length or (not in_quotes and command[cursor] in " \t"):
                break
            argument.append(command[cursor])
            cursor += 1

        arguments.append("".join(argument))
    return arguments


def split_command(command: str) -> list[str]:
    """Split a configured command using the host platform's quoting rules."""
    if os.name == "nt":
        return _split_windows_command_line(command)
    return shlex.split(command)
