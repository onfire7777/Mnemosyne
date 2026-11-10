"""Process deadlines shared by interactive hooks and the local MCP adapter."""
from __future__ import annotations

import json
import os
import subprocess
import time


def run_bounded(command, payload, *, primary_timeout=8.0, allow_local=True):
    """Return a response and sanitized attempt telemetry; never retain payloads.

    A killed provider process cannot hold a lock or leak an unfinished thread
    into subsequent requests. Failure type and duration remain distinguishable.
    """
    attempts = []
    phases = [(False, primary_timeout)] + ([(True, 2.8)] if allow_local else [])
    for local, timeout in phases:
        environment = dict(os.environ, MNEMOSYNE_INTERACTIVE_READ="1",
                           MNEMOSYNE_PROVIDER_TIMEOUT="2.5")
        if local:
            environment["MNEMOSYNE_LOCAL_RECALL"] = "1"
        start = time.monotonic()
        attempt = {"mode": "local" if local else "provider", "deadline_seconds": timeout}
        try:
            result = subprocess.run(command, input=json.dumps(payload), text=True,
                                    capture_output=True, timeout=timeout,
                                    env=environment, check=True)
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise ValueError("host response must be an object")
            attempt["status"] = "returned"
            attempt["seconds"] = round(time.monotonic() - start, 3)
            attempts.append(attempt)
            return response, {"degraded": local, "attempts": attempts,
                              "provider_deadline_seconds": primary_timeout}
        except subprocess.TimeoutExpired:
            attempt["status"] = "timeout"
        except subprocess.CalledProcessError as error:
            attempt.update(status="process_error", returncode=error.returncode)
        except (json.JSONDecodeError, ValueError):
            attempt["status"] = "invalid_response"
        attempt["seconds"] = round(time.monotonic() - start, 3)
        attempts.append(attempt)
    return None, {"degraded": True, "attempts": attempts,
                  "provider_deadline_seconds": primary_timeout}
