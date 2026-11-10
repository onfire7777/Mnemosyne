import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.receipts import digest
from mnemosyne.experience.runtime import LearningRuntime
from mnemosyne.experience.task_class import classify


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("fix the cache invalidation bug", "fix the authentication failure"),
        ("deploy image version 1.2", "deploy image version 1.3"),
        ("delete /data/users", "delete /backup/users"),
        ("run rm -rf cache", "run rm rf cache"),
        ("fix cache invalidation", "fix cache invalidation without deleting entries"),
        ("分析缓存错误", "分析登录错误"),
        ("delete /Data/A", "delete /Data/a"),
        ("print('a  b')", "print('a b')"),
    ],
)
def test_automatic_task_classes_preserve_complete_request(first, second):
    assert classify(first, ["shell"]) != classify(second, ["shell"])


def test_automatic_task_classes_normalize_formatting_and_tool_availability():
    assert classify(
        "  fix the cache invalidation bug  ", ["read", "shell", "read"]
    ) == classify("fix the cache invalidation bug", ["shell", "read"])
    assert classify("fix the cache invalidation bug", ["read"]) != classify(
        "fix the cache invalidation bug", ["shell"]
    )


def test_explicit_task_type_groups_different_phrasings_without_rewriting_identity():
    task = "cache-maintenance:v1"
    assert classify("fix the cache invalidation bug", ["shell"], task) == task
    assert classify("repair stale cache entries", ["read"], task) == task


def test_request_identity_does_not_reuse_ambiguous_legacy_namespace():
    legacy = "lexical:" + digest(["fix", ["shell"], ["fix", "the"]])[:20]
    assert classify("fix the cache invalidation bug", ["shell"]) != legacy
    assert classify("fix the authentication failure", ["shell"]) != legacy
    assert classify("repair stale cache entries", [], legacy) == legacy


def test_request_identity_does_not_reuse_casefolded_v2_namespace():
    prior = "lexical:v2:" + digest(["delete /data/a", ["shell"]])[:32]
    assert classify("delete /Data/A", ["shell"]) != prior
    assert classify("delete /data/a", ["shell"]) != prior


def test_runtime_keeps_automatic_task_classes_separate_after_reload(tmp_path):
    path = tmp_path / "memory.json"
    engine = LocalMemoryEngine(store_path=path)
    runtime = LearningRuntime(engine)
    cache = runtime.prepare_context(
        "t", "u", "cache", "fix the cache invalidation bug", ["shell"]
    )
    episode = runtime.observe_turn(
        "t",
        "u",
        "cache",
        "fix the cache invalidation bug",
        "fixed",
        receipt_ids=[cache["receipt_id"]],
    )
    engine.close()

    reopened = LocalMemoryEngine(store_path=path)
    restored = LearningRuntime(reopened)
    authentication = restored.prepare_context(
        "t", "u", "authentication", "fix the authentication failure", ["shell"]
    )
    repeated_cache = restored.prepare_context(
        "t", "u", "cache-again", "fix the cache invalidation bug", ["shell"]
    )
    assert authentication["task_class"] != cache["task_class"]
    assert repeated_cache["task_class"] == cache["task_class"]
    assert (
        restored.episode("t", episode["episode_id"])["task_class"]
        == cache["task_class"]
    )
    reopened.close()


def test_runtime_consumes_legacy_receipts_without_reclassifying_them(tmp_path):
    path = tmp_path / "memory.json"
    engine = LocalMemoryEngine(store_path=path)
    runtime = LearningRuntime(engine)
    legacy = "lexical:" + digest(["fix", ["shell"], ["fix", "the"]])[:20]
    old = runtime.prepare_context(
        "t", "u", "old", "fix the cache invalidation bug", ["shell"], task_type=legacy
    )
    engine.close()

    reopened = LocalMemoryEngine(store_path=path)
    restored = LearningRuntime(reopened)
    recorded = restored.writer.read("t")["receipts"][old["receipt_id"]]
    episode = restored.observe_turn(
        "t",
        "u",
        "old",
        "fix the cache invalidation bug",
        "fixed",
        receipt_ids=[old["receipt_id"]],
    )
    automatic = restored.prepare_context(
        "t", "u", "new", "fix the cache invalidation bug", ["shell"]
    )
    assert restored.episode("t", episode["episode_id"])["task_class"] == legacy
    assert restored.writer.read("t")["receipts"][old["receipt_id"]] == recorded
    assert automatic["task_class"] != legacy
    reopened.close()


def test_runtime_reuses_a_task_and_scoped_lesson_for_a_bounded_paraphrase():
    runtime = LearningRuntime(LocalMemoryEngine())
    query = "Summarize the build report"
    first = runtime.prepare_context("t", "u", "original", query)
    result = runtime.observe_turn("t", "u", "original", query, "long answer",
                                  receipt_ids=[first["receipt_id"]])
    runtime.record_signal("t", episode_id=result["episode_id"], kind="correction", value=-1,
                          evidence="Use bullet points for the build report.", final=True)
    runtime.consolidate("t")
    paraphrase = "Please give me a summary of the build report"
    contexts = [runtime.prepare_context("t", "u", str(i), paraphrase) for i in range(2)]
    assert all(item["task_class"] == first["task_class"] for item in contexts)
    assert any(item["lessons"] for item in contexts)
    receipt = runtime.writer.read("t")["receipts"][contexts[0]["receipt_id"]]
    assert receipt["query"] == paraphrase
    assert receipt["task_scope_query"] == query
    assert receipt["task_match"]["matched_episode_id"] == result["episode_id"]


@pytest.mark.parametrize("query", [
    "Summarize the authentication report", "Do not summarize the build report",
    "Summarize the build report without bullet points", "Summarize the Build report",
    "Summarize the build report version 2",
])
def test_task_reuse_preserves_entities_negation_constraints_and_literals(query):
    runtime = LearningRuntime(LocalMemoryEngine())
    first = runtime.prepare_context("t", "u", "original", "Summarize the build report")
    runtime.observe_turn("t", "u", "original", "Summarize the build report", "",
                         receipt_ids=[first["receipt_id"]])
    assert runtime.prepare_context("t", "u", "other", query)["task_class"] != first["task_class"]


def test_task_reuse_preserves_owner_tools_and_risk_and_survives_reload(tmp_path):
    path = tmp_path / "memory.json"
    engine = LocalMemoryEngine(store_path=path)
    runtime = LearningRuntime(engine)
    first = runtime.prepare_context("t", "u", "original", "Fix the cache bug", ["shell"])
    runtime.observe_turn("t", "u", "original", "Fix the cache bug", "",
                         receipt_ids=[first["receipt_id"]])
    engine.close()
    reopened = LocalMemoryEngine(store_path=path)
    runtime = LearningRuntime(reopened)
    paraphrase = "Please repair the cache bug"
    assert runtime.prepare_context("t", "u", "same", paraphrase, ["shell"])["task_class"] == first["task_class"]
    assert runtime.prepare_context("t", "other", "owner", paraphrase, ["shell"])["task_class"] != first["task_class"]
    assert runtime.prepare_context("t", "u", "tools", paraphrase, ["read"])["task_class"] != first["task_class"]
    assert runtime.prepare_context("t", "u", "risk", paraphrase, ["shell"], risk_level="high")["task_class"] != first["task_class"]
    reopened.close()


@pytest.mark.parametrize("observed", [False, True])
def test_paraphrase_scope_is_erased_with_its_original_source(observed):
    runtime = LearningRuntime(LocalMemoryEngine())
    original = "Summarize the private build report"
    first = runtime.prepare_context("t", "u", "first", original)
    recorded = runtime.observe_turn("t", "u", "first", original, "",
                                    receipt_ids=[first["receipt_id"]])
    source = runtime.episode("t", recorded["episode_id"])["source_cids"][0]
    alias = runtime.prepare_context("t", "u", "second", "Give me a summary of the private build report")
    receipt = runtime.writer.read("t")["receipts"][alias["receipt_id"]]
    assert source in receipt["source_cids"]
    assert receipt["task_scope_query"] == original
    if observed:
        runtime.observe_turn("t", "u", "second", "Give me a summary of the private build report", "",
                             receipt_ids=[alias["receipt_id"]])
    runtime.erase("t", source)
    saved = runtime.writer.read("t")
    assert saved["receipts"][alias["receipt_id"]]["task_scope_query"] == ""
    assert saved["receipts"][alias["receipt_id"]]["task_match"] is None
    again = runtime.prepare_context("t", "u", "third", "Give me a summary of the private build report")
    assert again["task_class"] != first["task_class"]


def test_exact_repetition_does_not_inherit_old_sources_and_aliases_do_not_chain():
    runtime = LearningRuntime(LocalMemoryEngine())
    query = "Summarize the build report"
    first = runtime.prepare_context("t", "u", "first", query)
    observed = runtime.observe_turn("t", "u", "first", query, "",
                                    receipt_ids=[first["receipt_id"]])
    exact = runtime.prepare_context("t", "u", "exact", query)
    receipt = runtime.writer.read("t")["receipts"][exact["receipt_id"]]
    assert receipt["task_match"] is None
    # Exact repetition inherits no alias sources. Any custody here belongs to
    # memories independently retrieved and actually delivered in this turn.
    assert set(receipt["source_cids"]) == {cid for cids in receipt["item_sources"].values() for cid in cids}
    alias_query = "Give me a summary of the build report"
    alias = runtime.prepare_context("t", "u", "alias", alias_query)
    runtime.observe_turn("t", "u", "alias", alias_query, "",
                         receipt_ids=[alias["receipt_id"]])
    repeated = runtime.prepare_context("t", "u", "repeated", alias_query)
    repeated_receipt = runtime.writer.read("t")["receipts"][repeated["receipt_id"]]
    assert repeated_receipt["task_match"]["matched_episode_id"] == observed["episode_id"]
    assert repeated_receipt["task_match"]["source_cids"] == runtime.episode("t", observed["episode_id"])["source_cids"]
