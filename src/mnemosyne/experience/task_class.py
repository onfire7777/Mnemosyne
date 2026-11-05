"""Stable task identities without presenting lexical hashes as semantic clustering."""

import re
from .receipts import digest


def classify(query: str, tools: list[str], task_type: str | None = None) -> str:
    if task_type:
        return str(task_type)
    words = re.findall(r"[a-z]+", query.lower())
    intent = next(
        (
            word
            for word in words
            if word
            in {
                "find",
                "search",
                "write",
                "fix",
                "build",
                "explain",
                "summarize",
                "compare",
                "calculate",
            }
        ),
        "answer",
    )
    return "lexical:" + digest([intent, sorted(tools), words[:2]])[:20]
