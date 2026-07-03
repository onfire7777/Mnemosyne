#!/usr/bin/env python3
"""Command-backed proposal-role provider ladder.

The wrapper keeps Mnemosyne's shell-free role-provider contract: JSON request
on stdin, JSON object on stdout, nonzero exit on failure. It tries an optional
frontier command for explicitly eligible low-volume roles, then the local role
LLM command, then an opt-in deterministic fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Any

LOCAL_ROLE_COMMAND_DEFAULT = "/opt/mnemosyne/bin/role-llm"
FRONTIER_ROLES_DEFAULT = frozenset({"entity_resolver", "lesson_distiller", "skill_inducer", "procedure_inducer"})
ALL_ROLES = frozenset({"candidate_extractor", "evidence_summarizer", "entity_resolver", "lesson_distiller", "skill_inducer", "procedure_inducer"})


def _env_key(role: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", role.upper()).strip("_")


def _csv_env(name: str, default: frozenset[str]) -> set[str]:
    raw = os.environ.get(name)
    if raw is None:
        return set(default)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _timeout(name: str, default: float) -> float:
    try:
        return max(0.001, float(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _command_for(role: str, rung: str) -> list[str] | None:
    role_key = _env_key(role)
    if rung == "frontier":
        raw = os.environ.get(f"MNEMOSYNE_FRONTIER_{role_key}_COMMAND") or os.environ.get("MNEMOSYNE_ROLE_LADDER_FRONTIER_COMMAND")
    elif rung == "local":
        raw = (
            os.environ.get(f"MNEMOSYNE_LOCAL_{role_key}_COMMAND")
            or os.environ.get("MNEMOSYNE_ROLE_LADDER_LOCAL_COMMAND")
            or LOCAL_ROLE_COMMAND_DEFAULT
        )
    else:
        raw = None
    if not raw:
        return None
    argv = shlex.split(raw)
    return argv or None


def _metadata(response: dict[str, Any]) -> dict[str, Any]:
    metadata = response.get("metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    return {}


def _with_ladder_metadata(
    response: dict[str, Any],
    *,
    role: str,
    selected: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    enriched = dict(response)
    metadata = _metadata(enriched)
    metadata["provider_ladder"] = {
        "role": role,
        "selected": selected,
        "attempts": attempts,
        "frontier_roles": sorted(_csv_env("MNEMOSYNE_ROLE_LADDER_FRONTIER_ROLES", FRONTIER_ROLES_DEFAULT)),
        "deterministic_fallback_enabled": _flag("MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC"),
    }
    enriched["metadata"] = metadata
    return enriched


def _run_command(
    argv: list[str],
    request: dict[str, Any],
    *,
    rung: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, {
            "rung": rung,
            "status": "timeout",
            "timeout_seconds": round(timeout_seconds, 3),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }
    except OSError as exc:
        return None, {
            "rung": rung,
            "status": "failed",
            "error_class": exc.__class__.__name__,
            "timeout_seconds": round(timeout_seconds, 3),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    if completed.returncode != 0:
        return None, {
            "rung": rung,
            "status": "failed",
            "returncode": completed.returncode,
            "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest()[:16] if completed.stderr else None,
            "timeout_seconds": round(timeout_seconds, 3),
            "duration_ms": duration_ms,
        }
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None, {
            "rung": rung,
            "status": "invalid_json",
            "timeout_seconds": round(timeout_seconds, 3),
            "duration_ms": duration_ms,
        }
    if not isinstance(parsed, dict):
        return None, {
            "rung": rung,
            "status": "invalid_shape",
            "timeout_seconds": round(timeout_seconds, 3),
            "duration_ms": duration_ms,
        }
    return parsed, {
        "rung": rung,
        "status": "ok",
        "timeout_seconds": round(timeout_seconds, 3),
        "duration_ms": duration_ms,
    }


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _first_evidence_text(request: dict[str, Any]) -> str:
    evidence = request.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and str(item.get("content") or "").strip():
                return str(item["content"]).strip()
    return ""


def _deterministic_response(role: str, request: dict[str, Any]) -> dict[str, Any]:
    candidates = request.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    if role == "evidence_summarizer":
        text = _first_evidence_text(request)
        summary = re.split(r"(?<=[.!?])\s+", text)[0].strip() if text else "No evidence summary available."
        return {"summary": summary}
    if role == "entity_resolver":
        rows = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            signature = str(candidate.get("signature") or "")
            subject = str(candidate.get("candidate_subject") or signature)
            rows.append({"signature": signature, "entity_key": _slug(subject)})
        return {"candidates": rows}
    if role == "lesson_distiller":
        lessons = []
        for candidate in candidates[:3]:
            if isinstance(candidate, dict):
                signature = str(candidate.get("signature") or "candidate")
                lessons.append(
                    {
                        "content": f"Review consolidation candidate `{signature}` against source evidence before promotion.",
                        "failure_signature": f"deterministic:{signature}",
                        "votes": 1,
                    }
                )
        return {"lessons": lessons}
    if role in {"skill_inducer", "procedure_inducer"}:
        procedures = []
        for candidate in candidates[:2]:
            if isinstance(candidate, dict):
                signature = str(candidate.get("signature") or "candidate")
                procedures.append(
                    {
                        "name": f"Consolidate {_slug(signature)}",
                        "body": "1. Re-read source evidence\n2. Validate candidate fields\n3. Promote only through gates",
                        "signature": {"candidate_signature": signature, "source": "deterministic-role-ladder"},
                    }
                )
        return {"procedures": procedures}
    if role == "candidate_extractor":
        text = _first_evidence_text(request)
        match = re.match(r"(?P<subject>.+?)\s+(?P<predicate>is|are|has|prefers|wants|needs)\s+(?P<object>.+?)[.!?]?$", text, re.I)
        if not match:
            return {"candidates": []}
        subject = match.group("subject").strip()
        predicate = match.group("predicate").strip()
        obj = match.group("object").strip()
        signature = hashlib.sha256(f"{subject}\x1f{predicate}\x1f{obj}".encode("utf-8")).hexdigest()[:32]
        return {
            "candidates": [
                {
                    "signature": signature,
                    "query": f"{subject} {predicate}",
                    "candidate_subject": subject,
                    "candidate_predicate": predicate,
                    "candidate_object": obj,
                    "entity_key": _slug(subject),
                }
            ]
        }
    raise ValueError(f"unsupported role {role}")


def handle(request: dict[str, Any]) -> dict[str, Any]:
    role = str((request.get("prompt_boundary") or {}).get("role") or "").strip()
    if role not in ALL_ROLES:
        raise ValueError(f"unsupported provider role {role!r}")
    total_timeout = _timeout("MNEMOSYNE_ROLE_LADDER_TIMEOUT", _timeout("OLLAMA_TIMEOUT", 25.0))
    deadline = time.monotonic() + total_timeout
    attempts: list[dict[str, Any]] = []
    frontier_roles = _csv_env("MNEMOSYNE_ROLE_LADDER_FRONTIER_ROLES", FRONTIER_ROLES_DEFAULT)
    rungs: list[tuple[str, list[str] | None, float]] = []
    if role in frontier_roles:
        rungs.append(("frontier", _command_for(role, "frontier"), _timeout("MNEMOSYNE_ROLE_LADDER_FRONTIER_TIMEOUT", min(12.0, total_timeout))))
    rungs.append(("local", _command_for(role, "local"), _timeout("MNEMOSYNE_ROLE_LADDER_LOCAL_TIMEOUT", min(20.0, total_timeout))))
    for rung, argv, configured_timeout in rungs:
        remaining = deadline - time.monotonic()
        if argv is None:
            attempts.append({"rung": rung, "status": "not_configured"})
            continue
        if remaining <= 0:
            attempts.append({"rung": rung, "status": "budget_exhausted"})
            continue
        parsed, attempt = _run_command(argv, request, rung=rung, timeout_seconds=min(configured_timeout, remaining))
        attempts.append(attempt)
        if parsed is not None:
            return _with_ladder_metadata(parsed, role=role, selected=rung, attempts=attempts)
    if _flag("MNEMOSYNE_ROLE_LADDER_ALLOW_DETERMINISTIC"):
        attempts.append({"rung": "deterministic", "status": "ok", "timeout_seconds": 0.0, "duration_ms": 0.0})
        return _with_ladder_metadata(
            _deterministic_response(role, request),
            role=role,
            selected="deterministic",
            attempts=attempts,
        )
    raise RuntimeError("provider ladder failed closed: no configured rung succeeded")


def main() -> int:
    try:
        request = json.load(sys.stdin)
        json.dump(handle(request), sys.stdout)
    except Exception as exc:  # fail closed and avoid echoing request payloads.
        print(f"role-ladder: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
