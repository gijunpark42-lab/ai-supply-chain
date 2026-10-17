"""insiders_us: reading SEC Form 4 lines (transaction code -> type, the per-line 10b5-1 flag).

Fixtures:
  insiders_us_form4_0001769628-26-000448.txt   the full submission text of CoreWeave's Form 4 0001769628-26-000448
      (https://www.sec.gov/Archives/edgar/data/1769628/000176962826000448/0001769628-26-000448.txt, fetched
      2026-10-17), as the daily-index walk downloads it. Line N2 is a sell-to-cover for RSU taxes with its own
      footnote; N3-N5 point at the Rule 10b5-1 plan footnote (user, 2026-10-17 verification).
  insiders_us_2026q1_form345_excerpt.zip   SEC's 2026q1 Insider Transactions Data Set cut down to the lines of
      CoreWeave's 0001769628-26-000005 (copied byte for byte from market/cache/insiders_us/2026q1_form345.zip):
      the backfill path. Lines N3 / N4 are sell-to-cover sales (footnote F2), the other sales are plan sales (F4).
The transaction-code test uses a small made-up Form 4 (built below), one line per code.
"""
import unittest

from market import insiders_us
from tests.market.helpers import FIXTURES, fixture_text

COREWEAVE = {1769628: ["CoreWeave"]}

# A made-up but well-formed Form 4: one Table I line per transaction code, the filing-level 10b5-1 check box set,
# and NO footnote that mentions a plan (so the check box decides, for buys and sells only).
SYNTHETIC_LINE = """
  <nonDerivativeTransaction>
    <securityTitle><value>Common Stock</value></securityTitle>
    <transactionDate><value>2026-09-01</value></transactionDate>
    <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>{code}</transactionCode></transactionCoding>
    <transactionAmounts>
      <transactionShares><value>100</value></transactionShares>
      <transactionPricePerShare><value>50.00</value></transactionPricePerShare>
    </transactionAmounts>
    <postTransactionAmounts><sharesOwnedFollowingTransaction><value>1000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
  </nonDerivativeTransaction>"""
SYNTHETIC_DOC = """<SEC-DOCUMENT>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerCik>0001234567</issuerCik><issuerName>Example Corp</issuerName></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>1</aff10b5One>
  <nonDerivativeTable>{lines}
  </nonDerivativeTable>
</ownershipDocument>
</SEC-DOCUMENT>"""
CODES = ["P", "S", "M", "X", "F", "A", "G", "C", "J"]


class TransactionCodes(unittest.TestCase):
    def setUp(self):
        text = SYNTHETIC_DOC.format(lines="".join(SYNTHETIC_LINE.format(code=c) for c in CODES))
        self.rows = insiders_us.rows_from_submission(text, "0000000000-26-000001", "2026-09-02",
                                                     {1234567: ["Example"]})

    def test_code_to_type(self):
        self.assertEqual([r["code"] for r in self.rows], CODES)
        self.assertEqual([r["type"] for r in self.rows],
                         ["buy", "sell", "option_exercise", "option_exercise", "tax_withholding", "grant", "gift",
                          "other", "other"])

    def test_check_box_alone_marks_only_buys_and_sells(self):
        plan = {r["code"]: r["plan_10b5_1"] for r in self.rows}
        self.assertTrue(plan["P"])
        self.assertTrue(plan["S"])
        self.assertFalse(any(plan[c] for c in CODES if c not in ("P", "S")))

    def test_row_fields(self):
        first = self.rows[0]
        self.assertEqual(first["line"], "N1")
        self.assertEqual(first["insider"], "Doe Jane")
        self.assertEqual(first["role"], "Director")
        self.assertEqual(first["value"], 5000.0)                  # 100 shares x $50.00
        self.assertEqual(first["url"], "https://www.sec.gov/Archives/edgar/data/1234567/000000000026000001/"
                                       "0000000000-26-000001-index.htm")

    def test_other_issuer_is_ignored(self):
        text = SYNTHETIC_DOC.format(lines=SYNTHETIC_LINE.format(code="S"))
        self.assertEqual(insiders_us.rows_from_submission(text, "x", "2026-09-02", COREWEAVE), [])


class CoreWeaveSellToCoverDailyIndex(unittest.TestCase):
    """The daily-index path (one submission .txt per filing)."""

    def setUp(self):
        text = fixture_text("insiders_us_form4_0001769628-26-000448.txt")
        self.rows = insiders_us.rows_from_submission(text, "0001769628-26-000448", "2026-10-14", COREWEAVE)

    def test_lines(self):
        self.assertEqual([(r["line"], r["code"], r["type"], r["shares"]) for r in self.rows],
                         [("N1", "M", "option_exercise", 42772), ("N2", "S", "sell", 15811),
                          ("N3", "S", "sell", 15100), ("N4", "S", "sell", 5969), ("N5", "S", "sell", 500)])
        self.assertEqual(self.rows[1]["price"], 80.365)
        self.assertEqual(self.rows[1]["role"], "Chief Revenue Officer")

    def test_sell_to_cover_is_not_a_plan_trade(self):
        # The filing's 10b5-1 check box is set, but only N3-N5 point at the plan footnote F4.
        self.assertEqual([r["plan_10b5_1"] for r in self.rows], [False, False, True, True, True])


class CoreWeaveSellToCoverDataSet(unittest.TestCase):
    """The backfill path (SEC's quarterly data-set zip): the same per-line rule."""

    def setUp(self):
        path = FIXTURES / "insiders_us_2026q1_form345_excerpt.zip"
        self.rows = insiders_us.rows_from_zip(path, COREWEAVE, set(), "2025-10-17")

    def test_eleven_lines_in_document_order(self):
        self.assertEqual([r["line"] for r in self.rows], [f"N{i}" for i in range(1, 12)])
        self.assertEqual([r["code"] for r in self.rows], ["M", "M", "S", "S", "S", "S", "S", "C", "S", "S", "S"])
        self.assertEqual(self.rows[0]["date"], "2025-12-31")
        self.assertEqual(self.rows[0]["filed"], "2026-01-02")
        self.assertEqual(self.rows[0]["role"], "CEO and President; Director; 10% owner")

    def test_plan_flag_per_line(self):
        plan = {r["line"]: r["plan_10b5_1"] for r in self.rows}
        self.assertFalse(plan["N3"])                              # sell-to-cover (footnote F2)
        self.assertFalse(plan["N4"])                              # sell-to-cover (footnote F2)
        for line in ("N5", "N6", "N7", "N9", "N10", "N11"):       # plan sales (footnote F4)
            self.assertTrue(plan[line], line)
        for line in ("N1", "N2", "N8"):                           # RSU settlements and a Class B conversion
            self.assertFalse(plan[line], line)

    def test_already_recorded_filing_is_skipped(self):
        path = FIXTURES / "insiders_us_2026q1_form345_excerpt.zip"
        self.assertEqual(insiders_us.rows_from_zip(path, COREWEAVE, {"0001769628-26-000005"}, "2025-10-17"), [])


class PlanFootnotes(unittest.TestCase):
    def test_mentions_plan(self):
        self.assertTrue(insiders_us.mentions_plan(["This transaction was executed pursuant to a Rule 10b5-1 "
                                                   "trading plan adopted by the reporting person on June 18, 2026."]))
        self.assertFalse(insiders_us.mentions_plan(["These shares were not sold under a Rule 10b5-1 plan."]))
        self.assertFalse(insiders_us.mentions_plan(["Weighted average price; prices ranged from $76.30 to $77.62."]))

    def test_line_plan(self):
        self.assertFalse(insiders_us.line_plan(True, "S", {"F2", "F3"}, {"F4"}))   # plan footnote elsewhere only
        self.assertTrue(insiders_us.line_plan(True, "S", {"F4", "F5"}, {"F4"}))
        self.assertTrue(insiders_us.line_plan(False, "S", {"F4"}, {"F4"}))         # the footnote decides
        self.assertFalse(insiders_us.line_plan(True, "F", set(), set()))           # check box: buys / sells only


class SmallHelpers(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(insiders_us.iso_date("28-SEP-2026"), "2026-09-28")
        self.assertEqual(insiders_us.iso_date("2026-09-28-05:00"), "2026-09-28")
        self.assertIsNone(insiders_us.iso_date(""))

    def test_to_number(self):
        self.assertEqual(insiders_us.to_number("4012678.0"), 4012678)
        self.assertEqual(insiders_us.to_number("1.15"), 1.15)
        self.assertIsNone(insiders_us.to_number(""))


if __name__ == "__main__":
    unittest.main()
