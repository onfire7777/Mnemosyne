"""FR-20 multimodal scope checks — the INTENTIONALLY-LIMITED v1 bar.

Blueprint context (do NOT over-build):
  - FR-20 (§14, P2 "future considerations"): *Multimodal memory (image/audio)
    behind the same substrate.*
  - Non-goal **N5** (§12): *Multimodal memory in v1 — Text/code/structured
    first; images/audio behind the same interfaces later. Why: scope; the
    substrate is designed to EXTEND (P2).*

So the v1 BAR is NOT "image/audio understanding works". It is strictly:

  (1) The data model + ingest path ACCEPT image/audio (and video/binary)
      modalities as first-class enum values — without a separate code path.
  (2) ``media.py`` exposes a single, modality-agnostic extraction interface
      (``MediaTextExtractor``) and an embedding boundary
      (``MediaEmbeddingProvider``) that take the SAME ``(payload, media_type,
      modality, metadata)`` signature for every modality. "Behind the same
      interfaces" = one Protocol, not one-per-modality.
  (3) The substrate EXTENDS: when an image/audio item is ingested, it flows
      through the identical evidence ledger + media-extraction job + derived
      indexing as text — the modality is a parameter, not a fork.

Everything beyond that bar (a real OCR/ASR model, perceptual embeddings,
cross-modal retrieval quality) is correctly DEFERRED to P2 and recorded in
``REAL_DEPLOYMENT_VALIDATION``.
"""

from __future__ import annotations

import inspect
import typing
from pathlib import Path

from ._scope_harness import Check

# Public, intentionally-deferred validation surface (out of scope for v1).
REAL_DEPLOYMENT_VALIDATION: tuple[str, ...] = (
    "Real OCR/ASR/vision model: ship a CommandMediaTextExtractor wrapping a real "
    "image-caption / OCR / speech-to-text binary and measure derived-text quality "
    "(WER/CER, caption faithfulness) on a labelled image+audio corpus. v1 ships only "
    "MetadataMediaTextExtractor (indexes caller-provided derived text) + the command "
    "boundary — no model is bundled.",
    "Perceptual media embeddings: wire a real CLIP/CLAP-style MediaEmbeddingProvider "
    "and prove cross-modal recall@k on a multimodal retrieval suite. v1 only proves the "
    "boundary is honoured (Protocol + CommandMediaEmbeddingProvider), not retrieval lift.",
    "Cross-modal answer quality: extend eval/harness suites with image/audio QA cases "
    "and judge end-to-end answers, vs. v1 which only proves the modality plumbing.",
    "Large-binary externalization SLOs: object-store throughput / residency for "
    "GB-scale media payloads under load (the substrate externalizes raw bytes today, "
    "but the SLOs are unmeasured for media at scale).",
)

_SRC_MEDIA = Path(__file__).resolve().parents[3] / "src" / "mnemosyne" / "media.py"


def _check_model_accepts_image_audio_modalities() -> str | None:
    """(1) Evidence + IngestRequest model image/audio as first-class enum values."""
    from mnemosyne.models import Evidence
    from mnemosyne.ingestion import IngestRequest

    ev_hints = typing.get_type_hints(Evidence)
    modality_hint = ev_hints["modality"]
    members = set(typing.get_args(modality_hint))
    required = {"text", "image", "audio"}
    missing = required - members
    assert not missing, f"Evidence.modality enum missing {missing}; got {members}"
    # IngestRequest must carry the same modality vocabulary (the public ingest door).
    req_modality = typing.get_type_hints(IngestRequest)["modality"]
    req_members = set(typing.get_args(req_modality))
    assert required <= req_members, (
        f"IngestRequest.modality missing image/audio; got {req_members}"
    )
    # The model must be constructible with an image/audio modality without error.
    img = Evidence(
        tenant_id="t",
        user_id="u",
        actor="user",  # type: ignore[arg-type]
        source_type="seed",
        content=None,
        modality="image",
        access_policy={"tenant": "t"},
    )
    aud = Evidence(
        tenant_id="t",
        user_id="u",
        actor="user",  # type: ignore[arg-type]
        source_type="seed",
        content=None,
        modality="audio",
        access_policy={"tenant": "t"},
    )
    assert img.modality == "image" and aud.modality == "audio"
    return f"Evidence/IngestRequest modality enum = {sorted(members)}"


def _check_single_extraction_interface_is_modality_agnostic() -> str | None:
    """(2a) One MediaTextExtractor Protocol; extract() takes modality as a param.

    "Behind the same interfaces" — there must NOT be an extract_image /
    extract_audio fork. A single ``extract(payload, *, media_type, modality,
    metadata)`` is the v1 contract.
    """
    from mnemosyne import media

    proto = media.MediaTextExtractor
    sig = inspect.signature(proto.extract)
    params = list(sig.parameters)
    assert params[0] == "self"
    for required in ("payload", "media_type", "modality", "metadata"):
        assert required in params, f"MediaTextExtractor.extract missing '{required}'"
    # Guard against accidental modality forks creeping into the module surface.
    forks = [
        name
        for name in dir(media)
        if name.lower().startswith(("extract_image", "extract_audio", "extract_video"))
    ]
    assert not forks, f"per-modality extraction forks leaked into media.py: {forks}"
    return "MediaTextExtractor.extract(payload, *, media_type, modality, metadata)"


def _check_metadata_extractor_handles_image_and_audio_identically() -> str | None:
    """(2b) The default extractor processes image & audio through one code path.

    MetadataMediaTextExtractor indexes caller-supplied derived text (OCR/caption
    for image, transcript for audio) — same call, different modality arg.
    """
    from mnemosyne.media import MetadataMediaTextExtractor

    extractor = MetadataMediaTextExtractor()
    image = extractor.extract(
        b"\x89PNG...",
        media_type="image/png",
        modality="image",
        metadata={"ocr_text": "invoice total 42", "caption": "a scanned invoice"},
    )
    audio = extractor.extract(
        b"RIFF....WAVE",
        media_type="audio/wav",
        modality="audio",
        metadata={"transcript": "the meeting is on tuesday"},
    )
    assert "invoice total 42" in image.text and "scanned invoice" in image.text
    assert "tuesday" in audio.text
    # Same result type for both modalities (one interface, not two).
    assert type(image) is type(audio)
    assert "ocr_text" in image.sources and "transcript" in audio.sources
    return "image(ocr/caption) + audio(transcript) -> same MediaExtractionResult"


def _check_command_extractor_is_modality_agnostic_boundary() -> str | None:
    """(2c) The operator-extension point (CommandMediaTextExtractor) is one boundary.

    This is where a *real* OCR/ASR model gets wired in P2 — proving the
    substrate is designed to EXTEND. We drive a tiny local 'model' for both an
    image and an audio payload through the SAME command class.
    """
    import shutil
    import sys

    from mnemosyne.media import CommandMediaTextExtractor

    python = sys.executable or shutil.which("python3") or "python3"
    # A stand-in 'extractor model': echoes a JSON result regardless of modality.
    prog = (
        "import json,sys;"
        "print(json.dumps({'text':'DERIVED','sources':['external_command']}))"
    )
    extractor = CommandMediaTextExtractor([python, "-c", prog])
    img = extractor.extract(b"img-bytes", media_type="image/png", modality="image", metadata={})
    aud = extractor.extract(b"aud-bytes", media_type="audio/wav", modality="audio", metadata={})
    assert img.text == "DERIVED" and aud.text == "DERIVED"
    # The boundary tags modality+media_type into provenance for both.
    assert img.metadata.get("modality") == "image"
    assert aud.metadata.get("modality") == "audio"
    assert img.metadata.get("extractor") == "command"
    return "CommandMediaTextExtractor: one shell-free boundary for any modality"


def _check_embedding_boundary_is_single_protocol() -> str | None:
    """(2d) MediaEmbeddingProvider is a single boundary taking modality as a param."""
    from mnemosyne.retrieval import MediaEmbeddingProvider

    sig = inspect.signature(MediaEmbeddingProvider.embed_media)
    params = list(sig.parameters)
    for required in ("payload", "media_type", "modality", "metadata"):
        assert required in params, f"MediaEmbeddingProvider.embed_media missing '{required}'"
    return "MediaEmbeddingProvider.embed_media(payload, *, media_type, modality, metadata)"


def _check_substrate_extends_via_media_extract_job() -> str | None:
    """(3a) END-TO-END N5 keystone: image ingest WITHOUT caller-supplied text.

    This is the load-bearing N5 claim — "the substrate is designed to extend".
    When the caller does NOT pre-extract text, the pipeline must enqueue a real
    ``media_extract`` job (the spot where a P2 OCR/ASR model gets wired). We run
    that job with a stand-in extractor and confirm:
      - the raw image becomes first-class evidence (modality='image'),
      - a media_extract job is enqueued (extension path, not a text-only fork),
      - the derived text lands as ordinary text evidence on the SAME ledger,
        provenance-linked back to the image.
    No image MODEL is asserted — only that the one pipeline extends to media.
    """
    import tempfile

    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.ingestion import IngestionPipeline, IngestRequest
    from mnemosyne.jobs import RuntimeJobHandlers
    from mnemosyne.media import MEDIA_EXTRACT_JOB, MediaExtractionResult
    from mnemosyne.queue import InProcessQueue
    from mnemosyne.storage import LocalObjectStore

    class _StandInExtractor:
        """Stand-in for a real OCR/ASR model (v1 ships no model)."""

        def extract(self, payload, *, media_type, modality, metadata):
            return MediaExtractionResult(
                text=f"DERIVED[{modality}] PURCHASE ORDER 7781 widget",
                sources=["external_command"],
                metadata={"extractor": "scope-stand-in"},
            )

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr20-") as tmp:
        root = Path(tmp)
        engine = LocalMemoryEngine()
        object_store = LocalObjectStore(root / "objects")
        queue = InProcessQueue()
        pipeline = IngestionPipeline(engine, object_store=object_store, queue=queue)

        # Image bytes, NO caller-supplied derived text -> must enqueue extraction.
        result = pipeline.ingest(
            IngestRequest(
                tenant_id="t",
                user_id="u",
                actor="user",
                source_type="upload",
                data=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                media_type="image/png",
                modality="image",
            )
        )
        assert result.modality == "image", f"raw modality lost: {result.modality}"
        pending_kinds = {job.kind for job in queue.jobs.values() if job.status in {"queued", "retry"}}
        assert MEDIA_EXTRACT_JOB in pending_kinds, (
            f"image ingest did not enqueue {MEDIA_EXTRACT_JOB}; saw {pending_kinds}"
        )

        # Run the real media-extraction job with a stand-in 'model'.
        runner = RuntimeJobHandlers(
            engine, queue=queue, object_store=object_store, media_extractor=_StandInExtractor()
        )
        ran = _drain(queue, runner)
        derived = [
            ev
            for ev in engine.evidence.values()
            if getattr(ev, "source_type", "") == "media-extraction"
        ]
        assert derived, f"media job did not derive text evidence (ran {ran} jobs)"
        derived_ev = derived[0]
        assert "PURCHASE ORDER 7781" in (derived_ev.content or "")
        assert derived_ev.modality == "text", "derived text must rejoin the text substrate"
        tags = set(getattr(derived_ev, "capability_tags", []) or [])
        assert "derived-from-media" in tags or "source:media-extraction" in tags
        # Provenance back to the originating image.
        assert derived_ev.metadata.get("source_evidence_cid") == result.cid
        return (
            "image ingest -> evidence(modality=image) -> media_extract job -> "
            f"derived text evidence(modality=text) on the SAME ledger ({ran} jobs run)"
        )


def _check_substrate_indexes_caller_derived_text_inline() -> str | None:
    """(3b) Alternate extension path: caller pre-extracted (OCR/caption/transcript).

    When a trusted caller supplies derived text in metadata, the pipeline indexes
    it INLINE on the same ledger (tag ``derived-text-indexed``) and does NOT
    enqueue a redundant media_extract job. Proves the modality flows into the
    text substrate either way.
    """
    import tempfile

    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.ingestion import IngestionPipeline, IngestRequest
    from mnemosyne.media import MEDIA_EXTRACT_JOB
    from mnemosyne.queue import InProcessQueue
    from mnemosyne.storage import LocalObjectStore

    with tempfile.TemporaryDirectory(prefix="mnemo-scope-fr20b-") as tmp:
        root = Path(tmp)
        engine = LocalMemoryEngine()
        object_store = LocalObjectStore(root / "objects")
        queue = InProcessQueue()
        pipeline = IngestionPipeline(engine, object_store=object_store, queue=queue)

        result = pipeline.ingest(
            IngestRequest(
                tenant_id="t",
                user_id="u",
                actor="user",
                source_type="upload",
                data=b"RIFF\x00\x00WAVE" + b"0" * 64,
                media_type="audio/wav",
                modality="audio",
                metadata={"transcript": "the standup is on thursday at nine"},
            )
        )
        assert result.modality == "audio"
        # The raw audio evidence carries the caller-derived transcript inline.
        raw_ev = engine.evidence[result.cid] if result.cid in engine.evidence else None
        if raw_ev is None:  # engine keys by (tenant,cid,branch) variants; fall back to scan
            raw_ev = next(ev for ev in engine.evidence.values() if ev.modality == "audio")
        assert "thursday" in (raw_ev.content or ""), "caller transcript not indexed inline"
        assert "derived-text-indexed" in set(getattr(raw_ev, "capability_tags", []) or [])
        # No redundant extraction job when caller already provided derived text.
        pending_kinds = {job.kind for job in queue.jobs.values() if job.status in {"queued", "retry"}}
        assert MEDIA_EXTRACT_JOB not in pending_kinds, (
            "redundant media_extract enqueued despite caller-supplied transcript"
        )
        return "audio + caller transcript -> indexed inline on the text substrate (no redundant job)"


def _drain(queue, runner, limit: int = 64) -> int:
    """Drain the in-process queue using its real lease/complete/fail lifecycle."""
    handlers = runner.handlers()
    ran = 0
    for _ in range(limit):
        job = queue.lease()
        if job is None:
            break
        handler = handlers.get(job.kind)
        if handler is None:
            queue.complete(job.id)
            continue
        try:
            handler(dict(job.payload))
            queue.complete(job.id)
            ran += 1
        except Exception as exc:  # noqa: BLE001 - record + continue draining
            queue.fail(job.id, str(exc))
    return ran


CHECKS: list[Check] = [
    Check(
        "FR-20",
        "model_accepts_image_audio_modalities",
        "v1 bar: Evidence/IngestRequest model image+audio as first-class enum values.",
        _check_model_accepts_image_audio_modalities,
    ),
    Check(
        "FR-20",
        "single_extraction_interface_modality_agnostic",
        "v1 bar: one MediaTextExtractor Protocol; modality is a parameter, not a fork.",
        _check_single_extraction_interface_is_modality_agnostic,
    ),
    Check(
        "FR-20",
        "metadata_extractor_image_audio_identical",
        "v1 bar: default extractor handles image(OCR/caption)+audio(transcript) via one call.",
        _check_metadata_extractor_handles_image_and_audio_identically,
    ),
    Check(
        "FR-20",
        "command_extractor_modality_agnostic_boundary",
        "v1 bar: the real-model extension point is one shell-free command boundary.",
        _check_command_extractor_is_modality_agnostic_boundary,
    ),
    Check(
        "FR-20",
        "embedding_boundary_single_protocol",
        "v1 bar: MediaEmbeddingProvider is one boundary taking modality as a param.",
        _check_embedding_boundary_is_single_protocol,
    ),
    Check(
        "FR-20",
        "substrate_extends_via_media_extract_job",
        "v1 bar (N5 keystone): image ingest WITHOUT caller text enqueues+runs media_extract onto the SAME ledger.",
        _check_substrate_extends_via_media_extract_job,
    ),
    Check(
        "FR-20",
        "substrate_indexes_caller_derived_text_inline",
        "v1 bar: audio + caller transcript is indexed inline on the text substrate (no redundant job).",
        _check_substrate_indexes_caller_derived_text_inline,
    ),
]
