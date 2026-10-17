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
  unit, or whether it is unresolved.
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

A book (PDF or EPUB) becomes one BurnSkill, the same way Proper Thinking makes a framework of
one:

1. The book is cut into passages of at most 500 words. Each passage carries its page, such as
   `[p.12]`, or its chapter, such as `[ch.3]`.
2. Five questions pick the passages to build from: the core method, the risks, the reasoning,
   the ethics and the examples. The neighbours of each pick are added.
3. At most 58 passages and 68,000 characters are kept. Those passages are the `units`.
4. The book file itself is kept in `files`.

The same applies to any source too long for one prompt.
