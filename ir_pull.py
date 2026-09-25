"""
ir_pull.py -- company IR press releases -> transcripts/ir/*.txt  (the `enrich ir` queue)

Why this exists
---------------
Some company news never reaches an earnings call or a transcript: product launches at a trade
show (ECOC, OFC, Computex), partnership announcements, design wins. The user's source rule
(2026-09-24) is: when there is no transcript, use ONLY company-issued documents -- never an
article about them. Almost every IR site publishes its press releases as a free RSS feed, so
this script reads those feeds directly from the company. No API key, no quota, no model.

    python ir_pull.py discover                 # find the IR RSS feed for companies that lack one
    python ir_pull.py discover --company Lumentum
    python ir_pull.py add "Sivers Semiconductors" https://.../rss   # register a feed by hand
    python ir_pull.py add "Tokyo Electron" https://www.tel.com/news/ --page --link-re "/news/\d{4}/"
                                               # no RSS: read the HTML list of releases instead
    python ir_pull.py feeds                    # list registered feeds
    python ir_pull.py sync                     # new releases from every feed (last 30 days)
    python ir_pull.py sync --since 2026-09-01 --company Marvell
    python ir_pull.py fetch <release-url> --company Marvell   # one release by hand
    python ir_pull.py pending                  # the enrichment queue
    python ir_pull.py done --label "<label>"   # remove ONE row after enriching it
    python ir_pull.py done --all               # clear the whole queue (rarely what you want)

Files
-----
    ir/feeds.json        company -> {"feed": url, "how": "discover"|"manual", "checked": date}
    ir/sync_state.json   runs[] (when, since, feeds read, saved) + seen{url: saved|skip:<why>|fail:<why>}
    ir/pending.json      rows {kind:"ir", company, label, file, url, title, date}
    transcripts/ir/<company>_<yyyy-mm-dd>_<title>.txt   verbatim body + header

Every saved file carries a NOT-a-transcript note and a `# source label:` line, e.g.
    # source label: Lumentum press release: Lumentum to Demonstrate DWDM ELSFP Laser Module (09-21-2026)
so verify_graph.py resolves the label to the file, and the label itself tells anyone reading the
graph that the fact came from a company press release, not a call.

What is skipped (recorded in sync_state.json with the reason, never silently):
    dividends, "to present / participate / host" event notices, results-date and webcast notices,
    annual-meeting and proxy notices, and -- for US-listed companies -- the quarterly results
    release itself (it is already filed as an 8-K exhibit and read by edgar_pull.py, and the call
    transcript covers it).
"""

import argparse
import html
import io
import json
import os
import re
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

try:
    from curl_cffi import requests      # a real Chrome TLS fingerprint -- several IR hosts block plain requests
except ImportError:
    sys.exit("pip install curl_cffi  (listed in requirements.txt)")

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
FEEDS = ROOT / "ir" / "feeds.json"
STATE = ROOT / "ir" / "sync_state.json"
PENDING = ROOT / "ir" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "ir"

US_EXCHANGES = {"NASDAQ", "NYSE", "NYSE American", "AMEX"}

# Title patterns that are notices, not news. (reason shown in sync_state.json)
NOISE = [
    (r"\bdividend", "dividend"),
    (r"\bto (present|participate|speak|host|webcast|attend)\b|\bat (upcoming )?investor conferences?\b", "event notice"),
    (r"\b(to report|to announce|will report|will announce|schedules?|sets date|date (for|of))\b.*\b(results|earnings|call)\b", "results-date notice"),
    (r"\bconference call\b|\bwebcast\b", "call/webcast notice"),
    # shareholder meetings only -- "data at 2026 AANEM Annual Meeting" is a medical congress, not a notice
    (r"\bannual general meeting\b|\bannual meeting of (share|stock)holders\b|\b(share|stock)holders['’]? meeting\b"
     r"|\bproxy\b|\bAGM\b", "shareholder-meeting notice"),
    # added 2026-09-25 after the first week-long run (kept narrow: a product "certified" by TSMC is NOT caught)
    (r"\binducement grants?\b|\bequity (award|grant)s?\b", "equity-grant notice"),
    (r"\bgreat place to work\b|\bbest places? to work\b|\bworkplace award\b", "employer award"),
    (r"\bannounces sponsorship\b|\bsponsorship and participation\b", "sponsorship notice"),
    (r"\bjoins? (the )?[A-Z][\w&.\- ]{0,40}\bindex\b|\badded to (the )?[\w&.\- ]{0,40}\bindex\b", "index inclusion"),
    (r"\bhonou?rs\b.*\b(first responders|veterans|community)\b", "community event"),
    (r"\bhosts?\b.*\b(technology|investor|analyst) sessions?\b", "event notice"),
    (r"\btransaction in own shares\b", "buyback notice"),       # Shell files one every trading day
    # Japanese / Chinese / Korean list pages (added 2026-09-25 with the list-page mode)
    (r"配当|股利|股息|배당", "dividend"),
    (r"株主総会|股東(常)?會|주주총회", "shareholder-meeting notice"),
    (r"決算説明会|法人說明會|法說會|기업설명회|IR\s*개최", "event notice"),
    (r"自己株式の取得|自己株式取得|庫藏股|자기주식|자사주", "buyback notice"),
    (r"株式報酬|ストックオプション|新株予約権|員工認股|주식매수선택권", "equity-grant notice"),
]
# Quarterly/annual FINANCIAL results only -- not "targets"/"outlook", and not clinical results
# ("Vertex Announces Positive Results From Phase 2b ..." is news, not an earnings release).
RESULTS = re.compile(r"\bfinancial results\b|\b(quarter|fiscal|full[- ]year|year[- ]end|Q[1-4])\b.*\bresults\b", re.I)

# Where a release body ends on most IR sites (the "About <company>" boilerplate onward).
END_MARKERS = re.compile(r"^(About [A-Z]|Forward[- ]Looking Statements|Safe Harbor|Cautionary|Media Contacts?|"
                         r"Investor (Relations )?Contacts?|Contact Information|Contacts?:|View source version|Source:)")
CHROME = {"Download", "(opens in new window)", "Download as PDF", "View All News", "Print", "Share", "Email Alerts"}


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    """Write to a temp file, then swap it in. On Windows another process (OneDrive, antivirus, the
    indexer) sometimes holds the file for a moment -> OSError Errno 22; wait and retry instead of
    crashing mid-sync. The swap also means a crash can never leave a half-written JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    for attempt in range(6):
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == 5:
                raise
            time.sleep(1 + attempt)


def slug(name):
    """'Applied Materials' -> 'appliedmaterials' (same rule as av.py / dart.py)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def ascii_text(s):
    """Straighten quotes/dashes and drop (R)/TM so labels and headers stay ASCII."""
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-").replace(" ", " "))
    s = re.sub(r"[®™©]", "", s)
    return s.encode("ascii", "ignore").decode()


_local = threading.local()
INSECURE_HOSTS = set()      # filled from ir/feeds.json entries with "insecure_tls": true (see get())


def _session():
    """One Chrome-fingerprint session per thread (discover runs several companies in parallel)."""
    if not hasattr(_local, "s"):
        _local.s = requests.Session(impersonate="chrome")
    return _local.s


def get(url, tries=3, timeout=40):
    # Some feeds list their releases as http:// links (AEP) while the server only answers on https;
    # a few company sites answer ONLY on http (TFC Optical). Try https first, then the http original.
    if url.startswith("http://"):
        return _get("https://" + url[len("http://"):], tries, timeout) or _get(url, tries, timeout)
    return _get(url, tries, timeout)


def _get(url, tries, timeout):
    for i in range(tries):
        try:
            # verify=False only for hosts registered with "insecure_tls" (a broken certificate chain on
            # the company's own site, e.g. Zhen Ding); everything else is fetched with normal checks
            r = _session().get(url, timeout=timeout, verify=urlparse(url).netloc not in INSECURE_HOSTS)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 404, 410):
                return None
        except Exception:
            pass
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return None


def public_companies():
    meta = load(META, {})
    return {name: info for name, info in meta.items() if info.get("status") == "public"}


# ---------------------------------------------------------------- RSS

def parse_feed(xml):
    """Return [{title, link, date}] from an RSS 2.0 or Atom feed."""
    items = []
    for block in re.findall(r"<item\b.*?</item>|<entry\b.*?</entry>", xml, re.S):
        def tag(t):
            m = re.search(r"<%s[^>]*>(.*?)</%s>" % (t, t), block, re.S)
            return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
        link = tag("link") or (re.search(r'<link[^>]+href="([^"]+)"', block) or [None, ""])[1]
        raw_date = tag("pubDate") or tag("published") or tag("updated")
        if not raw_date:                               # namespaced dates: <a10:updated>, <dc:date> (UMC)
            nm = re.search(r"<\w+:(?:updated|date|published)[^>]*>(.*?)</", block, re.S)
            raw_date = nm.group(1).strip() if nm else ""
        try:
            d = parsedate_to_datetime(raw_date).date()
        except Exception:
            try:
                d = datetime.fromisoformat(raw_date[:10]).date()
            except Exception:
                d = None
        # full text some feeds carry (WordPress content:encoded) -- used when the page itself is JS-rendered
        content = tag("content:encoded") or (tag("content") if "<entry" in block[:10] else "")
        # some feeds escape twice ("&amp;lsquo;"), so unescape the title once more
        items.append({"title": re.sub(r"\s+", " ", html.unescape(tag("title"))), "link": link, "date": d,
                      "content": content})
    return items


def prose_ok(lines, title):
    """Did we get the ARTICLE, or only page furniture? A JS-rendered page (SK hynix newsroom) leaves
    just menus and 'related content' headlines -- long enough, but no sentences. Require a minimum
    length AND at least two sentence endings (. ! ? 。 -- Korean sentences end in '다.')."""
    text = " ".join(lines)
    ends = len(re.findall(r"[.!?。！？](?=\s|$|[\"'”’）)」])", text))
    return len(text) >= (250 if mostly_ascii(title) else 120) and ends >= 2


def channel_title(xml):
    m = re.search(r"<title[^>]*>(.*?)</title>", xml, re.S)
    return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""


# ---------------------------------------------------------------- list pages (sites without RSS)
#
# Many Asian and European IR sites have no RSS feed -- only an HTML "news releases" list. For those,
# ir/feeds.json holds {"kind": "page", "feed": <list page url>, "link_re": <regex>}, where link_re
# matches the URL of ONE release on that site (found and tested per company, never guessed at run
# time). Every link on the list page that matches is a release. Its title is the link text; its
# date comes from the URL, else from the list text beside the link, else from the release page.

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DATE_YMD = re.compile(r"(20\d\d)\s?[-/.年]\s?(\d{1,2})\s?[-/.月]\s?(\d{1,2})日?")          # 2026-09-22, 2026.09.22, 2026年9月22日
DATE_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)", re.I)
DATE_MDY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)", re.I)
DATE_YMON = re.compile(r"\b(20\d\d)\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b", re.I)  # 2026 Sep 22
DATE_NUM = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-]|\s+)(20\d\d)\b")                # 09/22/2026, 22.09.2026, 22-09-2026, 08.05 2026
DATE_COMPACT = re.compile(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)")                           # 20260922 inside a URL
GENERIC_LINK_TEXT = {"read more", "more", "learn more", "details", "view", "view more", "more info", "more information",
                     "download", "pdf", "詳細", "詳細はこちら", "자세히 보기", "더보기", "詳情", "更多"}


def _date(y, m, d):
    try:
        out = date(int(y), int(m), int(d))
    except ValueError:
        return None
    return out if date(2000, 1, 1) <= out <= date.today() + timedelta(days=1) else None


def find_dates(text, order=None):
    """Every date written in `text`, in the order they appear.
    `order` = "mdy" or "dmy" also reads 09/22/2026-style dates. Those are ambiguous (US vs Europe),
    so they count only when the feed entry says which way round that site writes them."""
    found = []
    for m in DATE_YMD.finditer(text):
        found.append((m.start(), _date(m.group(1), m.group(2), m.group(3))))
    for m in DATE_DMY.finditer(text):
        found.append((m.start(), _date(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1))))
    for m in DATE_MDY.finditer(text):
        found.append((m.start(), _date(m.group(3), MONTHS[m.group(1)[:3].lower()], m.group(2))))
    for m in DATE_YMON.finditer(text):
        found.append((m.start(), _date(m.group(1), MONTHS[m.group(2)[:3].lower()], m.group(3))))
    if order in ("mdy", "dmy"):
        for m in DATE_NUM.finditer(text):
            a, b = m.group(1), m.group(2)
            found.append((m.start(), _date(m.group(3), a, b) if order == "mdy" else _date(m.group(3), b, a)))
    return [d for _, d in sorted(found, key=lambda x: x[0]) if d]


def url_date(link):
    """A date written into the release URL itself (/2026/09/22/, 2026-09-22, 20260922)."""
    d = find_dates(link)
    if d:
        return d[0]
    m = DATE_COMPACT.search(urlparse(link).path)
    return _date(*m.groups()) if m else None


def text_of(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def strip_dates(title):
    """List links often carry the date inside the link text ("2026/09/10 TSMC August Revenue");
    the release page's headline does not, so cut a date off the start or end of the title."""
    t = title.strip()
    for pat in (DATE_YMD, DATE_DMY, DATE_MDY, DATE_YMON, DATE_NUM):
        m = pat.match(t)
        if m:
            t = t[m.end():].lstrip(" |:-–—").strip()
        tail = list(pat.finditer(t))
        if tail and tail[-1].end() >= len(t.rstrip(" )]")) and tail[-1].start() > 0:
            t = t[:tail[-1].start()].rstrip(" |:-–—([").strip()
    return t


def parse_listing(page, base, link_re, order=None, title_strip_re=None):
    """Return [{title, link, date}] from an HTML list of releases, in page order.

    A list entry usually shows its date either just BEFORE the headline link or just AFTER it.
    We first check which layout the page uses (most entries have a date before their link?), then
    read every entry the same way -- so one entry can never borrow the date of its neighbour.
    """
    pat = re.compile(link_re)
    anchors = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", page, re.S | re.I):
        h = re.search(r'href\s*=\s*["\']([^"\']+)["\']', m.group(1))
        if not h:
            continue
        link = urljoin(base, html.unescape(h.group(1).strip()))
        if not pat.search(link):
            continue
        title = text_of(m.group(2))
        # many list cards wrap "24 Aug 2026 <headline>" in the link. A date at the START or END of the
        # link text is that card's own label -- stronger evidence than a date merely near the link
        # (which can belong to a neighbouring entry the link_re does not match).
        own_dates = find_dates(title[:40], order) or find_dates(title[-40:], order)
        if title_strip_re:                             # site-specific clutter in the link text (category tags)
            title = re.sub(title_strip_re, "", title).strip()
        title = strip_dates(title)
        if title.lower() in GENERIC_LINK_TEXT:
            title = ""
        if not title:                                  # icon-only link: use its title="" attribute
            t = re.search(r'title\s*=\s*["\']([^"\']+)["\']', m.group(1))
            title = html.unescape(t.group(1)).strip() if t and t.group(1).lower() not in GENERIC_LINK_TEXT else ""
        anchors.append((m.start(), m.end(), link, title, own_dates[0] if own_dates else None))

    # the text between this link and its neighbours (never reaching into the next/previous entry)
    windows = []
    for i, (start, end, link, title, own) in enumerate(anchors):
        prev_end = anchors[i - 1][1] if i else max(0, start - 800)
        next_start = anchors[i + 1][0] if i + 1 < len(anchors) else end + 400
        before = find_dates(text_of(page[max(prev_end, start - 800):start]), order)
        after = find_dates(text_of(page[end:min(next_start, end + 400)]), order)
        windows.append((before, after))
    dates_before = sum(1 for b, a in windows if b) >= sum(1 for b, a in windows if a)

    items, by_link = [], {}
    for (start, end, link, title, own), (before, after) in zip(anchors, windows):
        # URL date, then the date label inside the link text, then the date beside the link (page layout)
        beside = (before[-1] if before else None) if dates_before else (after[0] if after else None)
        u = url_date(link)
        d = u or own or beside
        src = "url" if u else "label" if own else "beside" if beside else None   # kept for audits
        if link in by_link:                            # same release linked twice (image + headline)
            it = by_link[link]
            if len(title) > len(it["title"]):
                it["title"] = title
            if it["date"] is None and d:
                it["date"], it["date_src"] = d, src
            continue
        by_link[link] = {"title": title, "link": link, "date": d, "date_src": src}
        items.append(by_link[link])
    return items


def _meta(page, key):
    """content= of a <meta property|name|itemprop=key ...> tag, whatever the attribute order."""
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        if re.search(r'(property|name|itemprop)\s*=\s*["\']%s["\']' % re.escape(key), tag, re.I):
            c = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.I)
            if c:
                return html.unescape(c.group(1)).strip()
    return ""


def is_pdf(url):
    """A PDF link -- also the download.php?f=en/xxx.pdf kind (Ferrotec)."""
    u = urlparse(url)
    return u.path.lower().endswith(".pdf") or bool(re.search(r"\.pdf(?:$|&)", u.query.lower()))


def pdf_lines(url):
    """A release published only as a PDF (common for Japanese / Taiwanese IR): its text, line by line.
    The whole document is kept -- there is no web-page navigation to cut away."""
    from pypdf import PdfReader                        # pip install pypdf (requirements.txt)
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    for attempt in range(3):
        try:
            r = _session().get(url, timeout=60)
            if r.status_code == 200 and r.content[:5] == b"%PDF-":
                reader = PdfReader(io.BytesIO(r.content))
                text = "\n".join((p.extract_text() or "") for p in reader.pages)
                return [l.strip() for l in text.splitlines() if l.strip()]
            if r.status_code in (403, 404, 410):
                return []
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return []


def fill_from_release(item, state, order=None, force_title=False, force_date=False):
    """List page gave no title or no date (or its link text is cluttered, force_title): read them
    from the release page itself. Cached in sync_state so each page is fetched once."""
    if is_pdf(item["link"]):
        return                                         # a PDF has no <h1>/<meta>; keep the list's title/date
    cache = state.setdefault("page_meta", {})
    if item["link"] not in cache:
        page = get(item["link"]) or ""
        # some sites put the logo in the first <h1>; the headline is the longest one
        h1s = [text_of(x) for x in re.findall(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)]
        h1 = max(h1s, key=len) if h1s else ""
        # og:title is usually "<headline> | <section> | <company>" -- keep the headline part
        og = re.split(r"\s+[|｜]\s+|｜", _meta(page, "og:title"))[0].strip()   # full-width ｜ often has no spaces
        title = og or h1
        ld = re.search(r'"datePublished"\s*:\s*"([^"]+)"', page)       # JSON-LD (Schneider Electric)
        raw = (_meta(page, "article:published_time") or _meta(page, "datePublished")
               or (ld.group(1) if ld else "") or _meta(page, "date") or _meta(page, "pubdate"))
        t = re.search(r'<time[^>]+datetime\s*=\s*["\']([^"\']+)', page, re.I)
        found = find_dates(raw) or (find_dates(t.group(1)) if t else [])
        if not found and title:                        # first date printed right after the headline
            lines = page_lines(page)
            # the headline can appear several times (<title>, breadcrumb, article); the publication
            # date sits within ~25 lines after one of them (Siemens: 16) ("Date of announcement: 2026/05/20")
            keys = [t[:20] for t in (item["title"], title) if t and len(t) >= 6]
            for head in [i for i, l in enumerate(lines) if any(k in l for k in keys)]:
                found = find_dates(" ".join(lines[head:head + 25]), order)
                if found:
                    break
        cache[item["link"]] = {"title": title, "date": found[0].isoformat() if found else None}
    got = cache[item["link"]]
    item["title"] = (got["title"] or item["title"]) if force_title else (item["title"] or got["title"])
    if got["date"] and (item["date"] is None or force_date):
        item["date"], item["date_src"] = date.fromisoformat(got["date"]), "page"
    elif force_date:
        item["date"] = None                            # list date not trusted and the page shows none


def json_strings(obj):
    """Every string inside a JSON value (used when a JSON response carries ready-made list HTML)."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, list):
        return [s for x in obj for s in json_strings(x)]
    return []


def _dig(obj, path):
    """obj["a"]["b"][0] for path "a.b.0"."""
    for part in [p for p in (path or "").split(".") if p]:
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def parse_json_items(raw, entry):
    """JSON (or JSONP) list endpoint behind a JavaScript news page -- AGC, ASPEED, Taiyo Yuden.

    feeds.json: {"kind": "json", "feed": <endpoint url>, "items_key": "data.list" (path to the list),
                 "title_key": "title", "date_key": "date", "link_key": "url" | "link_tpl": ".../{id}"}
    The endpoint and keys are found per company by reading the site's own JavaScript, never guessed.
    """
    # JSONP (callback({...});), a leading BOM (Pronexus EIR feeds) or a comment line (irpocket):
    # keep only the span from the first { or [ to the last } or ]
    text = raw.lstrip("﻿").strip()
    if text[:1] not in "{[":
        starts = [p for p in (text.find("{"), text.find("[")) if p >= 0]
        end = max(text.rfind("}"), text.rfind("]"))
        text = text[min(starts):end + 1] if starts and end > 0 else text
    data = json.loads(text)
    rows = _dig(data, entry.get("items_key"))
    items = []
    for row in rows if isinstance(rows, list) else []:
        title = text_of(str(_dig(row, entry["title_key"]) or ""))
        if entry.get("link_tpl"):
            link = entry["link_tpl"].format(**{k: v for k, v in row.items() if not isinstance(v, (dict, list))})
        else:
            link = str(_dig(row, entry["link_key"]) or "")
        if not link.strip():
            continue                                   # a schedule row with no document yet (EIR "earnings release" dates)
        link = urljoin(entry["feed"], html.unescape(link))
        if entry.get("link_re") and not re.search(entry["link_re"], link):
            continue                                   # e.g. a third-party transcript site mixed into the list
        raw_date = _dig(row, entry["date_key"]) if entry.get("date_key") else ""
        if isinstance(raw_date, (int, float)) and raw_date > 10 ** 9:  # epoch seconds / milliseconds
            d = datetime.utcfromtimestamp(raw_date / (1000 if raw_date > 10 ** 11 else 1)).date()
        else:
            found = find_dates(str(raw_date or ""), entry.get("date_order"))
            cm = DATE_COMPACT.search(str(raw_date or ""))              # "20260918-150000" (AGC)
            d = found[0] if found else (_date(*cm.groups()) if cm else None)
        if title and link:
            items.append({"title": strip_dates(title), "link": link, "date": d, "date_src": "json"})
    return items


def read_items(entry, state):
    """Releases listed by one registered source -- an RSS feed or a list page."""
    if entry.get("insecure_tls"):
        INSECURE_HOSTS.add(urlparse(entry["feed"]).netloc)
    raw = get(entry["feed"])
    if not raw:
        return None
    if entry.get("kind") == "json":
        items = parse_json_items(raw, entry)
    elif entry.get("kind") != "page":
        return parse_feed(raw)
    else:
        if raw.lstrip()[:1] in "{[":                   # the list arrives as JSON that carries HTML (Nanya)
            raw = "\n".join(json_strings(json.loads(raw)))
        items = parse_listing(raw, entry["feed"], entry["link_re"], entry.get("date_order"), entry.get("title_strip_re"))
    seen = state.get("seen", {})
    force_title = entry.get("title_from") == "page"    # link text carries tags/teasers -> use the page headline
    force_date = entry.get("date_from") == "page"      # list dates can shift onto a neighbour -> use the page's own
    if force_title or force_date:
        # opening every release page is slow; list pages run newest-first, so the top 60 cover any
        # sync window (Horiba's archive page lists 400+ releases back to 2016)
        items = items[:60]
    for it in items:
        done_before = it["link"] in seen and not seen[it["link"]].startswith("fail")
        if not done_before and (it["date"] is None or not it["title"] or force_title or force_date):
            fill_from_release(it, state, entry.get("date_order"), force_title, force_date)
            if entry.get("title_strip_re"):            # a headline read from the page can carry the same clutter
                it["title"] = strip_dates(re.sub(entry["title_strip_re"], "", it["title"]).strip())
    return [it for it in items if it["title"]]


# ---------------------------------------------------------------- discovery

PATHS = ["/rss/pressrelease.aspx", "/news-events/press-releases/rss", "/rss/news-releases.xml",
         "/news-releases/rss", "/press-releases/rss"]


def host_candidates(name):
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if w]
    bases = {slug(name), words[0] if words else slug(name), "-".join(words)}
    hosts = []
    for b in bases:
        for pre in ("investor", "investors", "ir"):
            hosts.append("https://%s.%s.com" % (pre, b))
    return list(dict.fromkeys(hosts))


GENERIC = {"inc", "corp", "corporation", "the", "and", "holdings", "group", "ltd", "plc", "company", "co"}


def looks_like(name, xml, ticker=None):
    """The feed must be real (has items) and belong to THIS company.

    Strict on purpose: EVERY distinctive word of the name must be in the channel title, or the
    company's ticker must be. One shared word is not enough -- "Applied Optoelectronics" once
    matched ir.applied.com, which is Applied Materials. A miss is cheap (register by hand);
    a wrong feed would file another company's news under this node.
    """
    if not xml or not re.search(r"<item\b|<entry\b", xml):
        return False
    title = channel_title(xml)
    low = title.lower()
    words = [w for w in re.split(r"[^a-z0-9]+", name.lower()) if len(w) > 2 and w not in GENERIC]
    if words and all(w in low for w in words):
        return True
    t = (ticker or "").split(".")[0].upper()
    return bool(t) and not t.isdigit() and re.search(r"\b%s\b" % re.escape(t), title) is not None


EXTRA_PATHS = ["/rss", "/feed", "/rss.xml", "/news/rss", "/press-releases/rss.xml", "/news-releases/rss.xml",
               "/rss/news-releases.xml", "/rss/pressrelease.aspx", "/news-events/press-releases/rss"]


def discover_from_page(name, page_url):
    """Given the company's OFFICIAL IR news page (found by a person or an agent), find its RSS feed:
    1) <link rel="alternate" type="application/rss+xml|atom+xml" href=...> in the page head,
    2) any <a href> on the page that looks like an RSS/XML feed,
    3) the common feed paths on the same host.
    Every candidate must pass the same strict ownership check as `discover` (looks_like)."""
    ticker = public_companies().get(name, {}).get("ticker")
    page = get(page_url, tries=2, timeout=20) or ""
    from urllib.parse import urljoin, urlparse
    cands = []
    for m in re.finditer(r"<link[^>]+>", page, re.I):
        tag = m.group(0)
        if re.search(r"application/(rss|atom)\+xml", tag, re.I):
            h = re.search(r'href="([^"]+)"', tag)
            if h:
                cands.append(urljoin(page_url, html.unescape(h.group(1))))
    for h in re.findall(r'href="([^"]*(?:rss|\.xml|/feed)[^"]*)"', page, re.I):
        cands.append(urljoin(page_url, html.unescape(h)))
    root = "%s://%s" % (urlparse(page_url).scheme or "https", urlparse(page_url).netloc)
    cands += [root + p for p in PATHS + EXTRA_PATHS]
    seen = set()
    for u in cands:
        if u in seen or "comments" in u:
            continue
        seen.add(u)
        xml = get(u, tries=1, timeout=15)
        if looks_like(name, xml, ticker):
            return u
    return None


def discover(company=None, url=None):
    if url:
        if not company:
            sys.exit("--url needs --company")
        feeds = load(FEEDS, {})
        hit = discover_from_page(company, url)
        if hit:
            feeds[company] = {"feed": hit, "how": "page", "page": url, "checked": date.today().isoformat()}
            save(FEEDS, feeds)
            print("found    %-30s %s" % (company, hit))
        else:
            print("none     %-30s no feed on %s that names the company" % (company, url))
        return
    feeds = load(FEEDS, {})
    pubs = public_companies()
    targets = [company] if company else [n for n in pubs if n not in feeds]

    def probe(name):
        """Try every host x path for one company; 10 s per request so dead hosts do not stall the run."""
        ticker = pubs.get(name, {}).get("ticker")
        for host in host_candidates(name):
            for path in PATHS:
                xml = get(host + path, tries=1, timeout=10)
                if looks_like(name, xml, ticker):
                    return host + path
        return None

    found = 0
    with ThreadPoolExecutor(max_workers=8) as pool:      # 8 companies at a time, each sequential inside
        for name, hit in zip(targets, pool.map(probe, targets)):
            if hit:
                feeds[name] = {"feed": hit, "how": "discover", "checked": date.today().isoformat()}
                found += 1
                print("found    %-30s %s" % (name, hit), flush=True)
            else:
                print("none     %-30s (register by hand: python ir_pull.py add \"%s\" <feed-url>)" % (name, name), flush=True)
            save(FEEDS, feeds)
    print("\n%d feed(s) found; %d registered in total" % (found, len(feeds)))


# ---------------------------------------------------------------- release body

def _drop_header(m):
    """Site headers are menus -- but one Webflow site (POET) wraps the whole article in <header>.
    Keep a <header> whose text is article-sized."""
    return m.group(0) if len(re.sub(r"<[^>]+>", " ", m.group(0)).split()) > 150 else " "


def page_lines(page):
    # closing tags may carry attributes on broken sites: </script nonce="..."> (King Slide)
    page = re.sub(r"(?is)<(script|style|noscript|svg|footer|nav)\b[^>]*>.*?</\1[^>]*>", " ", page)
    page = re.sub(r"(?is)<header\b[^>]*>.*?</header[^>]*>", _drop_header, page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>|</tr>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in text.splitlines()]
    return [l for l in lines if l]


def release_body(page, title):
    """Cut the release out of an IR page: from the headline to the first end marker.

    The headline usually appears twice (the <title> tag and the article heading); we take the
    occurrence followed by the most text, which is the article, and stop at "About <company>" /
    contacts / forward-looking boilerplate.
    """
    # a few sites (Delta Electronics) render the article inside <iframe srcdoc="...escaped html...">
    # (put it back where the iframe sits, so it follows the headline like normal article text)
    page = re.sub(r'<iframe\b[^>]*?srcdoc\s*=\s*"([^"]*)"[^>]*>', lambda m: "\n" + html.unescape(m.group(1)) + "\n",
                  page, flags=re.I)
    lines = page_lines(page)
    if mostly_ascii(title):
        norm = lambda s: re.sub(r"[^a-z0-9]", "", ascii_text(s).lower())
    else:
        # Japanese / Chinese / Korean headline: keep every letter (NFKC folds full-width forms),
        # otherwise the headline would shrink to its digits ("2026") and match the wrong line.
        norm = lambda s: re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", s).lower())
    want = norm(title)[:60]
    # a line that starts with the headline -- or, when the site breaks a long headline over several
    # lines, a line that is itself the first 25+ characters of it (Delta Electronics)
    starts = [i for i, l in enumerate(lines)
              if want and (norm(l).startswith(want) or (len(norm(l)) >= 25 and want.startswith(norm(l))))]
    best = []
    for s in starts:
        body = []
        for l in lines[s:]:
            if body and END_MARKERS.match(l):
                break
            if l not in CHROME:
                body.append(l)
        if sum(len(x) for x in body) > sum(len(x) for x in best):
            best = body
    return best


# ---------------------------------------------------------------- save + queue

def short_title(title, n=60):
    t = ascii_text(title)
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0]


def mostly_ascii(title):
    """True for an English headline. A Japanese/Chinese/Korean headline loses most of its
    characters in ascii_text(), so it cannot be used for a label or a filename."""
    t = title.strip()
    return bool(t) and len(ascii_text(t).strip()) >= 0.8 * len(t)


def label_title(title, url):
    """The headline as it goes into the (ASCII-only) source label and filename.
    Non-English headline -> "release <id from the URL>"; the original headline stays in the file."""
    if mostly_ascii(title):
        return title
    parts = [p for p in urlparse(url).path.split("/") if p]
    rid = re.sub(r"[^A-Za-z0-9]+", "-", parts[-1] if parts else "")
    rid = re.sub(r"-(html?|aspx|php)$", "", rid.strip("-"))[:40]
    return "release %s" % (rid or "untitled")


def shown_title(title):
    """Headline for the file header / queue: ASCII for English, the original text otherwise."""
    if mostly_ascii(title):
        return ascii_text(title)
    return title.strip() + "  (original language; write entries in English)"


def label_for(company, title, d):
    return "%s press release: %s (%s)" % (company, short_title(title), d.strftime("%m-%d-%Y"))


def write_release(company, title, d, url, body):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ltitle = label_title(title, url)
    tslug = re.sub(r"[^a-z0-9]+", "-", ascii_text(ltitle).lower()).strip("-")[:50]
    path = OUT_DIR / ("%s_%s_%s.txt" % (slug(company), d.isoformat(), tslug))
    label = label_for(company, ltitle, d)
    header = ("SOURCE: %s official press release -- %s\n"
              "TITLE: %s\n"
              "DATE: %s  (release date)\n"
              "NOTE: Official company press release from the company's own IR feed -- NOT a transcript, no\n"
              "      management Q&A. Saved verbatim (site navigation removed) by ir_pull.py on %s.\n"
              "      Product/event releases: 'first'/'leading' are company claims; demos are not shipping.\n"
              "# source label: %s\n\n---\n") % (company, url, ascii_text(title), d.strftime("%m-%d-%Y"),
                                               date.today().isoformat(), label)
    header = header.replace("TITLE: %s\n" % ascii_text(title), "TITLE: %s\n" % shown_title(title), 1)
    path.write_text(header + "\n\n".join(body) + "\n", encoding="utf-8")
    return path, label


def queue(company, label, path, url, title, d):
    rows = load(PENDING, [])
    if any(r["label"] == label for r in rows):
        return
    rows.append({"kind": "ir", "company": company, "label": label,
                 "file": path.relative_to(ROOT).as_posix(), "url": url, "title": shown_title(title),
                 "date": d.isoformat()})
    save(PENDING, rows)


def noise_reason(company, title):
    for pat, why in NOISE:
        if re.search(pat, title, re.I):
            return why
    exch = public_companies().get(company, {}).get("exchange")
    if exch in US_EXCHANGES and RESULTS.search(title):
        return "results release (US: read via edgar_pull.py 8-K + the call)"
    return None


def already_on_disk(url):
    """A release saved earlier by hand (e.g. into transcripts/non_transcript_sources/) must not be
    saved and enriched a second time under a different label. Match on the SOURCE line's URL."""
    key = url.split("?")[0].rstrip("/").lower()
    for f in (ROOT / "transcripts").rglob("*.txt"):
        if f.parent == OUT_DIR:          # our own saves are tracked by sync_state, not here
            continue
        try:
            head = f.open(encoding="utf-8", errors="ignore").read(600)
        except OSError:
            continue
        if head.startswith("SOURCE:") and key in head.lower():
            return f.relative_to(ROOT).as_posix()
    return None


def take(company, item, state, force=False):
    """Save one feed item if it is new, dated, and not noise. Returns 'saved' / 'skip' / 'fail' / 'seen'."""
    url, title, d = item["link"], item["title"], item["date"]
    seen = state.setdefault("seen", {})
    if url in seen and not seen[url].startswith("fail") and not force:
        return "seen"
    if d is None:
        seen[url] = "fail:no date"
        return "fail"
    why = noise_reason(company, title)
    if why and not force:
        seen[url] = "skip:" + why
        print("skip     %-22s %s  [%s]" % (company, title[:70], why))
        return "skip"
    dup = already_on_disk(url)
    if dup and not force:
        seen[url] = "skip:already saved as " + dup
        print("skip     %-22s %s  [already saved: %s]" % (company, title[:70], dup))
        return "skip"
    if is_pdf(url):
        body = pdf_lines(url)                          # PDF release: the whole document
    else:
        page = get(url)
        if page and page.lstrip().startswith("%PDF-"):  # a PDF served without a .pdf name (TOWA)
            body = pdf_lines(url)
        else:
            body = release_body(page, title) if page else []
    # Not the article (only a headline, or only menus / related links)? Then try the full text the
    # RSS item itself carries. Japanese/Chinese/Korean text packs ~3x the meaning per character, so
    # prose_ok's length floor is lower there.
    if not prose_ok(body, title) and item.get("content"):
        body = page_lines(item["content"])
    if not prose_ok(body, title):
        seen[url] = "fail:body not found"
        print("FAIL     %-22s %s  (body not found -- save it by hand)" % (company, title[:70]))
        return "fail"
    path, label = write_release(company, title, d, url, body)
    queue(company, label, path, url, title, d)
    seen[url] = "saved"
    state.setdefault("releases", {})[url] = {"company": company, "label": label, "date": d.isoformat(),
                                             "status": "pending"}
    print("saved    %-22s %s -> %s" % (company, label[:80], path.relative_to(ROOT).as_posix()))
    return "saved"


LABEL_DATE = re.compile(r"\((\d\d)-(\d\d)-(\d{4})\)")
EARNINGS_LABEL = re.compile(r" Q\d FY\d{4} \(")
MAX_BACK = 120      # never reach further back than this on a company's first sync


def last_source_date(company, graph=[]):
    """Date of the company's newest OWN earnings call already in the graph.

    A release published before that date was either discussed on that call or is old news, so a
    company's FIRST sync only reaches back to it (bounded to MAX_BACK days). After the first sync
    the start date does not matter: every URL already handled is remembered in sync_state.json.
    """
    if not graph:
        path = ROOT / "graph" / "merged_graph.json"
        graph.append(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"nodes": []})
    best = None
    for n in graph[0].get("nodes", []):
        if n.get("id") != company:
            continue
        for q in n.get("quarterly_data", []):
            lab = q.get("quarter") or ""
            # earnings calls only ("Marvell Q2 FY2027 (08-27-2026)") -- a later conference does not
            # cover the releases issued between the call and the conference
            if not lab.startswith(company + " ") or not EARNINGS_LABEL.search(lab):
                continue
            m = LABEL_DATE.search(lab)
            if m:
                d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                best = d if best is None or d > best else best
    floor = date.today() - timedelta(days=MAX_BACK)
    return max(best, floor) if best else date.today() - timedelta(days=30)


def sync(since=None, company=None):
    feeds = load(FEEDS, {})
    state = load(STATE, {"runs": [], "seen": {}})
    names = [company] if company else sorted(feeds)
    counts = {"saved": 0, "skip": 0, "fail": 0, "seen": 0}
    # Read every feed / list page 8 at a time (network-bound); saving releases below stays one by one,
    # because it writes the shared state and queue files.
    def safe_read(n):
        try:
            return read_items(feeds[n], state) if n in feeds else None
        except Exception as e:                         # one broken site must not stop the whole sync
            print("READ ERR %-22s %s" % (n, e))
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        listed = dict(zip(names, pool.map(safe_read, names)))
    for name in names:
        if name not in feeds:
            print("no feed  %s  (run: python ir_pull.py discover --company \"%s\")" % (name, name))
            continue
        items = listed[name]
        if items is None:
            print("FEED ERR %-22s %s" % (name, feeds[name]["feed"]))
            continue
        start = since or last_source_date(name)
        mine = {"saved": 0, "skip": 0, "fail": 0, "seen": 0}
        for item in items:
            if item["date"] and item["date"] < start:
                continue
            r = take(name, item, state)
            counts[r] += 1
            mine[r] += 1
            time.sleep(0.5)
        state.setdefault("companies", {})[name] = {"last_sync": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                   "since": start.isoformat()}
        if company or mine["saved"]:
            print("%-22s since %s: %d new, %d already handled, %d notices skipped"
                  % (name, start.isoformat(), mine["saved"], mine["seen"], mine["skip"]))
        save(STATE, state)
    state["runs"].append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                          "since": since.isoformat() if since else "per company (latest call)",
                          "feeds": len(names), **counts})
    save(STATE, state)
    print("\n%(saved)d saved, %(skip)d skipped as notices, %(fail)d failed, %(seen)d already handled" % counts)
    print("`python ir_pull.py pending` shows the queue; `python ir_pull.py status` shows what is done")


def mark_done(rows, why=None):
    """Remove rows from the queue AND stamp them enriched, so a later sync or `enrich ir <Company>`
    knows they were handled and never saves or enriches them again."""
    state = load(STATE, {"runs": [], "seen": {}})
    stamp = "enriched:" + date.today().isoformat() + (" (" + why + ")" if why else "")
    for r in rows:
        state.setdefault("seen", {})[r["url"]] = stamp
        rel = state.setdefault("releases", {}).setdefault(r["url"], {"company": r["company"], "label": r["label"],
                                                                     "date": r["date"]})
        rel["status"] = stamp
    save(STATE, state)


def status(company=None):
    """Per company: feed?, last sync, releases saved, enriched, still pending, notices skipped."""
    feeds, state, pend = load(FEEDS, {}), load(STATE, {}), load(PENDING, [])
    rel = state.get("releases", {})
    names = [company] if company else sorted(set(feeds) | {v["company"] for v in rel.values()})
    print("%-24s %-5s %-17s %-6s %-9s %-8s" % ("company", "feed", "last sync", "saved", "enriched", "pending"))
    for n in names:
        mine = [v for v in rel.values() if v["company"] == n]
        enr = [v for v in mine if str(v.get("status", "")).startswith("enriched")]
        pen = [r for r in pend if r["company"] == n]
        last = state.get("companies", {}).get(n, {}).get("last_sync", "-")
        print("%-24s %-5s %-17s %-6d %-9d %-8d" % (n[:24], "yes" if n in feeds else "NO", last, len(mine), len(enr), len(pen)))
        if company:
            for v in sorted(mine, key=lambda v: v["date"]):
                print("    %s  %-10s %s" % (v["date"], str(v.get("status", ""))[:28], v["label"][:90]))
    if company and not pend and company in feeds:
        print("-> nothing pending for %s; a sync only adds releases newer than those already handled." % company)


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover"); d.add_argument("--company"); d.add_argument("--url", help="the company's official IR news page")
    a = sub.add_parser("add"); a.add_argument("company"); a.add_argument("feed")
    a.add_argument("--page", action="store_true", help="FEED is an HTML list of releases, not RSS")
    a.add_argument("--link-re", help="--page: regex that matches the URL of one release on that site")
    a.add_argument("--date-order", choices=["mdy", "dmy"], help="--page: how the site writes 09/10/2026")
    a.add_argument("--lang", help="--page: language of the releases if not English (ja, zh, ko, de...)")
    a.add_argument("--title-from-page", action="store_true", help="--page: link text is cluttered; use the release page headline")
    a.add_argument("--title-strip-re", help="--page: regex removed from each link text (category tags etc.)")
    sub.add_parser("feeds")
    s = sub.add_parser("sync"); s.add_argument("--since"); s.add_argument("--company")
    f = sub.add_parser("fetch"); f.add_argument("url"); f.add_argument("--company", required=True)
    f.add_argument("--title", help="headline, if the page title is not usable"); f.add_argument("--date", help="MM-DD-YYYY")
    sub.add_parser("pending")
    st = sub.add_parser("status"); st.add_argument("--company")
    dn = sub.add_parser("done"); dn.add_argument("--label"); dn.add_argument("--all", action="store_true")
    dn.add_argument("--why", help="e.g. 'no new facts' when a release yielded nothing")
    args = ap.parse_args()

    if args.cmd == "discover":
        discover(args.company, args.url)
    elif args.cmd == "add":
        feeds = load(FEEDS, {})
        entry = {"feed": args.feed, "how": "manual", "checked": date.today().isoformat()}
        if args.page:
            if not args.link_re:
                sys.exit("--page needs --link-re (a regex matching one release URL on that site)")
            entry.update({"kind": "page", "link_re": args.link_re})
            if args.date_order:
                entry["date_order"] = args.date_order
            if args.lang:
                entry["lang"] = args.lang
            if args.title_from_page:
                entry["title_from"] = "page"
            if args.title_strip_re:
                entry["title_strip_re"] = args.title_strip_re
        feeds[args.company] = entry
        save(FEEDS, feeds)
        print("registered", args.company, args.feed)
    elif args.cmd == "feeds":
        for n, v in sorted(load(FEEDS, {}).items()):
            print("%-30s %-8s %-5s %s" % (n, v["how"], v.get("kind", "rss"), v["feed"]))
    elif args.cmd == "sync":
        since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None
        sync(since, args.company)
    elif args.cmd == "fetch":
        page = get(args.url) or sys.exit("could not fetch " + args.url)
        title = args.title or html.unescape(re.search(r"<title[^>]*>(.*?)</title>", page, re.S).group(1)).split("|")[0].split(" - ")[-1].strip()
        d = datetime.strptime(args.date, "%m-%d-%Y").date() if args.date else date.today()
        state = load(STATE, {"runs": [], "seen": {}})
        take(args.company, {"link": args.url, "title": title, "date": d}, state, force=True)
        save(STATE, state)
    elif args.cmd == "pending":
        rows = load(PENDING, [])
        for r in rows:
            print("%-10s %-22s %s" % (r["date"], r["company"], r["label"]))
        print("%d pending" % len(rows))
    elif args.cmd == "status":
        status(args.company)
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit("give --label \"<label>\" (one row) or --all")
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print("queue: %d marked enriched and removed, %d kept" % (len(hit), len(rows) - len(hit)))

if __name__ == "__main__":
    main()
