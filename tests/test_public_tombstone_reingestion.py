"""Public tombstone behavior; not an admitted M08 or M09 benchmark."""
from eval.harness.cli_driver import MnemoCLI


def test_identical_reingestion_preserves_tombstone_without_harming_controls(tmp_path):
    cli = MnemoCLI(store=str(tmp_path / "store.json"), timeout_s=30)

    def ingest(tenant, content):
        return cli.run("ingest", "--tenant", tenant, "--user", "probe", "--source-type", "note",
                       "--content", content, "--no-enqueue-consolidation").json["cid"]

    def search(tenant, query):
        result = cli.search(tenant, query)
        return result["abstained"], [hit["id"] for hit in result["hits"]]

    content = "Synthetic archive code is cobalt-482."
    target = ingest("probe", content)
    control = ingest("probe", "Unrelated orchard code is amber-193.")
    other = ingest("other", content)
    assert target != other
    assert search("probe", "cobalt-482") == (False, [target])
    for _ in range(2):
        receipt = cli.forget("probe", target, erasure_mode="tombstone_recompute")
        assert receipt["erased"] is True and receipt["cid"] == target
        assert receipt["erasure_mode"] == "tombstone_recompute"
        assert search("probe", "cobalt-482") == (True, [])
        assert ingest("probe", content) == target
        assert search("probe", "cobalt-482") == (True, [])
        assert search("probe", "amber-193") == (False, [control])
        assert search("other", "cobalt-482") == (False, [other])
