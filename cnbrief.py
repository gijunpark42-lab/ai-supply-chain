"""
cnbrief.py — China A-share results briefings (业绩说明会): the FULL live text Q&A, saved verbatim →
transcripts/cnbrief/*.txt, queued for `enrich china`.

Why this exists
---------------
Our A-share companies rarely hold an English earnings call, but almost all of them hold a results briefing
(业绩说明会) after their annual report, and many after their half-year / Q3 report too. It is an online event
on an exchange-linked roadshow platform: investors type questions, and the company's executives / IR type the
answers live, under their own names. The platform keeps the whole exchange online afterwards.
cninfo.py already saves the company's later announcement about the event (业绩说明会召开情况 / 投资者关系活动记录表)
— a SUMMARY written by the company. This collector saves the event itself: every answer, word for word.

The answers (and the company's own statements) are the company's words; the questions come from anonymous retail
investors and only frame the answers (enrich skill §2: like a conference talk, questions are context only).

Sources (all public JSON behind the platforms' own pages; no login, no token — found 2026-10-21)
---------------------------------------------------------------------------------------------
1. SSE Roadshow Center 上证路演中心 (roadshow.sseinfo.com, run by the Shanghai Stock Exchange's information company,
   上证所信息网络有限公司) — where SSE companies hold their briefings, alone or in the exchange's collective
   briefings (集体业绩说明会). Form-encoded POSTs to https://roadshow.sseinfo.com/base-service/api/pub/v1/…
     company/select_company_list         searchKeyWord=<stock code>              -> companyId
     activity/select_company_activity_list  companyId, pageNo, pageSize          -> the company's events (newest first;
                                                                                    status 3 = over, isMulti = collective)
     activity_guest/activity_guest_list  activityId, companyId, size=0          -> the company's guests (name, title)
     question_answer/answer_question_page  activityId, companyId, questionTypeList=2,3,4, pageNo, pageSize
                                          -> type 2 = an answer (with its question), 3 = a company guest's statement,
                                             4 = the host; guestName / guestTitle = who answered
     activity/question_collect_activity_page  activityId, companyId, pageNo, pageSize<=50
                                          -> questions collected BEFORE the event and the company's answers
   Page: https://roadshow.sseinfo.com/activityDetails/<id> (one company) or …/singleCompany/<id>/<companyId> (collective).
2. 全景路演 rs.p5w.net (全景网) — where most SZSE companies (and some SSE ones) hold theirs, alone or in a
   regional collective (投资者网上集体接待日暨业绩说明会, run with the local securities regulator / association).
     roadshow/getAllRoadshowList.shtml   roadshowTitle=<stock code>, perComType=0, page (0-based), rows
                                          -> every event of the company, collectives included, newest first
     roadshow/multCompanyList.shtml      companyRoadshowId=<collective pid>  -> each company's own room (pid)
     roadshowLive/getNInteractionDatas.shtml  roadshowId=<pid of the company's room>, type=1, isPagination=1, page, rows
                                          -> every line: host (speakType 1), questions (3) with replyList (the answers,
                                             speakUserName = who answered, e.g. "董事会秘书肖云兮")
3. SZSE 互动易 云访谈 (irm.cninfo.com.cn, run by the Shenzhen Stock Exchange's information company) — some SZSE
   companies hold their briefing on the exchange's own Q&A site.
     newircs/index/search                searchTypes=5,6,7, stockCode=<cninfo orgId>_<code>, pageNo, pageSize
                                          -> the company's online briefings (updateDate = start, pubDate = end, ms)
     interview/interview/findInterviewRecords  activityId, pageNo  -> publishVo (company statements), replyVo (an answer
                                          with its question), questionVo (a question; unanswered unless a reply has it)
   Page: https://irm.cninfo.com.cn/interview/interview/activityInfo?activityId=<id>

NOT covered (said so in the reference doc): briefings held on commercial IR platforms — 价值在线 (ir-online.cn /
eseb.cn: the page needs an OAuth login), 进门财经 (comein.cn, mostly audio), 约调研, 路演中 (roadshowchina.cn),
中国证券网路演中心 (roadshow.cnstock.com). For those companies cninfo.py's summary announcement is the record.

Commands (python -X utf8 cnbrief.py …)
-------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>" …] [--budget MIN]   find new briefings, save, queue
    pending [--company "<Company>"] [--market CN]                         the queue (`enrich china` works it)
    done --label "<label>" [--why …]                                      one briefing handled
    done --all                                                            every queued briefing handled (only when true)
    status [--company "<Company>"]                                        every event seen and its state

Files
-----
    transcripts/cnbrief/<slug>_<YYYY-MM-DD>_<sse|p5w|irm>_<id>.txt   header + the whole Q&A, verbatim (Chinese stays Chinese)
    cnbrief/sync_state.json   last sync, runs (with counts), per-company window, every event id seen {company, date,
                              platform, title, status = saved:<label> / skip:<why> / later:<why> / enriched:<date>},
                              the filter rules,
                              cached SSE companyIds, and one key per saved event (company | date | period) so the same
                              briefing listed on two platforms is saved once
    cnbrief/pending.json      saved briefings not yet enriched

Label (enrich skill §5; the shape of the Japan results-briefing exception)
--------------------------------------------------------------------------
    <Company> results briefing Q&A: <period(s)>[ collective] (MM-DD-YYYY)     dated the briefing day (China time)
    <Company> investor briefing Q&A: <platform> <event id> (MM-DD-YYYY)       a non-results 说明会 (M&A, restructuring)
    e.g. "JCET results briefing Q&A: H1 2026 (08-21-2026)",
         "Montage Technology results briefing Q&A: 2025 annual and Q1 2026 (05-14-2026)",
         "Eoptolink results briefing Q&A: H1 2026 collective (09-11-2026)"
"""

import argparse
import html as htmllib
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from cninfo import org_id, universe       # the same A-share universe; cninfo's orgId is 互动易's company id
from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
STATE = ROOT / "cnbrief" / "sync_state.json"
PENDING = ROOT / "cnbrief" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "cnbrief"

SSE_API = "https://roadshow.sseinfo.com/base-service/api/pub/v1"
SSE_SITE = "https://roadshow.sseinfo.com"
P5W = "https://rs.p5w.net"
IRM = "https://irm.cninfo.com.cn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
CST = timezone(timedelta(hours=8))       # every time on these platforms is China time
FIRST_BACK = 200                         # a company's first sync: ~6.5 months, so it holds the whole annual-briefing season (April-May)
OVERLAP = 7                              # a later sync re-lists from this many days before the company's last sync
GAP = 1.2                                # seconds between two requests (all platforms together)
BUDGET_MIN = 45                          # default run-time budget; companies not reached wait for the next sync

PLATFORM = {
    "sse": "SSE Roadshow Center 上证路演中心 (roadshow.sseinfo.com — the Shanghai Stock Exchange's information company)",
    "p5w": "全景路演 rs.p5w.net (全景网 — the online roadshow platform SZSE companies use for 业绩说明会)",
    "irm": "SZSE 互动易 云访谈 (irm.cninfo.com.cn — the Shenzhen Stock Exchange's information company)",
}
PLATFORM_SHORT = {"sse": "SSE Roadshow", "p5w": "p5w", "irm": "SZSE Interactive Easy"}

# ---------------------------------------------------------------- what is kept, what is skipped (and why)
# Event types the platforms list that are never a results / investor briefing (the type text the platform gives).
SKIP_TYPES = {"IPO路演", "仪式", "上市仪式", "摇号抽签", "再融资", "可转债路演", "金融培训", "财经节目", "论坛峰会",
              "发布会", "项目路演", "分析师解读"}
# Titles of offerings and ceremonies (financing roadshows: the prospectus is the source, enrich skill §2).
FINANCING_RE = re.compile(r"首次公开发行|上市仪式|摇号|抽签|可转换公司债|可转债|向特定对象发行|再融资|网上路演|网上投资者交流会")
# (a title that also names results, e.g. "…业绩网上路演", is still a results briefing)
RESULTS_RE = re.compile(r"业绩|年度报告|年报|半年报|季报|中报")            # a results briefing
BRIEFING_RE = re.compile(r"说明会|接待日|交流会|座谈会|沟通会|交流活动")      # any other investor briefing (M&A, restructuring …)

FILTERS = {
    "kept": "results briefings (业绩说明会, 年度报告网上说明会, collective 集体业绩说明会 / 投资者网上集体接待日暨业绩说明会) and "
            "other investor briefings the company holds (重大事项 / 重大资产重组 / 投资者说明会) on the SSE Roadshow Center, "
            "全景路演 rs.p5w.net or SZSE 互动易 云访谈 — once the event is over; the WHOLE text: every answer with its "
            "question and who answered, the company's own statements, pre-collected questions the company answered, "
            "the host's lines. Nothing inside a briefing is filtered or shortened.",
    "skipped": "IPO / bond / refinancing roadshows, listing ceremonies, lotteries, training, forums, shows (SKIP_TYPES, "
               "FINANCING_RE); events not over yet (later: — retried every sync); an event with no answered question and "
               "no company statement; the same briefing already saved from another platform (same company, day and "
               "period); questions nobody answered (counted in the file header, not saved)",
    "not_covered": "briefings on commercial platforms (价值在线 / ir-online.cn needs a login; 进门财经, 约调研, 路演中, "
                   "roadshow.cnstock.com) — cninfo.py's 业绩说明会召开情况 summary announcement is the record there",
}


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def mdy(d):
    return d.strftime("%m-%d-%Y")


def today_cst():
    return datetime.now(CST).date()


def ms_to_cst(ms):
    """Milliseconds since 1970 (what 互动易 gives) -> a China-time datetime."""
    return datetime.fromtimestamp(int(ms) / 1000, CST)


def clean(text):
    """A platform text field -> plain text. Only the HTML is removed: <br> / </p> become line breaks, tags go,
    entities (&ldquo; &nbsp;) become characters, runs of spaces shrink. The words themselves are untouched."""
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    for _ in range(2):                                # some fields are escaped twice ("&amp;ldquo;")
        text = htmllib.unescape(text)
    lines = (re.sub(r"[ \t\r\f\v　\xa0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
_last = [0.0]


def _polite():
    """One request every GAP seconds, across all three platforms."""
    wait = GAP - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def http_json(method, url, data=None, params=None):
    """GET / POST (form-encoded) -> the JSON answer, with three tries and a growing pause (3 s, 6 s) after a network
    error or a 5xx answer. Any other failure raises: the caller records the event as `later:` and the next sync
    retries it. (All three sources are JSON endpoints; Jina Reader cannot replay a POST, so it is no fallback here.)"""
    for attempt in range(3):
        _polite()
        try:
            r = _session.request(method, url, data=data, params=params, timeout=60)
            if r.status_code < 500:
                r.raise_for_status()
                return r.json()
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
        time.sleep(3 * (attempt + 1))
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- titles -> kind and English label text

def classify(title, type_text):
    """('results' | 'event', None) to keep an event, or ('skip', reason)."""
    if type_text in SKIP_TYPES:
        return "skip", f"{type_text}: not a results or investor briefing"
    if FINANCING_RE.search(title) and not RESULTS_RE.search(title):
        return "skip", "IPO / bond / refinancing roadshow or ceremony"
    if RESULTS_RE.search(title) or periods(title):      # '…2025年年度暨2026年第一季度…说明会' names results too
        return "results", None
    if BRIEFING_RE.search(title):
        return "event", None
    return "skip", f"not a briefing ({type_text or 'no type'})"


def periods(title, day=None):
    """The reporting periods a briefing title names, in English, in title order:
    '2025年年度暨2026年第一季度业绩说明会' -> ['2025 annual', 'Q1 2026']; '2026年半年度…' -> ['H1 2026'].
    A period word with no year of its own ('四川辖区2026年投资者网上集体接待日及半年度报告业绩说明会') takes the title's
    year, else the briefing's year; an annual report is at most the year before the briefing (annual reports come
    out January-April)."""
    found = []
    for m in re.finditer(r"(20\d\d)", title):
        year, after = m.group(1), title[m.end():m.end() + 8]
        if re.match(r"\s*年?\s*(第?[一1]季度|一季报)", after):
            name = f"Q1 {year}"
        elif re.match(r"\s*年?\s*(半年|上半年|中期|中报)", after):
            name = f"H1 {year}"
        elif re.match(r"\s*年?\s*(第?[二2]季度)", after):
            name = f"Q2 {year}"
        elif re.match(r"\s*年?\s*(前?第?[三3]季度|三季报)", after):
            name = f"Q3 {year}"
        elif re.match(r"\s*年?\s*(年?度|报|全年)", after):
            name = f"{year} annual"
        else:
            continue
        if name not in found:
            found.append(name)
    if found or not day:
        return found
    year = re.search(r"(20\d\d)", title)
    year = int(year.group(1)) if year else day.year
    if re.search(r"半年|中报|中期", title):
        return [f"H1 {year}"]
    if re.search(r"第?[三3]季度|三季报", title):
        return [f"Q3 {year}"]
    if re.search(r"第?[一1]季度|一季报", title):
        return [f"Q1 {year}"]
    if re.search(r"年度|年报", title):
        return [f"{min(year, day.year - 1)} annual"]
    if year < day.year:                               # '—2025年集体业绩说明会' held in 2026: last year's annual results
        return [f"{year} annual"]
    return []


def make_label(company, ev, kind, state):
    """The source label (enrich skill §5), unique among this collector's labels."""
    when = mdy(ev["day"])
    if kind == "results":
        named = periods(ev["title"], ev["day"])
        what = " and ".join(named) if named else f"{PLATFORM_SHORT[ev['platform']]} {ev['short_id']}"
        if ev["multi"] or "集体" in ev["title"]:
            what += " collective"
        label = f"{company} results briefing Q&A: {what} ({when})"
    else:
        label = f"{company} investor briefing Q&A: {PLATFORM_SHORT[ev['platform']]} {ev['short_id']} ({when})"
    if label in state["labels"]:                       # two events of one company and day with the same period
        label = label.replace(f" ({when})", f" {ev['short_id']} ({when})")
    return label


# ---------------------------------------------------------------- 1. SSE Roadshow Center

def sse_company_id(co, state):
    """The roadshow center's companyId for a stock code (cached in the state file; None = not on the platform)."""
    cache = state.setdefault("sse_company_id", {})
    if co["code"] not in cache:
        rows = http_json("POST", SSE_API + "/company/select_company_list",
                         data={"searchKeyWord": co["code"], "pageNo": 1, "pageSize": 10})["datas"][0]["records"]
        hit = [r for r in rows if r.get("stockCode") == co["code"]]
        cache[co["code"]] = hit[0]["companyId"] if hit else None
    return cache[co["code"]]


def sse_events(co, start, state):
    """The company's events on the SSE Roadshow Center, newest first, paging back until `start`."""
    cid = sse_company_id(co, state)
    if not cid:
        return []
    out, page = [], 1
    while True:
        data = http_json("POST", SSE_API + "/activity/select_company_activity_list",
                         data={"companyId": cid, "pageNo": page, "pageSize": 20})["datas"][0]
        for a in data["records"]:
            day = date.fromisoformat(a["startDate"][:10])
            # the id names the company too: one collective event is read once for each of its companies
            out.append({"platform": "sse", "id": f"sse:{a['id']}:{co['code']}", "short_id": str(a["id"]), "day": day,
                        "time": f"{(a.get('startTime') or '')[11:16]}-{(a.get('endTime') or '')[11:16]}",
                        "title": clean(a["title"]),
                        "type_text": a.get("activityTypeText") or "", "multi": bool(a.get("isMulti")),
                        "over": a.get("status") == 3,
                        "url": (f"{SSE_SITE}/singleCompany/{a['id']}/{cid}" if a.get("isMulti")
                                else f"{SSE_SITE}/activityDetails/{a['id']}"),
                        "activity": a["id"], "cid": cid})
        oldest = date.fromisoformat(data["records"][-1]["startDate"][:10]) if data["records"] else start
        if page >= int(data.get("pages") or 1) or oldest < start or page >= 10:
            return out
        page += 1


def sse_pages(path, data, size):
    """Every record of a paged SSE list."""
    records, page = [], 1
    while True:
        got = http_json("POST", SSE_API + path, data=data + [("pageNo", page), ("pageSize", size)])
        if not got.get("success"):
            raise ValueError(f"SSE {path}: {got.get('message')}")
        block = got["datas"][0]
        records += block["records"]
        if page >= int(block.get("pages") or 1) or page >= 50:
            return records
        page += 1


def sse_read(ev):
    """One SSE briefing -> {guests, pre, live, unanswered, data}. Only this company's lines (collectives too)."""
    base = [("activityId", ev["activity"]), ("companyId", ev["cid"])]
    guests = http_json("POST", SSE_API + "/activity_guest/activity_guest_list", data=base + [("size", 0)]).get("datas") or []
    # one company's own event: every line (the host's too); a collective: only this company's lines (and the host's
    # lines addressed to it) — that is what the companyId filter returns
    lines = base if ev["multi"] else base[:1]
    answers = sse_pages("/question_answer/answer_question_page",
                        lines + [("questionTypeList", 2), ("questionTypeList", 3), ("questionTypeList", 4)], 100)
    collected = sse_pages("/activity/question_collect_activity_page", base, 50)
    pre = [{"q": clean(r.get("question")), "q_time": r.get("crtTime") or "", "a": clean(r.get("answer")),
            "a_time": r.get("updTime") or "", "who": "the company"}
           for r in sorted(collected, key=lambda r: r.get("crtTime") or "") if clean(r.get("answer"))]
    live = []
    for r in sorted(answers, key=lambda r: r.get("crtTime") or ""):
        who = ", ".join(x for x in (clean(r.get("guestName")), clean(r.get("guestTitle"))) if x) or "the company"
        if ev["multi"] and r.get("guestCompanyName"):
            who += f" — {clean(r['guestCompanyName'])}"
        text = clean(r.get("content"))
        if not text:
            continue
        if r.get("questionType") == 2:
            live.append({"kind": "qa", "time": r.get("crtTime") or "", "q": clean(r.get("questionContent")),
                         "q_time": r.get("questionDate") or "", "answers": [(who, r.get("crtTime") or "", text)]})
        elif r.get("questionType") == 3:
            live.append({"kind": "statement", "time": r.get("crtTime") or "", "who": who, "text": text})
        else:
            live.append({"kind": "host", "time": r.get("crtTime") or "", "who": "host (上证路演中心)", "text": text})
    return {"guests": [", ".join(x for x in (clean(g.get("guestName")), clean(g.get("title"))) if x) for g in guests],
            "pre": pre, "live": live, "unanswered": None,
            "data": f"{SSE_API}/question_answer/answer_question_page (+ activity/question_collect_activity_page, "
                    f"activity_guest/activity_guest_list), activityId={ev['activity']}, companyId={ev['cid']}"}


# ---------------------------------------------------------------- 2. 全景路演 rs.p5w.net

def p5w_events(co, start):
    """The company's events on 全景路演 (collectives included), newest first, paging back until `start`."""
    out, page = [], 0
    while True:
        data = http_json("POST", P5W + "/roadshow/getAllRoadshowList.shtml",
                         data={"roadshowTitle": co["code"], "perComType": 0, "page": page, "rows": 20})
        rows = data.get("rows") or []
        for x in rows:
            if x.get("companyCode") not in (co["code"], None):   # a keyword hit on another company's title
                continue
            day = date.fromisoformat(x["roadshowDate"][:10])
            span = (x.get("roadshowDateTime") or "")[11:]
            out.append({"platform": "p5w", "id": f"p5w:{x['pid']}:{co['code']}", "short_id": str(x.get("urlNo") or x["pid"]),
                        "day": day, "time": span, "title": clean(x["roadshowTitle"]),
                        "type_text": x.get("roadshowTypeName") or "", "multi": x.get("singleMultitudeSign") == 1,
                        "over": str(x.get("roadshowStatus")) == "2", "url": x.get("roadshowUrl") or "",
                        "pid": x["pid"]})
        oldest = date.fromisoformat(rows[-1]["roadshowDate"][:10]) if rows else start
        if not rows or (page + 1) * 20 >= int(data.get("total") or 0) or oldest < start or page >= 10:
            return out
        page += 1


def p5w_read(co, ev):
    """One 全景路演 briefing -> {guests, pre, live, unanswered, data}. A collective event: this company's own room."""
    room, url = ev["pid"], ev["url"]
    if ev["multi"]:
        rooms = http_json("POST", P5W + "/roadshow/multCompanyList.shtml", data={"companyRoadshowId": ev["pid"]})
        mine = [r for r in rooms.get("rows") or [] if r.get("company_code") == co["code"]]
        if not mine:
            return None                                   # listed by keyword, but the company has no room in it
        room = mine[0]["pid"]
        url = f"{P5W}/html/{mine[0]['roadshow_url_no']}.shtml" if mine[0].get("roadshow_url_no") else url
    rows, page = [], 0
    while page < 60:
        got = http_json("POST", P5W + "/roadshowLive/getNInteractionDatas.shtml",
                        data={"roadshowId": room, "isPagination": 1, "rows": 50, "type": 1, "page": page})
        if not got.get("rows"):
            break
        rows += got["rows"]
        page += 1
    live, unanswered = [], 0
    for r in sorted(rows, key=lambda r: r.get("speakTime") or ""):
        text = clean(r.get("speakContent"))
        replies = [(clean(x.get("speakUserName")) or "the company", x.get("speakTime") or "", clean(x.get("speakContent")))
                   for x in r.get("replyList") or [] if clean(x.get("speakContent"))]
        speaker = clean(r.get("speakUserName"))
        if str(r.get("speakType")) == "3":               # an investor's question, with the company's answer(s)
            if replies:
                live.append({"kind": "qa", "time": replies[0][1], "q": text, "q_time": r.get("speakTime") or "",
                             "answers": replies})
            else:
                unanswered += 1
        elif text and (str(r.get("speakType")) in ("1", "5") or "主持人" in speaker):
            live.append({"kind": "host", "time": r.get("speakTime") or "", "who": "host (全景路演)", "text": text})
        elif text:
            live.append({"kind": "statement", "time": r.get("speakTime") or "", "who": speaker or "the company",
                         "text": text})
    return {"guests": [], "pre": [], "live": live, "unanswered": unanswered, "url": url,
            "data": f"{P5W}/roadshowLive/getNInteractionDatas.shtml roadshowId={room}"}


# ---------------------------------------------------------------- 3. SZSE 互动易 云访谈

def irm_events(co, start):
    """The company's online briefings on SZSE 互动易 (searchTypes 5, 6, 7 = its 云访谈 interviews)."""
    org = org_id(co["code"])
    if not org:
        return []
    out, page = [], 1
    while True:
        data = http_json("POST", IRM + "/newircs/index/search",
                         data={"pageNo": page, "pageSize": 20, "searchTypes": "5,6,7", "highLight": "false",
                               "stockCode": f"{org}_{co['code']}"})
        rows = data.get("results") or []
        for x in rows:
            if x.get("stockCode") != co["code"]:
                continue
            begin, end = ms_to_cst(x["updateDate"]), ms_to_cst(x["pubDate"])
            out.append({"platform": "irm", "id": f"irm:{x['indexId']}:{co['code']}", "short_id": str(x["indexId"]),
                        "day": begin.date(), "time": f"{begin:%H:%M}-{end:%H:%M}", "title": clean(x["mainContent"]),
                        "type_text": "", "multi": False, "over": end < datetime.now(CST),
                        "url": f"{IRM}/interview/interview/activityInfo?activityId={x['indexId']}",
                        "activity": x["indexId"]})
        oldest = ms_to_cst(rows[-1]["updateDate"]).date() if rows else start
        if not rows or page >= int(data.get("totalPage") or 1) or oldest < start or page >= 10:
            return out
        page += 1


def irm_read(ev):
    """One 互动易 briefing -> {guests, pre, live, unanswered, data}."""
    results, page = [], 1
    while page <= 60:
        got = http_json("POST", IRM + "/interview/interview/findInterviewRecords",
                        data={"activityId": ev["activity"], "pageNo": page, "pageSize": 50})
        if got.get("code") != "Y":
            raise ValueError(f"互动易 findInterviewRecords: {got.get('message') or got.get('code')}")
        results += got.get("results") or []
        if page >= int(got.get("pageCount") or 1):
            break
        page += 1
    live, asked, answered = [], set(), set()
    for x in results:
        if x.get("publishVo"):                            # the company's own posting during the event
            p = x["publishVo"]
            who = ", ".join(dict.fromkeys(v for v in (clean(p.get("publisher")), clean(p.get("guestPosition"))) if v))
            if clean(p.get("publishContent")):
                live.append({"kind": "statement", "time": p.get("publishDate") or "", "who": who or "the company",
                             "text": clean(p["publishContent"])})
        elif x.get("replyVo"):                            # an answer, with the question it answers
            rv = x["replyVo"]
            q = rv.get("question") or {}
            answered.add(rv.get("questionId"))
            replies = rv.get("pastReplyList") or [rv]
            answers = []
            for rep in replies:
                who = ", ".join(dict.fromkeys(v for v in (clean(rep.get("replyer")), clean(rep.get("guestPosition"))) if v))
                if clean(rep.get("replyContent")):
                    answers.append((who or "the company", rep.get("replyDate") or "", clean(rep["replyContent"])))
            if answers:
                live.append({"kind": "qa", "time": answers[0][1], "q": clean(q.get("questionContent")),
                             "q_time": q.get("questionDate") or "", "answers": answers})
        elif x.get("questionVo"):
            asked.add(x["questionVo"].get("questionId"))
    live.sort(key=lambda e: e["time"])
    return {"guests": [], "pre": [], "live": live, "unanswered": len(asked - answered),
            "data": f"{IRM}/interview/interview/findInterviewRecords activityId={ev['activity']}"}


# ---------------------------------------------------------------- writing one briefing

NOTE = (
    "# NOTE: NOT an earnings-call transcript — the company's own LIVE TEXT Q&A at its results briefing (业绩说明会) on an",
    "#       exchange-linked roadshow platform, typed by its executives / IR during the event and kept verbatim (Chinese).",
    "#       Treat it as MANAGEMENT Q&A (like a conference talk, enrich skill §2): the ANSWERS and the company's statements",
    "#       are the company's words — attribute them to the named executive when the line names one; the QUESTIONS are",
    "#       anonymous retail investors' — context only, never a fact (a number or customer only a question states is not",
    "#       captured). Host lines are the platform's. cninfo.py's 业绩说明会召开情况 / IR activity record of the same event",
    "#       is the company's SUMMARY of it: one event, enriched once, from this fuller text. Entries in English (§8).",
)


def body_text(content):
    """The briefing as text: pre-collected Q&A first (SSE), then the event in time order."""
    out = []
    if content["pre"]:
        out.append("==== PRE-COLLECTED QUESTIONS — sent in before the briefing, answered by the company ====")
        for i, r in enumerate(content["pre"], 1):
            out += [f"---- Pre-collected Q&A {i} (asked {r['q_time']}; answered {r['a_time']}) ----",
                    f"QUESTION (investor, context only): {r['q']}",
                    f"ANSWER ({r['who']}): {r['a']}", ""]
    out.append("==== THE BRIEFING — every line in time order ====")
    n = 0
    for e in content["live"]:
        if e["kind"] == "qa":
            n += 1
            out += [f"---- Q&A {n} ----", f"QUESTION (investor, context only; asked {e['q_time']}): {e['q']}"]
            out += [f"ANSWER — {who} ({when}): {text}" for who, when, text in e["answers"]]
            out.append("")
        elif e["kind"] == "statement":
            out += [f"---- COMPANY STATEMENT — {e['who']} ({e['time']}) ----", e["text"], ""]
        else:
            out += [f"---- HOST ({e['time']}) — {e['who']} ----", e["text"], ""]
    return "\n".join(out)


def take(co, ev, kind, state):
    """Read and save one briefing; return None (saved) or the reason it was not ('later: …' = retry next sync)."""
    if not ev["over"]:
        return "later: not held yet" if ev["day"] > today_cst() else "later: not over yet"
    named = periods(ev["title"], ev["day"])
    event_key = f"{co['name']}|{ev['day'].isoformat()}|{' and '.join(named)}"
    if kind == "results" and named and event_key in state["events"]:
        return f"same briefing already saved as {state['events'][event_key]}"
    if ev["platform"] == "sse":
        content = sse_read(ev)
    elif ev["platform"] == "p5w":
        content = p5w_read(co, ev)
        if content is None:
            return "collective event: the company has no room in it"
    else:
        content = irm_read(ev)
    qa = sum(1 for e in content["live"] if e["kind"] == "qa") + len(content["pre"])
    statements = sum(1 for e in content["live"] if e["kind"] == "statement")
    if not qa and not statements:
        return "no answered question and no company statement"
    hosts = sum(1 for e in content["live"] if e["kind"] == "host")
    label = make_label(co["name"], ev, kind, state)
    url = content.get("url") or ev["url"]
    unanswered = (f"; {content['unanswered']} question(s) nobody answered (not saved)"
                  if content["unanswered"] else "")
    header = [
        f"SOURCE: {url}",
        f"DATA: {content['data']}",
        f"TITLE: {ev['title']}",
        f"PLATFORM: {PLATFORM[ev['platform']]}",
        f"DATE: {ev['day'].isoformat()} {ev['time']} China time (the briefing; the label date)",
        f"COMPANY: {co['name']} ({co['code']} {co['exchange']})"
        + (" — a collective briefing: only this company's lines are kept" if ev["multi"] else ""),
    ]
    if content["guests"]:
        header.append("GUESTS (the company's people on the panel): " + "; ".join(content["guests"]))
    header += [
        f"CONTENT: {qa} answered question(s) ({len(content['pre'])} pre-collected), {statements} company statement(s), "
        f"{hosts} host line(s){unanswered}",
        *NOTE,
        f"# source label: {label}",
        "",
    ]
    path = OUT_DIR / f"{slug(co['name'])}_{ev['day'].isoformat()}_{ev['platform']}_{ev['short_id']}.txt"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + body_text(content) + "\n", encoding="utf-8")
    state["labels"].append(label)
    if named:
        state["events"][event_key] = label
    pending = load(PENDING, [])
    pending.append({"kind": "briefing", "company": co["name"], "label": label, "file": path.relative_to(ROOT).as_posix(),
                    "date": ev["day"].isoformat(), "id": ev["id"], "platform": ev["platform"], "title": ev["title"],
                    "answers": qa})
    save(PENDING, pending)
    print(f"  saved {label}  ({qa} answers)")
    return None


# ---------------------------------------------------------------- sync

def new_state():
    return {"last_sync": None, "runs": [], "companies": {}, "seen": {}, "labels": [], "events": {},
            "sse_company_id": {}}


def sync(since=None, companies=None, budget=BUDGET_MIN):
    state = load(STATE, new_state())
    for key, default in new_state().items():
        state.setdefault(key, default)
    state["filters"] = FILTERS
    ours, _hk = universe()
    if companies:
        missing = set(companies) - {c["name"] for c in ours}
        if missing:
            sys.exit(f"{sorted(missing)} not SZSE / SSE companies in company_metadata.json")
        ours = [c for c in ours if c["name"] in companies]
    today = today_cst()
    deadline = time.time() + budget * 60
    totals = {"listed": 0, "saved": 0, "skipped": 0, "later": 0, "failed": 0, "companies_done": 0}
    reasons = {}
    for co in ours:
        if time.time() > deadline:
            print(f"run-time budget of {budget} min used up — the remaining companies wait for the next sync")
            break
        name = co["name"]
        known = state["companies"].get(name)
        start = since or (date.fromisoformat(known["last_sync"][:10]) - timedelta(days=OVERLAP) if known
                          else today - timedelta(days=FIRST_BACK))
        try:
            events = sse_events(co, start, state) if co["exchange"] == "SSE" else irm_events(co, start)
            events += p5w_events(co, start)
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            print(f"  {name}: listing failed ({exc.__class__.__name__}: {str(exc)[:100]}) — retried next sync")
            totals["failed"] += 1
            save(STATE, state)
            continue
        saved_here, in_window = 0, 0
        # oldest first, SSE / 互动易 before 全景路演: when one briefing is listed on two platforms, the first is kept
        for ev in sorted(events, key=lambda e: (e["day"], e["platform"] == "p5w")):
            prev = state["seen"].get(ev["id"], {}).get("status", "")
            if prev and not prev.startswith("later"):
                continue                                   # handled by an earlier sync
            if ev["day"] < start and not prev.startswith("later"):
                continue                                   # older than this company's window
            totals["listed"] += 1
            in_window += 1
            kind, why = classify(ev["title"], ev["type_text"])
            if kind != "skip":
                try:
                    why = take(co, ev, kind, state)
                except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
                    why = f"later: fetch failed ({exc.__class__.__name__}: {str(exc)[:80]})"
            entry = {"company": name, "date": ev["day"].isoformat(), "platform": ev["platform"], "title": ev["title"]}
            if why is None:
                entry["status"] = f"saved:{state['labels'][-1]}"
                totals["saved"] += 1
                saved_here += 1
            elif why.startswith("later"):
                entry["status"] = why
                totals["later"] += 1
            else:
                entry["status"] = f"skip:{why}"
                totals["skipped"] += 1
                key = why.split(":")[0] if ":" in why else why.split(" as ")[0]
                reasons[key] = reasons.get(key, 0) + 1
            state["seen"][ev["id"]] = entry
            save(STATE, state)                             # after every event, so an interrupted run resumes
        state["companies"][name] = {"last_sync": datetime.now(CST).strftime("%Y-%m-%d %H:%M"), "since": start.isoformat()}
        totals["companies_done"] += 1
        print(f"{name:32s} {co['exchange']:4s} since {start}: {in_window} new event(s) in the window, {saved_here} saved")
        save(STATE, state)
    if not companies and totals["companies_done"] == len(ours):
        state["last_sync"] = today.isoformat()
    state["runs"].append({"at": datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
                          "since": since.isoformat() if since else "per company",
                          "companies": companies or "all", **totals,
                          "skip_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1]))})
    save(STATE, state)
    print(f"\n{totals['companies_done']} of {len(ours)} companies synced; {totals['listed']} new event(s) looked at: "
          f"{totals['saved']} saved, {totals['skipped']} skipped, {totals['later']} later (not over / failed); "
          f"{totals['failed']} company listing(s) failed; queue now {len(load(PENDING, []))}")
    if reasons:
        print("skipped: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))


# ---------------------------------------------------------------- queue commands

def mark_done(rows, why=None):
    state = load(STATE, new_state())
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state["seen"].setdefault(r["id"], {"company": r["company"], "date": r["date"]})["status"] = stamp
    save(STATE, state)


def status(company=None):
    """Every event seen for our companies (optionally one company) with its state."""
    state = load(STATE, new_state())
    queued = {r["id"] for r in load(PENDING, [])}
    rows = sorted(((s.get("date", ""), s.get("company", "?"), item, s) for item, s in state["seen"].items()
                   if not company or s.get("company") == company))
    for day, co, item, s in rows:
        print(f"{day}  {co:28s} {'queued' if item in queued else '      '} {str(s.get('status'))[:70]:70s} "
              f"{s.get('title', '')[:40]}")
    print(f"{len(rows)} event(s) seen; last sync {state.get('last_sync') or 'never'}")
    if not company:
        ours, _hk = universe()
        never = [c["name"] for c in ours if c["name"] not in state["companies"]]
        if never:
            print("never synced: " + ", ".join(never))


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # progress shows up line by line in a log
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: 7 days before the company's last sync, or 200 days back (first sync)")
    s.add_argument("--company", action="append", help="repeatable; default: every SZSE / SSE company")
    s.add_argument("--budget", type=float, default=BUDGET_MIN, help=f"minutes (default {BUDGET_MIN})")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--market", help="accepted for symmetry with the other collectors; every row here is CN")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a briefing yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(date.fromisoformat(args.since) if args.since else None, args.company, args.budget)
    elif args.cmd == "pending":
        meta = load(META, {})
        rows = [r for r in load(PENDING, []) if (not args.company or r["company"] == args.company)
                and (not args.market or market_of(meta.get(r["company"], {}).get("exchange")) == args.market)]
        for r in rows:
            print(f"{r['date']}  {r['company']:28s} {r['label']:80s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
        else:
            sys.exit('give --label "<label>" (one briefing) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)


if __name__ == "__main__":
    main()
