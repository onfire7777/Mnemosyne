"""Extract genuinely-embedded text from media container bytes (stdlib-only).

Reads text that really lives inside a media file's own metadata/structure —
PNG textual chunks (``tEXt``/``zTXt``/``iTXt``), JPEG EXIF ``ImageDescription``,
RIFF/WAV ``INFO`` tags, ID3v2 text frames, MP4/iTunes ``ilst`` atoms, and
WebVTT/SRT cue text — with no third-party dependency. Returns ``("", [])`` when
a file carries no embedded text, so an asset that genuinely has none produces no
fabricated derived text.
"""

from __future__ import annotations

import struct
import zlib

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MP4_CONTAINERS = {b"moov", b"udta", b"trak", b"mdia", b"minf", b"stbl", b"ilst"}


def extract_embedded_text(data: bytes, *, media_type: str = "") -> tuple[str, list[str]]:
    """Return ``(text, sources)`` for text embedded in ``data``.

    ``sources`` labels which container features contributed (e.g. ``png_text``,
    ``riff_info``, ``mp4_ilst``). Both are empty when nothing is embedded.
    """
    parts: list[str] = []
    sources: list[str] = []

    def add(source: str, text: str) -> None:
        cleaned = " ".join(text.split()).strip()
        if cleaned:
            parts.append(cleaned)
            if source not in sources:
                sources.append(source)

    if data[:8] == _PNG_MAGIC:
        for text in _png_text_chunks(data):
            add("png_text", text)
    if data[:3] == b"\xff\xd8\xff":
        for text in _jpeg_exif_description(data):
            add("exif_image_description", text)
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        for text in _riff_info(data):
            add("riff_info", text)
    if data[:3] == b"ID3":
        for text in _id3v2_text(data):
            add("id3", text)
    if len(data) >= 12 and data[4:8] == b"ftyp":
        for text in _mp4_ilst_text(data):
            add("mp4_ilst", text)
    if _looks_like_subtitles(data, media_type):
        for text in _subtitle_cues(data):
            add("subtitle", text)

    return "\n".join(parts), sources


# --- PNG textual chunks ------------------------------------------------------
def _png_text_chunks(data: bytes) -> list[str]:
    out: list[str] = []
    pos = 8
    n = len(data)
    while pos + 8 <= n:
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        start = pos + 8
        end = start + length
        if end > n:
            break
        chunk = data[start:end]
        if ctype == b"tEXt":
            nul = chunk.find(b"\x00")
            if nul != -1:
                out.append(chunk[nul + 1 :].decode("latin-1", "replace"))
        elif ctype == b"zTXt":
            nul = chunk.find(b"\x00")
            if nul != -1 and len(chunk) > nul + 2:
                try:
                    out.append(zlib.decompress(chunk[nul + 2 :]).decode("latin-1", "replace"))
                except zlib.error:
                    pass
        elif ctype == b"iTXt":
            out.append(_png_itxt(chunk))
        elif ctype == b"IEND":
            break
        pos = end + 4  # skip 4-byte CRC
    return [text for text in out if text]


def _png_itxt(chunk: bytes) -> str:
    try:
        i = chunk.find(b"\x00")
        if i == -1:
            return ""
        comp_flag = chunk[i + 1]
        rest = chunk[i + 3 :]  # skip comp flag + comp method
        rest = rest[rest.find(b"\x00") + 1 :]  # skip language tag
        rest = rest[rest.find(b"\x00") + 1 :]  # skip translated keyword
        if comp_flag == 1:
            rest = zlib.decompress(rest)
        return rest.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - malformed chunk yields no text.
        return ""


# --- RIFF / WAV INFO tags ----------------------------------------------------
def _riff_info(data: bytes) -> list[str]:
    out: list[str] = []
    pos = 12
    n = len(data)
    while pos + 8 <= n:
        size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        cid = data[pos : pos + 4]
        if cid == b"LIST" and body[:4] == b"INFO":
            out.extend(_riff_info_entries(body[4:]))
        pos += 8 + size + (size & 1)
    return out


def _riff_info_entries(body: bytes) -> list[str]:
    out: list[str] = []
    pos = 0
    n = len(body)
    while pos + 8 <= n:
        size = struct.unpack("<I", body[pos + 4 : pos + 8])[0]
        value = body[pos + 8 : pos + 8 + size]
        text = value.split(b"\x00")[0].decode("latin-1", "replace")
        if text:
            out.append(text)
        pos += 8 + size + (size & 1)
    return out


# --- ID3v2 text frames (best-effort) -----------------------------------------
def _synchsafe(raw: bytes) -> int:
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def _id3v2_text(data: bytes) -> list[str]:
    out: list[str] = []
    if len(data) < 10:
        return out
    version_major = data[3]
    size = _synchsafe(data[6:10])
    pos = 10
    end = min(10 + size, len(data))
    while pos + 10 <= end:
        fid = data[pos : pos + 4]
        if fid == b"\x00\x00\x00\x00":
            break
        raw_size = data[pos + 4 : pos + 8]
        fsize = _synchsafe(raw_size) if version_major >= 4 else struct.unpack(">I", raw_size)[0]
        fdata = data[pos + 10 : pos + 10 + fsize]
        if fid[:1] == b"T" and fdata:
            out.append(_decode_id3_text(fdata[0], fdata[1:]))
        elif fid == b"COMM" and len(fdata) > 4:
            rest = fdata[4:]
            nul = rest.find(b"\x00")
            out.append(_decode_id3_text(fdata[0], rest[nul + 1 :]))
        pos += 10 + fsize
    return [text for text in out if text]


def _decode_id3_text(encoding: int, raw: bytes) -> str:
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(encoding, "latin-1")
    try:
        return raw.split(b"\x00")[0].decode(codec, "replace") if codec == "latin-1" else raw.decode(codec, "replace").split("\x00")[0]
    except Exception:  # noqa: BLE001 - undecodable frame yields no text.
        return ""


# --- MP4 / iTunes ilst atoms -------------------------------------------------
def _mp4_ilst_text(data: bytes) -> list[str]:
    out: list[str] = []
    _mp4_walk(data, 0, len(data), out)
    return out


def _mp4_walk(data: bytes, start: int, end: int, out: list[str]) -> None:
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        btype = data[pos + 4 : pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                break
            size = struct.unpack(">Q", data[pos + 8 : pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        box_end = pos + size
        if size < header or box_end > end:
            break
        body_start = pos + header
        if btype in _MP4_CONTAINERS:
            _mp4_walk(data, body_start, box_end, out)
        elif btype == b"meta":
            _mp4_walk(data, body_start + 4, box_end, out)  # FullBox version/flags
        elif btype[:1] == b"\xa9" or btype in {b"name", b"titl", b"desc", b"cprt"}:
            text = _mp4_data_text(data, body_start, box_end)
            if text:
                out.append(text)
        pos = box_end


def _mp4_data_text(data: bytes, start: int, end: int) -> str:
    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos : pos + 4])[0]
        btype = data[pos + 4 : pos + 8]
        if size < 8 or pos + size > end:
            break
        if btype == b"data":
            payload = data[pos + 8 : pos + size]
            return payload[8:].decode("utf-8", "replace") if len(payload) > 8 else ""
        pos += size
    return ""


# --- JPEG EXIF ImageDescription (best-effort) --------------------------------
def _jpeg_exif_description(data: bytes) -> list[str]:
    marker = data.find(b"Exif\x00\x00")
    if marker == -1:
        return []
    tiff = data[marker + 6 :]
    if len(tiff) < 8:
        return []
    endian = "<" if tiff[:2] == b"II" else ">"
    try:
        ifd_offset = struct.unpack(endian + "I", tiff[4:8])[0]
        count = struct.unpack(endian + "H", tiff[ifd_offset : ifd_offset + 2])[0]
        for i in range(count):
            entry = ifd_offset + 2 + i * 12
            tag = struct.unpack(endian + "H", tiff[entry : entry + 2])[0]
            if tag == 0x010E:  # ImageDescription (ASCII)
                length = struct.unpack(endian + "I", tiff[entry + 4 : entry + 8])[0]
                value_off = struct.unpack(endian + "I", tiff[entry + 8 : entry + 12])[0]
                raw = tiff[value_off : value_off + length] if length > 4 else tiff[entry + 8 : entry + 8 + length]
                return [raw.split(b"\x00")[0].decode("latin-1", "replace")]
    except Exception:  # noqa: BLE001 - malformed EXIF yields no text.
        return []
    return []


# --- WebVTT / SRT cue text ---------------------------------------------------
def _looks_like_subtitles(data: bytes, media_type: str) -> bool:
    if data[:6] == b"WEBVTT":
        return True
    subtype = media_type.lower()
    return "vtt" in subtype or "srt" in subtype or "subrip" in subtype


def _subtitle_cues(data: bytes) -> list[str]:
    out: list[str] = []
    try:
        text = data.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return out
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "WEBVTT" or stripped.isdigit() or "-->" in stripped:
            continue
        out.append(stripped)
    return out
