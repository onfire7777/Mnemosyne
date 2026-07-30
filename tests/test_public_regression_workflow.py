from __future__ import annotations

import re
from pathlib import Path


WORKFLOW = Path(".github/workflows/public-regression.yml")
ACTION_SHA = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_TESTS = (
    "tests/test_public_longmemeval.py",
    "tests/test_public_hipporag.py",
    "tests/test_public_memoryagentbench.py",
    "tests/test_public_beam.py",
)


def _lines() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "\t" not in text
    assert "${{" not in text
    return text.splitlines()


def _top_level_blocks(lines: list[str]) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        match = re.fullmatch(r"([a-z][a-z0-9_-]*):(?: .*)?", line)
        if match:
            current = match.group(1)
            assert current not in blocks, f"duplicate top-level key: {current}"
            blocks[current] = [line]
        elif current is not None:
            blocks[current].append(line)
    return blocks


def _mapping_keys(block: list[str], indent: int) -> list[str]:
    prefix = " " * indent
    keys: list[str] = []
    for line in block:
        if not line.startswith(prefix) or line.startswith(prefix + " "):
            continue
        match = re.fullmatch(rf"{prefix}([a-z][a-z0-9_-]*):(?: .*)?", line)
        if match:
            keys.append(match.group(1))
    assert len(keys) == len(set(keys)), f"duplicate key at indent {indent}: {keys}"
    return keys


def _single_run_command(lines: list[str]) -> list[str]:
    run_indexes = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"\s+run: [>|]-?", line)
    ]
    assert len(run_indexes) == 1
    start = run_indexes[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    command: list[str] = []
    for line in lines[start + 1 :]:
        content_indent = len(line) - len(line.lstrip())
        if line.strip() and content_indent <= indent:
            break
        if line.strip():
            command.append(line.strip())
    return command


def test_workflow_is_a_bounded_development_only_regression() -> None:
    """Catch privilege, trigger, provider, and benchmark-scope expansion."""
    lines = _lines()
    blocks = _top_level_blocks(lines)

    assert set(blocks) == {
        "name",
        "on",
        "permissions",
        "concurrency",
        "jobs",
    }
    assert _mapping_keys(blocks["on"], 2) == ["schedule", "workflow_dispatch"]
    assert sum(line.strip().startswith("- cron:") for line in blocks["on"]) == 1
    cron_line = next(
        line.strip() for line in blocks["on"] if line.strip().startswith("- cron:")
    )
    cron = cron_line.removeprefix("- cron:").strip().strip("\"'")
    fields = cron.split()
    assert len(fields) == 5
    assert fields[2:] == ["*", "*", "1"]
    assert all(field.isdigit() for field in fields[:2])
    assert 0 <= int(fields[0]) <= 59
    assert 0 <= int(fields[1]) <= 23
    assert "workflow_dispatch:" in (line.strip() for line in blocks["on"])
    assert "inputs:" not in (line.strip() for line in blocks["on"])

    assert blocks["permissions"] == ["permissions:", "  contents: read", ""]
    assert _mapping_keys(blocks["jobs"], 2) == ["public-regression"]
    workflow = "\n".join(lines)
    assert "runs-on: ubuntu-latest" in workflow
    assert re.search(r"(?m)^    timeout-minutes: (?:[1-9]|1[0-9]|20)$", workflow)
    assert "if: github.event_name == 'schedule' || github.ref == 'refs/heads/main'" in workflow
    concurrency = [line.strip() for line in blocks["concurrency"]]
    assert "group: public-regression" in concurrency
    assert "cancel-in-progress: false" in concurrency

    forbidden = re.compile(
        r"(?i)"
        r"\b(push|pull_request|matrix|services?|cache|upload-artifact|secrets?|"
        r"curl|wget|download|provider|openai|anthropic|submit|official|frozen|"
        r"held-out|heldout|private|evidence|receipt|leaderboard|publish)\b"
    )
    matches = sorted(set(forbidden.findall(workflow)))
    assert matches == []
    assert "permissions: write" not in workflow
    assert "contents: write" not in workflow


def test_workflow_uses_immutable_locked_repo_setup() -> None:
    """Catch mutable actions or dependency/setup drift from canonical CI."""
    lines = _lines()
    workflow = "\n".join(lines)
    uses = [
        line.strip().removeprefix("- uses: ")
        for line in lines
        if line.strip().startswith("- uses: ")
    ]
    assert len(uses) == 2
    assert [item.split("@", 1)[0] for item in uses] == [
        "actions/checkout",
        "actions/setup-python",
    ]
    assert all(
        "@" in item and ACTION_SHA.fullmatch(item.split("@", 1)[1])
        for item in uses
    )
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in uses
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in uses
    assert "python-version: \"3.12\"" in workflow
    assert workflow.count("python -m pip install pip==26.1.2 uv==0.11.16") == 1
    assert workflow.count("uv sync --locked --group dev") == 1


def test_workflow_runs_only_the_fixed_public_contract_allowlist() -> None:
    """Catch dynamic discovery or any change to the development-test allowlist."""
    command = _single_run_command(_lines())
    assert command == [
        "uv run --locked python -m pytest \\",
        "tests/test_public_longmemeval.py \\",
        "tests/test_public_hipporag.py \\",
        "tests/test_public_memoryagentbench.py \\",
        "tests/test_public_beam.py \\",
        "-q",
    ]
    joined = "\n".join(command)
    assert all(joined.count(test) == 1 for test in EXPECTED_TESTS)
    assert "*" not in joined
    remainder = joined
    for test in EXPECTED_TESTS:
        remainder = remainder.replace(test, "")
    assert "tests/" not in remainder
