import pytest

from mnemosyne.engine import LocalMemoryEngine
from mnemosyne.learning import Procedure
from mnemosyne.mcp_tools import MemoryTools


@pytest.mark.parametrize("method", ["procedure_validate", "procedure_promote"])
def test_legacy_procedure_tools_do_not_bypass_outcome_gate(method):
    tools = MemoryTools(LocalMemoryEngine())
    procedure = Procedure(
        "t", "observed_sequence", "unverified", "Read source.", {}, status="candidate"
    )
    tools.learning.procedures[procedure.id] = procedure
    result = getattr(tools, method)(procedure.id, role="operator", source_trust_tier=0)
    assert result["status"] == "candidate"
    assert result["promoted"] is False
    assert result["gate"]["failed_cases"] == ["outcome_grounded_sources_required"]
    artifacts = tools._learning_runtime().writer.read("t")["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[procedure.id]["origin"] == "legacy"
    assert artifacts[procedure.id]["state"] == "candidate"
    assert tools.metrics.snapshot().counters.get("gate.promotions", 0) == 0
