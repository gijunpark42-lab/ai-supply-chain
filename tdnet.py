"""
tdnet.py — Japan TDnet timely disclosures (適時開示) of our Japanese companies → transcripts/tdnet/*.txt,
queued for `enrich japan`.

Why this exists
---------------
Most Japanese names in the graph hold no English earnings call on Investing.com, but every listed Japanese
company must file its results (決算短信), forecast revisions, capex / plant decisions, mid-term plans, major
agreements and M&A on TDnet, the Tokyo Stock Exchange's timely-disclosure network, on the day they happen.
TSE shows every filing of the last 31 days on ONE public list, so one script covers all our Japanese companies.

A TDnet filing is a company-issued document, NOT a transcript: enrich facts, company forecasts and plans from
it (enrich skill §2), written in English. The one exception is a results-meeting Q&A record (決算説明会の
質疑応答 / 書き起こし): management answers there, so it is treated like a conference talk.

Commands (python -X utf8 tdnet.py …)
------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>" …]   list TDnet, save every new important filing, queue it
    pending [--company "<Company>"] [--market JP]       the queue (`enrich japan` works it)
    done --label "<label>" [--why …]                    one filing handled — enriched, or `--why "no material facts"`
    done --all                                          every queued filing handled (only when that is true)
    status [--company "<Company>"]                      every filing seen for our companies and its state

Files
-----
    transcripts/tdnet/<slug>_<YYYY-MM-DD>_<doc id>[_qa].txt   header + the PDF's text, page by page
    tdnet/sync_state.json   last sync, runs (with skip-reason counts), every document id seen for our companies
                            {company, date, title, lang, category, status = saved / skip:<why> / enriched:<date>},
                            each company's first-sync window, and a hash per saved PDF
    tdnet/pending.json      saved filings not yet enriched

How TDnet answers (found 2026-10-01)
------------------------------------
Japanese list:  GET https://www.release.tdnet.info/inbs/I_main_00.html names the days online
                (I_list_001_YYYYMMDD.html); each day is split into pages of 100 rows (I_list_002_…, …).
                Row = time, 5-character code (4-character stock code + "0"; e.g. 80350 = 8035, 268A0 = 268A),
                company name, title -> <doc id>.pdf (relative to /inbs/), XBRL zip, exchange.
English list:   the "Company Announcements Service" (https://www.release.tdnet.info/index_e.html) — its public
                search form POSTs t0/t1 (YYYYMMDD), q (empty = everything) and p (page, 200 rows) to
                /onsf/TDJFSearch_e/TDJFSearch_e. The English PDFs live under /inbs/ek/. An English version
                carries its own doc id (not the Japanese one) and often a later time on the same day.
Files:          plain PDFs, no login. One request every 1.1 s with a normal browser User-Agent.
LIMIT:          TDnet keeps only about 31 days online (both lists). A sync gap longer than that loses filings
                for good — run it at least every 3 weeks. Older filings are only on each company's IR site.
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

import requests
from bs4 import BeautifulSoup

from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
STATE = ROOT / "tdnet" / "sync_state.json"
PENDING = ROOT / "tdnet" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "tdnet"

BASE = "https://www.release.tdnet.info"
MAIN = BASE + "/inbs/I_main_00.html"
DAY_PAGE = BASE + "/inbs/I_list_{page:03d}_{day}.html"
EN_SEARCH = BASE + "/onsf/TDJFSearch_e/TDJFSearch_e"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
MIN_TEXT = 200             # fewer characters than this = an image-only PDF (no text layer)
HOLD_DAYS = 2              # a Japanese filing waits this long for its English version before it is saved
EN_MATCH_DAYS = 7          # an English filing of the same type within this many days = the same document
RESYNC_OVERLAP = 3         # a later sync re-lists this many days before the last sync


# ---------------------------------------------------------------- which filings are kept
# Checked on the TITLE, in this order: (1) corrections, (2) the distinctive report types, (3) notices that look
# like results, (4) results, (5) the notices we never enrich, (6) the operating-fact types, (7) anything else =
# "other notice type". Every skip is recorded
# in sync_state.json with its reason and the title, never silently. Japanese and English patterns side by side.

CORRECTION = re.compile(r"訂正|\bcorrection|\bamendment|\bpartial (revision|change) (to|of) (the )?(notice|announcement)", re.I)

# (category, pattern) — step 2: distinctive titles, kept even when they also name a dividend
REPORTS = [
    ("qa", r"書き起こし|質疑応答|\bQ\s*&\s*A\b|\btranscript\b|question[- ]and[- ]answer"),
    ("deck", r"説明会資料|説明資料|補足資料|決算補足|プレゼンテーション|成長可能性に関する|"
             r"\bpresentation\b|\bsupplementary (material|information|data)|\bbriefing (material|session material)|"
             r"\bfact ?book\b|\bdata ?book\b"),
    ("forecast", r"業績予想|通期予想|予想値と実績値|"
                 r"\b(earnings|financial|business|results|performance|operating|consolidated|full[- ]year)\b"
                 r"[\w ,()-]{0,30}\bforecasts?\b|\bforecasts? (of|for) (the )?(financial|business|operating|consolidated)"),
    ("plan", r"中期経営計画|中期計画|長期ビジョン|経営計画|"
             r"\b(medium|mid)[- ]term (management |business )?plan|\blong[- ]term (vision|plan)|\bmanagement plan\b"),
]

# step 3: notices that LOOK like results (a results-date notice, a one-off gain / loss) — skipped before step 4
EARLY_SKIPS = [
    ("results-date notice", r"開示予定日|発表予定日|発表日|開示が.{0,20}超え|延期|"
                            r"\b(disclosure|announcement|release) date\b|\bpostpone|\bdelay|\bexceed(ed|s|ing)? \d+ days"),
    ("one-off gain / loss", r"投資有価証券|特別利益|特別損失|減損|評価損|"
                            r"\binvestment securities\b|\bextraordinary (income|gains?|loss(es)?)\b|\bimpairment\b"),
]

# step 4: the results themselves
RESULTS = r"決算短信|四半期決算|出荷額|売上高（速報|速報値|" \
          r"\bfinancial results\b|\bkessan\b|\bresults? for the\b|\b(quarterly|annual|consolidated) results\b|" \
          r"\bshipments\b|\bpreliminary (results|sales|figures)\b"

# step 5: never enriched (enrich skill §2). An alliance / acquisition title is spared by the lookahead.
NOT_DEAL = r"^(?!.*(提携|買収|alliance|acquisition of (shares|equity|a company|the business)))"
SKIPS = [
    ("dividend", r"配当|剰余金|\bdividends?\b"),
    ("buyback / treasury stock", NOT_DEAL + r".*(自己株式|自己株|\btreasury (shares|stock)|\bown shares\b|"
                                            r"\brepurchase\b|\bbuy-?backs?\b)"),
    ("stock compensation", r"株式報酬|譲渡制限付株式|ストック・?オプション|新株予約権|業績連動型株式|株式給付|持株会|"
                           r"\brestricted (stock|share)|\bstock options?\b|\b(stock|share)[- ]based compensation|"
                           r"\b(stock|share) compensation|\b(stock|share) acquisition rights|\bemployee stock"),
    ("officer change", r"役員|人事|代表取締役|取締役候補|執行役員|監査役|"
                       r"\b(directors?|officers?|representative|president|ceo|cfo|auditors?|executives?)\b"
                       r"[\w ,]{0,40}\b(change|changes|appointment|appointed|retire|resign|candidates?|duties|responsibilit)|"
                       r"\btransfer of [\w ]{0,20}officers\b|"
                       r"\b(change|changes|appointment|retirement|resignation)s? (of|in|to)\b[\w ,]{0,40}"
                       r"\b(directors?|officers?|representative|president|ceo|cfo|auditors?|executives?)\b|\bpersonnel\b"),
    ("governance", r"ガバナンス|内部統制|監査|定款|独立役員|政策保有|買収防衛|"
                   r"\bgovernance\b|\binternal control|\baudit|\barticles of incorporation|\bindependent (officer|director)|"
                   r"\btakeover defen"),
    ("shareholder meeting", r"株主総会|\bgeneral meeting\b|\bshareholders['’]? meeting|\bAGM\b"),
    ("ESG / CSR", r"サステナビリティ|ＥＳＧ|\bESG\b|CSR|統合報告|人的資本|TCFD|"
                  r"\bsustainability\b|\bintegrated report|\bhuman capital|\bclimate\b"),
    ("financing", NOT_DEAL + r".*(社債|借入|コミットメントライン|格付|第三者割当|新株式発行|増資|株式の売出し|"
                             r"ローン|\bbonds?\b|\bnotes\b|\bborrowing|\bloans?\b|\bcredit rating|\bcommitment line|"
                             r"\bthird[- ]party allotment|\bissuance of (new )?shares|\bshare offering|\bsecondary offering)"),
    ("listing / share admin", r"株式分割|株主優待|単元株|投資単位|上場|株式の併合|"
                              r"\binvestment units?\b|\bstock split|\bshare split|\bshareholder (benefit|incentive)|\blisting\b|\bshare unit"),
    ("monthly / routine report", r"月次|月度|\bmonthly\b|\bbalance of\b"),
]

# step 6: operating facts
FACTS = [
    ("capex", r"設備投資|工場|生産能力|増産|新棟|生産拠点|製造拠点|新拠点|固定資産の取得|"
              r"\bcapital (investment|expenditure)|\bcapex\b|\bplant\b|\bfactory\b|\bfab\b|\bproduction capacity|"
              r"\bmanufacturing (site|facility|base|plant)|\bnew (building|facility)|\bcapacity (expansion|increase)|"
              r"\bacquisition of (fixed|non-?current) assets|\bproduction (base|site|line)"),
    ("M&A", r"買収|子会社化|(?<!自己)株式の取得|(?<!自己)株式取得|事業譲渡|事業の譲受|事業譲受|合併|会社分割|吸収分割|"
            r"事業.{0,12}(譲渡|譲受|承継)|公開買付|子会社の異動|株式交換|株式移転|持分法|出資|スピンオフ.{0,20}(実行|完了)|"
            r"\btransfer .{0,30}subsidiar|\bsale of (shares in )?(a )?subsidiar|\bdivest|"
            r"\b(equity |follow-on |additional )?investment in\b|\b(follow-on|additional|equity) investment\b|\bspin-?off\b.{0,40}\bcomplet|\bcomplet\w* .{0,30}spin-?off|"
            r"\bacquisition\b|\bacquire|\bmerger\b|\btender offer|\bbusiness transfer|\btransfer of (the )?business|"
            r"\bchange in (a |the )?(specified |consolidated )?subsidiar|\bshare exchange|\bcompany split|"
            r"\babsorption-type|\bmake .{0,40} a (wholly[- ]owned )?subsidiary"),
    ("agreement", r"契約|業務提携|資本提携|提携|合意|受注|共同開発|"
                  r"\bagreement\b|\balliance\b|\bpartnership\b|\bcontract\b|\bjoint (development|venture)|"
                  r"\borders? received|\breceipt of [\w ]{0,30}orders?\b|\bmemorandum of understanding|\bMOU\b"),
]

CATEGORY_NAMES = {"qa": "results-meeting Q&A record", "deck": "results / IR presentation", "results": "earnings release",
                  "forecast": "forecast revision", "plan": "mid-term / management plan", "capex": "capex / plant notice",
                  "M&A": "M&A notice", "agreement": "supply / customer / alliance agreement"}


def classify(title):
    """('keep', category) or ('skip', reason) for one filing title."""
    t = title.replace("　", " ")
    if CORRECTION.search(t):
        return "skip", "correction"
    for cat, pat in REPORTS:
        if re.search(pat, t, re.I):
            return "keep", cat
    for why, pat in EARLY_SKIPS:
        if re.search(pat, t, re.I):
            return "skip", why
    if re.search(RESULTS, t, re.I):
        return "keep", "results"
    for why, pat in SKIPS:
        if re.search(pat, t, re.I):
            return "skip", why
    for cat, pat in FACTS:
        if re.search(pat, t, re.I):
            return "keep", cat
    return "skip", "other notice type"


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def new_state():
    return {"last_sync": None, "runs": [], "companies": {}, "seen": {}, "hashes": {}}


def universe():
    """{5-character TDnet code: canonical company name} for our Japanese companies.
    company_metadata.json writes '8035.T', '6857' or '268A.T'; TDnet lists the code + '0'."""
    out = {}
    for name, info in load(META, {}).items():
        if market_of(info.get("exchange")) != "JP":
            continue
        m = re.match(r"^(\d[0-9A-Z]{3})(\.T)?$", str(info.get("ticker") or "").strip().upper())
        if m:                                              # 'ASETEK.OL' (Oslo, mislabelled OSE) is not a TSE code
            out[m.group(1) + "0"] = name
    return out


_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
_last = [0.0]


def _polite():
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def fetch(url, data=None, tries=3):
    """GET (or POST when `data`), politely, with a short retry on network errors / 5xx."""
    for attempt in range(tries):
        _polite()
        try:
            r = _session.post(url, data=data, timeout=90) if data is not None else _session.get(url, timeout=120)
            if r.status_code < 500:
                return r
        except requests.RequestException:
            if attempt == tries - 1:
                raise
        time.sleep(3 * (attempt + 1))
    return r


def page_text(page):
    """One PDF page as text, blank lines and trailing spaces dropped. pypdf's plain mode (as kind.py uses):
    it sometimes splits an English word ('th at') but keeps numbers whole — the layout mode was tried
    2026-10-01 and split numbers ('202  6') and returned nothing on the 決算短信 summary pages."""
    lines = (l.strip() for l in (page.extract_text() or "").splitlines())
    return "\n".join(l for l in lines if l)


def pdf_pages(content):
    """[(page number, text)] of a PDF (pypdf), every page."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return [(i, page_text(p)) for i, p in enumerate(reader.pages, 1)]


# ---------------------------------------------------------------- the two lists

def days_online():
    """Every day TDnet still shows (YYYYMMDD strings, oldest first)."""
    html = fetch(MAIN).text
    return sorted(set(re.findall(r"I_list_001_(\d{8})\.html", html)))


def _clean(s):
    return re.sub(r"\s+", " ", s.replace("　", " ")).strip()


def japanese_day(day):
    """Every row TDnet lists for one day (all pages)."""
    rows, page, pages = [], 1, 1
    while page <= pages:
        r = fetch(DAY_PAGE.format(page=page, day=day))
        if r.status_code == 404:
            break
        html = r.content.decode("utf-8", "replace")
        if page == 1:
            pages = max([1] + [int(p) for p in re.findall(r"I_list_(\d{3})_%s\.html" % day, html)])
        for tr in BeautifulSoup(html, "html.parser").select("tr"):
            code, name, title = tr.select_one("td.kjCode"), tr.select_one("td.kjName"), tr.select_one("td.kjTitle")
            a = title.find("a", href=True) if title else None
            if not (code and a and a["href"].lower().endswith(".pdf")):
                continue
            hhmm = _clean(tr.select_one("td.kjTime").get_text()) if tr.select_one("td.kjTime") else "00:00"
            rows.append({"lang": "ja", "id": a["href"].rsplit("/", 1)[-1][:-4], "code": _clean(code.get_text()),
                         "tdnet_name": _clean(name.get_text()), "title": _clean(a.get_text()),
                         "date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "time": hhmm,
                         "url": f"{BASE}/inbs/{a['href'].rsplit('/', 1)[-1]}"})
        page += 1
    return rows


def english_range(t0, t1):
    """Every row of the English Company Announcements Service between two YYYYMMDD days."""
    rows, page = [], 1
    while True:
        html = fetch(EN_SEARCH, data={"t0": t0, "t1": t1, "q": "", "p": str(page)}).content.decode("utf-8", "replace")
        found = 0
        for tr in BeautifulSoup(html, "html.parser").select("table#maintable tr"):
            when, code, name, title = (tr.select_one(f"td.{c}") for c in ("time", "code", "companyname", "title"))
            a = title.find("a", href=True) if title else None
            if not (when and code and a and a["href"].lower().endswith(".pdf")):
                continue
            found += 1
            d, _sp, hhmm = _clean(when.get_text()).partition(" ")
            rows.append({"lang": "en", "id": "e" + a["href"].rsplit("/", 1)[-1][:-4], "code": _clean(code.get_text()),
                         "tdnet_name": _clean(name.get_text()), "title": _clean(a.get_text()),
                         "date": d.replace("/", "-"), "time": hhmm, "url": BASE + a["href"]})
        total = re.search(r"Total\s+([\d,]+)\s+Announcements", html)
        if not found or not total or page * 200 >= int(total.group(1).replace(",", "")):
            break
        page += 1
    return rows


# ---------------------------------------------------------------- labels and saving

EARNINGS_LABEL = re.compile(r" Q\d FY\d{4} \(")


def short_title(title, n=60):
    """An English title for the label: ASCII, without 'Notice Regarding …', at most n characters."""
    t = re.sub(r"^\s*\(?(\([^)]*\)\s*)*", "", title)          # '(Update on Disclosed Matter) …'
    t = re.sub(r"^(notice|announcement)s? (regarding|concerning|of|on|about|for|in relation to)\s+(the\s+)?", "", t, flags=re.I)
    t = re.sub(r"[^\x20-\x7e]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .,:;-")
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(" ,;:-(")
        if t.count("(") > t.count(")"):                  # cut inside a bracket: drop the open bracket part
            t = t[:t.rindex("(")].rstrip(" ,;:-")
    return t[:1].upper() + t[1:]


def label_for(company, row):
    """`<Company> TDnet: <short English title | release <doc id>> (MM-DD-YYYY)`, dated the disclosure day."""
    d = datetime.strptime(row["date"], "%Y-%m-%d")
    title = short_title(row["title"]) if row["lang"] == "en" else ""
    if len(title) < 8:
        title = "release " + row["id"].lstrip("e")
    label = f"{company} TDnet: {title} ({d.strftime('%m-%d-%Y')})"
    # a title such as '… Q2 FY2026' would read as an earnings-call label to the pipelines — write 'fiscal'
    return re.sub(r" (Q\d) FY(\d{4}) \(", r" \1 fiscal \2 (", label) if EARNINGS_LABEL.search(label) else label


def save_row(company, row, category, state):
    """Download, read and save one filing; return a skip reason or None."""
    r = fetch(row["url"])
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return f"later: HTTP {r.status_code}, not a PDF"
    digest = hashlib.sha256(r.content).hexdigest()
    if digest in state["hashes"]:
        return f"same file as {state['hashes'][digest]}"
    pages = pdf_pages(r.content)
    if sum(len(t) for _n, t in pages) < MIN_TEXT:
        state["hashes"][digest] = f"image-only PDF ({row['id']})"
        return "image-only PDF (no text layer)"
    label = label_for(company, row)
    state["hashes"][digest] = label
    qa = category == "qa"
    path = OUT_DIR / f"{slug(company)}_{row['date']}_{row['id']}{'_qa' if qa else ''}.txt"
    if qa:
        note = ("# NOTE: a results-meeting Q&A record the company filed on TDnet — management answers; questions are",
                "#       analysts (context only, enrich skill §2). Treat it like a conference talk. Entries in English.")
    else:
        note = ("# NOTE: NOT a transcript — a company-issued TDnet timely disclosure (%s). Facts, company forecasts"
                % CATEGORY_NAMES[category],
                "#       and plans only; attribute claims; write every entry in English (enrich skill §2, §8).")
    lang = ("English version (TDnet Company Announcements Service)" if row["lang"] == "en" else
            "Japanese original — no English version listed on TDnet; write the entries in English")
    header = [
        f"SOURCE: {row['url']}",
        f"TITLE: {row['title']}",
        f"DOCUMENT TYPE: {CATEGORY_NAMES[category]} (TDnet timely disclosure)",
        f"DATE: {row['date']} {row['time']} JST   (TDnet disclosure time)",
        f"COMPANY: {company} (TDnet code {row['code']}, listed as {row['tdnet_name']})",
        f"LANGUAGE: {lang}",
        *note,
        f"# source label: {label}",
        "",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + "".join(f"==== page {n} ====\n{t}\n" for n, t in pages if t), encoding="utf-8")
    pending = load(PENDING, [])
    pending.append({"kind": "qa" if qa else "filing", "company": company, "label": label,
                    "file": path.relative_to(ROOT).as_posix(), "date": row["date"], "id": row["id"],
                    "category": category, "lang": row["lang"], "title": row["title"]})
    save(PENDING, pending)
    print(f"  saved {label}")
    return None


def _days_apart(a, b):
    return abs((datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days)


def counterpart(row, category, rows, seen, claimed):
    """The other-language version of `row`: the nearest English row of the same company and type within
    EN_MATCH_DAYS (for a Japanese row), or an already SAVED Japanese filing of that type (for an English row).
    Pairs are one-to-one (`claimed` holds the ids already paired): two Japanese results releases and one
    English one -> the second Japanese release is still saved."""
    if row["lang"] == "ja":
        near = sorted((_days_apart(o["date"], row["date"]), o["id"]) for o in rows
                      if o["lang"] == "en" and o["code"] == row["code"] and o.get("category") == category
                      and o["id"] not in claimed and _days_apart(o["date"], row["date"]) <= EN_MATCH_DAYS)
    else:
        near = sorted((_days_apart(s["date"], row["date"]), doc_id) for doc_id, s in seen.items()
                      if s.get("lang") == "ja" and s.get("code") == row["code"] and s.get("category") == category
                      and str(s.get("status", "")).startswith(("saved", "enriched")) and doc_id not in claimed
                      and _days_apart(s["date"], row["date"]) <= EN_MATCH_DAYS)
    if not near:
        return None
    claimed.add(near[0][1])
    return near[0][1]


def already_paired(seen):
    """Ids that already stand in for the other language (from earlier syncs' skip reasons)."""
    out = set()
    for s in seen.values():
        m = re.search(r"(English|Japanese) version (e?\d+)", str(s.get("status", "")))
        if m:
            out.add(m.group(2))
    return out


def first_start(company):
    """A company's first sync reaches back to its latest earnings call in the graph (at most 120 days), else
    30 days — the same rule as ir_pull.py. TDnet itself only reaches back ~31 days."""
    import warnings
    with warnings.catch_warnings():                       # ir_pull's docstring trips a SyntaxWarning on first compile
        warnings.simplefilter("ignore", SyntaxWarning)
        from ir_pull import last_source_date
    return last_source_date(company)


def sync(since=None, companies=None):
    state = load(STATE, new_state())
    for k, v in new_state().items():
        state.setdefault(k, v)
    ours = universe()
    if companies:                                        # --company (repeatable): only these, one listing
        missing = set(companies) - set(ours.values())
        if missing:
            sys.exit(f"{sorted(missing)} not Japanese companies with a TSE code in company_metadata.json")
        ours = {c: n for c, n in ours.items() if n in companies}
    today = date.today()
    online = days_online()
    if not online:
        sys.exit("TDnet listed no days — check https://www.release.tdnet.info/inbs/I_main_00.html")
    last = state.get("last_sync")
    starts = {}
    for code, name in ours.items():
        if since:
            starts[name] = since
        elif name in state["companies"] and last:
            starts[name] = datetime.strptime(last, "%Y-%m-%d").date() - timedelta(days=RESYNC_OVERLAP)
        else:
            starts[name] = first_start(name)
    oldest = min(starts.values()).strftime("%Y%m%d")
    days = [d for d in online if d >= oldest]
    if oldest < online[0]:
        print(f"note: TDnet keeps only {online[0]} .. {online[-1]} online; nothing older can be fetched")
    print(f"listing TDnet {days[0]} .. {days[-1]} ({len(days)} days, Japanese + English lists) …")
    rows = []
    for d in days:
        rows += japanese_day(d)
    rows += english_range(days[0], days[-1])
    mine = [r for r in rows if r["code"] in ours
            and r["date"] >= starts[ours[r["code"]]].isoformat()]
    for r in mine:
        r["verdict"], r["category"] = classify(r["title"])
    # English first, so a Japanese filing can see that its English version was just saved
    mine.sort(key=lambda r: (r["lang"] != "en", r["date"], r["time"], r["id"]))
    counts = {"saved": 0, "skipped": 0, "later": 0}
    reasons = {}
    claimed = already_paired(state["seen"])                # one English filing stands for one Japanese filing
    for row in mine:
        prev = state["seen"].get(row["id"], {}).get("status", "")
        if prev and not prev.startswith("later"):
            continue
        name = ours[row["code"]]
        if row["verdict"] == "skip":
            why = row["category"]
        else:
            other = counterpart(row, row["category"], mine, state["seen"], claimed)
            if row["lang"] == "ja" and other:
                why = f"English version {other} listed"
            elif row["lang"] == "en" and other:
                why = f"Japanese version {other} already saved"
            elif row["lang"] == "ja" and (today - date.fromisoformat(row["date"])).days < HOLD_DAYS:
                why = "later: waiting for an English version"
            else:
                why = save_row(name, row, row["category"], state)
        status = "saved" if why is None else (why if why.startswith("later") else "skip:" + why)
        state["seen"][row["id"]] = {"company": name, "code": row["code"], "date": row["date"], "lang": row["lang"],
                                    "category": row["category"] if row["verdict"] == "keep" else None,
                                    "title": row["title"], "status": status}
        bucket = "saved" if why is None else "later" if why.startswith("later") else "skipped"
        counts[bucket] += 1
        if bucket == "skipped":
            key = why if not why.startswith(("English", "Japanese", "same file")) else why.split(" ")[0] + " duplicate"
            reasons[key] = reasons.get(key, 0) + 1
        if why and row["verdict"] == "keep":
            print(f"  {'hold' if bucket == 'later' else 'skip'} {name} {row['date']} {row['id']}: {why}")
        save(STATE, state)                                   # after every row, so an interrupted run resumes
    for name in starts:
        state["companies"].setdefault(name, {"first_sync": today.isoformat(), "since": starts[name].isoformat()})
    if not companies:
        state["last_sync"] = today.isoformat()
    state["runs"].append({"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "days": f"{days[0]}..{days[-1]}",
                          "companies": companies, "listed": len(rows), "ours": len(mine), **counts,
                          "skip_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1]))})
    save(STATE, state)
    print(f"TDnet {days[0]} .. {days[-1]}: {len(rows)} filings listed, {len(mine)} from our companies — "
          f"{counts['saved']} saved, {counts['skipped']} skipped, {counts['later']} held for an English version")
    if reasons:
        print("skipped: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    print(f"queue now {len(load(PENDING, []))} (`python tdnet.py pending`)")


# ---------------------------------------------------------------- queue commands

def mark_done(rows, why=None):
    state = load(STATE, new_state())
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state["seen"].setdefault(r["id"], {"company": r["company"], "date": r["date"]})["status"] = stamp
    save(STATE, state)


def status(company=None):
    """Every filing seen for our companies (optionally one company) with its state."""
    seen = load(STATE, new_state())["seen"]
    rows = sorted(((s.get("date", ""), s.get("company", "?"), doc_id, s) for doc_id, s in seen.items()
                   if not company or s.get("company") == company))
    for d, co, doc_id, s in rows:
        print(f"{d}  {co:26s} {doc_id:22s} {str(s.get('status'))[:48]:48s} {s.get('title', '')[:70]}")
    print(f"{len(rows)} filings seen")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: 3 days before the last sync, or the company's first-sync window")
    s.add_argument("--company", action="append", help="repeatable; default: every Japanese company")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--market", help="accepted for symmetry with the other pipelines; every row is JP")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a filing yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company)  # a list or None
    elif args.cmd == "pending":
        meta = load(META, {})
        rows = [r for r in load(PENDING, []) if (not args.company or r["company"] == args.company)
                and (not args.market or market_of(meta.get(r["company"], {}).get("exchange")) == args.market)]
        for r in rows:
            print(f"{r['date']}  {r['company']:26s} {r['label']:80s} {r['file']}")
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


if __name__ == "__main__":
    main()
