"""
hkex.py — Hong Kong-listed companies' own filings on HKEXnews → transcripts/hkex/*.txt, queued for `enrich china`.

Why this exists
---------------
Sixteen graph nodes are listed on the Stock Exchange of Hong Kong (company_metadata.json exchange "HKEX": ASMPT,
Lenovo, Innoscience, Foxconn Interconnect Technology, Kingboard Laminates, Biren Technology, SMIC, Hua Hong
Semiconductor, MiniMax, SUNeVision, Tencent, Zhipu AI, Lightelligence, Time Interconnect Technology, Iluvatar CoreX,
Xiaomi). cninfo.py covers only the Shanghai / Shenzhen A-shares, and many of these names hold no English call on
Investing.com. Every one of them must publish its documents on HKEXnews (www1.hkexnews.hk), the exchange's official
disclosure site, the day they are released: results announcements, annual and interim reports, business updates,
inside information, and notices of discloseable / major / connected transactions (the continuing connected
transactions are often supply agreements with a parent or a sister company, with yearly caps and amounts).
Every document there is the listed company's OWN filing — a company document, never an article.

Commands (python -X utf8 hkex.py …)
-----------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>" …] [--budget MIN]
                                        list each company's new documents, save the ones that can carry facts, queue
    pending [--company "<Company>"] [--market CN]   the queue (`enrich china` works it)
    done --label "<label>" [--why …]                one document handled — enriched, or `--why "no material facts"`
    done --all                                      every queued document handled (only when that is true)
    status [--company "<Company>"]                  every document seen for our companies and its state

Files
-----
    transcripts/hkex/<slug>_<YYYY-MM-DD>_<file no>.txt          header + the document's text, page by page (verbatim)
    transcripts/hkex/<slug>_<YYYY-MM-DD>_<file no>_extract.txt  long annual / interim reports and prospectuses only:
                                                                the key sections the enricher reads (report_extract);
                                                                both files declare the same label, so verify_graph.py
                                                                checks numbers against the whole document
    hkex/sync_state.json   last sync, runs (with skip-reason counts), each company's stock code / HKEXnews stockId /
                           last sync, every document seen {company, date, title, categories, kind, status = saved /
                           skip:<why> / later: <why> / enriched:<date>}, a hash per saved PDF, the filter rules
    hkex/pending.json      saved documents not yet enriched

Labels (enrich skill §5 — "[Company] [document type]: [title] (MM-DD-YYYY)", dated the HKEXnews release day, HKT)
--------------------------------------------------------------------------------------------------------------------
    <Company> HKEX announcement: <short English title, ≤ 60 chars> (MM-DD-YYYY)   results, updates, inside
                                                                                   information, transactions
    <Company> HKEX circular: <short English title> (MM-DD-YYYY)                   a transaction circular
    <Company> annual report: <YYYY or YYYY/YY> Annual Report (MM-DD-YYYY)         like the cninfo / EDINET labels
    <Company> interim report: <YYYY or YYYY/YY> Interim Report (MM-DD-YYYY)
    <Company> quarterly report: <short title> (MM-DD-YYYY)
    <Company> prospectus (MM-DD-YYYY)                                             the SEC prospectus shape
    e.g. "Kingboard Laminates HKEX announcement: Positive Profit Alert (07-30-2026)",
         "Tencent interim report: 2026 Interim Report (08-25-2026)", "Lenovo annual report: 2025/26 Annual Report (06-26-2026)"

How HKEXnews answers (found 2026-10-21; public, no login, no key)
-----------------------------------------------------------------
Stock id:  GET https://www1.hkexnews.hk/search/prefix.do?callback=callback&lang=EN&type=A&name=<5-digit code>&market=SEHK
           -> JSONP callback({"stockInfo": [{"stockId": 7609, "code": "00700", "name": "TENCENT"}, …]}). The id is kept
           in sync_state.json, so this is asked once per company.
List:      GET https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime&category=0
           &market=SEHK&stockId=<id>&documentType=-1&fromDate=YYYYMMDD&toDate=YYYYMMDD&title=&searchType=0&t1code=-2
           &t2Gcode=-2&t2code=-2&rowRange=<n>&lang=E   -> {"result": "<a JSON array as a string>"}; each row: NEWS_ID,
           TITLE, DATE_TIME ("dd/mm/yyyy HH:MM", Hong Kong time), LONG_TEXT (the exchange's own headline categories,
           e.g. "Announcements and Notices - [Final Results / Dividend or Distribution]"), FILE_LINK
           (/listedco/listconews/sehk/YYYY/MMDD/<file no>.pdf), FILE_TYPE, FILE_INFO ("Multi-Files" = an .htm index
           page that links the document's parts), TOTAL_COUNT. lang=ZH lists the Chinese section.
English:   the English and Chinese versions are separate files (the Chinese one ends in _c.pdf). The English list
           (lang=E) is used; a document published only in Chinese shows there as a one-line .htm stub ("published by
           the issuer in the Chinese section"), and its Chinese file is then taken from the lang=ZH list (same day,
           usually the stub's file number minus one).
Politeness: one request every 1.5 s, three tries with a growing pause, a run-time budget (--budget, default 45
           minutes; what is left waits for the next run). A 403 / bot page falls back to Jina Reader
           (https://r.jina.ai/<url>) for the list and for PDF text; Jina cannot read the JSONP stock-id answer.
"""

import argparse
import hashlib
import html as htmllib
import io
import json
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
STATE = ROOT / "hkex" / "sync_state.json"
PENDING = ROOT / "hkex" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "hkex"

BASE = "https://www1.hkexnews.hk"
PREFIX_URL = BASE + "/search/prefix.do"
SEARCH_URL = BASE + "/search/titleSearchServlet.do"
JINA = "https://r.jina.ai/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
HKT = timezone(timedelta(hours=8))          # every HKEXnews time is Hong Kong time
PAUSE = 1.5                                  # seconds between two requests
FIRST_BACK = 120                             # a company's first sync reaches this many days back
REPORT_BACK = 400                            # ... and takes its newest annual report from up to this far back
RESYNC_OVERLAP = 3                           # a later sync re-lists this many days before the company's last sync
BUDGET_MIN = 45                              # default run-time budget (minutes)
MIN_TEXT = 200                               # fewer characters in the whole PDF = image-only
EXTRACT_MIN_PAGES = 30                       # a report / prospectus longer than this also gets an _extract file
ROWS = 1000                                  # rows asked per list request (the window is split when there are more)


# ---------------------------------------------------------------- which documents are kept
# HKEXnews files every document under the exchange's own headline categories (LONG_TEXT). The categories decide
# first, the title second. Every skip is recorded in sync_state.json with its reason and the title, never silently.

RESULTS_CATS = {"Final Results", "Interim Results", "Quarterly Results"}
UPDATE_CATS = {"Other - Business Update", "Other - Trading Update"}
INSIDE_CATS = {"Inside Information", "Profit Warning"}
TRANSACTION_RE = re.compile(r"Discloseable Transaction|Major Transaction|Very Substantial (Acquisition|Disposal)|"
                            r"Connected Transaction|Reverse Takeover")
# a meeting or despatch notice is procedural even when it also names the transaction it is about
PROCEDURAL_RE = re.compile(r"Delay in Dispatch|Results of AGM|Results of EGM|Notice of AGM|Notice of EGM")

# whole groups that never carry operating facts
SKIP_GROUPS = {"Monthly Returns": "monthly return",
               "Next Day Disclosure Returns": "next day disclosure return (share movements / buybacks)",
               "Proxy Forms": "proxy form",
               "Constitutional Documents": "constitutional document",
               "Documents on Display": "documents on display",
               "Debt and Structured Products": "debt / structured product notice",
               "Application Proofs, OC Announcements and Post Hearing Information Packs or PHIPs":
                   "pre-listing draft (application proof / PHIP)"}

# the reason recorded for an announcement that is not kept: the first category that matches, in this order
SKIP_CATS = [
    ("overseas regulatory announcement (a copy of the company's filing on another exchange, e.g. Shanghai STAR; "
     "procedural or a duplicate of its HK report)", r"^Overseas Regulatory Announcement"),
    ("dividend / book closure", r"Dividend|Closure of Books"),
    ("board / personnel", r"Directors|Chief Executive|Company Secretary|Committee Member|Supervisors|Authorised Representative"),
    ("governance / constitution", r"Constitutional|Terms of Reference|Corporate Governance"),
    ("shareholder meeting", r"AGM|EGM"),
    ("share scheme", r"Share Scheme|Share Option"),
    ("financing / share capital", r"Placing|Issue of|Convertible|Debt Securities|Allotment|Capitalisation|Loan Agreement|"
                                  r"Rights Issue|Open Offer|Consideration Issue|Formal Notice|Change in Terms of Securities"),
    ("buyback", r"Buyback|Repurchase"),
    ("share capital admin", r"Shareholding|Movements in Issued Share Capital|Public Float|Conversion of Securities"),
    ("trading / listing admin", r"Trading Halt|Resumption|Suspension|Trading Arrangements|Change of Company Name|"
                                r"Registered Address|Board Lot|Listing on Overseas|Withdrawal of Listing"),
    ("price / turnover enquiry", r"Unusual Price"),
    ("clarification of news reports", r"Clarification"),
    ("litigation", r"Litigation"),
    ("date of board meeting", r"Date of Board Meeting"),
]

# title checks for the kept announcement kinds: capital, treasury and admin matters that sit under a business category
TITLE_SKIPS = [
    ("treasury investment (wealth management / deposits)", r"wealth management|structured deposits?|financial products?|"
                                                           r"money market|treasury"),
    ("financing (loans / guarantees / deposit services)", r"\bloans?\b|guarantee|financial assistance|deposit services|"
                                                          r"financial services"),
    ("share capital (H-share full circulation)", r"full circulation"),
    ("share scheme", r"share award|share option|restricted share|incentive (scheme|plan)|employee share"),
    ("buyback", r"buy-?back|repurchase"),
    ("trading halt / resumption", r"trading halt|resumption of trading|suspension of trading"),
    ("financing / share capital", r"\bplacing\b|subscription of new|issue of (new )?shares|convertible|\bbonds?\b|"
                                  r"\bnotes\b|rights issue"),
    ("listing admin", r"company name|company logo|stock short name"),
    ("index inclusion", r"\bindex\b|constituent"),
    ("clarification of news reports", r"clarification"),
]
# an "Other - Miscellaneous" announcement is kept only when its title is about the business
BUSINESS_TITLE = re.compile(r"launch|release of|unveil|partnership|strategic (cooperation|partner)|cooperation|agreement|"
                            r"contract|\border|collaborat|joint venture|memorandum|\bMOU\b|product|capacity|plant|factory|"
                            r"production|shipment|deliver|investment in|acquisition|expansion|business update|"
                            r"operational update|operating data|key operating|\bmodel\b|customer|supplier", re.I)
PROSPECTUS_TITLE = re.compile(r"global offering|prospectus|listing by way of introduction", re.I)

KIND_NAMES = {"results": "results announcement", "update": "business / trading update",
              "inside": "inside information / profit alert", "transaction": "transaction notice",
              "circular": "transaction circular", "annual": "annual report", "interim": "interim report",
              "quarterly": "quarterly report", "prospectus": "listing prospectus"}

FILTERS = {
    "kept": "results announcements (Final / Interim / Quarterly Results); annual, interim and quarterly reports; business "
            "and trading updates; inside information and profit alerts; discloseable / major / very substantial / connected "
            "and continuing connected transactions (incl. their completion and update notices); transaction circulars; "
            "voluntary announcements filed under 'Other - Miscellaneous' whose title is about the business (launches, "
            "agreements, orders, capacity, customers); a listing prospectus (global offering)",
    "skipped": "monthly returns, next day disclosure returns, proxy forms, constitutional documents, documents on display, "
               "debt notices, pre-listing drafts; overseas regulatory announcements (copies of A-share filings); dividends, "
               "board / personnel, governance, shareholder meetings and their notices, share schemes, financing / share "
               "capital, buybacks, trading / listing admin, clarifications, litigation, board-meeting dates; procedural "
               "circulars; ESG reports; and, by title, treasury investments (wealth management), loans / guarantees / deposit "
               "services, H-share full circulation, share awards, index inclusion — never silently (reason per document)",
    "first_sync": f"{FIRST_BACK} days, plus the company's newest annual report from up to {REPORT_BACK} days back",
    "language": "the English version (HKEXnews English section); the Chinese file only when no English one exists",
    "duplicates": "a document already saved under transcripts/ by hand or by ir_pull.py (same HKEXnews file number in "
                  "its SOURCE line), or the same PDF bytes, is not saved again",
}


def parse_categories(long_text):
    """'Announcements and Notices - [Final Results / Dividend or Distribution]' -> (groups, categories).
    A document filed under two groups lists both, separated by <br/>."""
    groups, cats = [], []
    for part in htmllib.unescape(long_text or "").split("<br/>"):
        part = part.strip()
        if not part:
            continue
        group, _sep, rest = part.partition(" - [")
        groups.append(group.strip())
        cats += [c.strip() for c in rest.rstrip("]").split(" / ") if c.strip()]
    return groups, cats


def classify(groups, cats, title):
    """('keep', kind) or ('skip', reason) for one HKEXnews document."""
    cat_set = set(cats)
    t = re.sub(r"\s+", " ", title or "")
    # 1. results and periodic reports: always kept (a results title never hides a capital matter)
    if cat_set & RESULTS_CATS:
        return "keep", "results"
    if "Financial Statements/ESG Information" in groups:
        if "Annual Report" in cat_set:
            return "keep", "annual"
        if "Interim/Half-Year Report" in cat_set:
            return "keep", "interim"
        if "Quarterly Report" in cat_set:
            return "keep", "quarterly"
        return "skip", "ESG report / other financial-statement document"
    if "Listing Documents" in groups:
        return ("keep", "prospectus") if PROSPECTUS_TITLE.search(t) else ("skip", "listing document (not a prospectus)")
    for g in groups:
        if g in SKIP_GROUPS:
            return "skip", SKIP_GROUPS[g]
    # 2. meeting / despatch notices are procedural even when they name a transaction
    if any(PROCEDURAL_RE.search(c) for c in cats):
        return "skip", "procedural notice (shareholder meeting / circular despatch)"
    # 3. the business kinds, then the title checks
    kind = None
    if "Circulars" in groups:
        if not any(TRANSACTION_RE.search(c) for c in cats):
            return "skip", "procedural circular (mandates, re-election, share schemes, constitution)"
        kind = "circular"
    elif cat_set & UPDATE_CATS:
        kind = "update"
    elif cat_set & INSIDE_CATS:
        kind = "inside"
    elif any(TRANSACTION_RE.search(c) for c in cats):
        kind = "transaction"
    elif "Other - Miscellaneous" in cat_set:
        kind = "misc"
    if kind:
        for why, pat in TITLE_SKIPS:
            if re.search(pat, t, re.I):
                return "skip", why
        if kind != "misc":
            return "keep", kind
        # 'Other - Miscellaneous' beside a capital / admin category (share scheme, public float …) is that matter
        for why, pat in SKIP_CATS:
            if any(re.search(pat, c) for c in cats if c != "Other - Miscellaneous"):
                return "skip", why
        if BUSINESS_TITLE.search(t):
            return "keep", "update"
        return "skip", "miscellaneous notice (not about the business)"
    # 4. everything else: the first category that names a reason
    for why, pat in SKIP_CATS:
        if any(re.search(pat, c) for c in cats):
            return "skip", why
    return "skip", "other notice type"


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def today_hkt():
    return datetime.now(HKT).date()


def mdy(d):
    return d.strftime("%m-%d-%Y")


def new_state():
    return {"last_sync": None, "runs": [], "companies": {}, "seen": {}, "hashes": {}, "filters": FILTERS}


def universe():
    """[{name, code}] for our HKEX companies; code = the 5-digit HKEX stock code ('0700.HK' -> '00700')."""
    out = []
    for name, info in load(META, {}).items():
        if info.get("exchange") != "HKEX":
            continue
        m = re.match(r"^0*(\d{1,5})(\.HK)?$", str(info.get("ticker") or "").strip().upper())
        if m:
            out.append({"name": name, "code": m.group(1).zfill(5)})
        else:
            print(f"note: {name} has no HKEX stock code in company_metadata.json (ticker {info.get('ticker')!r}) — skipped")
    return out


_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "en,zh;q=0.8"})
_last = [0.0]


def _polite():
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


class Blocked(Exception):
    """HKEXnews answered 403 or a bot page instead of the document."""


def fetch(url, params=None, timeout=120, expect="json"):
    """GET politely with three tries and a growing pause (5 s, 15 s) on network errors, 429 and 5xx.
    `expect` = 'json' / 'pdf' / 'html': a 403 or an answer of the wrong kind (a bot page) raises Blocked."""
    for attempt in range(3):
        _polite()
        try:
            r = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5 * 3 ** attempt)
            continue
        if r.status_code == 403:
            raise Blocked(f"HTTP 403 for {url}")
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == 2:
                r.raise_for_status()
            time.sleep(5 * 3 ** attempt)
            continue
        r.raise_for_status()
        head = r.content[:200].lstrip()
        if expect == "pdf" and not head.startswith(b"%PDF"):
            raise Blocked(f"not a PDF from {url} ({head[:40]!r})")
        if expect == "json" and head[:1] not in (b"{", b"[", b"c"):          # 'c' = callback( … ) of the JSONP answer
            raise Blocked(f"not JSON from {url} ({head[:40]!r})")
        return r


def jina_text(url):
    """The text of a page or PDF through Jina Reader (the fallback when HKEXnews blocks a direct request)."""
    _polite()
    r = requests.get(JINA + url, headers={"X-Respond-With": "text"}, timeout=180)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------- the HKEXnews lists

def stock_id(co, state):
    """HKEXnews' internal stockId for a stock code (from prefix.do), remembered in sync_state.json."""
    known = state["companies"].get(co["name"], {})
    if known.get("stock_id") and known.get("code") == co["code"]:
        return known["stock_id"], known.get("hkex_name", "")
    r = fetch(PREFIX_URL, params={"callback": "callback", "lang": "EN", "type": "A", "name": co["code"],
                                  "market": "SEHK", "_": str(int(time.time() * 1000))})
    m = re.search(r"callback\((.*)\)\s*;?\s*$", r.text, re.S)
    info = json.loads(m.group(1)).get("stockInfo", []) if m else []
    hit = next((s for s in info if s.get("code") == co["code"]), None)
    if not hit:
        return None, ""
    entry = state["companies"].setdefault(co["name"], {})
    entry.update({"code": co["code"], "stock_id": hit["stockId"], "hkex_name": hit.get("name", "")})
    return hit["stockId"], hit.get("name", "")


def _search(sid, start, end, lang):
    """One list request -> the raw rows (dicts) between two dates."""
    params = {"sortDir": "0", "sortByOptions": "DateTime", "category": "0", "market": "SEHK", "stockId": str(sid),
              "documentType": "-1", "fromDate": start.strftime("%Y%m%d"), "toDate": end.strftime("%Y%m%d"),
              "title": "", "searchType": "0", "t1code": "-2", "t2Gcode": "-2", "t2code": "-2",
              "rowRange": str(ROWS), "lang": lang}
    try:
        body = fetch(SEARCH_URL, params=params).json()
    except Blocked:
        url = requests.Request("GET", SEARCH_URL, params=params).prepare().url
        text = jina_text(url)
        body = json.loads(text[text.index("{"):text.rindex("}") + 1])
    result = body.get("result")
    return json.loads(result) if isinstance(result, str) and result.strip() not in ("", "null") else []


def list_docs(sid, start, end, lang="E"):
    """Every document of one stock between two dates (both included), newest first, as clean dicts.
    When the list is longer than one request returns, the window is split in two and each half asked again."""
    raw = _search(sid, start, end, lang)
    total = int(raw[0].get("TOTAL_COUNT") or 0) if raw else 0
    if total > len(raw) and end > start:
        mid = start + (end - start) / 2
        return list_docs(sid, start, mid, lang) + list_docs(sid, mid + timedelta(days=1), end, lang)
    out = []
    for x in raw:
        link = x.get("FILE_LINK") or ""
        m = re.search(r"/(\d{8,})(_c)?\.(pdf|htm|html)$", link, re.I)
        if not m:
            continue
        dt = datetime.strptime(x["DATE_TIME"], "%d/%m/%Y %H:%M")
        groups, cats = parse_categories(x.get("LONG_TEXT"))
        out.append({"id": m.group(1), "news_id": x.get("NEWS_ID"), "url": BASE + link,
                    "title": re.sub(r"\s+", " ", htmllib.unescape(x.get("TITLE") or "")).strip(),
                    "date": dt.date().isoformat(), "time": dt.strftime("%H:%M"),
                    "groups": groups, "cats": cats, "long_text": htmllib.unescape(x.get("LONG_TEXT") or ""),
                    "file_type": (x.get("FILE_TYPE") or "").upper(), "size": x.get("FILE_INFO") or "",
                    "lang": "zh" if m.group(2) else "en"})
    return out


def is_chinese_stub(row):
    """The English list's placeholder for a document published only in the Chinese section."""
    return row["file_type"] == "HTM" and row["size"].upper().startswith(("1KB", "0KB")) and "Chinese section" in row["title"]


def chinese_version(sid, row):
    """The Chinese file behind an English stub: the lang=ZH row of the same day whose file number is the stub's
    minus one (how HKEXnews numbers them), else the one released at the same minute."""
    day = date.fromisoformat(row["date"])
    zh = [r for r in list_docs(sid, day, day, lang="ZH") if r["url"].lower().endswith(".pdf")]
    want = str(int(row["id"]) - 1).zfill(len(row["id"]))
    hit = next((r for r in zh if r["id"] == want), None) or next((r for r in zh if r["time"] == row["time"]), None)
    if hit:
        hit = dict(hit, groups=row["groups"], cats=row["cats"], long_text=row["long_text"], stub=row["url"])
    return hit


# ---------------------------------------------------------------- documents → text

def page_text(page):
    """One PDF page as text: lines stripped, blank lines dropped (as tdnet.py)."""
    lines = (l.strip() for l in (page.extract_text() or "").splitlines())
    return "\n".join(l for l in lines if l)


def pdf_pages(content, first=1):
    """[(page number, text)] of a PDF, every page. An image-only page and a page pypdf cannot read keep a marker,
    so a 300-page report is never lost to one bad page."""
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)        # quiet pypdf's warnings about odd but readable PDFs
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, p in enumerate(reader.pages, first):
        try:
            t = page_text(p)
        except Exception:
            t = ""
            pages.append((i, f"[page {i}: could not be read]"))
            continue
        pages.append((i, t or f"[page {i}: image only - not text]"))
    return pages


def real_text(pages):
    return sum(len(t) for _n, t in pages if not t.startswith("[page "))


def download(row):
    """(pages, how, digest) for one document. A Multi-Files entry is an .htm index of its parts: every part is read in
    order and numbered on, with a '[part …]' line before each part's first page. `how` notes a Jina fallback."""
    if row["url"].lower().endswith(".pdf"):
        parts = [(row["url"], "")]
    else:
        index = fetch(row["url"], expect="html").text
        parts = [(urljoin(row["url"], h), re.sub(r"\s+", " ", htmllib.unescape(t)).strip())
                 for h, t in re.findall(r'href="([^"]+\.pdf)"[^>]*>([^<]*)<', index, re.I)]
        if not parts:
            raise ValueError("index page lists no PDF")
    pages, how, sha = [], "", hashlib.sha256()
    for url, name in parts:
        try:
            content = fetch(url, timeout=300, expect="pdf").content
            sha.update(content)
            part = pdf_pages(content, first=len(pages) + 1)
        except Blocked:
            text = jina_text(url)                     # Jina's PDF text: one block, no page breaks
            sha.update(text.encode("utf-8"))
            part = [(len(pages) + 1, text.strip())]
            how = "text via Jina Reader (HKEXnews refused the direct download)"
        if name and len(parts) > 1:
            n, t = part[0]
            part[0] = (n, f"[part: {name} — {url}]\n{t}")
        pages += part
    return pages, how, sha.hexdigest()


# ---------------------------------------------------------------- labels

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "under",
               "upon", "via", "with", "its"}
ACRONYMS = {"HK", "PRC", "JV", "RMB", "US", "USD", "HKD", "AI", "API", "GPU", "ESG", "AGM", "EGM", "SGM", "IPO", "CSRC",
            "IT", "IC", "EV", "NAV", "CEO", "CFO", "LLM", "OEM", "ODM", "PCB", "CCL", "IDC", "MOU", "SPA", "STAR", "H", "A",
            "IDCS", "GW", "MW", "SOC", "IOT", "R&D", "B2B", "UK", "EU"}
EARNINGS_LABEL = re.compile(r" Q\d FY\d{4} \(")


def smart_title(text, names=None):
    """An ALL-CAPS HKEX title in Title Case ('POSITIVE PROFIT ALERT' -> 'Positive Profit Alert'); a mixed-case
    title is left alone. Words with digits, known acronyms and vowel-less words (KBH) stay as they are; a word of
    the company's own name takes the node's spelling (`names`: {'SMIC': 'SMIC', 'MINIMAX': 'MiniMax'})."""
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return text
    names = names or {}
    words = []
    for i, w in enumerate(text.split(" ")):
        core = re.sub(r"[^A-Za-z&]", "", w)
        if core.upper() in names:
            words.append(w.replace(core, names[core.upper()]))
        elif not core or any(ch.isdigit() for ch in w) or core.upper() in ACRONYMS or not re.search(r"[AEIOUY]", core.upper()):
            words.append(w)
        elif i > 0 and core.lower() in SMALL_WORDS:
            words.append(w.lower())
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def short_title(title, company="", n=60):
    """An English title for a label: Title Case, the first item of a numbered list, without 'Announcement of …' /
    'Voluntary Announcement', ASCII only, at most n characters, cut at a word."""
    t = re.split(r";?\s*\(2\)", title)[0]                       # '(1) A; (2) B' -> '(1) A'
    t = re.sub(r"^\s*\(1\)\s*", "", t)
    t = smart_title(re.sub(r"\s+", " ", t).strip(), {w.upper(): w for w in company.split()})
    t = re.sub(r"^(voluntary announcement|inside information( announcement)?|announcement)\s*[-–:]?\s*"
               r"((of|on|in relation to|regarding|relating to|in respect of|concerning)\s+)?(the\s+)?", "", t, flags=re.I)
    t = re.sub(r"[^\x20-\x7e]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,:;-")
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(" ,;:-(")
        if t.count("(") > t.count(")"):                         # cut inside a bracket: drop the open bracket part
            t = t[:t.rindex("(")].rstrip(" ,;:-")
    while t and t.rsplit(" ", 1)[-1].lower() in SMALL_WORDS:    # never end on 'and' / 'of'
        t = t.rsplit(" ", 1)[0] if " " in t else ""
    return t[:1].upper() + t[1:]


def period_of(title, kind, day):
    """'2025/26 ANNUAL REPORT' -> '2025/26'; 'Interim Report 2026' -> '2026'; no year -> from the release day."""
    m = re.search(r"(20\d\d)\s*/\s*(\d{2,4})", title)
    if m:
        return f"{m.group(1)}/{m.group(2)[-2:]}"
    m = re.search(r"20\d\d", title)
    if m:
        return m.group(0)
    return str(day.year - 1 if kind == "annual" else day.year)


def label_for(company, row, kind):
    day = date.fromisoformat(row["date"])
    if kind == "annual":
        return f"{company} annual report: {period_of(row['title'], kind, day)} Annual Report ({mdy(day)})"
    if kind == "interim":
        return f"{company} interim report: {period_of(row['title'], kind, day)} Interim Report ({mdy(day)})"
    if kind == "prospectus":
        return f"{company} prospectus ({mdy(day)})"
    title = short_title(row["title"], company)
    if len(title) < 8:
        title = "release " + row["id"]
    word = {"circular": "HKEX circular", "quarterly": "quarterly report"}.get(kind, "HKEX announcement")
    label = f"{company} {word}: {title} ({mdy(day)})"
    # a title such as '… Q2 FY2026' would read as an earnings-call label to the pipelines — write 'fiscal'
    return re.sub(r" (Q\d) FY(\d{4}) \(", r" \1 fiscal \2 (", label) if EARNINGS_LABEL.search(label) else label


# ---------------------------------------------------------------- the _extract of a long report

# Section names an HK report prints as a running header on every page (or as a heading on its first page).
KEEP_SECTIONS = [
    ("financial highlights", r"financial (highlights|summary)|five-year|key (financial )?(figures|data|indicators)|"
                             r"principal financial indicators|(results|performance) highlights"),
    ("chairman / CEO statement", r"chairman'?s?’?s? (statement|letter|message)|letter to (the )?shareholders|"
                                 r"message from the (chairman|ceo|board)|ceo'?s?’?s? (statement|review|letter|message)|"
                                 r"chief executive'?s?’?s? (statement|review|officer'?s?’?s? review)"),
    ("MD&A", r"management'?s?’?s? discussion|discussion and analysis|business review|financial review|"
             r"operation(al|s)? review|operating review|review of operations"),
    ("prospectus: summary / business / financial information / future plans",
     r"^(summary|business|our business|financial information|future plans and use of proceeds)$"),
]
DROP_SECTIONS = re.compile(r"directors'?’?s? report|report of the directors|corporate governance|environmental,? social|"
                           r"sustainability|\besg\b|independent auditor|auditor'?’?s report|report on review|"
                           r"senior management|biographi|profiles? of (the )?directors|corporate information|definitions|"
                           r"glossary|notes to the|consolidated statement|condensed consolidated|statements? of "
                           r"(profit|financial position|changes|cash|comprehensive)|other information|shareholder information|"
                           r"information for shareholders|risk factors|industry overview|regulatory overview|^regulations$|"
                           r"history|^share capital$|underwriting|structure of the (global )?offering|^appendix|"
                           r"accountants'?’? report|statutory and general|significant events|changes in shares|"
                           r"corporate profile|connected transactions$|relationship with", re.I)
# Items worth a page anywhere outside the kept sections (the Directors' report, the notes, …).
ITEMS = [
    ("major customers / suppliers", r"(five|5) largest (customers|suppliers)|largest (customer|supplier)|"
                                    r"major customers and suppliers|top (five|5) (customers|suppliers)"),
    ("segment information", r"segment (information|results|revenue)|operating segments?|reportable segments?"),
    ("capex / capital commitments", r"capital commitments|capital expenditures?"),
    ("R&D", r"research and development (expenses|costs|expenditures?|investment)"),
    ("connected transactions (caps / amounts)", r"annual caps?\b"),
    ("related-party transactions", r"related part(y|ies) transactions"),
    ("capacity / utilisation", r"production capacity|utili[sz]ation rate|capacity utili[sz]ation|monthly capacity|"
                               r"wafer shipments|installed capacity"),
    ("orders / backlog", r"\bbookings\b|\bbacklog\b|order book|orders on hand|new orders"),
]


# Some reports (Hua Hong) put their business and financial review INSIDE the Directors' report, under a plain
# sub-heading; it runs until the report's routine items begin (results, dividends, reserves …).
DIRECTORS_REPORT = re.compile(r"directors'?’?s? report|report of the directors", re.I)
REVIEW_START = re.compile(r"^(business review|management'?’?s? discussion and analysis|management discussion and analysis|"
                          r"financial review|operational review|operating review|review of operations)$", re.I)
# (only headings that never double as a table row label: 'Property, plant and equipment' or 'Share capital' do)
REVIEW_END = re.compile(r"^(results( and (appropriations|dividends?))?|(final |interim |special )?dividends?( policy)?|"
                        r"distributable reserves|(charitable )?donations|equity-linked agreements|"
                        r"share (option|award) schemes?|pre-emptive rights|permitted indemnity( provisions?)?|"
                        r"major customers and suppliers|(five-year )?financial summary)$", re.I)


def _section_of(line):
    """('keep', name) / ('drop', None) / ('drop', "directors' report") / None for one short header line."""
    clean = re.sub(r"\(continued\)|\bsection\s+[\divx]+\b|^[\divx]+\s*[.、]?\s+|\s+\d+$|^\d+\s+", " ", line, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip(" |•·-–—:").lower()
    if not clean or len(clean) > 90:
        return None
    for name, pat in KEEP_SECTIONS:
        if re.search(pat, clean, re.I):
            return "keep", name
    if DIRECTORS_REPORT.search(clean):
        return "drop", "directors' report"
    if DROP_SECTIONS.search(clean):
        return "drop", None
    return None


def report_extract(pages):
    """The `_extract` body of a long report -> (text, located, pages kept, warning).
      A. every page of a kept section — financial highlights, the chairman's / CEO's statement, the management
         discussion and analysis (business / financial review); in a prospectus its Summary, Business, Financial
         Information and Future Plans sections — read from the running header each HK report prints at the top
         (or bottom) of a page, else from the section's heading on its first page; a section runs until the next one;
      B. any other page (Directors' report, notes, …) that holds an ITEMS hit: major customers / suppliers, segment
         information, capex / capital commitments, R&D, connected-transaction caps, related-party transactions,
         capacity, orders — plus the next page when the hit sits low on the page (its table usually continues).
    Table-of-contents pages are ignored. `warning` says why no extract could be made."""
    text_of = dict(pages)
    lines = {n: (t or "").splitlines() for n, t in pages}
    toc = set()                       # a contents page: many section names, most with a page number beside them
    for n, ls in lines.items():
        named = [l for l in ls if len(l) <= 120 and _section_of(l)]
        numbered = [l for l in named if re.match(r"^\s*\d{1,3}\b", l) or re.search(r"\b\d{1,3}\s*$", l)]
        if len(named) >= 5 and len(numbered) >= 3 and len(text_of[n]) < 4000:
            toc.add(n)
    keep, notes, section, in_review = {}, {}, None, False
    for n in sorted(lines):
        if n in toc:
            continue
        ls = lines[n]
        found = None
        for l in ls[:4] + ls[-3:]:                          # the running header / footer
            found = _section_of(l) if len(l) <= 100 else None
            if found:
                break
        if not found:                                       # an ALL-CAPS heading line on the section's first page
            for l in ls:
                if len(l) <= 60 and re.fullmatch(r"[A-Z0-9’'&,.:\-() ]+", l.strip()):
                    found = _section_of(l)
                    if found:
                        break
        if found:
            if found != section:
                in_review = False                           # a new section: a review sub-section never carries over
            section = found
        if section and section[0] == "keep":
            keep[n] = section[1]
        elif section == ("drop", "directors' report"):      # a review sub-section inside the Directors' report
            on_page = in_review
            for l in ls:
                s = l.strip()
                if len(s) > 45:
                    continue
                if REVIEW_START.match(s):
                    in_review = on_page = True
                elif in_review and REVIEW_END.match(s):
                    in_review = False
            if on_page:
                keep[n] = "business / financial review inside the Directors' report"
    hits = {}
    for n in sorted(lines):
        if n in toc or n in keep:
            continue
        text = text_of[n] or ""
        found = [(name, m) for name, pat in ITEMS for m in [re.search(pat, text, re.I)] if m]
        if not found:
            continue
        hits[n] = ", ".join(dict.fromkeys(name for name, _m in found))
        last = max(m.start() for _name, m in found)
        nxt = n + 1
        if last > 0.6 * len(text) and nxt in lines and nxt not in keep and nxt not in toc:
            hits.setdefault(nxt, f"continued from page {n}")
    for n, why in hits.items():
        keep.setdefault(n, None)
        notes[n] = why
    if not keep:
        return "", "", 0, "no MD&A / review section and no key item found"
    parts, kept_text, prev = [], {}, None
    for n in sorted(keep):
        body = (text_of[n] or "").strip()
        if not body or body.startswith("[page "):
            continue
        kept_text[n] = body
        note = keep[n] if keep[n] and keep[n] != prev else (f"outside the review sections: {notes[n]}" if n in notes else "")
        prev = keep[n]
        parts.append(f"==== page {n}" + (f" ({note})" if note else "") + f" ====\n{body}\n")
    found, absent = [], []
    for name, pat in ITEMS:
        where = [n for n, body in kept_text.items() if re.search(pat, body, re.I)]
        if where:
            found.append(f"{name} p{', p'.join(str(n) for n in where[:6])}" + (" …" if len(where) > 6 else ""))
        else:
            absent.append(name)
    if not any(v for v in keep.values()):
        found.insert(0, "no review section recognised (key-item pages only)")
    located = "; ".join(found) + (f". Not in the extract: {', '.join(absent)}" if absent else "")
    return "\n".join(parts), located[:900], len(kept_text), None


# ---------------------------------------------------------------- saving

def saved_elsewhere():
    """{HKEXnews file number: file} for documents already saved under transcripts/ outside this collector — by hand
    or by ir_pull.py — read from each file's SOURCE line (its first 2,500 characters; ~2 s for 7,500 files)."""
    found = {}
    for f in sorted((ROOT / "transcripts").rglob("*.txt")):
        if OUT_DIR in f.parents:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            head = fh.read(2500)
        for num in re.findall(r"hkexnews\.hk/listedco/listconews/\w+/\d{4}/\d{4}/(\d{8,})(?:_c)?\.(?:pdf|htm)", head, re.I):
            found.setdefault(num, f.relative_to(ROOT).as_posix())
    return found


NOTES = {
    "results": ("# NOTE: NOT a transcript — the company's own HKEX results announcement (statutory, filed on HKEXnews).",
                "#       Facts, segment figures and the company's own outlook; management commentary attributed. Entries in",
                "#       English (enrich skill §2, §8); amounts in the filing's currency and unit, no conversion."),
    "update": ("# NOTE: NOT a transcript — a company-issued HKEX announcement (business / trading update). Facts, company",
               "#       forecasts and plans only; attribute claims; every entry in English (enrich skill §2, §8)."),
    "inside": ("# NOTE: NOT a transcript — a company-issued HKEX inside-information / profit-alert announcement. Facts and",
               "#       the company's own estimates (keep the hedge: 'expects', 'not less than'); entries in English (§2, §8)."),
    "transaction": ("# NOTE: NOT a transcript — a company-issued HKEX transaction notice. Operating facts only: the counterparty,",
                    "#       what is supplied or built (products / services; a JV's fab, capacity, products), annual caps and",
                    "#       historical amounts of continuing connected transactions (= supply relationships). Never the price",
                    "#       of an acquisition or financing terms (§2). Entries in English."),
    "circular": ("# NOTE: NOT a transcript — the company's shareholder circular on a transaction (HKEX). Operating facts only:",
                 "#       counterparty, products / services, caps and historical amounts, the target's business; never",
                 "#       valuation, financing terms or the voting procedure (§2). Entries in English."),
    "report": ("# NOTE: company statutory report — NOT a transcript. Facts and the company's own statements, enriched like a",
               "#       DART periodic report (enrich skill §4 slot table: statutory statements — the ONE best entry per slot).",
               "#       Every entry in English (§8). A named major customer / supplier that is a node -> a contract on the",
               "#       edge; unnamed shares ('largest customer 23%') stay on the company's own quarterly_data."),
    "prospectus": ("# NOTE: NOT a transcript — the company's listing prospectus (HKEX). Facts on its business, customers,",
                   "#       suppliers, capacity, plans; the Industry Overview is a third-party consultant's report — context",
                   "#       only, never a company fact (§2). Never offering / financing terms. Entries in English."),
}


def save_doc(co, sid, hkex_name, row, kind, state, elsewhere):
    """Download, read and save one document (+ its extract). Returns (skip reason or None, label or None).
    A reason starting with 'later:' is a passing failure: the document is tried again next run."""
    company = co["name"]
    listed_id = row["id"]                       # the English list's file number: the key in sync_state / pending
    if listed_id in elsewhere:
        return f"already saved by hand: {elsewhere[listed_id]}", None
    try:
        if is_chinese_stub(row):
            zh = chinese_version(sid, row)
            if not zh:
                return "later: Chinese-only document, its Chinese file not found yet", None
            row = zh
        pages, how, digest = download(row)
    except (requests.RequestException, ValueError, Blocked) as exc:
        return f"later: download failed ({exc.__class__.__name__})", None
    except Exception as exc:                                      # an encrypted or broken PDF
        return f"pdf could not be read ({exc.__class__.__name__})", None
    if digest in state["hashes"]:
        return f"same file as {state['hashes'][digest]}", None
    if real_text(pages) < MIN_TEXT:
        state["hashes"][digest] = f"image-only PDF ({row['id']})"
        return "image-only PDF (no text layer)", None

    label = label_for(company, row, kind)
    taken = {s.get("label"): i for i, s in state["seen"].items() if s.get("label")}
    if label in taken and taken[label] != listed_id:                 # two documents, one title, one day
        label = label.replace(f" ({mdy(date.fromisoformat(row['date']))})",
                              f" [{row['id']}] ({mdy(date.fromisoformat(row['date']))})")
    stem = f"{slug(company)}_{row['date']}_{row['id']}"
    full_path = OUT_DIR / f"{stem}.txt"
    extract_path = OUT_DIR / f"{stem}_extract.txt"
    lang = ("English version (HKEXnews English section)" if row["lang"] == "en" else
            f"Chinese original — no English version on HKEXnews (English stub {row.get('stub', '?')}); write the entries in English")
    if how:
        lang += f"; {how}"
    note = NOTES["report" if kind in ("annual", "interim", "quarterly") else kind]
    header = [
        f"SOURCE: {row['url']}",
        f"TITLE: {row['title']}",
        f"DOCUMENT TYPE: {KIND_NAMES[kind]} (HKEXnews headline category: {row['long_text']})",
        f"DATE: {row['date']} {row['time']} HKT   (HKEXnews release time; the label date)",
        f"COMPANY: {company} (HKEX {co['code']}, listed as {hkex_name})",
        f"LANGUAGE: {lang}",
        *note,
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queued, reads = full_path, "read it whole"
    if kind in ("annual", "interim", "quarterly", "prospectus") and len(pages) > EXTRACT_MIN_PAGES:
        body, located, kept, warning = report_extract(pages)
        if warning:
            reads = f"no extract ({warning}) — read the whole document"
            print(f"  {company}: {reads}")
        else:
            extract_path.write_text("\n".join(header + [
                f"# EXTRACT: {kept} of {len(pages)} pages — financial highlights, the chairman's / CEO's statement and the",
                "#          management discussion and analysis whole, and the pages elsewhere with major customers /",
                "#          suppliers, segment information, capex, R&D, connected-transaction caps, related parties,",
                f"#          capacity or orders. The whole document: {full_path.relative_to(ROOT).as_posix()}",
                f"# LOCATED: {located}",
                f"# source label: {label}",
                ""]) + body, encoding="utf-8")
            queued = extract_path
            reads = "the enricher reads the _extract file beside it; this file is what verify_graph.py checks"
    full_path.write_text("\n".join(header + [f"# PAGES: {len(pages)} — the whole document, page by page ({reads})",
                                             f"# source label: {label}", ""])
                         + "".join(f"==== page {n} ====\n{t}\n" for n, t in pages), encoding="utf-8")
    state["hashes"][digest] = label
    pending = load(PENDING, [])
    entry = {"kind": "report" if kind in ("annual", "interim", "quarterly") else kind, "company": company,
             "label": label, "file": queued.relative_to(ROOT).as_posix(), "date": row["date"], "id": listed_id,
             "category": KIND_NAMES[kind], "title": row["title"], "pages": len(pages)}
    if queued != full_path:
        entry["full"] = full_path.relative_to(ROOT).as_posix()
    pending.append(entry)
    save(PENDING, pending)
    print(f"  saved {label}  ({len(pages)} pages)")
    return None, label


# ---------------------------------------------------------------- sync

def sync(since=None, companies=None, budget=BUDGET_MIN):
    state = load(STATE, new_state())
    for k, v in new_state().items():
        state.setdefault(k, v)
    state["filters"] = FILTERS
    ours = universe()
    if companies:
        missing = set(companies) - {c["name"] for c in ours}
        if missing:
            sys.exit(f"{sorted(missing)} not HKEX companies in company_metadata.json")
        ours = [c for c in ours if c["name"] in companies]
    started, today = time.time(), today_hkt()
    elsewhere = saved_elsewhere()
    totals = {"listed": 0, "saved": 0, "skipped": 0, "later": 0, "failed": 0}
    reasons, out_of_time = {}, False
    for co in ours:
        name = co["name"]
        known = state["companies"].get(name, {})
        first_look = since is None and not known.get("last_sync")
        if since:
            start = since
        elif not first_look:
            start = date.fromisoformat(known["last_sync"][:10]) - timedelta(days=RESYNC_OVERLAP)
        else:
            start = today - timedelta(days=FIRST_BACK)
        # a document that failed for a passing reason is listed again, however old
        later = [s["date"] for s in state["seen"].values() if s.get("company") == name
                 and str(s.get("status", "")).startswith("later")]
        if later:
            start = min(start, date.fromisoformat(min(later)))
        try:
            sid, hkex_name = stock_id(co, state)
            if not sid:
                print(f"{name:30s} stock code {co['code']} not found on HKEXnews — skipped")
                totals["failed"] += 1
                continue
            rows = list_docs(sid, today - timedelta(days=REPORT_BACK) if first_look else start, today)
        except (requests.RequestException, Blocked, ValueError) as exc:     # one company's failure must not stop the run
            print(f"  {name}: list failed ({exc.__class__.__name__}: {str(exc)[:100]}) — retried next run")
            totals["failed"] += 1
            continue
        # first look: the window, plus the newest annual report before it
        in_window = [r for r in rows if r["date"] >= start.isoformat()]
        if first_look:
            older_reports = [r for r in rows if r["date"] < start.isoformat()
                             and classify(r["groups"], r["cats"], r["title"]) == ("keep", "annual")]
            have_annual = any(classify(r["groups"], r["cats"], r["title"]) == ("keep", "annual") for r in in_window)
            if older_reports and not have_annual:
                in_window.append(max(older_reports, key=lambda r: (r["date"], r["time"])))
        totals["listed"] += len(in_window)
        saved_now = 0
        for row in sorted(in_window, key=lambda r: (r["date"], r["time"], r["id"])):
            prev = str(state["seen"].get(row["id"], {}).get("status", ""))
            if prev and not prev.startswith("later"):
                continue
            verdict, what = classify(row["groups"], row["cats"], row["title"])
            label = None
            if verdict == "skip":
                why = what
            elif (time.time() - started) / 60 > budget:
                out_of_time = True
                break
            else:
                why, label = save_doc(co, sid, hkex_name, row, what, state, elsewhere)
            status = "saved" if why is None else (why if why.startswith("later") else "skip:" + why)
            state["seen"][row["id"]] = {"company": name, "date": row["date"], "time": row["time"],
                                        "title": row["title"][:200], "categories": row["long_text"][:200],
                                        "kind": what if verdict == "keep" else None, "status": status,
                                        **({"label": label} if label else {})}
            if why is None:
                saved_now += 1
                totals["saved"] += 1
            elif why.startswith("later"):
                totals["later"] += 1
                print(f"  hold {name} {row['date']} {row['id']}: {why}")
            else:
                totals["skipped"] += 1
                key = "duplicate (saved by hand / same file)" if why.startswith(("already saved", "same file")) else why
                reasons[key] = reasons.get(key, 0) + 1
                if verdict == "keep":
                    print(f"  skip {name} {row['date']} {row['id']}: {why}")
            save(STATE, state)                                   # after every document, so an interrupted run resumes
        if out_of_time:
            print(f"  run-time budget of {budget} min used up during {name}: the rest waits for the next run")
            save(STATE, state)
            break
        entry = state["companies"].setdefault(name, {})
        entry.setdefault("first_sync", today.isoformat())
        entry.update({"code": co["code"], "last_sync": datetime.now(HKT).strftime("%Y-%m-%d %H:%M"),
                      "since": start.isoformat()})
        print(f"{name:30s} since {start}: {len(in_window)} document(s) listed, {saved_now} saved")
        save(STATE, state)
    if not companies and not out_of_time:
        state["last_sync"] = today.isoformat()
    state["runs"].append({"at": datetime.now(HKT).strftime("%Y-%m-%d %H:%M"),
                          "since": since.isoformat() if since else "per company",
                          "companies": companies or "all", **totals, "out_of_time": out_of_time,
                          "minutes": round((time.time() - started) / 60, 1),
                          "skip_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1]))})
    save(STATE, state)
    print(f"\nHKEXnews: {totals['listed']} documents listed, {totals['saved']} saved, {totals['skipped']} skipped, "
          f"{totals['later']} held for the next run, {totals['failed']} company list(s) failed")
    if reasons:
        print("skipped: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    print(f"queue now {len(load(PENDING, []))} (`python hkex.py pending`)")


# ---------------------------------------------------------------- queue commands

def mark_done(rows, why=None):
    state = load(STATE, new_state())
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state["seen"].setdefault(r["id"], {"company": r["company"], "date": r["date"]})["status"] = stamp
    save(STATE, state)


def status(company=None):
    """Every document seen for our companies (optionally one company) with its state."""
    state = load(STATE, new_state())
    rows = sorted(((s.get("date", ""), s.get("company", "?"), doc_id, s) for doc_id, s in state["seen"].items()
                   if not company or s.get("company") == company))
    for d, co, doc_id, s in rows:
        print(f"{d}  {co:30s} {doc_id:14s} {str(s.get('status'))[:50]:50s} {s.get('title', '')[:70]}")
    print(f"{len(rows)} documents seen")
    for name, info in sorted(state["companies"].items()):
        if not company or name == company:
            print(f"  {name:30s} HKEX {info.get('code')} stockId {info.get('stock_id')} ({info.get('hkex_name')}) "
                  f"last sync {info.get('last_sync') or 'never'}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help=f"YYYY-MM-DD; default: {RESYNC_OVERLAP} days before the company's last sync, or "
                                   f"(first sync) {FIRST_BACK} days + its newest annual report")
    s.add_argument("--company", action="append", help="repeatable; default: every HKEX company")
    s.add_argument("--budget", type=float, default=BUDGET_MIN, help="run-time budget in minutes")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--market", help="accepted for symmetry with the other collectors; every row here is CN")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a document yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company, args.budget)
    elif args.cmd == "pending":
        meta = load(META, {})
        rows = [r for r in load(PENDING, []) if (not args.company or r["company"] == args.company)
                and (not args.market or market_of(meta.get(r["company"], {}).get("exchange")) == args.market)]
        for r in rows:
            print(f"{r['date']}  {r['kind']:11s} {r['company']:24s} {r['label']:85s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit('give --label "<label>" (one document) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)


if __name__ == "__main__":
    main()
