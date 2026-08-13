from __future__ import annotations

import subprocess

from mnemosyne.command_line import _split_windows_command_line


def test_windows_command_line_parser_round_trips_python_quoting() -> None:
    arguments = [
        r"C:\Program Files\Mnemosyne\provider.exe",
        "",
        "plain",
        "contains spaces",
        'embedded "quote"',
        "trailing slash \\",
        r"slashes\\\before quote\"end",
    ]

    assert _split_windows_command_line(subprocess.list2cmdline(arguments)) == arguments


def test_windows_command_line_parser_handles_empty_and_adjacent_quotes() -> None:
    assert _split_windows_command_line(r'provider.exe "" "a""b"') == [
        "provider.exe",
        "",
        'a"b',
    ]
