"""Authenticated Codex lifecycle adapter with a hard, process-bounded deadline."""

import json
import hashlib
import os
import re
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from runtime import STATE, TENANT, USER, invoke, locked, open_facade
from mnemosyne.hosts.codex import CodexAdapter, redact


def adapter(stage_callback=None):
    return CodexAdapter(state_dir=STATE, tenant_id=TENANT, user_id=USER,
        open_facade=open_facade, locked=locked, invoke=invoke, require_delivery_confirmation=True,
        report_command=[sys.executable, str(Path(__file__).resolve()), "--report-use"],
        stage_callback=stage_callback)


def _diagnostic_identity(value):
    value = str(value or "")
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) else hashlib.sha256(value.encode()).hexdigest()


def _stage_path(payload):
    identity = payload.get("_hook_diagnostic_id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
        return None
    return STATE / ("hook-stage-" + identity + ".json")


def _write_stage(payload, stage, session, turn_id):
    path = _stage_path(payload)
    if path is None:
        return
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    row = {"stage": stage, "session_id": _diagnostic_identity(session),
           "turn_id": _diagnostic_identity(turn_id), "pid": os.getpid(),
           "at": datetime.now(UTC).isoformat()}
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        temporary.chmod(0o600)
        json.dump(row, stream)
    temporary.replace(path)


def handle(payload):
    return adapter(lambda stage, session, turn: _write_stage(payload, stage, session, turn)).handle(payload)


def supervise(payload):
    """Kill a stuck provider process, then retry recall using only local sources.

    Capture retries are recovered from saved state/transcripts by maintenance;
    they never pretend a timed-out observation completed successfully.
    """
    payload = {**payload, "_hook_diagnostic_id": uuid4().hex}
    command = [sys.executable, str(Path(__file__).resolve()), "--child"]
    event = payload.get("hook_event_name")
    deadline = 1.8 if event == "SessionEnd" else 8.0
    from mnemosyne.hosts.deadlines import run_bounded
    response, execution = run_bounded(command, payload, primary_timeout=deadline,
        allow_local=event in {"UserPromptSubmit", "HostCapabilities"})
    stage_path = _stage_path(payload)
    try:
        stage = json.loads(stage_path.read_text())
    except (OSError, ValueError):
        stage = {}
    finally:
        stage_path.unlink(missing_ok=True)
    if response is not None:
        if response.get('_mnemosyne_delivery'):
            response['_mnemosyne_delivery']['retrieval_execution'] = execution
        return response
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(STATE / 'host-attempts.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        record = {"event": event, "session_id": _diagnostic_identity(payload.get("session_id")),
                  "turn_id": _diagnostic_identity(payload.get("turn_id")),
                  "at": datetime.now(UTC).isoformat(), "last_stage": stage, **execution}
        os.write(descriptor, (json.dumps(record) + '\n').encode())
    finally:
        os.close(descriptor)
    if event in {"UserPromptSubmit", "HostCapabilities"}:
        return {"systemMessage": "Memory recall could not complete; this turn has no injected memory."}
    return {"systemMessage": "Memory capture is pending recovery from the retained transcript."}


def _log_delivery(delivery):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = STATE / 'deliveries.jsonl'
    record = {**delivery, 'status': 'returned', 'acknowledged': None, 'applied': None,
              'returned_at': datetime.now(UTC).isoformat()}
    from mnemosyne.experience.receipts import digest
    directory = STATE / 'deliveries'
    directory.mkdir(exist_ok=True, mode=0o700)
    marker = directory / (digest(delivery['receipt_id']) + '.json')
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.chmod(0o600)
    temporary.replace(marker)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(record) + '\n').encode())
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    child_failed = False
    try:
        payload = json.load(sys.stdin)
        arguments = sys.argv[1:]
        if arguments == ["--report-use"]:
            payload["hook_event_name"] = "MemoryUse"
        elif arguments == ["--report-capabilities"]:
            payload["hook_event_name"] = "HostCapabilities"
        elif arguments not in ([], ["--child"]):
            raise ValueError("unsupported lifecycle hook arguments")
        output = handle(payload) if arguments == ["--child"] else supervise(payload)
    except Exception as error:
        child_failed = True
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (STATE / "hook-errors.log").open("a") as log:
            (STATE / "hook-errors.log").chmod(0o600)
            log.write(datetime.now(UTC).isoformat() + " " + type(error).__name__ + "\n")
            log.write(redact("".join(traceback.format_exception(error))) + "\n")
        output = {"systemMessage": "Mnemosyne lifecycle capture needs attention. Check the local hook error log."}
    delivery = output.pop('_mnemosyne_delivery', None) if sys.argv[1:] != ['--child'] else None
    print(json.dumps(output, ensure_ascii=False, default=str), flush=True)
    if delivery:
        _log_delivery(delivery)
    if child_failed and sys.argv[1:] == ["--child"]:
        raise SystemExit(1)
