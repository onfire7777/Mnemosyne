"""Provider-free regressions for whole-book coverage, custody and bounded work."""

from __future__ import annotations

import copy
import json
import re
import threading
import time

import pytest

from mnemosyne import frameworks as fx


def node(unit, *, title="Assess risk", text=None, kind="step"):
    text = text or f"Check risk in chapter {unit}."
    return {"id": 0, "type": kind, "title": title, "content": text, "parent": None,
            "depends_on": None, "units": [unit], "fields": {
                "Action": f"Action {unit}", "Done When": f"Done {unit}", "ES": "Asserted",
                "EC": "Verbatim", "CT": "Prescriptive", "CN": "Core",
                "Source Quote": {"Quote": text, "Core Sentence": text}}}


def part(n):
    return {"name": "Book", "model": "fake", "passes": 1, "part": f"Chapter {n['units'][0]}",
            "numbers": n["units"], "nodes": [n], "edges": [],
            "logic": {"graph_issues": [], "logic_issues": [], "logic_warnings": []},
            "judgment": {"findings": [], "warrants_reextract": False},
            "mechanical": {"passed": True, "failures": [], "repairs": []}}


def fake_chat(system, user, max_tokens=0, task="", shared=""):
    source = shared.split("\n\nFRAMEWORK NODES", 1)[0]
    passages = {int(u): text.strip() for u, text in re.findall(
        r"\[Unit (\d+)\]\n(.*?)(?=\n\n\[Unit |\Z)", source, re.S)}
    if task == "map":
        return {"chapters": [{"title": f"Chapter {u}", "first_unit": u, "last_unit": u,
                              "kind": "content"} for u in passages],
                "overview": {"purpose": "Use the book.", "effects": []}}
    if task == "extract":
        return {"nodes": [{**node(u, title=f"Step {u}", text=text), "id": i}
                          for i, (u, text) in enumerate(passages.items())]}
    if task == "fields":
        items = json.loads(user.split("Items:\n")[1])
        return {"items": [{"index": item["index"], "fields": node(item["units"][0],
                           text=passages[item["units"][0]])["fields"]} for item in items]}
    if task in {"logic", "edges", "repair"}:
        return {"graph_issues": [], "logic_issues": [], "logic_warnings": [], "edges": [], "items": []}
    if task == "judge":
        return {"warrants_reextract": False, "findings": []}
    if task == "meta":
        return {"purpose": "Use the book.", "effects": []}
    raise AssertionError(task)


def test_explicit_end_does_not_swallow_unmapped_content_as_reference():
    result = fx.chapters({"chapters": [
        {"title": "References", "first_unit": 1, "last_unit": 1, "kind": "reference"},
        {"title": "End", "first_unit": 4, "last_unit": 4, "kind": "content"}]}, ["ref", "rule", "method", "end"])
    assert result == [("References", [1], True), ("Unmapped units 2-3", [2, 3], False), ("End", [4], False)]


def test_reference_title_never_overrides_explicit_content():
    assert fx.chapters({"chapters": [{"title": "Notes on decisions", "first_unit": 1,
                                     "last_unit": 1, "kind": "content"}]}, ["Evaluate the options."]) == [
                                         ("Notes on decisions", [1], False)]


def test_overlaps_and_missing_ends_are_content_without_duplicate_or_lost_units():
    result = fx.chapters({"chapters": [
        {"title": "Refs", "first_unit": 1, "last_unit": 3, "kind": "reference"},
        {"title": "Methods", "first_unit": 2, "last_unit": 4, "kind": "content"},
        {"title": "Ref without end", "first_unit": 5, "kind": "reference"}]}, ["a", "b", "c", "d", "e"])
    assert [u for _, numbers, _ in result for u in numbers] == [1, 2, 3, 4, 5]
    assert result[1] == ("Overlapping chapter ranges 2-3", [2, 3], False)
    assert result[-1] == ("Unmapped units 5-5", [5], False)


def test_section_only_and_unrepresented_duplicates_do_not_complete_coverage():
    covered = fx.coverage(["rule", "rule"], [node(1, kind="section")])
    assert covered["unresolved"] == [1, 2]
    assert not covered["complete"]
    assert fx.coverage(["rule", "rule"], [node(1)])["units"][1] == {"unit": 2, "status": "duplicate", "of": 1}


def test_join_preserves_all_chapter_fields_quotes_and_original_parts():
    one, two = part(node(1)), part(node(2))
    before = copy.deepcopy([one, two])
    result = fx.join("Book", ["Check risk in chapter 1.", "Check risk in chapter 2."], [one, two])
    merged = result["nodes"][0]
    assert merged["units"] == [1, 2]
    assert merged["parts"] == [1, 2]
    assert [c["fields"]["Action"] for c in merged["contributions"]] == ["Action 1", "Action 2"]
    assert [c["fields"]["Source Quote"]["Quote"] for c in merged["contributions"]] == [
        "Check risk in chapter 1.", "Check risk in chapter 2."]
    assert [one, two] == before
    result["meta"] = fx._overview({})
    assert "Action 2" in fx.render(result) and "Done 2" in fx.render(result)


def test_near_duplicate_merge_preserves_both_definition_records():
    result = fx.join("Book", ["A.", "B."], [part(node(1, title="One", text="A.", kind="definition")),
                                           part(node(2, title="Two", text="B.", kind="definition"))])
    fx._merge(result, ["A.", "B."], {1: 0})
    assert len(result["nodes"]) == 1
    assert [c["title"] for c in result["nodes"][0]["contributions"]] == ["One", "Two"]
    assert result["coverage"]["complete"]


@pytest.mark.parametrize("field", ["Quote", "Core Sentence"])
def test_quote_grounding_rejects_invented_or_other_chapter_text(field):
    n = node(1, text="Real source.")
    n["fields"]["Source Quote"][field] = "Different source."
    result = part(n)
    result["coverage"] = fx.coverage(["Real source.", "Different source."], [n], [1])
    audit = fx.mechanical_audit(result, ["Real source.", "Different source."])
    assert not audit["passed"]
    assert any(field in error and "grounded" in error for error in audit["failures"])
    assert n["fields"]["Source Quote"][field] == "Different source."


def test_normalized_whitespace_quotes_remain_valid_and_long_quotes_are_not_truncated():
    n = node(1, text="Read the source.")
    result = part(n)
    result["coverage"] = fx.coverage(["Read\n the   source."], [n])
    assert fx.mechanical_audit(result, ["Read\n the   source."])["passed"]
    long = " ".join(["source"] * 61)
    n["fields"]["Source Quote"]["Quote"] = long
    assert not fx.mechanical_audit(result, [long])["passed"]
    assert n["fields"]["Source Quote"]["Quote"] == long


@pytest.mark.parametrize("operation", ["fill", "repair"])
def test_field_batches_cannot_mutate_other_chapters_or_batches(monkeypatch, operation):
    nodes = [node(i + 1) for i in range(7)]
    for i, n in enumerate(nodes):
        n["id"] = i
        n["fields"] = {}
    result = {"name": "Book", "nodes": nodes, "numbers": list(range(1, 8))}
    def malicious(system, user, max_tokens=0, task="", shared=""):
        return {"items": [{"index": 6, "fields": {"Action": "wrong batch"}, "ES": "wrong batch"}]}
    monkeypatch.setattr(fx, "chat_json", malicious)
    batches = fx.fill_fields(result, ["source"] * 7) if operation == "fill" else fx.repair_fields(result, ["source"] * 7)
    batches[0]()
    assert nodes[6]["fields"] == {}


def test_map_and_chapter_prompts_only_carry_their_source_window(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 50)
    calls = []
    def record(system, user, max_tokens=0, task="", shared=""):
        calls.append((task, shared))
        return fake_chat(system, user, max_tokens, task, shared)
    monkeypatch.setattr(fx, "chat_json", record)
    source = [f"Unique chapter {i}. Read carefully." for i in range(1, 5)]
    result = fx.build("Book", source)
    maps = [shared for task, shared in calls if task == "map"]
    assert len(maps) == 4
    assert all(len(re.findall(r"\[Unit \d+\]", shared)) == 1 for shared in maps)
    extracts = [shared for task, shared in calls if task == "extract"]
    assert len(extracts) == 4
    assert all(sum(text in shared for text in source) == 1 for shared in extracts)
    assert result["approved"] and result["coverage"]["complete"]
    assert [c["status"] for c in result["chapter_manifest"]] == ["complete"] * 4
    assert len(result["book_map"]["windows"]) == 4


def test_map_chapter_indexes_are_global_and_invalid_ranges_are_not_trusted(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 4)
    def mapped(system, user, max_tokens=0, task="", shared=""):
        u = int(re.search(r"\[Unit (\d+)\]", shared)[1])
        return {"chapters": [{"title": f"C{u}", "first_unit": u, "last_unit": u},
                             {"title": "outside", "first_unit": 99, "last_unit": 99}],
                "glossary": [{"term": f"T{u}", "chapter": 1, "units": [u, 99]}],
                "spine": [{"title": f"S{u}", "chapter": 1}],
                "links": [{"from_chapter": 1, "to_chapter": 1, "why": "self"}]}
    monkeypatch.setattr(fx, "chat_json", mapped)
    mapped = fx.map_book("Book", ["aaaa", "bbbb"])
    assert [c["chapter"] for c in mapped["glossary"]] == [1, 2]
    assert [c["units"] for c in mapped["glossary"]] == [[1], [2]]
    assert mapped["links"][1]["from_chapter"] == 2
    assert all(w["invalid_chapters"] == 1 for w in mapped["windows"])


def test_oversized_individual_unit_fails_before_any_model_call(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 10)
    monkeypatch.setattr(fx, "chat_json", lambda *a, **k: pytest.fail("provider should not be called"))
    with pytest.raises(ValueError, match="split it into smaller units"):
        fx.build("Book", ["a" * 11])


def test_map_context_is_bounded_without_discarding_stored_entries(monkeypatch):
    monkeypatch.setattr(fx, "MAP_CONTEXT_CHARS", 500)
    bookmap = {"chapters": [{"first_unit": 1, "last_unit": 1, "title": "One"}],
               "glossary": [{"chapter": 1, "term": "a" * 100} for _ in range(20)]}
    context = fx._map_for_parts(bookmap, [1])
    assert len(json.dumps(context, ensure_ascii=False)) <= 500
    assert context["omitted_context_entries"] > 0
    assert len(bookmap["glossary"]) == 20


@pytest.mark.parametrize("failure", ["coverage", "mechanical", "graph", "judgment"])
def test_approval_requires_all_checks_even_when_logic_is_clean(monkeypatch, failure):
    result = part(node(1, text="Source."))
    result["coverage"] = fx.coverage(["Source."], result["nodes"])
    result["meta"] = fx._overview({})
    if failure == "coverage":
        result["coverage"].update(complete=False, unresolved=[1])
    elif failure == "mechanical":
        result["mechanical"].update(passed=False, failures=["bad quote"])
    elif failure == "graph":
        result["logic"]["graph_issues"] = ["broken link"]
    else:
        result["judgment"]["warrants_reextract"] = True
    monkeypatch.setattr(fx, "_passes", lambda *a, **k: result)
    built = fx.build("Book", ["Source."])
    assert not built["approved"]
    assert built["chapter_manifest"][0]["status"] == "incomplete"


def test_failed_chapter_does_not_hide_finished_chapter_or_source_gap(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 25)
    def sometimes(system, user, max_tokens=0, task="", shared=""):
        if task == "extract" and "[Unit 2]" in shared:
            raise RuntimeError("synthetic failure")
        return fake_chat(system, user, max_tokens, task, shared)
    monkeypatch.setattr(fx, "chat_json", sometimes)
    result = fx.build("Book", ["Read chapter one.", "Read chapter two."])
    assert not result["approved"]
    assert result["coverage"]["unresolved"] == [2]
    assert [c["status"] for c in result["chapter_manifest"]] == ["complete", "incomplete"]
    assert "synthetic failure" in str(result["chapter_manifest"][1]["failures"])
    assert any(n["units"] == [1] for n in result["nodes"])


def test_chapter_workers_are_bounded(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 20)
    monkeypatch.setattr(fx, "chat_json", fake_chat)
    original = fx._passes
    lock = threading.Lock()
    active = maximum = 0
    def observed(*args, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.02)
            return original(*args, **kwargs)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(fx, "_passes", observed)
    built = fx.build("Book", [f"Read chapter {i}." for i in range(9)])
    assert built["approved"]
    assert 1 < maximum <= fx.CHAPTER_WORKERS


def test_absolute_prompt_budget_rejects_before_provider(monkeypatch):
    monkeypatch.setattr(fx, "MAX_PROMPT_CHARS", 10)
    monkeypatch.setattr(fx, "_post", lambda *a, **k: pytest.fail("provider must not run"))
    with pytest.raises(ValueError, match="bounded input"):
        fx.chat_json("x", "y", task="test")


def test_large_global_audit_covers_complete_nodes_and_cross_batch_edges(monkeypatch):
    nodes = [node(i + 1, title=f"Step {i}", text=f"Text of node {i}. " + "detail " * 12) for i in range(6)]
    for i, n in enumerate(nodes):
        n["id"] = i
    fw = {"name": "Book", "nodes": nodes, "edges": [
        {"from": 0, "to": 5, "type": "leads_to", "why": "across chapters"},
        {"from": 1, "to": 4, "type": "leads_to", "why": "across chapters"}]}
    # Budget fits two complete nodes but not the full book.
    longest = max(len(json.dumps(n)) for n in nodes)
    monkeypatch.setattr(fx, "GLOBAL_AUDIT_CHARS", longest * 2 + 700)
    calls = []
    def audited(system, user, max_tokens=0, task="", shared=""):
        calls.append((user, shared))
        return {"graph_issues": [], "logic_issues": [], "logic_warnings": []}
    monkeypatch.setattr(fx, "chat_json", audited)
    fx.audit_logic(fw, [n["content"] for n in nodes])
    scope = fw["logic"]["audit_scope"]
    assert scope["complete"]
    assert scope["reviewed_node_ids"] == list(range(6))
    assert scope["reviewed_edge_count"] == 2
    assert all(len(user) + len(shared) <= fx.GLOBAL_AUDIT_CHARS for user, shared in calls)
    assert any("0 -[leads_to]-> 5" in user and nodes[0]["content"] in shared and nodes[5]["content"] in shared
               for user, shared in calls)
    assert all(any(n["fields"]["Source Quote"]["Quote"] in shared and '"Done When"' in shared
                   for _, shared in calls) for n in nodes)


def test_oversized_complete_node_remains_visible_and_blocks_global_approval(monkeypatch):
    n = node(1, text="source " * 100)
    fw = {"name": "Book", "nodes": [n], "edges": []}
    monkeypatch.setattr(fx, "GLOBAL_AUDIT_CHARS", 100)
    monkeypatch.setattr(fx, "chat_json", lambda *a, **k: pytest.fail("oversized node must not be sent"))
    fx.audit_logic(fw, [n["content"]])
    assert not fw["logic"]["audit_scope"]["complete"]
    assert "unreviewed" in fw["logic"]["logic_issues"][0]
    assert fw["nodes"][0]["content"] == "source " * 100


def test_reference_chapter_has_explicit_ledger_and_retained_unit(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 25)
    def mapped(system, user, max_tokens=0, task="", shared=""):
        result = fake_chat(system, user, max_tokens, task, shared)
        if task == "map" and "[Unit 2]" in shared:
            result["chapters"][0]["kind"] = "reference"
        return result
    monkeypatch.setattr(fx, "chat_json", mapped)
    built = fx.build("Book", ["Use a careful method.", "Bibliography citation."])
    assert built["approved"]
    assert built["coverage"]["reference_units"] == [2]
    assert built["chapter_manifest"][1] == {
        "title": "Chapter 2", "first_unit": 2, "last_unit": 2, "units": [2], "kind": "reference",
        "part": None, "complete": True, "status": "reference", "failures": []}
    assert "reference" in built["document"]


def test_joined_contribution_is_checked_against_its_own_source(monkeypatch):
    one, two = node(1, text="First rule."), node(2, text="Second rule.")
    two["fields"]["Source Quote"]["Quote"] = "First rule."
    result = fx.join("Book", ["First rule.", "Second rule."], [part(one), part(two)])
    assert result["coverage"]["complete"]
    assert not fx.mechanical_audit(result, ["First rule.", "Second rule."])["passed"]


def test_global_provider_error_preserves_completed_chapter_results(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 25)
    def audit_failure(system, user, max_tokens=0, task="", shared=""):
        if task == "logic" and "THE WHOLE BOOK'S FRAMEWORK" in shared:
            raise RuntimeError("synthetic global audit failure")
        return fake_chat(system, user, max_tokens, task, shared)
    monkeypatch.setattr(fx, "chat_json", audit_failure)
    result = fx.build("Book", ["Read chapter one.", "Read chapter two."])
    assert not result["approved"]
    assert result["coverage"]["complete"]
    assert len(result["nodes"]) == 2
    assert all(c["complete"] for c in result["chapter_manifest"])
    assert "synthetic global audit failure" in str(result["logic"]["logic_issues"])


@pytest.mark.parametrize("task", ["logic", "judge"])
def test_missing_audit_response_is_not_approval(monkeypatch, task):
    def malformed(system, user, max_tokens=0, task="", shared=""):
        if task == target:
            return {}
        if task == "extend":
            return {"add": [], "change": []}
        return fake_chat(system, user, max_tokens, task, shared)
    target = task
    monkeypatch.setattr(fx, "chat_json", malformed)
    result = fx.build("Book", ["Read the source."])
    assert not result["approved"]


def test_malformed_nodes_do_not_claim_source_coverage():
    assert fx.coverage(["source"], [None, {}, {"type": "unknown", "units": [1], "content": "x"}])["unresolved"] == [1]


def test_large_merged_node_audits_all_contributions_without_cartesian_edges(monkeypatch):
    sources = [f"Read original source chapter {i}." for i in range(80)]
    pieces = [part(node(i + 1, text=text)) for i, text in enumerate(sources)]
    result = fx.join("Book", sources, pieces)
    monkeypatch.setattr(fx, "GLOBAL_AUDIT_CHARS", 4000)
    calls = []
    def audited(system, user, max_tokens=0, task="", shared=""):
        calls.append((user, shared))
        return {"graph_issues": [], "logic_issues": [], "logic_warnings": []}
    monkeypatch.setattr(fx, "chat_json", audited)
    before = copy.deepcopy(result["nodes"])
    fx.audit_logic(result, sources)
    scope = result["logic"]["audit_scope"]
    assert scope["complete"] and scope["reviewed_node_ids"] == [0]
    assert scope["reviewed_contribution_count"] == scope["total_contributions"] == 80
    assert result["nodes"] == before
    assert all(any(text in shared for _, shared in calls) for text in sources)
    assert all(len(user) + len(shared) <= 4000 for user, shared in calls)
    assert len(calls) < 80


def test_concurrent_identical_cached_calls_publish_atomically(tmp_path, monkeypatch):
    # Both responses may finish together; each needs its own staging file for the shared cache key.
    providers = threading.Barrier(2)
    writers = threading.Barrier(2)
    original_dump = json.dump
    def response(*args, **kwargs):
        providers.wait(timeout=5)
        return {"choices": [{"message": {"content": '{"answer": "kept"}'}}]}
    def dump(*args, **kwargs):
        result = original_dump(*args, **kwargs)
        writers.wait(timeout=5)
        return result
    monkeypatch.setenv("OPENROUTER_API_KEY", "disposable-test-key")
    monkeypatch.setattr(fx, "_post", response)
    monkeypatch.setattr(json, "dump", dump)
    cache_token = fx.CACHE.set(str(tmp_path))
    model_token = fx.MODEL.set("test/model")
    try:
        results = fx._parallel([lambda: fx.chat_json("same", "same", task="test") for _ in range(2)])
        assert results == [{"answer": "kept"}] * 2
        monkeypatch.setattr(fx, "_post", lambda *a, **k: pytest.fail("completed response should be reused"))
        assert fx.chat_json("same", "same", task="test") == {"answer": "kept"}
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        fx.MODEL.reset(model_token)
        fx.CACHE.reset(cache_token)


def test_mechanical_failure_repairs_existing_quote_without_reextract(monkeypatch):
    calls = []
    def repair(system, user, max_tokens=0, task="", shared=""):
        calls.append((task, user))
        result = fake_chat(system, user, max_tokens, task, shared)
        if task == "fields":
            result["items"][0]["fields"]["Source Quote"] = {"Quote": "invented", "Core Sentence": "invented"}
        if task == "repair":
            assert "not grounded" in user and "invented" in user
            # An initial cached bad repair must not prevent the next pass carrying updated feedback.
            if "pass 2" in user:
                result = {"items": [{"index": 0, "Source Quote": {"Quote": "Read the source.",
                                                                        "Core Sentence": "Read the source."}}]}
        return result
    monkeypatch.setattr(fx, "chat_json", repair)
    result = fx.build("Book", ["Read the source."])
    assert result["approved"] and result["passes"] == 2
    assert sum(task == "extract" for task, _ in calls) == 1
    assert not any(task == "extend" for task, _ in calls)
    assert result["nodes"][0]["fields"]["Action"] == "Action 1"
    assert result["nodes"][0]["fields"]["Source Quote"]["Quote"] == "Read the source."


def test_unrepaired_quote_stays_incomplete_despite_clean_judgment(monkeypatch):
    def bad(system, user, max_tokens=0, task="", shared=""):
        result = fake_chat(system, user, max_tokens, task, shared)
        if task == "fields":
            result["items"][0]["fields"]["Source Quote"] = {"Quote": "invented", "Core Sentence": "invented"}
        return result
    monkeypatch.setattr(fx, "chat_json", bad)
    result = fx.build("Book", ["Read the source."])
    assert not result["approved"] and result["passes"] == 2
    assert result["nodes"][0]["fields"]["Source Quote"]["Quote"] == "invented"


def test_unicode_and_distinct_words_do_not_collapse_canonical_nodes():
    pieces = [part(node(i + 1, title=title, kind="definition"))
              for i, title in enumerate(["风险", "收益", "Asses", "Asset", "Class", "Clas"])]
    result = fx.join("Book", ["source"] * 6, pieces)
    assert len(result["nodes"]) == 6
    assert fx._name("收益") != fx._name("风险")


def test_join_preserves_both_chapter_relationship_rationales():
    pieces = []
    for unit in (1, 2):
        a, b = node(unit, title="Principle", kind="principle"), node(unit, title="Action")
        b["id"] = 1
        piece = part(a)
        piece["nodes"] = [a, b]
        piece["edges"] = [{"from": 0, "to": 1, "type": "implemented_by", "why": f"Unique chapter rationale {unit}"}]
        pieces.append(piece)
    result = fx.join("Book", ["source"] * 2, pieces)
    result["meta"] = fx._overview({})
    assert len(result["edges"]) == 1
    assert [c["why"] for c in result["edges"][0]["contributions"]] == [
        "Unique chapter rationale 1", "Unique chapter rationale 2"]
    assert "Unique chapter rationale 2" in fx.render(result)
    assert "Unique chapter rationale 2" in fx._edges_block(result["edges"])


def test_short_book_still_maps_each_chapter(monkeypatch):
    monkeypatch.setattr(fx, "chat_json", fake_chat)
    result = fx.build("Book", ["First chapter rule.", "Second chapter rule."], book=True)
    assert result["approved"]
    assert len(result["chapter_manifest"]) == 2
    assert [c["title"] for c in result["chapter_manifest"]] == ["Chapter 1", "Chapter 2"]


@pytest.mark.parametrize("units", [["US", "us"], ["if ready:\n    act()", "if ready:\nact()"]])
def test_case_and_indentation_are_not_duplicate_source_units(units):
    result = fx.coverage(units, [node(1)])
    assert result["unresolved"] == [2]
    assert not result["complete"]


def test_map_windows_use_bounded_parallelism_and_keep_source_order(monkeypatch):
    monkeypatch.setattr(fx, "WINDOW_CHARS", 4)
    lock = threading.Lock()
    active = peak = 0
    def record(system, user, max_tokens=0, task="", shared=""):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(active, peak)
        try:
            time.sleep(0.02)
            return fake_chat(system, user, max_tokens, task, shared)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(fx, "chat_json", record)
    mapped = fx.map_book("Book", [f"{i:04d}" for i in range(8)])
    assert 1 < peak <= fx.CHAPTER_WORKERS
    assert [chapter["first_unit"] for chapter in mapped["chapters"]] == list(range(1, 9))


def test_large_merged_edge_audits_every_rationale_in_bounded_views(monkeypatch):
    a, b = node(1, title="First"), node(2, title="Second")
    b["id"] = 1
    rationales = [{"part": i, "chapter": f"Chapter {i}", "from": 0, "to": 1, "type": "leads_to",
                   "why": f"Unique rationale {i}: " + ("Detailed original relation. " * 35)} for i in range(40)]
    edge = {"from": 0, "to": 1, "type": "leads_to", "why": "Original", "contributions": rationales}
    fw = {"name": "Book", "nodes": [a, b], "edges": [edge]}
    before = copy.deepcopy(edge)
    calls = []
    def audit(system, user, max_tokens=0, task="", shared=""):
        calls.append((user, shared))
        return {"graph_issues": [], "logic_issues": [], "logic_warnings": []}
    monkeypatch.setattr(fx, "chat_json", audit)
    monkeypatch.setattr(fx, "GLOBAL_AUDIT_CHARS", 4000)
    fx.audit_logic(fw, [a["content"], b["content"]])
    scope = fw["logic"]["audit_scope"]
    assert scope["complete"] and scope["reviewed_edge_count"] == 1
    assert scope["reviewed_edge_contribution_count"] == scope["total_edge_contributions"] == 40
    assert len(scope["edge_contribution_endpoint_views"]) == 40
    assert all(any(r["why"] in user for user, _ in calls) for r in rationales)
    assert all(len(user) + len(shared) <= 4000 for user, shared in calls)
    assert fw["edges"][0] == before
    assert len(calls) < 40


@pytest.mark.parametrize("kind", ["case", "example"])
def test_every_substantive_node_requires_grounded_source_quote(kind):
    n = node(1, kind=kind, text="An invented story.")
    n["fields"] = {}
    result = part(n)
    result["coverage"] = fx.coverage(["An unrelated source."], [n])
    audit = fx.mechanical_audit(result, ["An unrelated source."])
    assert not audit["passed"]
    assert any("Quote" in failure and "grounded" in failure for failure in audit["failures"])
