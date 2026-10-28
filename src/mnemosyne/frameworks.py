"""Proper Thinking's framework method, in one module.

A source (a skill's text, split into numbered units) becomes a framework the way Proper
Thinking AI builds one: typed nodes (definition, principle, step, warning, constraint, case,
example) with their definitive fields and epistemic tags, typed relations checked against
its edge taxonomy, a logic audit, purpose / audience / claimed and evidenced scope / overview,
a nine-section definitive document, a mechanical audit with repairs, and a judgment audit that
can send it back for another extraction. Prompts follow Proper Thinking's, and every auditor
reads whole nodes, not snippets; what does not depend on each other is sent side by side.

One rule is Mnemosyne's own: nothing in a source may be dropped. Every unit is cited by a node,
recorded as a duplicate, or listed unresolved - and an unresolved unit drives another pass.
"""

from __future__ import annotations

import contextvars
import copy
import hashlib
import http.client
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.2"
#: The model a conversion runs on (BurnOS's working model); per thread, so conversions side by
#: side keep their own.
MODEL: ContextVar[str] = ContextVar("framework_model", default="")
#: A folder where every answer of a conversion is kept, so a build cut off by a restart or a failed
#: call picks up where it stopped: a request with the same model, prompt and inputs is not asked twice.
CACHE: ContextVar[str] = ContextVar("framework_cache", default="")


@contextmanager
def cache_scope(path: str):
    """Context manager ensuring CACHE.set(...) is always paired with CACHE.reset(token)."""
    token = CACHE.set(path)
    try:
        yield token
    finally:
        CACHE.reset(token)


@contextmanager
def model_scope(model: str):
    """Context manager ensuring MODEL.set(...) is always paired with MODEL.reset(token)."""
    token = MODEL.set(model)
    try:
        yield token
    finally:
        MODEL.reset(token)


@contextmanager
def stats_scope(stats: dict[str, float] | None = None):
    """Context manager ensuring STATS.set(...) is always paired with STATS.reset(token)."""
    token = STATS.set({} if stats is None else stats)
    try:
        yield token
    finally:
        STATS.reset(token)


@contextmanager
def framework_context(*, cache: str | None = None, model: str | None = None, stats: dict[str, float] | None = None):
    """Safe execution context for framework contextvars, guaranteeing all tokens are reset."""
    tokens: list[tuple[ContextVar[Any], Any]] = []
    try:
        if cache is not None:
            tokens.append((CACHE, CACHE.set(cache)))
        if model is not None:
            tokens.append((MODEL, MODEL.set(model)))
        if stats is not None:
            tokens.append((STATS, STATS.set(stats)))
        yield
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)

MAX_PASSES = 2
FIELD_BATCH = 6
#: The most source one extraction prompt reads; a longer source (a book) is built part by part,
#: every part through the whole method, and the parts joined - so no passage is left out.
WINDOW_CHARS = 60_000
CHAPTER_WORKERS = 3
PARALLEL_WORKERS = 8
MAP_CONTEXT_CHARS = 12_000
GLOBAL_AUDIT_CHARS = 150_000
MAX_PROMPT_CHARS = 250_000
GAP = "Not specified in the source."
#: Seconds a step may take before it is asked again alongside: about twice the longest each step took
#: on gpt-5.2 (live runs, 18 Oct 2026), so only a real stall is sent twice.
PATIENCE = {"extract": 240.0, "extend": 240.0, "link": 240.0, "fields": 120.0, "edges": 120.0,
            "graph-repair": 160.0, "repair": 90.0, "logic": 60.0, "judge": 60.0, "meta": 45.0}
#: The least output room a call gets: a reasoning model thinks inside it, and is billed only for what it uses.
MIN_TOKENS = 16384
#: The running build's usage - calls, seconds, tokens in / cached / out, cost - when the caller counts it.
STATS: ContextVar[dict[str, float] | None] = ContextVar("framework_stats", default=None)
_STATS_LOCK = threading.Lock()
_CALLS = ThreadPoolExecutor(max_workers=24, thread_name_prefix="framework-call")
STEP_PREFIX = re.compile(r"^Step\s*\d+\s*[:.-]\s*", re.IGNORECASE)

NODE_TYPES = ("section", "definition", "principle", "step", "warning", "constraint", "case", "example")
EDGE_TYPES = ("supports", "implemented_by", "leads_to", "uses_definition", "constrains", "warns",
              "feeds_back_to", "refined_into", "exposes_problem_in", "drives_step", "tension")
_TAGGED = {"definition", "principle", "step", "warning", "constraint"}
#: Proper Thinking's definitive fields per node type (its template).
FIELDS: dict[str, str] = {
    "definition": '"Boundary": str, "Requires": [exact titles of other definitions, or []], '
                  '"Definition Source": "Author-defined"|"Framework-derived", "Operational Test": str',
    "principle": '"Statement": str, "Tier": "Governing"|"Operational", "Governs": str '
                 '("All steps" when it applies broadly), "Argument Chain": str',
    "step": '"Action": imperative str, "Done When": observable str, "Common Mistakes": [2-3 str or []], '
            '"Watch for": ["<warning title> - <risk>"], "Constrained by": ["<constraint title> - <limit>"], '
            '"In Practice": {"Case", "Context", "Action", "Outcome", "Lesson", "Tag"} (omit when no case)',
    "warning": '"The error": str, "Consequence": str, "Symptoms": [2-4 observable str], '
               '"Highest risk at": step title, "Tension pair": str (omit when unsupported)',
    "constraint": '"The condition": str, "If absent": what breaks, "Mitigation": str, "Affects": step title, '
                  '"Tension pair": str (omit when unsupported)',
    "case": '"Context": str, "Action": str, "Outcome": a metric or "qualitative only", "Lesson": str, '
            '"Tag": "First-hand"|"Second-hand"',
}
FIELDS["example"] = FIELDS["case"]
#: Proper Thinking's exact sentences for a field the source gives no basis for (its "book" is "source" here).
GAPS = {
    "Definition Source": "The source does not specify whether this term is author-defined or framework-derived.",
    "Operational Test": "The source does not specify an operational test by which two readers could agree whether "
                        "a case meets this definition.",
    "Action": "The source does not specify an imperative action for this step.",
    "Done When": "The source does not specify completion criteria for this step.",
    "Symptoms": "The source does not provide enough detail to list 2-4 observable symptoms for this warning; "
                "use the error description, consequence, and linked step for recognition.",
    "Mitigation": "The source does not provide a mitigation for this condition.",
}
#: Proper Thinking's per-type field rules (its Definitive System Feedback v2), word for word where they apply.
RULES = {
    "definition": (
        "Include Boundary when the source supports it. Requires is a JSON array of the exact titles of other "
        "definitions this term logically depends on, [] if none - never sentences or gap wording. Definition "
        "Source is exactly \"Author-defined\" or \"Framework-derived\" when the source supports either, otherwise "
        f"exactly: {GAPS['Definition Source']} Operational Test must be checkable from the text, otherwise "
        f"exactly: {GAPS['Operational Test']}"),
    "principle": (
        "Tier is \"Governing\" or \"Operational\". Governs is \"All steps\" when the principle applies broadly, "
        "otherwise the most specific applicable description. Argument Chain states why it holds, from the source."),
    "step": (
        f"Action is imperative (the procedure); if the source supports none, exactly: {GAPS['Action']} Done When "
        f"states observable completion criteria; if unsupported, exactly: {GAPS['Done When']} Common Mistakes: 2-3 "
        "concrete anti-patterns when inferable, else []. Watch for and Constrained by: each entry \"<Title> - "
        "<one-sentence risk or limit>\" from the given warnings and constraints; [] when none are given - never "
        "claim the source omitted them. Omit In Practice when no case is given; its Outcome names a metric or says "
        "\"qualitative only\". Omit inapplicable keys; never write \"N/A\"."),
    "warning": (
        "Symptoms is mandatory: 2-4 short observable signs of the error, or if the source cannot support them a "
        f"one-element array with exactly: {GAPS['Symptoms']} Highest risk at is the linked step's title, or \"The "
        "source does not specify the associated step for this warning.\" Omit Consequence or Tension pair only when "
        "unsupported."),
    "constraint": (
        "If absent says what breaks or fails without the condition, inferred from the condition and the source. "
        f"Mitigation is mandatory; when the source offers none, exactly: {GAPS['Mitigation']} Affects is the linked "
        "step's title, otherwise say the associated step is not specified. Omit Tension pair when unsupported."),
    "case": ("Outcome must name a specific metric or say \"qualitative only\". Tag is \"First-hand\" when the source "
             "shows the author was involved, otherwise \"Second-hand\"."),
}
RULES["example"] = RULES["case"]
#: Fields a node type may not leave out; the mechanical audit fills a missing one with GAP.
REQUIRED = {"step": ("Action", "Done When"), "warning": ("Symptoms",), "constraint": ("Mitigation",),
            "definition": ("Operational Test",)}
TAGS = (
    "For ES, EC, CT, CN give exactly one label each: ES in {Demonstrated, Argued, Asserted, Assumed}; "
    "EC in {Verbatim, Synthesized, Inferred}; CT in {Descriptive, Prescriptive, Evaluative}; CN in {Core, "
    "Supporting, Peripheral}. Infer them from how the source presents the content. \"Tag justifications\" "
    "gives one sentence per tag citing the quote."
)
#: Proper Thinking's edge taxonomy: a relation drawn the wrong way round is turned, not dropped.
#: (from_type, to_type, edge_type) -> (edge_type, flip)
REMAP: dict[tuple[str, str, str], tuple[str, bool]] = {
    ("step", "step", "implemented_by"): ("leads_to", False),
    ("warning", "step", "supports"): ("warns", False),
    ("constraint", "step", "supports"): ("constrains", False),
    ("step", "warning", "supports"): ("warns", True),
    ("step", "constraint", "supports"): ("constrains", True),
    ("definition", "step", "uses_definition"): ("uses_definition", True),
    ("definition", "principle", "uses_definition"): ("uses_definition", True),
    ("step", "constraint", "constrains"): ("constrains", True),
    ("step", "warning", "constrains"): ("warns", True),
    ("step", "warning", "warns"): ("warns", True),
    ("step", "case", "supports"): ("supports", True),
    ("step", "example", "supports"): ("supports", True),
    ("principle", "case", "supports"): ("supports", True),
    ("principle", "example", "supports"): ("supports", True),
    ("constraint", "case", "supports"): ("supports", True),
    ("constraint", "example", "supports"): ("supports", True),
    ("step", "principle", "implemented_by"): ("implemented_by", True),
    ("step", "principle", "drives_step"): ("drives_step", True),
}


# ---------------------------------------------------------------------------------- model


def _count(**amounts: float) -> None:
    """Add to the running build's usage (STATS), when one is being counted."""
    stats = STATS.get()
    if stats is not None:
        with _STATS_LOCK:
            for k, v in amounts.items():
                stats[k] = round(stats.get(k, 0) + (v or 0), 6)


def chat_json(system: str, user: str, max_tokens: int = 8192, task: str = "", shared: str = "",
              *, cache: str | None = None, model: str | None = None) -> dict[str, Any]:
    """One chat completion answered in JSON - on OpenRouter, or for a codex:<model> through the Codex
    program on the user's ChatGPT subscription; an empty or unreadable answer is asked again once.

    With ``shared`` (the source and the node list every call of a pass reads) the prompt is laid out
    for the provider's prompt cache: the fixed RULEBOOK, then ``shared``, then this call's task
    (``system`` and ``user``). Calls of one pass then differ only at their end, so the long start
    is read from the cache at a fraction of the price."""
    if cache is not None or model is not None:
        with framework_context(cache=cache, model=model):
            return chat_json(system, user, max_tokens, task, shared)
    if len(RULEBOOK) + len(system) + len(user) + len(shared) > MAX_PROMPT_CHARS:
        raise ValueError(f"{task or 'framework'} prompt exceeds the bounded input limit; source was not truncated")
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    cli = model.startswith("codex:")
    key = (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key and not cli:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    messages = ([{"role": "system", "content": RULEBOOK},
                 {"role": "user", "content": f"{shared}\n\n=== TASK ===\n{system}\n\n{user}"}] if shared else
                [{"role": "system", "content": system}, {"role": "user", "content": user}])
    payload: dict[str, Any] = {
        # a reasoning model's thinking counts against max_tokens: never so little that it eats the answer
        "model": model, "max_tokens": max(max_tokens, MIN_TOKENS), "temperature": 0,
        "reasoning": {"effort": "medium"}, "usage": {"include": True},
        "response_format": {"type": "json_object"},  # code quoted in a source broke hand-made JSON
        "messages": messages}
    if shared:  # keeps one pass's calls on the same provider cache
        payload["prompt_cache_key"] = hashlib.sha256(shared.encode("utf-8")).hexdigest()[:32]
    body = json.dumps(payload)
    kept = os.path.join(CACHE.get(), hashlib.sha256(body.encode("utf-8")).hexdigest() + ".json") if CACHE.get() else ""
    if kept and os.path.exists(kept):
        _count(answers_from_cache=1)
        with open(kept, encoding="utf-8") as f:
            return json.load(f)

    def post() -> dict[str, Any]:
        server = SERVER.get()
        if cli and server and shared:  # a branch of the thread that already holds ``shared``
            return server.ask(shared, messages[1]["content"][len(shared):].lstrip())
        if cli:
            return _codex(messages[0]["content"], messages[1]["content"], model.split(":", 1)[1].strip())
        return _post(body.encode("utf-8"), key)

    # A provider now and then sits on a request for minutes. When one has not answered well past the
    # time that step really takes, the same request goes again and the first answer wins. Not on a
    # subscription: a second copy would only spend its limit faster.
    patience = PATIENCE.get(task, 120.0)
    for attempt in range(2):
        started = time.monotonic()
        first = _CALLS.submit(contextvars.copy_context().run, post)
        done, _ = wait([first], timeout=None if cli else patience)
        racers = [first] if done else [first, _CALLS.submit(contextvars.copy_context().run, post)]
        if not done:
            log.info("framework call %s: no answer after %.0f s, asking again alongside", task, patience)
        done, _ = wait(racers, return_when=FIRST_COMPLETED)
        data = next(iter(done)).result()
        if data.get("error"):
            raise RuntimeError(f"OpenRouter error: {data['error']}")
        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        _count(calls=1, seconds=time.monotonic() - started, tokens_in=usage.get("prompt_tokens"),
               tokens_cached=cached, tokens_out=usage.get("completion_tokens"), cost_usd=usage.get("cost"))
        log.info("framework call %s on %s: %.1f s, %s tokens in (%s cached), %s out", task, model,
                 time.monotonic() - started, usage.get("prompt_tokens"), cached, usage.get("completion_tokens"))
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        # Only a fence AROUND the answer is taken off: a skill's own ``` blocks sit inside its strings.
        text = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", content)
        if not text.startswith("{") and "{" in text:  # a sentence before or after the JSON
            text = text[text.index("{"): text.rindex("}") + 1]
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                if kept:
                    os.makedirs(os.path.dirname(kept), exist_ok=True)
                    pending = None
                    try:
                        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(kept),
                                                         prefix=".framework-", suffix=".tmp", delete=False) as f:
                            pending = f.name
                            json.dump(parsed, f)
                        os.replace(pending, kept)
                    finally:
                        if pending and os.path.exists(pending):
                            os.unlink(pending)
                return parsed
        except json.JSONDecodeError:
            pass
        log.warning("framework call %s: no JSON in the answer (attempt %s): %.200r", task, attempt + 1, content)
    return {}


_HOST = OPENROUTER_URL.split("/")[2]
_PATH = "/" + OPENROUTER_URL.split("/", 3)[3]
_LINK = threading.local()


def _post(body: bytes, key: str) -> dict[str, Any]:
    """One request on this thread's kept-open connection (no new TLS handshake per call); a
    connection the server has dropped is opened again once."""
    for fresh in (False, True):
        conn = getattr(_LINK, "conn", None)
        if conn is None or fresh:
            conn = _LINK.conn = http.client.HTTPSConnection(_HOST, timeout=600)
        try:
            conn.request("POST", _PATH, body, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            return json.loads(conn.getresponse().read().decode("utf-8"))
        except (http.client.HTTPException, OSError):
            conn.close()
            _LINK.conn = None
            if fresh:
                raise
    raise AssertionError("unreachable")


#: Codex programs running at once. At 8, a 9-part book's field calls spent most of their time queued
#: (44 s alone, 207 s on average, 18 Oct 2026). shortcut: a fixed number, not the subscription's real
#: rate limit; lower it if a long book reports a usage limit.
_CODEX_AT_ONCE = threading.BoundedSemaphore(12)  # about 20 at once dropped the backend's streams
#: Turns at once on one Codex server, each on a branch holding a whole book. At about 20 at once the
#: ChatGPT backend dropped streams ("workspace routing discovery timed out") and the build stalled;
#: 8 answered at once in 3 s (18 Oct 2026). shortcut: measured once; raise it if the backend allows.
_CODEX_TURNS = threading.BoundedSemaphore(8)


def _codex(system: str, user: str, name: str) -> dict[str, Any]:
    """One answer from the official Codex program, signed in with the user's ChatGPT account (its
    login is never read here), shaped like an OpenRouter reply. It only writes the answer: no
    user config, no MCP servers, a read-only sandbox in an empty folder."""
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("codex")
    if not exe:
        raise RuntimeError("the Codex program is not installed, so a codex: model cannot build a BurnSkill")
    prompt = (f"{system}\n\nAnswer from the text below alone - do not run commands or read files - and "
              f"reply with the JSON only.\n\n{user}")
    for pause in (15, 30, 60, 120, 0):
        queued = time.monotonic()
        with _CODEX_AT_ONCE, tempfile.TemporaryDirectory(prefix="mnemosyne-codex-") as tmp:
            _count(seconds_queued=time.monotonic() - queued)  # waiting for a free slot, not for the model
            reply = os.path.join(tmp, "reply.txt")
            args = [exe, "exec", "--ignore-user-config", "-c", "mcp_servers={}", "-c", 'model_reasoning_effort="medium"',
                    "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "-C", tmp, "-o", reply]
            if name and name != "default":
                args += ["-m", name]
            try:
                run = subprocess.run([*args, "-"], input=prompt.encode("utf-8"), capture_output=True, timeout=1200,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired:
                return {"choices": [{"message": {"content": ""}}]}  # asked again once by the caller
            text = open(reply, encoding="utf-8").read() if os.path.exists(reply) else ""
        if text.strip():
            break
        kind, why = codex_failure((run.stderr + run.stdout).decode("utf-8", "replace"))
        if kind == "fatal":
            raise RuntimeError(f"Codex: {why}")  # a used-up subscription or a lost login will not answer again
        if kind != "busy" or not pause:
            break
        log.info("Codex busy (%s); asking again in %s s", why, pause)
        time.sleep(pause)
    return {"choices": [{"message": {"content": text}}]}


def codex_failure(output: str) -> tuple[str, str]:
    """Why a Codex call gave no answer: "busy" (the model is at capacity, overloaded or rate-limited for a
    moment - asked again after a wait), "fatal" (the usage limit is used up, or the login is gone), or
    "" (unknown - asked again once by the caller). Lines from its own MCP plugins are noise."""
    lines = [line for line in output.splitlines() if "ERROR" in line.upper() and "rmcp::" not in line]
    why = " ".join(lines)[-300:]
    if re.search(r"at capacity|overloaded|try again|temporarily|rate limit|too many requests|\b(429|5\d\d)\b", why, re.I):
        return "busy", why
    if re.search(r"usage limit|quota|not logged in|log ?in again|unauthori[sz]ed|\b401\b", why, re.I):
        return "fatal", why
    return "", why


class CodexServer:
    """One long-lived official `codex app-server` for a build, on the user's ChatGPT login (never read
    here): no program start per call. Every call starts with the same text, served from the
    provider's prompt cache.

    Isolated for this process only: the user's MCP servers, plugins, hooks and tools are switched
    off, and Codex's own instructions are replaced by the RULEBOOK."""

    def __init__(self, model: str) -> None:
        import shutil
        import subprocess
        import tempfile

        exe = shutil.which("codex")
        if not exe:
            raise RuntimeError("the Codex program is not installed, so a codex: model cannot build a BurnSkill")
        self.model = model
        self.tmp = tempfile.mkdtemp(prefix="mnemosyne-codex-")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        config = self._user_config(exe, flags)
        off = ["--disable", "hooks", "--disable", "shell_tool", "--disable", "unified_exec", "--disable", "view_image",
               "--disable", "memories", "-c", "mcp_servers={}", "-c", "include_environment_context=false",
               "-c", "include_apps_instructions=false", "-c", "include_permissions_instructions=false",
               "-c", "include_collaboration_mode_instructions=false"]
        for name in config.get("plugins") or {}:  # a plugin brings its own servers, hooks and instructions
            off += ["-c", f'plugins."{name}".enabled=false']
        self.proc = subprocess.Popen([exe, "app-server", *off], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, cwd=self.tmp, creationflags=flags)
        self.replies: dict[int, dict[str, Any]] = {}
        self.done: dict[str, dict[str, Any]] = {}  # turn id -> its end: text, usage, error
        self.events = threading.Condition()
        self.ids = iter(range(1, 10**9))
        self.write_lock = threading.Lock()
        self.closed = False
        threading.Thread(target=self._read, name="codex-app-server", daemon=True).start()
        self._call("initialize", {"clientInfo": {"name": "mnemosyne", "version": "1"}})
        self._send({"method": "initialized"})

    @staticmethod
    def _user_config(exe: str, flags: int) -> dict[str, Any]:
        """The user's Codex config, read from a throwaway server: which plugins to switch off."""
        import subprocess

        probe = subprocess.Popen([exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            for i, method in ((0, "initialize"), (1, "config/read")):
                params = {"clientInfo": {"name": "mnemosyne", "version": "1"}} if i == 0 else {}
                probe.stdin.write((json.dumps({"id": i, "method": method, "params": params}) + "\n").encode())
                probe.stdin.flush()
                while (msg := json.loads(probe.stdout.readline() or b"{}")).get("id") != i or "method" in msg:
                    if not msg:
                        return {}
            return (msg.get("result") or {}).get("config") or {}
        finally:
            probe.kill()

    def _send(self, msg: dict[str, Any]) -> None:
        with self.write_lock:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            self.proc.stdin.flush()

    def _read(self) -> None:
        texts: dict[str, str] = {}
        usage: dict[str, dict[str, Any]] = {}
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            method, params = msg.get("method"), msg.get("params") or {}
            if "id" in msg and method:  # the server asks for something (an approval): never, answered off
                log.info("codex asks %s: %.300s", method, json.dumps(params))  # this thread, which must keep reading
                threading.Thread(target=self._send, args=({"id": msg["id"], "result": {"decision": "decline"}},),
                                 daemon=True).start()
                continue
            if method in ("error", "warning", "configWarning", "model/rerouted"):
                log.info("codex %s: %.400s", method, json.dumps(params))
            with self.events:
                if "id" in msg:
                    self.replies[msg["id"]] = msg
                elif method == "item/completed" and (params.get("item") or {}).get("type") == "agentMessage":
                    texts[params.get("turnId") or ""] = params["item"].get("text") or ""
                elif method == "thread/tokenUsage/updated":
                    usage[params.get("turnId") or ""] = (params.get("tokenUsage") or {}).get("last") or {}
                elif method == "turn/completed":
                    turn = params.get("turn") or {}
                    text = texts.pop(turn.get("id"), "") or next(
                        (i.get("text") or "" for i in reversed(turn.get("items") or []) if i.get("type") == "agentMessage"), "")
                    self.done[turn.get("id")] = {"text": text, "usage": usage.pop(turn.get("id"), {}),
                                                 "status": turn.get("status"), "error": turn.get("error")}
                self.events.notify_all()
        with self.events:
            self.closed = True
            self.events.notify_all()

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        i = next(self.ids)
        self._send({"id": i, "method": method, "params": params})
        with self.events:
            if not self.events.wait_for(lambda: i in self.replies or getattr(self, "closed", False), timeout=120):
                raise RuntimeError(f"Codex did not answer {method}")
            reply = self.replies.pop(i, None)
        if reply is None or "error" in reply:
            raise RuntimeError(f"Codex {method}: {(reply or {}).get('error', 'the program stopped')}")
        return reply.get("result") or {}

    def _turn(self, thread: str, text: str) -> dict[str, Any]:
        started = self._call("turn/start", {"threadId": thread, "input": [{"type": "text", "text": text}],
                                            "effort": "medium"})
        tid = started["turn"]["id"]
        with self.events:
            if not self.events.wait_for(lambda: tid in self.done or getattr(self, "closed", False), timeout=1200):
                self._call("turn/interrupt", {"threadId": thread, "turnId": tid})
                return {"text": "", "usage": {}}  # asked again once by the caller
            end = self.done.pop(tid, {"status": "failed", "error": {"message": "the program stopped"}})
        if end.get("status") == "failed":
            why = json.dumps(end.get("error") or {})[:400]
            raise RuntimeError(f"Codex: {why}")  # a used-up limit or a lost login will not answer again
        return end

    def ask(self, shared: str, task: str) -> dict[str, Any]:
        """One task in a throwaway conversation: the fixed RULEBOOK as its instructions, then ``shared``
        (the book, the map, the part's nodes) and the task in one message. Every call starts with the
        same text, so the provider serves that start from its prompt cache - the model does not read
        the book again (the cached-token counts show it). Shaped like an OpenRouter reply.

        Not branches of one reading (thread/fork): with forks made while other turns ran, the Codex
        server stopped answering thread/fork (0.163.0, 18 Oct 2026)."""
        queued = time.monotonic()
        with _CODEX_TURNS:
            _count(seconds_queued=time.monotonic() - queued)
            thread = self._call("thread/start", {
                "model": self.model, "cwd": self.tmp, "sandbox": "read-only", "approvalPolicy": "never",
                "ephemeral": True, "baseInstructions": RULEBOOK})["thread"]["id"]
            try:
                end = self._turn(thread, f"{shared}\n\n{task}")
            finally:
                try:  # nothing of it is kept
                    self._call("thread/unsubscribe", {"threadId": thread})
                except Exception:  # noqa: BLE001
                    pass
        use = end.get("usage") or {}
        return {"choices": [{"message": {"content": end.get("text") or ""}}],
                "usage": {"prompt_tokens": use.get("inputTokens"), "completion_tokens": use.get("outputTokens"),
                          "prompt_tokens_details": {"cached_tokens": use.get("cachedInputTokens")}}}

    def close(self) -> None:
        import shutil

        self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


#: The build's Codex server, when it runs on a codex: model.
SERVER: ContextVar[CodexServer | None] = ContextVar("framework_codex_server", default=None)


#: What one part of a book (up to WINDOW_CHARS) is reckoned to cost on OpenRouter. shortcut: a rough
#: figure from the 18 Oct 2026 live runs; replace it with the average of the builds' recorded usage.
PART_COST_USD = 3.0


def check_credit(units: list[str]) -> None:
    """Before an OpenRouter build: refuse it, before any call, when the key's remaining credit cannot
    cover it - rather than stopping halfway when the limit is reached. A subscription has no charge."""
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if model.startswith("codex:") or not key:
        return
    conn = http.client.HTTPSConnection(_HOST, timeout=30)
    try:
        conn.request("GET", "/api/v1/key", headers={"Authorization": f"Bearer {key}"})
        left = (json.loads(conn.getresponse().read().decode("utf-8")).get("data") or {}).get("limit_remaining")
    except (OSError, http.client.HTTPException, ValueError):
        return  # the check is a courtesy; the build itself still reports a real limit
    finally:
        conn.close()
    need = PART_COST_USD * len(windows(units))
    if left is not None and float(left) < need:
        raise RuntimeError(f"the OpenRouter key has ${float(left):.2f} of credit left and this build needs about "
                           f"${need:.0f}; raise the key's limit, or build with a codex: model on the ChatGPT subscription")


def _int(value: Any) -> int | None:
    """An index the model gave, as a number or as a string of digits."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.strip().isdigit() else None


def _parallel(calls: list[Callable[[], Any]], *, workers: int = PARALLEL_WORKERS) -> list[Any]:
    """Run the calls side by side, each in a copy of this thread's context (the model)."""
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(calls)))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, c) for c in calls]
        return [f.result() for f in futures]


def _units_block(units: list[str], numbers: list[int] | None = None) -> str:
    """The units by their number in the whole source - all of them, or one part's."""
    return "\n\n".join(f"[Unit {i}]\n{units[i - 1]}" for i in (range(1, len(units) + 1) if numbers is None else numbers))


def _nodes_block(nodes: list[dict[str, Any]], fields: bool = False) -> str:
    """Every node with its whole content - and, for the auditors, its definitive fields and tags."""
    return "\n".join(f"[{n['id']}] {n['type']}: {n['title']} - {' '.join(n['content'].split())}"
                     + (f"\n    fields: {json.dumps(n['fields'], ensure_ascii=False)}" if fields and n['fields'] else "")
                     + (f"\n    chapter contributions: {json.dumps(n['contributions'], ensure_ascii=False)}"
                        if fields and n.get("contributions") else "")
                     for n in nodes)


def _edges_block(edges: list[dict[str, Any]]) -> str:
    return "\n".join(f"{e['from']} -[{e['type']}]-> {e['to']}: {e.get('why') or ''}"
                     + ("\nChapter relationship evidence: " + json.dumps(e["contributions"], ensure_ascii=False)
                        if e.get("contributions") else "") for e in edges) or "none"


def _source(name: str, units: list[str], numbers: list[int] | None) -> str:
    """The start every call of a pass shares: the name and the units it is built from. A joined
    book (no ``numbers``) is too long for one prompt and stands here as its nodes."""
    book = BOOK.get()
    if book and not numbers:
        return f"{book}\n\nTHE WHOLE BOOK'S FRAMEWORK, joined from its chapters, follows."
    if book:  # read once already: this part is a pointer into it, never a second copy of its text
        context = _map_for_parts(BOOK_MAP.get() or {}, numbers)
        return (f"{book}\n\nBOOK MAP CONTEXT (bounded to this part):\n{json.dumps(context, ensure_ascii=False)}"
                f"\n\nTHIS PART: {LABEL.get() or 'a part'} - units {numbers[0]}-{numbers[-1]} of {len(units)}. "
                "Work on these units only; the other chapters are built beside it. Use the BOOK MAP: title a "
                "definition with its glossary term exactly, and create a definition node only for glossary terms "
                "this chapter defines (or key terms the glossary lacks); title the steps of the book's spine exactly "
                "as the map does. For a relation to a node of another chapter, give the node \"cross\": [{\"to\": the "
                "exact glossary term or spine title, \"type\": edge type, \"why\": one sentence}]."
                f"\n\nSOURCE ({len(numbers)} units):\n{_units_block(units, numbers)}")
    if not numbers:
        return (f"Framework name: {name}\n\nSOURCE: a whole book of {len(units)} units, too long for one prompt; "
                "the framework nodes below were built from all of it, part by part, and cite every unit.")
    part = (f"This is one part of a longer book: units {numbers[0]}-{numbers[-1]} of {len(units)}. The other parts "
            "are built beside it.\n\n") if len(numbers) < len(units) else ""
    return f"Framework name: {name}\n\n{part}SOURCE ({len(numbers)} units):\n{_units_block(units, numbers)}"


def _shared(fw: dict[str, Any], units: list[str]) -> str:
    """The source and the framework's nodes: the same for every call after extraction in one pass."""
    return f"{_source(fw['name'], units, fw.get('numbers'))}\n\nFRAMEWORK NODES (by id):\n{_nodes_block(fw['nodes'])}"


# ---------------------------------------------------------------------------------- passes


EXTRACT_SYSTEM = (
    "You are a disciplined reasoning engine. Output ONLY valid JSON: {\"nodes\": [ ... ]}. Each node:\n"
    "- type: one of section, definition, principle, step, warning, constraint, case, example.\n"
    "- title: 5-60 characters. One term per definition node - never combine two terms in one.\n"
    "- content: 1-3 short paragraphs of clear sentences (quote or explanation).\n"
    "- parent: null for top-level section nodes, otherwise the 0-based index of the parent node.\n"
    "- depends_on: null or the 0-based index of a node this one logically or procedurally relies on.\n"
    "- units: the numbers of the source units this node comes from.\n"
    "Rules: use ONLY the provided units, no outside knowledge. Start with a few top-level section nodes "
    "(Definitions, Core Principles, Procedures, Warnings & Pitfalls, Constraints & Assumptions, Examples & "
    "Cases); every other node has a parent. Definitions fix the meaning of terms; principles state causal or "
    "normative claims; steps are concrete actions in order; cases and examples illustrate, they are never "
    "rules; warnings are cautions (title 'Warning: ...') and constraints are required conditions (title "
    "'Constraint: ...'). Never mix roles in one node. Parents come before children. Use terms consistently "
    "with their definitions; avoid equivocation and category errors. EVERY unit must be cited by at least "
    "one node - represent all of the source, not a summary of it. Give only those six keys (and \"cross\" "
    "when this part's instructions ask for it): the definitive fields, quotes and epistemic tags are "
    "written by later tasks."
)


def _node(item: dict[str, Any], i: int, allowed: set[int]) -> dict[str, Any]:
    ntype = str(item.get("type") or "section").strip().lower()
    return {"id": i, "type": ntype if ntype in NODE_TYPES else "section",
            "title": str(item.get("title") or f"Item {i + 1}").strip()[:120],
            "content": str(item.get("content") or "").strip(),
            "parent": _int(item.get("parent")), "depends_on": _int(item.get("depends_on")),
            "units": sorted({u for u in map(_int, item.get("units") or []) if u in allowed}), "fields": {},
            "cross": [c for c in item.get("cross") or [] if isinstance(c, dict) and c.get("to")][:20]}


def _no_dangling(nodes: list[dict[str, Any]]) -> None:
    for n in nodes:  # an index that points nowhere is no link
        for key in ("parent", "depends_on"):
            if not (isinstance(n[key], int) and 0 <= n[key] < len(nodes) and n[key] != n["id"]):
                n[key] = None


def extract(name: str, units: list[str], instructions: str = "", numbers: list[int] | None = None) -> list[dict[str, Any]]:
    """The nodes of the whole source, or of one part of a book (``numbers``: its unit numbers)."""
    numbers = numbers or list(range(1, len(units) + 1))
    extra = f"RE-EXTRACTION (mandatory; still use only the units):\n{instructions}\n\n" if instructions else ""
    data = chat_json(EXTRACT_SYSTEM, f"{extra}Output the JSON nodes array for every unit above.", 32000, "extract",
                     shared=_source(name, units, numbers))
    raw = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    nodes = [_node(item, i, set(numbers)) for i, item in enumerate(r for r in raw if isinstance(r, dict))]
    _no_dangling(nodes)
    if not nodes:
        raise ValueError("the model returned no framework nodes")
    return nodes


EXTEND_SYSTEM = (
    "The framework above was judged incomplete. Repair it by the instructions below WITHOUT rebuilding it: "
    "add the nodes that are missing and correct the nodes named as wrong; everything else stays as it is. "
    "Output ONLY valid JSON: {\"add\": [new nodes, each with type, title, content, parent, depends_on, units "
    "exactly as in extraction], \"change\": [{\"id\": an existing id, and only the keys that change among "
    "type, title, content, parent, depends_on, units}]}. New nodes take the ids {next}, {next}+1, ... in the order "
    "given; parent and depends_on may name any existing or new id. Use ONLY the source units.\n\nExtraction rules:\n"
)


def extend(fw: dict[str, Any], units: list[str], instructions: str) -> set[int]:
    """Proper Thinking's re-extraction as a repair: only the missing nodes are added and the wrong ones
    corrected, so the finished nodes keep their fields. Returns the ids added or changed."""
    nodes, allowed = fw["nodes"], set(fw["numbers"])
    data = chat_json(EXTEND_SYSTEM.replace("{next}", str(len(nodes))) + EXTRACT_SYSTEM,
                     f"REPAIR INSTRUCTIONS:\n{instructions}", 32000, "extend", shared=_shared(fw, units))
    touched: set[int] = set()
    for change in [c for c in data.get("change") or [] if isinstance(c, dict)]:
        idx = _int(change.get("id"))
        if idx is None or not 0 <= idx < len(nodes):
            continue
        fresh = _node({**nodes[idx], **change}, idx, allowed)
        nodes[idx].update({k: fresh[k] for k in ("type", "title", "content", "parent", "depends_on", "units")},
                          fields={})
        touched.add(idx)
    for item in [a for a in data.get("add") or [] if isinstance(a, dict)]:
        nodes.append(_node(item, len(nodes), allowed))
        touched.add(len(nodes) - 1)
    _no_dangling(nodes)
    return touched


FIELDS_SYSTEM = (
    "Write the definitive template fields of the items below, by the rulebook's fields and rules for each "
    "item's type. Output ONLY valid JSON: {\"items\": [{\"index\": int, \"fields\": {...}, \"epistemic_type\": "
    "\"fact\"|\"interpretation\"|\"assumption\", \"epistemic_note\": one line}]}. Use ONLY each item's content and "
    "the source units it cites; never invent concepts. Where a rule gives an exact sentence for a field the "
    f"source does not support, use it word for word; for any other unsupported field write \"{GAP}\"."
)


def fill_fields(fw: dict[str, Any], units: list[str], only: set[int] | None = None) -> list[Callable[[], None]]:
    """The definitive-fields calls, one per batch of nodes (``only``: just those ids), to run side by side."""
    nodes = fw["nodes"]
    shared = _shared(fw, units)

    def related(n: dict[str, Any], kind: tuple[str, ...]) -> list[str]:
        return [m["title"] for m in nodes if m["depends_on"] == n["id"] and m["type"] in kind]

    items = []
    for n in nodes:
        if n["type"] == "section" or (only is not None and n["id"] not in only):
            continue
        dep = nodes[n["depends_on"]] if n["depends_on"] is not None else None
        item = {"index": n["id"], "type": n["type"], "title": n["title"], "units": n["units"],
                "depends_on": f"{dep['type']}: {dep['title']}" if dep else ""}
        if n["type"] == "step":
            item |= {"warnings": related(n, ("warning",)), "constraints": related(n, ("constraint",)),
                     "cases": related(n, ("case", "example"))}
        if n["type"] == "definition":
            item["other_definitions"] = [m["title"] for m in nodes if m["type"] == "definition" and m is not n]
        items.append(item)

    def batch(chunk: list[dict[str, Any]]) -> None:
        assigned = {item["index"] for item in chunk}
        data = chat_json(FIELDS_SYSTEM, f"Items:\n{json.dumps(chunk, ensure_ascii=False)}", 8192, "fields", shared=shared)
        for out in data.get("items") or []:
            idx = _int(out.get("index")) if isinstance(out, dict) else None
            if idx in assigned:
                if isinstance(out.get("fields"), dict):
                    nodes[idx]["fields"] = out["fields"]
                if out.get("epistemic_type") in ("fact", "interpretation", "assumption"):
                    nodes[idx]["epistemic_type"] = out["epistemic_type"]
                    nodes[idx]["epistemic_note"] = str(out.get("epistemic_note") or "")[:200]

    return [lambda c=items[i:i + FIELD_BATCH]: batch(c) for i in range(0, len(items), FIELD_BATCH)]


def repair_fields(fw: dict[str, Any], units: list[str]) -> list[Callable[[], None]]:
    """Proper Thinking's tag and quote repair passes, only for the items that need one: a tagged item
    with missing ES/EC/CT/CN or no Source Quote although it cites source. Empty when nothing failed."""
    nodes = fw["nodes"]
    shared = _shared(fw, units)
    weak = [n for n in nodes if n["type"] != "section" and n["units"] and (
        (n["type"] in _TAGGED and not all(n["fields"].get(t) for t in ("ES", "EC", "CT", "CN"))) or _quote_errors(n, units))]

    def batch(chunk: list[dict[str, Any]]) -> None:
        assigned = {item["id"] for item in chunk}
        items = [{"index": n["id"], "type": n["type"], "title": n["title"], "units": n["units"],
                  "current_quote": n["fields"].get("Source Quote"), "validation_failures": _quote_errors(n, units)} for n in chunk]
        system = ("These framework items have missing or invalid evidence tags or quotes. Correct only the "
                  "reported defects, preserving valid fields. Output ONLY valid JSON: {\"items\": "
                  "[{\"index\": int, \"Source Quote\": {\"Quote\": at most 60 words copied from the units the item "
                  "cites, \"Core Sentence\": its most evidential sentence}, \"ES\", \"EC\", \"CT\", \"CN\", "
                  "\"Tag justifications\"}]}. " + TAGS + " Never use gap wording for tags; pick the closest label.")
        data = chat_json(system, f"Mechanical repair pass {fw.get('passes', 1)}.\nItems:\n{json.dumps(items, ensure_ascii=False)}",
                         8192, "repair", shared=shared)
        for out in data.get("items") or []:
            idx = _int(out.get("index")) if isinstance(out, dict) else None
            if idx in assigned:
                for key in ("Source Quote", "ES", "EC", "CT", "CN", "Tag justifications"):
                    invalid_quote = key == "Source Quote" and bool(_quote_errors(nodes[idx], units))
                    if out.get(key) and (invalid_quote or not nodes[idx]["fields"].get(key)):
                        nodes[idx]["fields"][key] = out[key]

    return [lambda c=weak[i:i + FIELD_BATCH]: batch(c) for i in range(0, len(weak), FIELD_BATCH)]


EDGES_SYSTEM = (
    "You map the relations of a framework. Output ONLY valid JSON: {\"edges\": "
    "[{\"from\": id, \"to\": id, \"type\": ..., \"why\": one sentence}]}.\nEdge types: supports (case/example "
    "-> step or principle), implemented_by (principle -> step only), leads_to (earlier step -> later step), "
    "uses_definition (step or principle -> definition), constrains (constraint -> step), warns (warning -> "
    "step), feeds_back_to (last step of a cycle -> first step), refined_into (case/definition -> principle), "
    "exposes_problem_in (case -> what it shows failing), drives_step (principle -> step), tension (two "
    "warnings/constraints that are opposite failure modes; why names the balance to hold). Make the full "
    "step order explicit; link each step to the definitions it uses and the warnings and constraints on it. "
    "Only the given ids; omit what you are unsure of."
)
LOGIC_SYSTEM = (
    "You are the Logic Auditor of a framework: its nodes and the relations drawn between them. Output ONLY "
    "valid JSON: {\"graph_issues\": [str], \"logic_issues\": [str], \"logic_warnings\": [str], \"note\": str}. "
    "logic_issues are serious contradictions, gaps, unstated assumptions, undefined terms, equivocation or "
    "category errors; logic_warnings are minor; graph_issues are structural problems in the relations - a "
    "missing step order, a relation drawn the wrong way, a step with no definition it plainly uses. Use [] when none."
)


def relate(fw: dict[str, Any], units: list[str]) -> None:
    data = chat_json(EDGES_SYSTEM, "Draw the relations between the framework nodes above.", 8192, "edges",
                     shared=_shared(fw, units))
    fw["edges"] = tidy_edges(fw["nodes"], data.get("edges") if isinstance(data.get("edges"), list) else [])


def _logic(fw: dict[str, Any], units: list[str]) -> dict[str, Any]:
    shared = _shared(fw, units)
    relations = f"Relations:\n{_edges_block(fw['edges'])}"
    if not fw.get("numbers"):
        # The global reviewer sees complete fields and all preserved chapter contributions.
        shared = f"{_source(fw['name'], units, None)}\n\nFRAMEWORK NODES:\n{_nodes_block(fw['nodes'], fields=True)}"
        if len(shared) + len(relations) > GLOBAL_AUDIT_CHARS:
            return _bounded_logic(fw, units)
    data = chat_json(LOGIC_SYSTEM, relations, 8192, "logic", shared=shared)
    logic = _logic_result(data)
    logic["note"] = str(data.get("note") or "")
    return logic


def _logic_result(data: dict[str, Any]) -> dict[str, Any]:
    keys = ("graph_issues", "logic_issues", "logic_warnings")
    if not isinstance(data, dict) or any(not isinstance(data.get(key), list) for key in keys):
        return {"graph_issues": [], "logic_issues": ["Logic audit did not return a valid result; review is incomplete."],
                "logic_warnings": []}
    return {key: [str(item) for item in data[key]] for key in keys}


def _bounded_logic(fw: dict[str, Any], units: list[str]) -> dict[str, Any]:
    """Review every original contribution, then canonical edges with explicit endpoint views.

    Merging repeated chapter content must not make a book indivisible. The stored node stays whole;
    an audit view retains one original contribution and its canonical identity. Edge checks select
    a pair of endpoint views, preferring a shared chapter. They are not a Cartesian comparison of
    every wording of the two nodes, and the recorded scope makes that limitation explicit.
    """
    nodes, edges = fw["nodes"], fw["edges"]
    views: dict[str, dict[str, Any]] = {}
    by_node: dict[int, list[str]] = {}
    for n in nodes:
        contributions = n.get("contributions") or [n]
        for index, contribution in enumerate(contributions):
            identity = f"{n['id']}:{index}"
            view = copy.deepcopy(contribution)
            view.pop("contributions", None)
            view.update(id=n["id"], audit_view=identity, canonical_title=n["title"],
                        contribution_index=index, contribution_count=len(contributions))
            views[identity] = view
            by_node.setdefault(n["id"], []).append(identity)
    blocks = {identity: json.dumps(view, ensure_ascii=False) for identity, view in views.items()}
    header = _source(fw["name"], units, None) + "\n\nFRAMEWORK NODE BATCH:\n"
    batches: list[tuple[list[str], str, str, set[int], list[str]]] = []
    failures: list[str] = []
    reviewed_edges: set[int] = set()
    edge_views: dict[int, tuple[str, str]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    evidence_endpoints: dict[str, list[str]] = {}
    reviewed_evidence: set[str] = set()
    for position, edge in enumerate(edges):
        for index, contribution in enumerate(edge.get("contributions") or [edge]):
            identity = f"{position}:{index}"
            evidence[identity] = {**copy.deepcopy(contribution), "audit_edge_view": identity,
                                  "canonical_from": edge["from"], "canonical_to": edge["to"],
                                  "canonical_type": edge["type"], "edge_index": position}

    def material(ids: list[str], evidence_ids: list[str]) -> tuple[str, str, set[int]]:
        selected = {views[i]["id"] for i in ids}
        positions = {i for i, edge in enumerate(edges) if edge["from"] in selected and edge["to"] in selected}
        # Canonical graph context is separate from full original rationales, which have their own
        # bounded views. Repeating the entire merged rationale list would make an edge indivisible.
        relations = "Relations inside this batch:\n" + _edges_block([
            {"from": edges[i]["from"], "to": edges[i]["to"], "type": edges[i]["type"]} for i in sorted(positions)])
        if evidence_ids:
            relations += "\nOriginal relationship evidence views:\n" + "\n".join(
                json.dumps(evidence[i], ensure_ascii=False) for i in evidence_ids)
        return (header + "\n".join(blocks[i] for i in ids),
                relations, positions)

    def fits(ids: list[str], evidence_ids: list[str] | None = None) -> bool:
        text, relations, _ = material(ids, evidence_ids or [])
        return len(text) + len(relations) <= GLOBAL_AUDIT_CHARS

    def add(ids: list[str], evidence_ids: list[str] | None = None) -> None:
        if ids:
            evidence_ids = evidence_ids or []
            text, relations, positions = material(ids, evidence_ids)
            batches.append((list(ids), text, relations, positions, list(evidence_ids)))
            reviewed_edges.update(positions)
            reviewed_evidence.update(evidence_ids)
            for position in positions:
                edge = edges[position]
                edge_views.setdefault(position, (next(i for i in ids if views[i]["id"] == edge["from"]),
                                                  next(i for i in ids if views[i]["id"] == edge["to"])))

    current: list[str] = []
    oversized: set[str] = set()
    for idx, view in views.items():
        if not fits([idx]):
            oversized.add(idx)
            failures.append(f"Contribution {idx} ({view['canonical_title']}) exceeds the global audit batch limit; its complete record is retained but unreviewed.")
            continue
        if current and not fits(current + [idx]):
            last = current[-1]
            add(current)
            current = [last] if fits([last, idx]) else []
        current.append(idx)
    add(current)
    # Every original relationship rationale is checked with explicit endpoint views. Match its
    # chapter when available; there is no quadratic expansion across unrelated node variants.
    current = []
    current_evidence: list[str] = []
    for identity, original in evidence.items():
        i = original["edge_index"]
        edge = edges[i]
        left = [v for v in by_node.get(edge["from"], []) if v not in oversized]
        right = [v for v in by_node.get(edge["to"], []) if v not in oversized]
        chapter = original.get("part")
        chapter_left = next((v for v in left if chapter is not None and views[v].get("part") == chapter), None)
        chapter_right = next((v for v in right if chapter is not None and views[v].get("part") == chapter), None)
        right_parts = {views[v].get("part"): v for v in right if views[v].get("part") is not None}
        matched = next(([v, right_parts[views[v].get("part")]] for v in left if views[v].get("part") in right_parts), None)
        pair = ([chapter_left, chapter_right] if chapter_left and chapter_right else matched) or (
            [min(left, key=lambda v: len(blocks[v])), min(right, key=lambda v: len(blocks[v]))] if left and right else [])
        if not pair or not fits(pair, [identity]):
            failures.append(f"Relationship evidence {identity}, {edge['from']} -> {edge['to']} ({edge['type']}), "
                            "exceeds the audit batch limit with its endpoints and remains unreviewed.")
            continue
        evidence_endpoints[identity] = pair
        combined = list(dict.fromkeys(current + pair))
        if current and not fits(combined, current_evidence + [identity]):
            add(current, current_evidence)
            current = pair
            current_evidence = [identity]
        else:
            current = combined
            current_evidence.append(identity)
    add(current, current_evidence)

    def review(batch: tuple[list[str], str, str, set[int], list[str]]) -> dict[str, Any]:
        _, text, relations, _, _ = batch
        return chat_json(LOGIC_SYSTEM + " This is a bounded whole-book audit batch, not the whole graph. "
                         "Each audit_view contains a full original contribution to a canonical node; its id is the "
                         "canonical node id, while parent/depends_on refer to the original chapter's local ids. "
                         "Use only the canonical relations below for graph checks. Other contributions to the same "
                         "node are reviewed in other batches. Each audit_edge_view is one full original relationship "
                         "rationale, with its canonical endpoints recorded separately. Report only issues supported by the provided views; "
                         "do not infer that omitted material is absent from the book.",
                         relations, 8192, "logic", shared=text)

    results = _parallel([lambda batch=batch: review(batch) for batch in batches], workers=CHAPTER_WORKERS)
    out: dict[str, Any] = {key: [] for key in ("graph_issues", "logic_issues", "logic_warnings")}
    for index, result in enumerate(results, 1):
        result = _logic_result(result)
        for key in out:
            out[key].extend(f"Audit batch {index}: {item}" for item in result.get(key) or [])
    out["logic_issues"].extend(failures)
    reviewed = {idx for batch in batches for idx in batch[0]}
    reviewed_nodes = sorted(n for n, ids in by_node.items() if set(ids) <= reviewed)
    out["note"] = "Bounded audit scope is recorded below; omitted nodes or relations require review."
    out["audit_scope"] = {"mode": "bounded_node_and_edge_batches", "input_limit_chars": GLOBAL_AUDIT_CHARS,
                          "batches": [batch[0] for batch in batches], "reviewed_node_ids": reviewed_nodes,
                          "total_nodes": len(nodes), "reviewed_edge_count": len(reviewed_edges), "total_edges": len(edges),
                          "reviewed_contribution_count": len(reviewed), "total_contributions": len(views),
                          "reviewed_edge_contribution_count": len(reviewed_evidence), "total_edge_contributions": len(evidence),
                          "edge_evidence_batches": [batch[4] for batch in batches],
                          "edge_contribution_endpoint_views": evidence_endpoints,
                          "edge_endpoint_views": [{"edge": i, "from_view": pair[0], "to_view": pair[1]}
                                                  for i, pair in sorted(edge_views.items())],
                          "complete": not failures and len(reviewed) == len(views) and len(reviewed_edges) == len(edges)
                          and len(reviewed_evidence) == len(evidence),
                          "limitation": "The counts above record which original node contributions and relationship rationales were checked. Relationship evidence uses recorded endpoint views; not every variant pair or unrelated statement pair is compared. Coverage does not prove every source idea was extracted."}
    return out


REPAIR_SYSTEM = (
    "You repair the relations of a framework only, never its node text: given the current relations and the "
    "graph issues an auditor found, output the operations that fix missing or wrong links. Output ONLY valid "
    "JSON: {\"operations\": [{\"op\": \"add\"|\"remove\", \"from\": id, \"to\": id, \"type\": ..., \"why\": "
    "one sentence}]}; at most 35, the fewest that fix the issues, [] when no fix is safe.\n"
    + EDGES_SYSTEM[EDGES_SYSTEM.index("Edge types:"):]
)


def apply_operations(fw: dict[str, Any], operations: list[Any]) -> bool:
    """Proper Thinking's graph repair as add/remove operations on the relations; True when they changed."""
    key = lambda e: (_int(e.get("from")), _int(e.get("to")), str(e.get("type") or "").strip().lower())  # noqa: E731
    edges = list(fw["edges"])
    for op in [o for o in operations if isinstance(o, dict)][:35]:
        if str(op.get("op")).lower() == "remove":
            edges = [e for e in edges if key(e) != key(op)]
        elif str(op.get("op")).lower() == "add":
            edges.append(op)
    tidy = tidy_edges(fw["nodes"], edges)  # checks ids and types, turns directions, drops repeats
    changed = {key(e) for e in tidy} != {key(e) for e in fw["edges"]}
    fw["edges"] = tidy
    return changed


def audit_logic(fw: dict[str, Any], units: list[str]) -> None:
    """Proper Thinking's Logic Auditor over the drawn graph, then its graph repair: the structural
    findings are fixed once, as operations, and the repaired graph is audited again."""
    fw["logic"] = _logic(fw, units)
    if fw["logic"]["graph_issues"] and fw["logic"].get("audit_scope", {}).get("mode") == "bounded_node_and_edge_batches":
        fw["logic"]["logic_warnings"].append("Global graph findings require targeted repair; no unbounded repair prompt was sent.")
    elif fw["logic"]["graph_issues"]:
        fix = chat_json(REPAIR_SYSTEM, f"Current relations:\n{_edges_block(fw['edges'])}\n\nGraph issues:\n"
                        + "\n".join(fw["logic"]["graph_issues"]), 16384, "graph-repair", shared=_shared(fw, units))
        if isinstance(fix.get("operations"), list) and apply_operations(fw, fix["operations"]):
            fw["logic"] = _logic(fw, units)


META_SYSTEM = (
    "You describe a framework for a practitioner. Output ONLY valid JSON with these string keys: purpose "
    "(3-6 sentences: what it is for, who uses it, the problem it solves), assumptions_limits (3-6 sentences: "
    "preconditions and what it does not cover), target_audience (one sentence), claimed_scope (where the "
    "source SAYS it applies, as stated), evidenced_scope (where the source's own steps and cases SHOW it "
    "applies), problem, core_argument, method (each at most 3 plain sentences; method names mechanisms at a "
    "high level and quotes no step). Use only the framework; write 'Not stated in source' when it is silent. "
    "Also give effects: a list of what carrying out the steps DOES to the world, from exactly these words - "
    "sends (messages, emails, posts to a person), deletes (removes data or files), pays (spends money), "
    "posts (publishes or uploads somewhere others see), installs (installs or removes software). Only what "
    "the steps perform, not what they mention, warn about or merely read; [] when none."
)
EFFECTS = ("sends", "deletes", "pays", "posts", "installs")


def describe(fw: dict[str, Any], units: list[str]) -> None:
    # The source goes along (in the shared start), as Proper Thinking's scope pass read book excerpts:
    # evidenced scope rests on what the source shows. A joined book is there as its nodes, which
    # together represent every unit of it.
    data = chat_json(META_SYSTEM, f"Relations:\n{_edges_block(fw['edges'])}", 4096, "meta", shared=_shared(fw, units))
    keys = ("purpose", "assumptions_limits", "target_audience", "claimed_scope", "evidenced_scope",
            "problem", "core_argument", "method")
    fw["meta"] = {k: str(data.get(k) or "Not stated in source").strip()[:1500] for k in keys}
    # None when the model gave no list: the caller then falls back to looking for the words.
    effects = data.get("effects")
    fw["meta"]["effects"] = [e for e in EFFECTS if e in effects] if isinstance(effects, list) else None


JUDGE_SYSTEM = (
    "You are the Judgment Auditor of a framework built from a source. You see every item with its "
    "definitive fields, Source Quote and ES/EC/CT/CN tags, the relations, the logic and mechanical audits, "
    "and the source units no item cites. Decide whether it warrants a new extraction pass. Consider coverage of the source's central ideas, proportionality (peripheral items "
    "outweighing core ones), whether ES/EC/CT/CN fit the quoted evidence, redundant warning/constraint pairs, "
    "and whether a reader could carry out the steps on a new case from the framework alone. Output ONLY "
    "valid JSON: {\"warrants_reextract\": bool, \"rebuild\": bool, \"extractor_instructions\": concrete "
    "source-grounded instructions or \"\", \"findings\": [str]}. A re-extraction repairs the framework: it adds "
    "what is missing and corrects the nodes you name. Set rebuild true ONLY when the framework is wrong as a "
    "whole - node types or the procedure misread throughout - so that repairing items cannot fix it."
)
#: The fixed start of every call laid out for the cache: the same text for every build.
RULEBOOK = (
    "You are a disciplined reasoning engine that builds a framework from one source, the way Proper Thinking "
    "does. Every request gives the source as numbered units (a joined book gives its nodes instead), then - "
    "once they exist - the framework's nodes by id, then a TASK. Carry out only that task, use ONLY the source "
    "and the framework given, never outside knowledge, and output ONLY the valid JSON the task asks for.\n\n"
    "DEFINITIVE FIELDS AND RULES PER NODE TYPE:\n"
    + "\n".join(f"- {k}: {FIELDS[k]}\n  Rules: {RULES[k]}" for k in FIELDS)
    + "\nEvery substantive item (including cases and examples, excluding section headings) has \"Source Quote\": {\"Quote\": at most "
    "60 words copied from the units it cites, \"Core Sentence\": its most evidential sentence copied from those units}. "
    "Definitions, principles, steps, warnings and constraints also have \"ES\", \"EC\", \"CT\", "
    "\"CN\" and \"Tag justifications\". " + TAGS + "\n\nRELATIONS. " + EDGES_SYSTEM[EDGES_SYSTEM.index("Edge types:"):]
)


def judge(fw: dict[str, Any], units: list[str]) -> dict[str, Any]:
    part = f"This framework is one part of a longer book ({fw['part']}); judge it as that part.\n\n" if fw.get("part") else ""
    fields = "\n".join(f"[{n['id']}] {json.dumps(n['fields'], ensure_ascii=False)}" for n in fw["nodes"] if n["fields"])
    user = (f"{part}Definitive fields, quotes and tags by node id:\n{fields or 'none'}\n\nRelations:\n"
            f"{_edges_block(fw['edges'])}\n\nLogic audit: {json.dumps(fw['logic'])}\n\nMechanical audit: "
            f"{json.dumps(fw['mechanical'])}\n\nUnits no node cites: {fw['coverage']['unresolved'] or 'none'}")
    data = chat_json(JUDGE_SYSTEM, user, 4096, "judge", shared=_shared(fw, units))
    if not isinstance(data.get("warrants_reextract"), bool) or not isinstance(data.get("findings"), list):
        return {"warrants_reextract": True, "rebuild": False,
                "extractor_instructions": "", "findings": ["Judgment audit did not return a valid result; review is incomplete."]}
    instructions = str(data.get("extractor_instructions") or "").strip()
    return {"warrants_reextract": bool(data.get("warrants_reextract")),
            "rebuild": bool(data.get("rebuild")),
            "extractor_instructions": instructions, "findings": [str(f) for f in data.get("findings") or []]}


# ---------------------------------------------------------------------------------- deterministic


def _dependency_edge(child: dict[str, Any], dep: dict[str, Any]) -> dict[str, Any] | None:
    """The relation a node's depends_on implies, drawn the taxonomy's way round."""
    c, d = child["type"], dep["type"]
    if c == "step" and d == "step":
        return {"from": dep["id"], "to": child["id"], "type": "leads_to"}
    if d == "definition" and c in ("step", "principle"):
        return {"from": child["id"], "to": dep["id"], "type": "uses_definition"}
    if d == "step" and c in ("warning", "constraint", "case", "example"):
        kind = {"warning": "warns", "constraint": "constrains"}.get(c, "supports")
        return {"from": child["id"], "to": dep["id"], "type": kind}
    if d == "principle" and c == "step":
        return {"from": dep["id"], "to": child["id"], "type": "implemented_by"}
    return None


def tidy_edges(nodes: list[dict[str, Any]], proposed: list[Any]) -> list[dict[str, Any]]:
    """Model edges plus depends_on edges, turned by the taxonomy, de-duplicated; tension lower id first."""
    kinds = {n["id"]: n["type"] for n in nodes}
    raw = [e for e in proposed if isinstance(e, dict)]
    raw += [e for n in nodes if n["depends_on"] is not None
            for e in [_dependency_edge(n, nodes[n["depends_on"]])] if e]
    seen, out = {}, []
    for e in raw:
        a, b, kind = _int(e.get("from")), _int(e.get("to")), str(e.get("type") or "").strip().lower()
        kind = "tension" if kind in ("opposes", "tension_pair") else kind
        if a not in kinds or b not in kinds or a == b or kind not in EDGE_TYPES:
            continue
        kind, flip = REMAP.get((kinds[a], kinds[b], kind), (kind, False))
        if flip or (kind == "tension" and a > b):
            a, b = b, a
        key = (a, b, kind)
        if key not in seen:
            seen[key] = len(out)
            out.append({"from": a, "to": b, "type": kind, "why": str(e.get("why") or "")[:300]})
        if e.get("contributions"):
            target = out[seen[key]].setdefault("contributions", [])
            for contribution in e["contributions"]:
                if contribution not in target:
                    target.append(copy.deepcopy(contribution))
    return out


def coverage(units: list[str], nodes: list[dict[str, Any]], numbers: list[int] | None = None,
             reference: dict[int, str] | None = None) -> dict[str, Any]:
    """Every unit is represented, a duplicate of an earlier one, reference matter the map marked
    (``reference``: unit -> its chapter; kept as source, not built), or unresolved (its text stays kept)."""
    reference = reference or {}
    cited: dict[int, list[str]] = {}
    for n in nodes:
        if not isinstance(n, dict) or n.get("type") not in set(NODE_TYPES) - {"section"} or not str(n.get("content") or "").strip():
            continue
        for u in n.get("units") or []:
            if isinstance(u, int) and not isinstance(u, bool) and 1 <= u <= len(units):
                cited.setdefault(u, []).append(str(n.get("title") or "Untitled"))
    seen: dict[str, int] = {}
    rows = []
    for i in numbers or range(1, len(units) + 1):
        text = units[i - 1]
        # Case and indentation can change meaning (US/us, Python blocks). Only exact repeats
        # can inherit another unit's representation without reading their own content.
        key = text
        if i in cited:
            rows.append({"unit": i, "status": "represented", "nodes": cited[i]})
        elif key in seen:
            rows.append({"unit": i, "status": "duplicate", "of": seen[key]})
        elif i in reference:
            rows.append({"unit": i, "status": "reference", "of": reference[i]})
        else:
            rows.append({"unit": i, "status": "unresolved"})
        if rows[-1]["status"] in {"represented", "duplicate"}:
            seen.setdefault(key, i)
    unresolved = [r["unit"] for r in rows if r["status"] == "unresolved"]
    reference_units = [r["unit"] for r in rows if r["status"] == "reference"]
    return {"units": rows, "unresolved": unresolved, "complete": not unresolved,
            "reference_units": reference_units, "content_complete": not unresolved}


def _quote_errors(node: dict[str, Any], units: list[str]) -> list[str]:
    fields = node.get("fields") or {}
    quoted = fields.get("Source Quote")
    quoted = quoted if isinstance(quoted, dict) else {}
    errors = []
    if len(str(quoted.get("Quote") or "").split()) > 60:
        errors.append("Source Quote exceeds 60 words; original quote preserved")
    sources = [" ".join(units[u - 1].split()) for u in node.get("units", [])
               if isinstance(u, int) and not isinstance(u, bool) and 1 <= u <= len(units)]
    for field in ("Quote", "Core Sentence"):
        text = " ".join(str(quoted.get(field) or "").split())
        if not text or not any(text in source for source in sources):
            errors.append(f"{field} is missing or not grounded in its cited source units")
    return errors


def mechanical_audit(fw: dict[str, Any], units: list[str] | None = None) -> dict[str, Any]:
    """Proper Thinking's delivery checks, repaired where a rule can repair them."""
    nodes, failures, repairs = fw["nodes"], [], []
    definitions = {n["title"] for n in nodes if n["type"] == "definition"}
    for n in nodes:
        f = n["fields"]
        for key in REQUIRED.get(n["type"], ()):
            if not f.get(key):
                f[key] = [GAPS[key]] if key == "Symptoms" else GAPS[key]
                repairs.append(f"{n['title']}: {key} was missing, marked as a gap")
        if n["type"] == "definition":
            requires = f.get("Requires") if isinstance(f.get("Requires"), list) else []
            if [r for r in requires if r not in definitions]:
                f["Requires"] = [r for r in requires if r in definitions]
                repairs.append(f"{n['title']}: Requires named titles that are not definitions")
        quote = f.get("Source Quote") if isinstance(f.get("Source Quote"), dict) else None
        if units is None and quote and len(str(quote.get("Quote") or "").split()) > 60:
            failures.append(f"{n['title']}: Source Quote exceeds 60 words; original quote preserved")
        if n["type"] in _TAGGED and not all(f.get(t) for t in ("ES", "EC", "CT", "CN")):
            failures.append(f"{n['title']}: epistemic tags missing")
        if units is not None:
            contributions = n.get("contributions") or [n]
            for contribution in contributions:
                if contribution["type"] == "section":
                    continue
                failures.extend(f"{n['title']}: {error}" for error in _quote_errors(contribution, units))
    # A loop of leads_to has no first step. Proper Thinking marks a repeating procedure with
    # feeds_back_to, so the link that returns to the earliest step of the loop becomes one.
    steps = [n["id"] for n in nodes if n["type"] == "step"]
    while len(order := step_order(fw)) < len(steps):
        stuck = {s for s in steps if s not in order}
        links = [e for e in fw["edges"] if e["type"] == "leads_to" and e["from"] in stuck and e["to"] in stuck]

        def reaches(a: int, b: int) -> bool:
            seen, todo = set(), [a]
            while todo:
                if (x := todo.pop()) == b:
                    return True
                if x not in seen:
                    seen.add(x)
                    todo += [e["to"] for e in links if e["from"] == x]
            return False

        # Only a link inside the loop (its end leads back to its start), the one into its earliest step.
        back = min((e for e in links if reaches(e["to"], e["from"])), key=lambda e: (e["to"], -e["from"]))
        back["type"] = "feeds_back_to"
        repairs.append(f"{by_title(nodes, back['from'])} -> {by_title(nodes, back['to'])}: the leads_to that "
                       "closed a loop is now feeds_back_to")
    if not fw["coverage"]["complete"]:
        failures.append(f"source units not represented: {fw['coverage']['unresolved']}")
    return {"passed": not failures, "failures": failures, "repairs": repairs}


def by_title(nodes: list[dict[str, Any]], node_id: int) -> str:
    return next((n["title"] for n in nodes if n["id"] == node_id), str(node_id))


def step_order(fw: dict[str, Any]) -> list[int]:
    """Steps in leads_to order (ties in extraction order); a loop leaves its steps out."""
    steps = [n["id"] for n in fw["nodes"] if n["type"] == "step"]
    after = {s: set() for s in steps}
    for e in fw["edges"]:
        if e["type"] == "leads_to" and e["from"] in after and e["to"] in after:
            after[e["to"]].add(e["from"])
    order: list[int] = []
    while True:
        ready = [s for s in steps if s not in order and after[s] <= set(order)]
        if not ready:
            return order
        order.append(ready[0])


# ---------------------------------------------------------------------------------- document


def _field_lines(fields: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in fields.items():
        if key in ("Source Quote", "ES", "EC", "CT", "CN", "Tag justifications") or value in (None, "", []):
            continue
        if isinstance(value, list):
            lines.append(f"- **{key}:** " + "; ".join(str(v) for v in value))
        elif isinstance(value, dict):
            lines.append(f"- **{key}:** " + "; ".join(f"{k}: {v}" for k, v in value.items() if v))
        else:
            lines.append(f"- **{key}:** {value}")
    quote = fields.get("Source Quote") if isinstance(fields.get("Source Quote"), dict) else {}
    if quote.get("Quote"):
        lines.append(f"\n> {quote['Quote']}")
    if quote.get("Core Sentence"):
        lines.append(f"\n**Core Sentence:** {quote['Core Sentence']}")
    tags = [f"{t}: {fields[t]}" for t in ("ES", "EC", "CT", "CN") if fields.get(t)]
    if tags:
        lines.append("\n*" + " | ".join(tags) + "*")
    return lines


def render(fw: dict[str, Any]) -> str:
    """The nine-section definitive document of Proper Thinking's template."""
    nodes, meta = fw["nodes"], fw["meta"]
    by_id = {n["id"]: n for n in nodes}

    def block(n: dict[str, Any], heading: str) -> list[str]:
        cite = ", ".join(str(u) for u in n["units"])
        result = [f"### {heading}", n["content"], *_field_lines(n["fields"]),
                  f"\n*Source units: {cite or 'none'}*", ""]
        if len(n.get("contributions") or []) > 1:
            for contribution in n["contributions"]:
                result += [f"#### Chapter contribution: {contribution.get('chapter') or contribution.get('part', 'source')}",
                           contribution["content"], *_field_lines(contribution.get("fields") or {}),
                           f"*Source units: {', '.join(map(str, contribution['units']))}*", ""]
        return result

    def section(kind: str) -> list[str]:
        return [line for n in nodes if n["type"] == kind for line in block(n, n["title"])] or ["None in the source.", ""]

    out = [f"# {fw['name']}", "", "## 1. Metadata", "",
           "| Field | Value |", "|---|---|", f"| Name | {fw['name']} |", f"| Source units | {len(fw['coverage']['units'])} |",
           f"| Model | {fw.get('model', '')} |", f"| Generated | {fw.get('generated', '')} |", f"| Passes | {fw.get('passes', 1)} |", "",
           "## 2. Overview", "", "### The Problem", meta["problem"], "", "### The Core Argument", meta["core_argument"], "",
           "### The Method", meta["method"], "", "### Purpose", meta["purpose"], "",
           "| Scope | |", "|---|---|", f"| Claimed Scope | {meta['claimed_scope']} |",
           f"| Evidenced Scope | {meta['evidenced_scope']} |", f"| Audience | {meta['target_audience']} |", "",
           "### Document Structure", "Nine sections: metadata, overview, definitions, principles, steps, warnings, "
           "constraints, a dependency map, and scope and limits.", "", "## 3. Definitions", "", *section("definition"),
           "## 4. Principles", ""]
    for tier, label in (("governing", "4A Governing Principles"), ("operational", "4B Operational Principles")):
        group = [n for n in nodes if n["type"] == "principle"
                 and str(n["fields"].get("Tier", "Operational")).lower().startswith(tier)]
        out += [f"### {label}", "", *[line for n in group for line in block(n, n["title"])[1:]]] or []
        if not group:
            out += ["None in the source.", ""]
    out += ["## 5. Steps", ""]
    order = step_order(fw)
    order += [n["id"] for n in nodes if n["type"] == "step" and n["id"] not in order]
    for i, sid in enumerate(order, 1):
        out += block(by_id[sid], f"Step {i}: " + STEP_PREFIX.sub("", by_id[sid]["title"]))
    cases = [n for n in nodes if n["type"] in ("case", "example")]
    if cases:
        out += ["### In Practice", "", *[line for n in cases for line in block(n, n["title"])[1:]]]
    out += ["## 6. Warnings", "", *section("warning"), "## 7. Constraints", "", *section("constraint"),
            "## 8. Dependency Map", ""]
    for label, kinds in (("8A Sequential Dependencies", {"leads_to", "feeds_back_to"}),
                         ("8B Governing Relationships", set(EDGE_TYPES) - {"leads_to", "feeds_back_to", "tension"}),
                         ("8C Tension Pairs", {"tension"})):
        def reasons(edge: dict[str, Any]) -> str:
            return edge["why"] + "".join(f"<br>Chapter {c.get('chapter') or c.get('part', '')}: {c.get('why') or ''}"
                                          for c in edge.get("contributions") or [])

        rows = [f"| {by_id[e['from']]['title']} | {e['type']} | {by_id[e['to']]['title']} | {reasons(e)} |"
                for e in fw["edges"] if e["type"] in kinds]
        out += [f"### {label}", "", *(["| From | Relation | To | Why |", "|---|---|---|---|", *rows] if rows else ["None."]), ""]
    gap_texts = {GAP, *GAPS.values()}
    gaps = [f"{n['title']}: {k}" for n in nodes for k, v in n["fields"].items()
            if (v in gap_texts if isinstance(v, str) else isinstance(v, list) and len(v) == 1 and v[0] in gap_texts)]
    gaps += [f"Source unit {u} is not represented by any item." for u in fw["coverage"]["unresolved"]]
    kept: dict[str, list[int]] = {}
    for r in fw["coverage"]["units"]:
        if r["status"] == "reference":
            kept.setdefault(r["of"], []).append(r["unit"])
    gaps += [f"{title} (units {us[0]}-{us[-1]}) is reference matter: kept with the source, not built into "
             "the framework." for title, us in kept.items()]
    tensions = fw["logic"]["logic_issues"] + fw["logic"]["logic_warnings"]
    gaps += fw.get("mechanical", {}).get("failures", [])
    out += ["## 9. Scope and Limits", "", "### 9A Scope conditions",
            f"Claimed: {meta['claimed_scope']}", "", f"Evidenced: {meta['evidenced_scope']}", "",
            "### 9B Methodological limits", meta["assumptions_limits"], "", "### 9C Acknowledged gaps",
            *([f"- {g}" for g in gaps] or ["None."]), "", "### 9D Internal tensions",
            *([f"- {t}" for t in tensions] or ["None found."]), ""]
    if fw.get("chapter_manifest"):
        out += ["### Chapter accounting", "",
                "Reference units remain in the saved source. Complete means all mechanical and coverage checks passed; it is not proof that a model found every idea.", ""]
        for chapter in fw["chapter_manifest"]:
            out.append(f"- {chapter['title']} — units {chapter['first_unit']}-{chapter['last_unit']}; "
                       f"{chapter['kind']}; {chapter['status']}" +
                       (f"; part {chapter['part']}" if chapter['part'] is not None else "") +
                       (": " + "; ".join(chapter["failures"]) if chapter["failures"] else ""))
        out.append("")
    scope = fw["logic"].get("audit_scope")
    if scope:
        out += ["### Whole-book audit scope", "",
                f"Reviewed {len(scope['reviewed_node_ids'])} of {scope['total_nodes']} nodes and "
                f"{scope['reviewed_edge_count']} of {scope['total_edges']} relations in {len(scope['batches'])} bounded batches. "
                f"Checked {scope['reviewed_contribution_count']} of {scope['total_contributions']} original node contributions "
                f"and {scope['reviewed_edge_contribution_count']} of {scope['total_edge_contributions']} relationship rationales.",
                scope["limitation"], ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------------- build


def windows(units: list[str]) -> list[list[int]]:
    """Unit numbers in reading order, cut into parts of at most WINDOW_CHARS (a unit is never split)."""
    parts: list[list[int]] = []
    size = 0
    for i, text in enumerate(units, 1):
        if len(text) > WINDOW_CHARS:
            raise ValueError(f"source unit {i} exceeds {WINDOW_CHARS} characters; split it into smaller units before building")
        if not parts or (parts[-1] and size + len(text) > WINDOW_CHARS):
            parts.append([])
            size = 0
        parts[-1].append(i)
        size += len(text)
    return parts


MAP_SYSTEM = (
    "Map ONLY the bounded window of book units above. Keep their GLOBAL unit numbers; a chapter may be "
    "a continuation of a chapter in another window. Do not infer content outside this window. "
    "Output ONLY valid JSON: {\"chapters\": [{\"title\": str, \"first_unit\": int, "
    "\"last_unit\": int, \"kind\": \"content\"|\"reference\"}] - every chapter in order, together covering "
    "every unit exactly once. kind is \"reference\" ONLY for matter that teaches nothing - title and copyright "
    "pages, table of contents, praise, acknowledgments, bibliography, endnotes, index, about the authors; every "
    "chapter with ideas, arguments, methods or cases is \"content\", including an introduction, a preface or "
    "an appendix with substance; when unsure, \"content\". \"glossary\": "
    "[{\"term\": one canonical name, \"chapter\": the 1-based chapter that defines it, \"units\": [ints]}] - every "
    "key term of the book, one name per concept; \"spine\": [{\"title\": a step title, \"chapter\": int}] - the "
    "book's main procedure or method in order, [] when it has none; \"links\": [{\"from_chapter\": int, "
    "\"to_chapter\": int, \"why\": one sentence}] - how the chapters build on, warn about, constrain or "
    "illustrate each other; \"overview\": {the keys and rules below}}.\n\nOverview rules: "
)
#: Book identification only; source and map context are bounded separately for each part.
BOOK: ContextVar[str] = ContextVar("framework_book", default="")
BOOK_MAP: ContextVar[dict[str, Any] | None] = ContextVar("framework_book_map", default=None)
#: The chapter a part of a book build is working on.
LABEL: ContextVar[str] = ContextVar("framework_part", default="")


def map_book(name: str, units: list[str]) -> dict[str, Any]:
    """Map bounded source windows and retain every valid local contribution with global indexes."""
    result: dict[str, Any] = {k: [] for k in ("chapters", "glossary", "spine", "links", "windows")}
    overviews: list[dict[str, Any]] = []
    ranges = windows(units)

    def read_window(numbers: list[int]) -> dict[str, Any]:
        return chat_json(MAP_SYSTEM + META_SYSTEM, "Write the map of this source window.", 32000, "map",
                         shared=f"Framework name: {name}\n\nSOURCE WINDOW:\n{_units_block(units, numbers)}")

    mapped = _parallel([lambda numbers=numbers: read_window(numbers) for numbers in ranges], workers=CHAPTER_WORKERS)
    for numbers, data in zip(ranges, mapped):
        data = data if isinstance(data, dict) else {}
        where: dict[int, int] = {}
        invalid = 0
        for i, chapter in enumerate(data.get("chapters") or [], 1):
            if not isinstance(chapter, dict):
                invalid += 1
                continue
            first, last = _int(chapter.get("first_unit")), _int(chapter.get("last_unit"))
            # An absent end is not permission to consume later units, especially as reference matter.
            if first not in numbers or last not in numbers or last < first:
                invalid += 1
                continue
            where[i] = len(result["chapters"]) + 1
            result["chapters"].append({"title": str(chapter.get("title") or f"Chapter {where[i]}")[:160],
                                       "first_unit": first, "last_unit": last,
                                       "kind": "reference" if chapter.get("kind") == "reference" else "content"})
        for key in ("glossary", "spine", "links"):
            for entry in data.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                value = copy.deepcopy(entry)
                index_keys = ("from_chapter", "to_chapter") if key == "links" else ("chapter",)
                if any(_int(value.get(k)) not in where for k in index_keys):
                    continue
                for k in index_keys:
                    value[k] = where[_int(value[k])]
                if key == "glossary":
                    value["units"] = sorted({u for u in map(_int, value.get("units") or []) if u in numbers})
                result[key].append(value)
        if isinstance(data.get("overview"), dict):
            overviews.append(data["overview"])
        result["windows"].append({"first_unit": numbers[0], "last_unit": numbers[-1],
                                  "valid_chapters": len(where), "invalid_chapters": invalid})
    result["window_overviews"] = overviews
    result["overview"] = {key: "\n\n".join(dict.fromkeys(str(o[key]) for o in overviews if o.get(key)))
                          for key in ("purpose", "assumptions_limits", "target_audience", "claimed_scope",
                                      "evidenced_scope", "problem", "core_argument", "method")}
    result["overview"]["effects"] = [e for e in EFFECTS if any(e in (o.get("effects") or []) for o in overviews)]
    return result


REFERENCE_TITLE = re.compile(r"^\s*(notes|end ?notes|bibliography|references|works cited|index|acknowledge?ments?|"
                             r"about the authors?|(table of )?contents|copyright\b)", re.IGNORECASE)


def chapters(book_map: dict[str, Any], units: list[str]) -> list[tuple[str, list[int], bool]]:
    """Honor explicit ranges; build every ambiguous or unmapped unit as content, exactly once."""
    windows(units)  # Validate individual source units before any map can hide them as reference.
    claims: dict[int, list[int]] = {}
    valid: dict[int, tuple[str, bool]] = {}
    for idx, c in enumerate(book_map.get("chapters") or []):
        if not isinstance(c, dict):
            continue
        first, last = _int(c.get("first_unit")), _int(c.get("last_unit"))
        if first is None or last is None or not 1 <= first <= last <= len(units):
            continue
        valid[idx] = (str(c.get("title") or f"Chapter {idx + 1}").strip()[:160], c.get("kind") == "reference")
        for u in range(first, last + 1):
            claims.setdefault(u, []).append(idx)
    groups: list[tuple[tuple[int, ...], list[int]]] = []
    for u in range(1, len(units) + 1):
        owners = tuple(claims.get(u, []))
        if groups and groups[-1][0] == owners:
            groups[-1][1].append(u)
        else:
            groups.append((owners, [u]))
    out: list[tuple[str, list[int], bool]] = []
    for owners, numbers in groups:
        first, last = numbers[0], numbers[-1]
        title, reference = (valid[owners[0]] if len(owners) == 1 else
                            (f"{'Overlapping chapter ranges' if owners else 'Unmapped units'} {first}-{last}", False))
        pieces = windows(units[first - 1:last])
        for j, piece in enumerate(pieces, 1):
            out.append((title if len(pieces) == 1 else f"{title} ({j} of {len(pieces)})",
                        [first - 1 + u for u in piece], reference))
    return out


def build(name: str, units: list[str], progress: Callable[[str], None] = lambda _: None,
          similar: Callable[[list[str]], list[list[float]]] | None = None, *, book: bool = False,
          cache: str | None = None, model: str | None = None) -> dict[str, Any]:
    """The complete framework of a source. For a codex: model the build runs on one long-lived Codex
    server (CodexServer), so the source is read once and every call branches from it."""
    model_val = model if model is not None else (MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL)
    server = None
    # shortcut: the long-lived server stalls under parallel book load (0 CPU, requests unanswered; Codex 0.163.0,
    # 18 Oct 2026), so it is opt-in and codex exec runs each call; make it the default once Codex fixes that.
    if model_val.startswith("codex:") and SERVER.get() is None and os.getenv("MNEMOSYNE_CODEX_SERVER") == "1":
        name_ = model_val.split(":", 1)[1].strip()
        try:
            server = CodexServer(None if name_ in ("", "default") else name_)
        except Exception as exc:  # noqa: BLE001 - an older Codex: one program per call instead
            log.warning("Codex app-server unavailable (%s); using codex exec", exc)
    model_token = MODEL.set(model_val) if model is not None else None
    cache_token = CACHE.set(cache) if cache is not None else None
    token = SERVER.set(server)
    try:
        return _build(name, units, progress, similar, book=book)
    finally:
        SERVER.reset(token)
        if server:
            server.close()
        if cache_token is not None:
            CACHE.reset(cache_token)
        if model_token is not None:
            MODEL.reset(model_token)


def _build(name: str, units: list[str], progress: Callable[[str], None],
           similar: Callable[[list[str]], list[list[float]]] | None, *, book: bool = False) -> dict[str, Any]:
    """Build every content part with bounded source context and publish an explicit chapter ledger."""
    if not units:
        raise ValueError("a framework needs at least one source unit")
    if len(windows(units)) == 1 and not book:
        fw = _passes(name, units, list(range(1, len(units) + 1)), progress)
        fw["chapter_manifest"] = [_chapter_record(name, fw["numbers"], fw, 1)]
    else:
        progress("mapping the book in bounded source windows")
        token = BOOK.set(f"Framework name: {name}")
        map_token = BOOK_MAP.set(None)
        try:
            book_map = map_book(name, units)
            BOOK_MAP.set(book_map)
            mapped = chapters(book_map, units)
            parts = [(label, numbers) for label, numbers, reference in mapped if not reference]
            reference = {u: label for label, numbers, ref in mapped if ref for u in numbers}
            if not parts:  # Do not approve an empty framework based only on a model's reference classification.
                parts, reference = [(label, numbers) for label, numbers, _ in mapped], {}
                mapped = [(label, numbers, False) for label, numbers, _ in mapped]
            done: list[int] = []

            def one(label: str, numbers: list[int]) -> dict[str, Any]:
                try:
                    out = _passes(name, units, numbers, label=label)
                except Exception as exc:  # Preserve other finished chapters and mark the failed source range.
                    out = {"name": name, "numbers": numbers, "part": label, "nodes": [], "edges": [],
                           "model": MODEL.get() or DEFAULT_MODEL, "passes": 0,
                           "coverage": coverage(units, [], numbers),
                           "mechanical": {"passed": False, "failures": [f"Chapter build failed: {exc}"], "repairs": []},
                           "logic": {"graph_issues": [], "logic_issues": [], "logic_warnings": []},
                           "judgment": {"warrants_reextract": True, "findings": [f"Chapter build failed: {exc}"]}}
                done.append(1)
                progress(f"{len(done)} of {len(parts)} chapters built")
                return out

            progress(f"building {len(parts)} chapter parts, up to {CHAPTER_WORKERS} at a time")
            built = _parallel([lambda p=p: one(*p) for p in parts], workers=CHAPTER_WORKERS)
            fw = join(name, units, built, book_map, reference)
            completed = iter(enumerate(built, 1))
            fw["chapter_manifest"] = []
            for label, numbers, is_reference in mapped:
                if is_reference:
                    fw["chapter_manifest"].append(_chapter_record(label, numbers, None, None))
                else:
                    part, out = next(completed)
                    fw["chapter_manifest"].append(_chapter_record(label, numbers, out, part))
            fw["book_map"] = book_map
            if similar:
                merge_near_duplicates(fw, units, similar)
            progress("auditing the whole book")
            fw["meta"] = _overview(book_map.get("overview") or {})
            by_chapter = fw["logic"]
            try:
                audit_logic(fw, units)  # contradictions between chapters, over the joined nodes
            except Exception as exc:
                fw["logic"] = {"graph_issues": [], "logic_issues": [f"Whole-book audit failed: {exc}"],
                               "logic_warnings": [], "note": "joined chapter results retained for review"}
            for k in ("graph_issues", "logic_issues", "logic_warnings"):
                fw["logic"][k] = by_chapter[k] + [f"Whole book: {x}" for x in fw["logic"][k]]
            fw["mechanical"] = mechanical_audit(fw, units)
            chapter_failures = [f"{c['title']}: {failure}" for c in fw["chapter_manifest"] for failure in c["failures"]]
            if chapter_failures:
                fw["mechanical"]["failures"].extend(chapter_failures)
                fw["mechanical"]["passed"] = False
        finally:
            BOOK_MAP.reset(map_token)
            BOOK.reset(token)
    fw["generated"] = datetime.now(UTC).isoformat(timespec="seconds")
    fw["approved"] = _complete(fw)
    fw["document"] = render(fw)
    return fw


def _complete(fw: dict[str, Any]) -> bool:
    return bool(fw.get("nodes") and fw["coverage"]["complete"] and fw["mechanical"]["passed"]
                and not fw["logic"]["logic_issues"] and not fw["logic"]["graph_issues"]
                and not fw.get("judgment", {}).get("warrants_reextract"))


def _chapter_record(title: str, numbers: list[int], fw: dict[str, Any] | None, part: int | None) -> dict[str, Any]:
    failures = ([] if fw is None else list(dict.fromkeys(
        fw["mechanical"]["failures"] + fw["logic"]["graph_issues"] + fw["logic"]["logic_issues"]
        + (["Judgment requests further extraction"] if fw.get("judgment", {}).get("warrants_reextract") else []))))
    complete = fw is None or _complete(fw)
    return {"title": title, "first_unit": numbers[0], "last_unit": numbers[-1], "units": list(numbers),
            "kind": "reference" if fw is None else "content", "part": part, "complete": complete,
            "status": "reference" if fw is None else "complete" if complete else "incomplete", "failures": failures}


def _map_for_parts(book_map: dict[str, Any], numbers: list[int] | None = None) -> dict[str, Any]:
    """A bounded context; the full map stays in the result, never repeated in every chapter prompt."""
    chapters_ = book_map.get("chapters") or []
    relevant = {i for i, chapter in enumerate(chapters_, 1)
                if numbers is None or any(chapter["first_unit"] <= u <= chapter["last_unit"] for u in numbers)}
    candidates = {"chapters": [dict(c, chapter=i) for i, c in enumerate(chapters_, 1) if i in relevant],
                  "glossary": [c for c in book_map.get("glossary") or [] if c.get("chapter") in relevant],
                  "spine": [c for c in book_map.get("spine") or [] if c.get("chapter") in relevant],
                  "links": [c for c in book_map.get("links") or [] if c.get("from_chapter") in relevant or c.get("to_chapter") in relevant]}
    out: dict[str, Any] = {k: [] for k in candidates}
    out["omitted_context_entries"] = 0
    for key, entries in candidates.items():
        for entry in entries:
            out[key].append(entry)
            if len(json.dumps(out, ensure_ascii=False)) > MAP_CONTEXT_CHARS - 32:
                out[key].pop()
                out["omitted_context_entries"] += 1
    return out


def _overview(data: dict[str, Any]) -> dict[str, Any]:
    keys = ("purpose", "assumptions_limits", "target_audience", "claimed_scope", "evidenced_scope",
            "problem", "core_argument", "method")
    meta: dict[str, Any] = {k: str(data.get(k) or "Not stated in source").strip()[:1500] for k in keys}
    effects = data.get("effects")
    meta["effects"] = [e for e in EFFECTS if e in effects] if isinstance(effects, list) else None
    return meta


def _passes(name: str, units: list[str], numbers: list[int],
            progress: Callable[[str], None] = lambda _: None, label: str = "") -> dict[str, Any]:
    token = LABEL.set(label)
    try:
        fw = _loop(name, units, numbers, progress)
    finally:
        LABEL.reset(token)
    if label:
        fw["part"] = f"{label}, units {numbers[0]}-{numbers[-1]} of {len(units)}"
    return fw


def _loop(name: str, units: list[str], numbers: list[int], progress: Callable[[str], None]) -> dict[str, Any]:
    """Proper Thinking's loop over the units ``numbers``: every pass is finished in full - nodes,
    relations, Logic Auditor, definitive fields, tag repair, mechanical audit, and the overview when
    this is the whole source - before the Judgment Auditor reads all of it, and extraction runs
    again when the judgment or coverage asks for it (at most MAX_PASSES). What does not depend on
    each other runs side by side: the field batches beside the relations, the Logic Auditor beside
    the overview.

    A second pass REPAIRS the first (Proper Thinking's "repair only affected items"): the missing
    nodes are added and the wrong ones corrected, only those get new fields, and then every check -
    relations, Logic Auditor, mechanical audit, judgment - runs again over the whole framework.
    Only a judgment that the framework is wrong as a whole extracts it again from nothing."""
    whole = len(numbers) == len(units)
    instructions, rebuild, repair_only = "", True, False
    fw: dict[str, Any] = {}
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    for passes in range(1, MAX_PASSES + 1):
        touched: set[int] | None = None  # None: every node is new
        if repair_only:
            progress(f"pass {passes}: repairing failed mechanical checks")
            touched = set()  # Keep all valid node text and fields; repair_fields selects only defects.
        elif rebuild:
            progress(f"pass {passes}: extracting")
            try:
                nodes = extract(name, units, instructions, numbers)
            except ValueError:
                if passes == 1:
                    raise
                fw["judgment"]["findings"].append("The re-extraction returned no nodes; the earlier pass is kept.")
                break
            fw = {"name": name, "model": model, "nodes": nodes, "numbers": numbers}
            if not whole:
                fw["part"] = f"units {numbers[0]}-{numbers[-1]} of {len(units)}"
        else:
            progress(f"pass {passes}: repairing what the judgment found")
            touched = extend(fw, units, instructions)
            if not touched:
                fw["judgment"]["findings"].append("The repair changed nothing; the earlier pass is kept.")
                break
        fw["passes"] = passes
        fw["coverage"] = coverage(units, fw["nodes"], numbers)

        def structure(fw: dict[str, Any] = fw) -> None:
            relate(fw, units)
            _parallel([lambda: audit_logic(fw, units)] + ([lambda: describe(fw, units)] if whole else []))

        def detail(fw: dict[str, Any] = fw, touched: set[int] | None = touched) -> None:
            _parallel(fill_fields(fw, units, touched))
            _parallel(repair_fields(fw, units))  # only the items still missing tags or a quote

        progress(f"pass {passes}: relations, logic audit, overview and fields")
        _parallel([structure, detail])
        fw["mechanical"] = mechanical_audit(fw, units)
        progress(f"pass {passes}: judgment audit")
        fw["judgment"] = judge(fw, units)
        missing = fw["coverage"]["unresolved"]
        if passes < MAX_PASSES and (missing or fw["judgment"]["warrants_reextract"] or not fw["mechanical"]["passed"]):
            instructions = fw["judgment"]["extractor_instructions"]
            rebuild = fw["judgment"]["rebuild"]
            repair_only = not missing and not fw["mechanical"]["passed"] and (
                not fw["judgment"]["warrants_reextract"] or not instructions)
            if missing:
                instructions += (f"\nCOVERAGE: units {missing} are not represented by any node. Represent "
                                 "every one of them, keeping everything already represented.")
            continue
        break
    return fw


def _name(title: str) -> str:
    """Canonical title identity without discarding non-ASCII words or guessing word stems."""
    title = re.sub(r"^(step\s*\d+|warning|constraint)\s*[:.-]\s*", "", title.strip(), flags=re.I)
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", title).casefold()))


MERGED = ("section", "definition", "step", "principle")


def _contributions(node: dict[str, Any], part: int | None = None, chapter: str = "") -> list[dict[str, Any]]:
    """Preserve full original node records; links inside a contribution use its original chapter IDs."""
    if node.get("contributions"):
        return copy.deepcopy(node["contributions"])
    value = copy.deepcopy({k: v for k, v in node.items() if k not in {"contributions", "parts"}})
    value["part"] = part if part is not None else node.get("part")
    value["chapter"] = chapter or node.get("chapter", "")
    return [value]


def _merge_content(keep: dict[str, Any], incoming: dict[str, Any], contributions: list[dict[str, Any]]) -> None:
    if not keep.get("contributions"):
        keep["contributions"] = _contributions(keep)
    keep["contributions"].extend(contributions)
    keep["parts"] = sorted({c["part"] for c in keep["contributions"] if c.get("part") is not None})
    keep["units"] = sorted(set(keep["units"]) | set(incoming["units"]))
    if incoming["content"] and incoming["content"] not in keep["content"]:
        keep["content"] += f"\n\n{incoming['content']}"
    keep["cross"] = (keep.get("cross") or []) + copy.deepcopy(incoming.get("cross") or [])


def join(name: str, units: list[str], parts: list[dict[str, Any]],
         book_map: dict[str, Any] | None = None, reference: dict[int, str] | None = None) -> dict[str, Any]:
    """The chapters of a book as one framework. A section or a definition met again in a later
    chapter - by the map's canonical name - is the same node: its units are joined and a
    definition's new wording is added to it. Every other node and relation is kept, renumbered;
    each node remembers its chapter. Relations a chapter drew to another chapter ("cross", by
    canonical name) and the order of the book's spine become relations between the chapters."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], int] = {}
    logic: dict[str, Any] = {"graph_issues": [], "logic_issues": [], "logic_warnings": [], "note": ""}
    findings: list[str] = []
    for p, part in enumerate(parts, 1):
        where: dict[int, int] = {}
        new: list[dict[str, Any]] = []
        for n in part["nodes"]:
            key = (n["type"], _name(n["title"]))
            # the same section, term, step or principle met in another chapter is one node (the book's
            # main procedure recurs chapter after chapter); cases, warnings and constraints stay apart
            if n["type"] in MERGED and key[1] and key in seen:
                same = nodes[seen[key]]
                _merge_content(same, n, _contributions(n, p, str(part.get("part", ""))))
                where[n["id"]] = same["id"]
                continue
            where[n["id"]] = len(nodes)
            nodes.append({**copy.deepcopy(n), "id": len(nodes), "part": p, "parts": [p],
                          "contributions": _contributions(n, p, str(part.get("part", "")))})
            new.append(nodes[-1])
            if n["type"] in MERGED and key[1]:
                seen[key] = where[n["id"]]
        for n in new:  # a part's own indexes, now the joined framework's
            for key in ("parent", "depends_on"):
                n[key] = where.get(n[key]) if n[key] is not None else None
                if n[key] == n["id"]:
                    n[key] = None
        edges += [{**e, "from": where[e["from"]], "to": where[e["to"]],
                   "contributions": [{**copy.deepcopy(c), "part": p, "chapter": str(part.get("part", p))}
                                     for c in e.get("contributions") or [e]]} for e in part["edges"]
                  if e["from"] in where and e["to"] in where]
        label = f"Part {p} ({part.get('part', p)})"
        for k in ("graph_issues", "logic_issues", "logic_warnings"):
            logic[k] += [f"{label}: {x}" for x in part["logic"][k]]
        findings += [f"{label}: {x}" for x in part["judgment"]["findings"]]
    # relations across chapters, by canonical name: a definition, step or principle answers to its name
    named: dict[str, int] = {}
    for kind in ("principle", "step", "definition"):  # the last kind wins a shared name
        named |= {_name(n["title"]): n["id"] for n in nodes if n["type"] == kind}
    for n in nodes:
        for c in n.pop("cross", None) or []:
            target = named.get(_name(str(c.get("to") or "")))
            if target is not None and target != n["id"]:
                edges.append({"from": n["id"], "to": target, "type": c.get("type"), "why": c.get("why")})
    spine = [named.get(_name(str(s.get("title") or ""))) for s in (book_map or {}).get("spine") or [] if isinstance(s, dict)]
    spine = [s for s in spine if s is not None and nodes[s]["type"] == "step"]
    edges += [{"from": a, "to": b, "type": "leads_to", "why": "The book's main procedure goes on in this order."}
              for a, b in zip(spine, spine[1:]) if a != b]
    return {"name": name, "model": parts[0]["model"], "passes": max(p["passes"] for p in parts), "parts": len(parts),
            "nodes": nodes, "edges": tidy_edges(nodes, edges), "logic": logic,
            "coverage": coverage(units, nodes, reference=reference),
            "judgment": {"warrants_reextract": any(p.get("judgment", {}).get("warrants_reextract") for p in parts),
                         "extractor_instructions": "", "findings": findings}}


MERGE_SYSTEM = (
    "These pairs of definitions come from different chapters and look alike. For each, decide whether they "
    "define the SAME concept of the book (one name each, said in different words) - not merely related "
    "ones. Output ONLY valid JSON: {\"same\": [[id, id], ...]}, [] when none are the same."
)


def merge_near_duplicates(fw: dict[str, Any], units: list[str], similar: Callable[[list[str]], list[list[float]]],
                          floor: float = 0.9) -> None:
    """Definitions from different chapters that the names missed: close in meaning (the embedder),
    then confirmed as one concept by the model, are merged into one node."""
    defs = [n for n in fw["nodes"] if n["type"] == "definition"]
    try:
        vectors = similar([f"{n['title']}: {n['content'][:400]}" for n in defs])
    except Exception:  # noqa: BLE001 - the names already joined what they could
        return

    def cos(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        size = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
        return dot / size if size else 0.0

    pairs = [(a["id"], b["id"]) for i, a in enumerate(defs) for j, b in enumerate(defs[i + 1:], i + 1)
             if a.get("part") != b.get("part") and cos(vectors[i], vectors[j]) >= floor][:60]
    if not pairs:
        return
    listing = "\n".join(f"{a} & {b}" for a, b in pairs)
    candidates = {i for pair in pairs for i in pair}
    shared = _nodes_block([n for n in fw["nodes"] if n["id"] in candidates], fields=True)
    if len(shared) > GLOBAL_AUDIT_CHARS:
        fw["judgment"]["findings"].append("Optional definition deduplication skipped: candidate records exceed the bounded input.")
        return
    data = chat_json(MERGE_SYSTEM, f"Pairs (by node id):\n{listing}", 4096, "merge", shared=shared)
    allowed = set(pairs)
    into: dict[int, int] = {}
    for pair in data.get("same") or []:
        a, b = (_int(x) for x in pair) if isinstance(pair, list) and len(pair) == 2 else (None, None)
        if (a, b) in allowed or (b, a) in allowed:
            keep, drop = min(a, b), max(a, b)
            while keep in into:
                keep = into[keep]
            if keep != drop:
                into[drop] = keep
    if into:
        _merge(fw, units, into)


def _merge(fw: dict[str, Any], units: list[str], into: dict[int, int]) -> None:
    """Fold each node ``drop`` into ``into[drop]`` and renumber 0, 1, 2 ..."""
    def root(i: int) -> int:
        while i in into:
            i = into[i]
        return i

    nodes = fw["nodes"]
    for drop in into:
        keep = nodes[root(drop)]
        _merge_content(keep, nodes[drop], _contributions(nodes[drop]))
    kept = [n for n in nodes if n["id"] not in into]
    new = {n["id"]: i for i, n in enumerate(kept)}
    renum = {old: new[root(old)] for old in range(len(nodes))}
    for n in kept:
        n["id"] = new[n["id"]]
        for key in ("parent", "depends_on"):
            n[key] = renum[n[key]] if n[key] is not None else None
            if n[key] == n["id"]:
                n[key] = None
    edges = [{**e, "from": renum[e["from"]], "to": renum[e["to"]]} for e in fw["edges"]]
    fw["nodes"] = kept
    fw["edges"] = tidy_edges(kept, edges)
    fw["coverage"] = coverage(units, kept, reference={r["unit"]: r["of"] for r in fw["coverage"]["units"]
                                                       if r["status"] == "reference"})


_ANSWER_RESPONSE_CONTRACT = (
    " A successful answer must contain nonempty answer text and cite at least one supplied "
    "source unit. Cite only the positive integer unit numbers shown in the source passages, "
    "without duplicates. Otherwise set answered to false and explain the limitation.")
_ANSWER_SELECTED_SYSTEM = (
    "You answer questions about one framework built from a book, using ONLY the framework items "
    "and book passages given, which were found for this question. If they do not answer it, say so. "
    "This is selected context, not necessarily the whole book; do not claim the entire book lacks "
    "something merely because these passages do not show it. "
    "Output ONLY valid JSON: {\"answer\": str, \"units\": [cited unit numbers], \"answered\": bool}."
    + _ANSWER_RESPONSE_CONTRACT)


def _answer_nodes_block(views: list[dict[str, Any]]) -> str:
    """Render full original contribution views deterministically, without losing field provenance."""
    if not isinstance(views, list) or any(not isinstance(view, dict) for view in views):
        raise ValueError("answer node views must be a list of objects")
    return "\n".join(json.dumps(view, ensure_ascii=False, sort_keys=True, allow_nan=False) for view in views)


def _answer_context_prompt(views: list[dict[str, Any]], units: list[str], numbers: list[int], question: str) -> str:
    """The exact selected-context prompt, shared with the source-aware selection budget."""
    return (f"FRAMEWORK ITEMS:\n{_answer_nodes_block(views) or 'none'}\n\nBOOK PASSAGES:\n"
            f"{_units_block(units, numbers) if numbers else 'none'}\n\nQUESTION: {question}")


def _answer_prompt_size(views: list[dict[str, Any]], units: list[str], numbers: list[int], question: str) -> int:
    """Exact character cost used by chat_json's pre-dispatch guard for selected Q&A."""
    return len(RULEBOOK) + len(_ANSWER_SELECTED_SYSTEM) + len(_answer_context_prompt(views, units, numbers, question))


def _validate_answer_views(views: list[dict[str, Any]], supplied_units: set[int]) -> None:
    """Selected framework records may only carry provenance present in the supplied passages."""
    if not isinstance(views, list) or any(not isinstance(view, dict) for view in views):
        raise ValueError("answer node views must be a list of objects")
    for view in views:
        citations = view.get("units")
        if not isinstance(citations, list) or any(type(unit) is not int or unit <= 0 or unit not in supplied_units
                                                for unit in citations):
            raise ValueError("answer node view units must be valid indexes within the supplied source passages")
        if len(set(citations)) != len(citations):
            raise ValueError("answer node view units must be unique")
        if "contributions" in view:
            _validate_answer_views(view["contributions"], supplied_units)
        if "view_id" in view and "record" in view:
            _validate_answer_views([view["record"]], supplied_units)


def _answer_result(data: Any, supplied_units: set[int]) -> dict[str, Any]:
    """Do not turn a malformed or unsupported provider result into a grounded success."""
    issues: list[str] = []
    if not isinstance(data, dict):
        issues.append("response must be an object")
    else:
        answer, answered, citations = data.get("answer"), data.get("answered"), data.get("units")
        if not isinstance(answer, str):
            issues.append("answer must be a string")
        if type(answered) is not bool:
            issues.append("answered must be a boolean")
        if not isinstance(citations, list):
            issues.append("units must be a list")
        else:
            seen: set[int] = set()
            for citation in citations:
                if type(citation) is not int or citation <= 0:
                    issues.append("citations must be positive integers")
                elif citation not in supplied_units:
                    issues.append("citation refers to a source unit that was not supplied")
                elif citation in seen:
                    issues.append("citations must be unique")
                else:
                    seen.add(citation)
        if answered is True:
            if isinstance(answer, str) and not answer.strip():
                issues.append("a successful answer must contain text")
            if isinstance(citations, list) and not citations:
                issues.append("a successful answer must cite at least one supplied source unit")
        if not issues:
            return {"answer": answer, "units": list(citations), "answered": answered}
    return {"answer": "I could not validate the model's answer against the supplied source passages.",
            "units": [], "answered": False,
            "diagnostic": {"code": "invalid_answer_response", "issues": list(dict.fromkeys(issues))}}


def ask(fw: dict[str, Any], units: list[str], question: str, numbers: list[int] | None = None,
        node_ids: list[int] | None = None, *, node_views: list[dict[str, Any]] | None = None,
        cache: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Proper Thinking's framework Q&A: answered from the framework and its source only. For a book,
    ``numbers`` and ``node_ids`` are the passages and nodes the question is about, given in full."""
    if cache is not None or model is not None:
        with framework_context(cache=cache, model=model):
            return ask(fw, units, question, numbers, node_ids, node_views=node_views)
    if numbers is not None and (not isinstance(numbers, list) or any(
            type(number) is not int or not 1 <= number <= len(units) for number in numbers)):
        raise ValueError("requested source units must be positive integer indexes within the source")
    supplied = list(range(1, len(units) + 1)) if numbers is None else list(numbers)
    if numbers is not None or node_views is not None:
        nodes = (node_views if node_views is not None else
                 [n for n in fw["nodes"] if n["id"] in set(node_ids or [])])
        _validate_answer_views(nodes, set(supplied))
        user = _answer_context_prompt(nodes, units, supplied, question)
        data = chat_json(_ANSWER_SELECTED_SYSTEM, user, 4096, "ask")
        return _answer_result(data, set(supplied))
    system = ("You answer questions about one framework using ONLY its definitive document and source units. "
              "If they do not answer it, say so. Output ONLY valid JSON: {\"answer\": str, \"units\": [cited unit "
              "numbers], \"answered\": bool}." + _ANSWER_RESPONSE_CONTRACT)
    user = f"{fw.get('document', '')}\n\nSOURCE UNITS:\n{_units_block(units)}\n\nQUESTION: {question}"
    data = chat_json(system, user, 4096, "ask")
    return _answer_result(data, set(supplied))


# ===========================================================================
# 1-Line AutoMemorySession Middleware SDK & Adaptive Memory Coordination
# ===========================================================================

_CONSTRAINT_KEYWORDS = frozenset({
    "always", "never", "must", "prefer", "preference", "preferring", "prefers",
    "don't", "dont", "do not", "rule", "constraint", "mandatory", "forbidden",
    "require", "requires", "requirement", "restrict", "restriction", "cannot",
    "can't", "cant", "should not", "shouldn't",
})

_GOAL_KEYWORDS = frozenset({
    "goal", "plan", "planning", "want to", "aim to", "need to", "objective",
    "decided", "decision", "will do", "intend to", "intention", "milestone",
    "target", "try to", "trying to", "going to",
})

_FIRST_PERSON_PATTERNS = [
    re.compile(r"\b(?:i am|i'm|i live|i work|i have|i own|i bought|my name|my email|my dog|my cat|my brother|my sister|my wife|my husband)\b", re.IGNORECASE),
]

_ACKNOWLEDGMENT_PATTERNS = [
    re.compile(r"^(?:ok|okay|thanks|thank you|thx|got it|cool|sure|yes|no|yep|nope|bye|hello|hi|hey|good morning|good evening)\.?$", re.IGNORECASE),
]


def score_turn_novelty(turn_text: str, prior_turns: list[str] | None = None) -> float:
    """Compute dynamic turn novelty and salience score in [0.0, 1.0].

    High salience (0.80 - 0.95): explicit constraints, user directives, goals, and decisions.
    Medium salience (0.50 - 0.75): factual claims, first-person statements, informative queries.
    Low salience (0.20 - 0.30): conversational acknowledgments, chit-chat, boilerplate.
    """
    if not isinstance(turn_text, str) or not turn_text.strip():
        return 0.0

    cleaned = turn_text.strip()
    lower = cleaned.lower()
    words = set(re.findall(r"\b\w+\b", lower))
    if not words:
        return 0.0

    # Routine conversational acknowledgments
    for pat in _ACKNOWLEDGMENT_PATTERNS:
        if pat.match(lower):
            return 0.25

    # Check for constraint keywords
    has_constraint = bool(words & _CONSTRAINT_KEYWORDS)

    # Check for goal / decision keywords
    has_goal = bool(words & _GOAL_KEYWORDS)

    # Base novelty score
    if has_constraint:
        base_score = 0.90
    elif has_goal:
        base_score = 0.85
    else:
        # Check for first-person declarative patterns
        has_fp = any(pat.search(lower) for pat in _FIRST_PERSON_PATTERNS)
        if has_fp:
            base_score = 0.75
        else:
            # Check for factual/metrics patterns (e.g. status codes, numerical metrics, technical terms)
            has_metrics = bool(re.search(r"\b\d+\b", lower))
            # Information density scaling based on distinct words and length
            word_count = len(words)
            density = min(1.0, word_count / 20.0)
            base_score = round(min(0.70, max(0.35, 0.40 + 0.30 * density + (0.10 if has_metrics else 0.0))), 4)

    # Repetition check against prior turns
    if prior_turns:
        prior_words: set[str] = set()
        for p in prior_turns:
            prior_words.update(re.findall(r"\b\w+\b", p.lower()))
        if words and prior_words:
            overlap = len(words & prior_words) / len(words)
            if overlap > 0.8:
                base_score = max(0.1, base_score * (1.0 - overlap * 0.8))

    return round(base_score, 4)


def adaptive_context_budget(
    confidence: float = 0.5,
    query_complexity: int = 1,
    max_budget: int = 4096,
    *,
    total_budget: int | None = None,
    active_goal_count: int = 0,
    history_turn_count: int = 0,
    turn_novelty: float = 0.5,
) -> dict[str, int]:
    """Dynamically calibrate and partition the token context sub-budgets.

    Partitions the context window across:
    - goals: active goals and constraints
    - knowledge: living knowledge pages and verified observations
    - evidence: episodic/semantic memory retrieval hits
    """
    effective_total = total_budget if total_budget is not None else max_budget
    if effective_total <= 0:
        return {"goals": 0, "knowledge": 0, "evidence": 0}

    # Dynamic ratio computation
    goal_ratio = 0.15 + (0.05 * min(4, active_goal_count))
    if turn_novelty > 0.7:
        evidence_ratio = 0.55 + 0.15 * (turn_novelty - 0.7) / 0.3
        knowledge_ratio = max(0.15, 1.0 - goal_ratio - evidence_ratio)
    else:
        evidence_ratio = 0.50
        knowledge_ratio = max(0.20, 1.0 - goal_ratio - evidence_ratio)

    total_ratio = goal_ratio + knowledge_ratio + evidence_ratio
    goal_ratio /= total_ratio
    knowledge_ratio /= total_ratio
    evidence_ratio /= total_ratio

    goals_tokens = int(effective_total * goal_ratio)
    knowledge_tokens = int(effective_total * knowledge_ratio)
    evidence_tokens = effective_total - (goals_tokens + knowledge_tokens)

    return {
        "goals": max(0, goals_tokens),
        "knowledge": max(0, knowledge_tokens),
        "evidence": max(0, evidence_tokens),
    }


def _extract_text_content(val: Any) -> str:
    """Extract string content from diverse LLM/chat message or response representations."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        if "content" in val and isinstance(val["content"], str):
            return val["content"]
        if "choices" in val and isinstance(val["choices"], list) and val["choices"]:
            c0 = val["choices"][0]
            if isinstance(c0, dict):
                msg = c0.get("message")
                if isinstance(msg, dict) and "content" in msg:
                    return str(msg["content"])
                if "text" in c0:
                    return str(c0["text"])
    if hasattr(val, "content") and isinstance(val.content, str):
        return val.content
    return str(val) if val is not None else ""


class AutoMemorySession:
    """1-Line drop-in memory session middleware for any chat callable.

    Automatically coordinates:
    1. Pre-turn: dynamic turn-velocity & goal-stability context retrieval with calibrated sub-budgets.
    2. Turn invocation: ContextVar isolation preventing thread state leaks.
    3. Post-turn: dynamic novelty scoring, dual episodic+working turn capture, and active goal detection.
    4. Session exit / close: automatic consolidation into durable observations and assertions.
    """

    def __init__(
        self,
        engine: Any,
        tenant_id: str,
        user_id: str,
        session_id: str | None = None,
        branch: str = "main",
        role: str = "agent",
        agent_id: str = "assistant",
        task_id: str = "chat",
        token_budget: int = 4096,
        max_working_turns: int = 10,
        auto_consolidate: bool = True,
        cache: str | None = None,
        model: str | None = None,
    ) -> None:
        if not tenant_id or not user_id:
            raise ValueError("tenant_id and user_id must be non-empty strings")
        self.engine = engine
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id or f"sess-{uuid4().hex[:12]}"
        self.branch = branch
        self.role = role
        self.agent_id = agent_id
        self.task_id = task_id
        self.token_budget = token_budget
        self.max_working_turns = max_working_turns
        self.auto_consolidate = auto_consolidate
        self.cache = cache
        self.model = model

        self._turn_timestamps: list[float] = []
        self._recent_goal_changes: list[int] = []
        self._turn_count: int = 0
        self._session_evidence_cids: list[str] = []
        self._active_goals: list[str] = []
        self._active_constraints: list[str] = []
        self._last_user_turn_text: str = ""
        self._last_user_evidence_cid: str = ""
        self._closed: bool = False

    def pre_turn_retrieve(self, query: str) -> dict[str, Any]:
        """Perform adaptive context retrieval with dynamic sub-budget partitioning."""
        now = time.monotonic()
        delta_t = (now - self._turn_timestamps[-1]) if self._turn_timestamps else 999.0
        self._turn_timestamps.append(now)

        recent_goal_churn = bool(
            self._recent_goal_changes and (self._turn_count - self._recent_goal_changes[-1] <= 2)
        )

        if recent_goal_churn:
            goals_pct = 0.30
            evidence_pct = 0.45
            knowledge_pct = 0.25
        else:
            goals_pct = 0.15
            knowledge_pct = 0.25
            evidence_pct = 0.60

        turn_window = 6 if delta_t < 10.0 else 3

        active_goals: list[str] = list(self._active_goals)
        active_constraints: list[str] = list(self._active_constraints)
        recent_turns: list[str] = []

        if hasattr(self.engine, "list_working"):
            try:
                items = self.engine.list_working(self.tenant_id, self.session_id)
                for it in items:
                    status = getattr(it, "status", "active")
                    if status != "active":
                        continue
                    k = getattr(it, "kind", "")
                    content = getattr(it, "content", "")
                    if k == "active_goal" and content not in active_goals:
                        active_goals.append(content)
                    elif k in ("active_constraint", "constraint") and content not in active_constraints:
                        active_constraints.append(content)
                    elif k == "conversation_turn":
                        recent_turns.append(content)
            except Exception as exc:
                log.debug("AutoMemorySession list_working error: %s", exc)

        kp_snippets: list[str] = []
        if hasattr(self.engine, "knowledge_page_list"):
            try:
                kps = self.engine.knowledge_page_list(self.tenant_id, branch=self.branch, limit=3)
                for p in kps:
                    kp_snippets.append(f"[{p.path}]: {p.title}\n{p.content_markdown[:250]}")
            except Exception as exc:
                log.debug("AutoMemorySession knowledge_page_list error: %s", exc)

        obs_snippets: list[str] = []
        if hasattr(self.engine, "observation_list"):
            try:
                obs_list = self.engine.observation_list(self.tenant_id, branch=self.branch, status="active", limit=3)
                for o in obs_list:
                    obs_snippets.append(f"({o.subject} / {o.topic}): {o.content}")
            except Exception as exc:
                log.debug("AutoMemorySession observation_list error: %s", exc)

        evidence_hits: list[str] = []
        if query and hasattr(self.engine, "retrieve"):
            try:
                evidence_budget = int(self.token_budget * evidence_pct)
                ret = self.engine.retrieve(
                    self.tenant_id,
                    query=query,
                    branch=self.branch,
                    token_budget=evidence_budget,
                )
                for h in getattr(ret, "hits", [])[:5]:
                    c = getattr(h, "content", getattr(h, "text", ""))
                    if c:
                        evidence_hits.append(f"[cid:{getattr(h, 'cid', '')}] {c[:250]}")
            except Exception as exc:
                log.debug("AutoMemorySession retrieve error: %s", exc)

        sections: list[str] = []
        if active_goals or active_constraints:
            g_lines: list[str] = []
            if active_goals:
                g_lines.append("Active Goals:\n" + "\n".join(f"- {g}" for g in active_goals))
            if active_constraints:
                g_lines.append("Active Constraints:\n" + "\n".join(f"- {c}" for c in active_constraints))
            sections.append("### Active Goals & Constraints\n" + "\n".join(g_lines))

        if kp_snippets or obs_snippets:
            k_lines: list[str] = []
            if kp_snippets:
                k_lines.append("Living Knowledge Pages:\n" + "\n".join(kp_snippets))
            if obs_snippets:
                k_lines.append("Verified Observations:\n" + "\n".join(obs_snippets))
            sections.append("### Living Knowledge & Observations\n" + "\n".join(k_lines))

        if evidence_hits:
            sections.append("### Relevant Memory Evidence\n" + "\n".join(evidence_hits))

        if recent_turns:
            selected_turns = recent_turns[-turn_window:]
            sections.append("### Recent Conversation Context\n" + "\n".join(f"- {t}" for t in selected_turns))

        context_str = "\n\n".join(sections)
        if context_str:
            context_str = f"<memory_context>\n{context_str}\n</memory_context>"

        return {
            "context_text": context_str,
            "sub_budgets": {
                "goals": goals_pct,
                "knowledge": knowledge_pct,
                "evidence": evidence_pct,
            },
            "active_goals": active_goals,
            "active_constraints": active_constraints,
            "turn_window": turn_window,
        }

    def post_turn_capture(self, user_text: str, assistant_text: str) -> dict[str, Any]:
        """Atomically record user and assistant turns into working memory and durable evidence."""
        from mnemosyne.engine import WorkingMemoryItem
        from mnemosyne.ids import evidence_cid
        from mnemosyne.models import Evidence, utc_now

        self._turn_count += 1
        now = utc_now()
        expires = now + timedelta(hours=12)
        user_salience = score_turn_novelty(user_text)

        # 1. Mirror User Turn to durable Evidence
        cid_user = evidence_cid(
            user_text,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            source_type="chat",
            content_pointer=None,
            modality="text",
            sensitivity=0,
        )
        ev_user = Evidence(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=self.session_id,
            actor="user",
            source_type="chat",
            content=user_text,
            branch=self.branch,
            cid=cid_user,
            created_at=now,
        )
        if hasattr(self.engine, "append_evidence"):
            self.engine.append_evidence(ev_user, branch=self.branch)
        self._session_evidence_cids.append(cid_user)
        self._last_user_turn_text = user_text
        self._last_user_evidence_cid = cid_user

        # 2. Store User Turn in Working Memory
        item_user = WorkingMemoryItem(
            item_id=f"turn-user-{uuid4().hex[:8]}",
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            user_id=self.user_id,
            agent_id=self.agent_id,
            kind="conversation_turn",
            task_id=self.task_id,
            content=user_text,
            created_at=now,
            expires_at=expires,
            evidence_ids=[cid_user],
            salience=user_salience,
        )
        if hasattr(self.engine, "put_working"):
            try:
                self.engine.put_working(item_user)
            except Exception as exc:
                log.debug("AutoMemorySession put_working user turn error: %s", exc)

        # 3. Mirror Assistant Turn to durable Evidence
        cid_asst = evidence_cid(
            assistant_text,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            source_type="chat",
            content_pointer=None,
            modality="text",
            sensitivity=0,
        )
        ev_asst = Evidence(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            session_id=self.session_id,
            actor="assistant",
            source_type="chat",
            content=assistant_text,
            branch=self.branch,
            cid=cid_asst,
            created_at=now,
        )
        if hasattr(self.engine, "append_evidence"):
            self.engine.append_evidence(ev_asst, branch=self.branch)
        self._session_evidence_cids.append(cid_asst)

        # 4. Store Assistant Turn in Working Memory
        item_asst = WorkingMemoryItem(
            item_id=f"turn-asst-{uuid4().hex[:8]}",
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            user_id=self.user_id,
            agent_id=self.agent_id,
            kind="conversation_turn",
            task_id=self.task_id,
            content=assistant_text,
            created_at=now,
            expires_at=expires,
            evidence_ids=[cid_asst],
            salience=0.50,
        )
        if hasattr(self.engine, "put_working"):
            try:
                self.engine.put_working(item_asst)
            except Exception as exc:
                log.debug("AutoMemorySession put_working asst turn error: %s", exc)

        # 5. Extract Active Goals & Constraints from User Turn
        goal_match = re.search(r"(?:my goal is|i want to|aim to|need to|objective is)\s+([^.!?\n]+)", user_text, re.IGNORECASE)
        if goal_match:
            goal_text = goal_match.group(0).strip()
            if goal_text not in self._active_goals:
                self._active_goals.append(goal_text)
                self._recent_goal_changes.append(self._turn_count)
                g_item = WorkingMemoryItem(
                    item_id=f"goal-{uuid4().hex[:8]}",
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    kind="active_goal",
                    task_id=self.task_id,
                    content=goal_text,
                    created_at=now,
                    expires_at=expires,
                    evidence_ids=[cid_user],
                    salience=0.90,
                )
                if hasattr(self.engine, "put_working"):
                    try:
                        self.engine.put_working(g_item)
                    except Exception as exc:
                        log.debug("AutoMemorySession put_working goal error: %s", exc)

        constraint_match = re.search(r"(?:always|never|must|prefer)\s+([^.!?\n]+)", user_text, re.IGNORECASE)
        if constraint_match:
            constraint_text = constraint_match.group(0).strip()
            if constraint_text not in self._active_constraints:
                self._active_constraints.append(constraint_text)
                self._recent_goal_changes.append(self._turn_count)
                c_item = WorkingMemoryItem(
                    item_id=f"constraint-{uuid4().hex[:8]}",
                    tenant_id=self.tenant_id,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    kind="active_constraint",
                    task_id=self.task_id,
                    content=constraint_text,
                    created_at=now,
                    expires_at=expires,
                    evidence_ids=[cid_user],
                    salience=0.92,
                )
                if hasattr(self.engine, "put_working"):
                    try:
                        self.engine.put_working(c_item)
                    except Exception as exc:
                        log.debug("AutoMemorySession put_working constraint error: %s", exc)

        return {
            "turn": self._turn_count,
            "salience": user_salience,
            "user_cid": cid_user,
            "assistant_cid": cid_asst,
            "active_goals": list(self._active_goals),
            "active_constraints": list(self._active_constraints),
        }

    def wrap(self, chat_fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        """Wrap a chat callable with transparent, bidirectional memory coordination."""

        def _wrapped(messages: Any, *args: Any, **kwargs: Any) -> Any:
            query = ""
            if isinstance(messages, str):
                query = messages
            elif isinstance(messages, list) and messages:
                last_msg = messages[-1]
                if isinstance(last_msg, dict):
                    query = str(last_msg.get("content", ""))
                elif hasattr(last_msg, "content"):
                    query = str(last_msg.content)

            # 1. Pre-turn retrieval
            retrieval = self.pre_turn_retrieve(query)
            context_text = retrieval["context_text"]

            # 2. Inject context into prompt
            if context_text:
                if isinstance(messages, str):
                    augmented_messages: Any = f"{context_text}\n\n{messages}"
                elif isinstance(messages, list):
                    augmented_messages = list(messages)
                    if augmented_messages and isinstance(augmented_messages[0], dict) and augmented_messages[0].get("role") == "system":
                        sys_copy = dict(augmented_messages[0])
                        sys_copy["content"] = f"{context_text}\n\n{sys_copy['content']}"
                        augmented_messages[0] = sys_copy
                    else:
                        augmented_messages.insert(0, {"role": "system", "content": context_text})
                else:
                    augmented_messages = messages
            else:
                augmented_messages = messages

            # 3. Invoke chat callable within safe ContextVar scope
            with framework_context(cache=self.cache, model=self.model):
                response = chat_fn(augmented_messages, *args, **kwargs)

            # 4. Post-turn turn capture
            asst_text = _extract_text_content(response)
            self.post_turn_capture(query, asst_text)

            return response

        setattr(_wrapped, "session", self)
        return _wrapped

    def step(self, user_input: str | dict[str, Any], chat_fn: Callable[[Any], Any]) -> Any:
        """Execute a single interactive conversation turn with automatic memory coordination."""
        wrapped = self.wrap(chat_fn)
        return wrapped(user_input)

    def consolidate(self) -> dict[str, Any]:
        """Consolidate session working memory and active directives into durable observations."""
        from mnemosyne.observations import Observation, ProofQuote

        consolidated_obs: list[str] = []
        user_cid = self._last_user_evidence_cid
        user_text = self._last_user_turn_text

        # Consolidate active goals
        for goal in self._active_goals:
            pq = None
            if user_cid and user_text and goal in user_text:
                start = user_text.find(goal)
                end = start + len(goal)
                sha = hashlib.sha256(goal.encode("utf-8")).hexdigest()
                pq = ProofQuote(cid=user_cid, quote=goal, start=start, end=end, sha256=sha)
            elif user_cid and user_text:
                sha = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
                pq = ProofQuote(cid=user_cid, quote=user_text, start=0, end=len(user_text), sha256=sha)

            obs = Observation(
                tenant_id=self.tenant_id,
                observation_id=f"obs-goal-{uuid4().hex[:8]}",
                user_id=self.user_id,
                subject="UserGoal",
                topic="Goal",
                content=f"User stated active goal: {goal}",
                proof_quotes=[pq] if pq is not None else [],
                source_evidence_cids=[user_cid] if user_cid else [],
                branch=self.branch,
            )
            if hasattr(self.engine, "observation_upsert"):
                try:
                    self.engine.observation_upsert(obs, branch=self.branch)
                    consolidated_obs.append(obs.observation_id)
                except Exception as exc:
                    log.debug("AutoMemorySession consolidate goal observation error: %s", exc)

        # Consolidate active constraints
        for constraint in self._active_constraints:
            pq = None
            if user_cid and user_text and constraint in user_text:
                start = user_text.find(constraint)
                end = start + len(constraint)
                sha = hashlib.sha256(constraint.encode("utf-8")).hexdigest()
                pq = ProofQuote(cid=user_cid, quote=constraint, start=start, end=end, sha256=sha)
            elif user_cid and user_text:
                sha = hashlib.sha256(user_text.encode("utf-8")).hexdigest()
                pq = ProofQuote(cid=user_cid, quote=user_text, start=0, end=len(user_text), sha256=sha)

            obs = Observation(
                tenant_id=self.tenant_id,
                observation_id=f"obs-constraint-{uuid4().hex[:8]}",
                user_id=self.user_id,
                subject="UserPreference",
                topic="Constraint",
                content=f"User stated constraint: {constraint}",
                proof_quotes=[pq] if pq is not None else [],
                source_evidence_cids=[user_cid] if user_cid else [],
                branch=self.branch,
            )
            if hasattr(self.engine, "observation_upsert"):
                try:
                    self.engine.observation_upsert(obs, branch=self.branch)
                    consolidated_obs.append(obs.observation_id)
                except Exception as exc:
                    log.debug("AutoMemorySession consolidate constraint observation error: %s", exc)

        return {
            "consolidated": True,
            "observations_created": consolidated_obs,
            "turns_processed": self._turn_count,
            "evidence_count": len(self._session_evidence_cids),
        }

    def close(self) -> dict[str, Any]:
        """Close the session and trigger auto-consolidation if enabled."""
        if not self._closed:
            self._closed = True
            if self.auto_consolidate:
                return self.consolidate()
        return {"closed": True}

    def __enter__(self) -> AutoMemorySession:
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        self.close()


def wrap_chat_callable(
    chat_fn: Callable[[Any], Any],
    engine: Any,
    tenant_id: str,
    user_id: str,
    session_id: str | None = None,
    branch: str = "main",
    role: str = "agent",
    token_budget: int = 4096,
    max_working_turns: int = 10,
    auto_consolidate: bool = True,
    cache: str | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> Callable[[Any], Any]:
    """1-Line factory helper wrapping any chat callable with AutoMemorySession middleware."""
    session = AutoMemorySession(
        engine=engine,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        branch=branch,
        role=role,
        token_budget=token_budget,
        max_working_turns=max_working_turns,
        auto_consolidate=auto_consolidate,
        cache=cache,
        model=model,
        **kwargs,
    )
    return session.wrap(chat_fn)

