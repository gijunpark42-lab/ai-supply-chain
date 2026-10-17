"""Insider and major-holder changes for the graph's Korean, Taiwanese and Japanese companies.

The user asked on 2026-10-17 for insider trades recorded every day by the nightly routine (no model tokens).
Insider trades are NOT "signals": they never go into quarterly_data / chains / patches; they live in
market/history/insiders_kr.jsonl, insiders_tw.jsonl and insiders_jp.jsonl and are shown in their own section of
the company panel (graph/insiders/, one file per company, built by market/insiders.py from every market's insiders_*.jsonl).

Where the data comes from (all free, all official):
  Korea   OpenDART (needs DART_API_KEY)
            elestock.json   임원ㆍ주요주주 특정증권등 소유상황보고서: an executive or 10% holder reports a change in
                            their holding. The list gives only the net change, so each new report's own text
                            (document.xml, ~5 KB) is read for its detail table: one line per transaction with the
                            reason (open-market purchase / sale, stock bonus, gift, ...), the date, the price and
                            the trading-plan date (Korea's pre-announced trading plans, the closest thing to a
                            US 10b5-1 plan). A report whose text cannot be read falls back to the list's net change.
            majorstock.json 주식등의 대량보유상황보고서: a 5% holder reports (shares and % after, the change).
          Backfill = both lists for every Korean company. Daily = DART's filing list (list.json, ownership
          disclosures only) since the last run, then the two lists only for our companies that filed.
  Taiwan  TWSE OpenAPI t187ap12_L and TPEx OpenAPI mopsfin_t187ap12_O: the day's insider pre-sale declarations
          (a director / officer / 10% holder must declare a planned transfer before making it). The feeds only
          show the latest day, so Taiwan history starts on the first run and grows every day (no backfill).
  Japan   EDINET v2 (needs EDINET_API_KEY): the daily document list (documents.json?type=2), docTypeCode 350
          (大量保有報告書 / 変更報告書: a 5% holder's report and its 1-point change reports) and 360 (訂正, an
          amendment) whose issuer is one of our companies. Each report's XBRL values (type=5 CSV) give the
          holding ratio now and in the previous report, so the sign of the change sets buy / sell.
          Backfill walks every day of the last 365; daily walks the days since the last run. Every day's list is
          cached under market/cache/insiders_asia/edinet_lists/ so a re-run reads it from disk.

What a row is: one reported change (contract 2 of the market-data task) plus node_id / node_ids, like
insiders_us.py, and "line" for Korea (one report can list several transactions). type: Korea = from the
report's reason (sign of the change when the reason is unknown); Taiwan = sell for a declared sale, gift for a
gift; Japan = sign of the ratio change, and "other" for an amendment (it corrects an earlier report instead of
reporting a new change).

History keys: Korea node_id + url + line; Japan node_id + url (one filing = one row); Taiwan's rows share the feed
URL, so its key also holds the date, the insider, the shares and the transfer method.

CLI:  python -m market.insiders_asia              (daily: new filings since the last run, then rebuild)
      python -m market.insiders_asia --backfill   (Korea: every company; Japan: walk the last 365 days)
      python -m market.insiders_asia --build-only (rebuild graph/insiders/ (one file per company) from history only)
"""
import argparse
import csv
import datetime as dt
import html
import importlib.util
import io
import os
import re
import sys
import time
import unicodedata
import warnings
import xml.etree.ElementTree as ET
import zipfile

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from market.common import (ROOT, BROWSER_UA, load_env, today, get, read_json, write_json, read_history,
                           append_history, universe)

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)   # DART's report XML reads fine as HTML

WINDOW_DAYS = 365                                       # keep filings of the last year
CACHE = ROOT / "market" / "cache" / "insiders_asia"     # corp-code tables, EDINET daily lists, run state
STATE_FILE = CACHE / "state.json"
EDINET_LISTS = CACHE / "edinet_lists"                   # one file per EDINET file date
DART_CODES_FILE = CACHE / "dart_corp_codes.json"
EDINET_CODES_FILE = CACHE / "edinet_codes.json"
CODE_TABLE_MAX_AGE = 30                                 # days before a corp-code table is downloaded again
SAVE_EVERY = 100                                        # append to history every N documents (resumable backfill)

KEY_KR = ("node_id", "url", "line")                     # one report can list several transactions
KEY_JP = ("node_id", "url")                             # one filing = one row
KEY_TW = ("node_id", "url", "date", "insider", "shares", "code")

DART_API = "https://opendart.fss.or.kr/api"
DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O"
EDINET_API = "https://api.edinet-fsa.go.jp/api/v2"
EDINET_CODE_LIST = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
EDINET_VIEWER = "https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?{},,2"   # the public page of one document
JST = dt.timezone(dt.timedelta(hours=9))                # EDINET's file dates are Japan time

# (graph/insiders_index.json's "sources" list is made by market/insiders.py from each row's source name + URL.)

# Taiwanese companies that the graph lists by their US ADR ticker: their Taiwan stock code.
TW_LOCAL_CODES = {"TSMC": "2330", "UMC": "2303", "ASE Group": "3711", "ChipMOS": "8150"}

PAUSE = {"dart": 0.5, "edinet": 1.0}                    # seconds between two requests to the same source
_last_call = {"dart": 0.0, "edinet": 0.0}


def log(msg):
    """Progress and warnings go to stderr so the nightly log shows them."""
    print(f"[insiders_asia] {msg}", file=sys.stderr, flush=True)


def polite(source):
    """Wait so that two requests to one source are at least PAUSE[source] seconds apart."""
    wait = PAUSE[source] - (time.time() - _last_call[source])
    if wait > 0:
        time.sleep(wait)
    _last_call[source] = time.time()


def scrub(text):
    """Remove API keys from an error message (a requests error repeats the whole URL, key included)."""
    for name in ("DART_API_KEY", "EDINET_API_KEY"):
        key = (os.getenv(name) or "").strip()
        if key:
            text = text.replace(key, "***")
    return text


def to_number(text):
    """'36,407,157' -> 36407157, '-1.52' -> -1.52, '-' / '' / '－' -> None."""
    if text is None:
        return None
    s = unicodedata.normalize("NFKC", str(text)).replace(",", "").strip()
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    number = float(s)
    return int(number) if number.is_integer() and "." not in s else number


def cutoff_day():
    """The oldest filing date we keep (365 days before today, Pacific)."""
    return (dt.date.fromisoformat(today()) - dt.timedelta(days=WINDOW_DAYS)).isoformat()


def save_state(key, value):
    """Update one key of the run state. The file is re-read first, so two markets run in two processes at once
    (a long backfill) do not overwrite each other's keys."""
    state = read_json(STATE_FILE, {}) or {}
    state[key] = value
    write_json(STATE_FILE, state)


def make_row(*, node_ids, date, filed, insider, role, code, type_, shares, owned_after, currency, market,
             source, url, price=None, value=None, plan=None):
    """One history row: the contract-2 fields + node_id / node_ids (which graph node the row belongs to)."""
    return {
        "node_id": node_ids[0], "node_ids": node_ids,
        "date": date, "filed": filed, "insider": insider, "role": role, "code": code, "type": type_,
        "shares": shares, "price": price, "value": value, "currency": currency, "owned_after": owned_after,
        "plan_10b5_1": plan, "market": market, "source": source, "url": url,
    }


def companies(country, code_of):
    """{local code: [node ids]} for one country. code_of(node_id, info) returns the local code or None.
    Two nodes can share one listing (a subsidiary shown beside its parent): both get the rows."""
    out = {}
    for node_id, info in universe().items():
        if info.get("country") != country or info.get("status") not in (None, "public"):
            continue
        code = code_of(node_id, info)
        if code:
            out.setdefault(code, []).append(node_id)
    return out


def by_sign(change):
    return "buy" if (change or 0) > 0 else "sell" if (change or 0) < 0 else "other"


# ================================================================ Korea (OpenDART)

# Korean executive titles -> English. The longest word found inside the title wins (부사장 contains 사장,
# 부회장 contains 회장, 사외이사 contains 이사), so the list is sorted longest first.
KR_TITLES = sorted([
    ("대표이사", "CEO"), ("부회장", "Vice Chairman"), ("회장", "Chairman"), ("사장", "President"),
    ("부사장", "Executive Vice President"), ("전무", "Senior Vice President"), ("상무", "Vice President"),
    ("사외이사", "Outside Director"), ("기타비상무이사", "Non-executive Director"), ("감사위원", "Audit Committee"),
    ("감사", "Auditor"), ("이사", "Director"), ("고문", "Advisor"), ("펠로우", "Fellow"), ("CFO", "CFO"),
    ("CEO", "CEO"), ("CTO", "CTO"), ("COO", "COO"), ("본부장", "Division Head"), ("센터장", "Center Head"),
    ("실장", "Office Head"), ("부문장", "Division Head"), ("담당", "Head of unit"), ("연구위원", "Research Fellow"),
    ("상근", "Standing officer"), ("임원", "Executive"),
], key=lambda pair: -len(pair[0]))

# The reason of one transaction in a report (보고사유) -> (English code, type). The first word found wins;
# None as the type = decide by the sign of the change.
KR_REASONS = [
    ("장내매수", "Open-market purchase", "buy"), ("장내매도", "Open-market sale", "sell"),
    ("장외매수", "Off-market purchase", "buy"), ("장외매도", "Off-market sale", "sell"),
    ("시간외", "After-hours block trade", None), ("블록", "Block trade", None),
    ("자사주상여", "Stock bonus (treasury shares)", "grant"), ("상여", "Stock bonus", "grant"),
    ("주식기준보상", "Stock-based compensation", "grant"), ("양도제한", "Restricted stock", "grant"),
    ("성과", "Performance stock", "grant"), ("RSU", "Restricted stock units", "grant"),
    ("PSU", "Performance stock units", "grant"), ("우리사주", "Employee stock ownership plan", "other"),
    ("주식매수선택권", "Stock option exercise", "option_exercise"), ("스톡옵션", "Stock option exercise", "option_exercise"),
    ("수증", "Gift received", "gift"), ("증여", "Gift", "gift"), ("상속", "Inheritance", "other"),
    ("신규선임", "Newly appointed (holding at appointment)", "other"), ("신규", "Initial report", "other"),
    ("퇴임", "Left office", "other"), ("유상", "Rights offering subscription", "buy"),
    ("무상", "Bonus issue", "other"), ("전환", "Conversion", "other"), ("합병", "Merger", "other"),
    ("분할", "Split", "other"), ("대여", "Stock lending", "other"), ("차입", "Stock borrowing", "other"),
    ("상환", "Stock loan returned", "other"), ("담보", "Pledge", "other"), ("공개매수", "Tender offer", None),
    ("교환", "Exchange (exchangeable bonds)", "other"), ("병합", "Reverse split", "other"),
    ("자본감소", "Capital reduction", "other"), ("감자", "Capital reduction", "other"),
    ("주식배당", "Stock dividend", "other"), ("계약", "Contract ended", "other"),
    ("기타", "Other change", "other"), ("매수", "Purchase", "buy"), ("취득", "Acquisition", "buy"), ("매도", "Sale", "sell"), ("처분", "Disposal", "sell"),
]
# The kind of security (특정증권등의 종류): ordinary shares need no note.
KR_SECURITIES = [("보통주", ""), ("우선주", "preferred shares"), ("종류주", "preferred shares"),
                 ("전환사채", "convertible bonds"), ("교환사채", "exchangeable bonds"), ("신주인수권", "warrants"),
                 ("주식매수선택권", "stock options")]

KR_HOLDER_NAMES = {"국민연금공단": "National Pension Service"}    # holders that are not companies on DART

# Revised Romanization of Korean, used for people's names when the report gives no English spelling.
_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_VOWELS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
           "yu", "eu", "ui", "i"]
_FINALS = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t",
           "ng", "t", "t", "k", "t", "p", "t"]
# Family names have their own customary spellings (Kim, not Gim).
_SURNAMES = {
    "김": "Kim", "이": "Lee", "박": "Park", "최": "Choi", "정": "Jung", "강": "Kang", "조": "Cho", "윤": "Yoon",
    "장": "Jang", "임": "Lim", "한": "Han", "오": "Oh", "서": "Seo", "신": "Shin", "권": "Kwon", "황": "Hwang",
    "안": "Ahn", "송": "Song", "류": "Ryu", "유": "Yoo", "홍": "Hong", "전": "Jeon", "고": "Ko", "문": "Moon",
    "양": "Yang", "손": "Son", "배": "Bae", "백": "Baek", "허": "Heo", "노": "Noh", "남": "Nam", "심": "Shim",
    "하": "Ha", "곽": "Kwak", "성": "Sung", "차": "Cha", "주": "Joo", "우": "Woo", "구": "Koo", "민": "Min",
    "진": "Jin", "나": "Na", "지": "Ji", "엄": "Eom", "채": "Chae", "원": "Won", "천": "Cheon", "방": "Bang",
    "공": "Kong", "현": "Hyun", "함": "Ham", "변": "Byun", "염": "Yeom", "여": "Yeo", "추": "Choo", "도": "Do",
    "소": "So", "석": "Seok", "선": "Sun", "설": "Seol", "마": "Ma", "길": "Gil", "연": "Yeon", "표": "Pyo",
    "명": "Myung", "기": "Ki", "반": "Ban", "왕": "Wang", "금": "Keum", "옥": "Ok", "육": "Yook", "인": "In",
    "맹": "Maeng", "제": "Je", "모": "Mo", "탁": "Tak", "국": "Kook", "어": "Eo", "은": "Eun", "용": "Yong",
}


def romanize_syllable(ch):
    """One Hangul syllable -> Latin letters (a Hangul syllable = initial consonant + vowel + optional final)."""
    code = ord(ch) - 0xAC00
    return _INITIALS[code // 588] + _VOWELS[(code % 588) // 28] + _FINALS[code % 28]


def romanize_name(name):
    """'곽노정' -> 'Kwak No-jeong'. Only for 2-4 Hangul syllables (a person's name); anything else is returned
    unchanged."""
    name = (name or "").replace(" ", "")
    if not re.fullmatch(r"[가-힣]{2,4}", name):
        return name
    family = _SURNAMES.get(name[0]) or romanize_syllable(name[0]).capitalize()
    given = "-".join(romanize_syllable(ch) for ch in name[1:])
    return f"{family} {given.capitalize()}"


def kr_name_key(name):
    """'(주)SK스퀘어' / 'SK스퀘어 주식회사' -> 'SK스퀘어' (the form DART's corp list uses)."""
    return re.sub(r"\(주\)|㈜|주식회사|\s+", "", name or "")


def kr_english_name(name, english):
    """A DART reporter name in English: a company's official English name, a known institution, a romanized
    person's name, or the name as filed (already Latin, e.g. 'BlackRockFundAdvisors')."""
    name = (name or "").strip()
    key = kr_name_key(name)
    if key in KR_HOLDER_NAMES:
        return KR_HOLDER_NAMES[key]
    if key in english:
        return html.unescape(english[key])
    return romanize_name(name)


def kr_report_name(name_ko, name_latin, fallback):
    """The reporter's name from the report itself: its 한자(영문) cell holds Chinese characters and/or an English
    spelling, e.g. '黃祥俊 (HWANG SANGJOON)', '黃喆周(Hwang Chul Joo)', 'Lumiastra Co.,Ltd.' or only '孫潤翼'.
    The English spelling is used when there is one, else `fallback`."""
    latin = name_latin or ""
    inside = re.search(r"\(([^()]*[A-Za-z][^()]*)\)", latin)
    if inside:
        text = inside.group(1)
    elif re.search(r"[A-Za-z]", latin) and not re.search(r"[぀-ヿ一-鿿가-힣]", latin):
        text = latin
    else:
        return fallback
    person = re.fullmatch(r"[가-힣]{2,4}", (name_ko or "").replace(" ", ""))
    if person:                                           # 'Woo, JunMyung' / 'HWANG SANGJOON' -> 'Hwang Sangjoon'
        text = text.replace(",", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text.isupper():
            text = text.title()
    return re.sub(r"\s+", " ", text).strip() or fallback


def kr_role(registered, title, major):
    """elestock's three role fields -> one English role, e.g. 'Vice President (non-registered officer)'."""
    parts = []
    title = (title or "").strip()
    if title and title != "-":
        english = next((en for ko, en in KR_TITLES if ko in title), "Executive")
        reg = {"등기임원": "registered officer", "비등기임원": "non-registered officer"}.get((registered or "").strip())
        parts.append(f"{english} ({reg})" if reg else english)
    if (major or "").strip() == "주요주주":
        parts.append("Major shareholder (10%+)")
    return "; ".join(parts) or "Insider"


def kr_date(text):
    """'2026년 01월 01일' / '2026.01.26' / '2026-01-26' -> '2026-01-26' (None when it is not a date)."""
    m = re.fullmatch(r"\s*(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?\s*", text or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


# One kept-alive connection for every DART call: no new TLS handshake per request (3x faster, and lighter for
# DART's servers than a fresh connection each time).
_dart_session = requests.Session()
_dart_session.headers.update({"User-Agent": BROWSER_UA})


def dart_request(endpoint, params, tries=3):
    """GET one OpenDART endpoint with the key (paced, retried on network errors / 5xx). Returns the response."""
    last = RuntimeError("no answer")
    for attempt in range(tries):
        polite("dart")
        try:
            r = _dart_session.get(f"{DART_API}/{endpoint}", params={"crtfc_key": os.getenv("DART_API_KEY"), **params},
                                  timeout=90)
        except requests.RequestException as e:
            last = RuntimeError(scrub(f"{e.__class__.__name__}: {e}")[:160])
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = RuntimeError(f"DART {endpoint}: HTTP {r.status_code}")
            time.sleep(5 * (attempt + 1))
            continue
        return r
    raise last


def dart_get(endpoint, **params):
    """One OpenDART JSON call -> (the whole answer, its 'list' rows). [] when DART has nothing; raises on error."""
    r = dart_request(endpoint, params)
    if r.status_code != 200:
        raise RuntimeError(f"DART {endpoint}: HTTP {r.status_code}")
    data = r.json()
    status = data.get("status")
    if status == "013":                                  # 조회된 데이타가 없습니다 = nothing filed
        return data, []
    if status != "000":
        raise RuntimeError(f"DART {endpoint}: status {status} {data.get('message')}")
    return data, data.get("list") or []


KR_FOOTNOTE = re.compile(r"\(\s*주\s*\d+\s*\)|(?<![가-힣])주\s*\d+\s*\)|\*\s*\d+\)?")
KR_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def kr_price(cell, security):
    """The unit price (단가) of one transaction line, from its table cell.
    The cell can hold more than one number, and joining every digit gave prices like 149,000,149,000
    (user, 2026-10-17 verification), so it is read token by token:
      '149,000(149,000)'                     -> 149000 (the first number)
      '295,500(주1)'                         -> 295500 (footnote mark '(주1)' removed first)
      '보통주 193,914 (원) 우선주 188,305(원)' -> the number after the label of the line's own security
                                                (cells[2]: 보통주 = common, 우선주 / 종류주 = preferred)
      '-' / ''                               -> None"""
    text = unicodedata.normalize("NFKC", cell or "")
    text = KR_FOOTNOTE.sub(" ", text)
    labelled = re.findall(r"(보통주|우선주|종류주)[^\d]{0,8}?(\d[\d,]*(?:\.\d+)?)", text)
    if labelled:
        own = next((k for k in ("우선주", "종류주", "보통주") if k in (security or "")), None)
        prices = {label: num for label, num in reversed(labelled)}     # the first number per label
        if own in prices:
            return to_number(prices[own])
        if own is None and len(set(prices.values())) == 1:            # one price for every class
            return to_number(labelled[0][1])
        return None                                                    # a price for another class only
    m = KR_NUMBER.search(text)
    return to_number(m.group(0)) if m else None


def dart_report(rcept_no):
    """One elestock report's own text -> (Korean name, 한자(영문) name, [transaction lines]).
    A line = {reason, date, security, change, after, price, plan_date}. Raises when DART sends no document."""
    r = dart_request("document.xml", {"rcept_no": rcept_no})
    if r.status_code != 200 or not r.content.startswith(b"PK"):   # a ZIP starts with PK; an error is XML/JSON
        raise RuntimeError(f"DART document {rcept_no}: HTTP {r.status_code}, no ZIP")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        text = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    name_ko = name_latin = None
    lines = []
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th", "te", "tu"])]
        if "한자(영문)" in cells:                           # the name row: ... | 한 글 | 손윤익 | 한자(영문) | 孫潤翼
            i = cells.index("한자(영문)")
            name_latin = cells[i + 1] if i + 1 < len(cells) else None
            for j, cell in enumerate(cells[:-1]):
                if cell.replace(" ", "") == "한글":
                    name_ko = cells[j + 1]
        elif (len(cells) >= 7 and kr_date(cells[1]) and to_number(cells[4]) is not None
              and not cells[0].replace(" ", "").startswith("합계")):
            # 보고사유 | 변동일 | 종류 | 변동전 | 증감 | 변동후 | 단가 | 비고 | (거래계획보고일자)
            lines.append({
                "reason": cells[0], "date": kr_date(cells[1]), "security": cells[2],
                "change": to_number(cells[4]), "after": to_number(cells[5]),
                "price": kr_price(cells[6], cells[2]), "price_text": cells[6],
                "plan_date": kr_date(cells[8]) if len(cells) >= 9 else None,
            })
    return name_ko, name_latin, lines


def kr_line_row(x, line, n, node_ids, insider, role, url):
    """One transaction line of an elestock report -> a history row."""
    code, kind = next(((en, t) for ko, en, t in KR_REASONS if ko in line["reason"]), ("Reported change", None))
    note = next((en for ko, en in KR_SECURITIES if ko in line["security"]), "other securities")
    if note:
        code += f" ({note})"
    shares = abs(line["change"]) if line["change"] else None
    price = line["price"] or None
    return make_row(
        node_ids=node_ids, date=line["date"], filed=x["rcept_dt"], insider=insider, role=role, code=code,
        type_=kind or by_sign(line["change"]), shares=shares, price=price,
        value=round(shares * price) if shares and price else None, owned_after=line["after"],
        plan=bool(line["plan_date"]), currency="KRW", market="KR", source="DART",
        url=url) | {"line": str(n), "price_text": line.get("price_text")}


def kr_elestock_rows(x, node_ids, english):
    """One elestock list entry -> its history rows (one per transaction line of the report)."""
    url = DART_VIEWER.format(x["rcept_no"])
    role = kr_role(x.get("isu_exctv_rgist_at"), x.get("isu_exctv_ofcps"), x.get("isu_main_shrholdr"))
    fallback = kr_english_name(x.get("repror"), english)
    name_ko, name_latin, lines = dart_report(x["rcept_no"])
    insider = kr_report_name(name_ko, name_latin, fallback)
    if lines:
        return [kr_line_row(x, line, n, node_ids, insider, role, url) for n, line in enumerate(lines, 1)]
    # The text had no readable detail table: record the list's net change instead.
    change = to_number(x.get("sp_stock_lmp_irds_cnt"))
    return [make_row(
        node_ids=node_ids, date=x["rcept_dt"], filed=x["rcept_dt"], insider=insider, role=role,
        code="Reported change", type_=by_sign(change), shares=abs(change) if change else None,
        owned_after=to_number(x.get("sp_stock_lmp_cnt")), currency="KRW", market="KR", source="DART",
        url=url) | {"line": "net"}]


def kr_major_row(x, node_ids, english):
    """One majorstock entry (5% holder report) -> a history row (the list already has every number)."""
    change = to_number(x.get("stkqy_irds"))
    ratio, ratio_change = to_number(x.get("stkrt")), to_number(x.get("stkrt_irds"))
    role = "5% holder"
    if ratio is not None:
        role += f", {ratio:.2f}%" + (f" ({ratio_change:+.2f} pts)" if ratio_change is not None else "")
    return make_row(
        node_ids=node_ids, date=x["rcept_dt"], filed=x["rcept_dt"],
        insider=kr_english_name(x.get("repror"), english), role=role, code="5% holder report",
        type_=by_sign(change), shares=abs(change) if change else None, owned_after=to_number(x.get("stkqy")),
        currency="KRW", market="KR", source="DART", url=DART_VIEWER.format(x["rcept_no"])) | {"line": "1"}


def dart_codes():
    """{'by_stock': {stock code: corp_code}, 'english': {corp name: English name}} from DART's corpCode.xml,
    cached for CODE_TABLE_MAX_AGE days. If the download fails, the old cache or the repo's dart/corp_codes.json
    (stock codes only) is used."""
    cached = read_json(DART_CODES_FILE, None)
    oldest = (dt.date.today() - dt.timedelta(days=CODE_TABLE_MAX_AGE)).isoformat()
    if cached and cached.get("downloaded", "") >= oldest:
        return cached
    try:
        r = dart_request("corpCode.xml", {})
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            root = ET.fromstring(z.read(z.namelist()[0]))
        table = {"downloaded": dt.date.today().isoformat(), "source": f"{DART_API}/corpCode.xml",
                 "by_stock": {}, "english": {}}
        for item in root.iter("list"):
            stock = (item.findtext("stock_code") or "").strip()
            name, english = (item.findtext("corp_name") or "").strip(), (item.findtext("corp_eng_name") or "").strip()
            if stock:
                table["by_stock"][stock] = (item.findtext("corp_code") or "").strip()
            if english:
                table["english"].setdefault(kr_name_key(name), html.unescape(english))
        write_json(DART_CODES_FILE, table)
        return table
    except Exception as e:
        log(f"WARNING: DART corp-code download failed ({scrub(str(e))[:120]}); using an older table")
        if cached:
            return cached
        repo_table = read_json(ROOT / "dart" / "corp_codes.json", {}) or {}
        return {"by_stock": {s: v["corp_code"] for s, v in repo_table.items()}, "english": {}}


def kr_stock_code(node_id, info):
    """'000660.KS' / '356860' -> '000660'; anything that is not a 6-digit KRX code -> None."""
    code = str(info.get("ticker") or "").split(".")[0].strip()
    if info.get("exchange") not in ("KRX", "KOSPI", "KOSDAQ", "KONEX") or not code.isdigit():
        return None
    return code.zfill(6)


def kr_filers_since(day, ours):
    """corp_codes of our companies that filed an ownership report (DART list, type D) since `day`."""
    found = set()
    page = 1
    while True:
        data, rows = dart_get("list.json", bgn_de=day.replace("-", ""), end_de=today().replace("-", ""),
                              pblntf_ty="D", page_count=100, page_no=page)
        for x in rows:
            if x.get("corp_code") in ours and re.search(r"소유상황보고서|대량보유상황보고서", x.get("report_nm", "")):
                found.add(x["corp_code"])
        if page >= int(data.get("total_page") or 1):
            return found
        page += 1


def run_kr(backfill, state):
    """Korea: returns the number of new rows. Raises if DART cannot be used at all."""
    if not os.getenv("DART_API_KEY"):
        raise RuntimeError("DART_API_KEY missing in .env")
    codes = dart_codes()
    by_corp = {}                                         # corp_code -> [node ids]
    for stock, node_ids in companies("KR", kr_stock_code).items():
        corp = codes["by_stock"].get(stock)
        if corp:
            by_corp[corp] = node_ids
        else:
            log(f"WARNING: no DART corp_code for {stock} ({', '.join(node_ids)})")
    since = cutoff_day()
    last = state.get("kr_last")
    if backfill or not last:
        todo = list(by_corp)
    else:                                                # re-read 3 days before the last run (late filings)
        start = (dt.date.fromisoformat(last) - dt.timedelta(days=3)).isoformat()
        todo = sorted(kr_filers_since(start, by_corp))
    log(f"KR: {len(todo)} of {len(by_corp)} companies to read")

    # 1) the two lists of each company: 5% holder rows are complete; elestock entries need their report text
    recorded = {r["url"] for r in read_history("insiders_kr")}
    major_rows, reports, failures = [], [], 0
    for corp in todo:
        try:
            _, ele = dart_get("elestock.json", corp_code=corp)
            _, major = dart_get("majorstock.json", corp_code=corp)
        except Exception as e:
            failures += 1
            log(f"WARNING: DART failed for {by_corp[corp][0]} ({scrub(str(e))[:120]})")
            continue
        for x in major:
            if x.get("rcept_dt", "") >= since and DART_VIEWER.format(x["rcept_no"]) not in recorded:
                major_rows.append(kr_major_row(x, by_corp[corp], codes["english"]))
        for x in ele:
            if x.get("rcept_dt", "") >= since and DART_VIEWER.format(x["rcept_no"]) not in recorded:
                reports.append((x, by_corp[corp]))
    if todo and failures == len(todo):
        raise RuntimeError("every DART request failed")
    added = append_history("insiders_kr", major_rows, KEY_KR)

    # 2) the elestock reports, newest first, saved every SAVE_EVERY reports (an interrupted backfill resumes)
    reports.sort(key=lambda item: item[0]["rcept_no"], reverse=True)
    log(f"KR: {len(major_rows)} new 5% holder reports; {len(reports)} new executive reports to read")
    rows, missed = [], 0
    for i, (x, node_ids) in enumerate(reports, 1):
        try:
            rows += kr_elestock_rows(x, node_ids, codes["english"])
        except Exception as e:
            missed += 1
            log(f"WARNING: DART report {x['rcept_no']} failed ({scrub(str(e))[:120]}); retried next run")
        if i % SAVE_EVERY == 0 or i == len(reports):
            added += append_history("insiders_kr", rows, KEY_KR)
            rows = []
            log(f"KR: read {i}/{len(reports)} executive reports ({missed} failed)")
    save_state("kr_last", today())
    return added


def recheck_kr_prices(ratio=2.5):
    """One-off repair (user, 2026-10-17 verification): the old price parser joined every digit of the unit-price
    cell ('149,000(149,000)' -> 149,000,149,000; '295,500(주1)' -> 2,955,001). Those rows stay in the ADD-only
    history, so this re-reads every report with a line priced more than `ratio` x the company's median price of
    other reports within 45 days (joined digits only ever make a price LARGER), parses it again with kr_price()
    and records the differences in market/history/corrections.jsonl, which market/insiders.py applies.
    Returns the number of corrections added."""
    import statistics
    from market import corrections
    load_env()
    if not os.getenv("DART_API_KEY"):
        raise RuntimeError("DART_API_KEY missing in .env")
    rows = corrections.apply("insiders_kr", read_history("insiders_kr"))
    priced = [r for r in rows if r.get("price") and r.get("date") and r.get("url")]
    by_node = {}
    for r in priced:
        by_node.setdefault(r["node_id"], []).append(r)
    suspicious = set()
    for node_rows in by_node.values():
        for r in node_rows:
            day = dt.date.fromisoformat(r["date"])
            near = [x["price"] for x in node_rows if x["url"] != r["url"]
                    and abs((dt.date.fromisoformat(x["date"]) - day).days) <= 45]
            others = near if len(near) >= 2 else [x["price"] for x in node_rows if x["url"] != r["url"]]
            if len(others) >= 2 and r["price"] > ratio * statistics.median(others):
                suspicious.add(r["url"])
    log(f"KR price recheck: {len(suspicious)} reports to read again")
    by_key = {(r["url"], r.get("line")): r for r in rows}
    fixes = []
    for url in sorted(suspicious):
        rcept_no = url.split("rcpNo=")[-1]
        try:
            _, _, lines = dart_report(rcept_no)
        except Exception as e:
            log(f"WARNING: DART report {rcept_no} failed ({scrub(str(e))[:120]}); not rechecked")
            continue
        for n, line in enumerate(lines, 1):
            old = by_key.get((url, str(n)))
            if not old or old.get("price") == line["price"]:
                continue
            shares = old.get("shares")
            value = round(shares * line["price"]) if shares and line["price"] else None
            fixes.append(corrections.correction(
                "insiders_kr", {"url": url, "line": str(n)},
                {"price": line["price"], "value": value, "price_text": line["price_text"]},
                reason=f"unit-price cell '{line['price_text']}' was read as {old.get('price')} by the old parser "
                       f"(every digit joined); re-read token by token",
                source="DART", url=url))
            log(f"KR price fix: {old.get('node_id')} {old.get('date')} {rcept_no} line {n}: "
                f"{old.get('price')} -> {line['price']} (cell '{line['price_text']}')")
    added = corrections.add(fixes)
    log(f"KR price recheck: {added} new corrections")
    return added


# ================================================================ Taiwan (TWSE / TPEx OpenAPI)

# Who declared (申報人身分) -> English. The base role is the first word found; the relation is added around it.
TW_BASES = [("法人董事代表人", "representative of a corporate director"), ("法人董事", "corporate director"),
            ("獨立董事", "independent director"), ("董事長", "chairman"), ("董事", "director"),
            ("監察人", "supervisor"), ("經理人", "officer"), ("大股東", "major shareholder (10%+)")]
TW_RELATIONS = [("配偶", "Spouse of {}"), ("未成年子女", "Minor child of {}"), ("利用他人名義", "Nominee holder for {}")]

# How the shares will be transferred (預定轉讓方式) -> (code, type).
TW_METHODS = [("贈與", ("Planned gift", "gift")), ("信託", ("Planned transfer into trust", "other")),
              ("鉅額", ("Planned block trade sale", "sell")), ("盤後定價", ("Planned after-hours sale", "sell")),
              ("特定人", ("Planned private sale", "sell")), ("一般交易", ("Planned open-market sale", "sell"))]


def tw_role(text):
    text = (text or "").strip()
    base = next((en for zh, en in TW_BASES if zh in text), "insider")
    for zh, pattern in TW_RELATIONS:
        if zh in text:
            return pattern.format(base)
    return base[0].upper() + base[1:]


def roc_to_iso(text):
    """'1151016' (Taiwan's ROC calendar: year 115 = 2026) -> '2026-10-16'."""
    m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", (text or "").strip())
    return f"{int(m.group(1)) + 1911}-{m.group(2)}-{m.group(3)}" if m else None


def tw_code(node_id, info):
    """'2330.TW' / '3264.TWO' / '6669' -> the Taiwan stock code; ADR-listed names via TW_LOCAL_CODES."""
    if node_id in TW_LOCAL_CODES:
        return TW_LOCAL_CODES[node_id]
    if info.get("exchange") not in ("TWSE", "TPEx"):
        return None
    m = re.fullmatch(r"(\d{4,6})(\.TWO?)?", str(info.get("ticker") or "").strip().upper())
    return m.group(1) if m else None


def tw_rows(url, source, ours):
    """The day's pre-sale declarations from one feed, for our companies."""
    r = get(url, headers={"Accept": "application/json"}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"{source}: HTTP {r.status_code}")
    rows = []
    for x in r.json():
        code = (x.get("公司代號") or x.get("SecuritiesCompanyCode") or "").strip()
        if code not in ours:
            continue
        day = roc_to_iso(x.get("出表日期") or x.get("Date"))
        method = (x.get("預定轉讓方式及股數-轉讓方式") or "").strip()
        label, kind = next((v for zh, v in TW_METHODS if zh in method), ("Planned transfer", "sell"))
        planned = [to_number(x.get("預定轉讓總股數-自有持股")), to_number(x.get("預定轉讓總股數-保留運用決定權信託股數"))]
        after = [to_number(x.get("預定轉讓後持股-自有持股")), to_number(x.get("預定轉讓後持股-保留運用決定權信託股數"))]
        name = (x.get("姓名") or "").strip()
        if name.endswith("之配偶"):                         # '<name>之配偶' = the spouse of <name>
            name = f"Spouse of {name[:-3]}"
        rows.append(make_row(
            node_ids=ours[code], date=day, filed=day, insider=name,
            role=tw_role(x.get("申報人身分") or x.get("申請人身分")), code=label, type_=kind,
            shares=sum(n for n in planned if n) or None,
            owned_after=sum(n for n in after if n) if any(n is not None for n in after) else None,
            currency="TWD", market="TW", source=source, url=url))
    return rows


def run_tw(backfill, state):
    """Taiwan: returns the number of new rows. Raises if both feeds failed."""
    ours = companies("TW", tw_code)
    rows, failures = [], 0
    for url, source in ((TWSE_URL, "TWSE"), (TPEX_URL, "TPEx")):
        try:
            rows += tw_rows(url, source, ours)
        except Exception as e:
            failures += 1
            log(f"WARNING: {source} pre-sale feed failed ({str(e)[:120]})")
    if failures == 2:
        raise RuntimeError("both Taiwan feeds failed")
    if backfill:
        log("TW: the feeds only show the latest day, so there is nothing older to backfill")
    save_state("tw_last", today())
    return append_history("insiders_tw", rows, KEY_TW)


# ================================================================ Japan (EDINET)

def edinet_get(path, params, tries=3):
    """One EDINET API call -> the response. EDINET answers HTTP 200 with a JSON error body, so check both."""
    last = RuntimeError("no answer")
    for attempt in range(tries):
        polite("edinet")
        try:
            r = get(f"{EDINET_API}/{path}", params={**params, "Subscription-Key": os.getenv("EDINET_API_KEY")},
                    timeout=180, retries=1)
        except Exception as e:
            last = RuntimeError(scrub(f"{e.__class__.__name__}: {e}")[:160])
            time.sleep(5 * (attempt + 1))
            continue
        if "json" in r.headers.get("Content-Type", ""):
            data = r.json()
            status = str(data.get("StatusCode") or (data.get("metadata") or {}).get("status") or r.status_code)
            if status == "200":
                return r
            last = RuntimeError(f"EDINET status {status}")
            if status == "401":
                raise last                               # a wrong key: asking again will not help
            if status == "429" or status.startswith("5"):
                time.sleep(60 if status == "429" else 10 * (attempt + 1))
                continue
            raise last
        if r.status_code == 200:
            return r                                     # a ZIP
        last = RuntimeError(f"EDINET HTTP {r.status_code}")
        time.sleep(5 * (attempt + 1))
    raise last


def edinet_codes():
    """{'sec': {5-char securities code: EDINET code}, 'english': {EDINET code: English name}} from EDINET's
    code list (no key needed), cached for CODE_TABLE_MAX_AGE days."""
    cached = read_json(EDINET_CODES_FILE, None)
    oldest = (dt.date.today() - dt.timedelta(days=CODE_TABLE_MAX_AGE)).isoformat()
    if cached and cached.get("downloaded", "") >= oldest:
        return cached
    try:
        r = get(EDINET_CODE_LIST, timeout=120)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            raw = z.read(z.namelist()[0]).decode("cp932", errors="replace")
        lines = list(csv.reader(raw.splitlines()))
        header = [unicodedata.normalize("NFKC", h).strip() for h in lines[1]]   # line 1 = date, line 2 = columns
        col = {h: i for i, h in enumerate(header)}
        table = {"downloaded": dt.date.today().isoformat(), "source": EDINET_CODE_LIST, "sec": {}, "english": {}}
        for row in lines[2:]:
            if len(row) < len(header):
                continue
            code = row[col["EDINETコード"]].strip()
            if row[col["証券コード"]].strip():
                table["sec"][row[col["証券コード"]].strip()] = code
            if row[col["提出者名(英字)"]].strip():
                table["english"][code] = row[col["提出者名(英字)"]].strip()
        write_json(EDINET_CODES_FILE, table)
        return table
    except Exception as e:
        if cached:
            log(f"WARNING: EDINET code list download failed ({str(e)[:120]}); using the cached copy")
            return cached
        raise


def jp_sec_code(node_id, info):
    """'8035.T' / '6857' / '268A.T' -> '80350' (EDINET's 5-character securities code = TSE code + '0')."""
    if info.get("exchange") not in ("TSE", "JPX"):
        return None
    m = re.fullmatch(r"(\d[0-9A-Z]{3})(\.T)?", str(info.get("ticker") or "").strip().upper())
    return m.group(1) + "0" if m else None


LIST_FIELDS = ("docID", "edinetCode", "filerName", "docTypeCode", "submitDateTime", "docDescription",
               "issuerEdinetCode", "parentDocID", "withdrawalStatus", "csvFlag")


def edinet_list(day, jst_today):
    """The large-holding rows (350 / 360) of EDINET's list for one file date, from the cache when that day was
    already listed after it ended (a day's list is complete once the day is over in Japan)."""
    path = EDINET_LISTS / f"{day}.json"
    cached = read_json(path, None)
    if cached and cached.get("at", "") > day:
        return cached["rows"]
    data = edinet_get("documents.json", {"date": day, "type": 2}).json()
    rows = [{k: x.get(k) for k in LIST_FIELDS} for x in data.get("results") or []
            if x.get("docTypeCode") in ("350", "360")]
    write_json(path, {"at": jst_today, "rows": rows})
    return rows


def csv_values(zip_bytes):
    """The XBRL values of a type=5 ZIP as {element name: {context: value}} (the CSV is UTF-16, tab separated)."""
    values = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            text = z.read(name).decode("utf-16")
            for row in list(csv.reader(io.StringIO(text), delimiter="\t"))[1:]:
                if len(row) >= 9:
                    values.setdefault(row[0].split(":")[-1], {}).setdefault(row[2], row[8])
    return values


def pick(values, element):
    """The filing's total for an element: the plain 'FilingDateInstant' context (filer + joint holders) when
    present, else the first holder's value (a report with one holder has only that)."""
    contexts = values.get(element) or {}
    if "FilingDateInstant" in contexts:
        return contexts["FilingDateInstant"]
    holder1 = [v for c, v in contexts.items() if c.endswith("Holder1Member")]
    return holder1[0] if holder1 else next(iter(contexts.values()), None)


def jp_row(doc, node_ids, english):
    """One large-holding report -> a history row (the XBRL values give the ratios; no CSV = only the list data)."""
    filed = (doc.get("submitDateTime") or "")[:10]
    desc = doc.get("docDescription") or ""
    amended = doc.get("docTypeCode") == "360"
    if amended:
        code = "Amended large holding report"
    elif desc.startswith("大量保有報告書"):
        code = "Large holding report (new 5% holder)"
    elif "短期大量譲渡" in desc:
        code = "Change report (short-term large transfer)"
    else:
        code = "Change report"
    filer = unicodedata.normalize("NFKC", doc.get("filerName") or "").strip()   # full-width letters -> plain
    insider = english.get(doc.get("edinetCode")) or filer
    date, ratio, before, held, joint = filed, None, None, None, 1
    values = None
    if doc.get("csvFlag") == "1":
        try:
            values = csv_values(edinet_get(f"documents/{doc['docID']}", {"type": 5}).content)
        except RuntimeError as e:
            if not re.search(r"status 40[04]", str(e)):   # 400 / 404 = EDINET has no CSV: keep the list data
                raise                                      # anything else: retried on the next run
    if values:
        date = pick(values, "DateWhenFilingRequirementAroseCoverPage") or ""   # the day the change happened
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            date = filed
        ratio = to_number(pick(values, "HoldingRatioOfShareCertificatesEtc"))
        before = to_number(pick(values, "HoldingRatioOfShareCertificatesEtcPerLastReport"))
        held = to_number(pick(values, "TotalNumberOfStocksEtcHeld"))
        joint = to_number(pick(values, "TotalNumberOfFilersAndJointHoldersCoverPage")) or 1
        name_en = pick(values, "FilerNameInEnglishDEI")
        if name_en and re.search(r"[A-Za-z]", name_en):
            insider = html.unescape(name_en).strip()      # 'Fidelity Management &amp; Research' -> '&'
    insider = re.sub(r"^株式会社\s*|\s*株式会社$", "", insider)   # '株式会社C&I Holdings' -> 'C&I Holdings'
    if joint > 1:
        insider += f" (+{joint - 1} joint holder{'s' if joint > 2 else ''})"
    role = "5% holder"
    if ratio is not None:
        role += f", {ratio * 100:.2f}%"
        if before is not None:
            role += f" (was {before * 100:.2f}%)"
        elif code.startswith("Large holding"):
            role += " (new)"
    if amended or ratio is None:
        kind = "other"
    elif before is None:
        kind = "buy" if code.startswith("Large holding") else "other"   # a new report = crossed above 5%
    else:
        kind = "buy" if ratio > before else "sell" if ratio < before else "other"
    return make_row(node_ids=node_ids, date=date, filed=filed, insider=insider, role=role, code=code, type_=kind,
                    shares=None, owned_after=held, currency="JPY", market="JP", source="EDINET",
                    url=EDINET_VIEWER.format(doc["docID"]))


def run_jp(backfill, state):
    """Japan: returns the number of new rows. Raises if EDINET cannot be used at all."""
    if not os.getenv("EDINET_API_KEY"):
        raise RuntimeError("EDINET_API_KEY missing in .env")
    EDINET_LISTS.mkdir(parents=True, exist_ok=True)
    codes = edinet_codes()
    ours = {}                                            # issuer EDINET code -> [node ids]
    for sec, node_ids in companies("JP", jp_sec_code).items():
        if codes["sec"].get(sec):
            ours[codes["sec"][sec]] = node_ids
        else:
            log(f"WARNING: no EDINET code for {sec} ({', '.join(node_ids)})")
    jst_today = dt.datetime.now(JST).date()
    first = jst_today - dt.timedelta(days=WINDOW_DAYS)
    if not backfill:                                     # daily: the days since the last run (2 days overlap)
        last = state.get("jp_last")
        start = dt.date.fromisoformat(last) - dt.timedelta(days=2) if last else jst_today - dt.timedelta(days=7)
        first = max(first, start)
    days = [(first + dt.timedelta(days=i)).isoformat() for i in range((jst_today - first).days + 1)]
    failures = 0
    for i, day in enumerate(days, 1):
        try:
            edinet_list(day, jst_today.isoformat())
        except Exception as e:
            failures += 1
            log(f"WARNING: EDINET list for {day} failed ({scrub(str(e))[:120]})")
            if "401" in str(e) or failures == i == 5:     # a wrong key, or the first 5 days all failed
                raise RuntimeError("EDINET list requests keep failing")
        if i % 30 == 0:
            log(f"JP: listed {i}/{len(days)} days (up to {day})")
    if days and failures == len(days):
        raise RuntimeError(f"every EDINET list request failed ({failures} days)")   # logged as a failed market

    # Every cached day inside the window, not only today's walk: a report whose CSV failed last time is retried.
    recorded = {r["url"] for r in read_history("insiders_jp")}
    since = (jst_today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    todo = []
    for path in sorted(EDINET_LISTS.glob("*.json"), reverse=True):   # newest day first
        if path.stem < since:
            continue
        for doc in (read_json(path, {}) or {}).get("rows", []):
            url = EDINET_VIEWER.format(doc["docID"])
            if doc.get("issuerEdinetCode") in ours and doc.get("withdrawalStatus") == "0" and url not in recorded:
                todo.append(doc)
                recorded.add(url)                        # a document listed on two file dates is read once
    log(f"JP: {len(todo)} new large-holding reports of our companies to read")
    rows, added, missed = [], 0, 0
    for i, doc in enumerate(todo, 1):
        try:
            rows.append(jp_row(doc, ours[doc["issuerEdinetCode"]], codes["english"]))
        except Exception as e:
            missed += 1
            log(f"WARNING: EDINET document {doc['docID']} failed ({scrub(str(e))[:120]}); retried next run")
        if i % SAVE_EVERY == 0 or i == len(todo):        # save as we go so an interrupted backfill resumes
            added += append_history("insiders_jp", rows, KEY_JP)
            rows = []
            log(f"JP: read {i}/{len(todo)} reports ({missed} failed)")
    if failures:
        # a day whose list failed has not been read: keep the cursor, so the next run lists it again
        log(f"JP: {failures} of {len(days)} list days failed; jp_last stays {state.get('jp_last')}")
    else:
        save_state("jp_last", jst_today.isoformat())
    return added


# ================================================================ run / build

def build():
    """graph/insiders/ (one file per company) is shared by every market (US, KR, TW, JP), so the builder lives in market/insiders.py.
    Until that module exists there is nothing to rebuild."""
    if importlib.util.find_spec("market.insiders") is None:
        log("market/insiders.py not found; graph/insiders/ (one file per company) not rebuilt")
        return None
    from market import insiders
    return insiders.build()


MARKETS = {"KR": run_kr, "TW": run_tw, "JP": run_jp}


def run(backfill=False, markets=("KR", "TW", "JP")):
    """Fetch new filings, append them to history, rebuild graph/insiders/ (one file per company).
    Returns {market: new rows, or None when that market failed}."""
    load_env()
    CACHE.mkdir(parents=True, exist_ok=True)
    gitignore = CACHE / ".gitignore"                     # caches are re-made on demand: keep them out of git
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")
    state = read_json(STATE_FILE, {}) or {}
    result = {}
    for market in markets:
        try:
            result[market] = MARKETS[market](backfill, state)
            log(f"{market}: {result[market]} new history rows")
        except Exception as e:
            result[market] = None
            log(f"WARNING: {market} failed ({scrub(str(e))[:160]}); previous data kept")
    build()
    return result


def main():
    ap = argparse.ArgumentParser(description="Korean / Taiwanese / Japanese insider and major-holder changes")
    ap.add_argument("--backfill", action="store_true", help="Korea: every company; Japan: walk the last 365 days")
    ap.add_argument("--build-only", action="store_true", help="rebuild graph/insiders/ (one file per company) from history only")
    ap.add_argument("--recheck-kr-prices", action="store_true",
                    help="one-off: re-read Korean reports whose unit price looks joined, record corrections, rebuild")
    args = ap.parse_args()
    if args.build_only:
        build()
        return 0
    if args.recheck_kr_prices:
        recheck_kr_prices()
        build()
        return 0
    result = run(backfill=args.backfill)
    return 1 if all(v is None for v in result.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
