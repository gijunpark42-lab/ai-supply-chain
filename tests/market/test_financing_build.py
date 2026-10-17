"""financing (the builder): which reports of one deal are shown once, and the build-time clean-ups.

Fixtures (real rows, copied from market/history/ on 2026-10-17):
  financing_history_us.jsonl   Google's three 2026-06-04 prospectuses (as first recorded, before the corrections)
                               and AMD's notes: the 424B5 at pricing (2026-08-14) and the 8-K at closing (2026-08-17)
  financing_history_jp.jsonl   SoftBank's four TDnet rows: two issues, one early repayment, one early redemption
  financing_corrections.jsonl  the 2026-10-17 corrections of Google's rows ($18B two-class share offering, Series
                               A / Series B names), from market/history/corrections.jsonl
"""
import copy
import unittest

import market.financing as financing
from tests.market.helpers import TempDataTestCase, fixture_jsonl, quietly


def corrected_google_rows():
    """Google's three prospectus rows with their corrections applied, keyed by the end of their URL."""
    rows = [r for r in fixture_jsonl("financing_history_us.jsonl") if r["company"] == "Google"]
    fixes = fixture_jsonl("financing_corrections.jsonl")
    out = {}
    for r in rows:
        r = dict(r)
        for c in fixes:
            if all(r.get(k) == v for k, v in c["match"].items()):
                r.update(c["set"])
        out[r["url"].rsplit("/", 1)[-1]] = r
    return out


class SameDeal(unittest.TestCase):
    """market.financing._same_deal decides when two rows are one deal reported twice."""

    def test_google_series_a_and_series_b_stay_separate(self):
        google = corrected_google_rows()
        series_a, series_b = google["d159942d424b5.htm"], google["d152175d424b5.htm"]
        self.assertIn("Series A", series_a["title"])
        self.assertIn("Series B", series_b["title"])
        self.assertFalse(financing._same_deal(series_a, series_b))

    def test_series_names_alone_keep_two_deals_apart(self):
        # Same day, type and amount; even if both were 8-Ks (so the "two prospectuses" rule does not apply),
        # different series numbers in the titles mean two deals.
        google = corrected_google_rows()
        a, b = copy.deepcopy(google["d159942d424b5.htm"]), copy.deepcopy(google["d152175d424b5.htm"])
        a["form"] = b["form"] = "8-K"
        a["url"], b["url"] = a["url"] + "#a", b["url"] + "#b"
        self.assertFalse(financing._same_deal(a, b))

    def test_pricing_prospectus_and_closing_8k_are_one_deal(self):
        amd = sorted((r for r in fixture_jsonl("financing_history_us.jsonl") if r["company"] == "AMD"),
                     key=lambda r: r["date"])
        self.assertEqual([r["form"] for r in amd], ["424B5", "8-K"])
        self.assertTrue(financing._same_deal(amd[0], amd[1]))

    def test_dollar_and_euro_tranches_are_two_deals(self):
        a = {"type": "debt", "currency": "USD", "date": "2026-06-18", "form": "8-K", "title": "$1B notes",
             "amount_usd": 1e9, "url": "u"}
        b = dict(a, currency="EUR", amount_usd=1.1e9)
        self.assertFalse(financing._same_deal(a, b))


class CleanRow(unittest.TestCase):
    """market.financing.clean: cash going OUT is shown, but never added to the money raised."""

    def test_repayment_becomes_other_without_usd(self):
        row = {"title": "Early Repayment of Bridge Loans, USD 25.9B", "type": "credit_facility",
               "amount": 25900000000, "currency": "USD", "amount_usd": 25900000000, "market": "JP",
               "date": "2026-09-09"}
        out = financing.clean(dict(row), {})
        self.assertEqual(out["type"], "other")
        self.assertIsNone(out["amount_usd"])
        self.assertEqual(out["amount"], 25900000000)          # the amount itself stays visible

    def test_redemption_becomes_other_without_usd(self):
        row = {"title": "Domestic unsecured convertible bonds (No. 2): early redemption", "type": "convertible",
               "amount": None, "currency": None, "amount_usd": None, "market": "TW", "date": "2026-07-28"}
        out = financing.clean(dict(row), {})
        self.assertEqual(out["type"], "other")
        self.assertIsNone(out["amount_usd"])

    def test_board_approval_keeps_amount_but_no_usd(self):
        # Nan Ya Plastics, MOPS 2026-03-11: the program; its issues are their own rows (no double count)
        row = {"title": "Unsecured straight bonds: board approval, TWD 10B", "type": "debt", "amount": 10000000000,
               "currency": "TWD", "amount_usd": 308375465, "market": "TW", "date": "2026-03-11"}
        out = financing.clean(dict(row), {})
        self.assertEqual(out["type"], "debt")
        self.assertEqual(out["amount"], 10000000000)
        self.assertIsNone(out["amount_usd"])

    def test_new_issue_is_untouched(self):
        row = {"title": "Issuance of Foreign Currency-Denominated Senior Notes, USD 11.1B", "type": "debt",
               "amount": 11100000000, "currency": "USD", "amount_usd": 11100000000, "market": "JP",
               "date": "2026-09-24"}
        self.assertEqual(financing.clean(dict(row), {}), row)


class FinancingBuild(TempDataTestCase):
    """A whole build (corrections, twins, clean-ups, one file per company) on the fixtures, in temp folders."""

    PATCHED_MODULES = (financing,)

    def setUp(self):
        super().setUp()
        self.put_history("financing_us", "financing_history_us.jsonl")
        self.put_history("financing_jp", "financing_history_jp.jsonl")
        self.put_history("corrections", "financing_corrections.jsonl")
        quietly(financing.build)
        self.index = self.read_graph("financing_index.json")

    def rows(self, company):
        return self.read_graph("financing/" + self.index["companies"][company]["file"])["rows"]

    def test_index(self):
        self.assertEqual(self.index["updated"], "2026-10-17")
        self.assertEqual(sorted(self.index["companies"]), ["AMD", "Google", "SoftBank"])
        self.assertEqual(self.index["companies"]["Google"], {"file": "google.json", "count": 3, "latest": "2026-06-04"})

    def test_google_three_deals_with_corrections_applied(self):
        rows = self.rows("Google")
        titles = sorted(r["title"] for r in rows)
        self.assertEqual(titles, ["$18B share offering",
                                  "$8.38B Series A mandatory convertible preferred stock",
                                  "$8.38B Series B mandatory convertible preferred stock"])
        equity = next(r for r in rows if r["type"] == "equity")
        self.assertEqual(equity["amount_usd"], 18000000123.0)    # not the $10B the first parser read

    def test_amd_pricing_and_closing_shown_once(self):
        rows = self.rows("AMD")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["form"], "8-K")                  # both have a number: the later report wins
        self.assertEqual(rows[0]["amount_usd"], 4750000000.0)

    def test_softbank_repayment_and_redemption_are_other_without_usd(self):
        rows = {r["title"]: r for r in self.rows("SoftBank")}
        for title in ("Early Repayment of Bridge Loans, USD 25.9B",
                      "Early Redemption of EUR-denominated Senior Notes Issued in 2021, EUR 405M"):
            self.assertEqual(rows[title]["type"], "other", title)
            self.assertIsNone(rows[title]["amount_usd"], title)
        issue = rows["Issuance of Foreign Currency-Denominated Senior Notes, USD 11.1B"]
        self.assertEqual(issue["type"], "debt")
        self.assertEqual(issue["amount_usd"], 11100000000)

    def test_rows_are_newest_first(self):
        dates = [r["date"] for r in self.rows("SoftBank")]
        self.assertEqual(dates, sorted(dates, reverse=True))


if __name__ == "__main__":
    unittest.main()
