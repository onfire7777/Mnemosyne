"""OpenRouter endpoint and the model each framework pass runs on.

Proper Thinking routed its passes to preset model buckets from its own settings file.
Inside Mnemosyne every pass uses the model the caller asked for (BurnOS's working model).
It is a context variable, so conversions running side by side each keep their own.
"""

import os
from contextvars import ContextVar

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENAI_MODEL = "openai/gpt-5.2"

MODEL: ContextVar[str] = ContextVar("framework_model", default="")


def resolve_model_for_task(task_name: str) -> str:
    return MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_OPENAI_MODEL
