"""Corrections for rows already in market/history/*.jsonl (2026-10-17).

The history files are ADD-only: a row that was parsed wrongly (a price cell read as one long number, a share
offering tagged as a convertible) stays in its file forever, and append_history() skips a fixed copy of it
because its key is already there. So a fix is recorded HERE instead, next to the raw row, and the builders
(market/insiders.py, market/financing.py) apply it when they write the web files. The raw row is never changed.

market/history/corrections.jsonl, one JSON object per line (ADD-only like every history file):
    {"id": "<dataset>|<match>|<set>",            dedup key, built by correction()
     "dataset": "insiders_kr",                   the history file the row lives in
     "match": {"url": "...", "line": "1"},       every field must be equal for the fix to apply
     "set": {"price": 149000, "value": ...},     fields to replace (null clears a field)
     "reason": "one English sentence",           why
     "source": "DART", "url": "...",             where the right value was read
     "recorded": "YYYY-MM-DD"}
Later lines win when two corrections set the same field of the same row.
A line may also carry "drop": true instead of "set": the row is then left out of the web file (still in history).
"""
import json

from market.common import append_history, read_history, today

DATASET = "corrections"
KEY_FIELDS = ("id",)


def correction(dataset, match, set_fields=None, reason="", source=None, url=None, drop=False):
    """One correction row (not yet written). `match` and `set_fields` are plain dicts."""
    row = {"dataset": dataset, "match": dict(match), "reason": reason, "source": source, "url": url,
           "recorded": today()}
    if drop:
        row["drop"] = True
    else:
        row["set"] = dict(set_fields or {})
    body = {"drop": True} if drop else row["set"]
    row["id"] = "|".join([dataset, json.dumps(row["match"], sort_keys=True, ensure_ascii=False),
                          json.dumps(body, sort_keys=True, ensure_ascii=False)])
    return row


def add(rows):
    """Append correction rows (ADD-only, deduplicated by id). Returns how many were new."""
    return append_history(DATASET, rows, KEY_FIELDS)


def for_dataset(dataset):
    """The corrections of one dataset, in the order they were recorded."""
    return [c for c in read_history(DATASET) if c.get("dataset") == dataset]


def apply(dataset, rows):
    """Return `rows` with the corrections of `dataset` applied (corrected rows are copies; dropped rows left out).
    Rows without any correction are returned as they are."""
    fixes = for_dataset(dataset)
    if not fixes:
        return rows
    # Index by the first match field's value, so a big history is not scanned once per correction.
    by_first = {}
    for c in fixes:
        if not c.get("match"):
            continue
        field = sorted(c["match"])[0]
        by_first.setdefault((field, json.dumps(c["match"][field], ensure_ascii=False)), []).append(c)
    fields = {f for f, _ in by_first}
    out = []
    for r in rows:
        hits = []
        for f in fields:
            hits += by_first.get((f, json.dumps(r.get(f), ensure_ascii=False)), [])
        hits = [c for c in hits if all(r.get(k) == v for k, v in c["match"].items())]
        if not hits:
            out.append(r)
            continue
        hits.sort(key=lambda c: fixes.index(c))       # recorded order: later lines win
        if any(c.get("drop") for c in hits):
            continue
        fixed = dict(r)
        for c in hits:
            fixed.update(c.get("set") or {})
        out.append(fixed)
    return out
