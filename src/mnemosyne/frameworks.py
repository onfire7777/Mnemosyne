"""Proper Thinking's framework method, in one module.

A source (a skill's text, split into numbered units) becomes a framework the way Proper
Thinking AI builds one: typed nodes (definition, principle, step, warning, constraint, case,
example) with their definitive fields and epistemic tags, typed relations checked against
its edge taxonomy, a logic audit, purpose / audience / claimed and evidenced scope / overview,
a nine-section definitive document, a mechanical audit with repairs, and a judgment audit that
can send it back for another extraction. Prompts follow Proper Thinking's; the passes it ran
one per node type, per batch and per repair are folded into a few calls, sent side by side.

One rule is Mnemosyne's own: nothing in a source may be dropped. Every unit is cited by a node,
recorded as a duplicate, or listed unresolved - and an unresolved unit drives another pass.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
import urllib.request
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
MAX_PASSES = 2
FIELD_BATCH = 6
GAP = "Not specified in the source."
#: Seconds a call may take beyond the time its length needs before it is asked again alongside.
PATIENCE = 30.0
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


def chat_json(system: str, user: str, max_tokens: int = 8192, task: str = "") -> dict[str, Any]:
    """One OpenRouter chat completion answered in JSON; an empty or unreadable answer is asked again once."""
    key = (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": 0,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})

    def post() -> dict[str, Any]:
        request = urllib.request.Request(OPENROUTER_URL, data=body.encode("utf-8"), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))

    # A provider now and then sits on a request for two minutes. When one has not answered well past
    # the time its length needs, the same request goes again and the first answer wins.
    patience = PATIENCE + max_tokens / 256
    for attempt in range(2):
        started = time.monotonic()
        first = _CALLS.submit(post)
        done, _ = wait([first], timeout=patience)
        racers = [first] if done else [first, _CALLS.submit(post)]
        if not done:
            log.info("framework call %s: no answer after %.0f s, asking again alongside", task, patience)
        done, _ = wait(racers, return_when=FIRST_COMPLETED)
        data = next(iter(done)).result()
        if data.get("error"):
            raise RuntimeError(f"OpenRouter error: {data['error']}")
        usage = data.get("usage") or {}
        log.info("framework call %s on %s: %.1f s, %s tokens in, %s out", task, model,
                 time.monotonic() - started, usage.get("prompt_tokens"), usage.get("completion_tokens"))
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        try:
            parsed = json.loads(fenced.group(1) if fenced else content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        log.warning("framework call %s: no JSON in the answer (attempt %s)", task, attempt + 1)
    return {}


def _int(value: Any) -> int | None:
    """An index the model gave, as a number or as a string of digits."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.strip().isdigit() else None


def _parallel(calls: list[Callable[[], Any]]) -> list[Any]:
    """Run the calls side by side, each in a copy of this thread's context (the model)."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(contextvars.copy_context().run, c) for c in calls]
        return [f.result() for f in futures]


def _units_block(units: list[str]) -> str:
    return "\n\n".join(f"[Unit {i}]\n{u}" for i, u in enumerate(units, 1))


def _nodes_block(nodes: list[dict[str, Any]], chars: int = 260) -> str:
    return "\n".join(f"[{n['id']}] {n['type']}: {n['title']} - {' '.join(n['content'].split())[:chars]}"
                      for n in nodes)


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
    "one node - represent all of the source, not a summary of it."
)


def extract(name: str, units: list[str], instructions: str = "") -> list[dict[str, Any]]:
    extra = f"\n\nRE-EXTRACTION (mandatory; still use only the units):\n{instructions}" if instructions else ""
    data = chat_json(EXTRACT_SYSTEM, f"Framework name: {name}\n\nSource ({len(units)} units):\n"
                     f"{_units_block(units)}{extra}\n\nOutput the JSON nodes array.", 32000, "extract")
    raw = data.get("nodes") if isinstance(data.get("nodes"), list) else []
    nodes = []
    for i, item in enumerate(r for r in raw if isinstance(r, dict)):
        ntype = str(item.get("type") or "section").strip().lower()
        nodes.append({
            "id": i, "type": ntype if ntype in NODE_TYPES else "section",
            "title": str(item.get("title") or f"Item {i + 1}").strip()[:120],
            "content": str(item.get("content") or "").strip(),
            "parent": _int(item.get("parent")), "depends_on": _int(item.get("depends_on")),
            "units": sorted({u for u in map(_int, item.get("units") or []) if u and 0 < u <= len(units)}),
            "fields": {},
        })
    for n in nodes:  # an index that points nowhere is no link
        for key in ("parent", "depends_on"):
            if not (isinstance(n[key], int) and 0 <= n[key] < len(nodes) and n[key] != n["id"]):
                n[key] = None
    if not nodes:
        raise ValueError("the model returned no framework nodes")
    return nodes


def fill_fields(nodes: list[dict[str, Any]], units: list[str]) -> list[Callable[[], None]]:
    """The definitive-fields calls, one per batch of nodes, to run side by side with the others."""
    def related(n: dict[str, Any], kind: tuple[str, ...]) -> list[str]:
        return [m["title"] for m in nodes if m["depends_on"] == n["id"] and m["type"] in kind]

    items = []
    for n in nodes:
        if n["type"] == "section":
            continue
        dep = nodes[n["depends_on"]] if n["depends_on"] is not None else None
        item = {"index": n["id"], "type": n["type"], "title": n["title"], "content": n["content"],
                "source": " ".join(units[u - 1] for u in n["units"])[:1500],
                "depends_on": f"{dep['type']}: {dep['title']}" if dep else ""}
        if n["type"] == "step":
            item |= {"warnings": related(n, ("warning",)), "constraints": related(n, ("constraint",)),
                     "cases": related(n, ("case", "example"))}
        if n["type"] == "definition":
            item["other_definitions"] = [m["title"] for m in nodes if m["type"] == "definition" and m is not n]
        items.append(item)

    def batch(chunk: list[dict[str, Any]]) -> None:
        kinds = sorted({c["type"] for c in chunk})
        system = (
            "You write the definitive template fields of framework items. Output ONLY valid JSON: "
            '{"items": [{"index": int, "fields": {...}, "epistemic_type": "fact"|"interpretation"|"assumption", '
            '"epistemic_note": one line}]}. Use ONLY each item\'s content and source; never invent concepts. '
            "Where a rule gives an exact sentence for a field the source does not support, use it word for word; "
            f'for any other unsupported field write "{GAP}". Fields and rules per type:\n'
            + "\n".join(f"- {k}: {FIELDS[k]}\n  Rules: {RULES[k]}" for k in kinds)
            + ("\nEvery definition, principle, step, warning and constraint also has \"Source Quote\": "
               '{"Quote": at most 60 words from the source, "Core Sentence": its most evidential sentence}, '
               '"ES", "EC", "CT", "CN" and "Tag justifications". ' + TAGS if _TAGGED & set(kinds) else "")
        )
        data = chat_json(system, f"Items:\n{json.dumps(chunk, ensure_ascii=False)}", 8192, "fields")
        for out in data.get("items") or []:
            idx = _int(out.get("index")) if isinstance(out, dict) else None
            if idx is not None and 0 <= idx < len(nodes):
                if isinstance(out.get("fields"), dict):
                    nodes[idx]["fields"] = out["fields"]
                if out.get("epistemic_type") in ("fact", "interpretation", "assumption"):
                    nodes[idx]["epistemic_type"] = out["epistemic_type"]
                    nodes[idx]["epistemic_note"] = str(out.get("epistemic_note") or "")[:200]

    return [lambda c=items[i:i + FIELD_BATCH]: batch(c) for i in range(0, len(items), FIELD_BATCH)]


def repair_fields(nodes: list[dict[str, Any]], units: list[str]) -> list[Callable[[], None]]:
    """Proper Thinking's tag and quote repair passes, only for the items that need one: a tagged item
    with missing ES/EC/CT/CN or no Source Quote although it cites source. Empty when nothing failed."""
    weak = [n for n in nodes if n["type"] in _TAGGED and n["units"] and (
        not all(n["fields"].get(t) for t in ("ES", "EC", "CT", "CN"))
        or not (n["fields"].get("Source Quote") or {}).get("Quote"))]

    def batch(chunk: list[dict[str, Any]]) -> None:
        items = [{"index": n["id"], "type": n["type"], "title": n["title"], "content": n["content"],
                  "source": " ".join(units[u - 1] for u in n["units"])[:1500]} for n in chunk]
        system = ("These framework items lack their evidence tags or quote. Output ONLY valid JSON: {\"items\": "
                  "[{\"index\": int, \"Source Quote\": {\"Quote\": at most 60 words copied from the source, "
                  "\"Core Sentence\": its most evidential sentence}, \"ES\", \"EC\", \"CT\", \"CN\", "
                  "\"Tag justifications\"}]}. " + TAGS + " Never use gap wording for tags; pick the closest label.")
        data = chat_json(system, f"Items:\n{json.dumps(items, ensure_ascii=False)}", 4096, "repair")
        for out in data.get("items") or []:
            idx = _int(out.get("index")) if isinstance(out, dict) else None
            if idx is not None and 0 <= idx < len(nodes):
                for key in ("Source Quote", "ES", "EC", "CT", "CN", "Tag justifications"):
                    if out.get(key) and not nodes[idx]["fields"].get(key):
                        nodes[idx]["fields"][key] = out[key]

    return [lambda c=weak[i:i + FIELD_BATCH]: batch(c) for i in range(0, len(weak), FIELD_BATCH)]


EDGES_SYSTEM = (
    "You map the relations of a framework and audit its logic. Output ONLY valid JSON: {\"edges\": "
    "[{\"from\": id, \"to\": id, \"type\": ..., \"why\": one sentence}], \"graph_issues\": [str], "
    "\"logic_issues\": [str], \"logic_warnings\": [str], \"note\": str}.\nEdge types: supports (case/example "
    "-> step or principle), implemented_by (principle -> step only), leads_to (earlier step -> later step), "
    "uses_definition (step or principle -> definition), constrains (constraint -> step), warns (warning -> "
    "step), feeds_back_to (last step of a cycle -> first step), refined_into (case/definition -> principle), "
    "exposes_problem_in (case -> what it shows failing), drives_step (principle -> step), tension (two "
    "warnings/constraints that are opposite failure modes; why names the balance to hold). Make the full "
    "step order explicit; link each step to the definitions it uses and the warnings and constraints on it. "
    "Only the given ids; omit what you are unsure of. Then audit: logic_issues are serious contradictions, "
    "gaps, unstated assumptions or undefined terms; logic_warnings are minor; graph_issues are structural "
    "problems that edges alone cannot fix. Use [] when none."
)


def relate(nodes: list[dict[str, Any]], out: dict[str, Any]) -> None:
    data = chat_json(EDGES_SYSTEM, f"Framework nodes:\n{_nodes_block(nodes)}", 8192, "edges")
    out["edges"] = data.get("edges") if isinstance(data.get("edges"), list) else []
    out["logic"] = {k: [str(x) for x in data.get(k) or []] for k in ("graph_issues", "logic_issues", "logic_warnings")}
    out["logic"]["note"] = str(data.get("note") or "")
    # Proper Thinking's graph repair: the audit's own structural findings are fixed once, then re-audited.
    if out["logic"]["graph_issues"]:
        current = "\n".join(f"{e.get('from')} -[{e.get('type')}]-> {e.get('to')}" for e in out["edges"] if isinstance(e, dict))
        fix = chat_json(EDGES_SYSTEM, f"Framework nodes:\n{_nodes_block(nodes)}\n\nCurrent relations:\n{current}\n\n"
                        f"Fix these graph issues and return the complete corrected relations and audit:\n"
                        + "\n".join(out["logic"]["graph_issues"]), 8192, "graph-repair")
        if isinstance(fix.get("edges"), list) and fix["edges"]:
            out["edges"] = fix["edges"]
            out["logic"] = {k: [str(x) for x in fix.get(k) or []] for k in ("graph_issues", "logic_issues", "logic_warnings")}
            out["logic"]["note"] = str(fix.get("note") or "")


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


def describe(name: str, nodes: list[dict[str, Any]], out: dict[str, Any], units: list[str] = ()) -> None:
    # The source itself goes along, as Proper Thinking's scope pass read book excerpts: evidenced scope
    # must rest on what the source shows, not only on the extracted titles.
    source = _units_block(list(units))[:16000]
    data = chat_json(META_SYSTEM, f"Framework name: {name}\n\n{_nodes_block(nodes, 400)}\n\nSOURCE:\n{source}",
                     4096, "meta")
    keys = ("purpose", "assumptions_limits", "target_audience", "claimed_scope", "evidenced_scope",
            "problem", "core_argument", "method")
    out["meta"] = {k: str(data.get(k) or "Not stated in source").strip()[:1500] for k in keys}
    # None when the model gave no list: the caller then falls back to looking for the words.
    effects = data.get("effects")
    out["meta"]["effects"] = [e for e in EFFECTS if e in effects] if isinstance(effects, list) else None


JUDGE_SYSTEM = (
    "You are the Judgment Auditor of a framework built from a source. Decide whether it warrants a new "
    "extraction pass. Consider coverage of the source's central ideas, proportionality (peripheral items "
    "outweighing core ones), whether ES/EC/CT/CN fit the quoted evidence, redundant warning/constraint pairs, "
    "and whether a reader could carry out the steps on a new case from the framework alone. Output ONLY "
    "valid JSON: {\"warrants_reextract\": bool, \"extractor_instructions\": concrete source-grounded "
    "instructions or \"\", \"findings\": [str]}."
)


def judge(fw: dict[str, Any]) -> dict[str, Any]:
    edges = "\n".join(f"{e['from']} -[{e['type']}]-> {e['to']}" for e in fw["edges"])
    user = (f"{_nodes_block(fw['nodes'], 400)}\n\nRelations:\n{edges}\n\nLogic audit: "
            f"{json.dumps(fw['logic'])}\n\nUnits no node cites: {fw['coverage']['unresolved'] or 'none'}")
    data = chat_json(JUDGE_SYSTEM, user, 4096, "judge")
    instructions = str(data.get("extractor_instructions") or "").strip()
    return {"warrants_reextract": bool(data.get("warrants_reextract")) and len(instructions) >= 24,
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


def coverage(units: list[str], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Every unit is represented, a duplicate of an earlier one, or unresolved (its text stays kept)."""
    cited: dict[int, list[str]] = {}
    for n in nodes:
        for u in n["units"]:
            cited.setdefault(u, []).append(n["title"])
    seen: dict[str, int] = {}
    rows = []
    for i, text in enumerate(units, 1):
        key = " ".join(text.split()).lower()
        if i in cited:
            rows.append({"unit": i, "status": "represented", "nodes": cited[i]})
        elif key in seen:
            rows.append({"unit": i, "status": "duplicate", "of": seen[key]})
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
    tensions = fw["logic"]["logic_issues"] + fw["logic"]["logic_warnings"]
    out += ["## 9. Scope and Limits", "", "### 9A Scope conditions",
            f"Claimed: {meta['claimed_scope']}", "", f"Evidenced: {meta['evidenced_scope']}", "",
            "### 9B Methodological limits", meta["assumptions_limits"], "", "### 9C Acknowledged gaps",
            *([f"- {g}" for g in gaps] or ["None."]), "", "### 9D Internal tensions",
            *([f"- {t}" for t in tensions] or ["None found."]), ""]
    return "\n".join(out)


# ---------------------------------------------------------------------------------- build


def build(name: str, units: list[str], progress: Callable[[str], None] = lambda _: None) -> dict[str, Any]:
    """A complete framework for one source, Proper Thinking's loop included: extract, relate and
    judge, and extract again when the judgment or coverage asks for it (at most MAX_PASSES).

    The fields and the overview of a pass that is re-extracted would be thrown away, so they are
    written only for the pass that is kept: after a judgment that asks for nothing more, or beside
    the relations and judgment of the last allowed pass. Every result kept is one Proper Thinking's
    order would have produced; none is made only to be discarded."""
    instructions = ""
    model = MODEL.get() or os.getenv("MNEMOSYNE_FRAMEWORK_MODEL") or DEFAULT_MODEL
    for passes in range(1, MAX_PASSES + 1):
        progress(f"pass {passes}: extracting")
        nodes = extract(name, units, instructions)
        side: dict[str, Any] = {}

        def structure(nodes: list[dict[str, Any]] = nodes, side: dict[str, Any] = side) -> None:
            relate(nodes, side)
            side["fw"] = {"name": name, "model": model, "passes": passes, "nodes": nodes,
                          "edges": tidy_edges(nodes, side["edges"]), "logic": side["logic"],
                          "coverage": coverage(units, nodes)}
            side["fw"]["judgment"] = judge(side["fw"])

        def detail(nodes: list[dict[str, Any]] = nodes, side: dict[str, Any] = side) -> list[Callable[[], None]]:
            return fill_fields(nodes, units) + [lambda: describe(name, nodes, side, units)]

        last = passes == MAX_PASSES
        progress(f"pass {passes}: relations and judgment" + (", fields and overview" if last else ""))
        _parallel([structure] + (detail() if last else []))
        fw = side["fw"]
        missing = fw["coverage"]["unresolved"]
        if not last and (missing or fw["judgment"]["warrants_reextract"]):
            instructions = fw["judgment"]["extractor_instructions"]
            if missing:
                instructions += (f"\nCOVERAGE: units {missing} are not represented by any node. Represent "
                                 "every one of them, keeping everything already represented.")
            continue
        if not last:
            progress(f"pass {passes}: fields and overview")
            _parallel(detail())
        break
    weak = repair_fields(fw["nodes"], units)
    if weak:
        progress("repairing tags and quotes")
        _parallel(weak)
    fw["meta"] = side["meta"]
    fw["generated"] = datetime.now(UTC).isoformat(timespec="seconds")
    fw["approved"] = not fw["logic"]["logic_issues"]  # Proper Thinking's governor: reported, never blocking
    fw["mechanical"] = mechanical_audit(fw)
    fw["document"] = render(fw)
    return fw


def ask(fw: dict[str, Any], units: list[str], question: str) -> dict[str, Any]:
    """Proper Thinking's framework Q&A: answered from the framework and its source only."""
    system = ("You answer questions about one framework using ONLY its definitive document and source units. "
              "If they do not answer it, say so. Output ONLY valid JSON: {\"answer\": str, \"units\": [cited unit "
              "numbers], \"answered\": bool}.")
    user = f"{fw.get('document', '')[:40000]}\n\nSOURCE UNITS:\n{_units_block(units)[:40000]}\n\nQUESTION: {question}"
    data = chat_json(system, user, 4096, "ask")
    return {"answer": str(data.get("answer") or "No answer."), "units": data.get("units") or [],
            "answered": bool(data.get("answered"))}
