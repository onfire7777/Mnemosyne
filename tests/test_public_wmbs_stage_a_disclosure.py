"""Pin the M02/M04/M05 public-harness disclosures in the public README.

M02 is registered under ``### M02 retrieval development``. M04 is registered
under ``### M04 conflict development``. M05 Stage B is registered under
``### M05 provenance development``. This mirrors the M12 and M13 pinning tests
in ``tests/test_public_pm_bench_triggerbench.py`` and
``tests/test_public_working_memory_action_probe.py``.

Nothing here changes module behavior, fixture bytes, or Stage-A oracles; it
refuses to let the honest labels rot after the M05 cell is registered.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.public import wmbs_m02 as m02
from eval.public import wmbs_m04 as m04
from eval.public import wmbs_m05 as m05
from eval.public.runner import load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "eval" / "public" / "README.md"
FIXTURES_DIR = REPO_ROOT / "eval" / "public" / "fixtures"

M02_SECTION_HEADING = "### M02 retrieval development"
M04_SECTION_HEADING = "### M04 conflict development"
M05_SECTION_HEADING = "### M05 provenance development"

#: No suite remains under the leftover unregistered Stage-A heading.
UNREGISTERED_SUITE_KEYS: tuple[str, ...] = ()


def _readme() -> str:
    """Return the README with line wrapping collapsed to single spaces."""
    return " ".join(README_PATH.read_text(encoding="utf-8").split())


def _section_after(heading: str) -> str:
    text = README_PATH.read_text(encoding="utf-8")
    assert heading in text, f"missing heading {heading}"
    body = text.split(heading, 1)[1]
    for line in body.splitlines():
        if line.startswith("#"):
            body = body.split("\n" + line, 1)[0]
            break
    return " ".join(body.split())


def _m02_section() -> str:
    return _section_after(M02_SECTION_HEADING)


def _m04_section() -> str:
    return _section_after(M04_SECTION_HEADING)


def _m05_section() -> str:
    return _section_after(M05_SECTION_HEADING)


#: Every key M02's scorer emits.  The disclosure says M02 measures no cost or
#: resource beyond the four it reports as ``unsupported``, so any addition here
#: has to be disclosed in the same change.
M02_METRIC_KEYS = frozenset(
    {
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "recall_at_10",
        "ndcg_at_5",
        "ndcg_at_10",
        "evidence_recall",
        "unanswerable_correct_rate",
        "unsupported_claim_rate",
        "exact_match",
        "token_f1",
        "latency",
        "tokens",
        "calls",
        "storage",
    }
)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _m02_traces(fixture: dict) -> list[dict]:
    """Gold-ranked traces over the committed M02 fixture; executes no system."""
    return [
        {
            "case_id": question["question_id"],
            "question_id": question["question_id"],
            "ranked_hits": [
                {"rank": rank, "stable_item_id": stable_item_id}
                for rank, stable_item_id in enumerate(question["gold_doc_ids"], start=1)
            ],
            "answer": question["answers"][0] if question["answers"] else None,
            "abstained": not question["answers"],
        }
        for question in fixture["questions"]
    ]


def test_disclosure_section_exists_and_names_all_three_modules() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    assert M02_SECTION_HEADING in readme
    assert M04_SECTION_HEADING in readme
    assert M05_SECTION_HEADING in readme
    assert "### M04/M05 Stage-A development oracles (unregistered)" not in readme
    assert "`wmbs_m02.py`" in _m02_section()
    assert "`wmbs_m04.py`" in _m04_section()
    assert "`wmbs_m05.py`" in _m05_section()
    assert "nothing whatsoever about any memory system" in _m05_section()


def test_disclosure_states_the_registered_status_and_the_registry_agrees() -> None:
    """The registered-cell claim must stay true of the live registry."""
    m02_section = _m02_section()
    m04_section = _m04_section()
    m05_section = _m05_section()
    assert "M05 remains **unregistered**." not in m05_section
    assert "wmbs-m02-retrieval-development" in m02_section
    assert "wmbs-m04-development" in m04_section
    assert "wmbs-m05-development" in m05_section

    registry = load_registry()
    assert "wmbs-m02-retrieval-development" in registry
    assert "wmbs-m04-development" in registry
    assert "wmbs-m05-development" in registry
    for key in UNREGISTERED_SUITE_KEYS:
        assert key not in registry, (
            f"{key} is now registered; the README Stage-A disclosure claims it is "
            "unregistered and must be rewritten in the same change"
        )
    cell = registry["wmbs-m05-development"]
    assert cell["adapter"] == "wmbs-m05-reference"
    assert cell["fixture"] == "fixtures/wmbs-m05-provenance-development.json"
    assert cell["scoring_profile"] == "wmbs-m05-v1"
    assert cell["system_seam"] == "public-cli-subprocess"


def test_disclosure_admission_labels_match_the_modules() -> None:
    section = _m05_section()
    assert (
        '`admission_state: "PROPOSED"` in both its labels and its committed' in section
    )
    assert (
        "labels, fixture, and registry cell record `publishable: false` and "
        "`pbpp_headline_eligible: false`" in section
    )
    assert "M02 emits no publication or headline field at all" not in section
    assert "M02 emits no publication or headline field at all" not in _m02_section()
    assert '`ADMISSION_STATE = "PROPOSED"`' in _m02_section()
    assert '`ADMISSION_STATE = "PROPOSED"`' in _m04_section()

    assert m02.ADMISSION_STATE == "PROPOSED"
    assert m04.ADMISSION_STATE == "PROPOSED"

    m05_fixture = _fixture("wmbs-m05-provenance-development.json")
    assert m05_fixture["admission_state"] == "PROPOSED"
    assert m05_fixture["publishable"] is False
    assert m05_fixture["pbpp_headline_eligible"] is False
    assert m05._LABELS["publishable"] is False
    assert m05._LABELS["pbpp_headline_eligible"] is False

    # M02 makes no publication claim anywhere in its module or fixture: pin the
    # absence, not just the prose asserting it.
    m02_fixture = _fixture("wmbs-m02-retrieval-development.json")
    assert not [key for key in m02_fixture if "publish" in key or "headline" in key]
    m02_source = (REPO_ROOT / "eval" / "public" / "wmbs_m02.py").read_text(
        encoding="utf-8"
    )
    assert "pbpp_headline_eligible" not in m02_source
    assert "publishable" not in m02_source


def test_disclosure_license_claim_matches_the_modules() -> None:
    assert "`license: CC0-1.0`" in _m05_section()
    assert (
        "The module `LICENSE`, committed fixture, and registry cell carry "
        "`license: CC0-1.0`" in _m05_section()
    )
    assert (
        "labels/fixture/registry cell record `publishable: false`, "
        "`pbpp_headline_eligible: false`, and `license: CC0-1.0`" not in _m05_section()
    )
    assert '`license: "CC0-1.0"`' in _m02_section()
    assert "M04 declares no license field at all" in _m04_section()

    assert m02.LICENSE == "CC0-1.0"
    assert m05.LICENSE == "CC0-1.0"
    assert _fixture("wmbs-m02-retrieval-development.json")["license"] == "CC0-1.0"
    assert _fixture("wmbs-m05-provenance-development.json")["license"] == "CC0-1.0"
    assert "license" not in _fixture("wmbs-m04-development.json")
    assert not hasattr(m04, "LICENSE")
    assert load_registry()["wmbs-m05-development"]["license"] == "CC0-1.0"
    assert "license" not in load_registry()["wmbs-m04-development"]


def test_disclosure_cost_and_resource_gaps_match_the_scorers() -> None:
    assert "M05 emits no latency, token, call, or storage metric" in _m05_section()
    assert "M04 emits no latency, token, call, or storage metric" in _m04_section()
    assert (
        "M02's scorer reports `latency`, `tokens`, `calls`, and `storage` "
        "literally as `unsupported`" in _m02_section()
    )

    # Pin M02's four cost keys to the scorer's own output, not to its source
    # text: renaming any one of them must fail here, because the README names
    # them as the metrics a reader will see reported `unsupported`.
    fixture = _fixture("wmbs-m02-retrieval-development.json")
    metrics = m02.score_retrieval(fixture, _m02_traces(fixture))["metrics"]
    for metric in ("latency", "tokens", "calls", "storage"):
        assert metrics[metric] == "unsupported", (
            f"M02 no longer reports {metric!r} as 'unsupported'; the Stage-A "
            "disclosure says it does"
        )
    # The whole metric surface, not just those four: a newly added `cost_usd`
    # or `gpu_seconds` would make the unsupported-cost disclosure false while
    # the four named keys still read `unsupported`.
    assert set(metrics) == M02_METRIC_KEYS, (
        "M02's metric surface changed; the Stage-A disclosure describes the "
        f"old one. Added: {sorted(set(metrics) - M02_METRIC_KEYS)}; removed: "
        f"{sorted(M02_METRIC_KEYS - set(metrics))}"
    )

    m04_source = (REPO_ROOT / "eval" / "public" / "wmbs_m04.py").read_text(
        encoding="utf-8"
    )
    m05_source = (REPO_ROOT / "eval" / "public" / "wmbs_m05.py").read_text(
        encoding="utf-8"
    )
    for source, name in ((m04_source, "M04"), (m05_source, "M05")):
        for metric in ('"latency"', '"tokens"', '"calls"', '"storage"'):
            assert metric not in source, (
                f"{name} now emits {metric}; the Stage-A disclosure says it emits "
                "no cost or resource metric"
            )


def test_disclosure_m02_fixture_shape_matches_the_committed_bytes() -> None:
    section = _m02_section()
    assert (
        "generated from seed `20260801` and holds 240 documents and 60 questions"
        in (section)
    )
    assert "ten per query family" in section
    assert (
        "The specification names a 2,000-event local corpus; Stage A commits 240 "
        "documents and defers the 2,000-event variant" in section
    )

    fixture = _fixture("wmbs-m02-retrieval-development.json")
    assert fixture["seed"] == 20260801 == m02.DEFAULT_SEED
    assert len(fixture["corpus"]) == 240
    assert len(fixture["questions"]) == 60
    families = sorted({question["family"] for question in fixture["questions"]})
    assert families == [
        "entity",
        "exact",
        "multi-hop",
        "paraphrase",
        "relation",
        "unanswerable",
    ]
    for family in families:
        assert (
            sum(question["family"] == family for question in fixture["questions"]) == 10
        )
        assert f"`{family}`" in section


def test_disclosure_m04_fixture_shape_and_declared_gaps_match() -> None:
    section = _m04_section()
    assert "generated from seed `20260801` and holds 140 cases over five per-case" in (
        section
    )
    assert "Numeric confidence calibration is `unsupported`" in section
    assert "`branch_merge` as `UNSUPPORTED-BY-SYSTEM`" in section
    assert "`transaction_time` as `unsupported`" in section
    assert "`update_hook` as `emulated`" in section
    assert "the `sqlite` and `postgresql` backends as `DEFERRED`" in section
    assert (
        "an additional load-bearing `source_id` that keys the ablation gold" in section
    )
    assert "never an ABI conformance claim" in section

    fixture = _fixture("wmbs-m04-development.json")
    assert fixture["seed"] == 20260801 == m04.DEFAULT_SEED
    assert len(fixture["cases"]) == 140
    assert tuple(fixture["seeds"]) == m04.SEEDS == (11, 23, 37, 53, 71)
    assert tuple(fixture["permutations"]) == m04.PERMUTATIONS
    assert tuple(fixture["source_classes"]) == m04.SOURCE_CLASSES
    for seed in fixture["seeds"]:
        assert f"`{seed}`" in section
    for name in list(fixture["permutations"]) + list(fixture["source_classes"]):
        assert f"`{name}`" in section

    disclosures = fixture["disclosures"]
    assert disclosures["branch_merge"] == "UNSUPPORTED-BY-SYSTEM"
    assert disclosures["transaction_time"] == "unsupported"
    assert disclosures["update_hook"] == "emulated"
    assert disclosures["backends"]["sqlite"] == "DEFERRED"
    assert disclosures["backends"]["postgresql"] == "DEFERRED"

    # The `source_id` departure is the disclosure's most load-bearing admission:
    # pin that the key is really there rather than trusting the prose.
    events = [
        event
        for case in fixture["cases"]
        for bundle in case["events_by_permutation"].values()
        for event in bundle
    ]
    assert events, "the M04 fixture must carry events for this pin to mean anything"
    assert all("source_id" in event for event in events)


def test_disclosure_m05_fixture_shape_and_deferrals_match() -> None:
    section = _m05_section()
    assert "generated from seed `13`, declares the five seeds" in section
    assert "five slices of twenty cases each" in section
    assert (
        "The module declares three retrieval stage IDs (`dense_hash`, `lexical`, "
        "`graph_ppr`), but every committed case freezes `lexical` alone" in section
    )
    assert "It scores **one-hop** claim-to-source grounding only" in section
    assert "explicitly **unsigned** (`signed: false`" in section
    assert (
        "eight unresolved integration dependencies in `INTEGRATION_DEPENDENCIES`"
        in (section)
    )

    fixture = _fixture("wmbs-m05-provenance-development.json")
    assert fixture["generator_seed"] == 13
    assert tuple(fixture["seeds"]) == m05.SEEDS == (13, 29, 41, 59, 73)
    for seed in fixture["seeds"]:
        assert f"`{seed}`" in section

    slices = fixture["slices"]
    assert len(slices) == 5
    for slice_ in slices:
        assert len(slice_["cases"]) == 20
        assert f"`{slice_['slice_id']}`" in section

    assert m05.RETRIEVAL_STAGE_IDS == ("dense_hash", "lexical", "graph_ppr")
    exercised = sorted(
        {
            stage
            for slice_ in slices
            for case in slice_["cases"]
            for stage in case["retrieval_stages"]
        }
    )
    assert exercised == ["lexical"], (
        "the committed M05 cases now exercise more than the lexical stage; the "
        "README disclosure says they freeze `lexical` alone"
    )

    assert fixture["source_manifest"]["signed"] is False
    dependencies = fixture["integration_dependencies"]
    assert len(dependencies) == 8 == len(m05.INTEGRATION_DEPENDENCIES)
    for tag in ("Q1", "Q2", "Q3", "Q4", "Q7", "Q9", "Q10", "Q12"):
        # `f"{tag} "`, not the bare tag: `Q1` prefixes both `Q10` and `Q12`, so a
        # raw-prefix check would stay green after `Q1`'s own entry was dropped.
        assert any(dependency.startswith(f"{tag} ") for dependency in dependencies)
        assert f"{tag} " in section


def test_disclosure_keeps_stage_b_delivered_and_claims_nothing() -> None:
    section = _m05_section()
    assert "Stage B — harness integration for M05 — is delivered." in section
    assert (
        "Stage B — harness integration for M05 — is **not delivered**." not in section
    )
    assert (
        "Nothing here is a publication, comparability, ranking, superiority, or "
        "upstream-equivalence claim." in section
    )

    plan = "docs/plans/wmb-m05-provenance-explanation-implementation-plan.md"
    assert plan in section, f"the disclosure no longer links {plan}"
    assert (REPO_ROOT / plan).is_file(), f"{plan} is linked but missing"


def test_disclosure_section_precedes_no_registration_elsewhere() -> None:
    """Registered M05 must document the full suite id, not a bare prefix."""
    readme = _readme()
    assert "--suite wmbs-m05-development" in readme
    assert "--suite wmbs-m04-development" in readme
    assert "--suite wmbs-m02-retrieval-development" in readme
