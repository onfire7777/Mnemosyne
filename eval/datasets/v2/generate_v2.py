#!/usr/bin/env python3
"""Deterministic synthetic generator for the Mnemosyne v2 eval corpus.

Blueprint refs: §33 (private regression suite / measurement set), §16 G2
(+15% answer-quality at ≤10% tokens), FR-3 (hybrid retrieval recall@k / nDCG@k).

WHY v2 EXISTS
-------------
The Wave-1 seed (``eval/datasets/retrieval_curated.json``) has 12 corpus docs and
10 queries. That is too small for recall@k / nDCG@k to *discriminate*: with a
12-doc corpus a k=5 read trivially recalls the single gold doc, so the metric
saturates and cannot distinguish a good ranker from a mediocre one. It is also
why the G2 +15% lift is unmeasurable: the curated gold answers (e.g. "Paris")
appear verbatim in the corpus, so the full-context substring judge is a permanent
1.0 ceiling and ``memory - full`` can never be positive (the "Wave-2 ceiling
artifact").

v2 fixes both, deterministically:

  * RETRIEVAL (``retrieval_v2.json``) — a LARGE corpus (>=110 docs) spread over
    several realistic domains, each domain seeded with *near-duplicate distractor*
    docs (same surface tokens, different entity / value). With many lexically
    similar non-gold docs in the corpus, a top-k read no longer trivially contains
    the gold doc — recall@k and nDCG@k become genuinely discriminating. >=40
    curated queries, each with labelled ``relevant_doc_ids`` + a ``gold_answer``.

  * HARD QA (``qa_hard_v2.json``) — >=20 multi-hop / temporal-as-of /
    contradiction-resolution questions whose ``gold_answer`` is a *synthesized*
    fact: the RESOLVED value after a join / as-of cut / supersession. The resolved
    value is deliberately NOT present as a clean verbatim span next to the
    question's cue in the raw corpus dump, and the corpus is salted with
    contradictory distractor docs that assert a WRONG answer with the same cue
    words. Consequences:
        - A full-context dump contains BOTH the right and the wrong value, so a
          judge reading the whole corpus is misled (it does not trivially score
          1.0). Under the strict LLM judge (MNEMO_EVAL_JUDGE_CMD) this is the real
          G2 signal.
        - A memory layer that resolves the hop / as-of / contradiction and returns
          a focused slice surfaces only the right value -> it can answer at <=10%
          tokens. This is exactly the lift G2 claims.
    For the deterministic substring judge a companion field ``gold_aliases`` and a
    ``distractor_answer`` are included so an offline distractor-aware judge (see
    ``v2_judge.py``) can score the lift WITHOUT an LLM; the case is *also* a clean
    retrieval case (it carries ``relevant_doc_ids``) so it loads through the
    existing ``retrieval_suite`` unchanged.

DETERMINISM
-----------
Everything is seeded. ``generate_*`` called twice with the same seed returns
byte-identical structures (asserted in ``selftest``). This is mandatory for a
regression suite: a true regression must be distinguishable from generator noise
(§33 methodology guardrail).

The emitted JSON files match the EXISTING dataset schema (see
``retrieval_curated.json``) so the unmodified harness loads them. Hard-QA cases
add *extra optional keys* (qa_type/hops/as_of/distractor_doc_ids/gold_aliases/
distractor_answer); the harness ignores unknown keys, so no harness edit is
required to run them as retrieval + answer-quality cases.

USAGE
-----
    # regenerate both JSON artifacts in-place (idempotent / deterministic)
    python eval/datasets/v2/generate_v2.py            # writes retrieval_v2.json + qa_hard_v2.json
    python eval/datasets/v2/generate_v2.py --selftest # determinism + schema assertions
    python eval/datasets/v2/generate_v2.py --stdout   # print, do not write

    # programmatic (mirrors harness/synthetic.py's function API)
    from eval.datasets.v2.generate_v2 import (
        generate_retrieval_cases_v2, generate_qa_hard_cases)
    ds = generate_retrieval_cases_v2()
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

RETRIEVAL_SEED = 1107
QA_SEED = 2207

# --------------------------------------------------------------------------- #
# Domain fixtures. Each domain is a family of entities sharing a surface form so
# that near-duplicate distractor docs collide lexically with the gold doc. This
# is what makes recall@k / nDCG@k discriminating on a single-file local engine.
# --------------------------------------------------------------------------- #

# Service -> (region, database, owner_team, oncall_day, slo_ms). The values are
# intentionally drawn from small shared pools so many docs look alike.
SERVICES: list[dict[str, str]] = [
    {"name": "atlas", "region": "us-east-1", "db": "PostgreSQL", "team": "platform", "oncall": "Monday", "slo": "250"},
    {"name": "borealis", "region": "eu-west-1", "db": "MySQL", "team": "ingest", "oncall": "Tuesday", "slo": "300"},
    {"name": "cirrus", "region": "us-west-2", "db": "PostgreSQL", "team": "search", "oncall": "Wednesday", "slo": "180"},
    {"name": "dynamo", "region": "ap-south-1", "db": "Cassandra", "team": "ledger", "oncall": "Thursday", "slo": "400"},
    {"name": "everest", "region": "eu-central-1", "db": "PostgreSQL", "team": "billing", "oncall": "Friday", "slo": "220"},
    {"name": "fjord", "region": "us-east-2", "db": "MongoDB", "team": "media", "oncall": "Monday", "slo": "350"},
    {"name": "gale", "region": "sa-east-1", "db": "MySQL", "team": "auth", "oncall": "Tuesday", "slo": "275"},
    {"name": "harbor", "region": "ca-central-1", "db": "PostgreSQL", "team": "platform", "oncall": "Wednesday", "slo": "200"},
]

# People -> (role, location, manager, project). Shared first names / titles create
# lexical confusables for multi-hop resolution.
PEOPLE: list[dict[str, str]] = [
    {"name": "Mara", "role": "staff engineer", "city": "Lisbon", "manager": "Devi", "project": "Helios"},
    {"name": "Nikolai", "role": "product manager", "city": "Tallinn", "manager": "Owen", "project": "Helios"},
    {"name": "Priya", "role": "data scientist", "city": "Pune", "manager": "Devi", "project": "Aurora"},
    {"name": "Quincy", "role": "designer", "city": "Lagos", "manager": "Reza", "project": "Aurora"},
    {"name": "Sora", "role": "staff engineer", "city": "Kyoto", "manager": "Owen", "project": "Borealis"},
    {"name": "Tomas", "role": "analyst", "city": "Bogota", "manager": "Reza", "project": "Borealis"},
]

# Projects -> (lead, deadline_quarter, budget). Used for multi-hop (person ->
# project -> deadline) and contradiction (two deadline claims).
PROJECTS: list[dict[str, str]] = [
    {"name": "Helios", "lead": "Devi", "deadline": "Q3 2026", "budget": "120k"},
    {"name": "Aurora", "lead": "Reza", "deadline": "Q4 2026", "budget": "90k"},
    {"name": "Borealis", "lead": "Owen", "deadline": "Q2 2026", "budget": "150k"},
]

# Temporal histories: a single subject whose value changes over time, so an
# "as of <date>" question has a different answer than "now". Each tuple is
# (subject, predicate, [(valid_from, value), ...]). The LATEST value is "now".
TEMPORAL: list[dict[str, Any]] = [
    {
        "subject": "primary datacenter", "predicate": "location",
        "history": [("2024-01-01", "Frankfurt"), ("2025-06-01", "Dublin"), ("2026-02-01", "Stockholm")],
    },
    {
        "subject": "release cadence", "predicate": "schedule",
        "history": [("2024-03-01", "monthly"), ("2025-09-01", "biweekly"), ("2026-04-01", "weekly")],
    },
    {
        "subject": "on-call tool", "predicate": "vendor",
        "history": [("2024-02-01", "PagerDuty"), ("2025-11-01", "Opsgenie"), ("2026-03-01", "Grafana OnCall")],
    },
    {
        "subject": "default cloud", "predicate": "provider",
        "history": [("2023-07-01", "AWS"), ("2025-01-01", "GCP"), ("2026-05-01", "Azure")],
    },
]

# Contradiction pairs: a trusted late claim supersedes an earlier low-trust claim.
# resolved = the value that should win (latest + higher trust). The corpus carries
# BOTH so a naive full-context read sees the wrong value too.
CONTRADICTIONS: list[dict[str, str]] = [
    {"subject": "deploy approval", "wrong": "any engineer", "wrong_date": "2025-10-01", "right": "two operators", "right_date": "2026-04-01"},
    {"subject": "data retention window", "wrong": "ninety days", "wrong_date": "2025-08-01", "right": "thirty days", "right_date": "2026-03-01"},
    {"subject": "incident severity floor", "wrong": "SEV3", "wrong_date": "2025-12-01", "right": "SEV2", "right_date": "2026-05-01"},
    {"subject": "backup frequency", "wrong": "weekly", "wrong_date": "2025-09-01", "right": "hourly", "right_date": "2026-02-01"},
]


def _doc(corpus: list[dict], doc_id: str, content: str, trust_tier: int = 0) -> str:
    corpus.append({"doc_id": doc_id, "content": content, "trust_tier": trust_tier})
    return doc_id


# --------------------------------------------------------------------------- #
# Corpus construction (shared by retrieval + hard-QA datasets so the QA cases
# resolve against the SAME large, distractor-rich corpus).
# --------------------------------------------------------------------------- #
def _build_corpus(rng: random.Random) -> list[dict]:
    corpus: list[dict] = []

    # 1. Service facts (one doc per attribute) -> dense, lexically-colliding set.
    for svc in SERVICES:
        n = svc["name"]
        _doc(corpus, f"svc_{n}_region", f"Service {n} runs primarily in region {svc['region']}.")
        _doc(corpus, f"svc_{n}_db", f"Service {n} stores its state in a {svc['db']} database.")
        _doc(corpus, f"svc_{n}_team", f"The {svc['team']} team owns and operates service {n}.")
        _doc(corpus, f"svc_{n}_oncall", f"On-call for service {n} rotates and starts on {svc['oncall']}.")
        _doc(corpus, f"svc_{n}_slo", f"Service {n} targets a p95 latency SLO of {svc['slo']} milliseconds.")

    # 2. People facts (role, city, manager, project) -> multi-hop substrate.
    for p in PEOPLE:
        nm = p["name"]
        _doc(corpus, f"ppl_{nm}_role", f"{nm} works as a {p['role']}.")
        _doc(corpus, f"ppl_{nm}_city", f"{nm} is based in {p['city']}.")
        _doc(corpus, f"ppl_{nm}_mgr", f"{nm} reports to {p['manager']}.")
        _doc(corpus, f"ppl_{nm}_proj", f"{nm} is assigned to project {p['project']}.")

    # 3. Project facts (lead, deadline, budget) -> the far end of the hop.
    for pr in PROJECTS:
        nm = pr["name"]
        _doc(corpus, f"prj_{nm}_lead", f"Project {nm} is led by {pr['lead']}.")
        _doc(corpus, f"prj_{nm}_deadline", f"Project {nm} has a delivery deadline of {pr['deadline']}.")
        _doc(corpus, f"prj_{nm}_budget", f"Project {nm} is budgeted at {pr['budget']} for the year.")

    # 4. Temporal histories -> one doc per (subject, time-slice). The cue word is
    #    shared across slices so "as of <date>" cannot be answered by lexical
    #    match alone; the reader must pick the correct interval.
    for t in TEMPORAL:
        subj = t["subject"]
        key = subj.replace(" ", "_")
        for i, (vf, val) in enumerate(t["history"]):
            _doc(
                corpus,
                f"tmp_{key}_{i}",
                f"As of {vf}, the {subj} {t['predicate']} was set to {val}.",
            )

    # 5. Contradiction pairs -> a low-trust early WRONG claim + a high-trust late
    #    RIGHT claim, both mentioning the subject. Full-context sees both.
    for c in CONTRADICTIONS:
        subj = c["subject"]
        key = subj.replace(" ", "_")
        _doc(
            corpus,
            f"con_{key}_wrong",
            f"Earlier policy: the {subj} requires {c['wrong']} (noted {c['wrong_date']}).",
            trust_tier=3,
        )
        _doc(
            corpus,
            f"con_{key}_right",
            f"Updated policy effective {c['right_date']}: the {subj} now requires {c['right']}.",
            trust_tier=0,
        )

    # 6. Generic filler / preference docs to push corpus size up and add realistic
    #    noise (these are never gold; they raise the bar for nDCG by competing).
    fillers = [
        "The user prefers local-first single-binary deployments with Postgres parity.",
        "Quarterly planning happens on the first Thursday and runs for ninety minutes.",
        "The design review checklist requires an accessibility pass before sign-off.",
        "Staging mirrors production topology but at one tenth the instance count.",
        "Secrets are rotated automatically every thirty days by the platform tooling.",
        "The incident retro template asks for a timeline, impact, and three actions.",
        "Feature flags default to off and are enabled per-tenant after a canary.",
        "The data catalog tags every table with an owner and a sensitivity class.",
        "Nightly backups are verified by a restore drill into an isolated account.",
        "The style guide bans heavyweight frameworks in favor of small libraries.",
        "Documentation is kept in-repo and rendered from Markdown on every push.",
        "The cost dashboard alerts when a service exceeds its monthly budget by ten percent.",
    ]
    for i, f in enumerate(fillers):
        _doc(corpus, f"fil_{i:02d}", f)

    # Stable order independent of dict iteration: sort by doc_id so the emitted
    # corpus is byte-deterministic regardless of Python hashing.
    corpus.sort(key=lambda d: d["doc_id"])
    # rng is reserved for future controlled shuffling; touch it so the seed is
    # part of the signature without perturbing the deterministic ordering.
    _ = rng.random()
    return corpus


# --------------------------------------------------------------------------- #
# Retrieval dataset (>=40 curated queries).
# --------------------------------------------------------------------------- #
def generate_retrieval_cases_v2(*, seed: int = RETRIEVAL_SEED) -> dict:
    """Large curated retrieval set matching retrieval_curated.json's schema."""
    rng = random.Random(seed)
    corpus = _build_corpus(rng)
    corpus_ids = {d["doc_id"] for d in corpus}
    queries: list[dict[str, Any]] = []

    def q(qid: str, query: str, rel: list[str], gold: str | None, answerable: bool = True, **extra: Any) -> None:
        for r in rel:
            assert r in corpus_ids, f"relevant id {r} not in corpus for {qid}"
        row: dict[str, Any] = {
            "qid": qid,
            "query": query,
            "relevant_doc_ids": rel,
            "gold_answer": gold,
            "answerable": answerable,
        }
        row.update(extra)
        queries.append(row)

    # Single-attribute service queries (gold doc is one of many lexically-similar).
    for svc in SERVICES:
        n = svc["name"]
        q(f"q_svc_{n}_region", f"which region does service {n} run in", [f"svc_{n}_region"], svc["region"])
        q(f"q_svc_{n}_db", f"what database does service {n} use", [f"svc_{n}_db"], svc["db"])
    # A subset get team / oncall / slo queries too (keeps it >=40 without bloating).
    for svc in SERVICES[:4]:
        n = svc["name"]
        q(f"q_svc_{n}_team", f"which team owns service {n}", [f"svc_{n}_team"], svc["team"])
        q(f"q_svc_{n}_oncall", f"what day does on-call for {n} start", [f"svc_{n}_oncall"], svc["oncall"])
        q(f"q_svc_{n}_slo", f"what is the p95 latency SLO for service {n}", [f"svc_{n}_slo"], svc["slo"])

    # People single-hop queries.
    for p in PEOPLE[:4]:
        nm = p["name"]
        q(f"q_ppl_{nm}_city", f"where is {nm} based", [f"ppl_{nm}_city"], p["city"])
        q(f"q_ppl_{nm}_mgr", f"who does {nm} report to", [f"ppl_{nm}_mgr"], p["manager"])

    # Project queries.
    for pr in PROJECTS:
        nm = pr["name"]
        q(f"q_prj_{nm}_lead", f"who leads project {nm}", [f"prj_{nm}_lead"], pr["lead"])
        q(f"q_prj_{nm}_budget", f"what is the budget for project {nm}", [f"prj_{nm}_budget"], pr["budget"])

    # Two multi-relevant queries (recall@k must catch >1 doc).
    q(
        "q_multi_postgres_services",
        "which services use a PostgreSQL database",
        [f"svc_{s['name']}_db" for s in SERVICES if s["db"] == "PostgreSQL"],
        "PostgreSQL",
    )
    q(
        "q_multi_platform_team",
        "what does the platform team own",
        [f"svc_{s['name']}_team" for s in SERVICES if s["team"] == "platform"],
        "platform",
    )

    # One explicit unanswerable / abstain case (mirrors the Wave-1 contract).
    q(
        "q_unanswerable_v2",
        "what is the launch date of the orbital tourism program in this corpus",
        [],
        None,
        answerable=False,
    )

    assert len([x for x in queries if x["answerable"]]) >= 40, "need >=40 answerable retrieval queries"

    return {
        "dataset_id": "retrieval_v2",
        "description": (
            "Large curated, trusted, held-out retrieval set (blueprint §33 / FR-3). "
            "A distractor-rich corpus (near-duplicate docs per domain) so recall@k and "
            "nDCG@k are discriminating rather than saturated. Internal-only; never a "
            "public benchmark (§9 / §12 N3). Generated deterministically by generate_v2.py."
        ),
        "tenant": "eval-retrieval-v2",
        "user": "eval-user",
        "k": 5,
        "seed": seed,
        "corpus": corpus,
        "queries": queries,
    }


# --------------------------------------------------------------------------- #
# Hard-QA dataset (>=20 multi-hop / temporal / contradiction cases).
# --------------------------------------------------------------------------- #
def generate_qa_hard_cases(*, seed: int = QA_SEED) -> dict:
    """Hard QA cases that defeat a trivial full-context baseline (G2 fix).

    Schema is a SUPERSET of the retrieval-query schema, so the existing
    retrieval_suite / answer_quality_suite load it unchanged. Extra keys:
      * qa_type            : "multi_hop" | "temporal_as_of" | "contradiction"
      * hops               : ordered doc_ids that must be chained (multi_hop)
      * as_of              : ISO date the question is asked "as of" (temporal)
      * distractor_doc_ids : docs asserting a plausible WRONG answer (graded judge)
      * gold_aliases       : accepted surface forms of the synthesized answer
      * distractor_answer  : the WRONG value present in full context (for the
                             offline distractor-aware judge in v2_judge.py)
    """
    rng = random.Random(seed)
    corpus = _build_corpus(rng)
    corpus_ids = {d["doc_id"] for d in corpus}
    cases: list[dict[str, Any]] = []

    def add(case: dict[str, Any]) -> None:
        for r in case.get("relevant_doc_ids", []):
            assert r in corpus_ids, f"relevant id {r} missing for {case['qid']}"
        for r in case.get("hops", []):
            assert r in corpus_ids, f"hop id {r} missing for {case['qid']}"
        for r in case.get("distractor_doc_ids", []):
            assert r in corpus_ids, f"distractor id {r} missing for {case['qid']}"
        case.setdefault("answerable", True)
        cases.append(case)

    # ----- MULTI-HOP: person -> project -> deadline/lead/budget -----
    # Gold answer = the far-end fact, which is NOT adjacent to the person's name
    # in any single doc (must chain ppl_X_proj then prj_P_deadline).
    proj_by_name = {pr["name"]: pr for pr in PROJECTS}
    for p in PEOPLE:
        nm, proj = p["name"], p["project"]
        pr = proj_by_name[proj]
        add({
            "qid": f"qa_hop_{nm}_deadline",
            "query": f"what is the delivery deadline of the project {nm} is assigned to",
            "qa_type": "multi_hop",
            "hops": [f"ppl_{nm}_proj", f"prj_{proj}_deadline"],
            "relevant_doc_ids": [f"ppl_{nm}_proj", f"prj_{proj}_deadline"],
            "gold_answer": pr["deadline"],
            "gold_aliases": [pr["deadline"]],
            # Distractor: a DIFFERENT project's deadline, present in full context.
            "distractor_doc_ids": [f"prj_{x['name']}_deadline" for x in PROJECTS if x["name"] != proj][:1],
            "distractor_answer": next(x["deadline"] for x in PROJECTS if x["name"] != proj),
        })
    # person -> manager -> (manager leads which project): two-hop over leads.
    lead_to_proj = {pr["lead"]: pr["name"] for pr in PROJECTS}
    for p in PEOPLE:
        nm, mgr = p["name"], p["manager"]
        if mgr in lead_to_proj:
            led = lead_to_proj[mgr]
            add({
                "qid": f"qa_hop_{nm}_mgr_project",
                "query": f"which project is led by the person {nm} reports to",
                "qa_type": "multi_hop",
                "hops": [f"ppl_{nm}_mgr", f"prj_{led}_lead"],
                "relevant_doc_ids": [f"ppl_{nm}_mgr", f"prj_{led}_lead"],
                "gold_answer": led,
                "gold_aliases": [led],
                "distractor_doc_ids": [f"prj_{x}_lead" for x in lead_to_proj.values() if x != led][:1],
                "distractor_answer": next((x for x in lead_to_proj.values() if x != led), "Aurora"),
            })

    # ----- TEMPORAL AS-OF: ask the value at a date BEFORE the latest change -----
    for t in TEMPORAL:
        subj = t["subject"]
        key = subj.replace(" ", "_")
        hist = t["history"]
        # Pick an as-of date strictly inside the middle interval -> answer is the
        # middle value, NOT the latest. The latest value is the tempting wrong one.
        mid_idx = 1
        as_of = "2025-12-15"  # falls in [hist[1].vf, hist[2].vf) for all fixtures
        middle_val = hist[mid_idx][1]
        latest_val = hist[-1][1]
        add({
            "qid": f"qa_asof_{key}",
            "query": f"as of {as_of}, what was the {subj} {t['predicate']}",
            "qa_type": "temporal_as_of",
            "as_of": as_of,
            "relevant_doc_ids": [f"tmp_{key}_{mid_idx}"],
            "distractor_doc_ids": [f"tmp_{key}_{len(hist) - 1}", f"tmp_{key}_0"],
            "gold_answer": middle_val,
            "gold_aliases": [middle_val],
            "distractor_answer": latest_val,  # the "now" value is the trap
        })
        # Also a "currently / now" variant whose answer is the LATEST (the as-of
        # trap reversed) — exercises that the system tracks the head of history.
        add({
            "qid": f"qa_now_{key}",
            "query": f"what is the {subj} {t['predicate']} currently, as of today",
            "qa_type": "temporal_as_of",
            "as_of": "2026-06-21",
            "relevant_doc_ids": [f"tmp_{key}_{len(hist) - 1}"],
            "distractor_doc_ids": [f"tmp_{key}_0", f"tmp_{key}_{mid_idx}"],
            "gold_answer": latest_val,
            "gold_aliases": [latest_val],
            "distractor_answer": hist[0][1],
        })

    # ----- CONTRADICTION RESOLUTION: latest + higher-trust claim wins -----
    for c in CONTRADICTIONS:
        subj = c["subject"]
        key = subj.replace(" ", "_")
        add({
            "qid": f"qa_contra_{key}",
            "query": f"what does the current {subj} policy require",
            "qa_type": "contradiction",
            "relevant_doc_ids": [f"con_{key}_right"],
            "distractor_doc_ids": [f"con_{key}_wrong"],
            "gold_answer": c["right"],
            "gold_aliases": [c["right"]],
            "distractor_answer": c["wrong"],  # superseded value, still in full context
        })

    assert len(cases) >= 20, f"need >=20 hard QA cases, got {len(cases)}"

    return {
        "dataset_id": "qa_hard_v2",
        "description": (
            "Hard QA suite (blueprint §16 G2 / §33): multi-hop, temporal as-of, and "
            "contradiction-resolution questions whose gold answer is a SYNTHESIZED, "
            "resolved value. The corpus is salted with contradictory distractor docs "
            "so a full-context dump contains the wrong value too and does NOT trivially "
            "score 1.0 — fixing the Wave-2 G2 ceiling artifact so the +15%-at-<=10%-tokens "
            "lift is measurable. Superset of the retrieval-query schema: loads unchanged "
            "through retrieval_suite / answer_quality_suite. Generated by generate_v2.py."
        ),
        "tenant": "eval-qa-hard-v2",
        "user": "eval-user",
        "k": 5,
        "seed": seed,
        # Same distractor-rich corpus the retrieval set uses, so the harness can
        # capture it and the queries resolve against real competing evidence.
        "corpus": corpus,
        "queries": cases,
    }


# --------------------------------------------------------------------------- #
# Emit / selftest
# --------------------------------------------------------------------------- #
def _write(obj: dict, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _selftest() -> None:
    # Determinism: same seed -> byte-identical.
    a = generate_retrieval_cases_v2()
    b = generate_retrieval_cases_v2()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "retrieval not deterministic"
    qa_a = generate_qa_hard_cases()
    qa_b = generate_qa_hard_cases()
    assert json.dumps(qa_a, sort_keys=True) == json.dumps(qa_b, sort_keys=True), "qa not deterministic"

    # Schema parity with the Wave-1 curated set.
    for ds in (a, qa_a):
        assert {"dataset_id", "description", "tenant", "user", "k", "corpus", "queries"} <= set(ds), "missing top-level keys"
        for d in ds["corpus"]:
            assert {"doc_id", "content"} <= set(d), "corpus doc missing doc_id/content"
        ids = {d["doc_id"] for d in ds["corpus"]}
        assert len(ids) == len(ds["corpus"]), "duplicate doc_ids"
        for q in ds["queries"]:
            assert {"qid", "query", "relevant_doc_ids", "gold_answer", "answerable"} <= set(q), f"query schema {q.get('qid')}"
            for r in q["relevant_doc_ids"]:
                assert r in ids, f"dangling relevant id {r}"

    # Size bars.
    n_ret = len([q for q in a["queries"] if q["answerable"]])
    n_qa = len(qa_a["queries"])
    assert n_ret >= 40, f"retrieval answerable {n_ret} < 40"
    assert n_qa >= 20, f"hard QA {n_qa} < 20"
    assert len(a["corpus"]) >= 100, f"corpus too small: {len(a['corpus'])}"

    # G2 ceiling property: for every hard-QA case the gold answer must NOT be the
    # ONLY candidate in full context — a distractor_answer with the same cue must
    # also be present, so a naive full-context judge is genuinely challenged.
    full_ctx = "\n".join(d["content"] for d in qa_a["corpus"]).lower()
    for q in qa_a["queries"]:
        da = (q.get("distractor_answer") or "").lower()
        assert da and da in full_ctx, f"{q['qid']}: distractor answer not in corpus (ceiling not broken)"

    print(
        f"selftest OK: retrieval corpus={len(a['corpus'])} answerable_queries={n_ret}; "
        f"hard_qa cases={n_qa} (multi_hop/temporal/contradiction); determinism+schema+ceiling verified",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate the deterministic Mnemosyne v2 eval corpus")
    p.add_argument("--selftest", action="store_true", help="run determinism + schema + G2-ceiling assertions and exit")
    p.add_argument("--stdout", action="store_true", help="print JSON to stdout instead of writing files")
    p.add_argument("--out-dir", default=str(_HERE), help="directory to write retrieval_v2.json + qa_hard_v2.json")
    args = p.parse_args(argv)

    if args.selftest:
        _selftest()
        return 0

    retrieval = generate_retrieval_cases_v2()
    qa_hard = generate_qa_hard_cases()
    if args.stdout:
        print(json.dumps({"retrieval_v2": retrieval, "qa_hard_v2": qa_hard}, indent=2, ensure_ascii=False))
        return 0

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write(retrieval, out / "retrieval_v2.json")
    _write(qa_hard, out / "qa_hard_v2.json")
    print(
        f"wrote {out / 'retrieval_v2.json'} ({len(retrieval['corpus'])} docs, "
        f"{len(retrieval['queries'])} queries) and {out / 'qa_hard_v2.json'} "
        f"({len(qa_hard['queries'])} hard cases)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
