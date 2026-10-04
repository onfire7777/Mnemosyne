# Offline Qwen reference-tokenizer measurement

Source inspected: `4f240e3672271964dc58d336cdf7f495f4b0b0dc`.
This advances the context prerequisite for Plan A S1 and native benchmark
execution. It is not a QA result, a resource admission or a changed candidate.

The installed `qwen3:8b` was queried through **metadata-only** `api/show` with
`verbose: true`. Its 151,643 reference vocabulary entries, 26 added-token IDs
and 151,387 ordered BPE merge rules all matched
[Qwen's tokenizer at revision b968826](https://huggingface.co/Qwen/Qwen3-8B/blob/b968826d9c46dd6066d109eabc6255188de91218/tokenizer.json).
The downloaded tokenizer SHA-256 is
`aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4`.
No model weights were downloaded or loaded. `/api/ps` was empty before and
after the audit. Only the optional isolated audit environment uses
`tokenizers==0.22.1`; no production dependency changed.

## Findings and limits

The [machine-readable report](local-reader-reference-tokens-2026-10-04.json)
counts **3,989 user-message tokens and 25 system-message tokens**, separately,
with the reference tokenizer. Both prompt hashes match the earlier static
audit of the aborted synthetic probe. The input is ASCII; this diagnostic
does not generalize normalization equivalence to arbitrary Unicode.

Even the user message plus the requested 512 output tokens totals **4,501**,
before adding the system message or chat formatting. This supports rejecting
4,096 as a full-input/full-output budget for this candidate. It is consistent
with the stronger retained runtime observation: 4,035 prompt tokens in a
4,096-token window, leaving 61, with context shifting enabled.

Matching vocabulary and merges does **not** establish runtime tokenization
equivalence: pre-tokenization, normalization, special-token handling and chat
template execution still matter. The separate message counts are not the
full rendered prompt count. This audit does not prove whether the aborted
request was truncated before reaching the runner. The existing receipts are
unchanged. A future candidate still needs an explicit effective context,
full rendered-input coverage, output reservation and a successful resource
preflight. Increasing the context alone does not establish that it fits the
available RAM. No new generation was attempted.

## Reproduction

Local artifacts are retained in
`.superpowers/sdd/completion-2026-10-04/qwen-context-audit/`:
`show.json`, `tokenizer.json`, `tokenizer_config.json`, `revision.txt`, and
`prompts.json`. Upstream tokenizer files are not checked into this repository.

To recreate `prompts.json`, run this in an installed Mnemosyne environment:

```python
import json
from pathlib import Path
from mnemosyne.providers.grounded_protocol import render_prompt

ordinary = 'The archive contains ordinary records about books and shelves. '
content = ('The access code is ORCHID. ' + ordinary * 500)[:24000]
system, user = render_prompt(
    'grounded_reader', 'What is the access code?',
    [{'cid': 'hardware-preflight-synthetic', 'content': content}],
)
Path('prompts.json').write_text(
    json.dumps({'system': system, 'user': user}), encoding='utf-8',
)
```

Capture `show.json` from the installed model using
`POST /api/show` with `{"model":"qwen3:8b","verbose":true}`; this endpoint
does not generate text. Download the tokenizer from the exact revision above.
From the repository root, with those three files in the working directory:

```sh
uv run --no-project --python 3.11 --with tokenizers==0.22.1 python \
  eval/compact_answering/qwen_context_audit.py show.json tokenizer.json prompts.json
```

The audit rejects different tokenizer bytes or mismatched model token IDs /
merge rules. Six optional real-artifact tests passed locally in 1.69 seconds,
including altered vocabulary, special-token IDs, merges, tokenizer bytes and
out-of-scope Unicode. To repeat them, set
`MNEMOSYNE_QWEN_CONTEXT_ARTIFACTS` to the artifact directory and run
`tests/test_qwen_context_audit.py` with pytest and the pinned tokenizers package.
Without the artifacts, these tests explicitly skip; such a skip is not
verification of the local measurement.
