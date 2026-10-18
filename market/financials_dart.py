"""market/financials_dart.py -- OpenDART statements for Korean companies in the financial-statement table.

Why (verification of 2026-10-17): Yahoo's Korean statements hold about 5 quarters (too few for year-over-year),
derive a fiscal Q4 EPS only approximately (SK Hynix Q4 25: FY - the three quarters' EPS = 21,537; DART's FY - 9
months cumulative EPS = 21,528), and mix share counts with and without preferred shares (Samsung's
OrdinarySharesNumber is 6,630M at 2025-12-31 but 5,793M a quarter later), which made the PBR columns
incomparable. The filings themselves (DART) have every quarter, the cumulative figures and the share counts.

What this module does (DART_API_KEY in .env; at most 4 calls per second):
  fetch(corp_code)   per report (Q1 11013, half-year 11012, Q3 11014, annual 11011) of the last 3-4 years:
                     fnlttSinglAcntAll (consolidated, else separate statements; the balance sheet, income statement
                     and cash-flow statement rows are kept) and stockTotqySttus (shares issued / treasury /
                     outstanding per share class). A filed report never changes, so each is fetched once (a report
                     cached before 2026-10-17 lacks the cash-flow statement and is fetched once more, keeping its
                     share counts); one not filed yet is retried after its due date. Also the exchange disclosures
                     since the newest report: a preliminary-results filing (연결재무제표기준영업(잠정)실적(공정공시)) is read
                     (document.xml) for its revenue and operating income.
                     Cache: market/cache/financials/dart/<corp_code>.json (gitignored).
  periods(cache)     pure: -> the same shape as market/financials_sec.periods(): per field [("DART", {end: (value,
                     computed)})]. A fiscal Q4 is the annual report minus the Q3 report's 9-month cumulative figure
                     (diluted EPS too, as Korean data vendors do); computed=True. Balances: total assets, equity
                     attributable to owners, and the shares outstanding of ALL classes (common + preferred - treasury),
                     the basis of Korean book value per share (FnGuide / Naver). "cash": operating cash flow (영업활동
                     현금흐름) and capex (유형자산의 취득, as a positive number) per quarter and year; the cash-flow
                     statement of a quarterly report is year-to-date, so Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M.
  preliminary(cache) pure: the newest preliminary results, or None.
"""
import datetime as dt
import io
import os
import re
import threading
import time
import zipfile

from market.common import ROOT, get, load_env, read_json, today, write_json

DART_API = "https://opendart.fss.or.kr/api/"
DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
CORP_CODES = ROOT / "dart" / "corp_codes.json"           # stock code -> corp_code (written by dart.py corp)
CACHE_DIR = ROOT / "market" / "cache" / "financials" / "dart"
SOURCE = {"name": "DART (Korea FSS)", "url": "https://dart.fss.or.kr/"}
MIN_GAP = 0.25                     # seconds between OpenDART calls
YEARS_BACK = 3                     # this year and the 3 before it
REPORTS = (("11013", 1), ("11012", 2), ("11014", 3), ("11011", 4))   # report code -> fiscal quarter it closes
DUE_DAYS = {1: 45, 2: 45, 3: 45, 4: 90}                              # filing deadline after the period end
RETRY_DAYS = 1                     # a report not found is asked again after this many days (until it is filed)
GIVE_UP_DAYS = 200                 # ... and no longer once its period ended this long ago (never filed)
REPORT_FORMAT = 2                  # 2 (2026-10-17): the cash-flow statement (sj_div "CF") is kept too

# Contract field -> (account ids, account names). Names catch rows filed without a standard id
# ("-표준계정코드 미사용-"); they are compared without spaces and without a "(손실)" suffix.
ACCOUNTS = {
    "revenue": (("ifrs-full_Revenue", "ifrs_Revenue", "ifrs-full_RevenueFromContractsWithCustomers"),
                ("매출액", "수익(매출액)", "영업수익", "매출", "매출액(영업수익)")),
    "gross_profit": (("ifrs-full_GrossProfit", "ifrs_GrossProfit"), ("매출총이익",)),
    "operating_income": (("dart_OperatingIncomeLoss",), ("영업이익", "영업손실")),
    "pretax_income": (("ifrs-full_ProfitLossBeforeTax", "ifrs_ProfitLossBeforeTax"),
                      ("법인세비용차감전순이익", "법인세차감전순이익", "법인세비용차감전이익")),
    "net_income_after_tax": (("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"),
                             ("당기순이익", "분기순이익", "반기순이익", "연결당기순이익")),
    "net_income": (("ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs_ProfitLossAttributableToOwnersOfParent"),
                   ("지배기업소유주지분", "지배기업의소유주지분", "지배기업소유지분", "지배주주지분")),
    "eps_diluted": (("ifrs-full_DilutedEarningsLossPerShare", "ifrs_DilutedEarningsLossPerShare"),
                    ("희석주당이익", "희석주당순이익", "희석주당분기순이익", "희석주당반기순이익")),
    "eps_basic": (("ifrs-full_BasicEarningsLossPerShare", "ifrs_BasicEarningsLossPerShare",
                   "ifrs-full_BasicAndDilutedEarningsLossPerShare"),
                  ("기본주당이익", "기본주당순이익", "기본및희석주당이익", "기본및희석주당순이익")),
}
BALANCE_ACCOUNTS = {
    "total_assets": (("ifrs-full_Assets", "ifrs_Assets"), ("자산총계",)),
    "equity": (("ifrs-full_EquityAttributableToOwnersOfParent", "ifrs_EquityAttributableToOwnersOfParent"),
               ("지배기업소유주지분", "지배기업의소유주지분", "지배기업소유지분")),
    "equity_total": (("ifrs-full_Equity", "ifrs_Equity"), ("자본총계",)),
}
# Cash-flow statement (sj_div "CF", 2026-10-17). Capex is the purchase of property, plant and equipment, as
# market/hyperscaler_cash.py's SEC capex tag (intangible assets are a separate row); its sign varies by filer.
CASH_ACCOUNTS = {
    "ocf": (("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"),
            ("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로인한순현금흐름", "영업활동순현금흐름")),
    "capex": (("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
               "ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
              ("유형자산의취득", "유형자산취득")),
}
FLOW_FIELDS = ("revenue", "gross_profit", "operating_income", "pretax_income", "net_income_after_tax", "net_income")
PER_SHARE = ("eps_diluted",)
PRELIM_ITEMS = {"매출액": "revenue", "영업이익": "operating_income",
                "법인세비용차감전계속사업이익": "pretax_income", "당기순이익": "net_income_after_tax",
                "지배기업소유주지분순이익": "net_income"}
PRELIM_UNITS = {"조원": 1e12, "억원": 1e8, "백만원": 1e6, "천원": 1e3, "원": 1.0}

_last = [0.0]
_lock = threading.Lock()           # a backfill may fetch several companies at once: one shared pace


def log(msg):
    print(f"[financials/dart] {msg}", flush=True)


class DartLimit(Exception):
    """OpenDART's daily request limit (status 020) or a key problem: stop asking for today."""


def call(endpoint, binary=False, **params):
    """One OpenDART call. JSON endpoints: the parsed body, None for status 013 (no data). binary: the bytes."""
    with _lock:
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    r = get(DART_API + endpoint, params={"crtfc_key": os.getenv("DART_API_KEY"), **params}, timeout=60)
    if binary:
        if r.content[:2] == b"PK":
            return r.content
        js = r.json() if r.content[:1] == b"{" else {}
        if js.get("status") in ("020", "010", "011", "012", "901"):
            raise DartLimit(f"{js.get('status')} {js.get('message')}")
        return None
    js = r.json()
    status = js.get("status")
    if status == "000":
        return js
    if status == "013":
        return None
    if status in ("020", "010", "011", "012", "901"):
        raise DartLimit(f"{status} {js.get('message')}")
    raise RuntimeError(f"OpenDART {endpoint}: status {status} {js.get('message')}")


def corp_code_of(ticker, exchange):
    """'000660.KS' / '356860' on a Korean board -> DART corp_code, or None."""
    if exchange not in ("KRX", "KOSPI", "KOSDAQ", "KONEX"):
        return None
    code = str(ticker or "").split(".")[0].strip()
    if not code.isdigit():
        return None
    codes = read_json(CORP_CODES, {}) or {}
    return (codes.get(code.zfill(6)) or {}).get("corp_code")


def cache_path(corp_code):
    return CACHE_DIR / f"{corp_code}.json"


# ------------------------------------------------ parsing helpers (pure)

def amount(text):
    """'1,234' / '-1,234' / '(1,234)' / '' -> float or None."""
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    if s in ("", "-", "N/A"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _norm_name(name):
    s = re.sub(r"\s+", "", name or "")
    s = re.sub(r"\((손실|이익|손익)\)$", "", s)
    return s


def _pick(rows, ids, names, statements):
    """The first row (by statement preference, then filing order) whose account id or name matches."""
    for sj in statements:
        cands = [r for r in rows if r.get("sj_div") == sj]
        for r in cands:
            if r.get("account_id") in ids:
                return r
        for r in cands:
            if _norm_name(r.get("account_nm")) in names:
                return r
    return None


ROW_COLUMNS = ("sj_div", "account_id", "account_nm", "thstrm_amount", "thstrm_add_amount", "frmtrm_amount",
               "bfefrmtrm_amount")


def compact_report(js, fs_div):
    """A fnlttSinglAcntAll answer -> what the cache keeps: {"fs_div", "currency", "format", "rows": [[sj_div,
    account_id, account_nm, this period, this period cumulative, FY-1, FY-2], ...]} for the balance sheet, the
    income statement(s) and the cash-flow statement. The rows are kept as filed, so a better account mapping later
    needs no new download."""
    rows = js.get("list") or []
    return {"fs_div": fs_div, "currency": next((r.get("currency") for r in rows if r.get("currency")), None),
            "format": REPORT_FORMAT,
            "rows": [[r.get(c) for c in ROW_COLUMNS] for r in rows if r.get("sj_div") in ("BS", "IS", "CIS", "CF")]}


def extract(report):
    """A cached report -> {"flows": {field: [this period, cumulative]}, "annual_prior": {field: [FY-1, FY-2]},
    "balances": {field: [now, FY-1, FY-2]}, "cash": {field: [year-to-date, FY-1, FY-2]}} (capex as a positive
    number; a cash-flow statement is year-to-date: "this period" of a Q3 report is the nine months)."""
    rows = [dict(zip(ROW_COLUMNS, r)) for r in report.get("rows") or []]
    out = {"flows": {}, "annual_prior": {}, "balances": {}, "cash": {}}
    for field, (ids, names) in ACCOUNTS.items():
        r = _pick(rows, ids, {_norm_name(n) for n in names}, ("IS", "CIS"))
        if r:
            out["flows"][field] = [amount(r.get("thstrm_amount")), amount(r.get("thstrm_add_amount"))]
            out["annual_prior"][field] = [amount(r.get("frmtrm_amount")), amount(r.get("bfefrmtrm_amount"))]
    for field, (ids, names) in BALANCE_ACCOUNTS.items():
        r = _pick(rows, ids, {_norm_name(n) for n in names}, ("BS",))
        if r:
            out["balances"][field] = [amount(r.get("thstrm_amount")), amount(r.get("frmtrm_amount")),
                                      amount(r.get("bfefrmtrm_amount"))]
    for field, (ids, names) in CASH_ACCOUNTS.items():
        r = _pick(rows, ids, {_norm_name(n) for n in names}, ("CF",))
        if r:
            ytd = amount(r.get("thstrm_add_amount"))       # a cumulative column, when a filer gives one
            values = [amount(r.get("thstrm_amount")) if ytd is None else ytd, amount(r.get("frmtrm_amount")),
                      amount(r.get("bfefrmtrm_amount"))]
            out["cash"][field] = [abs(v) if v is not None and field == "capex" else v for v in values]
    return out


def compact_shares(js):
    """A stockTotqySttus answer -> {"end": stlm_dt, "outstanding": all classes, "common": common only}."""
    rows = (js or {}).get("list") or []
    total = next((r for r in rows if (r.get("se") or "").strip() == "합계"), None)
    common = next((r for r in rows if (r.get("se") or "").strip() == "보통주"), None)
    end = next((r.get("stlm_dt") for r in rows if r.get("stlm_dt")), None)
    return {"end": end, "outstanding": amount((total or {}).get("distb_stock_co")),
            "common": amount((common or {}).get("distb_stock_co"))}


def parse_preliminary(html):
    """The preliminary-results disclosure (공정공시 XForm) -> {"start", "end", "unit", "values": {field: full
    currency units}} for the reported quarter (당해실적), or None when the layout is not recognised."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    start = end = None
    unit = None
    values = {}
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        if cells[0] == "당기실적" and len(cells) >= 4 and not start:
            start, end = cells[1], cells[3]
        text = " ".join(cells)
        m = re.search(r"단위\s*[:：]\s*([조억백만천]*원)", text)
        if m and unit is None:
            unit = PRELIM_UNITS.get(m.group(1))
        name = re.sub(r"\s+", "", cells[0])
        if name in PRELIM_ITEMS and len(cells) >= 3 and cells[1] == "당해실적":
            v = amount(cells[2])
            if v is not None:
                values[PRELIM_ITEMS[name]] = v
    if not (start and end and unit and values and re.fullmatch(r"\d{4}-\d{2}-\d{2}", end or "")):
        return None
    return {"start": start, "end": end, "unit": unit, "values": {k: v * unit for k, v in values.items()}}


# ------------------------------------------------ the window of reports

def assumed_end(year, quarter):
    """Period end of a report of a December fiscal year (almost every Korean listing)."""
    month = 3 * quarter
    day = 31 if month in (3, 12) else 30
    return dt.date(year, month, day).isoformat()


def wanted_reports(now):
    """[(bsns_year, reprt_code, fiscal quarter, assumed end)]: the reports of the 12 newest quarters that are due by
    `now` (a Q4 needs the annual report and the Q3 report: FY - 9 months), any later quarter that may already be
    filed (ended 2+ weeks ago), and the annual reports of the 4 newest fiscal years (shares and balances of each)."""
    today_d = dt.date.fromisoformat(now)
    candidates = []
    for year in range(today_d.year - YEARS_BACK - 1, today_d.year + 1):
        for code, quarter in REPORTS:
            end = dt.date.fromisoformat(assumed_end(year, quarter))
            if end + dt.timedelta(days=14) <= today_d:
                candidates.append((year, quarter, end + dt.timedelta(days=DUE_DAYS[quarter]) <= today_d))
    due = [(y, q) for y, q, is_due in candidates if is_due]
    keep = set(due[-12:]) | {(y, q) for y, q, is_due in candidates if not is_due}
    keep |= {(y, 3) for y, q in list(keep) if q == 4}
    keep |= set([(y, q) for y, q in due if q == 4][-4:])
    codes = {quarter: code for code, quarter in REPORTS}
    return [(str(y), codes[q], q, assumed_end(y, q)) for y, q in sorted(keep)]


def fetch(corp_code, now=None):
    """Bring one company's cache up to date. Returns the cache dict (possibly unchanged). Raises DartLimit."""
    load_env()
    if not os.getenv("DART_API_KEY"):
        raise DartLimit("DART_API_KEY missing in .env")
    now = now or today()
    path = cache_path(corp_code)
    cache = read_json(path, None) or {"corp_code": corp_code, "reports": {}, "missing": {}, "preliminary": {}}
    changed = False
    today_d = dt.date.fromisoformat(now)
    for year, code, quarter, end in wanted_reports(now):
        key = f"{year}-{code}"
        old = cache["reports"].get(key)
        if old and old.get("format", 1) >= REPORT_FORMAT:
            continue
        if not old:
            last_try = cache["missing"].get(key)
            if last_try and ((today_d - dt.date.fromisoformat(last_try)).days < RETRY_DAYS
                             or (today_d - dt.date.fromisoformat(end)).days > GIVE_UP_DAYS):
                continue
            if today_d < dt.date.fromisoformat(end) + dt.timedelta(days=14):
                continue                               # far too early for this report
        report = None
        for fs_div in ("CFS", "OFS"):
            js = call("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=year, reprt_code=code, fs_div=fs_div)
            if js:
                report = compact_report(js, fs_div)
                break
        if report is None:
            if not old:                                # not filed yet (or never): asked again after RETRY_DAYS
                cache["missing"][key] = now
                changed = True
            continue                                   # an older-format report stays as it is
        if old and old.get("shares"):
            report["shares"] = old["shares"]           # an older-format report: its share counts are still right
        else:
            shares = call("stockTotqySttus.json", corp_code=corp_code, bsns_year=year, reprt_code=code)
            report["shares"] = compact_shares(shares)
        report.update({"year": int(year), "quarter": quarter,
                       "end": report["shares"].get("end") or end})
        cache["reports"][key] = report
        cache["missing"].pop(key, None)
        changed = True
    changed |= _fetch_preliminary(cache, now)
    if changed or not path.exists():
        cache["fetched"] = now
        write_json(path, cache)
    return cache


def _newest_report_end(cache):
    ends = [r.get("end") for r in (cache.get("reports") or {}).values() if r.get("end")]
    return max(ends) if ends else None


def _fetch_preliminary(cache, now):
    """Exchange disclosures (type I) since the newest report's period end: read each preliminary-results filing
    once (by receipt number). Returns True when the cache changed."""
    newest = _newest_report_end(cache)
    if not newest:
        return False
    start = (dt.date.fromisoformat(newest) + dt.timedelta(days=1)).strftime("%Y%m%d")
    js = call("list.json", corp_code=cache["corp_code"], bgn_de=start, end_de=now.replace("-", ""),
              pblntf_ty="I", page_count=100)
    changed = False
    for item in (js or {}).get("list") or []:
        name = re.sub(r"\s+", "", item.get("report_nm") or "")
        if "잠정" not in name or "실적" not in name or "전망" in name:
            continue
        rcept = item.get("rcept_no")
        if not rcept or rcept in cache["preliminary"]:
            continue
        blob = call("document.xml", binary=True, rcept_no=rcept)
        parsed = None
        if blob:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for n in z.namelist():
                    raw = z.read(n)
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = raw.decode("cp949", errors="replace")
                    parsed = parse_preliminary(text)
                    if parsed:
                        break
        cache["preliminary"][rcept] = {"title": name, "filed": item.get("rcept_dt"), "consolidated": "연결" in name,
                                       **(parsed or {})}
        changed = True
    return changed


# ------------------------------------------------ cache -> periods (pure, tested offline)

def _flows(report):
    """A report's (flows, FY-1 / FY-2 flows, balances), with diluted EPS falling back to basic (= diluted when
    nothing dilutes) and, for separate statements (no minority interests), net income = income after tax and
    equity = total equity."""
    ex = extract(report)
    flows, prior, balances = ex["flows"], ex["annual_prior"], ex["balances"]
    for table in (flows, prior):
        diluted, basic = table.get("eps_diluted") or [None, None], table.get("eps_basic") or [None, None]
        table["eps_diluted"] = [d if d is not None else b for d, b in zip(diluted, basic)]
    if report.get("fs_div") == "OFS":
        flows.setdefault("net_income", flows.get("net_income_after_tax"))
        prior.setdefault("net_income", prior.get("net_income_after_tax"))
        balances.setdefault("equity", balances.get("equity_total"))
    return flows, prior, balances


def periods(cache, currency):
    """The cache -> {"kind": "DART", "quarterly": {field: [("DART", {end: (value, computed)})]}, "annual": {...},
    "balances": {field: [("DART", {end: value})]}} with money in full currency units (the caller scales). {} when
    empty or when the company does not report in `currency`."""
    reports = (cache or {}).get("reports") or {}
    if not reports:
        return {}
    by_year = {}
    for r in reports.values():
        if r.get("currency") and currency and r["currency"] != currency:
            return {}
        by_year.setdefault(r["year"], {})[r["quarter"]] = r
    q, a, b = {}, {}, {}

    def put(table, field, end, value, computed=False):
        if value is not None and end not in table.setdefault(field, {}):
            table[field][end] = (value, computed)

    for year, reps in sorted(by_year.items()):
        for quarter, r in sorted(reps.items()):
            end = r["end"]
            flows, prior, balances = _flows(r)
            if quarter < 4:
                for field in FLOW_FIELDS + PER_SHARE:
                    put(q, field, end, (flows.get(field) or [None, None])[0])
            else:
                for field in FLOW_FIELDS + PER_SHARE:
                    put(a, field, end, (flows.get(field) or [None, None])[0])
                # Q4 = FY - the Q3 report's 9-month cumulative figure (diluted EPS too, as Korean vendors do)
                q3 = reps.get(3)
                if q3 and q3.get("fs_div") == r.get("fs_div"):
                    q3_flows = _flows(q3)[0]
                    for field in FLOW_FIELDS + PER_SHARE:
                        fy = (flows.get(field) or [None, None])[0]
                        nine = (q3_flows.get(field) or [None, None])[1]
                        if fy is not None and nine is not None:
                            put(q, field, end, fy - nine, True)
            for field, vals in balances.items():
                if vals and vals[0] is not None:
                    b.setdefault(field, {})[end] = vals[0]
            shares = (r.get("shares") or {}).get("outstanding")
            if shares:
                b.setdefault("shares", {})[end] = shares
    # older fiscal years from the annual reports' comparative columns (FY-1, FY-2), where no own report was read
    for year, reps in sorted(by_year.items(), reverse=True):
        r = reps.get(4)
        if not r:
            continue
        _, prior, balances = _flows(r)
        for k, end in enumerate((_years_before(r["end"], 1), _years_before(r["end"], 2))):
            for field in FLOW_FIELDS + PER_SHARE:
                vals = prior.get(field) or [None, None]
                put(a, field, end, vals[k])
            for field, vals in balances.items():
                if vals and len(vals) > k + 1 and vals[k + 1] is not None:
                    b.setdefault(field, {}).setdefault(end, vals[k + 1])
    return {"kind": "DART", "fs_div": _main_fs_div(reports),
            "quarterly": {f: [("DART", s)] for f, s in q.items() if s},
            "annual": {f: [("DART", s)] for f, s in a.items() if s},
            "balances": {f: [("DART", s)] for f, s in b.items() if f in ("total_assets", "equity", "shares") and s},
            "cash": _cash_periods(by_year)}


def _cash_periods(by_year):
    """Operating cash flow and capex from the reports' cash-flow statements: {"quarterly": {field: {end: (value,
    computed)}}, "annual": {...}} in full currency units, or {} when no report has them. The statements are
    year-to-date: Q1 is the Q1 report's figure, Q2 = H1 - Q1, Q3 = 9M - H1 and Q4 = FY - 9M (computed=True; both
    reports on the same statement basis); a year is the annual report's figure, older years its comparative
    columns."""
    q, a = {}, {}

    def put(table, field, end, value, computed=False):
        if value is not None and end not in table.setdefault(field, {}):
            table[field][end] = (value, computed)

    for year, reps in sorted(by_year.items()):
        for quarter, r in sorted(reps.items()):
            cash = extract(r)["cash"]
            before = reps.get(quarter - 1)
            cash_before = extract(before)["cash"] if before and before.get("fs_div") == r.get("fs_div") else {}
            for field, (ytd, _, _) in cash.items():
                if ytd is None:
                    continue
                if quarter == 4:
                    put(a, field, r["end"], ytd)
                if quarter == 1:
                    put(q, field, r["end"], ytd)
                elif (cash_before.get(field) or [None])[0] is not None:
                    put(q, field, r["end"], ytd - cash_before[field][0], True)
    for year, reps in sorted(by_year.items(), reverse=True):
        r = reps.get(4)
        if r:
            for field, (_, fy1, fy2) in extract(r)["cash"].items():
                put(a, field, _years_before(r["end"], 1), fy1)
                put(a, field, _years_before(r["end"], 2), fy2)
    if not (q.get("ocf") or a.get("ocf")):
        return {}
    return {"quarterly": {f: s for f, s in q.items() if s}, "annual": {f: s for f, s in a.items() if s}}


def _main_fs_div(reports):
    divs = [r.get("fs_div") for r in reports.values()]
    return "CFS" if divs.count("CFS") >= divs.count("OFS") else "OFS"


def _years_before(end, n):
    d = dt.date.fromisoformat(end)
    try:
        return d.replace(year=d.year - n).isoformat()
    except ValueError:                                 # 29 February
        return d.replace(year=d.year - n, day=28).isoformat()


def preliminary(cache):
    """The newest preliminary results whose quarter has no regular report yet: {"start", "end", "filed", "url",
    "consolidated", "values": {field: full KRW}}; a later filing (e.g. a correction) for the same quarter wins,
    consolidated before separate. None when there is none."""
    items = [dict(v, rcept_no=k) for k, v in ((cache or {}).get("preliminary") or {}).items() if v.get("end")]
    if not items:
        return None
    newest_report = _newest_report_end(cache) or ""
    items = [i for i in items if i["end"] > newest_report]
    if not items:
        return None
    items.sort(key=lambda i: (i["end"], bool(i.get("consolidated")), i["rcept_no"]))
    best = items[-1]
    filed = best.get("filed") or ""
    return {"start": best.get("start"), "end": best["end"], "consolidated": bool(best.get("consolidated")),
            "filed": f"{filed[:4]}-{filed[4:6]}-{filed[6:8]}" if len(filed) == 8 else None,
            "url": DART_VIEW + best["rcept_no"], "values": best.get("values") or {}}
