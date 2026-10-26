# The BurnSkill standard, version 2

A BurnSkill is an Agent Skill represented as a structured framework: typed, linked nodes
identify the source units they cite, and coverage records show what remains unresolved.
As a file it is one `.burnskill` file that travels on its own. It is also still a skill: its top
is an ordinary `SKILL.md`, so any agent that reads Agent Skills can read it.

The reference implementation is `mnemosyne.skills`. It writes the format (`skill_export`), reads
it (`framework_import`) and checks it (`skill_validate`, or `mneme skill-validate --path <file>`).
The reference server is Mnemosyne's MCP server. It offers each active skill as an MCP prompt and
each of its files as a `skill://<skill_id>/<path>` resource.

## The file

```
---
name: weekly-update
description: "Post the weekly status update to the team channel."
---
# weekly-update
...the framework's readable document (nine sections)...

<!-- burnos-skill v2
<payload>
-->
```

1. **Front matter.** A `name`, and a `description` that is a JSON string. A file without them
   still imports, but the validator warns about it.
2. **The document.** Markdown written for people and agents. It is the same text as
   `framework.document`.
3. **The payload.** It comes last, inside an HTML comment that opens with `<!-- burnos-skill v2`.
   The payload is the JSON object below, compressed with zlib and then encoded as base64.

## The payload

| key | what it holds |
|---|---|
| `format` | always `"burnos-skill"` |
| `version` | `2`. Version 1 (Mnemosyne 1.3) still imports. |
| `skill` | `name`, `aliases`, `applicability`, `needs` (the MCP servers it needs), `attachments`, `meta` (the front matter of the original), `model` |
| `units` | the source cut into numbered units, starting at 1. Nodes cite these units as their sources; citations alone do not verify an interpretation. |
| `framework` | see below |
| `files` | the original files, as `path -> base64`. A path is relative, never absolute, and never contains `..` or a drive letter. Nothing in the files is ever executed on import. |

## The framework

- `nodes`: these are numbered `0, 1, 2 ...` in order. Each node has:
  - `type`: one of `section`, `definition`, `principle`, `step`, `warning`, `constraint`, `case`, `example`.
  - `title` and `content`.
  - `parent`: a node id, or null.
  - `depends_on`: a node id, or null.
  - `units`: the source units it cites.
  - `fields`: the definitive fields for its type.
  - `epistemic_type`.
- `edges`: each edge is `{from, to, type, why}` and joins two different nodes. `type` is one of
  `mnemosyne.frameworks.EDGE_TYPES`. Each type is drawn in one direction, the one its name reads,
  so a warning `warns` the step it guards.
- `coverage`: shows, for each unit, whether a node represents it, whether it repeats an earlier
  unit, whether it is retained reference matter, or whether it is unresolved.
- `chapter_manifest`, when present: the processed source ranges, content/reference classification,
  completion state, and failures for each part. Book builds also retain their `book_map`.
- A joined node can include `contributions`: complete original node records from the contributing
  parts, including their fields, quotations, tags, and source units. Their internal node references
  retain the original part's numbering; the joined node and `edges` use the final numbering.
- A joined edge can include `contributions` retaining the original chapter-specific
  relationship explanations. Bounded audits record their reviewed contribution and
  endpoint views in `logic.audit_scope`.
- `meta`:
  - `purpose`, `claimed_scope` and `evidenced_scope`.
  - `effects`: what running it does to the world. The values are `sends`, `deletes`, `pays`,
    `posts` and `installs`.
- `logic`, `judgment` and `mechanical`: the audits it passed or failed. The file reports them and
  never hides them.
- `document`: the readable text.

## What a reader must do

- Treat `effects` and any runnable file as **what the skill can do**, and ask the user before a
  step that does it.
- Never run a packed file on import.
- Refuse a file whose payload unpacks to more than 400 MB, or that holds a file path leaving the
  skill.
- Treat a version it does not know as an error, not a guess.

## Books

A PDF or EPUB is imported as one source and converted into one BurnSkill. The original
file is retained in `files`; extracted text is retained in numbered `units`. Passages
contain at most 500 content words and 4,000 characters including location labels.
PDF labels identify pages (`[p.12]`); EPUB labels identify reading-order spine items
(`[ch.3]`), which need not correspond one-to-one with the book's named chapters.
Separate EPUB spine items are never combined into one passage.
The book metadata also retains a publisher TOC inventory when an EPUB3 navigation
document or EPUB2 NCX is available, including unresolved links.

Import is text-only. It does not perform OCR or interpret diagrams, images, or page
layout. Missing or unreadable EPUB spine items, and nonblank PDF pages without
extractable text, fail import rather than silently producing a partial book.
PDF pages with empty content streams remain recorded as blank locations. Successful
text extraction still does not certify that a PDF library recovered every word or
that a model understood every idea.

All imported books receive chapter mapping. Long sources are processed in bounded,
concurrent parts with source coverage and audit results.
A unit recorded as represented, duplicate, or reference is **accounted for**, not proof
that every idea in that unit was extracted correctly. An incomplete conversion remains
a draft with diagnostics and does not replace the last active revision.

See [Whole-book processing](whole-book-processing.md) for the processing stages,
resource limits, progress states, review workflow, and source/chapter inventories.
These additions retain the public **version 2** payload and existing tool names;
version 1 imports remain supported. Import and activation recompute source coverage
and quotation checks rather than trusting saved approval flags. The saved document
must match the deterministic rendering of the verified framework, ignoring outer
whitespace. If verification would repair stored node fields or graph edges, the
original artifact remains a draft for review instead of being silently rewritten
and activated. An imported framework without the required approval, coverage, or
audit evidence also remains a draft; format compatibility alone does not activate it.
