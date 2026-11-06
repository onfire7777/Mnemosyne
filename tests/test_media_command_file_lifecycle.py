"""Real subprocess access and cleanup for command-backed media embeddings."""

import sys
from pathlib import Path

import pytest

from mnemosyne.retrieval import CommandMediaEmbeddingProvider


@pytest.mark.parametrize("mode", ["success", "failure", "invalid_json", "timeout"])
def test_media_child_can_read_payload_and_temporary_file_is_removed(tmp_path, mode):
    receipt = tmp_path / "path.txt"
    script = (
        "import pathlib,sys,time; "
        "payload=pathlib.Path(sys.argv[2]); "
        "pathlib.Path(sys.argv[1]).write_text(str(payload)); "
        "assert payload.read_bytes()==b'private-media'; "
        + {
            "success": "print('{\"embedding\":[3,4]}')",
            "failure": "sys.exit(7)",
            "invalid_json": "print('not-json')",
            "timeout": "time.sleep(30)",
        }[mode]
    )
    provider = CommandMediaEmbeddingProvider(
        [sys.executable, "-c", script, str(receipt)], dims=2, timeout_seconds=2,
    )
    if mode == "success":
        assert provider.embed_media(b"private-media", media_type="image/png", modality="image") == [0.6, 0.8]
    else:
        expected = {"failure": "command failed", "invalid_json": "valid JSON", "timeout": "timed out"}[mode]
        with pytest.raises(ValueError, match=expected) as error:
            provider.embed_media(b"private-media", media_type="image/png", modality="image")
        if mode == "failure":
            assert error.value.__cause__.returncode == 7
    assert receipt.exists(), "child must run before cleanup can be verified"
    assert not Path(receipt.read_text()).exists()
