"""Public skill tools and learning resolve the same currently configured library."""

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.experience.integration import learning_skill_store
from mnemosyne.mcp_tools import MemoryTools
from mnemosyne.skills import SkillStore


def library(tmp_path, name):
    path = tmp_path / f"{name}.md"
    path.write_text(f"---\nname: {name}\n---\nRead the {name} checklist.")
    store = SkillStore(str(tmp_path / f"{name}.sqlite"))
    imported = store.import_skill(str(path), "")
    return store, imported["skill_id"]


def test_old_public_skill_tools_follow_explicit_library_reconfiguration(tmp_path):
    engine = LocalMemoryEngine()
    first, first_id = library(tmp_path, "first")
    current, current_id = library(tmp_path, "current")
    old_tools = MemoryTools(engine, skill_store=first)
    assert old_tools.framework_status(first_id)["name"] == "first"
    new_tools = MemoryTools(engine, skill_store=current)
    assert old_tools.framework_status(current_id)["name"] == "current"
    assert new_tools.framework_status(current_id)["name"] == "current"
    assert old_tools._learning_runtime().skill_store is current


def test_default_tools_cannot_republish_an_old_cached_library(tmp_path):
    engine = LocalMemoryEngine()
    first, first_id = library(tmp_path, "first")
    current, current_id = library(tmp_path, "current")
    old_tools = MemoryTools(engine, skill_store=first)
    old_tools.framework_status(first_id)
    current_tools = MemoryTools(engine, skill_store=current)
    default_tools = MemoryTools(engine)
    assert engine._learning_configuration["skill_store"] is current
    assert default_tools.framework_status(current_id)["name"] == "current"
    assert current_tools._learning_runtime().skill_store is current


def test_shared_library_resolver_prefers_current_configuration_over_cache(tmp_path):
    engine = LocalMemoryEngine()
    first, first_id = library(tmp_path, "first")
    current, _ = library(tmp_path, "current")
    old_tools = MemoryTools(engine, skill_store=first)
    old_tools.framework_status(first_id)
    current_tools = MemoryTools(engine, skill_store=current)
    assert learning_skill_store(engine) is current
    assert current_tools._learning_runtime().skill_store is current
