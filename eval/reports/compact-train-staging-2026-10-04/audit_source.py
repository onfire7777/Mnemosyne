"""Independent streaming check against pinned raw parquet rows (no row transformer import)."""

import hashlib
import json
from pathlib import Path
import sys
import pyarrow.parquet as pq

raw, staged = map(Path, sys.argv[1:])
receipt = json.loads((staged / "staging.json").read_text())
rejected = {
    json.loads(line)["row_sha256"] for line in (staged / "rejected.jsonl").open()
}
counts = {"source_rows": 0, "retained_rows": 0, "rejected_rows": 0, "verified_spans": 0}
for name, expected in receipt["files"].items():
    with (staged / name).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"]
    assert (staged / name).stat().st_size == expected["bytes"]
with (staged / "rows.jsonl").open() as output:
    for source in receipt["sources"]:
        file = raw / source["repository"] / source["revision"] / source["path"]
        with file.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == source["sha256"]
        if not source["path"].endswith(".parquet"):
            continue
        for batch in pq.ParquetFile(file).iter_batches(
            batch_size=64, use_threads=False
        ):
            for row in batch.to_pylist():
                counts["source_rows"] += 1
                h = hashlib.sha256(
                    json.dumps(
                        row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest()
                if h in rejected:
                    counts["rejected_rows"] += 1
                    continue
                record = json.loads(next(output))
                assert (
                    record["raw_row_sha256"] == h and record["upstream_id"] == row["id"]
                )
                assert record["source"] == source and record["split"] == "train"
                assert record["question"] == row["question"]
                assert (
                    record["training_admitted"] is False
                    and record["overlap_verdict"] == "unchecked"
                )
                squad = source["repository"] == "rajpurkar/squad_v2"
                contexts = (
                    [row["context"]]
                    if squad
                    else ["".join(s) for s in row["context"]["sentences"]]
                )
                titles = [row["title"]] if squad else row["context"]["title"]
                assert [d["context"] for d in record["documents"]] == contexts
                assert [d["title"] for d in record["documents"]] == titles
                for span in record["spans"]:
                    context = contexts[span["document"]]
                    assert (
                        context[span["char_start"] : span["char_end"]] == span["answer"]
                    )
                    assert (
                        context.encode()[span["byte_start"] : span["byte_end"]].decode()
                        == span["answer"]
                    )
                    if squad:
                        assert (span["answer"], span["char_start"]) in zip(
                            row["answers"]["text"], row["answers"]["answer_start"]
                        )
                    else:
                        assert span["answer"] == row["answer"] and row[
                            "answer"
                        ].casefold() not in ("yes", "no")
                        sentences = row["context"]["sentences"][span["document"]]
                        supported = False
                        for title, sid in zip(
                            row["supporting_facts"]["title"],
                            row["supporting_facts"]["sent_id"],
                        ):
                            if title == titles[span["document"]]:
                                start = sum(map(len, sentences[:sid]))
                                supported |= (
                                    start
                                    <= span["char_start"]
                                    < span["char_end"]
                                    <= start + len(sentences[sid])
                                )
                        assert supported
                    counts["verified_spans"] += 1
                if record["target_kind"] == "null":
                    assert squad and not row["answers"]["text"] and not record["spans"]
                if record["target_kind"] == "span":
                    assert record["spans"]
                counts["retained_rows"] += 1
    assert not output.read()
assert counts["rejected_rows"] == len(rejected)
print(
    json.dumps(
        {
            "schema": "compact-train-source-audit/v1",
            "counts": counts,
            "all_retained_rows_checked_against_raw_source": True,
            "training_admitted": False,
        },
        indent=2,
    )
)
