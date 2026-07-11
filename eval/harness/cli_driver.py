"""Public-CLI driver for the Mnemosyne §33 evaluation harness.

This module is the *single* seam through which the harness touches Mnemosyne.
Per the rules of engagement (blueprint §33 / §30.7), the harness drives ONLY the
public CLI surface (``python -m mnemosyne.cli ...``) — it never imports internal
engine/retrieval/belief modules. Everything below shells out to a subprocess and
parses the JSON the CLI prints on stdout, exactly as a real agent host would.

Why a subprocess (not an in-process import):
  * It proves the *contract* the blueprint actually promises to agents (§30.7 ABI),
    not an internal API that could drift.
  * It measures real process-boundary latency (relevant to the §16 fast-path SLO,
    though we also expose a warm in-process timing path for tighter signal — see
    ``MnemoCLI.timed_search`` which still goes through the CLI entrypoint).
  * It keeps the harness honest: if the CLI breaks, the harness breaks.

ANSI stripping: the CLI pretty-prints with color codes; we strip them before
JSON parsing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

# Repo root = three levels up from this file: eval/harness/cli_driver.py -> repo
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove ANSI SGR color codes the CLI emits when pretty-printing."""
    return _ANSI_RE.sub("", text)


class CLIError(RuntimeError):
    """Raised when the CLI exits non-zero or emits unparseable output."""

    def __init__(self, argv: Sequence[str], returncode: int, stdout: str, stderr: str):
        self.argv = list(argv)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"CLI failed (rc={returncode}): mneme {' '.join(argv)}\n"
            f"--- stdout ---\n{stdout[-2000:]}\n--- stderr ---\n{stderr[-2000:]}"
        )


@dataclass(slots=True)
class CLIResult:
    """A single CLI invocation's full result."""

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    wall_ms: float
    json: Any | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(slots=True)
class MnemoCLI:
    """Thin wrapper that invokes the public Mnemosyne CLI as a subprocess.

    Parameters
    ----------
    store:
        Path to the local JSON store (``--store``). A fresh path gives an isolated
        deterministic engine — exactly what the harness wants for reproducibility.
    backend:
        ``local`` (default) or ``postgres``. The harness runs against the local
        deterministic engine NOW; pass ``postgres`` + ``postgres_dsn`` to sharpen
        once the real services are wired (blueprint §I portability / G8).
    global_flags:
        Extra top-level flags to forward (e.g. real embedding-service flags:
        ``--embedding-provider http --embedding-url ...``). When the real embedding
        / cross-encoder service is wired (FR-3), pass those flags here and every
        retrieval/calibration metric sharpens automatically with no harness change.
    """

    store: str
    backend: str = "local"
    postgres_dsn: str | None = None
    python: str = field(default_factory=lambda: sys.executable)
    global_flags: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 120.0

    def _base_argv(self) -> list[str]:
        argv = [self.python, "-m", "mnemosyne.cli", "--backend", self.backend]
        if self.backend == "postgres" and self.postgres_dsn:
            argv += ["--postgres-dsn", self.postgres_dsn]
        if self.backend == "local":
            argv += ["--store", self.store]
        argv += list(self.global_flags)
        return argv

    def _environ(self) -> dict[str, str]:
        environ = dict(os.environ)
        # Ensure the in-repo package is importable without an install step.
        existing = environ.get("PYTHONPATH", "")
        environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(_SRC), existing) if p)
        environ.update(self.env)
        return environ

    def run(
        self,
        command: str,
        *args: str,
        check: bool = True,
        parse_json: bool = True,
    ) -> CLIResult:
        """Run ``mneme <command> <args...>`` and capture timing + parsed JSON."""
        argv = self._base_argv() + [command, *args]
        start = time.perf_counter()
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=self._environ(),
            timeout=self.timeout_s,
        )
        wall_ms = (time.perf_counter() - start) * 1000.0
        stdout = strip_ansi(proc.stdout)
        stderr = strip_ansi(proc.stderr)
        result = CLIResult(
            argv=[command, *args],
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            wall_ms=wall_ms,
        )
        if check and proc.returncode != 0:
            raise CLIError(result.argv, proc.returncode, stdout, stderr)
        if parse_json:
            result.json = _try_parse_json(stdout)
        return result

    # ---- Convenience wrappers for the commands the harness exercises ----

    def capture(
        self,
        tenant: str,
        user: str,
        content: str,
        *,
        source_type: str = "chat",
        actor: str = "user",
        trust_tier: int | None = None,
        branch: str | None = None,
        source_identity: str | None = None,
        session_id: str | None = None,
        turn_index: int | None = None,
    ) -> dict[str, Any]:
        args = [
            "--tenant", tenant, "--user", user,
            "--actor", actor, "--source-type", source_type,
            "--content", content,
        ]
        if trust_tier is not None:
            args += ["--trust-tier", str(trust_tier)]
        if branch:
            args += ["--branch", branch]
        if source_identity:
            args += ["--source-identity", source_identity]
        if session_id:
            args += ["--session-id", session_id]
        if turn_index is not None:
            args += ["--turn-index", str(turn_index)]
        return self.run("capture", *args).json

    def capture_batch(self, input_jsonl: Path | str) -> dict[str, Any]:
        """Capture validated JSONL rows through one public CLI process."""
        return self.run("capture-batch", "--input-jsonl", str(input_jsonl)).json

    def eval_query_batch(self, input_jsonl: Path | str) -> dict[str, Any]:
        """Run validated search rows with embedded explanations in one process."""
        return self.run("eval-query-batch", "--input-jsonl", str(input_jsonl)).json

    def search(
        self,
        tenant: str,
        query: str,
        *,
        branch: str | None = None,
        min_trust_tier: int | None = None,
        max_trust_tier: int | None = None,
        max_sensitivity: int | None = None,
    ) -> dict[str, Any]:
        args = ["--tenant", tenant, "--query", query]
        if branch:
            args += ["--branch", branch]
        if min_trust_tier is not None:
            args += ["--min-trust-tier", str(min_trust_tier)]
        if max_trust_tier is not None:
            args += ["--max-trust-tier", str(max_trust_tier)]
        if max_sensitivity is not None:
            args += ["--max-sensitivity", str(max_sensitivity)]
        return self.run("search", *args).json

    def timed_search(self, tenant: str, query: str, **kwargs: Any) -> tuple[dict[str, Any], float]:
        """Run a search and also return the wall-clock latency in ms.

        Used by the fast-path P95 latency SLO test (blueprint §16). Note: this
        includes Python interpreter + process startup, so it is a *conservative
        upper bound* on the engine's own fast-path latency. The latency report
        records and labels this explicitly.
        """
        args = ["--tenant", tenant, "--query", query]
        branch = kwargs.get("branch")
        if branch:
            args += ["--branch", branch]
        if kwargs.get("max_trust_tier") is not None:
            args += ["--max-trust-tier", str(kwargs["max_trust_tier"])]
        res = self.run("search", *args)
        return res.json, res.wall_ms

    def explain(self, tenant: str, query: str, *, branch: str | None = None) -> dict[str, Any]:
        args = ["--tenant", tenant, "--query", query]
        if branch:
            args += ["--branch", branch]
        return self.run("explain", *args).json

    def forget(
        self,
        tenant: str,
        cid: str,
        *,
        branch: str | None = None,
        requested_by: str | None = None,
        role: str | None = None,
        source_trust_tier: int | None = None,
        erasure_mode: str | None = None,
    ) -> dict[str, Any]:
        args = ["--tenant", tenant, "--cid", cid]
        if branch:
            args += ["--branch", branch]
        if requested_by:
            args += ["--requested-by", requested_by]
        if role:
            args += ["--role", role]
        if source_trust_tier is not None:
            args += ["--source-trust-tier", str(source_trust_tier)]
        if erasure_mode:
            args += ["--erasure-mode", erasure_mode]
        return self.run("forget", *args).json

    def propose(
        self,
        tenant: str,
        user: str,
        subject: str,
        predicate: str,
        obj: str,
        *,
        evidence_cid: str | None = None,
        confidence: float | None = None,
        trust_tier: int | None = None,
        branch: str | None = None,
    ) -> dict[str, Any]:
        args = [
            "--tenant", tenant, "--user", user,
            "--subject", subject, "--predicate", predicate, "--object", obj,
        ]
        if evidence_cid:
            args += ["--evidence-cid", evidence_cid]
        if confidence is not None:
            args += ["--confidence", str(confidence)]
        if trust_tier is not None:
            args += ["--trust-tier", str(trust_tier)]
        if branch:
            args += ["--branch", branch]
        return self.run("propose", *args).json

    def confirm(
        self,
        assertion_id: str,
        *,
        tenant: str | None = None,
        branch: str | None = None,
        into: str | None = None,
        role: str | None = None,
        source_trust_tier: int | None = None,
        check: bool = True,
    ) -> CLIResult:
        args = ["--id", assertion_id]
        if tenant:
            args += ["--tenant", tenant]
        if branch:
            args += ["--branch", branch]
        if into:
            args += ["--into", into]
        if role:
            args += ["--role", role]
        if source_trust_tier is not None:
            args += ["--source-trust-tier", str(source_trust_tier)]
        return self.run("confirm", *args, check=check)

    def supersede(
        self,
        tenant: str,
        user: str,
        assertion_id: str,
        new: Mapping[str, Any],
        *,
        branch: str | None = None,
        confidence: float | None = None,
        role: str | None = None,
        source_trust_tier: int | None = None,
        check: bool = True,
    ) -> CLIResult:
        args = [
            "--tenant", tenant, "--user", user,
            "--id", assertion_id, "--new", json.dumps(new),
        ]
        if branch:
            args += ["--branch", branch]
        if confidence is not None:
            args += ["--confidence", str(confidence)]
        if role:
            args += ["--role", role]
        if source_trust_tier is not None:
            args += ["--source-trust-tier", str(source_trust_tier)]
        return self.run("supersede", *args, check=check)

    def branch(
        self,
        name: str,
        *,
        from_branch: str | None = None,
        kind: str | None = None,
        tenant: str | None = None,
        role: str = "operator",
        source_trust_tier: int = 0,
        check: bool = True,
    ) -> CLIResult:
        args = ["--name", name, "--role", role, "--source-trust-tier", str(source_trust_tier)]
        if from_branch:
            args += ["--from-branch", from_branch]
        if kind:
            args += ["--kind", kind]
        if tenant:
            args += ["--tenant", tenant]
        return self.run("branch", *args, check=check)

    def discard(
        self,
        branch_name: str,
        *,
        tenant: str | None = None,
        role: str = "operator",
        source_trust_tier: int = 0,
        check: bool = True,
    ) -> CLIResult:
        args = ["--branch", branch_name, "--role", role, "--source-trust-tier", str(source_trust_tier)]
        if tenant:
            args += ["--tenant", tenant]
        return self.run("discard", *args, check=check)

    def merge(
        self,
        from_branch: str,
        *,
        into: str | None = None,
        tenant: str | None = None,
        role: str = "operator",
        source_trust_tier: int = 0,
        check: bool = True,
    ) -> CLIResult:
        args = ["--from-branch", from_branch, "--role", role, "--source-trust-tier", str(source_trust_tier)]
        if into:
            args += ["--into", into]
        if tenant:
            args += ["--tenant", tenant]
        return self.run("merge", *args, check=check)

    def export(self, tenant: str) -> dict[str, Any]:
        return self.run("export", "--tenant", tenant).json

    def graph_as_of(
        self,
        tenant: str,
        subject: str,
        predicate: str,
        time_iso: str,
        *,
        branch: str | None = None,
    ) -> dict[str, Any]:
        args = [
            "--tenant", tenant, "--subject", subject,
            "--predicate", predicate, "--time", time_iso,
        ]
        if branch:
            args += ["--branch", branch]
        return self.run("graph-as-of", *args).json

    def belief_revision_check(
        self,
        cases_path: str,
        *,
        min_cases: int | None = None,
        require_case: list[str] | None = None,
    ) -> dict[str, Any]:
        args = ["--cases", cases_path]
        if min_cases is not None:
            args += ["--min-cases", str(min_cases)]
        for cid in require_case or []:
            args += ["--require-case", cid]
        # belief-revision-check exits non-zero when ok is False; we want the JSON
        # regardless so the harness can assert on it.
        return self.run("belief-revision-check", *args, check=False).json

    def calibration_tune(
        self,
        tenant: str,
        dataset: list[Mapping[str, Any]],
        *,
        memory_type: str | None = None,
        dry_run: bool = True,
        min_examples: int | None = None,
    ) -> dict[str, Any]:
        args = ["--tenant", tenant, "--dataset-json", json.dumps(list(dataset))]
        if memory_type:
            args += ["--memory-type", memory_type]
        if dry_run:
            args += ["--dry-run"]
        if min_examples is not None:
            args += ["--min-examples", str(min_examples)]
        return self.run("calibration-tune", *args, check=False).json


def _try_parse_json(text: str) -> Any | None:
    """Parse the last JSON document on stdout, tolerating leading log lines.

    The CLI prints a single JSON object for the commands the harness drives, but
    we are defensive: find the first ``{`` or ``[`` and attempt to decode from
    there.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back: locate the first JSON-looking span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None
