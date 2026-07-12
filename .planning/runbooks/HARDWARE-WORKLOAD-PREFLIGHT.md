# Hardware Workload Preflight

Status: mandatory for hardware-intensive local work

## Approved topology

- Host: Apple Silicon, 16 GiB unified memory, 10 logical CPUs.
- Colima: 6 CPUs, 12 GiB memory, production compose stack.
- Host Ollama: one model at a time; no in-VM Ollama during host-model work.

This runbook applies before model pulls/loads, full test suites, benchmarks,
index rebuilds, exact-scale evals, protected captures, and VM resizing. A failed
gate means wait and recheck; it is not permission to raise a timeout or run in
parallel.

## Admission check

Take three samples 15 seconds apart. Every sample must pass:

```sh
memory_pressure -Q
uptime
ollama ps
colima list
docker ps --format '{{.Names}} {{.Status}}'
```

- Host memory-free percentage: at least 55% before model or protected work.
- Host one-minute load: at most 7.0; five-minute load: at most 8.0.
- VM-only workload equivalent: one-minute at most 4.2 and five-minute at most
  4.8 for its six allocated CPUs.
- No model resident before a new model-admission probe.
- No concurrent pull, model request, index, full suite, benchmark, or evidence
  capture.
- Colima must remain at 6 CPU / 12 GiB. Protected work additionally requires
  the expected service count with no restarting or unhealthy service.

Targeted unit tests may run below the model/protected thresholds only when
memory-free is at least 35%, host one-minute load is at most 10, no model is
resident, and the test is serialized.

## Model admission

- Reject downloadable artifacts larger than 6.2 GB under this topology.
- Set `OLLAMA_NUM_PARALLEL=1`; one request and one model only.
- After warmup, require exactly one `ollama ps` row, resident size no more than
  7.0 GiB, `PROCESSOR` at 100% GPU, and context no more than 8192 unless the
  preregistered protocol requires more.
- Re-sample memory three times; every post-load sample must remain at least 35%.
- Measure swapout delta over 60 seconds. More than 64 MiB, any page throttling,
  CPU offload, or a second loaded model rejects the model.

Artifact size is only an admission ceiling. Actual residency, memory pressure,
GPU placement, context, and swap delta decide whether the model is viable.

## Full-scale and protected eval

- Run one eval process, one question, and one model request at a time.
- Before the 24-question development-scale wrapper, recheck memory-free at
  least 35%, five-minute host load at most 8.0, and swapout delta at most
  64 MiB over 60 seconds.
- Abort the development run if memory-free falls below 25%, one-minute host
  load exceeds 10 for two samples, swapout grows more than 256 MiB in any
  five-minute window, CPU offload appears, or another model/process starts.
- A protected attempt requires a passing exact-scale receipt followed by a
  fresh 60-second idle admission check. Never overlap it with CI reproduction,
  indexing, tests, model pulls, or evidence capture.

## VM changes

Stopping or resizing Colima reseals production Vault and invalidates in-flight
capture. Confirm no capture is active before the change. Afterward, restore the
approved topology, manually unseal Vault with operator-held material, and prove
all expected services healthy before resuming evidence work. Never place
unseal material in commands, logs, environment snapshots, or the repository.

## Evidence record

For every model or exact-scale attempt, record the three preflight samples,
artifact and resident sizes, GPU/context placement, swap deltas, concurrency,
and final admission decision in the internal evaluation report. A rejected
preflight does not create a protected ledger entry.
