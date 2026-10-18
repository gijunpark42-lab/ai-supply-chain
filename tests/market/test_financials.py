"""financials: Yahoo statement rows (+ the companies' SEC / DART filings) -> the company panel's financial-statement
table (graph/financials/).

The fixture financials_micron_like.json is made up in the shape of the collector's cache (Yahoo's timeseries rows,
quoteSummary modules and monthly chart), with Micron-like numbers: an August fiscal year whose newest quarter and
year (Q4 26 / FY26, ended 2026-09-03) are not in Yahoo's statements yet, only in its earnings summary. That is the
case the user's screenshot checks (Micron revenue FY24 25,111 / FY25 37,378 / FY26 133,188 USD mn; column dates
2024.08.29 / 2025.08.28 / 2026.09.03: the companies' own period ends, not month ends).

financials_sec_micron_like.json is a cut of SEC XBRL company facts in the collector's cache shape (FY26 10-Qs and
the FY26 10-K), plus one trailing-twelve-month figure of a 10-Q that must not count as a fiscal year.
financials_dart_hynix_like.json is a cut of a DART cache (SK Hynix-like: 2025 Q3 and annual reports, 2026 half
year, with SK Hynix's filed cash-flow rows), dart_preliminary_samsung_like.html a preliminary-results disclosure
(공정공시) as document.xml returns it. financials_cash_hyperscalers.json holds real SEC companyconcept facts of the
cash-flow tags of Amazon and Alphabet since 2024 (one fact per period span, the most recently filed): the cash flow
of the 8 companies of graph/hyperscaler_cash.json must be the same numbers in both files (added 2026-10-17).

The cases the verification of 2026-10-17 fixed are pinned here: zero placeholders in Yahoo's earnings summary, a
10-20 year old summary series, a statement net income on another GAAP than the EPS (TSMC), a wrong diluted EPS
(ASML FY22), EBITDA without D&A, a single missing quarter (Tokyo Electron Q1 26), exact 52/53-week period ends,
Korean Q4 EPS = FY - 9 months, and one share basis for Korean book value per share. Also pinned (2026-10-17): GAAP
and adjusted EPS as separate series with their own QoQ / YoY, the adjusted history that outlives Yahoo's 4-quarter
window (AdjustedEps, AdjustedHistoryRun), and a fiscal year's adjusted EPS = Yahoo's figure, else 4 quarters' sum.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from market import financials as fin
from market import financials_dart as fd
from market import financials_sec as fs
from market import hyperscaler_cash as hc
from tests.market.helpers import FIXED_TODAY, FIXTURES, TempDataTestCase, fixture_text, quietly

RAW = json.loads((FIXTURES / "financials_micron_like.json").read_text(encoding="utf-8"))
SEC = json.loads((FIXTURES / "financials_sec_micron_like.json").read_text(encoding="utf-8"))
DART = json.loads((FIXTURES / "financials_dart_hynix_like.json").read_text(encoding="utf-8"))
CASH = json.loads((FIXTURES / "financials_cash_hyperscalers.json").read_text(encoding="utf-8"))


def by_label(rows):
    return {r["label"]: r for r in rows}


def companyfacts(cik, facts):
    """companyconcept-shaped facts {tag: [fact]} -> the companyfacts answer that financials_sec.fetch downloads."""
    return {"cik": cik, "facts": {"us-gaap": {tag: {"units": {"USD": rows}} for tag, rows in facts.items()}}}


def yahoo_raw(symbol, quarter_ends, year_ends, extra_quarterly=None):
    """A minimal Yahoo answer: revenue and net income for these period ends (+ more quarterly rows)."""
    quarterly = {"TotalRevenue": {e: 1e9 for e in quarter_ends}, "NetIncome": {e: 1e8 for e in quarter_ends}}
    quarterly.update(extra_quarterly or {})
    annual = {"TotalRevenue": {e: 4e9 for e in year_ends}, "NetIncome": {e: 4e8 for e in year_ends}}
    return {"symbol": symbol, "fetched": FIXED_TODAY, "format": fin.RAW_FORMAT, "summary": {}, "chart": None,
            "timeseries": {"currency": "USD", "quarterly": quarterly, "annual": annual}}


def sec_compact(cik, tags):
    """A compact SEC cache from {tag: [(start, end, value, form)]}."""
    return {"cik": cik, "facts": {"us-gaap": {t: {"USD": [[s, e, v, f, "2026-01-30"] for s, e, v, f in rows]}
                                              for t, rows in tags.items()}}}


class FiscalLabels(unittest.TestCase):
    def test_micron_august_year(self):
        self.assertEqual(fin.month_end("2026-09-03"), "2026-08-31")       # a 53-week year ending in September
        self.assertEqual(fin.month_end("2026-05-28"), "2026-05-31")
        self.assertEqual(fin.fiscal_of("2026-05-31", 8), (2026, 3))
        self.assertEqual(fin.fiscal_of("2025-11-30", 8), (2026, 1))
        self.assertEqual(fin.fiscal_of("2026-08-31", 8), (2026, 4))
        self.assertEqual(fin.quarter_label(*fin.fiscal_of("2026-05-31", 8)), "Q3 26")

    def test_nvidia_january_year(self):
        self.assertEqual(fin.fiscal_of(fin.month_end("2026-07-26"), 1), (2027, 2))
        self.assertEqual(fin.quarter_label(2027, 2), "Q2 27")
        self.assertEqual(fin.fiscal_of("2026-01-31", 1), (2026, 4))
        self.assertEqual(fin.fiscal_of("2025-04-30", 1), (2026, 1))

    def test_calendar_and_march_years(self):
        self.assertEqual(fin.fiscal_of("2026-06-30", 12), (2026, 2))
        self.assertEqual(fin.fiscal_of("2026-12-31", 12), (2026, 4))
        self.assertEqual(fin.year_label(2026), "FY26")
        self.assertEqual(fin.fiscal_of("2026-06-30", 3), (2027, 1))      # a Japanese April-March year

    def test_year_end_month_is_the_most_recent_one(self):
        self.assertEqual(fin.fiscal_year_end_month(["2024-08-31", "2025-08-31"]), 8)
        self.assertEqual(fin.fiscal_year_end_month([], "2026-09-03"), 8)
        self.assertEqual(fin.fiscal_year_end_month([]), 12)
        self.assertEqual(fin.fiscal_quarter_end(2027, 1, 8), "2026-11-30")
        # Daifuku moved from March to December: its quarters are labelled on the new calendar, as Yahoo does
        daifuku = ["2022-03-31", "2023-03-31", "2024-03-31", "2025-12-31"]
        self.assertEqual(fin.fiscal_year_end_month(daifuku), 12)
        self.assertEqual(fin.quarter_label(*fin.fiscal_of("2025-09-30", 12)), "Q3 25")


class ExactPeriodEnds(unittest.TestCase):
    def test_weekday_rules(self):
        micron = fin.weekday_rule([("2026-08-31", "2026-09-03"), ("2026-05-31", "2026-05-28")])
        self.assertEqual(micron, (3, "nearest"))                         # the Thursday nearest the month end
        self.assertEqual(fin.rule_date("2026-11-30", micron), "2026-12-03")
        self.assertEqual(fin.rule_date("2027-08-31", micron), "2027-09-02")
        nvidia = fin.weekday_rule([("2026-01-31", "2026-01-25")])
        self.assertEqual(nvidia, (6, "last"))                            # the last Sunday of the month
        self.assertEqual(fin.rule_date("2026-10-31", nvidia), "2026-10-25")
        self.assertEqual(fin.rule_date("2027-01-31", nvidia), "2027-01-31")
        broadcom = fin.weekday_rule([("2025-10-31", "2025-11-02")])
        self.assertEqual(fin.rule_date("2026-07-31", broadcom), "2026-08-02")
        self.assertIsNone(fin.weekday_rule([("2025-12-31", "2025-12-31"), ("2026-06-30", "2026-06-30")]))

    def test_a_fiscal_q4_ends_with_its_year(self):
        ends = fin.PeriodEnds({}, {}, 12, mrq_exact="2026-09-27", last_fy_exact="2025-12-31")   # ASML-like
        self.assertEqual(ends.quarter("2026-09-30"), "2026-09-27")
        self.assertEqual(ends.quarter("2026-06-30"), "2026-06-28")
        self.assertEqual(ends.quarter("2025-12-31"), "2025-12-31")
        self.assertEqual(ends.year("2025-12-31"), "2025-12-31")
        calendar = fin.PeriodEnds({}, {}, 12, mrq_exact="2026-06-30", last_fy_exact="2025-12-31")
        self.assertEqual(calendar.quarter("2026-03-31"), "2026-03-31")


class Q4Derivation(unittest.TestCase):
    FIELDS = ["revenue", "net_income", "eps_diluted"]

    def test_missing_q4_is_fy_minus_three_quarters(self):
        quarters = {"2025-03-31": {"revenue": 10.0, "eps_diluted": 1.0}, "2025-06-30": {"revenue": 20.0, "eps_diluted": 2.0},
                    "2025-09-30": {"revenue": 30.0, "eps_diluted": 3.0}}
        years = {"2025-12-31": {"revenue": 100.0, "eps_diluted": 10.0, "net_income": 50.0}}
        derived = {}
        fin.derive_missing_quarter(quarters, years, derived, self.FIELDS)
        self.assertEqual(quarters["2025-12-31"], {"revenue": 40.0, "eps_diluted": 4.0})   # no Q1-Q3 net income
        self.assertEqual(derived, {"2025-12-31": {"revenue", "eps_diluted"}})

    def test_reported_q4_field_is_kept(self):
        quarters = {"2025-03-31": {"revenue": 10.0, "eps_diluted": 1.0}, "2025-06-30": {"revenue": 20.0, "eps_diluted": 2.0},
                    "2025-09-30": {"revenue": 30.0, "eps_diluted": 3.0}, "2025-12-31": {"revenue": 41.0}}
        derived = {}
        fin.derive_missing_quarter(quarters, {"2025-12-31": {"revenue": 100.0, "eps_diluted": 10.0}}, derived,
                                   self.FIELDS)
        self.assertEqual(quarters["2025-12-31"], {"revenue": 41.0, "eps_diluted": 4.0})
        self.assertEqual(derived, {"2025-12-31": {"eps_diluted"}})

    def test_needs_the_other_three_quarters(self):
        quarters = {"2025-03-31": {"revenue": 10.0}, "2025-09-30": {"revenue": 30.0}}
        self.assertEqual(fin.derive_missing_quarter(quarters, {"2025-12-31": {"revenue": 100.0}}, {}, self.FIELDS), [])

    def test_any_single_missing_quarter(self):
        # Tokyo Electron Q1 26: Yahoo had only its EPS; the year minus Q2-Q4 gives revenue and net income
        quarters = {"2025-06-30": {"eps_diluted": 51.3}, "2025-09-30": {"revenue": 630082.0, "net_income": 123825.0},
                    "2025-12-31": {"revenue": 552047.0, "net_income": 118538.0},
                    "2026-03-31": {"revenue": 711818.0, "net_income": 214290.0}}
        years = {"2026-03-31": {"revenue": 2443533.0, "net_income": 574454.0}}
        fin.derive_missing_quarter(quarters, years, {}, self.FIELDS)
        self.assertEqual((quarters["2025-06-30"]["revenue"], quarters["2025-06-30"]["net_income"]), (549586.0, 117801.0))

    def test_impossible_results_are_not_kept(self):
        quarters = {"2025-03-31": {"revenue": 50.0, "net_income": -5.0, "eps_diluted": 0.3},
                    "2025-06-30": {"revenue": 60.0, "eps_diluted": 0.1}, "2025-09-30": {"revenue": 40.0, "eps_diluted": -2.5},
                    "2025-12-31": {"net_income": -20.0}}
        years = {"2025-12-31": {"revenue": 120.0, "eps_diluted": -1.3}}
        made = fin.derive_missing_quarter(quarters, years, {}, ["revenue"])
        self.assertEqual(made, [])                                       # 120 - 150 < 0: two bases mixed
        quarters["2025-03-31"]["eps_diluted"] = -0.3
        self.assertEqual(fin.derive_missing_quarter(quarters, years, {}, ["eps_diluted"]), [])   # +1.4 vs a loss


class Summary(unittest.TestCase):
    def test_half_year_summary_is_not_a_quarter_series(self):
        summary = {"earnings": {"financialsChart": {"quarterly": [
            {"fiscalQuarter": "2Q2025", "revenue": 1e9, "earnings": 1e8},
            {"fiscalQuarter": "4Q2025", "revenue": 1e9, "earnings": 1e8}]}}}
        self.assertEqual(fin.summary_quarters(summary, 12), [])           # June and December: 6 months apart

    def test_zero_earnings_is_not_a_figure(self):
        # LG Electronics Q3 26: the preliminary-results quarter has revenue, but earnings 0 (not reported yet)
        summary = {"earnings": {"financialsChart": {"quarterly": [
            {"fiscalQuarter": "2Q2026", "revenue": 20e12, "earnings": 0.5e12},
            {"fiscalQuarter": "3Q2026", "revenue": 21e12, "earnings": 0}]}}}
        entries = fin.summary_quarters(summary, 12)
        self.assertEqual(entries[-1], ("2026-09-30", 21e12, None))
        periods = {"2026-06-30": {"revenue": 20e6, "net_income": 0.5e6}}
        derived = {}
        self.assertEqual(fin.fill_from_summary(periods, entries, derived, FIXED_TODAY), ["2026-09-30"])
        self.assertEqual(periods["2026-09-30"], {"revenue": 21e6})       # net income stays blank, so QoQ / YoY too

    def test_old_series_is_not_added(self):
        # ADDA-like: statements 2025-2026, a summary series from 2010
        periods = {"2025-12-31": {"revenue": 900.0}, "2026-03-31": {"revenue": 950.0}}
        entries = [("2010-06-30", 1e8, 1e7), ("2010-09-30", 1.1e8, 1e7), ("2010-12-31", 1.2e8, 1e7)]
        self.assertEqual(fin.fill_from_summary(periods, entries, {}, FIXED_TODAY), [])
        self.assertEqual(sorted(periods), ["2025-12-31", "2026-03-31"])
        # without statement periods only the last 15 months count
        self.assertEqual(fin.fill_from_summary({}, entries + [("2026-06-30", 1e9, 1e8)], {}, FIXED_TODAY),
                         ["2026-06-30"])

    def test_summary_series_that_disagrees_is_not_used(self):
        periods = {"2026-05-31": {"revenue": 41456.0}}
        entries = [("2026-05-31", 50000e6, 1e9), ("2026-08-31", 54229e6, 37701e6)]
        self.assertEqual(fin.fill_from_summary(periods, entries, {}), [])
        self.assertNotIn("2026-08-31", periods)

    def test_net_income_disagreement_rejects_the_series(self):
        # ASML FY25: the summary says 9,392.7, the statements (and EPS x shares) 9,609.4
        years = {"2025-12-31": {"revenue": 32667.3, "net_income": 9609.4, "eps_diluted": 24.71, "diluted_shares": 388.9e6}}
        entries = [("2025-12-31", 32667.3e6, 9392.7e6), ("2026-12-31", 40000e6, 12000e6)]
        self.assertEqual(fin.fill_from_summary(years, entries, {}, FIXED_TODAY), [])


class Reconcile(unittest.TestCase):
    def test_tsmc_net_income_from_the_summary(self):
        # Yahoo's statement Q4 25 mixes a 20-F IFRS year with Taiwan-IFRS quarters; EPS x shares says 505,655
        quarters = {"2025-12-31": {"net_income": 485465.36, "net_income_after_tax": 485143.45, "eps_diluted": 19.5,
                                   "diluted_shares": 25931e6}}
        marks = {}
        fixed = fin.reconcile_net_income(quarters, marks, [("2025-12-31", 1046090e6, 505744e6)])
        self.assertEqual(fixed, ["2025-12-31"])
        self.assertEqual(quarters["2025-12-31"]["net_income"], 505744.0)
        self.assertAlmostEqual(quarters["2025-12-31"]["net_income_after_tax"], 505422.09, places=2)
        self.assertEqual(marks["2025-12-31"], {"net_income", "net_income_after_tax"})

    def test_korean_preferred_structure_is_left_alone(self):
        # Samsung: net income includes the preferred holders' share, so EPS x common shares is lower; the summary
        # agrees with the statement, so nothing changes
        quarters = {"2025-09-30": {"net_income": 12006461.0, "eps_diluted": 1801.0, "diluted_shares": 5858.7e6}}
        self.assertEqual(fin.reconcile_net_income(quarters, {}, [("2025-09-30", 86e12, 12006.4e9)]), [])

    def test_asml_eps_from_the_filing(self):
        years = {"2022-12-31": {"net_income": 5624.2, "eps_diluted": 16.07, "diluted_shares": 398.0e6},
                 "2024-12-31": {"net_income": 7571.6, "eps_diluted": 19.24, "diluted_shares": 393.6e6}}
        fixed = fin.reconcile_eps(years, {"2022-12-31": 14.13, "2024-12-31": 19.24})
        self.assertEqual(fixed, ["2022-12-31"])
        self.assertEqual(years["2022-12-31"]["eps_diluted"], 14.13)

    def test_ebitda_without_d_and_a_is_blank(self):
        quarters = {"2025-12-31": {"ebitda": 3686.3, "ebit": 3431.1}, "2026-03-31": {"ebitda": 3157.8, "ebit": 3157.8}}
        self.assertEqual(fin.drop_ebitda_without_da(quarters), ["2026-03-31"])
        self.assertIsNone(quarters["2026-03-31"]["ebitda"])

    def test_missing_eps(self):
        quarters = {"2025-06-30": {"net_income": 398273.1, "eps_diluted": 15.36, "diluted_shares": 25928.9e6},
                    "2025-09-30": {"net_income": 452301.4, "diluted_shares": 25930.0e6},          # TSMC Q3 25
                    "2025-12-31": {"net_income": 505744.0, "eps_diluted": 19.5, "diluted_shares": 25931e6},
                    "2026-06-30": {"net_income": 706561.9, "eps_diluted": 27.25, "diluted_shares": 25931.8e6},
                    "2026-09-30": {"net_income": 763064.0}}                                      # Q3 26: summary only
        self.assertTrue(fin.eps_matches_shares(quarters))
        marks = {}
        filled = fin.fill_eps(quarters, marks, {"2026-09-30": 29.43}, {}, False, True)
        self.assertEqual(filled, ["2025-09-30", "2026-09-30"])
        self.assertAlmostEqual(quarters["2025-09-30"]["eps_diluted"], 17.443, places=3)          # NI / shares
        self.assertEqual(quarters["2026-09-30"]["eps_diluted"], 29.43)                           # the actual
        # a US "actual" is adjusted (Micron 33.42 vs GAAP 32.87): not within 1%, so NI / shares instead
        q = {"2026-05-31": {"net_income": 28243.0, "eps_diluted": 24.67, "diluted_shares": 1145e6},
             "2026-08-31": {"net_income": 37701.0}}
        fin.fill_eps(q, {}, {"2026-08-31": 33.42}, {}, False, True)
        self.assertAlmostEqual(q["2026-08-31"]["eps_diluted"], 32.9266, places=4)


class SecFacts(unittest.TestCase):
    def setUp(self):
        self.p = fs.periods(SEC, "USD")

    def series(self, scale, field):
        return dict(self.p[scale][field][0][1])

    def test_q4_is_the_year_minus_nine_months(self):
        revenue = self.series("quarterly", "revenue")
        self.assertEqual(revenue["2026-09-03"], (54229000000, True))      # 133,188 - 78,959
        self.assertEqual(revenue["2026-05-28"], (41456000000, False))
        ni = self.series("quarterly", "net_income")
        self.assertEqual(ni["2026-09-03"], (37701000000, True))

    def test_q4_diluted_eps_from_net_income_and_shares(self):
        eps = self.series("quarterly", "eps_diluted")
        value, computed = eps["2026-09-03"]
        self.assertTrue(computed)
        self.assertEqual(round(value, 2), 32.87)                         # 37,701 / (4 x 1,143 - 1,138 - 1,142 - 1,145)

    def test_ttm_figure_of_a_10q_is_not_a_year(self):
        self.assertEqual(sorted(self.series("annual", "revenue")), ["2025-08-28", "2026-09-03"])
        self.assertEqual(self.p["kind"], "10-K")

    def test_currency_must_match(self):
        self.assertNotIn("revenue", fs.periods(SEC, "EUR")["quarterly"])   # money facts are in USD

    def test_compose_with_the_filings(self):
        sec = copy.deepcopy(SEC)
        # the Yahoo fixture's quarter-end assets are made up; keep the filing's fiscal-year ends, which match it
        assets = sec["facts"]["us-gaap"]["Assets"]["USD"]
        sec["facts"]["us-gaap"]["Assets"]["USD"] = [r for r in assets if r[1] in ("2025-08-28", "2026-09-03")]
        data = fin.compose("Micron", copy.deepcopy(RAW), [], filings={"sec": sec})
        q = by_label(data["quarterly"])["Q4 26"]
        self.assertEqual(q["end"], "2026-09-03")
        self.assertEqual((q["gross_profit"], q["operating_income"], q["pretax_income"], q["net_income_after_tax"]),
                         (47047.0, 43751.0, 44238.0, 37701.0))
        self.assertEqual(round(q["eps_diluted"], 2), 32.87)                # Micron's 8-K: 32.87 (GAAP diluted)
        self.assertEqual(q["qoq"]["eps_diluted"], 33.24)
        self.assertEqual(q["ebit"], 44238.0)                             # pretax + interest (0), as Yahoo defines it
        fy26 = by_label(data["annual"])["FY26"]
        self.assertEqual((fy26["gross_profit"], fy26["operating_income"], fy26["pretax_income"]),
                         (107504.0, 99340.0, 99671.0))
        self.assertEqual(fy26["roa_pct"], 60.98)                         # 84,969 / avg(195,888, 82,800)
        self.assertTrue(any(s["name"].startswith("SEC") for s in data["sources"]))


class HyperscalerCashAgreement(unittest.TestCase):
    """The 8 companies of graph/hyperscaler_cash.json (the SEC-derived reference) must show the same quarterly
    OCF / capex / FCF / FCF after leases in their financials file. Real facts go through both collectors: Amazon
    (capex tag PaymentsToAcquireProductiveAssets; 10-Qs with 3-month, year-to-date and trailing-twelve-month
    figures) and Alphabet (year-to-date figures only, so Q2-Q4 are differences)."""

    PAIRS = (("ocf", "ocf_usd"), ("capex", "capex_usd"), ("fcf", "fcf_usd"), ("fcf_after_leases", "fcf_after_leases_usd"))

    def reference(self, cid, facts):
        c = next(x for x in hc.COMPANIES if x["id"] == cid)
        with mock.patch.object(hc, "sec_concept", lambda cik, tag: facts.get(tag, [])):
            rows = hc.company_quarters(c, backfill=False)
        return next(x for x in hc.build_companies(rows) if x["id"] == cid)["quarters"]

    def check(self, cid, facts=None):
        co = CASH[cid]
        facts = facts or co["facts"]
        ref = self.reference(cid, facts)
        self.assertEqual(len(ref), 8)
        ends = sorted(q["end"] for q in ref)
        years = sorted({e for e in ends if e.endswith("-12-31")})
        # Yahoo's own cash-flow rows are deliberately off: the SEC figures must replace them
        ticker = next(x["ticker"] for x in hc.COMPANIES if x["id"] == cid)
        raw = yahoo_raw(ticker, ends, years, {"OperatingCashFlow": {e: 1.0 for e in ends},
                                              "CapitalExpenditure": {e: -1.0 for e in ends}})
        compact = fs.compact_facts(companyfacts(co["cik"], facts), FIXED_TODAY)
        data = fin.compose(cid, raw, [], filings={"sec": compact})
        by_end = {p["end"]: p for p in data["quarterly"]}
        for q in ref:
            for mine, theirs in self.PAIRS:
                with self.subTest(company=cid, end=q["end"], field=mine):
                    expected = None if q[theirs] is None else round(q[theirs] / 1e6, 2)
                    self.assertEqual(by_end[q["end"]][mine], expected)
        return data, by_end

    def test_amazon(self):
        data, by_end = self.check("Amazon")
        q2 = by_end["2026-06-30"]                                       # graph/hyperscaler_cash.json, FY2026 Q2
        self.assertEqual((q2["ocf"], q2["capex"], q2["fcf"], q2["fcf_after_leases"]), (45387.0, 54208.0, -8821.0, -9216.0))
        self.assertIsNone(q2["qoq"]["fcf"])                             # a negative FCF has no growth %
        self.assertTrue(any(n.startswith("Cash flow from the company's SEC filings") and
                            "PaymentsToAcquireProductiveAssets" in n for n in data["notes"]))
        self.assertNotIn("ocf", by_end["2026-03-31"]["derived"])         # a 3-month fact
        self.assertEqual({"capex", "fcf", "fcf_after_leases", "ocf"} - set(by_end["2025-12-31"]["derived"]), set())

    def test_amazon_keeps_its_capex_tag(self):
        # a company of hyperscaler_cash uses its tag even when it files the default one too
        facts = copy.deepcopy(CASH["Amazon"]["facts"])
        facts[hc.CAPEX_TAG] = [dict(f, val=f["val"] // 2) for f in facts["PaymentsToAcquireProductiveAssets"]]
        _, by_end = self.check("Amazon", facts)
        self.assertEqual(by_end["2026-06-30"]["capex"], 54208.0)

    def test_alphabet_year_to_date_differences(self):
        _, by_end = self.check("Google")
        self.assertNotIn("ocf", by_end["2026-03-31"]["derived"])         # Q1: the year-to-date figure is 3 months
        for end in ("2026-06-30", "2025-12-31", "2025-09-30"):            # H1 - Q1, FY - 9M, 9M - H1
            self.assertIn("ocf", by_end[end]["derived"])


class SecCashFlow(unittest.TestCase):
    OCF = hc.OCF_TAG
    YEAR = [("2025-01-01", "2025-03-31", 10, "10-Q"), ("2025-01-01", "2025-06-30", 25, "10-Q"),
            ("2025-01-01", "2025-09-30", 45, "10-Q"), ("2025-01-01", "2025-12-31", 70, "10-K")]

    def test_productive_assets_when_that_is_what_the_company_files(self):
        # NVIDIA-like: "purchases related to property and equipment and intangible assets"
        cash = fs.cash_flow(sec_compact(1045810, {self.OCF: self.YEAR,
                                                  "PaymentsToAcquireProductiveAssets": self.YEAR}), "USD")
        self.assertEqual(cash["concepts"]["capex"], "PaymentsToAcquireProductiveAssets")
        self.assertEqual(cash["quarterly"]["capex"]["2025-03-31"], (10, False))
        self.assertEqual(cash["quarterly"]["capex"]["2025-06-30"], (15, True))     # H1 25 - Q1 10
        self.assertEqual(cash["quarterly"]["capex"]["2025-12-31"], (25, True))     # FY 70 - 9M 45
        self.assertEqual(cash["annual"]["capex"], {"2025-12-31": (70, False)})

    def test_default_tag_first_when_both_are_filed(self):
        both = {self.OCF: self.YEAR, hc.CAPEX_TAG: self.YEAR,
                "PaymentsToAcquireProductiveAssets": [(s, e, v * 2, f) for s, e, v, f in self.YEAR]}
        cash = fs.cash_flow(sec_compact(1, both), "USD")
        self.assertEqual(cash["concepts"]["capex"], hc.CAPEX_TAG)
        self.assertEqual(cash["annual"]["capex"]["2025-12-31"], (70, False))

    def test_newer_tag_first_older_one_fills(self):
        old = [("2024-01-01", "2024-03-31", 7, "10-Q"), ("2024-01-01", "2024-12-31", 30, "10-K")]
        cash = fs.cash_flow(sec_compact(1, {self.OCF: self.YEAR, hc.CAPEX_TAG: old,
                                            "PaymentsToAcquireProductiveAssets": self.YEAR}), "USD")
        self.assertEqual(cash["concepts"]["capex"], "PaymentsToAcquireProductiveAssets")
        self.assertEqual(cash["annual"]["capex"]["2024-12-31"], (30, False))

    def test_20f_filer_has_no_cash_quarters(self):
        rows = [("2025-01-01", "2025-12-31", 70, "20-F")]
        self.assertEqual(fs.cash_flow(sec_compact(1, {self.OCF: rows, hc.CAPEX_TAG: rows}), "USD"), {})


class DartReports(unittest.TestCase):
    def setUp(self):
        self.p = fd.periods(DART, "KRW")

    def test_q4_eps_is_fy_minus_nine_months(self):
        eps = dict(self.p["quarterly"]["eps_diluted"][0][1])
        self.assertEqual(eps["2025-12-31"], (21528.0, True))             # 60,378 - 38,850 (DART), not 21,537
        self.assertEqual(eps["2025-09-30"], (17850.0, False))
        ni = dict(self.p["quarterly"]["net_income"][0][1])
        self.assertEqual(ni["2025-12-31"], (15219783000000.0, True))

    def test_older_years_from_the_comparative_columns(self):
        revenue = dict(self.p["annual"]["revenue"][0][1])
        self.assertEqual(sorted(revenue), ["2023-12-31", "2024-12-31", "2025-12-31"])

    def test_shares_of_all_classes(self):
        shares = dict(self.p["balances"]["shares"][0][1])
        self.assertEqual(shares["2025-12-31"], 701691520.0)

    def test_cash_flow_is_year_to_date(self):
        cash = self.p["cash"]
        # Q4 25 = FY 53,373,126 - 9M 32,511,390 (KRW mn; SK Hynix's filings); capex = 27,518,924 - 15,648,350
        self.assertEqual(cash["quarterly"]["ocf"]["2025-12-31"], (20861736000000.0, True))
        self.assertEqual(cash["quarterly"]["capex"]["2025-12-31"], (11870574000000.0, True))
        self.assertNotIn("2025-09-30", cash["quarterly"]["ocf"])        # 9M - H1: the 2025 half year is not here
        self.assertNotIn("2026-06-30", cash["quarterly"]["ocf"])        # H1 - Q1: the 2026 Q1 report is not here
        self.assertEqual(cash["annual"]["ocf"]["2025-12-31"], (53373126000000.0, False))
        self.assertEqual(cash["annual"]["ocf"]["2024-12-31"], (29795885000000.0, False))   # comparative column

    def test_capex_sign_varies_by_filer(self):
        dart = copy.deepcopy(DART)
        for row in dart["reports"]["2025-11011"]["rows"]:
            if row[0] == "CF" and "PurchaseOfPropertyPlantAndEquipment" in row[1]:
                row[3] = "-" + row[3]
        cash = fd.periods(dart, "KRW")["cash"]
        self.assertEqual(cash["quarterly"]["capex"]["2025-12-31"], (11870574000000.0, True))

    def test_compose_uses_dart_cash_flow(self):
        q4 = {"2025-12-31": {"revenue": 1.0}}
        years = {"2025-12-31": {"revenue": 4.0}}
        marks_q, marks_y = {}, {}
        used = fin.apply_cash_flow(q4, years, marks_q, marks_y, [("SEC", {}), ("DART", self.p["cash"])])
        fin.finish_cash_flow(q4, marks_q)
        self.assertEqual(used, "DART")
        self.assertEqual((q4["2025-12-31"]["ocf"], q4["2025-12-31"]["capex"], q4["2025-12-31"]["fcf"]),
                         (20861736.0, 11870574.0, 8991162.0))
        self.assertEqual(marks_q["2025-12-31"], {"ocf", "capex", "fcf"})
        self.assertIsNone(q4["2025-12-31"]["fcf_after_leases"])        # no finance-lease figure in DART

    def test_older_report_is_read_again_for_its_cash_flow(self):
        # a report cached before 2026-10-17 has no cash-flow rows: read once more, its share counts kept
        cache = copy.deepcopy(DART)
        cache["reports"] = {"2025-11014": cache["reports"]["2025-11014"]}
        answer = {"status": "000", "list": [
            {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
             "account_nm": "영업활동 현금흐름", "thstrm_amount": "32,511,390,000,000", "currency": "KRW"}]}
        calls = []

        def fake_call(endpoint, binary=False, **params):
            calls.append(endpoint)
            return answer if endpoint == "fnlttSinglAcntAll.json" else None

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(fd, "CACHE_DIR", Path(tmp)), \
                mock.patch.object(fd, "call", fake_call), \
                mock.patch.object(fd, "load_env", lambda: None), \
                mock.patch.dict(fd.os.environ, {"DART_API_KEY": "test"}), \
                mock.patch.object(fd, "wanted_reports", lambda now: [("2025", "11014", 3, "2025-09-30")]):
            fd.write_json(fd.cache_path(cache["corp_code"]), cache)
            out = fd.fetch(cache["corp_code"], FIXED_TODAY)
            again = fd.fetch(cache["corp_code"], FIXED_TODAY)
        report = out["reports"]["2025-11014"]
        self.assertEqual(report["format"], fd.REPORT_FORMAT)
        self.assertEqual(report["shares"], DART["reports"]["2025-11014"]["shares"])
        self.assertEqual(calls.count("fnlttSinglAcntAll.json"), 1)    # once, not again on the second run
        self.assertNotIn("stockTotqySttus.json", calls)
        self.assertEqual(again["reports"]["2025-11014"]["format"], fd.REPORT_FORMAT)

    def test_preliminary_results_page(self):
        parsed = fd.parse_preliminary(fixture_text("dart_preliminary_samsung_like.html"))
        self.assertEqual((parsed["start"], parsed["end"], parsed["unit"]), ("2026-07-01", "2026-09-30", 1e12))
        self.assertEqual(parsed["values"], {"revenue": 195e12, "operating_income": 107.4e12})

    def test_preliminary_of_a_reported_quarter_is_not_shown(self):
        self.assertIsNone(fd.preliminary(DART))                          # Q2 26 already has its half-year report

    def test_preliminary_replaces_a_summary_only_column(self):
        # LG Electronics-like: Yahoo's summary has the new quarter's revenue (earnings not out yet), DART the
        # preliminary results: one "(P)" column, not a summary column next to it
        dart = {"reports": {"2026-11012": {"year": 2026, "quarter": 2, "end": "2026-05-31", "rows": []}},
                "preliminary": {"20260905800001": {"filed": "20260905", "consolidated": True, "start": "2026-06-01",
                                                   "end": "2026-08-31", "values": {"revenue": 54000e6,
                                                                                   "operating_income": 41000e6}}}}
        data = fin.compose("Micron", copy.deepcopy(RAW), [], filings={"dart": dart})
        self.assertNotIn("Q4 26", by_label(data["quarterly"]))
        pre = data["preliminary"]
        self.assertEqual((pre["label"], pre["end"], pre["filed"]), ("Q4 26", "2026-08-31", "2026-09-05"))
        self.assertEqual((pre["revenue"], pre["operating_income"], pre["net_income"]), (54000.0, 41000.0, 37701.0))
        self.assertEqual(pre["qoq"]["revenue"], 30.26)                   # vs Q3 26's 41,456

    def test_korean_share_basis(self):
        # Samsung-like: Yahoo's count jumps between common-only and common + preferred
        balances = {"2025-06-30": {"shares": 5876.7e6}, "2025-09-30": {"shares": 5828.2e6},
                    "2025-12-31": {"shares": 6630.2e6}}
        changed = fin.korean_share_basis(balances, {"2025-06-30": 6686.0e6, "2025-12-31": 6630.2e6})
        self.assertEqual(changed, ["2025-06-30", "2025-09-30"])
        self.assertAlmostEqual(balances["2025-09-30"]["shares"] / 1e6, 6658.0, delta=1)   # interpolated

    def test_wanted_reports(self):
        wanted = fd.wanted_reports(FIXED_TODAY)
        self.assertIn(("2026", "11014", 3, "2026-09-30"), wanted)        # Q3 26: may be filed early
        self.assertIn(("2023", "11014", 3, "2023-09-30"), wanted)        # the YoY base of the oldest shown quarter
        self.assertNotIn(("2023", "11013", 1, "2023-03-31"), wanted)


class Splits(unittest.TestCase):
    SPLITS = [("2023-03-30", 3.0), ("2026-09-29", 5.0)]           # Tokyo Electron-like

    def test_statement_filed_before_the_newest_split(self):
        later = fin.later_splits(self.SPLITS, "2026-03-31")
        self.assertEqual(fin.split_adjustment(459e6, later, 2270e6), 5.0)

    def test_restated_after_the_older_split_only(self):
        later = fin.later_splits(self.SPLITS, "2022-03-31")       # both splits are later
        self.assertEqual(fin.split_adjustment(469e6, later, 2270e6), 5.0)

    def test_already_adjusted(self):
        later = fin.later_splits([("2024-06-10", 10.0)], "2024-01-31")   # NVIDIA-like: Yahoo restated it
        self.assertEqual(fin.split_adjustment(25.0e9, later, 24.1e9), 1.0)


class Growth(unittest.TestCase):
    def test_pct_change(self):
        self.assertEqual(fin.pct_change(41456.0, 23860.0), 73.75)
        self.assertIsNone(fin.pct_change(5.0, -3.0))                 # from a loss: no meaningful %
        self.assertIsNone(fin.pct_change(5.0, 0.0))
        self.assertIsNone(fin.pct_change(None, 3.0))
        self.assertIsNone(fin.pct_change_positive(-5.0, 3.0))       # FCF: only between two positive values
        self.assertEqual(fin.pct_change_positive(6.0, 3.0), 100.0)


class MicronLike(unittest.TestCase):
    def setUp(self):
        self.data = fin.compose("Micron", copy.deepcopy(RAW), [])
        self.q = by_label(self.data["quarterly"])
        self.a = by_label(self.data["annual"])

    def test_contract_shape(self):
        d = self.data
        self.assertEqual(d["ticker"], "MU")
        self.assertEqual(d["currency"], "USD")
        self.assertEqual(d["unit"], 1000000)
        self.assertEqual(d["fiscal_year_end"], "09-03")
        self.assertEqual(d["updated"], "2026-10-17")
        for row in d["quarterly"] + d["annual"]:
            self.assertEqual(tuple(row), fin.PERIOD_KEYS)
        self.assertEqual([r["label"] for r in d["quarterly"]], ["Q3 25", "Q4 25", "Q1 26", "Q2 26", "Q3 26", "Q4 26"])

    def test_exact_period_ends_like_the_screenshot(self):
        # the user's screenshot: 2024.08.29 / 2025.08.28 / 2026.09.03 (Micron: the Thursday nearest August 31)
        self.assertEqual([r["end"] for r in self.data["annual"]], ["2024-08-29", "2025-08-28", "2026-09-03"])
        self.assertEqual(self.q["Q3 26"]["end"], "2026-05-28")
        self.assertEqual(self.q["Q4 26"]["end"], "2026-09-03")

    def test_screenshot_revenue(self):
        self.assertEqual([self.a[k]["revenue"] for k in ("FY24", "FY25", "FY26")], [25111.0, 37378.0, 133188.0])

    def test_lagging_statements_filled_from_the_summary(self):
        q4 = self.q["Q4 26"]
        # EPS: net income / the previous quarter's diluted shares (37,701 / 1,145); with the 10-K it is 32.87
        self.assertEqual((q4["revenue"], q4["net_income"], q4["eps_diluted"]), (54229.0, 37701.0, 32.9266))
        self.assertEqual(q4["derived"], ["eps_diluted", "net_income", "revenue"])
        self.assertIsNone(q4["ebit"])                                # not in the summary: blank until Yahoo has it
        fy26 = self.a["FY26"]
        self.assertEqual((fy26["net_income"], fy26["eps_diluted"]), (84969.0, 74.33))
        self.assertTrue(any("earnings summary" in n for n in self.data["notes"]))

    def test_per_pbr_roa_dividend_yield(self):
        q3 = self.q["Q3 26"]
        self.assertEqual(q3["per"], 21.98)                 # 971 / (2.83 + 4.60 + 12.07 + 24.67)
        self.assertEqual(q3["pbr"], 12.08)                 # 971 / (90,000 mn / 1,120 mn shares)
        self.assertEqual(q3["roa_pct"], 50.47)             # 50,469 / avg(120,000, 80,000)
        self.assertEqual(q3["dividend_yield_pct"], 0.05)   # 4 x 0.115 / 971
        self.assertEqual(self.q["Q4 26"]["per"], 12.91)    # 958.73 / (4.60 + 12.07 + 24.67 + 32.93)
        self.assertEqual(self.q["Q4 26"]["pbr"], 7.84)     # book value per share from key statistics (122.35)
        fy25 = self.a["FY25"]
        self.assertEqual(fy25["per"], 15.67)               # 118.9 / 7.59
        self.assertEqual(fy25["roa_pct"], 11.22)           # 8,539 / avg(82,800, 69,416)
        self.assertEqual(fy25["dividend_yield_pct"], 0.39)
        self.assertIsNone(self.q["Q3 25"]["per"])          # fewer than 4 quarters of EPS before it

    def test_qoq_yoy(self):
        q3 = self.q["Q3 26"]
        self.assertEqual(q3["qoq"]["revenue"], 73.75)
        self.assertEqual(q3["yoy"]["revenue"], 345.72)
        self.assertEqual(q3["yoy"]["eps_diluted"], 1368.45)
        self.assertIsNone(self.q["Q3 25"]["yoy"]["revenue"])
        self.assertIsNone(self.a["FY26"]["qoq"])
        self.assertEqual(self.a["FY26"]["yoy"]["revenue"], 256.33)

    def test_estimates(self):
        est = self.data["estimates"]
        self.assertEqual((est["quarter"]["label"], est["quarter"]["end"]), ("Q1 27", "2026-12-03"))
        self.assertEqual(est["quarter"]["revenue_avg"], 61744.34)          # full dollars -> millions
        self.assertEqual(est["quarter"]["eps_avg"], 38.2786)
        self.assertEqual(est["quarter"]["revenue_growth_pct"], 352.57)
        self.assertEqual(est["quarter"]["eps_analysts"], 30)
        self.assertEqual((est["fy"]["label"], est["next_fy"]["label"]), ("FY27", "FY28"))
        self.assertEqual((est["fy"]["end"], est["next_fy"]["end"]), ("2027-09-02", "2028-08-31"))

    def test_stale_estimate_is_dropped(self):
        raw = copy.deepcopy(RAW)
        raw["summary"]["earningsTrend"]["trend"][0]["endDate"] = "2026-08-31"   # an already reported quarter
        self.assertIsNone(fin.compose("Micron", raw, [])["estimates"]["quarter"])

    def test_history_fills_a_quarter_yahoo_dropped(self):
        hist = [{"company": "Micron", "period_type": "quarterly", "end": "2025-02-28", "revenue": 8709.0,
                 "net_income": 1583.0, "eps_diluted": 1.41}]
        q = by_label(fin.compose("Micron", copy.deepcopy(RAW), hist)["quarterly"])
        self.assertEqual(q["Q2 25"]["revenue"], 8709.0)
        self.assertEqual(q["Q2 26"]["yoy"]["revenue"], 173.97)          # (23,860 - 8,709) / 8,709
        self.assertEqual(q["Q1 26"]["per"], 22.81)                     # 240 / (4.60 + 2.83 + 1.68 + 1.41)

    def test_adr_in_another_currency_has_no_per(self):
        raw = copy.deepcopy(RAW)
        raw["timeseries"]["currency"] = "TWD"
        data = fin.compose("Some ADR", raw, [])          # symbol MU: a US line
        self.assertIsNone(by_label(data["quarterly"])["Q3 26"]["per"])
        self.assertEqual(by_label(data["quarterly"])["Q3 26"]["dividend_yield_pct"], 0.05)   # same-currency ratio

    def test_home_currency_price_is_converted(self):
        raw = copy.deepcopy(RAW)
        raw["timeseries"]["currency"] = "CNY"
        raw["symbol"], raw["chart"]["currency"] = "0700.HK", "HKD"       # a Hong Kong listing reporting in CNY
        fx = lambda a, b: {"2026-05": 0.9} if (a, b) == ("HKD", "CNY") else None
        q3 = by_label(fin.compose("HK co", raw, [], fx)["quarterly"])["Q3 26"]
        self.assertEqual(q3["per"], round(971 * 0.9 / 44.17, 2))


class YahooCashFlow(unittest.TestCase):
    """A company without SEC 10-K / 10-Q or DART cash flow: Yahoo's rows (Capital Expenditure is negative there)."""
    ENDS = ["2025-05-31", "2025-08-31", "2025-11-30", "2026-02-28", "2026-05-31"]
    OCF = [4609e6, 5730e6, 8411e6, 11903e6, 25388e6]
    CAPEX = [-2938e6, -6000e6, -5389e6, -6387e6, -7826e6]               # Q4 25: a negative free cash flow

    def compose(self, filings=None, drop_capex_at=None):
        raw = copy.deepcopy(RAW)
        q, a = raw["timeseries"]["quarterly"], raw["timeseries"]["annual"]
        q["OperatingCashFlow"] = dict(zip(self.ENDS, self.OCF))
        q["CapitalExpenditure"] = dict(zip(self.ENDS, self.CAPEX))
        q["FreeCashFlow"] = {e: o + c for e, o, c in zip(self.ENDS, self.OCF, self.CAPEX)}
        if drop_capex_at:
            del q["CapitalExpenditure"][drop_capex_at]
        a["OperatingCashFlow"], a["CapitalExpenditure"] = {"2025-08-31": 17525e6}, {"2025-08-31": -15857e6}
        data = fin.compose("Micron", raw, [], filings=filings)
        return data, by_label(data["quarterly"]), by_label(data["annual"])

    def test_capex_positive_and_fcf(self):
        data, q, a = self.compose()
        self.assertEqual((q["Q3 26"]["ocf"], q["Q3 26"]["capex"], q["Q3 26"]["fcf"]), (25388.0, 7826.0, 17562.0))
        self.assertEqual(q["Q4 25"]["fcf"], -270.0)
        self.assertEqual((a["FY25"]["capex"], a["FY25"]["fcf"]), (15857.0, 1668.0))
        self.assertIsNone(q["Q3 26"]["fcf_after_leases"])               # Yahoo has no finance-lease figure
        self.assertIsNone(q["Q4 26"]["ocf"])                            # summary-only quarter: no cash flow yet
        self.assertEqual(q["Q3 26"]["derived"], [])
        self.assertTrue(any(n.startswith("Cash flow from Yahoo Finance") for n in data["notes"]))

    def test_fcf_growth_only_between_positive_values(self):
        _, q, _ = self.compose()
        self.assertIsNone(q["Q4 25"]["qoq"]["fcf"])                     # to a negative
        self.assertIsNone(q["Q1 26"]["qoq"]["fcf"])                     # from a negative
        self.assertEqual(q["Q2 26"]["qoq"]["fcf"], 82.53)               # 5,516 vs 3,022
        self.assertEqual(q["Q3 26"]["yoy"]["fcf"], 950.99)              # 17,562 vs 1,671

    def test_yahoo_free_cash_flow_where_capex_is_missing(self):
        _, q, _ = self.compose(drop_capex_at="2026-02-28")
        self.assertEqual((q["Q2 26"]["capex"], q["Q2 26"]["fcf"]), (None, 5516.0))

    def test_filings_without_cash_facts_keep_yahoo(self):
        data, q, _ = self.compose(filings={"sec": SEC})                 # the SEC fixture has no cash-flow facts
        self.assertEqual(q["Q3 26"]["ocf"], 25388.0)
        self.assertTrue(any(n.startswith("Cash flow from Yahoo Finance") for n in data["notes"]))


class Snapshots(unittest.TestCase):
    def test_rows_are_the_reported_statements(self):
        stmt = fin.statement_periods(RAW["timeseries"])
        rows = fin.snapshot_rows("Micron", "MU", "USD", stmt, FIXED_TODAY)
        self.assertEqual(len(rows), 7)                                   # 5 quarters + 2 years, nothing derived
        q3 = next(r for r in rows if r["end"] == "2026-05-31")
        self.assertEqual((q3["period_type"], q3["revenue"], q3["eps_diluted"], q3["total_assets"]),
                         ("quarterly", 41456.0, 24.67, 120000.0))


class DueToday(unittest.TestCase):
    def test_order_and_rotation(self):
        today_bucket = fin.dt.date.fromisoformat(FIXED_TODAY).toordinal() % fin.ROTATION_DAYS
        other = next(f"E{i}" for i in range(100) if fin.rotation_bucket(f"E{i}") != today_bucket)
        match = next(f"F{i}" for i in range(100) if fin.rotation_bucket(f"F{i}") == today_bucket)
        tg = {k: {"degree": d} for k, d in (("A", 9), ("B", 1), ("C", 1), ("D", 1), (other, 1), (match, 1), ("G", 1))}
        state = {"A": {"fetched": FIXED_TODAY}, "C": {"fetched": "2026-10-09"},          # missed its weekly day
                 "D": {"fetched": "2026-10-16", "earnings_date": "2026-10-20"},
                 other: {"fetched": "2026-10-16"}, match: {"fetched": "2026-10-15"},
                 "G": {"fetched": "2026-10-16", "earnings_date": "2026-10-14"}}      # reported 3 days ago
        due = fin.due_companies(tg, state, {}, FIXED_TODAY)
        self.assertEqual(due[:3], ["D", "G", "B"])                       # earnings window, then never fetched
        self.assertEqual(set(due[3:]), {"C", match})                     # over a week old, and today's 1/7
        self.assertNotIn("A", due)
        self.assertEqual(fin.due_companies(tg, state, {}, FIXED_TODAY, backfill=True)[0], "A")   # by degree


class Build(TempDataTestCase):
    PATCHED_MODULES = (fin,)

    def setUp(self):
        super().setUp()
        cache = self.tmp / "cache"
        for module, name, value in ((fin, "CACHE", cache), (fs, "CACHE_DIR", cache / "sec"),
                                    (fd, "CACHE_DIR", cache / "dart")):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(fs, "cached_cik_map", lambda: {})
        patcher.start()
        self.addCleanup(patcher.stop)
        nodes = [{"id": "Micron", "ticker": "MU", "exchange": "NASDAQ", "status": "public"},
                 {"id": "Kept Co", "ticker": "KEPT", "exchange": "NYSE", "status": "public"},
                 {"id": "Private Co", "status": "private"}]
        (self.graph / "merged_graph.json").write_text(json.dumps({"nodes": nodes, "edges": []}), encoding="utf-8")
        (self.history / fin.STATE_FILE_NAME).write_text(json.dumps(
            {"Micron": {"symbol": "MU", "fetched": FIXED_TODAY, "ok": True}}), encoding="utf-8")
        fin.write_json(fin.cache_path("MU"), RAW)
        out = self.graph / "financials"
        out.mkdir()
        (out / "kept-co.json").write_text(json.dumps({"company": "Kept Co", "currency": "USD",
                                                      "quarterly": [{"end": "2026-06-30"}], "annual": []}),
                                          encoding="utf-8")
        (out / "gone.json").write_text("{}", encoding="utf-8")

    def test_index_and_files(self):
        index = quietly(fin.build)
        self.assertEqual(index["Micron"], {"file": "micron.json", "latest_end": "2026-09-03", "currency": "USD"})
        self.assertEqual(index["Kept Co"]["latest_end"], "2026-06-30")   # no cache here: its file is kept
        self.assertFalse((self.graph / "financials" / "gone.json").exists())
        written = self.read_graph("financials_index.json")
        self.assertEqual(set(written), {"updated", "source", "companies"})
        self.assertEqual(written["source"]["name"], "Yahoo Finance")
        micron = self.read_graph("financials/micron.json")
        self.assertEqual(by_label(micron["annual"])["FY26"]["revenue"], 133188.0)

    def test_unchanged_file_is_not_rewritten(self):
        quietly(fin.build)
        path = self.graph / "financials" / "micron.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(fin.write_company_file(path, data))


# Yahoo's earningsChart "actual" (the adjusted EPS, Micron-like) for the fixture's four quarters Q1 26 - Q4 26.
ADJ_ACTUALS = {"1Q2026": 4.78, "2Q2026": 12.20, "3Q2026": 25.11, "4Q2026": 33.42}


def with_adjusted(raw, actuals=ADJ_ACTUALS, fy_year_ago=None):
    """The fixture with Yahoo's adjusted EPS actuals (earningsChart) and, optionally, the 0y entry's year-ago EPS
    (Yahoo's own figure for the last fiscal year, FY26 here)."""
    raw = copy.deepcopy(raw)
    for q in raw["summary"]["earnings"]["earningsChart"]["quarterly"]:
        if q["fiscalQuarter"] in actuals:
            q["actual"] = actuals[q["fiscalQuarter"]]
    if fy_year_ago is not None:
        for t in raw["summary"]["earningsTrend"]["trend"]:
            if t["period"] == "0y":
                t["earningsEstimate"]["yearAgoEps"] = fy_year_ago
    return raw


def adj_row(end, value, seen="2026-07-01", period_type="quarterly", currency="USD"):
    """One market/history/financials_eps_adjusted.jsonl row of the Micron-like company."""
    return {"seen": seen, "company": "Micron", "ticker": "MU", "period_type": period_type, "end": end,
            "eps_adjusted": value, "currency": currency}


class AdjustedEps(unittest.TestCase):
    """The user (2026-10-17): "재무재표는 조정, gaap, net income 다 볼 수 있게": net income, GAAP EPS and adjusted EPS,
    each with its own QoQ / YoY; the adjusted series is kept past Yahoo's 4-quarter window by the history."""

    def compose(self, raw=None, adj_rows=()):
        data = fin.compose("Micron", raw or with_adjusted(RAW), [], adj_rows=list(adj_rows))
        return data, by_label(data["quarterly"]), by_label(data["annual"])

    def test_gaap_and_adjusted_side_by_side_with_their_own_growth(self):
        data, q, _ = self.compose()
        q3 = q["Q3 26"]
        self.assertEqual((q3["net_income"], q3["eps_diluted"], q3["eps_adjusted"]), (28243.0, 24.67, 25.11))
        self.assertEqual(q3["qoq"]["eps_diluted"], 104.39)              # 24.67 vs 12.07: GAAP vs GAAP
        self.assertEqual(q3["qoq"]["eps_adjusted"], 105.82)             # 25.11 vs 12.20: adjusted vs adjusted
        self.assertEqual(q3["qoq"]["net_income"], 104.88)
        self.assertEqual(q3["yoy"]["eps_diluted"], 1368.45)
        self.assertIsNone(q3["yoy"]["eps_adjusted"])                    # Q3 25 adjusted unknown: never GAAP instead
        self.assertIsNone(q["Q1 26"]["qoq"]["eps_adjusted"])            # Q4 25 adjusted unknown
        self.assertIsNone(q["Q4 25"]["eps_adjusted"])
        for row in data["quarterly"] + data["annual"]:
            self.assertEqual(tuple(row), fin.PERIOD_KEYS)
        self.assertTrue(any("EPS (adjusted)" in n and "(E) consensus" in n for n in data["notes"]))

    def test_annual_is_yahoos_figure_else_the_sum_of_four_quarters(self):
        _, _, a = self.compose()
        self.assertEqual(a["FY26"]["eps_adjusted"], 75.51)              # 4.78 + 12.20 + 25.11 + 33.42
        self.assertIn("eps_adjusted", a["FY26"]["derived"])
        self.assertIsNone(a["FY25"]["eps_adjusted"])                    # its quarters are unknown: blank
        _, _, a = self.compose(with_adjusted(RAW, fy_year_ago=75.52))    # Yahoo's own FY26 figure wins
        self.assertEqual(a["FY26"]["eps_adjusted"], 75.52)
        self.assertNotIn("eps_adjusted", a["FY26"]["derived"])
        three = {k: v for k, v in ADJ_ACTUALS.items() if k != "1Q2026"}
        _, _, a = self.compose(with_adjusted(RAW, three))               # three of four quarters: no sum
        self.assertIsNone(a["FY26"]["eps_adjusted"])

    def test_history_keeps_quarters_yahoo_dropped(self):
        rows = [adj_row("2024-11-30", 1.79, "2025-03-01"), adj_row("2025-02-28", 1.56, "2025-06-01"),
                adj_row("2025-05-31", 1.91), adj_row("2025-08-31", 3.03),
                adj_row("2026-05-31", 99.0),                             # Yahoo still lists Q3 26: its figure wins
                dict(adj_row("2025-08-31", 7.0), company="Other Co")]    # another company's row is ignored
        _, q, a = self.compose(adj_rows=rows)
        self.assertEqual((q["Q3 25"]["eps_adjusted"], q["Q4 25"]["eps_adjusted"]), (1.91, 3.03))
        self.assertEqual(q["Q3 26"]["eps_adjusted"], 25.11)
        self.assertEqual(q["Q3 26"]["yoy"]["eps_adjusted"], 1214.66)    # 25.11 vs the recorded 1.91
        self.assertEqual(q["Q1 26"]["qoq"]["eps_adjusted"], 57.76)      # 4.78 vs the recorded 3.03
        self.assertEqual(a["FY25"]["eps_adjusted"], 8.29)               # all four FY25 quarters recorded
        self.assertEqual(a["FY26"]["yoy"]["eps_adjusted"], 810.86)      # 75.51 vs 8.29
        self.assertNotIn("eps_adjusted", q["Q3 25"]["derived"])         # as recorded, not computed

    def test_history_figure_before_a_later_split_is_put_on_todays_basis(self):
        rows = [adj_row("2025-05-31", 3.82, seen="2026-06-01"), adj_row("2025-08-31", 3.03, seen="2026-07-15")]
        q, _, resplit = fin.adjusted_series({}, rows, "USD", [("2026-07-01", 2.0)])
        self.assertEqual(q, {"2025-05-31": 1.91, "2025-08-31": 3.03})   # only the one seen before the split
        self.assertEqual(resplit, {("quarterly", "2025-05-31")})

    def test_yahoo_eps_in_another_currency_is_not_shown(self):
        raw = with_adjusted(RAW)
        for t in raw["summary"]["earningsTrend"]["trend"]:
            t["earningsEstimate"]["earningsCurrency"] = "TWD"           # like 6805.TW / HYFT: USD for TWD / CAD
        data, q, _ = self.compose(raw, [adj_row("2025-05-31", 1.91, currency="TWD")])
        self.assertTrue(all(r["eps_adjusted"] is None for r in data["quarterly"] + data["annual"]))
        self.assertTrue(any("left blank" in n for n in data["notes"]))
        self.assertEqual(q["Q3 26"]["eps_diluted"], 24.67)               # the reported EPS is not affected

    def test_history_rows_of_one_answer(self):
        rows = fin.adjusted_rows("Micron", with_adjusted(RAW, fy_year_ago=75.52), FIXED_TODAY)
        self.assertEqual([(r["period_type"], r["end"], r["label"], r["eps_adjusted"]) for r in rows],
                         [("quarterly", "2025-11-30", "Q1 26", 4.78), ("quarterly", "2026-02-28", "Q2 26", 12.2),
                          ("quarterly", "2026-05-31", "Q3 26", 25.11), ("quarterly", "2026-08-31", "Q4 26", 33.42),
                          ("annual", "2026-08-31", "FY26", 75.52)])
        self.assertEqual({(r["seen"], r["company"], r["ticker"], r["currency"]) for r in rows},
                         {(FIXED_TODAY, "Micron", "MU", "USD")})
        self.assertEqual(fin.adjusted_rows("Micron", RAW, FIXED_TODAY), [])   # no actuals: nothing to record


class AdjustedHistoryRun(TempDataTestCase):
    """The daily run records the adjusted EPS it sees (ADD-only), also from the older cache it replaces, and the
    web file is built from that history."""
    PATCHED_MODULES = (fin,)

    def setUp(self):
        super().setUp()
        cache = self.tmp / "cache"
        for module, name, value in ((fin, "CACHE", cache), (fs, "CACHE_DIR", cache / "sec"),
                                    (fd, "CACHE_DIR", cache / "dart"), (fs, "cached_cik_map", lambda: {}),
                                    (fin, "refresh_filings", lambda *a, **k: {"sec": 0, "dart": 0, "errors": 0})):
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        nodes = [{"id": "Micron", "ticker": "MU", "exchange": "NASDAQ", "status": "public"}]
        (self.graph / "merged_graph.json").write_text(json.dumps({"nodes": nodes, "edges": []}), encoding="utf-8")
        # last week's cache still listed Q4 25 (3.03), which today's answer no longer has
        old = with_adjusted(RAW, {"4Q2026": 33.0})
        old["fetched"] = "2026-10-10"
        old["summary"]["earnings"]["earningsChart"]["quarterly"].insert(
            0, {"fiscalQuarter": "4Q2025", "periodEndDate": 1756598400, "actual": 3.03})     # 2025-08-31
        fin.write_json(fin.cache_path("MU"), old)
        self.new = with_adjusted(RAW)

    def run_once(self):
        with mock.patch.object(fin, "fetch_company", lambda symbol: copy.deepcopy(self.new)):
            self.assertTrue(quietly(fin.run, only=["Micron"]))
        path = self.history / f"{fin.ADJ_DATASET}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_recorded_and_used(self):
        rows = self.run_once()
        got = {(r["period_type"], r["end"]): (r["eps_adjusted"], r["seen"]) for r in rows}
        self.assertEqual(got[("quarterly", "2025-08-31")], (3.03, "2026-10-10"))   # kept from the older cache
        self.assertEqual(got[("quarterly", "2026-08-31")], (33.0, "2026-10-10"))   # the first sighting stays
        self.assertEqual(got[("quarterly", "2026-05-31")], (25.11, FIXED_TODAY))
        self.assertEqual(len(rows), 5)
        q = by_label(self.read_graph("financials/micron.json")["quarterly"])
        self.assertEqual(q["Q4 25"]["eps_adjusted"], 3.03)                       # gone from Yahoo, still shown
        self.assertEqual(q["Q4 26"]["eps_adjusted"], 33.42)                      # today's answer wins
        self.assertEqual(q["Q1 26"]["qoq"]["eps_adjusted"], 57.76)
        self.assertEqual(len(self.run_once()), 5)                                # ADD-only: a second run adds none


if __name__ == "__main__":
    unittest.main()
