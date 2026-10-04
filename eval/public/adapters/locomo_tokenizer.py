"""Offline, vocabulary-verified tokenizer for the pinned LoCoMo GPT path."""
from __future__ import annotations

import base64
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .locomo import LoCoMoError

VOCABULARY_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
VOCABULARY_BYTES = 1681126
TIKTOKEN_VERSION = "0.5.2"


def load_verified_encoding(path: str | Path):
    """Load exact cl100k_base bytes without cache access or network fallback.

    Pattern and special-token IDs match tiktoken 0.5.2 openai_public.cl100k_base.
    Calling Encoding.encode retains upstream's special-token rejection behavior.
    This only supports that encoding, not arbitrary model-to-encoding mappings.
    """
    with Path(path).open("rb") as source:
        data = source.read(VOCABULARY_BYTES + 1)
    if len(data) != VOCABULARY_BYTES or sha256(data).hexdigest() != VOCABULARY_SHA256:
        raise LoCoMoError("cl100k_base vocabulary size or SHA-256 mismatch")
    try:
        if version("tiktoken") != TIKTOKEN_VERSION:
            raise LoCoMoError("LoCoMo tokenizer requires tiktoken 0.5.2")
    except PackageNotFoundError as exc:
        raise LoCoMoError("LoCoMo tokenizer requires tiktoken 0.5.2") from exc
    import tiktoken

    ranks = {base64.b64decode(token, validate=True): int(rank)
             for token, rank in (line.split() for line in data.splitlines() if line)}
    return tiktoken.Encoding(
        name="cl100k_base",
        pat_str=r"""(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+""",
        mergeable_ranks=ranks,
        special_tokens={"<|endoftext|>": 100257, "<|fim_prefix|>": 100258,
                        "<|fim_middle|>": 100259, "<|fim_suffix|>": 100260,
                        "<|endofprompt|>": 100276},
    )
