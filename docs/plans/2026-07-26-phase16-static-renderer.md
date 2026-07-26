# Phase 16 L2 Static Leaderboard Renderer Plan

> Execute one GOAL.md task per RalphEx iteration. Use Ponytail and strict TDD,
> keep the exact lease, and do not turn synthetic renderer checks into
> publication, production, hardware, governance, or benchmark evidence.

## Goal

Render validated leaderboard result records and their already-disclosed public
bundle traces into a deterministic, self-contained static site without adding
a frontend framework, service, database, network call, or artifact schema.

## Exact Interface and Data Flow

`leaderboard.render.render_site(results, traces, destination)` accepts:

- `results`: a JSON file containing one result-v1 record or an array of records;
- `traces`: a mapping from each result `record_id` to that result's existing
  public-bundle `traces.jsonl` file;
- `destination`: the static output directory.

The result loader rejects duplicate JSON keys, non-standard/non-finite numbers,
non-object records, duplicate `record_id` values, and every record rejected by
`leaderboard.validate.validate_record`. The trace loader applies the same
fail-closed JSON parsing rules to each non-empty JSONL row, requires the
public-bundle per-question identity field `question_id`, and rejects duplicate
question IDs within a result.

The mapping is the linkage layer: it must contain exactly the validated result
IDs. A missing mapping, an extra/unlinked mapping, or a trace row without its
existing public-bundle question identity fails the whole render. The renderer
does not add fields to a trace row or define a second trace schema. It displays
only source fields that exist:

- stored context/evidence: `stored_records`;
- retrieved context/evidence: `ranked_retrieved_hits` and
  `authorized_retrieval_hops`;
- final answer: `answer`.

Records sort by `record_id`; traces sort by `question_id`; metrics sort by
`(family, name)`. Stable path components are lowercase hexadecimal SHA-256 of
the unmodified record or question ID. All values pass through HTML escaping.
Every emitted link is relative.

## Output Tree

```text
DESTINATION/
├── index.html
├── results/
│   └── <sha256(record_id)>.html
└── traces/
    └── <sha256(record_id)>/
        └── <sha256(question_id)>.html
```

`index.html` and each result page disclose system, track, benchmark/version,
publication label and publishability, operator identity/disclosure, metrics,
and the immutable run/build/config/bundle/trace-index digests. The result page
links to every trace page. Trace pages link back using relative paths and label
stored, retrieved, and final-answer evidence honestly. In particular,
`publishable: false` and `label: operator-run` render explicitly and are never
upgraded to neutral or headline-eligible language.

## Failure and Publication Semantics

Parsing, validation, linkage, duplicate detection, and complete in-memory
rendering finish before the destination changes. Files are written as UTF-8
with LF line endings into a temporary sibling directory. Publication uses
same-parent filesystem renames; when replacing an existing destination, the
old tree is retained as a sibling backup until the complete new tree is in
place and is restored if publication raises. Temporary and backup directories
are removed after success. Any pre-publication failure leaves the prior output
byte-for-byte unchanged and exposes no partial destination.

The command-line entry point uses local paths only and returns a deterministic
nonzero exit for invalid input or failed publication without a traceback.

## Acceptance Tests

`tests/test_leaderboard_render.py` uses synthetic result-v1 records and
synthetic rows shaped exactly like retained public-bundle retrieval/QA traces.
It proves:

1. one record and an array validate through the existing contract;
2. malformed, duplicate-key, non-finite, contract-invalid, and duplicate
   result input fails without output;
3. malformed, duplicate, missing-ID, missing-link, and unlinked trace input
   fails without output;
4. index/result/trace pages contain all required disclosures and immutable
   digests, with stable relative links;
5. stored records, retrieved hits/authorized hops, and final answers render
   from their existing source fields;
6. hostile values are escaped and cannot become HTML or path traversal;
7. permuting result, trace, and mapping order produces byte-identical trees;
8. a failed replacement preserves the previous destination byte-for-byte.

## Acceptance Commands

Task 1 RED:

```sh
uv run pytest -q tests/test_leaderboard_render.py
```

Expected: collection fails because `leaderboard.render` does not exist.

Task 2 focused GREEN:

```sh
uv run pytest -q tests/test_leaderboard_render.py
uv run ruff check leaderboard/render.py tests/test_leaderboard_render.py
git diff --check
```

Task 3 full delivery gates:

```sh
set -euo pipefail
uv run --extra mcp pytest -q
uv run ruff check .
git diff --check
git diff --name-only "$(git merge-base HEAD origin/main)"..HEAD
git diff --name-only "$(git merge-base HEAD origin/main)"..HEAD |
  while IFS= read -r path; do
    case "$path" in
      GOAL.md|leaderboard/render.py|tests/test_leaderboard_render.py|docs/plans/2026-07-26-phase16-static-renderer.md) ;;
      *) echo "out-of-lease path: $path" >&2; exit 1 ;;
    esac
  done
status=0
rg -n -i '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|password\s*[:=]|api[_-]?key\s*[:=]|secret\s*[:=])' \
  GOAL.md leaderboard/render.py tests/test_leaderboard_render.py \
  docs/plans/2026-07-26-phase16-static-renderer.md || status=$?
test "$status" -eq 1
```

The changed-file set must remain a subset of `GOAL.md`,
`leaderboard/render.py`, `tests/test_leaderboard_render.py`, and this plan.
Before commit, inspect the complete diff and scan the leased files for
secret-like material, private keys, credentials, oversized files, generated
artifacts, and unintended lockfile churn.

## Execution Evidence

- RED: the original focused suite failed during collection because
  `leaderboard.render` did not exist (`e193e7e9`).
- Initial GREEN: the focused renderer suite and scoped Ruff passed in
  `cffe9ed5`.
- Review repair: 22 focused renderer tests and the 88 renderer/result-contract
  tests pass; full Ruff, `git diff --check`, exact-lease verification, and the
  leased-file secret/risky surface scan pass.
- Full-suite gate: `uv run --extra mcp pytest -q` passed unchanged in the
  supervisor-owned persistent terminal after the restricted review sandbox
  denied `/bin/ps` and loopback sockets. No tests were excluded or bypassed.
