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

Commands (python -X utf8 cninfo.py …)
-------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>"]   fetch new records and answers, save, queue
    pending [--company "<Company>"] [--market CN]       the queue (`enrich china` works it)
    done --label "<label>" [--why …]                     one file handled (enriched, or "no material facts")
    done --all                                           every queued file handled (only when true)
    status [--company "<Company>"]                       every saved file and its state; out-of-scope names

Files
-----
    transcripts/cninfo/<slug>_<YYYY-MM-DD>_record_<id>.txt   one IR activity record (PDF text, page by page)
    transcripts/cninfo/<slug>_<YYYY-MM-DD>_qa_<szse|sse>.txt   one company's kept answers of one day
    cninfo/sync_state.json   last sync, runs, per-company window, every item id handled
                             (saved / skip:<why> / enriched:<date>), record hashes, SSE uids, the filter rules
    cninfo/pending.json      saved files not yet enriched

Labels (enrich skill §5)
------------------------
    <Company> IR activity record: <record no., or the date> (MM-DD-YYYY)   dated the disclosure day
    <Company> investor Q&A: <platform> (MM-DD-YYYY)                        dated the answer day, one per company per day
    e.g. "Innolight IR activity record: 2026-008 (08-23-2026)", "Eoptolink investor Q&A: SZSE Interactive Easy (09-23-2026)"

How the sources answer (found 2026-10-01; all public, no login, no token)
-----------------------------------------------------------------------
cninfo announcements: POST http://www.cninfo.com.cn/new/hisAnnouncement/query (the site's own search form;
    stock=<code>,<orgId>, column=szse|sse, tabName=relation (= 调研活动 tab) or fulltext, seDate=a~b).
    orgId comes from http://www.cninfo.com.cn/new/data/szse_stock.json (every A-share, SZSE and SSE).
    PDFs at https://static.cninfo.com.cn/<adjunctUrl>. The relation tab holds SZSE companies' records;
    SSE companies file none there, so their fulltext list is scanned for record titles as well.
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
    """[(page number, text)] of a PDF (pypdf), every page."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return [(i, (p.extract_text() or "").strip()) for i, p in enumerate(reader.pages, 1)]


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


def queue_row(kind, company, label, path, day, item_id):
    pending = load(PENDING, [])
    pending.append({"kind": kind, "company": company, "label": label, "file": path.relative_to(ROOT).as_posix(),
                    "date": day.isoformat(), "id": item_id})
    save(PENDING, pending)
    print(f"  saved {label}")


# ---------------------------------------------------------------- 1. IR activity records

def cninfo_list(co, tab, since, until):
    """Every announcement of one company on one cninfo tab between two dates -> [dict]."""
    column = "szse" if co["exchange"] == "SZSE" else "sse"
    out, page = [], 1
    while True:
        data = http("POST", QUERY_URL, headers={"X-Requested-With": "XMLHttpRequest"}, data={
            "pageNum": str(page), "pageSize": "30", "column": column, "tabName": tab, "plate": "",
            "stock": f"{co['code']},{org_id(co['code'])}", "searchkey": "", "secid": "", "category": "",
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


# ---------------------------------------------------------------- queue

def mark_done(rows, why=None):
    state = load(STATE, {"seen": {}})
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        for item in str(r["id"]).split(","):
            state.setdefault("seen", {})[item] = stamp
    save(STATE, state)


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
    state = load(STATE, {})
    ours, hk = universe()
    for co in ours:
        if company and co["name"] != company:
            continue
        info = state.get("companies", {}).get(co["name"])
        print(f"  {co['name']:26s} {co['exchange']:4s} last sync {info['last_sync'] if info else 'never'}")
    if hk and not company:
        print("out of scope (Hong Kong-only): " + ", ".join(sorted(hk)))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: 7 days before the company's last sync, or its latest call (≤120 days) / 30 days")
    s.add_argument("--company")
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
