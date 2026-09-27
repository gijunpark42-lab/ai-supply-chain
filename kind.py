"""
kind.py — Korean IR presentations (기업설명회 자료) from the Korea Exchange KIND IR library
→ transcripts/kind/*.txt, queued for `enrich korea`.

Why this exists
---------------
Most Korean names in the graph hold no English earnings call, but they present at 기업설명회
(IR meetings) and post the deck. KRX keeps ONE central library of those decks — the KIND
"IR자료실" (kind.krx.co.kr) — so a single script covers every company that posts there.
Checked 2026-09-27: 34 of our 84 Korean companies posted at least one deck there in 12 months
(ISC, Koh Young, Leeno, Jusung, Simmtech, Park Systems, PSK, Hana Micron, TES, Dongjin …).
The KOSPI large caps post on their own sites instead, so `sync` also reads six of them (SITES below):
Samsung (its official earnings-CALL script -> transcripts/kr_calls/, plus the deck), SK Hynix, SEMCO,
LG Innotek, NAVER and SK Telecom (results decks). Checked the same day: none of the others publishes a
call transcript (SK Hynix / SEMCO / SK Telecom have an audio replay only).

A deck is a company-issued document, NOT a transcript: enrich facts, company targets and
product roadmaps from it (enrich skill §2), written in English (the decks are mostly Korean).

Commands (python -X utf8 kind.py …)
------------------------------------
    sync [--since YYYY-MM-DD]          list the library, save every new deck of OUR companies, queue it
    pending [--company "<Company>"]    the queue (`enrich korea` works it)
    done --label "<label>" [--why …]   one deck handled — enriched, or `--why "no material facts"`
    done --all                         every queued deck handled (only when that is true)
    status [--company "<Company>"]     every deck seen for our companies and its state

Files
-----
    transcripts/kind/<slug>_<YYYY-MM-DD>_<irSeq>.txt   header + the deck's text, page by page
    kind/sync_state.json   last sync date, runs, every irSeq handled (saved / skip:<why> / enriched:<date>),
                           and a hash per saved deck (the same file is often attached to several rows)
    kind/pending.json      saved decks not yet enriched

How KIND answers (found 2026-09-27)
-----------------------------------
List:  POST https://kind.krx.co.kr/corpgeneral/irschedule.do (method=searchIRMaterialsSub, a date range,
       no company = every company) -> an HTML table, EUC-KR. Columns: no, company (with the 5-digit
       issuer code = the first 5 digits of the stock code), date, title (irSeq), attachments.
File:  GET https://kind.krx.co.kr/external/dst/irReference/<irSeq>/<file name> — a plain PDF, no login.
The date column is the IR EVENT date (not the upload date). A web firewall answers a block with
HTTP 200 and "Web firewall" in the body, so every response is checked. One request every 1.1 s.
"""

import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
STATE = ROOT / "kind" / "sync_state.json"
PENDING = ROOT / "kind" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "kind"

BASE = "https://kind.krx.co.kr"
LIST_URL = BASE + "/corpgeneral/irschedule.do"
MAIN = LIST_URL + "?method=searchIRScheduleMain&gubun=iRMaterials"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
FIRST_WINDOW_DAYS = 120    # a first sync reaches back this far (one results season)
MIN_TEXT = 300             # fewer characters than this = an image-only deck (no text layer)


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def universe():
    """{5-digit KIND issuer code: canonical company name} for our Korean companies.
    company_metadata.json writes Korean tickers as '035420.KS'; KIND lists the first 5 digits."""
    out = {}
    for name, info in load(META, {}).items():
        if market_of(info.get("exchange")) != "KR":
            continue
        m = re.search(r"(\d{6})", str(info.get("ticker") or ""))
        if m:
            out[m.group(1)[:5]] = name
    return out


_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
_last = [0.0]


def _polite():
    """One request every 1.1 s (the rate the library was probed at without any throttling)."""
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def _checked(r):
    r.raise_for_status()
    if b"Web firewall" in r.content[:4000]:
        raise RuntimeError("KIND's web firewall blocked the request — wait a while and run sync again")
    return r


def _decode(r):
    """Result pages come back as EUC-KR, the empty-result page as UTF-8 — follow the header."""
    ct = (r.headers.get("content-type") or "").lower()
    return r.content.decode("cp949" if any(x in ct for x in ("euc-kr", "ms949", "cp949")) else "utf-8", "replace")


# ---------------------------------------------------------------- listing and files

def list_page(since, until, page, size=500):
    """One page of the IR library for EVERY company between two IR event dates -> (rows, pages)."""
    _polite()
    r = _checked(_session.post(LIST_URL, data={
        "method": "searchIRMaterialsSub", "forward": "searchirmaterials_sub",
        "currentPageSize": str(size), "pageIndex": str(page), "repIsuSrtCd": "", "marketType": "",
        "title": "", "fromDate": since, "toDate": until, "searchFromDate": since, "searchToDate": until,
    }, headers={"X-Requested-With": "XMLHttpRequest", "Referer": MAIN}, timeout=60))
    html = _decode(r)
    rows = []
    for tr in BeautifulSoup(html, "html.parser").select("table.list tbody tr"):
        td = tr.find_all("td")
        if len(td) < 5:
            continue                                        # "조회된 결과값이 없습니다."
        company_a, title_a = td[1].find("a"), td[3].find("a")
        issuer = re.search(r"companysummary_open\('(\w+)'\)", company_a.get("onclick", "") if company_a else "")
        seq = re.search(r"fnDetailView\('(\d+)'", title_a.get("onclick", "") if title_a else "")
        files = [(a.get("title") or a.get_text(strip=True), urljoin(BASE, quote(a["href"], safe="/:()[]")))
                 for a in td[4].find_all("a", href=True) if a["href"] not in ("", "#")]
        rows.append({"issuer": issuer.group(1) if issuer else None, "kind_name": td[1].get_text(strip=True),
                     "date": td[2].get_text(strip=True), "title": td[3].get_text(strip=True),
                     "irSeq": seq.group(1) if seq else None, "files": files})
    m = re.search(r"전체\s*<em>([\d,]+)</em>\s*건\s*:\s*<strong>\d+</strong>\s*/\s*([\d,]+)", html)
    return rows, int(m.group(2).replace(",", "")) if m else 1


def list_range(since, until):
    rows, pages = list_page(since, until, 1)
    for page in range(2, pages + 1):
        rows += list_page(since, until, page)[0]
    return rows


def download(url):
    _polite()
    return _checked(_session.get(url, headers={"Referer": MAIN}, timeout=180)).content


def pdf_pages(content):
    """[(page number, text)] of a PDF (pypdf; AES-encrypted decks need `cryptography`)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return [(i, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages, 1)]


# ---------------------------------------------------------------- saving one deck

def label_for(company, ir_seq, event_date):
    """English-only source label: '<Company> IR presentation: KIND <irSeq> (MM-DD-YYYY)'. KIND titles are
    Korean and generic ('기업설명회(IR) 개최'), so the irSeq keeps two decks of one day apart."""
    return f"{company} IR presentation: KIND {ir_seq} ({event_date.strftime('%m-%d-%Y')})"


def take(row, company, state):
    """Save one library row (its PDF attachments) for `company`; return a skip reason or None."""
    pdfs = [(name, url) for name, url in row["files"] if name.lower().endswith(".pdf") or "pdf" in url.lower()]
    if not pdfs:
        exts = sorted({name.rsplit(".", 1)[-1].lower() for name, _u in row["files"] if "." in name}) or ["none"]
        return f"no pdf attached ({', '.join(exts)})"
    event = datetime.strptime(row["date"], "%Y-%m-%d").date()
    label = label_for(company, row["irSeq"], event)
    parts, first_url, reasons = [], None, []
    for name, url in pdfs:
        content = download(url)
        if content[:4] != b"%PDF":
            reasons.append("not a PDF")                     # a firewall page or a broken link
            continue
        digest = hashlib.sha256(content).hexdigest()
        if digest in state["hashes"]:                        # the same deck already saved under another row
            reasons.append(f"same file as {state['hashes'][digest]}")
            continue
        pages = pdf_pages(content)
        if sum(len(t) for _n, t in pages) < MIN_TEXT:
            state["hashes"][digest] = f"image-only deck (irSeq {row['irSeq']})"
            reasons.append("image-only deck (no text layer)")
            continue
        state["hashes"][digest] = label
        first_url = first_url or url
        parts += [f"==== {name} — page {n} ====\n{text}\n" for n, text in pages if text]
    if not parts:
        return "; ".join(reasons)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{slug(company)}_{row['date']}_{row['irSeq']}.txt"
    header = [
        f"SOURCE: {first_url}",
        f"KIND ITEM: irSeq {row['irSeq']} — {row['title']} — files: {', '.join(n for n, _u in pdfs)}",
        f"EVENT DATE: {row['date']}   (the IR event date KIND lists, not the upload date)",
        f"COMPANY: {company} (KIND: {row['kind_name']})",
        "# NOTE: NOT a transcript — a company-issued IR presentation (slides). Enrich facts and company targets",
        "#       only; attribute claims; write every entry in English (enrich skill §2, §8).",
        f"# source label: {label}",
        "",
    ]
    path.write_text("\n".join(header) + "\n".join(parts), encoding="utf-8")
    pending = load(PENDING, [])
    pending.append({"kind": "deck", "company": company, "label": label, "file": path.relative_to(ROOT).as_posix(),
                    "date": row["date"], "irSeq": row["irSeq"]})
    save(PENDING, pending)
    print(f"  saved {label}")
    return None


def sync(since=None):
    state = load(STATE, {"last_sync": None, "runs": [], "seen": {}, "hashes": {}})
    ours = universe()
    until = date.today() + timedelta(days=14)              # decks for events a few days ahead are listed early
    if since is None:
        last = state.get("last_sync")
        since = (datetime.strptime(last, "%Y-%m-%d").date() - timedelta(days=7)) if last \
            else date.today() - timedelta(days=FIRST_WINDOW_DAYS)
    rows = list_range(since.isoformat(), until.isoformat())
    mine = [r for r in rows if r["issuer"] in ours and r["irSeq"]]
    saved = skipped = 0
    for row in sorted(mine, key=lambda r: (r["date"], r["irSeq"])):
        if row["irSeq"] in state["seen"]:
            continue
        company = ours[row["issuer"]]
        why = take(row, company, state)
        state["seen"][row["irSeq"]] = "saved" if why is None else f"skip:{why}"
        saved += why is None
        skipped += why is not None
        if why:
            print(f"  skip {company} {row['date']} irSeq {row['irSeq']}: {why}")
        save(STATE, state)                                   # after every row, so an interrupted run resumes
    print(f"KIND library {since} .. {until}: {len(rows)} decks listed, {len(mine)} from our companies, "
          f"{saved} saved, {skipped} skipped")
    site_saved, site_skipped = sync_sites(state)
    state["last_sync"] = date.today().isoformat()
    state["runs"].append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "since": since.isoformat(),
                          "listed": len(rows), "ours": len(mine), "saved": saved, "skipped": skipped,
                          "site_saved": site_saved, "site_skipped": site_skipped})
    save(STATE, state)
    print(f"large-cap IR sites: {site_saved} saved, {site_skipped} skipped; queue now {len(load(PENDING, []))}")


# ---------------------------------------------------------------- the large caps' own IR sites
# KIND holds no decks for the KOSPI large caps: each posts on its own IR site (checked 2026-09-27).
# Samsung is the only one that publishes the CALL itself (an official English script: prepared remarks
# and the full Q&A) -> saved as an earnings-call transcript. The others post the results deck -> saved as
# an IR presentation. SK Hynix, SEMCO and SK Telecom only have an audio replay of the call; NAVER's replay
# sits behind an e-mail check; LG Innotek has no replay. A site that changes its layout makes its function
# find nothing (reported in the run) — the rest keep working.
# The label date is the company's earnings day, read from DART (see earnings_day), so every Korean
# label is dated the same way whatever the site shows.

LATEST_QUARTERS = 2          # only the two latest reported quarters are looked for


def latest_quarters(today=None):
    """The last LATEST_QUARTERS calendar quarters that ended at least 20 days ago -> [(year, quarter)]."""
    today = today or date.today()
    y, q = today.year, (today.month - 1) // 3 + 1          # the running quarter
    out = []
    while len(out) < LATEST_QUARTERS:
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        q_end = date(y, 12, 31) if q == 4 else date(y, 3 * q + 1, 1) - timedelta(days=1)
        if (today - q_end).days >= 20:
            out.append((y, q))
    return out


def earnings_day(company, year, quarter):
    """The day the company reported (year, quarter): its LATEST 영업(잠정)실적 filing on DART within 75 days
    after the quarter ended (Samsung files an early preliminary estimate and the full results on the call
    day — the later one is the call). None when DART has none."""
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        import dart
    code = re.search(r"(\d{6})", str(load(META, {}).get(company, {}).get("ticker") or ""))
    found = dart.corp_code(code.group(1)) if code else None        # {'corp_code': '00126380', 'corp_name': …}
    corp = found.get("corp_code") if isinstance(found, dict) else found
    if not corp:
        return None
    q_end = date(year, 12, 31) if quarter == 4 else date(year, 3 * quarter + 1, 1) - timedelta(days=1)
    data = dart._get("list.json", corp_code=corp, bgn_de=(q_end + timedelta(days=1)).strftime("%Y%m%d"),
                     end_de=(q_end + timedelta(days=75)).strftime("%Y%m%d"), pblntf_ty="I", page_count=100).json()
    days = [r["rcept_dt"] for r in data.get("list", []) if dart.PRELIM_RE.search(r.get("report_nm", ""))]
    return datetime.strptime(max(days), "%Y%m%d").date() if days else None


_GRAPH = {}


def graph_labels(company):
    """Every source label on the company's node in graph/merged_graph.json (read once per run)."""
    if not _GRAPH:
        graph = load(ROOT / "graph" / "merged_graph.json", {"nodes": []})
        for n in graph["nodes"]:
            _GRAPH[n["id"]] = {q.get("quarter") for q in n.get("quarterly_data", [])}
    return _GRAPH.get(company, set())


def _get_page(url, **kw):
    _polite()
    return _checked(_session.get(url, timeout=60, **kw))


def site_samsung():
    docs = []
    for y, q in latest_quarters():
        docs.append({"kind": "call", "year": y, "quarter": q, "title": f"{y} Q{q} earnings call script (official)",
                     "url": f"https://irsvc.teletogether.com/sec/pdf/{y}Q{q}_script_eng.pdf"})
        docs.append({"kind": "deck", "year": y, "quarter": q, "title": f"{y} Q{q} earnings presentation",
                     "url": f"https://images.samsung.com/is/content/samsung/assets/global/ir/docs/{y}_{q}Q_conference_eng.pdf"})
    return docs


def site_skhynix():
    """JSON behind skhynix.com/ir (board 105 = earnings results): one item per quarter, files 1-5."""
    js = _get_page("https://homeapi.skhynix.com/board/list?searchYear=null&searchKeyword=null&bcode=105&lang=ENG"
                   "&page=1&pageSize=20", headers={"Origin": "https://www.skhynix.com",
                                                   "Referer": "https://www.skhynix.com/"}).json()
    # cdnUrl is the full file base ('https://…azureedge.net/web'); fileUrlN is '/attach/<id>.pdf'
    cdn = (js.get("cdnUrl") or js.get("filePath") or "https://mis-prod-koce-homepage-cdn-01-blob-ep.azureedge.net/web").rstrip("/")
    wanted, docs = set(latest_quarters()), []
    for it in js.get("list", []):
        m = re.search(r"FY(20\d\d)\s*Q([1-4])", it.get("title") or "")
        if not m or (int(m.group(1)), int(m.group(2))) not in wanted:
            continue
        for n in range(1, 6):
            name, path = it.get(f"fileName{n}") or "", it.get(f"fileUrl{n}") or ""
            if path and name.lower().endswith(".pdf"):
                docs.append({"kind": "deck", "year": int(m.group(1)), "quarter": int(m.group(2)),
                             "title": f"{it['title']} — {name}", "url": cdn + path if path.startswith("/") else path})
    return docs


def site_semco():
    html = _get_page("https://www.samsungsem.com/global/about-us/investor-relations/earnings-release.do").text
    wanted, docs = set(latest_quarters()), []
    for q, yy in set(re.findall(r"/resources/file/global/ir/earnings_release/([1-4])Q(\d\d)_Earnings_Release_eng\.pdf", html)):
        if (2000 + int(yy), int(q)) in wanted:
            docs.append({"kind": "deck", "year": 2000 + int(yy), "quarter": int(q), "title": f"{q}Q{yy} earnings release",
                         "url": f"https://www.samsungsem.com/resources/file/global/ir/earnings_release/{q}Q{yy}_Earnings_Release_eng.pdf"})
    return docs


def site_lginnotek():
    """report.do lists rows under a year header; each row's button posts to /download/<id>.do."""
    html = _get_page("https://www.lginnotek.com/ir/report.do?locale=en").text
    wanted, docs, year = set(latest_quarters()), [], None
    for m in re.finditer(r"<th[^>]*>\s*(20\d\d)\s*</th>|<td>\s*([1-4])Q Earnings Release\s*</td>\s*<td>(.*?)</td>", html, re.S):
        if m.group(1):
            year = int(m.group(1))
            continue
        fid = re.search(r"lgitFile\.download\('([0-9a-f]{32})'\)", m.group(3) or "")
        if year and fid and (year, int(m.group(2))) in wanted:
            docs.append({"kind": "deck", "year": year, "quarter": int(m.group(2)), "post": True,
                         "title": f"{year} {m.group(2)}Q earnings release",
                         "url": f"https://www.lginnotek.com/download/{fid.group(1)}.do"})
    return docs


def site_naver():
    html = _get_page("https://www.navercorp.com/en/investment/earnings").text
    wanted, docs = set(latest_quarters()), []
    for q, y, uuid in re.findall(r"([1-4])Q (20\d\d) NAVER Earnings Release.*?/api/article/download/([0-9a-f-]{36})\"[^>]*>\s*slides",
                                 html, re.S):
        if (int(y), int(q)) in wanted:
            docs.append({"kind": "deck", "year": int(y), "quarter": int(q), "title": f"{q}Q {y} earnings release slides",
                         "url": f"https://www.navercorp.com/api/article/download/{uuid}"})
    return docs


def site_sktelecom():
    html = _get_page("https://www.sktelecom.com/en/investor/lib/announce.do").text
    wanted, docs = set(latest_quarters()), []
    for folder, q, yy in set(re.findall(r"/img/eng/qua/(\d{8})/([1-4])Q(\d\d)InvestorBriefingENG\.pdf", html)):
        if (2000 + int(yy), int(q)) in wanted:
            docs.append({"kind": "deck", "year": 2000 + int(yy), "quarter": int(q), "title": f"{q}Q{yy} investor briefing",
                         "url": f"https://www.sktelecom.com/img/eng/qua/{folder}/{q}Q{yy}InvestorBriefingENG.pdf"})
    return docs


SITES = {"Samsung": site_samsung, "SK Hynix": site_skhynix, "Samsung Electro-Mechanics": site_semco,
         "LG Innotek": site_lginnotek, "Naver": site_naver, "SK Telecom": site_sktelecom}


def take_site_doc(company, doc, state):
    """Save one site document; return a skip reason, "later" (not posted yet: retried next sync) or None."""
    try:
        _polite()
        r = _session.post(doc["url"], timeout=180) if doc.get("post") else _session.get(doc["url"], timeout=180)
    except requests.RequestException as exc:
        return f"later: {exc.__class__.__name__}"
    if r.status_code == 404:
        return "later: not posted yet"
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return f"later: HTTP {r.status_code}, not a PDF"
    digest = hashlib.sha256(r.content).hexdigest()
    if digest in state["hashes"]:
        return f"same file as {state['hashes'][digest]}"
    day = earnings_day(company, doc["year"], doc["quarter"])
    if day is None:
        return "later: no earnings day on DART yet"
    y, q = doc["year"], doc["quarter"]
    if doc["kind"] == "call":
        label = f"{company} Q{q} FY{y} ({day.strftime('%m-%d-%Y')})"
        if label in graph_labels(company):                  # this call was already enriched (e.g. pasted by hand)
            return "call already in the graph under the same label"
        path = ROOT / "transcripts" / "kr_calls" / f"{slug(company)}_q{q}_{y}.txt"
        note = ("# NOTE: the company's OFFICIAL call script (prepared remarks + Q&A). Management speaks; the Q&A lines",
                "#       '[Name, Firm] Q.' are analysts — context only (enrich skill §2). Write entries in English.")
    else:
        label = f"{company} IR presentation: Q{q} {y} results ({day.strftime('%m-%d-%Y')})"
        path = OUT_DIR / f"{slug(company)}_{day.isoformat()}_q{q}_{y}_site.txt"
        note = ("# NOTE: NOT a transcript — a company-issued results presentation from its own IR site. Facts and",
                "#       company targets only; attribute claims; write entries in English (enrich skill §2, §8).")
    pages = pdf_pages(r.content)
    if sum(len(t) for _n, t in pages) < MIN_TEXT:
        state["hashes"][digest] = f"image-only ({doc['url']})"
        return "image-only document (no text layer)"
    state["hashes"][digest] = label
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [f"SOURCE: {doc['url']}", f"TITLE: {doc['title']}", f"COMPANY: {company}",
              f"QUARTER: Q{q} {y}   EARNINGS DAY: {day.isoformat()} (DART 영업(잠정)실적 filing date)", *note,
              f"# source label: {label}", ""]
    path.write_text("\n".join(header) + "".join(f"==== page {n} ====\n{t}\n" for n, t in pages if t), encoding="utf-8")
    pending = load(PENDING, [])
    pending.append({"kind": doc["kind"], "company": company, "label": label,
                    "file": path.relative_to(ROOT).as_posix(), "date": day.isoformat(), "irSeq": doc["url"]})
    save(PENDING, pending)
    print(f"  saved {label}")
    return None


def sync_sites(state):
    """Every large-cap site: new documents of the latest quarters. Returns (saved, skipped)."""
    state.setdefault("sites", {})
    saved = skipped = 0
    for company, finder in SITES.items():
        try:
            docs = finder()
        except Exception as exc:                            # a changed site must not stop the others
            print(f"  {company}: site read failed ({exc.__class__.__name__}: {str(exc)[:80]}) — check its layout")
            continue
        if not docs:
            print(f"  {company}: nothing listed for {latest_quarters()} (layout changed, or not posted yet)")
        for doc in docs:
            if state["sites"].get(doc["url"], "").startswith(("saved", "skip", "enriched")):
                continue
            why = take_site_doc(company, doc, state)
            if why and why.startswith("later"):
                state["sites"][doc["url"]] = why            # retried next sync
                continue
            state["sites"][doc["url"]] = "saved" if why is None else f"skip:{why}"
            saved += why is None
            skipped += why is not None
            save(STATE, state)
    return saved, skipped


def mark_done(rows, why=None):
    state = load(STATE, {"last_sync": None, "runs": [], "seen": {}, "hashes": {}, "sites": {}})
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        # KIND rows are keyed by irSeq; large-cap site documents by their URL
        state.setdefault("sites" if str(r["irSeq"]).startswith("http") else "seen", {})[r["irSeq"]] = stamp
    save(STATE, state)


def status(company=None):
    """Every saved deck / call script (optionally one company's) with its state and queue mark."""
    queued = {r["file"] for r in load(PENDING, [])}
    for folder in (OUT_DIR, ROOT / "transcripts" / "kr_calls"):
        for f in sorted(folder.glob("*.txt")) if folder.exists() else []:
            head = f.read_text(encoding="utf-8").split("\n", 9)
            co = next((l.split(": ", 1)[1].split(" (KIND")[0] for l in head if l.startswith("COMPANY: ")), "?")
            if company and co != company:
                continue
            rel = f.relative_to(ROOT).as_posix()
            print(f"{'queued' if rel in queued else 'handled':8s} {rel}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD (IR event date); default: 7 days before the last sync, or 120 days")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a deck yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None)
    elif args.cmd == "pending":
        rows = [r for r in load(PENDING, []) if not args.company or r["company"] == args.company]
        for r in rows:
            print(f"{r['date']}  {r['company']:28s} {r['label']:70s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit('give --label "<label>" (one deck) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)


if __name__ == "__main__":
    main()
