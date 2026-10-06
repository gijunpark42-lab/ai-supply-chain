"""
cninfo.py — China A-share management Q&A: IR activity records (投资者关系活动记录表) and the company's
answers on the exchanges' investor Q&A platforms → transcripts/cninfo/*.txt, queued for `enrich china`.

Why this exists
---------------
Our Chinese A-share names (Innolight, Eoptolink, Accelink, TFC Optical, WUS, Victory Giant, Luxshare, JCET,
TFME, Huatian, Montage, Yuanjie) rarely publish an English earnings call. What they DO publish, often weekly,
is management talking to investors in writing:
  1. IR activity records (投资者关系活动记录表) — the company's own minutes of an institutional meeting
     (site visit, call, results briefing): management's prepared remarks and its answers to the funds'
     questions. Shenzhen-listed companies must file them; they sit in the cninfo announcement database
     under the "调研活动 / investor relations" tab. Shanghai-listed companies post them on SSE e互动.
  2. Investor Q&A answers — on SZSE 互动易 (irm.cninfo.com.cn) and SSE e互动 (sns.sseinfo.com) anyone may
     ask a question and the company (board secretary's office) answers in writing.
Both are treated as MANAGEMENT Q&A (like a conference talk, enrich skill §2 / slot table): the answer is
the company's statement; the investor's question is context only, never a fact.
  3. Periodic reports (added 2026-10-04, `reports` command) — the statutory 年度报告 (annual), 半年度报告
     (half-year) and 一季度 / 三季度报告 (quarterly) reports. The annual report is where an A-share company
     discloses its 前五名客户 / 前五名供应商 (top-5 customers / suppliers, % of sales or purchases, named when
     the company chooses to), its capacity / output (产能 / 产量), construction in progress (在建工程), R&D and
     the 管理层讨论与分析 (MD&A). These are company documents, not Q&A: enriched like a DART periodic report.

Commands (python -X utf8 cninfo.py …)
-------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>"]   fetch new records and answers, save, queue
    reports [--since YYYY-MM-DD] [--company "<Company>"] fetch new periodic reports, save, queue. A company's
                                                         first look takes only its NEWEST annual and half-year
                                                         report (and a quarterly one only when newer than both);
                                                         later runs take every report filed since the last run.
    pending [--company "<Company>"] [--market CN]       the queue (`enrich china` works it)
    done --label "<label>" [--why …]                     one file handled (enriched, or "no material facts")
    done --all                                           every queued file handled (only when true)
    status [--company "<Company>"]                       every saved file and its state; out-of-scope names

Files
-----
    transcripts/cninfo/<slug>_<YYYY-MM-DD>_record_<id>.txt   one IR activity record (PDF text, page by page)
    transcripts/cninfo/<slug>_<YYYY-MM-DD>_qa_<szse|sse>.txt   one company's kept answers of one day
    transcripts/cninfo_reports/<slug>_<YYYY-MM-DD>_report_<id>.txt          one periodic report, the WHOLE text
    transcripts/cninfo_reports/<slug>_<YYYY-MM-DD>_report_<id>_extract.txt  annual / half-year only: the key
                             sections the enricher reads (see report_extract). Both files declare the same label,
                             so verify_graph.py checks numbers against the whole report. (Own folder because the
                             status board attributes files to a pipeline by folder.)
    cninfo/sync_state.json   last sync, runs, per-company window, every item id handled
                             (saved / skip:<why> / enriched:<date>), record hashes, SSE uids, the filter rules
    cninfo/reports_state.json  the same bookkeeping for periodic reports (own file: a long report backfill must
                             never overwrite what a records / Q&A sync writes at the same time)
    cninfo/pending.json      saved files not yet enriched (kind record / qa / report)

Labels (enrich skill §5)
------------------------
    <Company> IR activity record: <record no., or the date> (MM-DD-YYYY)   dated the disclosure day
    <Company> investor Q&A: <platform> (MM-DD-YYYY)                        dated the answer day, one per company per day
    <Company> annual report: <YYYY> Annual Report (MM-DD-YYYY)             periodic reports, dated the disclosure day;
    <Company> half-year report: <YYYY> Half-Year Report (MM-DD-YYYY)       the same shape as the reports saved by hand
    <Company> quarterly report: <YYYY> Q1|Q3 Report (MM-DD-YYYY)           before 2026-10-04
    e.g. "Innolight IR activity record: 2026-008 (08-23-2026)", "Eoptolink investor Q&A: SZSE Interactive Easy (09-23-2026)",
         "Innolight annual report: 2025 Annual Report (03-31-2026)"

How the sources answer (found 2026-10-01; all public, no login, no token)
-----------------------------------------------------------------------
cninfo announcements: POST http://www.cninfo.com.cn/new/hisAnnouncement/query (the site's own search form;
    stock=<code>,<orgId>, column=szse|sse, tabName=relation (= 调研活动 tab) or fulltext, seDate=a~b).
    orgId comes from http://www.cninfo.com.cn/new/data/szse_stock.json (every A-share, SZSE and SSE).
    PDFs at https://static.cninfo.com.cn/<adjunctUrl>. The relation tab holds SZSE companies' records;
    SSE companies file none there, so their fulltext list is scanned for record titles as well.
    Periodic reports: the same query on tabName=fulltext with category=REPORT_CATEGORIES (年报 / 半年报 /
    一季报 / 三季报). The list also holds each report's 摘要 (summary) and sometimes an English version or a
    corrected re-issue; REPORT_FILTERS says which one is kept.
SZSE 互动易: POST https://irm.cninfo.com.cn/newircs/company/question?stockcode=&orgId=&pageNum=&pageSize=
    &startDay=&endDay= -> JSON, every question of the company in a question-date window; contentType 11 =
    answered (attachedContent = the answer, attachedPubDate = the answer time).
SSE e互动: https://sns.sseinfo.com/ajax/getCompany.do (POST data=<code>) -> the company uid;
    ajax/userfeeds.do?typeCode=company&uid=<uid>&type=11 -> the latest answers (HTML), type=30 -> the
    company's own postings (its IR activity records as PDFs). LIMIT: both SSE feeds show about ONE MONTH
    only ("近1个月"), so SSE companies must be synced at least every few weeks; a first sync cannot reach
    the full 120 days there.
One request every 1.2 s, a normal browser User-Agent.
"""

import argparse
import hashlib
import html as htmllib
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
STATE = ROOT / "cninfo" / "sync_state.json"
PENDING = ROOT / "cninfo" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "cninfo"
REPORTS_STATE = ROOT / "cninfo" / "reports_state.json"     # periodic reports keep their own bookkeeping
REPORT_DIR = ROOT / "transcripts" / "cninfo_reports"

CNINFO = "http://www.cninfo.com.cn"
QUERY_URL = CNINFO + "/new/hisAnnouncement/query"
STOCKS_URL = CNINFO + "/new/data/szse_stock.json"
STATIC = "https://static.cninfo.com.cn/"
IRM = "https://irm.cninfo.com.cn"
SSE = "https://sns.sseinfo.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
CST = timezone(timedelta(hours=8))          # every date on these sites is China time
MAX_BACK = 120                               # a company's first sync never reaches further back (as ir_pull)
QA_LAG = 90                                  # an answer can come weeks after the question: look this far back
MIN_TEXT = 200                               # fewer characters = an image-only PDF
PLATFORM = {"szse": "SZSE Interactive Easy", "sse": "SSE e-Interactive"}   # English names for the labels

# ---------------------------------------------------------------- what is kept, what is skipped (and why)
# An IR record title must look like the minutes of a meeting. Everything else in the announcement lists
# (event notices "关于召开/参加…说明会的公告", rules "投资者关系管理制度", results, buybacks …) is skipped.
RECORD_RE = re.compile(r"投资者关系活动记录|投资者活动记录|投资者关系管理信息|调研活动(记录|信息)|业绩说明会.{0,12}(召开情况|记录)|"
                       r"(召开情况|纪要).{0,12}说明会|调研纪要|交流会纪要")
# cninfo's 调研活动 (relation) tab lists only IR-activity filings, titled freely ("投资者关系活动记录表20260823",
# "300502新易盛投资者关系管理信息20260911" …): everything there is kept except the IR rules themselves.
RULES_RE = re.compile(r"制度|办法|细则|规则|章程")

# Investor Q&A: keep an answer only when the exchange is about the business —
# products, customers, capacity, orders, demand, guidance (KEEP, matched on question + answer).
KEEP_RE = re.compile(r"产品|客户|订单|在手|产能|扩产|扩建|投产|量产|出货|发货|交付|送样|验证|认证|导入|供货|供应|采购|"
                     r"需求|市占|份额|营收|营业收入|收入|毛利|产线|工厂|基地|良率|利用率|稼动|新品|研发进展|指引|展望|"
                     r"预计|目标|项目|合作|算力|服务器|光模块|光芯片|芯片|PCB|封装|晶圆|1\.6T|800G|3\.2T|NPO|CPO|HBM|"
                     r"GPU|ASIC|DSP|AI|数据中心|交换机|硅光", re.I)
# … and skip it when the QUESTION is about the stock, payouts or governance, unless the answer still
# states an operating fact (STRONG). Example skipped: "股价持续下跌，市值管理如何开展？"
SKIP_Q_RE = re.compile(r"股价|市值|分红|派息|利润分配|权益分派|回购|减持|增持|质押|股东人数|股东户数|股东总数|持股|"
                       r"董事|监事|高管|薪酬|股权激励|激励计划|诉讼|处罚|立案|问询函|信息披露|博主|传闻|谣言|停牌|退市|"
                       r"股东大会|股东会|披露时间|披露日期|可转债|定增|募集资金")
STRONG_RE = re.compile(r"订单|产能|扩产|出货|量产|送样|交付|客户|营收|营业收入|毛利|良率|利用率")
# A non-answer ("thanks for your attention", "a business secret", "see our announcements") yields nothing.
NON_ANSWER_RE = re.compile(r"不便|商业秘密|商业机密|以公司.{0,6}(公告|披露).{0,4}为准|请关注公司.{0,10}公告|感谢.{0,6}关注")
MIN_ANSWER = 25                              # shorter answers carry no fact

FILTERS = {
    "records_kept": "every filing on cninfo's 调研活动 (relation) tab except IR rules (RULES_RE); elsewhere (cninfo full "
                    "text list of SSE companies, SSE e互动 postings) titles matching RECORD_RE (投资者关系活动记录表, "
                    "投资者关系管理信息, 调研活动记录, 业绩说明会召开情况/记录, 调研/交流会纪要)",
    "records_skipped": "every other announcement: event notices (关于召开/参加…说明会的公告), IR rules, results, buybacks, "
                       "governance — not a record of what management said; image-only PDFs; a file already saved",
    "qa_kept": "answered questions whose question+answer match KEEP_RE (products, customers, capacity, orders, "
               "shipments, demand, revenue/margin, sampling/qualification, guidance/targets, named AI hardware)",
    "qa_skipped": "questions about the stock price / market value / dividends / buybacks / holdings / directors / pay / "
                  "lawsuits / disclosure rules / rumours (SKIP_Q_RE) unless the answer states an operating fact; "
                  "non-answers (不便透露 / 商业秘密 / 以公告为准 / thanks only) under 80 characters; answers under "
                  "25 characters; anything not about the business; answers of today (China time — the day is not over)",
    "out_of_scope": "Hong Kong-only listings (HKEX: e.g. ASMPT, Lenovo, Innoscience) — no cninfo / 互动易 / e互动 coverage",
}


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def cst_day(ms):
    """Milliseconds since 1970 (what the JSON gives) -> the China-time calendar day."""
    return datetime.fromtimestamp(int(ms) / 1000, CST).date()


def today_cst():
    return datetime.now(CST).date()


def mdy(d):
    return d.strftime("%m-%d-%Y")


def universe():
    """[{name, code, exchange}] for our A-share companies (market CN on SZSE / SSE) and the list of
    Hong Kong-only names that are out of scope."""
    ours, hk = [], []
    for name, info in load(META, {}).items():
        if market_of(info.get("exchange")) != "CN":
            continue
        m = re.search(r"(\d{6})", str(info.get("ticker") or ""))
        if info.get("exchange") in ("SZSE", "SSE") and m:
            ours.append({"name": name, "code": m.group(1), "exchange": info["exchange"]})
        else:
            hk.append(name)
    return ours, hk


_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
_last = [0.0]


def _polite():
    """One request every 1.2 s across all three sites."""
    wait = 1.2 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def http(method, url, **kw):
    """GET/POST with three tries (these sites drop the odd connection)."""
    for attempt in range(3):
        _polite()
        try:
            r = _session.request(method, url, timeout=60, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def pdf_pages(content):
    """[(page number, text)] of a PDF (pypdf), every page. A page pypdf cannot read is kept as a marker
    (a 300-page annual report must not be lost to one broken page)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    pages = []
    for i, p in enumerate(reader.pages, 1):
        try:
            pages.append((i, (p.extract_text() or "").strip()))
        except Exception:
            pages.append((i, "[page could not be read]"))
    return pages


def clean(text):
    """HTML fragment -> plain text on one line."""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"[ \t\r\f\v　]+", " ", text).strip()


_ORG = {}


def org_id(code):
    """cninfo's orgId for a stock code (the announcement query needs it)."""
    if not _ORG:
        for s in http("GET", STOCKS_URL).json()["stockList"]:
            _ORG[s["code"]] = s["orgId"]
    return _ORG.get(code)


def first_window(company):
    """Start date of a company's FIRST sync: its latest earnings-call label in the graph (≤ 120 days back),
    else 30 days — the same rule as ir_pull.py (what came before the call was discussed on it)."""
    graph = load(ROOT / "graph" / "merged_graph.json", {"nodes": []})
    best = None
    for n in graph["nodes"]:
        if n.get("id") != company:
            continue
        for q in n.get("quarterly_data", []):
            lab = q.get("quarter") or ""
            m = re.search(r" Q\d FY\d{4} \((\d\d)-(\d\d)-(\d{4})\)", lab)
            if lab.startswith(company + " ") and m:
                d = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                best = d if best is None or d > best else best
    floor = today_cst() - timedelta(days=MAX_BACK)
    return max(best, floor) if best else today_cst() - timedelta(days=30)


def queue_row(kind, company, label, path, day, item_id, full=None):
    """Append one saved file to the queue. `full` = the whole report beside a periodic report's extract."""
    pending = load(PENDING, [])
    row = {"kind": kind, "company": company, "label": label, "file": path.relative_to(ROOT).as_posix(),
           "date": day.isoformat(), "id": item_id}
    if full:
        row["full"] = full.relative_to(ROOT).as_posix()
    pending.append(row)
    save(PENDING, pending)
    print(f"  saved {label}")


# ---------------------------------------------------------------- 1. IR activity records

def cninfo_list(co, tab, since, until, category=""):
    """Every announcement of one company on one cninfo tab between two dates -> [dict].
    `category` narrows the list to cninfo's announcement categories (periodic reports: REPORT_CATEGORIES)."""
    column = "szse" if co["exchange"] == "SZSE" else "sse"
    out, page = [], 1
    while True:
        data = http("POST", QUERY_URL, headers={"X-Requested-With": "XMLHttpRequest"}, data={
            "pageNum": str(page), "pageSize": "30", "column": column, "tabName": tab, "plate": "",
            "stock": f"{co['code']},{org_id(co['code'])}", "searchkey": "", "secid": "", "category": category,
            "trade": "", "seDate": f"{since.isoformat()}~{until.isoformat()}", "sortName": "", "sortType": "",
            "isHLtitle": "true"}).json()
        out += data.get("announcements") or []
        if not data.get("hasMore") or page >= 40:
            return out
        page += 1


def sse_uid(co, state):
    """SSE e互动 user id of a Shanghai company (cached in the state file)."""
    uids = state.setdefault("sse_uid", {})
    if co["code"] not in uids:
        uid = http("POST", SSE + "/ajax/getCompany.do", data={"data": co["code"]}).text.strip()
        uids[co["code"]] = uid if uid.isdigit() else None
    return uids[co["code"]]


def sse_feed(uid, kind, pages=10):
    """Items of an SSE e互动 company feed (type 11 = answers, 30 = company postings) -> list of HTML blocks."""
    blocks = []
    for page in range(1, pages + 1):
        text = http("GET", f"{SSE}/ajax/userfeeds.do?typeCode=company&type={kind}&pageSize=10&uid={uid}&page={page}").text
        found = re.split(r'(?=<div class="m_feed_item[^"]*" id="item-\d+")', text)[1:]
        blocks += found
        if len(found) < 10:
            return blocks
    return blocks


def record_candidates(co, since, until, state):
    """IR activity records listed for one company: [(item id, title, day, pdf url, platform)], plus the
    number of announcements looked at and skipped (not a record)."""
    found, ignored = [], 0
    tabs = ["relation"] if co["exchange"] == "SZSE" else ["fulltext"]
    for tab in tabs:
        for a in cninfo_list(co, tab, since, until):
            title = clean(a.get("announcementTitle"))
            item = f"rec:cninfo:{a['announcementId']}"
            is_record = not RULES_RE.search(title) if tab == "relation" else bool(RECORD_RE.search(title))
            if not is_record:
                ignored += 1
                if tab == "relation":                # the IR tab itself: say what was skipped
                    state["seen"].setdefault(item, f"skip:not a meeting record ({title[:40]})")
                continue
            found.append((item, title, cst_day(a["announcementTime"]), STATIC + a["adjunctUrl"], "cninfo"))
    if co["exchange"] == "SSE":
        uid = sse_uid(co, state)
        for b in sse_feed(uid, 30) if uid else []:
            m_id = re.search(r'id="item-(\d+)"', b)
            pdf = re.search(r"href='([^']+\.pdf)'", b)
            title = clean(re.sub(r"<a .*?</a>", "", re.search(r'id="m_feed_txt-\d+">(.*?)</div>', b, re.S).group(1), flags=re.S)) \
                if 'id="m_feed_txt-' in b else ""
            d = re.search(r"<span>(\d{4})年(\d\d)月(\d\d)日", b)
            if not (m_id and pdf and d):
                continue
            day = date(int(d.group(1)), int(d.group(2)), int(d.group(3)))
            if day < since:
                continue
            if not RECORD_RE.search(title):
                ignored += 1
                state["seen"].setdefault(f"rec:sse:{m_id.group(1)}", f"skip:not a meeting record ({title[:40]})")
                continue
            found.append((f"rec:sse:{m_id.group(1)}", title, day, pdf.group(1), "SSE e-Interactive"))
    return found, ignored


def record_number(text, title, day):
    """The record's own number ('编号：2026-008' on the first page, or '（2026-011）' in the title), else the date."""
    m = re.search(r"编号\s*[:：]\s*([0-9A-Za-z][0-9A-Za-z\-－—_]*)", text[:1500]) or \
        re.search(r"[（(](\d{4}[-－—]\d{1,4})[）)]", title)
    return m.group(1).replace("－", "-").replace("—", "-") if m else day.isoformat()


def take_record(co, item, title, day, url, platform, state):
    """Save one IR activity record; return a skip reason or None."""
    content = http("GET", url).content
    if content[:4] != b"%PDF":
        return "not a PDF"
    digest = hashlib.sha256(content).hexdigest()
    if digest in state["hashes"]:                      # the same record posted on cninfo AND e互动
        return f"same file as {state['hashes'][digest]}"
    pages = pdf_pages(content)
    text = "\n".join(t for _n, t in pages)
    if len(text) < MIN_TEXT:
        state["hashes"][digest] = f"image-only ({item})"
        return "image-only PDF (no text layer)"
    company = co["name"]
    label = f"{company} IR activity record: {record_number(text, title, day)} ({mdy(day)})"
    if label in state["labels"]:                       # two records of one day without a number
        label = f"{company} IR activity record: {item.split(':')[-1]} ({mdy(day)})"
    state["hashes"][digest] = label
    state["labels"].append(label)
    path = OUT_DIR / f"{slug(company)}_{day.isoformat()}_record_{item.split(':')[-1]}.txt"
    header = [
        f"SOURCE: {url}",
        f"ITEM: {item} — {title} — posted on {platform}",
        f"DISCLOSED: {day.isoformat()} (China time; the label date)",
        f"COMPANY: {company} ({co['code']} {co['exchange']})",
        "# NOTE: NOT an earnings-call transcript — the company's OWN record (投资者关系活动记录表) of an institutional",
        "#       meeting. Treat it as MANAGEMENT Q&A (like a conference talk, enrich skill §2): the prepared remarks and",
        "#       the answers (A: / 答) are management's statements; the participants' questions (Q: / 问) are context",
        "#       only. The list of attending funds is not a fact to enrich. Write every entry in English (skill §8).",
        f"# source label: {label}",
        "",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + "".join(f"==== page {n} ====\n{t}\n" for n, t in pages if t), encoding="utf-8")
    queue_row("record", company, label, path, day, item)
    return None


# ---------------------------------------------------------------- 2. investor Q&A answers

def qa_reason(question, answer):
    """None = keep this answer; otherwise why it is skipped (see FILTERS)."""
    a = answer.strip()
    if len(a) < MIN_ANSWER:
        return "answer too short"
    if NON_ANSWER_RE.search(a) and len(a) < 80:
        return "non-answer"
    if SKIP_Q_RE.search(question) and not STRONG_RE.search(a):
        return "stock / payout / governance question"
    if not KEEP_RE.search(question + " " + a):
        return "not about products, customers, capacity, orders or guidance"
    return None


def szse_answers(co, since, until):
    """Answered 互动易 questions of a Shenzhen company whose ANSWER day is in [since, until)."""
    rows, page = [], 1
    org = org_id(co["code"])
    while True:
        data = http("POST", f"{IRM}/newircs/company/question", params={
            "stockcode": co["code"], "orgId": org, "pageSize": "200", "pageNum": str(page), "keyWord": "",
            "startDay": (since - timedelta(days=QA_LAG)).isoformat(), "endDay": until.isoformat()}).json()
        for r in data.get("rows") or []:
            if r.get("contentType") != 11 or not r.get("attachedContent"):
                continue                                  # unanswered
            day = cst_day(r.get("attachedPubDate") or r["updateDate"])
            if since <= day < until:
                rows.append({"id": f"qa:irm:{r['indexId']}", "q": clean(r["mainContent"]), "a": clean(r["attachedContent"]),
                             "q_day": cst_day(r["pubDate"]), "day": day,
                             "url": f"{IRM}/ircs/question/questionDetail?questionId={r['indexId']}"})
        if page >= int(data.get("totalPage") or 1) or page >= 30:
            return rows
        page += 1


def sse_answers(co, since, until, state):
    """Answered e互动 questions of a Shanghai company (the feed shows about one month)."""
    uid = sse_uid(co, state)
    rows = []
    for b in sse_feed(uid, 11) if uid else []:
        m_id = re.search(r'id="item-(\d+)"', b)
        q = re.search(r'<div class="m_feed_txt">\s*(?:<a [^>]*>.*?</a>)?(.*?)</div>', b, re.S)
        a = re.search(r'id="m_feed_txt-\d+">(.*?)</div>', b, re.S)
        days = re.findall(r"<span>(\d{4})年(\d\d)月(\d\d)日", b)
        if not (m_id and q and a and len(days) >= 2):
            continue
        q_day, day = (date(int(y), int(m), int(d)) for y, m, d in days[:2])
        if since <= day < until:
            rows.append({"id": f"qa:sse:{m_id.group(1)}", "q": clean(q.group(1)), "a": clean(a.group(1)),
                         "q_day": q_day, "day": day, "url": f"{SSE}/company.do?uid={uid}"})
    return rows


def take_qa_day(co, platform_key, day, kept):
    """Write one company's kept answers of one day as one file; return its label."""
    company = co["name"]
    label = f"{company} investor Q&A: {PLATFORM[platform_key]} ({mdy(day)})"
    path = OUT_DIR / f"{slug(company)}_{day.isoformat()}_qa_{platform_key}.txt"
    site = "SZSE 互动易 (irm.cninfo.com.cn)" if platform_key == "szse" else "SSE e互动 (sns.sseinfo.com)"
    header = [
        f"SOURCE: {kept[0]['url']}",
        f"PLATFORM: {site} — {len(kept)} answer(s) given on {day.isoformat()} (China time)",
        f"COMPANY: {company} ({co['code']} {co['exchange']})",
        "# NOTE: NOT a transcript — the company's WRITTEN answers to investors' questions on the exchange's Q&A",
        "#       platform. Treat as MANAGEMENT Q&A (like a conference talk, enrich skill §2): the ANSWER is the",
        "#       company's statement; the QUESTION is an anonymous investor's — context only, never a fact (a figure",
        "#       or a customer name that only the question states is not captured). Only answers about products,",
        "#       customers, capacity, orders and guidance were kept (cninfo.py FILTERS). Write entries in English (§8).",
        f"# source label: {label}",
        "",
    ]
    body = []
    for i, r in enumerate(kept, 1):
        body += [f"==== Q&A {i} — asked {r['q_day'].isoformat()}, answered {r['day'].isoformat()} — {r['url']}",
                 f"QUESTION (investor, context only): {r['q']}",
                 f"ANSWER (the company): {r['a']}", ""]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header + body), encoding="utf-8")
    queue_row("qa", company, label, path, day, ",".join(r["id"] for r in kept))
    return label


# ---------------------------------------------------------------- sync

def sync(since=None, company=None):
    state = load(STATE, {})
    for key, default in (("last_sync", None), ("runs", []), ("companies", {}), ("seen", {}), ("hashes", {}),
                         ("labels", []), ("sse_uid", {})):
        state.setdefault(key, default)
    state["filters"] = FILTERS
    ours, hk = universe()
    if company:
        ours = [c for c in ours if c["name"] == company]
        if not ours:
            sys.exit(f"{company!r} is not an SZSE / SSE company in company_metadata.json")
    today = today_cst()
    totals = {"records": 0, "qa_files": 0, "answers_kept": 0, "answers_skipped": 0, "skipped": 0}
    for co in ours:
        name = co["name"]
        known = state["companies"].get(name)
        start = since or (datetime.strptime(known["last_sync"][:10], "%Y-%m-%d").date() - timedelta(days=7)
                          if known else first_window(name))
        try:
            # 1. IR activity records (until tomorrow: a record disclosed tonight is listed with tomorrow's date)
            recs, ignored = record_candidates(co, start, today + timedelta(days=1), state)
            for item, title, day, url, platform in sorted(recs, key=lambda r: r[2]):
                if item in state["seen"]:
                    continue
                why = take_record(co, item, title, day, url, platform, state)
                state["seen"][item] = "saved" if why is None else f"skip:{why}"
                totals["records" if why is None else "skipped"] += 1
                if why:
                    print(f"  skip {name} {day} {item}: {why}")
                save(STATE, state)
            # 2. investor Q&A answers, one file per answer day (today excluded: the day is not over)
            key = "szse" if co["exchange"] == "SZSE" else "sse"
            answers = szse_answers(co, start, today) if key == "szse" else sse_answers(co, start, today, state)
            by_day = {}
            for r in answers:
                if r["id"] in state["seen"]:
                    continue
                why = qa_reason(r["q"], r["a"])
                if why:
                    state["seen"][r["id"]] = f"skip:{why}"
                    totals["answers_skipped"] += 1
                else:
                    by_day.setdefault(r["day"], []).append(r)
            for day, kept in sorted(by_day.items()):
                label = take_qa_day(co, key, day, sorted(kept, key=lambda r: r["id"]))
                for r in kept:
                    state["seen"][r["id"]] = f"saved:{label}"
                totals["qa_files"] += 1
                totals["answers_kept"] += len(kept)
        except (requests.RequestException, ValueError) as exc:     # one company's failure must not stop the run
            print(f"  {name}: fetch failed ({exc.__class__.__name__}: {str(exc)[:100]}) — retried next sync")
            save(STATE, state)
            continue
        state["companies"][name] = {"last_sync": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
                                    "since": start.isoformat()}
        print(f"{name:26s} since {start}: {len(recs)} record(s) listed, {ignored} other announcement(s) ignored, "
              f"{len(answers)} answer(s) in window")
        save(STATE, state)
    if not company:
        state["last_sync"] = today.isoformat()
    state["runs"].append({"at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
                          "since": since.isoformat() if since else "per company",
                          "company": company or "all", **totals})
    save(STATE, state)
    print(f"\n{totals['records']} record(s) saved, {totals['qa_files']} Q&A file(s) saved "
          f"({totals['answers_kept']} answers kept, {totals['answers_skipped']} skipped by the filter), "
          f"{totals['skipped']} record(s) skipped; queue now {len(load(PENDING, []))}")
    if hk and not company:
        print("out of scope (Hong Kong-only listings, no A-share disclosure): " + ", ".join(sorted(hk)))


# ---------------------------------------------------------------- 3. periodic reports (年度报告 / 半年度报告 / 季度报告)

# cninfo's announcement categories of the four periodic reports: annual, half-year, Q1, Q3.
REPORT_CATEGORIES = "category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh;"
REPORT_BACK = 400        # a company's first look reaches this many days back: far enough for its last annual report
REPORT_MIN_CJK = 0.15    # a Chinese report whose text is less than 15% Chinese characters has a broken text layer
# kind -> (label word, report name in the label). The shape matches the reports saved by hand before 2026-10-04,
# e.g. "Cambricon half-year report: 2026 Half-Year Report (08-08-2026)".
REPORT_KINDS = {"annual": ("annual report", "{year} Annual Report"),
                "half": ("half-year report", "{year} Half-Year Report"),
                "q1": ("quarterly report", "{year} Q1 Report"),
                "q3": ("quarterly report", "{year} Q3 Report")}
REPORT_KIND_CN = {"annual": "年度报告 (annual report)", "half": "半年度报告 (half-year report)",
                  "q1": "第一季度报告 (Q1 report)", "q3": "第三季度报告 (Q3 report)"}
# Titles in the category list that are NOT the report itself: its summary (摘要), notices about it
# ("关于2025年年度报告的更正公告", "…业绩说明会…"), the audit / internal-control / ESG reports, H-share copies.
NOT_REPORT_RE = re.compile(r"摘要|关于|公告|提示|说明会|审计|内部控制|社会责任|ESG|可持续发展|鉴证|专项|意见|决议|问询|回复|取消|H股")
ENGLISH_RE = re.compile(r"英文|English", re.I)
CORRECTED_RE = re.compile(r"更正|更新后|修订|修正")          # a full re-issue: "2025年年度报告（更正后）"

REPORT_FILTERS = {
    "kept": "the full Chinese 年度报告 / 半年度报告 / 第一季度报告 / 第三季度报告 of every SZSE / SSE company in "
            "company_metadata.json (cninfo categories 年报 / 半年报 / 一季报 / 三季报). First look per company: only the "
            "newest annual and half-year report, plus the newest quarterly report when it is newer than both; after "
            "that every report filed since the last run (from 7 days before it).",
    "skipped": "摘要 summaries and notices about a report (NOT_REPORT_RE); the English version when the Chinese one is "
               "listed; a corrected re-issue (更正后 / 更新后 / 修订) when the original is listed (the original is kept); "
               "a report already saved by this pipeline or saved by hand before 2026-10-04 (same company, kind and "
               "fiscal year in any transcripts/ file's '# source label:'); image-only or unreadable PDFs",
    "extract": "annual / half-year reports also get an _extract.txt: 第二节 from 主要会计数据和财务指标, 第三节 管理层讨论与分析 "
               "whole, and pages elsewhere (before the parent-company notes) with top-5 customers / suppliers, top-5 "
               "receivables / prepayments, 重要在建工程项目, 募投项目, other major contracts or capacity",
}


def report_kind(title, day):
    """('annual' | 'half' | 'q1' | 'q3', fiscal year) of a periodic-report title, or None.
    '2026年半年度报告' -> ('half', 2026); '亨通光电2025年年度报告' -> ('annual', 2025)."""
    if "半年度报告" in title or "半年报" in title:
        kind = "half"
    elif re.search(r"第?一季度报告", title):
        kind = "q1"
    elif re.search(r"第?三季度报告", title):
        kind = "q3"
    elif "年度报告" in title:
        kind = "annual"
    else:
        return None
    m = re.search(r"(20\d\d)\s*年", title)
    if m:
        year = int(m.group(1))
    else:                                   # no year in the title: an annual report covers the year before filing
        year = day.year - 1 if kind == "annual" else day.year
    return kind, year


def report_variant(title):
    """'original' | 'corrected' (a full re-issue) | 'english', or the reason the title is not the report."""
    m = NOT_REPORT_RE.search(title)
    if m:
        return f"not the report itself ({m.group(0)})"
    if ENGLISH_RE.search(title):
        return "english"
    if CORRECTED_RE.search(title):
        return "corrected"
    return "original"


REPORT_LABEL_RE = re.compile(r"^(?P<company>.+?) (?P<word>annual|half-year|quarterly) report: (?P<title>.+) \(\d\d-\d\d-\d{4}\)$")
HEADER_LABEL_RE = re.compile(r"(?im)^\s*#?\s*source label\s*:\s*`?(.+?)`?\s*$")


def label_key(label):
    """(company, kind, fiscal year) of a periodic-report label, or None. A report saved by hand under a slightly
    different title ('Kstar half-year report: 2026 Semi-Annual Report (…)') is still the same report."""
    m = REPORT_LABEL_RE.match(label.strip())
    year = re.search(r"20\d\d", m.group("title")) if m else None
    if not year:
        return None
    if m.group("word") == "annual":
        kind = "annual"
    elif m.group("word") == "half-year":
        kind = "half"
    else:
        q = re.search(r"\bQ([13])\b|\b(first|third) quarter", m.group("title"), re.I)
        if not q:
            return None
        kind = "q1" if q.group(1) == "1" or (q.group(2) or "").lower() == "first" else "q3"
    return m.group("company"), kind, int(year.group(0))


def reports_saved_elsewhere():
    """{(company, kind, year): file} for periodic reports saved OUTSIDE this pipeline — by hand before 2026-10-04
    (transcripts/non_transcript_sources/…). Read from each transcript file's '# source label:' header (~1 s)."""
    found = {}
    for f in sorted((ROOT / "transcripts").rglob("*.txt")):
        if REPORT_DIR in f.parents:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            head = fh.read(3000)
        for lab in HEADER_LABEL_RE.findall(head):
            key = label_key(lab)
            if key:
                found.setdefault(key, f.relative_to(ROOT).as_posix())
    return found


def cjk_share(text):
    """Share of Chinese characters among the non-space characters (a garbled text layer has almost none)."""
    chars = re.sub(r"\s", "", text)
    return len(re.findall(r"[一-鿿]", chars)) / max(1, len(chars))


# How report_extract finds its way around a report: every A-share periodic report since 2021 uses the same
# outline (第一节 重要提示 … 第二节 公司简介和主要财务指标 … 第三节 管理层讨论与分析 … 第八节 财务报告).
SECTION_HEAD_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十]+)\s*节\s*(.{0,24})$")
MDA_TITLE_RE = re.compile(r"管理层讨论与分析|经营情况讨论与分析|董事会报告")
TOC_LEADER_RE = re.compile(r"\.{4,}|…{2,}|·{4,}")             # the dotted leaders of a table-of-contents line
KEY_FIN_RE = re.compile(r"主要会计数据和财务指标")
PARENT_NOTES_RE = re.compile(r"母公司财务报表主要项目注释")    # parent-only notes repeat the group's tables
# Pages outside the MD&A worth keeping (part C of the extract).
EXTRA_PAGE_RE = re.compile(r"前五名的?(销售)?客户|前五名的?供应商|前\s*5\s*名的?(客户|供应商)|期末余额前五名的(应收账款|预付款)|"
                           r"重要在建工程项目|募投项目明细|募集资金投资项目的?(使用|实施|建设)?(情况|明细|进度)|募集资金使用进展|"
                           r"其他重大合同|重大销售合同|产能利用率|设计产能|在建产能")
# … unless the item right below says it does not apply ("□适用 √不适用", "公司报告期不存在其他重大合同。").
#   (The √ may come out as another symbol or not at all: "□适用 不适用" = not applicable, "适用 □不适用" = applicable.)
NOT_APPLICABLE_RE = re.compile(r"^.{0,40}?□\s*适用\s*[^\w\s□]?\s*不适用|^[^\n]*\n\s*(公司)?(报告期内?)?(不存在|无)", re.S)
# Wingdings glyphs some reports use, which pypdf returns as private-use characters: the √ of "√适用 □不适用"
# (U+F052) and a bullet (U+F0B7). Replaced in the saved text so the enricher reads the tick boxes.
GLYPHS = {"": "√", "": "•"}
NEGATED_RE = re.compile(r"不存在|没有|未发生")             # the hit sits inside a "there is no …" sentence


def extra_hits(text):
    """The EXTRA_PAGE_RE hits of one page that really hold the item: not followed by 'not applicable' and not
    inside a negative sentence ('公司报告期不存在其他重大合同。')."""
    hits = []
    for m in EXTRA_PAGE_RE.finditer(text):
        line_before = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        if NOT_APPLICABLE_RE.search(text[m.end():m.end() + 80]) or NEGATED_RE.search(line_before):
            continue
        hits.append(m)
    return hits
# What the extract header lists with page numbers, so the enricher knows where to look (and what is absent).
LOCATE = [("top-5 customers", r"前五名的?(销售)?客户|前\s*5\s*(名|大)的?客户|主要销售客户"),
          ("top-5 suppliers", r"前五名的?供应商|前\s*5\s*(名|大)的?供应商|主要供应商情况"),
          ("capacity / output", r"产能|产量"),
          ("R&D", r"研发投入"),
          ("construction in progress", r"在建工程"),
          ("major CIP projects", r"重要在建工程项目"),
          ("raised-fund projects", r"募投项目|募集资金投资项目"),
          ("top-5 receivables", r"期末余额前五名的应收账款"),
          ("top-5 prepayments", r"期末余额前五名的预付款"),
          ("major contracts", r"其他重大合同|重大销售合同"),
          ("outlook / business plan", r"未来发展的展望|未来发展的讨论与分析|经营计划")]


def report_extract(pages):
    """The `_extract` body of an annual / half-year report -> (text, located, pages kept, warning).
      A. 第二节 from the line '主要会计数据和财务指标' (revenue, profit, YoY, the quarterly breakdown) to the MD&A;
      B. 第三节 管理层讨论与分析 (MD&A) whole: business and products, capacity / output, the 主要销售客户 /
         主要供应商 (top-5) tables, R&D, assets incl. construction in progress, investments, the outlook;
      C. any other page before the parent-company notes that holds top-5 customers / suppliers, top-5 receivables /
         prepayments, major construction-in-progress projects, raised-fund (募投) projects, other major contracts or
         capacity — plus the next page when the hit sits low on the page (its table usually continues there).
    Section headings are read from the body; table-of-contents pages are ignored. `warning` says why no extract
    could be made (no MD&A heading found): the queue then points at the whole report instead."""
    text_of = dict(pages)
    lines = {n: (t or "").splitlines() for n, t in pages}
    toc = {n for n, ls in lines.items() if sum(1 for l in ls if TOC_LEADER_RE.search(l)) >= 3}

    # 1. every section heading in the body: (page, line, section number, title)
    heads = []
    for n, ls in lines.items():
        if n in toc:
            continue
        for i, l in enumerate(ls):
            m = SECTION_HEAD_RE.match(l)
            if not m or TOC_LEADER_RE.search(l):
                continue
            title = m.group(2).strip()
            if not title and i + 1 < len(ls) and len(ls[i + 1].strip()) <= 24:
                title = ls[i + 1].strip()                       # "第三节" on one line, its title on the next
            if title and "节" not in title and not re.search(r"[“”\"，,。]", title):
                heads.append((n, i, m.group(1), title))
    mda = next((h for h in heads if MDA_TITLE_RE.search(h[3])), None)
    if not mda:
        return "", "", 0, "no 第X节 管理层讨论与分析 heading found in the report body"
    mda_start = (mda[0], mda[1])
    after = next((h for h in heads if (h[0], h[1]) > mda_start and h[2] != mda[2]), None)
    mda_end = (after[0], after[1]) if after else (max(lines), len(lines[max(lines)]))

    keep, notes = {}, {}                                         # page -> line indexes kept; page -> a note

    def add_range(start, end):
        """Keep every line from `start` (page, line) up to, not including, `end` (page, line)."""
        for n in sorted(lines):
            if start[0] <= n <= end[0]:
                first = start[1] if n == start[0] else 0
                last = end[1] if n == end[0] else len(lines[n])
                keep.setdefault(n, set()).update(range(first, last))

    # 2. part A: 第二节 from '主要会计数据和财务指标' to the MD&A heading
    sec2 = next((h for h in heads if h[2] == "二"), None)
    fin_start = next(((n, i) for n in sorted(lines) if n not in toc for i, l in enumerate(lines[n])
                      if KEY_FIN_RE.search(l) and not TOC_LEADER_RE.search(l)
                      and (not sec2 or (n, i) > (sec2[0], sec2[1])) and (n, i) < mda_start), None)
    if fin_start:
        add_range(fin_start, mda_start)
        notes[fin_start[0]] = "第二节: from 主要会计数据和财务指标 (key financial data)"
    # 3. part B: the MD&A, whole
    add_range(mda_start, mda_end)
    notes[mda_start[0]] = (notes[mda_start[0]] + "; " if mda_start[0] in notes else "") + f"第{mda[2]}节 {mda[3]} (MD&A) starts"
    notes[mda_end[0]] = notes.get(mda_end[0], "the MD&A ends on this page")
    # 4. part C: other pages with top-5 / CIP projects / raised-fund projects / major contracts / capacity
    parent = next((n for n in sorted(lines) if n not in toc
                   for l in lines[n] if PARENT_NOTES_RE.search(l) and not TOC_LEADER_RE.search(l)), None)
    stop = parent if parent else max(lines) + 1
    for n in sorted(lines):
        if n in toc or n >= stop or (n >= mda_start[0] and n <= mda_end[0]):
            continue
        text = text_of[n] or ""
        hits = extra_hits(text)
        if not hits:
            continue
        keep.setdefault(n, set()).update(range(len(lines[n])))
        notes[n] = "outside the MD&A: " + ", ".join(dict.fromkeys(m.group(0) for m in hits))
        nxt = n + 1
        if hits[-1].start() > 0.6 * len(text) and nxt in lines and nxt < stop and nxt not in keep:
            keep[nxt] = set(range(len(lines[nxt])))
            notes[nxt] = f"continued from page {n}"

    # 5. the body, page by page, and where each key item sits
    parts, kept_text = [], {}
    for n in sorted(keep):
        body = "\n".join(lines[n][i] for i in sorted(keep[n])).strip()
        if not body:
            continue
        kept_text[n] = body
        parts.append(f"==== page {n}" + (f" ({notes[n]})" if notes.get(n) else "") + f" ====\n{body}\n")
    found, absent = [], []
    for name, pat in LOCATE:
        where = [n for n, body in kept_text.items() if re.search(pat, body)]
        if where:
            found.append(f"{name} p{', p'.join(str(n) for n in where[:6])}" + (" …" if len(where) > 6 else ""))
        else:
            absent.append(name)
    located = "; ".join(found) + (f". Not in the extract: {', '.join(absent)}" if absent else "")
    return "\n".join(parts), located[:700], len(kept_text), None


def choose_reports(co, listed, first_look, since, state, elsewhere):
    """Decide which of one company's listed periodic-report announcements to save.
    Returns ([(item id, announcement, kind, year, variant)], [(item id, skip reason)])."""
    name = co["name"]
    skips, groups = [], {}
    for a in listed:
        item = f"rep:{a['announcementId']}"
        before = str(state["seen"].get(item, ""))
        if before and not (since and before.startswith("skip:older")):
            continue                     # handled by an earlier run (--since re-opens only the 'older' skips)
        title = clean(a.get("announcementTitle"))
        day = cst_day(a["announcementTime"])
        found = report_kind(title, day)
        variant = report_variant(title) if found else "not a periodic report"
        if variant not in ("original", "corrected", "english"):
            skips.append((item, f"{variant} ({title[:40]})"))
            continue
        groups.setdefault(found, []).append({"item": item, "a": a, "title": title, "day": day, "variant": variant})

    # One report per (kind, fiscal year): the Chinese original; a corrected re-issue only when no original is
    # listed; the English version only when it is the only full version.
    order = {"original": 0, "corrected": 1, "english": 2}
    best = {}
    for key, cands in groups.items():
        cands.sort(key=lambda c: (order[c["variant"]], c["day"]))
        best[key] = cands[0]
        for c in cands[1:]:
            skips.append((c["item"], f"{c['variant']} version: the {cands[0]['variant']} one is kept "
                                     f"({cands[0]['title'][:30]})"))

    # A company's first look (the backfill): only its newest annual and half-year report, and the newest
    # quarterly report only when it is newer than both (in October the 2026 half-year report supersedes the
    # 2026 Q1 report; in late October the Q3 report is the newest and is taken).
    if first_look:
        newest = {}
        for (kind, year), c in best.items():
            group = "quarterly" if kind in ("q1", "q3") else kind
            if group not in newest or c["day"] > newest[group][1]["day"]:
                newest[group] = ((kind, year), c)
        wanted = {newest[g][0] for g in ("annual", "half") if g in newest}
        big_day = max((newest[g][1]["day"] for g in ("annual", "half") if g in newest), default=None)
        if "quarterly" in newest and (big_day is None or newest["quarterly"][1]["day"] > big_day):
            wanted.add(newest["quarterly"][0])
        for key in list(best):
            if key not in wanted:
                skips.append((best[key]["item"], "older: a company's first look takes only its newest report of each kind"))
                del best[key]

    # Never save a report twice: saved earlier by this pipeline, or saved by hand before 2026-10-04.
    saved = {(d["company"], d["kind"], d["year"]): d["label"] for d in state["docs"].values()}
    chosen = []
    for (kind, year), c in sorted(best.items(), key=lambda kv: kv[1]["day"]):
        key = (name, kind, year)
        if key in saved:
            skips.append((c["item"], f"{c['variant']}: already saved as {saved[key]}"))
        elif key in elsewhere:
            skips.append((c["item"], f"saved by hand earlier: {elsewhere[key]}"))
        else:
            chosen.append((c["item"], c["a"], kind, year, c["variant"]))
    return chosen, skips


def take_report(co, item, a, kind, year, variant, state):
    """Download one periodic report, save the whole text (+ the extract of an annual / half-year report) and
    queue it. Returns None (saved) or the skip reason ('pdf: …' = decided by the file itself)."""
    url = STATIC + a["adjunctUrl"]
    day = cst_day(a["announcementTime"])
    title = clean(a.get("announcementTitle"))
    content = http("GET", url).content
    if content[:4] != b"%PDF":
        return "pdf: not a PDF"
    digest = hashlib.sha256(content).hexdigest()
    if digest in state["hashes"]:
        return f"pdf: same file as {state['hashes'][digest]}"
    try:
        pages = pdf_pages(content)
    except Exception as exc:                          # an encrypted or broken file
        return f"pdf: could not be read ({exc.__class__.__name__})"
    pages = [(n, t.translate(str.maketrans(GLYPHS))) for n, t in pages]
    text = "".join(t for _n, t in pages)
    if len(text) < MIN_TEXT * 10:
        state["hashes"][digest] = f"image-only ({item})"
        return "pdf: image-only (no text layer)"
    share = cjk_share(text)
    if variant != "english" and share < REPORT_MIN_CJK:
        return f"pdf: text layer unreadable (Chinese characters only {share:.0%} of the text)"

    company = co["name"]
    word, shown = REPORT_KINDS[kind]
    label = f"{company} {word}: {shown.format(year=year)} ({mdy(day)})"
    stem = f"{slug(company)}_{day.isoformat()}_report_{a['announcementId']}"
    full_path = REPORT_DIR / f"{stem}.txt"
    extract_path = REPORT_DIR / f"{stem}_extract.txt"
    full_rel = full_path.relative_to(ROOT).as_posix()
    version = {"english": "  [English version: no Chinese full version was listed]",
               "corrected": "  [corrected re-issue: the original was not listed]"}.get(variant, "")
    header = [
        f"SOURCE: {url}",
        f"TITLE: {title} — cninfo announcement {a['announcementId']}{version}",
        f"DATE: {day.isoformat()} (disclosure day, China time; the label date)",
        f"COMPANY: {company} ({co['code']} {co['exchange']})",
        f"# NOTE: company statutory report — NOT a transcript. The company's own {REPORT_KIND_CN[kind]}, filed on",
        "#       cninfo: facts and the company's own statements, enriched like a DART periodic report (enrich skill §4",
        "#       slot table: statutory financial statements — any slot, the ONE best entry per slot). Every entry in",
        "#       English (§8), RMB amounts in English, Chinese names mapped to the canonical node. A named top-5",
        "#       customer that is a node -> a contract on the edge; unnamed ones (客户一 / 客户A) stay on the company's",
        "#       own quarterly_data, never mapped to a name (references/cninfo.md, 'Periodic reports').",
    ]

    # Annual / half-year reports: the extract the enricher reads. Quarterly reports are short: read whole.
    queued, extract_note = full_path, ""
    if kind in ("annual", "half"):
        body, located, kept, warning = report_extract(pages)
        if warning:
            extract_note = f"no extract ({warning}) — read the whole report"
            print(f"  {company}: {extract_note}")
        else:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            extract_path.write_text("\n".join(header + [
                f"# EXTRACT: {kept} of {len(pages)} pages — 第二节 key financial data, 第三节 管理层讨论与分析 (MD&A) whole, and",
                "#          the pages elsewhere with top-5 customers / suppliers, top-5 receivables / prepayments, major",
                "#          construction-in-progress projects, raised-fund projects, other major contracts or capacity.",
                f"#          The whole report: {full_rel} (open it to read around a cut table)",
                f"# LOCATED: {located}",
                f"# source label: {label}",
                ""]) + body, encoding="utf-8")
            queued = extract_path
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reads = ("the enricher reads the _extract file beside it; this file is what verify_graph.py checks"
             if queued == extract_path else extract_note or "a short report: read it whole")
    full_path.write_text("\n".join(header + [f"# PAGES: {len(pages)} — the whole report, page by page ({reads})",
                                             f"# source label: {label}", ""])
                         + "".join(f"==== page {n} ====\n{t}\n" for n, t in pages if t), encoding="utf-8")

    state["hashes"][digest] = label
    state["docs"][item] = {"company": company, "kind": kind, "year": year, "label": label, "date": day.isoformat(),
                           "title": title, "pages": len(pages), "file": queued.relative_to(ROOT).as_posix(),
                           "full": full_rel}
    queue_row("report", company, label, queued, day, item, full=full_path if queued != full_path else None)
    return None


def sync_reports(since=None, company=None):
    """Find, save and queue the periodic reports of every A-share company (or one). See REPORT_FILTERS."""
    state = load(REPORTS_STATE, {})
    for key, default in (("last_sync", None), ("runs", []), ("companies", {}), ("seen", {}), ("docs", {}),
                         ("hashes", {})):
        state.setdefault(key, default)
    state["filters"] = REPORT_FILTERS
    ours, hk = universe()
    if company:
        ours = [c for c in ours if c["name"] == company]
        if not ours:
            sys.exit(f"{company!r} is not an SZSE / SSE company in company_metadata.json")
    elsewhere = reports_saved_elsewhere()
    today = today_cst()
    totals = {"saved": 0, "skipped": 0, "failed": 0}
    for co in ours:
        name = co["name"]
        known = state["companies"].get(name)
        first_look = since is None and known is None
        if since:
            start = since
        elif known:
            start = datetime.strptime(known["last_sync"][:10], "%Y-%m-%d").date() - timedelta(days=7)
        else:
            start = today - timedelta(days=REPORT_BACK)
        saved_now, listed = 0, []
        try:
            if not org_id(co["code"]):
                print(f"{name:26s} no cninfo orgId for {co['code']} (not listed yet?) — skipped")
                continue
            listed = cninfo_list(co, "fulltext", start, today + timedelta(days=1), category=REPORT_CATEGORIES)
            chosen, skips = choose_reports(co, listed, first_look, since, state, elsewhere)
            for item, why in skips:
                state["seen"][item] = f"skip:{why}"
                totals["skipped"] += 1
            for item, a, kind, year, variant in chosen:
                why = take_report(co, item, a, kind, year, variant, state)
                state["seen"][item] = "saved" if why is None else f"skip:{why}"
                if why:
                    print(f"  skip {name} {item}: {why}")
                    totals["skipped"] += 1
                else:
                    saved_now += 1
                    totals["saved"] += 1
                save(REPORTS_STATE, state)                  # after every report, so an interrupted run resumes
        except (requests.RequestException, ValueError) as exc:     # one company's failure must not stop the run
            print(f"  {name}: fetch failed ({exc.__class__.__name__}: {str(exc)[:100]}) — retried next run")
            totals["failed"] += 1
            save(REPORTS_STATE, state)
            continue
        state["companies"][name] = {"last_sync": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
                                    "since": start.isoformat()}
        print(f"{name:26s} since {start}: {len(listed)} periodic-report announcement(s) listed, {saved_now} saved")
        save(REPORTS_STATE, state)
    if not company:
        state["last_sync"] = today.isoformat()
    state["runs"].append({"at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
                          "since": since.isoformat() if since else "per company",
                          "company": company or "all", **totals})
    save(REPORTS_STATE, state)
    print(f"\n{totals['saved']} report(s) saved, {totals['skipped']} announcement(s) skipped (reasons in "
          f"{REPORTS_STATE.relative_to(ROOT).as_posix()}), {totals['failed']} company fetch(es) failed; "
          f"queue now {len(load(PENDING, []))}")
    if hk and not company:
        print("out of scope (Hong Kong-only listings, no A-share disclosure): " + ", ".join(sorted(hk)))


# ---------------------------------------------------------------- queue

def mark_done(rows, why=None):
    state = load(STATE, {"seen": {}})
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        if r.get("kind") == "report":
            continue                                   # periodic reports: their own state file, below
        for item in str(r["id"]).split(","):
            state.setdefault("seen", {})[item] = stamp
    save(STATE, state)
    reports = [r for r in rows if r.get("kind") == "report"]
    if reports:
        rstate = load(REPORTS_STATE, {"seen": {}})
        for r in reports:
            rstate.setdefault("seen", {})[r["id"]] = stamp
        save(REPORTS_STATE, rstate)


def status(company=None):
    queued = {r["file"] for r in load(PENDING, [])}
    for f in sorted(OUT_DIR.glob("*.txt")) if OUT_DIR.exists() else []:
        head = f.read_text(encoding="utf-8").split("\n", 12)
        co = next((l.split(": ", 1)[1].split(" (")[0] for l in head if l.startswith("COMPANY: ")), "?")
        lab = next((l.split(": ", 1)[1] for l in head if l.startswith("# source label: ")), "?")
        if company and co != company:
            continue
        rel = f.relative_to(ROOT).as_posix()
        print(f"{'queued' if rel in queued else 'handled':8s} {lab:75s} {rel}")
    rstate = load(REPORTS_STATE, {})
    for item, d in sorted(rstate.get("docs", {}).items(), key=lambda kv: kv[1]["date"]):
        if company and d["company"] != company:
            continue                                   # periodic reports (`reports` command), from their state file
        print(f"{'queued' if d['file'] in queued else 'handled':8s} {d['label']:75s} {d['file']}")
    state = load(STATE, {})
    ours, hk = universe()
    for co in ours:
        if company and co["name"] != company:
            continue
        info = state.get("companies", {}).get(co["name"])
        rinfo = rstate.get("companies", {}).get(co["name"])
        print(f"  {co['name']:26s} {co['exchange']:4s} last sync {info['last_sync'] if info else 'never':16s} "
              f"reports {rinfo['last_sync'] if rinfo else 'never'}")
    if hk and not company:
        print("out of scope (Hong Kong-only): " + ", ".join(sorted(hk)))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: 7 days before the company's last sync, or its latest call (≤120 days) / 30 days")
    s.add_argument("--company")
    r = sub.add_parser("reports")
    r.add_argument("--since", help="YYYY-MM-DD: every periodic report filed since then; default: 7 days before the "
                                   "company's last run, or (first look) its newest annual + half-year report")
    r.add_argument("--company")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--market", help="accepted for symmetry with the other collectors; every row here is CN")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a file yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company)
    elif args.cmd == "reports":
        sync_reports(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company)
    elif args.cmd == "pending":
        rows = load(PENDING, [])
        if args.market and args.market != "CN":
            rows = []
        rows = [r for r in rows if not args.company or r["company"] == args.company]
        for r in rows:
            print(f"{r['date']}  {r['kind']:6s} {r['company']:24s} {r['label']:75s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit('give --label "<label>" (one file) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)


if __name__ == "__main__":
    main()
