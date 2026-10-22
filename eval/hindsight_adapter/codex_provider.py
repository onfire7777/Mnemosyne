"""Bridge Hindsight's native LLM interface to the authenticated Codex CLI.

This replaces only the provider factory in this evaluation process. Native
prompts, extraction, consolidation, embeddings and retrieval remain upstream.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import json
from pathlib import Path
from typing import Any

from hindsight_api.engine.llm_interface import LLMInterface
from hindsight_api.engine.response_models import LLMCallResult, TokenUsage

from eval.codex_bridge import complete

CASE_RECEIPT_DIR: ContextVar[Path | None] = ContextVar("hindsight_case_receipt_dir", default=None)


class CodexCLIProvider(LLMInterface):
    def __init__(self, *, receipt_dir: Path, **kwargs: Any):
        super().__init__(**kwargs)
        self.receipt_dir = receipt_dir

    async def verify_connection(self) -> None:
        # Runner explicitly requests skip_llm_verification. Do not disguise a
        # skipped paid/account-quota call as a successful connectivity probe.
        raise RuntimeError("Use skip_llm_verification=True; verify through an explicit smoke retain")

    async def call(
        self, messages, response_format=None, max_completion_tokens=None,
        temperature=None, scope="memory", max_retries=10,
        initial_backoff=1.0, max_backoff=60.0, skip_validation=False,
        strict_schema=False, cached_prefix=None, attempt_context=None,
    ) -> LLMCallResult:
        if cached_prefix is not None:
            raise ValueError("Codex bridge does not support opaque cached prefixes")
        schema = response_format.model_json_schema() if response_format is not None else None
        receipt_dir = CASE_RECEIPT_DIR.get() or self.receipt_dir
        response = await asyncio.to_thread(
            complete, messages, schema, scope="hindsight:" + scope,
            requested_max_tokens=max_completion_tokens,
            requested_temperature=temperature, receipt_dir=receipt_dir,
            timeout_seconds=self.timeout or 180,
        )
        validation = {"status": "text", "skip_validation": skip_validation}
        try:
            content = response["text"]
            if response_format is not None:
                content = json.loads(content)
                if not skip_validation:
                    content = response_format.model_validate(content)
                validation["status"] = "json_parsed" if skip_validation else "schema_validated"
        except Exception as exc:
            validation.update(status="failed", error_kind=type(exc).__name__)
            raise
        finally:
            # The bridge has already persisted its receipt. Add the native
            # parse/validation result so valid model transport cannot mask a
            # failed extractor contract. Do not copy output prose into logs.
            receipt = response.get("receipt", {})
            if receipt.get("attempt_id"):
                path = receipt_dir / (receipt["attempt_id"] + ".json")
                receipt["native_validation"] = validation
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(receipt, indent=2) + "\n")
                temporary.replace(path)
        usage = response.get("usage") or {}
        inputs = int(usage.get("input_tokens", 0))
        outputs = int(usage.get("output_tokens", 0))
        return LLMCallResult(content=content, usage=TokenUsage(
            input_tokens=inputs, output_tokens=outputs, total_tokens=inputs + outputs,
            cached_tokens=int(usage.get("cached_input_tokens", 0)),
            thoughts_tokens=int(usage.get("reasoning_output_tokens", usage.get("thoughts_tokens", 0))),
        ))

    async def call_with_tools(self, *args, **kwargs):
        raise RuntimeError("This controlled adapter supports native retain/recall, not reflect tool calls")

    async def cleanup(self) -> None:
        pass  # Each bridge call owns and closes its CLI subprocess.


def install_factory(receipt_dir: Path) -> None:
    """Install before constructing any MemoryEngine/provider instances."""
    import hindsight_api.engine.llm_wrapper as wrapper

    def factory(**kwargs: Any) -> CodexCLIProvider:
        return CodexCLIProvider(receipt_dir=receipt_dir, **kwargs)

    wrapper.create_llm_provider = factory
