# LongMemEval retrieval-only preregistration

This is the first current-source, full-dataset retrieval characterization in
the 2026-10-04 completion effort. It is not the comparative launch experiment
and does not replace the eight-system roster or any original Plan A/B gate.
It measures retrieval only, using the existing frozen registry and scorer.
All publication/headline flags remain false.

`preregistration.json` fixes source, inputs, settings, sample count, metrics,
stopping rules and the one-entrant roster before scoring. The detached
`preregistration.json.sig.json` signature verifies with `public.pem` using the
repository's existing Ed25519 evidence-signing mechanism. The private key is
held outside the repository and must never be included in an artifact or log.
The signature attests to the bytes, not independent operator identity.

From a checkout with the project dependencies installed:

```python
from pathlib import Path
from mnemosyne.evidence_signing import verify_evidence_manifest_signature

directory = Path("eval/registrations/2026-10-04-longmemeval-retrieval-b0cdbd89")
print(verify_evidence_manifest_signature(
    directory / "preregistration.json", directory / "public.pem"
))
```

## Execution gate

Preparing or verifying this file does not start a run. Before execution:

1. Verify this registration has a public Git commit preceding the run.
2. Use a clean checkout of the **registered harness commit**, not a newer
   registration/documentation commit. Verify the source and dependency hashes.
3. Finish the current local test workload and confirm normal memory pressure.
4. Verify exact raw and normalized dataset hashes without editing input records.
5. Claim a new external, exclusive start receipt for this experiment. No prior
   attempt may exist. Monitor the process tree and record any abort or failure.

The registered command shape in that source checkout is:

```sh
uv sync --locked --group dev
python -m mnemosyne.cli eval-public \
  --suite longmemeval-retrieval \
  --dataset-dir "$PINNED_LONGMEMEVAL_DIRECTORY" \
  --out-dir "$NEW_EXTERNAL_BUNDLE_DIRECTORY"
```

Use the checkout's `.venv/bin/python` (or `uv run --locked python`) for the
command above. The development dependency group supplies the harness's JSON
Schema validator; the base product install alone does not supply it. Record
the resolved Python and package versions before starting. The prepared local
environment uses Python 3.14.7, with all 19 installed packages recorded in the
external `source-environment.json` receipt.

The dataset directory contains only the already-verified pinned inputs and is
outside the source checkout. The output directory must be new. Paths and the
resolved Python executable are recorded in the start receipt; they are not
free parameters for changing the experiment. Use the registered resource
monitor and stopping rules around this command. Do not rerun a failed subset
or change settings after seeing results.

Retain the terminal outcome, process logs, produced bundle if any, and a signed
ledger outcome. A run that cannot start needs a reasoned `no_run` record. A
successful run still requires bundle verification and exact reproduction;
neither result permits a QA, superiority, independent-reproduction or public
launch claim. Later comparative work needs its own complete registration.

## Outer resource guard

`eval/public/monitor.py` is an outer process guard, separate from the registered
scoring source. Invoke its reviewed copy with the registered checkout as the
working directory and that checkout's Python as the target executable:

```sh
python /path/to/reviewed/eval/public/monitor.py \
  --cwd "$PINNED_SOURCE_CHECKOUT" \
  --output-dir "$NEW_MONITOR_ATTEMPT_DIRECTORY" \
  --wall-seconds 3600 -- \
  "$PINNED_SOURCE_CHECKOUT/.venv/bin/python" -m mnemosyne.cli eval-public \
  --suite longmemeval-retrieval \
  --dataset-dir "$PINNED_LONGMEMEVAL_DIRECTORY" \
  --out-dir "$NEW_EXTERNAL_BUNDLE_DIRECTORY"
```

Record the guard's source commit and file hash in the signed execution receipt.
The monitor must not be copied into the registered checkout or change its
source. It samples macOS pressure once per second, refuses non-normal or
unreadable pressure, and terminates the target's process group on resource
abort. It preserves stdout, stderr, pressure samples and a terminal receipt in
an exclusively created directory; an existing directory cannot be reused.
It is intended for this trusted harness, not workloads that escape process
groups. Monitor receipts are unsigned until separately signed by the operator.

A monitor status of `succeeded` means only that the command exited zero and
cleanup succeeded. It does not validate a bundle, authorize scoring before the
execution gates, supply the signed start receipt, or replace the signed outcome
ledger. Perform those steps explicitly. A hard host shutdown may leave only a
start receipt; reconcile that interrupted attempt without rerunning it.
