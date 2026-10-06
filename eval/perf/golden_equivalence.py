"""Golden equivalence harness for batch consolidation and retrieval.

Runs a scenario through the PUBLIC CLI in-process (gate-case-add, capture-batch --consolidate,
forget, eval-query-batch) under a deterministic runtime, and returns one canonical dump of
everything that must not change when the engine's internals change:

* every consolidation job result - each gate decision, every pass result, the mutation rails;
* the final MAIN-branch state of every tenant - evidence, assertions, relations, entities,
  justifications, contradictions, preferences, deletion log, the audit log minus branch
  bookkeeping, and the merge log minus the replay counters;
* the eval-query-batch output for a fixed query set - hits, order, scores, abstention and
  the embedded explanation.

The runtime is deterministic and implementation independent: the clock is frozen within a
step and advances one second before every captured row, every consolidation job and the
query phase; ids are counters, and the dump relabels them in a content-sorted traversal so
two engines that create different numbers of internal ids still compare equal when the
observable state is equal.

Branch bookkeeping is excluded on purpose (approved contract, see the PR): canary branches,
the per-merge ``upsert_assertion.noop_or_reinforce`` rows and the branch/merge/discard audit
rows. Everything that decides or retrieves is compared byte for byte.

    python eval/perf/golden_equivalence.py list
    python eval/perf/golden_equivalence.py dump --scenario NAME --out FILE [--src SRC] [--data DIR]
    python eval/perf/golden_equivalence.py compare A.json B.json

``--src`` puts another checkout's ``src`` first on sys.path, so the same harness can dump the
legacy engine. HippoRAG scenarios need ``--data`` (the pinned HippoRAG 2 files).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import gc
import hashlib
import importlib
import io
import json
import pkgutil
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ID_RE = re.compile(r"^00000000-0000-4000-8000-[0-9a-f]{12}$")
BOOKKEEPING_OPS = frozenset({"upsert_assertion.noop_or_reinforce", "branch", "merge", "discard"})
MERGE_REPLAY_KEYS = frozenset({"assertions_merged", "assertion_id_map"})
REPLAY_MARK = "_golden_merge_replay"
# Keys whose values are wall-clock measurements, never state. Found by legacy self-consistency.
VOLATILE_KEYS = frozenset({"metrics", "latency_ms", "elapsed_ms", "duration_ms", "took_ms", "wall_ms"})


# --------------------------------------------------------------------------- runtime


class LogicalClock:
    def __init__(self) -> None:
        self.base = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)
        self.step = 0

    def now(self) -> _dt.datetime:
        return self.base + _dt.timedelta(seconds=self.step)

    def tick(self) -> None:
        self.step += 1


def _import_all(package: Any) -> None:
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        with contextlib.suppress(Exception):
            importlib.import_module(info.name)


@contextlib.contextmanager
def deterministic_runtime() -> Any:
    import mnemosyne

    _import_all(mnemosyne)
    clock = LogicalClock()
    real_datetime = _dt.datetime

    class FakeDateTime(real_datetime):  # type: ignore[misc, valid-type]
        @classmethod
        def now(cls, tz: Any = None) -> Any:  # type: ignore[override]
            moment = clock.now()
            return moment.replace(tzinfo=None) if tz is None else moment.astimezone(tz)

        @classmethod
        def utcnow(cls) -> Any:  # type: ignore[override]
            return clock.now().replace(tzinfo=None)

    import uuid as real_uuid

    import mnemosyne.ids as ids_module

    counter = [0]

    class CountingUuid:
        """Stands in for the uuid module inside mnemosyne.ids: new_id() - and every dataclass
        default_factory that captured it - yields 00000000-0000-4000-8000-<counter>."""

        def __getattr__(self, name: str) -> Any:
            return getattr(real_uuid, name)

        @staticmethod
        def uuid4() -> Any:
            counter[0] += 1
            return real_uuid.UUID(f"00000000-0000-4000-8000-{counter[0]:012x}")

    patched: list[tuple[Any, str, Any]] = [(ids_module, "uuid", ids_module.uuid)]
    ids_module.uuid = CountingUuid()
    for name, module in list(sys.modules.items()):
        if module is None or not any(name == p or name.startswith(p + ".") for p in ("mnemosyne", "eval")):
            continue
        if getattr(module, "datetime", None) is real_datetime:
            patched.append((module, "datetime", real_datetime))
            module.datetime = FakeDateTime

    from mnemosyne.consolidation import ConsolidationWorker
    from mnemosyne.mcp_tools import MemoryTools

    def ticking(owner: Any, attr: str) -> None:
        original = getattr(owner, attr)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            clock.tick()
            return original(*args, **kwargs)

        patched.append((owner, attr, original))
        setattr(owner, attr, wrapper)

    ticking(MemoryTools, "capture")
    ticking(ConsolidationWorker, "run_job")

    # Mark the audit rows a merge writes while REPLAYING items that were already on the target
    # branch - the legacy engine re-upserts every unchanged copy on every merge, so those rows
    # are per-merge bookkeeping (approved contract), not facts about the memory.
    from mnemosyne.engine import LocalMemoryEngine

    original_merge = LocalMemoryEngine.merge

    def marking_merge(self: Any, frm: str, into: str = "main", tenant_id: str | None = None) -> Any:
        existing = {item.id for item in dict.values(self.assertions) if item.branch == into}
        start = len(self.audit_log)
        report = original_merge(self, frm, into=into, tenant_id=tenant_id)
        for row in self.audit_log[start:]:
            if str(row.get("op", "")).startswith("upsert_assertion") and row.get("target_id") in existing:
                row[REPLAY_MARK] = True
        return report

    patched.append((LocalMemoryEngine, "merge", original_merge))
    LocalMemoryEngine.merge = marking_merge
    try:
        yield clock
    finally:
        for owner, attr, original in reversed(patched):
            setattr(owner, attr, original)


def _cli(argv: list[str]) -> Any:
    from mnemosyne import cli

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    gc.collect()  # release the engine so the next command may own the store
    if code not in (0, None):
        raise RuntimeError(f"mneme {' '.join(argv[4:6])} exited {code}")
    text = out.getvalue().strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text.splitlines()[-1])


# --------------------------------------------------------------------------- scenarios


def _gate_case_argv(store: Path, content: str) -> list[str]:
    """Exactly what eval.harness.cli_driver.MnemoCLI.install_consolidation_gate_case sends."""
    first_line = next(line.strip() for line in content.splitlines() if line.strip())
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    return ["--backend", "local", "--store", str(store), "gate-case-add",
            "--id", f"eval-consolidation-{digest}", "--signature", f"evaluation consolidation smoke {digest}",
            "--query", first_line[:160], "--expected-substring", first_line[:80], "--origin", "curated", "--protected"]


def _row(tenant: str, content: str, identity: str, source_type: str = "hipporag:golden", **extra: Any) -> dict[str, Any]:
    return {"content": content, "source_identity": identity, "source_type": source_type, "tenant": tenant,
            "user": "benchmark-corpus", **extra}


COLOURS = ["amber", "cobalt", "crimson", "jade", "violet", "ochre", "teal"]
CITIES = ["Lisbon", "Oslo", "Quito", "Hanoi", "Dakar", "Perth", "Tbilisi"]


def synthetic_growth() -> dict[str, Any]:
    """Three growing batches, conflicting facts, mixed trust tiers, a twin tenant and a forget."""
    a, b = "golden-a", "golden-b"
    batch1 = [
        _row(a, f"Entity {i}\nEntity {i} is {COLOURS[i % 7]}. Entity {i} lives in {CITIES[i % 7]}. "
                f"Entity {i} Works With Entity {(i + 1) % 14}.", f"golden:a{i:03d}")
        for i in range(14)
    ]
    # Conflicting facts: capture-batch refuses the whole batch when any candidate is rejected,
    # and that refusal (which candidates, in what words) is part of the contract too.
    conflict = [
        _row(a, f"Update {i}\nEntity {i} is {COLOURS[(i + 3) % 7]}.", f"golden:u{i:03d}", trust_tier=[0, 2, 0][i % 3])
        for i in range(0, 14, 2)
    ]
    growth = [
        _row(a, f"Entity {i}\nEntity {i} is {COLOURS[i % 7]}. Entity {i} lives in {CITIES[(i + 3) % 7]}.",
             f"golden:g{i:03d}", trust_tier=[0, 1][i % 2])
        for i in range(14, 22)
    ] + [_row(b, row["content"], row["source_identity"]) for row in batch1[:8]]
    batch3 = [
        _row(a, f"Late {i}\nEntity {i} is {COLOURS[(i + 5) % 7]}. Entity {i} lives in {CITIES[(i + 2) % 7]}.",
             f"golden:l{i:03d}")
        for i in range(22, 28)
    ] + [batch1[0], _row(a, "Note\nThe Archive is open on Mondays.", "golden:note", source_type="note")]
    # A refused batch with relation sentences - its refusal text is compared too.
    relation = [
        _row(a, f"Trip {i}\nEntity {i} Visited {CITIES[(i + 2) % 7]} In 2024. Entity {i} Met Entity {i - 20}.",
             f"golden:t{i:03d}")
        for i in range(22, 25)
    ]
    queries = [{"question_id": f"q{i}", "tenant": a, "query": q} for i, q in enumerate([
        "What colour is Entity 3?", "Where does Entity 5 live?", "Who works with Entity 7?",
        "Which city did Entity 4 visit in 2024?", "Entity 10 colour", "When is the Archive open?",
        "Entity 0", "Is Entity 12 teal or ochre?",
    ])] + [{"question_id": "qb0", "tenant": b, "query": "What colour is Entity 2?"}]
    return {"gate_content": batch1[0]["content"], "tenants": [a, b], "queries": queries,
            "steps": [{"capture": batch1}, {"capture": conflict}, {"capture": growth}, {"forget": [2, 3]},
                      {"capture": batch3}, {"capture": relation}]}


def synthetic_rails() -> dict[str, Any]:
    """Worker-level gate: supersessions under every rail rate, with full main state after each."""
    from eval.g0.write_gating import _BudgetExtractor, _append, _budget_case, _worker
    from mnemosyne.engine import LocalMemoryEngine
    from mnemosyne.models import Assertion
    from mnemosyne.security import TrustTier

    tenant = "golden-rails"
    out: dict[str, Any] = {}
    for rate in (0.0, 0.25, 0.5, 1.0, None):
        engine = LocalMemoryEngine()
        replacements: list[str] = []
        for index in range(6):
            cid = _append(engine, tenant, f"Entity {index} value is alpha.")
            engine.upsert_assertion(Assertion(
                tenant_id=tenant, subject=f"Entity {index}", predicate="value is", object="alpha",
                source_evidence_cids=[cid], status="active", trust_tier=int(TrustTier.NORMAL),
                access_policy={"tenant": tenant}))
            replacements.append(_append(engine, tenant, f"Entity {index} value is beta.",
                                        metadata={"consolidation": {"prediction_error": 1.0}}))
            replacements.append(_append(engine, tenant, f"Independent note: Entity {index} value is beta.",
                                        metadata={"consolidation": {"prediction_error": 1.0}}, source_type="note"))
        run_result = _worker(engine, max_supersession_rate=rate, gate_cases=[_budget_case()],
                             candidate_extractor=_BudgetExtractor(6)).run_queue_payload({
            "tenant_id": tenant, "source_evidence_cids": replacements, "prediction_error": {"score": 1.0},
            "passes": ["extractor", "resolver", "belief_reviser", "promotion_gate"]})
        out[str(rate)] = {
            "run": run_result.to_dict(),
            "main": [a.to_dict() for a in engine.assertions.values() if a.branch == "main"],
            "relations": [r.to_dict() for r in engine.relations.values() if r.branch == "main"],
            "audit": [row for row in engine.audit_log
                      if row.get("op") not in BOOKKEEPING_OPS and not row.get(REPLAY_MARK)],
        }
    return out


def synthetic_conflicts() -> dict[str, Any]:
    """Supersession chains within and across batches, trust tiers, duplicate relations, and
    single-source facts that a forget retracts before more facts arrive."""
    t = "golden-conflicts"
    chains = [
        _row(t, f"Thing {i}\nThing {i} is {COLOURS[i % 7]}. Thing {i} is {COLOURS[(i + 1) % 7]}. "
                f"Thing {i} is {COLOURS[(i + 2) % 7]}.", f"conf:c{i}")
        for i in range(6)
    ]
    relations = [
        _row(t, f"Deal {i}\nAcme Corp acquired Beta Works. Gamma Labs partnered with Acme Corp.", f"conf:r{i}",
             trust_tier=i % 2)
        for i in range(2)
    ]
    later = [
        _row(t, f"Later {i}\nThing {i} is {COLOURS[(i + 4) % 7]}.", f"conf:l{i}", trust_tier=[0, 2, 1][i % 3])
        for i in range(6)
    ]
    # Two independent sources (the gate's corroboration floor), both forgotten later, so their
    # facts end up retracted while newer facts about the same subjects arrive.
    solo = [
        _row(t, "Solo\nSolo Item 0 is Lisbon. Solo Item 1 is Oslo.", "conf:s0"),
        _row(t, "Solo note\nSolo Item 0 is Lisbon. Solo Item 1 is Oslo.", "conf:s1", source_type="note"),
    ]
    replacements = [
        _row(t, f"Solo again {i}\nSolo Item {i} is {CITIES[(i + 3) % 7]}.", f"conf:t{i}{kind}",
             source_type=kind, trust_tier=i + 1)
        for i in range(2)
        for kind in ("hipporag:golden", "note")
    ]
    steps: list[dict[str, Any]] = [{"capture": chains}, {"capture": relations}, {"capture": later},
                                   {"capture": solo}, {"forget": [3, 0]}, {"forget": [3, 1]},
                                   {"capture": replacements}, {"capture": relations[:1]}, {"capture": chains[:2]}]
    queries = [{"question_id": f"q{i}", "tenant": t, "query": q} for i, q in enumerate([
        "What colour is Thing 2?", "Who acquired Beta Works?", "Where is Solo Item 1?", "Thing 5",
        "Acme Corp", "Solo Item 0",
    ])]
    return {"gate_content": chains[0]["content"], "tenants": [t], "queries": queries, "steps": steps}


def hipporag(corpus: str, dataset: str, n: int, data_dir: Path, questions: int = 25) -> dict[str, Any]:
    docs = json.loads((data_dir / f"{corpus}_corpus.json").read_text(encoding="utf-8"))[:n]
    tenant = f"public-hipporag-{dataset}"
    rows = [_row(tenant, f"{d.get('title', '')}\n{d.get('text', d.get('content', ''))}", f"{dataset}:p{i:05d}",
                 source_type=f"hipporag:{dataset}") for i, d in enumerate(docs)]
    raw_questions = json.loads((data_dir / f"{corpus}.json").read_text(encoding="utf-8"))[:questions]
    queries = [{"question_id": f"q{i}", "tenant": tenant, "query": str(q.get("question", ""))}
               for i, q in enumerate(raw_questions) if q.get("question")]
    return {"gate_content": rows[0]["content"], "tenants": [tenant], "queries": queries, "steps": [{"capture": rows}]}


def scenario(name: str, data_dir: Path | None) -> dict[str, Any] | Callable[[], Any]:
    if name == "synthetic-growth":
        return synthetic_growth()
    if name == "synthetic-rails":
        return synthetic_rails
    if name == "synthetic-conflicts":
        return synthetic_conflicts()
    if name == "g0-write-gating":
        from eval.g0.write_gating import run_write_gating_eval

        return run_write_gating_eval
    match = re.fullmatch(r"hipporag-(2wiki|hotpot|musique)-(\d+)", name)
    if match:
        if data_dir is None:
            raise SystemExit("HippoRAG scenarios need --data")
        corpus = {"2wiki": "2wikimultihopqa", "hotpot": "hotpotqa", "musique": "musique"}[match.group(1)]
        return hipporag(corpus, match.group(1), int(match.group(2)), data_dir)
    raise SystemExit(f"unknown scenario {name}")


SCENARIOS = ["synthetic-growth", "synthetic-rails", "synthetic-conflicts", "g0-write-gating", "hipporag-2wiki-10", "hipporag-2wiki-20", "hipporag-2wiki-35",
             "hipporag-hotpot-10", "hipporag-hotpot-20", "hipporag-musique-10", "hipporag-musique-20"]


# --------------------------------------------------------------------------- dump


def _main_state(store: Path, tenant: str) -> dict[str, Any]:
    from mnemosyne.engine import LocalMemoryEngine

    engine = LocalMemoryEngine(store_path=store, read_only=True)

    def on_main(items: Any) -> list[dict[str, Any]]:
        return [item.to_dict() for item in items if item.tenant_id == tenant and getattr(item, "branch", "main") == "main"]

    def of_tenant(items: Any) -> list[dict[str, Any]]:
        return [item.to_dict() for item in items if getattr(item, "tenant_id", None) == tenant]

    state = {
        "evidence": on_main(engine.evidence.values()),
        "assertions": on_main(engine.assertions.values()),
        "relations": on_main(engine.relations.values()),
        "entities": [dict(value) for key, value in engine.entities.items() if key[0] == tenant],
        "justifications": of_tenant(engine.justifications.values()),
        "contradictions": of_tenant(engine.contradictions.values()),
        "preferences": of_tenant(engine.preferences.values()),
        "deletion_log": [row for row in engine.deletion_log if row.get("tenant_id") in {tenant, "*"}],
        "audit": [row for row in engine.audit_log
                  if row.get("tenant_id") in {tenant, "*"} and row.get("op") not in BOOKKEEPING_OPS
                  and not row.get(REPLAY_MARK)],
        "merges": [{k: v for k, v in row.items() if k not in MERGE_REPLAY_KEYS} for row in engine.merge_log],
        "branches": sorted(name for name, meta in engine.branches.items() if (meta or {}).get("kind") != "canary"),
    }
    del engine
    gc.collect()
    return state


def run(name: str, data_dir: Path | None = None) -> dict[str, Any]:
    spec = scenario(name, data_dir)
    with deterministic_runtime() as clock, tempfile.TemporaryDirectory(prefix="mneme-golden-") as temp:
        if callable(spec):
            return canonical({"scenario": name, "result": spec()})
        work = Path(temp)
        store = work / "store.json"
        _cli(_gate_case_argv(store, spec["gate_content"]))
        steps: list[Any] = []
        captured: list[list[str]] = []
        for index, step in enumerate(spec["steps"]):
            if "capture" in step:
                path = work / f"batch-{index}.jsonl"
                path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in step["capture"]), encoding="utf-8")
                try:
                    out = _cli(["--backend", "local", "--store", str(store), "capture-batch", "--input-jsonl", str(path),
                                "--consolidate"])
                except Exception as exc:  # noqa: BLE001 - a refused batch is a recorded outcome
                    failure = f"{type(exc).__name__}: {exc}"
                else:
                    failure = None
                if failure is not None:
                    gc.collect()  # the refused batch's engine must be gone before the next command
                    captured.append([])
                    steps.append({"error": failure})
                    continue
                captured.append([r["cid"] for r in out["results"]])
                steps.append(out)
            else:
                batch, row = step["forget"]
                if row >= len(captured[batch]):
                    steps.append({"forget_skipped": f"capture step {batch} stored nothing"})
                    continue
                tenant = spec["steps"][[i for i, s in enumerate(spec["steps"]) if "capture" in s][batch]]["capture"][row]["tenant"]
                clock.tick()
                steps.append(_cli(["--backend", "local", "--store", str(store), "forget", "--tenant", tenant,
                                   "--cid", captured[batch][row]]))
        clock.tick()
        queries = work / "queries.jsonl"
        queries.write_text("".join(json.dumps(q, sort_keys=True) + "\n" for q in spec["queries"]), encoding="utf-8")
        answers = _cli(["--backend", "local", "--store", str(store), "--evaluation-read-only", "eval-query-batch",
                        "--input-jsonl", str(queries)])
        state = {tenant: _main_state(store, tenant) for tenant in spec["tenants"]}
        return canonical({"scenario": name, "steps": steps, "queries": answers, "state": state})


# --------------------------------------------------------------------------- canonical form


def _drop_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _drop_volatile(v)
            for k, v in value.items()
            # Per-branch listings (forget's branch_results) name whatever branches exist; merged
            # canaries are bookkeeping and are discarded by the new engine (approved contract).
            if k not in VOLATILE_KEYS and not k.startswith("canary-")
        }
    if isinstance(value, list):
        return [_drop_volatile(v) for v in value]
    return value


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    if isinstance(value, str) and ID_RE.match(value):
        return "<id>"
    return value


def _sort_state(state: dict[str, Any]) -> dict[str, Any]:
    ordered = {}
    for key, rows in state.items():
        if isinstance(rows, list) and key not in {"audit", "merges", "deletion_log"}:
            rows = sorted(rows, key=lambda r: json.dumps(_mask(r), sort_keys=True, default=str))
        ordered[key] = rows
    return ordered


def canonical(dump: dict[str, Any]) -> dict[str, Any]:
    dump = json.loads(json.dumps(_drop_volatile(dump), sort_keys=True, default=str))
    if isinstance(dump.get("state"), dict):
        dump["state"] = {t: _sort_state(s) for t, s in dump["state"].items()}
    labels: dict[str, str] = {}

    def relabel(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: relabel(value[k]) for k in sorted(value)}
        if isinstance(value, list):
            return [relabel(v) for v in value]
        if isinstance(value, str) and ID_RE.match(value):
            return labels.setdefault(value, f"L{len(labels) + 1}")
        return value

    # State first, in content order, so labels follow content rather than creation order.
    ordered = {"state": dump.get("state"), **{k: v for k, v in dump.items() if k != "state"}}
    return relabel(ordered)


def diff(a: Any, b: Any, path: str = "", out: list[str] | None = None, limit: int = 25) -> list[str]:
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if type(a) is not type(b):
        out.append(f"{path}: type {type(a).__name__} != {type(b).__name__}")
    elif isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(f"{path}/{key}: only in {'B' if key not in a else 'A'}")
            else:
                diff(a[key], b[key], f"{path}/{key}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for index, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{index}]", out, limit)
    elif a != b:
        out.append(f"{path}: {str(a)[:120]!r} != {str(b)[:120]!r}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    dump = sub.add_parser("dump")
    dump.add_argument("--scenario", required=True)
    dump.add_argument("--out", required=True)
    dump.add_argument("--src")
    dump.add_argument("--data")
    compare = sub.add_parser("compare")
    compare.add_argument("a")
    compare.add_argument("b")
    args = ap.parse_args(argv)
    if args.command == "list":
        print("\n".join(SCENARIOS))
        return 0
    if args.command == "compare":
        a = json.loads(Path(args.a).read_text(encoding="utf-8"))
        b = json.loads(Path(args.b).read_text(encoding="utf-8"))
        for dumped in (a, b):
            dumped.pop("engine_source", None)
        problems = diff(a, b)
        print("IDENTICAL" if not problems else "DIFFERENT\n" + "\n".join(problems))
        return 0 if not problems else 1
    if args.src:
        sys.path.insert(0, str(Path(args.src).resolve()))
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(1, str(repo_root))
    import mnemosyne

    result = run(args.scenario, Path(args.data) if args.data else None)
    result["engine_source"] = str(Path(mnemosyne.__file__).resolve().parent)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    print(f"{args.scenario}: {len(json.dumps(result))} bytes from {result['engine_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
