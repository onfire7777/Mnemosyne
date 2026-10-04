"""Optional POSIX outer guard; does not alter a registered scoring command.

A successful subprocess is not a verified benchmark result. Callers must still
verify registration, source, inputs, bundle and signatures before admission.
This guard retains one exclusive attempt and its logs even on resource abort.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time


def macos_memory_pressure() -> int:
    result = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
        check=True, capture_output=True, text=True, timeout=2,
    )
    return int(result.stdout.strip())


def _write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _live_group_members(group_id: int) -> list[int]:
    listing = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid=,stat="],
        check=True, capture_output=True, text=True, timeout=2,
    )
    return [int(pid) for line in listing.stdout.splitlines()
            for pid, group, status in [line.split()]
            if int(group) == group_id and not status.startswith("Z")]


def _terminate_group(process: subprocess.Popen) -> None:
    # A parent can exit before its children. Signal the group even then.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _live_group_members(process.pid):
            break
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            # macOS may report EPERM after the last live member has exited.
            if _live_group_members(process.pid):
                raise
            break
        if sig == signal.SIGTERM:
            time.sleep(0.1)
    process.wait(timeout=5)
    deadline = time.monotonic() + 1
    while _live_group_members(process.pid):
        if time.monotonic() >= deadline:
            raise RuntimeError("process group remained live after cancellation")
        time.sleep(0.01)


def run_monitored(
    argv: Sequence[str], *, cwd: Path, output_dir: Path, wall_seconds: float,
    pressure_probe: Callable[[], int] = macos_memory_pressure,
    poll_seconds: float = 1.0,
) -> dict[str, object]:
    """Run once, abort on non-normal pressure, and retain a terminal receipt.

    Probe errors fail closed. This controls processes remaining in the child's
    process group, not a hostile workload that deliberately escapes that group.
    The default probe is macOS-specific; other POSIX hosts need their own probe.
    """
    if os.name != "posix":
        raise ValueError("resource guard requires POSIX process groups")
    if not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("argv must contain strings")
    for value in (wall_seconds, poll_seconds):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError("time limits must be positive and finite")
    cwd = cwd.resolve(strict=True)
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    start = time.monotonic()
    receipt: dict[str, object] = {
        "schema": "mnemosyne.monitored-command.v1", "argv": list(argv),
        "cwd": str(cwd), "started_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": wall_seconds, "poll_seconds": poll_seconds,
        "status": "no_run", "reason": None, "returncode": None,
        "benchmark_verified": False,
    }
    _write_json(output_dir / "start.json", receipt)
    process = None
    try:
        with (output_dir / "pressure.jsonl").open("x") as samples, \
             (output_dir / "stdout.log").open("xb") as stdout, \
             (output_dir / "stderr.log").open("xb") as stderr:
            while True:
                if process is not None and process.poll() is not None:
                    receipt.update(status="succeeded" if process.returncode == 0 else "failed",
                                   reason="process-exited", returncode=process.returncode)
                    break
                elapsed = time.monotonic() - start
                if elapsed >= wall_seconds:
                    receipt.update(status="aborted" if process else "no_run", reason="wall-time-limit")
                    break
                pressure = pressure_probe()
                samples.write(json.dumps({"elapsed_seconds": elapsed, "pressure": pressure}) + "\n")
                samples.flush()
                # The probe can block. Never launch after it consumes the
                # remaining budget, even when it reports normal pressure.
                if time.monotonic() - start >= wall_seconds:
                    receipt.update(status="aborted" if process else "no_run", reason="wall-time-limit")
                    break
                if type(pressure) is not int or pressure != 1:
                    receipt.update(status="aborted" if process else "no_run",
                                   reason="memory-pressure" if pressure in (2, 4) else "unknown-pressure")
                    break
                if process is None:
                    process = subprocess.Popen(
                        list(argv), cwd=cwd, stdin=subprocess.DEVNULL,
                        stdout=stdout, stderr=stderr, start_new_session=True,
                    )
                    receipt["pid"] = process.pid
                time.sleep(min(poll_seconds, max(0, wall_seconds - (time.monotonic() - start))))
    except (KeyboardInterrupt, SystemExit):
        receipt.update(status="aborted" if process else "no_run", reason="interrupted")
    except Exception as exc:
        receipt.update(status="aborted" if process else "no_run", reason="monitor-error",
                       error_type=type(exc).__name__)
    finally:
        if process is not None:
            try:
                _terminate_group(process)
            except Exception as exc:
                receipt.update(status="failed", reason="cleanup-error",
                               cleanup_error_type=type(exc).__name__)
            receipt["returncode"] = process.returncode
        receipt["elapsed_seconds"] = time.monotonic() - start
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(output_dir / "terminal.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wall-seconds", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        result = run_monitored(command, cwd=args.cwd, output_dir=args.output_dir,
                               wall_seconds=args.wall_seconds)
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
