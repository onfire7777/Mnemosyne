from collections import Counter
import pytest
from eval.compact_answering.train_partitions import assign


def test_whole_groups_are_stable_and_largest_group_is_not_split():
    sizes = {"a": 70, "b": 10, "c": 10, "d": 10}
    result = assign(sizes)
    counts = Counter()
    for group, part in result.items():
        counts[part] += sizes[group]
    assert counts == {"train": 80, "selection": 10, "calibration": 10}
    assert result == assign(dict(reversed(list(sizes.items()))))
    assert result["a"] == "train"


def test_ties_and_oversized_components_are_explicit():
    assert assign({"a": 98, "b": 1, "c": 1}) == {
        "a": "train",
        "b": "selection",
        "c": "calibration",
    }
    assert assign({"only": 100}) == {"only": "train"}
    for sizes in ({}, {"a": 0}, {"a": -1}, {"a": True}, {"a": 1.5}):
        with pytest.raises(ValueError):
            assign(sizes)


def test_plan_is_source_bound_and_never_overwrites(tmp_path):
    import hashlib
    import json
    from eval.compact_answering.train_partitions import plan

    grouped = tmp_path / "groups"
    grouped.mkdir()
    data = "".join(
        json.dumps(
            {
                "row_identity_sha256": str(i),
                "group_id": str(i // 2),
                "repository": "test-source",
            }
        )
        + "\n"
        for i in range(20)
    ).encode()
    (grouped / "groups.jsonl").write_bytes(data)
    (grouped / "summary.json").write_text(
        json.dumps(
            {
                "schema": "mnemosyne.compact-train-groups.v1",
                "training_admitted": False,
                "groups_sha256": hashlib.sha256(data).hexdigest(),
                "summary": {"rows": 20, "groups": 10},
            }
        )
    )
    output = tmp_path / "plan"
    result = plan(grouped, output)
    assert result["rows"] == {"train": 16, "selection": 2, "calibration": 2}
    assert result["training_admitted"] is False
    assert json.loads((output / "partitions.json").read_text()) == result
    with pytest.raises(FileExistsError):
        plan(grouped, output)
    (grouped / "groups.jsonl").write_bytes(data + b"\n")
    with pytest.raises(ValueError, match="drift"):
        plan(grouped, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
