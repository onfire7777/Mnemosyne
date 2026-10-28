"""Dual user model: authoritative explicit entries plus advisory latent state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
import re
from typing import Any

from mnemosyne.ids import new_id
from mnemosyne.models import parse_dt
from mnemosyne.text import hashing_embedding, tokenize


class UserMemoryKind(str, Enum):
    IDENTITY = "identity"
    HARD_INSTRUCTION = "hard_instruction"
    EXPLICIT_PREFERENCE = "explicit_preference"
    INFERRED_PREFERENCE = "inferred_preference"
    SITUATIONAL_PREFERENCE = "situational_preference"
    TEMPORARY_STATE = "temporary_state"


AUTHORITY_ORDER = {
    UserMemoryKind.HARD_INSTRUCTION: 6,
    UserMemoryKind.IDENTITY: 5,
    UserMemoryKind.EXPLICIT_PREFERENCE: 4,
    UserMemoryKind.SITUATIONAL_PREFERENCE: 3,
    UserMemoryKind.TEMPORARY_STATE: 2,
    UserMemoryKind.INFERRED_PREFERENCE: 1,
}

#: What is left of a profile statement whose source evidence was erased.
ERASED_STATEMENT = "[retracted: the evidence this was built on was erased]"

_INTERNAL_SCOPE_KEYS = frozenset({
    "independent_sessions",
    "corroboration_count",
    "graduated_from",
    "drift_history",
})


def _user_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in (scope or {}).items() if k not in _INTERNAL_SCOPE_KEYS}


def correction_kind(kind: UserMemoryKind) -> UserMemoryKind:
    """The kind of the entry that replaces a corrected one.

    A correction is the user stating the thing outright, so the replacement is
    an explicit preference - unless what it replaces outranks one. A corrected
    instruction is still an instruction and a corrected identity still an
    identity: correcting an entry never lowers its authority.
    """

    explicit = UserMemoryKind.EXPLICIT_PREFERENCE
    return kind if AUTHORITY_ORDER[kind] > AUTHORITY_ORDER[explicit] else explicit


@dataclass(slots=True)
class UserModelEntry:
    tenant_id: str
    user_id: str
    kind: UserMemoryKind
    statement: str
    scope: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    exceptions: dict[str, Any] = field(default_factory=dict)
    source_evidence_cids: list[str] = field(default_factory=list)
    valid_from: datetime = field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None
    status: str = "active"
    id: str = field(default_factory=new_id)

    def authority(self) -> int:
        return AUTHORITY_ORDER[self.kind]

    def effective_authority(self) -> float:
        return effective_authority(self)

    def corroborate(
        self,
        evidence_cid: str,
        session_id: str | None = None,
        *,
        auto_graduate: bool = False,
    ) -> "UserModelEntry":
        return corroborate_entry(
            self,
            evidence_cid=evidence_cid,
            session_id=session_id,
            auto_graduate=auto_graduate,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["valid_from"] = self.valid_from.astimezone(UTC).isoformat()
        data["valid_to"] = self.valid_to.astimezone(UTC).isoformat() if self.valid_to else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserModelEntry":
        copy = dict(data)
        copy["kind"] = UserMemoryKind(copy["kind"])
        copy["valid_from"] = parse_dt(copy.get("valid_from")) or datetime.now(UTC)
        copy["valid_to"] = parse_dt(copy.get("valid_to"))
        return cls(**copy)


def _corroboration_count(entry: UserModelEntry) -> int:
    unique_cids = len(
        dict.fromkeys(
            cid.strip()
            for cid in (entry.source_evidence_cids or [])
            if isinstance(cid, str) and cid.strip()
        )
    )
    sessions_raw = (entry.scope or {}).get("independent_sessions", [])
    unique_sessions = (
        len(
            dict.fromkeys(
                s.strip()
                for s in sessions_raw
                if isinstance(s, str) and s.strip()
            )
        )
        if isinstance(sessions_raw, (list, tuple, set))
        else 0
    )
    stored_count = int((entry.scope or {}).get("corroboration_count", 0) or 0)
    return max(unique_cids, unique_sessions, stored_count)


def corroborate_entry(
    entry: UserModelEntry,
    evidence_cid: str,
    session_id: str | None = None,
    *,
    auto_graduate: bool = False,
) -> UserModelEntry:
    """Record corroborating evidence/session for a user-model entry (R5.3).

    Tracks independent ``source_evidence_cids`` and ``scope["independent_sessions"]``.
    When an ``INFERRED_PREFERENCE`` or ``SITUATIONAL_PREFERENCE`` is corroborated
    across ``>= 3`` independent sources/sessions, ``confidence`` increases
    monotonically (up to ``0.95``) and ``effective_authority(entry)`` graduates
    toward ``EXPLICIT_PREFERENCE`` authority (or promotes ``entry.kind`` to
    ``EXPLICIT_PREFERENCE`` when ``auto_graduate=True``).
    """

    if entry.scope is None:
        entry.scope = {}
    if entry.source_evidence_cids is None:
        entry.source_evidence_cids = []

    prev_count = _corroboration_count(entry)
    added_new_source = False

    clean_cid = (evidence_cid or "").strip()
    if clean_cid and clean_cid not in entry.source_evidence_cids:
        entry.source_evidence_cids.append(clean_cid)
        added_new_source = True

    sessions_raw = entry.scope.get("independent_sessions", [])
    sessions: list[str] = (
        [str(s).strip() for s in sessions_raw if str(s).strip()]
        if isinstance(sessions_raw, (list, tuple, set))
        else []
    )
    clean_session = (session_id or "").strip()
    if clean_session and clean_session not in sessions:
        sessions.append(clean_session)
        added_new_source = True
    if sessions or clean_session:
        entry.scope["independent_sessions"] = sessions

    count = max(
        len(dict.fromkeys(c for c in entry.source_evidence_cids if c)),
        len(dict.fromkeys(sessions)),
        prev_count + (1 if added_new_source and prev_count == 0 else 0),
    )
    entry.scope["corroboration_count"] = count

    # Monotonic confidence increase with each corroboration up to 0.95
    if count >= 3:
        target_conf = min(0.95, 0.85 + 0.035 * (count - 3))
        increment = 0.06 if added_new_source else 0.0
        entry.confidence = round(min(0.95, max(entry.confidence + increment, target_conf)), 4)
    elif count == 2:
        target_conf = 0.78
        increment = 0.05 if added_new_source else 0.0
        entry.confidence = round(min(0.95, max(entry.confidence + increment, target_conf)), 4)
    elif added_new_source:
        entry.confidence = round(min(0.95, max(entry.confidence, 0.72)), 4)

    if (
        auto_graduate
        and count >= 3
        and entry.kind in (UserMemoryKind.INFERRED_PREFERENCE, UserMemoryKind.SITUATIONAL_PREFERENCE)
    ):
        entry.scope.setdefault("graduated_from", entry.kind.value if hasattr(entry.kind, "value") else str(entry.kind))
        entry.kind = UserMemoryKind.EXPLICIT_PREFERENCE

    return entry


def effective_authority(entry: UserModelEntry) -> float:
    """Compute effective authority of an entry factoring in corroboration (R5.3).

    When ``INFERRED_PREFERENCE`` (base 1) or ``SITUATIONAL_PREFERENCE`` (base 3)
    is corroborated across ``>= 3`` independent sources/sessions, its effective
    authority graduates toward ``EXPLICIT_PREFERENCE`` (4.0).
    """

    base = float(AUTHORITY_ORDER[entry.kind])
    explicit_auth = float(AUTHORITY_ORDER[UserMemoryKind.EXPLICIT_PREFERENCE])
    count = _corroboration_count(entry)

    if entry.kind in (UserMemoryKind.INFERRED_PREFERENCE, UserMemoryKind.SITUATIONAL_PREFERENCE):
        if count >= 3:
            # Graduate into the [3.6, 4.0] range toward EXPLICIT_PREFERENCE (4.0)
            conf_factor = min(1.0, max(0.85, entry.confidence / 0.85))
            extra_sources = min(4, count - 3)
            grad_progress = min(1.0, (0.88 + 0.03 * extra_sources) * conf_factor)
            return round(base + (explicit_auth - base) * grad_progress, 4)
        if count == 2:
            conf_factor = min(1.0, max(0.5, entry.confidence / 0.85))
            return round(base + (explicit_auth - base) * 0.42 * conf_factor, 4)

    if entry.confidence < 0.7:
        return round(base * max(0.25, entry.confidence / 0.7), 4)
    return round(base + 0.2 * max(0.0, entry.confidence - 0.7), 4)


_PREF_DOMAIN_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"python", "rust", "go", "golang", "typescript", "javascript", "java", "ruby", "c", "cpp", "c++", "csharp", "zig", "julia", "kotlin", "swift", "scala", "elixir", "perl", "bash", "lua"}),
    frozenset({"vim", "neovim", "nvim", "emacs", "vscode", "cursor", "zed", "helix", "nano", "sublime", "intellij", "pycharm", "webstorm"}),
    frozenset({"dark", "light", "solarized", "dracula", "monokai", "nord", "gruvbox", "catppuccin", "high-contrast"}),
    frozenset({"tabs", "spaces", "2-space", "4-space"}),
    frozenset({"postgres", "postgresql", "mysql", "mariadb", "sqlite", "duckdb", "mongodb", "redis", "dynamodb", "cockroachdb", "cassandra"}),
    frozenset({"macos", "mac", "linux", "ubuntu", "debian", "arch", "fedora", "windows", "nixos"}),
    frozenset({"pip", "uv", "poetry", "pdm", "conda", "mamba", "pipenv", "npm", "pnpm", "yarn", "bun", "cargo"}),
    frozenset({"pytest", "unittest", "nose", "jest", "vitest", "mocha"}),
    frozenset({"react", "vue", "svelte", "angular", "solid", "nextjs", "remix", "htmx", "fastapi", "django", "flask", "express"}),
    frozenset({"coffee", "tea", "espresso", "matcha", "latte", "water"}),
    frozenset({"morning", "afternoon", "evening", "night"}),
    frozenset({"verbose", "concise", "brief", "detailed", "terse", "short", "long", "minimal"}),
    frozenset({"json", "yaml", "toml", "xml", "csv", "parquet", "protobuf"}),
    frozenset({"aws", "gcp", "azure", "cloudflare", "fly", "heroku", "vercel"}),
    frozenset({"docker", "podman", "kubernetes", "k8s", "nomad", "ecs"}),
    frozenset({"git", "mercurial", "hg", "jj", "jujutsu", "svn"}),
    frozenset({"zsh", "bash", "fish", "nushell", "pwsh", "tcsh"}),
    frozenset({"rest", "graphql", "grpc", "trpc", "websocket"}),
    frozenset({"celsius", "fahrenheit", "kelvin", "metric", "imperial"}),
)

_TRANSITION_RE = re.compile(
    r"\b(?:switched\s+to|migrated\s+to|moved\s+to|changed\s+to|transitioned\s+to|"
    r"converted\s+to|adopted|now\s+(?:prefers?|likes?|uses?|lov(?:es|ing)|wants?|favors?|chooses?)|"
    r"instead\s+of|rather\s+than|over)\b",
    re.IGNORECASE,
)

_NEGATIVE_PREF_RE = re.compile(
    r"\b(?:dislikes?|hates?|avoids?|stopped\s+using|no\s+longer\s+(?:uses?|prefers?|likes?)|"
    r"dropped|abandoned|quit\s+using|never\s+(?:uses?|likes?)|do(?:es)?\s+not\s+(?:like|prefer|use)|"
    r"don't\s+(?:like|prefer|use))\b",
    re.IGNORECASE,
)

_STATEMENT_PARSE_RE = re.compile(
    r"^(?:(?:the\s+user|user|they|i|we|he|she|[a-z]+)\s+)?"
    r"(?:(?:currently|now|always|usually|typically|generally|mostly|recently)\s+)*"
    r"(?P<verb>"
    r"switched\s+to|migrated\s+to|moved\s+to|changed\s+to|transitioned\s+to|converted\s+to|"
    r"stopped\s+using|no\s+longer\s+(?:uses?|prefers?|likes?)|"
    r"do(?:es)?\s+not\s+(?:like|prefer|use)|don't\s+(?:like|prefer|use)|"
    r"prefers?|likes?|loves?|uses?|using|chooses?|favors?|wants?|enjoys?|adopted|"
    r"dislikes?|hates?|avoids?|dropped|abandoned"
    r")\s+"
    r"(?P<rest>.+?)\.?$",
    re.IGNORECASE,
)

_PREP_SPLIT_RE = re.compile(
    r"^(?P<value>.+?)\s+(?:for|in|on|with|when|during|as|at|while)\s+(?P<topic>.+?)$",
    re.IGNORECASE,
)

_INSTEAD_SPLIT_RE = re.compile(
    r"^(?P<value>.+?)\s+(?:instead\s+of|rather\s+than|over)\s+(?P<old_target>.+?)$",
    re.IGNORECASE,
)

_FROM_TO_RE = re.compile(
    r"\b(?:switched|migrated|moved|changed|transitioned)\s+from\s+(?P<old_val>[a-z0-9_+#.-]+(?:\s+[a-z0-9_+#.-]+)?)\s+to\s+(?P<new_val>[a-z0-9_+#.-]+(?:\s+[a-z0-9_+#.-]+)?)"
    r"(?:\s+(?:for|in|on|with)\s+(?P<topic>.+?))?\.?$",
    re.IGNORECASE,
)


def _parse_preference_structure(statement: str) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", (statement or "").strip()).rstrip(".!;")
    lower = cleaned.lower()
    has_transition = bool(_TRANSITION_RE.search(lower))
    is_negative = bool(_NEGATIVE_PREF_RE.search(lower))
    polarity = -1 if is_negative else 1

    from_to = _FROM_TO_RE.search(lower)
    if from_to:
        old_explicit = from_to.group("old_val").strip()
        val = from_to.group("new_val").strip()
        topic = (from_to.group("topic") or "").strip()
        return {
            "raw": cleaned,
            "polarity": 1,
            "has_transition": True,
            "value": val,
            "topic": topic,
            "explicit_old": old_explicit,
            "head_noun": val.split()[-1] if " " in val else "",
            "modifier": " ".join(val.split()[:-1]) if " " in val else val,
            "tokens": set(tokenize(cleaned)),
        }

    m = _STATEMENT_PARSE_RE.match(cleaned)
    rest = m.group("rest").strip() if m else lower
    explicit_old = ""

    inst = _INSTEAD_SPLIT_RE.match(rest)
    if inst:
        rest = inst.group("value").strip()
        explicit_old = inst.group("old_target").strip().lower()

    topic = ""
    val = rest.lower()
    prep = _PREP_SPLIT_RE.match(rest)
    if prep:
        val = prep.group("value").strip().lower()
        topic = prep.group("topic").strip().lower()
        inst2 = _INSTEAD_SPLIT_RE.match(topic)
        if inst2:
            topic = inst2.group("value").strip().lower()
            explicit_old = inst2.group("old_target").strip().lower()

    val = re.sub(r"^(?:using|to\s+use|to\s+have|having|the|a|an)\s+", "", val).strip()
    words = [w for w in re.findall(r"[a-z0-9_+#.-]+", val) if w]
    head_noun = words[-1] if len(words) >= 2 else ""
    modifier = " ".join(words[:-1]) if len(words) >= 2 else (words[0] if words else val)

    return {
        "raw": cleaned,
        "polarity": polarity,
        "has_transition": has_transition,
        "value": val,
        "topic": topic,
        "explicit_old": explicit_old,
        "head_noun": head_noun,
        "modifier": modifier,
        "tokens": set(tokenize(cleaned)),
    }


def _same_domain_family(val_a: str, val_b: str) -> str | None:
    toks_a = {w for w in re.findall(r"[a-z0-9+#-]+", val_a.lower()) if w}
    toks_b = {w for w in re.findall(r"[a-z0-9+#-]+", val_b.lower()) if w}
    for family in _PREF_DOMAIN_FAMILIES:
        hit_a = toks_a & family
        hit_b = toks_b & family
        if hit_a and hit_b and hit_a != hit_b:
            return sorted(family)[0]
    # Check morphological substring relation for tool variants (e.g., vim vs neovim, mysql vs mariadb/sqlite)
    for a in toks_a:
        for b in toks_b:
            if a != b and len(a) >= 3 and len(b) >= 3 and (a in b or b in a):
                return a if len(a) <= len(b) else b
    return None


def detect_preference_drift(
    entries: Sequence[UserModelEntry],
    new_statement: str,
    new_evidence_cid: str | None = None,
    *,
    decay_factor: float = 0.5,
) -> list[dict[str, Any]]:
    """Detect when ``new_statement`` contradicts or drifts from active preferences (R5.3).

    Compares ``new_statement`` against active entries in ``entries``. When drift
    on the same topic/domain is detected (e.g. ``"prefers Python for scripting"``
    vs ``"now prefers Rust for scripting"``, ``"likes dark mode"`` vs
    ``"switched to light mode"``, ``"uses vim"`` vs ``"migrated to neovim"``),
    decays the outdated entry's confidence and returns structured drift records.
    """

    if not (new_statement or "").strip():
        return []

    parsed_new = _parse_preference_structure(new_statement)
    drifts: list[dict[str, Any]] = []

    for entry in entries:
        if entry.status != "active" or entry.statement == ERASED_STATEMENT:
            continue
        if entry.statement.strip().lower() == new_statement.strip().lower():
            continue

        parsed_old = _parse_preference_structure(entry.statement)
        old_val = parsed_old["value"]
        new_val = parsed_new["value"]
        old_topic = parsed_old["topic"]
        new_topic = parsed_new["topic"]

        matched_topic: str | None = None
        drift_type: str | None = None
        reported_old_val = old_val
        reported_new_val = new_val

        # Case 1: Explicit "from X to Y" or "Y instead of X" matching old_val
        if parsed_new["explicit_old"] and (
            parsed_new["explicit_old"] in old_val or old_val in parsed_new["explicit_old"]
        ):
            matched_topic = new_topic or old_topic or parsed_new["explicit_old"]
            drift_type = "explicit_transition"

        # Case 2: Polarity inversion on the same value/target (e.g. "likes dark mode" vs "dislikes dark mode")
        elif (
            old_val
            and new_val
            and old_val == new_val
            and parsed_old["polarity"] != parsed_new["polarity"]
        ):
            matched_topic = new_topic or old_topic or old_val
            drift_type = "polarity_inversion"

        # Case 3: Same explicit topic phrase (e.g., "for scripting") with different values ("python" vs "rust")
        elif (
            old_topic
            and new_topic
            and (
                old_topic == new_topic
                or bool(set(tokenize(old_topic)) & set(tokenize(new_topic)))
            )
            and old_val != new_val
        ):
            matched_topic = new_topic or old_topic
            drift_type = "value_shift"

        # Case 4: Shared head noun with different modifier (e.g. "dark mode" vs "light mode")
        elif (
            parsed_old["head_noun"]
            and parsed_old["head_noun"] == parsed_new["head_noun"]
            and parsed_old["modifier"] != parsed_new["modifier"]
        ):
            matched_topic = old_topic or new_topic or parsed_old["head_noun"]
            reported_old_val = parsed_old["modifier"]
            reported_new_val = parsed_new["modifier"]
            drift_type = "value_shift"

        # Case 5: Values belong to the same domain/tool family or morphological root (e.g. "vim" vs "neovim")
        else:
            family_topic = _same_domain_family(old_val, new_val)
            if family_topic is not None and (
                not old_topic or not new_topic or old_topic == new_topic
            ):
                matched_topic = old_topic or new_topic or family_topic
                drift_type = (
                    "explicit_transition" if parsed_new["has_transition"] else "value_shift"
                )

        if matched_topic is None or drift_type is None:
            continue

        old_conf = float(entry.confidence)
        decayed_conf = round(max(0.05, old_conf * decay_factor), 4)
        if decayed_conf >= old_conf:
            decayed_conf = round(max(0.05, old_conf - 0.15), 4)
        entry.confidence = decayed_conf

        if entry.scope is None:
            entry.scope = {}
        drift_record: dict[str, Any] = {
            "entry_id": entry.id,
            "old_statement": entry.statement,
            "new_statement": new_statement,
            "topic": matched_topic,
            "old_value": reported_old_val,
            "new_value": reported_new_val,
            "drift_type": drift_type,
            "previous_confidence": old_conf,
            "decayed_confidence": decayed_conf,
            "confidence_delta": round(decayed_conf - old_conf, 4),
            "new_evidence_cid": new_evidence_cid,
        }
        history = list(entry.scope.get("drift_history", []))
        history.append(dict(drift_record))
        entry.scope["drift_history"] = history

        drifts.append(drift_record)

    return drifts


@dataclass(slots=True)
class LatentUserProfile:
    tenant_id: str
    user_id: str
    embedding: list[float]
    summary: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "embedding": list(self.embedding),
            "summary": self.summary,
            "updated_at": self.updated_at.astimezone(UTC).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LatentUserProfile":
        copy = dict(data)
        copy["updated_at"] = parse_dt(copy.get("updated_at")) or datetime.now(UTC)
        return cls(**copy)


def build_advisory_latent_profile(
    tenant_id: str,
    user_id: str,
    summary: str,
    *,
    dims: int = 64,
) -> LatentUserProfile:
    """Build an advisory latent profile from free-text summary (FR-16 residual #26).

    Uses the deterministic hashing embedding as a local stand-in so the dual-user
    model can carry a fixed-width advisory vector without ML deps in Python core.
    Explicit/hard preferences still outrank this advisory signal.
    """

    text = (summary or "").strip() or "empty"
    return LatentUserProfile(
        tenant_id=tenant_id,
        user_id=user_id,
        embedding=hashing_embedding(text, dims=dims),
        summary=text,
    )


@dataclass(slots=True)
class UserMistakeEvent:
    """A neutral episodic record of a user slip (blueprint §24).

    Stored as an event, never a judgment. The ``pattern`` is the similarity key
    used to group repeated occurrences; ``description`` narrates the event
    factually without characterizing the user.
    """

    tenant_id: str
    user_id: str
    pattern: str
    description: str
    scope: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["occurred_at"] = self.occurred_at.astimezone(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserMistakeEvent":
        copy = dict(data)
        copy["occurred_at"] = parse_dt(copy.get("occurred_at")) or datetime.now(UTC)
        return cls(**copy)


@dataclass(slots=True)
class SupportStrategy:
    """A scoped, reversible assistance offer derived from repeated user slips.

    Per blueprint §24 a single slip never yields a strategy and never a durable
    judgment; only repeated similar events promote one, framed as assistance
    (e.g. "Offer to double-check date math before deploys.") and retractable.
    """

    tenant_id: str
    user_id: str
    pattern: str
    suggestion: str
    scope: dict[str, Any] = field(default_factory=dict)
    supporting_event_ids: list[str] = field(default_factory=list)
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: str = field(default_factory=new_id)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.astimezone(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SupportStrategy":
        copy = dict(data)
        copy["created_at"] = parse_dt(copy.get("created_at")) or datetime.now(UTC)
        return cls(**copy)


def _default_support_suggestion(pattern: str) -> str:
    readable = pattern.replace("_", " ").replace("-", " ").strip()
    return f"Offer to double-check {readable} proactively."


class UserModel:
    def __init__(self, support_strategy_threshold: int = 2) -> None:
        self.entries: dict[str, UserModelEntry] = {}
        self.latent_profiles: dict[tuple[str, str], LatentUserProfile] = {}
        self.mistake_events: list[UserMistakeEvent] = []
        self.support_strategies: dict[str, SupportStrategy] = {}
        # Repeated-similar threshold (>=2): a single user slip never promotes a
        # strategy and never a durable judgment (blueprint §24).
        self.support_strategy_threshold = max(2, support_strategy_threshold)

    def add_entry(self, entry: UserModelEntry) -> str:
        for current in self.entries.values():
            if (
                current.tenant_id == entry.tenant_id
                and current.user_id == entry.user_id
                and _user_scope(current.scope) == _user_scope(entry.scope)
                and current.status == "active"
                # Only an INFERENCE yields to a higher-authority statement that
                # merely differs from it. What the user stated outright - an
                # identity, an instruction, a preference - is never retired
                # because they also stated something else: 'Their name is
                # Jordan' used to retire 'Prefers Celsius'. A stated entry is
                # replaced by correcting it, or taken back, by id.
                and current.kind is UserMemoryKind.INFERRED_PREFERENCE
                and self._conflicts(current.statement, entry.statement)
                and current.authority() < entry.authority()
            ):
                current.status = "superseded"
                current.valid_to = entry.valid_from
        self.entries[entry.id] = entry
        return entry.id

    def corroborate_entry(
        self,
        entry_or_id: UserModelEntry | str,
        evidence_cid: str,
        session_id: str | None = None,
        *,
        auto_graduate: bool = False,
    ) -> UserModelEntry:
        """Corroborate an entry by instance or ID and return the updated entry (R5.3)."""
        if isinstance(entry_or_id, str):
            target = self.entries.get(entry_or_id)
            if target is None:
                raise ValueError(f"profile entry not found: {entry_or_id}")
        else:
            target = entry_or_id
            if target.id not in self.entries:
                self.entries[target.id] = target
        return corroborate_entry(
            target,
            evidence_cid=evidence_cid,
            session_id=session_id,
            auto_graduate=auto_graduate,
        )

    @staticmethod
    def effective_authority(entry: UserModelEntry) -> float:
        return effective_authority(entry)

    def detect_preference_drift(
        self,
        new_statement_or_entries: str | Sequence[UserModelEntry],
        new_evidence_cid_or_statement: str | None = None,
        maybe_evidence_cid: str | None = None,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        decay_factor: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Detect preference drift against stored or provided entries (R5.3)."""
        if isinstance(new_statement_or_entries, str):
            stmt = new_statement_or_entries
            ev_cid = new_evidence_cid_or_statement
            candidates = [
                e
                for e in self.entries.values()
                if (tenant_id is None or e.tenant_id == tenant_id)
                and (user_id is None or e.user_id == user_id)
            ]
        else:
            candidates = list(new_statement_or_entries)
            stmt = str(new_evidence_cid_or_statement or "")
            ev_cid = maybe_evidence_cid
        return detect_preference_drift(
            candidates,
            stmt,
            ev_cid,
            decay_factor=decay_factor,
        )

    def entry_in_scope(self, entry_id: str, *, tenant_id: str, user_id: str) -> UserModelEntry:
        """The entry with this id, if it belongs to this tenant and user."""

        entry = self.entries.get(entry_id)
        if entry is None or entry.tenant_id != tenant_id or entry.user_id != user_id:
            raise ValueError(f"profile entry not found in this tenant/user scope: {entry_id}")
        return entry

    def close_entry(
        self,
        entry_id: str,
        *,
        tenant_id: str,
        user_id: str,
        status: str,
        at: datetime | None = None,
    ) -> bool:
        """Take one entry out of the active profile, keeping the record.

        ``status`` is ``superseded`` (a correction replaced it) or ``retracted``
        (it was taken back). Returns ``False`` when the entry was already
        closed; an id outside the tenant/user scope is an error.
        """

        if status not in {"superseded", "retracted"}:
            raise ValueError("a profile entry closes as 'superseded' or 'retracted'")
        entry = self.entry_in_scope(entry_id, tenant_id=tenant_id, user_id=user_id)
        if entry.status != "active":
            return False
        entry.status = status
        entry.valid_to = at or datetime.now(UTC)
        return True

    def originating_evidence_cids(self, entry: UserModelEntry) -> list[str]:
        """Evidence CIDs this entry depends on.

        A correction used to record the replaced profile id as its only
        source. Walk those ids, within the same tenant and user, and return
        the evidence CIDs at the end of the chain.
        """

        seen: set[str] = set()
        evidence: list[str] = []
        pending = [cid for cid in entry.source_evidence_cids if isinstance(cid, str) and cid]
        while pending:
            cid = pending.pop(0)
            if cid in seen:
                continue
            seen.add(cid)
            cited = self.entries.get(cid)
            if (
                cited is not None
                and cited.tenant_id == entry.tenant_id
                and cited.user_id == entry.user_id
                and cited.id != entry.id
            ):
                pending.extend(
                    source for source in cited.source_evidence_cids if isinstance(source, str) and source
                )
                continue
            evidence.append(cid)
        return evidence

    def retract_citing(self, tenant_id: str, cid: str, *, at: datetime | None = None) -> list[str]:
        """Retract every entry built on erased evidence, including corrections.

        A correction may cite the profile entry it replaced rather than the
        original evidence CID. Follow that chain so the live correction is
        retracted too. Already-closed entries that still quote the forgotten
        text are blanked. Every id whose statement was blanked, or whose
        status moved to retracted, is returned so the caller persists closed
        residue as well as live retractions.
        """

        moment = at or datetime.now(UTC)
        dependent: set[str] = set()
        progressed = True
        while progressed:
            progressed = False
            for entry in self.entries.values():
                if entry.tenant_id != tenant_id or entry.id in dependent:
                    continue
                if cid in entry.source_evidence_cids or any(
                    source in dependent for source in entry.source_evidence_cids
                ):
                    dependent.add(entry.id)
                    progressed = True
        changed: list[str] = []
        for entry in self.entries.values():
            if entry.id not in dependent:
                continue
            mutated = False
            if entry.status == "active":
                entry.status = "retracted"
                entry.valid_to = moment
                mutated = True
            if entry.statement != ERASED_STATEMENT:
                entry.statement = ERASED_STATEMENT
                mutated = True
            if mutated:
                changed.append(entry.id)
        return changed

    def set_latent_profile(self, profile: LatentUserProfile) -> None:
        self.latent_profiles[(profile.tenant_id, profile.user_id)] = profile

    def record_user_mistake(
        self,
        event: UserMistakeEvent,
        *,
        suggestion: str | None = None,
    ) -> dict[str, Any]:
        """Record an episodic user-mistake event and promote a support strategy
        only once similar events repeat (blueprint §24).

        The event is stored verbatim as a neutral episode. When the count of
        similar events (same tenant/user/pattern/scope) reaches the configured
        threshold, a single scoped, reversible :class:`SupportStrategy` is
        emitted (or its supporting evidence refreshed). A lone slip promotes
        nothing. Returns a summary with the event id, the strategy id (if any),
        whether a strategy was newly promoted, and the similar-event count.
        """
        self.mistake_events.append(event)
        similar = [
            existing
            for existing in self.mistake_events
            if existing.tenant_id == event.tenant_id
            and existing.user_id == event.user_id
            and existing.pattern == event.pattern
            and existing.scope == event.scope
        ]
        result: dict[str, Any] = {
            "event_id": event.id,
            "strategy_id": None,
            "promoted": False,
            "similar_count": len(similar),
        }
        if len(similar) < self.support_strategy_threshold:
            return result
        existing_strategy = self._active_strategy(
            event.tenant_id, event.user_id, event.pattern, event.scope
        )
        supporting_ids = [item.id for item in similar]
        if existing_strategy is None:
            strategy = SupportStrategy(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                pattern=event.pattern,
                suggestion=suggestion or _default_support_suggestion(event.pattern),
                scope=dict(event.scope),
                supporting_event_ids=supporting_ids,
            )
            self.support_strategies[strategy.id] = strategy
            result["strategy_id"] = strategy.id
            result["promoted"] = True
        else:
            existing_strategy.supporting_event_ids = supporting_ids
            result["strategy_id"] = existing_strategy.id
        return result

    def active_support_strategies(
        self, tenant_id: str, user_id: str, scope: dict[str, Any]
    ) -> list[SupportStrategy]:
        return [
            strategy
            for strategy in self.support_strategies.values()
            if strategy.tenant_id == tenant_id
            and strategy.user_id == user_id
            and strategy.status == "active"
            and self._scope_matches(strategy.scope, scope)
        ]

    def retire_support_strategy(self, strategy_id: str) -> bool:
        """Reversibly retire a support strategy; returns False if already gone."""
        strategy = self.support_strategies.get(strategy_id)
        if strategy is None or strategy.status != "active":
            return False
        strategy.status = "retired"
        return True

    def _active_strategy(
        self, tenant_id: str, user_id: str, pattern: str, scope: dict[str, Any]
    ) -> SupportStrategy | None:
        for strategy in self.support_strategies.values():
            if (
                strategy.tenant_id == tenant_id
                and strategy.user_id == user_id
                and strategy.pattern == pattern
                and strategy.scope == scope
                and strategy.status == "active"
            ):
                return strategy
        return None

    def context_packet(self, tenant_id: str, user_id: str, scope: dict[str, Any]) -> dict[str, Any]:
        active = [
            entry
            for entry in self.entries.values()
            if entry.tenant_id == tenant_id
            and entry.user_id == user_id
            and entry.status == "active"
            and self._scope_matches(entry.scope, scope)
            and not self._excepted(entry, scope)
        ]
        active.sort(
            key=lambda item: (effective_authority(item), item.authority(), item.confidence),
            reverse=True,
        )
        latent = self.latent_profiles.get((tenant_id, user_id))
        strategies = self.active_support_strategies(tenant_id, user_id, scope)
        return {
            "authoritative": [entry.to_dict() for entry in active if entry.kind != UserMemoryKind.INFERRED_PREFERENCE],
            "inferred": [entry.to_dict() for entry in active if entry.kind == UserMemoryKind.INFERRED_PREFERENCE],
            "latent_advisory": latent.to_dict() if latent else None,
            "support_strategies": [strategy.to_dict() for strategy in strategies],
            "rules": {
                "hard_instruction_outranks_inference": True,
                "latent_never_overrides_explicit": True,
                "scope_matching_required": True,
            },
        }

    @staticmethod
    def _scope_matches(entry_scope: dict[str, Any], request_scope: dict[str, Any]) -> bool:
        return all(
            request_scope.get(key) == value
            for key, value in (entry_scope or {}).items()
            if key not in _INTERNAL_SCOPE_KEYS
        )

    @staticmethod
    def _excepted(entry: UserModelEntry, scope: dict[str, Any]) -> bool:
        return any(scope.get(key) == value for key, value in entry.exceptions.items())

    @staticmethod
    def _conflicts(left: str, right: str) -> bool:
        return left.strip().lower() != right.strip().lower()
