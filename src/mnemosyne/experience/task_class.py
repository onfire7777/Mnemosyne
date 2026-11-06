"""Stable task identities without presenting lexical hashes as semantic clustering."""

import unicodedata

from .receipts import digest

METHOD = "explicit-or-full-request-lexical-v3"


def classify(query: str, tools: list[str], task_type: str | None = None) -> str:
    """Group formatting-equivalent requests or honor an explicit shared class.

    Automatic matching normalizes Unicode and trims outer whitespace. Case,
    internal whitespace, words, numbers and punctuation retain their identity. Reusing a
    class across semantic paraphrases requires a caller-supplied ``task_type``.
    The versioned namespace keeps new requests separate from persisted classes
    made by the former two-word hash, whose members may be unrelated.
    """
    if task_type:
        return str(task_type)
    request = unicodedata.normalize("NFC", query).strip()
    return "lexical:v3:" + digest([request, sorted(set(tools))])[:32]
