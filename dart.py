"""Pull Korean company earnings from DART (opendart.fss.or.kr) into transcripts/dart/*.txt.

Korean listed companies (SK Hynix, Samsung, Hanmi, Simmtech, ...) have no Motley
Fool transcript. What they DO have is the mandatory periodic filing on DART:
사업보고서 (annual), 반기보고서 (H1), 분기보고서 (Q1/Q3). The filing contains the
sections a supply-chain analyst wants -- 사업의 내용 (products, raw-material
suppliers, capacity/utilisation, order backlog 수주상황) and 재무에 관한 사항.

For every (company, year, quarter) this script writes ONE text file that holds:
    1. a header with the canonical source label to use during enrichment
    2. the full financial statements (BS / IS / CF, consolidated) as a table
    3. the full text of the periodic report (tables flattened to "a | b | c")

The file goes to transcripts/dart/<slug>_q<N>_<year>_dart.txt and is then
enriched exactly like any other transcript (CLAUDE.md, Workflow 2).

Two more filing types matter and arrive on their own schedule, so `sync` scans
the WHOLE DART feed for a date range and keeps only our companies:
    잠정실적 (영업(잠정)실적(공정공시))  earnings-day numbers, same day as the IR
                                          release -> transcripts/dart/<slug>_prelim_<date>.txt
    공급계약 (단일판매ㆍ공급계약체결)      order wins, any day -> appended to
                                          supply_contracts/<slug>.txt (one file per company, full text)

Usage:
    python dart.py corp                      download the corp_code table (once; re-run yearly)
    python dart.py fetch "SK Hynix" 2026 2   one company, one quarter (1-4; 4 = annual 사업보고서)
    python dart.py fetch --all 2026 2        every KRX company in company_metadata.json
    python dart.py fetch --all --latest      newest periodic filing per company
    python dart.py sync                      everything new on DART since the last sync, for OUR
                                             companies only: 잠정실적 → transcripts/dart/, 공급계약 →
                                             supply_contracts/<company>.txt, 정기보고서 → full fetch
    python dart.py sync --since 20260801     re-scan from a date (already-saved filings are skipped)
    python dart.py pending                   files saved by sync that have not been enriched yet
    python dart.py done                      clear that queue after enriching everything in it

Needs DART_API_KEY in .env -- free key from https://opendart.fss.or.kr (회원가입 → 인증키 신청).
"""
import argparse
import html
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

import requests
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)  # DART XML is HTML-ish on purpose

ROOT = Path(__file__).parent
METADATA = ROOT / "company_metadata.json"     # the universe: KRX rows carry a 6-digit stock code
CORP_CODES = ROOT / "dart" / "corp_codes.json"  # stock_code -> {corp_code, corp_name}, from `corp`
OUT_DIR = ROOT / "transcripts" / "dart"
CONTRACTS_DIR = ROOT / "supply_contracts"        # one accumulating file per company
STATE = ROOT / "dart" / "sync_state.json"        # last sync date + rcept_nos already saved
PENDING = ROOT / "dart" / "pending.json"         # files saved by sync but not yet enriched

API = "https://opendart.fss.or.kr/api"
API_KEY = os.getenv("DART_API_KEY")

# DART's code for each periodic report. Q4 has no separate filing -- the annual
# report (사업보고서) covers it, so quarter 4 means "annual".
REPRT_CODE = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
REPORT_NAME = {1: "분기보고서", 2: "반기보고서", 3: "분기보고서", 4: "사업보고서"}
# The month DART prints in the report title, e.g. "반기보고서 (2026.06)".
REPORT_MONTH = {1: "03", 2: "06", 3: "09", 4: "12"}


# ---------------------------------------------------------------- universe

def universe():
    """Korean companies from company_metadata.json, one entry per stock code.

    If two names ever share one stock code (Samsung Foundry used to sit beside
    Samsung on 005930 before they were merged), the filing is the same, so we
    keep the first canonical name per code and skip the duplicate.
    """
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    seen = {}
    for name, info in meta.items():
        # Tickers come in two spellings: a bare 6-digit code ("319660") and a
        # Yahoo-style suffixed one ("005490.KS" / ".KQ"). Both are the same DART
        # company -- taking the part before the dot covers each of them. Codes
        # shorter than 6 digits are zero-padded ("7810" -> "007810").
        code = str(info.get("ticker", "")).split(".")[0].strip().zfill(6)
        korean = info.get("exchange") in ("KRX", "KOSPI", "KOSDAQ")
        if korean and re.fullmatch(r"\d{6}", code) and code not in seen:
            seen[code] = name
    return {name: code for code, name in seen.items()}  # canonical name -> stock code


def slug(name):
    """'HD Hyundai Electric' -> 'hdhyundaielectric', matching skhynix_q1_2026.txt style."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ---------------------------------------------------------------- DART calls

def _get(endpoint, **params):
    if not API_KEY:
        sys.exit("DART_API_KEY missing in .env (get one at https://opendart.fss.or.kr)")
    r = requests.get(f"{API}/{endpoint}", params={"crtfc_key": API_KEY, **params}, timeout=60)
    r.raise_for_status()
    return r


def download_corp_codes():
    """corpCode.xml is a zip holding one XML with every DART-registered company.

    We keep only rows that have a stock code (listed companies) so the JSON stays small.
    """
    raw = _get("corpCode.xml").content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read(z.namelist()[0]).decode("utf-8")
    table = {}
    for block in re.findall(r"<list>(.*?)</list>", xml, flags=re.S):
        stock = re.search(r"<stock_code>\s*(\S*?)\s*</stock_code>", block).group(1)
        if not stock:
            continue
        table[stock] = {
            "corp_code": re.search(r"<corp_code>(.*?)</corp_code>", block).group(1).strip(),
            "corp_name": re.search(r"<corp_name>(.*?)</corp_name>", block).group(1).strip(),
        }
    CORP_CODES.parent.mkdir(exist_ok=True)
    CORP_CODES.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    return table


def corp_code(stock_code):
    if not CORP_CODES.exists():
        download_corp_codes()
    table = json.loads(CORP_CODES.read_text(encoding="utf-8"))
    if stock_code not in table:
        raise KeyError(f"stock code {stock_code} not in dart/corp_codes.json (run: python dart.py corp)")
    return table[stock_code]


def list_periodic_filings(corp, since="20150101"):
    """All 정기공시 (pblntf_ty=A) for a company, newest first.

    Each row: rcept_no (filing id), report_nm ('반기보고서 (2026.06)'), rcept_dt ('20260814').
    Amended filings are titled '[기재정정] ...' -- kept, and picked over the original
    when both exist because the correction is the final version.
    """
    rows, page = [], 1
    while True:
        data = _get("list.json", corp_code=corp, bgn_de=since, end_de=date.today().strftime("%Y%m%d"),
                    pblntf_ty="A", page_no=page, page_count=100).json()
        if data.get("status") != "000":
            break
        rows += data["list"]
        if page >= int(data.get("total_page", 1)):
            break
        page += 1
    return rows


def find_filing(corp, year, quarter):
    """The one filing for (year, quarter), e.g. '반기보고서 (2026.06)'."""
    wanted = f"{REPORT_NAME[quarter]} ({year}.{REPORT_MONTH[quarter]})"
    hits = [r for r in list_periodic_filings(corp) if wanted in r["report_nm"]]
    if not hits:
        raise LookupError(f"no {wanted} on DART")
    # Prefer the corrected version ([기재정정]) if one was filed.
    hits.sort(key=lambda r: ("기재정정" in r["report_nm"], r["rcept_dt"]), reverse=True)
    return hits[0]


def latest_filing(corp):
    """Newest periodic report of any kind -> (row, year, quarter)."""
    for r in list_periodic_filings(corp):
        m = re.search(r"(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)", r["report_nm"])
        if m:
            year, month = int(m.group(2)), m.group(3)
            quarter = {"03": 1, "06": 2, "09": 3, "12": 4}[month]
            return r, year, quarter
    raise LookupError("no periodic filing on DART")


def financials(corp, year, quarter):
    """Full statements via fnlttSinglAcntAll (연결 CFS; falls back to 별도 OFS).

    Returns (fs_div, rows). Each row has sj_nm (statement), account_nm, and amounts:
    thstrm_amount = this period, thstrm_add_amount = year-to-date (quarterly IS only),
    frmtrm_amount = same period last year. Amounts are KRW (원).
    """
    for fs_div in ("CFS", "OFS"):
        data = _get("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=year,
                    reprt_code=REPRT_CODE[quarter], fs_div=fs_div).json()
        if data.get("status") == "000":
            return fs_div, data["list"]
    return None, []


def report_text(rcept_no):
    """document.xml -> the report body as plain text.

    The zip holds the main report XML (plus sometimes attachments); the main one
    is the largest. DART's XML is HTML-like and not always well-formed, so we
    parse it with BeautifulSoup's forgiving html.parser and flatten tables to
    'cell | cell | cell' rows so the numbers keep their column context.
    """
    raw = _get("document.xml", rcept_no=rcept_no).content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = max(z.namelist(), key=lambda n: z.getinfo(n).file_size)
        body = z.read(name)
    try:
        text = body.decode("utf-8")          # DART files are UTF-8 (often with a BOM) ...
    except UnicodeDecodeError:
        text = body.decode("cp949", errors="ignore")  # ... older ones are EUC-KR
    soup = BeautifulSoup(text, "html.parser")

    for table in soup.find_all("table"):
        lines = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th", "te", "tu"])]
            if any(cells):
                lines.append(" | ".join(cells))
        table.replace_with("\n" + "\n".join(lines) + "\n")

    # Titles/paragraphs become their own lines so sections stay readable.
    for tag in soup.find_all(["title", "p", "br", "section-1", "section-2", "section-3"]):
        tag.insert_before("\n")
    out = html.unescape(soup.get_text())
    out = re.sub(r"[ \t ]+", " ", out)
    out = re.sub(r"\n\s*\n+", "\n\n", out)
    return out.strip()


# ---------------------------------------------------------------- writing

def source_label(name, quarter, rcept_dt):
    """Canonical label from CLAUDE.md: '[Company] Q[N] FY[YYYY] (MM-DD-YYYY)'.

    Korean filers use the calendar year, and the date is the FILING date, not
    quarter-end. Q4 == the annual report.
    """
    d = datetime.strptime(rcept_dt, "%Y%m%d")
    return f"{name} Q{quarter} FY{d.year if quarter != 4 else d.year - 1} ({d:%m-%d-%Y})"


def _fmt(amount):
    try:
        return f"{int(str(amount).replace(',', '')):,}"
    except (TypeError, ValueError):
        return amount or "-"


def write_file(name, year, quarter, filing, fs_div, rows, body):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{slug(name)}_q{quarter}_{year}_dart.txt"
    label = source_label(name, quarter, filing["rcept_dt"])

    lines = [
        f"# {name} — {year} Q{quarter} — {filing['report_nm']}",
        f"# source label: {label}",
        f"# DART rcept_no: {filing['rcept_no']}   filed: {filing['rcept_dt']}   "
        f"url: https://dart.fss.or.kr/dsaf001/main.do?rcptNo={filing['rcept_no']}",
        f"# financials: {'연결 (consolidated)' if fs_div == 'CFS' else '별도 (separate)' if fs_div else 'none'}, KRW",
        "",
        "## FINANCIAL STATEMENTS (fnlttSinglAcntAll)",
        "",
    ]
    current = None
    for r in rows:
        if r["sj_nm"] != current:
            current = r["sj_nm"]
            lines += ["", f"### {current}",
                      f"account | {r.get('thstrm_nm', '당기')} | YTD | {r.get('frmtrm_nm', '전기')} | {r.get('bfefrmtrm_nm', '전전기')}"]
        lines.append(" | ".join([
            r["account_nm"], _fmt(r.get("thstrm_amount")), _fmt(r.get("thstrm_add_amount")),
            _fmt(r.get("frmtrm_amount")), _fmt(r.get("bfefrmtrm_amount")),
        ]))
    lines += ["", "", "## REPORT TEXT", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, label


def fetch(name, stock_code, year=None, quarter=None):
    corp = corp_code(stock_code)["corp_code"]
    if year is None:
        filing, year, quarter = latest_filing(corp)
    else:
        filing = find_filing(corp, year, quarter)
    fs_div, rows = financials(corp, year, quarter)
    body = report_text(filing["rcept_no"])
    return write_file(name, year, quarter, filing, fs_div, rows, body)


# ---------------------------------------------------------------- sync (whole feed -> our companies)

# report_nm patterns for the two event-driven filing types. '[정정]' variants match too.
PRELIM_RE = re.compile(r"영업\(잠정\)실적")             # 연결재무제표기준영업(잠정)실적(공정공시) / 영업(잠정)실적(공정공시)
CONTRACT_RE = re.compile(r"단일판매|공급계약")           # 단일판매ㆍ공급계약체결
PERIODIC_RE = re.compile(r"(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)")


def list_feed(since, until=None):
    """Every filing on DART in [since, until] for ALL companies (no corp_code).

    A corp-less query is capped at 3 months and a busy day runs to thousands of
    rows, so we ask only for the two publication types we route:
    A = 정기공시 (periodic reports), I = 거래소공시 (잠정실적, 공급계약, ...).
    """
    until = until or date.today().strftime("%Y%m%d")
    rows = []
    for pblntf_ty in ("A", "I"):
        page = 1
        while True:
            data = _get("list.json", bgn_de=since, end_de=until, pblntf_ty=pblntf_ty,
                        page_no=page, page_count=100).json()
            if data.get("status") != "000":
                break
            rows += data["list"]
            if page >= int(data.get("total_page", 1)):
                break
            page += 1
    return rows


def quarter_from_filing_date(rcept_dt):
    """Which quarter a 잠정실적 filed on this date reports on.

    Korean prelims land ~1-6 weeks after quarter end: Jan-Mar -> Q4 of the prior
    year, Apr-Jun -> Q1, Jul-Sep -> Q2, Oct-Dec -> Q3.
    """
    month = datetime.strptime(rcept_dt, "%Y%m%d").month
    return {1: 4, 2: 4, 3: 4, 4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3}[month]


def _header(name, filing):
    return [
        f"# {name} — {filing['report_nm']}",
        f"# DART rcept_no: {filing['rcept_no']}   filed: {filing['rcept_dt']}   "
        f"url: https://dart.fss.or.kr/dsaf001/main.do?rcptNo={filing['rcept_no']}",
    ]


def save_prelim(name, filing):
    """잠정실적 -> its own transcript file (full text of the 공정공시)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = datetime.strptime(filing["rcept_dt"], "%Y%m%d")
    label = source_label(name, quarter_from_filing_date(filing["rcept_dt"]), filing["rcept_dt"])
    # Companies file 연결 and 별도 prelims the same day; keep both, 연결 gets the plain name.
    suffix = "" if "연결" in filing["report_nm"] else "_separate"
    path = OUT_DIR / f"{slug(name)}_prelim_{d:%Y-%m-%d}{suffix}.txt"
    lines = _header(name, filing) + [f"# source label: {label}", "# amounts: KRW", "",
                                     "## PRELIMINARY RESULTS (잠정실적 공정공시)", "",
                                     report_text(filing["rcept_no"]), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, label


def save_contract(name, filing):
    """공급계약 -> appended to the company's supply_contracts file (newest at the bottom)."""
    CONTRACTS_DIR.mkdir(exist_ok=True)
    d = datetime.strptime(filing["rcept_dt"], "%Y%m%d")
    label = f"{name} DART supply contract ({d:%m-%d-%Y})"
    path = CONTRACTS_DIR / f"{slug(name)}.txt"
    block = ["", "=" * 100] + _header(name, filing) + [f"# source label: {label}", "# amounts: KRW", "",
                                                        report_text(filing["rcept_no"]), ""]
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block))
    return path, label


def sync(since=None, until=None):
    """Pull everything new for OUR companies. Returns a list of (kind, name, path, label)."""
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"last_sync": None, "seen": []}
    seen = set(state["seen"])
    if since is None:  # from the last sync DAY inclusive -- same-day filings keep arriving after a run
        since = state["last_sync"] or date.today().replace(day=1).strftime("%Y%m%d")

    uni = universe()
    ours = {corp_code(code)["corp_code"]: name for name, code in uni.items()}  # corp_code -> canonical name

    saved = []
    for filing in sorted(list_feed(since, until), key=lambda r: r["rcept_no"]):
        name = ours.get(filing["corp_code"])
        if not name or filing["rcept_no"] in seen:
            continue  # not one of ours, or already saved
        report = filing["report_nm"]
        kind = None
        try:
            if PRELIM_RE.search(report):
                kind = "prelim"
                path, label = save_prelim(name, filing)
            elif CONTRACT_RE.search(report):
                kind = "contract"
                path, label = save_contract(name, filing)
            elif (m := PERIODIC_RE.search(report)):
                kind = "periodic"
                year, quarter = int(m.group(2)), {"03": 1, "06": 2, "09": 3, "12": 4}[m.group(3)]
                path, label = fetch(name, uni[name], year, quarter)
            else:
                continue  # other 거래소공시 (주주총회, 자기주식, ...) -- not routed
            seen.add(filing["rcept_no"])
            saved.append((kind, name, path, label))
            print(f"{kind:9s} {label:45s} -> {path.relative_to(ROOT)}")
            time.sleep(0.3)
        except Exception as exc:
            print(f"FAIL {kind} {name} {report}: {exc}")

    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"last_sync": date.today().strftime("%Y%m%d"), "seen": sorted(seen)}, indent=1),
                     encoding="utf-8")

    # Queue for enrichment. Entries stay here across runs until `python dart.py done`
    # clears them, so nothing is enriched twice and nothing new is skipped.
    pending = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else []
    known = {(x["kind"], x["file"], x["label"]) for x in pending}
    for kind, name, path, label in saved:
        row = {"kind": kind, "company": name, "file": str(path.relative_to(ROOT)).replace("\\", "/"), "label": label}
        if (row["kind"], row["file"], row["label"]) not in known:
            pending.append(row)
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")
    return saved


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Korean report names on the Windows console
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("corp", help="download DART corp_code table")
    f = sub.add_parser("fetch", help="pull filings into transcripts/dart/")
    f.add_argument("company", nargs="?", help="canonical name from company_metadata.json")
    f.add_argument("year", nargs="?", type=int)
    f.add_argument("quarter", nargs="?", type=int, choices=[1, 2, 3, 4], help="4 = annual 사업보고서")
    f.add_argument("--all", action="store_true", help="every KRX company in company_metadata.json")
    f.add_argument("--latest", action="store_true", help="newest filing instead of year/quarter")
    sy = sub.add_parser("sync", help="new 잠정실적 / 공급계약 / 정기보고서 for our companies since last sync")
    sy.add_argument("--since", help="YYYYMMDD; default = last sync date (first run: 1st of this month)")
    sy.add_argument("--until", help="YYYYMMDD; default = today")
    sub.add_parser("pending", help="list files saved by sync that are not enriched yet")
    sub.add_parser("done", help="mark everything in the pending queue as enriched")
    args = parser.parse_args()

    if args.cmd == "pending":
        rows = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else []
        for r in rows:
            print(f"{r['kind']:9s} {r['label']:50s} {r['file']}")
        print(f"{len(rows)} pending")
        sys.exit()
    if args.cmd == "done":
        PENDING.write_text("[]", encoding="utf-8")
        print("pending queue cleared")
        sys.exit()

    if args.cmd == "sync":
        saved = sync(args.since, args.until)
        print(f"{len(saved)} new filings saved -> python dart.py pending")
        sys.exit()

    if args.cmd == "corp":
        table = download_corp_codes()
        print(f"{len(table)} listed companies -> {CORP_CODES.relative_to(ROOT)}")
        sys.exit()

    uni = universe()
    if args.all:
        # with --all there is no company word, so the positionals shift left by one
        if args.company is not None:
            args.year, args.quarter = int(args.company), args.year
        targets = uni
    elif args.company in uni:
        targets = {args.company: uni[args.company]}
    else:
        sys.exit(f"unknown company {args.company!r}. Known: {', '.join(uni)}")
    if not args.latest and (args.year is None or args.quarter is None):
        sys.exit("give YEAR QUARTER, or --latest")

    for i, (name, code) in enumerate(targets.items()):
        try:
            path, label = fetch(name, code, None if args.latest else args.year, None if args.latest else args.quarter)
            print(f"OK   {label:45s} -> {path.relative_to(ROOT)}")
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
        if i < len(targets) - 1:
            time.sleep(0.5)  # polite; DART allows 20k calls/day
