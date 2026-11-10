"""Bind the repository adapter to the host's local authenticated runtime."""

import json
import sys
import traceback
from datetime import UTC, datetime

from runtime import STATE, TENANT, USER, invoke, locked, open_facade

from mnemosyne.hosts.codex import CodexAdapter, redact


def adapter():
    return CodexAdapter(
        state_dir=STATE,
        tenant_id=TENANT,
        user_id=USER,
        open_facade=open_facade,
        locked=locked,
        invoke=invoke,
    )


def handle(payload):
    return adapter().handle(payload)


if __name__ == "__main__":
    try:
        output = handle(json.load(sys.stdin))
    except Exception as error:
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (STATE / "hook-errors.log").open("a") as log:
            (STATE / "hook-errors.log").chmod(0o600)
            log.write(datetime.now(UTC).isoformat() + " " + type(error).__name__ + "\n")
            log.write(redact("".join(traceback.format_exception(error))) + "\n")
        output = {
            "systemMessage": "Mnemosyne lifecycle capture needs attention. Check the local hook error log."
        }
    print(json.dumps(output, ensure_ascii=False, default=str))
