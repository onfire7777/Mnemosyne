"""Media extraction adapters for externalized multimodal evidence."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from mnemosyne.command_line import split_command

from mnemosyne.media_limits import DEFAULT_MAX_INGEST_BYTES, enforce_byte_limit, validate_byte_limit


MEDIA_EXTRACT_JOB = "media_extract"
DERIVED_TEXT_FIELDS = (
    "derived_text",
    "ocr_text",
    "transcript",
    "caption",
    "alt_text",
    "description",
)


@dataclass(slots=True)
class MediaExtractionResult:
    text: str
    sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MediaTextExtractor(Protocol):
    def extract(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, Any],
    ) -> MediaExtractionResult:
        raise NotImplementedError


class MetadataMediaTextExtractor:
    """Cheap extractor that indexes text already provided by a trusted caller."""

    def extract(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, Any],
    ) -> MediaExtractionResult:
        text, sources = extract_derived_text(metadata)
        return MediaExtractionResult(text=text, sources=sources, metadata={"extractor": "metadata"})


class CommandMediaTextExtractor:
    """Run an operator-configured local media extractor without invoking a shell."""

    def __init__(
        self,
        command: str | list[str],
        timeout_seconds: float = 30.0,
        max_media_bytes: int = DEFAULT_MAX_INGEST_BYTES,
    ):
        self.command = split_command(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("media extractor command must not be empty")
        self.timeout_seconds = timeout_seconds
        self.max_media_bytes = validate_byte_limit(max_media_bytes, name="max_media_bytes")

    def extract(
        self,
        payload: bytes,
        *,
        media_type: str,
        modality: str,
        metadata: dict[str, Any],
    ) -> MediaExtractionResult:
        enforce_byte_limit(payload, limit=self.max_media_bytes, label="media extraction payload")
        suffix = _suffix_for_media_type(media_type)
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(payload)
            tmp.flush()
            completed = subprocess.run(
                [*self.command, tmp.name],
                check=True,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        output = completed.stdout.strip()
        if not output:
            return MediaExtractionResult(text="", sources=[], metadata={"extractor": "command"})
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return MediaExtractionResult(
                text=output,
                sources=["external_command"],
                metadata={"extractor": "command", "media_type": media_type, "modality": modality},
            )
        return _result_from_json(parsed, media_type=media_type, modality=modality)


def extract_derived_text(metadata: dict[str, Any]) -> tuple[str, list[str]]:
    parts: list[str] = []
    sources: list[str] = []
    for key in DERIVED_TEXT_FIELDS:
        value = metadata.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                parts.append(text)
                sources.append(key)
        elif isinstance(value, list):
            list_parts = [
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            ]
            if list_parts:
                parts.extend(list_parts)
                sources.append(key)
    return "\n".join(parts), sources


def _result_from_json(parsed: Any, *, media_type: str, modality: str) -> MediaExtractionResult:
    if isinstance(parsed, str):
        return MediaExtractionResult(
            text=parsed.strip(),
            sources=["external_command"],
            metadata={"extractor": "command", "media_type": media_type, "modality": modality},
        )
    if not isinstance(parsed, dict):
        raise ValueError("media extractor JSON output must be an object, string, or plain text")
    text = str(parsed.get("text", "")).strip()
    sources = parsed.get("sources", ["external_command"])
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
        raise ValueError("media extractor JSON field 'sources' must be a string or string list")
    metadata = parsed.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("media extractor JSON field 'metadata' must be an object")
    return MediaExtractionResult(
        text=text,
        sources=[item for item in sources if item],
        metadata={"extractor": "command", "media_type": media_type, "modality": modality, **metadata},
    )


def _suffix_for_media_type(media_type: str) -> str:
    subtype = media_type.split("/", 1)[1] if "/" in media_type else ""
    subtype = subtype.split(";", 1)[0].strip().lower()
    if subtype and all(ch.isalnum() or ch in {"-", "."} for ch in subtype):
        return f".{subtype}"
    return ".bin"
