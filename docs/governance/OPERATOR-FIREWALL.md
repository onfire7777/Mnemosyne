# Operator Firewall

Version: 0.2.0
Status: active; enforced mechanically. External activation required only for the optional board upgrade

The one harness rule is non-waivable: every evaluated system uses the same
harness version, same configuration class, same budget, same access to public
data and instructions, and the same publication gates. There are no special runs,
private tuning windows, hidden retries, or vendor-only data; no vendor-authored scores
are accepted.

Where operator and product team are different people, they are separated as
people. Where they are the same person, separation is enforced **in time and
code** instead, and the personnel form is not simulated or claimed: the pipeline
is deterministic from pinned inputs, configuration is frozen at pre-registration
before any score exists, grading is programmatic wherever possible, and results
are published automatically from the append-only ledger rather than hand-picked.
The operator's only residual power is to not run something, which the ledger
makes visible as a recorded absence.

Operators They execute pinned public inputs,
retain immutable run identifiers and logs, and publish failures as well as
successes. Product teams may submit a public adapter and factual documentation;
they cannot operate, judge, redact, or choose the reported run for their own
system. Credentials and embargoed artifacts are least-privilege and auditable.

Any deviation makes the result ineligible. The board cannot waive equal
treatment, even unanimously. Suspected violations enter the public appeal log.
