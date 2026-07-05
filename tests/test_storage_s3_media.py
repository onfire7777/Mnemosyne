"""Tests for the additive S3/SeaweedFS object backend + embedded-media-text.

Covers: AWS SigV4 signing-key derivation against the published AWS test vector,
the four byte-backend seams wired through an in-memory fake S3 client (both the
plain and AES-GCM encrypted stores, including crypto-shred), and genuinely-
embedded text extraction from crafted PNG/WAV/MP4 containers.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from mnemosyne.ids import bytes_cid
from mnemosyne.media_embedded_text import extract_embedded_text
from mnemosyne.storage import (
    EncryptedS3ObjectStore,
    JsonKeyManager,
    S3ObjectNotFoundError,
    S3ObjectStore,
    S3ObjectStoreConfig,
    SeaweedS3Client,
    _load_seaweed_credentials,
    _s3_signing_key,
    s3_config_from_env,
)


# --- SigV4 --------------------------------------------------------------------
def test_sigv4_signing_key_matches_aws_reference_vector() -> None:
    # Published AWS "derive the signing key" reference value.
    key = _s3_signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20150830", "us-east-1", "iam")
    assert key.hex() == "c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9"


def test_seaweed_client_rejects_non_http_endpoint() -> None:
    with pytest.raises(ValueError):
        SeaweedS3Client(S3ObjectStoreConfig(endpoint="ftp://x", bucket="b", access_key="a", secret_key="s"))


# --- config loading -----------------------------------------------------------
def test_s3_config_from_env_reads_credentials_file(tmp_path) -> None:
    creds = tmp_path / "seaweed-s3.json"
    creds.write_text(
        '{"identities":[{"name":"m","credentials":[{"accessKey":"AK","secretKey":"SK"}]}]}',
        encoding="utf-8",
    )
    cfg = s3_config_from_env(
        {
            "MNEMOSYNE_S3_ENDPOINT": "https://s3.mnemo.local",
            "MNEMOSYNE_S3_BUCKET": "media",
            "MNEMOSYNE_S3_CREDENTIALS_FILE": str(creds),
        }
    )
    assert (cfg.access_key, cfg.secret_key, cfg.region, cfg.bucket) == ("AK", "SK", "us-east-1", "media")


def test_load_seaweed_credentials_flat_shape(tmp_path) -> None:
    creds = tmp_path / "flat.json"
    creds.write_text('{"accessKey":"A","secretKey":"S"}', encoding="utf-8")
    assert _load_seaweed_credentials(creds) == ("A", "S")


def test_s3_config_requires_bucket() -> None:
    with pytest.raises(ValueError):
        s3_config_from_env({"MNEMOSYNE_S3_ACCESS_KEY": "a", "MNEMOSYNE_S3_SECRET_KEY": "s"})


# --- byte-backend seams via an in-memory fake S3 client -----------------------
class _FakeS3:
    """In-memory stand-in exposing the four verbs the stores call."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, key: str, data: bytes) -> None:
        self.objects[key] = bytes(data)

    def get_object(self, key: str) -> bytes:
        if key not in self.objects:
            raise S3ObjectNotFoundError(key)
        return self.objects[key]

    def head_object(self, key: str) -> bool:
        return key in self.objects

    def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)


def test_s3_object_store_roundtrip_and_key_layout() -> None:
    fake = _FakeS3()
    store = S3ObjectStore(fake)
    record = store.put_bytes(b"hello media", tenant_id="t1", kind="image", media_type="image/png")
    assert record.uri.startswith("s3-object://sha256/")
    cid = record.cid
    assert f"{cid[:2]}/{cid}" in fake.objects  # sharded key layout
    assert store.exists(record.uri) is True
    assert store.read_bytes(record.uri) == b"hello media"
    store._delete_object_bytes(cid)
    assert store.exists(record.uri) is False


def test_encrypted_s3_store_roundtrip_and_crypto_shred(tmp_path) -> None:
    fake = _FakeS3()
    keys = JsonKeyManager(tmp_path / "keys.json")
    store = EncryptedS3ObjectStore(fake, keys)
    payload = b"secret camera frame bytes"
    record = store.put_bytes(payload, tenant_id="t1", kind="image", media_type="image/png")
    assert record.uri.startswith("s3-object+aesgcm://sha256/")
    # The stored bytes are a ciphertext envelope, not the plaintext.
    stored = next(iter(fake.objects.values()))
    assert payload not in stored
    assert store.read_bytes(record.uri) == payload
    assert store.exists(record.uri) is True
    result = store.shred(record.uri, tenant_id="t1")
    assert result["crypto_shredded"] is True
    with pytest.raises(KeyError):
        store.read_bytes(record.uri)


def test_encrypted_s3_store_reports_missing_object(tmp_path) -> None:
    store = EncryptedS3ObjectStore(_FakeS3(), JsonKeyManager(tmp_path / "keys.json"))
    missing = store.shred("s3-object+aesgcm://sha256/" + "a" * 64)
    assert missing["crypto_shredded"] is False
    assert missing["reason"] == "object_not_found"


# --- embedded media text ------------------------------------------------------
def _png_with_text(keyword: str, text: str) -> bytes:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", keyword.encode("latin-1") + b"\x00" + text.encode("latin-1"))
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _wav_with_comment(comment: str) -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8)
    data_chunk = b"data" + struct.pack("<I", 2) + b"\x00\x00"
    value = comment.encode("latin-1") + b"\x00"
    if len(value) % 2:
        value += b"\x00"
    info = b"INFO" + b"ICMT" + struct.pack("<I", len(comment) + 1) + comment.encode("latin-1") + b"\x00"
    if len(info) % 2:
        info += b"\x00"
    list_chunk = b"LIST" + struct.pack("<I", len(info)) + info
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + data_chunk + list_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _mp4_with_title(title: str) -> bytes:
    def box(btype: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload) + 8) + btype + payload

    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 0) + b"isomiso2mp41")
    data = box(b"data", struct.pack(">I", 1) + struct.pack(">I", 0) + title.encode("utf-8"))
    nam = box(b"\xa9nam", data)
    ilst = box(b"ilst", nam)
    hdlr = box(b"hdlr", struct.pack(">I", 0) + b"\x00\x00\x00\x00" + b"mdir" + b"appl" + b"\x00" * 9)
    meta = box(b"meta", struct.pack(">I", 0) + hdlr + ilst)
    udta = box(b"udta", meta)
    moov = box(b"moov", udta)
    return ftyp + moov


def test_extract_png_text() -> None:
    text, sources = extract_embedded_text(_png_with_text("Description", "a red bicycle by the river"))
    assert "a red bicycle by the river" in text
    assert "png_text" in sources


def test_extract_wav_info() -> None:
    text, sources = extract_embedded_text(_wav_with_comment("field recording of morning birdsong"))
    assert "field recording of morning birdsong" in text
    assert "riff_info" in sources


def test_extract_mp4_ilst() -> None:
    text, sources = extract_embedded_text(_mp4_with_title("timelapse of a city skyline at dusk"))
    assert "timelapse of a city skyline at dusk" in text
    assert "mp4_ilst" in sources


def test_extract_returns_empty_for_textless_media() -> None:
    text, sources = extract_embedded_text(b"\x00\x01\x02not a real media file")
    assert text == ""
    assert sources == []
