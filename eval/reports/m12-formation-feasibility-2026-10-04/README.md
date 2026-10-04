# Small-model formation feasibility attempt

The full 220-case development corpus was attempted once from clean source
`88a56f24c6ae95fe2fd992beef080bf0a93fd86d`, with the explicitly pinned local
Qwen3 0.6B formation role. It stopped on the first response: the model combined
a clarification question with a task write. Its proposed task also omitted
`task_id` and used the wrong trigger shape. The bridge rejected the response
before any task create/update or downstream firing. No case completed.

The model did execute locally: its raw HTTP response reported 726 input tokens,
140 output tokens and 2,144,786,292 ns total duration. The outer monitored
attempt lasted 4.062 seconds; all three sampled memory-pressure readings were
normal. One server sample reported 1,507,747,430 bytes of model size. That is
server-reported allocation, not verified peak RSS. Client process-group RSS
excludes the Ollama server. Cleanup confirmed no loaded models afterward.

This proves a small local model invocation is feasible on this machine under
these conditions. It is not a successful formation benchmark, an accuracy
estimate, proof that the full corpus fits, resource admission or a comparison
against other memory systems. No score or ranking is assigned. The existing
8B grounded-reader protocol and its earlier pressure failures are unchanged.

`manifest.json` binds the retained raw inputs, HTTP exchange, failed trace,
monitor, cleanup and launch script. Server-reported model identity is not an
independent attestation. No output was repaired or substituted. Future adapter
variants must keep this failure visible and identify their changed settings.
