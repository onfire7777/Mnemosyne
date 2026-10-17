"""Skills kept as complete frameworks (mnemosyne.frameworks), one record per revision.

Importing a skill - an Agent Skills folder, a zip, any Markdown file, a folder of Markdown
files (one skill each) or a .bs file - keeps its files byte for byte, splits its text into
numbered source units and builds the framework in the background, three skills at a time.
The framework (nodes, edges, audits, scopes, coverage, document) is one JSON column of the
revision. Scripts are stored, never run.
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
#: BurnOS's own skill file: the readable document, then the framework and the original files
#: packed in a comment below it, so it imports with no conversion.
BS_SUFFIX = ".bs"
BS_HEAD = "<!-- burnos-skill v"
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
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


def effects_of(nodes: list[dict[str, Any]], files: list[str]) -> list[str]:
    text = " ".join(f"{n.get('title', '')} {n.get('content', '')}" for n in nodes).lower()
    return [k for k, pattern in EFFECT_WORDS.items() if re.search(pattern, text)] + (
        ["runs scripts"] if runnable(files) else [])


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
                fw: dict[str, Any] | None, state: str = "draft", applicability: str = "") -> None:
        with self._sql() as conn:
            conn.execute(
                "INSERT INTO skill_revisions (skill_id, revision, name, applicability, needs, effects, attachments, "
                "meta, state, conversion, units, framework, source_sha, source_dir, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (skill_id, revision, name, applicability or str(meta.get("description") or ""), json.dumps(needs),
                 json.dumps(effects_of(fw["nodes"], attachments) if fw else []), json.dumps(sorted(attachments)),
                 json.dumps(meta), state, "completed" if fw else "converting", json.dumps(units),
                 json.dumps(fw) if fw else None, source_sha, str(keep), model, _now()))

    def import_skill(self, path: str, model: str, name: str | None = None, force: bool = False) -> dict[str, Any]:
        folder = Path(path).expanduser()
        if folder.suffix.lower() == BS_SUFFIX:
            return self._import_bs(folder)
        # A folder of Markdown files with no SKILL.md (a prompt or command library): one skill each.
        if folder.is_dir() and not any(p.name.lower() == "skill.md" for p in folder.iterdir()):
            pages = sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".md", ".markdown", BS_SUFFIX)
                           and p.is_file() and ".git" not in p.relative_to(folder).parts
                           and p.stem.lower() not in LEGAL)
            if len(pages) > 1:
                return {"imported": [self.import_skill(str(p), model) for p in pages[:MAX_FILES]]}
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
        if sum(len(t) for _, t in texts) > MAX_TEXT_CHARS:
            raise ValueError(f"skill text over {MAX_TEXT_CHARS} characters: books are not imported yet")
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
                     needs if isinstance(needs, list) else [needs], kept, None)
        self._jobs.put((skill_id, revision))
        return {"skill_id": skill_id, "revision": revision, "name": skill_name, "units": len(units),
                "attachments": sorted(kept), "status": "converting"}

    def regenerate(self, skill_id: str, model: str) -> dict[str, Any]:
        """A fresh conversion of a skill's kept files, as a new revision."""
        row = self._skill(skill_id)
        files = sorted(Path(row["source_dir"]).rglob("*"))
        if len([p for p in files if p.is_file()]) == 1:
            return self.import_skill(str(next(p for p in files if p.is_file())), model, row["name"], force=True)
        return self.import_skill(row["source_dir"], model, row["name"], force=True)

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

        fw = frameworks.build(row["name"], json.loads(row["units"]), progress)
        scope = " ".join(fw["meta"][k] for k in ("claimed_scope", "evidenced_scope") if "Not stated" not in fw["meta"][k])
        with self._sql() as conn:
            conn.execute(
                "UPDATE skill_revisions SET framework = ?, conversion = 'completed', progress = 'done', "
                "applicability = ?, effects = ? WHERE skill_id = ? AND revision = ?",
                (json.dumps(fw), " ".join(s for s in (row["applicability"], scope) if s).strip(),
                 json.dumps(effects_of(fw["nodes"], json.loads(row["attachments"]))), skill_id, revision))

    # ------------------------------------------------------------------ .bs files

    def export_skill(self, skill_id: str, path: str, revision: int | None = None) -> dict[str, Any]:
        """A revision as a .bs file: its document, then framework, units and original files packed below."""
        row = self._skill(skill_id, revision)
        if row["conversion"] != "completed":
            raise ValueError(f"{row['name']} is not converted yet")
        out = Path(path).expanduser()
        if out.suffix.lower() != BS_SUFFIX:
            out = out / f"{row['name']}{BS_SUFFIX}"
        kept = Path(row["source_dir"])
        fw = json.loads(row["framework"])
        payload = {"format": "burnos-skill", "version": 2,
                   "skill": {k: row[k] for k in ("name", "aliases", "applicability", "needs", "attachments", "meta", "model")},
                   "units": json.loads(row["units"]), "framework": fw,
                   "files": {p.relative_to(kept).as_posix(): base64.b64encode(p.read_bytes()).decode("ascii")
                             for p in sorted(kept.rglob("*")) if p.is_file()}}
        packed = base64.b64encode(zlib.compress(json.dumps(payload).encode("utf-8"), 9)).decode("ascii")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"{fw['document'].rstrip()}\n\n{BS_HEAD}2\n{packed}\n-->\n", encoding="utf-8")
        return {"skill_id": row["skill_id"], "revision": row["revision"], "path": str(out), "bytes": out.stat().st_size}

    def _import_bs(self, src: Path) -> dict[str, Any]:
        text = src.read_text(encoding="utf-8")
        at = text.rfind(BS_HEAD)
        if at < 0:
            raise ValueError(f"{src.name} is not a BurnOS skill file")
        body = text[at + len(BS_HEAD):].split("\n", 1)[1].split("-->")[0].strip()
        payload = json.loads(zlib.decompress(base64.b64decode(body)))
        if payload.get("format") != "burnos-skill" or payload.get("version") not in (1, 2):
            raise ValueError(f"{src.name}: unsupported skill file version")
        files = [(rel, base64.b64decode(data)) for rel, data in payload["files"].items()]
        if not all(_safe(rel) for rel, _ in files):
            raise ValueError(f"unsafe path in {src.name}")
        units, fw = (payload["units"], payload["framework"]) if payload["version"] == 2 else _from_v1(payload)
        skill = payload["skill"]
        source_sha = _sha_of(files)
        nxt = self._next(skill["name"], source_sha, False)
        if isinstance(nxt, dict):
            return nxt
        load = lambda v: json.loads(v) if isinstance(v, str) else v  # noqa: E731
        self._insert(*nxt, skill["name"], units, source_sha, self._keep(source_sha, files), skill.get("model", ""),
                     load(skill.get("meta") or {}), load(skill.get("needs") or []), load(skill.get("attachments") or []),
                     fw, applicability=skill.get("applicability", ""))
        return {"skill_id": nxt[0], "revision": nxt[1], "name": skill["name"], "status": "imported", "from": BS_SUFFIX}

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

        if attachment is not None:
            base = Path(row["source_dir"]).resolve()
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

    def ask(self, skill_id: str, question: str, revision: int | None = None) -> dict[str, Any]:
        """A question about a skill, answered from its framework and source only."""
        row = self._skill(skill_id, revision)
        if row["conversion"] != "completed":
            raise ValueError(f"{row['name']} is not converted yet")
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

    def _doc(self, row: dict[str, Any]) -> str:
        """What a skill is found by: its name, applicability and the titles of its nodes."""
        fw = json.loads(row["framework"]) if row["framework"] else {}
        titles = "; ".join(n["title"] for n in fw.get("nodes") or [])
        return f"{row['name']}. {row['applicability']} {titles}"[:4000]

    def search(self, query: str, available: list[str] | None = None, include_drafts: bool = False,
               limit: int = 5, embedder: Any = None, floor: float = 0.5, timeout: float = 2.0) -> dict[str, Any]:
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
                    "applicability": r["applicability"][:400], "effects": json.loads(r["effects"]),
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
                norm = math.sqrt(sum(a * a for a in qv)) or 1.0
                scores = [c if c >= floor else 0.0 for c in (
                    sum(a * b for a, b in zip(qv, v, strict=False)) / ((norm * math.sqrt(sum(b * b for b in v))) or 1.0)
                    for v in vectors)]
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
        if state == "active" and row["conversion"] != "completed":
            raise ValueError(f"{row['name']} is not converted yet ({row['conversion']})")
        with self._sql() as conn:
            if state == "active":  # one active revision per skill
                conn.execute("UPDATE skill_revisions SET state = 'draft' WHERE skill_id = ? AND state = 'active'",
                             (row["skill_id"],))
            conn.execute("UPDATE skill_revisions SET state = ? WHERE skill_id = ? AND revision = ?",
                         (state, row["skill_id"], row["revision"]))
        return self.status(row["skill_id"], row["revision"])

    def forget(self, skill_id: str) -> dict[str, Any]:
        """Every revision, its framework, source units, vectors and kept files."""
        row = self._skill(skill_id)
        rows = self._rows("SELECT * FROM skill_revisions WHERE skill_id = ?", (row["skill_id"],))
        with self._sql() as conn:
            conn.executemany("DELETE FROM skill_vectors WHERE text_sha = ?",
                             [(hashlib.sha256(self._doc(r).encode("utf-8")).hexdigest(),) for r in rows])
            conn.execute("DELETE FROM skill_revisions WHERE skill_id = ?", (row["skill_id"],))
        for sha in {r["source_sha"] for r in rows}:
            if not self._rows("SELECT 1 FROM skill_revisions WHERE source_sha = ?", (sha,)):
                shutil.rmtree(self.sources / sha, ignore_errors=True)
        return {"forgotten": row["skill_id"], "name": row["name"], "revisions": len(rows)}

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
