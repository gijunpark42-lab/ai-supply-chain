"""hyperscaler_cash: turning SEC XBRL cash-flow facts into discrete quarters.

A 10-Q cash-flow statement is year-to-date, so Q2 = H1 - Q1, Q3 = 9M - H1 and Q4 = FY - 9M; a reported 3-month
fact is used as it is, and when a period is reported again the most recently FILED value wins.
The facts below are made up (same shape as the companyconcept API's "units" -> "USD" list).
"""
import unittest
from unittest import mock

from market import hyperscaler_cash as hc


def fact(start, end, val, filed, form="10-Q", accn="0000000000-26-000001"):
    """One XBRL fact in the companyconcept API's shape."""
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "accn": accn}


# A December fiscal year: FY2025, then 2026's Q1 (3 months), H1 and 9M (year-to-date).
FACTS = [
    fact("2025-01-01", "2025-09-30", 430, "2025-10-30"),                  # 9M 2025
    fact("2025-01-01", "2025-12-31", 600, "2026-02-01", form="10-K"),     # FY 2025
    fact("2026-01-01", "2026-03-31", 100, "2026-04-30"),                  # Q1 2026
    fact("2026-01-01", "2026-06-30", 250, "2026-07-30"),                  # H1 2026
    fact("2026-01-01", "2026-09-30", 420, "2026-10-29"),                  # 9M 2026
    {"end": "2026-09-30", "val": 999, "filed": "2026-10-29"},             # an instant fact (no start): ignored
]


class DiscreteQuarters(unittest.TestCase):
    def setUp(self):
        self.q = hc.discrete_quarters(FACTS)

    def test_q1_is_the_three_month_fact(self):
        self.assertEqual(self.q["2026-03-31"]["val"], 100)
        self.assertEqual(self.q["2026-03-31"]["start"], "2026-01-01")

    def test_q2_is_h1_minus_q1(self):
        self.assertEqual(self.q["2026-06-30"]["val"], 150)
        self.assertEqual(self.q["2026-06-30"]["start"], "2026-04-01")

    def test_q3_is_9m_minus_h1(self):
        self.assertEqual(self.q["2026-09-30"]["val"], 170)

    def test_q4_is_fy_minus_9m(self):
        self.assertEqual(self.q["2025-12-31"]["val"], 170)        # 600 - 430
        self.assertEqual(self.q["2025-12-31"]["start"], "2025-10-01")
        self.assertEqual(self.q["2025-12-31"]["fact"]["form"], "10-K")

    def test_nine_months_alone_is_not_a_quarter(self):
        self.assertNotIn("2025-09-30", self.q)                     # no H1 2025 fact to subtract

    def test_latest_filing_wins(self):
        restated = FACTS + [fact("2026-01-01", "2026-03-31", 110, "2027-04-29")]   # next year's comparative column
        q = hc.discrete_quarters(restated)
        self.assertEqual(q["2026-03-31"]["val"], 110)
        self.assertEqual(q["2026-06-30"]["val"], 140)              # H1 250 - restated Q1 110


class FiscalQuarter(unittest.TestCase):
    def test_june_fiscal_year(self):
        self.assertEqual(hc.fiscal_quarter(hc.day("2026-09-30"), 6), (2027, 1))   # Microsoft FY2027 Q1
        self.assertEqual(hc.fiscal_quarter(hc.day("2026-06-30"), 6), (2026, 4))

    def test_december_fiscal_year(self):
        self.assertEqual(hc.fiscal_quarter(hc.day("2026-03-31"), 12), (2026, 1))


class AmazonCapexTag(unittest.TestCase):
    """Amazon's capex is PaymentsToAcquireProductiveAssets (it does not tag ...PropertyPlantAndEquipment)."""

    def test_company_entry(self):
        amazon = next(c for c in hc.COMPANIES if c["id"] == "Amazon")
        self.assertEqual(amazon["capex"], "PaymentsToAcquireProductiveAssets")
        others = [c for c in hc.COMPANIES if c["id"] != "Amazon"]
        self.assertTrue(all("capex" not in c for c in others))     # everyone else uses the default tag

    def test_company_quarters_asks_for_amazons_tag(self):
        asked = []

        def fake_concept(cik, tag):                                # stands in for the SEC request
            asked.append(tag)
            return FACTS[:5] if tag != hc.LEASE_TAG else []

        amazon = next(c for c in hc.COMPANIES if c["id"] == "Amazon")
        with mock.patch.object(hc, "sec_concept", fake_concept):
            rows = hc.company_quarters(amazon, backfill=True)
        self.assertEqual(asked, ["PaymentsToAcquireProductiveAssets", hc.OCF_TAG, hc.LEASE_TAG])
        self.assertIn("capex=us-gaap:PaymentsToAcquireProductiveAssets", rows[0]["tags"])
        q2 = next(r for r in rows if r["end"] == "2026-06-30")
        self.assertEqual((q2["capex_usd"], q2["ocf_usd"], q2["lease_principal_usd"]), (150, 150, None))
        self.assertEqual(q2["fiscal"], "FY2026 Q2")


if __name__ == "__main__":
    unittest.main()
