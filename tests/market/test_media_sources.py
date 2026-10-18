"""Unit tests for how the enrich tools treat a news-interview source (transcripts/media/, media_pull.py).

The user's rules (2026-10-17): only the named executive's own words may become a signal, verbatim from the
transcript with its [mm:ss] timestamp (rule 4), and nothing of the video or the transcript is shown on the
website (rule 5). Four places enforce that, and these tests pin them (verification of 2026-10-17):

  evidence.hide_media_source()        the site's "source" box (graph/evidence.json -> Evidence.tsx) gets no excerpt
                                      and no file path for a news interview
  utils/check_patch.py source_kind()  a news interview fills no screener slot (enrich skill section 4)
  verify_graph.media_quote_problems() the quoted words must be verbatim in the cited [mm:ss] paragraph of the
                                      transcript body, and every figure number must be inside the quote
  verify_graph.label_company()        "Dell CNBC interview (10-13-2026)" names Dell, so a contract's counterparty
                                      check looks at the right side of the edge

Everything runs offline on small inline inputs (tests/market/__init__.py switches the network off).
Run from the repo root:
    python -X utf8 -m unittest tests/market/test_media_sources.py -v
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # verify_graph / evidence import agent.* from the repo root

import evidence  # noqa: E402
import verify_graph  # noqa: E402
from agent.corpus import normalize_company  # noqa: E402

CHECK_PATCH_PY = ROOT / "utils" / "check_patch.py"


def check_patch_parts():
    """utils/check_patch.py reads every transcript and the whole graph when it is imported (minutes), so the test
    takes only the pieces it checks from its source -- SLOTS, source_kind() and ALLOWED_SLOTS -- and runs them with
    the real verify_graph. Returns {name: object}."""
    tree = ast.parse(CHECK_PATCH_PY.read_text(encoding="utf-8"))
    wanted = [node for node in tree.body
              if (isinstance(node, ast.FunctionDef) and node.name == "source_kind")
              or (isinstance(node, ast.Assign)
                  and any(getattr(t, "id", None) in ("SLOTS", "ALLOWED_SLOTS") for t in node.targets))]
    namespace = {"re": re, "vg": verify_graph}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(CHECK_PATCH_PY), "exec"), namespace)
    return namespace


# A small transcript in the transcripts/media/ format (header, '---', then [mm:ss] paragraphs). The anchor's
# question carries "$40 BILLION"; the executive's answer carries "240 MEGAWATTS"; the title carries "$50 billion".
TRANSCRIPT = "\n".join([
    "# source label: CoreWeave Fox Business interview (10-11-2026)",
    "# SOURCE: https://www.youtube.com/watch?v=0Tt7L-ki994",
    "# OUTLET: Fox Business",
    "# SPEAKER: Michael Intrator, co-founder, chairman and CEO, CoreWeave",
    "# PUBLISHED: 2026-10-11",
    "# TRANSCRIPT: youtube manual captions",
    "# NOTE: news interview; only the named executive's own first-person words may become signals",
    "# TITLE: CoreWeave CEO on a $50 billion buildout",
    "",
    "---",
    "",
    "[06:05] LIZ: YOU HAVE A $40 BILLION BACKLOG. HOW BIG OF A START IS THAT?",
    "[06:12] >> WE ARE BRINGING ON THE FIRST 240 MEGAWATTS THIS YEAR AND WE ARE",
    "[06:40] SOLD OUT THROUGH NEXT YEAR.",
])
URL = "(video: https://www.youtube.com/watch?v=0Tt7L-ki994)"


class MediaLabelTests(unittest.TestCase):

    def test_media_label_shapes(self):
        self.assertTrue(verify_graph.is_media_source("Dell CNBC interview (10-13-2026)"))
        self.assertTrue(verify_graph.is_media_source("Micron Bloomberg interview G0gOxDLsTD8 (10-16-2026)"))
        self.assertTrue(verify_graph.is_media_source("TSMC CNBC International interview (10-16-2026)"))
        self.assertTrue(verify_graph.is_media_source("anything", "transcripts/media/dell_2026-10-13_nHpXEkcfhGo.txt"))
        self.assertTrue(verify_graph.is_media_source("anything", "transcripts\\media\\dell_2026-10-13_x.txt"))
        # a company's own press release whose headline ends in "interview" is not a news interview
        self.assertFalse(verify_graph.is_media_source("Dell press release: Dell CEO interview (10-13-2026)",
                                                      "transcripts/ir/dell_2026-10-13_x.txt"))
        self.assertFalse(verify_graph.is_media_source("NVIDIA Q2 FY2027 (08-26-2026)", "transcripts/av/nvidia.txt"))

    def test_label_company_of_an_interview(self):
        # the contract check compares the first 5 letters: 'dellcnbcinterview' would pick the wrong edge side
        self.assertEqual(verify_graph.label_company("Dell CNBC interview (10-13-2026)"), normalize_company("Dell"))
        self.assertEqual(verify_graph.label_company("AMD Bloomberg interview abcdefghijk (10-13-2026)"),
                         normalize_company("AMD"))
        self.assertEqual(verify_graph.label_company("Arm Holdings Yahoo Finance interview (10-13-2026)"),
                         normalize_company("Arm Holdings"))
        # unchanged for the other labels
        self.assertEqual(verify_graph.label_company("Broadcom Q2 FY2026 (06-03-2026)"), normalize_company("Broadcom"))


class EvidenceTests(unittest.TestCase):

    def test_media_record_shows_no_excerpt_and_no_path(self):
        record = {"doc": "transcripts/media/coreweave_2026-10-11_0Tt7L-ki994.txt", "excerpt": "…LIZ: YOU HAVE…",
                  "matched": "240", "status": "found", "via": "number"}
        evidence.hide_media_source(record, "CoreWeave Fox Business interview (10-11-2026)", record["doc"])
        self.assertEqual(record, {"doc": None, "excerpt": None, "matched": None, "status": "found", "via": "number"})

    def test_other_records_are_untouched(self):
        record = {"doc": "transcripts/av/nvidia_q3_2027.txt", "excerpt": "…«$57 billion»…", "matched": "$57 billion",
                  "status": "found", "via": "number"}
        before = dict(record)
        evidence.hide_media_source(record, "NVIDIA Q3 FY2027 (11-19-2026)", record["doc"])
        self.assertEqual(record, before)


class SlotTests(unittest.TestCase):

    def test_news_interview_fills_no_slot(self):
        parts = check_patch_parts()
        kind = parts["source_kind"]("Dell CNBC interview (10-13-2026)", "transcripts/media/dell_2026-10-13_x.txt")
        self.assertEqual(kind, "news interview")
        self.assertEqual(parts["ALLOWED_SLOTS"][kind], set())
        # a press release stays a press release, a call stays a call
        self.assertEqual(parts["source_kind"]("Dell press release: Dell CEO interview (10-13-2026)",
                                              "transcripts/ir/dell_2026-10-13_x.txt"), "press release")
        self.assertEqual(parts["source_kind"]("Dell Q2 FY2027 (08-28-2026)", "transcripts/av/dell_q2_2027.txt"),
                         "call / conference / periodic report")


class MediaQuoteTests(unittest.TestCase):

    def problems(self, signal, figure="no specific figure"):
        return verify_graph.media_quote_problems(signal, [figure], TRANSCRIPT)

    def test_verbatim_quote_in_its_paragraph_passes(self):
        signal = f"CEO Michael Intrator on Fox Business [06:12]: 'We are bringing on the first 240 megawatts this year' {URL}"
        self.assertEqual(self.problems(signal, "240 megawatts"), [])

    def test_quote_may_run_into_the_next_paragraph(self):
        signal = (f"CEO Michael Intrator on Fox Business [06:12] (broadcast captions): 'we are bringing on the first "
                  f"240 megawatts this year and we are sold out through next year' {URL}")
        self.assertEqual(self.problems(signal), [])

    def test_quote_under_the_wrong_timestamp_fails(self):
        signal = f"CEO Michael Intrator on Fox Business [06:05]: 'We are bringing on the first 240 megawatts' {URL}"
        self.assertTrue(self.problems(signal))

    def test_anchor_number_is_never_the_figure(self):
        # the quote is the executive's, but $40 billion came from the anchor's question
        signal = f"CEO Michael Intrator on Fox Business [06:12]: 'We are bringing on the first 240 megawatts' {URL}"
        self.assertTrue(any("40" in p for p in self.problems(signal, "$40 billion backlog")))

    def test_words_from_the_title_header_never_count(self):
        signal = f"CEO Michael Intrator on Fox Business [06:12]: 'a $50 billion buildout' {URL}"
        self.assertTrue(self.problems(signal, "$50 billion"))

    def test_signal_without_the_quote_shape_fails(self):
        self.assertTrue(self.problems("CEO Michael Intrator said CoreWeave is sold out through next year"))


if __name__ == "__main__":
    unittest.main()
