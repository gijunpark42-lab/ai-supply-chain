"""
investing.py -- non-US, non-Korean companies: Investing.com earnings-call transcripts
                -> transcripts/investing/*.txt

Who this is for: the 88 names in company_metadata.json listed in Taiwan, Japan, Europe, HK,
China (Quanta, Wiwynn, Alchip, MediaTek, Tokyo Electron, Infineon, ASMPT ...). They hold
quarterly investor calls but publish no written transcript, and no free API carries them
(Alpha Vantage = US only, defeatbeta = US only, MOPS blocks file downloads). Investing.com
does transcribe the English calls and posts them as articles within ~a day. Verified on
Alchip Q2 2026: ~18,000 words, every speaker turn, full analyst Q&A.

Same interface as dart.py / av.py:

    python investing.py sync                # search Investing.com for each of OUR companies,
                                            #   download every transcript not saved yet
    python investing.py fetch <url>         # one article by hand (company/quarter read from title)
    python investing.py pending / done      # the enrichment queue

How the fetch works, and the honest caveat
------------------------------------------
Investing.com sits behind a bot filter that rejects plain `requests` (HTTP 403). The
`curl_cffi` library sends the request with a real Chrome TLS fingerprint, which the site
accepts like a normal browser visit. We read public article pages only, one page per second,
for personal research -- but it is scraping, and Investing.com's T&C do not grant an API.
If they block it one day, the fallback is the Chrome extension (open the article, copy
the text) under the same label.

Label: `[Company] Q[N] FY[YYYY] (MM-DD-YYYY)` with the ARTICLE publish date (the call is
usually the same day or the day before). Quarter/year come from the article title
("Earnings call transcript: Alchip Q2 2026 ..."); FY = the year in the title.

Conferences (fireside chats at Goldman Communacopia, Citi TMT, UBS, ...)
-----------------------------------------------------------------------
Investing.com also posts a same-day article per conference appearance, titled
"<Company> at <Conference> <YYYY>: <summary>". The first ~2,000 words are an editorial
summary; after the paragraph "Full transcript - ..." comes the verbatim fireside chat with
speaker labels ("Shannon Cross, Executive, HPE: ..."). Verified on HPE at Goldman
Communacopia 2026-09-10: 8,195 words, 6,081 of them transcript. The site search cannot
find these reliably, so `conferences` walks the /news/transcripts listing pages instead
(36 articles per page, publish date in the page JSON) and stops at --since.

    python investing.py conferences             # every company in company_metadata.json (US too),
                                                #   last 180 days -> transcripts/conferences/*.txt
    python investing.py conferences --since 2026-06-01 --pages 400
    python investing.py fetch <url>             # a conference URL is recognised by its title

Only the transcript part is saved (the summary is dropped). Label follows the enrich skill's
Event format `[Company] [Event] [YYYY] (MM-DD-YYYY)`, e.g.
`HPE Goldman Sachs Communacopia + Technology Conference 2026 (09-10-2026)`.
Every run is recorded in investing/conferences_state.json (when, pages walked, oldest
article date reached, files saved) so you can see how far back each run went.
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from curl_cffi import requests

ROOT = Path(__file__).parent
METADATA = ROOT / "company_metadata.json"
OUT_DIR = ROOT / "transcripts" / "investing"
STATE = ROOT / "investing" / "sync_state.json"    # article URLs already saved
PENDING = ROOT / "investing" / "pending.json"     # saved, not yet enriched

SEARCH_URL = "https://api.investing.com/api/search/v2/search"   # the site's own search; JSON
COVERED_ELSEWHERE = {"NASDAQ", "NYSE", "KRX", "KOSPI", "KOSDAQ"}   # av.py / dart.py

LIST_URL = "https://www.investing.com/news/transcripts"          # newest first; /2, /3 ... older
CONF_DIR = ROOT / "transcripts" / "conferences"
CONF_STATE = ROOT / "investing" / "conferences_state.json"       # runs + every conference URL seen
CONF_TITLE = re.compile(r"^(?P<co>.+?) at (?P<conf>.+?)(?: (?P<yr>20\d\d))?:")   # "HPE at Goldman ... 2026: ..."

# Titles name companies slightly differently from our nodes. Parentheticals in our names
# ("GUC (Global Unichip)") are split automatically; these are the extra spellings.
ALIASES = {
    "Quanta": ["Quanta Computer"],          # never bare "Quanta" -- that is Quanta Services (US)
    "Foxconn": ["Hon Hai"],
    "ASM International": ["ASMI"],
    "Nan Ya PCB": ["NanYa PCB", "Nan Ya Printed Circuit"],
    "Panasonic Holdings": ["Panasonic"],
    "Disco Corporation": ["DISCO Corp"],
    "Mitsubishi Heavy Industries": ["MHI"],
    "Tokyo Ohka Kogyo": ["TOK"],
    "SoftBank": ["SoftBank Group"],         # our node is the Group (9984), not SoftBank Corp (9434, telecom)
}
# Same name, different listed company -- a title containing one of these is NOT ours.
EXCLUDE = {
    "Quanta": ["Quanta Services"],
    "SoftBank": ["SoftBank Corp"],
    "Delta Electronics": ["Thailand"],      # Delta Electronics (Thailand) PCL, a separate listing
    "Disco Corporation": ["CS Disco"],
    "ABB": ["ABB India", "ABB Power"],
    "Schneider Electric": ["Schneider Electric Infrastructure"],   # the Indian listed subsidiary
    "Siemens": ["Healthineers", "Siemens Ltd"],
}
# Listed Indian subsidiaries of European parents report separately; never ours.
EXCLUDE_ANY = [r"\bIndia\b"]


# ---------------------------------------------------------------- universe

def universe(everyone=False):
    """{canonical name: [title spellings]} for every company NOT covered by av.py or dart.py.
    `everyone=True` (conferences): every listed company in company_metadata.json, US included --
    no other pipeline carries conference appearances."""
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    out = {}
    for name, info in meta.items():
        if not info.get("exchange") or (not everyone and info.get("exchange") in COVERED_ELSEWHERE):
            continue
        spellings = [name] + ALIASES.get(name, [])
        if name in EXCLUDE and name in ALIASES:      # bare name is ambiguous -> aliases only
            spellings = ALIASES[name][:]
        m = re.match(r"^(.+?)\s*\((.+)\)$", name)      # "GUC (Global Unichip)" -> both halves
        if m:
            spellings += [m.group(1), m.group(2)]
        out[name] = spellings
    return out


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def match_company(title, uni):
    """Which of our companies does this article title name? Longest spelling wins."""
    head = title.split(":", 1)[-1]          # text after "Earnings call transcript:"
    best, best_len = None, 0
    for name, spellings in uni.items():
        if any(x.lower() in head.lower() for x in EXCLUDE.get(name, [])):
            continue
        if any(re.search(x, head) for x in EXCLUDE_ANY):
            continue
        for sp in spellings:
            if len(sp) >= 3 and re.search(r"(?<![A-Za-z])" + re.escape(sp) + r"(?![A-Za-z])", head, re.I):
                if len(sp) > best_len:
                    best, best_len = name, len(sp)
    return best


def quarter_from_title(title):
    """Read (year, quarter) out of an article title. Case-insensitive; a bare "Q1" plus a year
    anywhere in the title beats a "FY2026" mention (Advantest "lifts FY2026 outlook after record Q1").

    'Alchip Q2 2026 ...'        -> (2026, 2)      'X-FAB rises on q2 2026'        -> (2026, 2)
    'Wiwynn 2Q26 results'       -> (2026, 2)      'ASMPT posts strong H1 2026'    -> (2026, 2)
    'Infineon Q3 FY2025'        -> (2025, 3)      'Tokyo Electron full-year 2025' -> (2025, 4)
    """
    t = title
    m = re.search(r"\b(?:FY\s?)?(20\d\d)\b", t)
    if m:
        year = int(m.group(1))
    else:
        m = re.search(r"\bQ[1-4]\s?'?(\d\d)\b|\b[1-4]Q(\d\d)\b", t, re.I)
        if not m:
            return None
        year = 2000 + int(m.group(1) or m.group(2))
    m = re.search(r"\bQ([1-4])\b", t, re.I) or re.search(r"\b([1-4])Q\d\d\b", t, re.I)
    if m:
        return year, int(m.group(1))
    m = re.search(r"\bH([12])\b", t, re.I)
    if m:
        return year, 2 if m.group(1) == "1" else 4
    if re.search(r"\bFY|full[- ]year|fiscal|annual", t, re.I):
        return year, 4
    return None


_LABEL = re.compile(r"^(?P<name>.+?) Q(?P<q>[1-4]) FY(?P<fy>20\d\d) \((?P<d>\d\d-\d\d-\d{4})\)$")


def latest_label_in_graph(name):
    """(fy, q, date) of the newest earnings label this company already has in the graph, or None.

    The graph is the record of what has been enriched, and its labels already encode each
    company's fiscal calendar -- so the next call is simply Q+1 in the same convention.
    """
    path = ROOT / "graph" / "merged_graph.json"
    if not path.exists():
        return None
    best = None
    for node in json.loads(path.read_text(encoding="utf-8"))["nodes"]:
        if node["id"] != name:
            continue
        for q in node.get("quarterly_data", []):
            m = _LABEL.match(q.get("quarter", ""))
            if m and m.group("name") == name:
                d = datetime.strptime(m.group("d"), "%m-%d-%Y").date()
                if best is None or d > best[2]:
                    best = (int(m.group("fy")), int(m.group("q")), d)
    return best


# Japanese companies whose fiscal year ends in March. Our graph labels these by the calendar
# year the fiscal year ENDS in (Q4 FY2026 = Jan-Mar 2026, Q1 FY2027 = Apr-Jun 2026), which is
# what TEL / TDK / Kioxia already carry. Investing.com titles are inconsistent for them
# ("SoftBank Q1 2026" and "Panasonic Q1 2027" are the same Apr-Jun 2026 quarter), so the
# title year is ignored and the FY is computed from the article date instead.
def _japan_march_fy(name):
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    if meta.get(name, {}).get("country") != "JP":
        return False
    return name not in {"Renesas", "SUMCO", "Resonac (Showa Denko)", "Tokyo Ohka Kogyo", "Lasertec"}


def label_parts(name, title, published):
    """Decide (fy, q) for the label. Priority:
    1. the graph already has this company -> the quarter after its latest label, if the
       title's quarter number agrees (keeps the label convention consistent with history);
       and if the title's quarter IS the graph's latest and the dates are within 45 days,
       this article is the same call we already enriched -> Skip.
    2. Japanese March-FY companies -> FY from the article date (see _japan_march_fy).
    3. otherwise the year and quarter printed in the title.
    """
    yq = quarter_from_title(title)
    if not yq:
        raise RuntimeError(f"no quarter in title: {title}")
    last = latest_label_in_graph(name)
    if last:
        fy, q, d = last
        if yq[1] == q and abs((published - d).days) <= 45:
            raise Skip(f"same call already in graph as {name} Q{q} FY{fy} ({d.strftime('%m-%d-%Y')})")
        nxt = (fy + 1, 1) if q == 4 else (fy, q + 1)
        if yq[1] == nxt[1] and published > d:
            return nxt
    if _japan_march_fy(name):
        # FY "Y" runs Apr (Y-1) .. Mar (Y). Q1/Q2 are reported Jul-Nov of Y-1 -> FY = year + 1;
        # Q3 (Jan-Feb of Y) and Q4 (Apr-Jun of Y) are reported inside calendar year Y -> FY = year.
        q = yq[1]
        return (published.year + 1 if q in (1, 2) else published.year), q
    return yq


# ---------------------------------------------------------------- fetching

def get(url, params=None, tries=4):
    """GET with a Chrome fingerprint; on 503 (rate limit) wait and retry, doubling the pause.
    A 403 after many fast requests is the bot filter cooling us off (seen at listing page 131 on
    2026-09-10) -- wait a full minute before each retry instead of giving up.
    A dropped connection / DNS blip (curl errors 6 and 56, seen 2026-09-16) is retried the same way."""
    pause = 5
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, impersonate="chrome", timeout=60)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(60)
            continue
        if r.status_code == 200:
            return r.text
        if r.status_code not in (403, 503) or attempt == tries - 1:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        time.sleep(60 if r.status_code == 403 else pause)
        pause *= 2


def search_transcripts(spelling):
    """Ask the site's search for '<company> earnings call transcript' -> [(url, title)].

    The search returns at most ~5 news hits, newest first, which is enough: a company has
    one call per quarter, and `sync` runs at least monthly.
    """
    data = json.loads(get(SEARCH_URL, params={"q": f"{spelling} earnings call transcript"}))
    out = []
    for n in data.get("news") or []:
        url = n.get("url") or ""
        if "/news/transcripts/earnings-call-transcript-" in url:
            out.append(("https://www.investing.com" + url if url.startswith("/") else url,
                        (n.get("description") or "").strip()))
    return out


def _clean(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).replace("&amp;", "&").replace("&#39;", "'") \
             .replace("&quot;", '"').replace("&nbsp;", " ").strip()


def article(url):
    """Download one transcript article -> (title, published date, [paragraphs])."""
    html = get(url)
    title = _clean(re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S).group(1))
    m = re.search(r'datePublished":"(\d{4}-\d\d-\d\d)', html)
    published = datetime.strptime(m.group(1), "%Y-%m-%d").date() if m else datetime.today().date()
    body = html.split('<div id="article">', 1)[1] if '<div id="article">' in html else html
    paras = [_clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
    paras = [p for p in paras if p and not p.startswith("This article was generated")]
    return title, published, paras


def write_file(name, year, q, published, url, title, paras):
    label = f"{name} Q{q} FY{year} ({published.strftime('%m-%d-%Y')})"
    path = OUT_DIR / f"{slug(name)}_q{q}_{year}.txt"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    head = [
        f"SOURCE: Investing.com earnings call transcript -- {url}",
        f"TITLE: {title}",
        f"CALL DATE: {published.strftime('%m-%d-%Y')}  (article publish date)",
        f"QUARTER: Q{q} FY{year}",
        f"# source label: {label}",
        f"# paragraphs: {len(paras)}   characters: {sum(len(p) for p in paras):,}",
    ]
    if any(re.search(r"Q&A (?:was|were) not included|question-and-answer session was not included|No analyst Q&A", p) for p in paras):
        head.append("# note: prepared remarks only -- Investing.com did not include the analyst Q&A for this call")
    head += ["", "---", ""]
    path.write_text("\n".join(head) + "\n\n".join(paras) + "\n", encoding="utf-8")
    return path, label


def _queue(saved, kind="transcript"):
    pending = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else []
    known = {(x["file"], x["label"]) for x in pending}
    for name, path, label in saved:
        row = {"kind": kind, "company": name,
               "file": str(path.relative_to(ROOT)).replace("\\", "/"), "label": label}
        if (row["file"], row["label"]) not in known:
            pending.append(row)
    PENDING.parent.mkdir(exist_ok=True)
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")


class Skip(Exception):
    """Not an error: the article is older than --since, or that quarter is already saved."""


def fetch_one(url, uni, company=None, since=None, overwrite=False):
    title, published, paras = article(url)
    name = company or match_company(title, uni)
    if not name:
        raise RuntimeError(f"no company of ours in title: {title}")
    if since and published < since:
        raise Skip(f"published {published} < since {since}")
    fy, q = label_parts(name, title, published)
    path = OUT_DIR / f"{slug(name)}_q{q}_{fy}.txt"
    if path.exists() and not overwrite:
        # Investing.com sometimes posts the same call twice (a first cut and a fuller one).
        # Search results come newest first, so the file already there is the newer article.
        raise Skip(f"{path.name} already saved")
    from agent.corpus import find_document_for_label
    if not overwrite and find_document_for_label(f"{name} Q{q} FY{fy} (01-01-2000)") is not None:
        raise Skip(f"{name} Q{q} FY{fy} already in transcripts/ from another source")
    if len(paras) < 20:
        raise RuntimeError(f"only {len(paras)} paragraphs -- page not fully rendered?")
    path, label = write_file(name, fy, q, published, url, title, paras)
    return name, path, label


def sync(since=None):
    """One search per company (88 names, ~2 min), then download every transcript we do not
    have yet and that was published on/after `since` (default: the last 120 days -- older
    calls are history, not enrichment work). Returns [(name, path, label)]."""
    if since is None:
        since = date.today() - timedelta(days=120)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"saved": []}
    saved_urls = set(state["saved"])
    uni = universe()
    todo = {}
    for name, spellings in uni.items():
        try:
            for url, title in search_transcripts(spellings[0]):
                if url not in saved_urls and match_company(title, uni) == name:
                    todo[url] = title
        except Exception as exc:
            print(f"FAIL search {name}: {exc}")
        time.sleep(1)
    print(f"{len(todo)} new transcript(s) found for our companies")
    saved = []
    for url, title in todo.items():
        try:
            name, path, label = fetch_one(url, uni, since=since)
            saved.append((name, path, label))
            print(f"saved    {label:45s} -> {path.relative_to(ROOT)}")
        except Skip as why:
            print(f"skip     {title[26:66]:40s} ({why})")
        except Exception as exc:
            print(f"FAIL     {title[:70]}: {exc}")
            continue
        saved_urls.add(url)          # saved or skipped-for-good: never look at this URL again
        time.sleep(1)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"saved": sorted(saved_urls)}, indent=1), encoding="utf-8")
    _queue(saved)
    return saved


# ---------------------------------------------------------------- conferences

def list_page(n):
    """Listing page n (1 = newest) -> [(url, title, published date)], newest first.
    The page embeds its article list as JSON (props.pageProps.state.newsStore._news)."""
    html = get(LIST_URL if n == 1 else f"{LIST_URL}/{n}")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(f"listing page {n}: no __NEXT_DATA__ -- page layout changed?")
    news = json.loads(m.group(1))["props"]["pageProps"]["state"]["newsStore"]["_news"]
    out = []
    for a in news:
        link = a.get("link") or ""
        if "/news/transcripts/" not in link:
            continue
        url = "https://www.investing.com" + link if link.startswith("/") else link
        published = datetime.strptime(a["published_at"][:10], "%Y-%m-%d").date()
        out.append((url, _clean(a.get("title") or ""), published))
    return out


def conference_from_title(title):
    """'HPE at Goldman Sachs Communacopia + Technology Conference 2026: growth lifts'
    -> ('HPE', 'Goldman Sachs Communacopia + Technology Conference', 2026 or None); None if not a conference."""
    m = CONF_TITLE.match(title)
    if not m or title.lower().startswith("earnings call transcript"):
        return None
    conf, year = m.group("conf").strip(), int(m.group("yr")) if m.group("yr") else None
    conf = re.sub(r"^the\s+", "", conf, flags=re.I)   # "the Six Five Summit" -> "Six Five Summit"
    y = re.search(r"\b(20\d\d)\b", conf)          # "Citi's 2026 Global TMT Conference" -> year once, at the end
    if y:
        year = year or int(y.group(1))
        conf = re.sub(r"\s*\b20\d\d\b\s*", " ", conf).strip()
    return m.group("co").strip(), conf, year


def transcript_part(paras):
    """Drop the editorial summary: keep everything after the 'Full transcript - ...' paragraph.
    Returns (paragraphs, True) or, if the marker is missing, (all paragraphs, False)."""
    for i, p in enumerate(paras):
        if re.match(r"^Full transcript\b", p, re.I):
            return paras[i + 1:], True
    return paras, False


def write_conference_file(name, conf, year, published, url, title, paras, verbatim):
    label = f"{name} {conf} {year} ({published.strftime('%m-%d-%Y')})"
    path = CONF_DIR / f"{slug(name)}_{slug(conf)[:40]}_{published.isoformat()}.txt"
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    speakers = []
    for p in paras:
        m = re.match(r"^([A-Z][A-Za-z.\-' ]{2,40}), ([^:]{2,60}):", p)
        if m and m.group(0) not in speakers:
            speakers.append(m.group(0))
    head = [
        f"SOURCE: Investing.com conference transcript -- {url}",
        f"TITLE: {title}",
        f"EVENT: {conf} {year}",
        f"DATE: {published.strftime('%m-%d-%Y')}  (article publish date = event day)",
        f"# source label: {label}",
        f"# speakers: {'; '.join(s.rstrip(':') for s in speakers[:8]) or 'not labelled'}",
        f"# paragraphs: {len(paras)}   characters: {sum(len(p) for p in paras):,}",
    ]
    if not verbatim:
        head.append("# note: no 'Full transcript' marker in the article -- summary and transcript saved together")
    head += ["", "---", ""]
    path.write_text("\n".join(head) + "\n\n".join(paras) + "\n", encoding="utf-8")
    return path, label


def fetch_conference(url, uni, published=None, title=None, overwrite=False):
    """One conference article -> (name, path, label). Raises Skip when it is not ours / already saved."""
    if title is None or published is None:
        title, published, paras = article(url)
    else:
        paras = article(url)[2]
    parsed = conference_from_title(title)
    if not parsed:
        raise Skip(f"not a conference title: {title[:60]}")
    co, conf, year = parsed
    name = match_company(co, uni)
    if not name:
        raise Skip(f"not our company: {co}")
    year = year or published.year
    paras, verbatim = transcript_part(paras)
    if len(paras) < 10:
        raise RuntimeError(f"only {len(paras)} transcript paragraphs -- page not fully rendered?")
    path = CONF_DIR / f"{slug(name)}_{slug(conf)[:40]}_{published.isoformat()}.txt"
    if path.exists() and not overwrite:
        raise Skip(f"{path.name} already saved")
    path, label = write_conference_file(name, conf, year, published, url, title, paras, verbatim)
    return name, path, label


def _conf_state():
    if CONF_STATE.exists():
        return json.loads(CONF_STATE.read_text(encoding="utf-8"))
    return {"runs": [], "seen": {}}


def sync_conferences(since=None, max_pages=400):
    """Walk the listing pages newest-first, fetch every conference article about one of OUR
    companies (all 160-odd listed names, US included) published on/after `since`
    (default 180 days), stop at the first page that is entirely older. ~1 s per page and
    per article. Returns [(name, path, label)]."""
    if since is None:
        since = date.today() - timedelta(days=180)
    state = _conf_state()
    seen = state["seen"]                       # url -> "saved" | "skip" | "fail"
    uni = universe(everyone=True)
    started = datetime.now()
    todo, pages, oldest = [], 0, None
    for n in range(1, max_pages + 1):
        try:
            rows = list_page(n)
        except Exception as exc:
            print(f"FAIL listing page {n}: {exc}")
            break
        pages = n
        if not rows:
            break
        oldest = min(p for _, _, p in rows)
        for url, title, published in rows:
            if published < since or seen.get(url) in ("saved", "skip"):     # "fail" is retried
                continue
            parsed = conference_from_title(title)
            if parsed and match_company(parsed[0], uni):
                todo.append((url, title, published))
        if oldest < since:
            break
        time.sleep(1)
    print(f"{pages} listing page(s) walked back to {oldest}; {len(todo)} new conference article(s) for our companies")
    saved = []
    for url, title, published in todo:
        try:
            name, path, label = fetch_conference(url, uni, published, title)
            saved.append((name, path, label))
            seen[url] = "saved"
            print(f"saved    {label[:70]:70s} -> {path.relative_to(ROOT)}")
        except Skip as why:
            seen[url] = "skip"
            print(f"skip     {title[:60]:60s} ({why})")
        except Exception as exc:
            seen[url] = "fail"
            print(f"FAIL     {title[:70]}: {exc}")
        time.sleep(1)
    state["runs"].append({"at": started.strftime("%Y-%m-%d %H:%M"), "since": since.isoformat(),
                          "pages": pages, "oldest_seen": oldest.isoformat() if oldest else None,
                          "candidates": len(todo), "saved": len(saved)})
    CONF_STATE.parent.mkdir(exist_ok=True)
    CONF_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    _queue(saved, kind="conference")
    return saved


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sy = sub.add_parser("sync"); sy.add_argument("--since", help="YYYY-MM-DD; default = 120 days ago")
    cf = sub.add_parser("conferences"); cf.add_argument("--since", help="YYYY-MM-DD; default = 180 days ago")
    cf.add_argument("--pages", type=int, default=400, help="max listing pages to walk (36 articles each)")
    f = sub.add_parser("fetch"); f.add_argument("url"); f.add_argument("--company", help="override the name read from the title")
    sub.add_parser("pending")
    dn = sub.add_parser("done"); dn.add_argument("--kind", choices=["transcript", "conference"],
                                                 help="clear only this kind of row (default: whole queue)")
    args = ap.parse_args()

    if args.cmd == "sync":
        rows = sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None)
        print(f"\n{len(rows)} transcript(s) saved; `python investing.py pending` shows the queue")
    elif args.cmd == "conferences":
        rows = sync_conferences(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.pages)
        print(f"\n{len(rows)} conference transcript(s) saved; `python investing.py pending` shows the queue")
    elif args.cmd == "fetch":
        if "earnings-call-transcript-" not in args.url:
            name, path, label = fetch_conference(args.url, universe(everyone=True), overwrite=True)
            state = _conf_state(); state["seen"][args.url] = "saved"
            CONF_STATE.parent.mkdir(exist_ok=True)
            CONF_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
            _queue([(name, path, label)], kind="conference")
            print(f"saved {label} -> {path.relative_to(ROOT)}")
            sys.exit(0)
        name, path, label = fetch_one(args.url, universe(), args.company, overwrite=True)
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"saved": []}
        state["saved"] = sorted(set(state["saved"]) | {args.url})
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
        _queue([(name, path, label)])
        print(f"saved {label} -> {path.relative_to(ROOT)}")
    elif args.cmd == "pending":
        rows = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else []
        for r in rows:
            print(f"{r.get('kind', 'transcript'):10s} {r['company']:32s} {r['label'][:70]:70s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else []
        keep = [r for r in rows if args.kind and r.get("kind", "transcript") != args.kind]
        PENDING.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"queue cleared: {len(rows) - len(keep)} row(s) removed, {len(keep)} kept")
