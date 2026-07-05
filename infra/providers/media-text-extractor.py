#!/usr/bin/env python3
"""Command-backed media text extractor (Mnemosyne ``CommandMediaTextExtractor``).

Mnemosyne invokes this as ``<this> <tmp-media-path>`` with NO stdin and expects
JSON ``{"text": ..., "sources": [...], "metadata": {...}}`` on stdout. It pulls
GENUINELY-embedded text out of the media container (PNG tEXt/iTXt, EXIF
ImageDescription, RIFF/WAV INFO, ID3v2, MP4 ilst, WebVTT/SRT) via the stdlib-only
``mnemosyne.media_embedded_text`` extractor. Empty text when the file has none.
"""

from __future__ import annotations

import json
import sys

from mnemosyne.media_embedded_text import extract_embedded_text


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"error": "missing media path argument"}), file=sys.stderr)
        return 2
    path = argv[-1]
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        print(json.dumps({"error": f"could not read media: {exc}"}), file=sys.stderr)
        return 1
    text, sources = extract_embedded_text(data)
    print(json.dumps({"text": text, "sources": sources, "metadata": {"extractor": "embedded-media-text"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
