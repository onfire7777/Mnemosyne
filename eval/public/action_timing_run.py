"""Persist the five-seed exact-time DEVELOPMENT diagnostic, without admission."""

import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile
import uuid

from eval.harness.cli_driver import MnemoCLI
from eval.public.action_cli import ActionCLI
from eval.public.action_sink import ActionSink
from eval.public.action_timing import score_exact_time
from eval.public.bundle import _canonical, _parse_json

SEEDS = (7, 19, 41, 73, 101)


def make_plan():
    cases = []
    for seed in SEEDS:
        rng = random.Random(seed)
        start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(
            days=rng.randrange(730), seconds=rng.randrange(86400),
        )
        def stamp(now):
            return now.isoformat().replace("+00:00", "Z")
        delays = [0, 60, 300, 86400]
        rng.shuffle(delays)
        operations = []
        for name in ("keep", "cancel"):
            operations.append({"command": "task.create", "payload": {
                "task_id": name, "action_id": name,
                "trigger": {"type": "exact_time", "payload": {"at": stamp(start)}},
                "recurrence_policy": {"type": "interval", "interval_seconds": 604800, "max_occurrences": 4},
            }})
        for index, delay in enumerate(delays):
            due = start + timedelta(weeks=index)
            for now in (due - timedelta(seconds=1), due + timedelta(seconds=delay), due + timedelta(seconds=delay)):
                operations.extend([
                    {"command": "clock.inject", "payload": {"now": stamp(now)}},
                    {"command": "intention.observe", "payload": {}},
                ])
            if index == 1:
                operations.append({"command": "task.update", "payload": {"type": "cancel", "task_id": "cancel"}})
        operations.extend([
            {"command": "clock.inject", "payload": {"now": stamp(start + timedelta(weeks=4))}},
            {"command": "intention.observe", "payload": {}},
        ])
        cases.append({"case_id": f"seed-{seed}", "seed": seed, "operations": operations,
                      "expected": [
                          {"action_id": name, "occurrence": index,
                           "due_at": stamp(start + timedelta(weeks=index)),
                           "cancelled": name == "cancel" and index >= 2}
                          for name in ("keep", "cancel") for index in range(4)
                      ]})
    return {"schema": "m12-exact-time-run/v1", "track": "DEVELOPMENT", "publishable": False, "cases": cases}


def _reports(plan, records):
    if _canonical(plan) != _canonical(make_plan()):
        raise ValueError("saved plan differs from the versioned development workload")
    if len(records) != sum(len(case["operations"]) for case in plan["cases"]):
        raise ValueError("missing or extra operation records")
    cursor = 0
    reports = []
    for case in plan["cases"]:
        ticks = []
        now = None
        for step, operation in enumerate(case["operations"]):
            record = records[cursor]
            cursor += 1
            if not isinstance(record, dict) or set(record) != {"case_id", "step", "command", "payload", "response"}:
                raise ValueError("invalid operation record")
            if (record["case_id"] != case["case_id"] or type(record["step"]) is not int
                    or record["step"] != step or record["command"] != operation["command"]
                    or _canonical(record["payload"]) != _canonical(operation["payload"])):
                raise ValueError("operation record does not match the plan")
            if operation["command"] == "clock.inject":
                now = operation["payload"]["now"]
            if operation["command"] == "intention.observe":
                response = record["response"]
                if not isinstance(response, dict) or response.get("evaluated_at") != now:
                    raise ValueError("observation clock differs from the planned clock")
                ticks.append(response)
            elif record["response"] != {}:
                raise ValueError("unexpected non-observation response")
        reports.append({"case_id": case["case_id"], "report": score_exact_time(case["expected"], ticks)})
    return {"schema": "m12-exact-time-reports/v1", "publishable": False, "cases": reports}


def _write(path, value):
    with path.open("xb") as output:
        output.write(_canonical(value))


def _source_receipt(with_sink=False):
    root = Path(__file__).resolve().parents[2]
    files = [Path(__file__), Path(__file__).with_name("action_cli.py"),
             Path(__file__).with_name("action_timing.py"), root / "eval/harness/cli_driver.py"]
    if with_sink:
        files.append(Path(__file__).with_name("action_sink.py"))
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    return {"source_commit": head, "source_dirty": bool(dirty), "python_version": platform.python_version(),
            "harness_files": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
            "production_runtime_match_verified": False, "sink_enabled": with_sink}


def _deliver(sink, response):
    for firing in response["firing_observations"]:
        fields = {name: firing[name] for name in ("intention_id", "occurrence", "action_id")}
        first = sink.deliver(**fields)
        retry = sink.deliver(**fields, origin="harness-retry")
        if first["outcome"] == "conflict" or retry["outcome"] != "duplicate":
            raise ValueError("inconsistent sink delivery; durable attempts retained")


def _sink_for(path, run_id, case_id, session_id="timing"):
    return ActionSink(path, run_id=run_id, case_id=case_id, tenant_id=case_id, session_id=session_id)


def _replay_sink(plan, records, run_id, session_id="timing"):
    cases = []
    with tempfile.TemporaryDirectory(prefix="m12-sink-replay-") as temp:
        for case in plan["cases"]:
            sink = _sink_for(Path(temp) / "sink.sqlite3", run_id, case["case_id"], session_id)
            for record in records:
                if record["case_id"] == case["case_id"] and record["command"] == "intention.observe":
                    _deliver(sink, record["response"])
            cases.append({"case_id": case["case_id"], "snapshot": sink.snapshot()})
    return {"schema": "m12-inert-sink-annex/v1", "run_id": run_id, "cases": cases}


def _validate_sink_annex(output, read, plan, records, session_id="timing"):
    source = _parse_json(read("source.json"), "source")
    if not isinstance(source, dict):
        raise ValueError("invalid source receipt")
    enabled = source.get("sink_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("invalid sink declaration")
    if enabled:
        annex = _parse_json(read("sink.json"), "sink")
        if not isinstance(annex, dict) or not isinstance(annex.get("run_id"), str):
            raise ValueError("invalid sink annex")
        if _canonical(annex) != _canonical(_replay_sink(plan, records, annex["run_id"], session_id)):
            raise ValueError("sink annex does not recompute")
    elif (output / "sink.json").exists():
        raise ValueError("unadvertised sink annex")


def run_development(output, *, with_sink=False):
    """Save the plan before execution; retain completed operations on failure."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    plan = make_plan()
    _write(output / "plan.json", plan)
    _write(output / "source.json", _source_receipt(with_sink))
    records = []
    sink_cases = []
    run_id = str(uuid.uuid4()) if with_sink else None
    try:
        with (output / "operations.jsonl").open("xb") as log, tempfile.TemporaryDirectory(prefix="m12-timing-") as temp:
            adapter = ActionCLI(MnemoCLI(store=str(Path(temp) / "unused.json"), timeout_s=30))
            for case in plan["cases"]:
                scope = {"store": str(Path(temp) / (case["case_id"] + ".json")),
                         "tenant_id": case["case_id"], "session_id": "timing"}
                sink = _sink_for(output / "sink.sqlite3", run_id, case["case_id"]) if with_sink else None
                for step, operation in enumerate(case["operations"]):
                    response = adapter.run(operation["command"], scope, operation["payload"])
                    record = {"case_id": case["case_id"], "step": step, **operation, "response": response}
                    log.write(_canonical(record))
                    log.flush()
                    records.append(record)
                    if sink is not None and operation["command"] == "intention.observe":
                        _deliver(sink, response)
                if sink is not None:
                    sink_cases.append({"case_id": case["case_id"], "snapshot": sink.snapshot()})
        reports = _reports(plan, records)
        _write(output / "reports.json", reports)
        if with_sink:
            _write(output / "sink.json", {"schema": "m12-inert-sink-annex/v1", "run_id": run_id, "cases": sink_cases})
    except BaseException as error:
        # Exceptions may contain signed session tokens; never persist their text.
        _write(output / "status.json", {"status": "failed", "exception_type": type(error).__name__,
                                       "completed_operations": len(records), "publishable": False})
        raise
    _write(output / "status.json", {"status": "completed", "completed_operations": len(records), "publishable": False})
    return reports


def recompute(output):
    """Replay saved observations, not the model/system; no custody certification."""
    output = Path(output)

    def read(name):
        with (output / name).open("rb") as source:
            raw = source.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("diagnostic artifact exceeds 16 MiB")
        return raw.decode("utf-8")

    status = _parse_json(read("status.json"), "status")
    if not isinstance(status, dict) or status.get("status") != "completed":
        raise ValueError("diagnostic execution did not complete")
    plan = _parse_json(read("plan.json"), "plan")
    records = [_parse_json(line, "operation") for line in read("operations.jsonl").splitlines()]
    reports = _reports(plan, records)
    if status != {"status": "completed", "completed_operations": len(records), "publishable": False}:
        raise ValueError("operation count differs from completion record")
    if _canonical(_parse_json(read("reports.json"), "reports")) != _canonical(reports):
        raise ValueError("saved reports do not recompute")
    _validate_sink_annex(output, read, plan, records)
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--recompute", action="store_true")
    mode.add_argument("--sink", action="store_true", help="record inert deliveries and deliberate retries in a durable sink")
    args = parser.parse_args()
    try:
        result = recompute(args.output) if args.recompute else run_development(args.output, with_sink=args.sink)
    except Exception as error:
        print(f"Development diagnostic failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(_canonical(result).decode("utf-8"), end="")
