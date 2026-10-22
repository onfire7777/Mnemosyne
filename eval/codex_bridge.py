"""Evaluation-only native LLM bridge using the existing authenticated Codex CLI.

No network server, credentials, retries, or production routing. Raw receipts are
written to the caller's isolated evaluation directory, one file per attempt.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any
import uuid

from eval.codex_reader import process_with_codex

MODEL = "gpt-6-astra"
EFFORT = "low"
_SLOTS = threading.BoundedSemaphore(3)


def complete(
    messages: list[dict[str, Any]], response_schema: dict[str, Any] | None = None,
    *, scope: str | None = None, requested_max_tokens: int | None = None,
    requested_temperature: float | None = None, receipt_dir: Path | str,
    timeout_seconds: float = 180,
) -> dict[str, Any]:
    """Return text/usage/receipt; schema validation is done by the native caller.

    Temperature and completion-token caps cannot be enforced by this CLI bridge.
    Recording them without claiming enforcement prevents a false API equivalence.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a nonempty list")
    clean = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in {"system", "developer", "user", "assistant"}
            or not isinstance(message.get("content"), str)
            or set(message) - {"role", "content"}
        ):
            raise ValueError("only text messages without tool calls are supported")
        clean.append({"role": message["role"], "content": message["content"]})
    if response_schema is not None and not isinstance(response_schema, dict):
        raise ValueError("response_schema must be an object")
    prompt = "Native task messages, in order:\n" + json.dumps(clean, ensure_ascii=False)
    if response_schema is not None:
        prompt += "\n\nThe task output must be JSON matching this schema:\n" + json.dumps(response_schema)
    root = Path(receipt_dir)
    root.mkdir(parents=True, exist_ok=True)
    attempt_id = uuid.uuid4().hex
    receipt: dict[str, Any] = {
        "schema": "mnemosyne.codex-native-attempt.v1", "attempt_id": attempt_id,
        "started_at": datetime.now(timezone.utc).isoformat(), "scope": scope,
        "requested_model": MODEL, "requested_reasoning_effort": EFFORT,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_chars": len(prompt), "requested_max_tokens": requested_max_tokens,
        "requested_temperature": requested_temperature, "generation_token_cap_enforced": False,
        "temperature_enforced": False, "cost_usd": None,
        "cost_basis": "Existing Codex account quota; monetary cost not measured",
    }
    started = time.monotonic()
    try:
        with _SLOTS:
            response = process_with_codex(
                prompt, model=MODEL, reasoning_effort=EFFORT, timeout_seconds=timeout_seconds,
            )
        receipt.update(response)
        receipt["status"] = "completed"
        receipt["response_sha256"] = hashlib.sha256(response["answer"].encode()).hexdigest()
        return {"text": response["answer"], "usage": response.get("usage"), "receipt": receipt}
    except Exception as exc:
        receipt.update(status="failed", error_kind=getattr(exc, "kind", type(exc).__name__))
        raise
    finally:
        receipt["total_seconds"] = round(time.monotonic() - started, 6)
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        # Unique filename and atomic replacement avoid partial receipts on interruption.
        temp = root / (attempt_id + ".tmp")
        temp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(root / (attempt_id + ".json"))
