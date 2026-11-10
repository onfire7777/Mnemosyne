"""Bounded counterfactual experiments in disposable SQLite/Python environments.

Inputs and assertions come from retained external tool snapshots. Proposed
alternatives cannot replace checks. Results describe this isolated environment,
never a successful user task, and do not bypass promotion or privacy gates.
"""

from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
try:
    import resource
except ImportError:  # Unsupported hosts keep the rest of consolidation usable.
    resource = None
import shutil
import signal
import sqlite3
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
import time



def _files(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 128:
        return False
    for name, content in files.items():
        if (not isinstance(name, str) or not isinstance(content, str) or len(content) > 131072
                or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                or any(part.startswith(".") for part in PurePosixPath(name).parts)
                or not name.endswith(".py")):
            return False
    return sum(len(value) for value in files.values()) <= 2097152


def valid_environment(environment):
    if not isinstance(environment, dict) or environment.get("version") != 1:
        return False
    if len(json.dumps(environment, default=str)) > 4194304:
        return False
    if environment.get("kind") == "sqlite":
        checks = environment.get("checks")
        return (all(isinstance(environment.get(key), list) and len(environment[key]) <= 64
                    and all(isinstance(sql, str) and 0 < len(sql) <= 32768 for sql in environment[key])
                    for key in ("setup", "baseline"))
                and isinstance(checks, list) and 1 <= len(checks) <= 32
                and all(isinstance(check, dict) and isinstance(check.get("query"), str)
                        and len(check["query"]) <= 32768 and isinstance(check.get("expected_rows"), list)
                        for check in checks))
    if environment.get("kind") == "python":
        if not _files(environment.get("files")):
            return False
        if "source_hashes" in environment and environment["source_hashes"] != {
                name: hashlib.sha256(content.encode()).hexdigest() for name, content in environment["files"].items()}:
            return False
        if environment.get("runner") == "pytest":
            tests = environment.get("tests")
            return (isinstance(tests, list) and 1 <= len(tests) <= 16
                    and all(isinstance(test, str) and test.split("::")[0] in environment["files"] for test in tests))
        return environment.get("test_pattern", "test*.py") in {"test*.py", "test_*.py", "*_test.py"}
    return False


def valid_alternative(environment, alternative):
    if not isinstance(alternative, dict) or not isinstance(alternative.get("id"), str):
        return False
    if environment["kind"] == "sqlite":
        rows = alternative.get("statements")
        return (set(alternative) <= {"id", "statements", "rationale"}
                and isinstance(rows, list) and 1 <= len(rows) <= 64
                and all(isinstance(sql, str) and 0 < len(sql) <= 32768 for sql in rows))
    files = alternative.get("files")
    test_files = {node.split("::")[0] for node in environment.get("tests", [])}
    return (set(alternative) <= {"id", "files", "rationale"} and _files(files)
            and all(name in environment["files"] and name not in test_files and not any(
                part.startswith("test") or part.endswith("_test.py") or part == "conftest.py"
                for part in PurePosixPath(name).parts)
                    for name in files))


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _sqlite_variant(environment, statements):
    db = sqlite3.connect(":memory:")
    db.enable_load_extension(False)
    denied = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}
    def authorize(action, first, second, database, trigger):
        if action in denied or (action == sqlite3.SQLITE_FUNCTION and str(second).lower() == "load_extension"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    db.set_authorizer(authorize)
    deadline = time.monotonic() + 2
    remaining = [200000]
    def progress():
        remaining[0] -= 1000
        return int(remaining[0] <= 0 or time.monotonic() > deadline)
    db.set_progress_handler(progress, 1000)
    results = []
    try:
        for sql in environment["setup"]:
            db.execute(sql)
        for sql in statements:
            db.execute(sql)
        # Read-only assertions cannot change the state being measured.
        def read_only(action, first, second, database, trigger):
            allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                       sqlite3.SQLITE_RECURSIVE}
            return authorize(action, first, second, database, trigger) if action in allowed else sqlite3.SQLITE_DENY
        db.set_authorizer(read_only)
        for check in environment["checks"]:
            cursor = db.execute(check["query"])
            rows = cursor.fetchmany(1001)
            if len(rows) > 1000:
                raise ValueError("result row limit")
            actual = [list(row) for row in rows]
            if len(json.dumps(actual)) > 65536:
                raise ValueError("result byte limit")
            results.append({"passed": actual == check["expected_rows"], "actual": actual})
        passed = sum(row["passed"] for row in results)
        return {"passed": passed, "failed": len(results) - passed, "results": results}
    except (sqlite3.Error, ValueError) as exc:
        return {"passed": 0, "failed": len(environment["checks"]), "error": str(exc)[:500]}
    finally:
        db.close()


def _sandbox_command(command, directory):
    """Only audited OS isolation backends may execute proposed Python code."""
    directory = str(Path(directory).resolve())
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").exists():
        roots = {str(Path(sys.base_prefix).resolve()), str(Path(sys.executable).resolve().parent.parent),
                 "/System/Library", "/usr/lib", "/usr/share/terminfo", directory,
                 sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}
        reads = " ".join("(subpath " + json.dumps(root) + ")" for root in roots)
        profile = ("(version 1)(deny default)(allow process-exec)(allow process-fork)(allow sysctl-read)(allow file-read-metadata)"
                   "(allow mach-lookup)(allow file-read* " + reads + " (literal \"/\") (literal \"/dev/null\"))"
                   "(allow file-map-executable " + reads + ")"
                   "(allow file-write* (subpath " + json.dumps(directory) + ") (literal \"/dev/null\"))")
        return ["/usr/bin/sandbox-exec", "-p", profile, *command]
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        args = [shutil.which("bwrap"), "--unshare-all", "--die-with-parent", "--new-session", "--proc", "/proc", "--dev", "/dev"]
        for path in {"/usr", "/lib", "/lib64", str(Path(sys.base_prefix).resolve()),
                     sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}:
            if Path(path).exists():
                args += ["--ro-bind", path, path]
        return [*args, "--bind", directory, directory, "--chdir", directory, *command]
    return None


def _process(command, cwd, *, stdin=None, capture_root=None):
    with TemporaryDirectory(prefix="mnemosyne-check-output-", dir=capture_root) as output_root:
        output_path = Path(output_root) / "result"
        with output_path.open("wb") as output:
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, env={"PATH": os.defpath, "PYTHONHASHSEED": "0",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1", "TERM": "dumb"},
                start_new_session=True, preexec_fn=_limits)
            try:
                process.communicate(stdin.encode() if stdin is not None else None, timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return {"status": "inconclusive", "reason": "environment_timeout"}
        text = output_path.read_bytes()[:1048576].decode(errors="replace")
        if process.returncode:
            return {"status": "inconclusive", "reason": "environment_process_failed", "return_code": process.returncode,
                    "detail": text[-1000:]}
        try:
            return json.loads(text)
        except ValueError:
            return {"status": "inconclusive", "reason": "environment_result_invalid", "detail": text[-1000:]}


def _python_variant(environment, replacement):
    with TemporaryDirectory(prefix="mnemosyne-python-experiment-") as directory:
        root = Path(directory)
        for name, content in {**environment["files"], **replacement}.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        runner = root / "mnemosyne_isolated_runner.py"
        # The observed test corpus is immutable between baseline and candidate.
        if environment.get("runner") == "pytest":
            dependency_paths = list({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
            runner.write_text("import contextlib,json,os,sys\n"
                "sys.path.extend(" + repr(dependency_paths) + ")\n"
                "with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):\n import pytest\n"
                "sys.path[:0]=[sys.argv[1],os.path.join(sys.argv[1],'src')]\n"
                "class Results:\n"
                " def __init__(self): self.passed=0; self.failed=0; self.ids=[]\n"
                " def pytest_runtest_logreport(self,report):\n"
                "  if report.when=='call' and report.passed: self.passed+=1\n"
                "  if report.failed: self.failed+=1; self.ids.append(report.nodeid)\n"
                " def pytest_collectreport(self,report):\n"
                "  if report.failed: self.failed+=1; self.ids.append(report.nodeid)\n"
                "r=Results()\n"
                "with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):\n"
                " code=pytest.main(['-q','-o','addopts=','-p','no:cacheprovider']+json.loads(sys.argv[2]),plugins=[r])\n"
                "print(json.dumps({'passed':r.passed,'failed':r.failed,'total':r.passed+r.failed,'failed_tests':r.ids,'exit_code':int(code)}))\n")
            selector = json.dumps(environment["tests"])
        else:
            runner.write_text("import contextlib,json,os,sys,unittest\n"
                          "sys.path.insert(0,sys.argv[1])\n"
                          "with open(os.devnull,'w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):\n"
                          " suite=unittest.TestLoader().discover(sys.argv[1],pattern=sys.argv[2])\n"
                          " result=unittest.TextTestRunner(stream=sink).run(suite)\n"
                          "print(json.dumps({'passed':result.testsRun-len(result.failures)-len(result.errors),"
                          "'failed':len(result.failures)+len(result.errors),'total':result.testsRun}))\n")
            selector = environment.get("test_pattern", "test*.py")
        command = _sandbox_command([str(Path(sys.executable).resolve()), "-I", "-S", str(runner), str(root), selector], root)
        if command is None:
            return {"status": "inconclusive", "reason": "os_sandbox_unavailable"}
        result = _process(command, directory, capture_root=directory)
        if result.get("total") == 0:
            return {"status": "inconclusive", "reason": "no_tests_executed"}
        return result


def run_environment_experiment(environment, alternative):
    if not valid_environment(environment) or not valid_alternative(environment, alternative):
        return {"status": "inconclusive", "reason": "invalid_environment_contract"}
    if resource is None:
        return {"status": "inconclusive", "reason": "resource_limits_unavailable"}
    if environment["kind"] == "sqlite":
        runner = str(Path(__file__).resolve())
        # A dedicated child bounds the real SQLite engine's memory and CPU.
        result = _process([sys.executable, "-I", "-S", runner], "/",
                          stdin=json.dumps({"environment": environment, "alternative": alternative}))
        return result
    baseline = _python_variant(environment, {})
    candidate = _python_variant(environment, alternative["files"])
    expected_failures = set(environment.get("original_failed_tests", []))
    if expected_failures and not expected_failures <= set(baseline.get("failed_tests", [])):
        return {"status": "inconclusive", "reason": "original_failure_not_reproduced", "baseline": baseline, "candidate": candidate}
    return comparison(baseline, candidate)


def comparison(baseline, candidate):
    if any(row.get("status") == "inconclusive" for row in (baseline, candidate)):
        return {"status": "inconclusive", "reason": "environment_unavailable", "baseline": baseline, "candidate": candidate}
    improved = candidate.get("failed", 1) == 0 and candidate.get("passed", 0) > 0 and baseline.get("failed", 0) > 0
    return {"status": "improved" if improved else "not_improved", "baseline": baseline, "candidate": candidate,
            "scope": "isolated_environment_comparison", "live_task_outcome": False}


def environment_proposals(runtime, tenant, episodes, limit=2):
    from .hypotheses import typed_hypothesis
    from .receipts import digest
    result = []
    existing = runtime.writer.read(tenant)["policy"].get("hypotheses", {})
    proposer = getattr(runtime.engine, "_learning_configuration", {}).get("environment_experiment_proposer")
    for episode in sorted(episodes, key=lambda row: (row.get("created_at", ""), row["id"]), reverse=True):
        if episode.get("status") != "resolved" or (episode.get("reward") or 0) >= 0:
            continue
        for event in episode.get("tool_events", []):
            environment = event.get("experiment_environment")
            if event.get("source") != "tool" or not valid_environment(environment):
                continue
            for cid in episode.get("source_cids", []):
                if not runtime._sources_live(tenant, [cid], episode.get("user_id")):
                    continue
                source = runtime.engine.get_evidence(tenant, cid)
                if not source or source.actor != "tool" or source.metadata.get("experiment_environment") != environment:
                    continue
                cohort = digest([tenant, episode["user_id"], cid, environment])
                if any(row.get("environment_cohort") == cohort for row in existing.values()):
                    continue
                alternatives = environment.get("alternatives", [])
                if not alternatives and callable(proposer):
                    try:
                        proposed = proposer(environment=deepcopy(environment), failure=event.get("output", ""),
                                            task=episode.get("user_text", ""))
                    except Exception:
                        proposed = None
                    alternatives = proposed.get("alternatives", []) if isinstance(proposed, dict) else []
                alternatives = [row for row in alternatives if valid_alternative(environment, row)][:2]
                if not alternatives:
                    continue
                for alternative in alternatives:
                    identity = "environment:" + digest([cohort, alternative])
                    check = {"version": 1, "kind": "isolated_environment", "environment": deepcopy(environment),
                             "alternative": deepcopy(alternative), "source_cid": cid}
                    row = {"id": identity, "content": str(alternative.get("rationale") or "Compare a proposed repair with the retained failing environment."),
                           "steps": [json.dumps(alternative, sort_keys=True)], "sandbox_check": check,
                           "source_cids": [cid], "source_episode_ids": [episode["id"]],
                           "task_class": episode["task_class"], "user_id": episode["user_id"], "conditions": [],
                           "environment_cohort": cohort,
                           "experiment_scope": "isolated_environment_comparison_not_live_task_outcome",
                           "capability_tags": ["data-only", "no-write-authority"], "instruction_authority": "none"}
                    result.append(typed_hypothesis(runtime, tenant, row, kind="procedural"))
                    if len(result) >= limit:
                        return result
                break
            if len(result) >= limit:
                return result
    return result


if __name__ == "__main__":
    request = json.loads(sys.stdin.read(4194305))
    env = request["environment"]
    baseline = _sqlite_variant(env, env["baseline"])
    candidate = _sqlite_variant(env, request["alternative"]["statements"])
    print(json.dumps(comparison(baseline, candidate)))
