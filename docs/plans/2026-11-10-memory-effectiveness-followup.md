# Memory effectiveness follow-up

This change addresses the five functional gaps found after `cee67c6b`. It does
not claim a competitive result against Anthropic or substitute synthetic
outcomes for the personal memory store's actual experience.

## Implemented paths

1. **Attribution and utility.** Codex retains structured verifier claims and
   accepts explicit, receipt-bound usage of ordinary memories as well as lessons.
   Usage is separate from the independent result. Source custody and delivered
   item identity are rechecked; randomized positive and negative evidence can
   respectively increase and decrease utility under the same sample gates.
2. **Conversation and commitments.** Scoped cross-turn references retain all
   required source spans. Quoted entity names survive extraction. Ordinary
   completed actions close matching commitments; named dates, relative periods,
   noon and midnight preserve their calendar/timezone meaning. Erasing any
   required antecedent retracts the dependent fact and graph edge.
3. **Useful bounded retrieval.** Context selection rejects conversational
   overlap without topical relevance and respects reranker score semantics.
   Foreground reads do not re-embed the corpus. Background indexing preserves
   configured model identity and source policy; provider/local attempts have
   distinct timing and failure records. Query work is shared inside each facade.
4. **Knowledge and experiments.** Maintained pages contain cited proposition
   overviews and support content, inverse-relation and semantic lookup. Ordinary
   successful/failed tool histories generate bounded predictive experiments;
   held-out outcomes remain hidden during proposal. Completed historical reviews
   expose real-task verification requests and eligible procedures enter normal
   candidate gates.
5. **Transfer.** Reusable procedures have explicit entity-variable applicability
   inferred from independently verified operations on distinct entities. Entity,
   constraint, risk, tool and workspace requirements are validated against the
   retained episodes. Literal task identities and per-task outcomes stay separate.

## Evidence boundaries

Historical trace prediction is not causal proof of task improvement. Replay
does not create live credits or bypass protected regressions/probation. Missing
current tool manifests remain unknown; a bound capabilities report can supply
them. Dates or references that are still ambiguous remain unresolved.

Focused behavioral and integration checks cover the changed paths, including
negative utility, rejected self-grades, concurrent indexing, source erasure,
delivery budgets and live host wiring. The full suite and broad benchmark are
intentionally excluded from this implementation pass.

The live rollout backs up the SQLite stores and host scripts, installs the
versioned host, reprojects eligible existing direct sources without rewriting
their evidence, and runs maintenance. Empty training eligibility remains empty;
no demonstration data is inserted into personal memory to make counters rise.

## Verified local rollout

- 398 focused checks passed; one live PostgreSQL check was skipped because no
  DSN was configured. The full suite and broad benchmark were not run.
- The built wheel matches the final Python sources. Its isolated SQLite smoke
  check retained a fact across turns and completed a natural-language commitment.
- All 24 eligible retained direct-user sources were previewed and reprojected.
  They contained no additional supported facts; zero assertions were invented.
- A fresh MCP connection reported the v6 transfer implementation, 22 active
  components, no guard failures and no open defects. Provider-backed search
  returned in 2.025 seconds in that observed call.
- The current chat's explicit capability refresh returned a 2,464-byte context
  in 7.589 seconds without fallback. The persisted return marker contains the
  actual provider attempt; acknowledgement/use are still separate events.
- The restarted maintenance worker completed recovery, learning review, indexing
  and knowledge maintenance without errors. Its first indexing batch repaired
  16 missing vectors; the bounded follow-up repaired the remaining 35. Final
  eligible backlog: zero, with no indexing errors.

Existing long-lived Codex MCP connections retain their imported Python modules
until reconnected. The installed hooks, worker and freshly opened MCP connection
use the update. Automated access to Codex's connection controls is unavailable,
so an already-open chat needs its Mnemosyne connection reconnected to update
in-process MCP operations as well.
