# Book answer grounding and CI repairs — 2026-10-26

Baseline: `97091695ccd90330e8300804524bd5b2d3043c7a`.
Exact tested source: [source-sha256.json](source-sha256.json).

## Corrected behavior

Book Q&A searches full original chapter contributions, including fields absent
from the first canonical node. Each selected record travels with all its cited
source passages. Packing uses the actual serialized records, source labels,
separators, question and request overhead. It preserves complete selected records
within the bounded context and continues past oversized candidates.

The response reports which source units and original views were selected, why
other material was omitted, and whether the context is partial. Full-document
mode explicitly distinguishes a rendered document from original JSON records.
Partial-context abstention no longer repeats a claim that the entire book lacks
an answer. An empty matching context requires no provider call.

Successful answers require strict response types, nonempty text, and unique
positive integer citations limited to the source actually supplied. Invalid
responses return an abstention and a diagnostic, not a coerced successful answer.

Two ancestor CI failures also led to corrections:

- PostgreSQL's role validator now recognizes the existing `documents` cascade
  permission. The regression checks the actual SQL grants; no permission changed.
- The native runtime releases admission after inference and before publishing
  completion. A following request can enter immediately; timed-out work still
  holds admission until it really finishes. Panic and error paths are covered.

See [CI investigation and native evidence](../ci-2026-10-26/RUNTIME-REPORT.md).

## Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Book/framework/answer/CLI wait and role regression suite | 262 passed, no failures/skips | [JUnit](regression.xml), [log](regression.log) |
| Native crate, cached dependencies, `onnx` feature | 51 passed, 2 ignored, no failures | [Log](../ci-2026-10-26/answering-ort-tests.log) |
| Restricted live PostgreSQL roles | 9 checks passed | [JSON](../ci-2026-10-26/pg-role-default-live.json) |
| Ruff, Clippy with warnings denied, formatting, whitespace | Passed | Native command/log details in the CI report |

The two ignored native tests require ONNX fixtures and were not executed. Native
tests used synthetic session implementations; there were no provider calls or
full benchmarks. Local success does not assert that GitHub's complete CI matrix
has finished successfully.

The first combined Python run had 260 passes and one failed rename test. Its
fixture rebuilt an EPUB rather than copying it: ZIP timestamps crossed a
two-second boundary, producing different input bytes with identical members.
Both stored revisions were valid. The test now copies the original bytes under
the new filename; runtime identity rules remain unchanged. The original failed
run is retained as [initial-regression.log](initial-regression.log).

Reproduce the final Python suite using the existing workspace runtime:

```sh
.venv/bin/python - <<'PY'
import sys, pytest
sys.path.append('/Users/admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages')
raise SystemExit(pytest.main([
    'tests/test_skill_frameworks.py', 'tests/test_book_framework_integrity.py',
    'tests/test_book_import_integrity.py', 'tests/test_book_cli_wait.py',
    'tests/test_book_ask_integrity.py', 'tests/test_book_answer_context.py',
    'tests/test_postgres_role_check.py', '--tb=short',
]))
PY
```

The extra path supplies the already-installed PDF parser. The tests use real
lexical scoring and deterministic transport doubles, not an external model.

## Remaining limits

Valid citations establish source availability, not semantic support for every
claim. Lexical selection can miss relevant passages; partial context is exposed
rather than presented as exhaustive understanding. No comparative rank, real-model
quality improvement, or speedup was measured. The broad memory-quality goal and
historical benchmark acceptance remain open.
