"""financing_us: how one SEC filing is read (parse_financing), on real filings.

The fixtures are the filings' plain text as market.financing_us.html_to_text() makes it (fetched once on
2026-10-17). A 424B prospectus is only read up to character 12,000 (select_focus), so its first 14,000 characters
are kept; the two 8-Ks are kept whole.
  financing_us_googl_424b5_2026-06-04.txt  https://www.sec.gov/Archives/edgar/data/1652044/000119312526256375/d152107d424b5.htm
  financing_us_smci_424b5_2026-06-12.txt   https://www.sec.gov/Archives/edgar/data/1375365/000119312526267973/d41737d424b5.htm
  financing_us_cifr_8k_2026-06-15.txt      https://www.sec.gov/Archives/edgar/data/1819989/000095010326008994/dp248453_8k.htm
  financing_us_crwv_8k_2026-06-18.txt      https://www.sec.gov/Archives/edgar/data/1769628/000176962826000291/crwv-20260618.htm
"""
import unittest
from unittest import mock

from market import financing_us
from tests.market.helpers import fixture_text


def parse(fixture, form, items, filed):
    """parse_financing() on a fixture: the list of records the filing gives."""
    return financing_us.parse_financing(fixture_text(fixture), form, items, filed)


class AlphabetShareOffering(unittest.TestCase):
    """Alphabet's June 2026 424B5 offers Class A AND Class C shares at once. Before the 2026-10-17 fix only the
    Class A half was read ($10B, 25,459,689 shares); the price table's two "Total" rows must be added up."""

    def setUp(self):
        self.records = parse("financing_us_googl_424b5_2026-06-04.txt", "424B5", "", "2026-06-04")

    def test_one_equity_record(self):
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0]["type"], "equity")

    def test_amount_is_both_classes_about_18_billion(self):
        record = self.records[0]
        self.assertEqual(record["amount"], 18000000123.0)
        self.assertEqual(record["currency"], "USD")
        self.assertEqual(record["amount_usd"], 18000000123.0)
        self.assertEqual(record["title"], "$18B share offering")

    def test_share_count_is_class_a_plus_class_c(self):
        self.assertTrue(self.records[0]["detail"].startswith(
            "50,919,378 shares (25,459,689 Class A Common Stock + 25,459,689 Class C Capital Stock)"),
            self.records[0]["detail"])


class SupermicroCommonStock(unittest.TestCase):
    """Supermicro's 2026-06-12 prospectus offers common stock; a sentence about the CONCURRENT mandatory
    convertible preferred offering made the old parser type it 'convertible'."""

    def setUp(self):
        self.records = parse("financing_us_smci_424b5_2026-06-12.txt", "424B5", "", "2026-06-12")

    def test_equity_not_convertible(self):
        self.assertEqual([r["type"] for r in self.records], ["equity"])

    def test_amount_and_shares(self):
        record = self.records[0]
        self.assertEqual(record["amount"], 1249999987.5)
        self.assertEqual(record["title"], "$1.25B share offering")
        self.assertEqual(record["detail"], "45,454,545 shares")


class NotesEightK(unittest.TestCase):
    """An 8-K with Item 2.03 for a notes issue: amount, coupon and maturity come out of the item text."""

    def test_cipher_senior_secured_notes(self):
        records = parse("financing_us_cifr_8k_2026-06-15.txt", "8-K", "1.01,2.03,9.01", "2026-06-15")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["type"], "debt")
        self.assertEqual(record["amount"], 810000000.0)
        self.assertEqual(record["currency"], "USD")
        self.assertEqual(record["title"], "$810M 6.000% Senior Secured Notes due 2031")   # amount, coupon, maturity

    def test_coreweave_dollar_and_euro_notes_are_two_records(self):
        # One 8-K, two currencies = two rows. The euro row is converted with the FX close of the filing day;
        # a fixed rate is put in the FX cache so no price is downloaded.
        with mock.patch.dict(financing_us._fx_cache, {"EUR": {"2026-06-17": 1.16}}):
            records = parse("financing_us_crwv_8k_2026-06-18.txt", "8-K", "1.01,2.03,9.01", "2026-06-18")
        by_currency = {r["currency"]: r for r in records}
        self.assertEqual(sorted(by_currency), ["EUR", "USD"])
        self.assertEqual(by_currency["USD"]["title"], "$1.25B 9.625% Senior Notes due 2032")
        self.assertEqual(by_currency["USD"]["amount"], 1250000000.0)
        self.assertEqual(by_currency["EUR"]["title"], "€2B 8.500% Senior Notes due 2032")
        self.assertEqual(by_currency["EUR"]["amount"], 2000000000.0)
        self.assertAlmostEqual(by_currency["EUR"]["amount_usd"], 2320000000.0, places=0)
        self.assertEqual({r["type"] for r in records}, {"debt"})


class SmallHelpers(unittest.TestCase):
    def test_short_money(self):
        self.assertEqual(financing_us.short_money(18000000123.0), "$18B")
        self.assertEqual(financing_us.short_money(810000000.0), "$810M")
        self.assertEqual(financing_us.short_money(2e9, "EUR"), "€2B")

    def test_preliminary_prospectus_is_skipped(self):
        # The final version follows a few days later; a "subject to completion" draft is never a row.
        text = "Subject to Completion, dated June 1, 2026. Preliminary Prospectus Supplement. $1,000,000,000 " \
               "4.500% Senior Notes due 2031. We are offering $1,000,000,000 aggregate principal amount of notes."
        self.assertEqual(financing_us.parse_financing(text, "424B5", "", "2026-06-01"), [])


if __name__ == "__main__":
    unittest.main()
