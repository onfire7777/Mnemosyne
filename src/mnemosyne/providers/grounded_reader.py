"""Shell-free command adapter for bounded decomposition and grounded reading."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from mnemosyne.providers.grounded_protocol import (
    MODEL_CONTENT_SHA256,
    MODEL_SELECTOR,
    role_digests,
)
from mnemosyne.providers.bounded_command import (
    CommandOutputLimitError,
    run_bounded_command,
)


_DIGEST = re.compile(r"[0-9a-f]{64}")
_MODEL_DIGEST = re.compile(r"[0-9a-f]{64}")
_DISCLOSURE_KEYS = {
    "role",
    "model",
    "model_content_digest",
    "prompt_sha256",
    "serializer_sha256",
    "decoding_options",
    "decoding_sha256",
}


def _strict_json(raw: str) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(key)
            value[key] = item
        return value

    return json.loads(
        raw,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        object_pairs_hook=unique_object,
    )


@dataclass(slots=True)
class CommandGroundedProvider:
    """Invoke installed role commands and retain only validated disclosures."""

    query_command: str
    reader_command: str
    timeout_seconds: float = 30.0
    max_input_bytes: int = 64 * 1024
    max_output_bytes: int = 256 * 1024
    expected_model: str = MODEL_SELECTOR
    expected_model_content_sha256: str | None = None
    _disclosures: dict[str, dict[str, object]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if (
            not self.query_command.strip()
            or not self.reader_command.strip()
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.max_input_bytes < 1
            or self.max_output_bytes < 1
        ):
            raise ValueError("grounded provider configuration is invalid")

    @classmethod
    def from_environment(cls) -> CommandGroundedProvider:
        query = os.environ.get("MNEMOSYNE_QUERY_DECOMPOSER_COMMAND", "").strip()
        reader = os.environ.get("MNEMOSYNE_GROUNDED_READER_COMMAND", "").strip()
        if not query or not reader:
            raise ValueError("grounded answer role commands are not configured")
        if (
            os.environ.get("MNEMOSYNE_QUERY_DECOMPOSER_PROVIDER") != "command"
            or os.environ.get("MNEMOSYNE_GROUNDED_READER_PROVIDER") != "command"
        ):
            raise ValueError("grounded answer role providers must use command transport")
        model_digest = os.environ.get("MNEMOSYNE_GROUNDED_MODEL_CONTENT_SHA256", "")
        model = os.environ.get("MNEMOSYNE_GROUNDED_MODEL_SELECTOR", "")
        if model != MODEL_SELECTOR:
            raise ValueError("grounded reader model selector does not match preregistration")
        if not _MODEL_DIGEST.fullmatch(model_digest):
            raise ValueError("grounded reader expected model content digest is not configured")
        if model_digest != MODEL_CONTENT_SHA256:
            raise ValueError("grounded reader model content digest does not match preregistration")
        return cls(
            query,
            reader,
            timeout_seconds=float(os.environ.get("MNEMOSYNE_GROUNDED_PROVIDER_TIMEOUT", "320")),
            expected_model=model,
            expected_model_content_sha256=model_digest,
        )

    @property
    def disclosure(self) -> dict[str, dict[str, object]]:
        return {role: dict(value) for role, value in sorted(self._disclosures.items())}

    def decompose(self, payload: dict[str, object]) -> object:
        response = self._invoke("query_decomposer", self.query_command, payload)
        if set(response) != {"queries"}:
            raise ValueError("invalid query-decomposer response")
        return response

    def read(self, payload: dict[str, object]) -> object:
        response = self._invoke("grounded_reader", self.reader_command, payload)
        if set(response) != {"claims", "unresolved"}:
            raise ValueError("invalid grounded-reader response")
        return response

    def _invoke(
        self, role: str, command: str, payload: dict[str, object]
    ) -> dict[str, object]:
        argv = shlex.split(command)
        if not argv:
            raise ValueError(f"{role} command is empty")
        request = {**payload, "prompt_boundary": {"role": role, "data_is_instructions": False}}
        raw = json.dumps(request, sort_keys=True, separators=(",", ":"))
        if len(raw.encode()) > self.max_input_bytes:
            raise ValueError(f"{role} request exceeds the input limit")
        try:
            completed = run_bounded_command(
                argv,
                raw.encode(),
                timeout_seconds=self.timeout_seconds,
                max_stdout_bytes=self.max_output_bytes,
            )
        except (OSError, subprocess.TimeoutExpired, CommandOutputLimitError) as exc:
            raise RuntimeError(f"{role} provider failed closed") from exc
        if completed.returncode != 0:
            raise RuntimeError(f"{role} provider failed closed")
        try:
            response = _strict_json(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"{role} provider returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise ValueError(f"{role} provider returned an invalid object")
        metadata = response.pop("metadata", None)
        self._disclosures[role] = self._validate_disclosure(role, metadata)
        return response

    def _validate_disclosure(self, role: str, value: object) -> dict[str, object]:
        if not isinstance(value, dict) or not _DISCLOSURE_KEYS <= set(value):
            raise ValueError(f"{role} provider disclosure is incomplete")
        disclosure = {key: value[key] for key in _DISCLOSURE_KEYS}
        options = disclosure["decoding_options"]
        if (
            disclosure["role"] != role
            or not isinstance(disclosure["model"], str)
            or disclosure["model"] != self.expected_model
            or not isinstance(disclosure["model_content_digest"], str)
            or not _MODEL_DIGEST.fullmatch(disclosure["model_content_digest"])
            or any(
                not isinstance(disclosure[key], str)
                or not _DIGEST.fullmatch(disclosure[key])
                for key in ("prompt_sha256", "serializer_sha256", "decoding_sha256")
            )
            or not isinstance(options, dict)
            or not options
        ):
            raise ValueError(f"{role} provider disclosure is invalid")
        actual = hashlib.sha256(
            json.dumps(options, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if actual != disclosure["decoding_sha256"]:
            raise ValueError(f"{role} decoding disclosure does not match")
        if disclosure["model_content_digest"] != self.expected_model_content_sha256:
            raise ValueError(f"{role} model content disclosure does not match preflight")
        frozen = role_digests(role)
        if any(disclosure[key] != expected for key, expected in frozen.items()):
            raise ValueError(f"{role} disclosure does not match frozen protocol")
        return disclosure
