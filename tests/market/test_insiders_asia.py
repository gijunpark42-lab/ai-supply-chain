"""insiders_asia: the Korean DART unit-price cell (kr_price), fixed on 2026-10-17.

The cells below are the real ones recorded in market/history/corrections.jsonl: the old parser joined every digit
of the cell, so '149,000(149,000)' became 149,000,149,000 and '295,500(주1)' became 2,955,001.
"""
import unittest

from market import insiders_asia


class KoreanUnitPrice(unittest.TestCase):
    def test_samsung_repeated_number(self):
        # Samsung, DART 20260123000107 line 1 (Min Gyeong-il, open-market sale)
        self.assertEqual(insiders_asia.kr_price("149,000(149,000)", "보통주"), 149000)

    def test_footnote_mark_removed(self):
        # Hansol Chemical, DART 20260211000651 line 1: '(주1)' is a footnote mark, not a digit of the price
        self.assertEqual(insiders_asia.kr_price("295,500(주1)", "보통주"), 295500)

    def test_samsung_common_and_preferred_in_one_cell(self):
        # Samsung, DART 20260814003747 line 1: the price of the line's own share class is taken
        cell = "보통주 193,914 (원 )우선주 188,305(원)"
        self.assertEqual(insiders_asia.kr_price(cell, "보통주"), 193914)
        self.assertEqual(insiders_asia.kr_price(cell, "우선주"), 188305)

    def test_samsung_stock_bonus_cell(self):
        # Samsung, DART 20260814003973 line 1
        self.assertEqual(insiders_asia.kr_price("보통주 254,674 (원 )우선주 191,000(원)", "보통주"), 254674)

    def test_no_price(self):
        self.assertIsNone(insiders_asia.kr_price("-", "보통주"))
        self.assertIsNone(insiders_asia.kr_price("", "보통주"))

    def test_price_for_another_class_only(self):
        # a cell that prices only preferred shares says nothing about a common-share line
        self.assertIsNone(insiders_asia.kr_price("우선주 188,305(원)", "보통주"))

    def test_plain_number(self):
        self.assertEqual(insiders_asia.kr_price("84,215", "보통주"), 84215)


if __name__ == "__main__":
    unittest.main()
