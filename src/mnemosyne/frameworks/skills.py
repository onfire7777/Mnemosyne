"""Skills kept as complete Proper Thinking frameworks.

Importing a skill (an Agent Skills folder, a zip or one Markdown file) keeps its files byte
for byte, splits its text into numbered source units, and runs Proper Thinking's framework
pipeline over them in a background job. The result - nodes, edges, scopes, audits, the
nine-section definitive document and a coverage ledger accounting for every unit - lives in
one SQLite file beside the memory store, with a skill record on top: name, applicability,
needs, effects, state and revisions. Scripts are stored, never run.
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

from .app_config import MODEL
from .book_manager import BookManager, cited_units
from .database import BookDatabase
from .framework import DEFAULT_MAX_CONTEXT_CHARS, DEFAULT_MAX_FRAMEWORK_CHUNKS

WORKERS = 3
#: BurnOS's own skill file: the nine-section document a person reads, then the whole framework
#: and the original files packed in a comment below it, so it imports with no conversion.
BS_SUFFIX = ".bs"
BS_HEAD = "<!-- burnos-skill v1"
MAX_FILES = 200
MAX_BYTES = 5_000_000
#: Everything a skill says must reach the extractor in one pass, so a skill's text is capped at
#: what Proper Thinking puts in one prompt. Books (larger sources) are a later step.
MAX_TEXT_CHARS = DEFAULT_MAX_CONTEXT_CHARS - 8_000
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
#: Attachments that could be run; anything else a skill carries (a licence, a template, an image)
#: does not make it able to act.
RUNNABLE_SUFFIXES = {".py", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".js", ".mjs", ".cjs",
                     ".ts", ".rb", ".pl", ".php", ".vbs", ".exe", ".dll", ".jar"}


def runnable(paths: list[str]) -> list[str]:
    return [p for p in paths if PurePosixPath(p).suffix.lower() in RUNNABLE_SUFFIXES]
STATES = {"draft", "active", "retired"}
STOPWORDS = set(
    "a an and are as at be but by can could do does for from had has have how i if in into is it its "
    "just me my no not of on only or our please so some than that the their them then "
    "there these they this to up us was we what when where which who why will with would you your".split()
)
SECTIONS = ("definition", "principle", "step", "warning", "constraint", "case", "example")
#: Words in a skill's framework that mean it acts on the world. BurnOS asks before such a
#: run acts; the list is read back to the user before the skill is turned on.
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
            value = pair.group(2).strip().strip("'\"")
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            meta[key] = value
    return meta, text[match.end():]


def blocks(text: str) -> list[str]:
    """Markdown split at blank lines and headings; a fenced code block stays whole."""
    out: list[str] = []
    current: list[str] = []
    fenced = False
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and (not line.strip() or line.startswith("#")):
            # A heading stays with what it heads: alone it is no unit a node could cite.
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


def source_units(texts: list[tuple[str, str]], limit: int = DEFAULT_MAX_FRAMEWORK_CHUNKS) -> list[str]:
    """Blocks of every text file, packed into at most ``limit`` units in reading order."""
    parts = [f"[{name}]\n{b}" if i == 0 and name != "SKILL.md" else b
             for name, text in texts for i, b in enumerate(blocks(text))]
    size = max(1, math.ceil(len(parts) / limit))
    return ["\n\n".join(parts[i:i + size]) for i in range(0, len(parts), size)]


def effects_of(nodes: list[dict[str, Any]], scripts: list[str]) -> list[str]:
    # Every node, not only steps: a skill that says anywhere that it acts is guarded.
    text = " ".join(f"{n.get('title', '')} {n.get('content', '')}" for n in nodes).lower()
    found = [name for name, pattern in EFFECT_WORDS.items() if re.search(pattern, text)]
    return found + (["runs scripts"] if runnable(scripts) else [])


class UnitStore:
    """Proper Thinking's vector store, for a skill: every bucket query gets every unit.

    shortcut: no ranking because a skill's units all fit one prompt (MAX_TEXT_CHARS); books
    will need real retrieval here.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    def search(self, book_id: int, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        return [
            {"chunk_id": c["id"], "page_number": c["page_number"], "chunk_index": c["chunk_index"],
             "text": c["chunk_text"], "distance": 0.0}
            for c in self.db.get_chunks_by_book_id(book_id)
        ]


class SkillStore:
    """One per frameworks file; a single worker thread converts one skill at a time."""

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
        self.manager = BookManager(str(self.path), UnitStore(BookDatabase(str(self.path))))
        self.db = self.manager.db
        with self._sql() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id TEXT NOT NULL, revision INTEGER NOT NULL, name TEXT NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '[]', applicability TEXT NOT NULL DEFAULT '',
                    needs TEXT NOT NULL DEFAULT '[]', effects TEXT NOT NULL DEFAULT '[]',
                    attachments TEXT NOT NULL DEFAULT '[]', meta TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL, book_id INTEGER NOT NULL, framework_id INTEGER NOT NULL,
                    source_sha TEXT NOT NULL, source_dir TEXT NOT NULL, model TEXT NOT NULL,
                    runs INTEGER NOT NULL DEFAULT 0, successes INTEGER NOT NULL DEFAULT 0,
                    last_outcome TEXT, created_at TEXT NOT NULL,
                    PRIMARY KEY (skill_id, revision));
                CREATE TABLE IF NOT EXISTS skill_vectors (
                    text_sha TEXT NOT NULL, model TEXT NOT NULL, vector TEXT NOT NULL,
                    PRIMARY KEY (text_sha, model));
                """
            )
        self._jobs: queue.Queue[tuple[str, int]] = queue.Queue()
        for n in range(WORKERS):  # several skills convert side by side
            threading.Thread(target=self._work, name=f"mnemosyne-skill-frameworks-{n}", daemon=True).start()
        # A conversion cut off by a restart starts again from its source units.
        # shortcut: restarts the whole conversion, not the phase it was in; a skill takes minutes.
        for row in self._rows("SELECT s.* FROM skills s JOIN frameworks f ON f.id = s.framework_id "
                              "WHERE f.generation_status = 'running'"):
            self._jobs.put((row["skill_id"], row["revision"]))

    def _sql(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._sql() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

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
                    name = PurePosixPath(info.filename)
                    if name.is_absolute() or ".." in name.parts or ":" in info.filename:
                        raise ValueError(f"unsafe path in zip: {info.filename}")
                    files.append((str(name), archive.read(info)))
            # A zip of one top folder: the skill is that folder.
            tops = {PurePosixPath(n).parts[0] for n, _ in files}
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

    # ------------------------------------------------------------------ .bs files

    def export_skill(self, skill_id: str, path: str, revision: int | None = None) -> dict[str, Any]:
        """One skill revision as a .bs file: the readable nine-section document, then everything
        needed to import it again with no conversion (framework, nodes, edges, source units and
        the original files) packed below it."""
        row = self._skill(skill_id, revision)
        out = Path(path).expanduser()
        if out.suffix.lower() != BS_SUFFIX:
            out = out / f"{row['name']}{BS_SUFFIX}"
        fid, bid = row["framework_id"], row["book_id"]
        kept = Path(row["source_dir"])
        payload = {
            "format": "burnos-skill", "version": 1,
            "skill": {k: row[k] for k in ("name", "aliases", "applicability", "needs", "effects",
                                           "attachments", "meta", "model")},
            "book": self._rows("SELECT * FROM books WHERE id = ?", (bid,))[0],
            "chunks": self._rows("SELECT * FROM chunks WHERE book_id = ? ORDER BY id", (bid,)),
            "framework": self._rows("SELECT * FROM frameworks WHERE id = ?", (fid,))[0],
            "nodes": self._rows("SELECT * FROM framework_nodes WHERE framework_id = ? ORDER BY id", (fid,)),
            "edges": self._rows("SELECT * FROM framework_edges WHERE framework_id = ? ORDER BY id", (fid,)),
            "files": {p.relative_to(kept).as_posix(): base64.b64encode(p.read_bytes()).decode("ascii")
                      for p in sorted(kept.rglob("*")) if p.is_file()},
        }
        packed = base64.b64encode(zlib.compress(json.dumps(payload).encode("utf-8"), 9)).decode("ascii")
        document = payload["framework"].get("definitive_document") or f"# {row['name']}\n"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"{document.rstrip()}\n\n{BS_HEAD}\n{packed}\n-->\n", encoding="utf-8")
        return {"skill_id": row["skill_id"], "revision": row["revision"], "path": str(out),
                "bytes": out.stat().st_size}

    def _import_bs(self, src: Path) -> dict[str, Any]:
        text = src.read_text(encoding="utf-8")
        at = text.rfind(BS_HEAD)
        if at < 0:
            raise ValueError(f"{src.name} is not a BurnOS skill file")
        payload = json.loads(zlib.decompress(base64.b64decode(text[at + len(BS_HEAD):].split("-->")[0].strip())))
        if payload.get("format") != "burnos-skill" or payload.get("version") != 1:
            raise ValueError(f"{src.name}: unsupported skill file version")
        files = [(rel, base64.b64decode(data)) for rel, data in payload["files"].items()]
        for rel, _ in files:
            p = PurePosixPath(rel)
            if p.is_absolute() or ".." in p.parts or ":" in rel:
                raise ValueError(f"unsafe path in skill file: {rel}")
        source_sha = _sha_of(files)
        skill = payload["skill"]
        same = self._rows("SELECT * FROM skills WHERE lower(name) = lower(?) ORDER BY revision DESC", (skill["name"],))
        for row in same:
            if row["source_sha"] == source_sha:
                return {"skill_id": row["skill_id"], "revision": row["revision"], "unchanged": True}
        keep = self._keep(source_sha, files)

        def insert(conn: sqlite3.Connection, table: str, row: dict[str, Any], **override: Any) -> int:
            values = {k: v for k, v in row.items() if k != "id"} | override
            cur = conn.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                               tuple(values.values()))
            return int(cur.lastrowid)

        with self._sql() as conn:
            bid = insert(conn, "books", payload["book"], file_path=str(keep))
            for c in payload["chunks"]:
                insert(conn, "chunks", c, book_id=bid)
            fid = insert(conn, "frameworks", payload["framework"], book_id=bid)
            ids = {n["id"]: insert(conn, "framework_nodes", n, framework_id=fid, parent_id=None,
                                   depends_on_node_id=None) for n in payload["nodes"]}
            for n in payload["nodes"]:
                conn.execute("UPDATE framework_nodes SET parent_id = ?, depends_on_node_id = ? WHERE id = ?",
                             (ids.get(n["parent_id"]), ids.get(n["depends_on_node_id"]), ids[n["id"]]))
            for e in payload["edges"]:
                if e["from_node_id"] in ids and e["to_node_id"] in ids:
                    insert(conn, "framework_edges", e, framework_id=fid,
                           from_node_id=ids[e["from_node_id"]], to_node_id=ids[e["to_node_id"]])
            skill_id = same[0]["skill_id"] if same else f"skill-{uuid4().hex[:12]}"
            revision = (same[0]["revision"] + 1) if same else 1
            conn.execute(
                "INSERT INTO skills (skill_id, revision, name, aliases, applicability, needs, effects, attachments, "
                "meta, state, book_id, framework_id, source_sha, source_dir, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
                (skill_id, revision, skill["name"], skill["aliases"], skill["applicability"], skill["needs"],
                 skill["effects"], skill["attachments"], skill["meta"], bid, fid, source_sha, str(keep),
                 skill["model"], _now()),
            )
        return {"skill_id": skill_id, "revision": revision, "name": skill["name"], "status": "imported",
                "from": BS_SUFFIX}

    def _keep(self, source_sha: str, files: list[tuple[str, bytes]]) -> Path:
        """The originals, byte for byte, under their digest; nothing in them is executed."""
        keep = self.sources / source_sha
        if not keep.exists():
            for rel, data in files:
                target = keep / PurePosixPath(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        return keep

    def import_skill(self, path: str, model: str, name: str | None = None) -> dict[str, Any]:
        if Path(path).suffix.lower() == BS_SUFFIX:
            return self._import_bs(Path(path).expanduser())
        # Plain Markdown is converted too: one .md file is one skill, and a folder of .md
        # files with no SKILL.md (prompt or command libraries) is one skill per file.
        folder = Path(path).expanduser()
        if folder.is_dir() and not any(p.name.lower() == "skill.md" for p in folder.iterdir()):
            pages = sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".md", ".markdown", BS_SUFFIX)
                           and p.is_file() and ".git" not in p.relative_to(folder).parts)
            if len(pages) > 1:
                return {"imported": [self.import_skill(str(p), model) for p in pages[:MAX_FILES]]}
        src, files = self._read_source(path)
        source_sha = _sha_of(files)

        texts: list[tuple[str, str]] = []
        scripts: list[str] = []
        for rel, data in files:
            # A licence is kept with the skill but is not part of what it teaches: converting the
            # Apache text made up 15 of internal-comms' 36 source units.
            legal = PurePosixPath(rel).stem.lower() in {"license", "licence", "notice", "copying"}
            if PurePosixPath(rel).suffix.lower() in TEXT_SUFFIXES and not legal:
                texts.append((rel, data.decode("utf-8", errors="replace")))
            else:
                scripts.append(rel)
        texts.sort(key=lambda t: (t[0] != "SKILL.md", t[0]))
        if not texts:
            raise ValueError("the skill has no Markdown or text file to read")
        meta, body = front_matter(texts[0][1])
        texts[0] = (texts[0][0], body)
        if sum(len(t) for _, t in texts) > MAX_TEXT_CHARS:
            raise ValueError(f"skill text over {MAX_TEXT_CHARS} characters: books are not imported yet")
        skill_name = (name or str(meta.get("name") or "") or src.stem).strip()
        if skill_name.lower() == "skill":
            skill_name = src.parent.name if src.is_file() else src.name

        same = self._rows("SELECT * FROM skills WHERE lower(name) = lower(?) ORDER BY revision DESC", (skill_name,))
        for row in same:
            if row["source_sha"] == source_sha:
                return {"skill_id": row["skill_id"], "revision": row["revision"], "unchanged": True}
        skill_id = same[0]["skill_id"] if same else f"skill-{uuid4().hex[:12]}"
        revision = (same[0]["revision"] + 1) if same else 1

        keep = self._keep(source_sha, files)
        units = source_units(texts)
        book_id = self.db.add_book(title=skill_name, filename="SKILL.md", file_path=str(keep),
                                   total_pages=len(units), page_numbering_basis="Source unit",
                                   target_audience=None)
        self.db.add_chunks(book_id, [{"page_number": i + 1, "chunk_index": 0, "chunk_text": u}
                                     for i, u in enumerate(units)])
        self.db.set_embeddings_generated(book_id, 1)
        framework_id = self.db.add_framework(book_id, skill_name, "", audit_result=None,
                                             generation_status="running")
        self.db.mark_framework_generation_running(framework_id)
        needs = meta.get("needs") or meta.get("mcp-servers") or meta.get("mcp_servers") or []
        with self._sql() as conn:
            conn.execute(
                "INSERT INTO skills (skill_id, revision, name, applicability, needs, attachments, meta, state, "
                "book_id, framework_id, source_sha, source_dir, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
                (skill_id, revision, skill_name, str(meta.get("description") or ""),
                 json.dumps(needs if isinstance(needs, list) else [needs]), json.dumps(sorted(scripts)),
                 json.dumps(meta), book_id, framework_id, source_sha, str(keep), model, _now()),
            )
        self._jobs.put((skill_id, revision))
        return {"skill_id": skill_id, "revision": revision, "name": skill_name, "units": len(units),
                "attachments": sorted(scripts), "status": "converting"}

    def _work(self) -> None:
        while True:
            skill_id, revision = self._jobs.get()
            try:
                self._convert(skill_id, revision)
            except Exception:  # noqa: BLE001 - the failure is recorded on the framework row
                pass

    def _convert(self, skill_id: str, revision: int) -> None:
        row = self._skill(skill_id, revision)
        fid = row["framework_id"]
        self.db.delete_framework_nodes(fid)
        self.db.delete_framework_edges(fid)
        self.db.mark_framework_generation_running(fid)
        MODEL.set(row["model"])  # this worker thread's context only
        self.manager._execute_framework_generation_job(row["book_id"], fid, row["name"], None, None)
        fw = self.db.get_framework(fid) or {}
        scope = " ".join(s for s in (fw.get("claimed_scope"), fw.get("evidenced_scope")) if s)
        with self._sql() as conn:
            conn.execute(
                "UPDATE skills SET applicability = ?, effects = ? WHERE skill_id = ? AND revision = ?",
                (" ".join(s for s in (row["applicability"], scope) if s).strip(),
                 json.dumps(effects_of(fw.get("nodes") or [], json.loads(row["attachments"]))),
                 skill_id, revision),
            )

    # ------------------------------------------------------------------ read

    def _skill(self, skill_id: str, revision: int | None = None) -> dict[str, Any]:
        rows = self._rows(
            "SELECT * FROM skills WHERE (skill_id = ? OR lower(name) = lower(?)) "
            + ("AND revision = ? " if revision else "")
            + "ORDER BY state = 'active' DESC, revision DESC LIMIT 1",
            (skill_id, skill_id, revision) if revision else (skill_id, skill_id),
        )
        if not rows:
            raise ValueError(f"no skill {skill_id}" + (f" revision {revision}" if revision else ""))
        return rows[0]

    def status(self, skill_id: str, revision: int | None = None) -> dict[str, Any]:
        row = self._skill(skill_id, revision)
        fw = self.db.get_framework(row["framework_id"]) or {}
        audit = fw.get("audit_result") or {}
        coverage = audit.get("coverage") or {}
        mech = fw.get("mechanical_audit_result") or {}
        judgment = (audit.get("phase4") or {}).get("last_judgment") or {}
        return {
            "skill_id": row["skill_id"], "revision": row["revision"], "name": row["name"],
            "state": row["state"], "conversion": fw.get("generation_status") or "unknown",
            "progress": fw.get("generation_last_log_line"), "error": fw.get("generation_error"),
            "nodes": len(fw.get("nodes") or []), "edges": len(fw.get("edges") or []),
            "coverage": {k: coverage.get(k) for k in ("complete", "unresolved")} if coverage else None,
            "mechanical_audit_passed": mech.get("passed") if mech else None,
            "judgment_findings": (judgment.get("findings") or [])[:5],
            "applicability": row["applicability"], "needs": json.loads(row["needs"]),
            "effects": json.loads(row["effects"]), "attachments": json.loads(row["attachments"]),
        }

    def get(self, skill_id: str, revision: int | None = None, section: str | None = None,
            node_id: int | None = None, attachment: str | None = None,
            offset: int = 0, limit: int = 6000) -> dict[str, Any]:
        row = self._skill(skill_id, revision)
        fw = self.db.get_framework(row["framework_id"]) or {}
        nodes = fw.get("nodes") or []
        edges = fw.get("edges") or []
        head = {"skill_id": row["skill_id"], "revision": row["revision"], "name": row["name"]}

        def page(text: str) -> dict[str, Any]:
            start = max(0, int(offset))
            end = start + max(1, min(int(limit), 20000))
            return {**head, "text": text[start:end], "offset": start, "total": len(text),
                    "more": end < len(text)}

        if attachment is not None:
            base = Path(row["source_dir"]).resolve()
            target = (base / PurePosixPath(attachment)).resolve()
            if base not in target.parents or not target.is_file():
                raise ValueError(f"no attachment {attachment}")
            return page(target.read_bytes().decode("utf-8", errors="replace"))
        if node_id is not None:
            node = next((n for n in nodes if n.get("id") == int(node_id)), None)
            if node is None:
                raise ValueError(f"no node {node_id} in {row['name']}")
            units = {c["page_number"]: c["chunk_text"] for c in self.db.get_chunks_by_book_id(row["book_id"])}
            return {**head, "node": node,
                    "edges": [e for e in edges if node["id"] in (e.get("from_node_id"), e.get("to_node_id"))],
                    "sources": {u: units[u] for u in sorted(cited_units(node.get("page_ref"))) if u in units}}
        section = None if section in (None, "", "overview") else section
        if section == "document":
            return page(fw.get("definitive_document") or "")
        if section == "source":
            units = self.db.get_chunks_by_book_id(row["book_id"])
            return page("\n\n".join(f"[Page {c['page_number']}]\n{c['chunk_text']}" for c in units))
        if section:
            kind = section.lower().rstrip("s")
            if kind not in SECTIONS:
                raise ValueError(f"section is one of document, source, {', '.join(s + 's' for s in SECTIONS)}")
            return {**head, "section": section,
                    "nodes": [{k: n.get(k) for k in ("id", "title", "content", "page_ref", "definitive_fields",
                                                       "epistemic_type")}
                              for n in nodes if n.get("node_type") == kind]}
        counts: dict[str, int] = {}
        for n in nodes:
            counts[n.get("node_type") or "section"] = counts.get(n.get("node_type") or "section", 0) + 1
        return {**self.status(row["skill_id"], row["revision"]), "sections": counts,
                "claimed_scope": fw.get("claimed_scope"), "evidenced_scope": fw.get("evidenced_scope"),
                "revisions": [{"revision": r["revision"], "state": r["state"], "created_at": r["created_at"]}
                              for r in self._rows("SELECT revision, state, created_at FROM skills "
                                                  "WHERE skill_id = ? ORDER BY revision", (row["skill_id"],))]}

    # ------------------------------------------------------------------ search

    def _vectors(self, embedder: Any, texts: list[str]) -> list[list[float]]:
        from mnemosyne.passages import _embed, _embedding_model_key

        model = _embedding_model_key(embedder)
        shas = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
        known = {r["text_sha"]: json.loads(r["vector"]) for r in self._rows(
            f"SELECT text_sha, vector FROM skill_vectors WHERE model = ? AND text_sha IN "
            f"({','.join('?' * len(shas))})", (model, *shas))} if shas else {}
        missing = [i for i, s in enumerate(shas) if s not in known]
        if missing:
            fresh = _embed(embedder, [texts[i] for i in missing])
            with self._sql() as conn:
                for i, vector in zip(missing, fresh, strict=True):
                    known[shas[i]] = vector
                    conn.execute("INSERT OR REPLACE INTO skill_vectors VALUES (?, ?, ?)",
                                 (shas[i], model, json.dumps(vector)))
        return [known[s] for s in shas]

    def _doc(self, row: dict[str, Any]) -> str:
        """What a skill is found by: its name, applicability and the titles of its nodes."""
        fw = self.db.get_framework(row["framework_id"]) or {}
        titles = "; ".join(n.get("title") or "" for n in fw.get("nodes") or [])
        return f"{row['name']}. {row['applicability']} {titles}"[:4000]

    def search(self, query: str, available: list[str] | None = None, include_drafts: bool = False,
               limit: int = 5, embedder: Any = None, floor: float = 0.5,
               timeout: float = 2.0) -> dict[str, Any]:
        """Exact name first; then only skills whose needs are met; then rank by meaning."""
        states = ("active", "draft") if include_drafts else ("active",)
        rows = [r for r in self._rows("SELECT * FROM skills ORDER BY revision DESC") if r["state"] in states]
        latest: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r["skill_id"] not in latest or r["state"] == "active":
                latest[r["skill_id"]] = r
        have = {a.strip().lower() for a in (available or [])}
        skipped = []
        eligible = []
        for r in latest.values():
            missing = [n for n in json.loads(r["needs"]) if available is not None and n.lower() not in have]
            (skipped if missing else eligible).append({**r, "missing": missing})

        def out(r: dict[str, Any], score: float) -> dict[str, Any]:
            # effects and scripts travel with every hit: the caller guards a run by them.
            return {"skill_id": r["skill_id"], "revision": r["revision"], "name": r["name"],
                    "state": r["state"], "applicability": r["applicability"][:400],
                    "effects": json.loads(r["effects"]), "scripts": bool(runnable(json.loads(r["attachments"]))),
                    "score": round(score, 4)}

        q = " ".join(query.lower().split())
        not_eligible = [{"name": r["name"], "missing": r["missing"]} for r in skipped]
        if not q:  # an empty query lists them all
            return {"skills": [out(r, 0.0) for r in eligible], "not_eligible": not_eligible}
        # A skill named in the request is the one meant, ahead of anything ranked.
        named = [r for r in eligible
                 if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", q)
                        for n in {r["name"].lower(), r["name"].lower().replace("-", " "),
                                  *json.loads(r["aliases"])})]
        if named:
            return {"skills": [out(r, 1.0) for r in named], "matched": "name", "not_eligible": not_eligible}
        if not eligible:
            return {"skills": [], "not_eligible": not_eligible}
        docs = [self._doc(r) for r in eligible]
        scores: list[float] = []
        semantic = embedder is not None and getattr(embedder, "name", "") != "local-hashing"
        if semantic:
            # A hosted embedder can stall for seconds; the caller is a task waiting to start.
            pool = ThreadPoolExecutor(max_workers=1)
            pending = pool.submit(lambda: (self._vectors(embedder, docs), self._vectors(embedder, [query])[0]))
            pool.shutdown(wait=False)
            try:
                vectors, qv = pending.result(timeout=timeout)
                cosines = [sum(a * b for a, b in zip(qv, v, strict=False))
                           / ((math.sqrt(sum(a * a for a in qv)) * math.sqrt(sum(b * b for b in v))) or 1.0)
                           for v in vectors]
                # Every pair of texts has some cosine: below the floor is "not about this".
                scores = [c if c >= floor else 0.0 for c in cosines]
            except Exception:  # noqa: BLE001 - timeout or provider error: rank by words instead
                semantic = False
        if not semantic:
            from mnemosyne.passages import PassageIndex

            # With a handful of skills BM25 cannot tell "the" from "outbox": the IDF of every
            # word is the same, so the little words alone would match everything.
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
        if state == "active":
            fw = self.db.get_framework(row["framework_id"]) or {}
            if fw.get("generation_status") != "completed":
                raise ValueError(f"{row['name']} is not converted yet ({fw.get('generation_status')})")
        with self._sql() as conn:
            if state == "active":  # one active revision per skill
                conn.execute("UPDATE skills SET state = 'draft' WHERE skill_id = ? AND state = 'active'",
                             (row["skill_id"],))
            conn.execute("UPDATE skills SET state = ? WHERE skill_id = ? AND revision = ?",
                         (state, row["skill_id"], row["revision"]))
        return self.status(row["skill_id"], row["revision"])

    def forget(self, skill_id: str) -> dict[str, Any]:
        """Every revision, its framework, source units, vectors and kept files."""
        row = self._skill(skill_id)
        rows = self._rows("SELECT * FROM skills WHERE skill_id = ?", (row["skill_id"],))
        shas = [hashlib.sha256(self._doc(r).encode("utf-8")).hexdigest() for r in rows]
        with self._sql() as conn:
            conn.executemany("DELETE FROM skill_vectors WHERE text_sha = ?", [(s,) for s in shas])
            for r in rows:
                fid, bid = r["framework_id"], r["book_id"]
                conn.execute("DELETE FROM framework_edges WHERE framework_id = ?", (fid,))
                conn.execute("DELETE FROM framework_nodes WHERE framework_id = ?", (fid,))
                conn.execute("DELETE FROM frameworks WHERE id = ?", (fid,))
                conn.execute("DELETE FROM chunks WHERE book_id = ?", (bid,))
                conn.execute("DELETE FROM books WHERE id = ?", (bid,))
            conn.execute("DELETE FROM skills WHERE skill_id = ?", (row["skill_id"],))
        for sha in {r["source_sha"] for r in rows}:
            if not self._rows("SELECT 1 FROM skills WHERE source_sha = ?", (sha,)):
                shutil.rmtree(self.sources / sha, ignore_errors=True)
        return {"forgotten": row["skill_id"], "name": row["name"], "revisions": len(rows)}

    def outcome(self, skill_id: str, revision: int, success: bool, evidence: str) -> dict[str, Any]:
        row = self._skill(skill_id, revision)
        with self._sql() as conn:
            conn.execute(
                "UPDATE skills SET runs = runs + 1, successes = successes + ?, last_outcome = ? "
                "WHERE skill_id = ? AND revision = ?",
                (1 if success else 0, json.dumps({"success": bool(success), "evidence": evidence[:2000],
                                                  "at": _now()}), row["skill_id"], row["revision"]),
            )
        updated = self._skill(row["skill_id"], row["revision"])
        return {"skill_id": row["skill_id"], "revision": row["revision"], "runs": updated["runs"],
                "successes": updated["successes"]}
