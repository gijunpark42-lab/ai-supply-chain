"""Builds graph/insiders.json (insider trades for the company panel) from every market's history.

Each market has its own collector that appends rows to market/history/insiders_<market>.jsonl
(insiders_us = SEC Form 4, and insiders_kr / insiders_tw / insiders_jp from their own collectors), all with
the same row fields. This module only reads those files (no network) and writes the web file:

  { "updated": "YYYY-MM-DD",
    "sources": [{"name", "url"}],
    "companies": { "<node id>": [ {date, filed, insider, role, code, type, shares, price, value, currency,
                                   owned_after, plan_10b5_1, market, source, url}, ... newest first ] } }

Only the last 365 days (by transaction date) are written; the history files keep everything, line by line.
For the website, the lines of ONE filing that are really one trade split by fill price (a sale reported as
30 lines at 30 prices) are merged into one row: total shares, total value, average price, shares owned after
the last line. Insider trades are NOT signals: nothing here touches quarterly_data, chains/ or patches/.

Clean-ups for the web file only (user, 2026-10-17 verification; the history files keep the raw rows):
  - market/history/corrections.jsonl is applied first (rows the old parsers read wrongly, see corrections.py);
  - a buy / sell / tax-withholding price more than 20x away from the company's other prices of the same weeks
    (a typo such as Eli Lilly's 1031414 for $1,031.41) is shown without price and value;
  - lines of one filing are merged per holder (direct, spouse, each trust: the "nature" of the holding), not
    across holders;
  - an amendment (4/A, or a later Korean report of the same line) replaces the trade it restates;
  - one block trade reported by two related filers (same day, shares, price and holding after) is shown once;
  - grants and gifts get no value (shares x price is not money that changed hands there).

CLI:  python -m market.insiders     (rebuild graph/insiders.json)
"""
import datetime as dt
import importlib
import json
import os
import statistics
import sys
from urllib.parse import urlparse

from market import corrections
from market.common import GRAPH, HISTORY, today, read_history

OUT_FILE = GRAPH / "insiders.json"
WINDOW_DAYS = 365
FIELDS = ("date", "filed", "insider", "role", "code", "type", "shares", "price", "value", "currency",
          "owned_after", "plan_10b5_1", "market", "source", "url")
# Lines with the same filing, day, person, code, security and holder (direct / indirect + the nature of the
# indirect holding, e.g. "By Spouse") are one trade. security / ownership / nature exist only where a collector
# records them (nature since 2026-10-17); missing = None, which still groups fine.
MERGE_KEY = ("url", "date", "insider", "code", "security", "ownership", "nature")
PRICE_TYPES = ("buy", "sell", "tax_withholding")   # their price is the market price, so they can be compared
PRICE_FACTOR = 20                                  # more than 20x off the company's other prices = a typo
PRICE_WINDOW = 45                                  # days around the trade whose prices are the reference
NO_VALUE_TYPES = ("grant", "gift")


def log(msg):
    print(f"[insiders] {msg}", file=sys.stderr)


def sources_for(dataset, rows):
    """A collector module may list its sources as SOURCES = [{"name", "url"}]; otherwise use each row's source
    name with the home page of its first URL."""
    try:
        module = importlib.import_module(f"market.{dataset}")
        if getattr(module, "SOURCES", None):
            return list(module.SOURCES)
    except Exception:          # no module of that name, or it failed to import: fall back to the rows
        pass
    found = {}
    for r in rows:
        if r.get("source") and r.get("url") and r["source"] not in found:
            u = urlparse(r["url"])
            found[r["source"]] = f"{u.scheme}://{u.netloc}/"
    return [{"name": name, "url": url} for name, url in found.items()]


def short_names(insider):
    """A fund group often files jointly as 5-10 entities ('Fund III, LP; Fund IV, LP; GP LLC; ...').
    The panel shows the first (designated) filer and how many others joined; the history keeps every name."""
    names = [n for n in (insider or "").split("; ") if n]
    if len(names) <= 2:
        return insider
    return f"{names[0]} and {len(names) - 1} joint filers"


def merge_lines(rows):
    """Merge the lines of one trade (see MERGE_KEY). `rows` must be in history (= document) order."""
    groups = {}                                    # dicts keep insertion order, so the output keeps it too
    for r in rows:
        groups.setdefault(tuple(r.get(k) for k in MERGE_KEY), []).append(r)
    merged = []
    for lines in groups.values():
        if len(lines) == 1:
            merged.append(lines[0])
            continue
        row = dict(lines[0])
        shares = [x.get("shares") for x in lines]
        values = [x.get("value") for x in lines]
        row["shares"] = sum(shares) if None not in shares else None
        row["value"] = round(sum(values), 2) if None not in values else None   # unknown if any line has no price
        if row["value"] is not None and row["shares"]:
            row["price"] = round(row["value"] / row["shares"], 4)              # share-weighted average price
        elif len({x.get("price") for x in lines}) != 1:
            row["price"] = None
        row["owned_after"] = lines[-1].get("owned_after")                      # holding after the LAST line
        row["plan_10b5_1"] = any(x.get("plan_10b5_1") for x in lines)
        merged.append(row)
    return merged


def holder_label(r):
    """' (By Trust for Child 1)' for a line held indirectly, so two trusts selling the same block in one filing are
    two visibly different rows; '' for a direct holding or when the filing only says 'See footnote'."""
    nature = " ".join(str(r.get("nature") or "").split())
    if r.get("ownership") != "I" or not nature or "footnote" in nature.lower():
        return ""
    return f" ({nature[:60]})"


def check_prices(rows, dataset):
    """Price plausibility guard (user, 2026-10-17 verification). A buy / sell / tax-withholding line whose price is
    more than PRICE_FACTOR x above or below the median price of the same company's OTHER filings within
    PRICE_WINDOW days (else of the other lines of the same filing) is a typo in the filing or a parse error:
    its price and value become None (the shares stay). Works on history lines, before they are merged.
    Returns the rows (changed ones are copies)."""
    by_node = {}
    for i, r in enumerate(rows):
        if r.get("type") in PRICE_TYPES and isinstance(r.get("price"), (int, float)) and r["price"] > 0 \
                and r.get("date"):
            by_node.setdefault(r.get("node_id"), []).append(i)
    out = list(rows)
    flagged = 0
    for idx in by_node.values():
        idx.sort(key=lambda i: rows[i]["date"])
        days = [dt.date.fromisoformat(rows[i]["date"][:10]) for i in idx]
        lo = 0
        for k, i in enumerate(idx):
            r = rows[i]
            while (days[k] - days[lo]).days > PRICE_WINDOW:
                lo += 1
            hi = k
            while hi + 1 < len(idx) and (days[hi + 1] - days[k]).days <= PRICE_WINDOW:
                hi += 1
            near = [rows[j]["price"] for j in idx[lo:hi + 1] if rows[j].get("url") != r.get("url")]
            if len(near) < 2:                       # no other filing close by: the filing's other lines
                near = [rows[j]["price"] for j in idx[lo:hi + 1] if j != i and rows[j].get("url") == r.get("url")]
            if len(near) < 2:
                continue
            ref = statistics.median(near)
            if r["price"] > PRICE_FACTOR * ref or r["price"] * PRICE_FACTOR < ref:
                out[i] = dict(r, price=None, value=None)
                flagged += 1
                log(f"price guard: {dataset} {r.get('node_id')} {r.get('date')} {r.get('accession') or r.get('url')} "
                    f"{r.get('line') or ''} price {r['price']} vs median {ref:g} of nearby trades; shown without "
                    f"price / value")
    if flagged:
        log(f"price guard: {flagged} {dataset} lines shown without price")
    return out


def trade_key(r):
    return (r.get("insider"), r.get("date"), r.get("code"), r.get("shares"), r.get("price"), r.get("security"))


def drop_refilings(rows):
    """The same trade filed twice is shown once, keeping the latest filing:
      - every field except the filing date and link matches (a plain refiling), or
      - the later filing is an amendment (SEC form 4/A; any later Korean / Japanese / Taiwanese report) that
        restates the trade (same insider, day, code, shares, price and security), even when it changes the
        holding after, the 10b5-1 flag or the role: the amendment's values win (user, 2026-10-17 verification,
        AAON 4/A 0001565768-26-000021 marking the original sales as 10b5-1 plan sales)."""
    rows = sorted(rows, key=lambda r: r.get("filed") or "", reverse=True)   # stable: lines keep their order
    first_filing, amended, unique = {}, {}, []   # trade -> url of the latest filing that reported it
    for r in rows:
        same = tuple(r.get(k) for k in FIELDS if k not in ("filed", "url"))
        if same in first_filing and first_filing[same] != r.get("url"):
            continue                     # an older filing of a trade we already have
        key = trade_key(r)
        if key in amended and amended[key] != r.get("url"):
            continue                     # restated by a later amendment
        first_filing.setdefault(same, r.get("url"))
        if str(r.get("form") or "").endswith("/A") or (r.get("market") not in (None, "US") and r.get("shares")):
            amended.setdefault(key, r.get("url"))
        unique.append(r)
    return unique


def collapse_joint_filers(rows):
    """One block trade is often reported by two related reporting persons in two filings (a fund and its manager,
    a director and his family company). Same day, code, shares, price and shares held after = the same trade:
    shown once with both names, so it is not counted twice (user, 2026-10-17 verification: NRG Energy
    2026-03-04, LS Power and David Nanus)."""
    kept, seen = [], {}
    for r in rows:
        if r.get("type") in ("buy", "sell") and r.get("shares") and r.get("owned_after") is not None:
            key = (r.get("date"), r.get("code"), r.get("shares"), r.get("price"), r.get("owned_after"))
            first = seen.get(key)
            if first is not None and first.get("url") != r.get("url") and first.get("insider") != r.get("insider"):
                names = [n for n in (first.get("insider") or "").split("; ") + (r.get("insider") or "").split("; ")
                         if n]
                first["insider"] = "; ".join(dict.fromkeys(names))
                roles = [x for x in (first.get("role"), r.get("role")) if x]
                first["role"] = "; ".join(dict.fromkeys(roles)) or None
                first["plan_10b5_1"] = bool(first.get("plan_10b5_1") or r.get("plan_10b5_1"))
                continue
            if first is None:
                r = dict(r)
                seen[key] = r
        kept.append(r)
    return kept


def write_rows_json(path, data):
    """Like common.write_json (atomic), but one trade per line: the file stays small for the website and a
    nightly git diff shows only the new trades instead of re-indenting thousands of lines."""
    parts = ["{",
             f' "updated": {json.dumps(data["updated"])},',
             f' "sources": {json.dumps(data["sources"], ensure_ascii=False)},',
             ' "companies": {']
    companies = list(data["companies"].items())
    for i, (node_id, rows) in enumerate(companies):
        parts.append(f"  {json.dumps(node_id, ensure_ascii=False)}: [")
        for j, r in enumerate(rows):
            comma = "," if j < len(rows) - 1 else ""
            parts.append("   " + json.dumps(r, ensure_ascii=False, separators=(",", ":")) + comma)
        parts.append("  ]" + ("," if i < len(companies) - 1 else ""))
    parts += [" }", "}"]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(parts) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def build():
    """Rebuild graph/insiders.json from market/history/insiders_*.jsonl."""
    cutoff = (dt.date.fromisoformat(today()) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    companies, sources = {}, []
    lines_in, rows_out = 0, 0
    for path in sorted(HISTORY.glob("insiders_*.jsonl")):
        dataset = path.stem
        rows = corrections.apply(dataset, read_history(dataset))
        for s in sources_for(dataset, rows):
            if s not in sources:
                sources.append(s)
        recent = check_prices([r for r in rows if r.get("date") and r["date"] >= cutoff], dataset)
        lines_in += len(recent)
        for r in merge_lines(recent):
            out = {k: r.get(k) for k in FIELDS}
            out["form"], out["security"] = r.get("form"), r.get("security")      # dropped again below
            out["holder"] = holder_label(r)
            if out["date"] and out["filed"] and out["date"] > out["filed"]:
                out["date"] = out["filed"]      # a trade cannot happen after its filing: a typo in the filing
            if out["type"] in NO_VALUE_TYPES:
                out["value"] = None             # shares x price of a grant / gift is no money changing hands
            # a row normally belongs to one node; a listing shared by two graph nodes carries "node_ids"
            for node_id in (r.get("node_ids") or [r.get("node_id")]):
                if node_id:
                    companies.setdefault(node_id, []).append(out)

    for node_id, rows in companies.items():
        rows = collapse_joint_filers(drop_refilings(rows))
        # newest first (sort is stable, so lines of one filing keep their order)
        rows.sort(key=lambda r: (r.get("date") or "", r.get("filed") or ""), reverse=True)
        companies[node_id] = [{k: (short_names(r[k]) + r["holder"] if k == "insider" else r.get(k)) for k in FIELDS}
                              for r in rows]
        rows_out += len(rows)

    data = {"updated": today(), "sources": sources, "companies": dict(sorted(companies.items()))}
    write_rows_json(OUT_FILE, data)
    log(f"wrote {OUT_FILE.relative_to(GRAPH.parent)}: {rows_out} trades ({lines_in} filing lines) "
        f"for {len(companies)} companies since {cutoff}")
    return data


if __name__ == "__main__":
    build()
