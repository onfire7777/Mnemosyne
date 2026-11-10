# Codex host

The host binds authenticated local calls to the package's memory and learning
runtime. `runtime_template.py` is installed as `runtime.py`; keeping a template
name avoids shadowing runtime fixtures when running isolated integration checks.
Credentials and model configuration remain in the destination's `reader.json`
and `retrieval_config.py`, outside the repository.

Update a configured installation with:

```sh
.venv/bin/python integrations/codex/install.py --backup /private/path/to/new-backup
```

The installer atomically replaces each script and writes content hashes into the
backup directory. Stop the maintenance LaunchAgent during deployment and start
it afterward. Existing stdio processes must reconnect to load package changes.
The hook command stays unchanged, so existing command trust entries are retained.

`hook.py` runs lifecycle handling in a bounded child process. Prompt recall gets
8 seconds, followed by a 2.8-second local-only attempt if needed. Local fallback
uses the same custody checks and does not mix replacement vectors into the
persistent embedding index. Fresh MCP `prepare_context`, `search` and `deep_search` calls use the same provider/local deadlines. Session state uses short per-session locks; storage
transactions protect memory writes. No provider call holds the global host lock.

Foreground retrieval scores retained vectors instead of embedding every missing
document during a read. Maintenance repairs missing source vectors with the
configured provider. The authenticated single-owner host shares its existing
query cache between wiki lookup and retrieval; private page/source embeddings
bypass that cache. Delivery markers record the mode, duration and outcome of
each provider/local attempt. A provider failure is never labeled a provider success.

The only injected memory string is `prepare_context._context_text`. Its UTF-8
byte length is a conservative token upper bound, including the instruction-
authority statement, reporting information and every memory section. Structured
API fields retain diagnostics for admitted items; clients should not serialize
the entire API response into the prompt. Atomic claims are omitted rather than
cut mid-negation or qualifier. Overflow is explicit.

The immutable receipt records preparation. A separate marker, written only
after the hook response is flushed, records return. Completion capture does not
associate an unreturned receipt with a turn. `MemoryUse` is explicit acknowledgement
and application reporting, never a success grade. External checks must identify
the exact receipt, used target and checker call. Hosts that supply a current
`available_tools` array enable matching capabilities; absent manifests remain
unknown, and historical tool calls do not become current capability claims.

Use `--report-use` with `used_items` for actually used ordinary memories or
knowledge pages, and `used_lessons` for lessons. Usage alone earns no reward.
Structured verifier evidence retains its original claims and exact target.
The `--report-capabilities` route accepts an explicit current tool manifest,
bound to `session_id`, `turn_id` and `receipt_id`, and returns refreshed context.
Report capabilities before using memory; the new receipt replaces the old one.

Completed authenticated turns mirror their existing direct-user sources into session working memory with the original one-hour expiry and stable IDs.

`worker.py` recovers completed turns, advances source-grounded learning reviews,
updates automatic topic pages, and refreshes maintained answers. Its nonblocking
singleton lock prevents overlapping maintenance without blocking foreground
hooks. The knowledge checkpoint retains identifiers and hashes, not source prose.

Backfill is explicit and previewable:

```sh
python /path/to/deployed/backfill.py --dry-run --limit 20
python /path/to/deployed/backfill.py --apply --limit 20
```

Use the returned `next_cursor` for the next batch. Only eligible direct-user
sources are reprojected. Source text is never rewritten; imported historical
records never become fresh user assertions. No backfill creates a task outcome,
changes an acceptance threshold, or sends a reminder.
