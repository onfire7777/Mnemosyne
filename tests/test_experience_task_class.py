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
