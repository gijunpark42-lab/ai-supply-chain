"""
utility_filings.py — US utilities' OWN regulatory filings about data-center / large load
-> transcripts/utility_filings/*.txt, queued for `enrich us` (monthly).

Why this exists
---------------
The utility nodes of chains/components/power_cooling.json (Dominion, Southern, AEP, Entergy, Xcel,
NextEra …) say the most about data-center load in documents that never reach an earnings call or an
8-K: Integrated Resource Plans (IRPs), ten-year site plans, large-load / data-center tariff filings
and the quarterly large-load reports they file with their state commission. Those documents are
company-issued (the utility is the filer) and public, but they are huge (an IRP is 300-1,100 pages).
So, like edgar_pull.py, every document is saved TWICE:
    <slug>_<date>_<id>.txt        the whole text, page by page (kept for verification)
    <slug>_<date>_<id>_load.txt   ONLY the pages / paragraphs / tables about data centers, large load,
                                  MW / GW tied to that load, interconnection queues, electric service
                                  agreements, and the transmission / generation build-out for it.
The enricher reads the `_load` file (see .claude/skills/enrich/references/utility_filings.md).

Where documents come from: utility_filings/sources.json (curated, company -> official sources).
Three kinds of source, all public, no login:
    "page"    a page on the utility's own website that links the PDFs (IRP page, regulatory page);
              every PDF link is a candidate, kept or skipped by its title.
    "ga_psc"  a Georgia PSC docket (psc.ga.gov FACTS): the public JSON list the docket page itself
              loads, filtered to documents FILED BY the utility (staff data requests, intervenor
              testimony and commission orders are not company-issued and are skipped).
    "doc"     one document chosen by hand (a big plan that should be read even though it is older
              than the sync window). Taken once, whatever its date.

Commands (python -X utf8 utility_filings.py …)
-----------------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>"]   read every source, save new documents, queue them
    pending [--company "<Company>"] [--market US]        the queue (`enrich us` works it, monthly)
    done --label "<label>" [--why …] | --all             one document handled (or every queued one)
    status [--company "<Company>"]                       every document seen and its state (saved / skip:<why>)
    sources                                              the curated sources, one line each

Files
-----
    utility_filings/sources.json      curated sources (how to add one: its "_how_to_add" block)
    utility_filings/sync_state.json   runs, every document id seen (saved / skip:<why> / enriched:<date>), hashes
    utility_filings/pending.json      saved documents not yet enriched
    transcripts/utility_filings/      the saved text (full + _load)

Sync window (same rule as ir_pull.py): a listed document dated before the company's latest earnings
call in the graph (at most 120 days back; no call -> 30 days) is skipped as "before the window" — the
call already covered that period. `--since` overrides it. "doc" sources ignore the window.

Label: `<Company> regulatory filing: <document short title> (MM-DD-YYYY)`, dated the document (the
commission filing date where the docket gives one, else the date in the title / URL, else the PDF's
creation date). <Company> is the graph node (Southern Company for Georgia Power, NextEra Energy for FPL).
"""

import argparse
import hashlib
import html
import io
import json
import re
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from curl_cffi import requests      # a real Chrome TLS fingerprint -- utility sites block plain requests
except ImportError:
    sys.exit("pip install curl_cffi  (listed in requirements.txt)")
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from taxonomy import market_of              # noqa: E402

META = ROOT / "company_metadata.json"
SOURCES = ROOT / "utility_filings" / "sources.json"
STATE = ROOT / "utility_filings" / "sync_state.json"
PENDING = ROOT / "utility_filings" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "utility_filings"
IR_STATE = ROOT / "ir" / "sync_state.json"     # ir_pull.py's seen URLs: never save a document twice

MAX_BACK = 120          # a first look never reaches further back than this (days)
NO_CALL_BACK = 30       # a company with no earnings call in the graph: this many days
MAX_BYTES = 150_000_000 # a 1,100-page ten-year site plan is ~45 MB; anything far bigger is not a plan
MIN_TEXT = 500          # fewer characters = an image-only scan (no text layer)
PAUSE = 1.5             # seconds between two requests to any host


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def new_state():
    return {"runs": [], "seen": {}, "hashes": {}, "docs": {}}


_session = requests.Session(impersonate="chrome")
_last = [0.0]


def _polite():
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def http_get(url, headers=None, timeout=60, tries=3):
    """GET with a pause before every request and two retries; returns the response or raises."""
    err = None
    for i in range(tries):
        _polite()
        try:
            r = _session.get(url, headers=headers or {}, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 404, 410):
                raise RuntimeError(f"HTTP {r.status_code}")
            err = RuntimeError(f"HTTP {r.status_code}")
        except RuntimeError:
            raise
        except Exception as exc:          # timeouts, resets
            err = exc
        time.sleep(3 * (i + 1))
    raise err


def http_head_date(url):
    """The server's Last-Modified date of a file (cheap: no download), or None."""
    try:
        _polite()
        r = _session.head(url, timeout=30, allow_redirects=True)
        lm = r.headers.get("last-modified")
        return parsedate_to_datetime(lm).date() if lm else None
    except Exception:
        return None


# ---------------------------------------------------------------- which documents are kept

# Titles that are notices or procedure, not a plan or a load report (reason shown in sync_state.json).
NOISE = [
    (r"data request|request for information|\bSTF-[A-Z]+-\d", "data request / response"),
    (r"errata|correction", "errata"),
    (r"notice of|legal notice|affidavit|certificate of service|proof of publication", "notice"),
    (r"\bmotion\b|\bbrief\b|petition to intervene|intervene|appearance|counsel|substitution", "procedural filing"),
    (r"hearing transcript|transcript of", "hearing transcript"),
    (r"\bfee\b|filing fee|app fee", "fee"),
    (r"confidential|non-?disclosure|user guide|access request|request form|data access", "access paperwork"),
    (r"privacy|handbook|rules and regulations|terms (and|&) conditions", "customer paperwork"),
    (r"greenhouse|\bGHG\b|environmental compliance|coal combustion|\bCCR\b|hydro|nuclear uprate|"
     r"renewable integration cost|demand side|\bDSM\b|energy efficiency|potential study|vegetation|storm|"
     r"resilien", "topic outside data-center load"),
    (r"testimony", "testimony (the plan itself is filed separately)"),
]
# A document is kept only when its title says it is a plan, a load report, a large-load / data-center
# tariff or agreement, or a generation / transmission certification (a sources.json entry may override).
KEEP = (r"integrated resource plan|\bIRP\b|resource plan|site plan|load forecast|large[- ]load|\blg load\b|"
        r"data ?cent(er|re)|economic development|electric service agreement|\bESA\b|\bLLCS\b|tariff|"
        r"\bDCO\b|transmission (plan|update|project)|\d+ ?kV|power station|generating (station|facility)|"
        r"certification|capacity|data assumptions|stakeholder|technical conference|interconnection")


def title_verdict(title, src):
    """None when the title is a document to keep; otherwise the reason it is skipped."""
    for pat, why in NOISE + [(p, "excluded for this source") for p in src.get("skip_re", [])]:
        if re.search(pat, title, re.I):
            return why
    if not re.search(src.get("keep_re") or KEEP, title, re.I):
        return "not a plan / load report / large-load tariff (title)"
    return None


# ---------------------------------------------------------------- dates

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"], 1)}


def _ok(y, m, d):
    try:
        x = date(y, m, d)
    except ValueError:
        return None
    return x if 2015 <= y <= date.today().year + 1 else None


def date_in(text):
    """A full date written in a title or URL: 2026_04_24 / 2026-04-24 / 04-24-2026 / 03062026 (mmddyyyy) /
    032825 (mmddyy) / 'April 24, 2026'. None when there is none (a bare year is not a date)."""
    t = text or ""
    for m in re.finditer(r"(20\d\d)[-_.](\d\d)[-_.](\d\d)", t):
        d = _ok(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            return d
    for m in re.finditer(r"(\d\d)[-_.](\d\d)[-_.](20\d\d)", t):
        d = _ok(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return d
    d = written_date(t)
    if d:
        return d
    for m in re.finditer(r"(?<!\d)(\d\d)(\d\d)(20\d\d)(?!\d)", t):          # 03062026
        d = _ok(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return d
    for m in re.finditer(r"(?<![\d.])(\d\d)(\d\d)(\d\d)(?![\d])", t):         # 032825, 100725
        d = _ok(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
        if d:
            return d
    return None


def written_date(text):
    """The first date written out in words ('October 15, 2025') — how a filing's cover letter is dated."""
    for m in re.finditer(r"\b([A-Z][a-z]{2,8})\.? (\d{1,2}), (20\d\d)", text or ""):
        mo = MONTHS.get(m.group(1)[:3].lower())
        d = mo and _ok(int(m.group(3)), mo, int(m.group(2)))
        if d:
            return d
    return None


def pdf_created(reader):
    """The PDF's own creation date (D:20260401105142-04'00') or None."""
    try:
        raw = str((reader.metadata or {}).get("/CreationDate") or "")
    except Exception:
        return None
    m = re.search(r"(20\d\d)(\d\d)(\d\d)", raw)
    return _ok(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------- reading a file

def pdf_pages(content):
    """(reader, [(page number, text)]) of a PDF, whole (pypdf)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, p in enumerate(reader.pages, 1):
        try:
            pages.append((i, (p.extract_text() or "").strip()))
        except Exception:                 # one broken page must not lose the document
            pages.append((i, "[page could not be read]"))
    return reader, pages


def files_of(content, name):
    """[(file name, PDF bytes)] from one download: a PDF itself, or every PDF inside a ZIP (the Georgia PSC
    files a filing's attachments as one zip). Other formats (xlsx, docx) are reported, not read."""
    if content[:5] == b"%PDF-":
        return [(name, content)], []
    if content[:2] == b"PK":
        out, other = [], []
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(".pdf"):
                    out.append((Path(info.filename).name, z.read(info)))
                elif not info.is_dir():
                    other.append(Path(info.filename).name)
        return out, other
    return [], [name]


# ---------------------------------------------------------------- the _load extract

# STRONG = the subject itself. A page is relevant only when it holds at least one STRONG term.
STRONG_RE = re.compile(
    r"(?i)data ?cent(er|re)s?|hyperscal|large[- ]load|\blg load|large (power|customer|commercial|industrial) (customer|load|user)s?|"
    r"\bLLCS|\bLLPS|\bGS-5\b|\bDCO\b|economic development (load|customer|report|project|pipeline)|"
    r"electric service agreements?|\bESAs?\b|interconnection (queue|request)|load (interconnection|queue)|"
    r"contracted (load|capacity|demand)|signed (agreements?|contracts?)|letters? of (agreement|authori[sz]ation)|"
    r"artificial intelligence|\bAI\b|crypto|bitcoin|cloud computing|server farm")
# FORECAST = the load-forecast pages: data-center load is the driver of the forecast even where a table does
# not say "data center" (Dominion's 2025 IRP Update: 22 pages say it, 29 more hold the forecast it drives).
FORECAST_RE = re.compile(r"(?i)load forecast|peak (load|demand) forecast|forecasted (peak|load)")
# WEAK = numbers and build-out that matter only on a page about that load.
WEAK_RE = re.compile(
    r"(?i)\b(MW|GW|MWs|GWs)\b|megawatts?|gigawatts?|peak (load|demand)|load (growth|forecast|additions?)|"
    r"energy (sales|requirements)|capacity (need|position|shortfall)|transmission (capital|investment|projects?|"
    r"expansion|lines?|upgrades?)|substations?|\d+ ?kV|generation (additions?|capital|investment)|"
    r"new (generation|resources)|combined[- ]cycle|combustion turbines?|capital (plan|investment|expenditures?)|"
    r"\bcapex\b|minimum (bill|demand|take|contract)|take[- ]or[- ]pay|contract term|collateral|ramp")
SENT_END = re.compile(r"[.!?:;)\]]\s*$")
BULLET = re.compile(r"^\s*([•▪●◦■\-–]|\(?\d{1,2}[.)]|\(?[a-z][.)])\s+")


def is_numeric_row(line):
    """A table row: three or more numbers and few words."""
    nums = len(re.findall(r"\(?-?\$?\d[\d,]*\.?\d*%?\)?", line))
    words = len(re.findall(r"[A-Za-z]{3,}", line))
    return nums >= 3 and nums >= words


def blocks_of(page_text):
    """Lines of one PDF page grouped into blocks: prose paragraphs (a line ending a sentence, a short line
    or a bullet starts a new one) and tables (runs of numeric rows, kept whole). [(is_table, text)]"""
    lines = [l.rstrip() for l in page_text.splitlines()]
    width = sorted(len(l) for l in lines if l.strip())
    full = width[int(len(width) * 0.75)] if width else 80          # a "full" line on this page
    out = []
    for line in lines:
        if not line.strip():
            if out and out[-1][1]:
                out.append((False, ""))                            # a blank line closes a block
            continue
        table = is_numeric_row(line)
        if out and out[-1][1] and out[-1][0] == table:
            prev_last = out[-1][1].splitlines()[-1]
            ends = (not table) and SENT_END.search(prev_last) and len(prev_last) < 0.8 * full
            if table or not (ends or BULLET.match(line)):
                out[-1] = (table, out[-1][1] + "\n" + line)
                continue
        out.append((table, line))
    return [(t, b) for t, b in out if b.strip()]


def load_extract(pages):
    """The `_load` file body: for every page that mentions the subject (STRONG_RE) or the load forecast
    (FORECAST_RE), the blocks that carry a STRONG, FORECAST or WEAK term, every table whose own text or lead-in
    line carries one, and the block right before a kept table (its title). Other pages are left out.
    Returns (text, pages kept)."""
    parts, kept_pages = [], 0
    for n, text in pages:
        if not (STRONG_RE.search(text or "") or FORECAST_RE.search(text or "")):
            continue
        blocks = blocks_of(text)
        keep = set()
        for i, (is_table, b) in enumerate(blocks):
            lead = blocks[i - 1][1] if i else ""
            if STRONG_RE.search(b) or FORECAST_RE.search(b) or WEAK_RE.search(b):
                keep.add(i)
                if is_table and i:
                    keep.add(i - 1)                                 # the table's title / lead-in
            elif is_table and (STRONG_RE.search(lead) or FORECAST_RE.search(lead) or WEAK_RE.search(lead)):
                keep.update({i - 1, i})
        if keep:
            kept_pages += 1
            body = "\n\n".join(blocks[i][1] for i in sorted(keep))
            parts.append(f"==== page {n} ====\n{body}\n")
    return "\n".join(parts), kept_pages


# ---------------------------------------------------------------- the companies and their sources

def us_companies():
    meta = load(META, {})
    return {n: i for n, i in meta.items() if market_of(i.get("exchange")) == "US"}


def curated(company=None):
    """sources.json without its help block, checked against company_metadata.json (US nodes only)."""
    src = {k: v for k, v in load(SOURCES, {}).items() if not k.startswith("_")}
    us = us_companies()
    for name in list(src):
        if name not in us:
            print(f"  sources.json: '{name}' is not a US company in company_metadata.json — ignored")
            src.pop(name)
    if company:
        if company not in src:
            sys.exit(f"'{company}' has no entry in {SOURCES.relative_to(ROOT)} — add one first (see its _how_to_add)")
        return {company: src[company]}
    return src


LABEL_DATE = re.compile(r"\((\d\d)-(\d\d)-(\d{4})\)")
EARNINGS_LABEL = re.compile(r" Q\d FY\d{4} \(")
_GRAPH = []


def window_start(company):
    """The day before which a listed document is 'before the window' (the ir_pull.py rule): the company's
    newest own earnings call in the graph, at most MAX_BACK days back; no call -> NO_CALL_BACK days."""
    if not _GRAPH:
        _GRAPH.append(load(ROOT / "graph" / "merged_graph.json", {"nodes": []}))
    best = None
    for node in _GRAPH[0].get("nodes", []):
        if node.get("id") != company:
            continue
        for q in node.get("quarterly_data", []):
            lab = q.get("quarter") or ""
            m = LABEL_DATE.search(lab)
            if lab.startswith(company + " ") and EARNINGS_LABEL.search(lab) and m:
                d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                best = d if best is None or d > best else best
    floor = date.today() - timedelta(days=MAX_BACK)
    return max(best, floor) if best else date.today() - timedelta(days=NO_CALL_BACK)


def clean_title(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    t = re.sub(r"\((pdf|PDF)\)|\bPDF\b|&nbsp;", " ", t)
    t = re.sub(r"^\s*(View|Download|Read)\s+", "", t.strip())
    t = re.sub(r"^\s*(DKT|Docket No\.?)\s*[\d &]+[-_:]?\s*", "", t)           # "DKT 55378 Lg Load …"
    t = re.sub(r"\s+(PD|PUBLIC DISCLOSURE|Public Version)\s*$", "", t.strip(), flags=re.I)
    for short, word in (("Lg", "Large"), ("Econ", "Economic"), ("Dev", "Development"), ("Rept?", "Report")):
        t = re.sub(rf"\b{short}\b\.?", word, t)                    # the Georgia PSC's abbreviated titles
    t = t.replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip(" -_|")


def list_page(src):
    """Candidate documents linked from a page on the utility's own site: [{id, url, title, date?}]."""
    r = http_get(src["url"])
    soup = BeautifulSoup(r.text, "html.parser")
    link_re = re.compile(src.get("link_re") or r"\.pdf(\?|$)", re.I)
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = clean_title(a.get_text(" "))
        if not (link_re.search(href) or re.search(r"\(PDF\)", a.get_text(" "))):
            continue
        url = urljoin(r.url, href)
        doc_id = url.split("?")[0]                       # ?rev=… changes with every CMS publish
        title = text or clean_title(Path(urlparse(url).path).stem.replace("-", " ").replace("_", " "))
        if doc_id not in found or len(title) > len(found[doc_id]["title"]):
            found[doc_id] = {"id": doc_id, "url": url, "title": title, "date": date_in(href) or date_in(text),
                             "listed_at": src["url"]}
    return list(found.values())


GA_PSC = "https://psc.ga.gov"


def list_ga_psc(src):
    """Documents of one Georgia PSC docket FILED BY the utility (newest 50) — the JSON the public docket page
    loads (psc.ga.gov/search/facts-docket/?docketId=N). [{id, title, date, document page, filer}]"""
    docket = str(src["docket"])
    page = f"{GA_PSC}/search/facts-docket/?docketId={docket}"
    r = http_get(f"{GA_PSC}/search/service-facts-docket/?docketId={docket}&sortDirection=DESC&sortColumn=Filed"
                 f"&searchText=&pageSize=50&pageNumber=1", headers={"X-Requested-With": "XMLHttpRequest", "Referer": page})
    out = []
    for it in r.json().get("resultsItems", []):
        filers = [c.get("companyName", "").strip() for c in it.get("companyDetailsVm", [])]
        out.append({"id": f"gapsc:{it['documentId']}", "title": clean_title(it.get("description")),
                    "date": datetime.strptime(it["filedDate"][:10], "%Y-%m-%d").date(),
                    "doc_page": f"{GA_PSC}/search/facts-document/?documentId={it['documentId']}",
                    "filers": filers, "has_file": it.get("hasAttachment"), "listed_at": page})
    return out


def ga_psc_files(item):
    """The download links of one Georgia PSC document page: [(file name, url)]."""
    r = http_get(item["doc_page"])
    soup = BeautifulSoup(r.text, "html.parser")
    return [(a.get_text(" ", strip=True) or "attachment", a["href"]) for a in soup.find_all("a", href=True)
            if "/Document/DownloadFile/" in a["href"]]


# ---------------------------------------------------------------- saving one document

def short_label_title(src, title, n=70):
    """'<entity> <title>' cut at a word boundary to ~n characters; no parentheses (they would look like
    the label's date)."""
    entity = src.get("entity") or ""
    t = title if not entity or title.lower().startswith(entity.lower()) else f"{entity} {title}"
    t = re.sub(r"[()\[\]]", "", t).strip()
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0]
    return t


def label_for(company, src, title, d, state):
    base = f"{company} regulatory filing: {short_label_title(src, title)}"
    label, k = f"{base} ({d.strftime('%m-%d-%Y')})", 2
    used = {v.get("label") for v in state["docs"].values()}
    while label in used:                              # two documents, same title, same day
        label, k = f"{base} #{k} ({d.strftime('%m-%d-%Y')})", k + 1
    return label


def take(company, src, item, state, ir_seen):
    """Download one candidate, save the full text + the _load extract, queue it. Returns None (saved),
    a skip reason, or 'later: …' (a network failure: retried next sync)."""
    if item.get("url") and (item["url"] in ir_seen or item["url"].split("?")[0] in ir_seen):
        return "already saved by ir_pull.py"
    if item.get("doc_page"):                                  # Georgia PSC: the document page lists the files
        try:
            links = ga_psc_files(item)
        except Exception as exc:
            return f"later: {exc.__class__.__name__}: {str(exc)[:60]}"
        if not links:
            return "no attachment"
        item["url"] = links[0][1]
    else:
        links = [(Path(urlparse(item["url"]).path).name, item["url"])]

    pdfs, other = [], []
    for name, url in links:
        try:
            r = http_get(url, timeout=300)
        except Exception as exc:
            return f"later: {exc.__class__.__name__}: {str(exc)[:60]}"
        if len(r.content) > MAX_BYTES:
            other.append(f"{name} (too big: {len(r.content) // 1_000_000} MB)")
            continue
        got, rest = files_of(r.content, name)
        pdfs += got
        other += rest
    if not pdfs:
        return "no PDF (" + ", ".join(other)[:80] + ")" if other else "no PDF"

    parts, all_pages, created = [], [], None
    for name, content in pdfs:
        digest = hashlib.sha256(content).hexdigest()
        if digest in state["hashes"]:
            continue                                          # the same file under another listing
        reader, pages = pdf_pages(content)
        created = created or pdf_created(reader)
        if sum(len(t) for _n, t in pages) < MIN_TEXT:
            state["hashes"][digest] = f"image-only ({item['id']})"
            other.append(f"{name} (image-only)")
            continue
        state["hashes"][digest] = item["id"]
        all_pages += [(f"{name} p.{n}" if len(pdfs) > 1 else n, t) for n, t in pages]
        parts += [f"==== {name} — page {n} ====\n{t}\n" for n, t in pages if t]
    if not parts:
        return "same file already saved, or image-only"

    # The document date: the docket's filing date, else a date in the title / URL, else the date written on
    # its first two pages (the cover letter / title page), else the PDF's creation date, else the file's date.
    how = "commission filing date" if item.get("doc_page") else None
    d = item.get("date")
    if d and not how:
        how = "date in the title / URL" if src["kind"] != "doc" else "date given in sources.json"
    if not d:
        d = written_date(" ".join(t for _n, t in all_pages[:2]))
        how = "date written on the first pages" if d else None
    if not d and created:
        d, how = created, "PDF creation date"
    if not d and item.get("modified"):
        d, how = item["modified"], "file's Last-Modified date"
    if not d:
        d, how = date.today(), "no date found: the day it was fetched"
    item["date"] = d
    if src["kind"] != "doc" and d < item["start"]:
        return f"before the window ({d} < {item['start']})"

    extract, kept = load_extract(all_pages)
    if not extract.strip():
        return "no data-center / large-load content"

    label = label_for(company, src, item["title"], d, state)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{slug(company)}_{d.isoformat()}_{slug(item['title'])[:40]}"
    full_path, load_path = OUT_DIR / f"{stem}.txt", OUT_DIR / f"{stem}_load.txt"
    header = [
        f"SOURCE: {item['url']}",
        f"LISTED AT: {item['listed_at']}",
        f"DOCUMENT: {item['title']}" + (f"   (filed by {src['entity']})" if src.get("entity") else ""),
        f"DOCUMENT DATE: {d.isoformat()}   ({how})",
        f"COMPANY: {company}",
        "# NOTE: NOT a transcript — a company-issued regulatory filing (resource plan / large-load report or tariff)",
        "#       the utility filed or posted itself. Facts and the company's own forecasts and plans only; attribute",
        "#       forecasts as the company's; nothing from intervenors or commission staff (enrich skill §2).",
        f"# source label: {label}",
    ]
    full_path.write_text("\n".join(header + [f"# PAGES: {len(all_pages)}" + (f"   not read: {', '.join(other)}" if other else ""),
                                              ""]) + "\n".join(parts), encoding="utf-8")
    load_path.write_text("\n".join(header + [
        f"# EXTRACT: only the {kept} of {len(all_pages)} pages that mention data centers / large load or the load",
        "#          forecast, and on them only the paragraphs and tables about that load (MW / GW, queues, ESAs,",
        "#          the build-out for it).",
        f"#          The whole document: {full_path.relative_to(ROOT).as_posix()}", ""]) + extract, encoding="utf-8")
    state["docs"][item["id"]] = {"company": company, "label": label, "date": d.isoformat(), "url": item["url"],
                                 "file": load_path.relative_to(ROOT).as_posix()}
    pending = load(PENDING, [])
    pending.append({"kind": "filing", "company": company, "label": label, "file": load_path.relative_to(ROOT).as_posix(),
                    "full": full_path.relative_to(ROOT).as_posix(), "date": d.isoformat(), "id": item["id"]})
    save(PENDING, pending)
    print(f"  saved {label}   ({kept}/{len(all_pages)} pages in _load)")
    return None


def candidates(company, src):
    """Every candidate of one source, before the title filter."""
    if src["kind"] == "page":
        return list_page(src)
    if src["kind"] == "ga_psc":
        items = list_ga_psc(src)
        mine = [i for i in items if src["filer"] in i["filers"]]
        return mine
    if src["kind"] == "doc":
        return [{"id": src["url"].split("?")[0], "url": src["url"], "title": src["title"],
                 "date": datetime.strptime(src["date"], "%Y-%m-%d").date() if src.get("date") else None,
                 "listed_at": src.get("listed_at") or src["url"]}]
    raise ValueError(f"unknown source kind {src['kind']!r}")


def sync(since=None, company=None):
    state = load(STATE, new_state())
    for k, v in new_state().items():
        state.setdefault(k, v)
    ir_seen = set(load(IR_STATE, {}).get("seen", {}))
    counts = {"saved": 0, "skipped": 0, "later": 0, "seen": 0}
    for name, entry in curated(company).items():
        start = since or window_start(name)
        print(f"{name}  (window from {start})")
        # "doc" sources first: a hand-picked document must not be pre-empted by the same file seen on a page
        for src in sorted(entry["sources"], key=lambda x: x["kind"] != "doc"):
            try:
                items = candidates(name, src)
            except Exception as exc:                    # one changed site must not stop the others
                print(f"  READ ERR {src['kind']} {src.get('url') or src.get('docket')}: {exc.__class__.__name__}: {str(exc)[:80]}")
                continue
            for item in items:
                if str(state["seen"].get(item["id"], "")).startswith(("saved", "skip", "enriched")):
                    counts["seen"] += 1
                    continue
                item["start"] = start
                why = title_verdict(item["title"], src) if src["kind"] != "doc" else None
                if why is None and src["kind"] != "doc" and item.get("date") and item["date"] < start:
                    why = f"before the window ({item['date']} < {start})"
                if why is None and src["kind"] == "page" and not item.get("date"):
                    lm = item["modified"] = http_head_date(item["url"])   # cheap pre-check before a 40 MB download
                    if lm and lm < start:
                        why = f"before the window (file last modified {lm} < {start})"
                if why is None:
                    why = take(name, src, item, state, ir_seen)
                if why and why.startswith("later"):
                    state["seen"][item["id"]] = why
                    counts["later"] += 1
                    print(f"  later {item['title'][:70]}: {why}")
                    continue
                state["seen"][item["id"]] = "saved" if why is None else f"skip:{why}"
                if why:
                    state.setdefault("skipped", {})[item["id"]] = {"company": name, "title": item["title"][:120],
                                                                  "why": why}
                    print(f"  skip  {item['title'][:70]}: {why}")
                counts["saved" if why is None else "skipped"] += 1
                save(STATE, state)                       # after every document, so an interrupted run resumes
    state["last_sync"] = date.today().isoformat()
    state["runs"].append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                          "since": since.isoformat() if since else "per company (latest call)",
                          "company": company or "all", **counts})
    save(STATE, state)
    print(f"\n{counts['saved']} saved, {counts['skipped']} skipped (reasons in {STATE.relative_to(ROOT).as_posix()}), "
          f"{counts['later']} to retry, {counts['seen']} already handled; queue now {len(load(PENDING, []))}")


def mark_done(rows, why=None):
    state = load(STATE, new_state())
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state.setdefault("seen", {})[r["id"]] = stamp
        if r["id"] in state.get("docs", {}):
            state["docs"][r["id"]]["status"] = stamp
    save(STATE, state)


def status(company=None):
    state, queued = load(STATE, new_state()), {r["id"] for r in load(PENDING, [])}
    for doc_id, d in sorted(state.get("docs", {}).items(), key=lambda kv: kv[1]["date"]):
        if company and d["company"] != company:
            continue
        mark = "queued" if doc_id in queued else state["seen"].get(doc_id, "?")
        print(f"{d['date']}  {mark[:28]:28s} {d['label']}")
    skipped = [v for v in state.get("skipped", {}).values() if not company or v["company"] == company]
    if skipped:
        print(f"\nskipped ({len(skipped)}):")
        for v in skipped:
            print(f"  {v['company'][:20]:20s} {v['title'][:70]:70s} {v['why']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: per company, its latest earnings call (≤120 days) or 30 days")
    s.add_argument("--company")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--market", help="only US companies are covered; accepted for the market commands")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a filing yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    sub.add_parser("sources")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company)
    elif args.cmd == "pending":
        rows = [r for r in load(PENDING, []) if not args.company or r["company"] == args.company]
        if args.market and args.market != "US":
            rows = []
        for r in rows:
            print(f"{r['date']}  {r['company']:22s} {r['label']:100s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit('give --label "<label>" (one filing) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)
    elif args.cmd == "sources":
        for name, entry in curated().items():
            for src in entry["sources"]:
                where = src.get("url") or f"Georgia PSC docket {src.get('docket')} (filer: {src.get('filer')})"
                print(f"{name:22s} {src['kind']:7s} {src.get('entity', ''):26s} {where}")


if __name__ == "__main__":
    main()
