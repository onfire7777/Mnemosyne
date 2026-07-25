# Credibility Model

Version: 0.2.0
Status: active for source-owned gates; External activation required only for the optional independent-board upgrade

## The problem this document solves

The v0.1.0 policy package borrowed its credibility model from HELM, MTEB, and
LMArena: an independent multi-institution board vouches that the operator did
not manipulate results. That model is correct for an organisation. It is
unreachable for a solo maintainer, because it requires seated academics, a legal
steward, durable funding, external ratification, and a multi-owner archive —
none of which a single person can produce by building software.

The consequence was not a high standard. It was a **permanently closed gate**:
Phase 16 could never open, so the roadmap terminated in a block that no amount
of engineering could clear.

This document replaces institutional trust with **mechanical verifiability**.
The standard does not drop. It changes shape.

## The substitution

Every externally-gated requirement existed to buy one thing: assurance that the
operator could not quietly favour their own system. Each is replaced by a
mechanism a solo maintainer can build and a stranger can check.

| v0.1.0 external gate | What it bought | v0.2.0 mechanism |
|---|---|---|
| Five-member board, two academics | Independent check that results were not massaged | Pre-registration + append-only signed run ledger |
| Legal steward | Institutional accountability | No institutional claim is made; outputs are an open dataset and method |
| Durable funding | Survival | Static hosting and flat files in git; running cost approaches zero |
| Multi-owner archive | Survives operator disappearance | Replication, not co-ownership: git + DOI snapshot + public archive + permissive licence |
| External ratification | Humans attest the method | Cryptographic signing of every bundle plus deterministic re-run |
| Peer-reviewed methods paper | Methodological scrutiny | Public preprint plus an open, logged review channel; not gated on acceptance |
| Mandatory third-party reproduction | Someone else got the number | Results are reproducible by construction from a pinned bundle; outside reproductions are accepted as bonus evidence, never as a gate |

**Why this is not weaker.** A board can be captured, can rubber-stamp, or can
simply never be assembled. A pre-registered split hash cannot be retroactively
changed, and an append-only ledger makes a discarded run visible. "Do not trust
me, verify" is a stronger claim than "a committee vouches for me", and it is the
only one a solo maintainer can honestly make.

## The four integrity mechanisms

### 1. Pre-registration

Before any scoring run, a signed `preregistration.json` is committed publicly
containing: harness commit, adapter versions, dataset revisions and digests,
metric definitions, the held-out split digest, the stopping rule, and the
**expected entrant roster**. Scores
produced under a configuration that does not match a prior pre-registration are
ineligible and are labelled as such.

### 2. Append-only run ledger

Every run is appended to a hash-chained, Ed25519-signed ledger — including runs
that failed, were aborted, or were discarded. Entries are never deleted, only
superseded with a stated reason. This reuses the evidence-signing and audit
hash-chain substrate already built for the v1.0 Tier-B attestation.

Cherry-picking is therefore **detectable by any third party**, which is the
property the board was there to provide.

### 3. Mechanical operator separation

A solo maintainer cannot separate operator from product team as *people*. The
separation is enforced in **time and code** instead:

- The pipeline is deterministic and runs from pinned inputs; the operator
  supplies no per-run judgement.
- Configuration is frozen at pre-registration, before any score exists.
- The grader is programmatic wherever possible; where a model judge is
  unavoidable its prompt, version, and acceptance rate on
  intentionally-wrong-but-topical answers are published.
- Result publication is automated from the ledger, not hand-curated.

The operator's remaining power is to *not run something*. A run ledger alone does
**not** close this: a system that is never run produces no entry, so silent
omission would stay invisible. It is closed by pre-registering the **expected
entrant roster** alongside the configuration, and requiring an explicit
`no_run` ledger record — with a stated reason — for every rostered system that
does not produce a result. An unexplained gap between roster and ledger is
itself a detectable violation.

Pre-registration and the ledger are necessary but not jointly sufficient: both
can pass independently while an omitted entrant leaves no trace anywhere. The
binding check is a **roster-to-ledger completeness gate** — publication is
refused unless every rostered system resolves to either a result or a reasoned
`no_run` record. It is listed as its own Register A gate rather than left
implicit in the other two.

### 4. Adversarial self-reporting

Any system the operator authors — including Mnemosyne — must publish where it
**loses**. A results page with no Mnemosyne failures is presumed to be
misconfigured or rigged until failures appear. This is a standing obligation,
not a courtesy.

## Honest labelling

Until an independent board exists, outputs are labelled:

> **Open, operator-run, fully auditable.**

They are **not** labelled "neutral" or "independent". Those terms remain
reserved for the optional board upgrade described in [CHARTER](CHARTER.md).
This is a claim that can be reached and defended by one person, and it is the
strongest claim the evidence supports.

## What is still non-waivable

The revision relaxes *who vouches*, never *what is measured or disclosed*. These
remain in force exactly as written in v0.1.0 and are enforced mechanically:

- The one-harness rule ([OPERATOR-FIREWALL](OPERATOR-FIREWALL.md)).
- The permanent Mnemosyne conflict, which disclosure cannot cure
  ([CONFLICT-OF-INTEREST](CONFLICT-OF-INTEREST.md)).
- Separate metric families, published uncertainty, ties reported as ties
  ([METHODOLOGY](METHODOLOGY.md)).
- Never silently retract; versioned corrections only
  ([CHANGE-CONTROL](CHANGE-CONTROL.md)).
- A public appeal log ([APPEALS-AND-DISPUTES](APPEALS-AND-DISPUTES.md)).

## Relationship to the optional board

Nothing here forbids seating an independent board later. If one is ever seated,
it is a strict upgrade: the label may become "neutral", and
[BOARD-STATUS](BOARD-STATUS.md) records the gates that upgrade would require.
The board is **no longer on the critical path** for building, measuring, or
publishing.
