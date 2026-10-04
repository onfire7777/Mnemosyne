"""Positive offline-tokenizer checks; CI supplies a hash-verified vocabulary."""
from hashlib import sha256
import os
from pathlib import Path
import random

import pytest

from eval.public.adapters.locomo import LoCoMoError, prepare_nonrag_request
from eval.public.adapters.locomo_tokenizer import (
    VOCABULARY_BYTES, VOCABULARY_SHA256, load_verified_encoding,
)


@pytest.fixture
def vocabulary():
    path = os.environ.get("MNEMOSYNE_TEST_TOKENIZER_VOCAB")
    if not path:
        pytest.skip("set MNEMOSYNE_TEST_TOKENIZER_VOCAB to the pinned vocabulary")
    data = Path(path).read_bytes()
    assert len(data) == VOCABULARY_BYTES
    assert sha256(data).hexdigest() == VOCABULARY_SHA256
    return Path(path)


def test_verified_tokenizer_matches_upstream_offline(vocabulary, monkeypatch):
    import tiktoken
    import tiktoken.load
    from tiktoken_ext.openai_public import cl100k_base

    def local_only(url):
        assert url == "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
        return vocabulary.read_bytes()

    # Supply exact verified bytes to the original constructor without its cache
    # or HTTP path. Its pattern/special tokens stay independent of our loader.
    monkeypatch.setattr(tiktoken.load, "read_file_cached", local_only)
    reference = tiktoken.Encoding(**cl100k_base())

    def forbidden(*args, **kwargs):
        raise AssertionError("verified loader must not access upstream file/cache loaders")

    monkeypatch.setattr(tiktoken.load, "read_file_cached", forbidden)
    monkeypatch.setattr(tiktoken.load, "read_file", forbidden)
    actual = load_verified_encoding(vocabulary)
    rng = random.Random(42)
    texts = ["", "hello", "Ω café 中文 😀", "\n\r\n\t", "Don't stop 123456789."]
    texts += ["".join(rng.choice("abcXYZ 0123\n\tΩ—😀é中") for _ in range(rng.randrange(200)))
              for _ in range(500)]
    for text in texts:
        assert actual.encode(text) == reference.encode(text)
    for token in ("<|endoftext|>", "<|fim_prefix|>", "<|fim_middle|>",
                  "<|fim_suffix|>", "<|endofprompt|>"):
        for encoder in (actual, reference):
            with pytest.raises(ValueError):
                encoder.encode(token)


def test_verified_tokenizer_composes_a_replayable_request(vocabulary):
    encoding = load_verified_encoding(vocabulary)
    sample = {"sample_id": "synthetic", "conversation": {
        "session_1_date_time": "Synthetic date", "session_1": [
            {"speaker": "A", "text": "A synthetic violet kite.", "dia_id": "D1:1"},
            {"speaker": "B", "text": "I heard that.", "dia_id": "D1:2"}]},
        "qa": [{"question": "What color?", "answer": "violet", "category": 4, "evidence": ["D1:1"]}]}
    kwargs = dict(speaker_order=["A", "B"], token_count=lambda text: len(encoding.encode(text)),
                  max_length=16000)
    first = prepare_nonrag_request(sample, 0, **kwargs)
    assert first == prepare_nonrag_request(sample, 0, **kwargs)
    assert not first["context_assembly"]["truncated"]
    assert len(first["context_assembly"]["included_record_ids"]) == 2
    assert not first["publication_authorized"]


def test_verified_vocabulary_still_requires_pinned_runtime(vocabulary, monkeypatch):
    from eval.public.adapters import locomo_tokenizer
    monkeypatch.setattr(locomo_tokenizer, "version", lambda _: "0.0.0")
    with pytest.raises(LoCoMoError, match="tiktoken 0.5.2"):
        load_verified_encoding(vocabulary)
