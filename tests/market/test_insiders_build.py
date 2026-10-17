"""insiders (the builder): the web-file clean-ups of the 2026-10-17 verification, on real history rows.

Fixtures (real rows, copied from market/history/ on 2026-10-17):
  insiders_history_us.jsonl   Eli Lilly 2025-11-13..18 (Lilly Endowment sales; filing 0000316011-25-000073 prints
                              the prices 1031414 and 1032319 for $1,031.41 / $1,032.32), NRG Energy 2026-03-04 (one
                              block sale reported by LS Power and by David Nanus), CoreWeave 0001769628-26-000448,
                              a Nordson grant and a Microchip gift that both carry a price
  insiders_corrections.jsonl  the 2026-10-17 correction of CoreWeave 0001769628-26-000448 line N2 (sell-to-cover,
                              not a 10b5-1 plan sale), from market/history/corrections.jsonl
"""
import unittest

import market.insiders as insiders
from tests.market.helpers import TempDataTestCase, fixture_jsonl, quietly

LILLY_TYPO = "0000316011-25-000073"


class PriceGuard(unittest.TestCase):
    """check_prices: a price more than 20x away from the company's other prices of the same weeks is a typo."""

    def setUp(self):
        rows = [r for r in fixture_jsonl("insiders_history_us.jsonl") if r["node_id"] == "Eli Lilly"]
        self.before = {(r["accession"], r["line"]): r for r in rows}
        self.after = {(r["accession"], r["line"]): r for r in quietly(insiders.check_prices, rows, "insiders_us")}

    def test_typo_prices_lose_price_and_value(self):
        for line in ("N2", "N3"):
            self.assertGreater(self.before[(LILLY_TYPO, line)]["price"], 1_000_000)      # the raw typo
            self.assertIsNone(self.after[(LILLY_TYPO, line)]["price"])
            self.assertIsNone(self.after[(LILLY_TYPO, line)]["value"])
            self.assertEqual(self.after[(LILLY_TYPO, line)]["shares"], self.before[(LILLY_TYPO, line)]["shares"])

    def test_normal_prices_are_untouched(self):
        for key, row in self.before.items():
            if key not in ((LILLY_TYPO, "N2"), (LILLY_TYPO, "N3")):
                self.assertEqual(self.after[key], row, key)

    def test_history_rows_are_not_changed_in_place(self):
        self.assertEqual(self.before[(LILLY_TYPO, "N2")]["price"], 1031414)


class MergeLines(unittest.TestCase):
    def test_one_trade_split_by_fill_price_is_one_row(self):
        lines = [{"url": "u", "date": "2026-10-13", "insider": "A", "code": "S", "security": "Common", "shares": 100,
                  "price": 10.0, "value": 1000.0, "owned_after": 900, "plan_10b5_1": False},
                 {"url": "u", "date": "2026-10-13", "insider": "A", "code": "S", "security": "Common", "shares": 300,
                  "price": 11.0, "value": 3300.0, "owned_after": 600, "plan_10b5_1": True}]
        merged = insiders.merge_lines(lines)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["shares"], 400)
        self.assertEqual(merged[0]["value"], 4300.0)
        self.assertEqual(merged[0]["price"], 10.75)                 # share-weighted average
        self.assertEqual(merged[0]["owned_after"], 600)             # holding after the LAST line
        self.assertTrue(merged[0]["plan_10b5_1"])

    def test_two_trusts_are_two_rows(self):
        base = {"url": "u", "date": "2026-10-13", "insider": "A", "code": "S", "security": "Common",
                "ownership": "I", "shares": 100, "price": 10.0, "value": 1000.0}
        merged = insiders.merge_lines([dict(base, nature="By Trust 1"), dict(base, nature="By Trust 2")])
        self.assertEqual(len(merged), 2)


class InsidersBuild(TempDataTestCase):
    """A whole build on the fixtures, in temp folders: one file per company plus the index."""

    PATCHED_MODULES = (insiders,)

    def setUp(self):
        super().setUp()
        self.put_history("insiders_us", "insiders_history_us.jsonl")
        self.put_history("corrections", "insiders_corrections.jsonl")
        quietly(insiders.build)
        self.index = self.read_graph("insiders_index.json")

    def rows(self, company):
        return self.read_graph("insiders/" + self.index["companies"][company]["file"])["rows"]

    def test_index(self):
        self.assertEqual(self.index["updated"], "2026-10-17")
        self.assertEqual(sorted(self.index["companies"]),
                         ["CoreWeave", "Eli Lilly", "Microchip Technology", "NRG Energy", "Nordson"])
        self.assertEqual(self.index["companies"]["NRG Energy"],
                         {"file": "nrg-energy.json", "count": 1, "latest": "2026-03-04"})

    def test_eli_lilly_typo_never_reaches_the_site(self):
        rows = self.rows("Eli Lilly")
        self.assertEqual(len(rows), 4)                              # one row per filing (fill prices merged)
        self.assertTrue(all(r["price"] is None or r["price"] < 2000 for r in rows))
        typo_day = next(r for r in rows if r["date"] == "2025-11-14")
        self.assertIsNone(typo_day["price"])
        self.assertIsNone(typo_day["value"])
        self.assertEqual(typo_day["shares"], 178295)

    def test_nrg_joint_filers_are_one_row(self):
        rows = self.rows("NRG Energy")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["insider"], "LS Power Equity Advisors, LLC; Nanus David")
        self.assertEqual(row["shares"], 16129269)                   # 14,300,000 + 1,829,269, counted once
        self.assertEqual(row["price"], 164.0)
        self.assertEqual(row["owned_after"], 4820731)

    def test_grants_and_gifts_have_no_value(self):
        grant = self.rows("Nordson")[0]
        gift = self.rows("Microchip Technology")[0]
        self.assertEqual((grant["type"], gift["type"]), ("grant", "gift"))
        self.assertIsNone(grant["value"])
        self.assertIsNone(gift["value"])
        self.assertEqual(grant["price"], 240.38)                    # the price itself is still shown

    def test_coreweave_correction_applied(self):
        rows = self.rows("CoreWeave")
        by_date = {r["date"]: r for r in rows}
        self.assertEqual([r["date"] for r in rows], ["2026-10-13", "2026-10-12", "2026-10-11"])   # newest first
        self.assertFalse(by_date["2026-10-12"]["plan_10b5_1"])     # sell-to-cover N2 (corrected)
        self.assertTrue(by_date["2026-10-13"]["plan_10b5_1"])      # plan sales N3-N5, merged
        self.assertEqual(by_date["2026-10-13"]["shares"], 21569)
        self.assertEqual(by_date["2026-10-11"]["type"], "option_exercise")


if __name__ == "__main__":
    unittest.main()
