"""Bounded provider windows with explicit, resumable source coverage."""
from __future__ import annotations

import json

MAX_PASSES_PER_WINDOW = 8
MAX_STALLS = 3


def select_windows(spans, cursor=None, *, max_chars=12000, max_items=16):
    cursor = cursor if isinstance(cursor, dict) else {}
    offset = cursor.get("offset", 0)
    offset = offset if type(offset) is int and offset >= 0 else 0
    pending = [span for span in spans if span["end"] > offset]
    selected, size = [], 0
    for span in pending:
        if selected and (len(selected) >= max_items or size + len(span["quote"]) > max_chars):
            break
        selected.append(span)
        size += len(span["quote"])
    stalls = cursor.get("stalls", 0)
    return selected, pending[len(selected):], {"offset": offset,
        "already_proposed": list(cursor.get("already_proposed", [])),
        "stalls": stalls if type(stalls) is int and stalls >= 0 else 0}


def advance_coverage(cursor, selected, remaining, response, *, claim_limit):
    """Saturation is unfinished work, never evidence that a source is covered.

    A provider may declare the supplied window complete. Legacy providers that
    return fewer than their limit also finish that window. Saturated output
    keeps the window pending and is backed off by the worker. Both the number
    of passes over one window and the number of passes that add nothing are
    bounded, so a misbehaving provider cannot hold the rest of a source back.
    An unusable response is passed as ``None`` and counts as adding nothing.
    """
    usable = isinstance(response, dict) and isinstance(response.get("claims"), list)
    rows = response["claims"] if usable else []
    prior = cursor.get("already_proposed", [])
    seen = {json.dumps(item, sort_keys=True) for item in prior}
    combined = list(prior)
    allowed = {(span["start"], span["end"]): span for span in selected}
    for row in rows[:claim_limit]:
        if not isinstance(row, dict):
            continue
        span = row.get("span")
        if (not isinstance(span, dict) or type(span.get("start")) is not int or type(span.get("end")) is not int
                or allowed.get((span["start"], span["end"])) != span
                or not all(isinstance(row.get(key), str) and 0 < len(row[key]) <= 500
                           for key in ("subject", "predicate", "object"))):
            continue
        item = {key: row[key] for key in ("subject", "predicate", "object")}
        item["span"] = {key: span[key] for key in ("start", "end")}
        encoded = json.dumps(item, sort_keys=True)
        if encoded not in seen:
            combined.append(item)
            seen.add(encoded)
    complete = usable and (response.get("coverage_complete") is True or (
        response.get("coverage_complete") is not False and len(rows) < claim_limit))
    stalled = len(combined) == len(prior)
    stalls = cursor.get("stalls", 0) + 1 if stalled else 0
    if not complete and stalls < MAX_STALLS and len(combined) < MAX_PASSES_PER_WINDOW * claim_limit:
        return {"provider_pending": True, "provider_cursor": {
            "offset": cursor["offset"], "already_proposed": combined, "stalls": stalls},
            "coverage_stalled": stalled}
    offset = selected[-1]["end"] if selected else cursor["offset"]
    return {"provider_pending": bool(remaining), "provider_cursor": {
        "offset": offset, "already_proposed": [], "stalls": 0}, "coverage_complete": not remaining}
