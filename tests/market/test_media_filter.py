"""Unit tests for media_pull.decide(): which news videos the interview puller keeps.

The user's rule (2026-10-17): "찌라시면 시그널이면 안 돼. 무조건 뉴스여야 함. 회사 관계자가 직접 얘기한 거여야 해"
(a rumor is never a signal; it must be news, and a company official must say it directly). So the puller keeps a
video only when an executive who is on the company's roster (media/executives.json) is named in its title or
description as the person speaking. Analysts, strategists, anchors, "reportedly" / "sources say" stories and
"here's why the stock fell" explainers are always skipped, and so is a former executive who is no longer on the
roster.

media_pull.decide(title, description, roster) -> (keep, node_id, exec_name, reason)
    keep       True when the video is an interview / remarks of a rostered executive
    node_id    the graph node the executive works for (None when skipped)
    exec_name  the executive's name as written in the roster (None when skipped)
    reason     a short text saying why (logged in media/sync_state.json)

The roster below is a small inline copy in the media/executives.json shape, so these pins do not change when the
real roster is edited. Everything runs offline (tests/market/__init__.py switches the network off).

Run from the repo root (standard library only):
    python -X utf8 -m unittest tests/market/test_media_filter.py -v
"""
import importlib.util
import unittest
from pathlib import Path

# Load media_pull.py straight from its file at the repo root (the same way test_health.py loads market/health.py),
# so the test works however unittest is started. When the file does not exist (a checkout without the puller), the
# tests are skipped instead of failing, like routine/market_data.ps1 skips its step.
MEDIA_PULL_PY = Path(__file__).resolve().parents[2] / "media_pull.py"
media_pull = None
if MEDIA_PULL_PY.exists():
    _spec = importlib.util.spec_from_file_location("media_pull_under_test", MEDIA_PULL_PY)
    media_pull = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(media_pull)

# The "companies" part of media/executives.json: graph node id -> its current executives.
ROSTER = {
    "NVIDIA": [
        {"name": "Jensen Huang", "title": "Founder, President and CEO", "aliases": [], "source": "test"},
        {"name": "Colette Kress", "title": "EVP and CFO", "aliases": [], "source": "test"},
    ],
    "Micron": [
        {"name": "Sanjay Mehrotra", "title": "Chairman, President and CEO", "aliases": [], "source": "test"},
        {"name": "Mark Murphy", "title": "EVP and CFO", "aliases": [], "source": "test"},
    ],
    "Intel": [
        # Pat Gelsinger left Intel in December 2024, so he is not on the roster.
        {"name": "Lip-Bu Tan", "title": "CEO", "aliases": [], "source": "test"},
        {"name": "David Zinsner", "title": "EVP and CFO", "aliases": [], "source": "test"},
    ],
    "AMD": [
        {"name": "Lisa Su", "title": "Chair and CEO", "aliases": [], "source": "test"},
    ],
    "Apple": [
        {"name": "Tim Cook", "title": "CEO", "aliases": [], "source": "test"},
    ],
    "CoreWeave": [
        {"name": "Michael Intrator", "title": "co-founder, chairman and CEO", "aliases": [], "source": "test"},
    ],
    "Anthropic": [
        {"name": "Dario Amodei", "title": "co-founder and CEO", "aliases": [], "source": "test"},
    ],
    "OpenAI": [
        {"name": "Sam Altman", "title": "CEO", "aliases": [], "source": "test"},
        {"name": "Sarah Friar", "title": "CFO", "aliases": [], "source": "test"},
    ],
    "Synopsys": [
        {"name": "Sassine Ghazi", "title": "president and CEO", "aliases": [], "source": "test"},
    ],
    "Cohere": [
        {"name": "Aidan Gomez", "title": "Co-founder and CEO", "aliases": [], "source": "test"},
    ],
    "Generac": [
        {"name": "Aaron Jagdfeld", "title": "President and Chief Executive Officer", "aliases": [], "source": "test"},
    ],
}


@unittest.skipUnless(media_pull is not None, "media_pull.py does not exist in this checkout")
class DecideTests(unittest.TestCase):

    def decide(self, title, description=""):
        """Call the puller's decision function and check the shape of what it returns."""
        result = media_pull.decide(title, description, ROSTER)
        self.assertEqual(len(result), 4, f"decide() must return (keep, node_id, exec_name, reason), got {result!r}")
        keep, node_id, exec_name, reason = result
        self.assertIsInstance(keep, bool)
        self.assertTrue(reason, "every decision needs a reason for media/sync_state.json")
        return keep, node_id, exec_name, reason

    def assertKept(self, title, node_id, exec_name, description=""):
        keep, got_node, got_exec, reason = self.decide(title, description)
        self.assertTrue(keep, f"should be kept: {title!r} (reason given: {reason})")
        self.assertEqual(got_node, node_id)
        self.assertEqual(got_exec, exec_name)

    def assertSkipped(self, title, description=""):
        keep, _node, _exec, reason = self.decide(title, description)
        self.assertFalse(keep, f"should be skipped: {title!r} / {description!r} (reason given: {reason})")

    # --- KEEP: a rostered executive is named as the person speaking -----------------------------------------------

    def test_keep_ceo_named_in_title(self):
        self.assertKept("Nvidia CEO Jensen Huang on AI demand: 'All of this is going to pass'", "NVIDIA", "Jensen Huang")

    def test_keep_full_interview(self):
        self.assertKept("Micron CEO Sanjay Mehrotra: HBM sold out through 2026 | Full interview", "Micron",
                        "Sanjay Mehrotra")

    # --- SKIP: analysts, rumors, explainers, former executives ------------------------------------------------------

    def test_skip_analyst_dan_ives(self):
        self.assertSkipped("Dan Ives: Nvidia is the most important stock")
        # Naming a rostered CEO does not let an analyst segment in: the analyst is the one speaking.
        self.assertSkipped("Dan Ives on Nvidia CEO Jensen Huang's comments")

    def test_skip_reportedly(self):
        self.assertSkipped("Nvidia reportedly in talks to invest in a new AI lab")

    def test_skip_sources_say(self):
        self.assertSkipped("Sources say Apple is planning a new chip supplier")

    def test_skip_stock_move_explainer(self):
        self.assertSkipped("Here's why Nvidia shares fell")

    def test_skip_analyst_explains(self):
        self.assertSkipped("Analyst explains AMD's outlook")

    def test_skip_former_ceo_not_on_roster(self):
        self.assertSkipped("Former Intel CEO Pat Gelsinger on the future of U.S. chipmaking")
        # The roster decides, not the word "former": an old-style title that still calls him CEO is skipped too.
        self.assertSkipped("Intel CEO Pat Gelsinger on the future of U.S. chipmaking")

    # --- SKIP: the description shows a reporter's segment or remarks made elsewhere (verification 2026-10-17) ------
    # The title alone would pass in each case; the description says someone else is speaking.

    def test_skip_reporter_with_the_latest_on_comments(self):
        self.assertSkipped("Nvidia CEO Jensen Huang says AI demand is insane",
                           "CNBC's Kif Leswing joins 'Closing Bell' with the latest on comments from Nvidia CEO "
                           "Jensen Huang.")

    def test_skip_bloomberg_recap_has_more(self):
        # the real description of Bloomberg 2d1WpPhg9Kw, under a title without the stock move
        self.assertSkipped("CoreWeave CEO Intrator Says Market Is Acting Irrationally",
                           "CoreWeave Chief Executive Officer Mike Intrator said the market is acting “irrationally"
                           "” and that he remains confident in the AI cloud company’s business model. Nick "
                           "Turner has more on \"The Asia Trade.\"")

    def test_skip_remarks_made_elsewhere_plus_bloomberg_intelligence(self):
        self.assertSkipped("Nvidia CEO Jensen Huang says China is nanoseconds behind in chips",
                           "Nvidia CEO Jensen Huang says China is 'nanoseconds behind' the US in chips. He made the "
                           "remarks at a conference in Washington. Mandeep Singh of Bloomberg Intelligence weighs in.")

    def test_skip_reporter_breaks_down_comments_made_at_computex(self):
        self.assertSkipped("Nvidia CEO Jensen Huang: AI factories are the future",
                           "CNBC's Kristina Partsinevelos joins 'Squawk Box' to break down comments made by Jensen "
                           "Huang at Computex.")

    def test_skip_interview_with_another_outlet(self):
        self.assertSkipped("Anthropic CEO Dario Amodei says AI could wipe out half of entry-level jobs",
                           "Anthropic CEO Dario Amodei in an interview with Axios said AI could eliminate half of all "
                           "entry-level white-collar jobs.")

    # --- SKIP: an "Exclusive:" scoop headline that names only the company -------------------------------------------

    def test_skip_exclusive_scoop_headlines(self):
        self.assertSkipped("Exclusive: Micron to build $100B fab in New York",
                           "Micron CEO Sanjay Mehrotra says the plant will open in 2030.")
        self.assertSkipped("Exclusive: Nvidia in talks to invest $5B in Intel",
                           "Nvidia is in talks to invest $5 billion in Intel. Nvidia CEO Jensen Huang says the deal "
                           "is good.")

    # --- KEEP: real interviews the first version skipped (rule 2 is met) -------------------------------------------

    def test_keep_family_name_with_company_in_title(self):
        # Bloomberg nrl9mZntIzM (2026-09-29)
        self.assertKept("Altman on OpenAI's IPO Plans, AI Agent Dots, AI Security", "OpenAI", "Sam Altman",
                        "OpenAI CEO Sam Altman talks about launching its new AI personal agent called Dots, which he "
                        "says is a premium product. Altman also says the company will go public at some point, but "
                        "it's being patient. He speaks to Bloomberg's Ed Ludlow in San Francisco.")

    def test_keep_executive_named_only_in_description(self):
        # Fox Business kDr-VsKjGeo (2026-10-04): the title names the company, the description the CEO
        self.assertKept("Synopsys, OpenAI develop NEW AI model for chip design work", "Synopsys", "Sassine Ghazi",
                        "Synopsys CEO Sassine Ghazi discusses the company's artificial intelligence chip design "
                        "partnerships with Amazon and OpenAI on ‘The Claman Countdown.’")

    def test_keep_appositive_title_and_bloomberg_speaking_with(self):
        # CNBC PXVx9o9sD20 (Generac) and Bloomberg u8ZID-SjZ2o (OpenAI CFO), CNBC 2YF3lR5m6yY (Cohere)
        self.assertKept("Generac CEO Aaron Jagdfeld on powering data centers and size of the market", "Generac",
                        "Aaron Jagdfeld",
                        "Aaron Jagdfeld, Generac chairman, president and CEO, joins 'Power Lunch' to discuss powering "
                        "AI data centers and the data center boom, power demand, and more.")
        self.assertKept("OpenAI CFO Friar on New AI Assistant, Capital Raise", "OpenAI", "Sarah Friar",
                        "OpenAI CFO Sarah Friar discusses the company's new proactive assistant Dots. Speaking with "
                        "Ed Ludlow on \"Bloomberg The Close,\" Friar also says OpenAI is \"really well capitalized.\"")
        self.assertKept("OpenAI–Hugging Face breach is a great example of how 'potent' these AI models are, says "
                        "Cohere CEO", "Cohere", "Aidan Gomez",
                        "Cohere CEO Aidan Gomez joins CNBC’s 'Squawk on the Street' to discuss the acquisition of "
                        "AI cybersecurity firm Aisle, rogue agents, AI safety, and more.")

    def test_open_source_is_not_a_second_hand_source(self):
        # CNBC ozJvva8bTyI's description talks about an "open source AI model": that is not "sources say"
        self.assertKept("Cohere CEO Aidan Gomez on its new open source AI model", "Cohere", "Aidan Gomez",
                        "Cohere CEO Aidan Gomez joins 'Closing Bell' to talk its new open source AI model.")
        self.assertSkipped("Cohere CEO Aidan Gomez on AI", "Sources say Cohere is raising new funding.")

    def test_company_name_alone_is_not_the_family_name(self):
        # "Dell" in a Dell headline is the company, not Michael Dell speaking
        roster = {"Dell": [{"name": "Michael Dell", "title": "CEO and Founder", "aliases": [], "source": "test"}]}
        keep, _node, _exec, reason = media_pull.decide("Dell: AI server orders keep growing", "", roster)
        self.assertFalse(keep, reason)

    def test_skip_family_name_two_executives_share(self):
        # Two rostered "Huang"s at two companies and a title that fits both: nobody can say who speaks
        roster = {"NVIDIA": [{"name": "Jensen Huang", "title": "CEO", "aliases": [], "source": "test"}],
                  "TSMC": [{"name": "Wendell Huang", "title": "CFO", "aliases": [], "source": "test"}]}
        keep, _node, _exec, reason = media_pull.decide("Huang says Nvidia and TSMC will build more fabs", "", roster)
        self.assertFalse(keep, reason)


@unittest.skipUnless(media_pull is not None, "media_pull.py does not exist in this checkout")
class TranscriptAndStateTests(unittest.TestCase):

    def test_fox_speaker_tag_starts_a_new_paragraph(self):
        # Fox captions put the anchor's tag inside a line: the question and the answer must not share a [mm:ss] line
        lines = [(155.0, "WE'RE BUILDING AS FAST AS WE CAN. LIZ: HOW BIG OF A START IS THAT?"),
                 (158.0, ">> IT IS A VERY BIG START.")]
        self.assertEqual(media_pull.paragraphs(lines),
                         ["[02:35] WE'RE BUILDING AS FAST AS WE CAN.",
                          "[02:35] LIZ: HOW BIG OF A START IS THAT?",
                          "[02:38] >> IT IS A VERY BIG START."])

    def test_soft_skip_is_decided_again_after_a_roster_or_rule_change(self):
        stamp = media_pull.decision_stamp("2026-10-17")
        soft = {"decision": "skip", "reason": "no rostered executive is named in the title or description",
                "stamp": stamp}
        self.assertTrue(media_pull.already_decided(soft, stamp))
        self.assertFalse(media_pull.already_decided(soft, media_pull.decision_stamp("2026-10-18")))
        self.assertFalse(media_pull.already_decided({"decision": "skip", "reason": "old record, no stamp"}, stamp))
        hard = {"decision": "skip", "reason": "rumor (in the title)", "hard": True}
        self.assertTrue(media_pull.already_decided(hard, media_pull.decision_stamp("2099-01-01")))
        self.assertFalse(media_pull.already_decided({"decision": "fail", "reason": "error"}, stamp))
        # a saved video whose transcript is not on disk (another checkout) is fetched again
        self.assertFalse(media_pull.already_decided({"decision": "saved", "file": "transcripts/media/none_x.txt"},
                                                    stamp))


if __name__ == "__main__":
    unittest.main()
