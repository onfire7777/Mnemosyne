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
import copy
import hashlib
import io
import json
import math
import os
import posixpath
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
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from mnemosyne import frameworks

WORKERS = 3
MAX_UNITS = 60
MAX_FILES = 200
#: The model answers kept for resuming and rebuilding; the books built longest ago are dropped first.
CACHE_MAX_BYTES = 500_000_000
MAX_BYTES = 5_000_000
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
CHUNK_CHARS = 4000
FRAGMENT_WORDS = 40
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


def _epub_member(base: str, href: str) -> str:
    """Resolve one package URL inside the archive, never on the filesystem."""
    url = urlsplit(href)
    if url.scheme or url.netloc or url.query:
        raise ValueError(f"unsupported EPUB chapter URL: {href!r}")
    relative = unquote(url.path, errors="strict")
    if not relative or relative.startswith("/") or "\\" in relative or "\x00" in relative:
        raise ValueError(f"unsafe EPUB chapter URL: {href!r}")
    member = posixpath.normpath(posixpath.join(base, relative))
    if member == ".." or member.startswith("../"):
        raise ValueError(f"EPUB chapter URL leaves the archive: {href!r}")
    return member


def _epub_text(raw: bytes, *, fragment_ids: set[str] | None = None) -> str:
    """Read XML encodings and mixed text without stripping literal markup text."""
    from xml.etree import ElementTree

    root = ElementTree.fromstring(raw)
    if fragment_ids is not None:
        for element in root.iter():
            for key in ("id", "{http://www.w3.org/XML/1998/namespace}id"):
                if element.get(key):
                    fragment_ids.add(element.get(key))
    local = lambda e: e.tag.rsplit("}", 1)[-1].lower()  # noqa: E731
    body = next((e for e in root.iter() if local(e) == "body"), root)
    blocks = {"address", "article", "aside", "blockquote", "br", "div", "dl", "dt", "dd", "figure",
              "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
              "main", "nav", "ol", "p", "pre", "section", "table", "td", "th", "tr", "ul"}
    parts: list[str] = []

    def walk(element: Any) -> None:
        tag = local(element)
        if tag in {"head", "script", "style"}:
            return
        if tag in blocks:
            parts.append("\n")
        if tag == "img" and element.get("alt"):
            parts.extend((" ", element.get("alt"), " "))
        if element.text:
            parts.append(element.text)
        for child in element:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if tag in blocks:
            parts.append("\n")

    walk(body)
    return " ".join("".join(parts).split())


def _epub_toc(book: zipfile.ZipFile, opf: Any, base: str, sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Publisher navigation inventory; unresolved targets remain visible for review."""
    from xml.etree import ElementTree

    tag = lambda e: e.tag.rsplit("}", 1)[-1].lower()  # noqa: E731
    items = [e for e in opf.iter() if tag(e) == "item"]
    spine = next((e for e in opf.iter() if tag(e) == "spine"), None)
    ncx_id = spine.get("toc") if spine is not None else None
    candidates = [(e, "epub3-nav") for e in items if "nav" in (e.get("properties") or "").split()]
    ncx = next((e for e in items if ncx_id and e.get("id") == ncx_id), None)
    missing_ncx = bool(ncx_id and ncx is None)
    if ncx is None:
        ncx = next((e for e in items if e.get("media-type") == "application/x-dtbncx+xml"), None)
    if ncx is not None:
        candidates.append((ncx, "epub2-ncx"))
    members = set(book.namelist())
    report: dict[str, Any] = {"detection": "publisher-toc-unreadable" if candidates or missing_ncx else "spine-only",
                              "format": None, "entries": [],
                              "errors": [f"declared NCX item {ncx_id!r} is missing"] if missing_ncx else [],
                              "source_count": sum(len(s["labels"]) for s in sources.values())}
    for item, format_name in candidates:
        entries: list[dict[str, Any]] = []
        try:
            member = _epub_member(base, item.get("href") or "")
            root = ElementTree.fromstring(book.read(member))
            toc_base = posixpath.dirname(member)

            def entry(title: str, href: str | None, depth: int, parent: int | None) -> int:
                order = len(entries) + 1
                result = {"order": order, "title": " ".join(title.split()), "depth": depth, "parent": parent,
                          "href": href, "target": None, "fragment": None, "source_labels": [],
                          "status": "heading" if not href else "unresolved", "reason": None}
                if href:
                    try:
                        url = urlsplit(href)
                        target = member if href.startswith("#") else _epub_member(toc_base, href)
                        fragment = unquote(url.fragment, errors="strict")
                        result.update(target=target, fragment=fragment or None)
                        source = sources.get(target)
                        if source is None:
                            result["reason"] = "target is outside the spine" if target in members else "target is missing"
                        else:
                            result["source_labels"] = list(source["labels"])
                            if fragment and fragment not in source["fragments"]:
                                result["reason"] = "target fragment is missing"
                            else:
                                result["status"] = "resolved"
                    except (ValueError, UnicodeError) as exc:
                        result["reason"] = str(exc)
                entries.append(result)
                return order

            if format_name == "epub3-nav":
                nav = next((e for e in root.iter() if tag(e) == "nav" and (
                    "toc" in (e.get("{http://www.idpf.org/2007/ops}type") or e.get("type") or "").split()
                    or "doc-toc" in (e.get("role") or "").split())), None)
                listing = next((e for e in nav.iter() if tag(e) == "ol"), None) if nav is not None else None
                if listing is None:
                    raise ValueError("navigation document has no toc ordered list")

                def walk_list(node: Any, depth: int = 0, parent: int | None = None) -> None:
                    for li in node:
                        if tag(li) != "li":
                            continue
                        label = next((e for e in li if tag(e) in {"a", "span"}), None)
                        title = "".join(label.itertext()) if label is not None else (li.text or "")
                        order = entry(title, label.get("href") if label is not None else None, depth, parent)
                        for child in li:
                            if tag(child) == "ol":
                                walk_list(child, depth + 1, order)

                walk_list(listing)
            else:
                nav_map = next((e for e in root.iter() if tag(e) == "navmap"), None)
                if nav_map is None:
                    raise ValueError("NCX document has no navMap")

                def walk_ncx(node: Any, depth: int = 0, parent: int | None = None) -> None:
                    for point in node:
                        if tag(point) != "navpoint":
                            continue
                        label = next((e for e in point if tag(e) == "navlabel"), None)
                        content = next((e for e in point if tag(e) == "content"), None)
                        order = entry("".join(label.itertext()) if label is not None else "",
                                      content.get("src") if content is not None else None, depth, parent)
                        walk_ncx(point, depth + 1, order)

                walk_ncx(nav_map)
            if not entries:
                raise ValueError("publisher table of contents has no entries")
            report.update(detection="publisher-toc", format=format_name, entries=entries)
            break
        except (KeyError, ValueError, ElementTree.ParseError, LookupError) as exc:
            report["errors"].append(f"{format_name}: {exc}")
    report.update(toc_entry_count=len(report["entries"]),
                  resolved_count=sum(e["status"] == "resolved" for e in report["entries"]),
                  unresolved_count=sum(e["status"] == "unresolved" for e in report["entries"]),
                  heading_count=sum(e["status"] == "heading" for e in report["entries"]))
    return report


def book_pages(path: Path, *, source_bytes: bytes | None = None,
               inventory: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Text only, located by PDF page or EPUB spine item; no OCR or visual interpretation.

    Provably blank PDF pages retain an empty entry. Unreadable nonblank pages
    fail the import instead of silently presenting partial text as the book.
    """
    if source_bytes is None and path.stat().st_size > BOOK_MAX_BYTES:
        raise ValueError(f"{path.name} is over {BOOK_MAX_BYTES} bytes")
    source_bytes = path.read_bytes() if source_bytes is None else source_bytes
    if len(source_bytes) > BOOK_MAX_BYTES:
        raise ValueError(f"{path.name} is over {BOOK_MAX_BYTES} bytes")
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("reading a PDF needs pypdf (pip install pypdf)") from exc
        pages = []
        unreadable = []
        for n, page in enumerate(PdfReader(io.BytesIO(source_bytes)).pages, 1):
            try:
                text = (page.extract_text() or "").strip()
                content = page.get_contents()
                annotations = page.get("/Annots") if hasattr(page, "get") else None
                blank = (content is None or not content.get_data().strip()) and not annotations
            except Exception:  # malformed text streams must not yield a partial book
                unreadable.append(n)
                continue
            if not text and not blank:
                unreadable.append(n)
            pages.append((f"p.{n}", text))
        if unreadable:
            raise ValueError(f"incomplete PDF text extraction in {path.name}: pages {unreadable} have content "
                             "but no readable text; apply OCR or repair their text layer before importing")
        return pages
    # EPUB: a zip of XHTML chapters, in the order its package file's spine gives.
    from xml.etree import ElementTree

    with zipfile.ZipFile(io.BytesIO(source_bytes)) as book:
        if sum(i.file_size for i in book.infolist()) > BOOK_MAX_BYTES:
            raise ValueError(f"{path.name} unpacks to over {BOOK_MAX_BYTES} bytes")
        try:
            container = ElementTree.fromstring(book.read("META-INF/container.xml"))
        except (KeyError, ElementTree.ParseError) as exc:
            raise ValueError(f"incomplete EPUB: cannot read its container: {exc}") from exc
        tag = lambda e: e.tag.rsplit("}", 1)[-1]  # noqa: E731 - with or without the OPF namespace
        package = next((e.get("full-path") for e in container.iter() if tag(e) == "rootfile"), None)
        if not package:
            raise ValueError("incomplete EPUB: no package path in its container")
        opf_path = _epub_member("", package)
        try:
            opf = ElementTree.fromstring(book.read(opf_path))
        except (KeyError, ElementTree.ParseError) as exc:
            raise ValueError(f"incomplete EPUB: cannot read its package: {exc}") from exc
        hrefs = {}
        for item in (e for e in opf.iter() if tag(e) == "item"):
            key = item.get("id")
            if key in hrefs:
                raise ValueError(f"incomplete EPUB: duplicate manifest ID {key!r}")
            hrefs[key] = item.get("href")
        base = posixpath.dirname(opf_path)
        pages = []
        sources: dict[str, dict[str, Any]] = {}
        refs = [e.get("idref") for e in opf.iter() if tag(e) == "itemref"]
        if not refs:
            raise ValueError(f"incomplete EPUB: {path.name} has no reading-order spine")
        for n, ref in enumerate(refs, 1):
            if ref not in hrefs or not hrefs[ref]:
                raise ValueError(f"incomplete EPUB: spine item {n} ({ref!r}) has no chapter in the manifest")
            member = _epub_member(base, hrefs[ref])
            fragments: set[str] = set()
            try:
                text = _epub_text(book.read(member), fragment_ids=fragments)
            except (KeyError, ElementTree.ParseError, ValueError, LookupError) as exc:
                raise ValueError(f"incomplete EPUB: cannot read spine item {n} ({member}): {exc}") from exc
            if not text:
                raise ValueError(f"incomplete EPUB: spine item {n} ({member}) has no readable text; "
                                 "extract its image or embedded content before importing")
            pages.append((f"ch.{n}", text))
            source = sources.setdefault(member, {"labels": [], "fragments": fragments})
            source["labels"].append(f"ch.{n}")
        if inventory is not None:
            inventory["publisher_toc"] = _epub_toc(book, opf, base, sources)
        return pages


def chunk_pages(pages: list[tuple[str, str]]) -> list[str]:
    """Bounded passages, each led by where it stands in the book. A scrap shorter
    than FRAGMENT_WORDS (a page break's tail, a caption) joins the passage before it - or after it,
    at the start - when it fits. Separate EPUB chapters never share a passage."""
    out: list[str] = []
    counts: list[int] = []
    labels: list[str] = []
    for label, text in pages:
        head = f"[{label}] " if label else ""
        room = CHUNK_CHARS - len(head)
        if room < 1:
            raise ValueError("book location label exceeds the passage size limit")
        words = [word[i:i + room] for word in text.split() for i in range(0, len(word), room)]
        groups: list[list[str]] = []
        size = 0
        for word in words:
            if not groups or len(groups[-1]) >= CHUNK_WORDS or size + 1 + len(word) > room:
                groups.append([])
                size = 0
            size += len(word) + bool(groups[-1])
            groups[-1].append(word)
        for group in groups:
            piece = head + " ".join(group)
            count = len(group)
            chapter_boundary = bool(out and label != labels[-1]
                                    and (label.startswith("ch.") or labels[-1].startswith("ch.")))
            if (out and not chapter_boundary and counts[-1] + count <= CHUNK_WORDS
                    and len(out[-1]) + 1 + len(piece) <= CHUNK_CHARS
                    and (count < FRAGMENT_WORDS or counts[-1] < FRAGMENT_WORDS)):
                out[-1] += f" {piece}"
                counts[-1] += count
                labels[-1] = label
            else:
                out.append(piece)
                counts.append(count)
                labels.append(label)
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
    chunks = sorted(payload["chunks"], key=lambda c: c["page_number"])
    units = [c["chunk_text"] for c in chunks]
    page_units: dict[int, list[int]] = {}
    for number, chunk in enumerate(chunks, 1):
        page = chunk["page_number"]
        if type(page) is int and page >= 0:
            page_units.setdefault(page, []).append(number)

    def cited_units(reference: Any) -> list[int]:
        if not isinstance(reference, str):
            return []
        # Legacy references name source pages, not chunk positions. A page can
        # have several chunks; a missing page must never cite an unrelated unit.
        value = re.sub(r"\b(?:pages?|pp?)\.?\s*(?=\d)", "", reference, flags=re.I).strip(" []()")
        item = r"\d{1,9}(?:\s*[-–]\s*\d{1,9})?"
        if not re.fullmatch(rf"{item}(?:(?:\s*[,;]\s*|\s+){item})*", value):
            return []
        cited: set[int] = set()
        for match in re.finditer(r"(\d{1,9})(?:\s*[-–]\s*(\d{1,9}))?", value):
            first = int(match[1])
            last = int(match[2]) if match[2] is not None else first
            # Iterate the actual inventory, never allocate a potentially huge
            # numeric range supplied by an imported reference.
            for page, numbers in page_units.items():
                if first <= page <= last:
                    cited.update(numbers)
        return sorted(cited)

    ids = {n["id"]: i for i, n in enumerate(payload["nodes"])}
    nodes = []
    for n in payload["nodes"]:
        fields = json.loads(n["definitive_fields"]) if isinstance(n.get("definitive_fields"), str) else {}
        cited = cited_units(n.get("page_ref"))
        nodes.append({"id": ids[n["id"]], "type": n["node_type"], "title": n["title"], "content": n["content"],
                      "parent": ids.get(n.get("parent_id")), "depends_on": ids.get(n.get("depends_on_node_id")),
                      "units": cited, "fields": fields or {}, "epistemic_type": n.get("epistemic_type")})
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


def _verified_framework(fw: dict[str, Any], units: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Recheck stored source accounting and quotes without trusting saved verdicts."""
    if not isinstance(fw, dict) or not isinstance(units, list) or not units or not all(isinstance(u, str) for u in units):
        raise ValueError("framework and nonempty text source units are required")
    checked = copy.deepcopy(fw)
    nodes, edges = checked.get("nodes"), checked.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("framework nodes and edges must be lists")

    def source_record(node: Any) -> None:
        if (not isinstance(node, dict) or node.get("type") not in frameworks.NODE_TYPES
                or not isinstance(node.get("title"), str) or not node["title"].strip()
                or not isinstance(node.get("content"), str) or not isinstance(node.get("fields"), dict)
                or not isinstance(node.get("units"), list)
                or any(type(u) is not int or not 1 <= u <= len(units) for u in node["units"])):
            raise ValueError("invalid framework node or source-unit reference")
        quote = node["fields"].get("Source Quote")
        if quote is not None and (not isinstance(quote, dict)
                                  or any(not isinstance(quote.get(k, ""), str) for k in ("Quote", "Core Sentence"))):
            raise ValueError("invalid framework source quote")
        if any(k in node["fields"] and not isinstance(node["fields"][k], str) for k in ("ES", "EC", "CT", "CN")):
            raise ValueError("invalid framework epistemic tags")

    for index, node in enumerate(nodes):
        source_record(node)
        if type(node.get("id")) is not int or node["id"] != index:
            raise ValueError("framework node IDs must be consecutive integers")
        for key in ("parent", "depends_on"):
            if node.get(key) is not None and (type(node[key]) is not int or not 0 <= node[key] < len(nodes)):
                raise ValueError("invalid framework node relationship")
            node.setdefault(key, None)
        contributions = node.get("contributions")
        if contributions is not None:
            if not isinstance(contributions, list) or not contributions:
                raise ValueError("invalid framework contributions")
            for contribution in contributions:
                source_record(contribution)
                if contribution["type"] != node["type"] or contribution.get("contributions"):
                    raise ValueError("invalid nested or mismatched framework contribution")
            if {u for c in contributions for u in c["units"]} != set(node["units"]):
                raise ValueError("framework contributions do not account for the node's cited units")
    for edge in edges:
        if (not isinstance(edge, dict) or edge.get("type") not in frameworks.EDGE_TYPES
                or any(type(edge.get(k)) is not int or not 0 <= edge[k] < len(nodes) for k in ("from", "to"))
                or edge["from"] == edge["to"]):
            raise ValueError("invalid framework edge")
    problems = []
    if checked.get("approved") is not True:
        problems.append("framework was not approved")
    logic, judgment = checked.get("logic"), checked.get("judgment")
    if (not isinstance(logic, dict) or any(not isinstance(logic.get(k), list)
            or not all(isinstance(x, str) for x in logic[k]) for k in ("graph_issues", "logic_issues", "logic_warnings"))):
        problems.append("framework lacks a valid logic review")
    elif logic["graph_issues"] or logic["logic_issues"]:
        problems.append("framework has unresolved review issues")
    if (not isinstance(judgment, dict) or type(judgment.get("warrants_reextract")) is not bool
            or not isinstance(judgment.get("findings"), list)
            or not all(isinstance(x, str) for x in judgment["findings"])):
        problems.append("framework lacks a valid judgment review")
    elif judgment["warrants_reextract"]:
        problems.append("framework requires further extraction")
    reference: dict[int, str] = {}
    manifest = checked.get("chapter_manifest")
    if manifest is not None:
        accounted: list[int] = []
        valid = isinstance(manifest, list) and bool(manifest)
        for chapter in manifest if isinstance(manifest, list) else []:
            if (not isinstance(chapter, dict) or chapter.get("kind") not in {"content", "reference"}
                    or not isinstance(chapter.get("title"), str) or not isinstance(chapter.get("units"), list)
                    or not chapter["units"] or any(type(u) is not int or not 1 <= u <= len(units) for u in chapter["units"])
                    or chapter.get("first_unit") != chapter["units"][0] or chapter.get("last_unit") != chapter["units"][-1]
                    or chapter["units"] != list(range(chapter["units"][0], chapter["units"][-1] + 1))):
                valid = False
                continue
            accounted.extend(chapter["units"])
            if chapter.get("complete") is not True or chapter.get("failures") != []:
                problems.append("chapter review is incomplete")
            if chapter["kind"] == "reference":
                if chapter.get("status") != "reference" or chapter.get("part") is not None:
                    valid = False
                reference.update({u: chapter["title"] for u in chapter["units"]})
            elif chapter.get("status") != "complete" or type(chapter.get("part")) is not int:
                problems.append("chapter review is incomplete")
        if not valid or accounted != list(range(1, len(units) + 1)):
            reference = {}
            problems.append("chapter manifest does not account for every source unit exactly once")
    checked["coverage"] = frameworks.coverage(units, nodes, reference=reference)
    # The audit repairs fields/edges internally. Its validation copy must not
    # rewrite an imported artifact, especially a legacy draft kept for review.
    audit_copy = copy.deepcopy(checked)
    checked["mechanical"] = frameworks.mechanical_audit(audit_copy, units)
    if audit_copy["edges"] != checked["edges"]:
        checked["mechanical"]["passed"] = False
        checked["mechanical"]["failures"].append("stored graph requires structural repair before activation")
    if audit_copy["nodes"] != checked["nodes"]:
        checked["mechanical"]["passed"] = False
        checked["mechanical"]["failures"].append("stored node fields require repair before activation")
    if not checked["coverage"]["complete"]:
        problems.append("source coverage is incomplete")
    if not checked["mechanical"]["passed"]:
        problems.append("mechanical audit did not pass")
    if not nodes or not isinstance(checked.get("document"), str) or not checked["document"].strip():
        problems.append("framework has no usable nodes or document")
    if not problems:
        try:
            canonical_document = frameworks.render(checked)
        except (KeyError, TypeError, ValueError, AttributeError):
            problems.append("framework lacks complete canonical document metadata")
        else:
            if checked["document"].strip() != canonical_document.strip():
                problems.append("framework document does not match its verified nodes and metadata")
    checked["approved"] = not problems
    return checked, list(dict.fromkeys(problems))


def _framework_problems(fw: dict[str, Any], units: list[str]) -> list[str]:
    try:
        return _verified_framework(fw, units)[1]
    except (ValueError, KeyError, TypeError) as exc:
        return [f"invalid framework: {exc}"]


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
        self.cache = self.path.parent / "framework-cache"  # one folder of model answers per source digest
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
        # A conversion cut off by a restart runs again; its answers so far come from the answer cache.
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

    def make_burnskill(self, skill_id: str, model: str, memory: dict[str, str] | None = None, *,
                      source_revision: int | None = None) -> dict[str, Any]:
        """The framework of a skill's kept text, built in the background as a new revision; when it is
        done it becomes the active one and, given ``memory``, its nodes go into that memory."""
        row = self._skill(skill_id, source_revision)
        if source_revision is None:
            latest = self._rows("SELECT * FROM skill_revisions WHERE skill_id = ? ORDER BY revision DESC LIMIT 1",
                                (row["skill_id"],))[0]
            if latest["revision"] > row["revision"] and latest["conversion"] in {"failed", "incomplete"}:
                row = latest
        head = {"skill_id": row["skill_id"], "name": row["name"]}
        busy = self._rows("SELECT revision FROM skill_revisions WHERE skill_id = ? AND conversion = 'converting'",
                          (row["skill_id"],))
        if busy:
            if memory:  # the build already running goes into this memory too
                with self._sql() as conn:
                    conn.execute("UPDATE skill_revisions SET memory = ? WHERE skill_id = ? AND revision = ? "
                                 "AND memory IS NULL", (json.dumps(memory), row["skill_id"], busy[0]["revision"]))
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
        # a book's file name can be very long; kept under skill-sources/<sha>/ it must stay inside Windows' 260
        if src.stat().st_size > BOOK_MAX_BYTES:
            raise ValueError(f"{src.name} is over {BOOK_MAX_BYTES} bytes")
        files = [(src.stem[:60].strip() + src.suffix.lower(), src.read_bytes())]
        source_sha = _sha_of([(src.suffix.lower(), files[0][1])])  # the book's contents, whatever the file is called
        title = (name or src.stem).strip()
        built = self._rows("SELECT skill_id, revision, name, framework, units FROM skill_revisions WHERE source_sha = ? AND "
                           "conversion = 'completed' ORDER BY revision DESC", (source_sha,))
        built = [row for row in built if not _framework_problems(json.loads(row["framework"] or "{}"), json.loads(row["units"]))]
        if built:  # the same book, whatever its file is called: built once, here at once
            return {**{k: built[0][k] for k in ("skill_id", "revision", "name")},
                    "kind": "burnskill", "status": "ready", "unchanged": True}
        nxt = self._next(title, source_sha, False)
        if isinstance(nxt, dict):
            previous = self._skill(nxt["skill_id"], nxt["revision"])
            if (previous["conversion"] in {"failed", "incomplete"}
                    or previous["conversion"] == "completed"
                    and _framework_problems(json.loads(previous["framework"] or "{}"), json.loads(previous["units"]))):
                return {**self.make_burnskill(nxt["skill_id"], model, memory, source_revision=nxt["revision"]),
                        "kind": "burnskill"}
            return nxt
        inventory: dict[str, Any] = {}
        pages = book_pages(src, source_bytes=files[0][1], inventory=inventory)
        units = chunk_pages(pages)
        if not units:
            raise ValueError(f"{src.name} holds no text to read (a scanned book needs OCR first)")
        meta = {"book": src.name, "book_text_only": True, "book_visual_content_processed": False,
                "book_pages": [{"label": label, "has_text": bool(text)} for label, text in pages]}
        if "publisher_toc" in inventory:
            meta["publisher_toc"] = inventory["publisher_toc"]
            toc_orders: dict[str, list[int]] = {}
            for entry in inventory["publisher_toc"]["entries"]:
                for label in entry["source_labels"]:
                    toc_orders.setdefault(label, []).append(entry["order"])
            for page in meta["book_pages"]:
                orders = toc_orders.get(page["label"], [])
                if orders:
                    page["toc_entry_orders"] = orders
        self._insert(*nxt, title, units, source_sha, self._keep(source_sha, files), model, meta,
                     [], [], None, memory=memory)
        self._jobs.put(nxt)
        return {"skill_id": nxt[0], "revision": nxt[1], "name": title, "kind": "burnskill",
                "status": "converting", "passages": len(units)}

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
        # Every answer is kept under the source's digest: a build cut off by a restart or a usage limit,
        # a rebuild, or the same book imported again pays only for the requests that changed.
        frameworks.CACHE.set(str(self.cache / row["source_sha"]))
        usage: dict[str, float] = {}
        frameworks.STATS.set(usage)

        def progress(text: str) -> None:
            with self._sql() as conn:
                conn.execute("UPDATE skill_revisions SET progress = ? WHERE skill_id = ? AND revision = ?",
                             (text, skill_id, revision))

        units = json.loads(row["units"])
        if sum(map(len, units)) > frameworks.WINDOW_CHARS and max(map(len, units)) > 4000:
            # a long text in a few big blocks becomes 500-word passages, so it can be built part by part
            units = chunk_pages([("", "\n".join(units))])
            with self._sql() as conn:
                conn.execute("UPDATE skill_revisions SET units = ? WHERE skill_id = ? AND revision = ?",
                             (json.dumps(units), skill_id, revision))
        frameworks.check_credit(units)
        embedder = self.embedder
        similar = ((lambda texts: [v for i in range(0, len(texts), 64) for v in self._vectors(embedder, texts[i:i + 64])])
                   if embedder is not None and getattr(embedder, "name", "") != "local-hashing" else None)
        fw = frameworks.build(row["name"], units, progress, similar, book=bool(json.loads(row["meta"]).get("book")))
        fw["usage"] = usage
        fw, problems = _verified_framework(fw, units)
        if problems:
            # Keep the draft and its diagnostics reviewable without displacing
            # the last usable revision or publishing unapproved memory nodes.
            with self._sql() as conn:
                conn.execute(
                    "UPDATE skill_revisions SET framework = ?, conversion = 'incomplete', "
                    "progress = 'needs review', error = ?, state = 'draft' WHERE skill_id = ? AND revision = ?",
                    (json.dumps(fw), "; ".join(problems), skill_id, revision),
                )
            return
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
        self._trim_cache()
        self._embed_now(skill_id, revision)

    def _trim_cache(self) -> None:
        """The answer cache stays under CACHE_MAX_BYTES: the books built longest ago go first."""
        folders = sorted((p for p in self.cache.glob("*") if p.is_dir()), key=lambda p: p.stat().st_mtime)
        sizes = {p: sum(f.stat().st_size for f in p.glob("*")) for p in folders}
        total = sum(sizes.values())
        for p in folders[:-1]:  # never the one just built
            if total <= CACHE_MAX_BYTES:
                break
            shutil.rmtree(p, ignore_errors=True)
            total -= sizes[p]

    # ------------------------------------------------------------------ memory

    def unread_passages(self) -> list[dict[str, Any]]:
        """Books whose passages are not in the user's memory yet: they go in at once, before the
        framework is built, so the whole book can be recalled from the moment it is imported."""
        return self._rows("SELECT * FROM skill_revisions WHERE memory IS NOT NULL AND json_extract(meta, '$.book') "
                          "IS NOT NULL AND json_extract(memory, '$.passages') IS NULL")

    @staticmethod
    def passage_texts(row: dict[str, Any]) -> list[str]:
        return [f"{row['name']} (book passage {i}): {text}" for i, text in enumerate(json.loads(row["units"]), 1)]

    def passages_read(self, skill_id: str, revision: int, cids: list[str]) -> None:
        with self._sql() as conn:
            conn.execute("UPDATE skill_revisions SET memory = json_set(memory, '$.passages', json(?)) "
                         "WHERE skill_id = ? AND revision = ?", (json.dumps(cids), skill_id, revision))

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
        return [m for m in old if m.get("cids") or m.get("passages")]

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
        fw, problems = _verified_framework(fw, units)
        skill = payload["skill"]
        source_sha = _sha_of(files)
        nxt = self._next(skill["name"], source_sha, False)
        if isinstance(nxt, dict):
            return nxt
        load = lambda v: json.loads(v) if isinstance(v, str) else v  # noqa: E731
        self._insert(*nxt, skill["name"], units, source_sha, self._keep(source_sha, files), skill.get("model", ""),
                     load(skill.get("meta") or {}), load(skill.get("needs") or []), load(skill.get("attachments") or []),
                     fw, state="draft" if problems else "active", conversion="incomplete" if problems else "completed",
                     applicability=skill.get("applicability", ""), memory=memory)
        if problems:
            with self._sql() as conn:
                conn.execute("UPDATE skill_revisions SET progress = 'needs review', error = ? "
                             "WHERE skill_id = ? AND revision = ?", ("; ".join(problems), *nxt))
        return {"skill_id": nxt[0], "revision": nxt[1], "name": skill["name"], "kind": "burnskill",
                "status": "incomplete" if problems else "ready"}

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
        meta = json.loads(row["meta"])
        return {
            "skill_id": row["skill_id"], "revision": row["revision"], "name": row["name"], "state": row["state"],
            "kind": "burnskill" if row["framework"] else "skill",
            "conversion": row["conversion"], "progress": row["progress"], "error": row["error"],
            "nodes": len(fw.get("nodes") or []), "edges": len(fw.get("edges") or []),
            "coverage": {"complete": (fw.get("coverage") or {}).get("complete", False),
                         "unresolved": (fw.get("coverage") or {}).get("unresolved", [])} if fw else None,
            "source_coverage": fw.get("coverage"), "chapter_manifest": fw.get("chapter_manifest", []),
            "source_inventory": meta.get("book_pages", []), "text_only": meta.get("book_text_only"),
            "visual_content_processed": meta.get("book_visual_content_processed"),
            "publisher_toc": meta.get("publisher_toc"),
            "mechanical_audit_passed": (fw.get("mechanical") or {}).get("passed"),
            "judgment_findings": ((fw.get("judgment") or {}).get("findings") or [])[:5],
            "usage": fw.get("usage"),  # calls, seconds, tokens in / cached / out, cost, answers from the cache
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
        if section == "coverage":
            status = self.status(row["skill_id"], row["revision"])
            return {**head, **{key: status[key] for key in ("conversion", "state", "error", "source_coverage",
                                                          "chapter_manifest", "source_inventory", "text_only",
                                                          "visual_content_processed", "publisher_toc")}}
        if not row["framework"] and row["conversion"] != "completed" and attachment is None and node_id is None and section != "source":
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
                raise ValueError("section is one of document, source, graph, coverage, " + ", ".join(s + "s" for s in SECTIONS))
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
        fw, units = json.loads(row["framework"]), json.loads(row["units"])
        numbers = node_ids = None
        if sum(map(len, units)) + len(fw.get("document") or "") > 80_000:
            # a whole book is too long for one answer: the passages and nodes the question is about, in full
            from mnemosyne.passages import PassageIndex

            words = " ".join(w for w in re.findall(r"\w+", question.lower()) if w not in STOPWORDS)

            def best(texts: list[str], budget: int) -> list[int]:
                scores = PassageIndex(tuple(texts)).scores(words) if words else {}
                picked, used = [], 0
                for i in sorted(scores, key=lambda i: -scores[i]):
                    if used + len(texts[i]) > budget:
                        break
                    picked.append(i)
                    used += len(texts[i])
                return sorted(picked)

            numbers = [i + 1 for i in best(units, 40_000)]
            node_ids = best([f"{n['title']} {n['content']} {json.dumps(n['fields'])}" for n in fw["nodes"]], 40_000)
        answer = frameworks.ask(fw, units, question, numbers, node_ids)
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
        if state == "active" and row["framework"]:
            problems = _framework_problems(json.loads(row["framework"]), json.loads(row["units"]))
            if problems:
                raise ValueError("framework needs review: " + "; ".join(problems))
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
                shutil.rmtree(self.cache / sha, ignore_errors=True)
        return {"forgotten": row["skill_id"], "name": row["name"], "revisions": len(rows),
                "memory": [m for m in memory if m.get("cids") or m.get("passages")]}

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
