# The BurnSkill standard, version 2

A BurnSkill is an Agent Skill turned into a complete framework: every part of what the skill
teaches becomes a typed, linked node, and each node says which part of the source it comes from.
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
| `units` | the source cut into numbered units, starting at 1. Every claim a node makes cites them. |
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

A book (PDF or EPUB) becomes one BurnSkill. In Mnemosyne v1.7.0:

1. The book is cut into passages of at most 500 words, labeled by page (`[p.12]`) or
   chapter (`[ch.3]`). All passages are retained as numbered `units`; the old
   58-passage and 68,000-character selection limits no longer apply.
2. A source that fits one processing window is built directly. For longer sources,
   one reading of the whole book maps its chapters, canonical terms, main procedure,
   relationships and overview.
3. Content chapters are built in parallel using the shared map and their own passages.
   Oversized chapters are split into parts. Each part receives nodes, relations,
   definitive fields, logic checks and a mechanical audit before the judgment auditor
   reads the completed pass. Missing coverage or judgment findings can trigger a second
   pass to repair affected items, or rebuild the part when required.
4. Chapter frameworks are joined by canonical names, including relationships across
   chapters and the main procedure. The combined framework receives another logic and
   mechanical audit and retains the chapter judgments.
5. Reference matter, such as a bibliography or index, stays in the source and is marked
   `reference` in coverage instead of becoming framework nodes. Chapters teaching ideas,
   arguments, methods or cases remain content. Coverage can also report unresolved
   passages: retaining a passage does not guarantee successful representation.
6. The original book is kept in `files`.

Conversion runs in the background and reports progress or failure. Model answers are
cached by source digest, so interrupted conversions and retries can reuse completed
requests. An already completed book is reused even if its filename changes. The cache
has a 500 MB target; older source caches are removed first, retaining the latest build.

When a memory destination is configured, the book's passages are made available to the
memory integration before framework conversion finishes. Scanned PDFs without
extractable text need OCR before import.

Conversion supports OpenRouter models and `codex:<model>` names. Codex models use an
installed Codex CLI with the user's ChatGPT login. The persistent app-server path is
opt-in through `MNEMOSYNE_CODEX_SERVER=1`; otherwise conversion uses `codex exec`.

The same framework-building approach applies to other sources too long for one
processing window.
