"""Exact-source staging for approved TRAIN rows; never grants training admission.

PyArrow is optional and used only by the offline CLI. The pure row validators
use the standard library. No learned tokenizer, model or protected data is read.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import unicodedata

from eval.compact_answering.train_intake import ASSETS

NORMALIZER = "nfkc-casefold-whitespace-v1"


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text(value, *, empty=False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError("invalid text")
    value.encode("utf-8")
    return value


def fingerprint(value: str) -> dict:
    return {"raw_sha256": sha(value), "normalized_sha256": sha(normalize(value))}


def document(title: str, context: str) -> dict:
    return {
        "title": title,
        "context": context,
        "hashes": {"title": fingerprint(title), "context": fingerprint(context)},
        "grouping_keys": [
            "title:" + sha(normalize(title)),
            "context:" + sha(normalize(context)),
        ],
    }


def span(context: str, answer: str, start: int, doc: int) -> dict:
    if (
        type(start) is not int
        or start < 0
        or not answer
        or context[start : start + len(answer)] != answer
    ):
        raise ValueError("answer does not match its exact source offset")
    end = start + len(answer)
    return {
        "document": doc,
        "char_start": start,
        "char_end": end,
        "byte_start": len(context[:start].encode("utf-8")),
        "byte_end": len(context[:end].encode("utf-8")),
        "answer": answer,
        "hashes": fingerprint(answer),
    }


def stage_row(row: dict, family: str) -> dict:
    if not isinstance(row, dict):
        raise ValueError("row must be an object")
    upstream_id, question = text(row["id"]), text(row["question"])
    spans, documents, supports = [], [], []
    if family == "squad":
        context, title = text(row["context"]), text(row["title"])
        documents = [document(title, context)]
        answers = row["answers"]
        labels, offsets = answers["text"], answers["answer_start"]
        if (
            not isinstance(labels, list)
            or not isinstance(offsets, list)
            or len(labels) != len(offsets)
        ):
            raise ValueError("answer arrays differ")
        for answer, offset in zip(labels, offsets):
            spans.append(span(context, text(answer), offset, 0))
        mode = "span" if spans else "null"
        answer_hashes = [fingerprint(text(a)) for a in labels]
    elif family == "hotpot":
        answer = text(row["answer"])
        titles, paragraphs = row["context"]["title"], row["context"]["sentences"]
        if (
            not isinstance(titles, list)
            or not isinstance(paragraphs, list)
            or not titles
            or len(titles) != len(paragraphs)
        ):
            raise ValueError("context arrays differ")
        if len(set(titles)) != len(titles):
            raise ValueError("ambiguous duplicate document title")
        boundaries = []
        for title, sentences in zip(titles, paragraphs):
            text(title)
            if not isinstance(sentences, list) or not sentences:
                raise ValueError("invalid sentence array")
            # Preserve upstream sentence bytes exactly; never invent a separator.
            starts, offset = [], 0
            for sentence in sentences:
                starts.append(offset)
                offset += len(text(sentence, empty=True))
            context = "".join(sentences)
            documents.append(document(title, context))
            boundaries.append(starts)
        support_titles, sentence_ids = (
            row["supporting_facts"]["title"],
            row["supporting_facts"]["sent_id"],
        )
        if (
            not isinstance(support_titles, list)
            or not isinstance(sentence_ids, list)
            or not support_titles
            or len(support_titles) != len(sentence_ids)
        ):
            raise ValueError("support arrays differ")
        for title, sentence_id in zip(support_titles, sentence_ids):
            if title not in titles or type(sentence_id) is not int:
                raise ValueError("unknown support reference")
            doc = titles.index(title)
            if sentence_id < 0 or sentence_id >= len(paragraphs[doc]):
                raise ValueError("support sentence out of range")
            support = {"document": doc, "sentence": sentence_id}
            if support in supports:
                continue
            supports.append(support)
            sentence = paragraphs[doc][sentence_id]
            if answer.casefold() not in {"yes", "no"}:
                start = sentence.find(answer)
                while start >= 0:
                    spans.append(
                        span(
                            documents[doc]["context"],
                            answer,
                            boundaries[doc][sentence_id] + start,
                            doc,
                        )
                    )
                    start = sentence.find(answer, start + 1)
        # An absent exact supporting span is not an upstream no-answer label.
        mode = "span" if spans else "ranking-only"
        answer_hashes = [fingerprint(answer)]
    else:
        raise ValueError("unsupported source family")
    return {
        "upstream_id": upstream_id,
        "question": question,
        "question_hashes": fingerprint(question),
        "documents": documents,
        "spans": spans,
        "supporting_facts": supports,
        "answer_hashes": answer_hashes,
        "target_kind": mode,
        "normalizer": NORMALIZER,
        "overlap_verdict": "unchecked",
        "training_admitted": False,
    }


def stage(intake: Path, destination: Path) -> dict:
    import pyarrow
    import pyarrow.parquet as pq

    if pyarrow.__version__ != "23.0.1":
        raise ValueError("staging requires pyarrow 23.0.1")
    transform = sha(Path(__file__).read_text())
    sources = []
    # Verify fixed pins independently of potentially stale intake receipts.
    for repo, revision, name, size, digest in ASSETS:
        path = intake / repo / revision / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError("missing, nonregular or resized asset")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise ValueError("asset hash drift")
        sources.append(
            {"repository": repo, "revision": revision, "path": name, "sha256": digest}
        )
    destination.mkdir(parents=True, exist_ok=False)
    counts, seen = Counter(), set()
    partial = destination / "rows.jsonl.partial"
    rejected = destination / "rejected.jsonl.partial"
    with partial.open("x") as output, rejected.open("x") as failures:
        for source in sources:
            if not source["path"].endswith(".parquet"):
                continue
            family = (
                "squad" if source["repository"] == "rajpurkar/squad_v2" else "hotpot"
            )
            path = intake / source["repository"] / source["revision"] / source["path"]
            for batch in pq.ParquetFile(path).iter_batches(
                batch_size=128, use_threads=False
            ):
                for row in batch.to_pylist():
                    counts[family + "/input"] += 1
                    raw_hash = sha(
                        json.dumps(
                            row,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                    try:
                        record = stage_row(row, family)
                        key = (source["repository"], record["upstream_id"])
                        if key in seen:
                            raise ValueError("duplicate upstream id")
                        seen.add(key)
                    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
                        counts[family + "/rejected"] += 1
                        failures.write(
                            json.dumps(
                                {
                                    "source": source,
                                    "row_sha256": raw_hash,
                                    "error": str(exc),
                                }
                            )
                            + "\n"
                        )
                        continue
                    record.update(
                        source=source,
                        split="train",
                        raw_row_sha256=raw_hash,
                        transform_sha256=transform,
                        license="CC-BY-SA-4.0",
                    )
                    output.write(
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    )
                    counts[family + "/" + record["target_kind"]] += 1
        output.flush()
        os.fsync(output.fileno())
        failures.flush()
        os.fsync(failures.fileno())
    files = {}
    for path in (partial, rejected):
        final = path.with_suffix("")
        os.link(path, final)
        path.unlink()
        with final.open("rb") as stream:
            files[final.name] = {
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                "bytes": final.stat().st_size,
            }
    receipt = {
        "schema": "mnemosyne.compact-train-staging.v1",
        "sources": sources,
        "transform_sha256": transform,
        "normalizer": NORMALIZER,
        "pyarrow": pyarrow.__version__,
        "counts": dict(counts),
        "files": files,
        "training_admitted": False,
        "overlap_verdict": "unchecked",
        "partition_status": "unassigned",
        "entity_clustering": "not-performed",
    }
    temporary = destination / "staging.json.partial"
    with temporary.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, destination / "staging.json")
    temporary.unlink()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intake", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    receipt = stage(args.intake, args.destination)
    print(json.dumps(receipt["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
