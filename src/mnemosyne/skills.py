"""Skills, one record per revision: plain skills at once, BurnSkills on request.

Importing a skill - an Agent Skills folder, a zip, any Markdown file or a folder of Markdown
files (one skill each) - keeps its files byte for byte and makes it usable at once, with no
model call: a plain skill is read as written (SKILL.md first, its other files on demand).
Making it a BurnSkill builds the complete framework (mnemosyne.frameworks) in the background,
three at a time, as a new revision that replaces the plain one; its nodes then go into the
user's memory. A .burnskill file (or an old .bs) imports as a BurnSkill with no conversion.
Scripts are stored, never run.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import queue
import re
import shutil
import sqlite3
import threading
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from mnemosyne import frameworks

WORKERS = 3
MAX_UNITS = 60
MAX_FILES = 200
MAX_BYTES = 5_000_000
#: A skill's whole text goes to the extractor in one prompt. Books are a later step.
MAX_TEXT_CHARS = 60_000
#: BurnOS's own skill file: a SKILL.md view (front matter, the document), then the framework
#: and the original files packed in a comment below it, so it imports with no conversion.
BS_SUFFIX = ".burnskill"
SKILL_FILES = (BS_SUFFIX, ".bs")  # .bs: what 1.3 and 1.4 wrote
BS_HEAD = "<!-- burnos-skill v"
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
#: A book is read page by page (PDF) or chapter by chapter (EPUB) and becomes one BurnSkill.
BOOK_SUFFIXES = {".pdf", ".epub"}
BOOK_MAX_BYTES = 200_000_000
CHUNK_WORDS = 500
#: Proper Thinking's retrieval for a source too long for one prompt: five questions, how many
#: passages each brings, their neighbours, then at most 58 passages and 68,000 characters.
BOOK_BUCKETS = (
    ("Main definitions, rules, principles, step-by-step processes, methods, constraints, and warnings "
     "described in this book.", 20),
    ("Risks, failures, mistakes, warnings, constraints, dangers, pitfalls, and what to avoid discussed "
     "in this book.", 10),
    ("Why the approach works; theory, arguments, justification, philosophy, assumptions, and debates in "
     "this book.", 10),
    ("Ethics, harm, injustice, fairness, responsibility, abuse, misuse, and moral limits in this book.", 8),
    ("Key examples, case studies, stories, and concrete illustrations of the main ideas in this book.", 10),
)
BOOK_MAX_CHUNKS = 58
BOOK_MAX_CHARS = 68_000
LEGAL = {"license", "licence", "notice", "copying"}
RUNNABLE_SUFFIXES = {".py", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".js", ".mjs", ".cjs",
                     ".ts", ".rb", ".pl", ".php", ".vbs", ".exe", ".dll", ".jar"}
STATES = {"draft", "active", "retired"}
SECTIONS = ("definition", "principle", "step", "warning", "constraint", "case", "example")
STOPWORDS = set(
    "a an and are as at be but by can could do does for from had has have how i if in into is it its "
    "just me my no not of on only or our please so some than that the their them then "
    "there these they this to up us was we what when where which who why will with would you your".split()
)
#: Words in a framework that mean the skill acts on the world: BurnOS asks before such a run acts.
EFFECT_WORDS = {
    "sends": r"\b(send|sent|email|e-mail|message|reply|forward)\w*",
    "deletes": r"\b(delete|remove|erase|wipe|rm\b|drop)\w*",
    "pays": r"\b(pay|purchase|buy|checkout|charge|order)\w*",
    "posts": r"\b(post|publish|tweet|upload|share|push)\w*",
    "installs": r"\b(install|uninstall|pip |npm |winget|choco)\w*",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha_of(files: list[tuple[str, bytes]]) -> str:
    """One digest for a skill's files: each path with the sha256 of its bytes, in path order."""
    digest = hashlib.sha256()
    for rel, data in sorted(files):
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def _safe(rel: str) -> bool:
    p = PurePosixPath(rel)
    return not (p.is_absolute() or ".." in p.parts or ":" in rel)


def runnable(paths: list[str]) -> list[str]:
    return [p for p in paths if PurePosixPath(p).suffix.lower() in RUNNABLE_SUFFIXES]


def front_matter(text: str) -> tuple[dict[str, Any], str]:
    """The ``---`` block of a SKILL.md as flat keys (lists for ``- item`` lines), and the body."""
    match = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.S)
    if not match:
        return {}, text
    meta: dict[str, Any] = {}
    key = None
    for line in match.group(1).splitlines():
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            if not isinstance(meta.get(key), list):
                meta[key] = [] if meta.get(key) in (None, "") else [meta[key]]
            meta[key].append(item.group(1).strip().strip("'\""))
            continue
        pair = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if pair:
            key = pair.group(1).lower()
            value: Any = pair.group(2).strip().strip("'\"")
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            meta[key] = value
    return meta, text[match.end():]


def blocks(text: str) -> list[str]:
    """Markdown split at blank lines and headings; a fenced block stays whole, a heading with its text."""
    out: list[str] = []
    current: list[str] = []
    fenced = False
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and (not line.strip() or line.startswith("#")):
            if current and not all(c.startswith("#") for c in current):
                out.append("\n".join(current).strip())
                current = []
            if line.startswith("#"):
                current.append(line)
            continue
        current.append(line)
    if current:
        out.append("\n".join(current).strip())
    return [b for b in out if b]


def source_units(texts: list[tuple[str, str]], limit: int = MAX_UNITS) -> list[str]:
    """Blocks of every text file, packed into at most ``limit`` units in reading order."""
    parts = [f"[{name}]\n{b}" if i == 0 and name != "SKILL.md" else b
             for name, text in texts for i, b in enumerate(blocks(text))]
    size = max(1, math.ceil(len(parts) / limit))
    return ["\n\n".join(parts[i:i + size]) for i in range(0, len(parts), size)]


def book_pages(path: Path) -> list[tuple[str, str]]:
    """A book's text with where it stands: ("p.12", text) for a PDF page, ("ch.3", text) for an EPUB chapter."""
    if path.stat().st_size > BOOK_MAX_BYTES:
        raise ValueError(f"{path.name} is over {BOOK_MAX_BYTES} bytes")
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("reading a PDF needs pypdf (pip install pypdf)") from exc
        return [(f"p.{n}", text.strip()) for n, page in enumerate(PdfReader(str(path)).pages, 1)
                if (text := page.extract_text() or "").strip()]
    # EPUB: a zip of XHTML chapters, in the order its package file's spine gives.
    import html
    from xml.etree import ElementTree

    with zipfile.ZipFile(path) as book:
        if sum(i.file_size for i in book.infolist()) > BOOK_MAX_BYTES:
            raise ValueError(f"{path.name} unpacks to over {BOOK_MAX_BYTES} bytes")
        container = ElementTree.fromstring(book.read("META-INF/container.xml"))
        tag = lambda e: e.tag.rsplit("}", 1)[-1]  # noqa: E731 - with or without the OPF namespace
        opf_path = next(e.get("full-path") for e in container.iter() if tag(e) == "rootfile")
        opf = ElementTree.fromstring(book.read(opf_path))
        hrefs = {e.get("id"): e.get("href") for e in opf.iter() if tag(e) == "item"}
        base = PurePosixPath(opf_path).parent
        pages = []
        for n, ref in enumerate((e.get("idref") for e in opf.iter() if tag(e) == "itemref"), 1):
            if ref not in hrefs:
                continue
            raw = book.read(str(base / hrefs[ref])).decode("utf-8", errors="replace")
            raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
            text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())
            if text:
                pages.append((f"ch.{n}", text))
        return pages


def chunk_pages(pages: list[tuple[str, str]]) -> list[str]:
    """Passages of at most CHUNK_WORDS words, each led by where it stands in the book."""
    out = []
    for label, text in pages:
        words = text.split()
        head = f"[{label}] " if label else ""
        out += [head + " ".join(words[i:i + CHUNK_WORDS]) for i in range(0, len(words), CHUNK_WORDS)]
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b, strict=False)) / (norm or 1.0)


def effects_of(nodes: list[dict[str, Any]], files: list[str], judged: list[str] | None = None) -> list[str]:
    """What a skill does to the world: as the model judged it from the steps, else by keyword."""
    if judged is None:
        text = " ".join(f"{n.get('title', '')} {n.get('content', '')}" for n in nodes).lower()
        judged = [k for k, pattern in EFFECT_WORDS.items() if re.search(pattern, text)]
    return list(judged) + (["runs scripts"] if runnable(files) else [])


def _from_v1(payload: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """A Mnemosyne 1.3.0 framework (Proper Thinking's tables) in this module's form."""
    units = [c["chunk_text"] for c in sorted(payload["chunks"], key=lambda c: c["page_number"])]
    ids = {n["id"]: i for i, n in enumerate(payload["nodes"])}
    nodes = []
    for n in payload["nodes"]:
        fields = json.loads(n["definitive_fields"]) if isinstance(n.get("definitive_fields"), str) else {}
        cited = {int(x) for x in re.findall(r"\d+", n.get("page_ref") or "") if 0 < int(x) <= len(units)}
        nodes.append({"id": ids[n["id"]], "type": n["node_type"], "title": n["title"], "content": n["content"],
                      "parent": ids.get(n.get("parent_id")), "depends_on": ids.get(n.get("depends_on_node_id")),
                      "units": sorted(cited), "fields": fields or {}, "epistemic_type": n.get("epistemic_type")})
    edges = [{"from": ids[e["from_node_id"]], "to": ids[e["to_node_id"]], "type": e["edge_type"],
              "why": e.get("why") or ""} for e in payload["edges"]
             if e["from_node_id"] in ids and e["to_node_id"] in ids]
    old = payload["framework"]
    fw = {"name": payload["skill"]["name"], "model": payload["skill"].get("model", ""), "passes": 1,
          "nodes": nodes, "edges": edges, "logic": {"graph_issues": [], "logic_issues": [], "logic_warnings": [],
                                                   "note": ""},
          "meta": {"claimed_scope": old.get("claimed_scope") or "", "evidenced_scope": old.get("evidenced_scope") or ""},
          "coverage": frameworks.coverage(units, nodes), "document": old.get("definitive_document") or "",
          "mechanical": {"passed": None, "failures": [], "repairs": []}, "judgment": {"findings": []}}
    return units, fw


def read_burnskill(src: Path) -> tuple[str, dict[str, Any], list[tuple[str, bytes]]]:
    """A .burnskill (or old .bs) file: its text, its payload and its original files, checked at the
    trust boundary - format and version, a bounded unpack, no file path that leaves the skill."""
    text = src.read_text(encoding="utf-8")
    at = text.rfind(BS_HEAD)
    if at < 0:
        raise ValueError(f"{src.name} is not a BurnSkill file")
    body = text[at + len(BS_HEAD):].split("\n", 1)[1].split("-->")[0].strip()
    unpack = zlib.decompressobj()
    raw = unpack.decompress(base64.b64decode(body), BOOK_MAX_BYTES * 2)
    if unpack.unconsumed_tail:
        raise ValueError(f"{src.name} unpacks to more than {BOOK_MAX_BYTES * 2} bytes")
    payload = json.loads(raw)
    if payload.get("format") != "burnos-skill" or payload.get("version") not in (1, 2):
        raise ValueError(f"{src.name}: unsupported skill file version")
    files = [(rel, base64.b64decode(data)) for rel, data in payload["files"].items()]
    if not all(_safe(rel) for rel, _ in files):
        raise ValueError(f"unsafe path in {src.name}")
    return text, payload, files


def validate_burnskill(path: str) -> dict[str, Any]:
    """A .burnskill file checked against the BurnSkill standard (docs/BURNSKILL.md): errors make it
    invalid; warnings are what a reader may still want fixed."""
    src = Path(path).expanduser()
    try:
        text, payload, files = read_burnskill(src)
    except Exception as exc:  # noqa: BLE001 - every failure to read is the verdict
        return {"valid": False, "errors": [str(exc)], "warnings": []}
    errors: list[str] = []
    warnings: list[str] = []
    meta, _ = front_matter(text)
    if not meta.get("name") or not meta.get("description"):
        warnings.append("no SKILL.md front matter with name and description: Agent Skills readers cannot list it")
    if payload["version"] == 1:
        warnings.append("version 1 (Mnemosyne 1.3): imports, but export it again for version 2")
        return {"valid": True, "version": 1, "errors": errors, "warnings": warnings}
    name = str((payload.get("skill") or {}).get("name") or "")
    units, fw = payload.get("units"), payload.get("framework")
    if not name:
        errors.append("skill.name is empty")
    if not files:
        warnings.append("no original files are packed")
    if not isinstance(units, list) or not units or not all(isinstance(u, str) for u in units):
        errors.append("units must be a non-empty list of strings")
        units = []
    if not isinstance(fw, dict):
        return {"valid": False, "version": 2, "name": name, "errors": [*errors, "framework is missing"],
                "warnings": warnings}
    nodes, edges = fw.get("nodes") or [], fw.get("edges") or []
    ids = {n.get("id") for n in nodes if isinstance(n, dict)}
    if [n.get("id") for n in nodes] != list(range(len(nodes))):
        errors.append("node ids must be 0, 1, 2 ... in order")
    for n in nodes:
        where = f"node {n.get('id')}"
        if n.get("type") not in frameworks.NODE_TYPES:
            errors.append(f"{where}: type {n.get('type')!r} is not one of {', '.join(frameworks.NODE_TYPES)}")
        if not str(n.get("title") or "").strip():
            errors.append(f"{where}: no title")
        for key in ("parent", "depends_on"):
            if n.get(key) is not None and n.get(key) not in ids:
                errors.append(f"{where}: {key} {n.get(key)} is not a node")
        if any(not isinstance(u, int) or not 1 <= u <= len(units) for u in n.get("units") or []):
            errors.append(f"{where}: cites a unit that does not exist")
    for e in edges:
        if e.get("from") not in ids or e.get("to") not in ids or e.get("from") == e.get("to"):
            errors.append(f"edge {e.get('from')} -> {e.get('to')}: not between two different nodes")
        if e.get("type") not in frameworks.EDGE_TYPES:
            errors.append(f"edge {e.get('from')} -> {e.get('to')}: type {e.get('type')!r} is unknown")
    if not str(fw.get("document") or "").strip():
        errors.append("framework.document is empty")
    if units and not errors:
        missing = frameworks.coverage(units, nodes)["unresolved"]
        if missing:
            warnings.append(f"source units no node represents: {missing[:20]}")
    if (fw.get("mechanical") or {}).get("passed") is False:
        warnings.append("its mechanical audit did not pass: " + "; ".join(fw["mechanical"].get("failures") or [])[:300])
    return {"valid": not errors, "version": 2, "name": name, "nodes": len(nodes), "edges": len(edges),
            "errors": errors[:50], "warnings": warnings[:50]}


class SkillStore:
    """One per store file; WORKERS threads convert skills side by side."""

    _stores: dict[str, SkillStore] = {}
    _lock = threading.Lock()

    @classmethod
    def at(cls, db_path: str | os.PathLike[str]) -> SkillStore:
        key = str(Path(db_path).resolve())
        with cls._lock:
            if key not in cls._stores:
                cls._stores[key] = cls(key)
            return cls._stores[key]

    def __init__(self, db_path: str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sources = self.path.parent / "skill-sources"
        #: The server's semantic embedder, handed in by the tools; None ranks by words.
        self.embedder: Any = None
        with self._sql() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS skill_revisions (
                    skill_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '[]', applicability TEXT NOT NULL DEFAULT '',
                    needs TEXT NOT NULL DEFAULT '[]', effects TEXT NOT NULL DEFAULT '[]',
                    attachments TEXT NOT NULL DEFAULT '[]', meta TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL DEFAULT 'draft', conversion TEXT NOT NULL, progress TEXT, error TEXT,
                    units TEXT NOT NULL, framework TEXT, source_sha TEXT NOT NULL, source_dir TEXT NOT NULL,
                    model TEXT NOT NULL, runs INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0,
                    last_outcome TEXT, created_at TEXT NOT NULL, PRIMARY KEY (skill_id, revision));
                CREATE TABLE IF NOT EXISTS skill_vectors (
                    text_sha TEXT NOT NULL, model TEXT NOT NULL, vector TEXT NOT NULL,
                    PRIMARY KEY (text_sha, model));
            """)
            if "memory" not in {c["name"] for c in conn.execute("PRAGMA table_info(skill_revisions)")}:
                # where a BurnSkill sits in the user's memory: {"tenant", "user", "cids"}
                conn.execute("ALTER TABLE skill_revisions ADD COLUMN memory TEXT")
        self._migrate(self.path.parent / "frameworks.sqlite")
        self._jobs: queue.Queue[tuple[str, int]] = queue.Queue()
        for n in range(WORKERS):
            threading.Thread(target=self._work, name=f"mnemosyne-skills-{n}", daemon=True).start()
        # shortcut: a conversion cut off by a restart starts over; a skill takes about two minutes.
        for row in self._rows("SELECT skill_id, revision FROM skill_revisions WHERE conversion = 'converting'"):
            self._jobs.put((row["skill_id"], row["revision"]))

    def _sql(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._sql() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def _migrate(self, old: Path) -> None:
        """Skills Mnemosyne 1.3.0 kept in frameworks.sqlite come across once, as they were."""
        if not old.exists() or old == self.path or self._rows("SELECT 1 FROM skill_revisions LIMIT 1"):
            return
        src = sqlite3.connect(old)
        src.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in src.execute("SELECT * FROM skills")]
            for row in rows:
                one = lambda sql, key: [dict(r) for r in src.execute(sql, (row[key],))]  # noqa: E731
                fw_rows = one("SELECT * FROM frameworks WHERE id = ?", "framework_id")
                if not fw_rows or fw_rows[0].get("generation_status") != "completed":
                    continue
                units, fw = _from_v1({"skill": row, "framework": fw_rows[0],
                                      "chunks": one("SELECT * FROM chunks WHERE book_id = ?", "book_id"),
                                      "nodes": one("SELECT * FROM framework_nodes WHERE framework_id = ?", "framework_id"),
                                      "edges": one("SELECT * FROM framework_edges WHERE framework_id = ?", "framework_id")})
                self._insert(row["skill_id"], row["revision"], row["name"], units, row["source_sha"],
                             Path(row["source_dir"]), row["model"], json.loads(row["meta"]), json.loads(row["needs"]),
                             json.loads(row["attachments"]), fw, row["state"], row["applicability"])
        except sqlite3.Error:
            pass  # no 1.3.0 skills there
        finally:
            src.close()

    # ------------------------------------------------------------------ import

    def _read_source(self, path: str) -> tuple[Path, list[tuple[str, bytes]]]:
        """Every file of the skill as (relative posix path, bytes), within the import limits."""
        src = Path(path).expanduser()
        if not src.exists():
            raise ValueError(f"no such file or folder: {path}")
        files: list[tuple[str, bytes]] = []
        if src.is_file() and src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as archive:
                infos = [i for i in archive.infolist() if not i.is_dir()]
                if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
                    raise ValueError(f"skill too large: at most {MAX_FILES} files and {MAX_BYTES} bytes")
                for info in infos:
                    if not _safe(info.filename):
                        raise ValueError(f"unsafe path in zip: {info.filename}")
                    files.append((str(PurePosixPath(info.filename)), archive.read(info)))
            tops = {PurePosixPath(n).parts[0] for n, _ in files}  # a zip of one folder: that folder
            if len(tops) == 1 and all(len(PurePosixPath(n).parts) > 1 for n, _ in files):
                files = [(str(PurePosixPath(*PurePosixPath(n).parts[1:])), b) for n, b in files]
        elif src.is_file():
            files = [("SKILL.md" if src.name.lower() == "skill.md" else src.name, src.read_bytes())]
        else:
            for p in sorted(src.rglob("*")):
                if p.is_symlink():
                    raise ValueError(f"symbolic links are not imported: {p}")
                if p.is_file() and ".git" not in p.relative_to(src).parts:
                    files.append((p.relative_to(src).as_posix(), p.read_bytes()))
                    if len(files) > MAX_FILES or sum(len(b) for _, b in files) > MAX_BYTES:
                        raise ValueError(f"skill too large: at most {MAX_FILES} files and {MAX_BYTES} bytes")
        if not files:
            raise ValueError("the skill has no files")
        return src, files

    def _keep(self, source_sha: str, files: list[tuple[str, bytes]]) -> Path:
        """The originals, byte for byte, under their digest; nothing in them is executed."""
        keep = self.sources / source_sha
        if not keep.exists():
            for rel, data in files:
                target = keep / PurePosixPath(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        return keep

    def _next(self, name: str, source_sha: str, force: bool) -> tuple[str, int] | dict[str, Any]:
        """The id and revision a new import of ``name`` gets, or the revision it already is."""
        same = self._rows("SELECT * FROM skill_revisions WHERE lower(name) = lower(?) ORDER BY revision DESC", (name,))
        for row in same if not force else []:
            if row["source_sha"] == source_sha:
                return {"skill_id": row["skill_id"], "revision": row["revision"], "unchanged": True}
        return (same[0]["skill_id"], same[0]["revision"] + 1) if same else (f"skill-{uuid4().hex[:12]}", 1)

    def _insert(self, skill_id: str, revision: int, name: str, units: list[str], source_sha: str, keep: Path,
                model: str, meta: dict[str, Any], needs: list[str], attachments: list[str],
                fw: dict[str, Any] | None, state: str = "draft", applicability: str = "",
                conversion: str = "", memory: dict[str, str] | None = None) -> None:
        effects = effects_of(fw["nodes"] if fw else [{"content": " ".join(units)}], attachments,
                             (fw.get("meta") or {}).get("effects") if fw else None)
        if "bash" in str(meta.get("allowed-tools") or "").lower() and "runs scripts" not in effects:
            effects.append("runs scripts")  # a skill that asks for a shell runs commands
        with self._sql() as conn:
            if state == "active":  # one active revision per skill
                conn.execute("UPDATE skill_revisions SET state = 'draft' WHERE skill_id = ? AND state = 'active'",
                             (skill_id,))
            conn.execute(
                "INSERT INTO skill_revisions (skill_id, revision, name, applicability, needs, effects, attachments, "
                "meta, state, conversion, units, framework, source_sha, source_dir, model, created_at, memory) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (skill_id, revision, name, applicability or str(meta.get("description") or ""), json.dumps(needs),
                 json.dumps(effects), json.dumps(sorted(attachments)),
                 json.dumps(meta), state, conversion or ("completed" if fw else "converting"), json.dumps(units),
                 json.dumps(fw) if fw else None, source_sha, str(keep), model, _now(),
                 json.dumps(memory) if memory else None))

    def import_skill(self, path: str, model: str, name: str | None = None, force: bool = False,
                     memory: dict[str, str] | None = None) -> dict[str, Any]:
        """A plain skill, active and searchable at once; a .burnskill file as the BurnSkill it is."""
        folder = Path(path).expanduser()
        if folder.suffix.lower() in SKILL_FILES:
            return self._import_bs(folder, memory)
        if folder.suffix.lower() in BOOK_SUFFIXES and folder.is_file():
            return self._import_book(folder, model, name, memory)
        # A folder of Markdown files with no SKILL.md (a prompt or command library): one skill each.
        if folder.is_dir() and not any(p.name.lower() == "skill.md" for p in folder.iterdir()):
            pages = sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".md", ".markdown", *SKILL_FILES)
                           and p.is_file() and ".git" not in p.relative_to(folder).parts
                           and p.stem.lower() not in LEGAL)
            if len(pages) > 1:
                return {"imported": [self.import_skill(str(p), model, memory=memory) for p in pages[:MAX_FILES]]}
        src, files = self._read_source(path)
        source_sha = _sha_of(files)
        texts, kept = [], []
        for rel, data in files:
            # A licence stays with the skill but is not what it teaches.
            if PurePosixPath(rel).suffix.lower() in TEXT_SUFFIXES and PurePosixPath(rel).stem.lower() not in LEGAL:
                texts.append((rel, data.decode("utf-8", errors="replace")))
            else:
                kept.append(rel)
        texts.sort(key=lambda t: (t[0] != "SKILL.md", t[0]))
        if not texts:
            raise ValueError("the skill has no Markdown or text file to read")
        meta, body = front_matter(texts[0][1])
        texts[0] = (texts[0][0], body)
        skill_name = (name or str(meta.get("name") or "") or src.stem).strip()
        if skill_name.lower() == "skill":
            skill_name = src.parent.name if src.is_file() else src.name
        nxt = self._next(skill_name, source_sha, force)
        if isinstance(nxt, dict):
            return nxt
        skill_id, revision = nxt
        needs = meta.get("needs") or meta.get("mcp-servers") or meta.get("mcp_servers") or []
        units = source_units(texts)
        self._insert(skill_id, revision, skill_name, units, source_sha, self._keep(source_sha, files), model, meta,
                     needs if isinstance(needs, list) else [needs], kept, None, state="active", conversion="native")
        status = self.status(skill_id, revision)
        return {"skill_id": skill_id, "revision": revision, "name": skill_name, "kind": "skill", "status": "ready",
                "effects": status["effects"], "attachments": sorted(kept)}

    def make_burnskill(self, skill_id: str, model: str, memory: dict[str, str] | None = None) -> dict[str, Any]:
        """The framework of a skill's kept text, built in the background as a new revision; when it is
        done it becomes the active one and, given ``memory``, its nodes go into that memory."""
        row = self._skill(skill_id)
        head = {"skill_id": row["skill_id"], "name": row["name"]}
        busy = self._rows("SELECT revision FROM skill_revisions WHERE skill_id = ? AND conversion = 'converting'",
                          (row["skill_id"],))
        if busy:
            return {**head, "revision": busy[0]["revision"], "status": "converting"}
        units = json.loads(row["units"])
        revision = self._rows("SELECT max(revision) AS top FROM skill_revisions WHERE skill_id = ?",
                              (row["skill_id"],))[0]["top"] + 1
        self._insert(row["skill_id"], revision, row["name"], units, row["source_sha"], Path(row["source_dir"]),
                     model, json.loads(row["meta"]), json.loads(row["needs"]), json.loads(row["attachments"]), None,
                     memory=memory)
        self._jobs.put((row["skill_id"], revision))
        return {**head, "revision": revision, "status": "converting"}

    def _import_book(self, src: Path, model: str, name: str | None,
                     memory: dict[str, str] | None) -> dict[str, Any]:
        """A book becomes one BurnSkill, built in the background; the file is kept as it came."""
        files = [(src.name, src.read_bytes())]
        source_sha = _sha_of(files)
        title = (name or src.stem).strip()
        nxt = self._next(title, source_sha, False)
        if isinstance(nxt, dict):
            return nxt
        units = chunk_pages(book_pages(src))
        if not units:
            raise ValueError(f"{src.name} holds no text to read (a scanned book needs OCR first)")
        self._insert(*nxt, title, units, source_sha, self._keep(source_sha, files), model, {"book": src.name},
                     [], [], None, memory=memory)
        self._jobs.put(nxt)
        return {"skill_id": nxt[0], "revision": nxt[1], "name": title, "kind": "burnskill",
                "status": "converting", "passages": len(units)}

    def _select(self, chunks: list[str]) -> list[str]:
        """Proper Thinking's retrieval for a source too long for one prompt (BOOK_BUCKETS), by meaning
        when the store has an embedder and by words otherwise. Bucket hits come before their
        neighbours when the caps bite, rather than whatever stands first in the book."""
        from mnemosyne.passages import PassageIndex

        embedder = self.embedder
        vectors = None
        if embedder is not None and getattr(embedder, "name", "") != "local-hashing":
            try:
                # a hosted embedder takes a request of a few dozen texts, not a whole book
                vectors = [v for i in range(0, len(chunks), 64) for v in self._vectors(embedder, chunks[i:i + 64])]
            except Exception:  # noqa: BLE001 - by words instead
                vectors = None
        words = None if vectors is not None else PassageIndex(tuple(chunks))
        ranked: list[int] = []
        for query, k in BOOK_BUCKETS:
            if vectors is not None:
                q = self._vectors(embedder, [query])[0]
                scores = [_cosine(q, v) for v in vectors]
            else:
                got = words.scores(" ".join(w for w in re.findall(r"\w+", query.lower()) if w not in STOPWORDS))
                scores = [got.get(i, 0.0) for i in range(len(chunks))]
            top = sorted((i for i in range(len(chunks)) if scores[i] > 0), key=lambda i: -scores[i])[:k]
            ranked += [i for i in top if i not in ranked]
        ranked += [j for i in list(ranked) for j in (i - 1, i + 1) if 0 <= j < len(chunks) and j not in ranked]
        kept, total = [], 0
        for i in dict.fromkeys(ranked):
            if len(kept) == BOOK_MAX_CHUNKS or total + len(chunks[i]) > BOOK_MAX_CHARS:
                break
            kept.append(i)
            total += len(chunks[i])
        return [chunks[i] for i in sorted(kept)] or chunks[:BOOK_MAX_CHUNKS]

    def _work(self) -> None:
        while True:
            skill_id, revision = self._jobs.get()
            try:
                self._convert(skill_id, revision)
            except Exception as exc:  # noqa: BLE001 - recorded on the revision
                with self._sql() as conn:
                    conn.execute("UPDATE skill_revisions SET conversion = 'failed', error = ? "
                                 "WHERE skill_id = ? AND revision = ?", (str(exc)[:1000], skill_id, revision))

    def _convert(self, skill_id: str, revision: int) -> None:
        row = self._skill(skill_id, revision)
        frameworks.MODEL.set(row["model"])  # this worker thread's context only

        def progress(text: str) -> None:
            with self._sql() as conn:
                conn.execute("UPDATE skill_revisions SET progress = ? WHERE skill_id = ? AND revision = ?",
                             (text, skill_id, revision))

        units = json.loads(row["units"])
        if sum(len(u) for u in units) > MAX_TEXT_CHARS:
            # Too long for one prompt (a book): built from the passages Proper Thinking would pick.
            progress("choosing the passages to build from")
            units = self._select(units if max(len(u) for u in units) <= 4000 else chunk_pages([("", "\n".join(units))]))
            with self._sql() as conn:
                conn.execute("UPDATE skill_revisions SET units = ? WHERE skill_id = ? AND revision = ?",
                             (json.dumps(units), skill_id, revision))
        fw = frameworks.build(row["name"], units, progress)
        scope = " ".join(fw["meta"][k] for k in ("claimed_scope", "evidenced_scope") if "Not stated" not in fw["meta"][k])
        with self._sql() as conn:
            conn.execute(
                "UPDATE skill_revisions SET framework = ?, conversion = 'completed', progress = 'done', "
                "applicability = ?, effects = ? WHERE skill_id = ? AND revision = ?",
                (json.dumps(fw), " ".join(s for s in (row["applicability"], scope) if s).strip(),
                 json.dumps(effects_of(fw["nodes"], json.loads(row["attachments"]), fw["meta"].get("effects"))),
                 skill_id, revision))
            # the finished BurnSkill replaces whatever was on; the older revisions stay
            conn.execute("UPDATE skill_revisions SET state = 'draft' WHERE skill_id = ? AND state = 'active'",
                         (skill_id,))
            conn.execute("UPDATE skill_revisions SET state = 'active' WHERE skill_id = ? AND revision = ?",
                         (skill_id, revision))
        self._embed_now(skill_id, revision)

    # ------------------------------------------------------------------ memory

    def unremembered(self) -> list[dict[str, Any]]:
        """Finished BurnSkills whose nodes are not in the user's memory yet."""
        return self._rows("SELECT * FROM skill_revisions WHERE conversion = 'completed' AND memory IS NOT NULL "
                          "AND json_extract(memory, '$.cids') IS NULL")

    @staticmethod
    def memory_texts(row: dict[str, Any]) -> list[str]:
        """One memory entry per node, named by its skill so a recall says where it came from."""
        fw = json.loads(row["framework"])
        return [f"{row['name']} (BurnSkill {n['type']}): {n['title']}\n{n.get('content') or ''}".strip()
                for n in fw["nodes"]]

    def remembered(self, skill_id: str, revision: int, memory: dict[str, Any]) -> list[dict[str, Any]]:
        """Record where a BurnSkill sits in memory; returns the older revisions' entries, to forget."""
        old = [json.loads(r["memory"]) for r in self._rows(
            "SELECT memory FROM skill_revisions WHERE skill_id = ? AND revision != ? AND memory IS NOT NULL",
            (skill_id, revision))]
        with self._sql() as conn:
            conn.execute("UPDATE skill_revisions SET memory = NULL WHERE skill_id = ? AND revision != ?",
                         (skill_id, revision))
            conn.execute("UPDATE skill_revisions SET memory = ? WHERE skill_id = ? AND revision = ?",
                         (json.dumps(memory), skill_id, revision))
        return [m for m in old if m.get("cids")]

    # ------------------------------------------------------------------ .burnskill files

    def export_skill(self, skill_id: str, path: str, revision: int | None = None) -> dict[str, Any]:
        """A plain skill as its SKILL.md folder; a BurnSkill as one .burnskill file - a SKILL.md view
        (front matter, document), then framework, units and original files packed below."""
        row = self._skill(skill_id, revision)
        out = Path(path).expanduser()
        kept = Path(row["source_dir"])
        if row["conversion"] == "native":
            target = out / row["name"]
            shutil.copytree(kept, target, dirs_exist_ok=True)
            return {"skill_id": row["skill_id"], "revision": row["revision"], "path": str(target), "kind": "skill"}
        if row["conversion"] != "completed":
            raise ValueError(f"{row['name']} is not a BurnSkill yet ({row['conversion']})")
        if out.suffix.lower() not in SKILL_FILES:
            out = out / f"{row['name']}{BS_SUFFIX}"
        fw = json.loads(row["framework"])
        about = " ".join(str(json.loads(row["meta"]).get("description") or row["applicability"]).split())
        payload = {"format": "burnos-skill", "version": 2,
                   "skill": {k: row[k] for k in ("name", "aliases", "applicability", "needs", "attachments", "meta", "model")},
                   "units": json.loads(row["units"]), "framework": fw,
                   "files": {p.relative_to(kept).as_posix(): base64.b64encode(p.read_bytes()).decode("ascii")
                             for p in sorted(kept.rglob("*")) if p.is_file()}}
        packed = base64.b64encode(zlib.compress(json.dumps(payload).encode("utf-8"), 9)).decode("ascii")
        out.parent.mkdir(parents=True, exist_ok=True)
        view = f"---\nname: {row['name']}\ndescription: {json.dumps(about)}\n---\n"
        out.write_text(f"{view}{fw['document'].rstrip()}\n\n{BS_HEAD}2\n{packed}\n-->\n", encoding="utf-8", newline="\n")
        return {"skill_id": row["skill_id"], "revision": row["revision"], "path": str(out), "kind": "burnskill",
                "bytes": out.stat().st_size}

    def _import_bs(self, src: Path, memory: dict[str, str] | None = None) -> dict[str, Any]:
        _, payload, files = read_burnskill(src)
        units, fw = (payload["units"], payload["framework"]) if payload["version"] == 2 else _from_v1(payload)
        skill = payload["skill"]
        source_sha = _sha_of(files)
        nxt = self._next(skill["name"], source_sha, False)
        if isinstance(nxt, dict):
            return nxt
        load = lambda v: json.loads(v) if isinstance(v, str) else v  # noqa: E731
        self._insert(*nxt, skill["name"], units, source_sha, self._keep(source_sha, files), skill.get("model", ""),
                     load(skill.get("meta") or {}), load(skill.get("needs") or []), load(skill.get("attachments") or []),
                     fw, state="active", applicability=skill.get("applicability", ""), memory=memory)
        return {"skill_id": nxt[0], "revision": nxt[1], "name": skill["name"], "kind": "burnskill", "status": "ready"}

    # ------------------------------------------------------------------ read

    def _skill(self, skill_id: str, revision: int | None = None) -> dict[str, Any]:
        rows = self._rows(
            "SELECT * FROM skill_revisions WHERE (skill_id = ? OR lower(name) = lower(?)) "
            + ("AND revision = ? " if revision else "") + "ORDER BY state = 'active' DESC, revision DESC LIMIT 1",
            (skill_id, skill_id, revision) if revision else (skill_id, skill_id))
        if not rows:
            raise ValueError(f"no skill {skill_id}" + (f" revision {revision}" if revision else ""))
        return rows[0]

    def status(self, skill_id: str, revision: int | None = None) -> dict[str, Any]:
        row = self._skill(skill_id, revision)
        fw = json.loads(row["framework"]) if row["framework"] else {}
        return {
            "skill_id": row["skill_id"], "revision": row["revision"], "name": row["name"], "state": row["state"],
            "kind": "burnskill" if row["framework"] else "skill",
            "conversion": row["conversion"], "progress": row["progress"], "error": row["error"],
            "nodes": len(fw.get("nodes") or []), "edges": len(fw.get("edges") or []),
            "coverage": {k: fw["coverage"][k] for k in ("complete", "unresolved")} if fw else None,
            "mechanical_audit_passed": (fw.get("mechanical") or {}).get("passed"),
            "judgment_findings": ((fw.get("judgment") or {}).get("findings") or [])[:5],
            "applicability": row["applicability"], "needs": json.loads(row["needs"]),
            "effects": json.loads(row["effects"]), "attachments": json.loads(row["attachments"]),
        }

    def get(self, skill_id: str, revision: int | None = None, section: str | None = None,
            node_id: int | None = None, attachment: str | None = None,
            offset: int = 0, limit: int = 6000) -> dict[str, Any]:
        row = self._skill(skill_id, revision)
        fw = json.loads(row["framework"]) if row["framework"] else {"nodes": [], "edges": [], "document": ""}
        units = json.loads(row["units"])
        head = {"skill_id": row["skill_id"], "revision": row["revision"], "name": row["name"]}

        def page(text: str) -> dict[str, Any]:
            start = max(0, int(offset))
            end = start + max(1, min(int(limit), 20000))
            return {**head, "text": text[start:end], "offset": start, "total": len(text), "more": end < len(text)}

        base = Path(row["source_dir"]).resolve()
        if row["conversion"] != "completed" and attachment is None and node_id is None and section != "source":
            if json.loads(row["meta"]).get("book"):
                raise ValueError(f"{row['name']} is a book; its BurnSkill is {row['conversion']} ({row['progress']})")
            # A plain skill is read as written: SKILL.md (or its one page), the rest by name on demand.
            if section not in (None, "", "overview", "document"):
                raise ValueError(f"{row['name']} is a plain skill: read its document and files, "
                                 "or make it a BurnSkill for sections")
            files = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
            main = next((f for f in files if f.lower() == "skill.md"), None) or next(
                (f for f in files if PurePosixPath(f).suffix.lower() in TEXT_SUFFIXES), files[0])
            return {**page((base / main).read_bytes().decode("utf-8", errors="replace")), "kind": "skill",
                    "file": main, "files": files, "effects": json.loads(row["effects"]),
                    "needs": json.loads(row["needs"]), "conversion": row["conversion"]}
        if attachment is not None:
            target = (base / PurePosixPath(attachment)).resolve()
            if base not in target.parents or not target.is_file():
                raise ValueError(f"no attachment {attachment}")
            return page(target.read_bytes().decode("utf-8", errors="replace"))
        if node_id is not None:
            node = next((n for n in fw["nodes"] if n["id"] == int(node_id)), None)
            if node is None:
                raise ValueError(f"no node {node_id} in {row['name']}")
            return {**head, "node": node, "edges": [e for e in fw["edges"] if node["id"] in (e["from"], e["to"])],
                    "sources": {u: units[u - 1] for u in node["units"]}}
        section = None if section in (None, "", "overview") else section
        if section == "document":
            return page(fw["document"])
        if section == "source":
            return page("\n\n".join(f"[Unit {i}]\n{u}" for i, u in enumerate(units, 1)))
        if section == "graph":  # Proper Thinking's mindmap: every node and relation, small
            return {**head, "nodes": [{k: n[k] for k in ("id", "type", "title", "parent")} for n in fw["nodes"]],
                    "edges": fw["edges"]}
        if section:
            kind = section.lower().rstrip("s")
            if kind not in SECTIONS:
                raise ValueError("section is one of document, source, graph, " + ", ".join(s + "s" for s in SECTIONS))
            return {**head, "section": section, "nodes": [
                {k: n.get(k) for k in ("id", "title", "content", "units", "fields", "epistemic_type")}
                for n in fw["nodes"] if n["type"] == kind]}
        counts: dict[str, int] = {}
        for n in fw["nodes"]:
            counts[n["type"]] = counts.get(n["type"], 0) + 1
        return {**self.status(row["skill_id"], row["revision"]), "sections": counts, "meta": fw.get("meta"),
                "revisions": [{"revision": r["revision"], "state": r["state"], "created_at": r["created_at"]}
                              for r in self._rows("SELECT revision, state, created_at FROM skill_revisions "
                                                  "WHERE skill_id = ? ORDER BY revision", (row["skill_id"],))]}

    def files(self, skill_id: str) -> list[str]:
        """A skill's kept files, as paths relative to its folder."""
        base = Path(self._skill(skill_id)["source_dir"])
        return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())

    def ask(self, skill_id: str, question: str, revision: int | None = None) -> dict[str, Any]:
        """A question about a skill, answered from its framework and source only."""
        row = self._skill(skill_id, revision)
        if row["conversion"] != "completed":
            raise ValueError(f"{row['name']} is not a BurnSkill ({row['conversion']}): read it with skill_get")
        frameworks.MODEL.set(row["model"])
        answer = frameworks.ask(json.loads(row["framework"]), json.loads(row["units"]), question)
        return {"skill_id": row["skill_id"], "revision": row["revision"], **answer}

    # ------------------------------------------------------------------ search

    def _vectors(self, embedder: Any, texts: list[str]) -> list[list[float]]:
        from mnemosyne.passages import _embed, _embedding_model_key

        model = _embedding_model_key(embedder)
        shas = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
        known = {r["text_sha"]: json.loads(r["vector"]) for r in self._rows(
            f"SELECT text_sha, vector FROM skill_vectors WHERE model = ? AND text_sha IN ({','.join('?' * len(shas))})",
            (model, *shas))} if shas else {}
        missing = [i for i, s in enumerate(shas) if s not in known]
        if missing:
            fresh = _embed(embedder, [texts[i] for i in missing])
            with self._sql() as conn:
                for i, vector in zip(missing, fresh, strict=True):
                    known[shas[i]] = vector
                    conn.execute("INSERT OR REPLACE INTO skill_vectors VALUES (?, ?, ?)", (shas[i], model, json.dumps(vector)))
        return [known[s] for s in shas]

    def _embed_now(self, skill_id: str, revision: int) -> None:
        """Embed a converted skill at once, so the first task that could use it does not wait for it."""
        embedder = self.embedder
        if embedder is None or getattr(embedder, "name", "") == "local-hashing":
            return
        try:
            self._vectors(embedder, [self._doc(self._skill(skill_id, revision))])
        except Exception:  # noqa: BLE001 - search embeds it later instead
            pass

    def _doc(self, row: dict[str, Any]) -> str:
        """What a skill is found by: its name, applicability and the titles of its nodes."""
        fw = json.loads(row["framework"]) if row["framework"] else {}
        titles = "; ".join(n["title"] for n in fw.get("nodes") or []) or " ".join(json.loads(row["units"]))
        return f"{row['name']}. {row['applicability']} {titles}"[:4000]

    def search(self, query: str, available: list[str] | None = None, include_drafts: bool = False,
               limit: int = 5, embedder: Any = None, floor: float = 0.5, timeout: float = 1.0) -> dict[str, Any]:
        """Exact name first; then only skills whose needs are met; then rank by meaning (or words)."""
        states = ("active", "draft") if include_drafts else ("active",)
        latest: dict[str, dict[str, Any]] = {}
        for r in self._rows("SELECT * FROM skill_revisions ORDER BY revision DESC"):
            if r["state"] in states and (r["skill_id"] not in latest or r["state"] == "active"):
                latest[r["skill_id"]] = r
        have = {a.strip().lower() for a in (available or [])}
        skipped, eligible = [], []
        for r in latest.values():
            missing = [n for n in json.loads(r["needs"]) if available is not None and n.lower() not in have]
            (skipped if missing else eligible).append({**r, "missing": missing})

        def out(r: dict[str, Any], score: float) -> dict[str, Any]:
            # effects and scripts travel with every hit: the caller guards a run by them.
            return {"skill_id": r["skill_id"], "revision": r["revision"], "name": r["name"], "state": r["state"],
                    "kind": "burnskill" if r["framework"] else "skill", "applicability": r["applicability"][:400], "effects": json.loads(r["effects"]),
                    "scripts": bool(runnable(json.loads(r["attachments"]))), "score": round(score, 4)}

        q = " ".join(query.lower().split())
        not_eligible = [{"name": r["name"], "missing": r["missing"]} for r in skipped]
        if not q:  # an empty query lists them all
            return {"skills": [out(r, 0.0) for r in eligible], "not_eligible": not_eligible}
        named = [r for r in eligible if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", q) for n in
                 {r["name"].lower(), r["name"].lower().replace("-", " "), *json.loads(r["aliases"])})]
        if named:
            return {"skills": [out(r, 1.0) for r in named], "matched": "name", "not_eligible": not_eligible}
        if not eligible:
            return {"skills": [], "not_eligible": not_eligible}
        docs = [self._doc(r) for r in eligible]
        scores: list[float] = []
        semantic = embedder is not None and getattr(embedder, "name", "") != "local-hashing"
        if semantic:
            pool = ThreadPoolExecutor(max_workers=1)  # a hosted embedder can stall; the caller is waiting
            pending = pool.submit(lambda: (self._vectors(embedder, docs), self._vectors(embedder, [query])[0]))
            pool.shutdown(wait=False)
            try:
                vectors, qv = pending.result(timeout=timeout)
                scores = [c if c >= floor else 0.0 for c in (_cosine(qv, v) for v in vectors)]
            except Exception:  # noqa: BLE001 - timeout or provider error: rank by words instead
                semantic = False
        if not semantic:
            from mnemosyne.passages import PassageIndex

            words = " ".join(w for w in re.findall(r"\w+", q) if w not in STOPWORDS)
            bm25 = PassageIndex(tuple(docs)).scores(words) if words else {}
            scores = [bm25.get(i, 0.0) for i in range(len(docs))]
        ranked = sorted(zip(scores, eligible, strict=True), key=lambda p: -p[0])
        hits = [out(r, s) for s, r in ranked if s > 0][: max(1, min(int(limit), 20))]
        return {"skills": hits, "matched": "meaning" if semantic else "words", "not_eligible": not_eligible}

    # ------------------------------------------------------------------ change

    def set_state(self, skill_id: str, state: str, revision: int | None = None) -> dict[str, Any]:
        if state not in STATES:
            raise ValueError(f"state is one of {sorted(STATES)}")
        row = self._skill(skill_id, revision)
        if state == "active" and row["conversion"] not in ("completed", "native"):
            raise ValueError(f"{row['name']} is not converted yet ({row['conversion']})")
        with self._sql() as conn:
            if state == "active":  # one active revision per skill
                conn.execute("UPDATE skill_revisions SET state = 'draft' WHERE skill_id = ? AND state = 'active'",
                             (row["skill_id"],))
            conn.execute("UPDATE skill_revisions SET state = ? WHERE skill_id = ? AND revision = ?",
                         (state, row["skill_id"], row["revision"]))
        return self.status(row["skill_id"], row["revision"])

    def forget(self, skill_id: str) -> dict[str, Any]:
        """Every revision, its framework, source units, vectors and kept files; returns its memory
        entries for the caller to erase from the memory itself."""
        row = self._skill(skill_id)
        rows = self._rows("SELECT * FROM skill_revisions WHERE skill_id = ?", (row["skill_id"],))
        memory = [json.loads(r["memory"]) for r in rows if r.get("memory")]
        with self._sql() as conn:
            conn.executemany("DELETE FROM skill_vectors WHERE text_sha = ?",
                             [(hashlib.sha256(self._doc(r).encode("utf-8")).hexdigest(),) for r in rows])
            conn.execute("DELETE FROM skill_revisions WHERE skill_id = ?", (row["skill_id"],))
        for sha in {r["source_sha"] for r in rows}:
            if not self._rows("SELECT 1 FROM skill_revisions WHERE source_sha = ?", (sha,)):
                shutil.rmtree(self.sources / sha, ignore_errors=True)
        return {"forgotten": row["skill_id"], "name": row["name"], "revisions": len(rows),
                "memory": [m for m in memory if m.get("cids")]}

    def outcome(self, skill_id: str, revision: int, success: bool, evidence: str) -> dict[str, Any]:
        row = self._skill(skill_id, revision)
        with self._sql() as conn:
            conn.execute(
                "UPDATE skill_revisions SET runs = runs + 1, successes = successes + ?, last_outcome = ? "
                "WHERE skill_id = ? AND revision = ?",
                (1 if success else 0, json.dumps({"success": bool(success), "evidence": evidence[:2000], "at": _now()}),
                 row["skill_id"], row["revision"]))
        updated = self._skill(row["skill_id"], row["revision"])
        return {"skill_id": row["skill_id"], "revision": row["revision"], "runs": updated["runs"],
                "successes": updated["successes"]}
