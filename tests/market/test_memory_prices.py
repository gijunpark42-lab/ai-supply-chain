"""memory_prices: reading the DRAMeXchange home page (parse_dramexchange is a pure function).

Fixture: memory_dramexchange_home.htm = a hand-written page with the tag and class structure of two price boxes of
https://www.dramexchange.com/ (not a copy of the page: DRAMeXchange's terms restrict republishing, and this repo is
public). "DRAM Spot Price" holds the 7 rows the collector recorded on 2026-10-17 (kept); "Flash Spot Price" has one
placeholder row (ignored on purpose: only the key series are shown).
"""
import unittest

from market import memory_prices
from tests.market.helpers import FIXTURES


class DramExchangeHomePage(unittest.TestCase):
    def setUp(self):
        html = (FIXTURES / "memory_dramexchange_home.htm").read_bytes()
        self.rows = memory_prices.parse_dramexchange(html, "2026-10-17")
        self.by_id = {r["id"]: r for r in self.rows}

    def test_only_the_key_box_is_kept(self):
        self.assertEqual(len(self.rows), 7)
        self.assertEqual({r["section"] for r in self.rows}, {"DRAM Spot Price"})

    def test_ddr5_16gb_series(self):
        row = self.by_id["dram_spot_ddr5_16gb_2gx8_4800_5600"]
        self.assertEqual(row["label"], "DDR5 16Gb (2Gx8) 4800/5600")
        self.assertEqual(row["date"], "2026-10-16")                 # the page's own price date, not the fetch date
        self.assertEqual(row["asof"], "2026-10-16 18:10 GMT+8")
        self.assertEqual(row["fetched"], "2026-10-17")
        self.assertEqual((row["high"], row["low"], row["avg"], row["change_pct"]), (71.0, 46.0, 60.6, 0.28))
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["cadence"], "daily")
        self.assertEqual(row["unit"], "USD per chip")

    def test_page_order_is_kept(self):
        self.assertEqual([r["id"] for r in self.rows][:3],
                         ["dram_spot_ddr5_16gb_2gx8_4800_5600", "dram_spot_ddr5_16gb_2gx8_ett",
                          "dram_spot_ddr4_16gb_2gx8_3200"])

    def test_page_without_boxes_gives_no_rows(self):
        self.assertEqual(memory_prices.parse_dramexchange(b"<html><body>maintenance</body></html>", "2026-10-17"), [])


class SmallHelpers(unittest.TestCase):
    def test_parse_last_update(self):
        self.assertEqual(memory_prices.parse_last_update("Last Update: Oct.16 2026    18:10 (GMT+8)"),
                         ("2026-10-16", "2026-10-16 18:10 GMT+8"))
        self.assertEqual(memory_prices.parse_last_update("no date here"), (None, None))

    def test_to_number(self):
        self.assertEqual(memory_prices.to_number("2,176.000"), 2176.0)
        self.assertEqual(memory_prices.to_number("0.28 %"), 0.28)
        self.assertIsNone(memory_prices.to_number("--"))

    def test_memory_release_titles(self):
        self.assertTrue(memory_prices.is_memory_release("DRAM Contract Prices to Rise 10-15% QoQ in 4Q26"))
        self.assertFalse(memory_prices.is_memory_release("AI Server Shipments to Grow in 2027"))


if __name__ == "__main__":
    unittest.main()
