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
import hashlib
import http.client
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Callable

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-5.2"
#: The model a conversion runs on (BurnOS's working model); per thread, so conversions side by
#: side keep their own.
MODEL: ContextVar[str] = ContextVar("framework_model", default="")
#: A folder where every answer of a conversion is kept, so a build cut off by a restart or a failed
#: call picks up where it stopped: a request with the same model, prompt and inputs is not asked twice.
CACHE: ContextVar[str] = ContextVar("framework_cache", default="")
MAX_PASSES = 2
FIELD_BATCH = 6
#: The most source one extraction prompt reads; a longer source (a book) is built part by part,
#: every part through the whole method, and the parts joined - so no passage is left out.
WINDOW_CHARS = 60_000
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


def chat_json(system: str, user: str, max_tokens: int = 8192, task: str = "", shared: str = "") -> dict[str, Any]:
    """One chat completion answered in JSON - on OpenRouter, or for a codex:<model> through the Codex
    program on the user's ChatGPT subscription; an empty or unreadable answer is asked again once.

    With ``shared`` (the source and the node list every call of a pass reads) the prompt is laid out
    for the provider's prompt cache: the fixed RULEBOOK, then ``shared``, then this call's task
    (``system`` and ``user``). Calls of one pass then differ only at their end, so the long start
    is read from the cache at a fraction of the price."""
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
                    with open(kept + ".tmp", "w", encoding="utf-8") as f:
                        json.dump(parsed, f)
                    os.replace(kept + ".tmp", kept)
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


def _parallel(calls: list[Callable[[], Any]]) -> list[Any]:
    """Run the calls side by side, each in a copy of this thread's context (the model)."""
    with ThreadPoolExecutor(max_workers=max(1, min(64, len(calls)))) as pool:  # every chapter and batch at once
        futures = [pool.submit(contextvars.copy_context().run, c) for c in calls]
        return [f.result() for f in futures]


def _units_block(units: list[str], numbers: list[int] | None = None) -> str:
    """The units by their number in the whole source - all of them, or one part's."""
    return "\n\n".join(f"[Unit {i}]\n{units[i - 1]}" for i in (numbers or range(1, len(units) + 1)))


def _nodes_block(nodes: list[dict[str, Any]], fields: bool = False) -> str:
    """Every node with its whole content - and, for the auditors, its definitive fields and tags."""
    return "\n".join(f"[{n['id']}] {n['type']}: {n['title']} - {' '.join(n['content'].split())}"
                     + (f"\n    fields: {json.dumps(n['fields'], ensure_ascii=False)}" if fields and n['fields'] else "")
                     for n in nodes)


def _edges_block(edges: list[dict[str, Any]]) -> str:
    return "\n".join(f"{e['from']} -[{e['type']}]-> {e['to']}: {e.get('why') or ''}" for e in edges) or "none"


def _source(name: str, units: list[str], numbers: list[int] | None) -> str:
    """The start every call of a pass shares: the name and the units it is built from. A joined
    book (no ``numbers``) is too long for one prompt and stands here as its nodes."""
    book = BOOK.get()
    if book and not numbers:
        return f"{book}\n\nTHE WHOLE BOOK'S FRAMEWORK, joined from its chapters, follows."
    if book:  # read once already: this part is a pointer into it, never a second copy of its text
        return (f"{book}\n\nTHIS PART: {LABEL.get() or 'a part'} - units {numbers[0]}-{numbers[-1]} of {len(units)}. "
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
        data = chat_json(FIELDS_SYSTEM, f"Items:\n{json.dumps(chunk, ensure_ascii=False)}", 8192, "fields", shared=shared)
        for out in data.get("items") or []:
            idx = _int(out.get("index")) if isinstance(out, dict) else None
            if idx is not None and 0 <= idx < len(nodes):
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
    weak = [n for n in nodes if n["type"] in _TAGGED and n["units"] and (
        not all(n["fields"].get(t) for t in ("ES", "EC", "CT", "CN"))
        or not (n["fields"].get("Source Quote") or {}).get("Quote"))]

    def batch(chunk: list[dict[str, Any]]) -> None:
        items = [{"index": n["id"], "type": n["type"], "title": n["title"], "units": n["units"]} for n in chunk]
        system = ("These framework items lack their evidence tags or quote. Output ONLY valid JSON: {\"items\": "
                  "[{\"index\": int, \"Source Quote\": {\"Quote\": at most 60 words copied from the units the item "
                  "cites, \"Core Sentence\": its most evidential sentence}, \"ES\", \"EC\", \"CT\", \"CN\", "
                  "\"Tag justifications\"}]}. " + TAGS + " Never use gap wording for tags; pick the closest label.")
        data = chat_json(system, f"Items:\n{json.dumps(items, ensure_ascii=False)}", 8192, "repair", shared=shared)
        for out in data.get("items") or []:
            idx = _int(out.get("index")) if isinstance(out, dict) else None
            if idx is not None and 0 <= idx < len(nodes):
                for key in ("Source Quote", "ES", "EC", "CT", "CN", "Tag justifications"):
                    if out.get(key) and not nodes[idx]["fields"].get(key):
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
    data = chat_json(LOGIC_SYSTEM, f"Relations:\n{_edges_block(fw['edges'])}", 8192, "logic", shared=_shared(fw, units))
    logic: dict[str, Any] = {k: [str(x) for x in data.get(k) or []] for k in ("graph_issues", "logic_issues", "logic_warnings")}
    logic["note"] = str(data.get("note") or "")
    return logic


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
    if fw["logic"]["graph_issues"]:
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
    + "\nEvery definition, principle, step, warning and constraint also has \"Source Quote\": {\"Quote\": at most "
    "60 words from the units it cites, \"Core Sentence\": its most evidential sentence}, \"ES\", \"EC\", \"CT\", "
    "\"CN\" and \"Tag justifications\". " + TAGS + "\n\nRELATIONS. " + EDGES_SYSTEM[EDGES_SYSTEM.index("Edge types:"):]
)


def judge(fw: dict[str, Any], units: list[str]) -> dict[str, Any]:
    part = f"This framework is one part of a longer book ({fw['part']}); judge it as that part.\n\n" if fw.get("part") else ""
    fields = "\n".join(f"[{n['id']}] {json.dumps(n['fields'], ensure_ascii=False)}" for n in fw["nodes"] if n["fields"])
    user = (f"{part}Definitive fields, quotes and tags by node id:\n{fields or 'none'}\n\nRelations:\n"
            f"{_edges_block(fw['edges'])}\n\nLogic audit: {json.dumps(fw['logic'])}\n\nMechanical audit: "
            f"{json.dumps(fw['mechanical'])}\n\nUnits no node cites: {fw['coverage']['unresolved'] or 'none'}")
    data = chat_json(JUDGE_SYSTEM, user, 4096, "judge", shared=_shared(fw, units))
    instructions = str(data.get("extractor_instructions") or "").strip()
    return {"warrants_reextract": bool(data.get("warrants_reextract")) and len(instructions) >= 24,
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
    seen, out = set(), []
    for e in raw:
        a, b, kind = _int(e.get("from")), _int(e.get("to")), str(e.get("type") or "").strip().lower()
        kind = "tension" if kind in ("opposes", "tension_pair") else kind
        if a not in kinds or b not in kinds or a == b or kind not in EDGE_TYPES:
            continue
        kind, flip = REMAP.get((kinds[a], kinds[b], kind), (kind, False))
        if flip or (kind == "tension" and a > b):
            a, b = b, a
        if (a, b, kind) not in seen:
            seen.add((a, b, kind))
            out.append({"from": a, "to": b, "type": kind, "why": str(e.get("why") or "")[:300]})
    return out


def coverage(units: list[str], nodes: list[dict[str, Any]], numbers: list[int] | None = None,
             reference: dict[int, str] | None = None) -> dict[str, Any]:
    """Every unit is represented, a duplicate of an earlier one, reference matter the map marked
    (``reference``: unit -> its chapter; kept as source, not built), or unresolved (its text stays kept)."""
    reference = reference or {}
    cited: dict[int, list[str]] = {}
    for n in nodes:
        for u in n["units"]:
            cited.setdefault(u, []).append(n["title"])
    seen: dict[str, int] = {}
    rows = []
    for i in numbers or range(1, len(units) + 1):
        text = units[i - 1]
        key = " ".join(text.split()).lower()
        if i in cited:
            rows.append({"unit": i, "status": "represented", "nodes": cited[i]})
        elif key in seen:
            rows.append({"unit": i, "status": "duplicate", "of": seen[key]})
        elif i in reference:
            rows.append({"unit": i, "status": "reference", "of": reference[i]})
        else:
            rows.append({"unit": i, "status": "unresolved"})
        seen.setdefault(key, i)
    unresolved = [r["unit"] for r in rows if r["status"] == "unresolved"]
    return {"units": rows, "unresolved": unresolved, "complete": not unresolved}


def mechanical_audit(fw: dict[str, Any]) -> dict[str, Any]:
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
        if quote and len(str(quote.get("Quote") or "").split()) > 60:
            quote["Quote"] = " ".join(str(quote["Quote"]).split()[:60]) + " ..."
            repairs.append(f"{n['title']}: Source Quote cut to 60 words")
        if n["type"] in _TAGGED and not all(f.get(t) for t in ("ES", "EC", "CT", "CN")):
            failures.append(f"{n['title']}: epistemic tags missing")
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
        return [f"### {heading}", n["content"], *_field_lines(n["fields"]),
                f"\n*Source units: {cite or 'none'}*", ""]

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
        rows = [f"| {by_id[e['from']]['title']} | {e['type']} | {by_id[e['to']]['title']} | {e['why']} |"
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
    out += ["## 9. Scope and Limits", "", "### 9A Scope conditions",
            f"Claimed: {meta['claimed_scope']}", "", f"Evidenced: {meta['evidenced_scope']}", "",
            "### 9B Methodological limits", meta["assumptions_limits"], "", "### 9C Acknowledged gaps",
            *([f"- {g}" for g in gaps] or ["None."]), "", "### 9D Internal tensions",
            *([f"- {t}" for t in tensions] or ["None found."]), ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------------- build


def windows(units: list[str]) -> list[list[int]]:
    """Unit numbers in reading order, cut into parts of at most WINDOW_CHARS (a unit is never split)."""
    parts: list[list[int]] = [[]]
    size = 0
    for i, text in enumerate(units, 1):
        if parts[-1] and size + len(text) > WINDOW_CHARS:
            parts.append([])
            size = 0
        parts[-1].append(i)
        size += len(text)
    return parts


MAP_SYSTEM = (
    "You have read the WHOLE book above. Map it, from the whole text, for the parts that will be built from "
    "it side by side. Output ONLY valid JSON: {\"chapters\": [{\"title\": str, \"first_unit\": int, "
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
#: The whole book (and, once written, its map): the start every call of a book build shares. The
#: book is read once, here; every part's work branches from it.
BOOK: ContextVar[str] = ContextVar("framework_book", default="")
#: The chapter a part of a book build is working on.
LABEL: ContextVar[str] = ContextVar("framework_part", default="")


def map_book(name: str, units: list[str]) -> dict[str, Any]:
    """The map of the whole book, from one reading of it."""
    data = chat_json(MAP_SYSTEM + META_SYSTEM, "Write the map of the whole book.", 32000, "map", shared=BOOK.get())
    return data if isinstance(data, dict) else {}


REFERENCE_TITLE = re.compile(r"^\s*(notes|end ?notes|bibliography|references|works cited|index|acknowledge?ments?|"
                             r"about the authors?|(table of )?contents|copyright\b)", re.IGNORECASE)


def chapters(book_map: dict[str, Any], units: list[str]) -> list[tuple[str, list[int], bool]]:
    """The map's chapters as unit ranges that cover every unit exactly once, in order: a gap joins the
    chapter before it, an overlap is cut, and a chapter longer than one part is split - so no
    passage falls between chapters or is built twice. Fixed parts when the map gives none. The third
    value is True for reference matter (bibliography, notes, index ...), which is not built."""
    marks = []
    for c in book_map.get("chapters") or []:
        first = _int(c.get("first_unit")) if isinstance(c, dict) else None
        if first is not None and 1 <= first <= len(units):
            title = str(c.get("title") or "").strip()[:80]
            # the model kept a book's Notes as content once (Blue Ocean, 18 Oct 2026): titles settle it too
            marks.append((first, (title, str(c.get("kind")).lower() == "reference" or bool(REFERENCE_TITLE.match(title)))))
    marks = sorted(dict(sorted(marks, reverse=True)).items())  # one title per first unit
    if not marks:
        return [(f"Part {i}", part, False) for i, part in enumerate(windows(units), 1)]
    if marks[0][0] != 1:
        marks.insert(0, (1, ("Front matter", False)))  # unmapped: built, never dropped unseen
    out: list[tuple[str, list[int], bool]] = []
    for i, (first, (title, reference)) in enumerate(marks):
        last = marks[i + 1][0] - 1 if i + 1 < len(marks) else len(units)
        pieces = windows(units[first - 1:last])
        for j, piece in enumerate(pieces, 1):
            label = title or f"Chapter {i + 1}"
            out.append((label if len(pieces) == 1 else f"{label} ({j} of {len(pieces)})",
                        [first - 1 + u for u in piece], reference))
    return out


def build(name: str, units: list[str], progress: Callable[[str], None] = lambda _: None,
          similar: Callable[[list[str]], list[list[float]]] | None = None) -> dict[str, Any]:
    """The complete framework of a source. For a codex: model the build runs on one long-lived Codex
    server (CodexServer), so the source is read once and every call branches from it."""
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    server = None
    # shortcut: the long-lived server stalls under parallel book load (0 CPU, requests unanswered; Codex 0.163.0,
    # 18 Oct 2026), so it is opt-in and codex exec runs each call; make it the default once Codex fixes that.
    if model.startswith("codex:") and SERVER.get() is None and os.getenv("MNEMOSYNE_CODEX_SERVER") == "1":
        name_ = model.split(":", 1)[1].strip()
        try:
            server = CodexServer(None if name_ in ("", "default") else name_)
        except Exception as exc:  # noqa: BLE001 - an older Codex: one program per call instead
            log.warning("Codex app-server unavailable (%s); using codex exec", exc)
    token = SERVER.set(server)
    try:
        return _build(name, units, progress, similar)
    finally:
        SERVER.reset(token)
        if server:
            server.close()


def _build(name: str, units: list[str], progress: Callable[[str], None],
           similar: Callable[[list[str]], list[list[float]]] | None) -> dict[str, Any]:
    """A source that fits one prompt goes through Proper Thinking's loop once. A book is read ONCE,
    whole, and mapped (chapters, glossary, spine, links, overview); then every chapter goes through
    the whole loop side by side, branching from that reading with the map in hand, and the
    chapters are joined by the map's canonical names. Nothing is selected or left out: coverage
    is checked over every unit."""
    if len(windows(units)) == 1:
        fw = _passes(name, units, list(range(1, len(units) + 1)), progress)
    else:
        progress("reading the whole book once and mapping it")
        token = BOOK.set(f"Framework name: {name}\n\nTHE WHOLE BOOK ({len(units)} units):\n{_units_block(units)}")
        try:
            book_map = map_book(name, units)
            # read once: from here on the chapters carry the map and only their own passages
            BOOK.set(f"Framework name: {name}\n\nBOOK MAP (written from one reading of the whole book):\n"
                     f"{json.dumps(_map_for_parts(book_map), ensure_ascii=False)}")
            mapped = chapters(book_map, units)
            parts = [(label, numbers) for label, numbers, reference in mapped if not reference]
            reference = {u: label for label, numbers, ref in mapped if ref for u in numbers}
            if not parts:  # a map that calls everything reference is wrong: build it all
                parts, reference = [(label, numbers) for label, numbers, _ in mapped], {}
            done: list[int] = []

            def one(label: str, numbers: list[int]) -> dict[str, Any]:
                out = _passes(name, units, numbers, label=label)
                done.append(1)
                progress(f"{len(done)} of {len(parts)} chapters built")
                return out

            progress(f"building the book's {len(parts)} chapters side by side")
            fw = join(name, units, _parallel([lambda p=p: one(*p) for p in parts]), book_map, reference)
            if similar:
                merge_near_duplicates(fw, units, similar)
            progress("auditing the whole book")
            fw["meta"] = _overview(book_map.get("overview") or {})
            by_chapter = fw["logic"]
            audit_logic(fw, units)  # contradictions between chapters, over the joined nodes
            for k in ("graph_issues", "logic_issues", "logic_warnings"):
                fw["logic"][k] = by_chapter[k] + [f"Whole book: {x}" for x in fw["logic"][k]]
            fw["mechanical"] = mechanical_audit(fw)
        finally:
            BOOK.reset(token)
    fw["generated"] = datetime.now(UTC).isoformat(timespec="seconds")
    fw["approved"] = not fw["logic"]["logic_issues"]  # Proper Thinking's governor: reported, never blocking
    fw["document"] = render(fw)
    return fw


def _map_for_parts(book_map: dict[str, Any]) -> dict[str, Any]:
    """What every chapter is told: the chapters, glossary, spine and links (not the overview)."""
    return {k: book_map.get(k) or [] for k in ("chapters", "glossary", "spine", "links")}


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
    instructions, rebuild = "", True
    fw: dict[str, Any] = {}
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    for passes in range(1, MAX_PASSES + 1):
        touched: set[int] | None = None  # None: every node is new
        if rebuild:
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
        fw["mechanical"] = mechanical_audit(fw)
        progress(f"pass {passes}: judgment audit")
        fw["judgment"] = judge(fw, units)
        missing = fw["coverage"]["unresolved"]
        if passes < MAX_PASSES and (missing or fw["judgment"]["warrants_reextract"]):
            instructions = fw["judgment"]["extractor_instructions"]
            rebuild = fw["judgment"]["rebuild"]
            if missing:
                instructions += (f"\nCOVERAGE: units {missing} are not represented by any node. Represent "
                                 "every one of them, keeping everything already represented.")
            continue
        break
    return fw


def _name(title: str) -> str:
    """A title as a name to match on: case, punctuation, a Step/Warning/Constraint prefix and plurals aside."""
    title = re.sub(r"^(step\s*\d+|warning|constraint)\s*[:.-]\s*", "", title.strip(), flags=re.I)
    return " ".join(w.rstrip("s") for w in re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


MERGED = ("section", "definition", "step", "principle")


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
            if n["type"] in MERGED and key in seen:
                same = nodes[seen[key]]
                same["units"] = sorted(set(same["units"]) | set(n["units"]))
                if n["type"] != "section" and n["content"] and n["content"] not in same["content"]:
                    same["content"] += f"\n\n{n['content']}"
                same["cross"] = (same.get("cross") or []) + (n.get("cross") or [])
                where[n["id"]] = same["id"]
                continue
            where[n["id"]] = len(nodes)
            nodes.append({**n, "id": len(nodes), "part": p})
            new.append(nodes[-1])
            if n["type"] in MERGED:
                seen[key] = where[n["id"]]
        for n in new:  # a part's own indexes, now the joined framework's
            for key in ("parent", "depends_on"):
                n[key] = where.get(n[key]) if n[key] is not None else None
                if n[key] == n["id"]:
                    n[key] = None
        edges += [{**e, "from": where[e["from"]], "to": where[e["to"]]} for e in part["edges"]
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
            "judgment": {"warrants_reextract": False, "extractor_instructions": "", "findings": findings}}


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
    data = chat_json(MERGE_SYSTEM, f"Pairs (by node id):\n{listing}", 4096, "merge", shared=_shared(fw, units))
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
        keep["units"] = sorted(set(keep["units"]) | set(nodes[drop]["units"]))
        if nodes[drop]["content"] and nodes[drop]["content"] not in keep["content"]:
            keep["content"] += f"\n\n{nodes[drop]['content']}"
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


def ask(fw: dict[str, Any], units: list[str], question: str, numbers: list[int] | None = None,
        node_ids: list[int] | None = None) -> dict[str, Any]:
    """Proper Thinking's framework Q&A: answered from the framework and its source only. For a book,
    ``numbers`` and ``node_ids`` are the passages and nodes the question is about, given in full."""
    if numbers is not None:
        nodes = [n for n in fw["nodes"] if n["id"] in set(node_ids or [])]
        system = ("You answer questions about one framework built from a book, using ONLY the framework items "
                  "and book passages given, which were found for this question. If they do not answer it, say so. "
                  "Output ONLY valid JSON: {\"answer\": str, \"units\": [cited unit numbers], \"answered\": bool}.")
        user = (f"FRAMEWORK ITEMS:\n{_nodes_block(nodes, fields=True) or 'none'}\n\nBOOK PASSAGES:\n"
                f"{_units_block(units, numbers) if numbers else 'none'}\n\nQUESTION: {question}")
        data = chat_json(system, user, 4096, "ask")
        return {"answer": str(data.get("answer") or "No answer."), "units": data.get("units") or [],
                "answered": bool(data.get("answered"))}
    system = ("You answer questions about one framework using ONLY its definitive document and source units. "
              "If they do not answer it, say so. Output ONLY valid JSON: {\"answer\": str, \"units\": [cited unit "
              "numbers], \"answered\": bool}.")
    user = f"{fw.get('document', '')[:40000]}\n\nSOURCE UNITS:\n{_units_block(units)[:40000]}\n\nQUESTION: {question}"
    data = chat_json(system, user, 4096, "ask")
    return {"answer": str(data.get("answer") or "No answer."), "units": data.get("units") or [],
            "answered": bool(data.get("answered"))}
