"""Build the company panel's "Financing" feed from every financing history: graph/financing_index.json plus one
file per company in graph/financing/ (split on 2026-10-17 so a panel downloads only its own company; see
market.common.write_company_split).

Inputs (all ADD-only JSONL, one row per financing event, same schema):
  market/history/financing_us.jsonl      SEC EDGAR 8-K / 424B / 6-K       (market/financing_us.py)
  market/history/financing_kr.jsonl ...  DART / MOPS / EDINET collectors  (other market/financing_*.py)
  market/history/financing_manual.jsonl  rows the enrich session appends by hand (e.g. credit ratings)

Row schema: {"company": <graph node id>, "date", "type", "title", "amount", "currency", "amount_usd",
             "detail", "form", "market", "source", "url", ...extra fields are ignored}

Output contract (web code reads this exactly):
  graph/financing_index.json  {"updated", "sources": [{"name", "url"}],
                               "companies": {"<node id>": {"file", "count", "latest"}}}
  graph/financing/<file>      {"company": "<node id>", "rows": [{"date","type","title","amount","currency",
                               "amount_usd","detail","form","market","source","url"}]}
  type in debt|convertible|equity|credit_facility|abs|lease_financing|rating|other; newest first; last 365 days.

The same deal is often filed twice (a 424B5 at pricing and the 8-K at closing; a pricing and a closing 6-K).
Such twins (same company, type and currency, filed within 10 days, amounts within 20%) are shown once:
the report with a number wins, else the later one (final terms). The histories themselves keep every row.
Never twins (user, 2026-10-17 verification): two different prospectuses (424B*), titles with different series /
issue numbers (Series A vs Series B, No. 2 vs No. 3), an at-the-market program or a warrant issuance next to any
other kind of deal, and two amount-less reports that are not the same day, an amendment, or the same numbered issue.

Also applied here, to every market's rows (the histories keep the raw rows):
  - market/history/corrections.jsonl (rows a parser read wrongly, see market/corrections.py);
  - a repayment, redemption or buyback (cash going OUT) is type "other" with no amount_usd, so it is never added
    to the money raised;
  - a board approval of a program (Taiwan "board approval") keeps its amount but gets no amount_usd: the issues
    under it are their own rows and would otherwise be counted twice;
  - Korean, Taiwanese and Japanese amounts are converted at the rate of the filing day (market/history/
    fx_usd.jsonl, recorded by market/financing_asia.py), like the US rows.

Financing is NOT a supply-chain signal: nothing here writes quarterly_data, chains/, patches/ or derive.py.

CLI:  python -m market.financing [--build-only]   (always a rebuild only; the collectors fetch)
"""
import argparse
import bisect
import datetime as dt
import re
import sys
from urllib.parse import urlparse

from market import corrections
from market.common import HISTORY, read_history, today, write_company_split

WINDOW_DAYS = 365
WINDOW_TWINS = 10                                    # days between two reports of one deal (pricing -> closing)
TYPES = {"debt", "convertible", "equity", "credit_facility", "abs", "lease_financing", "rating", "other"}
FIELDS = ["date", "type", "title", "amount", "currency", "amount_usd", "detail", "form", "market", "source", "url"]

# Home pages for the sources list (anything else falls back to the scheme + host of its first row's URL).
SOURCE_HOMES = {
    "SEC EDGAR": "https://www.sec.gov/edgar/search/",
    "DART": "https://dart.fss.or.kr/",
    "OpenDART": "https://opendart.fss.or.kr/",
    "KIND": "https://kind.krx.co.kr/",
    "MOPS": "https://mops.twse.com.tw/",
    "EDINET": "https://disclosure2.edinet-fsa.go.jp/",
    "TDnet": "https://www.release.tdnet.info/",
}


def _company(row):
    return row.get("company") or row.get("node_id") or row.get("node")


SECURITIES = {"debt", "convertible", "equity"}


def _value(row):
    """USD amount (or the native amount) as a number, None when missing or not numeric."""
    for key in ("amount_usd", "amount"):
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _iso_date(value):
    """'2026-10-17' (also accepts '2026/10/17' or a timestamp); None when it is not a date."""
    text = str(value or "")[:10].replace("/", "-")
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        return None


ISSUE_NUMBER = re.compile(r"\bSeries [A-Z0-9]{1,3}\b|\bNo\.\s*\d+|\btranche \d+|第\s*\d+\s*回", re.I)
ONE_OF_A_KIND = re.compile(r"^(At-the-market|Unregistered warrant)", re.I)
REPAYMENT = re.compile(r"\b(?:re|pre)payments?\b|\bredemptions?\b|\bredeem\w*|\brepurchas\w*|\bbuy-?backs?\b",
                       re.I)


def _issue_numbers(title):
    return {re.sub(r"\s+", " ", m.group(0)).lower() for m in ISSUE_NUMBER.finditer(title or "")}


def _kind_of(row):
    m = ONE_OF_A_KIND.search(row.get("title") or "")
    return m.group(1).lower() if m else None


def _is_amendment(form):
    return str(form or "").rstrip().endswith("/A")


def _same_deal(a, b):
    """The same deal reported twice by one company: a 424B5 at pricing and the 8-K at closing, a pricing and a
    closing 6-K (the closing amount includes the over-allotment option, so it can be up to ~15% larger), or a
    6-K and its 6-K/A. Same type and currency, filed within 10 days, and amounts within 20% (or one side states
    no amount). Never: two different prospectuses, different series / issue numbers, an ATM program or a warrant
    issuance next to another kind of deal (user, 2026-10-17 verification: Google's Series A and Series B
    mandatory convertible preferred, VPEC's CB No. 2 and No. 3, Magnachip's preferred offering and its ATM)."""
    if a["type"] != b["type"]:
        return False
    if a.get("currency") and b.get("currency") and a["currency"] != b["currency"]:
        return False                            # dollar and euro tranches of one day are two deals
    if abs((dt.date.fromisoformat(a["date"]) - dt.date.fromisoformat(b["date"])).days) > WINDOW_TWINS:
        return False
    if str(a.get("form") or "").startswith("424B") and str(b.get("form") or "").startswith("424B") \
            and a.get("url") != b.get("url"):
        return False                            # each prospectus offers its own securities
    na, nb = _issue_numbers(a.get("title")), _issue_numbers(b.get("title"))
    if na and nb and na != nb:
        return False
    if _kind_of(a) != _kind_of(b):
        return False                            # an ATM program / a warrant issuance next to any other deal
    va, vb = _value(a), _value(b)
    if va and vb:
        return abs(va - vb) <= 0.2 * max(va, vb)
    if not va and not vb:
        # Without numbers only a re-report of the very same event is a twin: the same day, an amendment, or the
        # same numbered issue (Seagate's note exchanges a week apart are separate deals).
        return a.get("title") == b.get("title") and (
            a["date"] == b["date"] or _is_amendment(a.get("form")) or _is_amendment(b.get("form")) or bool(na))
    # One side without a number: only the 8-K that closes an offering priced in a prospectus (424B...).
    forms = {str(a.get("form") or "")[:4], str(b.get("form") or "")[:4]}
    return a["type"] in SECURITIES and "424B" in forms and len(forms) == 2


def _better(kept, new):
    """Of two reports of one deal keep the one with a number, else the later one (the final terms)."""
    if bool(_value(kept)) != bool(_value(new)):
        return kept if _value(kept) else new
    return new


def history_files():
    return sorted(p.stem for p in HISTORY.glob("financing_*.jsonl"))


def fx_table():
    """{currency: (sorted dates, USD per unit)} from market/history/fx_usd.jsonl (empty when not recorded yet)."""
    series = {}
    for r in read_history("fx_usd"):
        if r.get("currency") and r.get("date") and r.get("usd"):
            series.setdefault(r["currency"], {})[r["date"]] = float(r["usd"])
    return {cur: (sorted(days), [days[d] for d in sorted(days)]) for cur, days in series.items()}


def usd_on(fx, amount, currency, date):
    """amount x the USD rate of `date` (or of the last trading day up to 10 days before); None when unknown."""
    if amount is None or currency not in fx:
        return None
    days, rates = fx[currency]
    i = bisect.bisect_right(days, date) - 1
    if i < 0 or (dt.date.fromisoformat(date) - dt.date.fromisoformat(days[i])).days > 10:
        return None
    return round(float(amount) * rates[i])


def clean(item, fx):
    """The build-time rules of the module docstring (repayments, approvals, filing-day FX) on one web row."""
    if REPAYMENT.search(item.get("title") or ""):
        item["type"] = "other"                  # cash going out: shown, never added to the money raised
        item["amount_usd"] = None
    elif re.search(r"\bboard approval\b", item.get("title") or "", re.I):
        item["amount_usd"] = None               # the program; its issues are separate rows
    elif item.get("market") in ("KR", "TW", "JP") and item.get("amount") and item.get("currency") \
            and item["currency"] != "USD":
        usd = usd_on(fx, item["amount"], item["currency"], item["date"])
        if usd is not None:
            item["amount_usd"] = usd
    return item


def build():
    cutoff = (dt.date.fromisoformat(today()) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    by_company, sources = {}, {}
    total = 0
    fx = fx_table()
    for dataset in history_files():
        for row in corrections.apply(dataset, read_history(dataset)):
            company, date = _company(row), _iso_date(row.get("date"))
            if not company or not date or date < cutoff or not row.get("url"):
                continue
            item = {k: row.get(k) for k in FIELDS}
            item["date"] = date
            if item["type"] not in TYPES:
                item["type"] = "other"
            by_company.setdefault(company, []).append(clean(item, fx))
            name = item.get("source") or dataset
            if name not in sources:
                parsed = urlparse(row["url"])
                sources[name] = SOURCE_HOMES.get(name) or f"{parsed.scheme}://{parsed.netloc}/"

    companies = {}
    for company, items in by_company.items():
        # Oldest first, so a later report of the same deal can replace the earlier one; newest first for the web.
        items.sort(key=lambda r: (r["date"], r.get("url") or ""))
        kept = []
        for item in items:
            if any(k["url"] == item["url"] and k["type"] == item["type"] and k.get("currency") == item.get("currency")
                   for k in kept):
                continue                         # the very same row (one filing can hold $ and € notes: two rows)
            twin = next((i for i, k in enumerate(kept) if _same_deal(k, item)), None)
            if twin is None:
                kept.append(item)
            else:
                kept[twin] = _better(kept[twin], item)
        kept.sort(key=lambda r: r["date"], reverse=True)
        companies[company] = kept
        total += len(kept)

    out = {
        "updated": today(),
        "sources": [{"name": n, "url": u} for n, u in sorted(sources.items())],
        "companies": dict(sorted(companies.items(), key=lambda kv: kv[0].lower())),
    }
    write_company_split("financing", out["updated"], out["sources"], out["companies"])
    print(f"  graph/financing_index.json + graph/financing/: {total} events for {len(companies)} companies "
          f"from {', '.join(history_files()) or 'no history yet'}")
    return out


def run(backfill=False):
    """No fetching here (each market/financing_*.py collector fetches); just rebuild the web file."""
    build()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild graph/financing_index.json + graph/financing/ from "
                                                 "market/history/financing_*.jsonl")
    parser.add_argument("--backfill", action="store_true", help="accepted for symmetry; nothing is fetched here")
    parser.add_argument("--build-only", action="store_true", help="accepted for symmetry; this is always a rebuild")
    parser.parse_args()
    build()
    sys.exit(0)
