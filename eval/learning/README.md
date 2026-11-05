# Learning mechanics and agent benchmark

`probes.py` contains executable environments for all 26 preregistered families. Each uses the production `LearningRuntime`, its engine, receipts, episodes, and native state. Source fixtures and successful tool demonstrations enter through public interfaces. A missing prerequisite (for example, no active procedure after training) produces an unsupported result with its reason; it never produces a synthetic zero or a passing status.

Run a small development diagnostic:

```sh
PYTHONPATH=src .venv/bin/python -m eval.learning.runner --split dev --families 2 7 23 --arms learning_on memory_frozen no_memory --episodes 64 --output /tmp/learning.json
```

Omit `--families` and `--arms` to run all families, five preregistered seeds, and all 28 arms. Local, SQLite, and PostgreSQL engine factories are available via `--backend`; PostgreSQL requires an explicitly supplied `--postgres-dsn` and uses that database. A development or incomplete report exits with status 1 unless all report gates pass. This is not a claim of production performance.

## Executable environments

| Families | Operations and independent observations |
| --- | --- |
| F1–F3 | Source-backed lexical/graph retrieval; ordered tool demonstrations and novel procedure executions; format corrections and held-out JSON decisions. |
| F4–F6 | Incumbent training followed by misleading partial-task demonstrations and observed revision trials; source erasure and forged feedback; old-fact recall before and after interference and 30 virtual days. |
| F7–F9 | Delayed external outcomes with premature-credit checks; changed procedure order and observed recovery; interleaved similar tasks compared with isolated-task tenants. |
| F10–F12 | Quoted schema import and consistent/inconsistent demonstrations; spaced procedure tests through 30 days; irrelevant evidence with exogenous reward and actual served/withheld sample requirements. |
| F13–F15 | Failure streak followed by a solvable environment; balanced positive/negative posterior updates and calibration; an observed fast-path serve followed by changed goals. |
| F16–F18 | Thanks-only feedback and promotion counts; repeated consolidation without new evidence; actual one-shot correction followed by out-of-scope requests. |
| F19–F21 | Retirement training and old-context renewal; untrusted misinformation and original evidence comparison; concrete corrections followed by abstract-rule evaluation on new examples. |
| F22–F24 | Five independently trained procedure classes and transfer to new endings against a separate tenant with chunking disabled; repeated retrieval with source, rank, standing, authority and confidence snapshots; immutable prior predictions and unlucky-outcome observations. |
| F25–F26 | Source-backed imports differing only in popularity, with actual selection observations and a prespecified exact test; source-quoted schema nodes and novel self-generated content with matched standing observations. |

The symbolic executor compares the actually selected ordered operations with a private environment contract. Actual actions are captured as tool events. The training verifier may reveal corrective steps after failures; held-out cases never reveal corrective steps. Successful demonstration setup is separately marked and excluded from task-success metrics. `ScriptedAgent` has a fixed policy, exploration probability 0.1, and no learning cache. It follows surfaced steps, composable chunk prefixes, simple explicit format instructions, or source text; all learned state lives in Mnemosyne.

The clock fixture advances learning and Python engine clocks together. It does not rewrite a PostgreSQL server clock. Thirty simulated days are a mechanics test, not a longitudinal production observation.

## Optional model agent

The model track is opt-in and uses the existing JSON command transport. Supply an explicit command adapter that accepts the JSON request on stdin and returns `{"action":"...", "used_skills":[], "used_lessons":[]}`. The adapter can use an existing authenticated provider; no external request happens unless this command is selected.

```sh
PYTHONPATH=src .venv/bin/python -m eval.learning.runner --split dev --families 2 --arms learning_on memory_frozen no_memory --episodes 64 --agent-command-json '["/absolute/path/to/model-adapter"]' --model explicit-model-id --temperature 0 --output /tmp/learning-model.json
```

The fixed system prompt hash, model, temperature, preregistered seed, command and request hashes are recorded. The model receives only the public query, permitted choices, task class, and surfaced memory. It never receives the private expected action. Reported use of an unserved artifact is rejected. A requested seed is not evidence that a provider is deterministic. Tests exercise this transport with a local process; they make no external model calls.

## Evidence and limitations

Raw rows and operations accompany every result. Paired AULC bootstrap intervals require the same seeds and aligned query/expected-action/phase workloads. Non-benefit ablations use the explicit mechanism endpoint and direction registered in the manifest, requiring supported matching-budget probes for every seed. Missing metrics or unequal workloads become `missing_comparisons`. They are not silently treated as failures, zero scores, or positive lift. `passed` additionally requires all families/arms, supported family verifiers, and the preregistered comparison gates. Unsupported mechanism ablations are explicit in the manifest.

The manifest preserves hashed development/sealed seed splits. Sealed execution requires a clean commit and creates an exclusive, durable reservation before running; a failed run consumes that SHA. Use a shared reservation directory across machines. These controls prevent repeat execution through the runner; they do not make the publicly readable fixture templates an independently authored unseen corpus. The existing quality-gate corpus has been used in tuning and remains marked development-contaminated.

`tests/test_learning_specialized_families.py` executes every family, checks held-out separation, verifies a real read-strengthening fault, and feeds all 26 tests-only guard mutations through the actual writer and independent zero-defect acceptance gate. These guard tests establish detection/containment for those mutations; they do not establish family-specific positive learning, a model-agent win, or complete semantic fault sensitivity for every environment. Advanced probes can remain unsupported until their real training prerequisites emerge. Review reasons and raw operations rather than counting implemented functions as passed experiments.
