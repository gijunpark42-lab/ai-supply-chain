"""market/financials_sec.py -- SEC XBRL "company facts" for the financial-statement table (market/financials.py).

Why (verification of 2026-10-17): Yahoo's statements lag the filing by weeks (Micron filed its FY26 10-K on
2026-10-09; on 2026-10-17 Yahoo still had no Q4 26 / FY26 statements), hold only about 5 quarters (too few for a
year-over-year column), date every period at a month end (Micron's FY26 ended 2026-09-03, not 08-31) and sometimes
carry a wrong figure (ASML's FY22 diluted EPS 16.07; the 20-F says 14.13). For a company that files with the SEC,
the XBRL facts of its 10-K / 10-Q (or 20-F) have the exact period ends and the reported figures.

What this module does:
  fetch(cik)          one request to https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json (a few MB,
                      gzip'd), keeps only the concepts below (and only 10-K / 10-Q / 20-F / 40-F facts of the last
                      7 years) and caches that in market/cache/financials/sec/CIK##########.json (gitignored).
  periods(compact, currency)
                      pure: the cached facts -> per contract field, per XBRL concept, {exact period end:
                      (value, computed)}. A quarter the filings give only as year-to-date figures (always the
                      fiscal Q4: FY minus nine months) is computed from them (computed=True); so is a Q4 diluted EPS
                      (Q4 net income / Q4 diluted shares, where Q4 shares = 4 x the year's - the three quarters').
                      market/financials.py picks, per field, the concept that agrees with Yahoo's own figures.
  cash_flow(compact, currency)
                      pure (added 2026-10-17): operating cash flow, capex and finance-lease principal payments per
                      quarter and fiscal year of a 10-K / 10-Q filer. The tags and the quarter logic are
                      market/hyperscaler_cash.py's (imported, not copied): a 10-Q cash-flow statement is
                      year-to-date, so a quarter without its own 3-month fact is the difference of two (Q2 = H1 - Q1,
                      Q3 = 9M - H1, Q4 = FY - 9M; hyperscaler_cash.discrete_quarters), and a company listed there
                      uses its tags (Amazon's capex: PaymentsToAcquireProductiveAssets). So the 8 companies of
                      graph/hyperscaler_cash.json get the same numbers in both files.

SEC's fair-access rules apply: a descriptive User-Agent (EDGAR_USER_AGENT in .env) and at most 4 requests per
second (market/financing_us.sec_get paces every request).
"""
import datetime as dt
import json

from market import hyperscaler_cash as hc
from market.common import ROOT, read_json, today, write_json

CACHE_DIR = ROOT / "market" / "cache" / "financials" / "sec"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SOURCE = {"name": "SEC EDGAR (XBRL company facts)", "url": "https://www.sec.gov/edgar/search/"}
CACHE_FORMAT = 2            # 2 (2026-10-17): the cash-flow concepts are kept too; an older cache is fetched again
KEEP_YEARS = 7
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}
ANNUAL_ONLY_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A"}
ANNUAL_FORMS = ANNUAL_ONLY_FORMS | {"10-K", "10-K/A", "10-KT", "10-KT/A"}

# Contract field -> XBRL concepts, best first (market/financials.py keeps the one that matches Yahoo's figures).
# Flow items are durations; "interest_expense" and "d_and_a" only feed the EBIT / EBITDA computation.
US_GAAP = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquity"
                      "MethodInvestments"),
    "net_income_after_tax": ("ProfitLoss", "NetIncomeLoss"),
    # ProfitLoss last: a company without minority interests may file only that (Broadcom since FY25)
    "net_income": ("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",
                       "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                         "InterestAndDebtExpense"),
    "d_and_a": ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
                "DepreciationAndAmortization"),
}
US_GAAP_BALANCE = {
    "total_assets": ("Assets",),
    "equity": ("StockholdersEquity",),
    "shares": ("CommonStockSharesOutstanding",),
}
# 20-F filers reporting under IFRS (TSMC). Only the per-share data is used from them (see market/financials.py).
IFRS = {
    "revenue": ("Revenue", "RevenueFromContractsWithCustomers"),
    "net_income": ("ProfitLossAttributableToOwnersOfParent",),
    "eps_diluted": ("DilutedEarningsLossPerShare",),
    "diluted_shares": ("AdjustedWeightedAverageShares",),
}
IFRS_BALANCE = {"total_assets": ("Assets",), "equity": ("EquityAttributableToOwnersOfParent",)}
ADDITIVE = {"revenue", "gross_profit", "operating_income", "pretax_income", "net_income_after_tax", "net_income",
            "interest_expense", "d_and_a"}          # may be differenced (FY - 9 months); per-share data may not
# Cash flow (2026-10-17): hyperscaler_cash's tags. Capex is PaymentsToAcquirePropertyPlantAndEquipment, or the
# capex tag a hyperscaler_cash company uses instead (PaymentsToAcquireProductiveAssets: Amazon; NVIDIA files it too).
CAPEX_TAGS = (hc.CAPEX_TAG,) + tuple(sorted({c["capex"] for c in hc.COMPANIES if c.get("capex")} - {hc.CAPEX_TAG}))
CASH_FLOW = {"ocf": (hc.OCF_TAG,), "capex": CAPEX_TAGS, "lease_principal": (hc.LEASE_TAG,)}


def log(msg):
    print(f"[financials/sec] {msg}", flush=True)


def cache_path(cik):
    return CACHE_DIR / f"CIK{int(cik):010d}.json"


def _all_concepts():
    names = set()
    for table in (US_GAAP, US_GAAP_BALANCE, IFRS, IFRS_BALANCE, CASH_FLOW):
        for concepts in table.values():
            names.update(concepts)
    return names


def compact_facts(facts_json, fetched):
    """The companyfacts answer -> {"cik", "entity", "fetched", "format", "facts": {taxonomy: {concept: {unit:
    [[start, end, value, form, filed], ...]}}}} with only the concepts above, 10-K/10-Q/20-F/40-F facts and the
    last KEEP_YEARS."""
    floor = (dt.date.fromisoformat(fetched) - dt.timedelta(days=366 * KEEP_YEARS)).isoformat()
    wanted = _all_concepts()
    out = {"cik": facts_json.get("cik"), "entity": facts_json.get("entityName"), "fetched": fetched,
           "format": CACHE_FORMAT, "facts": {}}
    for taxonomy in ("us-gaap", "ifrs-full"):
        block = (facts_json.get("facts") or {}).get(taxonomy) or {}
        for concept, body in block.items():
            if concept not in wanted:
                continue
            for unit, rows in (body.get("units") or {}).items():
                kept = [[r.get("start"), r["end"], r["val"], r.get("form"), r.get("filed")]
                        for r in rows if r.get("form") in FORMS and r.get("end", "") >= floor
                        and isinstance(r.get("val"), (int, float))]
                if kept:
                    out["facts"].setdefault(taxonomy, {}).setdefault(concept, {})[unit] = kept
    return out


def fetch(cik):
    """Refresh one company's cached facts (at most once a day, or again when the cache has an older format).
    Returns the compact facts, or None (404 / error: the old cache, if any, is returned instead)."""
    from market.financing_us import sec_get
    path = cache_path(cik)
    cached = read_json(path)
    if cached and cached.get("fetched") == today() and cached.get("format") == CACHE_FORMAT:
        return cached
    try:
        body = sec_get(FACTS_URL.format(cik=int(cik)))
    except Exception as e:                            # SEC unreachable: yesterday's facts beat none
        log(f"WARNING CIK {cik}: {type(e).__name__}: {str(e)[:120]}")
        return cached
    if body is None:
        return cached
    compact = compact_facts(json.loads(body), today())
    write_json(path, compact)
    return compact


def cik_map():
    """{TICKER: cik} from the SEC ticker list (market/financing_us.ticker_map: cached weekly)."""
    from market.financing_us import ticker_map
    return ticker_map()


def cached_cik_map():
    """The ticker list as cached by financing_us (no network; empty when it was never downloaded)."""
    from market.financing_us import TICKER_CACHE
    return (read_json(TICKER_CACHE, {}) or {}).get("map") or {}


# ------------------------------------------------ cached facts -> periods (pure, tested offline)

def _days(start, end):
    return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1


def _latest(rows):
    """(start, end) -> value of the latest filing (a restated figure replaces the original)."""
    best = {}
    for start, end, value, form, filed in rows:
        k = (start, end)
        if k not in best or (filed or "") >= best[k][1]:
            best[k] = (value, filed or "")
    return {k: v for k, (v, _) in best.items()}


def _durations(rows):
    """{"q": {end: value} (3-month facts), "fy": {end: value} (12-month facts of annual reports), "ytd": {start:
    {end: value}} (every fact from a fiscal year start: 3, 6, 9 and 12 months)}. A 12-month figure in a 10-Q is
    a trailing-twelve-month one (Amazon's), not a fiscal year: only a 10-K / 20-F's count."""
    annual_periods = {(r[0], r[1]) for r in rows if r[3] in ANNUAL_FORMS}
    out = {"q": {}, "fy": {}, "ytd": {}, "starts": {}}
    for (start, end), value in _latest(rows).items():
        if not start:
            continue
        days = _days(start, end)
        is_year = 350 <= days <= 380 and (start, end) in annual_periods
        if 80 <= days <= 100:
            out["q"][end] = value
            out["starts"][end] = start
        elif is_year:
            out["fy"][end] = value
        if 80 <= days <= 100 or 170 <= days <= 200 or 260 <= days <= 290 or is_year:
            out["ytd"].setdefault(start, {})[end] = value
    return out


def _quarters(d, additive, field=None):
    """{end: (value, computed)}: the 3-month facts, plus (additive items only) quarters computed from the
    year-to-date facts of the same fiscal year (6M - 3M, 9M - 6M, FY - 9M). A computed revenue below zero means
    the two figures are on different bases (a 10-K restated for a discontinued business, minus the 10-Q's original
    nine months: Applied Digital Q4 FY25) and is left out."""
    out = {end: (v, False) for end, v in d["q"].items()}
    if not additive:
        return out
    for start, cumulative in d["ytd"].items():
        ends = sorted(cumulative)
        for prev, end in zip(ends, ends[1:]):
            if end in out:
                continue
            if 80 <= _days((dt.date.fromisoformat(prev) + dt.timedelta(days=1)).isoformat(), end) <= 100:
                value = cumulative[end] - cumulative[prev]
                if field == "revenue" and value < 0:
                    continue
                out[end] = (value, True)
    return out


def periods(compact, currency):
    """Cached facts -> {"kind": "10-K" | "20-F", "quarterly": {field: [(concept, {end: (value, computed)})]},
    "annual": {...}, "balances": {field: [(concept, {end: value})]}, "cash": cash_flow(...)}. Money in full
    currency units (the caller scales); only facts in `currency` (EPS in `currency`/shares) are used. Empty dict
    when nothing fits."""
    facts = (compact or {}).get("facts") or {}
    if not facts or not currency:
        return {}
    if facts.get("us-gaap"):
        taxonomy, flows, balances = "us-gaap", US_GAAP, US_GAAP_BALANCE
    else:
        taxonomy, flows, balances = "ifrs-full", IFRS, IFRS_BALANCE
    block = facts.get(taxonomy) or {}
    forms = {r[3] for c in block.values() for rows in c.values() for r in rows}
    kind = "20-F" if forms and forms <= ANNUAL_ONLY_FORMS else "10-K"

    def unit_rows(concept, field):
        units = block.get(concept) or {}
        unit = (f"{currency}/shares" if field == "eps_diluted" else
                "shares" if field in ("diluted_shares", "shares") else currency)
        return units.get(unit) or []

    out = {"kind": kind, "quarterly": {}, "annual": {}, "balances": {}}
    for field, concepts in flows.items():
        for concept in concepts:
            rows = unit_rows(concept, field)
            if not rows:
                continue
            d = _durations(rows)
            q = _quarters(d, field in ADDITIVE, field)
            if q:
                out["quarterly"].setdefault(field, []).append((concept, q))
            if d["fy"]:
                out["annual"].setdefault(field, []).append((concept, {e: (v, False) for e, v in d["fy"].items()}))
    for field, concepts in balances.items():
        for concept in concepts:
            rows = unit_rows(concept, field)
            series = {}
            for (start, end), value in _latest(rows).items():
                if not start:
                    series[end] = value
            if series:
                out["balances"].setdefault(field, []).append((concept, series))
    _q4_eps(out)
    out["cash"] = cash_flow(compact, currency)
    return out


def cash_flow(compact, currency):
    """Cached facts -> {"quarterly": {field: {end: (value, computed)}}, "annual": {...}, "concepts": {field:
    concept}} for "ocf" (operating cash flow), "capex" (purchases of property and equipment, a positive number as
    filed) and "lease_principal" (finance-lease principal payments), in full currency units; {} for a 20-F filer
    (no quarters: Yahoo's are used) or when there is no operating cash flow.
    A company of market/hyperscaler_cash.py (same CIK) uses its tags and quarters exactly. Any other company uses
    the same default tags; for capex the concept with the newest figure comes first (a company that files only
    PaymentsToAcquireProductiveAssets, like NVIDIA, or switched to it), the other fills periods it lacks.
    Quarters are hyperscaler_cash.discrete_quarters of the facts; computed = the difference of two year-to-date
    figures. Fiscal years are the 12-month facts of annual reports (a 10-Q's trailing twelve months are not)."""
    facts = ((compact or {}).get("facts") or {}).get("us-gaap") or {}
    if not facts or not currency:
        return {}
    forms = {r[3] for c in facts.values() for rows in c.values() for r in rows}
    if forms <= ANNUAL_ONLY_FORMS:
        return {}
    known = next((c for c in hc.COMPANIES if c["cik"] == (compact or {}).get("cik")), None)
    if known:
        tags = {"ocf": (known.get("ocf", hc.OCF_TAG),), "capex": (known.get("capex", hc.CAPEX_TAG),),
                "lease_principal": (known.get("lease", hc.LEASE_TAG),)}
    else:
        tags = CASH_FLOW
    out = {"quarterly": {}, "annual": {}, "concepts": {}}
    for field, concepts in tags.items():
        cands = []
        for concept in concepts:
            rows = (facts.get(concept) or {}).get(currency) or []
            if not rows:
                continue
            as_facts = [{"start": s, "end": e, "val": v, "form": form, "filed": filed or ""}
                        for s, e, v, form, filed in rows]
            quarters = {end: (q["val"], q["start"] != q["fact"]["start"])
                        for end, q in hc.discrete_quarters(as_facts).items()}
            years = {end: (v, False) for end, v in _durations(rows)["fy"].items()}
            if quarters or years:
                cands.append((concept, quarters, years))
        if not cands:
            continue
        # newest figure first; a tie keeps the listed order (sorted() is stable, also with reverse=True)
        cands.sort(key=lambda c: max(list(c[1]) + list(c[2])), reverse=True)
        out["concepts"][field] = cands[0][0]
        for scale, k in (("quarterly", 1), ("annual", 2)):
            merged = {}
            for cand in cands:
                for end, value in cand[k].items():
                    merged.setdefault(end, value)
            if merged:
                out[scale][field] = merged
    if not (out["quarterly"].get("ocf") or out["annual"].get("ocf")):
        return {}
    return out


def _q4_eps(out):
    """A fiscal Q4's diluted EPS is not filed on its own (the 10-K has the year): Q4 net income / Q4 diluted shares,
    where Q4 shares = 4 x the year's weighted average - the three quarters' (all four quarters weigh about the
    same). Added to the first EPS concept's quarterly series as computed."""
    q = out["quarterly"]
    a = out["annual"]
    if not q.get("net_income") or not q.get("diluted_shares") or not a.get("diluted_shares"):
        return

    def combined(cands):                               # concepts in the listed order, period by period
        merged = {}
        for _, series in cands:
            for end, value in series.items():
                merged.setdefault(end, value)
        return merged

    ni = combined(q["net_income"])
    q_sh = combined(q["diluted_shares"])
    fy_sh = combined(a["diluted_shares"])
    if q.get("eps_diluted"):
        eps_concept, eps = q["eps_diluted"][0]
    else:
        eps_concept, eps = "EarningsPerShareDiluted", {}
        q["eps_diluted"] = [(eps_concept, eps)]
    q_ends = sorted(q_sh)
    for fy_end, (shares_fy, _) in fy_sh.items():
        if fy_end in eps or fy_end not in ni:
            continue
        earlier = [e for e in q_ends if e < fy_end][-3:]
        if len(earlier) != 3 or _days(earlier[0], fy_end) > 290:
            continue                                   # the three quarters must lie in the same fiscal year
        q4_ni = ni[fy_end][0]
        if all((ni.get(e) or (0,))[0] > 0 for e in earlier) and q4_ni > 0:
            q4_shares = 4 * shares_fy - sum(q_sh[e][0] for e in earlier)
        else:
            # a loss quarter's diluted count is its basic count (nothing dilutes a loss), so the formula above is
            # off (Broadcom Q3 FY24): take the newest earlier quarter whose result has Q4's sign instead
            same_sign = [e for e in earlier if e in ni and (ni[e][0] > 0) == (q4_ni > 0)]
            if not same_sign:
                continue
            q4_shares = q_sh[same_sign[-1]][0]
        if q4_shares <= 0 or abs(q4_shares / q_sh[earlier[-1]][0] - 1) > 0.1:
            continue                                   # implausible (a big buyback or issuance): leave it blank
        eps[fy_end] = (q4_ni / q4_shares, True)
