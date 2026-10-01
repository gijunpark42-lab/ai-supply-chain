"""
mops.py — Taiwan MOPS (公開資訊觀測站) company filings -> transcripts/mops/*.txt, queued for `enrich taiwan`.

Why this exists
---------------
Every TWSE / TPEx company files to MOPS: the deck of each 法人說明會 (investor conference), its 重大訊息
(material information) and its monthly revenue. Investing.com / tw.py cover the CALLS; ir_pull.py the press
releases of the companies that run an IR feed. MOPS is the one place that holds the company's own decks and
filings for every Taiwanese company in company_metadata.json (market TW), so one script covers them all.

Three document kinds (each saved once, by its MOPS id):
  deck      the presentation PDF filed for each 法說會 (the English file when one is filed, else the Chinese one).
            Label: `<Company> IR presentation: MOPS <file id> (MM-DD-YYYY)`, dated the conference.
  material  重大訊息, IMPORTANT ones only (see KEEP / SKIP below): customer / supply orders, capacity and capex
            resolutions, plant incidents, guidance, M&A operating facts.
            Label: `<Company> MOPS material information: release <code>-<YYYYMMDD>-<serial> (MM-DD-YYYY)`,
            dated the filing day (subjects are Chinese, so the id stands in for an English title).
  revenue   the monthly revenue report — ONLY for companies with no ir_pull feed (user, 2026-10-01: the feed
            companies post their monthly revenue release there; MOPS would save it twice).
            Label: `<Company> MOPS monthly revenue: <Month YYYY> (MM-DD-YYYY)` (date: see revenue_label).

None is a transcript: enrich facts, company guidance and targets only (enrich skill §2), in English (§8).

Commands (python -X utf8 mops.py …)
------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>"]   fetch new decks / material information / revenue, queue them
    pending [--company …] [--kind deck|material|revenue] [--market TW]   the queue (`enrich taiwan` works it)
    done --label "<label>" [--why …]                    one document handled (or `--why "no material facts"`)
    done --all                                          every queued document handled (only when that is true)
    status [--company "<Company>"]                      per company: saved / enriched / pending / skipped

Files
-----
    transcripts/mops/<slug>_<YYYY-MM-DD>_<kind>_<id>.txt   header + the document text
    mops/sync_state.json   runs, per-company last sync, every id handled (saved / skip:<why> / enriched:<date>),
                           deck hashes, and `skip_rules` (what is skipped and why, rewritten every sync)
    mops/pending.json      saved documents not yet enriched

Where MOPS answers (found 2026-10-01; no login, no token)
---------------------------------------------------------
Decks:    POST https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1 (TYPEK sii|otc, ROC year, month) — the 法說會
          list (same endpoint tw.py reads; the new MOPS site forwards this page to it). Each row names the filed
          files `<code><YYYYMMDD>M001.pdf` (Chinese) / `…E001.pdf` (English). The list's own download form
          (/server-java/FileDownLoad) is WAF-blocked for scripts; the same file store is served read-only by
          TWSE's document server: GET https://doc.twse.com.tw/nas/STR/<file name>.
Material: POST https://mops.twse.com.tw/mops/api/t05st01 (JSON: companyId, ROC year, month "all") — the
          company's 歷史重大訊息 list; POST …/api/t05st01_detail (companyId, marketKind, enterDate, serialNumber)
          — one filing's full text. These are the JSON calls the official MOPS web app itself makes.
Revenue:  POST https://mops.twse.com.tw/mops/api/t05st10_ifrs (companyId, dataType 2, ROC year, month).
A WAF block answers HTTP 200 with "FOR SECURITY REASONS" — every response is checked. One request every 1.1 s.
"""

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
FEEDS = ROOT / "ir" / "feeds.json"
STATE = ROOT / "mops" / "sync_state.json"
PENDING = ROOT / "mops" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "mops"
IR_DIR = ROOT / "transcripts" / "ir"

DECK_LIST = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
DECK_FILE = "https://doc.twse.com.tw/nas/STR/"
API = "https://mops.twse.com.tw/mops/api/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
MIN_TEXT = 300               # fewer characters than this = an image-only deck (no text layer)
RESYNC_OVERLAP = 7           # a later sync re-reads this many days before the last one (late filings)

# ---------------------------------------------------------------- what material information is kept
# Checked in this order on the filing's SUBJECT (主旨): the first SKIP that matches wins, then a KEEP must match,
# otherwise the filing is skipped as "not an important type". Kept narrow on purpose: "簽訂聯貸合約" (a loan) is
# financing even though 簽訂 / 合約 also mark an order.
SKIP = [
    (r"股利|配息|除息|除權|股息|盈餘(不)?分配|盈餘(不)?分派|現金減資", "dividend"),
    (r"庫藏股|買回(本公司)?股份|買回股票|實施股份買回|回購", "treasury stock"),
    (r"董事長|總經理|發言人|財務長|會計主管|稽核主管|研發主管|公司治理主管|資訊安全長|經理人|法人董事|獨立董事"
     r"|監察人|董事.{0,6}(變動|異動|辭任|改選|補選|解任)|審計委員|薪資報酬委員|人事|辭任|退休|新任|接任",
     "personnel"),
    (r"董事會.{0,8}(召開|開會)日期|召開董事會|股東(常|臨時)?會|股東會|董事會.{0,12}(財務報告|財報)|財務報告|財報"
     r"|自結|合併損益|會計師|內部控制|公司章程|員工酬勞|董事酬勞|董監酬勞|停止過戶|基準日|印鑑", "routine board / results / governance"),
    (r"公司債|可轉換|轉換公司債|可轉債|交換公司債|現金增資|私募|減資|籌資|海外存託憑證|存託憑證|GDR|ECB"
     r"|背書保證|資金貸與|貸款|借款|聯貸|授信|融資|額度|票券|商業本票|發行新股|新股增資|增資發行|辦理增資"
     r"|員工認股|認股權|限制員工權利新股|註銷", "financing / securities"),
    (r"法人說明會|法說會|說明會|投資論壇|受邀參加|受邀參|法人與會|座談會|投資人會議|業績發表會", "investor-conference notice (decks: see deck kind)"),
    (r"營收|營業收入", "monthly revenue notice (the revenue report is its own kind)"),
    (r"澄清|媒體報導|報載|價量異常|注意交易資訊|公布注意|處置", "media clarification / trading-attention notice"),
    (r"有價證券|基金|債券|公債|定存|理財|金融商品|衍生性|匯率|外幣|貨幣市場|ETF", "treasury / financial investment"),
    (r"獎項|榮獲|獲頒|得獎|ESG|永續|捐贈|公益|碳權", "award / ESG / CSR"),
    (r"解散|清算|更名|遷址|地址變更|變更.{0,6}(名稱|地址)", "subsidiary housekeeping"),
    (r"訴訟|判決|仲裁|裁定|起訴|檢調|搜索", "litigation (not a kept type)"),
]
KEEP = [
    (r"火災|火警|爆炸|氣爆|停工|停產|停電|斷電|地震|颱風|水災|淹水|災害|意外|事故|洩漏|罷工|網路攻擊|資安|駭客|勒索|系統異常", "incident"),
    (r"財務預測|財測|營運展望|展望|預估|預計.{0,10}(營收|出貨|產能)", "guidance"),
    (r"合併|收購|併購|購併|公開收購|股份轉換|分割|合資|股權|股份|普通股|特別股|子公司.{0,10}(設立|成立|新設)|(設立|成立|新設).{0,10}子公司",
     "M&A / investment"),
    (r"訂單|接獲|得標|簽訂|簽署|合約|契約|供貨|供應|採購案|合作|策略聯盟|聯盟|備忘錄|MOU|授權|委託.{0,6}(生產|製造)|代工",
     "order / supply / partnership"),
    (r"資本支出|資本預算|擴建|擴廠|建廠|新建|興建|新廠|產能|廠房|取得.{0,12}(機器|設備|不動產|土地|廠|使用權資產)"
     r"|(機器|生產)設備|不動產|土地|使用權資產", "capacity / capex"),
]
# Capacity / capex filings are usually one asset purchase each (`取得機器設備`, `取得使用權資產`, a plot of land).
# Thresholds on the largest amount the filing states (items 1-5 of the asset template), converted to NT$:
#   - machinery / equipment / right-of-use assets: at least NT$1 billion (≈ US$31 million) — below that a purchase
#     rarely changes capacity, and large filers (Foxconn, Quanta) file dozens a month;
#   - a SITE (land, buildings, a plant or its facility works: 土地 / 廠房 / 建物 / 廠辦 / 不動產 / 廠務 / 工程, read
#     from the subject and item 1 only): at least NT$200 million — a new site is a capacity fact even for a small
#     cap (Auras' NT$~225 million Thai plant site, 05-2026; Gold Circuit's Thai plant facility works, 09-2026).
# A subject naming a capacity PLAN (資本支出 / 資本預算 / 擴建 / 擴廠 / 建廠 / 新建 / 興建 / 新廠 / 產能) is kept at any
# amount. M&A by share purchase (`股權`, `普通股`) uses the NT$1 billion threshold unless the subject says
# merger / acquisition (合併 / 收購 / 併購 / 公開收購 / 股份轉換 / 分割 / 合資), which is kept at any amount.
CAPEX_MIN_TWD = 1_000_000_000
SITE_MIN_TWD = 200_000_000
SITE = re.compile(r"土地|廠房|建物|廠辦|不動產|廠務|工程")
CAPACITY_PLAN = re.compile(r"資本支出|資本預算|擴建|擴廠|建廠|新建|興建|新廠|產能")
TAKEOVER = re.compile(r"合併|收購|併購|購併|公開收購|股份轉換|分割|合資")
# Filter-only conversion to NT$ (the amount itself is never written to the graph from this table).
TO_TWD = {"NT": 1, "US": 32, "CN": 4.5, "JP": 0.21, "EU": 35, "TH": 0.9, "VN": 0.0012, "MX": 1.7, "IN": 0.38}
CURRENCY = [(r"新台幣|新臺幣|台幣|臺幣|NTD|NT\$|TWD", "NT"), (r"美金|美元|USD|US\$", "US"),
            (r"人民幣|RMB|CNY", "CN"), (r"日圓|日幣|日元|JPY", "JP"), (r"歐元|EUR", "EU"), (r"泰銖|THB", "TH"),
            (r"越南盾|VND", "VN"), (r"墨西哥披索|墨西哥比索|MXN", "MX"), (r"印度盧比|INR", "IN")]
UNIT = {"千": 1e3, "仟": 1e3, "萬": 1e4, "百萬": 1e6, "億": 1e8, "thousand": 1e3, "million": 1e6, "billion": 1e9}
_CUR = "|".join(p for p, _c in CURRENCY)
# '新台幣 32,604 千元' (currency first) and '約2.5億泰銖' (number first)
AMOUNT_POST = re.compile(r"([\d,]+(?:\.\d+)?)\s*(百萬|千|仟|萬|億)?\s*元?\s*(%s)" % _CUR, re.I)
AMOUNT = re.compile(r"(%s)\s*[:：]?\s*(?:約)?\s*([\d,]+(?:\.\d+)?)\s*(百萬|千|仟|萬|億|thousand|million|billion)?"
                    % "|".join(p for p, _c in CURRENCY), re.I)


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    """Temp file + swap: OneDrive / antivirus can hold the file for a moment on Windows."""
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
    return re.sub(r"[^a-z0-9]", "", name.lower())


def roc(d):
    return d.year - 1911


def roc_date(s):
    """'115/09/04' or '1150904' -> date(2026, 9, 4)."""
    m = re.match(r"(\d{3})/?(\d\d)/?(\d\d)$", s.strip())
    return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None


def universe(company=None):
    """{stock code: canonical name} for our Taiwanese companies (market TW)."""
    out = {}
    for name, info in load(META, {}).items():
        if market_of(info.get("exchange")) != "TW" or info.get("status") != "public":
            continue
        if company and name != company:
            continue
        m = re.search(r"(\d{4,6})", str(info.get("ticker") or ""))
        if m:
            out[m.group(1)] = name
    return out


_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"})
_last = [0.0]


def _polite():
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def _checked(r):
    r.raise_for_status()
    if b"FOR SECURITY REASONS" in r.content[:4000]:
        raise RuntimeError("MOPS's web firewall blocked the request — wait a while and run sync again")
    return r


def api(name, payload):
    """One call to the MOPS web app's JSON API -> result dict, or None when MOPS has no data (code 406)."""
    _polite()
    js = _checked(_session.post(API + name, json=payload, timeout=60,
                                headers={"Referer": "https://mops.twse.com.tw/mops/"})).json()
    if js.get("code") == 200:
        return js.get("result")
    if js.get("code") == 406:                                   # 查無相符資料 = nothing filed
        return None
    raise RuntimeError(f"MOPS {name}: {js.get('code')} {js.get('message')}")


def pdf_pages(content):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return [(i, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages, 1)]


def enqueue(row):
    pending = load(PENDING, [])
    if not any(r["label"] == row["label"] for r in pending):
        pending.append(row)
        save(PENDING, pending)


def same_day_release(company, day):
    """An ir_pull release of the same company and day (ir files are <slug>_<YYYY-MM-DD>_<title>.txt)."""
    if not IR_DIR.exists():
        return []
    return sorted(p.relative_to(ROOT).as_posix() for p in IR_DIR.glob(f"{slug(company)}_{day.isoformat()}_*.txt"))


def write_doc(path, header, body):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + "\n\n" + body.rstrip() + "\n", encoding="utf-8")


_HAND_SAVED = []


def hand_saved(token):
    """A document saved earlier by hand (outside transcripts/mops) whose SOURCE line names this MOPS id."""
    if not _HAND_SAVED:
        found = {}
        for f in (ROOT / "transcripts").rglob("*.txt"):
            if f.parent == OUT_DIR:
                continue
            try:
                head = f.open(encoding="utf-8", errors="ignore").read(600)
            except OSError:
                continue
            if head.startswith("SOURCE:") and ("twse.com.tw" in head or "MOPS" in head):
                found[f.relative_to(ROOT).as_posix()] = head
        _HAND_SAVED.append(found)
    return next((p for p, head in _HAND_SAVED[0].items() if token in head), None)


# ---------------------------------------------------------------- since: same rule as ir_pull

def first_since(company):
    """A company's FIRST sync reaches back to its latest earnings call in the graph (cap 120 days), else 30 days
    — ir_pull.last_source_date, reused so both pipelines start from the same day."""
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        from ir_pull import last_source_date
    return last_source_date(company)


def company_since(company, state, since):
    if since:
        return since
    last = state.get("companies", {}).get(company, {}).get("last_sync")
    if last:
        return datetime.strptime(last[:10], "%Y-%m-%d").date() - timedelta(days=RESYNC_OVERLAP)
    return first_since(company)


def months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------------------------------------------------------------- decks (法人說明會)

def deck_rows(year, month):
    """Every 法說會 of one month, listed and OTC -> [{code, date, subject, files: [M…, E…]}]."""
    rows = []
    for typek in ("sii", "otc"):
        _polite()
        r = _checked(_session.post(DECK_LIST, data={
            "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
            "TYPEK": typek, "year": str(year - 1911), "month": f"{month:02d}"}, timeout=60))
        r.encoding = "utf-8"
        for tr in re.findall(r"<tr[^>]*data-type='body'[^>]*>(.*?)</tr>", r.text, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(cells) < 8:
                continue
            text = [html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", c))).strip() for c in cells]
            when = roc_date(text[2])
            if not when:
                continue
            files = re.findall(r'fileName\.value="([^"]+)"', tr)
            rows.append({"code": text[0], "zh": text[1], "date": when, "place": text[4], "subject": text[5][:300],
                         "files": files, "market": typek})
    return rows


def deck_label(company, file_id, day):
    return f"{company} IR presentation: MOPS {file_id} ({day.strftime('%m-%d-%Y')})"


def take_deck(company, row, state):
    """Save one 法說會 deck (English file first); return None when saved, else a skip reason ('later: …' = retry)."""
    files = row["files"]
    english = [f for f in files if re.search(r"E\d{3}\.pdf$", f, re.I)]
    chinese = [f for f in files if f not in english]
    if not files:
        return "later: no file filed yet" if (date.today() - row["date"]).days <= 7 else "no file filed"
    # A company files ONE deck and names it under every broker event it presents at (Elite Material: one file,
    # eight August events), so the file name is the deck's id: seen once, saved once, dated its earliest event.
    by_file = state.setdefault("deck_files", {})
    for name in files:
        if name in by_file:
            return f"same file as {by_file[name]}"
    reasons = []
    for name in english + chinese:                        # the English file wins; the Chinese one is the fallback
        file_id = name.rsplit(".", 1)[0]
        dup = hand_saved(file_id)
        if dup:
            return f"already saved as {dup}"
        r = None
        for attempt in range(3):                           # the document server drops a connection now and then
            _polite()
            try:
                r = _session.get(DECK_FILE + name, timeout=180)
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    return f"later: {name} {exc.__class__.__name__}"   # never fall back to Chinese on a network error
                time.sleep(5 * (attempt + 1))
        if r.status_code == 404:
            return f"later: {name} not on the document server yet"
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            reasons.append(f"{name}: HTTP {r.status_code}, not a PDF")
            continue
        digest = hashlib.sha256(r.content).hexdigest()
        if digest in state["hashes"]:                      # the same deck filed again for another broker event
            return f"same file as {state['hashes'][digest]}"
        pages = pdf_pages(r.content)
        if sum(len(t) for _n, t in pages) < MIN_TEXT:
            state["hashes"][digest] = f"image-only deck ({name})"
            reasons.append(f"{name}: image-only (no text layer)")
            continue
        label = deck_label(company, file_id, row["date"])
        state["hashes"][digest] = label
        for other in files:
            by_file[other] = label                         # its other-language twin is the same deck
        lang = "English" if name in english else "Chinese (no English file filed)"
        path = OUT_DIR / f"{slug(company)}_{row['date'].isoformat()}_deck_{file_id}.txt"
        header = [
            f"SOURCE: {DECK_FILE}{name}",
            f"MOPS ITEM: 法人說明會 {row['code']} {row['zh']} — files filed: {', '.join(files)} — saved: {name} ({lang})",
            f"EVENT DATE: {row['date'].isoformat()}   (the conference date MOPS lists)",
            f"EVENT: {row['subject']}",
            f"PLACE: {row['place']}",
            f"COMPANY: {company} (MOPS: {row['code']} {row['zh']})",
            "# NOTE: NOT a transcript — a company-issued investor-conference presentation (slides) filed to MOPS.",
            "#       Enrich facts and company targets only; attribute claims; write every entry in English (enrich",
            "#       skill §2, §8). The call itself (if any) comes through investing.py / tw.py and is the primary source.",
            f"# source label: {label}",
        ]
        write_doc(path, header, "".join(f"==== page {n} ====\n{t}\n" for n, t in pages if t))
        enqueue({"kind": "deck", "company": company, "label": label, "file": path.relative_to(ROOT).as_posix(),
                 "date": row["date"].isoformat(), "id": f"deck:{file_id}"})
        print(f"  saved {label}")
        return None
    return "; ".join(reasons) or "no PDF"


def sync_decks(ours, starts, state, stats):
    first = min(starts.values())
    until = date.today() + timedelta(days=14)               # decks for events a few days ahead are filed early
    for y, m in months_between(first, until):
        try:
            rows = deck_rows(y, m)
        except Exception as exc:                            # material information and revenue still run
            print(f"  deck list {y}-{m:02d} failed ({exc.__class__.__name__}: {str(exc)[:80]}) — "
                  "mopsov.twse.com.tw unreachable; the next sync retries (rows are remembered per id)")
            stats["deck_list_failed"] = stats.get("deck_list_failed", 0) + 1
            continue
        for row in sorted(rows, key=lambda r: r["date"]):    # earliest event first: it dates the deck
            company = ours.get(row["code"])
            if not company or row["date"] < starts[company]:
                continue
            key = f"deck:{row['code']}:{row['date'].isoformat()}:{','.join(row['files']) or 'nofile'}"
            if key in state["seen"] and not state["seen"][key].startswith("later"):
                continue
            why = take_deck(company, row, state)
            state["seen"][key] = "saved" if why is None else (why if why.startswith("later") else f"skip:{why}")
            stats["deck_saved" if why is None else "deck_skipped"] += why is None or not why.startswith("later")
            if why:
                print(f"  {'wait' if why.startswith('later') else 'skip'} {company} deck {row['date']}: {why}")
            save(STATE, state)


# ---------------------------------------------------------------- material information (重大訊息)

def classify(subject):
    """('keep', category) or ('skip', reason) from the subject alone."""
    s = re.sub(r"\s+", "", subject)
    for pat, why in SKIP:
        if re.search(pat, s, re.I):
            return "skip", why
    for pat, cat in KEEP:
        if re.search(pat, s, re.I):
            return "keep", cat
    return "skip", "not an important type"


def max_amount_twd(text):
    """The largest money amount a filing states, in NT$ (filter use only). For the asset-acquisition template
    only items 1-5 are read (item 5 = quantity, unit price and TOTAL amount)."""
    head = text
    cut = re.search(r"(?m)^\s*6[.．、]", text)
    if cut and re.search(r"(?m)^\s*5[.．、]", text[:cut.start()]):
        head = text[:cut.start()]
    best = 0.0
    for m in AMOUNT.finditer(head):
        cur = next(c for p, c in CURRENCY if re.fullmatch(p, m.group(1), re.I))
        try:
            n = float(m.group(2).replace(",", ""))
        except ValueError:
            continue
        unit = m.group(3) or ""
        # '新台幣32,604千元': the unit sits right after the number; '元' alone = 1
        best = max(best, n * UNIT.get(unit.lower() if unit.isascii() else unit, 1) * TO_TWD[cur])
    for m in AMOUNT_POST.finditer(head):
        cur = next(c for p, c in CURRENCY if re.fullmatch(p, m.group(3), re.I))
        try:
            n = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        best = max(best, n * UNIT.get(m.group(2) or "", 1) * TO_TWD[cur])
    return best


def material_id(params):
    """'2382-20260904-1' from the detail parameters (MOPS enterDate is ROC: 1150904)."""
    return f"{params['companyId']}-{roc_date(params['enterDate']).strftime('%Y%m%d')}-{params['serialNumber']}"


def material_label(company, mid, day):
    return f"{company} MOPS material information: release {mid} ({day.strftime('%m-%d-%Y')})"


def take_material(company, item, state):
    """item = one t05st01 row. Return None when saved, else the skip reason."""
    code, _zh, day_s, _t, subject, link = item[:6]
    kind, cat = classify(subject)
    if kind == "skip":
        return cat
    p = link["parameters"]
    detail = api("t05st01_detail", p)
    if not detail or not detail.get("data"):
        return "later: detail not available"
    d = detail["data"][0]
    # [serial, date, time, speaker, speaker title, phone, subject, clause (第N款), fact date, description]
    serial, speaker, title, clause, fact_day, body = d[0], d[3].strip(), d[4].strip(), d[7].strip(), d[8].strip(), d[9]
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    if cat in ("capacity / capex", "M&A / investment"):
        plan = CAPACITY_PLAN.search(subject) if cat == "capacity / capex" else TAKEOVER.search(subject)
        amount = max_amount_twd(body)
        # item 6 = the counterparty and its relation. '母子公司' there = an intra-group deal: a capital injection
        # into an own subsidiary ('現金增資不適用；母子公司') or a transfer between group companies — not M&A.
        item6 = (re.search(r"(?s)^\s*6[.．、](.*?)^\s*7[.．、]", body, re.M) or ["", ""])[1]
        if cat == "M&A / investment" and not plan and "母子公司" in item6:
            return "intra-group capital injection / transfer (financing, not M&A)"
        # item 1 = what is acquired; drop the template's own example '（如坐落台中市…土地）' before matching
        item1 = re.sub(r"[（(]如[^）)]*[）)]", "", (re.search(r"(?s)^\s*1[.．、](.*?)^\s*2[.．、]", body, re.M) or ["", ""])[1])
        site = cat == "capacity / capex" and SITE.search(subject + item1)
        floor = SITE_MIN_TWD if site else CAPEX_MIN_TWD
        if not plan and amount < floor:
            return (f"{cat} below the NT${floor / 1e6:,.0f} million threshold (largest amount stated ≈ "
                    f"NT${amount / 1e6:,.0f} million)" if amount
                    else f"{cat} with no amount stated and no capacity plan in the subject")
    day = roc_date(day_s)
    mid = material_id(p)
    label = material_label(company, mid, day)
    path = OUT_DIR / f"{slug(company)}_{day.isoformat()}_material_{mid}.txt"
    header = [
        f"SOURCE: {API}t05st01_detail  (POST {json.dumps(p, ensure_ascii=False)}; MOPS 歷史重大訊息 t05st01)",
        f"MOPS ITEM: 重大訊息 {code} {_zh} — filed {day.isoformat()} {d[2].strip()} — {clause} — kept as: {cat}",
        f"SUBJECT: {re.sub(r'\s+', ' ', subject).strip()}  (original language; write entries in English)",
        f"FILED BY: {speaker} ({title})   FACT DATE: {fact_day}",
        f"COMPANY: {company} (MOPS: {code} {_zh})",
        "# NOTE: NOT a transcript — a company filing (material information) to MOPS. Facts and company guidance only;",
        "#       never financing terms or the price of an acquisition; write every entry in English (enrich skill §2, §8).",
    ]
    for rel in same_day_release(company, day):
        header.append(f"# SEE ALSO: {rel} (a same-day company release — enrich each fact once)")
    header.append(f"# source label: {label}")
    write_doc(path, header, body)
    enqueue({"kind": "material", "company": company, "label": label, "file": path.relative_to(ROOT).as_posix(),
             "date": day.isoformat(), "id": f"mi:{mid}", "category": cat})
    print(f"  saved {label}  [{cat}]")
    return None


def sync_material(ours, starts, state, stats):
    today = date.today()
    for code, company in sorted(ours.items(), key=lambda x: x[1]):
        start = starts[company]
        for year in range(start.year, today.year + 1):
            try:
                res = api("t05st01", {"companyId": code, "year": str(year - 1911), "month": "all",
                                      "firstDay": "", "lastDay": ""})
            except Exception as exc:                        # one company's failure must not stop the others
                print(f"  {company}: material list failed ({exc.__class__.__name__}: {str(exc)[:80]})")
                continue
            for item in (res or {}).get("data", []):
                day = roc_date(item[2])
                p = item[5].get("parameters", {}) if isinstance(item[5], dict) else {}
                if not day or day < start or not p:
                    continue
                key = f"mi:{material_id(p)}"
                if key in state["seen"] and not state["seen"][key].startswith("later"):
                    continue
                why = take_material(company, item, state)
                state["seen"][key] = "saved" if why is None else (why if why.startswith("later") else f"skip:{why}")
                if why is None:
                    stats["material_saved"] += 1
                elif not why.startswith("later"):
                    state["seen"][key] += " | " + re.sub(r"\s+", " ", item[4]).strip()[:80]   # the subject, for audits
                    stats["material_skipped"] += 1
                    stats["skip_reasons"][why.split(" (")[0]] = stats["skip_reasons"].get(why.split(" (")[0], 0) + 1
            save(STATE, state)


# ---------------------------------------------------------------- monthly revenue (no-feed companies only)

REV_ROWS = {"本月": "This month", "去年同期": "Same month last year", "增減金額": "Change (NT$ thousand)",
            "增減百分比": "Change %", "本年累計": "Year to date", "去年累計": "Same period last year",
            "備註/營收變化原因說明": "Note / reason for the change (as filed)"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def revenue_label(company, y, m, filed):
    return f"{company} MOPS monthly revenue: {MONTHS[m - 1]} {y} ({filed.strftime('%m-%d-%Y')})"


def take_revenue(company, code, y, m, state):
    res = api("t05st10_ifrs", {"companyId": code, "dataType": "2", "year": str(y - 1911), "month": str(m),
                               "subsidiaryCompanyId": ""})
    if not res or not res.get("data"):
        return "later: not filed yet"
    # MOPS shows no filing timestamp. Revenue is due by the 10th of the next month, so the label is dated the
    # day this sync first saw it, capped at that deadline (never later than the true filing day + one sync gap).
    deadline = (date(y + (m == 12), m % 12 + 1, 10))
    filed = min(date.today(), deadline)
    label = revenue_label(company, y, m, filed)
    path = OUT_DIR / f"{slug(company)}_{filed.isoformat()}_revenue_{y}{m:02d}.txt"
    lines = [f"{REV_ROWS.get(k, k)} ({k}): {v}" for k, v in res["data"]]
    header = [
        f"SOURCE: {API}t05st10_ifrs  (POST companyId={code}, year={y - 1911}, month={m}; MOPS 每月營收 t05st10_ifrs)",
        f"MOPS ITEM: 每月營業收入 {code} {res.get('companyAbbreviation', '')} {res.get('marketKindName', '')} — month "
        f"{y}-{m:02d} (yymm {res.get('yymm')})",
        f"FILED: on or before {filed.isoformat()} (MOPS shows no filing time; due by {deadline.isoformat()})",
        f"COMPANY: {company} (MOPS: {code})",
        "# NOTE: NOT a transcript — the company's monthly revenue report to MOPS (consolidated net revenue,",
        "#       NT$ thousand). Write the figures as filed (no arithmetic); English only (enrich skill §2, §8).",
        f"# source label: {label}",
    ]
    write_doc(path, header, "Monthly net revenue (營業收入淨額), NT$ thousand:\n" + "\n".join(lines))
    enqueue({"kind": "revenue", "company": company, "label": label, "file": path.relative_to(ROOT).as_posix(),
             "date": filed.isoformat(), "id": f"rev:{code}-{y}{m:02d}"})
    print(f"  saved {label}")
    return None


def sync_revenue(ours, starts, state, stats):
    feeds = load(FEEDS, {})
    today = date.today()
    last_month = (today.replace(day=1) - timedelta(days=1))
    for code, company in sorted(ours.items(), key=lambda x: x[1]):
        if company in feeds:
            continue                                        # its monthly revenue release comes through ir_pull
        # a revenue month is "in the window" when its report (due the 10th after) falls after the start date
        start = starts[company].replace(day=1) - timedelta(days=1)
        for y, m in months_between(start.replace(day=1), last_month):
            key = f"rev:{code}-{y}{m:02d}"
            if key in state["seen"] and not state["seen"][key].startswith("later"):
                continue
            try:
                why = take_revenue(company, code, y, m, state)
            except Exception as exc:
                print(f"  {company}: revenue {y}-{m:02d} failed ({exc.__class__.__name__}: {str(exc)[:80]})")
                continue
            state["seen"][key] = "saved" if why is None else why
            stats["revenue_saved"] += why is None
        save(STATE, state)


# ---------------------------------------------------------------- sync / queue / status

def sync(since=None, company=None):
    state = load(STATE, {})
    for k, v in (("runs", []), ("seen", {}), ("hashes", {}), ("companies", {})):
        state.setdefault(k, v)
    state["skip_rules"] = {
        "material: skipped by subject": {why: pat for pat, why in SKIP},
        "material: kept by subject (after no skip matched)": {cat: pat for pat, cat in KEEP},
        "material: capex / share-purchase threshold": "equipment / right-of-use / share purchases kept only when the "
            "filing states >= NT$1 billion; a site (land, buildings, plant) >= NT$200 million; any amount when the "
            "subject names a capacity plan (資本支出|資本預算|擴建|擴廠|建廠|新建|興建|新廠|產能) or a merger / acquisition",
        "material: anything else": "skip:not an important type",
        "deck": "every 法說會 deck (English file first); skipped: same file as an earlier deck (sha256), image-only, "
                "no file filed; 'later' = not posted yet, retried next sync",
        "revenue": "only companies WITHOUT an ir/feeds.json entry (the feed companies post their revenue release "
                   "there); 'later: not filed yet' is retried",
    }
    ours = universe(company)
    if not ours:
        sys.exit(f"no Taiwanese (market TW) company named {company!r} in company_metadata.json")
    starts = {name: company_since(name, state, since) for name in ours.values()}
    stats = {"deck_saved": 0, "deck_skipped": 0, "material_saved": 0, "material_skipped": 0, "revenue_saved": 0,
             "skip_reasons": {}}
    print(f"MOPS sync for {len(ours)} Taiwanese companies (earliest start {min(starts.values())})")
    retry = state.get("deck_retry_from")                     # deck months a blocked run could not list
    deck_starts = {n: min(d, date.fromisoformat(retry)) if retry else d for n, d in starts.items()}
    sync_decks(ours, deck_starts, state, stats)
    if stats.get("deck_list_failed"):
        state["deck_retry_from"] = min(deck_starts.values()).isoformat()
    else:
        state.pop("deck_retry_from", None)
    sync_material(ours, starts, state, stats)
    sync_revenue(ours, starts, state, stats)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    for name in ours.values():
        state["companies"][name] = {"last_sync": stamp, "since": starts[name].isoformat()}
    state["last_sync"] = date.today().isoformat()
    state["runs"].append({"at": stamp, "since": since.isoformat() if since else "per company",
                          "companies": len(ours), **{k: v for k, v in stats.items() if k != "skip_reasons"}})
    save(STATE, state)
    print(f"decks: {stats['deck_saved']} saved, {stats['deck_skipped']} skipped; material information: "
          f"{stats['material_saved']} saved, {stats['material_skipped']} skipped "
          f"({', '.join(f'{k} {v}' for k, v in sorted(stats['skip_reasons'].items(), key=lambda x: -x[1]))}); "
          f"monthly revenue: {stats['revenue_saved']} saved; queue now {len(load(PENDING, []))}")


def mark_done(rows, why=None):
    state = load(STATE, {"seen": {}})
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state.setdefault("done", {})[r["label"]] = stamp
    save(STATE, state)


def status(company=None):
    state, pend = load(STATE, {}), load(PENDING, [])
    done = state.get("done", {})
    names = sorted(universe(company).values())
    saved = {}
    for f in sorted(OUT_DIR.glob("*.txt")) if OUT_DIR.exists() else []:
        head = f.read_text(encoding="utf-8").split("\n", 14)
        co = next((l[9:].split(" (MOPS")[0] for l in head if l.startswith("COMPANY: ")), "?")
        lab = next((l.split(": ", 1)[1] for l in head if l.startswith("# source label: ")), "?")
        saved.setdefault(co, []).append(lab)
    print(f"{'company':34s} {'saved':>5s} {'enriched':>8s} {'pending':>7s}  last sync")
    for n in names:
        labs = saved.get(n, [])
        print(f"{n[:34]:34s} {len(labs):5d} {sum(1 for l in labs if l in done):8d} "
              f"{sum(1 for r in pend if r['company'] == n):7d}  {state.get('companies', {}).get(n, {}).get('last_sync', '-')}")
        if company:
            for lab in sorted(labs):
                print(f"    {'pending ' if any(r['label'] == lab for r in pend) else done.get(lab, 'handled')[:30]:30s} {lab}")
    skips = {}
    for v in state.get("seen", {}).values():
        if v.startswith("skip:"):
            k = re.split(r" \(| \| ", v[5:])[0]
            skips[k] = skips.get(k, 0) + 1
    if skips and not company:
        print("skipped:", ", ".join(f"{k} {v}" for k, v in sorted(skips.items(), key=lambda x: -x[1])))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: 7 days before the company's last sync, else its latest "
                                   "call in the graph (cap 120 days), else 30 days")
    s.add_argument("--company")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--kind", choices=["deck", "material", "revenue"])
    p.add_argument("--market", help="accepted for parity with ir_pull (every MOPS row is TW)")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a document yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company)
    elif args.cmd == "pending":
        rows = [r for r in load(PENDING, []) if (not args.company or r["company"] == args.company)
                and (not args.kind or r["kind"] == args.kind) and (not args.market or args.market == "TW")]
        for r in sorted(rows, key=lambda r: (r["date"], r["company"])):
            print(f"{r['date']}  {r['kind']:8s} {r['company']:28s} {r['label']:90s} {r['file']}")
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
