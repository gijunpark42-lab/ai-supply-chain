"""
Unit tests for verify_graph.py — the number matcher, the counterparty (PARTY) matcher and
the label -> document resolver.

Run from anywhere:
    python -X utf8 utils/test_verify_graph.py

The first two groups use tiny synthetic documents, so they never depend on what is on disk.
The resolver group reads the real transcripts/ and supply_contracts/ folders (read-only) and
skips itself when a file it expects is not there.
"""

import os
import sys
import unittest

# The script lives in utils/; verify_graph.py and the data folders live one level up.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import verify_graph as v  # noqa: E402  (import after the path fix on purpose)


def doc(text, path="transcripts/test/testco_q2_2026.txt", label=None):
    """A throw-away Doc from a snippet of text."""
    return v.Doc(path, text, label)


# ---------------------------------------------------------------------------
# NUMBERS
# ---------------------------------------------------------------------------

class NumberMatcherTest(unittest.TestCase):

    def test_exact_and_trailing_zeros(self):
        self.assertTrue(doc("revenue of $3,274 million").has_number("3,274"))
        self.assertTrue(doc("$14 billion").has_number("14.0"))

    def test_rescale_and_round_won_to_millions(self):
        # a DART statement in won vs a figure in KRW millions: rounding carries a digit
        self.assertTrue(doc("매출액 | 45,945,836,761 | 33,950,120,000").has_number("45,946", "Q2 rev KRW 45,946M"))
        # a 천원 table
        self.assertTrue(doc("1,235,184,725").has_number("1,235,185", "H1 capex KRW 1,235,185M"))

    def test_rescale_and_round_millions_to_billions(self):
        self.assertTrue(doc("revenue of $8,965 million").has_number("8.97", "FQ4 rev $8.97B"))
        self.assertTrue(doc("operating profit 45,293").has_number("45.3", "OP 45.3B yen"))
        self.assertTrue(doc("(단위: 백만원) 422,483").has_number("422.5", "H1 new orders KRW 422.5B"))
        self.assertTrue(doc("115,948").has_number("115.9", "FY26 $115.9B"))

    def test_korean_units(self):
        self.assertTrue(doc("계약금액 408.9억원").has_number("40,890", "KRW 40,890M"))
        self.assertTrue(doc("계약금액 130.3억원").has_number("13.03", "13.03B"))
        self.assertTrue(doc("매출 27조 8,000억원").has_number("27.8", "revenue KRW 27.8T"))
        self.assertTrue(doc("16,975억원").has_number("1,697.5", "KRW 1,697.5B"))

    def test_numbers_written_in_words(self):
        self.assertTrue(doc("more than 6 thousand racks per month").has_number("6,000", ">6,000 racks/month"))
        self.assertTrue(doc("half a million wafers").has_number("500", "High-NA >500K wafers"))
        self.assertTrue(doc("a SAM of $700 million").has_number("0.7", "SiPho/InP SAM $0.7B"))
        self.assertTrue(doc("960 thousand Rubin GPUs").has_number("960,000", "960,000 GPUs"))
        self.assertTrue(doc("1 thousandx better reliability").has_number("1,000", "~1,000x reliability"))

    def test_unit_suffix_on_the_figure(self):
        self.assertTrue(doc("750 V and 1,200 V discretes").has_number("1.2", "750V/1.2kV discretes"))
        self.assertTrue(doc("operating profit 4,900,000,000 won").has_number("4.9", "OP KRW 4.9B"))
        # a zero after the decimal point is the writer's precision: "62.0" is a 3-digit figure
        self.assertTrue(doc("영업이익 | 62,038 | 45,101").has_number("62.0", "OP KRW 62.0B"))
        self.assertTrue(doc("11,500 | 12.3%").has_number("1,150.0", "wafers KRW 1,150.0B"))

    def test_percentages_are_never_rescaled(self):
        d = doc("capex of 12,200,000 and 1,220")
        self.assertFalse(d.has_number("12.2", "OP margin 12.2%"))
        self.assertTrue(doc("ratio 0.122").has_number("12.2", "12.2% margin"))     # the decimal spelling
        self.assertTrue(doc("margin was 12.2%").has_number("12.2", "12.2% margin"))

    def test_plainly_wrong_numbers_still_fail(self):
        self.assertFalse(doc("매출액 | 45,945,836,761").has_number("47,123", "Q2 rev KRW 47,123M"))
        self.assertFalse(doc("revenue of $8,965 million").has_number("8.75", "rev $8.75B"))
        self.assertFalse(doc("1,234,567 and 2,345").has_number("1.6", "$1.6B"))
        self.assertFalse(doc("nothing here but 2026").has_number("3.07", "EPS $3.07"))
        # a 1-2 digit figure needs exactly the same digits at a plausible power of ten
        self.assertFalse(doc("7,407백만원에 취득").has_number("7.4", "capex KRW 7.4B"))
        self.assertFalse(doc("영업이익 4,912,345,678").has_number("4.9", "OP KRW 4.9B"))
        self.assertTrue(doc("영업이익 4,900,000,000").has_number("4.9", "OP KRW 4.9B"))
        self.assertTrue(doc("full year 220,000 (12.5)").has_number("220", "sales JPY 220B"))
        self.assertTrue(doc("売上収益 13000 17500").has_number("1,300", "OP 1,300B yen"))
        self.assertFalse(doc("13,100 and 1,299").has_number("1,300", "OP 1,300B yen"))

    def test_asian_currency_tables(self):
        # 억원 / 億円 tables sit eight powers of ten below the KRW/JPY unit
        self.assertTrue(doc("소 계 | 99,963 | 100.0%").has_number("9,996", "purchases KRW 9,996B"))
        self.assertTrue(doc("16,975 | 17.0%").has_number("1,697.5", "chemicals KRW 1,697.5B"))
        self.assertTrue(doc("10,029 5,991").has_number("1,002.9", "Q4 rev 1,002.9B yen"))
        self.assertFalse(doc("10,029 5,991").has_number("1,002.9", "Q4 rev $1,002.9B"))   # not for dollars

    def test_year_fragments_are_not_figures(self):
        self.assertEqual(v.numbers_in("$40B LTA CY27-29; cash 26-27; >$30B cum. 2026-28; (was 4% in '23)"), ["40", "30"])

    def test_numbers_must_stand_alone(self):
        self.assertFalse(doc("other bets 373 382 hedging").has_number("38", "+38% QoQ"))
        self.assertFalse(doc("total 1,138 units").has_number("38", "38 units"))
        self.assertFalse(doc("a ratio of 1.38").has_number("38", "38%"))
        self.assertTrue(doc("up 38% year over year").has_number("38", "+38% QoQ"))
        self.assertTrue(doc("guide of $50 billion.").has_number("50", "$50B"))
        self.assertTrue(doc("sales of 1,570.0 billion yen").has_number("1,570", "1,570B yen"))

    def test_near_miss_only_for_money_figures(self):
        d = doc("earnings per share of $3.7. Net income $531 million.")
        self.assertFalse(d.has_number("3.07", "NG EPS $3.07 (+79%)"))
        self.assertEqual(d.near_miss("3.07", "NG EPS $3.07 (+79%)"), "3.7")
        # a percentage's twin proves nothing
        self.assertIsNone(doc("up 10.06% this year").near_miss("10.6", "Q2 rev KRW 216,472M (-10.6%)"))
        # a twin inside a longer number does not count
        self.assertIsNone(doc("$3.75 billion").near_miss("3.07", "EPS $3.07"))

    def test_derived_from_in_field_numbers(self):
        self.assertEqual(v.derived_from("234.9", ["67.6", "79.0", "88.3"]), "67.6 + 79.0 + 88.3")
        self.assertEqual(v.derived_from("51.9", ["251.2", "130.3"]), "130.3 / 251.2 x 100")
        self.assertEqual(v.derived_from("12.9", ["146.7", "11.4"]), "146.7 / 11.4")
        self.assertEqual(v.derived_from("151.9", ["13.03", "14.52", "12.13", "14.52", "32.85", "15.15", "30.3", "19.4"]),
                         "13.03 + 14.52 + 12.13 + 14.52 + 32.85 + 15.15 + 30.3 + 19.4")
        # 9.2 / 28.0 = 32.86 -> 32.9, so 32.8 is NOT the arithmetic of these two
        self.assertIsNone(v.derived_from("32.8", ["28.0", "9.2"]))
        self.assertIsNone(v.derived_from("16.3", ["6,629,816", "1,062,067"]))

    def test_numbers_in_skips_dates_years_and_single_digits(self):
        self.assertEqual(v.numbers_in("KRW 45,946M (+35.0% YoY) at 06-30-2026; 2026-01-01 to 2026-06-30; to 12-2027; 5 units"),
                         ["45,946", "35.0"])
        # digits glued to a word are labels, not figures
        self.assertEqual(v.numbers_in("FY27 guide $65-72B; PowerEdge XE9680; Q2 rev $11.1B; 800G"), ["65", "72", "11.1", "800"])

    def test_check_entry_verdicts(self):
        docs = [doc("Revenue was $1,604 million, up 9%. Earnings per share of $3.7.")]
        fields = {"signal": "s", "figure": "Q2 $1,604M (+9%)"}
        self.assertEqual(v.check_entry("Testco Q2 FY2026 (08-03-2026)", docs, fields)[0], "pass")
        fields = {"signal": "s", "figure": "EPS $3.07"}
        verdict, issues, detail = v.check_entry("Testco Q2 FY2026 (08-03-2026)", docs, fields)
        self.assertEqual((verdict, issues), ("warn", ["number_near_miss"]))
        self.assertEqual(detail["numbers_near_miss"], {"3.07": "3.7"})
        fields = {"signal": "s", "figure": "Q2 $1,604M; margin 42.5%"}
        verdict, issues, detail = v.check_entry("Testco Q2 FY2026 (08-03-2026)", docs, fields)
        self.assertEqual((verdict, issues), ("fail", ["number_not_in_source"]))
        self.assertEqual(detail["numbers_missing"], ["42.5"])
        self.assertEqual(v.check_entry("Testco Q2 FY2026 (08-03-2026)", [], fields)[0], "fail")
        self.assertEqual(v.check_entry("Testco Q2 FY2026 (08-03-2026)", docs, {"signal": "s", "figure": "no specific figure"})[0],
                         "unchecked")


# ---------------------------------------------------------------------------
# PARTY
# ---------------------------------------------------------------------------

class CounterpartyMatcherTest(unittest.TestCase):

    def test_korean_aliases(self):
        self.assertTrue(doc("주요 매출처: 솔브레인㈜").mentions("Soulbrain"))
        self.assertTrue(doc("(주)포스코 외").mentions("POSCO"))
        self.assertTrue(doc("에스케이트리켐㈜").mentions("SK Trichem"))
        self.assertTrue(doc("시스코시스템즈캐피탈").mentions("Cisco"))
        self.assertTrue(doc("동우화인켐㈜").mentions("Dongwoo Fine-Chem"))
        self.assertTrue(doc("피에스케이㈜").mentions("PSK Inc."))
        self.assertTrue(doc("다이요잉크프로덕츠㈜").mentions("Taiyo Holdings"))
        self.assertTrue(doc("SK실트론").mentions("SK Siltron"))
        self.assertTrue(doc("샌디스크").mentions("Sandisk"))
        self.assertTrue(doc("시높시스").mentions("Synopsys"))
        self.assertTrue(doc("대한전선").mentions("Taihan Cable"))
        self.assertTrue(doc("삼성전자㈜").mentions("Samsung"))
        self.assertTrue(doc("日本化学工業とJV").mentions("Nippon Chemical Industrial"))

    def test_english_aliases_subsidiaries_brands(self):
        self.assertTrue(doc("design wins at AWS").mentions("Amazon"))
        self.assertTrue(doc("Trainium 3 ramp").mentions("Amazon"))
        self.assertTrue(doc("Atotech Korea Co., Ltd").mentions("MKS Instruments"))
        self.assertTrue(doc("STATS ChipPAC Korea").mentions("JCET"))
        self.assertTrue(doc("Hynix and Micron").mentions("SK Hynix"))
        self.assertTrue(doc("LITEON and MACOM").mentions("Lite-On"))
        self.assertTrue(doc("Lg Chem, Doosan Electronic (Gimcheon)").mentions("Doosan Corporation"))
        self.assertTrue(doc("Mitsubishi Hitachi Power Systems, Ltd.").mentions("Mitsubishi Heavy Industries"))
        self.assertTrue(doc("Nvidia's GPUs").mentions("NVIDIA"))
        self.assertTrue(doc("Meta Platforms").mentions("Meta"))

    def test_short_names_are_whole_words(self):
        self.assertTrue(doc("Big5 packaging (ASE, Amkor, SPIL, JCET, PTI)").mentions("ASE Group"))
        self.assertTrue(doc("Big5 packaging (ASE, Amkor, SPIL, JCET, PTI)").mentions("Powertech Technology"))
        self.assertFalse(doc("the second phase of the ramp").mentions("ASE Group"))
        self.assertTrue(doc("Arm-based CPUs").mentions("Arm Holdings"))
        self.assertTrue(doc("ARM IP licence").mentions("Arm Holdings"))
        self.assertFalse(doc("an arm's length deal").mentions("Arm Holdings"))
        self.assertTrue(doc("ISC Link-Edge socket").mentions("ISC"))
        self.assertFalse(doc("a discount on sockets").mentions("ISC"))
        self.assertTrue(doc("utilities PSE and Xcel").mentions("Puget Sound Energy"))
        self.assertTrue(doc("utilities PSE and Xcel").mentions("Xcel Energy"))
        self.assertTrue(doc("supplied to TUC").mentions("Taiwan Union Technology (TUC)"))
        self.assertTrue(doc("committed to the KOACC build").mentions("Korea AI Computing Center (KOACC)"))
        self.assertTrue(doc("EMC and Doosan").mentions("Elite Material"))

    def test_common_words_are_not_companies(self):
        self.assertFalse(doc("artificial intelligence workloads").mentions("Intel"))
        self.assertTrue(doc("Intel Corporation").mentions("Intel"))
        self.assertFalse(doc("we work together with partners").mentions("Together AI"))
        self.assertFalse(doc("a coherent strategy").mentions("Coherent"))
        self.assertTrue(doc("Coherent Corp.").mentions("Coherent"))
        self.assertFalse(doc("sub-micron features").mentions("Micron"))
        self.assertTrue(doc("Micron Technology").mentions("Micron"))
        self.assertFalse(doc("MITSUBISHI, RESONAC").mentions("Mitsubishi Gas Chemical"))   # which Mitsubishi?

    def test_counterparty_absent_is_a_warn(self):
        docs = [doc("no partner named; revenue $5 billion")]
        fields = {"signal": "s", "value": "$5B"}
        verdict, issues, detail = v.check_entry("Testco Q2 FY2026 (08-03-2026)", docs, fields, counterparty="Meta")
        self.assertEqual((verdict, issues, detail["counterparty"]), ("warn", ["counterparty_not_in_source"], "not_found"))
        verdict, issues, detail = v.check_entry("Testco Q2 FY2026 (08-03-2026)", [doc("Meta took $5 billion")], fields, counterparty="Meta")
        self.assertEqual((verdict, detail["counterparty"]), ("pass", "mentioned"))


# ---------------------------------------------------------------------------
# SOURCE resolution
# ---------------------------------------------------------------------------

class CompanyRankTest(unittest.TestCase):

    def test_ranks(self):
        r = v.company_rank
        self.assertEqual(r("Samsung Electro-Mechanics", "samsung_electro"), 3)   # listed alias
        self.assertEqual(r("Samsung Electro-Mechanics", "samsung_electr"), 2)    # leading part of the name
        self.assertEqual(r("Samsung Electro-Mechanics", "semco"), 3)
        self.assertEqual(r("Samsung Electro-Mechanics", "samsung"), 0)        # Samsung's call is not SEMCO's
        self.assertEqual(r("Samsung", "samsung_electro"), 0)
        self.assertEqual(r("Samsung", "samsungelectromechanics"), 0)
        self.assertEqual(r("Samsung Foundry", "samsung"), 2)
        self.assertEqual(r("Intel Foundry", "intel"), 2)
        self.assertEqual(r("Applied Materials", "applied_digital"), 0)
        self.assertEqual(r("Applied Digital", "apld"), 3)
        self.assertEqual(r("Amazon", "amazon_aws"), 1)
        self.assertEqual(r("Lumentum", "lumen"), 0)
        self.assertEqual(r("Lumen Technologies", "lumen"), 2)
        self.assertEqual(r("Nan Ya PCB", "nanya"), 0)
        self.assertEqual(r("Nanya Technology", "nanya"), 2)
        self.assertEqual(r("Hyosung Heavy Industries", "hyosung_heavy"), 2)
        self.assertEqual(r("Tokyo Electron", "tel"), 3)
        self.assertEqual(r("Tokyo Electron", "tokyoelectron"), 3)
        self.assertEqual(r("Mitsubishi Gas Chemical", "mgc"), 3)
        self.assertEqual(r("Goldman Sachs", "gs"), 3)
        self.assertEqual(r("NVIDIA", "nvda"), 3)


class HeaderLabelTest(unittest.TestCase):

    def test_header_spellings(self):
        cases = {
            "# source label: Techwing DART supply contract (08-04-2026)\n": "Techwing DART supply contract (08-04-2026)",
            "# source label: Sanil Electric DART 공급계약 (08-20-2026)\n": "Sanil Electric DART supply contract (08-20-2026)",
            "Source label for enrichment: Micron Q3 FY2026 (06-24-2026)\n": "Micron Q3 FY2026 (06-24-2026)",
            "SOURCE LABEL USED FOR ENRICHMENT: Keysight Q3 FY2026 (08-18-2026)\n": "Keysight Q3 FY2026 (08-18-2026)",
            "Canonical source label used in chains: NVIDIA Q2 FY2027 (08-26-2026)\n": "NVIDIA Q2 FY2027 (08-26-2026)",
            "Source label: IQE FY2025 (05-28-2026)\n": "IQE FY2025 (05-28-2026)",
            "NOTE: UPGRADES the 8-K sourcing (same source label `Intel Q2 FY2026 (07-23-2026)`). Companion: x.txt\n":
                "Intel Q2 FY2026 (07-23-2026)",
        }
        for text, expected in cases.items():
            self.assertEqual(v.header_labels(text), [expected], text)
        self.assertEqual(v.header_labels("NOTE: same source label as before.\n"), [])

    def test_filename_facts(self):
        d = v.Doc("transcripts/equipment/tel_fy2026.txt", "x")
        self.assertEqual((d.company_token, d.quarter, d.year, d.suffix), ("tel", 4, 2026, ""))
        d = v.Doc("transcripts/non_transcript_sources/apld_q4_fy2026_earnings_release.txt", "CALL DATE: 07-27-2026\n")
        self.assertEqual((d.company_token, d.quarter, d.year, d.suffix, d.date), ("apld", 4, 2026, "_earnings_release", "07-27-2026"))
        d = v.Doc("transcripts/dart/sanilelectric_prelim_2026-08-07.txt", "# DART rcept_no: 1   filed: 20260807   url: x\n")
        self.assertEqual((d.company_token, d.quarter, d.date), ("sanilelectric", None, "08-07-2026"))


class ResolverIntegrationTest(unittest.TestCase):
    """Against the real corpus (read-only). Skipped when the expected files are absent."""

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir("transcripts"):
            raise unittest.SkipTest("no transcripts/ folder")
        cls.by_label, cls.all_docs = v.load_documents()
        cls.cache = {}

    def docs(self, label):
        return [d.path for d in v.resolve_label_docs(label, self.by_label, self.all_docs, None, self.cache)]

    def need(self, *paths):
        for p in paths:
            if not os.path.exists(p):
                self.skipTest("missing " + p)

    def test_longest_company_match(self):
        # each call keeps its own same-day results deck (kind.py) as a companion, never the other company's files
        self.need("transcripts/power/samsung_electro_q1_2026.txt", "transcripts/memory/samsung_q1_2026.txt",
                  "transcripts/kind/samsungelectromechanics_2026-04-30_q1_2026_site.txt",
                  "transcripts/kind/samsung_2026-04-30_q1_2026_site.txt")
        self.assertEqual(self.docs("Samsung Electro-Mechanics Q1 FY2026 (04-30-2026)"),
                         ["transcripts/power/samsung_electro_q1_2026.txt",
                          "transcripts/kind/samsungelectromechanics_2026-04-30_q1_2026_site.txt"])
        self.assertEqual(self.docs("Samsung Q1 FY2026 (04-30-2026)"),
                         ["transcripts/memory/samsung_q1_2026.txt", "transcripts/kind/samsung_2026-04-30_q1_2026_site.txt"])

    def test_quarter_never_contradicts_label(self):
        self.need("transcripts/non_transcript_sources/apld_q4_fy2026_earnings_release.txt", "transcripts/bigtech/applied_digital_q3_2026.txt")
        self.assertEqual(self.docs("Applied Digital Q4 FY2026 (07-27-2026)"),
                         ["transcripts/non_transcript_sources/apld_q4_fy2026_earnings_release.txt"])

    def test_companions(self):
        self.need("transcripts/equipment/lam_research_q4_2026.txt", "transcripts/equipment/lam_research_q4_2026_call.txt")
        self.assertEqual(set(self.docs("Lam Research Q4 FY2026 (07-29-2026)")),
                         {"transcripts/equipment/lam_research_q4_2026_call.txt", "transcripts/equipment/lam_research_q4_2026.txt"})
        self.need("transcripts/bigtech/amazon_q2_2026.txt", "transcripts/non_transcript_sources/amazon_aws_q2_2026_earnings_release.txt")
        self.assertEqual(self.docs("Amazon Q2 FY2026 (07-30-2026)"),
                         ["transcripts/bigtech/amazon_q2_2026.txt", "transcripts/non_transcript_sources/amazon_aws_q2_2026_earnings_release.txt"])

    def test_fy_files_are_q4(self):
        self.need("transcripts/equipment/tel_fy2026.txt", "transcripts/non_transcript_sources/sumitomo_bakelite_fy2026.txt")
        self.assertEqual(self.docs("Tokyo Electron Q4 FY2026 (04-30-2026)"), ["transcripts/equipment/tel_fy2026.txt"])
        self.assertEqual(self.docs("Sumitomo Bakelite Q4 FY2026 (05-11-2026)"), ["transcripts/non_transcript_sources/sumitomo_bakelite_fy2026.txt"])

    def test_prelim_and_report_are_different_documents(self):
        self.need("transcripts/dart/sanilelectric_prelim_2026-08-07.txt", "transcripts/dart/sanilelectric_q2_2026_dart.txt")
        prelim = self.docs("Sanil Electric Q2 FY2026 (08-07-2026)")
        self.assertTrue(prelim and all("prelim" in p for p in prelim), prelim)
        self.assertEqual(self.docs("Sanil Electric Q2 FY2026 (08-14-2026)"), ["transcripts/dart/sanilelectric_q2_2026_dart.txt"])

    def test_dart_supply_contract_labels(self):
        self.need("supply_contracts/sanilelectric.txt", "supply_contracts/techwing.txt")
        self.assertEqual(self.docs("Sanil Electric DART supply contract (08-20-2026)"), ["supply_contracts/sanilelectric.txt"])
        block = v.resolve_label_docs("Techwing DART supply contract (08-10-2026)", self.by_label, self.all_docs, None, self.cache)
        self.assertEqual(len(block), 1)
        self.assertIn("20260810", block[0].text)
        # a supply-contract label with no block never falls back to the half-year report
        self.assertEqual(self.docs("Sanil Electric DART supply contract (06-22-2026)"), [])

    def test_informal_headers_and_events(self):
        self.need("transcripts/memory/micron_q3_2026.txt", "transcripts/accelerators/nvda_gtc_taipei_2026.txt",
                  "transcripts/optical/gs_optical_networking_apr2026.txt")
        self.assertIn("Micron Q3 FY2026 (06-24-2026)", self.by_label)
        self.assertEqual(self.docs("NVIDIA GTC Taipei 2026 (06-01-2026)"), ["transcripts/accelerators/nvda_gtc_taipei_2026.txt"])
        self.assertEqual(self.docs("Goldman Sachs optical note (04-17-2026)"), ["transcripts/optical/gs_optical_networking_apr2026.txt"])

    def test_resolve_label_keeps_returning_one_doc(self):
        self.need("transcripts/equipment/lam_research_q4_2026_call.txt")
        one = v.resolve_label("Lam Research Q4 FY2026 (07-29-2026)", self.by_label, self.all_docs, None, self.cache)
        self.assertEqual(one.path, "transcripts/equipment/lam_research_q4_2026_call.txt")
        self.assertIsNone(v.resolve_label("Nan Ya PCB Q2 FY2026 (07-10-2026)", self.by_label, self.all_docs, None, self.cache))


if __name__ == "__main__":
    unittest.main(verbosity=2)
