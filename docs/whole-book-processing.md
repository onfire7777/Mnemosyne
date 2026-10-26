# Whole-book processing

Mnemosyne turns a book's extracted text into a source-linked BurnSkill framework.
It retains the original file, processes numbered source units, and reports audit and
coverage results. This is a way to account for the text and review its interpretation;
it does not guarantee that every concept, implication, or nuance was extracted.
The portable file remains [BurnSkill version 2](BURNSKILL.md).

## Import and follow the conversion

For a CLI conversion, use `--wait` to keep its worker alive until the attempt
finishes:

```sh
mneme framework-import --path "/absolute/path/to/book.epub" --model "codex:default" --wait
```

Progress is written to stderr and the final status is emitted as JSON. A failed
or incomplete conversion exits nonzero. Without `--wait`, import remains queued
and nonblocking; use a persistent application or MCP server to keep background
workers running. Restarting a process against the same skill store requeues
revisions still marked `converting`.

For example, call the MCP tool `framework_import` with:

```json
{
  "path": "/absolute/path/to/book.epub",
  "model": "codex:default"
}
```

`codex:<model>` uses the installed Codex CLI and its existing login; `codex:default`
uses the CLI's default model. OpenRouter model names require provider configuration.
The default conversion path for Codex uses `codex exec`; the persistent app-server
path remains opt-in with `MNEMOSYNE_CODEX_SERVER=1`. Provider availability, account
limits, and charges depend on the selected service and account.

Keep the returned `skill_id` and `revision`. Use `framework_status` with both fields
to follow that exact attempt. A new import can return `status: "converting"` before
its framework is usable; a previously completed identical book can return
`status: "ready", unchanged: true` even when its filename changed.

| Conversion state | Meaning |
| --- | --- |
| `converting` | Background work is still pending or running; inspect `progress`. |
| `completed` | Conversion passed its activation checks. Review the framework before relying on its interpretation. |
| `incomplete` | A framework and diagnostics were retained, but approval, coverage, mechanical checks, or usable output are missing. It remains a draft. |
| `failed` | An exception stopped conversion. Inspect `error`; do not treat the attempt as completed. |

The equivalent inspection commands are:

```sh
mneme framework-status --skill-id SKILL_ID --revision REVISION
mneme skill-get --skill-id SKILL_ID --revision REVISION --section coverage
mneme skill-get --skill-id SKILL_ID --revision REVISION --section source --offset 0 --limit 20000
mneme skill-get --skill-id SKILL_ID --revision REVISION --node-id NODE_ID
```

Text views are paginated. Continue from `offset` until `more` is false; a first page
is not the whole source or document. A node view includes its cited source units.
Keep the same configured store for import, status, and inspection.

## What is read

The input-file limit is 200,000,000 bytes. An EPUB's total declared uncompressed
size must also fit that limit. PDFs require `pypdf` and an extractable text layer.
The preserved file and the parsed text come from the same input-byte snapshot.

- **EPUB:** XML text is read in package spine order, respecting XML encodings and
  mixed inline text. Archive-relative paths are resolved inside the EPUB. Missing,
  malformed, or empty spine items fail the import. An image's supplied alternative
  text may be retained; the image itself is not interpreted. `[ch.N]` means spine
  item N, not a promise of semantic chapter detection.
  An EPUB3 navigation document or EPUB2 NCX also supplies a `publisher_toc`
  inventory: entry titles, order, hierarchy, source targets, and unresolved links.
  EPUB3 navigation is preferred, with NCX as a fallback. The inventory reports
  `spine-only` when no publisher TOC is declared and `publisher-toc-unreadable` when
  a declared TOC cannot be read. Unresolved file or fragment targets and TOC errors
  remain visible without failing an otherwise complete text import. Publisher
  entries and model-inferred chapter ranges remain separately inspectable; a TOC
  link is not proof that its text was understood.
- **PDF:** text is extracted page by page. Empty content streams are recorded as
  blank locations. Pages with content but no readable text, or extraction errors,
  stop import with the affected page numbers. Apply OCR or repair the text layer
  outside this importer, then import the corrected file. PDF outline extraction is
  not implemented.
- **Passages:** each has at most 500 content words and 4,000 characters including
  labels. Small PDF fragments can share a passage within those limits while their
  page labels remain present. Different EPUB spine items cannot share a passage.
  Whitespace is normalized; unusually long tokens can be split to respect the
  character bound. The original file remains the exact-byte source of record.

Neither successful import nor passage coverage establishes visual completeness,
correct reading order for complex PDF layouts, or exhaustive semantic extraction.

## How the framework is built

1. **Plan bounded source ranges.** Every imported book is mapped, including a short
   book fitting one 60,000-character window. Up to three independent windows are
   mapped concurrently and merged in source order, retaining global
   unit numbers, chapter ranges, terminology, procedure order, links, and window
   overviews in `book_map`. Windows never split a unit. The map is model-generated;
   its chapter titles and reference classifications need review.
2. **Account for every range.** A mapped range needs both `first_unit` and
   `last_unit`. Gaps, invalid ranges, and overlapping claims cannot silently remove
   units: unclaimed or ambiguously claimed units are processed as content. A title
   such as "Notes" alone does not make a range reference matter. Explicit reference
   ranges remain in the source and coverage; if the map classifies the entire book
   as reference, all ranges are processed as content instead.
3. **Build the content parts.** Oversized chapter ranges are divided into parts of
   at most 60,000 source characters. Up to three parts run concurrently. Each gets
   its own source units and a relevant map excerpt capped at 12,000 characters.
   `omitted_context_entries` records map entries omitted from that excerpt; the
   full map and source units remain retained.
4. **Extract and check each part.** The builder extracts typed nodes, relationships,
   definitive fields, source quotations, and epistemic tags. Independent field and
   structure work runs concurrently. Logic, mechanical, and judgment audits inspect
   the result. Unresolved units or a judgment requesting further extraction can
   trigger a second pass. Missing, ungrounded, or oversized quotations trigger
   targeted field repair even when the judgment does not request more extraction.
   There are at most two passes; unresolved findings remain visible afterward.
5. **Join without discarding chapter contributions.** Repeated canonical sections,
   definitions, steps, and principles can become one joined node. Its
   `contributions` retain the original node records, including chapter-specific
   content, fields, quotations, tags, and citations. The document renders the
   separate contributions when several nodes were joined. Final relationships use
   joined node IDs; references inside a contribution retain that part's original
   numbering. Relationship contributions retain each chapter's explanation, too.
   Unicode titles are preserved when identifying shared concepts. Name-based joins
   still require review for distinct concepts sharing a name.
6. **Audit the combined result.** The joined graph receives a cross-chapter logic
   audit and another mechanical audit. When its full audit input exceeds 150,000
   characters, the logic audit uses bounded views of every original node
   contribution, preserving that contribution's full fields and content. Every
   relationship rationale is reviewed with recorded views of both endpoints.
   A frequently repeated concept or relationship can therefore span many bounded
   requests without losing its chapter-specific evidence. Chapter failures remain
   part of the final outcome. An exception in one content part retains the other
   part results and records that range as incomplete; it does not certify the whole
   book.

Mechanical checks verify quotations and core sentences for every substantive node,
including examples and case studies, against the cited
source units after whitespace normalization. A quotation longer than 60 words is
preserved and flagged, rather than silently shortened. These checks establish text
matching, not that a quotation supports every interpretation attached to it.

Approval requires nonempty nodes, complete source-unit accounting, a passing
mechanical audit, no unresolved graph or logic issues, and no outstanding request
for re-extraction. Activation also requires a usable document. Advisory warnings
and reported repairs remain available even when these conditions pass.

The bounded audit records `logic.audit_scope`: mode, character limit, node and
contribution IDs in each batch, reviewed and total node/edge contributions,
relationship endpoint views, completion, and a limitation statement. It does not
compare every possible variant pair or unrelated statement pair across batches.
Structural findings from these global
batches remain open for targeted repair; no unbounded repair request is sent.
The rendered document includes a "Whole-book audit scope" summary with reviewed
node, relationship, and contribution counts and the comparison limitation.

## Read the inventories and completion evidence

`framework_status` and `skill_get(section="coverage")` expose:

| Field | What to inspect |
| --- | --- |
| `source_inventory` | Original page/spine labels with `has_text`; includes blank PDF locations that produce no text passage. EPUB records also associate matching TOC entry orders. |
| `publisher_toc` | EPUB publisher entries, hierarchy and resolved source labels; unresolved targets and absent TOCs remain explicit. |
| `text_only`, `visual_content_processed` | For imported books, `true` and `false` respectively. |
| `source_coverage.units` | One status per numbered unit: `represented`, `duplicate`, `reference`, or `unresolved`. |
| `source_coverage.reference_units` | Units intentionally retained as reference matter rather than built as content. Check their classification. |
| `source_coverage.complete`, `content_complete` | No unresolved units; neither field proves every idea was extracted. |
| `chapter_manifest` | `title`, `first_unit`, `last_unit`, explicit `units`, `kind`, `part`, `complete`, `status`, and `failures` for each processed range. |
| `conversion`, `state`, `error` | Whether the revision is usable and what blocked it. |

The compact `coverage` field on status remains available for existing callers.
Coverage and chapter records appear when a framework result has been saved; while
conversion is running they can be absent or empty. Use `progress` on status to
follow the current stage. An incomplete saved framework remains readable through
`skill_get`, including its document and node details, but cannot be activated,
exported, or used with `skill_ask` as a completed BurnSkill.

A `represented` unit is cited by at least one nonempty, non-section node.
`duplicate` means its stored text exactly matches an earlier accounted text unit.
Differences in capitalization or whitespace do not qualify. Book extraction itself
normalizes whitespace, while the original file retains the exact source bytes.
A `reference` range is retained without content extraction.
The manifest therefore makes omissions and classifications reviewable; it is not
a semantic completeness score or a guaranteed table of the book's named chapters.

## Resource limits and efficient retries

The window and concurrency limits above are implementation limits, not CLI tuning
flags. Reuse one imported revision and inspect its progress before starting another
conversion. Completed identical requests are cached by their model and full
request payload under the source digest. This can reduce repeated work after an
interruption; a changed model, prompt, or source can require new calls. The local
answer cache has a 500 MB target and removes older source caches first, retaining
the latest build even if that leaves the target exceeded. No measured speedup or
fixed completion time is claimed.

Bounds can prevent completion even after text import succeeds:

- A direct framework input containing one unit over 60,000 characters is rejected
  with an instruction to split it. Book import already creates smaller passages.
- Combined source, instructions, and generated context over 250,000 characters
  cause that provider request to fail before dispatch.
- The bounded global audit cannot truncate an individual contribution or a required
  evidence-and-endpoint group to fit its 150,000-character batch limit. Such
  indivisible oversized groups remain flagged as unreviewed
  and block approval. Provider failure during the global audit also leaves the
  saved chapter work incomplete. Retrying unchanged input does not remove a size
  limit.

These are character bounds rather than token guarantees. A provider can impose
smaller limits or fail for other reasons. Inspect the saved error and affected
ranges; a partial result should remain a draft until its outstanding checks can
be completed.

## Review and reuse

### Ask questions with inspectable context

`skill_ask` uses the full document and source when they fit its context budget.
For larger books, it searches both source passages and the full original chapter
contributions. A selected contribution includes all its cited source passages;
oversized candidates are skipped so smaller useful matches can still be included.
Selected records are preserved in full, with an 80,000-character context budget
that is further reduced when needed to honor the complete request limit.

The answer includes `context`: its mode, `partial` flag, selected source unit
numbers and character budget. `framework_representation` distinguishes the full
rendered document from selected original records. Selected-context mode also
reports contribution view IDs, total/selected/omitted counts and omission reasons;
full-document mode does not claim to have supplied every original JSON field.
A partial-context abstention
means that no supported answer was established from those selected passages. It
does not establish that the answer is absent from the rest of the book.

A successful answer must contain text and cite valid integer source-unit numbers
that were actually supplied. Invalid response types, duplicate citations, or
citations outside that context produce an abstention with
`diagnostic.code: "invalid_answer_response"`. These checks validate the response
structure and citation availability; they do not prove that a cited passage
semantically supports every claim. No provider request is made when no matching
source passage fits the selected context.

Read the reported source coverage, unresolved units, audit findings, and source
quotations alongside the framework. Check that chapter-specific conditions,
exceptions, examples, and disagreements remain represented. Coverage means source
units were accounted for; even complete coverage can coexist with an inaccurate
interpretation that needs human review.

An incomplete attempt does not replace the previous active revision. Inspect its
specific revision and error before retrying through `skill_make_burnskill` (CLI:
`mneme skill-make-burnskill --skill-id SKILL_ID --model codex:default --wait`). Retrying
targets the newest intended source, even when an older revision is still active.
It reuses identical cached requests where available; changing the model or prompt can
require new calls. Correcting the source requires importing the corrected file.

Once a revision is completed, export and validate its portable file:

```sh
mneme skill-export --skill-id SKILL_ID --revision REVISION --path book.burnskill
mneme skill-validate --path book.burnskill
```

Format validation is not an independent review of all the book's ideas. When a
tenant memory destination is supplied at import, source passages can enter memory
before conversion finishes; availability for retrieval does not mean the framework
has been approved. Failed or incomplete generated frameworks are not published as
completed framework nodes.

Import and activation do not trust saved `approved`, coverage, or mechanical flags.
They validate structure and source references and recompute unit coverage and
quotation checks on a defensive copy. Stored node fields and graph edges must not
need repair, and the saved document must match deterministic rendering of the
verified framework, ignoring leading and trailing whitespace. A mismatch keeps
the original imported artifact inspectable as an incomplete draft; verification
does not silently rewrite it into an active skill. These deterministic checks
still cannot independently establish that a saved model review was sound or every
interpretation is correct.
