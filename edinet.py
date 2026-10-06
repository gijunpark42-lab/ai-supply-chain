"""
edinet.py — Japanese companies' statutory reports from the FSA's EDINET → transcripts/edinet/*.txt,
queued for `enrich japan`.

Why this exists
---------------
TDnet (tdnet.py) carries a Japanese company's results releases, but it keeps only 31 days, and the deepest
supply-chain text sits in the statutory reports every listed company files with the Financial Services Agency
(FSA) on EDINET:
    有価証券報告書  annual securities report     (EDINET docTypeCode 120; an amended one, 訂正, = 130)
    半期報告書      semi-annual report           (160; amended = 170). Since April 2024 listed companies file a
                                                 半期報告書 for the first half instead of a Q2 quarterly report
                                                 (the Q1 / Q3 quarterly reports were abolished).
They hold 主要な相手先別の販売実績 (named customers with their % of sales), 生産・受注・販売の実績, 設備投資 and
設備の新設計画 (capex), 研究開発活動, 経営方針・対処すべき課題 and management's own analysis (MD&A).
This is Japan's equivalent of dart.py (Korea's periodic reports).

Commands (python -X utf8 edinet.py …)
-------------------------------------
    codes                                               EDINET's code list (NO key needed) → edinet/codes.json
    sync [--since YYYY-MM-DD] [--company "<Company>" …] walk EDINET's daily lists, save our companies' new reports
    fetch "<Company>" [--latest] [--days N]             backfill one company: its newest annual report AND newest
                                                        semi-annual report (--latest: only the single newest one)
    pending [--company "<Company>"] [--market JP]       the queue (`enrich japan` works it)
    done --label "<label>" [--why …] | --all            one report handled (or every queued one)
    status [--company "<Company>"]                      every report seen for our companies and its state

Files
-----
    transcripts/edinet/<slug>_<YYYY-MM-DD>_<docID>.txt          the WHOLE report: header + every section, tables
                                                                flattened to "a | b | c" rows (kept for verification)
    transcripts/edinet/<slug>_<YYYY-MM-DD>_<docID>_extract.txt  only the key sections (what the enricher reads; an
                                                                amended report has no extract — it is short)
    edinet/sync_state.json   last sync, runs, every report of our companies seen with its status
                             (listed / saved / skip:<why> / later: <why> / enriched:<date>), hashes of saved texts
    edinet/pending.json      saved reports not yet enriched
    edinet/codes.json        securities code → EDINET code, names, fiscal-year end (from `codes`; re-made when missing)
    edinet/index.json        cache of EDINET's daily lists (every listed company's 120/130/160/170 rows) — gitignored

How EDINET answers (API v2 spec ESE140206 and the viewing guide ESE140133, read 2026-10-04)
------------------------------------------------------------------------------------------
List:       GET https://api.edinet-fsa.go.jp/api/v2/documents.json?date=YYYY-MM-DD&type=2&Subscription-Key=…
            One "file date" per request (any date in the last 10 years, weekends included). Each row: docID,
            edinetCode, secCode (5 characters = the 4-character stock code + "0", the same code TDnet uses),
            docTypeCode, periodStart / periodEnd (the business year, for annual AND semi-annual reports), submitDateTime,
            docDescription, withdrawalStatus, disclosureStatus, xbrlFlag, pdfFlag, englishDocFlag, csvFlag.
            A file date's list is complete once that day is over (JST).
Document:   GET https://api.edinet-fsa.go.jp/api/v2/documents/<docID>?type=N&Subscription-Key=…
            type=1 = the filed report (ZIP: XBRL/PublicDoc/0000000_header…htm, 0101010_honbun…_ixbrl.htm, …: one
            inline-XBRL HTML file per section, named so that sorting by name gives the document order),
            type=2 = the PDF, type=5 = CSV of the XBRL values.
Errors:     EDINET answers HTTP 200 even on errors, with a JSON body ({"StatusCode": 401, …} for a missing or wrong
            key; {"metadata": {"status": "404", …}} otherwise) — so the Content-Type decides (spec 3-3).
Key:        every API call needs a free key (EDINET_API_KEY in .env). The code list (`codes`) does not.
Why type=1 and not the CSV (type=5): the viewing guide (ESE140133 p.18) says a CSV value longer than 30,000 characters
            is CUT at 30,000, so a long section would be silently truncated. The HTML of type=1 is the whole report
            and keeps every table row. The PDF (type=2) is the fallback when a report has no XBRL.
"""

import argparse
import calendar
import csv
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import unicodedata
import warnings
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv

from taxonomy import market_of
from tdnet import page_text, universe   # the same Japanese universe (TSE code + "0") and PDF page reader as tdnet.py

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)   # inline XBRL is XHTML; html.parser reads it fine

META = ROOT / "company_metadata.json"
CODES = ROOT / "edinet" / "codes.json"
STATE = ROOT / "edinet" / "sync_state.json"
PENDING = ROOT / "edinet" / "pending.json"
INDEX = ROOT / "edinet" / "index.json"
OUT_DIR = ROOT / "transcripts" / "edinet"
IR_STATE = ROOT / "ir" / "sync_state.json"       # ir_pull.py's seen URLs: a report it already saved is not saved twice

API = "https://api.edinet-fsa.go.jp/api/v2"
CODE_LIST_URL = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
VIEWER = "https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{doc_id},,2"   # the public page of one filed document
REGISTER_URL = "https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) earnings-ai edinet.py"
JST = timezone(timedelta(hours=9))                # EDINET's dates are Japan time

PAUSE = 1.0             # seconds between two API requests (EDINET answers 429 to bursts)
FIRST_SYNC_DAYS = 120   # a company's first sync reaches back this far: the last annual-report season (late June)
RESYNC_OVERLAP = 3      # a later sync re-reads this many days before the last sync
FETCH_DAYS = 400        # `fetch` walks back at most this many days (one annual report is always inside)
MIN_TEXT = 500          # fewer characters = nothing readable (an image-only PDF)

# docTypeCode -> (pending kind, English name used in the label, Japanese name)
DOC_TYPES = {
    "120": ("annual", "annual securities report", "有価証券報告書"),
    "130": ("amended annual", "amended annual securities report", "訂正有価証券報告書"),
    "160": ("semi-annual", "semi-annual report", "半期報告書"),
    "170": ("amended semi-annual", "amended semi-annual report", "訂正半期報告書"),
}
SEMI = {"160", "170"}
AMENDED = {"130", "170"}
# the list fields kept in the cache (edinet/index.json)
KEEP_FIELDS = ("docID", "edinetCode", "secCode", "filerName", "docTypeCode", "periodStart", "periodEnd",
               "submitDateTime", "docDescription", "parentDocID", "withdrawalStatus", "disclosureStatus",
               "xbrlFlag", "pdfFlag", "englishDocFlag")

MISSING_KEY = (
    "EDINET_API_KEY is missing in .env — EDINET's document API needs a free key.\n"
    f"  1. Register (free): {REGISTER_URL}\n"
    "     (the page opens a pop-up window: allow pop-ups for api.edinet-fsa.go.jp)\n"
    "  2. Add one line to .env in the repo root:   EDINET_API_KEY=<the key EDINET shows you>\n"
    "  3. Run again, e.g.   python -X utf8 edinet.py sync\n"
    "(`edinet.py codes`, `pending`, `done` and `status` work without a key.)"
)
BAD_KEY = ("EDINET refused the API key (status 401). Check the EDINET_API_KEY line in .env against the key shown at "
           f"{REGISTER_URL} (no quotes, no spaces).")


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def jst_today():
    return datetime.now(JST).date()


def new_state():
    return {"last_sync": None, "runs": [], "companies": {}, "filings": {}, "hashes": {}}


def load_state():
    state = load(STATE, new_state())
    for k, v in new_state().items():
        state.setdefault(k, v)
    return state


def new_index():
    return {"days": {}, "rows": {}}


def api_key():
    """The key from .env — or stop with the instructions to get one."""
    key = (os.getenv("EDINET_API_KEY") or "").strip()
    if not key:
        sys.exit(MISSING_KEY)
    return key


def scrub(text):
    """Remove the API key from an error message (a requests error repeats the whole URL, key included)."""
    key = (os.getenv("EDINET_API_KEY") or "").strip()
    return text.replace(key, "***") if key else text


class EdinetError(Exception):
    """EDINET answered with an error (its own status + message), or the network failed."""


# ---------------------------------------------------------------- the API

_session = requests.Session()
_session.headers.update({"User-Agent": UA})
_last = [0.0]


def _polite():
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def json_status(r):
    """(status, message) of a JSON answer. EDINET uses two shapes: the gateway's own {"StatusCode": 401, "message"}
    for a key problem, and {"metadata": {"status", "message"}} for everything else (spec 3-3)."""
    try:
        data = r.json()
    except ValueError:
        return str(r.status_code), "answer is not JSON"
    if "StatusCode" in data:
        return str(data["StatusCode"]), str(data.get("message", ""))
    meta = data.get("metadata") or {}
    return str(meta.get("status", r.status_code)), str(meta.get("message", ""))


def api_get(path, params, tries=3):
    """GET one EDINET API path with the key. Returns the response; raises EdinetError with EDINET's status.
    A wrong key stops the program (nothing else can work); 429 / 5xx / network errors are retried."""
    key = api_key()
    last = EdinetError("no answer")
    for attempt in range(tries):
        _polite()
        try:
            r = _session.get(f"{API}/{path}", params={**params, "Subscription-Key": key}, timeout=180)
        except requests.RequestException as exc:
            last = EdinetError(scrub(f"{exc.__class__.__name__}: {exc}")[:200])
            time.sleep(5 * (attempt + 1))
            continue
        if "json" in r.headers.get("Content-Type", ""):
            status, message = json_status(r)
            if status == "200":
                return r                                  # the document list (JSON) on success
            if status == "401":
                sys.exit(BAD_KEY)
            last = EdinetError(f"EDINET {status} {message}".strip())
            if status == "429" or status.startswith("5"):
                time.sleep(60 if status == "429" else 10 * (attempt + 1))
                continue
            raise last                                    # 400 / 404: asking again will not help
        if r.status_code == 200:
            return r                                      # a ZIP or a PDF
        last = EdinetError(f"HTTP {r.status_code}")
        time.sleep(5 * (attempt + 1))
    raise last


def list_day(day):
    """EDINET's list for one file date (YYYY-MM-DD): (the annual / semi-annual rows of listed companies, all rows)."""
    data = api_get("documents.json", {"date": day, "type": 2}).json()
    results = data.get("results") or []
    rows = [{k: r.get(k) for k in KEEP_FIELDS} for r in results
            if r.get("docTypeCode") in DOC_TYPES and r.get("secCode")]
    return rows, len(results)


def ensure_listed(days, index, quiet=False):
    """List every day not yet in the cache (or listed before that day was over), then save the cache."""
    today = jst_today().isoformat()
    todo = [d for d in days if d not in index["days"] or index["days"][d]["at"] <= d]
    for i, day in enumerate(todo, 1):
        rows, n = list_day(day)
        for row in rows:
            known = index["rows"].get(row["docID"])
            if known:                                     # listed again later (an edit / withdrawal): keep the
                known["withdrawalStatus"] = row["withdrawalStatus"]   # first file date, update the statuses
                known["disclosureStatus"] = row["disclosureStatus"]
            else:
                index["rows"][row["docID"]] = dict(row, fileDate=day)
        index["days"][day] = {"at": today, "documents": n}
        save(INDEX, index)                                # after every day, so an interrupted run resumes
        if not quiet and (i % 30 == 0 or i == len(todo)):
            print(f"  listed {i}/{len(todo)} days (up to {day})")


# ---------------------------------------------------------------- the EDINET code list (no key)

def download_codes():
    """Edinetcode.zip → edinet/codes.json: {secCode: {edinet_code, name, name_en, fy_end}} for listed filers.
    The CSV is Shift_JIS; line 1 = download date + count, line 2 = column names, rows from line 3."""
    r = requests.get(CODE_LIST_URL, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode("cp932", errors="replace")
    rows = list(csv.reader(raw.splitlines()))
    # NFKC turns the full-width column names into plain ones: 'ＥＤＩＮＥＴコード' -> 'EDINETコード'
    header = [unicodedata.normalize("NFKC", h).strip() for h in rows[1]]
    col = {h: i for i, h in enumerate(header)}
    need = ["EDINETコード", "決算日", "提出者名", "提出者名(英字)", "証券コード"]
    missing = [h for h in need if h not in col]
    if missing:
        sys.exit(f"EDINET code list changed its columns (missing {missing}); header: {header}")
    table = {}
    for row in rows[2:]:
        if len(row) < len(header):
            continue
        sec = row[col["証券コード"]].strip()
        if sec:
            table[sec] = {"edinet_code": row[col["EDINETコード"]].strip(), "name": row[col["提出者名"]].strip(),
                          "name_en": row[col["提出者名(英字)"]].strip(), "fy_end": row[col["決算日"]].strip()}
    save(CODES, {"downloaded": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"), "source": CODE_LIST_URL,
                 "codes": table})
    return table


def load_codes():
    """edinet/codes.json's table (downloaded first when missing — it needs no key)."""
    if not CODES.exists():
        download_codes()
    return load(CODES, {}).get("codes", {})


# ---------------------------------------------------------------- fiscal year and label

DESC_PERIOD = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\D{1,3}(\d{4})/(\d{1,2})/(\d{1,2})")   # '(2025/04/01－2026/03/31)'


def _iso(text):
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _month_day(year, month, day):
    """date(year, month, day), with the day clipped to the month's length ('2月29日' in a normal year)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def fiscal_year_end(row, code_entry):
    """(the last day of the fiscal year the report covers, how it was found) — or (None, None).
    The label names the fiscal year by the year it ENDS in, as the graph does for March years
    (Tokyo Electron Q1 FY2027 = Apr-Jun 2026), so an annual report for Apr 2025 - Mar 2026 is FY2026."""
    semi = row["docTypeCode"] in SEMI
    start, end = _iso(row.get("periodStart") or ""), _iso(row.get("periodEnd") or "")
    how = "EDINET period fields"
    if not (start and end):                               # an amended report lists no period; its title does
        m = DESC_PERIOD.search(row.get("docDescription") or "")
        if m:
            y1, m1, d1, y2, m2, d2 = (int(x) for x in m.groups())
            start, end, how = date(y1, m1, d1), date(y2, m2, d2), "period in the EDINET document title"
    if start and end:
        if semi and (end - start).days < 300:             # the half-year itself: the year ends 12 months after it starts
            return _month_day(start.year + 1, start.month, start.day) - timedelta(days=1), how
        return end, how
    # last resort: the fiscal-year end in the code list ('3月31日', or '3月末日' = the month's last day) and the filing date
    m = re.match(r"(\d{1,2})月(\d{1,2}|末)日", (code_entry or {}).get("fy_end", ""))
    if not m:
        return None, None
    filed = _iso(row["submitDateTime"])
    month, day = int(m.group(1)), 31 if m.group(2) == "末" else int(m.group(2))   # 31 is clipped to the month
    ends = [_month_day(y, month, day) for y in (filed.year - 1, filed.year, filed.year + 1)]
    # an annual report covers the year that ended before it was filed; a semi-annual one, the year still running
    end = min(e for e in ends if e > filed) if semi else max(e for e in ends if e < filed)
    return end, "fiscal-year end in edinet/codes.json"


def label_for(company, row, fy_end, state):
    """'<Company> annual securities report: FY2026 (06-20-2026)' / '<Company> semi-annual report: H1 FY2027 (11-12-2026)'
    (amended: '<Company> amended annual securities report: …'), dated the filing day. Two filings of the same kind on the
    same day get '#2'."""
    english = DOC_TYPES[row["docTypeCode"]][1]
    half = "H1 " if row["docTypeCode"] in SEMI else ""
    filed = _iso(row["submitDateTime"])
    base = f"{company} {english}: {half}FY{fy_end.year}"
    used = {f.get("label") for f in state["filings"].values()}
    label, k = f"{base} ({filed:%m-%d-%Y})", 2
    while label in used:
        label, k = f"{base} #{k} ({filed:%m-%d-%Y})", k + 1
    return label


# ---------------------------------------------------------------- reading a report

def html_to_text(body):
    """One inline-XBRL HTML section file → plain text. Tables become 'cell | cell | cell' rows so every number keeps
    its row and column (the same idea as dart.py); the hidden XBRL header block (contexts, units) is dropped."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("cp932", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    hidden = soup.find_all(["script", "style", "head", "ix:header"]) + \
        soup.find_all(style=re.compile(r"display\s*:\s*none", re.I))
    for tag in hidden:
        if not tag.decomposed:                            # a tag inside one removed a moment ago is gone already
            tag.decompose()
    # innermost tables first: a table inside a cell becomes text inside that cell
    for table in reversed(soup.find_all("table")):
        lines = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if any(cells):
                lines.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(lines) + "\n")
    for tag in soup.find_all(["p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
        tag.insert_before("\n")                           # each paragraph / heading on its own line
    out = html.unescape(soup.get_text())
    out = re.sub(r"[ \t\u00a0\u3000]+", " ", out)   # \u00a0 = no-break space, \u3000 = full-width space
    out = re.sub(r" *\n *", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def public_doc_text(zip_bytes):
    """The report text from a type=1 ZIP: every PublicDoc HTML file in name order (= document order), each under a
    '==== <file> ====' line. The audit report (AuditDoc), images and XBRL schema files are left out."""
    parts = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = [n for n in z.namelist() if "PublicDoc/" in n and n.lower().endswith((".htm", ".html", ".xhtml"))]
        for name in sorted(names, key=lambda n: n.rsplit("/", 1)[-1]):
            text = html_to_text(z.read(name))
            if text:
                parts.append(f"==== {name.rsplit('/', 1)[-1]} ====\n{text}\n")   # ZIP names always use '/'
    return "\n".join(parts)


def pdf_text(content):
    """The report text from the PDF (type=2), page by page (tdnet.py's pypdf reader)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            pages.append(f"==== page {i} ====\n{page_text(page)}\n")
        except Exception:                                 # one broken page must not lose the report
            pages.append(f"==== page {i} ====\n[page could not be read]\n")
    return "\n".join(pages)


def report_text(row):
    """(text, how it was read) for one report: the filed HTML (type=1) when it has XBRL, else the PDF (type=2).
    (None, None) when EDINET holds neither; ('', …) for a PDF with no text layer. Raises EdinetError when a download
    failed (the caller retries later)."""
    errors = []
    if row.get("xbrlFlag") == "1":
        try:
            r = api_get(f"documents/{row['docID']}", {"type": 1})
            if r.content[:2] == b"PK":
                text = public_doc_text(r.content)
                if text.strip():                          # an amended report can be short: any filed text counts
                    return text, "the filed report's inline-XBRL HTML (EDINET API type=1), every section in order"
        except EdinetError as exc:                        # try the PDF before giving up
            errors.append(f"type=1: {exc}")
    if row.get("pdfFlag") == "1":
        r = api_get(f"documents/{row['docID']}", {"type": 2})
        if r.content[:4] == b"%PDF":
            text = pdf_text(r.content)
            words = re.sub(r"==== page \d+ ====", "", text).strip()
            return (text if len(words) >= MIN_TEXT else ""), "the report PDF (EDINET API type=2), page by page (pypdf)"
    if errors:
        raise EdinetError("; ".join(errors))
    return None, None


# ---------------------------------------------------------------- the _extract (key sections)

# A numbered heading on its own line, the way every Japanese statutory report writes them:
#   '第一部 【企業情報】' (part), '第２ 【事業の状況】' (chapter), '４ 【経営者による財政状態、…の分析】' (section).
HEADING = re.compile(r"^\s*(?P<num>第[一二三四五六七八九十]+部|第\s*[0-9０-９]+|[0-9０-９]+)\s*[.．、]?\s*(?:\|\s*)?"
                     r"【(?P<title>[^】]{1,70})】\s*$")
OPEN_HEADING = re.compile(r"^\s*(第\s*[0-9０-９]+|[0-9０-９]+)\s*【[^】]*$")       # a heading the PDF broke in two
# Sections kept whole (their title, or the chapter they sit in):
KEEP_SECTION = re.compile(r"事業の内容|経営方針|対処すべき課題|経営者による財政状態|生産、受注及び販売|生産・受注|"
                          r"重要な契約|研究開発活動|設備投資等の概要|主要な設備の状況|設備の新設")
KEEP_CHAPTER = re.compile(r"設備の状況")
# Passages elsewhere (risk factors, segment notes '主要な顧客ごとの情報') that name major customers:
CUSTOMER = re.compile(r"主要な(顧客|相手先|販売先)|特定の?(顧客|販売先|取引先)|相手先別")
PASSAGE_LINES = 25      # a customer passage = the line, 2 lines before it and up to this many after it


def heading_level(num):
    """0 = part (第一部), 1 = chapter (第２), 2 = section (４)."""
    if num.endswith("部"):
        return 0
    return 1 if num.startswith("第") else 2


def join_split_headings(lines):
    """'４ 【経営者による財政状態、経営成績及び' + 'キャッシュ・フローの状況の分析】' -> one line (PDF text only)."""
    out, i = [], 0
    while i < len(lines):
        if OPEN_HEADING.match(lines[i]) and i + 1 < len(lines) and "】" in lines[i + 1] and len(lines[i + 1]) < 60:
            out.append(lines[i].rstrip() + lines[i + 1].strip())
            i += 2
            continue
        out.append(lines[i])
        i += 1
    return out


def key_sections(text):
    """(sections, passages): sections = [(heading path, text)] of the parts the enricher reads, in document order —
    事業の内容, 経営方針・対処すべき課題, 経営者による…分析 (with 生産・受注・販売の実績 and 主要な相手先別の販売実績),
    重要な契約, 研究開発活動 and the whole 設備の状況 chapter; passages = [(heading path, text)] of the lines outside
    them that name major customers (e.g. 主要な顧客ごとの情報 in the segment notes)."""
    lines = join_split_headings(text.splitlines())
    heads, path = [], {}                                  # heads: (line index, level, title, path to here)
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if not m:
            continue
        level = heading_level(m.group("num"))
        path = {lv: shown for lv, shown in path.items() if lv < level}
        path[level] = re.sub(r"\s+", "", line.strip().replace("|", ""))
        heads.append((i, level, m.group("title"), " > ".join(path[lv] for lv in sorted(path))))

    def path_at(i):
        before = [h for h in heads if h[0] <= i]
        return before[-1][3] if before else "(before the first heading)"

    keep = []                                             # (start line, end line, path)
    for k, (i, level, title, where) in enumerate(heads):
        if any(s <= i < e for s, e, _w in keep):
            continue                                      # inside a chapter already kept whole
        if (level == 2 and KEEP_SECTION.search(title)) or (level == 1 and KEEP_CHAPTER.search(title)):
            end = next((j for j, lv, _t, _w in heads[k + 1:] if lv <= level), len(lines))
            keep.append((i, end, where))

    passages = []                                         # (start, end, path), overlapping ones merged
    for i, line in enumerate(lines):
        if any(s <= i < e for s, e, _w in keep) or not CUSTOMER.search(line):
            continue
        start = max(0, i - 2)
        end = min([len(lines), i + PASSAGE_LINES + 1] + [s for s, _e, _w in keep if s > i])
        end = next((j for j in range(i + 1, end) if HEADING.match(lines[j])), end)
        start = max([start] + [e for _s, e, _w in keep if e <= i])
        if passages and start <= passages[-1][1]:
            passages[-1] = (passages[-1][0], max(end, passages[-1][1]), passages[-1][2])
        else:
            passages.append((start, end, path_at(i)))
    def cut(s, e):
        """lines[s:e] as text, without the page / file marker lines that only open the NEXT part."""
        part = lines[s:e]
        while part and (not part[-1].strip() or part[-1].startswith("==== ")):
            part.pop()
        return "\n".join(part).strip()
    return [(w, cut(s, e)) for s, e, w in keep], [(w, cut(s, e)) for s, e, w in passages]


def extract_body(text):
    """The _extract file's body, or '' when no key section was found (then the enricher reads the full file)."""
    sections, passages = key_sections(text)
    if not sections:
        return ""
    out = [f"==== SECTION: {where} ====\n{body}\n" for where, body in sections]
    if passages:
        out.append("==== OTHER PASSAGES THAT NAME MAJOR CUSTOMERS (outside the sections above) ====\n")
        out += [f"---- in {where} ----\n{body}\n" for where, body in passages]
    return "\n".join(out)


# ---------------------------------------------------------------- saving one report

_IR_SEEN = []


def ir_copy(doc_id):
    """The URL under which ir_pull.py already saved this very report, else None (Japanese IR sites often post the
    report PDF with its EDINET document id in the path, e.g. …/yuho_pdf/S100YUOR/00.pdf)."""
    if not _IR_SEEN:
        _IR_SEEN.append(list(load(IR_STATE, {}).get("seen", {})))
    return next((u for u in _IR_SEEN[0] if f"/{doc_id}/" in u or u.rstrip("/").endswith(f"/{doc_id}")), None)


def save_report(company, row, state, codes):
    """Download, read and save one report (full + _extract), queue it. Returns None (saved), a skip reason, or
    'later: …' (retried by the next sync)."""
    doc_id, code = row["docID"], row["docTypeCode"]
    kind, english, japanese = DOC_TYPES[code]
    if row.get("withdrawalStatus") not in (None, "", "0"):
        return "withdrawn by the filer"
    if row.get("disclosureStatus") == "2":
        return "not disclosed (FSA)"
    ir_url = ir_copy(doc_id)
    if ir_url:
        return f"already saved by ir_pull.py ({ir_url})"
    fy_end, fy_how = fiscal_year_end(row, codes.get(row["secCode"]))
    if not fy_end:
        return "later: fiscal year not found (run `python edinet.py codes`)"
    try:
        text, how = report_text(row)
    except EdinetError as exc:
        return f"later: {exc}"[:160]
    if text is None:
        return "no XBRL or PDF on EDINET"
    if not text:
        return "image-only PDF (no text layer)"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest in state["hashes"]:
        return f"same text as {state['hashes'][digest]}"

    label = label_for(company, row, fy_end, state)
    filed = row["submitDateTime"]
    stem = f"{slug(company)}_{filed[:10]}_{doc_id}"
    full_path, extract_path = OUT_DIR / f"{stem}.txt", OUT_DIR / f"{stem}_extract.txt"
    extract = "" if code in AMENDED else extract_body(text)
    code_entry = codes.get(row["secCode"]) or {}
    period = (f"fiscal year ending {fy_end.isoformat()} (FY{fy_end.year}; {fy_how})" +
              ("; this report covers its first half" if code in SEMI else ""))
    header = [
        f"SOURCE: {VIEWER.format(doc_id=doc_id)}",
        f"API: {API}/documents/{doc_id}  (EDINET document id {doc_id})",
        f"TITLE: {row.get('docDescription') or japanese}",
        f"DOCUMENT TYPE: {english} ({japanese}, EDINET docTypeCode {code})",
        f"FILED: {filed[:10]} {filed[11:16]} JST   (EDINET submission time)",
        f"PERIOD: {period}",
        f"COMPANY: {company} (TSE code {row['secCode']}, EDINET code {row.get('edinetCode') or code_entry.get('edinet_code', '?')},"
        f" filed as {row.get('filerName') or code_entry.get('name', '?')})",
        "LANGUAGE: Japanese original — write every entry in English; yen stays yen, written in English (JPY … million)"
        + ("; EDINET also lists an English file for it (not fetched)" if row.get("englishDocFlag") == "1" else ""),
        f"READ FROM: {how}",
        "# NOTE: NOT a transcript — a company statutory filing with the FSA (EDINET). Facts, the company's own plans",
        "#       and management's own analysis only; attribute forecasts as the company's (enrich skill §2, §8).",
        f"# source label: {label}",
    ]
    if code in AMENDED:
        header.insert(-1, "# AMENDED REPORT: only the corrected parts (訂正理由 + 訂正箇所) — read it whole; it is short.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_path.write_text("\n".join(header + [
        f"# EXTRACT: {extract_path.relative_to(ROOT).as_posix()} holds only the key sections" if extract else
        "# EXTRACT: none — read this file whole", ""]) + text + "\n", encoding="utf-8")
    if extract:
        extract_path.write_text("\n".join(header + [
            "# EXTRACT: only the key sections — 事業の内容, 経営方針・経営環境及び対処すべき課題, 経営者による財政状態…の分析",
            "#          (生産・受注及び販売の実績, 主要な相手先別の販売実績), 重要な契約, 研究開発活動, 設備の状況 (設備投資,",
            "#          主要な設備, 設備の新設・除却等の計画) — then every other passage that names major customers.",
            f"#          The whole report: {full_path.relative_to(ROOT).as_posix()}", ""]) + extract + "\n", encoding="utf-8")
    queued = extract_path if extract else full_path
    state["hashes"][digest] = label
    state["filings"].setdefault(doc_id, {}).update({"label": label, "file": queued.relative_to(ROOT).as_posix()})
    pending = load(PENDING, [])
    pending.append({"kind": kind, "company": company, "label": label, "file": queued.relative_to(ROOT).as_posix(),
                    "full": full_path.relative_to(ROOT).as_posix(), "date": filed[:10], "id": doc_id,
                    "doc_type": code, "fy_end": fy_end.isoformat()})
    save(PENDING, pending)
    print(f"  saved {label}" + ("" if extract else "   (no extract — the full file is queued)"))
    return None


def handle(company, row, state, codes):
    """Save one listed report (unless it was handled before) and record its status. Returns the status."""
    doc_id = row["docID"]
    prev = state["filings"].get(doc_id, {}).get("status", "")
    if prev and not prev.startswith(("listed", "later")):
        return prev                                       # saved / skipped / enriched before: never twice
    why = save_report(company, row, state, codes)
    status = "saved" if why is None else (why if why.startswith("later") else "skip:" + why)
    state["filings"].setdefault(doc_id, {}).update({
        "company": company, "sec_code": row["secCode"], "doc_type": row["docTypeCode"],
        "date": row["submitDateTime"][:10], "title": row.get("docDescription"), "status": status})
    save(STATE, state)                                    # after every report, so an interrupted run resumes
    if why:
        word, shown = ("later", why[len("later: "):]) if why.startswith("later") else ("skip", why)
        print(f"  {word} {company} {row['submitDateTime'][:10]} {doc_id}: {shown}")
    return status


# ---------------------------------------------------------------- sync / fetch

def sync(since=None, companies=None):
    """Walk EDINET's daily lists from the last sync (a company's first sync: FIRST_SYNC_DAYS back) to today and save
    every new annual / semi-annual report (and amendment) of our companies."""
    api_key()
    state, index, codes = load_state(), load(INDEX, new_index()), load_codes()
    ours = universe()                                     # {TSE code + "0": company} = EDINET's secCode
    if companies:                                         # --company (repeatable): only these
        missing = set(companies) - set(ours.values())
        if missing:
            sys.exit(f"{sorted(missing)} not Japanese companies with a TSE code in company_metadata.json")
        ours = {c: n for c, n in ours.items() if n in companies}
    today = jst_today()
    last = state.get("last_sync")
    starts = {}
    for name in ours.values():
        if since:
            starts[name] = since
        elif name in state["companies"] and last:
            starts[name] = date.fromisoformat(last) - timedelta(days=RESYNC_OVERLAP)
        else:
            starts[name] = today - timedelta(days=FIRST_SYNC_DAYS)
    oldest = min(starts.values())
    days = [(oldest + timedelta(days=i)).isoformat() for i in range((today - oldest).days + 1)]
    print(f"EDINET lists {days[0]} .. {days[-1]} ({len(days)} days; days already cached are not asked again) …")
    ensure_listed(days, index)
    rows = sorted((r for r in index["rows"].values() if r["secCode"] in ours and days[0] <= r["fileDate"] <= days[-1]
                   and r["fileDate"] >= starts[ours[r["secCode"]]].isoformat()),
                  key=lambda r: (r.get("submitDateTime") or "", r["docID"]))
    counts = {"saved": 0, "skipped": 0, "later": 0, "already": 0}
    for row in rows:
        prev = state["filings"].get(row["docID"], {}).get("status", "")
        status = handle(ours[row["secCode"]], row, state, codes)
        if prev and not prev.startswith(("listed", "later")):
            counts["already"] += 1
        else:
            counts["saved" if status == "saved" else "later" if status.startswith("later") else "skipped"] += 1
    for name in starts:
        state["companies"].setdefault(name, {"first_sync": today.isoformat(), "since": starts[name].isoformat()})
    if not companies:
        state["last_sync"] = today.isoformat()
    state["runs"].append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "days": f"{days[0]}..{days[-1]}",
                          "companies": companies, "reports": len(rows), **counts})
    save(STATE, state)
    print(f"EDINET {days[0]} .. {days[-1]}: {len(rows)} annual / semi-annual reports of our companies — "
          f"{counts['saved']} saved, {counts['skipped']} skipped, {counts['later']} to retry, {counts['already']} handled before")
    print(f"queue now {len(load(PENDING, []))} (`python edinet.py pending`)")


def fetch(company, latest=False, days=FETCH_DAYS):
    """Backfill one company: walk back day by day (cached days cost nothing) until its newest annual report and
    newest semi-annual report are found (--latest: the newest of either), then save them."""
    api_key()
    ours = universe()
    code = next((c for c, n in ours.items() if n == company), None)
    if not code:
        sys.exit(f"{company!r} is not a Japanese company with a TSE code in company_metadata.json")
    state, index, codes = load_state(), load(INDEX, new_index()), load_codes()
    today, found = jst_today(), {}
    print(f"looking back up to {days} days for {company}'s newest {'report' if latest else 'annual + semi-annual reports'} …")
    for back in range(days + 1):
        day = (today - timedelta(days=back)).isoformat()
        ensure_listed([day], index, quiet=True)
        for row in index["rows"].values():
            if (row["fileDate"] == day and row["secCode"] == code and row["docTypeCode"] in ("120", "160")
                    and row["docTypeCode"] not in found and row.get("withdrawalStatus") in (None, "", "0")):
                found[row["docTypeCode"]] = row
        if (latest and found) or len(found) == 2:
            break
        if back and back % 30 == 0:
            print(f"  … back to {day}")
    if not found:
        print(f"no annual or semi-annual report of {company} in the last {days} days")
        return
    targets = sorted(found.values(), key=lambda r: r["submitDateTime"])
    for row in targets[-1:] if latest else targets:
        prev = state["filings"].get(row["docID"], {}).get("status", "")
        status = handle(company, row, state, codes)
        if status == prev:                                # handled before: say so instead of saving it twice
            print(f"  {row['submitDateTime'][:10]} {row['docID']} {DOC_TYPES[row['docTypeCode']][1]}: already {status}")
    print(f"queue now {len(load(PENDING, []))} (`python edinet.py pending`)")


# ---------------------------------------------------------------- queue commands

def mark_done(rows, why=None):
    state = load_state()
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state["filings"].setdefault(r["id"], {"company": r["company"], "date": r["date"]})["status"] = stamp
    save(STATE, state)


def status(company=None):
    """Every report seen for our companies (optionally one company) with its state."""
    filings = load_state()["filings"]
    rows = sorted((f.get("date", ""), f.get("company", "?"), doc_id, f) for doc_id, f in filings.items()
                  if not company or f.get("company") == company)
    for d, co, doc_id, f in rows:
        kind = DOC_TYPES.get(f.get("doc_type"), ("?",))[0]
        print(f"{d}  {co:26s} {doc_id:9s} {kind:20s} {str(f.get('status'))[:50]:50s} {f.get('label') or f.get('title') or ''}")
    print(f"{len(rows)} reports seen")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("codes", help="download EDINET's code list (no key needed) -> edinet/codes.json")
    s = sub.add_parser("sync", help="save our companies' new annual / semi-annual reports")
    s.add_argument("--since", help=f"YYYY-MM-DD; default: {RESYNC_OVERLAP} days before the last sync "
                                   f"(a company's first sync: {FIRST_SYNC_DAYS} days back)")
    s.add_argument("--company", action="append", help="repeatable; default: every Japanese company")
    f = sub.add_parser("fetch", help="backfill one company's newest annual + semi-annual report")
    f.add_argument("company", help="canonical name from company_metadata.json")
    f.add_argument("--latest", action="store_true", help="only the single newest report")
    f.add_argument("--days", type=int, default=FETCH_DAYS, help=f"how far back to look (default {FETCH_DAYS})")
    p = sub.add_parser("pending", help="the queue")
    p.add_argument("--company")
    p.add_argument("--market", help="accepted for symmetry with the other pipelines; every row is JP")
    d = sub.add_parser("done", help="mark queued reports handled")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a report yielded nothing")
    st = sub.add_parser("status", help="every report seen and its state")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "codes":
        table = download_codes()
        ours = universe()
        missing = sorted(f"{name} ({code})" for code, name in ours.items() if code not in table)
        print(f"{len(table)} listed EDINET filers -> {CODES.relative_to(ROOT).as_posix()}; "
              f"{len(ours) - len(missing)} of our {len(ours)} Japanese companies found")
        if missing:
            print("not in the code list: " + ", ".join(missing))
    elif args.cmd == "sync":
        sync(date.fromisoformat(args.since) if args.since else None, args.company)
    elif args.cmd == "fetch":
        fetch(args.company, args.latest, args.days)
    elif args.cmd == "pending":
        meta = load(META, {})
        rows = [r for r in load(PENDING, []) if (not args.company or r["company"] == args.company)
                and (not args.market or market_of(meta.get(r["company"], {}).get("exchange")) == args.market)]
        for r in rows:
            print(f"{r['date']}  {r['company']:26s} {r['label']:75s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit('give --label "<label>" (one report) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)


if __name__ == "__main__":
    main()
