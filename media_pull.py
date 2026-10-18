"""
media_pull.py -- news-outlet interviews in which a named company executive speaks on camera
                 -> transcripts/media/<node-slug>_<YYYY-MM-DD>_<video id>.txt   (enrich inputs only)

The user's rule (2026-10-17): "찌라시면 시그널이면 안 돼. 무조건 뉴스여야 함. 회사 관계자가 직접 얘기한 거여야 해"
(a rumor is never a signal; it must be news, and a company official must have said it directly). So:

  1. Only the official YouTube channels of news outlets listed in media/channels.json are read
     (CNBC Television, CNBC International, Bloomberg Television, Yahoo Finance, Fox Business).
  2. A video is kept only when an executive on the company's roster (media/executives.json) is NAMED in the title
     or the description AND the title shows that person speaking ("<Name> on ...", "<Company> CEO <Name>: ...",
     "..., says <Name>", "full interview", "joins", ...). When the description names the executive too, it must
     show them speaking as well ("<Exec> joins / discusses / says ...", "sits down with <Exec>"). A title that
     names only the company counts when the description's first sentence has the fully named executive as the
     speaking subject ("Synopsys CEO Sassine Ghazi discusses ..."), never for an "Exclusive:" scoop headline.
  3. Rumors, reports, "sources say", analyst / strategist / anchor commentary, "here's why the stock fell" explainers,
     stock-move segments and show compilations are always skipped (Dan Ives and other analysts never get in).
  4. The saved transcript is the enrich session's input: only the named executive's own first-person words may become
     a signal (enrich skill section 11). Machine captions are marked as such in the "# TRANSCRIPT:" header line.
  5. Nothing of the video or the transcript is shown on the website.

How it runs (no API key, no cookies, no login):
  a. Each channel's RSS feed lists its latest 15 uploads (with descriptions). When those 15 do not reach back to the
     start of the --days window (a busy channel posts 40+ videos a day), or when --days is more than 7, the channel's
     /videos tab is also listed with `yt-dlp --flat-playlist` (titles and approximate dates only).
  b. decide(title, description, roster) keeps or skips each video and gives the reason. A listed video without a
     description is looked up with `yt-dlp -J` only when its title names a rostered person or company.
  c. For a kept video: YouTube's manual English captions, else its auto-captions, else (videos under 30 minutes)
     the audio is transcribed locally with faster-whisper ("small.en", cpu, int8). The text is written with a
     [mm:ss] timestamp every ~25 seconds (and at every ">>" speaker change of broadcast captions).
  d. Every decision and its reason goes to media/sync_state.json. A video already there as "saved" (and its file
     is on disk) or as a hard "skip" (a rumor, a report, a Short, ...) is not looked at again. Any other skip
     ("no rostered executive is named", "the title does not show the executive speaking", ...) carries a stamp: the
     roster's "updated" date plus DECIDE_VERSION. When the roster or the decision rules change, such a skip is
     decided again the next time its video is in the --days window. A "fail" (network error, captions not ready
     yet) is retried on the next runs, 3 times at most.

    python -X utf8 media_pull.py                     # the default window: the last 2 days
    python -X utf8 media_pull.py --days 7 --dry-run  # print the decisions only, save nothing
    python -X utf8 media_pull.py --only-video <id>   # one video (it must come from an allowlisted channel)

Politeness: one run a day (a second run on the same day stops at once unless --force), a pause before every
yt-dlp call, and a run-time budget (--max-minutes, default 15) because routine/market_data.ps1 gives this step
20 minutes. Never crashes on one video: each video has its own try/except. Exit code 0, unless nothing at all
could be fetched (no channel listing and no --only-video video could be read) -> 1.
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
MEDIA_DIR = ROOT / "media"                       # channels.json, executives.json, sync_state.json
OUT_DIR = ROOT / "transcripts" / "media"         # one transcript per kept video

# The fixed NOTE header line (contract shared with the enrich skill, section 11).
NOTE = ("news interview; only the named executive's own first-person words may become signals; "
        "anchor/reporter/analyst lines and anything reported second-hand never count")

PAUSE_SECONDS = 3            # wait this long before every yt-dlp call (be polite to YouTube)
MAX_ATTEMPTS = 3             # a failing video is retried on this many runs, then recorded as a skip
WHISPER_MAX_SECONDS = 30 * 60    # only videos shorter than this are transcribed locally when they have no captions
LONG_SHOW_SECONDS = 40 * 60      # a longer video is a whole show (many guests) unless its title says "interview"
PARAGRAPH_SECONDS = 25           # one [mm:ss] timestamp about every 25 seconds
# Change this whenever decide() changes what it keeps: every skip that was not a hard exclusion is then decided
# again (see "d." above), so a video skipped by an older rule gets a second look.
DECIDE_VERSION = "2026-10-17.2"


# =====================================================================================================================
# 1. Text helpers
# =====================================================================================================================

def norm(text):
    """Lower-case text with accents removed and curly quotes / dashes made plain, for matching.
    'Benoît O’Hanley — CEO' -> "benoit o'hanley - ceo"."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for fancy, plain in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), (" ", " ")):
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text).strip().lower()


def word(phrase):
    """A regex for a normalized phrase as whole words: 'su' must not match inside 'super'."""
    return r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"


def slug(name):
    """'Applied Materials' -> 'appliedmaterials' (the same rule as av.py / tw.py / defeatbeta_fetch.py)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)                            # write-then-rename: a killed run never leaves half a file


# Lines where a YouTube description stops being the outlet's summary and becomes boilerplate.
BOILERPLATE = re.compile(
    r"^\s*(»|►|▶|->|subscribe|for access to|watch more|to watch more|watch the full|follow|connect with|like us|"
    r"turn to|download|get the|sign up|more from|visit|check out|read more|--|—|__|#|https?://|this post was|"
    r"for full episodes|about (cnbc|bloomberg|yahoo|fox)|bloomberg (television|tv) brings)", re.I)


def description_summary(description):
    """The outlet's own summary at the top of a description (it names the guest), without the subscribe links."""
    kept = []
    for line in (description or "").splitlines():
        if BOILERPLATE.match(line):
            break
        if line.strip():
            kept.append(line.strip())
    summary = re.sub(r"#\w+", " ", " ".join(kept))      # Fox Business adds "#breakingnews #report ..." inline
    return re.sub(r"\s+", " ", summary).strip()[:800]


# =====================================================================================================================
# 2. The roster: who counts as a company official
# =====================================================================================================================

# Words that name an executive role in a title ("Nvidia CEO", "Micron's chief financial officer", "AMD chair").
ROLE = (r"(?:co-?founder|founder|chief executive officer|chief executive|chief [a-z]+ officer|ceo|cfo|coo|cto|cio|"
        r"cmo|cso|president|vice chair(?:man|woman)?|executive chair(?:man|woman)?|chair(?:man|woman|person)?|"
        r"chief|head|boss|exec|executive)")
TICKER = r"(?:\s*\((?:[a-z]+:\s*)?[a-z0-9.]{1,8}\))?"          # "Nvidia (NVDA) CEO", "Nvidia (NASDAQ: NVDA) CEO"
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
CORPORATE_ENDINGS = re.compile(r"\s+(holdings|technology|technologies|group|corporation|corp\.?|inc\.?|platforms|"
                               r"co\.?|ltd\.?|limited|plc|ag|se|nv|n\.v\.)$", re.I)

_ALIASES = None


def node_aliases():
    """Other English names of graph nodes ("Google" -> "Alphabet", "Foxconn" -> "Hon Hai"), from the alias table
    verify_graph.py already keeps. Loaded once, lazily; an empty table when it cannot be read."""
    global _ALIASES
    if _ALIASES is None:
        try:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from verify_graph import KO_ALIASES
            _ALIASES = KO_ALIASES
        except Exception:
            _ALIASES = {}
    return _ALIASES


def company_forms(node):
    """How a news title can write a graph node's name: 'GUC (Global Unichip)' -> ['global unichip', 'guc'];
    'Arm Holdings' -> ['arm holdings', 'arm']; 'Google' -> ['google', 'alphabet', 'google cloud', ...]."""
    forms = {node}
    base = re.sub(r"\s*\(.*?\)\s*", " ", node).strip()
    forms.add(base)
    forms.update(re.findall(r"\((.*?)\)", node))
    forms.add(CORPORATE_ENDINGS.sub("", base))
    for alias in node_aliases().get(node, []):
        if alias.isascii():
            forms.add(alias)
    return sorted({norm(f) for f in forms if len(norm(f)) >= 2}, key=len, reverse=True)


def family_name(name):
    """'Jensen Huang' -> 'huang', 'Hock E. Tan' -> 'tan', 'Paulo Ruiz Jr.' -> 'ruiz'; None for a one-word name."""
    tokens = [t for t in norm(name or "").split() if t not in NAME_SUFFIXES]
    return tokens[-1] if len(tokens) >= 2 else None


def build_executives(companies):
    """The roster's "companies" block -> one dict per executive with the name forms used for matching."""
    executives = []
    for node, people in (companies or {}).items():
        forms = company_forms(node)
        # A family name that two people of one company share ("Lee" at Samsung) cannot tell which of them a
        # title means, so it never counts alone for that company (the full name still does).
        families = Counter(family_name(p.get("name")) for p in people or [])
        for person in people or []:
            name = (person.get("name") or "").strip()
            if not name:
                continue
            full_names, singles = {norm(name)}, set()
            family = family_name(name)
            if family and families[family] == 1:
                singles.add(family)                      # the family name: "huang", "su", "mehrotra"
            for alias in person.get("aliases") or []:
                alias = norm(alias)
                if " " in alias:
                    full_names.add(alias)                # "jay y. lee" -> counts as the full name
                elif len(alias) >= 2:
                    singles.add(alias)                   # one-word aliases only count next to the company / role
            executives.append({
                "node": node, "name": name, "title": person.get("title") or "",
                "full_names": sorted(full_names, key=len, reverse=True),
                "singles": sorted(singles), "company_forms": forms,
            })
    return executives


_EXEC_CACHE = {}


def executives_for(roster):
    """build_executives() once per roster object (decide() is called for hundreds of titles per run)."""
    key = id(roster)
    if key not in _EXEC_CACHE:
        _EXEC_CACHE.clear()
        _EXEC_CACHE[key] = (roster, build_executives(roster))
    return _EXEC_CACHE[key][1]


def role_agrees(role, title):
    """Does the role word in a headline ('ceo', 'cfo', 'president') fit the roster title ('EVP and CFO')?"""
    role, title = norm(role), norm(title)
    if "founder" in role:
        return "founder" in title
    if role in ("ceo", "chief executive", "chief executive officer"):
        return "ceo" in title or "chief executive" in title
    acronyms = {"cfo": "financial", "coo": "operating", "cto": "technology", "cio": "information",
                "cmo": "marketing", "cso": "strategy"}
    if role in acronyms:
        return role in title or f"chief {acronyms[role]}" in title
    if role.startswith("chief ") and role.endswith(" officer"):
        return role[:-len(" officer")] in title
    if role == "president":
        return re.search(r"(?<!vice )president", title) is not None
    if "chair" in role:
        return "chair" in title
    return True                                          # "chief", "head", "boss", "exec", "executive": any role


def mentions(person, text):
    """Every place a normalized text refers to `person`, as merged spans [(start, end, {kinds})].

    kinds: "name"          the full name or a multi-word alias            ("jensen huang")
           "company_last"  company + family name                          ("nvidia's huang", "nvidia ceo huang")
           "role_last"     role + family name                             ("ceo huang"; needs the company nearby)
           "company_role"  company + a role that fits the roster title    ("nvidia ceo"; needs the name nearby)
           "last_with_company"  the family name alone while the same text names the company somewhere else
                                ("Altman on OpenAI's IPO Plans"); the company's own name never counts as the
                                family name ("Dell" in "Dell earnings: ..." is the company, not Michael Dell)
    Touching spans are merged, so "nvidia ceo jensen huang" is ONE mention."""
    spans = []
    for full in person["full_names"]:
        spans += [(m.start(), m.end(), "name") for m in re.finditer(word(full), text)]
    # where the text names the person's company (for "last_with_company")
    company_spans = [(m.start(), m.end()) for comp in person["company_forms"] if comp in text
                     for m in re.finditer(word(comp), text)]
    for single in person["singles"]:
        if single not in text:
            continue
        if company_spans:
            for m in re.finditer(word(single), text):
                if not any(s < m.end() and m.start() < e for s, e in company_spans):
                    spans.append((m.start(), m.end(), "last_with_company"))
        # after a role, one first-name word may differ from the roster: "CoreWeave CEO Mike Intrator" (Michael)
        for comp in person["company_forms"]:
            pattern = word(comp) + TICKER + r"(?:'s|')?\s+(?:" + ROLE + r"\s+(?:[a-z][a-z.'-]*\s+)?)?" + word(single)
            spans += [(m.start(), m.end(), "company_last") for m in re.finditer(pattern, text)]
        for m in re.finditer(r"(?<![a-z0-9])(" + ROLE + r")\s+(?:[a-z][a-z.'-]*\s+)?" + word(single), text):
            if role_agrees(m.group(1), person["title"]):
                spans.append((m.start(), m.end(), "role_last"))
    for comp in person["company_forms"]:
        if comp not in text:
            continue
        for m in re.finditer(word(comp) + TICKER + r"(?:'s|')?\s+(" + ROLE + r")(?![a-z0-9])", text):
            if role_agrees(m.group(1), person["title"]):
                spans.append((m.start(), m.end(), "company_role"))
        # the same, written the other way round: "chief executive of Micron", "head of Amazon Prime Video on ..."
        # (up to three division words may follow the company when "on" / ":" / "says" comes right after them)
        for m in re.finditer(r"(?<![a-z0-9])(" + ROLE + r")\s+of\s+" + word(comp) +
                             r"(?:(?:\s+[a-z0-9&.'-]+){1,3}?(?=\s*(?::|\bon\b|\bsays?\b)))?", text):
            if role_agrees(m.group(1), person["title"]):
                spans.append((m.start(), m.end(), "company_role"))
    merged = []
    for start, end, kind in sorted(spans):
        if merged and start <= merged[-1][1] + 1:          # overlapping or separated by one space
            last = merged[-1]
            merged[-1] = (last[0], max(last[1], end), last[2] | {kind})
        else:
            merged.append((start, end, {kind}))
    return merged


def company_named(person, text):
    """Is the person's company named anywhere in the text? (substring test first: it is much faster)"""
    return any(comp in text and re.search(word(comp), text) for comp in person["company_forms"])


# =====================================================================================================================
# 3. The decision: keep only a named, rostered executive speaking; never rumors, reports or commentary
# =====================================================================================================================

# HARD exclusions: any match in the title OR the description summary skips the video. (pattern, reason)
HARD_EXCLUDE = [
    (r"\breportedly\b", "second-hand: 'reportedly'"),
    # "sources say", "according to sources" -- not "open source", "power source", "source code", "sources of ..."
    (r"(?<!open )(?<!open-)(?<!power )(?<!energy )(?<!single )(?<!data )(?<!revenue )\bsources?\b"
     r"(?!\s+(?:of|code)\b)", "second-hand: 'sources'"),
    (r"\baccording to\b", "second-hand: 'according to'"),
    (r"\bpeople (familiar|close to|with knowledge)\b|\bfamiliar with the matter\b|\bleak(s|ed)?\b",
     "second-hand: unnamed people / leak"),
    (r"\brumou?r(s|ed)?\b|\bspeculation\b", "rumor"),
    # an analyst speaking or quoted ("Analyst explains ...", "analysts say", "Wedbush analyst ..."); NOT the topic
    # words of an executive interview ("following latest analyst valuations", "beat analyst estimates", "analyst day")
    (r"\banalysts?'?(?!'?\s+(day|valuations?|estimates?|expectations?|forecasts?|ratings?|upgrades?|downgrades?|"
     r"(price )?targets?|consensus|meeting|event|calls?)\b)\b", "analyst content"),
    (r"\bstrategists?\b", "strategist content"),
    (r"\bdan ives\b|\bwedbush\b", "analyst content (Dan Ives)"),
    (r"\breact(s|ed|ing|ion|ions)?\b", "reaction segment"),
    (r"\b(shares|stocks?)\s+(jump|surge|soar|fall|fell|slide|slid|sink|sank|drop|tumble|rise|rose|rall|plunge|climb|"
     r"pop|slump|gain|rebound|spike|crash|tank|skyrocket)\w*", "stock-move segment"),
    (r"^(jim\s+)?cramer\b|\bcramer'?s\b|\bcramer\s+(says|on|thinks|explains|breaks|reacts|weighs|gives|picks?|likes|"
     r"warns)\b|\blightning round\b|\bfinal trades?\b", "Cramer / show commentary"),
    (r"\baudio only\b|\bfull episode\b|\bfull show\b|\bmarket (open|midday|close)\b|\bweek ahead\b|\bheadlines\b|"
     r"\bnews quiz\b|#shorts\b", "show compilation / headlines"),
    (r"\bon x\b|\btweets?\b|\btweeted\b|\bposted on\b|\bsocial media post\b|\bx post\b|\bmemo\b|\bletter to\b|"
     r"\bblog post\b|\btold (employees|staff)\b|\binternal (email|meeting)\b",
     "statement relayed second-hand (post / memo / letter)"),
    (r"\bdeepfake\b|\bai-generated\b|\bparody\b|\bimpersonat", "not the real person"),
    (r"\bopinion\b|\bop-ed\b|\bcolumn(ist)?\b|\bcommentary\b", "opinion / commentary"),
]
# Extra hard exclusions for the TITLE only: the executive's remarks reported as a news headline.
TITLE_ONLY_EXCLUDE = [
    (r"\bafter\b[^.]{0,80}\b(says|said|comments|remarks|warns|warned)\b", "headline about remarks made elsewhere"),
]
# Extra hard exclusions for the DESCRIPTION only: it reports what the executive said somewhere else.
DESCRIPTION_ONLY_EXCLUDE = [
    (r"\bsaid (at|during|on|in a)\b", "the description reports remarks made elsewhere"),
    (r"'s (comments|remarks)\b", "the description reports remarks made elsewhere"),
    # "Bloomberg's Ed Ludlow said that ... Nvidia's Jensen Huang have downplayed ..." = the outlet's journalist
    # talking about the executive. ("CNBC's David Faber sits down with Dell CEO Michael Dell" is not caught.)
    (r"\b(bloomberg|cnbc|yahoo finance|yahoo|fox business|fox)(?: news| tv| television)?'s [a-z.'-]+(?: [a-z.'-]+)"
     r"{0,2} (said|says|reports?|explains?|breaks? down|looks at|takes a look|details|walks (?:us )?through|"
     r"weighs in|recaps?|has (?:more|the latest|the details))\b", "a reporter's segment (the outlet's journalist speaks)"),
    # "... Nick Turner has more on 'The Asia Trade'", "X joins 'Closing Bell' with the latest on comments from ...":
    # a reporter tells what the executive said
    (r"\bhas more\b", "a reporter's segment ('has more')"),
    (r"\bwith the latest on\b", "a reporter's segment ('with the latest on')"),
    (r"\b(comments|remarks) (made |from |by )", "the description reports remarks made elsewhere"),
    (r"\bmade (the|his|her|those|these) (remarks|comments)\b", "the description reports remarks made elsewhere"),
    (r"\bspoke (at|during)\b", "the description reports remarks made elsewhere"),
    (r"\bbloomberg intelligence\b", "analyst content (Bloomberg Intelligence)"),
]
# "... told reporters", "... tells investors", "in an interview with Axios", "speaking to the Financial Times": the
# words were said to someone else, not on this outlet's camera. Allowed only when the rest of the sentence names the
# outlet or one of its shows ("tells CNBC's Jim Cramer", "speaking with Ed Ludlow on 'Bloomberg The Close'").
RELAYED = re.compile(r"\b(told|tells|in an interview with|speaking (?:to|with))\s+")
# "report" is second-hand ("a report says", "CNBC's X reports") EXCEPT the company's own results report.
REPORT = re.compile(r"\breport(s|ed|ing)?\b")
EARNINGS_WORDS = re.compile(r"\b(earnings|results|quarter|quarterly|q[1-4]|annual|financial|revenue|sales|profit|"
                            r"loss|record|guidance|beat|miss|after reporting|company reported|it reported)\b")
# SOFT exclusions (explainer framing): skipped unless the executive is already the speaking subject before them
# ("Jensen Huang explains why ..." is the executive; "Here's why Nvidia CEO ..." is an explainer).
SOFT_EXCLUDE = [
    (r"\bhere'?s (why|what|how)\b", "explainer ('here's why / what')"),
    (r"\bwhat (it|this|that|they|he|she) means?\b|\bmeans? for\b", "explainer ('what it means')"),
    (r"\bexplains? why\b|\bbreaks? down\b|\bweighs? in\b", "commentary ('explains why' / 'breaks down')"),
    (r"\bwhat to (know|expect|watch)\b|\bwhat we know\b|\btakeaways?\b", "explainer ('what to know')"),
]

# The title shows the person speaking when the mention is followed by one of these ...
SPEAK_AFTER = re.compile(
    r"(?:,\s*)?(?::|-\s|\|\s|(?:on|says?|said|joins?|speaks?|talks?|tells?|discuss(?:es)?|explains?|breaks? down|"
    r"details?|outlines?|reveals?|warns?|predicts?|sees?|expects?|touts?|defends?|addresses?|responds?|shares?|"
    r"believes?|thinks?|calls?|argues?|insists?|downplays?|dismiss(?:es)?|weighs? in|sits? down|goes one-on-one|"
    r"answers?|unveils?|announces?|confirms?|denies|hopes?|vows?|pledges?|promises?|admits?|acknowledges?|gives?|"
    r"offers?|describes?|suggests?|stresses?|emphasi[sz]es?|highlights?|discloses?|delivers?|presents?|showcases?|"
    r"teases?|slams?|blasts?|pushes back|claims?|forecasts?|projects?|doubles? down|reflects?|recalls?|lays out|"
    r"makes the case|sounds (?:off|the alarm)|opens up|interview|keynote|in conversation)(?![a-z0-9]))")
# ... or when it closes the title as the attribution ("..., says Micron CEO Sanjay Mehrotra", "Quote | Name").
# (a bare role may stand between: "..., says CEO Sanjay Mehrotra", "..., says chief executive Lisa Su")
SPEAK_BEFORE_END = re.compile(r"(?:says|said|:|\||-|,|with|from)(?:\s+" + ROLE + r")?\s*$")
# Words anywhere in the title that mean an interview / remarks of the person the title names.
INTERVIEW = re.compile(r"(?<![a-z0-9])(full interview|interview|one-on-one|sits? down|sit-down|sitdown|joins|"
                       r"joined by|in conversation|conversation with|fireside chat|keynote|exclusive|q&a|"
                       r"testif(?:y|ies)|testimony|remarks|speech)(?![a-z0-9])")
# The same, for a title that names only the company ("Full interview: inside Nvidia"). "Exclusive", "remarks" and
# "speech" are left out: "Exclusive: Micron to build a $100B fab" is a reporter's scoop, and "remarks" / "speech"
# without the speaker's name are usually a report of what was said elsewhere.
COMPANY_ONLY_INTERVIEW = re.compile(r"(?<![a-z0-9])(full interview|interview|one-on-one|sits? down|sit-down|sitdown|"
                                    r"joins|joined by|in conversation|conversation with|fireside chat|keynote|q&a|"
                                    r"testif(?:y|ies)|testimony)(?![a-z0-9])")
EXCLUSIVE = re.compile(r"(?<![a-z0-9])exclusive(?![a-z0-9])")
OWN_WORDS = re.compile(r"(?<![a-z0-9])(full interview|interview|keynote|remarks|speech|fireside chat|testimony)"
                       r"(?![a-z0-9])")

# In a DESCRIPTION the executive counts as speaking only when the speaking word belongs to them: they are its
# subject ("Cohere CEO Aidan Gomez joins ...", "Aaron Jagdfeld, Generac chairman, president and CEO, joins ...",
# "Altman also says ...") or its object ("CNBC's David Faber sits down with Dell CEO Michael Dell"). Not when a
# reporter is the subject and the executive only appears later ("CNBC's Kif Leswing joins 'Closing Bell' with the
# latest on comments from Nvidia CEO Jensen Huang"). Present tense only: "Mike Intrator said ..." is a recap.
DESCRIPTION_VERB = (r"(?:joins|joined|sits down|discusses|talks|speaks|says|explains|breaks down|weighs in|shares|"
                    r"outlines|details|tells|answers|goes one-on-one|offers|gives|lays out|describes|reveals|"
                    r"addresses|responds|walks us through|previews|unveils)")
# the mention, then maybe an appositive (", Generac chairman, president and CEO,"), maybe "also", then the verb
SUBJECT_AFTER = re.compile(r"(?:\s*,[^.;:!?]{0,90}?,?)?\s+(?:also\s+)?" + DESCRIPTION_VERB + r"(?![a-z0-9])")
# "Dell CEO Michael Dell and ServiceNow CEO Bill McDermott join ..."
SUBJECT_AND = re.compile(r"\s+(?:and|&)\s+[^.;:!?]{0,80}?\s+(?:join|discuss|talk|speak|sit down)(?![a-z0-9])")
OBJECT_BEFORE = re.compile(r"(?:sits? down with|sat down with|speaks? with|talks? with|interview with|interviews|"
                           r"conversation with|chats? with|catches up with|joined by|one-on-one with)\s+$")
SUBORDINATE = re.compile(r"\b(as|after|while|when|amid|following|since|because)\s+(?:[a-z0-9&.'()-]+\s+){0,3}$")
FORMER = re.compile(r"\b(former|ex|retired|outgoing|the late)\b[- ](?:[a-z0-9&.'()-]+\s+){0,3}$")


# A title that ENDS in an attribution names its speaker there: "...: Chris Hughes", "..., says Fundstrat's Tom Lee",
# "... | Nvidia CEO Jensen Huang". TAIL finds that last short piece (on the original title, capitals kept).
TAIL = re.compile(r"(?:[:|]|\s-\s|,?\s+says)\s+([^:|]{1,60}?)\s*$")
TAIL_STOPWORDS = {"is", "are", "was", "were", "be", "will", "can", "could", "has", "have", "had", "the", "a", "an",
                  "to", "of", "for", "in", "on", "and", "or", "not", "it", "it's", "its", "we", "we're", "i", "i'm",
                  "you", "they", "this", "that", "more", "very", "all", "no", "how", "why", "what", "full",
                  "interview"}
SHOW_NAMES = re.compile(r"\b(bloomberg|cnbc|yahoo|fox|squawk|closing bell|mad money|surveillance|the close|"
                        r"power lunch|halftime|money movers|fast money|countdown|mornings with|varney|kudlow|"
                        r"opening bid|market domination|catalysts|balance of power|wall street week|the exchange|"
                        r"last call|overtime|street signs|worldwide exchange|asia trade|china show|morning brief|"
                        r"making money|big money|cavuto)\b", re.I)


def credited_to_someone_else(title, person):
    """True when the title ends by naming another speaker: 'AI needs to be regulated by someone besides Sam Altman
    and Dario Amodei: Chris Hughes' is Chris Hughes talking about Sam Altman, not Sam Altman speaking."""
    m = TAIL.search(title.replace("’", "'").strip())
    if not m:
        return False
    tail = m.group(1).strip(" '\"")
    words = tail.split()
    if not 1 <= len(words) <= 5 or SHOW_NAMES.search(tail):
        return False                                     # a quote, or the show's name ("| Bloomberg The Close")
    if any(w.lower().strip(".,!?'\"") in TAIL_STOPWORDS for w in words):
        return False                                     # a sentence ("Demand Is Very Strong"), not a name
    if not all(w[0].isupper() or w[0].isdigit() for w in words):
        return False                                     # names are written with capitals
    t = norm(tail)
    if mentions(person, t) or company_named(person, t) or any(re.search(word(s), t) for s in person["singles"]):
        return False                                     # the tail is the executive ("...: CoreWeave CEO")
    return True


def hard_exclusion(text, where):
    """The reason a title / description summary is never a signal source, or None."""
    rules = HARD_EXCLUDE + (TITLE_ONLY_EXCLUDE if where == "title" else DESCRIPTION_ONLY_EXCLUDE)
    for pattern, reason in rules:
        if re.search(pattern, text):
            return f"{reason} (in the {where})"
    for m in REPORT.finditer(text):
        window = text[max(0, m.start() - 30): m.end() + 30]
        if not EARNINGS_WORDS.search(window):            # "earnings report" is the company's own results
            return f"second-hand: a report (in the {where})"
    if where == "description":
        for m in RELAYED.finditer(text):
            # the whole sentence the phrase stands in
            start = max(text.rfind(".", 0, m.start()), text.rfind("!", 0, m.start()), text.rfind("?", 0, m.start()))
            end = min([i for i in (text.find(".", m.end()), text.find("!", m.end()), text.find("?", m.end()))
                       if i >= 0] or [len(text)])
            if not SHOW_NAMES.search(text[start + 1:end]):
                return f"said to someone else ('{m.group(1)}'), not on this outlet's camera (in the description)"
    return None


def hard_reason(title, description):
    """The hard exclusion of a video's title or description summary (both normalized here), or None.
    A video skipped for one of these is never looked at again (see remember())."""
    for text, where in ((norm(title), "title"), (norm(description_summary(description)), "description")):
        reason = hard_exclusion(text, where) if text else None
        if reason:
            return reason
    return None


def speaks_in_title(person, title, description=""):
    """(True, position) when the title shows `person` speaking; (False, why) otherwise.

    title        the normalized title
    description  the normalized description summary; used only when the title names the company but not the
                 person: then the description's first sentence must have the fully named executive as the
                 speaking subject (Fox: "Synopsys, OpenAI develop NEW AI model for chip design work" +
                 "Synopsys CEO Sassine Ghazi discusses ..."). The position is then the end of the title, so any
                 explainer framing in the title (SOFT_EXCLUDE) still skips the video."""
    spans = mentions(person, title)
    if not spans:
        if not company_named(person, title):
            return False, "the title does not name the executive or the company"
        m = COMPANY_ONLY_INTERVIEW.search(title)
        if m:
            return True, m.start()                        # "Full interview: inside Nvidia" + the name in the description
        if EXCLUSIVE.search(title):
            return False, "an 'Exclusive' headline that names only the company (a reporter's scoop)"
        if description and speaks_in_description(person, first_sentence(description), full_name_only=True):
            return True, len(title)
        return False, ("the title names the company but not the executive, and the description does not open "
                       "with the executive speaking")
    possessive_only = all(title[end:end + 2] in ("'s", "s'") or title[end:end + 1] == "'" for _, end, _ in spans)
    if possessive_only and not OWN_WORDS.search(title):
        return False, "the title only talks about the executive (possessive), not with them"
    usable = [(s, e) for s, e, _ in spans if not SUBORDINATE.search(title[:s])]
    if not usable:
        return False, "the executive appears only in a headline clause ('as / after <name> ...')"
    for start, end in usable:
        after = title[end:].lstrip(" )'\"")
        if SPEAK_AFTER.match(after):
            return True, start
        if re.match(r"(?:and|&)\s", after) and SPEAK_AFTER.search(after):
            return True, start                                # "Microsoft CEO Satya Nadella and OpenAI's Altman on ..."
        tail = re.sub(r"[\W_]+", "", re.sub(r"\(?full interview\)?|\binterview\b", "", after))
        if not tail and SPEAK_BEFORE_END.search(title[:start].rstrip(" '\"")):
            return True, start                                # "..., says Nvidia CEO Jensen Huang"
    if INTERVIEW.search(title):
        return True, usable[0][0]
    return False, "the title does not show the executive speaking"


def first_sentence(text):
    """'cohere ceo aidan gomez joins cnbc. he talks about ...' -> 'cohere ceo aidan gomez joins cnbc.'"""
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def speaks_in_description(person, text, full_name_only=False):
    """Does the (normalized) description show `person` speaking? Only when a speaking word belongs to them:
    they are its subject ("<exec> joins / discusses / says"), or its object ("sits down with <exec>").
    full_name_only: count only mentions that carry the full name (for a title that names only the company)."""
    for start, end, kinds in mentions(person, text):
        if full_name_only and "name" not in kinds:
            continue
        m = SUBJECT_AFTER.match(text[end:])
        # an appositive that names the outlet or another person ("..., CNBC's Jon Fortt says") is not the exec's
        if m and not re.search(r"'s\b|\b(cnbc|bloomberg|yahoo|fox)\b", m.group(0)):
            return True
        if SUBJECT_AND.match(text[end:]):
            return True
        if OBJECT_BEFORE.search(text[:start]):
            return True
    return False


def decide(title, description, roster):
    """Keep a news video only when a rostered executive is named and the title shows them speaking.

    title, description  the video's title and YouTube description (the description may be "")
    roster              the "companies" block of media/executives.json: {graph node id: [{name, title, aliases}]}
    Returns (keep, node_id, exec_name, reason); node_id / exec_name are None when the video is skipped."""
    t = norm(title)
    d = norm(description_summary(description))
    reason = hard_reason(title, description)
    if reason:
        return False, None, None, reason

    # Who is NAMED (rule 2: the name, or the family name next to the company, in the title or the description)?
    named, former = [], []
    for person in executives_for(roster):
        found = [(text, s, e, kinds) for text in (t, d) for s, e, kinds in mentions(person, text)]
        if not found:
            continue
        by_name = any(k & {"name", "company_last", "last_with_company"} for _, _, _, k in found) or \
            (any("role_last" in k for _, _, _, k in found) and (company_named(person, t) or company_named(person, d)))
        if not by_name:
            continue                                      # "Intel CEO" alone does not name anyone
        if any(FORMER.search(text[:s]) for text, s, _, _ in found):
            former.append(person["name"])
            continue
        named.append(person)
    if not named:
        if former:
            return False, None, None, f"former executive: {', '.join(former)}"
        return False, None, None, "no rostered executive is named in the title or description"

    # Does the TITLE show one of them speaking? The earliest speaker in the title is the video's speaker.
    # And when the description names them too, the speaking word there must belong to them: "Nvidia CEO Jensen
    # Huang says ...", "sits down with Dell CEO Michael Dell" -- not "... with the latest on comments from Nvidia CEO
    # Jensen Huang" or "Nvidia's Jensen Huang have downplayed concerns" (a reporter's recap).
    speakers, why_not = [], []
    for person in named:
        ok, info = speaks_in_title(person, t, d)
        if ok and credited_to_someone_else(title, person):
            ok, info = False, "the title credits its words to someone else (a name at the end of the title)"
        if ok and d and mentions(person, d) and not speaks_in_description(person, d):
            ok, info = False, "the description talks about the executive but does not show them speaking"
        if ok:
            speakers.append((info, person))
        else:
            why_not.append(f"{person['name']}: {info}")
    if not speakers:
        return False, None, None, "; ".join(why_not)
    # One person on two rosters (Elon Musk: Tesla and SpaceX/xAI): the company the title names wins, then the
    # company the description names. When two rostered people are still level (the same family name at two
    # companies, or Elon Musk with neither company named), nobody can say whose words these are: skip.
    ranked = sorted(((pos, 0 if company_named(p, t) else 1 if company_named(p, d) else 2, p) for pos, p in speakers),
                    key=lambda item: (item[0], item[1]))
    position, rank, speaker = ranked[0]
    level = [p for pos, r, p in ranked if (pos, r) == (position, rank)]
    if len(level) > 1:
        names = ", ".join(f"{p['name']} ({p['node']})" for p in level)
        return False, None, None, f"ambiguous speaker: the title and description fit {names} equally"

    for pattern, reason in SOFT_EXCLUDE:
        m = re.search(pattern, t)
        if m and m.start() < position:
            return False, None, None, f"{reason} (in the title)"

    return True, speaker["node"], speaker["name"], f"{speaker['name']} ({speaker['title']}, {speaker['node']}) speaks"


def title_could_pass(title, roster):
    """Cheap pre-check for a listed video that has no description yet: is it worth one `yt-dlp -J` lookup?
    True when the title mentions a rostered person ("Jensen Huang", "Nvidia's Huang", "Nvidia CEO") or names a
    company that has a rostered executive at all: Fox Business titles often leave the guest's name out
    ("Synopsys, OpenAI develop NEW AI model ..."), and only the description says who speaks."""
    t = norm(title)
    return any(mentions(p, t) or company_named(p, t) for p in executives_for(roster))


# =====================================================================================================================
# 4. YouTube: channel listings, video metadata, captions, audio
# =====================================================================================================================

_last_call = [0.0]


def ytdlp(args, timeout=300):
    """Run yt-dlp as `python -m yt_dlp` (no PATH dependency) after the polite pause; return (code, out, err).
    --js-runtimes node: yt-dlp needs a JavaScript runtime for YouTube, and node is the one installed here."""
    wait = PAUSE_SECONDS - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    try:
        p = subprocess.run([sys.executable, "-X", "utf8", "-m", "yt_dlp", "--js-runtimes", "node", "--no-warnings",
                            *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    finally:
        _last_call[0] = time.time()


ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/"}


def read_rss(channel):
    """The channel's RSS feed -> its latest ~15 videos [{id, title, description, published, is_short}]
    and the feed's own channel title (checked against the allowlist name)."""
    r = requests.get(channel["rss"], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    feed = ET.fromstring(r.content)
    feed_title = feed.findtext("a:title", default="", namespaces=ATOM)
    videos = []
    for entry in feed.findall("a:entry", ATOM):
        link = entry.find("a:link", ATOM)
        videos.append({
            "id": entry.findtext("yt:videoId", default="", namespaces=ATOM),
            "title": entry.findtext("a:title", default="", namespaces=ATOM),
            "description": entry.findtext("media:group/media:description", default="", namespaces=ATOM),
            "published": entry.findtext("a:published", default="", namespaces=ATOM)[:10],   # UTC date
            "is_short": "/shorts/" in (link.get("href", "") if link is not None else ""),
        })
    return feed_title, videos


def read_videos_tab(channel, days):
    """The channel's /videos tab (newest first) via `yt-dlp --flat-playlist`: id, title, duration and an
    approximate upload date ("3 days ago"), no description. Used when the RSS feed does not cover the window."""
    end = min(100 * days + 50, 2000)                     # Bloomberg Television posts ~75 videos a day
    code, out, err = ytdlp(["--flat-playlist", "--extractor-args", "youtubetab:approximate_date",
                            "--playlist-end", str(end), "--print",
                            "%(id)s\t%(upload_date)s\t%(duration)s\t%(title)s",
                            f"https://www.youtube.com/channel/{channel['channel_id']}/videos"])
    videos = []
    for line in out.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4 or not re.fullmatch(r"\d{8}", parts[1]):
            continue
        vid, day, duration, title = parts
        videos.append({"id": vid, "title": title, "description": None,
                       "published": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                       "duration": float(duration) if duration not in ("NA", "") else None, "is_short": False})
    if not videos and code != 0:
        raise RuntimeError(f"yt-dlp listing failed: {err.strip()[-200:]}")
    return videos


def fetch_info(video_id, work_dir):
    """`yt-dlp -J` for one video -> (info dict, path of the saved JSON). The JSON is reused for the captions /
    audio download (--load-info-json), so YouTube is asked for the video page only once."""
    code, out, err = ytdlp(["-J", "--skip-download", "--no-playlist", f"https://www.youtube.com/watch?v={video_id}"],
                           timeout=180)
    if code != 0 or not out.strip():
        raise RuntimeError(f"yt-dlp -J failed: {err.strip()[-200:]}")
    path = Path(work_dir) / f"{video_id}.info.json"
    path.write_text(out, encoding="utf-8")
    return json.loads(out), path


def reuse_info(video, work_dir):
    """The metadata already fetched for this video (--only-video), written where the download step expects it."""
    path = Path(work_dir) / f"{video['id']}.info.json"
    path.write_text(video["info_json"], encoding="utf-8")
    return json.loads(video["info_json"]), path


LONG_ONE_SPEAKER = re.compile(r"(?<![a-z0-9])(full interview|keynote|fireside chat|testimony|speech|remarks)"
                              r"(?![a-z0-9])")


def video_problem(info, title):
    """A reason the video cannot be used (yet): ('skip' | 'fail', reason), or None when it is fine."""
    live = info.get("live_status")
    if live in ("is_live", "is_upcoming", "post_live"):
        return "fail", f"live status '{live}': captions come after the stream is processed"
    duration = info.get("duration") or 0
    if duration and duration < 60:
        return "skip", "a YouTube Short / clip under 60 s: who is speaking cannot be checked"
    # A long video is a whole show (anchors and several guests, no speaker names in the captions) unless the title
    # says it is one person's full interview / keynote, and the description does not list several guests.
    if duration > LONG_SHOW_SECONDS and (not LONG_ONE_SPEAKER.search(norm(title)) or
                                         re.search(r"\bguests\b", norm(description_summary(info.get("description"))))):
        return "skip", f"a {duration // 60:.0f}-minute show episode (many speakers), not one interview"
    return None


def caption_plan(info):
    """Which transcript to use: ('youtube manual captions', 'manual', [langs]) | ('youtube auto-captions', 'auto',
    [lang]) | ('faster-whisper (machine)', 'whisper', []) | (None, reason, []) when there is no usable English text."""
    manual = [k for k in (info.get("subtitles") or {}) if re.match(r"en($|[-_])", k)]
    if manual:
        return "youtube manual captions", "manual", manual
    auto = info.get("automatic_captions") or {}
    originals = [k for k in auto if k.endswith("-orig")]
    language = (info.get("language") or "").lower()
    if "en-orig" in auto:
        return "youtube auto-captions", "auto", ["en-orig"]
    # Without "en-orig", an "en" track is YouTube's machine TRANSLATION of another language unless nothing says so.
    if "en" in auto and not originals and (not language or language.startswith("en")):
        return "youtube auto-captions", "auto", ["en"]
    if language and not language.startswith("en"):
        return None, f"no English captions (the audio language is '{language}')", []
    if (info.get("duration") or 0) < WHISPER_MAX_SECONDS:
        return "faster-whisper (machine)", "whisper", []
    return None, "no captions yet and too long for local transcription", []


def download_captions(info_path, kind, langs, work_dir):
    """Download the chosen caption tracks as WebVTT; return the cleaned [(seconds, line)] of the fullest track."""
    flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
    code, out, err = ytdlp(["--load-info-json", str(info_path), "--skip-download", flag,
                            "--sub-langs", ",".join(re.escape(lang) for lang in langs), "--sub-format", "vtt",
                            "-o", str(Path(work_dir) / "captions.%(ext)s")])
    tracks = [vtt_lines(p.read_text(encoding="utf-8", errors="replace"))
              for p in Path(work_dir).glob("captions.*.vtt")]
    tracks = [t for t in tracks if t]
    if not tracks:
        raise RuntimeError(f"no caption file was written: {err.strip()[-200:]}")
    # Broadcast captions often come twice (CC1 and DTVCC1): keep the track with the most words.
    return max(tracks, key=lambda t: sum(len(line.split()) for _, line in t))


def transcribe_audio(info_path, work_dir):
    """Download the audio (lowest bitrate is plenty for speech) and transcribe it with faster-whisper."""
    code, out, err = ytdlp(["--load-info-json", str(info_path), "-f", "bestaudio[abr<70]/bestaudio",
                            "-o", str(Path(work_dir) / "audio.%(ext)s"), "--no-part"], timeout=300)
    audio = next((p for p in Path(work_dir).glob("audio.*")), None)
    if audio is None:
        raise RuntimeError(f"audio download failed: {err.strip()[-200:]}")
    # GOTCHA (same as tw.py): this repo's av.py (Alpha Vantage) shadows the PyAV package that faster-whisper imports
    # as `av`. Drop the repo root from sys.path and forget any half-imported `av` before importing faster_whisper.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
    own_av = sys.modules.get("av")
    if own_av is not None and Path(getattr(own_av, "__file__", "") or "").resolve().parent == ROOT:
        sys.modules.pop("av", None)                    # only the repo's av.py, never the real PyAV once loaded
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    # No VAD and no conditioning on earlier text: tw.py measured that VAD drops speech and that conditioning loops.
    segments, _info = model.transcribe(str(audio), language="en", vad_filter=False,
                                       condition_on_previous_text=False)
    return [(s.start, s.text.strip()) for s in segments if s.text.strip()]


# =====================================================================================================================
# 5. Captions -> timestamped plain text
# =====================================================================================================================

CUE_TIME = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})\.(\d{3})\s+-->")


def vtt_lines(vtt):
    """WebVTT -> [(start seconds, line)]: tags removed, entities decoded, rolling duplicates dropped.

    YouTube auto-captions and broadcast roll-up captions repeat each line in the next cue ("A / B", then "B",
    then "B / C") and sometimes grow a line word by word ("CUSTOMERS WI" -> "CUSTOMERS WILL"). We keep each line once."""
    cues = []
    for block in re.split(r"\n\s*\n", vtt.replace("\r", "")):
        rows = block.strip().split("\n")
        for i, row in enumerate(rows):
            m = CUE_TIME.match(row.strip())
            if m:
                start = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000
                for raw in rows[i + 1:]:
                    line = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", raw))).strip()
                    if line:
                        cues.append((start, line))
                break
    kept = []
    for start, line in cues:
        recent = [text for _, text in kept[-2:]]
        if line in recent:
            continue                                      # the rolling repeat of a line already kept
        if kept and line.startswith(kept[-1][1]):
            kept[-1] = (kept[-1][0], line)                # the same line, grown by a few letters / words
            continue
        if kept and kept[-1][1].startswith(line):
            continue                                      # a shorter echo of the line just kept
        kept.append((start, line))
    return kept


def stamp(seconds):
    return f"[{int(seconds // 60):02d}:{int(seconds % 60):02d}]"


# Fox Business captions name the anchor in capitals inside a line ("... WE'RE EXCITED. LIZ: HOW BIG OF A START ...")
# instead of starting a new ">>" line. Such a tag also starts a new paragraph, so the anchor's question and the
# executive's answer never share one [mm:ss] line (enrich skill section 11c).
SPEAKER_TAG = re.compile(r"(?<!\S)([A-Z][A-Z.'-]{1,20}):\s")


def split_speaker_tags(lines):
    """[(seconds, line)] -> the same, with a line cut in two before every upper-case speaker tag inside it.
    (seconds, "WE'RE EXCITED. LIZ: HOW BIG") -> (seconds, "WE'RE EXCITED."), (seconds, "LIZ: HOW BIG")"""
    out = []
    for start, line in lines:
        cuts = [m.start(1) for m in SPEAKER_TAG.finditer(line) if m.start(1) > 0]
        bounds = [0] + cuts + [len(line)]
        out += [(start, line[a:b].strip()) for a, b in zip(bounds, bounds[1:]) if line[a:b].strip()]
    return out


def paragraphs(lines):
    """[(seconds, line)] -> '[mm:ss] text' paragraphs: a new one about every 25 s, at every '>>' speaker change and
    at every upper-case speaker tag ('LIZ: ...')."""
    out, current, current_start = [], [], 0.0
    for start, line in split_speaker_tags(lines):
        new_speaker = line.startswith(">>") or SPEAKER_TAG.match(line) is not None
        if current and (start - current_start >= PARAGRAPH_SECONDS or new_speaker):
            out.append(f"{stamp(current_start)} {' '.join(current)}")
            current = []
        if not current:
            current_start = start
        current.append(line)
    if current:
        out.append(f"{stamp(current_start)} {' '.join(current)}")
    return out


# =====================================================================================================================
# 6. Saving one transcript
# =====================================================================================================================

def outlet_name(channel_name):
    """The outlet in the source label: 'CNBC Television' -> 'CNBC', 'Bloomberg Television' -> 'Bloomberg',
    'CNBC International TV' -> 'CNBC International' (enrich skill section 5)."""
    return re.sub(r"\s+(television|tv)$", "", channel_name.strip(), flags=re.I)


def source_label(node, outlet, published, video_id, out_dir):
    """'[Company] [Outlet] interview (MM-DD-YYYY)'; a second video of the same company, outlet and day adds its
    video id before the date, so every label still points at exactly one file (enrich skill section 5)."""
    day = datetime.strptime(published, "%Y-%m-%d").strftime("%m-%d-%Y")
    label = f"{node} {outlet} interview ({day})"
    for path in Path(out_dir).glob("*.txt"):
        if path.stem.endswith(f"_{video_id}"):
            continue                                       # this video's own earlier file
        head = path.read_text(encoding="utf-8", errors="replace")[:400]
        if f"# source label: {label}\n" in head:
            return f"{node} {outlet} interview {video_id} ({day})"
    return label


def write_transcript(out_dir, node, speaker, channel_name, published, video_id, title, transcript_kind, lines):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    label = source_label(node, outlet_name(channel_name), published, video_id, out_dir)
    path = out_dir / f"{slug(node)}_{published}_{video_id}.txt"
    head = [
        f"# source label: {label}",
        f"# SOURCE: https://www.youtube.com/watch?v={video_id}",
        f"# OUTLET: {channel_name}",
        f"# SPEAKER: {speaker['name']}, {speaker['title']}, {node}",
        f"# PUBLISHED: {published}",
        f"# TRANSCRIPT: {transcript_kind}",
        f"# NOTE: {NOTE}",
        f"# TITLE: {title}",
        "", "---", "",
    ]
    path.write_text("\n".join(head + paragraphs(lines)) + "\n", encoding="utf-8")
    return path, label


# =====================================================================================================================
# 7. One video, start to finish
# =====================================================================================================================

def process_video(video, channel, roster, executives, dry_run, out_dir, deadline):
    """Decide one listed video and, when kept, save its transcript. Returns the state record (a dict).
    A skip that no roster or rule change can undo (a rumor, a report, a Short, a long show, no English captions)
    carries "hard": True; every other skip is decided again when the roster or DECIDE_VERSION changes."""
    record = {"title": video["title"], "channel": channel["name"], "published": video["published"]}
    if video.get("is_short"):
        return {**record, "decision": "skip", "hard": True,
                "reason": "a YouTube Short: who is speaking cannot be checked"}
    work_dir = Path(tempfile.mkdtemp(prefix="media_pull_"))     # outside the repo (OneDrive), deleted at the end
    try:
        info = info_path = None
        if video.get("info_json"):                     # --only-video: main() already fetched the metadata
            info, info_path = reuse_info(video, work_dir)
        description = video.get("description")
        if description is None:                        # listed from the /videos tab: no description yet
            reason = hard_exclusion(norm(video["title"]), "title")
            if reason:
                return {**record, "decision": "skip", "hard": True, "reason": reason}
            if not title_could_pass(video["title"], roster):
                return {**record, "decision": "skip", "reason": "the title names no rostered executive or company"}
            info, info_path = fetch_info(video["id"], work_dir)
            description = info.get("description") or ""

        keep, node, name, reason = decide(video["title"], description, roster)
        if not keep:
            hard = hard_reason(video["title"], description) is not None
            return {**record, "decision": "skip", "reason": reason, **({"hard": True} if hard else {})}
        speaker = next(p for p in executives if p["node"] == node and p["name"] == name)
        record.update({"company": node, "speaker": name})

        if info is None:
            info, info_path = fetch_info(video["id"], work_dir)
        if info.get("upload_date"):
            d = info["upload_date"]
            record["published"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        problem = video_problem(info, video["title"])
        if problem:
            return {**record, "decision": problem[0], "reason": f"{reason}; but {problem[1]}",
                    **({"hard": True} if problem[0] == "skip" else {})}
        transcript_kind, kind, langs = caption_plan(info)
        if transcript_kind is None:
            decision = "skip" if "English" in kind else "fail"
            return {**record, "decision": decision, "reason": f"{reason}; but {kind}",
                    **({"hard": True} if decision == "skip" else {})}
        if dry_run:
            return {**record, "decision": "keep", "reason": f"{reason}; transcript would be: {transcript_kind}"}

        if kind == "whisper":
            needed = (info.get("duration") or 0) * 0.8         # small.en on this CPU: ~0.75x the video length
            if deadline and time.time() + needed > deadline:
                return {**record, "decision": "fail", "postponed": True,
                        "reason": f"{reason}; local transcription postponed (it would pass this run's time budget)"}
            lines = transcribe_audio(info_path, work_dir)
        else:
            lines = download_captions(info_path, kind, langs, work_dir)
        if not lines:
            raise RuntimeError("the transcript came out empty")
        path, label = write_transcript(out_dir, node, speaker, channel["name"], record["published"], video["id"],
                                       video["title"], transcript_kind, lines)
        return {**record, "decision": "saved", "reason": reason, "label": label, "transcript": transcript_kind,
                "file": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# =====================================================================================================================
# 8. The run
# =====================================================================================================================

def channel_is_genuine(channel, feed_title):
    """Rule 1 guard: the feed behind a channel id must still be the outlet that was checked when media/channels.json
    was made (its "feed_title"; without one, the channel's name). Any other channel is never read."""
    a, b = norm(channel.get("feed_title") or channel["name"]), norm(feed_title)
    return bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def list_window(channel, days, cutoff):
    """Every video of one channel published on or after `cutoff` (ISO date string). Returns (videos, ok)."""
    videos, ok = {}, False
    try:
        feed_title, rss = read_rss(channel)
        if not channel_is_genuine(channel, feed_title):
            print(f"  ! {channel['name']}: the feed belongs to '{feed_title}', not this outlet -- channel skipped")
            return [], False
        ok = True
        for v in rss:
            videos[v["id"]] = v
    except Exception as exc:
        print(f"  ! {channel['name']}: RSS failed: {exc}")
        rss = []
    oldest = min((v["published"] for v in rss), default=None)
    if days > 7 or oldest is None or oldest > cutoff:   # the 15 feed entries do not reach back to the window start
        try:
            for v in read_videos_tab(channel, days):
                videos.setdefault(v["id"], v)            # the RSS entry (with its description) wins
            ok = True
        except Exception as exc:
            print(f"  ! {channel['name']}: /videos listing failed: {exc}")
    window = [v for v in videos.values() if v["published"] >= cutoff and v["id"]]
    return sorted(window, key=lambda v: v["published"], reverse=True), ok


def decision_stamp(roster_updated):
    """The stamp a soft skip carries: the roster's "updated" date and DECIDE_VERSION ('2026-10-17|2026-10-17.2')."""
    return f"{roster_updated or 'unknown'}|{DECIDE_VERSION}"


def already_decided(record, stamp, root=ROOT):
    """Does a video already in media/sync_state.json need no new look?
    - "saved": only while its transcript file is on disk (a checkout without the file fetches it again);
    - "skip": a hard skip always; any other skip only while its stamp is the current one (roster and rules
      unchanged since), so a video skipped for a roster gap or an older rule is decided again;
    - "fail": never (it is retried, see remember())."""
    record = record or {}
    if record.get("decision") == "saved":
        return bool(record.get("file")) and (Path(root) / record["file"]).exists()
    if record.get("decision") == "skip":
        return bool(record.get("hard")) or record.get("stamp") == stamp
    return False


def remember(state, video_id, result, today, stamp=None):
    """Write one decision into the state, counting the attempts of a failing video. A soft skip gets `stamp`."""
    previous = state["seen"].get(video_id) or {}
    result = {**result, "decided": today}
    if result["decision"] == "fail":
        attempts = previous.get("attempts", 0) + (0 if result.pop("postponed", False) else 1)
        result["attempts"] = attempts
        if attempts >= MAX_ATTEMPTS:
            result["decision"] = "skip"
            result["hard"] = True
            result["reason"] = f"gave up after {attempts} attempts: {result['reason']}"
    if result["decision"] == "skip" and not result.get("hard") and stamp:
        result["stamp"] = stamp
    state["seen"][video_id] = result


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=2, help="look at videos published in the last N days (default 2)")
    ap.add_argument("--dry-run", action="store_true", help="print the decisions only; write no state, no transcript")
    ap.add_argument("--only-video", metavar="ID", help="decide (and save) this one YouTube video id")
    ap.add_argument("--force", action="store_true", help="run even though a run already happened today")
    ap.add_argument("--max-minutes", type=float, default=15,
                    help="stop starting new videos after this many minutes (default 15; 0 = no limit)")
    args = ap.parse_args(argv)

    started = time.time()
    deadline = started + args.max_minutes * 60 if args.max_minutes else None
    today = date.today().isoformat()
    channels = (load_json(MEDIA_DIR / "channels.json", {}) or {}).get("channels") or []
    roster_file = load_json(MEDIA_DIR / "executives.json", {}) or {}
    roster = roster_file.get("companies") or {}
    if not channels or not roster:
        print(f"media/channels.json or media/executives.json is missing or empty in {MEDIA_DIR} -- nothing to do")
        return 1
    stamp = decision_stamp(roster_file.get("updated"))
    state_path = MEDIA_DIR / "sync_state.json"
    state = load_json(state_path, None) or {}
    state["_about"] = ("media_pull.py: every news video looked at, with its decision (saved / skip / fail) and the "
                       "reason. 'saved' (while its file exists) and a hard skip ('hard': true) are final; any other "
                       "skip carries a 'stamp' (roster 'updated' | DECIDE_VERSION) and is decided again when that "
                       "changes; 'fail' is retried up to 3 runs.")
    state.setdefault("runs", [])
    state.setdefault("seen", {})
    executives = executives_for(roster)
    print(f"roster: {len(executives)} executives of {len(roster)} companies; channels: {len(channels)}")

    if not args.dry_run and not args.only_video and not args.force and \
            any(r.get("date") == today and not r.get("only_video") for r in state["runs"]):
        print(f"media_pull already ran today ({today}); one run a day -- use --force to run again")
        return 0

    # ---- which videos to look at
    work = []                                            # (video, channel)
    listed_ok = 0
    if args.only_video:
        tmp = Path(tempfile.mkdtemp(prefix="media_pull_"))
        try:
            info, info_path = fetch_info(args.only_video, tmp)
            info_json = info_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"! {args.only_video}: {exc}")
            return 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        channel = next((c for c in channels if c["channel_id"] == info.get("channel_id")), None)
        if channel is None:
            print(f"skip  {args.only_video}: channel '{info.get('channel')}' ({info.get('channel_id')}) is not on "
                  f"the news-outlet allowlist (media/channels.json)")
            return 0
        d = info.get("upload_date") or "19700101"
        work.append(({"id": args.only_video, "title": info.get("title") or "", "description":
                      info.get("description") or "", "published": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                      "is_short": False, "info_json": info_json}, channel))
        listed_ok = 1
    else:
        cutoff = (date.today() - timedelta(days=args.days)).isoformat()
        for channel in channels:
            videos, ok = list_window(channel, args.days, cutoff)
            listed_ok += ok
            new = [v for v in videos if not already_decided(state["seen"].get(v["id"]), stamp)]
            print(f"  {channel['name']:24s} {len(videos):4d} videos since {cutoff}, {len(new):4d} not decided yet")
            work += [(v, channel) for v in new]
        if not listed_ok:
            print("no channel could be listed -- nothing fetched")
            return 1

    # ---- decide each one (and save its transcript)
    counts = {"saved": 0, "keep": 0, "skip": 0, "fail": 0}
    kept_lines = []
    left = 0
    for i, (video, channel) in enumerate(work):
        if deadline and time.time() > deadline:
            left = len(work) - i
            print(f"time budget of {args.max_minutes:g} min reached: {left} video(s) left for the next run")
            break
        try:
            result = process_video(video, channel, roster, executives, args.dry_run, OUT_DIR, deadline)
        except Exception as exc:                          # one bad video never stops the run
            result = {"title": video["title"], "channel": channel["name"], "published": video["published"],
                      "decision": "fail", "reason": f"error: {str(exc)[:200]}"}
        counts[result["decision"]] = counts.get(result["decision"], 0) + 1
        line = (f"{result['decision']:5s} {channel['name'][:22]:22s} {result['published']} {video['id']:11s} "
                f"{video['title'][:90]}\n      -> {result['reason']}")
        print(line, flush=True)
        if result["decision"] in ("saved", "keep"):
            kept_lines.append(line + (f"\n      -> {result['file']}" if result.get("file") else ""))
        if not args.dry_run:
            remember(state, video["id"], result, today, stamp)
            save_json(state_path, state)                  # after every video: a killed run keeps what it did

    # ---- summary
    if not args.dry_run:
        state["runs"].append({"date": today, "when": datetime.now().isoformat(timespec="seconds"),
                              "days": args.days, "only_video": args.only_video, "looked_at": len(work) - left,
                              **counts, "minutes": round((time.time() - started) / 60, 1)})
        state["runs"] = state["runs"][-200:]
        save_json(state_path, state)
    print("\n" + ("DRY RUN (nothing saved): " if args.dry_run else "") +
          f"{len(work) - left} looked at -- " + ", ".join(f"{k} {v}" for k, v in counts.items() if v) +
          f" -- {(time.time() - started) / 60:.1f} min")
    if kept_lines:
        print("\nkept:\n" + "\n".join(kept_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
