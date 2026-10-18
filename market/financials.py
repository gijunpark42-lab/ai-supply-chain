"""market/financials.py -- a basic financial-statement table for every public company in the graph.

The user asked on 2026-10-17 for a table like Naver Finance's 재무제표 in the company panel: revenue, PER, PBR,
EBITDA, EBIT, pre-tax income, income after tax, net income, dividend yield and ROA, by fiscal QUARTER (the default
tab) and by fiscal YEAR, with QoQ / YoY growth, each column labelled with the company's OWN fiscal period
("Q3 26", "FY26": the user chose fiscal labels, not calendar ones), and the street estimates for the next quarter,
this fiscal year and the next one as extra "(E)" columns. Every public company of the graph, every market.

Web files (data contract, the company panel reads them):
  graph/financials_index.json   {"updated", "source": {"name", "url"},
                                 "companies": {"<node id>": {"file", "latest_end", "currency"}}}
  graph/financials/<file>       {"company", "ticker" (Yahoo symbol), "currency", "unit": 1000000,
                                 "fiscal_year_end": "MM-DD", "updated", "quarterly": [period, oldest -> newest, <= 8],
                                 "annual": [period, <= 4], "estimates": {"quarter", "fy", "next_fy"},
                                 "preliminary": {...} | null (Korea), "source": {"name", "url"},
                                 "sources": [{"name", "url"}] (Yahoo + the filings used), "notes": [str]}
  period = {"end" (the company's own period end), "label", "fiscal_year", "fiscal_quarter", "revenue",
            "gross_profit", "ebitda", "ebit", "operating_income" (as reported), "pretax_income",
            "net_income_after_tax" (세후손익, incl. minority interests), "net_income" (당기순이익, attributable to
            shareholders), "eps_diluted" (reported), "eps_adjusted" (Yahoo's EPS on the analysts' basis, the basis
            of the estimates: for US companies usually adjusted / non-GAAP), "per", "pbr", "dividend_yield_pct",
            "roa_pct", "ocf" (operating cash flow), "capex" (capital expenditure, a positive number), "fcf"
            (ocf - capex), "fcf_after_leases" (fcf - finance-lease principal payments; null unless the company files
            those: SEC 10-K / 10-Q filers), "qoq": {...} | null, "yoy": {...}, "derived": [field names]}
  Money is in the company's reporting currency, in millions ("unit"), rounded to 2 decimals; EPS is in full
  currency units (4 decimals). per = price at the period end / trailing-4-quarter diluted EPS (annual: that year's
  EPS); pbr = price / book value per share at the period end; dividend_yield_pct = dividends of the last 12 months
  per share / price; roa_pct = trailing-4-quarter (annual: the year's) net income / average total assets (period
  end and 12 months earlier). Each is null when an input is missing or the EPS / book value is not positive.
  qoq / yoy: % change of revenue, ebit, net_income and eps_diluted against the previous fiscal quarter / the same
  quarter a year earlier (annual: the previous fiscal year); null when the earlier value is missing, zero or
  negative (a % change from a loss has no meaning; the values themselves are in the table). "fcf" too, but only
  when both values are positive (free cash flow swings through zero).

Sources:
  - Yahoo Finance, read with yfinance's own session (cookie + crumb): per company ONE fundamentals-timeseries
    request (quarterly + annual income statement, balance sheet and cash-flow rows), ONE quoteSummary request (earnings
    summary, estimates, key statistics, calendar) and ONE monthly price chart with dividends and splits. That is the
    same data as yfinance's Ticker.quarterly_income_stmt / income_stmt / quarterly_balance_sheet / balance_sheet /
    earnings_estimate / revenue_estimate / dividends / history / info, in 3 requests instead of about 9, so the
    whole graph fits in Yahoo's rate limit. Unofficial and personal-use, like the earnings dates of hyperscaler_cash.
  - The companies' own filings (verification of 2026-10-17: Yahoo lags, holds about 5 quarters, dates periods at
    month ends and has the odd wrong figure): SEC XBRL company facts for US filers (market/financials_sec.py) and
    OpenDART for Korean listings (market/financials_dart.py).

Rules that make the numbers line up (each is said in the file's notes when it applies):
  - Period ends: inside, every period is keyed by Yahoo's month end (a date in the first 7 days of a month counts as
    the previous month's end, so a 52/53-week year ending 2026-09-03 is "2026-08-31"), so the same period never
    shows up twice. The file's "end" is the company's OWN date (the user: the column shows the date, so no calendar
    label is needed): the SEC filings' period ends, Yahoo's mostRecentQuarter and lastFiscalYearEnd, and for every
    other period (estimates too) the company's weekday rule (PeriodEnds). Month-end reporters keep the month end.
  - Fiscal labels: the fiscal year end month is the most recent fiscal year's (lastFiscalYearEnd: a company that
    moved its year end is labelled on its new calendar); a quarter belongs to the fiscal year whose end is the next
    fiscal year end on or after it, and the year is named by the calendar year it ends in (Micron's quarter ending
    May 2026 = "Q3 26", NVIDIA's ending July 2026 = "Q2 27", a March year ending in 2026 = "FY26").
  - The filings first (merge_filing): a 10-K / 10-Q filer's XBRL facts and a Korean company's DART reports fill
    what Yahoo lacks (the newest filed period before Yahoo has it, and the quarters before Yahoo's 5-quarter
    window, as the YoY base); a fiscal Q4 is the year minus the nine months (EPS: SEC = Q4 net income / Q4 diluted
    shares, DART = the year's EPS minus the nine months' cumulative EPS); operating income is the as-reported one.
    Each XBRL concept is checked against Yahoo's figures on the periods both have. A 20-F filer's facts only check
    EPS and give the dates (a 20-F can use another GAAP than the home listing: TSMC). Korean book value per share
    uses DART's shares outstanding of all classes (common + preferred - treasury).
  - Then Yahoo's earnings summary (quoteSummary "earnings"): revenue and net income of the newest periods that
    neither has yet. A 0 there is "not reported yet" (blank); only periods newer than the newest known one are
    added; a series that disagrees (> 2%) with the statements on revenue or net income is not used.
  - Cash flow (2026-10-17), ONE source per company, so a table never mixes capex definitions: a 10-K / 10-Q
    filer's SEC XBRL facts (market/financials_sec.cash_flow: market/hyperscaler_cash.py's tags and year-to-date
    differencing, so the 8 companies of graph/hyperscaler_cash.json show the same quarters), else a Korean
    company's DART cash-flow statements (year-to-date too: Q2 = H1 - Q1 ... Q4 = FY - 9M), else Yahoo's cash-flow
    rows (Operating Cash Flow, Capital Expenditure with its sign turned, Free Cash Flow where one of the two is
    missing). fcf = ocf - capex; fcf / fcf_after_leases are listed in "derived" when an input is.
  - Contradictions: a net income that does not match diluted EPS x diluted shares while the summary's does is
    replaced (reconcile_net_income); an EPS that does not match net income / shares while the SEC filing's does is
    replaced (reconcile_eps); an EBITDA equal to EBIT (no D&A) is left blank.
  - Gaps: one missing quarter of a fiscal year = FY - the other three (never a negative revenue, never an EPS of
    the other sign than the quarter's net income); a missing EPS = Yahoo's reported EPS when it is within 1% of net
    income / diluted shares, else net income / diluted shares (when the company's EPS follows its share count).
    Everything computed is listed in "derived".
  - Stock splits: Yahoo's price chart is split-adjusted, but a statement filed before a recent split still has the
    old per-share numbers. EPS and share counts are put on the current share basis when the implied share count
    (net income / EPS) matches the current one only after the split factor; listed in "derived" and the notes.
  - Currency: PER / PBR convert the price into the reporting currency at the month-end rate (Yahoo FX), e.g. a Hong
    Kong listing reporting in CNY. A US-listed ADR whose statements are in another currency gets no PER / PBR (the
    ADR ratio is unknown); a node whose US line is an ADR of a home listing (TSMC = TSM -> 2330.TW, the same
    mapping as web/src/lib/yahoo.ts homeSymbol) uses the home listing, so price and per-share data match.

Schedule: daily (market/run_all.py), at most DAILY_MAX_MINUTES of Yahoo, then at most FILINGS_MAX_MINUTES of the
same companies' filings. Refreshed each day: companies whose earnings date (graph/hyperscaler_cash.json calendar,
or Yahoo's) was in the last 4 days or is in the next 10 days, companies never fetched (or whose last fetch failed),
and a rotating 1/7 of the rest (each company at least weekly). --backfill fetches every company. Requests are
paced (PAUSE seconds apart) and back off on HTTP 429 (the back-off counts against the time budget).

Files:
  market/cache/financials/<symbol>.json   the latest raw Yahoo answers per company (gitignored); build() reads them,
                                          so a rebuild needs no network. A company without a cache keeps its file.
                                          "format" 2 (2026-10-17) = the cash-flow rows were requested too; an
                                          older cache is fetched again even on the day it was written.
  market/cache/financials/sec/, dart/     the companies' filings as last read (gitignored, see the two modules).
  market/history/financials_snapshots.jsonl  ADD-only: every reported period as first seen (key company + end +
                                          period_type), so a later restatement can be spotted; also fills quarters
                                          that have dropped out of Yahoo's 5-quarter window.
  market/history/financials_state.json    per company: symbol, last fetch date, ok, next earnings date.

CLI:
  python -X utf8 -m market.financials                    daily run
  python -X utf8 -m market.financials --backfill         every company (about 2.5 s each)
  python -X utf8 -m market.financials --build-only       rebuild the web files from the cache, no network
  python -X utf8 -m market.financials --only "Micron,NVIDIA" [--limit N] [--max-minutes M]
  python -X utf8 -m market.financials --filings-only [--workers 8]   SEC / DART caches of every company, rebuild
"""
import argparse
import calendar
import datetime as dt
import hashlib
import json
import logging
import math
import os
import sys
import time
from collections import Counter

from market import financials_dart, financials_sec
from market.common import (GRAPH, HISTORY, ROOT, append_history, company_file_names, read_history, read_json,
                           today, universe, write_json)

DATASET = "financials_snapshots"
OUT_DIR_NAME = "financials"
CACHE = ROOT / "market" / "cache" / "financials"
STATE_FILE_NAME = "financials_state.json"
UNIT = 1_000_000
KEEP_QUARTERS = 8
KEEP_YEARS = 4
PAUSE = 0.6                 # seconds after each Yahoo request (3 per company: about 2-2.5 s per company)
DAILY_MAX_MINUTES = 15      # a daily run stops fetching Yahoo after this long (the rest waits for tomorrow)
FILINGS_MAX_MINUTES = 5     # ... then spends at most this long on the same companies' SEC / DART filings
DART_WORKERS = 4            # DART answers a statement call in ~8 s: read several companies at once (one shared pace)
ROTATION_DAYS = 7
EARNINGS_BEFORE_DAYS = 10   # refresh daily from 10 days before an earnings date...
EARNINGS_AFTER_DAYS = 4     # ...to 4 days after it
SOURCE = {"name": "Yahoo Finance", "url": "https://finance.yahoo.com"}

TIMESERIES_URL = "https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{s}"
SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{s}"
CHART_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{s}"
SUMMARY_MODULES = "earnings,earningsTrend,defaultKeyStatistics,financialData,price,calendarEvents"

# Contract field -> Yahoo timeseries row names, first one with a value wins.
FLOW_FIELDS = {
    "revenue": ("TotalRevenue", "OperatingRevenue"),
    "gross_profit": ("GrossProfit",),
    "ebitda": ("EBITDA", "NormalizedEBITDA"),
    "ebit": ("EBIT",),
    "operating_income": ("TotalOperatingIncomeAsReported", "OperatingIncome"),   # as reported, not "normalized"
    "pretax_income": ("PretaxIncome",),
    "net_income_after_tax": ("NetIncomeIncludingNoncontrollingInterests",),
    "net_income": ("NetIncomeCommonStockholders", "NetIncome"),
}
PER_SHARE_FIELDS = {"eps_diluted": ("DilutedEPS",), "diluted_shares": ("DilutedAverageShares",)}
BALANCE_FIELDS = {
    "total_assets": ("TotalAssets",),
    "equity": ("CommonStockEquity", "StockholdersEquity"),
    "shares": ("OrdinarySharesNumber", "ShareIssued"),
}
# Yahoo's cash-flow rows (2026-10-17). Capital Expenditure is negative there; it is stored as a positive "capex".
# The filings' figures replace them for SEC 10-K / 10-Q filers and Korean companies (apply_cash_flow).
CASH_FIELDS = {"ocf": ("OperatingCashFlow",), "capex": ("CapitalExpenditure",), "fcf": ("FreeCashFlow",)}
ALL_FIELDS = {**FLOW_FIELDS, **PER_SHARE_FIELDS, **BALANCE_FIELDS, **CASH_FIELDS}
MONEY = set(FLOW_FIELDS) | {"total_assets", "equity"} | set(CASH_FIELDS)      # stored in millions
GROWTH_FIELDS = ("revenue", "ebit", "net_income", "eps_diluted")
CASH_KEYS = ("ocf", "capex", "fcf", "lease_principal")       # inside a period ("lease_principal" is not shown)
PERIOD_KEYS = ("end", "label", "fiscal_year", "fiscal_quarter", "revenue", "gross_profit", "ebitda", "ebit",
               "operating_income", "pretax_income", "net_income_after_tax", "net_income", "eps_diluted",
               "eps_adjusted", "per", "pbr", "dividend_yield_pct", "roa_pct", "ocf", "capex", "fcf",
               "fcf_after_leases", "qoq", "yoy", "derived")
RAW_FORMAT = 2              # 2 (2026-10-17): the timeseries request includes the cash-flow rows

# ------------------------------------------------ graph node -> Yahoo symbol (port of web/src/lib/yahoo.ts)

SYMBOL_OVERRIDE = {
    "BESI": "BESI.AS",
    "6600.T": "285A.T",          # Kioxia listed under code 285A
    "222800": "222800.KQ",       # Simmtech (KOSDAQ, filed as KRX)
    "033170.KS": "033170.KQ",    # Signetics (KOSDAQ)
    "RR.": "RR.L",               # Rolls-Royce: the LSE code has a trailing dot
}
# yahoo.ts EXCHANGE_SUFFIX, plus the boards it does not list (from market/hyperscaler_cash.py).
EXCHANGE_SUFFIX = {
    "TSE": ".T", "KOSPI": ".KS", "KRX": ".KS", "KOSDAQ": ".KQ", "KONEX": ".KN", "TWSE": ".TW", "TPEx": ".TWO",
    "SZSE": ".SZ", "SSE": ".SS", "HKEX": ".HK", "XETRA": ".DE", "AMS": ".AS", "Euronext Amsterdam": ".AS",
    "EPA": ".PA", "Euronext Paris": ".PA", "Euronext Brussels": ".BR", "MIL": ".MI", "STO": ".ST",
    "OMX Stockholm": ".ST", "OMX Helsinki": ".HE", "OSE": ".OL", "SIX": ".SW", "VIE": ".VI", "LSE": ".L",
    "IDX": ".JK", "NSE": ".NS", "TSX": ".TO", "ASX": ".AX", "SGX": ".SI", "Bursa": ".KL", "Bursa Malaysia": ".KL",
    "B3": ".SA",
}
US_EXCHANGES = {"NASDAQ", "NYSE", "NYSE American", "OTC"}
# yahoo.ts HOME_LISTING: a US line (ADR) -> its home listing, where price and per-share figures share a currency.
HOME_LISTING = {
    "TSM": "2330.TW", "ASX": "3711.TW", "UMC": "2303.TW", "IMOS": "8150.TW", "BABA": "9988.HK", "BIDU": "9888.HK",
    "GDS": "9698.HK", "KC": "3896.HK", "NVO": "NOVO-B.CO", "SNY": "SAN.PA", "AZN": "AZN.L", "SHEL": "SHEL.L",
    "RHHBY": "ROP.SW", "BAYRY": "BAYN.DE", "NOK": "NOKIA.HE", "STM": "STMPA.PA", "ASML": "ASML.AS",
}
KNOWN_SUFFIXES = {s.lstrip(".") for s in EXCHANGE_SUFFIX.values()} | {"CO"}
OTHER_BOARD = {".TW": ".TWO", ".TWO": ".TW", ".KS": ".KQ", ".KQ": ".KS"}   # some graph tickers name the wrong board


def log(msg):
    print(f"[financials] {msg}", flush=True)


def yahoo_symbol(ticker, exchange):
    """The Yahoo symbol of a graph ticker (yahoo.ts yahooSymbol), or None."""
    t = (ticker or "").strip()
    if not t:
        return None
    if t in SYMBOL_OVERRIDE:
        return SYMBOL_OVERRIDE[t]
    if "." in t:
        if exchange in US_EXCHANGES and t.rsplit(".", 1)[1].upper() not in KNOWN_SUFFIXES:
            return t.replace(".", "-")             # BRK.B -> BRK-B
        return t                                   # already carries a Yahoo suffix
    suffix = EXCHANGE_SUFFIX.get(exchange)
    if suffix:
        if suffix == ".HK" and t.isdigit():
            t = t.zfill(4)
        return t + suffix
    if t.isdigit():
        return t + ".KS"                           # legacy fallback: bare numeric = KRX
    return t                                       # plain US / ADR ticker


def symbol_candidates(ticker, exchange):
    """Symbols to try, best first: the home listing of an ADR, the symbol itself, the other Korean/Taiwan board."""
    s = yahoo_symbol(ticker, exchange)
    if not s:
        return []
    out = []
    if exchange in US_EXCHANGES and s in HOME_LISTING:
        out.append(HOME_LISTING[s])
    out.append(s)
    if "." in s:
        base, suffix = s.rsplit(".", 1)
        other = OTHER_BOARD.get("." + suffix)
        if other:
            out.append(base + other)
    return out


# ------------------------------------------------ dates and fiscal labels

def month_end(value):
    """A date (ISO string, date or unix seconds) -> the Yahoo-style month end, as YYYY-MM-DD. A date in the first
    7 days of a month belongs to the previous month (52/53-week fiscal years end a few days after a month end)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        d = dt.datetime.fromtimestamp(value, dt.timezone.utc).date()
    elif isinstance(value, dt.date):
        d = value
    else:
        d = dt.date.fromisoformat(str(value)[:10])
    if d.day <= 7:
        d = d.replace(day=1) - dt.timedelta(days=1)
    return d.replace(day=calendar.monthrange(d.year, d.month)[1]).isoformat()


def add_months(end, months):
    """A month-end date moved by whole months (stays a month end)."""
    y, m = int(end[:4]), int(end[5:7])
    total = y * 12 + (m - 1) + months
    y, m = divmod(total, 12)
    m += 1
    return dt.date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def fiscal_year_end_month(annual_ends, last_fy_end=None):
    """The fiscal year end month of the MOST RECENT fiscal year: Yahoo's lastFiscalYearEnd, else the newest annual
    period end (a company that moved its year end, like Daifuku from March to December or Hut 8 from June to
    December, is labelled by its current calendar, as Yahoo does)."""
    if last_fy_end:
        return int(month_end(last_fy_end)[5:7])
    ends = [e for e in annual_ends if e]
    return int(max(ends)[5:7]) if ends else 12


def fiscal_of(end, fy_month):
    """(fiscal year, fiscal quarter) of a period ending in `end`: the fiscal year is the one whose end is the next
    fiscal year end on or after `end`, named by the calendar year it ends in."""
    y, m = int(end[:4]), int(end[5:7])
    fiscal_year = y + (1 if m > fy_month else 0)
    months_to_year_end = (fy_month - m) % 12
    quarter = min(4, max(1, 4 - round(months_to_year_end / 3)))
    return fiscal_year, quarter


def quarter_label(fiscal_year, fiscal_quarter):
    return f"Q{fiscal_quarter} {fiscal_year % 100:02d}"


def year_label(fiscal_year):
    return f"FY{fiscal_year % 100:02d}"


def fiscal_quarter_end(fiscal_year, fiscal_quarter, fy_month):
    """The month end of fiscal quarter n of a fiscal year (the year ends in fiscal_year-fy_month)."""
    year_end = dt.date(fiscal_year, fy_month, calendar.monthrange(fiscal_year, fy_month)[1]).isoformat()
    return add_months(year_end, -3 * (4 - fiscal_quarter))


# ------------------------------------------------ small helpers

def raw_value(x):
    """quoteSummary values come as numbers (formatted=false) or as {"raw", "fmt"} objects."""
    if isinstance(x, dict):
        x = x.get("raw")
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)) and math.isfinite(x):
        return float(x)
    return None


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def pct_change(cur, prev):
    if cur is None or prev is None or prev <= 0:
        return None
    return round((cur - prev) / prev * 100, 2)


def pct_change_positive(cur, prev):
    """A % change only between two positive values (free cash flow: a change to or from a negative is no growth)."""
    return pct_change(cur, prev) if cur is not None and cur > 0 else None


def rounded(field, value):
    if value is None:
        return None
    if field == "eps_diluted":
        return round(value, 4)
    return round(value, 2)


# ------------------------------------------------ Yahoo (network)

class RateLimited(Exception):
    pass


def _yf_data():
    import yfinance  # noqa: F401  (imports the package so its session is set up)
    from yfinance.data import YfData
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return YfData()


def _get_json(url, params):
    """One Yahoo request through yfinance's session. Returns parsed JSON, or None for an unknown symbol (404)."""
    import requests
    from yfinance.exceptions import YFRateLimitError
    data = _yf_data()
    try:
        response = data.get(url, params=params, timeout=30)
    except YFRateLimitError as e:
        raise RateLimited(str(e))
    if response.status_code == 429:
        raise RateLimited("HTTP 429")
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise requests.HTTPError(f"HTTP {response.status_code} for {url}")
    return response.json()


def fetch_timeseries(symbol):
    """Quarterly (3-month) and annual (12-month) statement rows: {"currency", "quarterly": {row: {end: value}},
    "annual": {...}}. Ends are Yahoo month ends."""
    names = sorted({n for names in ALL_FIELDS.values() for n in names})
    types = ",".join(p + n for p in ("quarterly", "annual") for n in names)
    now = int(time.time())
    j = _get_json(TIMESERIES_URL.format(s=symbol), {"symbol": symbol, "type": types,
                                                     "period1": now - 7 * 366 * 86400, "period2": now + 86400})
    out = {"currency": None, "quarterly": {}, "annual": {}}
    for res in ((j or {}).get("timeseries") or {}).get("result") or []:
        typ = ((res.get("meta") or {}).get("type") or [None])[0]
        if not typ:
            continue
        scale = "quarterly" if typ.startswith("quarterly") else "annual" if typ.startswith("annual") else None
        if not scale:
            continue
        name = typ[len(scale):]
        want = "3M" if scale == "quarterly" else "12M"
        for v in res.get(typ) or []:
            if not v or (v.get("periodType") and v["periodType"] != want):
                continue
            val = raw_value((v.get("reportedValue") or {}))
            if val is None or not v.get("asOfDate"):
                continue
            out[scale].setdefault(name, {})[v["asOfDate"]] = val
            if v.get("currencyCode") and name in ("TotalRevenue", "NetIncome", "TotalAssets"):
                out["currency"] = out["currency"] or v["currencyCode"]
    return out


def fetch_summary(symbol):
    j = _get_json(SUMMARY_URL.format(s=symbol), {"modules": SUMMARY_MODULES, "formatted": "false",
                                                  "corsDomain": "finance.yahoo.com", "symbol": symbol})
    result = (((j or {}).get("quoteSummary") or {}).get("result") or [None])[0]
    return result or {}


def fetch_chart(symbol, range_="7y"):
    """Monthly closes (split-adjusted), dividends and splits: {"currency", "closes": {"YYYY-MM": close},
    "dividends": [[date, amount]], "splits": [[date, ratio]]}."""
    from zoneinfo import ZoneInfo
    j = _get_json(CHART_URL.format(s=symbol), {"range": range_, "interval": "1mo", "events": "div,splits",
                                                "includePrePost": "false"})
    res = (((j or {}).get("chart") or {}).get("result") or [None])[0]
    if not res:
        return None
    meta = res.get("meta") or {}
    try:
        tz = ZoneInfo(meta.get("exchangeTimezoneName") or "UTC")
    except Exception:
        tz = dt.timezone.utc
    closes = {}
    quote = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    for ts, close in zip(res.get("timestamp") or [], quote):
        if num(close) is None:
            continue
        closes[dt.datetime.fromtimestamp(ts, tz).strftime("%Y-%m")] = round(close, 6)   # last bar of a month wins
    events = res.get("events") or {}
    dividends = sorted([dt.datetime.fromtimestamp(d["date"], tz).date().isoformat(), d["amount"]]
                       for d in (events.get("dividends") or {}).values() if num(d.get("amount")) is not None)
    splits = []
    for s in (events.get("splits") or {}).values():
        num_, den = num(s.get("numerator")), num(s.get("denominator"))
        if num_ and den:
            splits.append([dt.datetime.fromtimestamp(s["date"], tz).date().isoformat(), num_ / den])
    return {"currency": meta.get("currency"), "closes": closes, "dividends": dividends, "splits": sorted(splits)}


def fetch_company(symbol):
    """All raw answers for one symbol (3 requests), or None when Yahoo has no statements for it."""
    ts = fetch_timeseries(symbol)
    time.sleep(PAUSE)
    has_rows = any(ts["quarterly"].get(n) or ts["annual"].get(n) for n in ("TotalRevenue", "NetIncome",
                                                                           "NetIncomeCommonStockholders"))
    summary = fetch_summary(symbol)
    time.sleep(PAUSE)
    has_summary = bool(((summary.get("earnings") or {}).get("financialsChart") or {}).get("yearly"))
    if not has_rows and not has_summary:
        return None
    chart = fetch_chart(symbol)
    time.sleep(PAUSE)
    return {"symbol": symbol, "fetched": today(), "format": RAW_FORMAT, "timeseries": ts, "summary": summary,
            "chart": chart}


_FX_MEMO = {}


def fx_closes(from_ccy, to_ccy):
    """Monthly rates {"YYYY-MM": units of to_ccy per 1 from_ccy} (Yahoo FX), cached for the day; None if unknown."""
    if from_ccy == to_ccy:
        return None
    key = f"{from_ccy}{to_ccy}"
    if key in _FX_MEMO:
        return _FX_MEMO[key]
    path = CACHE / "fx" / f"{key}.json"
    cached = read_json(path)
    rates = None
    if cached and cached.get("fetched") == today():
        rates = cached.get("closes")
    else:
        for pair, invert in ((f"{from_ccy}{to_ccy}=X", False), (f"{to_ccy}{from_ccy}=X", True)):
            try:
                chart = fetch_chart(pair)
            except RateLimited:
                raise
            except Exception:
                chart = None
            time.sleep(PAUSE)
            if chart and chart["closes"]:
                rates = {k: (1 / v if invert else v) for k, v in chart["closes"].items() if v}
                break
        if rates is None and cached:
            rates = cached.get("closes")           # yesterday's rates beat none
        write_json(path, {"fetched": today(), "closes": rates})
    _FX_MEMO[key] = rates
    return rates


def cached_fx(from_ccy, to_ccy):
    """FX for build(): today's (or the last) cached rates only, never the network."""
    if from_ccy == to_ccy:
        return None
    key = f"{from_ccy}{to_ccy}"
    if key not in _FX_MEMO:
        _FX_MEMO[key] = (read_json(CACHE / "fx" / f"{key}.json") or {}).get("closes")
    return _FX_MEMO[key]


# ------------------------------------------------ raw answers -> periods (pure, tested offline)

def statement_periods(ts):
    """{"quarterly": {end: {field: value}}, "annual": {...}, "balances": {end: {...}}} from the timeseries answer.
    Money in millions (capex as a positive number); EPS and share counts as they are. Ends normalized to month
    ends."""
    out = {"quarterly": {}, "annual": {}, "balances": {}}
    for scale in ("quarterly", "annual"):
        rows = (ts or {}).get(scale) or {}
        dates = sorted({month_end(d) for name in rows for d in rows[name]})
        by_norm = {}
        for name, series in rows.items():
            for d, v in series.items():
                by_norm.setdefault(name, {})[month_end(d)] = v
        for end in dates:
            flow, bal = {}, {}
            for field, names in ALL_FIELDS.items():
                v = next((by_norm[n][end] for n in names if end in by_norm.get(n, {})), None)
                if v is None:
                    continue
                v = v / UNIT if field in MONEY else v
                if field == "capex":
                    v = -v                         # Yahoo's Capital Expenditure is a cash outflow (negative)
                (bal if field in BALANCE_FIELDS else flow)[field] = v
            if any(flow.get(f) is not None for f in FLOW_FIELDS) or flow.get("eps_diluted") is not None:
                out[scale][end] = {**flow, **bal}
            if bal:
                out["balances"].setdefault(end, {}).update({k: v for k, v in bal.items()
                                                            if out["balances"].get(end, {}).get(k) is None})
    return out


def snapshot_rows(node_id, symbol, currency, stmt, seen):
    """History rows (ADD-only, key company + end + period_type): each reported statement period as Yahoo gave it
    (in millions, capex as a positive number, as in statement_periods)."""
    rows = []
    for period_type in ("quarterly", "annual"):
        for end, values in sorted(stmt[period_type].items()):
            row = {"seen": seen, "company": node_id, "ticker": symbol, "period_type": period_type, "end": end,
                   "currency": currency, "unit": UNIT}
            row.update({k: (round(v, 4) if k in MONEY or k == "eps_diluted" else v)
                        for k, v in values.items() if v is not None})
            rows.append(row)
    return rows


def merge_history(stmt, hist_rows):
    """Periods that only the history still has (they dropped out of Yahoo's window) are added back."""
    for r in hist_rows:
        scale = r.get("period_type")
        if scale not in ("quarterly", "annual") or not r.get("end") or r["end"] in stmt[scale]:
            continue
        values = {k: r[k] for k in ALL_FIELDS if num(r.get(k)) is not None}
        stmt[scale][r["end"]] = values
        bal = {k: v for k, v in values.items() if k in BALANCE_FIELDS}
        if bal and r["end"] not in stmt["balances"]:
            stmt["balances"][r["end"]] = bal
    return stmt


def later_splits(splits, end):
    """The splits that happened after a period end, oldest first: [(date, ratio)]."""
    return [(d, r) for d, r in splits if d > end and r and r > 0]


def split_adjustment(implied_shares, later_splits, reference_shares):
    """The factor still missing from a period's per-share data: 1 when it already is on today's share basis.
    Candidates are the products of the latest k splits (a statement restated after an older split but before the
    newest one is missing only the newest); the one that brings the implied share count closest to today's wins,
    when it lands within 25%."""
    if not later_splits or not implied_shares or not reference_shares or implied_shares <= 0:
        return 1.0
    candidates, factor = [1.0], 1.0
    for _, ratio in reversed(later_splits):
        factor *= ratio
        candidates.append(factor)
    best = min(candidates, key=lambda f: abs(math.log(implied_shares * f / reference_shares)))
    if best != 1.0 and abs(math.log(implied_shares * best / reference_shares)) < math.log(1.25):
        return best
    return 1.0


def is_us_listing(symbol):
    """A Yahoo symbol without a foreign-market suffix (MU, BRK-B) trades in the US."""
    return bool(symbol) and ("." not in symbol or symbol.rsplit(".", 1)[1].upper() not in KNOWN_SUFFIXES)


def close(a, b, tol, abs_tol=0.0):
    """a and b agree within `tol` of the larger magnitude (or within abs_tol, for rounded small numbers)."""
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol * max(abs(a), abs(b)), abs_tol)


def eps_times_shares(p):
    """Diluted EPS x diluted shares, in millions (what net income should be), or None."""
    if p.get("eps_diluted") is None or not p.get("diluted_shares"):
        return None
    return p["eps_diluted"] * p["diluted_shares"] / UNIT


def _summary_value(x):
    """A summary figure; Yahoo puts 0 where a figure is not reported yet (verification 2026-10-17: LG Electronics'
    preliminary-results quarter had revenue and earnings 0), so 0 counts as missing."""
    v = raw_value(x)
    return None if v is None or v == 0 else v


def summary_quarters(summary, fy_month):
    """[(end, revenue, net income)] from the earnings summary (financialsChart quarterly, ends from earningsChart).
    Empty unless the ends are 3 months apart (a half-year reporter's summary is not a quarter series)."""
    earnings = summary.get("earnings") or {}
    ends = {}
    for q in ((earnings.get("earningsChart") or {}).get("quarterly") or []):
        if q.get("fiscalQuarter") and raw_value(q.get("periodEndDate")):
            ends[q["fiscalQuarter"]] = month_end(raw_value(q["periodEndDate"]))
    out = []
    for q in ((earnings.get("financialsChart") or {}).get("quarterly") or []):
        label = q.get("fiscalQuarter") or ""
        end = ends.get(label)
        if not end and len(label) == 6 and label[0].isdigit() and label[1] == "Q" and label[2:].isdigit():
            end = fiscal_quarter_end(int(label[2:]), int(label[0]), fy_month)
        if end:
            out.append((end, _summary_value(q.get("revenue")), _summary_value(q.get("earnings"))))
    ends = sorted(e for e, _, _ in out)
    if any(add_months(a, 3) != b for a, b in zip(ends, ends[1:])):
        return []
    return out


def summary_years(summary, fy_month):
    """[(end, revenue, net income)] from the earnings summary's yearly chart ("date" = the fiscal year)."""
    out = []
    for y in (((summary.get("earnings") or {}).get("financialsChart") or {}).get("yearly") or []):
        year = y.get("date")
        if isinstance(year, (int, float)) and 1990 < year < 2100:
            end = dt.date(int(year), fy_month, calendar.monthrange(int(year), fy_month)[1]).isoformat()
            out.append((end, _summary_value(y.get("revenue")), _summary_value(y.get("earnings"))))
    return out


def chart_actuals(summary):
    """{month-end: EPS} of Yahoo's earningsChart ("actual": on the analysts' basis, usually adjusted / non-GAAP for
    US companies), plus the year-ago EPS of the estimate entries (0q / +1q: quarters, 0y: the last fiscal year).
    Returns (quarterly, annual)."""
    earnings = summary.get("earnings") or {}
    quarterly, annual = {}, {}
    for q in ((earnings.get("earningsChart") or {}).get("quarterly") or []):
        actual, end = raw_value(q.get("actual")), raw_value(q.get("periodEndDate"))
        if actual is not None and end:
            quarterly[month_end(end)] = actual
    for t in ((summary.get("earningsTrend") or {}).get("trend") or []):
        ago = raw_value((t.get("earningsEstimate") or {}).get("yearAgoEps"))
        if ago is None or not t.get("endDate"):
            continue
        key = add_months(month_end(t["endDate"]), -12)
        if t.get("period") in ("0q", "+1q"):
            quarterly.setdefault(key, ago)
        elif t.get("period") == "0y":
            annual.setdefault(key, ago)
    return quarterly, annual


def fill_from_summary(periods, entries, derived, now=None):
    """Revenue / net income of the newest periods that the statements do not have yet, from Yahoo's earnings
    summary (verification of 2026-10-17):
      - the series is skipped as a whole when it disagrees (> 2%) with the statements on a period both have, in
        revenue or in net income -- unless the summary's net income is the one that matches diluted EPS x diluted
        shares (then the statement figure is the odd one: reconcile_net_income replaces it);
      - only periods NEWER than the newest period that has revenue or net income are added (some small listings
        carry a 10-20 year old series in the summary); without such a period, only periods that ended within
        15 months of `now`.
    A field a known period lacks is still filled. Returns the ends that were added."""
    for end, revenue, earnings in entries:
        known = periods.get(end)
        if not known:
            continue
        if known.get("revenue") and revenue is not None and not close(revenue / UNIT, known["revenue"], 0.02):
            return []
        ni = known.get("net_income")
        if ni is not None and earnings is not None and not close(earnings / UNIT, ni, 0.02):
            implied = eps_times_shares(known)
            if implied is None or not close(earnings / UNIT, implied, 0.01):
                return []
    with_figures = [e for e, p in periods.items() if p.get("revenue") is not None or p.get("net_income") is not None]
    newest = max(with_figures) if with_figures else None
    floor = add_months(month_end(now), -15) if now else None
    added = []
    for end, revenue, earnings in entries:
        p = periods.get(end)
        if p is None:
            if revenue is None and earnings is None:
                continue
            if (newest is not None and end <= newest) or (newest is None and floor and end < floor):
                continue
            p = periods[end] = {}
            added.append(end)
        for field, value in (("revenue", revenue), ("net_income", earnings)):
            if value is not None and p.get(field) is None:
                p[field] = value / UNIT
                derived.setdefault(end, set()).add(field)
    return added


# ------------------------------------------------ filings (SEC XBRL / DART) merged into Yahoo's periods

FILING_FIELDS = list(FLOW_FIELDS) + ["eps_diluted", "diluted_shares"]
ABS_TOL = {"eps_diluted": 0.006}                  # EPS is filed with 2 decimals


def _scaled(field, value):
    return value / UNIT if field in MONEY else value


def _combine(series_list):
    """Several {exact end: value} series -> one, period by period: the first series that has a period wins."""
    combined, keys = {}, set()
    for series in series_list:
        for end, value in series.items():
            if month_end(end) not in keys:
                combined[end] = value
                keys.add(month_end(end))
    return combined


def pick_series(cands, yahoo, field, tol=0.01):
    """One series from the candidate concepts ([(concept, {exact end: (value, computed)})], best first), checked
    against Yahoo's own figures (overlap = the same month-end key, reported values): a concept with more
    disagreements than agreements is dropped; the rest are combined period by period, the concept with the most
    agreements first (then the listed order), so a company that switched concepts between years still has every
    year. None when no concept is left."""
    ranked = []
    for i, (_, series) in enumerate(cands):
        agree = disagree = 0
        for end, (value, computed) in series.items():
            y = (yahoo.get(month_end(end)) or {}).get(field)
            if y is None or computed:
                continue
            if close(_scaled(field, value), y, tol, ABS_TOL.get(field, 0.5)):
                agree += 1
            else:
                disagree += 1
        if disagree <= agree:
            ranked.append((-agree, i, series))
    return _combine([series for _, _, series in sorted(ranked, key=lambda r: r[:2])]) or None


def _calibrated(series, yahoo, field, tol=0.02):
    """A computed series (EBIT / EBITDA from the filings) is used only when it matches Yahoo's own figure on at
    least one period and on at least two thirds of the periods both have."""
    agree = disagree = 0
    for end, (value, _) in series.items():
        y = (yahoo.get(month_end(end)) or {}).get(field)
        if y is None:
            continue
        if close(_scaled(field, value), y, tol, 0.5):
            agree += 1
        else:
            disagree += 1
    return agree >= 1 and agree >= 2 * disagree


def filing_ebit(cands, chosen, yahoo):
    """EBIT = pre-tax income + interest expense and EBITDA = EBIT + depreciation & amortisation (Yahoo's
    definitions), from the filings: {field: {end: (value, True)}} for those that match Yahoo's on overlap."""
    pre = chosen.get("pretax_income")
    if not pre:
        return {}
    out = {}
    # concepts are combined period by period (a company may switch, e.g. Micron's InterestExpense ->
    # InterestExpenseNonoperating in FY26)
    interest = _combine([series for _, series in cands.get("interest_expense") or []])
    ebit = {e: (v + interest[e][0], True) for e, (v, _) in pre.items() if e in interest}
    if ebit and _calibrated(ebit, yahoo, "ebit"):
        out["ebit"] = ebit
        da = _combine([series for _, series in cands.get("d_and_a") or []])
        ebitda = {e: (v + da[e][0], True) for e, (v, _) in ebit.items() if e in da}
        if ebitda and _calibrated(ebitda, yahoo, "ebitda"):
            out["ebitda"] = ebitda
    return out


def merge_filing(filing, quarters, years, balances, marks_q, marks_y, exact_q, exact_y, fill, floors):
    """Merge one company's filing periods (market/financials_sec.periods or financials_dart.periods) into Yahoo's.
    Always: the exact period ends of the filings. With fill (10-K / 10-Q filers, DART): fields Yahoo lacks, periods
    Yahoo does not have (back to floors[scale]: the YoY base of the oldest shown quarter), and the as-reported
    operating income where Yahoo's differs. Values that are computed (a fiscal Q4 = FY - 9 months, EBIT / EBITDA)
    are listed in derived. Returns ({"added": {(scale, key)}, "filled": {(scale, key, field)}, "overridden":
    {...}}, {"quarterly": {key: filed EPS}, "annual": {...}})."""
    used = {"added": set(), "filled": set(), "overridden": set()}
    filed_eps = {"quarterly": {}, "annual": {}}
    for scale, periods, marks, exact in (("quarterly", quarters, marks_q, exact_q), ("annual", years, marks_y, exact_y)):
        cands = filing.get(scale) or {}
        chosen = {}
        for field in FILING_FIELDS:
            if field == "eps_diluted":                 # per-share data is checked against net income, not Yahoo
                series = (cands.get(field) or [(None, None)])[0][1]
            else:
                series = pick_series(cands.get(field) or [], periods, field)
            if series:
                chosen[field] = series
        if fill:
            chosen.update(filing_ebit(cands, chosen, periods))
        filed_eps[scale] = {month_end(e): v for e, (v, computed) in (chosen.get("eps_diluted") or {}).items()
                            if not computed}
        for series in chosen.values():
            for end in series:
                key = month_end(end)
                if key in periods or (fill and key >= floors[scale]):
                    exact.setdefault(key, end)
        if not fill:
            continue
        for field, series in chosen.items():
            for end, (value, computed) in sorted(series.items()):
                key = month_end(end)
                if key < floors[scale]:
                    continue
                v = _scaled(field, value)
                p = periods.get(key)
                if p is None:
                    p = periods[key] = {}
                    used["added"].add((scale, key))
                if p.get(field) is None:
                    p[field] = v
                    if computed:
                        marks.setdefault(key, set()).add(field)
                    used["filled"].add((scale, key, field))
                elif field == "operating_income" and not computed and not close(p[field], v, 0.005, 0.5):
                    p[field] = v                       # Yahoo's may be its "normalized" figure
                    used["overridden"].add((scale, key, field))
    for field, cands in (filing.get("balances") or {}).items():
        as_flow = [(c, {e: (v, False) for e, v in s.items()}) for c, s in cands]
        series = pick_series(as_flow, balances, field, 0.02) if field != "shares" or filing.get("kind") != "DART" \
            else as_flow[0][1]
        if not series or not fill:
            continue
        for end, (value, _) in series.items():
            key = month_end(end)
            if key < min(floors.values()):
                continue
            b = balances.setdefault(key, {})
            if b.get(field) is None:
                b[field] = _scaled(field, value)
    return used, filed_eps


def korean_share_basis(balances, dart_shares):
    """Book value per share on ONE basis: DART's shares outstanding of all classes (common + preferred - treasury,
    as FnGuide / Naver compute BPS) replace Yahoo's count, whose OrdinarySharesNumber sometimes includes the
    preferred shares and sometimes not (Samsung 2025-12-31: 6,630M; 2026-03-31: 5,793M). A date DART has no count
    for (its Q1 / Q3 reports often lack the share table) takes the count interpolated between DART's neighbours,
    unless Yahoo's own count is within 3% of that. Returns the keys changed."""
    known = sorted((month_end(e), v) for e, v in dart_shares.items() if v)
    if not known:
        return []
    changed = []
    by_key = dict(known)
    for key, b in balances.items():
        if key in by_key:
            new = by_key[key]
        else:
            before = [(k, v) for k, v in known if k < key]
            after = [(k, v) for k, v in known if k > key]
            if not before or not after:
                continue
            (k0, v0), (k1, v1) = before[-1], after[0]
            d0, d1, dk = (dt.date.fromisoformat(x) for x in (k0, k1, key))
            new = v0 + (v1 - v0) * (dk - d0).days / max(1, (d1 - d0).days)
            if b.get("shares") and close(b["shares"], new, 0.03):
                continue
        if not b.get("shares") or not close(b["shares"], new, 0.001):
            b["shares"] = new
            changed.append(key)
    return changed


def filing_floors(quarters, years, filing):
    """Oldest month-end key a filing may add: 12 quarters (8 shown + the year-ago base of the oldest shown one) and
    KEEP_YEARS + 1 fiscal years back from the newest period (Yahoo's or the filing's)."""
    floors = {}
    for scale, periods, months in (("quarterly", quarters, 3 * (KEEP_QUARTERS + 3)),
                                   ("annual", years, 12 * KEEP_YEARS)):
        ends = list(periods) + [month_end(e) for cands in (filing.get(scale) or {}).values()
                                for _, series in cands for e in series]
        floors[scale] = add_months(max(ends), -months) if ends else "0000"
    return floors


# ------------------------------------------------ cash flow (2026-10-17)

def apply_cash_flow(quarters, years, marks_q, marks_y, filed):
    """Cash flow from ONE source per company (SEC, DART and Yahoo draw capex a little differently, so a table never
    mixes them): the first filing in `filed` ([(name, financials_sec.cash_flow / financials_dart "cash" result)],
    best first) that has an operating cash flow for one of the company's periods replaces Yahoo's ocf / capex /
    fcf in every period (its values in full currency units: scaled to millions; year-to-date differences marked as
    derived; a computed lease principal marks fcf_after_leases). Without such a filing, Yahoo's rows stay.
    Returns the name of the source used, "Yahoo", or None when there is no cash flow at all."""
    for name, cash in filed:
        if not cash:
            continue
        if not any(month_end(e) in periods for scale, periods in (("quarterly", quarters), ("annual", years))
                   for e in (cash.get(scale) or {}).get("ocf") or {}):
            continue
        for scale, periods, marks in (("quarterly", quarters, marks_q), ("annual", years, marks_y)):
            for p in periods.values():
                for field in CASH_KEYS:
                    p.pop(field, None)
            for field, series in (cash.get(scale) or {}).items():
                for end, (value, computed) in series.items():
                    key = month_end(end)
                    if key not in periods:
                        continue
                    periods[key][field] = value / UNIT
                    if computed:
                        marks.setdefault(key, set()).add("fcf_after_leases" if field == "lease_principal" else field)
        return name
    if any(p.get("ocf") is not None or p.get("fcf") is not None
           for periods in (quarters, years) for p in periods.values()):
        return "Yahoo"
    return None


def finish_cash_flow(periods, marks):
    """fcf = ocf - capex (else Yahoo's own Free Cash Flow, when it gave one), fcf_after_leases = fcf - finance-lease
    principal payments; each is listed in derived when an input is."""
    for end, p in periods.items():
        m = marks.get(end, set())
        if p.get("ocf") is not None and p.get("capex") is not None:
            p["fcf"] = p["ocf"] - p["capex"]
            if {"ocf", "capex"} & m:
                marks.setdefault(end, set()).add("fcf")
        p["fcf_after_leases"] = p["fcf"] - p["lease_principal"] \
            if p.get("fcf") is not None and p.get("lease_principal") is not None else None
        if p["fcf_after_leases"] is None:
            marks.get(end, set()).discard("fcf_after_leases")
        elif "fcf" in marks.get(end, ()):
            marks.setdefault(end, set()).add("fcf_after_leases")


def cash_flow_note(source, concepts=None, has_leases=False):
    """The file's note on how its cash flow is drawn (shown under "How these are computed")."""
    if source == "SEC":
        concepts = concepts or {}
        lease = ", finance-lease principal FinanceLeasePrincipalPayments" if has_leases else ""
        return ("Cash flow from the company's SEC filings (XBRL: operating cash flow "
                f"{concepts.get('ocf', 'NetCashProvidedByUsedInOperatingActivities')}, capex "
                f"{concepts.get('capex', 'PaymentsToAcquirePropertyPlantAndEquipment')}{lease}), drawn as the "
                "Capex tab's SEC cash-flow table: 10-Q cash-flow figures are year-to-date, so a quarter without its "
                "own 3-month figure is the difference of two (Q2 = H1 - Q1, Q4 = full year - 9 months). FCF = "
                "operating cash flow - capex" + ("; FCF after leases also subtracts the finance-lease principal "
                                                 "payments" if has_leases else "")
                + ". FCF QoQ / YoY only between two positive values.")
    if source == "DART":
        return ("Cash flow from the company's DART filings (영업활동 현금흐름; capex = 유형자산의 취득, purchases of "
                "property, plant and equipment): the reports' cash-flow statements are year-to-date, so Q2 = H1 - "
                "Q1, Q3 = 9M - H1 and Q4 = full year - 9M. FCF = operating cash flow - capex. FCF QoQ / YoY only "
                "between two positive values.")
    return ("Cash flow from Yahoo Finance's cash-flow statement (Operating Cash Flow; capex = Capital Expenditure, "
            "shown as a positive number). FCF = operating cash flow - capex. FCF QoQ / YoY only between two "
            "positive values.")


# ------------------------------------------------ checks and gap filling on the merged periods

def reconcile_net_income(periods, marks, entries):
    """A statement net income that does not match diluted EPS x diluted shares (> 1%) while Yahoo's earnings summary
    does (<= 1%) is replaced by the summary's (verification 2026-10-17: TSMC's statements mix its 20-F IFRS net
    income with its Taiwan-IFRS EPS; Q4 25 485,465 vs the reported 505,744). Income after tax moves by the same
    amount (the minority share is kept). Returns the ends fixed."""
    summary = {end: earnings / UNIT for end, _, earnings in entries if earnings is not None}
    fixed = []
    for end, p in sorted(periods.items()):
        ni, implied = p.get("net_income"), eps_times_shares(p)
        if ni is None or implied is None or end not in summary or "net_income" in marks.get(end, ()):
            continue
        m = summary[end]
        if close(ni, implied, 0.01) or not close(m, implied, 0.01):
            continue
        if p.get("net_income_after_tax") is not None:
            p["net_income_after_tax"] += m - ni
            marks.setdefault(end, set()).add("net_income_after_tax")
        p["net_income"] = m
        marks.setdefault(end, set()).add("net_income")
        fixed.append(end)
    return fixed


def reconcile_eps(periods, filed_eps):
    """A diluted EPS that does not match net income / diluted shares (> 2%) while the SEC filing's does (<= 1%) is
    replaced by the filing's (verification 2026-10-17: ASML FY22 16.07 on Yahoo; the 20-F says 14.13). Returns the
    ends fixed."""
    fixed = []
    for end, p in sorted(periods.items()):
        eps, ni, sh = p.get("eps_diluted"), p.get("net_income"), p.get("diluted_shares")
        f = filed_eps.get(end)
        if eps is None or ni is None or not sh or f is None:
            continue
        if close(eps * sh / UNIT, ni, 0.02, 0.5) or not close(f * sh / UNIT, ni, 0.01, 0.5) or close(f, eps, 0.005):
            continue
        p["eps_diluted"] = f
        fixed.append(end)
    return fixed


def drop_ebitda_without_da(periods):
    """EBITDA equal to (or below) EBIT means Yahoo had no depreciation & amortisation for that period; when the
    company's other periods show D&A, such an EBITDA is understated and left blank (ASML Q1 26 / Q2 26).
    Returns the ends cleared."""
    gaps = {e: p["ebitda"] - p["ebit"] for e, p in periods.items()
            if p.get("ebitda") is not None and p.get("ebit") is not None}
    if not any(g > 0 for g in gaps.values()):
        return []
    cleared = [e for e, g in gaps.items() if g <= 0]
    for e in cleared:
        periods[e]["ebitda"] = None
    return sorted(cleared)


def derive_missing_quarter(quarters, years, derived, fields, skip=()):
    """For each fiscal year: when exactly one of its four quarters (the year end and 3, 6, 9 months before it)
    lacks a field that the year and the other three have, that quarter = FY - (the other three); a quarter missing
    altogether is created (Tokyo Electron Q1 26: Yahoo had only its EPS). Not kept when the result cannot be right:
    a negative revenue or capex, or an EPS whose sign differs from the quarter's net income (per-share figures do not add up
    across a reorganisation or a large share issue: Galaxy Digital 2025). Quarters in `skip` are not created (one
    shown as preliminary results). Returns [(end, field)]."""
    made = []
    for fy_end, fy in sorted(years.items()):
        q_ends = [add_months(fy_end, -9), add_months(fy_end, -6), add_months(fy_end, -3), fy_end]
        for field in fields:
            if fy.get(field) is None:
                continue
            values = [(quarters.get(e) or {}).get(field) for e in q_ends]
            missing = [i for i, v in enumerate(values) if v is None]
            if len(missing) != 1:
                continue
            end = q_ends[missing[0]]
            if end in skip:
                continue
            value = fy[field] - sum(v for v in values if v is not None)
            ni = (quarters.get(end) or {}).get("net_income")
            if (field in ("revenue", "capex") and value < 0) \
                    or (field == "eps_diluted" and ni and (value > 0) != (ni > 0)):
                continue
            quarters.setdefault(end, {})[field] = value
            derived.setdefault(end, set()).add(field)
            made.append((end, field))
    return made


def eps_matches_shares(*period_maps):
    """True when the company's diluted EPS x diluted shares equals its net income (median within 2%): then a
    missing EPS may be computed as net income / shares. Not for share structures where it does not hold (Korean
    preferred shares share the net income)."""
    ratios = sorted(p["eps_diluted"] * p["diluted_shares"] / (p["net_income"] * UNIT)
                    for periods in period_maps for p in periods.values()
                    if p.get("eps_diluted") and p.get("diluted_shares") and p.get("net_income"))
    return bool(ratios) and abs(ratios[len(ratios) // 2] - 1) <= 0.02


def _shares_for(periods, end, balances, annual):
    """Diluted shares for a period without its own: a quarter takes the average of its neighbours within 6 months,
    a year the shares outstanding at its end (else its neighbours within 2 years)."""
    if annual and (balances.get(end) or {}).get("shares"):
        return balances[end]["shares"]
    reach = 24 if annual else 6
    keys = sorted(k for k, p in periods.items() if p.get("diluted_shares"))
    before = [k for k in keys if add_months(end, -reach) <= k < end]
    after = [k for k in keys if end < k <= add_months(end, reach)]
    near = ([before[-1]] if before else []) + ([after[0]] if after else [])
    if not near:
        return None
    return sum(periods[k]["diluted_shares"] for k in near) / len(near)


def fill_eps(periods, marks, actuals, balances, annual, by_shares):
    """A period with net income but no diluted EPS (TSMC Q3 25 / Q3 26, ASML Q3 25, Tokyo Electron): Yahoo's
    earningsChart actual when it is within 1% of net income / diluted shares (outside the US it is the reported
    EPS; a US one is usually adjusted, so it fails this check), else net income / diluted shares when the company's
    EPS follows its share count (by_shares). Listed in derived. Returns the ends filled."""
    filled = []
    for end, p in sorted(periods.items()):
        if p.get("eps_diluted") is not None or p.get("net_income") is None:
            continue
        shares = p.get("diluted_shares") or _shares_for(periods, end, balances, annual)
        implied = p["net_income"] * UNIT / shares if shares else None
        actual = actuals.get(end)
        if implied is not None and actual is not None and close(actual, implied, 0.01, 0.006):
            p["eps_diluted"] = actual
        elif implied is not None and by_shares:
            p["eps_diluted"] = implied
        else:
            continue
        marks.setdefault(end, set()).add("eps_diluted")
        filled.append(end)
    return filled


# ------------------------------------------------ exact period ends

def weekday_rule(anchors):
    """From known (month-end key, exact end) pairs: (weekday, "last" | "nearest") for a 52/53-week calendar whose
    periods end on one weekday (NVIDIA: the last Sunday of the month; Micron: the Thursday nearest the month end;
    Broadcom: the Sunday nearest), or None for month-end reporters (or when the anchors do not agree)."""
    offsets, weekdays = [], set()
    for key, exact in anchors:
        off = (dt.date.fromisoformat(exact) - dt.date.fromisoformat(key)).days
        if abs(off) > 7:
            continue
        offsets.append(off)
        weekdays.add(dt.date.fromisoformat(exact).weekday())
    if not offsets or all(o == 0 for o in offsets) or len(weekdays) != 1:
        return None
    weekday = weekdays.pop()
    if any(o > 0 for o in offsets):
        return weekday, "nearest"
    if any(o <= -4 for o in offsets):
        return weekday, "last"
    return weekday, "nearest"


def rule_date(key, rule):
    """The period end that a weekday rule gives for a month-end key."""
    k = dt.date.fromisoformat(key)
    weekday, mode = rule
    back = (k.weekday() - weekday) % 7
    if mode == "last":
        return (k - dt.timedelta(days=back)).isoformat()
    forward = (weekday - k.weekday()) % 7
    return (k - dt.timedelta(days=back) if back <= forward else k + dt.timedelta(days=forward)).isoformat()


class PeriodEnds:
    """Exact period ends for month-end keys: the filings' (SEC XBRL), Yahoo's mostRecentQuarter and
    lastFiscalYearEnd, and for every other period the company's weekday rule (a fiscal Q4 ends with its year).
    Month-end reporters keep the month end, which is their exact date."""

    def __init__(self, exact_q, exact_y, fy_month, mrq_exact=None, last_fy_exact=None):
        self.q = dict(exact_q)
        self.y = dict(exact_y)
        if mrq_exact:
            self.q.setdefault(month_end(mrq_exact), mrq_exact)
        if last_fy_exact:
            self.y.setdefault(month_end(last_fy_exact), last_fy_exact)
        self.fy_month = fy_month
        self.q_rule = weekday_rule(self.q.items())
        self.y_rule = weekday_rule(self.y.items())

    @staticmethod
    def _resolve(key, anchors, rule):
        if key in anchors:
            return anchors[key]
        if rule:
            d = rule_date(key, rule)
            if abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(key)).days) <= 7:
                return d
        return key

    def year(self, key):
        return self._resolve(key, self.y, self.y_rule)

    def quarter(self, key):
        if key in self.q:
            return self.q[key]
        if key in self.y or int(key[5:7]) == self.fy_month:
            return self.year(key)
        return self._resolve(key, self.q, self.q_rule or (None if self.q else self.y_rule))


def build_estimate(entry, kind, fy_month, currency, newest_q_end, rate_to_currency, ends=None):
    """One street-estimate column from an earningsTrend entry (0q / 0y / +1y), or None. `end` is the exact
    period end when the company's calendar is known (ends: PeriodEnds)."""
    if not entry or not entry.get("endDate"):
        return None
    key = month_end(entry["endDate"])
    if newest_q_end and key <= newest_q_end:
        return None                                # stale: that period is already reported
    fiscal_year, fiscal_quarter = fiscal_of(key, fy_month)
    label = quarter_label(fiscal_year, fiscal_quarter) if kind == "quarter" else year_label(fiscal_year)
    eps, rev = entry.get("earningsEstimate") or {}, entry.get("revenueEstimate") or {}

    def factor(ccy):
        if not ccy or ccy == currency:
            return 1.0
        return rate_to_currency(ccy)               # None when the rate is unknown

    fe, fr = factor(eps.get("earningsCurrency")), factor(rev.get("revenueCurrency"))
    end = (ends.quarter(key) if kind == "quarter" else ends.year(key)) if ends else key
    out = {"label": label, "end": end}
    for name, src, f, scale in (("eps", eps, fe, 1), ("revenue", rev, fr, UNIT)):
        for part in ("avg", "low", "high"):
            v = raw_value(src.get(part))
            out[f"{name}_{part}"] = rounded("eps_diluted" if name == "eps" else name, v * f / scale) \
                if v is not None and f else None
        n = raw_value(src.get("numberOfAnalysts"))
        out[f"{name}_analysts"] = int(n) if n is not None and out[f"{name}_avg"] is not None else None
        g = raw_value(src.get("growth"))
        out[f"{name}_growth_pct"] = round(g * 100, 2) if g is not None and out[f"{name}_avg"] is not None else None
    if out["eps_avg"] is None and out["revenue_avg"] is None:
        return None
    return {k: out[k] for k in ("label", "end", "revenue_avg", "revenue_low", "revenue_high", "revenue_analysts",
                                "eps_avg", "eps_low", "eps_high", "eps_analysts", "revenue_growth_pct",
                                "eps_growth_pct")}


def _labels(keys, fy_month, annual):
    """Fiscal labels of month-end keys, joined with ", " ("Q4 25, FY22")."""
    if annual:
        return [year_label(int(k[:4])) for k in sorted(keys)]
    return [quarter_label(*fiscal_of(k, fy_month)) for k in sorted(keys)]


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else None


def compose(node_id, raw, hist_rows=(), fx=None, filings=None):
    """The web file of one company from its raw Yahoo answers (+ its history rows, + its SEC / DART filings when
    known). fx(from, to) returns monthly rates {"YYYY-MM": rate} or None. filings: {"sec": compact SEC facts,
    "dart": DART cache} (either may be missing). Returns None when there is nothing to show.

    Periods are keyed by Yahoo's month end inside (so the same period never shows up twice); the file's "end" is the
    exact period end."""
    fx = fx or (lambda a, b: None)
    filings = filings or {}
    summary = raw.get("summary") or {}
    chart = raw.get("chart") or {}
    stats = summary.get("defaultKeyStatistics") or {}
    fin = summary.get("financialData") or {}
    stmt = statement_periods(raw.get("timeseries"))
    currency = ((raw.get("timeseries") or {}).get("currency") or fin.get("financialCurrency")
                or (summary.get("earnings") or {}).get("financialCurrency") or chart.get("currency"))
    # history rows of the same company in the same currency and unit (a ticker fix could change the listing)
    stmt = merge_history(stmt, [r for r in hist_rows if r.get("company") == node_id
                                and r.get("currency", currency) == currency and r.get("unit", UNIT) == UNIT])
    quarters, years, balances = stmt["quarterly"], stmt["annual"], stmt["balances"]
    now = raw.get("fetched") or today()
    notes = []
    sources = [SOURCE]
    derived, derived_y = {}, {}                            # month-end key -> computed fields
    exact_q, exact_y = {}, {}                              # month-end key -> exact period end (filings)
    last_fy_exact = _iso(raw_value(stats.get("lastFiscalYearEnd")))
    mrq_exact = _iso(raw_value(stats.get("mostRecentQuarter")))
    fy_month = fiscal_year_end_month(years.keys(), last_fy_exact)
    entries_q, entries_y = summary_quarters(summary, fy_month), summary_years(summary, fy_month)

    # 1) the company's own filings: SEC XBRL (10-K / 10-Q: fill and add periods; 20-F: per-share check and dates
    #    only, since a 20-F may use another GAAP than the home listing, e.g. TSMC), DART (Korea: fill and add)
    filed_eps = {"quarterly": {}, "annual": {}}
    sec = financials_sec.periods(filings.get("sec"), currency) if filings.get("sec") else {}
    dart = financials_dart.periods(filings.get("dart"), currency) if filings.get("dart") else {}
    for name, filing in (("sec", sec), ("dart", dart)):
        if not filing or not (filing.get("quarterly") or filing.get("annual")):
            continue
        fill = filing["kind"] in ("10-K", "DART")
        yahoo_q, yahoo_y = sorted(quarters), sorted(years)
        used, eps = merge_filing(filing, quarters, years, balances, derived, derived_y, exact_q, exact_y, fill,
                                 filing_floors(quarters, years, filing))
        if name == "sec":
            filed_eps = eps
        if used["added"] or used["filled"]:
            sources.append(financials_sec.SOURCE if name == "sec" else financials_dart.SOURCE)
            # the newest periods (filed, not in Yahoo's statements yet) are named; older ones are the YoY base
            q_new = sorted(k for s, k in used["added"] if s == "quarterly" and (not yahoo_q or k > yahoo_q[-1]))
            y_new = sorted(k for s, k in used["added"] if s == "annual" and (not yahoo_y or k > yahoo_y[-1]))
            older = any(s == "quarterly" and yahoo_q and k < yahoo_q[0] for s, k in used["added"])
            what = ("from the company's SEC filings (XBRL company facts: 10-K / 10-Q); a fiscal Q4 is the 10-K year "
                    "minus the 10-Q nine months, its diluted EPS Q4 net income / Q4 diluted shares, and EBIT / "
                    "EBITDA pre-tax income + interest expense (+ depreciation & amortisation) when that matches "
                    "Yahoo's own figures" if name == "sec" else
                    "from the company's DART filings (" + ("consolidated" if filing.get("fs_div") == "CFS"
                                                           else "separate") + " statements); a fiscal Q4 is the "
                    "annual report minus the Q3 report's nine-month figures, diluted EPS included")
            listed = ", ".join(_labels(q_new, fy_month, False) + _labels(y_new, fy_month, True))
            notes.append((f"{listed}: not in Yahoo's statements yet. " if listed else "")
                         + ("Quarters before Yahoo's 5-quarter window (the year-over-year base) and f" if older
                            else "F") + "igures Yahoo's statements lack are " + what
                         + " (computed ones are listed in \"derived\").")
        if used["overridden"]:
            notes.append("Operating income is the as-reported figure of the filings (Yahoo's can be a normalized "
                         "one).")
        if name == "dart":
            shares = ((filing.get("balances") or {}).get("shares") or [(None, {})])[0][1]
            if korean_share_basis(balances, shares):
                notes.append("PBR: book value per share uses the shares outstanding of all share classes (common + "
                             "preferred, without treasury shares; DART), as Korean BPS does.")

    # 2) Yahoo's earnings summary fills the newest periods the statements (and filings) do not have yet
    added_q = fill_from_summary(quarters, entries_q, derived, now)
    added_y = fill_from_summary(years, entries_y, derived_y, now)
    # a Korean quarter with preliminary results (DART) shows them as its "(P)" column; a column Yahoo's summary made
    # for the same quarter (revenue only: LG Electronics Q3 26) gives way to it and only lends what the filing lacks
    pre = financials_dart.preliminary(filings.get("dart")) if filings.get("dart") else None
    pre_fallback, pre_skip = {}, set()
    if pre and month_end(pre["end"]) in added_q \
            and set(quarters.get(month_end(pre["end"])) or {}) <= {"revenue", "net_income"}:
        key = month_end(pre["end"])
        pre_fallback = quarters.pop(key)
        derived.pop(key, None)
        added_q.remove(key)
        pre_skip.add(key)
    if added_q or added_y:
        names = _labels(added_q, fy_month, False) + _labels(added_y, fy_month, True)
        notes.append(f"{', '.join(names)}: revenue and net income from Yahoo's earnings summary (the financial "
                     "statements on Yahoo do not have these periods yet); other items are blank until they do.")

    # 2b) cash flow: the SEC 10-K / 10-Q facts, else DART, else Yahoo's rows (one source per company)
    cash_source = apply_cash_flow(quarters, years, derived, derived_y,
                                  [("SEC", sec.get("cash")), ("DART", dart.get("cash"))])
    if cash_source:
        cash = (sec if cash_source == "SEC" else dart if cash_source == "DART" else {}).get("cash") or {}
        has_leases = any(p.get("lease_principal") is not None for p in quarters.values())
        notes.append(cash_flow_note(cash_source, cash.get("concepts"), has_leases))
        filing_source = {"SEC": financials_sec.SOURCE, "DART": financials_dart.SOURCE}.get(cash_source)
        if filing_source and filing_source not in sources:
            sources.append(filing_source)

    # 3) split basis: put EPS / share counts on today's basis
    splits = [tuple(s) for s in chart.get("splits") or []]
    trailing_eps = raw_value(stats.get("trailingEps"))
    ni_ttm = raw_value(stats.get("netIncomeToCommon"))
    reference = (ni_ttm / trailing_eps) if ni_ttm and trailing_eps and ni_ttm > 0 and trailing_eps > 0 \
        else raw_value(stats.get("sharesOutstanding"))
    adjusted = set()
    for scale, periods, marks in (("quarterly", quarters, derived), ("annual", years, derived_y)):
        for end, p in periods.items():
            later = later_splits(splits, end)
            if not later:
                continue
            implied = p.get("diluted_shares") or (p["net_income"] * UNIT / p["eps_diluted"]
                                                   if p.get("net_income") and p.get("eps_diluted") else None)
            f = split_adjustment(implied, later, reference)
            if f != 1.0 and p.get("eps_diluted") is not None:
                p["eps_diluted"] /= f
                marks.setdefault(end, set()).add("eps_diluted")
                adjusted.add(f)
            if p.get("diluted_shares"):
                p["diluted_shares"] *= f
    for end, b in balances.items():
        later = later_splits(splits, end)
        if later and b.get("shares"):
            f = split_adjustment(b["shares"], later, reference)
            if f != 1.0:
                b["shares"] *= f
                adjusted.add(f)
    if adjusted:
        notes.append("Per-share figures filed before a stock split are shown on today's share basis (split factor "
                     + ", ".join(f"{f:g}" for f in sorted(adjusted)) + "), like the split-adjusted prices.")

    # 4) figures that contradict each other: net income vs EPS x shares (the summary decides), EPS vs the SEC filing
    fixed_q = reconcile_net_income(quarters, derived, entries_q)
    fixed_y = reconcile_net_income(years, derived_y, entries_y)
    if fixed_q or fixed_y:
        notes.append(f"{', '.join(_labels(fixed_q, fy_month, False) + _labels(fixed_y, fy_month, True))}: net "
                     "income from Yahoo's earnings summary, which matches diluted EPS x diluted shares (Yahoo's "
                     "statement figure did not; income after tax is moved by the same amount).")
    eps_q = reconcile_eps(quarters, filed_eps["quarterly"])
    eps_y = reconcile_eps(years, filed_eps["annual"])
    if eps_q or eps_y:
        notes.append(f"{', '.join(_labels(eps_q, fy_month, False) + _labels(eps_y, fy_month, True))}: diluted EPS "
                     "from the SEC filing (Yahoo's figure did not match net income / diluted shares).")
    cleared = drop_ebitda_without_da(quarters) + drop_ebitda_without_da(years)
    if cleared:
        notes.append("EBITDA is left blank where Yahoo's equals EBIT (its depreciation & amortisation was missing "
                     "for that period).")

    # 5) gaps: a single missing quarter of a fiscal year = FY - the other three (flows); then diluted EPS from
    #    Yahoo's actual / net income / shares; then EPS = FY - the other three as the last resort
    made = derive_missing_quarter(quarters, years, derived, list(FLOW_FIELDS) + ["ocf", "capex"], pre_skip)
    actual_q, actual_y = chart_actuals(summary)
    by_shares = eps_matches_shares(quarters, years)
    filled_q = fill_eps(quarters, derived, actual_q, balances, False, by_shares)
    mrq = month_end(mrq_exact) if mrq_exact else None
    if mrq and mrq in years and years[mrq].get("eps_diluted") is None and trailing_eps is not None \
            and years[mrq].get("net_income") is not None:
        shares = years[mrq].get("diluted_shares") or _shares_for(years, mrq, balances, True)
        if shares and close(trailing_eps, years[mrq]["net_income"] * UNIT / shares, 0.02):
            years[mrq]["eps_diluted"] = trailing_eps   # the fiscal year that just ended is the trailing 12 months
            derived_y.setdefault(mrq, set()).add("eps_diluted")
    filled_y = fill_eps(years, derived_y, {}, balances, True, by_shares)
    made += derive_missing_quarter(quarters, years, derived, ["eps_diluted"], pre_skip)
    if made:
        notes.append(f"{', '.join(sorted(set(_labels([e for e, _ in made], fy_month, False))))}: computed as the "
                     "fiscal year minus its other three quarters where Yahoo's quarterly statements lack them; "
                     "the fields are listed in \"derived\".")
    if filled_q or filled_y:
        notes.append(f"{', '.join(_labels(filled_q, fy_month, False) + _labels(filled_y, fy_month, True))}: diluted "
                     "EPS from Yahoo's reported EPS where it matches net income / diluted shares, else net income / "
                     "diluted shares (Yahoo's statements lack it).")
    finish_cash_flow(quarters, derived)                    # fcf, fcf_after_leases
    finish_cash_flow(years, derived_y)

    if not quarters and not years:
        return None

    # 6) prices, dividends, FX for the ratios
    closes = chart.get("closes") or {}
    price_ccy = chart.get("currency") or (summary.get("price") or {}).get("currency")
    price_scale = 0.01 if price_ccy == "GBp" else 1.0
    base_ccy = "GBP" if price_ccy == "GBp" else price_ccy
    # a US line (ADR) quoted in USD for statements in another currency: the ADR ratio is unknown
    adr_mismatch = is_us_listing(raw.get("symbol")) and base_ccy and currency and base_ccy != currency
    rates = fx(base_ccy, currency) if base_ccy and currency and base_ccy != currency and not adr_mismatch else None
    first_month = min(closes) if closes else None

    def month_value(series, month):
        if not series:
            return None
        if month in series:
            return series[month]
        earlier = [k for k in series if k <= month]
        return series[max(earlier)] if earlier else None

    def price_at(end):
        """Close at a period end in the price currency (as listed) and in the reporting currency."""
        if not closes or end[:7] < (first_month or "9999"):
            return None, None
        p = closes.get(end[:7])
        if p is None:
            return None, None
        local = p * price_scale
        if adr_mismatch:
            return local, None
        if base_ccy == currency or not base_ccy:
            return local, local
        r = month_value(rates, end[:7])
        return local, (local * r if r else None)

    def dividends_12m(end):
        start = add_months(end, -12)
        if not closes or start[:7] < (first_month or "9999"):
            return None
        return sum(a for d, a in chart.get("dividends") or [] if start < d <= end) * price_scale

    if adr_mismatch:
        notes.append(f"A US listing whose statements are in {currency}: PER and PBR are left blank (the price is in "
                     f"{base_ccy} per ADR, the figures per {currency} share).")
    elif base_ccy and currency and base_ccy != currency:
        notes.append(f"PER and PBR convert the {base_ccy} share price into {currency} at the month-end rate "
                     "(Yahoo Finance FX).")
    book_value_mrq = raw_value(stats.get("bookValue"))

    def ratios(end, eps_window, ni_window, assets_then):
        local, conv = price_at(end)
        per = round(conv / eps_window, 2) if conv is not None and eps_window and eps_window > 0 else None
        b = balances.get(end) or {}
        bvps = b["equity"] * UNIT / b["shares"] if b.get("equity") and b.get("shares") else None
        if bvps is None and end == mrq and book_value_mrq:
            bvps = book_value_mrq
        pbr = round(conv / bvps, 2) if conv is not None and bvps and bvps > 0 else None
        divs = dividends_12m(end)
        dy = round(divs / local * 100, 2) if divs is not None and local else None
        a_now, a_then = b.get("total_assets"), assets_then
        roa = round(ni_window / ((a_now + a_then) / 2) * 100, 2) \
            if ni_window is not None and a_now and a_then and a_now + a_then > 0 else None
        return per, pbr, dy, roa

    def assets_at(end):
        return (balances.get(end) or {}).get("total_assets")

    ends = PeriodEnds(exact_q, exact_y, fy_month, mrq_exact, last_fy_exact)

    # 7) the period rows (keys are month ends: the previous quarter is 3 months back, the year-ago one 12)
    q_rows = []
    for end in sorted(quarters):
        p = quarters[end]
        window = [add_months(end, -3 * k) for k in range(4)]
        in_window = [quarters.get(e) or {} for e in window]
        eps_ttm = sum(w["eps_diluted"] for w in in_window) \
            if all(w.get("eps_diluted") is not None for w in in_window) else None
        ni_ttm_q = sum(w["net_income"] for w in in_window) \
            if all(w.get("net_income") is not None for w in in_window) else None
        per, pbr, dy, roa = ratios(end, eps_ttm, ni_ttm_q, assets_at(add_months(end, -12)))
        prev = quarters.get(add_months(end, -3)) or {}
        year_ago = quarters.get(add_months(end, -12)) or {}
        fyq = fiscal_of(end, fy_month)
        q_rows.append(period_row(ends.quarter(end), quarter_label(*fyq), fyq[0], fyq[1], p, actual_q.get(end),
                                 per, pbr, dy, roa, growth(p, prev), growth(p, year_ago), derived.get(end, set())))
    y_rows = []
    for end in sorted(years):
        p = years[end]
        fiscal_year = int(end[:4])                         # named by the calendar year it ends in
        prev_end = add_months(end, -12)                    # a fiscal-year change leaves no comparable year
        per, pbr, dy, roa = ratios(end, p.get("eps_diluted"), p.get("net_income"),
                                   assets_at(prev_end) if prev_end in years else None)
        prev = years.get(prev_end) or {}
        y_rows.append(period_row(ends.year(end), year_label(fiscal_year), fiscal_year, None, p, actual_y.get(end),
                                 per, pbr, dy, roa, None, growth(p, prev), derived_y.get(end, set())))

    # a company that changed its fiscal year can have two years with one label (Hut 8: June 2023 and, from the
    # successor's filings, December 2023): the one on the current calendar stays
    labels = Counter(r["label"] for r in y_rows)
    y_rows = [r for r in y_rows if labels[r["label"]] == 1 or int(month_end(r["end"])[5:7]) == fy_month]

    # 8) street estimates: next unreported quarter, this fiscal year, next fiscal year
    newest_q = max(quarters) if quarters else None
    newest_known = max([e for e in (newest_q, mrq, max(years) if years else None) if e])
    trend = {t.get("period"): t for t in ((summary.get("earningsTrend") or {}).get("trend") or [])}

    def rate_to_currency(ccy):
        r = fx(ccy, currency)
        return r[max(r)] if r else None

    estimates = {
        "quarter": build_estimate(trend.get("0q"), "quarter", fy_month, currency, newest_known, rate_to_currency,
                                  ends),
        "fy": build_estimate(trend.get("0y"), "year", fy_month, currency, newest_known, rate_to_currency, ends),
        "next_fy": build_estimate(trend.get("+1y"), "year", fy_month, currency, newest_known, rate_to_currency,
                                  ends),
    }
    if estimates["fy"] and estimates["next_fy"] and estimates["fy"]["label"] == estimates["next_fy"]["label"]:
        estimates["next_fy"] = None

    # 9) preliminary results (Korea: DART's 잠정실적 filing) for a quarter not reported yet
    prelim = preliminary_column(pre, quarters, fy_month, newest_q, pre_fallback)
    if prelim:
        notes.append(f"{prelim['label']} (P): preliminary results the company filed on {prelim['filed']} (DART "
                     "공정공시); the full statements follow with the quarterly report.")

    fy_end_exact = last_fy_exact or (ends.year(max(years)) if years else None)
    if any(k != ends.quarter(k) for k in quarters) or any(k != ends.year(k) for k in years):
        notes.append("Period ends are the companies' own (52/53-week calendars end on a weekday: from the SEC "
                     "filings, Yahoo's key statistics and the company's weekday rule); fiscal labels are the "
                     "company's own fiscal year, named by the calendar year it ends in.")
    else:
        notes.append("Fiscal labels are the company's own fiscal year, named by the calendar year it ends in.")
    notes.append("PER uses the trailing 4 quarters' diluted EPS (annual: the year's), ROA the trailing 4 quarters' "
                 "net income over average total assets. The (E) EPS is the analysts' consensus, on Yahoo's EPS "
                 "basis (\"EPS (Yahoo basis)\": for US companies usually adjusted, non-GAAP).")
    symbol = raw.get("symbol")
    out = {
        "company": node_id, "ticker": symbol, "currency": currency, "unit": UNIT,
        "fiscal_year_end": fy_end_exact[5:10] if fy_end_exact else None,
        "updated": raw.get("fetched"),
        "quarterly": shown(q_rows)[-KEEP_QUARTERS:], "annual": shown(y_rows)[-KEEP_YEARS:],
        "estimates": estimates,
        "preliminary": prelim,
        "source": {"name": SOURCE["name"], "url": f"https://finance.yahoo.com/quote/{symbol}/financials"},
        "sources": [{"name": SOURCE["name"], "url": f"https://finance.yahoo.com/quote/{symbol}/financials"}]
                   + [s for s in sources[1:]],
        "notes": notes,
    }
    return out


def preliminary_column(pre, quarters, fy_month, newest_q, fallback=None):
    """DART's newest preliminary results (financials_dart.preliminary) as a "(P)" column, when its quarter is newer
    than every reported one: {"label", "end", "filed", "consolidated", money fields in millions (null when not
    given; `fallback` lends Yahoo's summary figures the filing lacks), "qoq", "yoy" (revenue, operating_income),
    "url"}."""
    if not pre:
        return None
    key = month_end(pre["end"])
    if newest_q and key <= newest_q:
        return None
    fallback = fallback or {}
    values = {}
    for f in PRELIM_FIELDS:
        v = (pre.get("values") or {}).get(f)
        values[f] = round(v / UNIT, 2) if v is not None else \
            (round(fallback[f], 2) if fallback.get(f) is not None else None)
    prev = quarters.get(add_months(key, -3)) or {}
    year_ago = quarters.get(add_months(key, -12)) or {}
    fyq = fiscal_of(key, fy_month)
    return {"label": quarter_label(*fyq), "end": pre["end"], "filed": pre.get("filed"),
            "consolidated": pre.get("consolidated"), **values,
            "qoq": {f: pct_change(values.get(f), prev.get(f)) for f in ("revenue", "operating_income")},
            "yoy": {f: pct_change(values.get(f), year_ago.get(f)) for f in ("revenue", "operating_income")},
            "url": pre.get("url")}


PRELIM_FIELDS = ("revenue", "operating_income", "pretax_income", "net_income_after_tax", "net_income")


def shown(rows):
    """Columns worth showing: a period with neither revenue nor net income (Yahoo sometimes has only its EPS) is
    still used for growth and PER, but not shown."""
    return [r for r in rows if r["revenue"] is not None or r["net_income"] is not None]


def growth(p, earlier):
    """% changes against an earlier period: GROWTH_FIELDS, plus fcf only between two positive values."""
    out = {f: pct_change(p.get(f), earlier.get(f)) for f in GROWTH_FIELDS}
    out["fcf"] = pct_change_positive(p.get("fcf"), earlier.get("fcf"))
    return out


def period_row(end, label, fiscal_year, fiscal_quarter, p, eps_adjusted, per, pbr, dy, roa, qoq, yoy, derived):
    row = {"end": end, "label": label, "fiscal_year": fiscal_year, "fiscal_quarter": fiscal_quarter}
    for field in list(FLOW_FIELDS) + ["eps_diluted", "ocf", "capex", "fcf", "fcf_after_leases"]:
        row[field] = rounded(field, p.get(field))
    row.update({"eps_adjusted": rounded("eps_diluted", eps_adjusted), "per": per, "pbr": pbr,
                "dividend_yield_pct": dy, "roa_pct": roa, "qoq": qoq, "yoy": yoy, "derived": sorted(derived)})
    return {k: row[k] for k in PERIOD_KEYS}


# ------------------------------------------------ which companies, in what order

def targets():
    """Public graph nodes with a ticker -> {"ticker", "exchange", "symbols", "degree"}."""
    graph = read_json(GRAPH / "merged_graph.json", {}) or {}
    degree = Counter()
    for e in graph.get("edges") or []:
        degree[e.get("source")] += 1
        degree[e.get("target")] += 1
    out = {}
    for node_id, info in universe().items():
        if info.get("status") != "public" or not (info.get("ticker") or "").strip():
            continue
        symbols = symbol_candidates(info["ticker"], info.get("exchange"))
        if symbols:
            out[node_id] = {"ticker": info["ticker"], "exchange": info.get("exchange"), "symbols": symbols,
                            "degree": degree.get(node_id, 0)}
    return out


def rotation_bucket(node_id):
    return int(hashlib.sha1(node_id.encode("utf-8")).hexdigest(), 16) % ROTATION_DAYS


def due_companies(tg, state, calendar_dates, now, backfill=False):
    """Node ids to fetch today, most urgent first."""
    def degree_order(ids):
        return sorted(ids, key=lambda i: (-tg[i]["degree"], i))

    if backfill:
        return degree_order(tg)
    today_d = dt.date.fromisoformat(now)
    near, never, failed, rotation = [], [], [], []
    for node_id in tg:
        st = state.get(node_id) or {}
        fetched = st.get("fetched")
        if fetched == now:
            continue                                   # already fetched today
        dates = [d for d in (calendar_dates.get(node_id), st.get("earnings_date")) if d]
        if any(-EARNINGS_AFTER_DAYS <= (dt.date.fromisoformat(d) - today_d).days <= EARNINGS_BEFORE_DAYS
               for d in dates):
            near.append(node_id)
        elif not fetched:
            never.append(node_id)
        elif st.get("error"):
            failed.append(node_id)
        else:
            age = (today_d - dt.date.fromisoformat(fetched)).days
            # its weekly day, or it missed that day (laptop off, time budget used up): more than a week old
            if rotation_bucket(node_id) == today_d.toordinal() % ROTATION_DAYS or age > ROTATION_DAYS:
                rotation.append(node_id)
    rotation.sort(key=lambda i: (state[i].get("fetched") or "", -tg[i]["degree"]))
    return degree_order(near) + degree_order(never) + degree_order(failed) + rotation


def calendar_dates():
    """{node id: next earnings date} from graph/hyperscaler_cash.json."""
    data = read_json(GRAPH / "hyperscaler_cash.json", {}) or {}
    return {c["id"]: c["date"] for c in data.get("calendar") or [] if c.get("id") and c.get("date")}


def cache_path(symbol):
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in symbol)
    return CACHE / f"{safe}.json"


# ------------------------------------------------ the companies' own filings (SEC XBRL, DART)

def filing_ids(info, sec_map):
    """(SEC CIK, DART corp code) of a target: the CIK of a US-listed ticker (SEC's ticker list), the corp code of a
    Korean listing (dart/corp_codes.json). Either may be None."""
    cik = None
    if info.get("exchange") in US_EXCHANGES:
        cik = sec_map.get((info.get("ticker") or "").strip().upper().replace(".", "-"))
    return cik, financials_dart.corp_code_of(info.get("ticker"), info.get("exchange"))


def load_filings(info, sec_map):
    """The cached filings of one target, for compose(): {"sec": compact facts, "dart": DART cache} (no network)."""
    cik, corp = filing_ids(info, sec_map)
    out = {}
    if cik and financials_sec.cache_path(cik).exists():
        out["sec"] = read_json(financials_sec.cache_path(cik))
    if corp and financials_dart.cache_path(corp).exists():
        out["dart"] = read_json(financials_dart.cache_path(corp))
    return out


def refresh_filings(node_ids, tg, max_minutes=None, workers=1):
    """Bring the SEC facts (one request per company, at most once a day) and the DART reports (only reports not
    read yet, plus preliminary-results filings) of these companies up to date, in this order. Stops after
    max_minutes; DART stops for the day on its request limit. workers > 1 reads DART for several companies at once
    (one shared pace of 4 calls per second): a first DART read is about 13 reports x 8 s. Returns
    {"sec": n, "dart": n, "errors": n}."""
    started = time.monotonic()

    def time_left():
        return max_minutes is None or time.monotonic() - started < max_minutes * 60

    counts = {"sec": 0, "dart": 0, "errors": 0}
    try:
        sec_map = financials_sec.cik_map()
    except Exception as e:                             # SEC unreachable: the cached list (or none) still works
        log(f"WARNING SEC ticker list: {type(e).__name__}: {str(e)[:120]}")
        sec_map = financials_sec.cached_cik_map()
    sec_ids, dart_ids = [], []
    for node_id in node_ids:
        cik, corp = filing_ids(tg[node_id], sec_map)
        if cik:
            sec_ids.append((node_id, cik))
        if corp:
            dart_ids.append((node_id, corp))
    for node_id, cik in sec_ids:
        if not time_left():
            log(f"filings: time budget reached; SEC facts of {len(sec_ids) - counts['sec']} companies wait")
            return counts
        if financials_sec.fetch(cik) is not None:
            counts["sec"] += 1
    stop = [False]

    def one(item):
        node_id, corp = item
        if stop[0] or not time_left():
            return None
        try:
            financials_dart.fetch(corp)
            return True
        except financials_dart.DartLimit as e:
            stop[0] = True
            log(f"WARNING DART: {e}; stopping DART for today")
        except Exception as e:
            log(f"WARNING DART {node_id}: {type(e).__name__}: {str(e)[:120]}")
            return False
        return None

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, dart_ids))
    else:
        results = [one(item) for item in dart_ids]
    counts["dart"] = sum(1 for r in results if r)
    counts["errors"] = sum(1 for r in results if r is False)
    return counts


# ------------------------------------------------ writing the web files

def _period_lines(rows):
    return ["  " + json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]


def write_company_file(path, data):
    """One period per line (readable diffs); an unchanged file is not rewritten."""
    parts = ["{"]
    keys = list(data)
    for i, key in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        value = data[key]
        if key in ("quarterly", "annual"):
            lines = _period_lines(value)
            body = ",\n".join(lines)
            parts.append(f' "{key}": [' + ("\n" + body + "\n ]" if lines else "]") + comma)
        else:
            parts.append(f" {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}{comma}")
    parts.append("}")
    text = "\n".join(parts) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def build(only=None):
    """Rebuild graph/financials/ + graph/financials_index.json from the cache and history (no network).
    A company without a cache keeps its existing file; files of nodes that left the graph are deleted."""
    tg = targets()
    out_dir = GRAPH / OUT_DIR_NAME
    names = company_file_names(tg)
    state = read_json(HISTORY / STATE_FILE_NAME, {}) or {}
    sec_map = financials_sec.cached_cik_map()
    hist = {}
    for r in read_history(DATASET):
        hist.setdefault(r.get("company"), []).append(r)
    index, written = {}, 0
    for node_id in sorted(tg):
        path = out_dir / names[node_id]
        data = None
        symbol = (state.get(node_id) or {}).get("symbol")
        raw = read_json(cache_path(symbol)) if symbol and cache_path(symbol).exists() else None
        if raw and (only is None or node_id in only):
            try:
                data = compose(node_id, raw, hist.get(node_id, []), cached_fx, load_filings(tg[node_id], sec_map))
            except Exception as e:                     # one odd company never stops the build
                log(f"WARNING {node_id} ({symbol}): {type(e).__name__}: {e}")
                data = None
            if data:
                written += write_company_file(path, data)
            elif path.exists():
                path.unlink()
        if path.exists():
            if data is None:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    continue
            latest = [p["end"] for p in (data.get("quarterly") or []) + (data.get("annual") or [])]
            index[node_id] = {"file": names[node_id], "latest_end": max(latest) if latest else None,
                              "currency": data.get("currency")}
    keep = {v["file"] for v in index.values()}
    for old in out_dir.glob("*.json"):
        if old.name not in keep:
            old.unlink()
    updated = max((s.get("fetched") or "" for s in state.values()), default="") or today()
    write_json(GRAPH / "financials_index.json", {"updated": updated, "source": SOURCE, "companies": index})
    log(f"wrote graph/financials_index.json: {len(index)} companies ({written} files changed)")
    return index


# ------------------------------------------------ the daily run

def run(backfill=False, only=None, limit=None, max_minutes=None):
    """Fetch the due companies (Yahoo, then their SEC / DART filings), record history, rebuild the web files.
    False only when every fetch failed."""
    CACHE.mkdir(parents=True, exist_ok=True)
    tg = targets()
    if only:
        tg = {k: v for k, v in tg.items() if k in only}
    state_path = HISTORY / STATE_FILE_NAME
    state = read_json(state_path, {}) or {}
    now = today()
    due = due_companies(tg, state, calendar_dates(), now, backfill=backfill or bool(only))
    if limit:
        due = due[:limit]
    budget = (max_minutes if max_minutes is not None else (None if backfill or only else DAILY_MAX_MINUTES))
    started = time.monotonic()
    log(f"{len(due)} companies due ({'backfill' if backfill else 'selected' if only else 'daily'}), "
        f"{len(tg)} public companies")
    ok = nodata = failed = 0
    limited_in_a_row = 0                               # companies in a row that hit Yahoo's rate limit
    snapshots = []
    fetched_ids = []

    def out_of_time(extra_seconds=0):
        return budget is not None and time.monotonic() - started + extra_seconds > budget * 60

    for i, node_id in enumerate(due):
        if out_of_time():
            log(f"time budget of {budget} min reached; {len(due) - i} companies wait for the next run")
            break
        info = tg[node_id]
        st = dict(state.get(node_id) or {})
        raw, error = None, None
        for symbol in info["symbols"]:
            cached = read_json(cache_path(symbol))
            if cached and cached.get("fetched") == now and cached.get("format") == RAW_FORMAT:
                raw = cached
                break
            for attempt in range(3):
                try:
                    raw = fetch_company(symbol)
                    error = None
                    break
                except RateLimited:
                    wait = 30 * (attempt + 1)
                    error = "rate limited"
                    if out_of_time(wait):              # the back-off counts against the budget too
                        log(f"rate-limited at {symbol}; no time left to wait {wait}s")
                        break
                    log(f"rate-limited at {symbol}; waiting {wait}s")
                    time.sleep(wait)
                except Exception as e:
                    error = f"{type(e).__name__}: {str(e)[:120]}"
                    time.sleep(PAUSE)
                    break
            if raw:
                write_json(cache_path(symbol), raw)
                break
            if error == "rate limited":
                break
        if error == "rate limited":
            limited_in_a_row += 1
            if limited_in_a_row >= 3:
                log("WARNING Yahoo keeps rate-limiting; stopping for today")
                break
            continue                                   # not recorded as fetched: due again next run
        limited_in_a_row = 0
        st["fetched"] = now
        if raw:
            ok += 1
            fetched_ids.append(node_id)
            st.update({"symbol": raw["symbol"], "ok": True})
            st.pop("error", None)
            ed = (((raw.get("summary") or {}).get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate")
            ts = raw_value(ed[0]) if ed else None
            st["earnings_date"] = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else None
            stmt = statement_periods(raw.get("timeseries"))
            currency = (raw.get("timeseries") or {}).get("currency")
            snapshots += snapshot_rows(node_id, raw["symbol"], currency, stmt, now)
            # FX rates the build will need (fetched now, so build() stays offline)
            price_ccy = (raw.get("chart") or {}).get("currency")
            base = "GBP" if price_ccy == "GBp" else price_ccy
            if base and currency and base != currency and not is_us_listing(raw["symbol"]):
                fx_closes(base, currency)
            for t in (((raw.get("summary") or {}).get("earningsTrend") or {}).get("trend") or []):
                for part, key in (("earningsEstimate", "earningsCurrency"), ("revenueEstimate", "revenueCurrency")):
                    ccy = (t.get(part) or {}).get(key)
                    if ccy and currency and ccy != currency:
                        fx_closes(ccy, currency)
        elif error:
            failed += 1
            st.update({"ok": False, "error": error})
            log(f"WARNING {node_id} ({', '.join(info['symbols'])}): {error}")
        else:
            nodata += 1
            st.update({"symbol": info["symbols"][0], "ok": False})
            st.pop("error", None)
        state[node_id] = st
        if (i + 1) % 25 == 0:
            write_json(state_path, state)
            append_history(DATASET, snapshots, ("company", "end", "period_type"))
            snapshots = []
            log(f"{i + 1}/{len(due)} done ({ok} ok, {nodata} without data, {failed} failed)")
    write_json(state_path, state)
    new_rows = append_history(DATASET, snapshots, ("company", "end", "period_type"))
    log(f"fetched {ok} companies, {nodata} without data on Yahoo, {failed} failed; {new_rows} new history rows "
        f"in the last batch")
    # the same companies' filings (SEC XBRL for US filers, DART for Korea): exact dates, depth, the newest filing
    counts = refresh_filings(fetched_ids, tg, None if backfill or only else FILINGS_MAX_MINUTES, DART_WORKERS)
    log(f"filings: SEC facts of {counts['sec']} companies, DART reports of {counts['dart']} "
        f"({counts['errors']} failed)")
    build()
    attempted = ok + nodata + failed
    return attempted == 0 or ok + nodata > 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(description="Financial statements (Yahoo Finance) for every public graph company")
    p.add_argument("--backfill", action="store_true", help="fetch every company (about 2.5 s each)")
    p.add_argument("--build-only", action="store_true", help="rebuild the web files from the cache, no network")
    p.add_argument("--only", help="comma-separated node ids, e.g. \"Micron,NVIDIA\"")
    p.add_argument("--limit", type=int, help="fetch at most this many companies")
    p.add_argument("--max-minutes", type=float, help="stop fetching after this many minutes")
    p.add_argument("--filings-only", action="store_true",
                   help="refresh the SEC / DART filings of every company (or --only), no Yahoo, then rebuild")
    p.add_argument("--workers", type=int, default=1, help="with --filings-only: DART companies read at once")
    args = p.parse_args(argv)
    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    if args.build_only:
        build()
        return 0
    if args.filings_only:
        tg = targets()
        ids = due_companies({k: v for k, v in tg.items() if not only or k in only}, {}, {}, today(), backfill=True)
        counts = refresh_filings(ids[:args.limit] if args.limit else ids, tg, args.max_minutes, args.workers)
        log(f"filings: SEC facts of {counts['sec']} companies, DART reports of {counts['dart']} "
            f"({counts['errors']} failed)")
        build()
        return 0
    return 0 if run(backfill=args.backfill, only=only, limit=args.limit, max_minutes=args.max_minutes) else 1


if __name__ == "__main__":
    sys.exit(main())
