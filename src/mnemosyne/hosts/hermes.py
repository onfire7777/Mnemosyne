"""Hermes lifecycle adapter. Outcome interpretation stays in Mnemosyne."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from mnemosyne.experience.receipts import digest
from mnemosyne.experience.integration import (
    build_learning_runtime, end_learning_session, observe_completed_turn,
)
from mnemosyne.sqlite_engine import SqliteEngine


class HermesAdapter:
    def __init__(self, runtime=None, *, tenant_id=None, user_id=None):
        self.runtime = runtime
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = ""
        self._writable = True
        self._pending = {}
        self._used_skills = {}
        self._lock = threading.RLock()

    @property
    def name(self):
        return "mnemosyne"

    def is_available(self):
        return True

    def initialize(self, session_id, **kwargs):
        with self._lock:
            if self.runtime is None:
                home = kwargs.get("hermes_home")
                if not home:
                    raise ValueError("Hermes must supply its profile-scoped home")
                root = Path(home).expanduser().resolve()
                self.tenant_id = "hermes-" + digest(str(root))[:24]
                self.user_id = str(kwargs.get("user_id") or "primary")
                self.runtime = build_learning_runtime(SqliteEngine(root / "mnemosyne"))
            self.session_id = session_id
            self._writable = kwargs.get("agent_context", "primary") == "primary"

    def get_tool_schemas(self):
        return []

    def system_prompt_block(self):
        return ""

    def prefetch(self, query, *, session_id=""):
        session = session_id or self.session_id
        with self._lock:
            context = self.runtime.prepare_context(
                self.tenant_id, self.user_id, session, query
            )
            self._pending[session] = context["receipt_id"]
            # This boundary explicitly marks returned memory as untrusted data.
            return json.dumps(
                {
                    "kind": "retrieved_memory_data",
                    "instruction_authority": "none",
                    "context": context,
                },
                ensure_ascii=False,
            )

    def on_skill_lifecycle(self, skill_id, *, session_id="", revision=None, **kwargs):
        session = session_id or self.session_id
        with self._lock:
            self._used_skills.setdefault(session, []).append(skill_id)

    def sync_turn(
        self,
        user_content,
        assistant_content,
        *,
        session_id="",
        messages=None,
        turn_author=None,
    ):
        if not self._writable or (turn_author and turn_author.get("is_bot")):
            return None
        if (
            turn_author
            and turn_author.get("id")
            and str(turn_author["id"]) != self.user_id
        ):
            raise ValueError("turn author differs from the initialized profile user")
        session = session_id or self.session_id
        events = []
        for message in reversed(messages or []):
            if message.get("role") == "user":
                break
            if message.get("role") == "tool":
                content = message.get("content", "")
                try:
                    payload = (
                        json.loads(content) if isinstance(content, str) else content
                    )
                except (TypeError, ValueError):
                    payload = {"output": str(content)}
                if isinstance(payload, dict):
                    events.append(
                        {
                            **payload,
                            "source": "tool",
                            "name": message.get("name", "tool"),
                        }
                    )
        events.reverse()
        with self._lock:
            receipt = self._pending.pop(session, None)
            return observe_completed_turn(
                self.runtime,
                self.tenant_id,
                self.user_id,
                session,
                user_content,
                assistant_content,
                tool_events=events,
                receipt_ids=[receipt] if receipt else [],
                used_skills=self._used_skills.pop(session, []),
            )

    def on_session_switch(self, new_session_id, **kwargs):
        self.session_id = new_session_id

    def on_session_end(self, messages):
        with self._lock:
            result = end_learning_session(self.runtime, self.tenant_id,
                                          self.user_id, self.session_id)
            self._pending.pop(self.session_id, None)
            return result

    def shutdown(self):
        if self.runtime is not None:
            close = getattr(self.runtime.engine, "close", None)
            if close:
                close()
