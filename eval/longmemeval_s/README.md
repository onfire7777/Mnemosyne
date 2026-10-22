# LongMemEval-S development evaluation

This runner ingests each question's source conversations into a fresh Mnemosyne
instance, retrieves context, and makes separate reader and judge calls. It is an
internal development evaluation. It neither connects to Mnemetric nor changes
any external leaderboard.

Download `longmemeval_s_cleaned.json` and `longmemeval_oracle.json` from the
[upstream dataset](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
into an explicit local directory, for example `_scratch/longmemeval/`. Retain
the dataset revision and hashes. The oracle is used for scoring coverage; its
answer labels are not included in the reader's context.

## Use an existing Codex login

With Codex CLI already installed and authenticated:

```sh
uv run --locked python -m eval.longmemeval_s.run_bench_LongMemEval \
  --data _scratch/longmemeval/longmemeval_s_cleaned.json \
  --out-dir work/longmemeval-codex \
  --run development-smoke \
  --inference-provider codex --mode passages --context sessions \
  --top-k 10 --split dev --limit 5 --workers 2
```

Specify `--codex-model` and `--codex-reasoning-effort` to record an explicit
choice supported by your Codex installation. With no model argument, the
isolated CLI runtime chooses its default; this runner ignores user config.
Codex performs inference through the signed-in account. This does not require
an OpenRouter API key, but consumes Codex account quota and is not offline
inference. Monetary cost and generation token caps are not measured or enforced.

Reader and judge calls run in separate ephemeral sessions, with tools, browser,
MCP, plugins, memory and host skill discovery disabled. Each call starts a fresh
session with its benchmark prompt and no prior conversation; normal Codex runtime
and policy instructions remain. The judge also sees the reference answer. Tool activity, invalid
structured output, failed turns and ambiguous judge verdicts fail the attempt.
Provider identity, prompt hashes, token usage when available, and elapsed time
are retained. Requested model names are not presented as resolved identities
unless the CLI explicitly reports them.

Remove `--limit` and use a new `--run` to evaluate all 100 frozen development
questions, including abstention cases. The development split is the 100 lowest
SHA-256 question-ID hashes; the other 400 questions are held out. Freeze changes
before running `--split heldout`. Do not tune against held-out answers.

## Retrieval without model calls

```sh
uv run --locked python -m eval.longmemeval_recall \
  --data _scratch/longmemeval --split dev --modes default,passages \
  --out work/longmemeval-recall.json
```

This measures source retrieval, not generated-answer accuracy. Abstention rows
remain in the frozen split but are excluded from retrieval-only scoring and
listed in the report. Conversation dates and the question clock use UTC.

The answer runner also supports `--dry-run` for `default` and `passages` modes.
It builds prompts without calling a model. `dense` plus `--dry-run` is rejected
because generating missing vectors requires a model call. Codex mode supports
`default` and `passages`; it does not silently invoke a separate embedding
provider. The existing OpenRouter path remains available through
`--inference-provider openrouter` with its separately configured key and budget.

## Receipts and limitations

Codex runs write a manifest binding source and dependency hashes, Python runtime,
dataset hashes, selected question IDs and configuration. Resume requires an
identical manifest. A different split, limit, model or code revision needs a new
run name. Completed predictions go to `.jsonl`, failures to `.failures.jsonl`,
and only a complete, failure-free run receives a `.summary.json`. Failed runs
retain their evidence and cannot silently retry into a favorable aggregate.

Accuracy reports use a Wilson 95% interval, including for all-correct or
all-incorrect samples. Small development samples establish functionality, not
superiority. This runner uses the official grading prompt with the chosen judge;
different readers, judges, ingestion methods or context budgets do not establish
a controlled comparison with Hindsight's published score. Production `reflect`
also has a stricter citation protocol than this free-text benchmark reader; this
evaluation does not measure that feature.
