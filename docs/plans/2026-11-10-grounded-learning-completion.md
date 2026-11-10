# Grounded memory and learning completion

This follow-up implements the gaps audited after `b67c2b0c`. It preserves the
distinction between source retention, verified knowledge, a task outcome, and
evidence that a memory improves future tasks.

## Implemented behavior

- **Project knowledge:** owned tool observations become source-cited assertions
  and maintained pages. Configuration, repository state, and useful command
  outcomes retain their scope, time, evidence, and independent verification
  contracts. Reviewed synthesis must be supported by retained sources; it is
  never relabeled as a direct user fact. Printed assistant-generated claims do
  not become independent observations. Maintenance retries bounded batches of
  old episodes without inventing missing evidence. Deterministic extraction
  precedes a resumable queue of at most two provider-reviewed sources per pass;
  large episodes cannot monopolize that queue. Legacy tool events use exact
  indexed source matching rather than repeated archive scans.
- **Entity continuity:** persistent source-backed entities and aliases survive
  neutral continuation turns. Cross-session references require sufficient owner
  and project context; ambiguous references remain unresolved. Renames retain
  identity and dependency custody. Richer apposition and relocation statements
  reach extraction and independent entailment review. Negation, dates, and
  attribution remain mandatory.
- **Feedback:** the Codex adapter preserves hypothesis contract hashes and
  typed experiment metadata. Applied command/fact memories can be checked
  against matching independent observations. Frozen projection fingerprints
  prevent changed or withdrawn claims receiving new credit. Diagnostic checks
  never substitute for a task outcome, and partial pages cannot receive
  whole-page verification. Existing controlled utility requirements remain.
- **Transfer:** evidence-backed operation roles recognize compatible workflows
  despite different filenames, commands, and extra inspections. Concrete
  source traces remain available. Promotion combines complete randomized
  pairs only across validated matching applicability contexts; sample,
  superiority, ownership, and protected-case requirements remain intact.
- **Experiments:** real failed pytest events can trigger a bounded, hashed
  snapshot at the current tool-completion hook. Captured failures must reproduce
  before a candidate can count as an isolated improvement. Python runs in an OS
  sandbox, and SQLite runs with restricted operations and resource limits.
  Tests and expected results are fixed between baseline and candidate. These
  results are retained as isolated experiments and still need real-task
  verification before promotion.
- **Live runtime:** newly connected MCP sessions execute operations in fresh
  processes. The host can activate an immutable wheel snapshot independently of
  the editable development checkout. Mutation timeouts are not automatically
  retried. Local `file:` workspace URLs normalize consistently across capture,
  scope, transfer, and experiments. Maintenance reads normal captured sources
  under the configured trust policy, independently of its operator authority.
  Existing processes predating this dispatcher require one reconnect.

## Validation and delivery

Focused behavior and integration checks cover these changed paths. The full
suite and broad acceptance benchmark are intentionally excluded. No synthetic
episodes, success labels, or training examples are inserted into personal
memory to improve counters. Live rollout receipts are kept outside the repo.

These changes implement broader practical memory formation and learning; they
do not establish a measured competitive advantage over Anthropic or guarantee
that every arbitrary project can be reproduced in the bounded sandbox.

### Focused validation

- 598 checks passed. One optional live PostgreSQL check was skipped because
  `MNEMOSYNE_POSTGRES_DSN` was not configured. The full suite was not run.
- Ruff and whitespace checks passed for the changed files.
- All 148 packaged Python sources matched the checkout. An isolated installed
  package converted an actual configuration read into two assertions and one
  maintained page; a sandboxed Python experiment reproduced one failure and
  passed the unchanged test after the proposed implementation repair.
- A fresh authenticated MCP session reported v7, all 22 components enabled,
  and zero guard failures. Current chat capabilities were refreshed from its
  actual available tool manifest.
