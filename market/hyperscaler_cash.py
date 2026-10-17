"""market/hyperscaler_cash.py -- hyperscaler capex / cash flow (SEC XBRL) + the earnings calendar.

Writes graph/hyperscaler_cash.json (data contract 4) for the website:
  companies: the last 8 discrete quarters of capex, operating cash flow (OCF), free cash flow (FCF = OCF - capex)
             and FCF after finance-lease principal payments, for the 8 AI-cloud spenders below.
  calendar:  the next earnings date of every PUBLIC company in the graph, for the next 60 days.

Sources (all free, no model tokens, one fetch per source per day):
  - SEC XBRL "companyconcept" API (data.sec.gov), 3 small requests per company, <= 4 requests/second,
    with the descriptive EDGAR_USER_AGENT header (market.common.sec_headers()).
  - Alpha Vantage EARNINGS_CALENDAR (CSV, horizon 3month): ONE call per day, US listings.
  - Yahoo Finance via yfinance (calendarEvents module): every listing, paced and cached per symbol.
  - The 8 companies' own investor-relations pages (earnings-call event listings / date press releases).

Why quarters need work: a 10-Q cash-flow statement is YEAR-TO-DATE (6 or 9 months), and a 10-K is the full year.
So a discrete quarter is a ~3-month fact when the company tags one, otherwise the difference of two year-to-date
facts with the same start date (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M). When a period is reported again
(a restatement, or next year's comparative column), the most recently FILED value wins.

"confirmed" earnings dates: the company's own IR page lists the date, or Alpha Vantage and Yahoo Finance give
the same date and Yahoo does not flag it as an estimate. A date from one source only is shown as unconfirmed.

History (ADD-only, market/history/):
  hyperscaler_cash.jsonl   one row per company + quarter end + tag set (+ the values, so a restatement is a new row)
  earnings_calendar.jsonl  one row each time a source's date for a company CHANGES (not one row per day)

CLI:
  python -m market.hyperscaler_cash               # fetch today's data, append history, rebuild the web file
  python -m market.hyperscaler_cash --backfill    # also record every quarter XBRL can derive + refresh all Yahoo symbols
  python -m market.hyperscaler_cash --build-only  # rebuild graph/hyperscaler_cash.json from history only
"""
import argparse
import csv
import datetime as dt
import html
import io
import logging
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

from market.common import (GRAPH, ROOT, append_history, get, load_env, read_history, read_json,
                           sec_headers, today, universe, write_json)

OUT = GRAPH / "hyperscaler_cash.json"
CACHE = ROOT / "market" / "cache" / "hyperscaler_cash"     # today's raw responses (a same-day re-run reuses them)
YAHOO_CACHE = CACHE / "yahoo_earnings.json"                 # per-symbol Yahoo answers, refreshed on a schedule
CASH_DATASET = "hyperscaler_cash"
CAL_DATASET = "earnings_calendar"

KEEP_QUARTERS = 8          # quarters per company on the website
CALENDAR_DAYS = 60         # how far ahead the calendar looks
SEC_PAUSE = 0.25           # seconds between SEC requests (SEC allows 10/s; we stay at 4/s)
YAHOO_PAUSE = 0.5          # seconds between Yahoo requests
YAHOO_MAX_PER_RUN = 300    # a normal daily run refreshes at most this many Yahoo symbols (--backfill: all)
YAHOO_STALE_DAYS = 7       # every symbol is re-checked at least weekly
YAHOO_SOON_DAYS = 14       # ...and daily once its date is this close (dates get confirmed or moved late)

NY = ZoneInfo("America/New_York")

# Default XBRL tags (us-gaap). A company entry overrides a metric when it tags it differently.
CAPEX_TAG = "PaymentsToAcquirePropertyPlantAndEquipment"
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"
LEASE_TAG = "FinanceLeasePrincipalPayments"

# The 8 companies. id = the graph node id; cik = SEC company number; fye = month the fiscal year ends;
# ir = how to read the company's own earnings-date announcement; caveat = a sentence for the web note.
COMPANIES = [
    {"id": "Microsoft", "ticker": "MSFT", "cik": 789019, "fye": 6, "ir": ("microsoft", None)},
    {"id": "Google", "ticker": "GOOGL", "cik": 1652044, "fye": 12, "ir": ("q4", "https://abc.xyz")},
    {"id": "Amazon", "ticker": "AMZN", "cik": 1018724, "fye": 12, "ir": ("q4", "https://ir.aboutamazon.com"),
     "capex": "PaymentsToAcquireProductiveAssets",
     "caveat": "Amazon capex is PaymentsToAcquireProductiveAssets (purchases of property and equipment before "
               "proceeds from sales and incentives, which Amazon nets in its own free-cash-flow figure)."},
    {"id": "Meta", "ticker": "META", "cik": 1326801, "fye": 12, "ir": ("q4", "https://investor.atmeta.com")},
    {"id": "Oracle", "ticker": "ORCL", "cik": 1341439, "fye": 5, "ir": ("q4", "https://investor.oracle.com")},
    {"id": "CoreWeave", "ticker": "CRWV", "cik": 1769628, "fye": 12, "ir": ("q4", "https://investors.coreweave.com")},
    {"id": "Nebius", "ticker": "NBIS", "cik": 1513845, "fye": 12, "ir": ("nebius", "https://nebius.com/newsroom"),
     "caveat": "Nebius files an annual 20-F and furnishes quarterly results on 6-K without XBRL, so SEC XBRL has "
               "no quarterly cash-flow figures for it (annual only)."},
    {"id": "IREN", "ticker": "IREN", "cik": 1878848, "fye": 6, "ir": ("iren", "https://iren.com/investors"),
     "caveat": "IREN moved from IFRS (20-F/6-K) to US GAAP (10-K/10-Q) in fiscal 2025; only the US GAAP facts are "
               "used, so older IFRS quarters are not mixed in."},
]

# Graph exchange -> Yahoo Finance symbol suffix ("" = US listing, no suffix).
EXCHANGE_SUFFIX = {
    "NASDAQ": "", "NYSE": "", "NYSE American": "", "OTC": "",
    "TWSE": ".TW", "TPEx": ".TWO", "KOSPI": ".KS", "KOSDAQ": ".KQ", "KRX": ".KS", "KONEX": ".KN",
    "TSE": ".T", "SSE": ".SS", "SZSE": ".SZ", "HKEX": ".HK", "XETRA": ".DE", "SIX": ".SW", "NSE": ".NS",
    "LSE": ".L", "OMX Stockholm": ".ST", "STO": ".ST", "Euronext Paris": ".PA", "EPA": ".PA",
    "Euronext Amsterdam": ".AS", "AMS": ".AS", "Euronext Brussels": ".BR", "MIL": ".MI", "OMX Helsinki": ".HE",
    "OSE": ".OL", "VIE": ".VI", "TSX": ".TO", "ASX": ".AX", "SGX": ".SI", "Bursa": ".KL", "Bursa Malaysia": ".KL",
    "IDX": ".JK", "B3": ".SA",
}
US_EXCHANGES = {ex for ex, suffix in EXCHANGE_SUFFIX.items() if suffix == ""}

# Yahoo symbol suffix -> (market time zone, session open, session close). Used to turn Yahoo's timestamp into the
# local report date and into bmo (before market open) / amc (after market close).
MARKET_HOURS = {
    "": ("America/New_York", "09:30", "16:00"),
    ".KS": ("Asia/Seoul", "09:00", "15:30"), ".KQ": ("Asia/Seoul", "09:00", "15:30"), ".KN": ("Asia/Seoul", "09:00", "15:30"),
    ".T": ("Asia/Tokyo", "09:00", "15:30"), ".TW": ("Asia/Taipei", "09:00", "13:30"), ".TWO": ("Asia/Taipei", "09:00", "13:30"),
    ".HK": ("Asia/Hong_Kong", "09:30", "16:00"), ".SS": ("Asia/Shanghai", "09:30", "15:00"), ".SZ": ("Asia/Shanghai", "09:30", "15:00"),
    ".SI": ("Asia/Singapore", "09:00", "17:00"), ".KL": ("Asia/Kuala_Lumpur", "09:00", "17:00"), ".JK": ("Asia/Jakarta", "09:00", "16:00"),
    ".NS": ("Asia/Kolkata", "09:15", "15:30"), ".AX": ("Australia/Sydney", "10:00", "16:00"),
    ".DE": ("Europe/Berlin", "09:00", "17:30"), ".PA": ("Europe/Paris", "09:00", "17:30"), ".AS": ("Europe/Amsterdam", "09:00", "17:30"),
    ".BR": ("Europe/Brussels", "09:00", "17:30"), ".MI": ("Europe/Rome", "09:00", "17:30"), ".SW": ("Europe/Zurich", "09:00", "17:30"),
    ".ST": ("Europe/Stockholm", "09:00", "17:30"), ".HE": ("Europe/Helsinki", "10:00", "18:30"), ".OL": ("Europe/Oslo", "09:00", "16:20"),
    ".VI": ("Europe/Vienna", "09:00", "17:30"), ".L": ("Europe/London", "08:00", "16:30"), ".CO": ("Europe/Copenhagen", "09:00", "17:00"),
    ".TO": ("America/Toronto", "09:30", "16:00"), ".SA": ("America/Sao_Paulo", "10:00", "17:00"),
}

AV_URL = "https://www.alphavantage.co/query"
AV_DOC_URL = "https://www.alphavantage.co/documentation/#earnings-calendar"
Q4_EVENTS = ("/feed/Event.svc/GetEventList?LanguageId=1&eventSelection=1&eventDateFilter=1"
             "&includeFinancialReports=false&includePresentations=false&includePressReleases=false"
             "&sortOperator=1&pageSize=10&pageNumber=0&tagList=&includeTags=true&year=-1&excludeSelection=1")
SOURCE_NAMES = {"ir": "Company investor relations", "alpha_vantage": "Alpha Vantage", "yahoo": "Yahoo Finance"}


def log(msg):
    print(f"[hyperscaler_cash] {msg}", flush=True)


def day(s):
    return dt.date.fromisoformat(s)


def html_text(page):
    """Visible text of an HTML page, whitespace collapsed."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page))).strip()


def fetch_cached(name, url, headers=None, params=None, as_json=True, timeout=30, pause=0.0):
    """Fetch once per day: today's response is kept in market/cache/hyperscaler_cash/<name>.json and a same-day
    re-run reuses it. Returns the body (parsed JSON or text), None for a 404, and raises on any other failure.
    Only `url` (never `params`, which may hold an API key) is written to the cache file."""
    path = CACHE / f"{name}.json"
    cached = read_json(path)
    if cached and cached.get("fetched") == today():
        return cached.get("body")
    r = get(url, headers=headers, params=params, timeout=timeout)
    if pause:
        time.sleep(pause)
    if r.status_code == 404:
        body = None
    elif r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {url}")
    else:
        body = r.json() if as_json else r.text
    write_json(path, {"fetched": today(), "url": url, "body": body})
    return body


# ============================================================ part 1: quarterly cash flow from SEC XBRL

def fiscal_quarter(end, fye):
    """(fiscal year, quarter number) of a quarter ending on `end` for a fiscal year ending in month `fye`.
    The fiscal year is named after the calendar year it ends in (Microsoft FY2026 ends 2026-06-30)."""
    fy = end.year + 1 if end.month > fye else end.year
    q = ((end.month - fye - 1) % 12) // 3 + 1
    return fy, q


def sec_concept(cik, tag):
    """All USD facts of one us-gaap tag for one company ([] when the company never used the tag)."""
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
    body = fetch_cached(f"sec_{cik}_{tag}", url, headers=sec_headers(), pause=SEC_PAUSE)
    return ((body or {}).get("units") or {}).get("USD", [])


def discrete_quarters(facts):
    """Turn cash-flow facts (3-month, year-to-date and full-year) into one value per quarter end.
    Returns {end: {"val", "start", "fact"}} where fact is the reported fact that ends on that date."""
    # 1) one fact per (start, end) span: the most recently filed one (restatements / comparatives win)
    latest = {}
    for f in facts:
        if not f.get("start") or f.get("val") is None:
            continue                                   # instant facts carry no period
        span = (f["start"], f["end"])
        if span not in latest or f.get("filed", "") > latest[span].get("filed", ""):
            latest[span] = f

    def length(start, end):
        return (day(end) - day(start)).days + 1

    out = {}
    # 2) a ~3-month fact is the quarter itself
    for (start, end), f in latest.items():
        if 80 <= length(start, end) <= 100:
            out[end] = {"val": f["val"], "start": start, "fact": f}
    # 3) otherwise: year-to-date minus the year-to-date one quarter earlier (same start date)
    for (start, end), f in latest.items():
        if end in out or length(start, end) <= 100:
            continue
        for (start2, end2), f2 in latest.items():
            if start2 == start and 80 <= (day(end) - day(end2)).days <= 100:
                out[end] = {"val": f["val"] - f2["val"], "start": (day(end2) + dt.timedelta(days=1)).isoformat(),
                            "fact": f}
                break
    return out


def filing_url(cik, accn):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm"


def company_quarters(c, backfill):
    """History rows (one per quarter) for one company, newest last."""
    tags = {"capex": c.get("capex", CAPEX_TAG), "ocf": c.get("ocf", OCF_TAG), "lease": c.get("lease", LEASE_TAG)}
    series = {metric: discrete_quarters(sec_concept(c["cik"], tag)) for metric, tag in tags.items()}
    tag_set = ";".join(f"{metric}=us-gaap:{tag}" for metric, tag in tags.items())
    ends = sorted(set(series["capex"]) | set(series["ocf"]))
    if not backfill:
        ends = ends[-KEEP_QUARTERS:]
    rows = []
    for end in ends:
        capex, ocf, lease = (series[m].get(end) for m in ("capex", "ocf", "lease"))
        main = (capex or ocf)["fact"]                 # the filing that reported this period's figure
        fy, q = fiscal_quarter(day(end), c["fye"])
        rows.append({
            "id": c["id"], "ticker": c["ticker"], "cik": c["cik"],
            "start": (capex or ocf)["start"], "end": end,
            "period": f"{day(end).year}Q{(day(end).month - 1) // 3 + 1}", "fiscal": f"FY{fy} Q{q}",
            "tags": tag_set,
            "capex_usd": capex["val"] if capex else None,
            "ocf_usd": ocf["val"] if ocf else None,
            "lease_principal_usd": lease["val"] if lease else None,
            "form": main.get("form"), "filed": main.get("filed"), "accn": main.get("accn"),
            "url": filing_url(c["cik"], main["accn"]),
            "source": "SEC EDGAR XBRL", "seen": today(),
        })
    return rows


def collect_cash(backfill=False):
    """Fetch the 8 companies' XBRL facts and append new quarter rows. Returns how many companies worked."""
    ok, rows = 0, []
    for c in COMPANIES:
        try:
            got = company_quarters(c, backfill)
            ok += 1
            rows += got
            log(f"SEC XBRL {c['id']}: {len(got)} quarters")
        except Exception as e:                        # one dead company never stops the others
            log(f"WARNING SEC XBRL {c['id']} failed ({type(e).__name__}: {e}); keeping previous data")
    # Key = company + quarter end + tag set; the three values are part of the key too, so a restated figure
    # becomes a new row (build() then shows the most recently filed one) instead of being dropped.
    added = append_history(CASH_DATASET, rows,
                           ("id", "end", "tags", "capex_usd", "ocf_usd", "lease_principal_usd"))
    log(f"history {CASH_DATASET}: +{added} rows")
    return ok


# ============================================================ part 2: earnings calendar

# Taiwan and Korea each have two boards; a few graph tickers name the wrong one, so the other is tried too.
OTHER_BOARD = {".TW": ".TWO", ".TWO": ".TW", ".KS": ".KQ", ".KQ": ".KS"}


def yahoo_symbols(ticker, exchange):
    """Yahoo Finance symbol candidates for a graph ticker, most likely first."""
    t = (ticker or "").strip().rstrip(".")
    if not t:
        return []
    known = {s.lstrip(".") for s in MARKET_HOURS if s}
    if "." in t and t.rsplit(".", 1)[1].upper() in known:
        base, suffix = t.rsplit(".", 1)                # already a Yahoo symbol, e.g. 000660.KS
        suffix = "." + suffix.upper()
    elif exchange in US_EXCHANGES:
        return [t.replace(".", "-")]                   # BRK.B -> BRK-B
    elif EXCHANGE_SUFFIX.get(exchange) is None:
        return []
    else:
        base, suffix = t, EXCHANGE_SUFFIX[exchange]
        if suffix == ".HK" and base.isdigit():
            base = base.zfill(4)
    other = OTHER_BOARD.get(suffix)
    return [base + suffix] + ([base + other] if other else [])


def calendar_targets():
    """Every public graph node -> {ticker, av (US symbol or None), yahoo (symbol candidates)}."""
    out = {}
    for node_id, info in universe().items():
        if info.get("status") != "public" or not info.get("ticker"):
            continue
        ex = info.get("exchange")
        ticker = info["ticker"].strip()
        is_us = ex in US_EXCHANGES and re.fullmatch(r"[A-Z][A-Z.\-]{0,6}", ticker) is not None
        out[node_id] = {"ticker": ticker, "av": ticker if is_us else None, "yahoo": yahoo_symbols(ticker, ex)}
    return out


def session_time(local, open_hm, close_hm):
    """bmo / amc / unknown for a local report time (00:00 = no time given)."""
    hm = local.strftime("%H:%M")
    if hm == "00:00":
        return "unknown"
    if hm < open_hm:
        return "bmo"
    if hm >= close_hm:
        return "amc"
    return "unknown"


# ------------------------------------------------ Alpha Vantage (one CSV call per day)

def fetch_alpha_vantage():
    """{symbol: {"date", "time"}} for every US listing Alpha Vantage expects to report in the next 3 months."""
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY missing in .env")
    try:
        text = fetch_cached("alphavantage_earnings_calendar", AV_URL, as_json=False, timeout=90,
                            params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": key})
    except Exception as e:
        raise RuntimeError(str(e).replace(key, "<key>")) from None     # never let the key reach a log
    if not text or not text.startswith("symbol,"):
        raise RuntimeError(f"unexpected Alpha Vantage answer: {(text or '')[:120]!r}")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        sym, date = row.get("symbol"), row.get("reportDate")
        if not sym or not date:
            continue
        when = {"pre-market": "bmo", "post-market": "amc"}.get((row.get("timeOfTheDay") or "").strip(), "unknown")
        if sym not in out or date < out[sym]["date"]:
            out[sym] = {"date": date, "time": when}
    return out


# ------------------------------------------------ Yahoo Finance (per symbol, cached)

def yahoo_lookup(symbol):
    """Raw Yahoo calendarEvents for one symbol: {"ts": [unix seconds], "estimate": bool|None, "ok": bool}.
    Uses yfinance's quoteSummary fetch directly because Ticker.calendar drops isEarningsDateEstimate and converts
    the timestamp with the laptop's time zone (an Asian report date then lands one day early)."""
    import yfinance as yf
    res = yf.Ticker(symbol)._quote._fetch(modules=["calendarEvents"])
    result = ((res or {}).get("quoteSummary") or {}).get("result") or []
    if not result:
        return {"ts": [], "estimate": None, "ok": False}
    earnings = (result[0].get("calendarEvents") or {}).get("earnings") or {}
    return {"ts": earnings.get("earningsDate") or [], "estimate": earnings.get("isEarningsDateEstimate"), "ok": True}


def yahoo_date(symbol, entry):
    """(date, time) from a cached Yahoo entry, in the listing market's local time zone, or (None, None)."""
    if not entry or not entry.get("ts"):
        return None, None
    suffix = "." + symbol.rsplit(".", 1)[1] if "." in symbol else ""
    tz, open_hm, close_hm = MARKET_HOURS.get(suffix, MARKET_HOURS[""])
    local = dt.datetime.fromtimestamp(entry["ts"][0], ZoneInfo(tz))
    exact = entry.get("estimate") is False and len(entry["ts"]) == 1   # a 2-value list is an estimate window
    return local.date().isoformat(), session_time(local, open_hm, close_hm) if exact else "unknown"


def refresh_yahoo(targets, backfill):
    """Refresh the Yahoo cache for symbols that are due. Returns (cache, symbols refreshed this run, failures)."""
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)        # unknown symbols would print 404 noise
    cache = read_json(YAHOO_CACHE, {}) or {}
    now = day(today())

    def priority(node_id):
        """None = fresh enough; smaller number = refresh sooner."""
        entries = [cache.get(s) for s in targets[node_id]["yahoo"]]
        entry = next((e for e in entries if e and e.get("ok")), None)
        if not entry and None in entries:
            return 0                                   # never asked, or the other board was never tried
        entry = entry or entries[0]
        age = (now - day(entry["fetched"])).days
        if age >= YAHOO_STALE_DAYS or (backfill and age >= 1):
            return 2
        if age >= 1 and entry.get("ok"):
            symbol = next(s for s in targets[node_id]["yahoo"] if cache.get(s) is entry)
            date, _ = yahoo_date(symbol, entry)
            if not date or date < now.isoformat() or day(date) <= now + dt.timedelta(days=YAHOO_SOON_DAYS):
                return 1
        return None

    due = sorted((p, node_id) for node_id in targets if targets[node_id]["yahoo"]
                 for p in [priority(node_id)] if p is not None)
    if not backfill:
        due = due[:YAHOO_MAX_PER_RUN]
    refreshed, failures, in_a_row = set(), 0, 0
    for _, node_id in due:
        if in_a_row >= 10:
            log("WARNING Yahoo: 10 failures in a row (blocked or down); stopping for today")
            break
        for symbol in targets[node_id]["yahoo"]:
            known = cache.get(symbol) or {}
            if known.get("fetched") == today() and not known.get("ok"):
                continue                               # Yahoo did not know this symbol today; try the next
            try:
                answer = yahoo_lookup(symbol)
            except Exception as e:
                failures += 1
                in_a_row += 1
                log(f"WARNING Yahoo {symbol}: {type(e).__name__}: {str(e)[:100]}")
                time.sleep(YAHOO_PAUSE)
                continue
            in_a_row = 0
            cache[symbol] = {"fetched": today(), **answer}
            refreshed.add(node_id)
            time.sleep(YAHOO_PAUSE)
            if answer["ok"]:
                break                                  # KRX: the first board that answers is the right one
    write_json(YAHOO_CACHE, cache)
    log(f"Yahoo: {len(due)} companies due, {len(refreshed)} refreshed, {failures} request failures")
    return cache, refreshed, failures


# ------------------------------------------------ the companies' own IR pages (the 8 hyperscalers)

def ir_q4(host, now):
    """Q4 Inc. investor sites (Meta, Amazon, Alphabet, Oracle, CoreWeave) list the next earnings call as an event."""
    zones = {"P": "America/Los_Angeles", "M": "America/Denver", "C": "America/Chicago", "E": "America/New_York"}
    body = fetch_cached("ir_" + re.sub(r"\W+", "_", host.split("//")[1]), host + Q4_EVENTS)
    for event in (body or {}).get("GetEventListResult") or []:
        if not re.search(r"earnings|results", event.get("Title") or "", re.I):
            continue
        start = dt.datetime.strptime(event["StartDate"], "%m/%d/%Y %H:%M:%S")
        zone = zones.get((event.get("TimeZone") or " ")[0].upper())
        when = "unknown"
        if zone:
            start = start.replace(tzinfo=ZoneInfo(zone)).astimezone(NY)
            when = session_time(start, "09:30", "16:00")
        if start.date() >= now:
            return {"date": start.date().isoformat(), "time": when, "url": host + event.get("LinkToDetailPage", "")}
    return None


def ir_microsoft(c, now):
    """Microsoft publishes an event page per fiscal quarter once the date is set (404 before that)."""
    last_end = dt.date(now.year, ((now.month - 1) // 3) * 3 + 1, 1) - dt.timedelta(days=1)   # last quarter end
    month = last_end.month + 3                                    # any day of the next quarter-end month
    nxt = dt.date(last_end.year + (month > 12), (month - 1) % 12 + 1, 1)
    for end in (last_end, nxt):
        fy, q = fiscal_quarter(end, c["fye"])
        url = f"https://www.microsoft.com/en-us/investor/events/fy-{fy}/earnings-fy-{fy}-q{q}"
        page = fetch_cached(f"ir_microsoft_fy{fy}_q{q}", url, as_json=False)
        if not page:
            continue
        m = re.search(r'"EventName":"[^"]*Earnings[^"]*","DateTime":\{"TimeZone":"\w*","UTC":"([0-9T:\-]+)"',
                      html.unescape(page))
        if not m:
            continue
        start = dt.datetime.fromisoformat(m.group(1)).replace(tzinfo=dt.timezone.utc).astimezone(NY)
        if start.date() >= now:
            return {"date": start.date().isoformat(), "time": session_time(start, "09:30", "16:00"), "url": url}
    return None


def ir_nebius(url, now):
    """Nebius newsroom: 'Nebius Group announces date of ... results' press release."""
    page = fetch_cached("ir_nebius_newsroom", url, as_json=False) or ""
    items = re.findall(r'"name":"([^"]*announces date of[^"]*)","url":"([^"]+)"', page, re.I)
    if not items:
        return None
    link = items[0][1]                                 # the newsroom lists the newest release first
    slug = re.sub(r"\W+", "_", link.rstrip("/").rsplit("/", 1)[-1])[:80]
    text = html_text(fetch_cached(f"ir_nebius_{slug}", link, as_json=False) or "")
    m = re.search(r"will (?:release|report|announce) its .{0,80}?results on (?:[A-Z][a-z]+day, )?"
                  r"([A-Z][a-z]+ \d{1,2}, \d{4}),?( before| after)?", text)
    if not m:
        return None
    date = dt.datetime.strptime(m.group(1), "%B %d, %Y").date()
    if date < now:
        return None
    when = {"before": "bmo", "after": "amc"}.get((m.group(2) or "").strip(), "unknown")
    return {"date": date.isoformat(), "time": when, "url": link}


def ir_iren(url, now):
    """IREN investors page: each results call is a card 'Mon D, YYYY' + 'IREN Q1 FY27 Results Conference Call'."""
    page = fetch_cached("ir_iren_investors", url, as_json=False) or ""
    dates = []
    for d, _title in re.findall(r">([A-Z][a-z]{2,8} \d{1,2}, \d{4})</p><h2[^>]*>([^<]*Results Conference Call[^<]*)</h2>", page):
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                dates.append(dt.datetime.strptime(d, fmt).date())
                break
            except ValueError:
                pass
    upcoming = sorted(x for x in dates if x >= now)
    return {"date": upcoming[0].isoformat(), "time": "unknown", "url": url} if upcoming else None


def ir_date(c, now):
    kind, where = c["ir"]
    if kind == "q4":
        return ir_q4(where, now)
    if kind == "microsoft":
        return ir_microsoft(c, now)
    if kind == "nebius":
        return ir_nebius(where, now)
    return ir_iren(where, now)


# ------------------------------------------------ calendar history (one row per change)

def latest_calendar_rows(hist):
    """{(id, source): newest row}."""
    latest = {}
    for r in hist:
        k = (r["id"], r["source"])
        if k not in latest or r["seen"] >= latest[k]["seen"]:
            latest[k] = r
    return latest


def collect_calendar(backfill=False):
    """Read the three calendar sources and record what changed. Returns how many sources worked."""
    now = day(today())
    targets = calendar_targets()
    latest = latest_calendar_rows(read_history(CAL_DATASET))
    observations = []          # (id, source, date or None, time, estimate, symbol, url)
    sources_ok = 0

    # Alpha Vantage: US listings. A US company missing from the CSV has no report within 3 months.
    try:
        av = fetch_alpha_vantage()
        sources_ok += 1
        for node_id, t in targets.items():
            if t["av"]:
                hit = av.get(t["av"])
                observations.append((node_id, "alpha_vantage", hit and hit["date"], hit and hit["time"],
                                     None, t["av"], AV_DOC_URL))
        log(f"Alpha Vantage: {sum(1 for t in targets.values() if t['av'] and t['av'] in av)} of our US listings dated")
    except Exception as e:
        log(f"WARNING Alpha Vantage failed ({type(e).__name__}: {e}); keeping previous data")

    # Yahoo Finance: every listing, refreshed on a schedule (only refreshed symbols are compared).
    try:
        cache, refreshed, failures = refresh_yahoo(targets, backfill)
        if refreshed or not failures:
            sources_ok += 1
        for node_id in refreshed:
            answered = [s for s in targets[node_id]["yahoo"] if cache.get(s)]
            symbol = next((s for s in answered if cache[s].get("ok")), answered[0])
            entry = cache[symbol]
            date, when = yahoo_date(symbol, entry)
            if date and date < now.isoformat():
                date = when = None                     # already reported; Yahoo has no next date yet
            observations.append((node_id, "yahoo", date, when, entry.get("estimate") if date else None,
                                 symbol, f"https://finance.yahoo.com/quote/{symbol}"))
    except Exception as e:
        log(f"WARNING Yahoo Finance failed ({type(e).__name__}: {e}); keeping previous data")

    # The 8 companies' own IR pages.
    ir_ok = 0
    for c in COMPANIES:
        try:
            hit = ir_date(c, now)
            ir_ok += 1
            observations.append((c["id"], "ir", hit and hit["date"], hit and hit["time"], False if hit else None,
                                 c["ticker"], hit["url"] if hit else None))
        except Exception as e:
            log(f"WARNING IR page {c['id']} failed ({type(e).__name__}: {str(e)[:120]}); keeping previous data")
    sources_ok += 1 if ir_ok else 0
    log(f"IR pages: {ir_ok} of {len(COMPANIES)} read")

    # Append a row only when a source's answer for a company changed since its last recorded row.
    rows = []
    for node_id, source, date, when, estimate, symbol, url in observations:
        prev = latest.get((node_id, source))
        if not date and (not prev or not prev.get("date") or prev["date"] < now.isoformat()):
            continue                                   # nothing listed now, nothing upcoming recorded before
        if prev and (prev.get("date"), prev.get("time"), prev.get("estimate")) == (date, when, estimate):
            continue
        rows.append({"id": node_id, "ticker": targets.get(node_id, {}).get("ticker") or symbol,
                     "source": source, "symbol": symbol, "date": date, "time": when, "estimate": estimate,
                     "url": url, "seen": today()})
    added = append_history(CAL_DATASET, rows, ("id", "source", "date", "time", "estimate", "seen"))
    log(f"history {CAL_DATASET}: +{added} rows")
    return sources_ok


# ============================================================ build the web file from history

def build_companies(hist):
    best = {}
    for r in hist:
        k = (r["id"], r["end"])
        if k not in best or (r.get("filed") or "", r["seen"]) >= (best[k].get("filed") or "", best[k]["seen"]):
            best[k] = r
    out = []
    for c in COMPANIES:
        rows = sorted((r for (cid, _), r in best.items() if cid == c["id"]), key=lambda r: r["end"],
                      reverse=True)[:KEEP_QUARTERS]
        quarters = []
        for r in rows:
            capex, ocf, lease = r.get("capex_usd"), r.get("ocf_usd"), r.get("lease_principal_usd")
            fcf = ocf - capex if ocf is not None and capex is not None else None
            quarters.append({
                "period": r["period"], "fiscal": r["fiscal"], "end": r["end"],
                "capex_usd": capex, "ocf_usd": ocf, "fcf_usd": fcf, "lease_principal_usd": lease,
                "fcf_after_leases_usd": fcf - lease if fcf is not None and lease is not None else None,
                "form": r["form"], "filed": r["filed"], "accn": r["accn"], "url": r["url"],
            })
        out.append({"id": c["id"], "ticker": c["ticker"], "quarters": quarters})
    return out


def build_calendar(hist):
    now = day(today())
    horizon = (now + dt.timedelta(days=CALENDAR_DAYS)).isoformat()
    by_id = {}
    for (node_id, source), r in latest_calendar_rows(hist).items():
        if r.get("date") and now.isoformat() <= r["date"] <= horizon:
            by_id.setdefault(node_id, {})[source] = r
    out = []
    for node_id, src in by_id.items():
        ir, av, yh = src.get("ir"), src.get("alpha_vantage"), src.get("yahoo")
        confirmed = False
        if ir:
            date, confirmed = ir["date"], True
        elif av and yh and av["date"] == yh["date"] and yh.get("estimate") is False:
            date, confirmed = av["date"], True
        elif yh and yh.get("estimate") is False:
            date = yh["date"]                          # Yahoo's vendor says it is set, but a second source differs
        else:
            date = (av or yh)["date"]
        agreeing = [r for r in (ir, av, yh) if r and r["date"] == date]
        when = next((r["time"] for r in agreeing if r.get("time") in ("bmo", "amc")), "unknown")
        out.append({
            "id": node_id, "ticker": agreeing[0].get("ticker"), "date": date, "time": when, "confirmed": confirmed,
            "sources": [{"name": SOURCE_NAMES[r["source"]], "url": r["url"]} for r in agreeing],
        })
    return sorted(out, key=lambda x: (x["date"], x["id"]))


def build_note(companies):
    parts = [
        "Quarterly cash flow from SEC XBRL filings (10-Q, 10-K). 10-Q cash-flow figures are year-to-date, so "
        "discrete quarters are derived by differencing (Q2 = H1 - Q1, Q4 = full year - 9 months) unless a 3-month "
        "figure is tagged; a restated period shows the most recently filed value.",
        "capex = purchases of property and equipment; FCF = operating cash flow - capex; FCF after leases also "
        "subtracts principal payments on finance leases. period = calendar quarter of the period end; fiscal = "
        "the company's own label.",
    ]
    parts += [c["caveat"] for c in COMPANIES if c.get("caveat")]
    no_lease = [c["id"] for c in companies if c["quarters"] and c["quarters"][0]["lease_principal_usd"] is None]
    if no_lease:
        parts.append("No finance-lease principal payment figure (us-gaap FinanceLeasePrincipalPayments) for the "
                     f"latest quarter of: {', '.join(no_lease)}; FCF after leases is blank there.")
    parts.append("Earnings calendar: Alpha Vantage (US listings) and Yahoo Finance (all listings) for every public "
                 f"company in the graph, next {CALENDAR_DAYS} days; confirmed = the company's own investor-relations "
                 "page lists the date, or Alpha Vantage and Yahoo Finance agree and Yahoo does not mark it as an "
                 "estimate.")
    return " ".join(parts)


def build():
    """Rebuild graph/hyperscaler_cash.json from history only."""
    cash_hist, cal_hist = read_history(CASH_DATASET), read_history(CAL_DATASET)
    companies = build_companies(cash_hist)
    seen = [r["seen"] for r in cash_hist + cal_hist if r.get("seen")]
    data = {
        "updated": max(seen) if seen else today(),
        "note": build_note(companies),
        "companies": companies,
        "calendar": build_calendar(cal_hist),
    }
    write_json(OUT, data)
    log(f"wrote {OUT.relative_to(ROOT)}: {sum(len(c['quarters']) for c in companies)} quarters, "
        f"{len(data['calendar'])} calendar dates")
    return data


def run(backfill=False):
    """Fetch today's data, append history, rebuild the web file. Returns False only if every source failed."""
    load_env()
    CACHE.mkdir(parents=True, exist_ok=True)
    cash_ok = collect_cash(backfill)
    calendar_ok = collect_calendar(backfill)
    build()
    return cash_ok > 0 or calendar_ok > 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Hyperscaler capex / cash flow (SEC XBRL) + earnings calendar")
    p.add_argument("--backfill", action="store_true",
                   help="record every quarter XBRL can derive and refresh every Yahoo symbol")
    p.add_argument("--build-only", action="store_true", help="rebuild graph/hyperscaler_cash.json from history")
    args = p.parse_args(argv)
    if args.build_only:
        build()
        return 0
    return 0 if run(backfill=args.backfill) else 1


if __name__ == "__main__":
    sys.exit(main())
