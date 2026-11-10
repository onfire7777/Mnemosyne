"""Authenticated Codex lifecycle adapter with a hard, process-bounded deadline."""

import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

from runtime import STATE, TENANT, USER, invoke, locked, open_facade
from mnemosyne.hosts.codex import CodexAdapter, redact


def adapter():
    return CodexAdapter(state_dir=STATE, tenant_id=TENANT, user_id=USER,
        open_facade=open_facade, locked=locked, invoke=invoke, require_delivery_confirmation=True,
        report_command=[sys.executable, str(Path(__file__).resolve()), "--report-use"])


def handle(payload):
    return adapter().handle(payload)


def supervise(payload):
    """Kill a stuck provider process, then retry recall using only local sources.

    Capture retries are recovered from saved state/transcripts by maintenance;
    they never pretend a timed-out observation completed successfully.
    """
    command = [sys.executable, str(Path(__file__).resolve()), "--child"]
    event = payload.get("hook_event_name")
    deadline = 1.8 if event == "SessionEnd" else 8.0
    from mnemosyne.hosts.deadlines import run_bounded
    response, execution = run_bounded(command, payload, primary_timeout=deadline,
        allow_local=event in {"UserPromptSubmit", "HostCapabilities"})
    if response is not None:
        if response.get('_mnemosyne_delivery'):
            response['_mnemosyne_delivery']['retrieval_execution'] = execution
        return response
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(STATE / 'host-attempts.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps({'event': event, **execution}) + '\n').encode())
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
