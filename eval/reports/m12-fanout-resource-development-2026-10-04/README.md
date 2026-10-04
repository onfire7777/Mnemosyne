# Bounded fan-out: local resource observation

The five-seed, four-virtual-week public-CLI workload completed all 1,220
operations from clean recorded source `421a1fcd1473b4669300910483f97c155e30f310`.
Full operation/report/sink replay passed, and every recorded harness hash matched
that commit. Documentation changed after launch; the workload and measurement
code remained unchanged. Production-runtime identity is not certified.

The local deterministic backend produced 750 expected firings, no observed
false positives, misses or duplicate firings, and left all 150 unmatched-event
controls unfired. The inert sink retained 750 receipts and 1,500 attempts,
including 750 deliberate duplicate deliveries. No external action was executed.
The versioned workload increases fan-out through 2, 4, 8 and 16 actions per
explicit trigger type. This is bounded fan-out, not saturation testing.

| Observation | Measured value |
| --- | ---: |
| Monitor elapsed time, monotonic seconds | 304.7011161669798 |
| Resource samples | 292 |
| Maximum sampled process-group RSS | 92,274,688 bytes (88 MiB) |
| Maximum sampled logical file bytes | 3,913,523 bytes (about 3.73 MiB) |
| Normal macOS pressure samples | 291 of 291 |
| Physical host memory | 17,179,869,184 bytes (16 GiB) |

The host reported arm64, ten logical CPUs and macOS 26.6.2. The workload used
Python 3.14.7. These observations describe this structured-action workload on
this host; they do not establish that model-heavy QA or other workloads fit.

The monitor sampled approximately once per second and retained its raw samples,
start/terminal receipts and measurement-source hashes. Maxima were recomputed
from those samples. RSS sums processes remaining in the child's process group;
short-lived peaks and escaped descendants can be missed. It excludes the parent
monitor. Disk measurements sum logical regular-file sizes under the attempt
root, including output, monitor logs, environment metadata and temporary stores.
`TMPDIR` pointed to the root's `scratch` directory; live store paths were observed
there and recorded in `environment.json`. Caches outside the root are excluded.
Logical bytes are not allocated blocks, an enforced quota or a verified peak.
The two supplemental metadata files were added during execution and are included
in later disk samples. The final terminal receipt itself is written after sampling.

Both `peak_rss_verified` and `admission_verified` remain false. The 30-minute,
4-GiB-RSS and 1-GiB-disk planning envelope is not certified by these observations.
No latency comparison to another run or system is warranted from this capture.
Cost, implicit cases, overload semantics, reference calibration and full M12
admission remain open. This is DEVELOPMENT evidence with `publishable:false`.

## Validation

All recorded harness hashes matched source 421a1fcd. The full operation log,
per-case/per-load reports and sink annex replayed both before and after copying
into this directory. Resource maxima and sample counts were recomputed from the
retained raw samples; every pressure sample was normal. The existing retained
fan-out regression now covers this capture as well as the earlier capture.

## Replay and reproduction

Replay the complete retained workload and sink annex:

```sh
python -m eval.public.action_trigger_run eval/reports/m12-fanout-resource-development-2026-10-04 --recompute
```

To collect a new observation, use a separate, nonexistent absolute directory
and the verified Python environment. From the repository root, for example:

```sh
run_root=/absolute/path/to/new-action-resource-attempt
mkdir -p "$run_root/scratch"
TMPDIR="$run_root/scratch" python -m eval.public.monitor \
  --cwd "$PWD" --output-dir "$run_root/monitor" --wall-seconds 1800 \
  --usage-root "$run_root" -- \
  python -m eval.public.action_trigger_run "$run_root/workload" --sink --fanout
```

The monitor refuses to overwrite its output directory. A new run is a new
measurement, not byte-for-byte reproduction of timings, UUIDs or resource samples.

Original files and the sink database remain under
`/Users/admin/.local/state/mnemosyne/action-resource-runs/2026-10-04-421a1fcd-attempt2`.
The database is 524,288 bytes, SHA-256
`3ecd4cdf268d62325b3f3c8eaba1336095952a02d82c6f94690763a9804cd9e0`.
The retained annex replays without that database; this is consistency checking,
not independent authentication or reproduction.

`launch-error/` preserves the preceding attempt's argument-validation failure:
the operator supplied unsupported `--output` instead of the positional output
directory. It exited with code 2 before any workload operation. Its zero RSS
samples are not a valid workload measurement. The corrected attempt was started
only after that process was terminal, in a separate directory.
