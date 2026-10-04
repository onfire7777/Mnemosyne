"""Audit membership coverage and shared-document edges using the frozen key policy."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

from eval.compact_answering.train_groups import document_keys
from eval.compact_answering.train_rows import sha

staged, grouped = map(Path, sys.argv[1:])
receipt = json.loads((grouped / "summary.json").read_text())
with (grouped / "groups.jsonl").open("rb") as stream:
    assert hashlib.file_digest(stream, "sha256").hexdigest() == receipt["groups_sha256"]
with (staged / "rows.jsonl").open("rb") as stream:
    assert (
        hashlib.file_digest(stream, "sha256").hexdigest()
        == receipt["staged_rows"]["sha256"]
    )
members, sizes, families, minimum = {}, Counter(), defaultdict(Counter), {}
for line in (grouped / "groups.jsonl").open():
    record = json.loads(line)
    identity, group = record["row_identity_sha256"], record["group_id"]
    assert identity not in members
    members[identity] = record
    sizes[group] += 1
    families[group][record["repository"]] += 1
    minimum[group] = min(minimum.get(group, identity), identity)
assert all(g == smallest for g, smallest in minimum.items())
keys, seen = {}, set()
for line in (staged / "rows.jsonl").open():
    row = json.loads(line)
    identity = sha(
        json.dumps(
            [row["source"]["repository"], row["upstream_id"]], separators=(",", ":")
        )
    )
    assert identity not in seen
    seen.add(identity)
    member = members[identity]
    assert member["raw_row_sha256"] == row["raw_row_sha256"]
    assert member["repository"] == row["source"]["repository"]
    for document in row["documents"]:
        for key in document_keys(document):
            assert keys.setdefault(key, member["group_id"]) == member["group_id"]
assert seen == set(members)
largest = sizes.most_common(1)[0][0]
print(
    json.dumps(
        {
            "schema": "compact-train-group-edge-audit/v1",
            "rows_checked": len(seen),
            "document_keys_checked": len(keys),
            "groups": len(sizes),
            "shared_document_edges_crossing_groups": 0,
            "largest_group_rows": sizes[largest],
            "largest_group_by_source": dict(families[largest]),
            "outside_largest_by_source": dict(
                sum((c for g, c in families.items() if g != largest), Counter())
            ),
            "partition_status": "unassigned",
            "training_admitted": False,
        },
        indent=2,
    )
)
