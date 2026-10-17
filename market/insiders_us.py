"""US insider trades (SEC Form 4 / 4/A) for the graph's US-listed companies.

The user asked on 2026-10-17 for insider trades recorded every day by the nightly routine (no model tokens).
Insider trades are NOT "signals": they never go into quarterly_data / chains / patches; they live in
market/history/insiders_us.jsonl and are shown in their own section of the company panel (graph/insiders.json,
built by market/insiders.py from every market's insiders_*.jsonl).

Where the data comes from (all free, all SEC):
  1. Backfill (the last 365 days): SEC's quarterly "Insider Transactions Data Sets" zips, one per quarter
     (https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets). Each zip is ~10 MB and
     already flattened into tables, so a whole year costs 4-5 downloads instead of ~20,000 filing requests.
     The zips are kept in market/cache/insiders_us/ so a company added to the graph later can be backfilled
     from disk without downloading them again.
  2. Daily: the EDGAR daily form index (Archives/edgar/daily-index/<YYYY>/QTR<n>/form.<YYYYMMDD>.idx) for every
     business day since the last run. The Form 4 / 4/A lines of our issuers are kept, and each filing's full
     submission text (one request per filing) is parsed for its ownershipDocument XML.
  No /cgi-bin URLs (SEC's robots.txt disallows them). Every SEC request sends the descriptive EDGAR_USER_AGENT
  (market.common.sec_headers()) and is paced to at most 4 requests per second (SEC allows 10; we stay below 5).

What a row is: one line of Form 4 Table I (non-derivative transactions: the shares that were actually bought,
sold, granted, withheld for tax, or received from an option exercise). Table II (the options/RSUs themselves)
is skipped because it mirrors Table I (an exercise shows up in both tables) and would double count.

History key: accession number + line ("N1", "N2", ... in document order). Whole filings are also skipped when
their accession is already in history, so the backfill and the daily walk never record the same filing twice.

CLI:  python -m market.insiders_us              (daily: new filings since the last run, then rebuild)
      python -m market.insiders_us --backfill   (re-scan the data sets for ALL US companies, then daily)
      python -m market.insiders_us --build-only (rebuild graph/insiders.json from history only)
"""
import argparse
import csv
import datetime as dt
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

import requests

from market.common import (ROOT, load_env, today, sec_headers, read_json, write_json,
                           read_history, append_history, universe)

DATASET = "insiders_us"
KEY_FIELDS = ("accession", "line")
US_EXCHANGES = ("NASDAQ", "NYSE", "NYSE American", "AMEX")
WINDOW_DAYS = 365

CACHE = ROOT / "market" / "cache" / "insiders_us"       # zips, ticker map, daily-index lines, run state
STATE_FILE = CACHE / "state.json"
TICKERS_FILE = CACHE / "company_tickers.json"
IDX_DIR = CACHE / "idx"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DATASETS_PAGE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
DAILY_INDEX = "https://www.sec.gov/Archives/edgar/daily-index"

SOURCE_NAME = "SEC Form 4"
# Read by market/insiders.py for the "sources" list of graph/insiders.json.
SOURCES = [
    {"name": "SEC Form 4 (EDGAR daily index)", "url": "https://www.sec.gov/Archives/edgar/daily-index/"},
    {"name": "SEC Insider Transactions Data Sets", "url": DATASETS_PAGE},
]

# Form 4 transaction code -> our type (contract 2). Everything else (C conversion, J other, D to issuer, ...) = other.
CODE_TYPES = {"P": "buy", "S": "sell", "M": "option_exercise", "X": "option_exercise",
              "F": "tax_withholding", "A": "grant", "G": "gift"}

PLAN_RE = re.compile(r"10b5\s*-?\s*1|10b-5-1", re.I)
NOT_PLAN_RE = re.compile(r"\bnot\b[^.]{0,80}10b5", re.I)

MIN_GAP = 0.25          # seconds between SEC requests = at most 4 per second
_last_request = [0.0]
_session = []           # one shared requests.Session, made on the first SEC request
_tickers = {}           # filled once per run by ticker_map()


def log(msg):
    """Progress and warnings go to stderr so the nightly log shows them."""
    print(f"[insiders_us] {msg}", file=sys.stderr)


# ---------------------------------------------------------------- small helpers

def sec_get(url, timeout=60, retries=3):
    """One polite SEC request: waits so we never exceed MIN_GAP between requests, and reuses one connection
    (a requests.Session) so hundreds of small filings do not each open a new TLS connection.
    Retries like common.get on 429/5xx and network errors; raises after the last failure."""
    if not _session:
        _session.append(requests.Session())
        _session[0].headers.update(sec_headers())
    last = None
    for attempt in range(retries):
        wait = MIN_GAP - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = _session[0].get(url, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code} for {url}")
                time.sleep(3 * (attempt + 1))
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
        finally:
            _last_request[0] = time.time()
    raise last


def is_missing(response):
    """SEC's archive answers a file that does not exist (weekend, holiday, not yet published) with an S3
    'AccessDenied'/'NoSuchKey' XML error. A rate-limit block is a different 403 page, which is NOT 'missing'."""
    if response.status_code == 404:
        return True
    return response.status_code == 403 and ("AccessDenied" in response.text or "NoSuchKey" in response.text)


def to_number(text):
    """'4012678.0' -> 4012678, '1.15' -> 1.15, '' -> None."""
    if text is None:
        return None
    text = str(text).strip().replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def iso_date(text):
    """Data sets write '28-SEP-2026', the XML writes '2026-09-28' (sometimes with a timezone suffix)."""
    text = (text or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        return dt.datetime.strptime(text, "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def filing_url(issuer_cik, accession):
    """The filing's index page on EDGAR (lists the Form 4 document itself)."""
    return (f"https://www.sec.gov/Archives/edgar/data/{int(issuer_cik)}/"
            f"{accession.replace('-', '')}/{accession}-index.htm")


def role_text(director, officer, ten_pct, other, officer_title, other_text):
    """'EVP, CFO; Director; 10% owner' from the relationship check boxes."""
    parts = []
    if officer:
        parts.append((officer_title or "").strip() or "Officer")
    if director:
        parts.append("Director")
    if ten_pct:
        parts.append("10% owner")
    if other:
        parts.append((other_text or "").strip() or "Other")
    return "; ".join(parts)


def mentions_plan(footnote_texts):
    """True when a footnote of this transaction says it was made under a Rule 10b5-1 trading plan."""
    for text in footnote_texts:
        if PLAN_RE.search(text or "") and not NOT_PLAN_RE.search(text or ""):
            return True
    return False


def line_plan(flag, code, fn_ids, plan_fns):
    """Was this line made under a Rule 10b5-1 plan?
    The filing-level check box (aff10b5One) covers the whole form, but a filer usually attaches the plan footnote
    only to the lines the plan made: a sell-to-cover for RSU taxes in the same form is not a plan sale (user,
    2026-10-17 verification, CoreWeave 0001769628-26-000448). So when ANY footnote of the filing mentions a
    10b5-1 plan, only the lines that point at such a footnote are marked; the check box decides (for buys and
    sells only) when no footnote mentions a plan."""
    if plan_fns:
        return bool(set(fn_ids) & set(plan_fns))
    return bool(flag and code in ("P", "S"))


def make_row(*, accession, line, node_ids, issuer_cik, form, filed, owners, code, trans_date, shares, price,
             owned_after, security, ownership, plan, nature=""):
    """One history row = the contract-2 fields + a few extra fields for our own bookkeeping
    (market/insiders.py copies only the contract fields to the website)."""
    value = round(shares * price, 2) if (shares is not None and price is not None) else None
    return {
        "accession": accession, "line": line,
        "node_id": node_ids[0], "node_ids": node_ids, "issuer_cik": int(issuer_cik), "form": form,
        "security": security, "ownership": ownership, "nature": nature or "",
        "date": trans_date or filed, "filed": filed,
        "insider": "; ".join(name for name, _ in owners),
        "role": "; ".join(dict.fromkeys(role for _, role in owners if role)),   # unique roles, in order
        "code": code, "type": CODE_TYPES.get(code, "other"),
        "shares": shares, "price": price, "value": value, "currency": "USD",
        "owned_after": owned_after, "plan_10b5_1": bool(plan),
        "market": "US", "source": SOURCE_NAME, "url": filing_url(issuer_cik, accession),
    }


# ---------------------------------------------------------------- which companies (issuer CIKs)

def ticker_map():
    """{TICKER: cik} from SEC's company_tickers.json, cached on disk and refreshed once a week."""
    if _tickers:
        return _tickers
    cached = read_json(TICKERS_FILE)
    fresh = TICKERS_FILE.exists() and (time.time() - TICKERS_FILE.stat().st_mtime) < 7 * 86400
    if not fresh:
        try:
            r = sec_get(SEC_TICKERS_URL)
            if r.status_code == 200:
                cached = r.json()
                write_json(TICKERS_FILE, cached)
            else:
                log(f"WARNING: company_tickers.json returned HTTP {r.status_code}; using the cached copy")
        except Exception as e:   # network down: fall back to the cached copy
            log(f"WARNING: company_tickers.json failed ({e.__class__.__name__}); using the cached copy")
    for item in (cached or {}).values():
        _tickers.setdefault(str(item["ticker"]).upper(), int(item["cik_str"]))
    return _tickers


def us_issuers():
    """{issuer CIK: [node ids]} for graph nodes listed on a US exchange."""
    tickers = ticker_map()
    out = {}
    for node_id, info in universe().items():
        if info.get("status") != "public" or info.get("exchange") not in US_EXCHANGES or not info.get("ticker"):
            continue
        cik = tickers.get(info["ticker"].upper().replace(".", "-").replace("/", "-"))
        if cik is None:
            log(f"note: no SEC CIK for {node_id} ({info['ticker']}); skipped")
            continue
        out.setdefault(cik, []).append(node_id)
    return out


def known_accessions():
    return {r.get("accession") for r in read_history(DATASET)}


# ---------------------------------------------------------------- 1) quarterly data sets (backfill)

def quarter_end(q):
    """'2026q3' -> 2026-09-30 (the day before the next quarter starts)."""
    year, n = int(q[:4]), int(q[5])
    if n == 4:
        return dt.date(year, 12, 31)
    return dt.date(year, 3 * n + 1, 1) - dt.timedelta(days=1)


def dataset_links():
    """{'2026q3': absolute zip URL} scraped from SEC's data-set page (the folder name changed in 2026)."""
    r = sec_get(DATASETS_PAGE)
    if r.status_code != 200:
        raise RuntimeError(f"data-set page returned HTTP {r.status_code}")
    links = {}
    for href, quarter in re.findall(r'href="([^"]*?(\d{4}q\d)_form345\.zip)"', r.text):
        links[quarter] = href if href.startswith("http") else "https://www.sec.gov" + href
    return links


def tsv_rows(zf, name):
    """Stream one tab-separated table out of a data-set zip as dicts."""
    with zf.open(name) as f:
        reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                            delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader)
        for values in reader:
            yield dict(zip(header, values))


def rows_from_zip(path, issuers, skip, cutoff):
    """History rows for our issuers' Form 4 / 4/A filings (filed on/after cutoff) in one data-set zip."""
    zf = zipfile.ZipFile(path)
    subs = {}
    for s in tsv_rows(zf, "SUBMISSION.tsv"):
        if s.get("DOCUMENT_TYPE") not in ("4", "4/A"):
            continue
        cik = to_number(s.get("ISSUERCIK"))
        filed = iso_date(s.get("FILING_DATE"))
        if cik in issuers and s["ACCESSION_NUMBER"] not in skip and filed and filed >= cutoff:
            subs[s["ACCESSION_NUMBER"]] = s
    owners = {}
    for o in tsv_rows(zf, "REPORTINGOWNER.tsv"):
        if o["ACCESSION_NUMBER"] in subs:
            rel = (o.get("RPTOWNER_RELATIONSHIP") or "").lower()       # e.g. "Director,Officer"
            role = role_text("director" in rel, "officer" in rel, "tenpercentowner" in rel, "other" in rel,
                             o.get("RPTOWNER_TITLE"), o.get("RPTOWNER_TXT"))
            owners.setdefault(o["ACCESSION_NUMBER"], []).append((o["RPTOWNERNAME"].strip(), role))
    footnotes = {}
    for f in tsv_rows(zf, "FOOTNOTES.tsv"):
        if f["ACCESSION_NUMBER"] in subs:
            footnotes[(f["ACCESSION_NUMBER"], f["FOOTNOTE_ID"])] = f.get("FOOTNOTE_TXT") or ""
    trans = {}
    for t in tsv_rows(zf, "NONDERIV_TRANS.tsv"):
        if t["ACCESSION_NUMBER"] in subs:
            trans.setdefault(t["ACCESSION_NUMBER"], []).append(t)

    plan_fns = {}                              # accession -> ids of its footnotes that mention a 10b5-1 plan
    for (accession, fid), text in footnotes.items():
        if mentions_plan([text]):
            plan_fns.setdefault(accession, set()).add(fid)
    rows = []
    for accession, items in trans.items():
        s = subs[accession]
        flag = (s.get("AFF10B5ONE") or "").strip().lower() in ("1", "true")
        items.sort(key=lambda t: int(t.get("NONDERIV_TRANS_SK") or 0))     # SK follows document order
        for i, t in enumerate(items, start=1):
            code = (t.get("TRANS_CODE") or "").strip()
            fn_ids = set()                      # every footnote this transaction points at (*_FN columns)
            for col, val in t.items():
                if col.endswith("_FN") and val:
                    fn_ids.update(x.strip() for x in val.split(","))
            plan = line_plan(flag, code, fn_ids, plan_fns.get(accession, set()))
            rows.append(make_row(
                accession=accession, line=f"N{i}", node_ids=issuers[to_number(s["ISSUERCIK"])],
                issuer_cik=s["ISSUERCIK"], form=s["DOCUMENT_TYPE"], filed=iso_date(s["FILING_DATE"]),
                owners=owners.get(accession, []), code=code, trans_date=iso_date(t.get("TRANS_DATE")),
                shares=to_number(t.get("TRANS_SHARES")), price=to_number(t.get("TRANS_PRICEPERSHARE")),
                owned_after=to_number(t.get("SHRS_OWND_FOLWNG_TRANS")),
                security=(t.get("SECURITY_TITLE") or "").strip(),
                ownership=(t.get("DIRECT_INDIRECT_OWNERSHIP") or "").strip(), plan=plan,
                nature=(t.get("NATURE_OF_OWNERSHIP") or "").strip()))
    return rows


def from_datasets(issuers, skip, cutoff_day):
    """Rows from every published quarterly zip that overlaps the window. Returns (rows, last quarter end covered).
    Zips are cached; quarters entirely older than the window are deleted from the cache.
    Any failed download raises, so the year never silently has a hole in it."""
    links = dataset_links()
    wanted = sorted(q for q in links if quarter_end(q) >= cutoff_day)
    if not wanted:
        raise RuntimeError("no data-set links found on the SEC page (layout changed?)")
    for old in CACHE.glob("*_form345.zip"):
        if old.name.split("_")[0] not in wanted:
            old.unlink()
    rows = []
    for q in wanted:
        path = CACHE / f"{q}_form345.zip"
        if not path.exists():
            r = sec_get(links[q], timeout=180)
            if r.status_code != 200:
                raise RuntimeError(f"{q} data set returned HTTP {r.status_code}")
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(path)
            log(f"downloaded {q} data set ({len(r.content) / 1e6:.1f} MB)")
        got = rows_from_zip(path, issuers, skip, cutoff_day.isoformat())
        skip.update(row["accession"] for row in got)
        rows += got
        log(f"{q} data set: {len(got)} rows for {len(issuers)} companies")
    return rows, quarter_end(wanted[-1])


# ---------------------------------------------------------------- 2) daily index + filing XML

def idx_lines(day):
    """Form 4 / 4/A lines of one day's EDGAR form index as {cik: [[form, file], ...]}, or None when that day has
    no index (holiday, or not published yet). Only CIKs that have a ticker are kept (issuers, not people), and
    the result is cached in market/cache/insiders_us/idx/ so a later catch-up of new companies needs no request."""
    cache = IDX_DIR / f"{day:%Y%m%d}.json"
    cached = read_json(cache)
    if cached is not None:
        return cached
    url = f"{DAILY_INDEX}/{day.year}/QTR{(day.month - 1) // 3 + 1}/form.{day:%Y%m%d}.idx"
    r = sec_get(url)
    if is_missing(r):
        return None
    if r.status_code != 200:
        raise RuntimeError(f"daily index {day} returned HTTP {r.status_code}")
    with_ticker = set(ticker_map().values())
    line_re = re.compile(r"^(4(?:/A)?)\s+.*?\s+(\d+)\s+(\d{8})\s+(edgar/\S+)\s*$")
    out = {}
    for line in r.text.splitlines():
        m = line_re.match(line)
        if m and int(m.group(2)) in with_ticker:
            out.setdefault(m.group(2), []).append([m.group(1), m.group(4)])
    write_json(cache, out)
    return out


def xml_text(node, path):
    """Text of <path><value>..</value></path> (or of <path> itself), '' when missing."""
    found = node.find(path + "/value")
    if found is None:
        found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def rows_from_submission(text, accession, filed, issuers):
    """Parse the ownershipDocument XML inside one full submission .txt into history rows."""
    start, end = text.find("<ownershipDocument"), text.find("</ownershipDocument>")
    if start < 0 or end < 0:
        return []
    try:
        doc = ET.fromstring(text[start:end + len("</ownershipDocument>")])
    except ET.ParseError as e:            # a broken document will not fix itself: log it and move on
        log(f"WARNING: filing {accession} has unreadable XML ({e}); skipped")
        return []
    issuer_cik = to_number(xml_text(doc, "issuer/issuerCik"))
    if issuer_cik not in issuers:
        return []
    form = xml_text(doc, "documentType")
    flag = xml_text(doc, "aff10b5One").lower() in ("1", "true")

    def yes(owner, tag):
        return xml_text(owner, f"reportingOwnerRelationship/{tag}").lower() in ("1", "true")

    owners = []
    for o in doc.findall("reportingOwner"):
        owners.append((xml_text(o, "reportingOwnerId/rptOwnerName"),
                       role_text(yes(o, "isDirector"), yes(o, "isOfficer"), yes(o, "isTenPercentOwner"),
                                 yes(o, "isOther"), xml_text(o, "reportingOwnerRelationship/officerTitle"),
                                 xml_text(o, "reportingOwnerRelationship/otherText"))))
    footnotes = {f.get("id"): "".join(f.itertext()) for f in doc.findall("footnotes/footnote")}
    plan_fns = {fid for fid, text in footnotes.items() if mentions_plan([text])}

    rows = []
    for i, t in enumerate(doc.findall("nonDerivativeTable/nonDerivativeTransaction"), start=1):
        code = xml_text(t, "transactionCoding/transactionCode")
        fn_ids = {f.get("id") for f in t.iter("footnoteId")}
        plan = line_plan(flag, code, fn_ids, plan_fns)
        rows.append(make_row(
            accession=accession, line=f"N{i}", node_ids=issuers[issuer_cik], issuer_cik=issuer_cik, form=form,
            filed=filed, owners=owners, code=code, trans_date=iso_date(xml_text(t, "transactionDate")),
            shares=to_number(xml_text(t, "transactionAmounts/transactionShares")),
            price=to_number(xml_text(t, "transactionAmounts/transactionPricePerShare")),
            owned_after=to_number(xml_text(t, "postTransactionAmounts/sharesOwnedFollowingTransaction")),
            security=xml_text(t, "securityTitle"),
            ownership=xml_text(t, "ownershipNature/directOrIndirectOwnership"), plan=plan,
            nature=xml_text(t, "ownershipNature/natureOfOwnership")))
    return rows


def from_daily_index(first_day, last_day, issuers, skip):
    """Walk business days first_day..last_day. Returns (rows, last day fully read or None, failed?).
    A day without an index (holiday, or not published yet) is simply passed: `done` only moves to days whose
    index was read, so a day SEC has not published yet is tried again on the next run. A failed request stops
    the walk at that day (failed=True) and the next run starts there again."""
    rows, done, failed = [], None, False
    day = first_day
    while day <= last_day:
        if day.weekday() >= 5:                      # EDGAR does not accept filings on weekends
            day += dt.timedelta(days=1)
            continue
        try:
            lines = idx_lines(day)
        except Exception as e:
            log(f"WARNING: daily index {day} failed ({e.__class__.__name__}: {e}); stopping here")
            failed = True
            break
        if lines is None:
            day += dt.timedelta(days=1)
            continue
        for cik, entries in lines.items():
            if int(cik) not in issuers:
                continue
            for form, path in entries:
                accession = path.rsplit("/", 1)[-1].replace(".txt", "")
                if accession in skip:
                    continue
                try:
                    r = sec_get(f"https://www.sec.gov/Archives/{path}")
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                except Exception as e:
                    log(f"WARNING: filing {accession} failed ({e.__class__.__name__}: {e}); will retry next run")
                    failed = True
                    continue
                rows += rows_from_submission(r.text, accession, day.isoformat(), issuers)
                skip.add(accession)
        if failed:
            break
        done = day
        day += dt.timedelta(days=1)
    return rows, done, failed


def prune_idx_cache(before_day):
    """Daily-index lines older than the newest data set (or than the 365-day window) are no longer needed."""
    for f in IDX_DIR.glob("*.json"):
        if f.stem < f"{before_day:%Y%m%d}":
            f.unlink()


# ---------------------------------------------------------------- run / build

def build():
    """graph/insiders.json is shared by every market (US, KR, TW, JP), so the builder lives in market/insiders.py."""
    from market import insiders
    return insiders.build()


def run(backfill=False):
    """Fetch new Form 4s, append them to history, rebuild graph/insiders.json.
    Returns False only when every source we tried failed (the CLI then exits with code 1)."""
    load_env()
    CACHE.mkdir(parents=True, exist_ok=True)
    gitignore = CACHE / ".gitignore"                 # zips and caches are re-made on demand: keep them out of git
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")

    issuers = us_issuers()
    if not issuers:
        log("WARNING: no US issuers found (graph or SEC ticker list missing); nothing to do")
        build()
        return False
    state = read_json(STATE_FILE, {}) or {}
    skip = known_accessions()
    now = dt.date.fromisoformat(today())
    cutoff = now - dt.timedelta(days=WINDOW_DAYS)
    tried, failures, added = 0, 0, 0

    # 1) companies never backfilled (first run, or nodes newly added to the graph): quarterly data sets.
    #    --backfill re-scans them for every company (filings already in history are skipped).
    covered = set(state.get("ciks", []))
    todo = set(issuers) if backfill else set(issuers) - covered
    if todo:
        tried += 1
        new = {cik: issuers[cik] for cik in todo}
        try:
            ds_rows, ds_end = from_datasets(new, skip, cutoff)
        except Exception as e:
            log(f"WARNING: data sets failed ({e.__class__.__name__}: {e}); backfill postponed to the next run")
            failures += 1
            ds_rows, ds_end = [], None
        added += append_history(DATASET, ds_rows, KEY_FIELDS)
        if ds_end:
            if not state.get("last_day"):
                # first run: the daily walk below starts ON the data set's last day, because filings made
                # after 5:30 pm ET that day are only in the NEXT quarter's data set
                state["last_day"] = (ds_end - dt.timedelta(days=1)).isoformat()
                covered |= todo
            else:
                # the daily walk already went past these days for the other companies: catch the new ones up
                gap_rows, _, gap_failed = from_daily_index(ds_end, dt.date.fromisoformat(state["last_day"]),
                                                           new, skip)
                added += append_history(DATASET, gap_rows, KEY_FIELDS)
                if not gap_failed:
                    covered |= todo
            state["ciks"] = sorted(covered)
            state["datasets_to"] = ds_end.isoformat()
            prune_idx_cache(ds_end)
            write_json(STATE_FILE, state)

    # 2) daily walk: every business day after the last fully read day, up to today
    walk = {cik: nodes for cik, nodes in issuers.items() if cik in covered} or issuers
    if state.get("last_day"):
        start = dt.date.fromisoformat(state["last_day"]) + dt.timedelta(days=1)
    else:
        start = now - dt.timedelta(days=7)          # no data set yet: at least keep the last week
    tried += 1
    day_rows, done, failed = from_daily_index(start, now, walk, skip)
    failures += failed
    added += append_history(DATASET, day_rows, KEY_FIELDS)
    if done:
        state["last_day"] = done.isoformat()
    state["last_run"] = today()
    write_json(STATE_FILE, state)
    prune_idx_cache(cutoff)
    log(f"{added} new history rows; daily index read through {state.get('last_day')}")
    build()
    return failures < tried


def recheck_history():
    """One-off repair (user, 2026-10-17 verification) of rows recorded before 2026-10-17, written to
    market/history/corrections.jsonl (applied by market/insiders.py; the history rows stay as they were):
      - 10b5-1 flag per line (line_plan): the old rows carry the filing-level check box on every buy/sell line;
      - "nature" of an indirect holding ("By Spouse", "By 2022 Irrevocable Trust"), which the old rows did not
        record, so sales of two trusts in one filing were merged into one row. Only lines whose filing has more
        than one holder for the same day, code and security get a correction (they are the only ones that merge
        wrongly).
    Data-set rows are re-read from the cached quarterly zips (no request); rows from the daily index are re-read
    from their filing (one SEC request each, paced like every other request) only when one of their lines can
    change: a line marked as a plan trade, or two indirect lines of the same day and code.
    Returns the number of corrections added."""
    from market import corrections
    load_env()
    history = corrections.apply(DATASET, read_history(DATASET))
    by_key = {(r["accession"], r["line"]): r for r in history}
    issuers, first, indirect = {}, {}, {}
    for r in history:
        issuers.setdefault(r["issuer_cik"], r.get("node_ids") or [r["node_id"]])
        first.setdefault(r["accession"], r)
        if r.get("ownership") == "I":
            group = (r["accession"], r.get("date"), r.get("code"), r.get("security"))
            indirect[group] = indirect.get(group, 0) + 1
    fresh, in_zips = [], set()
    for path in sorted(CACHE.glob("*_form345.zip")):
        got = rows_from_zip(path, issuers, set(), "0000-00-00")
        in_zips.update(r["accession"] for r in got)
        fresh += got
        log(f"recheck: {path.name} re-read ({len(got)} lines)")
    todo = {r["accession"] for r in history if r["accession"] not in in_zips and r.get("plan_10b5_1")}
    todo |= {g[0] for g, n in indirect.items() if n >= 2 and g[0] not in in_zips}
    log(f"recheck: {len(todo)} daily-index filings to read again")
    for accession in sorted(todo):
        row = first[accession]
        url = (f"https://www.sec.gov/Archives/edgar/data/{row['issuer_cik']}/"
               f"{accession.replace('-', '')}/{accession}.txt")
        try:
            resp = sec_get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
        except Exception as e:
            log(f"WARNING: filing {accession} failed ({e.__class__.__name__}: {e}); not rechecked")
            continue
        fresh += rows_from_submission(resp.text, accession, row["filed"], issuers)

    fixes, plan_fixes = [], 0
    natures = {}                                   # (accession, day, code, security) -> natures of its I lines
    for r in fresh:
        if r.get("ownership") == "I":
            natures.setdefault((r["accession"], r["date"], r["code"], r["security"]), set()).add(r["nature"])
    for r in fresh:
        old = by_key.get((r["accession"], r["line"]))
        if old is None:
            continue
        if bool(old.get("plan_10b5_1")) != r["plan_10b5_1"]:
            plan_fixes += 1
            fixes.append(corrections.correction(
                DATASET, {"accession": r["accession"], "line": r["line"]}, {"plan_10b5_1": r["plan_10b5_1"]},
                reason="10b5-1 flag re-derived per line: the filing's plan footnote is attached to other lines, "
                       "so the filing-level check box does not cover this one",
                source=SOURCE_NAME, url=old.get("url")))
        group = (r["accession"], r["date"], r["code"], r["security"])
        if r.get("ownership") == "I" and len(natures.get(group, ())) > 1 and not old.get("nature"):
            fixes.append(corrections.correction(
                DATASET, {"accession": r["accession"], "line": r["line"]}, {"nature": r["nature"]},
                reason="nature of the indirect holding recorded, so the sales of different holders in this filing "
                       "are not merged into one row",
                source=SOURCE_NAME, url=old.get("url")))
    added = corrections.add(fixes)
    log(f"recheck: {plan_fixes} 10b5-1 flags and {len(fixes) - plan_fixes} holder natures differ, "
        f"{added} new corrections")
    return added


def main():
    ap = argparse.ArgumentParser(description="US insider trades from SEC Form 4 (data sets + daily index)")
    ap.add_argument("--backfill", action="store_true", help="re-scan the quarterly data sets for every US company")
    ap.add_argument("--build-only", action="store_true", help="rebuild graph/insiders.json from history only")
    ap.add_argument("--recheck", action="store_true",
                    help="one-off: re-derive the 10b5-1 flag and holder of rows already in history, then rebuild")
    args = ap.parse_args()
    if args.build_only:
        build()
        return 0
    if args.recheck:
        recheck_history()
        build()
        return 0
    return 0 if run(backfill=args.backfill) else 1


if __name__ == "__main__":
    sys.exit(main())
