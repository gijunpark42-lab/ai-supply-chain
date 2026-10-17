"""Financing events of our Korean, Taiwanese and Japanese companies (user, 2026-10-17).

What it records
---------------
Debt, convertible and equity raises, loan / credit-facility deals and credit-rating actions, one row per event,
in the row shape of graph/financing.json (contract 3) plus "company" (the graph node id, so the builder can group):
    {"company", "date", "type", "title", "amount", "currency", "amount_usd", "detail", "form", "market", "source", "url"}
    type in debt | convertible | equity | credit_facility | abs | lease_financing | rating | other

These are NOT signals: nothing here is written into quarterly_data, chains/, patches/ or derive.py. The rows go to
    market/history/financing_kr.jsonl   Korea   — OpenDART (FSS) major-issues reports + debt registration statements
    market/history/financing_tw.jsonl   Taiwan  — MOPS material information (重大訊息) about bonds / CBs / capital increases / loans
    market/history/financing_jp.jsonl   Japan   — TDnet timely disclosures about bonds / loans / ratings / share offerings
and market/financing.py (another collector) builds graph/financing.json from all financing histories.
ADD-only: a row whose url is already in the history is never written again (one url = one filing).

Where each market comes from
----------------------------
Korea (DART_API_KEY in .env):
  list.json pblntf_ty=B (주요사항보고서) and pblntf_ty=C (발행공시) per company. One event = one original filing; its
  [기재정정] / [발행조건확정] corrections are not separate events. The row is dated and linked to the ORIGINAL filing;
  the amount comes from the decision endpoint, which returns one (latest or amended) version of each event:
      유상증자결정 piicDecsn / 유무상증자결정 pifricDecsn -> equity   (amount = the use-of-proceeds total)
      전환사채권 cvbdIsDecsn / 신주인수권부사채권 bdwtIsDecsn / 교환사채권 exbdIsDecsn -> convertible  (face value)
      증권신고서(채무증권) bdRs -> debt   (sum of the tranches' offering amounts)
  Daily: the whole-market feed (list.json without corp_code) for the days since the last run names the companies
  with a new financing filing; only those companies are re-read for 365 days.
Taiwan (no key): mops.py skips financing announcements and records them in mops/sync_state.json ("skip:financing /
  securities | <subject>"): those ids seed the history. The daily path lists MOPS itself through mops.api():
  t05st02 (every company's material information of one day, 1 call per day); --backfill lists t05st01 per
  company for the last 365 days. Only issuance-type subjects are kept (公司債 / 可轉債 / 交換公司債 / 現金增資 / 私募 /
  GDR / 聯貸 / 授信 / 商業本票); guarantees (背書保證), loans to others (資金貸與), employee options, capital
  injections into own subsidiaries, conversion-price resets and admin notices are left out. The amount is read
  from the filing text (t05st01_detail).
Japan (no key): tdnet.py skips financing disclosures and records them in tdnet/sync_state.json ("skip:financing";
  convertible bonds land in "skip:stock compensation" because of 新株予約権): those rows seed the history. The daily
  path re-lists TDnet with tdnet.py's own japanese_day() / english_range() (TDnet keeps only ~31 days online).
  The English version is used when TDnet lists one; the amount is read from the PDF's first pages.

market/history/financing_asia_state.json keeps each market's last run (the next daily run re-reads from 3 days
before it) and the MOPS ids already judged (so mops.py's seeds are not listed again).

amount_usd uses the exchange rate of the filing day (Yahoo Finance daily closes, fetched once per run and kept in
market/history/fx_usd.jsonl so market/financing.py converts older rows the same way; the latest close, or a fixed
fallback rate, only when Yahoo has no close for that day), like the US rows (user, 2026-10-17 verification).
A repayment, redemption or buyback is typed "other" (money going out, not a raise).

Usage (from the repo root):
    python -X utf8 -m market.financing_asia               today's run (days since the last run, at least 7)
    python -X utf8 -m market.financing_asia --backfill    the last 365 days (TDnet: the ~31 days it keeps online)
    python -X utf8 -m market.financing_asia --build-only  rebuild graph/financing.json from history (market.financing)
    add --market KR|TW|JP to run one market only
"""
import argparse
import datetime as dt
import importlib
import importlib.util
import os
import re
import sys
import time

from market.common import ROOT, get, load_env, read_history, append_history, read_json, write_json, today, universe

DATASETS = {"KR": "financing_kr", "TW": "financing_tw", "JP": "financing_jp"}
KEY = ("url",)                                       # one filing = one row
STATE = ROOT / "market" / "history" / "financing_asia_state.json"   # last successful run per market
WINDOW_DAYS = 365
MIN_DAILY_DAYS = 7                                   # a daily run always re-reads at least this many days

# Source names as market/financing.py's SOURCE_HOMES knows them (it links each name to the source's home page).
SOURCES = {
    "KR": ("DART", "https://dart.fss.or.kr/"),            # Korea FSS filings, read through the OpenDART API
    "TW": ("MOPS", "https://mops.twse.com.tw/"),          # Taiwan Market Observation Post System
    "JP": ("TDnet", "https://www.release.tdnet.info/"),   # Tokyo Stock Exchange timely disclosures
}


def scrub(text):
    """Remove API keys from a message: a requests error repeats the whole URL, crtfc_key=<key> included."""
    for name in ("DART_API_KEY", "EDINET_API_KEY"):
        key = (os.getenv(name) or "").strip()
        if key:
            text = text.replace(key, "***")
    return text


def log(msg):
    print(f"[financing_asia] {scrub(str(msg))}", flush=True)


# ---------------------------------------------------------------- shared small helpers

FALLBACK_PER_USD = {"KRW": 1350.0, "TWD": 32.0, "JPY": 150.0, "CNY": 7.1, "EUR": 0.9, "USD": 1.0}
FX_DATASET = "fx_usd"                                # market/history/fx_usd.jsonl: {date, currency, usd, source, url}
FX_KEY = ("date", "currency")
FX_PAIRS = {"KRW": "KRWUSD=X", "TWD": "TWDUSD=X", "JPY": "JPYUSD=X", "CNY": "CNYUSD=X", "EUR": "EURUSD=X"}
_FX = {}                                             # currency -> {date: USD per unit}, filled once per run


def fx_daily():
    """{currency: {YYYY-MM-DD: USD per 1 unit}}: Yahoo Finance daily closes of the last 2 years (one request per
    currency, once per run), appended to market/history/fx_usd.jsonl; the recorded history when Yahoo fails."""
    if _FX:
        return _FX
    rows = []
    try:
        import yfinance as yf
        for cur, pair in FX_PAIRS.items():
            hist = yf.Ticker(pair).history(period="2y", interval="1d")
            for day, close in hist["Close"].items():
                if close and close == close:                 # skip NaN
                    rows.append({"date": day.date().isoformat(), "currency": cur, "usd": round(float(close), 10),
                                 "source": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{pair}"})
        append_history(FX_DATASET, rows, FX_KEY)
    except Exception as e:                                   # FX is a convenience; never fail the run on it
        log(f"warning: FX rates unavailable ({e.__class__.__name__}); using the recorded rates")
    for r in read_history(FX_DATASET):
        _FX.setdefault(r["currency"], {})[r["date"]] = float(r["usd"])
    _FX.setdefault("USD", {})
    return _FX


def to_usd(amount, currency, date=None):
    """amount in USD at the close of `date` (or of the last trading day before it); the latest close, else a fixed
    fallback rate, when that day is not known."""
    if amount is None or not currency:
        return None
    if currency == "USD":
        return round(amount)
    closes = fx_daily().get(currency) or {}
    days = sorted(d for d in closes if not date or d <= date)
    if days:
        return round(amount * closes[days[-1]])
    if closes:
        return round(amount * closes[max(closes)])
    rate = FALLBACK_PER_USD.get(currency)
    return round(amount / rate) if rate else None


def fmt_amount(amount, currency):
    """1.2e12, 'KRW' -> 'KRW 1.2T'; 7e11 -> 'KRW 700B'."""
    if amount is None:
        return ""
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if amount >= div * 0.9995:                      # 999.99M rounds up to '1B', not '1,000M'
            v = amount / div
            return f"{currency} {v:.3g}{unit}" if v < 100 else f"{currency} {v:,.0f}{unit}"
    return f"{currency} {amount:,.0f}"


def number(s):
    """'40,023,070,290,000' -> 40023070290000.0; '-' or '' -> None."""
    s = str(s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


REPAYMENT = re.compile(r"\b(?:re|pre)payments?\b|\bredemptions?\b|\bredeem\w*|\brepurchas\w*|\bbuy-?backs?\b",
                       re.I)


def make_row(company, market, date, type_, title, amount, currency, detail, form, url):
    source_name = SOURCES[market][0]
    if REPAYMENT.search(title or ""):
        type_ = "other"                                      # a repayment / redemption: cash going out
    return {"company": company, "date": date, "type": type_, "title": title,
            "amount": round(amount) if amount is not None else None,
            "currency": currency if amount is not None else None,
            "amount_usd": to_usd(amount, currency, date), "detail": detail, "form": form, "market": market,
            "source": source_name, "url": url}


def history_urls(market):
    return {r.get("url") for r in read_history(DATASETS[market])}


def window_start(market, backfill, state):
    """First day to read: 365 days back on --backfill or a first run, else the last run minus 3 days (>= 7 days)."""
    now = dt.date.fromisoformat(today())
    floor = now - dt.timedelta(days=WINDOW_DAYS)
    last = (state.get(market) or {}).get("last_run")
    if backfill or not last:
        return floor
    start = min(dt.date.fromisoformat(last) - dt.timedelta(days=3), now - dt.timedelta(days=MIN_DAILY_DAYS))
    return max(start, floor)


# ================================================================ Korea: OpenDART

DART_API = "https://opendart.fss.or.kr/api/"
DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
CORP_CODES = ROOT / "dart" / "corp_codes.json"           # written by dart.py corp (read only here)

# report_nm pattern -> (kind, decision endpoint). The first match wins (유무상 before 유상).
KR_KINDS = [
    (r"유무상증자결정", "equity", "pifricDecsn"),
    (r"유상증자결정", "equity", "piicDecsn"),
    (r"전환사채권발행결정", "cb", "cvbdIsDecsn"),
    (r"신주인수권부사채권발행결정", "bw", "bdwtIsDecsn"),
    (r"교환사채권발행결정", "eb", "exbdIsDecsn"),
    (r"증권신고서\(채무증권\)", "bond", "bdRs"),
    (r"일괄신고추가서류\(채무증권\)", "shelf_bond", None),     # shelf drawdown: no structured endpoint, amount unknown
]
KR_TYPE = {"equity": "equity", "cb": "convertible", "bw": "convertible", "eb": "convertible",
           "bond": "debt", "shelf_bond": "debt"}
KR_NAME = {"cb": "Convertible bond (전환사채)", "bw": "Bond with warrants (신주인수권부사채)",
           "eb": "Exchangeable bond (교환사채)", "bond": "Corporate bond offering (회사채)",
           "shelf_bond": "Corporate bond offering, shelf drawdown (회사채 일괄신고)"}
KR_FORM = {"B": "DART major-issues report (주요사항보고서)", "C": "DART securities registration (증권신고서 / 발행공시)"}
EQUITY_METHOD = [(r"주주배정후\s*실권주\s*일반공모", "Rights offering with public offer of unsubscribed shares"),
                 (r"주주배정", "Rights offering"), (r"제3자배정", "Third-party allotment"),
                 (r"일반공모", "Public offering")]
PROCEEDS = {"fclt": "facilities", "bsninh": "business acquisition", "op": "operating funds",
            "dtrp": "debt repayment", "ocsa": "acquisition of other companies' securities", "etc": "other"}

_dart_last = [0.0]


def dart(endpoint, **params):
    """One OpenDART call (JSON), at most ~2 per second. Returns the parsed body; status 013 (= no data) -> None."""
    wait = 0.5 - (time.time() - _dart_last[0])
    if wait > 0:
        time.sleep(wait)
    _dart_last[0] = time.time()
    r = get(DART_API + endpoint + ".json", params={"crtfc_key": os.getenv("DART_API_KEY"), **params}, timeout=60)
    js = r.json()
    status = js.get("status")
    if status == "000":
        return js
    if status == "013":
        return None
    raise RuntimeError(f"OpenDART {endpoint}: status {status} {js.get('message')}")


def kr_companies():
    """{corp_code: node id} for our Korean listed companies (6-digit KRX code in the graph's ticker)."""
    codes = read_json(CORP_CODES, {}) or {}
    out = {}
    for node, info in universe().items():
        if info.get("country") != "KR" and info.get("exchange") not in ("KRX", "KOSPI", "KOSDAQ"):
            continue
        stock = str(info.get("ticker") or "").split(".")[0].strip().zfill(6)
        if re.fullmatch(r"\d{6}", stock) and stock in codes:
            out.setdefault(codes[stock]["corp_code"], node)
    return out


def kr_kind(report_nm):
    for pat, kind, endpoint in KR_KINDS:
        if re.search(pat, report_nm):
            return kind, endpoint
    return None, None


def dart_list(corp_code, start, end, pblntf_ty):
    rows, page = [], 1
    while True:
        params = {"bgn_de": start.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"), "pblntf_ty": pblntf_ty,
                  "page_no": page, "page_count": 100}
        if corp_code:
            params["corp_code"] = corp_code
        js = dart("list", **params)
        if not js:
            break
        rows += js.get("list", [])
        if page >= int(js.get("total_page") or 1):
            break
        page += 1
    return rows


def kr_events(filings, records):
    """Pair each event's ORIGINAL filing with the decision endpoint's record of it.

    One event = one original filing (no "[...]" prefix); its corrections ([기재정정], [발행조건확정], …) are separate
    filings that do not say which original they correct. The decision endpoint returns ONE record per event, keyed
    by the rcept_no of whichever version it holds (the original, or a correction). So:
      1. an original whose own rcept_no is a record -> that record;
      2. the remaining records of the same kind (corrections) go, oldest first, to the remaining originals that
         DART marks as corrected later (rm contains 정) and that were filed before the record.
    Returns [(original filing, record or None, record rcept_no or None)], oldest first."""
    originals = sorted((f for f in filings if not f["report_nm"].startswith("[")), key=lambda f: f["rcept_no"])
    events, used = [], set()
    for f in originals:
        if f["rcept_no"] in records and records[f["rcept_no"]][0] == f["kind"]:
            events.append([f, records[f["rcept_no"]][1], f["rcept_no"]])
            used.add(f["rcept_no"])
        else:
            events.append([f, None, None])
    leftover = sorted(no for no in records if no not in used)
    for ev in events:
        f = ev[0]
        if ev[1] is not None or "정" not in (f.get("rm") or ""):
            continue
        no = next((n for n in leftover if records[n][0] == f["kind"] and n > f["rcept_no"]), None)
        if no:
            leftover.remove(no)
            ev[1], ev[2] = records[no][1], no
    return events


def ymd(s):
    """'20260624' or '2026년 06월 24일' -> '2026-06-24' (else the text as given, '' for '-')."""
    s = str(s or "").strip()
    m = re.match(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return "" if s in ("-", "") else s


def kr_equity(rec):
    """Use-of-proceeds total (KRW) and the English method / detail of a 유상증자 decision."""
    parts, total = [], 0.0
    for key, value in rec.items():
        if "fdpp_" in key:
            n = number(value)
            if n:
                total += n
                parts.append(f"{PROCEEDS.get(key.split('fdpp_')[-1], 'other')} {fmt_amount(n, 'KRW')}")
    method_kr = rec.get("ic_mthn") or rec.get("piic_ic_mthn") or ""
    method = next((en for pat, en in EQUITY_METHOD if re.search(pat, method_kr)), "Capital increase")
    shares = rec.get("nstk_ostk_cnt") or rec.get("piic_nstk_ostk_cnt")
    bits = [f"{method} ({method_kr})" if method_kr else method]
    if number(shares):
        bits.append(f"{shares} new common shares")
    if parts:
        bits.append("use of proceeds: " + ", ".join(parts))
    return (total or None), method, "; ".join(bits)


def kr_bond(rec, kind):
    """Face value and detail of a CB / BW / EB decision."""
    amount, currency = number(rec.get("bd_fta")), "KRW"
    if not amount and number(rec.get("ovis_fta")):
        raw = (rec.get("ovis_fta_crn") or "").strip()
        currency = raw.upper() if re.fullmatch(r"[A-Za-z]{3}", raw) else next(
            (code for word, code in (("달러", "USD"), ("미화", "USD"), ("유로", "EUR"), ("엔", "JPY"), ("위안", "CNY"))
             if word in raw), "USD")
        amount = number(rec.get("ovis_fta"))
    bits = []
    if rec.get("bdis_mthn") and rec["bdis_mthn"] != "-":
        bits.append({"사모": "private placement", "공모": "public offering"}.get(rec["bdis_mthn"].strip(),
                                                                              rec["bdis_mthn"].strip()))
    if rec.get("bd_intr_ex") not in (None, "", "-") or rec.get("bd_intr_sf") not in (None, "", "-"):
        bits.append(f"coupon {rec.get('bd_intr_ex', '-')}% / yield to maturity {rec.get('bd_intr_sf', '-')}%")
    price = rec.get("cv_prc") if kind == "cb" else rec.get("ex_prc")
    if number(price):
        bits.append(f"{'conversion' if kind == 'cb' else 'exercise' if kind == 'bw' else 'exchange'} price KRW {price}")
    if kind == "eb" and rec.get("extg") not in (None, "", "-"):
        own = "자기주식" in rec["extg"] or re.sub(r"주식회사|\(주\)|\s", "", rec.get("corp_name") or "-") in rec["extg"]
        bits.append("exchangeable into the company's own (treasury) shares" if own
                    else "exchangeable into shares of another company held by the issuer")
    if ymd(rec.get("bd_mtd")):
        bits.append(f"maturity {ymd(rec.get('bd_mtd'))}")
    if ymd(rec.get("pymd")):
        bits.append(f"payment {ymd(rec.get('pymd'))}")
    return amount, currency, "; ".join(bits)


def kr_debt(tranches):
    """Sum and detail of the tranches of one 증권신고서(채무증권) (bdRs 일반사항 rows of one rcept_no)."""
    total = sum(number(t.get("slta")) or number(t.get("fta")) or 0 for t in tranches)
    maturities = sorted({ymd(t.get("rpd")) for t in tranches if ymd(t.get("rpd"))})
    first = tranches[0]
    bits = [f"{len(tranches)} tranche{'s' if len(tranches) > 1 else ''}"
            + (f" (series {', '.join(t.get('tm', '') for t in tranches)})" if first.get("tm") else "")]
    if first.get("slmth") and first["slmth"] != "-":
        bits.append({"공모": "public offering", "사모": "private placement"}.get(first["slmth"], first["slmth"]))
    if maturities:
        bits.append("maturity " + ", ".join(maturities))
    if ymd(first.get("pymd")):
        bits.append(f"payment {ymd(first.get('pymd'))}")
    return (total or None), "; ".join(bits)


def kr_company_rows(corp, node, start, end):
    """Every financing event of one company filed between start and end."""
    filings, overseas = [], []
    for ty in ("B", "C"):
        for f in dart_list(corp, start, end, ty):
            kind, endpoint = kr_kind(f["report_nm"])
            if kind:
                filings.append({**f, "kind": kind, "endpoint": endpoint, "ty": ty})
            elif "해외증권시장주권등상장" in f["report_nm"] and not f["report_nm"].startswith("["):
                overseas.append(ymd(f["rcept_dt"]))           # 해외증권시장주권등상장결정: an overseas (DR) listing
    if not filings:
        return []
    # The decision endpoint answers with one record per event (its latest or an amended version), keyed by rcept_no.
    records = {}                                        # rcept_no -> (kind, record); a bond record = its tranches
    for kind, endpoint in sorted({(f["kind"], f["endpoint"]) for f in filings if f["endpoint"]}):
        js = dart(endpoint, corp_code=corp, bgn_de=start.strftime("%Y%m%d"), end_de=end.strftime("%Y%m%d"))
        if not js:
            continue
        if endpoint == "bdRs":                               # grouped answer: 일반사항 = one row per tranche
            for group in js.get("group", []):
                if group.get("title") == "일반사항":
                    for t in group.get("list", []):
                        records.setdefault(t["rcept_no"], (kind, []))[1].append(t)
        else:
            for rec in js.get("list", []):
                records[rec["rcept_no"]] = (kind, rec)
    rows = []
    for first, rec, rec_no in kr_events(filings, records):
        if "철" in (first.get("rm") or ""):
            continue                                         # withdrawn (철회): not an event
        kind = first["kind"]
        amount, currency, detail = None, "KRW", ""
        if kind == "equity":
            method = "Capital increase"
            if rec:
                amount, method, detail = kr_equity(rec)
            title = f"{method} (유상증자)"
            listed = [d for d in overseas if abs((dt.date.fromisoformat(d)
                                                  - dt.date.fromisoformat(ymd(first["rcept_dt"]))).days) <= 5]
            if method == "Third-party allotment" and listed:
                # the "third party" is the depositary bank of a depositary-receipt offering abroad (SK Hynix's
                # US ADR offering and Nasdaq listing, 2026-06-24: the new shares go to Citibank as depositary)
                title = "New shares for an overseas depositary receipt offering and listing (유상증자)"
                detail = (detail + "; " if detail else "") + \
                    f"overseas listing decision (해외증권시장주권등상장결정) filed {listed[0]}"
        elif kind in ("cb", "bw", "eb"):
            if rec:
                amount, currency, detail = kr_bond(rec, kind)
            series = re.sub(r"\D", "", str((rec or {}).get("bd_tm") or ""))
            title = KR_NAME[kind].replace(")", f", No. {series})") if series else KR_NAME[kind]
        else:
            if rec:
                amount, detail = kr_debt(rec)
            title = KR_NAME[kind]
        if amount:
            title += f" {fmt_amount(amount, currency)}"
        if rec_no and rec_no != first["rcept_no"]:
            detail = (detail + "; " if detail else "") + f"terms as amended on {ymd(rec_no[:8])}"
        elif "정" in (first.get("rm") or ""):
            detail = (detail + "; " if detail else "") + "amended later (see the filing)"
        rows.append(make_row(node, "KR", ymd(first["rcept_dt"]), KR_TYPE[kind], title, amount, currency,
                             detail, KR_FORM[first["ty"]], DART_VIEW + first["rcept_no"]))
    return rows


def run_kr(backfill, state):
    if not os.getenv("DART_API_KEY"):
        raise RuntimeError("DART_API_KEY missing in .env")
    ours = kr_companies()
    end = dt.date.fromisoformat(today())
    floor = end - dt.timedelta(days=WINDOW_DAYS)
    start = window_start("KR", backfill, state)
    if start <= end - dt.timedelta(days=89):                # the market-wide feed is capped at 3 months
        targets = sorted(ours)
        log(f"KR: reading {len(targets)} companies, {floor} .. {end}")
    else:
        hits = set()
        for ty in ("B", "C"):
            for f in dart_list(None, start, end, ty):
                if f.get("corp_code") in ours and kr_kind(f["report_nm"])[0]:
                    hits.add(f["corp_code"])
        targets = sorted(hits)
        log(f"KR: market feed {start} .. {end} -> {len(targets)} of our companies with a financing filing")
    rows, failed = [], 0
    for corp in targets:
        try:
            rows += kr_company_rows(corp, ours[corp], floor, end)
        except RuntimeError as e:
            if "status 020" in str(e):                    # daily request limit: stop, keep what we have
                log(f"KR: OpenDART request limit reached ({e}); stopping")
                failed += 1
                break
            log(f"KR: {ours[corp]} failed ({e})")
            failed += 1
        except Exception as e:
            log(f"KR: {ours[corp]} failed ({e.__class__.__name__}: {str(e)[:120]})")
            failed += 1
    if targets and failed == len(targets):
        raise RuntimeError("every Korean company failed")
    return rows


# ================================================================ Taiwan: MOPS

MOPS_VIEW = ("https://mopsov.twse.com.tw/mops/web/ajax_t05st01?step=2&colorchg=1&co_id={code}&TYPEK={kind}&off=1"
             "&firstin=1&year={roc}&month={mm}&spoke_date={ymd}&spoke_time={hms}&seq_no={serial}")
MOPS_STATE = ROOT / "mops" / "sync_state.json"
# Our Taiwanese companies that the graph lists by their US ticker (ADR): their TWSE code, so MOPS can be read.
TW_LOCAL_CODE = {"TSMC": "2330", "UMC": "2303", "ASE Group": "3711", "ChipMOS": "8150"}

TW_LEAVE_OUT = (r"背書保證|資金貸與|員工認股|認股權憑證|限制員工權利新股|註銷|注意交易資訊|轉換價格|轉換價額|轉換價|代收價款|"
                r"存儲專戶|收足|收齊|募足|間接以現金增資|現金增資子公司|增資子公司|對子公司.{0,12}增資|減資|終止.{0,6}買賣|"
                r"終止上櫃|下櫃|轉換.{0,6}普通股|行使|股務|更正|澄清|媒體|股利|庫藏股|到期還本|到期償還|到期贖回|還本付息|"
                r"催繳|認股率|備案|參與認購|認購.{0,30}(公司債|債券|票券)|(取得|處分|買賣|投資).{0,40}?(債券|公司債|有價證券|票券)|基金|"
                r"除息|除權|停止轉換|停止受理轉|資金運用計畫|延長.{0,12}(募集|繳款)|展延|全數轉換|轉換完畢|放棄認購|"
                r"參與[^發]{0,30}增資|(取得|處分|投資).{0,40}?可轉債")
# ... unless the subject is the pricing of a new issue or an early redemption (both are financing events)
TW_RESCUE = r"定價|訂價|贖回權|提前贖回|提前償還"
# (type, pattern) — first match wins; convertible before debt (轉換公司債 contains 公司債)
TW_TYPES = [
    ("convertible", r"可轉換|轉換公司債|可轉債|交換公司債|附認股權.{0,4}公司債"),
    ("debt", r"公司債|發行.{0,12}債券|商業本票|票券|中期票據|(?<![A-Za-z])MTN(?![A-Za-z])"),
    ("credit_facility", r"聯貸|聯合授信|授信|融資額度|借款|貸款|銀行額度"),
    ("equity", r"現金增資|私募|存託憑證|GDR|發行新股"),
]
TW_INSTRUMENT = [
    (r"海外.{0,8}無擔保.{0,4}轉換公司債", "Overseas unsecured convertible bonds"),
    (r"海外.{0,8}轉換公司債", "Overseas convertible bonds"),
    (r"國內.{0,8}無擔保.{0,4}轉換公司債", "Domestic unsecured convertible bonds"),
    (r"國內.{0,8}有擔保.{0,4}轉換公司債", "Domestic secured convertible bonds"),
    (r"交換公司債", "Exchangeable bonds"),
    (r"可轉換|轉換公司債|可轉債", "Convertible bonds"),
    (r"綠色.{0,6}(公司債|債券)", "Green bonds"),
    (r"永續.{0,6}(公司債|債券)", "Sustainability bonds"),
    (r"無擔保普通公司債|無擔保.{0,4}公司債", "Unsecured straight bonds"),
    (r"有擔保普通公司債|有擔保.{0,4}公司債", "Secured straight bonds"),
    (r"普通公司債", "Straight bonds"),
    (r"公司債|債券|(?<![A-Za-z])MTN(?![A-Za-z])|中期票據", "Corporate bonds"),
    (r"商業本票|票券", "Commercial paper"),
    (r"聯貸|聯合授信", "Syndicated loan"),
    (r"授信|融資額度|借款|貸款|銀行額度", "Credit facility"),
    (r"存託憑證|GDR", "Cash capital increase via global depositary receipts"),
    (r"私募.{0,10}(普通股|股票|新股)", "Private placement of common shares"),
    (r"私募", "Private placement"),
    (r"現金增資", "Cash capital increase"),
    (r"發行新股", "New share issue"),
]
TW_STAGE = [
    (r"撤銷|撤回", "withdrawn"), (r"定價|訂價", "pricing completed"), (r"主要發行條件|發行條件|發行辦法", "main terms"),
    (r"申報生效|生效", "registration effective"), (r"認股基準日|增資基準日", "subscription record date"), (r"董事會.{0,8}(決議|通過)|決議", "board approval"),
    (r"簽(訂|署)", "agreement signed"), (r"贖回權|提前贖回|提前償還", "early redemption"),
    (r"到期|贖回|償還|清償", "redemption / repayment"), (r"發行|辦理", "issue"),
]
ZH_DIGIT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
TW_CUR = {"NT": "TWD", "US": "USD", "CN": "CNY", "JP": "JPY", "EU": "EUR", "TH": "THB", "VN": "VND", "MX": "MXN",
          "IN": "INR"}
# A filing written on the asset-acquisition template (subject of the deal, units, unit price, total) is the company
# buying someone else's shares / bonds / private placement — an investment, not the company raising money.
TW_INVESTMENT_TEMPLATE = r"標的物之名稱及性質|交易單位數量|交易數量、每單位價格"
TW_AMOUNT_KEY = r"發行總額|發行總金額|總發行金額|募集總金額|募集總額|私募總金額|預計募集|發行金額|總額度|授信額度|聯貸額度|融資額度|額度|總金額"


def tw_companies():
    """{TWSE / TPEx code: node id} — mops.py's Taiwanese companies plus the ADR-listed ones."""
    import mops
    nodes = universe()
    out = {code: name for code, name in mops.universe().items() if name in nodes}
    for name, code in TW_LOCAL_CODE.items():
        if name in nodes:
            out[code] = name
    return out


def tw_classify(subject):
    """The financing type of a MOPS subject, or None (not an issuance-type financing event)."""
    s = re.sub(r"\s+", "", subject)
    if re.search(TW_LEAVE_OUT, s) and not re.search(TW_RESCUE, s):
        return None
    for type_, pat in TW_TYPES:
        if re.search(pat, s):
            # a capital increase by / into a subsidiary is an intra-group transfer, not the company raising money
            if type_ == "equity" and re.search(r"子公司", s):
                return None
            return type_
    return None


def tw_number(s):
    """'第三' -> 3, '第3' -> 3."""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in ZH_DIGIT:
        return ZH_DIGIT[s]
    if len(s) == 2 and s[0] == "十" and s[1] in ZH_DIGIT:
        return 10 + ZH_DIGIT[s[1]]
    if len(s) >= 2 and s[0] in ZH_DIGIT and s[1] == "十":
        return ZH_DIGIT[s[0]] * 10 + (ZH_DIGIT.get(s[2], 0) if len(s) > 2 else 0)
    return None


def tw_amount(subject, body):
    """(amount, currency) of the issue / facility, from a labelled amount in the text, else from the subject."""
    import mops

    def first_amount(text):
        best = None
        for m in mops.AMOUNT.finditer(text):                  # '新台幣 30 億元' (currency first)
            cur = next(c for p, c in mops.CURRENCY if re.fullmatch(p, m.group(1), re.I))
            n = number(m.group(2))
            unit = m.group(3) or ""
            if n:
                best = (m.start(), n * mops.UNIT.get(unit.lower() if unit.isascii() else unit, 1), TW_CUR[cur])
                break
        for m in mops.AMOUNT_POST.finditer(text):             # '30億元新台幣' / '日圓1,019億元' handled above
            cur = next(c for p, c in mops.CURRENCY if re.fullmatch(p, m.group(3), re.I))
            n = number(m.group(1))
            if n and (best is None or m.start() < best[0]):
                best = (m.start(), n * mops.UNIT.get(m.group(2) or "", 1), TW_CUR[cur])
            break
        return (best[1], best[2]) if best else (None, None)

    flat = re.sub(r"\s+", "", body or "")
    for m in re.finditer(TW_AMOUNT_KEY, flat):
        amount, cur = first_amount(flat[m.end(): m.end() + 80])
        if amount and amount >= 1e6:
            return amount, cur
    amount, cur = first_amount(re.sub(r"\s+", "", subject))
    return (amount, cur) if amount and amount >= 1e6 else (None, None)


def tw_title(subject, amount, currency):
    s = re.sub(r"\s+", "", subject)
    instrument = next((en for pat, en in TW_INSTRUMENT if re.search(pat, s)), "Financing")
    bits = []
    m = re.search(r"(\d{3})年(度)?(?!\d{1,2}月)", s)          # '115年度' = 2026, not a date '115年11月'
    if m and 100 <= int(m.group(1)) <= 130:
        bits.append(str(int(m.group(1)) + 1911))
    m = re.search(r"第([0-9一二三四五六七八九十]{1,3})(次|期)", s)
    if m and tw_number(m.group(1)):
        bits.append(f"{'No.' if m.group(2) == '次' else 'tranche'} {tw_number(m.group(1))}")
    title = instrument + (f" ({', '.join(bits)})" if bits else "")
    stage = next((en for pat, en in TW_STAGE if re.search(pat, s)), None)
    if stage:
        title += f": {stage}"
    if amount:
        title += f", {fmt_amount(amount, currency)}"
    sub = re.search(r"代(重要)?子公司\s*([A-Za-z0-9][A-Za-z0-9 .,&()\-]+?)\s*(公告|之|辦理|發行|$)", subject)
    if sub:
        title += f" (subsidiary {sub.group(2).strip(' ,.')})"
    elif "子公司" in s:
        title += " (subsidiary)"
    return title


def tw_tranches(flat):
    """Per-tranche terms of a multi-tranche bond notice, whose fields list each tranche in turn
    ('甲類發行金額為新台幣140億元整、乙類發行金額為新台幣45億元整 ... 甲類發行期限為5年期、乙類 ... 10年期 ...
    甲類固定年利率2.03%、乙類固定年利率2.10%') -> ['A: TWD 14B 5y 2.03%', 'B: TWD 4.5B 10y 2.10%'];
    [] when the notice has one tranche (user, 2026-10-17 verification: TSMC's 2026 tranche 3 green bonds)."""
    import mops
    letters = []
    for m in re.finditer(r"([甲乙丙丁戊己])(?:種|類|券|期)", flat):
        if m.group(1) not in letters:
            letters.append(m.group(1))
    if len(letters) < 2:
        return []
    out = []
    for letter in letters:
        def near(pattern):
            """The first '<letter>類 ... <value>' with no field separator in between."""
            gap = r"(?:(?![甲乙丙丁戊己](?:種|類|券|期)|\d+\.\D)[^、，,；;。]){0,25}?"   # stop at the next tranche / field
            return next(re.finditer(letter + r"(?:種|類|券|期)" + gap + pattern, flat), None)
        bits = []
        a = near(mops.AMOUNT.pattern)
        if a and number(a.group(2)):
            cur = next(c for p, c in mops.CURRENCY if re.fullmatch(p, a.group(1), re.I))
            unit = a.group(3) or ""
            bits.append(fmt_amount(number(a.group(2)) * mops.UNIT.get(unit.lower() if unit.isascii() else unit, 1),
                                   TW_CUR[cur]))
        y = near(r"(?<![0-9.])([0-9]{1,2})\s*年(?![0-9]{1,2}月|度)")
        if y:
            bits.append(f"{y.group(1)}y")
        c = near(r"([0-9]+(?:\.[0-9]+)?)\s*%")
        if c:
            bits.append(f"{c.group(1)}%")
        if len(bits) >= 2:
            out.append(f"{'ABCDEF'['甲乙丙丁戊己'.index(letter)]}: " + " ".join(bits))
    return out if len(out) >= 2 else []


def tw_detail(item_time, clause, body):
    flat = re.sub(r"\s+", "", body or "")
    bits = []
    tranches = tw_tranches(flat)
    if tranches:
        bits.append("; ".join(tranches))
    m = None if tranches else re.search(r"(票面)?利率[^0-9%]{0,12}([0-9]+(?:\.[0-9]+)?)\s*%", flat)
    if m:
        bits.append(f"coupon {m.group(2)}%")
    m = None if tranches else re.search(
        r"(發行期間|期間|年期|期限)[^0-9]{0,6}(?<![0-9])([0-9]{1,2}(?:\.[0-9]+)?|[一二三四五六七八九十]{1,2})年(?![0-9]{1,2}月|度)", flat)
    if m:
        years = m.group(2) if m.group(2)[0].isdigit() else tw_number(m.group(2))
        if years:
            bits.append(f"tenor {years} years")
    if clause:
        bits.append(f"MOPS material information, clause {re.sub(r'[^0-9]', '', clause) or clause}")
    if item_time:
        bits.append(f"filed {item_time} Taiwan time")
    return "; ".join(bits)


def tw_seed_ids():
    """Material-information ids that mops.py skipped as financing (mops/sync_state.json): {'2317-20260904-1': subject}."""
    seen = (read_json(MOPS_STATE, {}) or {}).get("seen", {})
    out = {}
    for key, status in seen.items():
        if key.startswith("mi:") and "financing" in status:
            out[key[3:]] = status.split(" | ", 1)[-1] if " | " in status else ""
    return out


def tw_listing_backfill(codes, start, end):
    """t05st01 per company and ROC year (mops.py's own listing call) -> list items in [start, end].
    Raises when every request failed (MOPS down: the market is logged as failed and its state is not moved)."""
    import mops
    items, tried, failed = [], 0, 0
    for code in sorted(codes):
        for year in range(start.year, end.year + 1):
            tried += 1
            try:
                res = mops.api("t05st01", {"companyId": code, "year": str(year - 1911), "month": "all",
                                           "firstDay": "", "lastDay": ""})
            except Exception as e:
                failed += 1
                log(f"TW: listing {codes[code]} {year} failed ({e.__class__.__name__}: {str(e)[:80]})")
                continue
            items += (res or {}).get("data", [])
    if tried and failed == tried:
        raise RuntimeError(f"every MOPS listing request failed ({failed})")
    return items


def tw_listing_days(days, required=True):
    """t05st02 (every company's material information of one day) for each day. With `required`, raises when
    every day failed (MOPS down: the market is logged as failed and its last_run is not moved)."""
    import mops
    items, failed = [], 0
    for day in days:
        try:
            res = mops.api("t05st02", {"year": str(day.year - 1911), "month": f"{day.month:02d}",
                                       "day": f"{day.day:02d}"})
        except Exception as e:
            failed += 1
            log(f"TW: day list {day} failed ({e.__class__.__name__}: {str(e)[:80]})")
            if required and failed == len(days):
                raise RuntimeError(f"every MOPS day list failed ({failed} days)")
            continue
        for x in (res or {}).get("data", []):
            # t05st02 rows: [date, time, code, name, subject, link]; t05st01 rows: [code, name, date, time, subject, link]
            items.append([x[2], x[3], x[0], x[1], x[4], x[5]])
    return items


def run_tw(backfill, state):
    import mops
    ours = tw_companies()
    end = dt.date.fromisoformat(today())
    floor = end - dt.timedelta(days=WINDOW_DAYS)
    start = window_start("TW", backfill, state)
    have = history_urls("TW")
    # MOPS ids (company-entry date-serial, as mops.py keys them) this collector has already judged: the seeds
    # from mops/sync_state.json are checked against them (the filing URL uses the speaking date, not the entry date)
    handled = set((state.get("TW") or {}).get("handled_ids", []))
    seeds = {k: v for k, v in tw_seed_ids().items() if k not in handled}
    if start <= end - dt.timedelta(days=31):
        log(f"TW: listing {len(ours)} companies (t05st01), {start} .. {end}")
        items = tw_listing_backfill(ours, start, end)
    else:
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        log(f"TW: listing every company's material information for {len(days)} days (t05st02), {start} .. {end}")
        items = tw_listing_days(days)
    # mops.py seeds that this listing did not cover (an older day): list those days too (at most 31)
    listed = set()
    for it in items:
        p = it[5].get("parameters", {}) if isinstance(it[5], dict) else {}
        if p:
            listed.add(mops.material_id(p))
    missing_days = sorted({dt.date(int(k.split("-")[1][:4]), int(k.split("-")[1][4:6]), int(k.split("-")[1][6:]))
                           for k in seeds if k not in listed and k.split("-")[0] in ours})
    missing_days = [d for d in missing_days if d >= floor][-31:]          # the most recent 31
    if missing_days:
        log(f"TW: {len(missing_days)} more days listed for mops.py's financing skips")
        items += tw_listing_days(missing_days, required=False)
    rows, done = [], set()
    for it in items:
        code, _name, day_s, hms, subject, link = it[:6]
        p = link.get("parameters", {}) if isinstance(link, dict) else {}
        day = mops.roc_date(day_s) if day_s else None
        if code not in ours or not p or not day or day < floor:
            continue
        mid = mops.material_id(p)
        if mid in done:
            continue
        done.add(mid)
        type_ = tw_classify(subject)
        if not type_:
            if mid in seeds:
                handled.add(mid)
            continue
        url = MOPS_VIEW.format(code=code, kind=p.get("marketKind", "sii"), roc=day.year - 1911, mm=f"{day.month:02d}",
                               ymd=day.strftime("%Y%m%d"), hms=hms.replace(":", ""), serial=p.get("serialNumber"))
        handled.add(mid)
        if url in have:
            continue
        body, clause = "", ""
        try:
            detail = mops.api("t05st01_detail", p)
            if detail and detail.get("data"):
                d = detail["data"][0]
                clause, body = d[7].strip(), d[9]
        except Exception as e:
            log(f"TW: detail {mid} failed ({e.__class__.__name__}); recorded without amount")
        if re.search(TW_INVESTMENT_TEMPLATE, re.sub(r"\s+", "", body)):
            continue
        amount, currency = tw_amount(subject, body)
        rows.append(make_row(ours[code], "TW", day.isoformat(), type_, tw_title(subject, amount, currency),
                             amount, currency, tw_detail(hms, clause, body),
                             "MOPS material information (重大訊息)", url))
    keep_from = (floor - dt.timedelta(days=30)).strftime("%Y%m%d")      # ids older than the window are not needed
    state.setdefault("TW", {})["handled_ids"] = sorted(m for m in handled if m.split("-")[1] >= keep_from)
    return rows


# ================================================================ Japan: TDnet

TDNET_STATE = ROOT / "tdnet" / "sync_state.json"
JP_LEAVE_OUT = (r"訂正|correction|amendment|自己株式|treasury|own shares|buy-?back|ストック・?オプション|stock options?|"
                r"譲渡制限付株式|restricted (stock|share)|株式報酬|株式給付|業績連動|貸付|loans? to (its |a |our )?"
                r"(subsidiar|affiliat)|債務保証|guarantee|配当|dividend|行使|exercise|転換価額|conversion price|"
                r"株式分割|stock split|上場|listing|減損|impairment")
JP_TYPES = [
    ("rating", r"格付|credit rating|\bratings?\b"),
    ("convertible", r"転換社債|新株予約権付社債|convertible|exchangeable"),
    ("debt", r"社債|債券|コマーシャル・?ペーパー|\bbonds?\b|\bnotes\b|commercial paper|debentures?"),
    ("credit_facility", r"コミットメントライン|シンジケート|ブリッジローン|ローン|借入|(?<!金)融資|commitment line|syndicat|"
                        r"bridge (loan|facilit)|\bloans?\b|borrowing|credit facilit|facility agreement"),
    ("equity", r"第三者割当|新株式|募集株式|公募|増資|株式の売出し|売出し|third[- ]party allotment|issuance of (new )?shares|"
               r"share offering|public offering|secondary offering|capital increase|global offering"),
    ("abs", r"証券化|流動化|securiti[sz]ation|asset[- ]backed"),
    ("other", r"資金調達|fund[- ]?raising|capital raising"),
]
JP_INSTRUMENT = [
    (r"転換社債型新株予約権付社債", "Convertible bonds"), (r"(外貨建|米ドル建|ユーロ建).{0,8}社債", "Foreign-currency bonds"),
    (r"劣後|ハイブリッド", "Subordinated (hybrid) bonds"), (r"グリーン.{0,6}(ボンド|社債)", "Green bonds"),
    (r"無担保普通社債|普通社債", "Unsecured straight bonds"), (r"社債", "Bonds"),
    (r"コマーシャル・?ペーパー", "Commercial paper"), (r"コミットメントライン", "Commitment line"),
    (r"シンジケート", "Syndicated loan"), (r"ブリッジローン", "Bridge loan"), (r"借入|ローン|(?<!金)融資", "Borrowing"),
    (r"格付", "Credit rating"), (r"第三者割当", "Third-party allotment"), (r"株式の売出し|売出し", "Secondary share offering"),
    (r"新株式|募集株式|公募|増資", "Share offering"), (r"証券化|流動化", "Securitisation"), (r"資金調達", "Fund raising"),
]
JP_STAGE = [
    (r"条件決定|発行条件", "terms determined"), (r"期限前償還|繰上償還", "early redemption"),
    (r"期限前返済|繰上返済", "early repayment"), (r"発行登録", "shelf registration"), (r"引上げ|引き上げ", "upgrade"),
    (r"引下げ|引き下げ", "downgrade"), (r"格付.{0,6}取得|新規取得", "rating assigned"), (r"変更", "change"),
    (r"締結|契約", "agreement signed"), (r"返済|償還", "repayment / redemption"), (r"発行", "issuance"),
    (r"借入", "borrowing"),
]
JP_UNIT = {"兆": 1e12, "億": 1e8, "百万": 1e6, "万": 1e4, "千": 1e3, "trillion": 1e12, "billion": 1e9, "million": 1e6}


def jp_companies():
    """{5-character TDnet code: node id} — tdnet.py's Japanese companies that are graph nodes."""
    import tdnet
    nodes = universe()
    return {code: name for code, name in tdnet.universe().items() if name in nodes}


def jp_classify(title):
    t = title.replace("　", " ")
    if re.search(JP_LEAVE_OUT, t, re.I):
        return None
    for type_, pat in JP_TYPES:
        if re.search(pat, t, re.I):
            if type_ == "equity" and re.search(r"子会社|subsidiar", t, re.I):
                return None                                  # capital into an own subsidiary: intra-group
            return type_
    return None


def jp_url(doc_id):
    import tdnet
    return f"{tdnet.BASE}/inbs/ek/{doc_id[1:]}.pdf" if doc_id.startswith("e") else f"{tdnet.BASE}/inbs/{doc_id}.pdf"


def jp_title_ja(title):
    """A short English title for a Japanese-only disclosure (keyword translation)."""
    instrument = next((en for pat, en in JP_INSTRUMENT if re.search(pat, title)), "Financing")
    m = re.search(r"第\s*(\d+)\s*回", title)
    if m:
        instrument += f" No. {int(m.group(1))}"
    m = re.search(r"(\d{4})年(満期|発行)", title)
    if m:
        instrument += f" ({'due' if m.group(2) == '満期' else 'issued'} {m.group(1)})"
    stage = next((en for pat, en in JP_STAGE if re.search(pat, title)), None)
    return instrument + (f": {stage}" if stage else "")


def jp_amount(text, lang, repay=False):
    """(amount, currency) from the filing's first pages; (None, None) when no labelled amount is found.
    repay=True (a repayment / redemption notice): the repaid amount is looked for first, not the facility size."""
    flat = re.sub(r"\s+", " ", text.replace("，", ",").replace("　", " "))
    if lang == "en":
        cur_pat = r"(USD|US\$|U\.S\.\s?\$|\$|EUR|€|JPY|¥|\\|yen)"
        num_pat = r"([\d,]+(?:\.\d+)?)\s*(trillion|billion|million)?"
        labels = (r"aggregate (?:principal )?amount|total (?:principal |issue )?amount(?: of (?:the )?(?:issu\w*|bonds?|"
                  r"notes|offering|borrowings?|loans?))?|(?:borrowing|loan|facility|commitment) amount|amount of "
                  r"(?:the )?(?:borrowings?|loans?|facility|funds to be raised)|maximum amount")
        if repay:
            labels = (r"outstanding (?:principal )?(?:balance|amount)|(?:re|pre)payment amount|redemption amount|"
                      r"amount (?:to be )?(?:re|pre)paid|amount (?:to be )?redeemed|" + labels)
        for m in re.finditer(labels, flat, re.I):
            seg = flat[m.end(): m.end() + 120]
            a = re.search(cur_pat + r"\s?" + num_pat, seg, re.I)          # 'USD 11.1 billion', '¥100,000,000,000'
            b = re.search(num_pat + r"\s*(yen|U\.S\. dollars|dollars|euros)", seg, re.I)
            hit = min((x for x in (a, b) if x), key=lambda x: x.start(), default=None)
            if not hit:
                continue
            if hit is a:
                cur, n, unit = a.group(1), number(a.group(2)), (a.group(3) or "").lower()
            else:
                n, unit, cur = number(b.group(1)), (b.group(2) or "").lower(), b.group(3)
            if not n:
                continue
            cur = cur.lower()
            code = "USD" if ("$" in cur or "usd" in cur or "dollar" in cur) else "EUR" if ("eur" in cur or "€" in cur) else "JPY"
            return n * JP_UNIT.get(unit, 1), code
        return None, None
    labels = r"発行総額|社債の総額|各社債の金額の総額|払込金額の総額|発行価額の総額|調達資金の額|借入金額|借入額|借入総額|融資枠|極度額|契約金額|総額"
    if repay:
        labels = r"返済金額|返済額|返済する金額|償還金額|償還額|償還する金額|残高|" + labels
    for m in re.finditer(labels, flat):
        seg = flat[m.end(): m.end() + 60]
        a = re.search(r"(?:金)?\s*(\d[\d,]*(?:\.\d+)?)\s*兆\s*(?:(\d[\d,]*)\s*億)?\s*円", seg)
        if a:
            return number(a.group(1)) * 1e12 + (number(a.group(2)) or 0) * 1e8, "JPY"
        b = re.search(r"(?:金)?\s*(\d[\d,]*(?:\.\d+)?)\s*(億|百万|万|千)?\s*円", seg)
        if b and number(b.group(1)):
            return number(b.group(1)) * JP_UNIT.get(b.group(2) or "", 1), "JPY"
        c = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(億|百万|万)?\s*(米ドル|ドル|ユーロ)", seg)
        if c and number(c.group(1)):
            return number(c.group(1)) * JP_UNIT.get(c.group(2) or "", 1), "EUR" if c.group(3) == "ユーロ" else "USD"
    return None, None


def jp_detail(text, lang, when):
    flat = re.sub(r"\s+", " ", text)
    bits = []
    if lang == "en":
        # a multi-tranche issue prints one rate / maturity per tranche: give the range, not the first tranche only
        rates = sorted({float(x) for x in re.findall(r"([\d.]+)%\s*per annum", flat) if number(x)})
        if len(rates) > 1:
            bits.append(f"interest rates {rates[0]:g}%-{rates[-1]:g}% per annum across tranches")
        elif rates:
            bits.append(f"interest rate {rates[0]:g}% per annum")
        dates = re.findall(r"Maturity date\s*:?\s*((?:[A-Z][a-z]+ \d{1,2}, \d{4}\s*)+)", flat)
        years = sorted(set(re.findall(r"\d{4}", " ".join(dates))))
        if len(years) > 1:
            bits.append(f"maturities {years[0]}-{years[-1]}")
        elif dates:
            bits.append(f"maturity {dates[0].strip()}")
    else:
        m = re.search(r"利率\s*:?\s*(年)?\s*([\d.]+)\s*[%％]", flat)
        if m:
            bits.append(f"interest rate {m.group(2)}% per annum")
    bits.append(f"disclosed {when} JST" + ("" if lang == "en" else " (Japanese original; no English version listed)"))
    return "; ".join(bits)


def jp_candidates(rows, ours):
    """Financing rows of our companies, the English version kept when TDnet lists both languages."""
    fin = []
    for r in rows:
        if r.get("code") in ours:
            type_ = jp_classify(r.get("title", ""))
            if type_:
                fin.append({**r, "type": type_})
    english = [r for r in fin if r["id"].startswith("e")]
    claimed, keep = set(), []
    for r in fin:
        if r["id"].startswith("e"):
            keep.append(r)
            continue
        # the nearest unclaimed English row of the same company and type within a day = the same disclosure
        near = sorted((abs((dt.date.fromisoformat(e["date"]) - dt.date.fromisoformat(r["date"])).days),
                       abs(int(re.sub(r"\D", "", e["id"])[-6:]) - int(re.sub(r"\D", "", r["id"])[-6:])), e["id"])
                      for e in english if e["code"] == r["code"] and e["type"] == r["type"] and e["id"] not in claimed
                      and abs((dt.date.fromisoformat(e["date"]) - dt.date.fromisoformat(r["date"])).days) <= 1)
        if near:
            claimed.add(near[0][2])
        else:
            keep.append(r)
    return keep


def run_jp(backfill, state):
    import tdnet
    ours = jp_companies()
    have = history_urls("JP")
    end = dt.date.fromisoformat(today())
    start = window_start("JP", backfill, state)
    # seed: every row tdnet.py has seen (its "skip:financing" rows, and convertibles it filed as stock compensation)
    seen = (read_json(TDNET_STATE, {}) or {}).get("seen", {})
    rows = {doc_id: {"id": doc_id, "code": s.get("code"), "date": s.get("date"), "time": "", "title": s.get("title", ""),
                     "lang": s.get("lang", "en" if doc_id.startswith("e") else "ja")}
            for doc_id, s in seen.items() if s.get("code") and s.get("date")}
    # daily path: re-list TDnet with tdnet.py's own listing functions
    listing_failed = False
    try:
        online = tdnet.days_online()
        days = [d for d in online if d >= start.strftime("%Y%m%d")]
        if days:
            log(f"JP: listing TDnet {days[0]} .. {days[-1]} ({len(days)} days, Japanese + English lists)")
            listed = []
            for d in days:
                listed += tdnet.japanese_day(d)
            listed += tdnet.english_range(days[0], days[-1])
            for r in listed:
                if r["code"] in ours:
                    rows[r["id"]] = r
    except Exception as e:
        log(f"JP: TDnet listing failed ({e.__class__.__name__}: {str(e)[:120]}); using tdnet.py's records only")
        listing_failed = True
        if not rows:
            raise
    # an English version that arrives after its Japanese original was recorded is the same disclosure
    recorded_ja = [h for h in read_history(DATASETS["JP"]) if "/inbs/ek/" not in (h.get("url") or "")]
    out = []
    for r in jp_candidates(rows.values(), ours):
        url = r.get("url") or jp_url(r["id"])
        if url in have:
            continue
        lang = "en" if r["id"].startswith("e") else "ja"
        if lang == "ja" and (end - dt.date.fromisoformat(r["date"])).days < 2:
            continue                       # like tdnet.py: give TDnet two days to list the English version
        if lang == "en" and any(h.get("company") == ours[r["code"]] and h.get("type") == r["type"] and
                                abs((dt.date.fromisoformat(h["date"]) - dt.date.fromisoformat(r["date"])).days) <= 1
                                for h in recorded_ja):
            continue
        text = ""
        try:
            resp = tdnet.fetch(url)
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                text = "\n".join(t for _n, t in tdnet.pdf_pages(resp.content)[:3])
        except Exception as e:
            log(f"JP: PDF {r['id']} unavailable ({e.__class__.__name__}); recorded without amount")
        repay = bool(re.search(r"返済|償還|repay|redemption|redeem", r["title"], re.I))
        amount, currency = jp_amount(text, lang, repay) if text else (None, None)
        title = tdnet.short_title(r["title"], 100) if lang == "en" else jp_title_ja(r["title"])
        if amount:
            title += f", {fmt_amount(amount, currency)}"
        when = f"{r['date']} {r.get('time') or ''}".strip()
        out.append(make_row(ours[r["code"]], "JP", r["date"], r["type"], title, amount, currency,
                            jp_detail(text, lang, when), "TDnet timely disclosure (適時開示)", url))
    if listing_failed and not out:
        # nothing new from tdnet.py's records and TDnet itself did not answer: report the market as failed, so
        # its last_run stays and the next run re-reads these days
        raise RuntimeError("TDnet listing failed and tdnet.py's records gave nothing new")
    return out


# ================================================================ run / build

RUNNERS = {"KR": run_kr, "TW": run_tw, "JP": run_jp}


def build():
    """graph/financing.json is built by market/financing.py from every financing history; call it when present."""
    if importlib.util.find_spec("market.financing") is None:
        log("market/financing.py not present yet; history kept, graph/financing.json not rebuilt")
        return False
    importlib.import_module("market.financing").build()
    return True


def run(backfill=False, markets=None):
    load_env()
    state = read_json(STATE, {}) or {}
    ok, failed = [], []
    for market in markets or ("KR", "TW", "JP"):
        try:
            rows = RUNNERS[market](backfill, state)
            added = append_history(DATASETS[market], rows, KEY)
            log(f"{market}: {len(rows)} financing events found, {added} new rows -> market/history/{DATASETS[market]}.jsonl")
            state.setdefault(market, {}).update({"last_run": today(), "rows_seen": len(rows), "added": added})
            write_json(STATE, state)
            ok.append(market)
        except Exception as e:                               # a dead source: warn, keep the previous history
            log(f"warning: {market} failed ({e.__class__.__name__}: {str(e)[:200]}); previous history kept")
            failed.append(market)
    build()
    return ok, failed


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", action="store_true", help="read the last 365 days")
    ap.add_argument("--build-only", action="store_true", help="rebuild graph/financing.json from history only")
    ap.add_argument("--market", choices=sorted(RUNNERS), action="append", help="KR, TW or JP (repeatable)")
    args = ap.parse_args()
    if args.build_only:
        build()
        return 0
    ok, failed = run(backfill=args.backfill, markets=args.market)
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
