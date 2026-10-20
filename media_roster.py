"""
media_roster.py -- the executive roster and the news-channel allowlist for the media-interview puller.

WHY (user, 2026-10-17): a news video may feed the map only when an official of the company speaks on camera
("찌라시면 시그널이면 안 돼. 무조건 뉴스여야 함. 회사 관계자가 직접 얘기한 거여야 해"). media_pull.py therefore
needs two lists it can trust:

  media/executives.json   who counts as an official of each graph company (name, title, aliases, source)
  media/channels.json     which YouTube channels count as news outlets (5 official channels, ids checked)

Nothing here calls a model. The roster is mined from documents already saved under transcripts/ -- the
speaker lines of earnings calls and conference talks, the executive-officer table of 10-Ks, and the quote
attributions of company press releases -- so every name it lists was stated, with a title, in a source the
project already trusts. Analysts, moderators, hosts and interpreters are dropped. When a person appears in
several documents, the title from the most recent one is kept.

Run (from the repo root):
    python -X utf8 media_roster.py                  # rebuild media/executives.json and print the coverage
    python -X utf8 media_roster.py --show NVIDIA    # spot check: one company's people with every source
    python -X utf8 media_roster.py channels         # fetch the 5 RSS feeds and write media/channels.json

Which companies: the 200 graph nodes with the most edges in graph/merged_graph.json, plus every node in the
cloud_infra (hyperscalers, neoclouds) and ai_models (AI labs) layers. A company with no verified official
yet is listed with an empty list, so the gap is visible (media_pull.py then accepts no video for it). Every
other graph node is listed too when the documents name at least one titled official for it (no model calls).

Who counts (rule 2): only titles naming CEO, CFO, COO, CTO or another chief officer, president, founder,
chair, the head or GM of a named division / business unit / group, or investor relations; a person found at
two companies stays only at the company of the newer document; a CEO or CFO succeeded by a newer one is left
out. HAND_ADD adds the officials the mining cannot find, each with the company document that states the title.
"""

import argparse
import glob
import html
import json
import os
import re
import unicodedata
import sys
from collections import Counter, defaultdict
from datetime import date

import requests

# verify_graph.py already knows how to read the "# source label:" header and how a filename names a company;
# reuse those helpers instead of writing a second copy.
import verify_graph as vg
from agent.corpus import normalize_company

ROOT = os.path.dirname(os.path.abspath(__file__))
GRAPH_FILE = os.path.join(ROOT, "graph", "merged_graph.json")
TRANSCRIPTS = os.path.join(ROOT, "transcripts")
MEDIA_DIR = os.path.join(ROOT, "media")
EXECUTIVES_FILE = os.path.join(MEDIA_DIR, "executives.json")
CHANNELS_FILE = os.path.join(MEDIA_DIR, "channels.json")

TOP_N = 200                                    # the most-connected graph nodes
ALWAYS_LAYERS = {"cloud_infra", "ai_models"}   # hyperscalers / neoclouds and AI labs: always covered

# transcripts/media/ holds what media_pull.py itself saves (news interviews). Mining names from it would let a
# news video vouch for its own speaker, so it is never read here.
SKIP_FOLDERS = {"media"}


# ---------------------------------------------------------------------------------------------------------
# 1. The news-channel allowlist (rule 1: only news outlets' own official channels)
# ---------------------------------------------------------------------------------------------------------

# Each id was checked on 2026-10-17: its RSS feed answered 200 and named the channel, and the channel page
# resolved from the outlet's own handle. feed_title is what YouTube calls the channel today.
CHANNELS = [
    {"name": "CNBC Television", "channel_id": "UCrp_UI8XtuYfpiqluWLD7Lw",
     "feed_title": "CNBC Television", "handle": "@CNBCtelevision"},
    # "CNBC International TV" is the old name: youtube.com/c/CNBCInternationalTV now opens this channel,
    # renamed "CNBC International Live" (Squawk Box Europe / Asia, Street Signs). It is NOT @CNBCi
    # (UCo7a6riBFJ3tkeHjvkXPn1g), CNBC International's feature / documentary channel.
    {"name": "CNBC International TV", "channel_id": "UCF8HUTbUwPKh2Q-KpGOCVGw",
     "feed_title": "CNBC International Live", "handle": "@CNBCInternationalLive"},
    # Bloomberg Television's handle is @markets (@BloombergTelevision is an unrelated personal channel).
    {"name": "Bloomberg Television", "channel_id": "UCIALMKvObZNtJ6AmdCLP7Lg",
     "feed_title": "Bloomberg Television", "handle": "@markets"},
    {"name": "Yahoo Finance", "channel_id": "UCEAZeUIeJs0IjQiqTCdVSIg",
     "feed_title": "Yahoo Finance", "handle": "@YahooFinance"},
    {"name": "Fox Business", "channel_id": "UCCXoCcu9Rp7NPbTzIvogpZg",
     "feed_title": "Fox Business", "handle": "@FoxBusiness"},
]

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def check_channels():
    """Fetch every channel's RSS feed. A channel passes when the feed answers 200, its <title> is the expected
    channel name and the feed points back at the same channel id. Writes media/channels.json only when all
    five pass, so a YouTube hiccup can never shrink the allowlist."""
    checked, failures = [], []
    for ch in CHANNELS:
        url = RSS_URL.format(ch["channel_id"])
        try:
            r = requests.get(url, timeout=30)
        except requests.RequestException as e:
            failures.append(f"{ch['name']}: request failed ({e.__class__.__name__})")
            continue
        title = re.search(r"<title>(.*?)</title>", r.text)        # the first <title> is the feed's own
        title = html.unescape(title.group(1)) if title else None
        points_back = f"youtube.com/channel/{ch['channel_id']}" in r.text
        entries = r.text.count("<entry>")
        print(f"  {ch['name']:<22} {ch['channel_id']}  HTTP {r.status_code}  title={title!r}  "
              f"entries={entries}  id-in-feed={points_back}")
        if r.status_code != 200 or title != ch["feed_title"] or not points_back:
            failures.append(f"{ch['name']}: HTTP {r.status_code}, title {title!r}, id in feed {points_back}")
            continue
        checked.append({"name": ch["name"], "channel_id": ch["channel_id"], "rss": url,
                        "handle": ch["handle"], "feed_title": title})
    if failures:
        print("NOT written -- these channels failed:\n  " + "\n  ".join(failures))
        return 1
    out = {
        "_about": "News outlets whose YouTube videos media_pull.py may read (user rule 2026-10-17: only news "
                  "outlets' own official channels). Each channel_id was checked by fetching its RSS feed "
                  "(HTTP 200, the feed title below, the feed pointing back at the same id). Rebuilt by "
                  "`python -X utf8 media_roster.py channels`; the list itself lives in media_roster.py CHANNELS.",
        "verified": date.today().isoformat(),
        "channels": checked,
    }
    write_json(CHANNELS_FILE, out)
    print(f"wrote {os.path.relpath(CHANNELS_FILE, ROOT)} ({len(checked)} channels)")
    return 0


# ---------------------------------------------------------------------------------------------------------
# 2. Which companies, and how a company name in a document maps to a graph node
# ---------------------------------------------------------------------------------------------------------

def load_graph():
    with open(GRAPH_FILE, encoding="utf-8") as f:
        return json.load(f)


def selected_nodes(graph):
    """The top TOP_N nodes by edge count, then every hyperscaler / AI-lab node not already in. Returns the
    node ids in that order (it is also the order of media/executives.json)."""
    edges = Counter()
    for e in graph["edges"]:
        edges[e["source"]] += 1
        edges[e["target"]] += 1
    ids = [n["id"] for n in graph["nodes"]]
    ranked = sorted(ids, key=lambda i: (-edges[i], i))
    chosen = ranked[:TOP_N]
    for n in sorted(graph["nodes"], key=lambda n: (-edges[n["id"]], n["id"])):
        if ALWAYS_LAYERS & set(n.get("layers", [])) and n["id"] not in chosen:
            chosen.append(n["id"])
    return chosen, edges


# Words a company name may end with that do not change which company it is ("Micron Technology" = Micron).
CORP_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "ag",
                 "se", "sa", "nv", "bv", "kk", "llc", "lp", "holdings", "holding", "group", "technology",
                 "technologies", "networks", "electronics", "computer", "platforms", "industries", "industry",
                 "com", "the"}

# Spellings in speaker lines and press releases that differ from the node id (checked by hand).
# The SpaceX node carries xAI's products (Grok training, Colossus) in the graph, so xAI officials belong to it.
ORG_ALIASES = {
    "TSMC": ["Taiwan Semiconductor Manufacturing", "Taiwan Semiconductor Manufacturing Company",
             "Taiwan Semiconductor"],
    "AMD": ["Advanced Micro Devices"],
    "Google": ["Alphabet", "Google Cloud", "Google DeepMind", "DeepMind"],
    "Amazon": ["Amazon Web Services", "AWS", "Amazon.com"],
    "Oracle": ["Oracle Cloud Infrastructure", "OCI"],
    "Microsoft": ["Microsoft Azure"],
    "Foxconn": ["Hon Hai", "Hon Hai Precision", "Hon Hai Technology Group"],
    "SMIC": ["Semiconductor Manufacturing International", "Semiconductor Manufacturing International Corporation"],
    "Samsung": ["Samsung Electronics"],
    "SpaceX": ["xAI"],
    # from investing.py ALIASES
    "Quanta": ["Quanta Computer"],
    "ASM International": ["ASMI"],
    "Nan Ya PCB": ["NanYa PCB", "Nan Ya Printed Circuit"],
    "Panasonic Holdings": ["Panasonic"],
    "Disco Corporation": ["DISCO Corp"],
    "Mitsubishi Heavy Industries": ["MHI"],
    "Tokyo Ohka Kogyo": ["TOK"],
    "SoftBank": ["SoftBank Group"],
}
# Same name, a different company (from investing.py EXCLUDE): an org text containing one of these is not ours.
ORG_EXCLUDE = {
    "Quanta": ["Quanta Services"],
    "SoftBank": ["SoftBank Corp"],
    "Delta Electronics": ["Thailand"],
    "Disco Corporation": ["CS Disco"],
    "ABB": ["ABB India", "ABB Power"],
    "Schneider Electric": ["Schneider Electric Infrastructure"],
    "Siemens": ["Healthineers", "Siemens Ltd"],
    "Tencent": ["Tencent Music"],
}


def name_variants(name):
    """'VAT Group AG' -> {'vatgroupag', 'vatgroup', 'vat'}: the name with corporate suffix words dropped from
    the end, one by one. Used on both sides, so 'Micron Technology' meets the node 'Micron'."""
    words = re.sub(r"[.,]", " ", name).split()
    out = set()
    while words:
        key = normalize_company(" ".join(words))
        if key:
            out.add(key)
        if words[-1].lower() in CORP_SUFFIXES:
            words = words[:-1]
        else:
            break
    return out


class OrgMatcher:
    """Maps a company name as a document writes it ('Micron Technology, Inc.', 'SK hynix', 'Hon Hai') to the
    graph node id, or None. Exact spellings win; a variant shared by two nodes is ambiguous -> None."""

    def __init__(self, node_ids):
        self.exact = {}                        # normalized full name / alias -> node id
        self.by_variant = defaultdict(set)     # normalized variant -> node ids
        for nid in node_ids:
            spellings = [nid] + ORG_ALIASES.get(nid, [])
            m = re.match(r"^(.+?)\s*\((.+)\)$", nid)          # "GUC (Global Unichip)" -> both halves
            if m:
                spellings += [m.group(1), m.group(2)]
            for s in spellings:
                self.exact.setdefault(normalize_company(s), nid)
                for v in name_variants(s):
                    self.by_variant[v].add(nid)
        for nid in node_ids:                   # a node's own id always beats someone else's alias / half
            self.exact[normalize_company(nid)] = nid

    def match(self, org):
        if not org:
            return None
        org = html.unescape(org).strip(" ,.;:()")
        if not org or len(org) > 90:
            return None
        hit = self._match_one(org)
        if hit is None and "(" in org:                        # "Semiconductor Manufacturing ... (SMIC)"
            inner = org.split("(", 1)[1].split(")", 1)[0]        # the closing ")" may have been stripped
            hit = self._match_one(inner) or self._match_one(org.split("(")[0])
        if hit is None and "/" in org:                        # "Alexion/AstraZeneca"
            for part in org.split("/"):
                hit = hit or self._match_one(part)
        if hit and any(x.lower() in org.lower() for x in ORG_EXCLUDE.get(hit, [])):
            return None
        return hit

    def _match_one(self, org):
        org = org.strip(" ,.;:()")
        key = normalize_company(org)
        if not key:
            return None
        if key in self.exact:
            return self.exact[key]
        found = set()
        for v in name_variants(org):
            found |= self.by_variant.get(v, set())
        return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------------------------------------------------
# 3. People: what a name looks like, which titles count, who is never an official
# ---------------------------------------------------------------------------------------------------------

HONORIFICS = {"dr", "mr", "ms", "mrs", "prof", "sir", "dame"}
NAME_SUFFIXES = {"phd", "md", "jr", "sr", "ii", "iii", "iv", "cpa", "cfa", "mba"}
PARTICLES = {"de", "da", "del", "der", "van", "von", "di", "la", "le", "bin", "al", "du", "dos", "ten", "ter"}
# Words that are never part of a person's name (turn heads like "Unidentified Speaker", "Company Representative").
NOT_NAME_WORDS = {"unidentified", "speaker", "operator", "company", "representative", "analyst", "participant",
                  "executive", "management", "moderator", "interpreter", "unknown", "corporate", "investor",
                  "relations", "team", "host", "the", "and", "of", "inc", "ltd", "group", "presenter", "question",
                  "questions", "answer", "conference", "call", "attendee", "audience", "male", "female", "member",
                  "officer", "chief", "president", "director", "ceo", "cfo", "note", "source", "date", "quarter",
                  "label", "title", "event", "speakers", "outlook", "revenue", "guidance", "summary", "image",
                  "q", "a", "transcript", "presentation", "remarks", "highlights", "unnamed", "other",
                  "panel", "panelist", "staff", "spokesperson", "multiple", "various", "end"}

# A title counts when it names an executive role (rule 2: CEO, CFO, President, COO, CTO, founder, division
# head, IR head -- plus chairs and other chief officers).
EXEC_TITLE = re.compile(
    r"\b(?:CEO|CFO|COO|CTO|CBO|CRO|CMO|CPO|CSO|CIO|CCO|CAO|Co-?CEO|Chief\b[\w\s&,-]{0,40}?\bOfficer|"
    r"Chief Executive|President|Chair(?:man|woman|person)?|Co-?founder|Founder|EVP|SVP|"
    r"Executive Vice President|Senior Vice President|Corporate Vice President|Vice President|VP|"
    r"General Manager|GM|Head of|Managing Director|Treasurer|Investor Relations|IR|"
    r"Director,? (?:of )?Investor|"
    # Japanese / Asian officer titles (執行役員, 代表取締役): "Senior Executive Officer", "Representative Director"
    r"Executive Officer|Representative Director|Corporate Officer|Executive Director)\b", re.I)
# Never an official in this pipeline (rule 3): analysts and other outside voices, and the people who run a call.
NON_EXEC = re.compile(
    r"\b(?:analysts?|moderator|operator|interpreter|host|co-?host|reporter|anchor|journalist|strategist|"
    r"economist|portfolio manager|equity research|research analyst|securities|investor/analyst|shareholder|"
    r"participant|unidentified|guest|panelist|professor|advisor|adviser|consultant|partner at)\b", re.I)
# Board seats are not management: "Board Director, Chair of the Audit Committee" is dropped, while
# "Board Director and CFO" stays because it also names a management role.
BOARD_ONLY = re.compile(r"\b(?:board director|board member|member of the board|director of the board|"
                        r"independent director|non-executive|supervisory board|committee)\b", re.I)
MANAGEMENT_ROLE = re.compile(
    r"\b(?:CEO|CFO|COO|CTO|C[A-Z]O|Chief\b[\w\s&,-]{0,40}?\bOfficer|Chief Executive|(?<!Vice )President|"
    r"Co-?founder|Founder|EVP|SVP|Vice President|VP|General Manager|Head of|Managing Director|"
    r"Investor Relations|Executive Officer)\b", re.I)
# Banks and brokers: a line naming one is an analyst's line (Dan Ives / Wedbush included).
BROKERS = re.compile(
    r"\b(?:Morgan Stanley|Goldman|JPMorgan|J\.?P\.? ?Morgan|BofA|Bank of America|Merrill|Citi(?:group|bank)?|"
    r"UBS|Barclays|Jefferies|Bernstein|Evercore|Needham|KeyBanc|Mizuho|Wells Fargo|Deutsche Bank|Cowen|"
    r"Raymond James|Piper Sandler|Stifel|Oppenheimer|Wolfe|Rosenblatt|Cantor|Truist|BMO|RBC|HSBC|Macquarie|"
    r"Nomura|Daiwa|CLSA|KGI|Melius|Loop Capital|Baird|William Blair|Northland|Craig-Hallum|B\. ?Riley|"
    r"Benchmark|Susquehanna|Arete|Redburn|Berenberg|BNP|Exane|Kepler|Societe Generale|Credit Suisse|"
    r"Morningstar|New Street|MoffettNathanson|Guggenheim|Wedbush|Seaport|Lake Street|Roth|Ladenburg|"
    r"Canaccord|Bryan Garnier|Mirae|Daishin|Kiwoom|Hana Financial|Hana Securities|Shinhan|Yuanta|Fubon|SMBC|"
    r"Bank|Capital Markets|Investment|Asset Management)\b")
# The person has left: such a line never makes anyone an official, and when it is a person's newest line the
# person is dropped.
FORMER = re.compile(r"\b(?:former|formerly|retired|ex-|the late)\b", re.I)


def clean_name(raw):
    """Return the name as written minus honorifics / degree suffixes ('Dr. Lisa Su' -> 'Lisa Su'), or None
    when it does not look like a person's full name (two to five capitalised words)."""
    raw = html.unescape(raw or "").strip().strip(",;:.").strip()
    raw = re.sub(r"\s+", " ", raw)
    tokens = raw.split(" ")
    while tokens and tokens[0].lower().rstrip(".") in HONORIFICS:
        tokens = tokens[1:]
    while tokens and tokens[-1].lower().replace(".", "").rstrip(",") in NAME_SUFFIXES:
        tokens = tokens[:-1]
    tokens = [t.rstrip(",") for t in tokens]
    if not 2 <= len(tokens) <= 5:
        return None
    for t in tokens:
        bare = t.lower().replace(".", "").replace("’", "'")
        if bare in NOT_NAME_WORDS:
            return None
        if bare in PARTICLES:
            continue
        if not re.fullmatch(r"[^\W\d_]+(?:[-'’.][^\W\d_]+)*\.?", t):     # letters, inner - ' . only
            return None
        if not t[0].isupper():
            return None
        if len(t) >= 4 and t.isupper() and "." not in t:                  # "SOURCE", "CALL" -- not a name
            return None
    if len(tokens[-1].strip(".")) < 2:                                    # the family name is not an initial
        return None
    return " ".join(tokens)


# Short and long forms of one first name ("Dave Zinsner" = "David Zinsner"); both map to the long form.
NICKNAMES = {
    "andy": "andrew", "dave": "david", "tim": "timothy", "mike": "michael", "bill": "william",
    "will": "william", "bob": "robert", "rob": "robert", "jim": "james", "tom": "thomas", "matt": "matthew",
    "chris": "christopher", "dan": "daniel", "joe": "joseph", "steve": "steven", "ken": "kenneth",
    "rick": "richard", "rich": "richard", "dick": "richard", "tony": "anthony", "nick": "nicholas",
    "pat": "patrick", "sam": "samuel", "ben": "benjamin", "greg": "gregory", "jeff": "jeffrey",
    "ed": "edward", "ron": "ronald", "don": "donald", "doug": "douglas", "charlie": "charles",
    "chuck": "charles", "fred": "frederick", "alex": "alexander", "jon": "jonathan", "josh": "joshua",
    "liz": "elizabeth", "beth": "elizabeth", "sue": "susan", "jen": "jennifer", "larry": "lawrence",
    "phil": "philip", "ray": "raymond", "stan": "stanley", "zach": "zachary", "zachariah": "zachary",
    "gio": "giordano", "kate": "katherine", "katie": "katherine", "drew": "andrew",
}


def _plain(word):
    """'Wirén' -> 'wiren', 'O’Connor' -> 'oconnor': lower case, accents and punctuation removed."""
    word = unicodedata.normalize("NFKD", word)
    word = "".join(c for c in word if not unicodedata.combining(c))
    return re.sub(r"[.\-'’]", "", word).lower()


def name_words(name):
    """The words of a name that identify the person: no particles, no single-letter middle initials."""
    words = [_plain(w) for w in name.split()]
    words = [w for w in words if w and w not in PARTICLES]
    longer = [w for w in words if len(w) > 1]
    if len(longer) >= 2:
        words = longer
    if words:
        words[0] = NICKNAMES.get(words[0], words[0])
    return words


def person_key(name):
    """One key per person across spellings: first + last word, plain lower case, nicknames expanded, the
    two words in alphabetical order (Chinese names come in both orders: 'Zou Tao' / 'Tao Zou').
    'Hock E. Tan' / 'Hock Tan' -> 'hock tan'; 'C.C. Wei' / 'CC Wei' -> 'cc wei'; 'Dave Zinsner' -> 'david zinsner'."""
    words = name_words(name)
    return " ".join(sorted([words[0], words[-1]])) if len(words) >= 2 else None


def clean_title(raw):
    t = html.unescape(raw or "")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:(?:Ph\.? ?D|M\.? ?D)\.?,\s*)+", "", t)               # "PhD, founder and CEO" -> "founder ..."
    t = re.sub(r"^(?:and\s+)?(?:our|the|its|their|his|her)\s+", "", t, flags=re.I)
    t = re.sub(r"(?:,|\band\b|\b(?:Mr|Ms|Mrs|Dr)\b\.?|\s)+$", "", t).strip(" ,;:.-–—")   # "..., Ms" (next person)
    t = re.sub(r"\s+(?:of|at) (?:the|our) company$", "", t, flags=re.I)      # "Senior Manager of IR of the company"
    return t


def title_ok(title):
    """An executive role, no outside-voice word, no bank or broker, not a board seat only, not too long."""
    if not title or len(title) > 120 or EXEC_TITLE.search(title) is None:
        return False
    if NON_EXEC.search(title) or BROKERS.search(title):
        return False
    if BOARD_ONLY.search(title) and not MANAGEMENT_ROLE.search(title):
        return False
    return True


# A title written in running text starts with one of these words ("..., Chair and CEO, ...").
TITLE_START = re.compile(
    r"^(?:Co-?founder|Founder|Chair(?:man|woman|person)?|President|Chief|CEO|CFO|COO|CTO|C[A-Z]O|Co-?CEO|"
    r"Co-?Chief|Executive|Senior|Corporate|Group|Global|Vice|EVP|SVP|VP|Head|Director|General|Managing|"
    r"Treasurer|Interim|Acting|Deputy|Principal|Investor|IR)\b", re.I)


# ---------------------------------------------------------------------------------------------------------
# 4. Reading one document
# ---------------------------------------------------------------------------------------------------------

LABEL_DATE = re.compile(r"\((\d\d)-(\d\d)-(\d{4})\)\s*$")
HEADER_DATE = re.compile(r"(?im)^\s*#?\s*(?:CALL DATE|DATE|Filed)\s*:\s*(\d\d)-(\d\d)-(\d{4})")
FILE_DATE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")


def doc_date(label, head, path):
    """The document's own date as YYYY-MM-DD: the label's (MM-DD-YYYY), else a CALL DATE / DATE header,
    else a date in the filename. '' when none is stated (sorts as the oldest)."""
    m = LABEL_DATE.search(label or "")
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    m = HEADER_DATE.search(head)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    m = FILE_DATE.search(os.path.basename(path))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def subject_node(label, path, node_ids):
    """Which company the document is about. The label prefix must equal the node name (enrich §5 rule 3),
    so the longest node id the label starts with wins; a file without a label is joined by its filename,
    the same way verify_graph.py does it."""
    if label:
        best = None
        for nid in node_ids:
            if label.startswith(nid + " ") and (best is None or len(nid) > len(best)):
                best = nid
        if best:
            return best
        return None                       # a label naming a company that is not a graph node
    stem = os.path.basename(path)[:-4]
    for pattern in (vg.STEM_QUARTER, vg.STEM_FY, vg.STEM_PRELIM):
        m = pattern.match(stem)
        if m:
            token = normalize_company(m.group("company"))
            break
    else:
        token = normalize_company(stem.split("_")[0])
    if not token:
        return None
    best, best_rank = None, 0
    for nid in node_ids:
        key = normalize_company(nid)
        if not (key[:3] == token[:3] or token in key or key in token):   # cheap pre-filter
            continue
        rank = vg.company_rank(nid, token)
        if rank > best_rank or (rank == best_rank and best and len(nid) > len(best)):
            best, best_rank = nid, rank
    return best if best_rank >= 1 else None


# Spellings that name a business unit, not the whole company: kept in the title ("CEO, AWS"), so the roster
# never says Matt Garman is Amazon's CEO.
# (Plain letters-and-digits keys here: normalize_company() would turn "Amazon Web Services" into "amazon".)
def _letters(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


BUSINESS_UNITS = {_letters(u) for u in
                  ["AWS", "Amazon Web Services", "Google Cloud", "Google DeepMind", "DeepMind",
                   "Oracle Cloud Infrastructure", "OCI", "Microsoft Azure", "xAI"]}


def with_unit(title, org_text):
    """'CEO' + 'AWS' -> 'CEO, AWS' when the company was named by one of its business units."""
    org_text = (org_text or "").strip(" ,.;:")
    if _letters(org_text) in BUSINESS_UNITS and org_text.lower() not in title.lower():
        return f"{title}, {org_text}"
    return title


def split_title_org(title, resolve):
    """A title may carry its company: 'founder and CEO of NVIDIA', 'NVIDIA's founder and CEO',
    'AMD chair and CEO', 'SVP, Windows and Devices, Microsoft'. `resolve` maps a company name to a node id.
    Returns (title without the company, node id) or (title, None) when it names no graph company."""
    t = title.strip()
    m = re.match(r"^(.{2,60}?)['’]s\s+(.+)$", t)                          # "NVIDIA's founder and CEO"
    if m and TITLE_START.match(m.group(2)):
        node = resolve(m.group(1))
        if node:
            return with_unit(clean_title(m.group(2)), m.group(1)), node
    words = t.split()
    for k in range(min(4, len(words) - 1), 0, -1):                       # "AMD chair and CEO"
        rest = " ".join(words[k:])
        if TITLE_START.match(rest):
            node = resolve(" ".join(words[:k]))
            if node:
                return with_unit(clean_title(rest), " ".join(words[:k])), node
    if "," in t:                                                          # "..., Microsoft"
        head, tail = t.rsplit(",", 1)
        node = resolve(tail)
        if node:
            return with_unit(clean_title(head), tail), node
    for m in re.finditer(r"\s(?:of|at|for|from|with)\s", t):              # "Head of Infrastructure at OpenAI"
        node = resolve(t[m.end():])
        if node:
            return with_unit(clean_title(t[:m.start()]), t[m.end():]), node
    return clean_title(t), None


class Observation:
    """One sighting of one person with one title in one document."""

    def __init__(self, node, name, title, date_, label, path, kind, departed=False):
        self.node, self.name, self.title = node, name, title
        self.date, self.label, self.path, self.kind = date_, label, path, kind
        self.departed = departed

    def source(self):
        where = self.path.replace(os.sep, "/")
        return f"{self.label} | {where}" if self.label else where


# Source kinds, best first: used only to break a tie between two sightings of the same date.
KIND_RANK = {"filing_table": 6, "call_turn": 5, "call_header": 4, "conference_header": 4,
             "press_quote": 3, "intro": 2, "note": 1}

# --- line formats with the company written on the line ---------------------------------------------------
# Investing.com calls and conference talks:   "Song Hyeon-jong, President of Corporate Center, SK hynix: ..."
TURN_NAME_TITLE_ORG = re.compile(r"^([A-Z][^,:\n]{2,50}), ([^:\n]{2,140}), ([^,:\n]{2,90}):\s", re.M)
# LSEG / Refinitiv calls:                     "Jeff Su - Taiwan Semiconductor Manufacturing Co Ltd - Director - IR"
TURN_DASHED = re.compile(r"^([A-Z][^-\n]{2,50}) - ([^\n]{2,90}?) - ([^\n]{2,140})$", re.M)
# Conference header written by investing.py:  "# speakers: Lisa Su, CEO, AMD; Tom Brown, Co-founder ..., Anthropic"
CONF_HEADER = re.compile(r"^# speakers:\s*(.+)$", re.M | re.I)
# Company press releases (quote attributions): "said Jensen Huang, founder and CEO of NVIDIA."
PRESS_SAID = re.compile(
    r"\b(?:said|says|added|noted|commented|stated|explained)\s+((?:(?:Dr|Mr|Ms|Mrs)\.\s+)?[A-Z][^\s,]*(?:\s+[^\s,]+){1,4}?)"
    r"\s?,\s+([^\"“”;\n]{3,170}?)(?=\.(?:\s|$)|[;\"“”\n]|,\s+(?:who|which|in|at the|during)\b|$)")
PRESS_BEFORE_SAID = re.compile(
    r"(?:^|[\"“”]\s*|\.\s+)((?:(?:Dr|Mr|Ms|Mrs)\.\s+)?[A-Z][^\s,]*(?:\s+[^\s,]+){1,4}?),\s+([^\"“”;\n]{3,170}?),"
    r"\s+(?:said|says|added|noted|commented|stated)\b", re.M)
# Asian companies' English releases: "Foxconn Rotating CEO Michael Chiang stated ..." (company, title, name).
PRESS_ORG_TITLE = re.compile(
    r"\b(CEO|CFO|COO|CTO|Chairman|Chairwoman|Chair|President|Chief Executive Officer|Chief Financial Officer)"
    r"\s+((?:Dr\.\s+)?[A-Z][\w'’\-]*\.?(?:\s+[A-Z][\w'’\-]*\.?){1,3})\s+(?:said|says|stated|noted|added|explained)\b")
# Words that may stand between the company and that title keyword ("Foxconn Rotating CEO", "NVIDIA founder and CEO").
TITLE_PREFIX_WORD = re.compile(r"(?i)^(?:and|&|co-?founder|founder|chief|executive|senior|vice|president|chairman|"
                               r"chair|group|global|rotating|interim|acting|deputy|managing|general|co-?ceo)$")

# --- line formats where the company is the document's subject --------------------------------------------
# Alpha Vantage calls:                         "Michael Intrator (CEO): ..."
TURN_PAREN_TITLE = re.compile(r"^([A-Z][^()\n:]{2,50}) \(([^()\n]{2,120})\):", re.M)
# Hand-saved calls:                            "Speakers: Jensen Huang (President & CEO), Colette Kress (EVP & CFO)"
SPEAKERS_HEADER = re.compile(r"^Speakers?:\s*(.+)$", re.M)
SPEAKERS_ITEM = re.compile(r"([A-Z][^(),;]{2,50}?)\s*\(([^)]{2,80})\)")
# Hand-saved summaries:                        "[Sundar Pichai — CEO]"
BRACKET = re.compile(r"^\[([A-Z][^\]—–]{2,50}?)\s+(?:—|–|-{1,2})\s+([^\]]{2,80})\]\s*$", re.M)
# Hand-saved NOTE lines:                       "prepared remarks (Sundar Pichai CEO, Anat Ashkenazi CFO; Jim Friedland IR)"
NOTE_REMARKS = re.compile(r"prepared remarks \(([^)]{5,300})\)", re.I)
NOTE_ITEM = re.compile(r"^(.+?)\s+((?:Co-)?(?:CEO|CFO|COO|CTO|CBO|CRO|CMO|CPO|CSO|CIO|IR|President|Chair|Chairman|"
                       r"EVP|SVP)(?:\s*(?:/|&|and)\s*(?:CEO|CFO|COO|CTO|President|Chair|Chairman))*)$")
# 10-K executive-officer table (edgar_pull.py keeps it as "Name | | Age | | Positions |").
TEN_K_TABLE = re.compile(r"^([A-Z][^|\n]{2,50}?) \| \| (\d{2}) \| \| ([^|\n]{2,})\|", re.M)
# A call's turn heads ("Wendell Huang: ...", "Michael Intrator (CEO): ..."): the people who spoke on it.
TURN_HEAD = re.compile(r"^([A-Z][^:\n()]{2,50}?)(?: \([^)\n]*\))?:\s", re.M)


def read_document(path, rel, node_ids, matcher):
    """Every (person, title, company) sighting in one file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    head = text[:3000]
    labels = vg.header_labels(head)
    label = labels[0] if labels else None
    when = doc_date(label, head, rel)
    subject = subject_node(label, rel, node_ids)
    subject_key = normalize_company(subject) if subject else ""
    found = []

    def resolve(org_text):
        """Company name -> node id. A short form of the document's own company means that company: in a
        Quanta Services release "CEO of Quanta" is Quanta Services, not the node "Quanta" (Quanta Computer)."""
        key = normalize_company(org_text or "")
        if subject and len(key) >= 4 and subject_key != key and subject_key.startswith(key):
            return subject
        return matcher.match(org_text)

    def add(raw_name, raw_title, node, kind):
        """Validate one sighting and keep it. `node` is the company the line itself names, or None for the
        document's subject company."""
        name = clean_name(raw_name)
        if not name:
            return
        title = clean_title(raw_title)
        if not title or NON_EXEC.search(title) or BROKERS.search(title or ""):
            return
        departed = FORMER.search(title) is not None
        if node is None:
            stripped, named = split_title_org(title, resolve)
            if named:                                # the title names a company: that one, not the subject
                title, node = stripped, named
            else:
                node = subject
        if node is None or not title_ok(FORMER.sub("", title).strip() if departed else title):
            return
        found.append(Observation(node, name, title, when, label, rel, kind, departed))

    # -- company on the line ------------------------------------------------------------------------------
    for m in CONF_HEADER.finditer(head):
        for item in m.group(1).split(";"):
            parts = [p.strip() for p in item.split(",")]
            if len(parts) >= 3:
                node = resolve(parts[-1])
                if node:
                    add(parts[0], with_unit(", ".join(parts[1:-1]), parts[-1]), node, "conference_header")
    for m in TURN_NAME_TITLE_ORG.finditer(text):
        node = resolve(m.group(3))
        if node:
            add(m.group(1), with_unit(m.group(2), m.group(3)), node, "call_turn")
    for m in TURN_DASHED.finditer(text):
        node = resolve(m.group(2))
        if node:
            add(m.group(1), with_unit(m.group(3), m.group(2)), node, "call_turn")
    for pattern in (PRESS_SAID, PRESS_BEFORE_SAID):
        for m in pattern.finditer(text):
            title, node = split_title_org(clean_title(m.group(2)), resolve)
            if node:                                 # a quote counts only when it names the person's company
                add(m.group(1), title, node, "press_quote")
    for m in PRESS_ORG_TITLE.finditer(text):
        # the up-to-7 words before the title keyword hold the company and maybe more title words
        words = [w.strip(",;:()\"“”") for w in text[max(0, m.start() - 80):m.start()].split()][-7:]
        words = [re.sub(r"['’]s$", "", w) for w in words]
        done = False
        for j in range(len(words), 0, -1):                     # words[j:] = extra title words
            if not all(TITLE_PREFIX_WORD.match(w) for w in words[j:]):
                break
            for i in range(max(0, j - 4), j):                  # words[i:j] = the company, longest first
                node = resolve(" ".join(words[i:j]))
                if node:
                    add(m.group(2), " ".join(words[j:] + [m.group(1)]), node, "press_quote")
                    done = True
                    break
            if done:
                break

    # -- company = the document's subject -----------------------------------------------------------------
    if subject:
        for m in TURN_PAREN_TITLE.finditer(text):
            add(m.group(1), m.group(2), None, "call_turn")
        for m in SPEAKERS_HEADER.finditer(head):
            for item in SPEAKERS_ITEM.finditer(m.group(1)):
                add(item.group(1), item.group(2), None, "call_header")
        for m in BRACKET.finditer(text):
            add(m.group(1), m.group(2), None, "call_turn")
        for m in NOTE_REMARKS.finditer(head):
            for item in re.split(r"[;,]", m.group(1)):
                im = NOTE_ITEM.match(item.strip())
                if im:
                    add(im.group(1), im.group(2), None, "note")
        if "executive officers" in text.lower():
            for m in TEN_K_TABLE.finditer(text):
                # the cell often runs on into the biography: "President ... Business Mr. Chakravarthy currently"
                title = re.split(r"\s(?:Mr|Ms|Mrs|Dr)\.\s|\.\s", m.group(3))[0]
                add(m.group(1), title, None, "filing_table")
        intro_sightings(text, add)
    return found


def intro_sightings(text, add):
    """Calls without titled turn heads (Motley Fool, defeatbeta): the host introduces the people on the line
    ("With me today are Jensen Huang, President and Chief Executive Officer, and Colette Kress, ..." /
    "TSMC's Senior Vice President and CFO, Mr. Wendell Huang"). Only people who then hold a turn of their
    own are read, and only in the opening of the call, where the company introduces its own team."""
    speakers = set()
    for m in TURN_HEAD.finditer(text):
        name = clean_name(m.group(1))
        if name:
            speakers.add(m.group(1).strip())
    if not speakers:
        return
    body = text[:15000]
    others = sorted(speakers, key=len, reverse=True)
    for spoken in speakers:
        name = clean_name(spoken)
        bare = re.sub(r"^(?:(?:Dr|Mr|Ms|Mrs)\.?\s+)", "", spoken)
        for m in re.finditer(r"(?:\b(?:Dr|Mr|Ms|Mrs)\.?\s+)?" + re.escape(bare) + r"\b", body):
            # (a) the title follows the name: "Shantanu Narayen, Adobe's Chair and CEO, David Wadhwani, ..."
            after = body[m.end():m.end() + 200]
            # "Clay Magouyrk, and Chief Financial Officer Hilary Maxson" / "Christophe Fouquet, and our CFO,
            # Roger Dassen": a title after ", and" belongs to the next person
            if after.startswith(",") and not re.match(r"(?i),\s*and\b", after):
                seg = after[1:]
                cut = len(seg)
                stop = re.search(r"[;\n(\"“]|\.(?:\s|$)|\s(?:who|will|is|are|to|for the|on the|joining|I'm|I am|"
                                 r"we|we're)\s", seg)
                if stop:
                    cut = stop.start()
                for other in others:
                    if other != spoken:
                        i = seg.find(other)
                        if 0 <= i < cut:
                            cut = i
                seg = clean_title(seg[:cut])
                seg = re.sub(r"^[A-Z][\w&.\-]*(?:\s[A-Z][\w&.\-]*)?['’]s\s+", "", seg)   # "Adobe's Chair"
                # keep the comma-separated parts that read as a title; the first that does not ("David
                # Wadhwani", "and I'm joined by") is the next person or the next sentence
                kept = []
                for part in seg.split(", "):
                    # test the piece without a leading "and", but keep the words as written
                    if not title_part(re.sub(r"^and\s+", "", part.strip()), first=not kept):
                        break
                    kept.append(part.strip())
                if kept:
                    add(name, ", ".join(kept), None, "intro")
            # (b) the title comes first: "TSMC's Senior Vice President and CFO, Mr. Wendell Huang"
            before = body[max(0, m.start() - 140):m.start()]
            bm = re.search(r"(?:\bour|[A-Z][\w&.\-]*['’]s)\s+([A-Za-z&,\- ]{2,110}?),?\s+$", before)
            if not bm or re.search(r"(?:^|[\s,])and$", bm.group(1).strip()):
                continue        # "..., our CEO, and Name" -- the title belongs to the person before
            # walk back from the name: "Chief Executive Officer, Robert Feurle, and Chief Financial Officer,
            # Gregg Lowe" gives Gregg Lowe only "Chief Financial Officer"
            kept = []
            for part in reversed(bm.group(1).split(", ")):
                if not title_part(re.sub(r"^and\s+(?:our\s+)?", "", part.strip()), first=False):
                    break
                kept.insert(0, part.strip())
            if kept:                                            # the first piece loses its "and our"
                kept[0] = re.sub(r"^and\s+(?:our\s+)?", "", kept[0])
            while kept and not TITLE_START.match(kept[0]):      # the title must start like one
                kept.pop(0)
            if kept:
                add(name, ", ".join(kept), None, "intro")


def title_part(part, first):
    """Is this comma-separated piece of running text part of a title? The first piece must start like a
    title ("Senior Vice President"); later pieces may also be a unit or role in capitals ("Controller",
    "Digital ICs and RF Products Group"), but never something shaped like a person's name ("Robert Feurle")
    or ordinary words ("I'm joined today by")."""
    part = part.strip()
    if not part:
        return False
    if TITLE_START.match(part):
        return True
    if first:
        return False
    words = part.split()
    if len(words) > 7 or clean_name(part):
        return False
    return all(w[0].isupper() or w.lower() in {"and", "of", "the", "&", "for", "in"} for w in words)


# ---------------------------------------------------------------------------------------------------------
# 5. Building the roster
# ---------------------------------------------------------------------------------------------------------

# Hand-checked short forms people use for a few very visible executives (video titles say "Jensen", "CC Wei").
# Applied only to a person the mining found; nobody is added by hand.
HAND_ALIASES = {
    ("NVIDIA", "Jensen Huang"): ["Jensen Huang", "Jensen"],
    ("AMD", "Lisa Su"): ["Lisa Su", "Dr. Lisa Su"],
    ("Broadcom", "Hock Tan"): ["Hock Tan", "Hock E. Tan"],
    ("Micron", "Sanjay Mehrotra"): ["Sanjay Mehrotra"],
    ("TSMC", "C.C. Wei"): ["C.C. Wei", "CC Wei", "C. C. Wei", "Dr. C.C. Wei"],
    # the Oracle Q4 FY2026 transcript spells her "Hilary Maxon"; Oracle Q1 FY2027 (09-10-2026) introduces "Chief
    # Financial Officer Hilary Maxson"
    ("Oracle", "Hilary Maxon"): ["Hilary Maxson"],
}
# Hand-checked: two spellings of one person that no rule can join (an English first name used instead of
# the given name). The first spelling is folded into the second.
SAME_PERSON = {
    ("Lattice Semiconductor", "Ford Tamer"): "Fouad Tamer",     # Lattice's CEO goes by Ford
    ("Tokyo Electron", "Tony Kawai"): "Toshiki Kawai",          # TEL's President & CEO goes by Tony
}
# Hand-checked: a name a source got wrong. Dropped, so it never becomes a name media_pull.py looks for.
HAND_DROP = {
    ("Sandisk", "Luis Russo"): "the Investing.com header misspells CFO Luis Visoso (listed from other sources)",
    # transcripts/conferences/vertex_goldmansachscommunacopiatechnologyconfer_2026-09-09.txt is a tech conference talk
    # of Vertex Inc. (tax software), not of the graph's Vertex (Vertex Pharmaceuticals, CEO Reshma Kewalramani)
    ("Vertex", "Chris Young"): "a Vertex Inc. (tax software) talk saved under the Vertex Pharmaceuticals node",
    ("Vertex", "John Schwab"): "a Vertex Inc. (tax software) talk saved under the Vertex Pharmaceuticals node",
    # the Investing.com header calls the moderator "Chief Financial Officer, Jazz Pharmaceuticals"; the transcript
    # itself says "Moderator: Jack Spinks"
    ("Jazz Pharmaceuticals", "Jack Spinks"): "the conference moderator, mislabelled as CFO in the speakers header",
}

# Hand-checked officials the mining cannot find (verification, 2026-10-17): the company's own documents name them,
# but never in a line the patterns above read ("joined today by Elon Musk, Vaibhav Taneja" has no titles), or the
# company has no document under transcripts/ at all. Every entry cites the company document that states the title.
# A hand entry replaces a mined entry of the same person at the same company and is never filtered or deduplicated.
# Left out on purpose because no company document could be found (only news articles): Matt Wood at AWS ("Chief AI
# and Technology Officer", GeekWire 2026) and Misha Laskin at Reflection (reflection.ai lists no leadership).
HAND_ADD = {
    "Tesla": [
        {"name": "Elon Musk", "title": "CEO", "aliases": [],
         "source": "Tesla 10-K (04-30-2026) | transcripts/edgar/TSLA_10-K_2026-04-30_supplychain.txt "
                   "('has served as our Chief Executive Officer since October 2008')"},
        {"name": "Vaibhav Taneja", "title": "Chief Financial Officer", "aliases": [],
         "source": "Tesla 10-K for FY2025, Exhibit 31.2 certification signed 01-28-2026 | https://www.sec.gov/Archives/"
                   "edgar/data/1318605/000162828026003952/tsla-2025x12x31xex312.htm"},
    ],
    # The SpaceX node carries xAI's products (Grok, Colossus): xAI Holdings became a SpaceX subsidiary in Feb 2026.
    "SpaceX": [
        {"name": "Elon Musk", "title": "CEO, CTO and Chairman", "aliases": [],
         "source": "Tesla 10-K (04-30-2026) | transcripts/edgar/TSLA_10-K_2026-04-30_supplychain.txt ('Chief Executive "
                   "Officer, Chief Technical Officer and Chairman of Space Exploration Technologies Corporation'); he "
                   "speaks for SpaceX on SpaceX Q2 FY2026 (08-04-2026) | transcripts/av/spacex_q2_2026.txt"},
    ],
    "OpenAI": [
        {"name": "Sarah Friar", "title": "CFO", "aliases": [],
         "source": "OpenAI announcement 'OpenAI welcomes Sarah Friar (CFO) and Kevin Weil (CPO)' (06-10-2024) | "
                   "https://openai.com/index/openai-welcomes-cfo-cpo/"},
    ],
    "SK Hynix": [
        {"name": "Kwak Noh-jung", "title": "CEO", "aliases": ["Noh-Jung Kwak", "Noh-jung Kwak", "Kwak Noh-Jung"],
         "source": "SK Hynix Q2 FY2026 (08-14-2026) | transcripts/dart/skhynix_q2_2026_dart.txt (the half-year report: "
                   "the representative director (CEO) is Kwak Noh-jung as of the filing date)"},
    ],
    "Oracle": [
        {"name": "Larry Ellison", "title": "Executive Chair of the Board and Chief Technology Officer", "aliases": [],
         "source": "Oracle press release: Larry Ellison Cancels His Plan to Sell Oracle Stock (09-12-2026) | "
                   "transcripts/ir/oracle_2026-09-12_larry-ellison-cancels-his-plan-to-sell-oracle-stoc.txt"},
    ],
    # cohere.com/about (read 2026-10-17): the leadership list with titles. Cohere has no document under transcripts/.
    "Cohere": [
        {"name": "Aidan Gomez", "title": "Co-founder and CEO", "aliases": [],
         "source": "Cohere About page, leadership list (read 10-17-2026) | https://cohere.com/about"},
        {"name": "François Chadwick", "title": "Chief Financial Officer", "aliases": ["Francois Chadwick"],
         "source": "Cohere About page, leadership list (read 10-17-2026) | https://cohere.com/about"},
        {"name": "Phil Blunsom", "title": "Chief Technology Officer", "aliases": [],
         "source": "Cohere About page, leadership list (read 10-17-2026) | https://cohere.com/about"},
        {"name": "Joelle Pineau", "title": "Chief AI Officer", "aliases": [],
         "source": "Cohere About page, leadership list (read 10-17-2026) | https://cohere.com/about"},
        {"name": "Nick Frosst", "title": "Co-founder", "aliases": [],
         "source": "Cohere About page, leadership list (read 10-17-2026) | https://cohere.com/about"},
        {"name": "Ivan Zhang", "title": "Co-founder", "aliases": [],
         "source": "Cohere About page, leadership list (read 10-17-2026) | https://cohere.com/about"},
    ],
}

# Hand-checked: one person who really holds roles at two companies at once. Everybody else found at two companies is
# kept only at the company of the newer document (the other entry is stale: Olivier Leonetti moved from Eaton to
# Equinix, Desmond Lynch from Rambus to Astera Labs).
BOTH_CURRENT = {
    "masayoshi son": "SoftBank Chairman and CEO and Arm Holdings Chairman of the Board (Arm Holdings 20-F, 05-26-2026)",
}

# Rule 2 (user, 2026-10-17): only these roles count as "an official of the company" -- CEO, CFO, COO, CTO and the other
# chief officers, president, founder, chair, the head or general manager of a named division / business unit / group,
# and the head of investor relations. A plain VP / SVP / EVP, a marketing or product lead, "SVP of Finance" or a
# "Managing Director" for a region do not.
RULE2_ACRONYM = re.compile(r"\b(?:Co-?)?C[A-Z]{1,2}O\b")                    # CEO, CFO, COO, CTO, CAIO, Co-CEO (capitals only)
RULE2_WORDS = re.compile(
    r"\b(?:chief\b[\w\s&,'’-]{0,40}?\bofficer|chief executive|(?<!vice )(?<!vice-)president|co-?founder|founder|"
    r"chair(?:man|woman|person)?|general manager|representative director|investor relations)\b", re.I)
RULE2_IR = re.compile(r"\bIR\b")
# "Head of Digital Appliances (DA) Business", "Head of Audio Group": the head of a named division / business / group.
# Not "Head of NAND Marketing", "Head of the R&D Team of the DA Business" or "Head of Galaxy Ecosystems Business Team".
RULE2_HEAD = re.compile(r"\bhead of (?:the )?(?:(?!\bof\b)[^,;])*?\b(?:division|business(?: unit| group)?|group|unit|"
                        r"sector|segment)s?\b\s*(?:\([^)]*\))?\s*(?=,|;|$|\band\b)", re.I)
RULE2_GM = re.compile(r"\bGM\b")


def rule2_title(title):
    """Does this title name one of the rule-2 roles above?"""
    title = title or ""
    return bool(RULE2_ACRONYM.search(title) or RULE2_WORDS.search(title) or RULE2_IR.search(title)
                or RULE2_HEAD.search(title) or RULE2_GM.search(title))


MAIN_ROLES = [("ceo", r"\bCEO\b|chief executive"), ("cfo", r"\bCFO\b|chief financial"),
              ("coo", r"\bCOO\b|chief operating"), ("cto", r"\bCTO\b|chief technology|chief technical"),
              ("cio", r"\bCIO\b|chief information"), ("ir", r"investor relations|\bIR\b"),
              ("president", r"(?<!vice )\bpresident\b"), ("chair", r"\bchair"), ("founder", r"founder"),
              ("gm", r"general manager|\bGM\b")]


def main_roles(title):
    """'EVP and Chief Financial Officer' -> {'cfo'}; 'Founder, President and CEO' -> {'founder', 'president', 'ceo'}."""
    return {role for role, pattern in MAIN_ROLES if re.search(pattern, title or "", re.I)}


def company_wide_role(title):
    """'ceo' / 'cfo' when the title is the whole company's CEO or CFO ("Founder, President and CEO", "EVP and CFO",
    "Interim Chief Financial Officer"); None for a unit's ("CEO, AWS", "CFO of Microsoft's Global Commercial Sales and
    Marketing Business", "Vice Chairman & CEO of the Device Solutions (DS) Division"), a co- or rotating CEO, or any
    other title. Used to notice that a new CEO / CFO took over (see build_roster)."""
    title = title or ""
    if re.search(r"\b(?:co-?ceo|co-chief|rotating)\b", title, re.I):
        return None
    for role, pattern in (("ceo", r"\bCEO\b|\bchief executive(?: officer)?\b"),
                          ("cfo", r"\bCFO\b|\bchief financial officer\b")):
        m = re.search(pattern, title, re.I)
        if not m:
            continue
        rest = title[m.end():]
        names_unit = re.match(r"\s*(?:,|of\b|for\b|at\b|-|–)\s*\S", rest, re.I)
        more_roles = re.match(r"\s*,\s*(?:and\s+)?(?:president|director|chair|founder|co-?founder|board|principal)",
                              rest, re.I)
        return None if names_unit and not more_roles else role
    return None


def edit_distance(a, b):
    """How many single-letter edits turn a into b (Levenshtein)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def same_person(name_a, name_b):
    """Two spellings of one person at one company: 'Marc Graff' / 'Mark Graff' (one letter apart),
    'Haijian He' / 'Henry Haijian He' and 'Paulo Ruiz' / 'Paulo Ruiz Sternadt' (one name inside the other)."""
    a, b = name_words(name_a), name_words(name_b)
    if len(a) < 2 or len(b) < 2:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if set(short) <= set(long_):
        return True

    def close(x, y):
        return x == y or (min(len(x), len(y)) >= 3 and edit_distance(x, y) <= 1)
    return (a[0] == b[0] and close(a[-1], b[-1])) or (a[-1] == b[-1] and close(a[0], b[0]))

# Order inside a company: chief executive first, IR last.
ROLE_ORDER = [r"\bCEO\b|Chief Executive", r"(?<!Vice )\bPresident\b", r"\bCFO\b|Chief Financial",
              r"\bCOO\b|Chief Operating", r"\bCTO\b|Chief Technology", r"founder", r"Chair", r"Chief",
              r"EVP|SVP|Executive Vice|Senior Vice|General Manager|Head of|President of", r"Investor Relations|\bIR\b"]


def role_rank(title):
    for i, pattern in enumerate(ROLE_ORDER):
        if re.search(pattern, title, re.I):
            return i
    return len(ROLE_ORDER)


def derived_aliases(name):
    """Spellings a news title may use for the same person: without middle initials ('Hock E. Tan' ->
    'Hock Tan'), without dots in initials ('C.C. Wei' -> 'CC Wei')."""
    out = set()
    words = name.split()
    no_initials = [w for w in words if not re.fullmatch(r"[A-Z]\.", w)]
    if len(no_initials) >= 2 and len(no_initials) < len(words):
        out.add(" ".join(no_initials))
    if re.search(r"\b[A-Z]\.[A-Z]\.", name):
        out.add(re.sub(r"\b([A-Z])\.([A-Z])\.", r"\1\2", name))
    return out


def group_people(observations, chosen):
    """{(company, person key): [sightings]}. Sightings are first grouped by person_key, then groups of one
    company that same_person() (or SAME_PERSON) calls one person are joined."""
    same = {(node, person_key(a)): person_key(b) for (node, a), b in SAME_PERSON.items()}
    drop = {(node, person_key(n)) for (node, n) in HAND_DROP}
    groups = defaultdict(list)
    for o in observations:
        if o.node not in chosen:
            continue
        key = person_key(o.name)
        if not key or (o.node, key) in drop:
            continue
        key = same.get((o.node, key), key)
        groups[(o.node, key)].append(o)
    # join near-duplicates inside each company; the key with more sightings absorbs the other
    by_company = defaultdict(list)
    for (node, key) in groups:
        by_company[node].append(key)
    for node, keys in by_company.items():
        keys.sort(key=lambda k: -len(groups[(node, k)]))
        for i, big in enumerate(keys):
            if (node, big) not in groups:
                continue
            big_name = groups[(node, big)][0].name
            for small in keys[i + 1:]:
                if (node, small) in groups and same_person(big_name, groups[(node, small)][0].name):
                    groups[(node, big)].extend(groups.pop((node, small)))
    return groups


def build_roster(observations, chosen):
    """Group sightings per company and person and keep the people who are officials today:

    1. the person's newest sighting must not say they left; the title shown is the newest one that names a rule-2
       role (rule2_title), and a person with no such title is left out;
    2. one person at two companies: only the company of the newer document stays (BOTH_CURRENT excepted);
    3. a company-wide CEO or CFO whose last sighting in that role is older than the first sighting of another
       person in the same role was succeeded and is left out ("Kirsten Spears, CFO" 06-2026 at Broadcom, then
       "Amie Thuener, CFO" from 09-2026); two holders seen side by side are both kept (co-CEOs);
    4. HAND_ADD entries are added last and replace a mined entry of the same person.
    Returns (companies, sightings, dropped); dropped lists who was left out by steps 1-3 and why (printed)."""
    groups = group_people(observations, chosen)
    hand_aliases = {(node, person_key(n)): a for (node, n), a in HAND_ALIASES.items()}
    sightings = {}                          # (company, listed name) -> its sightings, for --show
    dropped = defaultdict(list)             # reason -> ["Name (Company): ..."]
    people = []                             # one dict per (company, person) still in
    for (node, key), obs in groups.items():
        newest_first = sorted(obs, key=lambda o: (o.date, KIND_RANK.get(o.kind, 0)), reverse=True)
        if newest_first[0].departed:
            continue
        current = [o for o in newest_first if not o.departed]
        best = next((o for o in current if rule2_title(o.title)), None)
        if best is None:
            dropped["no rule-2 role (CEO / CFO / chief officer / president / founder / chair / division head or "
                    "GM / IR)"].append(f"{current[0].name} ({node}): {current[0].title}")
            continue
        spellings = Counter(o.name for o in obs)
        # the most frequent spelling; on a tie the newest document's spelling
        name = max(spellings, key=lambda s: (spellings[s], s == best.name))
        aliases = set(spellings) | derived_aliases(name)
        for s in list(spellings):
            aliases |= derived_aliases(s)
        aliases |= set(hand_aliases.get((node, key), []))
        aliases = sorted(a for a in aliases if a.lower() != name.lower())
        roles = defaultdict(list)           # 'ceo' / 'cfo' -> [(date, document)] of the sightings in that role
        for o in current:
            role = company_wide_role(o.title)
            if role:
                roles[role].append((o.date, o.path))
        people.append({"node": node, "key": key, "entry": {"name": name, "title": best.title, "aliases": aliases,
                                                          "source": best.source()},
                       # first = the oldest DATED sighting ('' when none is dated: then no move is ever decided)
                       "first": min((o.date for o in current if o.date), default=""),
                       "newest": current[0].date, "roles": roles, "obs": obs})

    # 2. one person, two companies: a MOVE (every sighting at company A is older than the first one at company B)
    #    leaves only B. Sightings that overlap in time are kept at both companies: that is two people with one name
    #    (Micron's CFO Mark Murphy and 3M's CIO Mark Murphy) or a person who holds both roles.
    by_key = defaultdict(list)
    for p in people:
        by_key[p["key"]].append(p)
    for key, same in by_key.items():
        if len({p["node"] for p in same}) < 2 or key in BOTH_CURRENT:
            continue
        newest = max(same, key=lambda p: p["newest"])
        for p in same:
            # a move keeps the kind of role (CFO -> CFO, IR -> IR); "CIO" at 3M and "CFO" at Micron are two people
            same_role = main_roles(p["entry"]["title"]) & main_roles(newest["entry"]["title"])
            if p is not newest and same_role and p["newest"] and p["newest"] < newest["first"]:
                p["drop"] = "moved"
                dropped["moved to another company (a newer document names the new one)"].append(
                    f"{p['entry']['name']} ({p['node']}, last {p['newest'] or 'undated'}) -> {newest['node']} "
                    f"(from {newest['first']})")

    # 3. a CEO / CFO who was succeeded. Two spellings of one person ("Jack Kober" / "John Kober": the same family name;
    #    "Adam Norwitt" / "Adam Norvell": the same first name and family names that start alike) are joined instead.
    #    A successor must be named in that role in
    #    at least two documents, so one mis-read title ("Chief Executive Officer" for the CEO of a unit) never
    #    removes the real CEO.
    by_node = defaultdict(list)
    for p in people:
        if "drop" not in p:
            by_node[p["node"]].append(p)
    for node, staff in by_node.items():
        for role in ("ceo", "cfo"):
            holders = [p for p in staff if p["roles"].get(role) and "drop" not in p]
            if len(holders) < 2:
                continue
            latest = max(holders, key=lambda p: max(p["roles"][role]))
            took_over = min(latest["roles"][role])[0]
            for p in holders:
                if p is latest or max(p["roles"][role])[0] >= took_over:
                    continue                              # seen side by side: co-holders, or not clear -> keep both
                a, b = name_words(p["entry"]["name"]), name_words(latest["entry"]["name"])
                if a[-1] == b[-1] or (a[0] == b[0] and a[-1][:3] == b[-1][:3]):
                    # one person, two spellings: the spelling found in more documents is the name, the other an alias
                    docs_p, docs_latest = len({o.path for o in p["obs"]}), len({o.path for o in latest["obs"]})
                    keep, lose = (p, latest) if docs_p > docs_latest else (latest, p)
                    keep["entry"]["aliases"] = sorted(set(keep["entry"]["aliases"]) | set(lose["entry"]["aliases"])
                                                      | {lose["entry"]["name"]})
                    keep["entry"]["title"], keep["entry"]["source"] = latest["entry"]["title"], latest["entry"]["source"]
                    lose["drop"] = "same person"
                    dropped["one person, two spellings (joined)"].append(
                        f"{lose['entry']['name']} -> {keep['entry']['name']} ({node})")
                    continue
                successor_docs = {path for _date, path in latest["roles"][role]}
                if company_wide_role(p["entry"]["title"]) == role and len(successor_docs) >= 2:
                    p["drop"] = "succeeded"
                    dropped[f"succeeded as {role.upper()}"].append(
                        f"{p['entry']['name']} ({node}, last {max(p['roles'][role])[0] or 'undated'}) -> "
                        f"{latest['entry']['name']} (from {took_over}, {len(successor_docs)} documents)")

    companies = defaultdict(list)
    for p in people:
        if "drop" not in p:
            companies[p["node"]].append(p["entry"])
            sightings[(p["node"], p["entry"]["name"])] = p["obs"]

    # 4. the hand-checked officials
    for node, entries in hand_added(chosen).items():
        for entry in entries:
            key = person_key(entry["name"])
            companies[node] = [e for e in companies[node] if person_key(e["name"]) != key]
            companies[node].append(dict(entry))
            sightings[(node, entry["name"])] = []
    for node in companies:
        companies[node].sort(key=lambda p: (role_rank(p["title"]), p["name"]))
    return dict(companies), sightings, dropped


def collect(node_ids, matcher):
    observations = []
    files = sorted(glob.glob(os.path.join(TRANSCRIPTS, "**", "*.txt"), recursive=True))
    for path in files:
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        parts = rel.split("/")
        if len(parts) > 2 and parts[1] in SKIP_FOLDERS:
            continue
        observations.extend(read_document(path, rel, node_ids, matcher))
    return observations, len(files)


# Officials the nightly gap fill adds (enrich skill section 12, 2026-10-19) for companies whose documents name nobody the
# mining can read (most Korean / Japanese / Chinese names): media/roster_additions.json, the same shape as HAND_ADD,
# each entry citing the company document that states the title. It is data, so the nightly can add to it without
# touching this file; a HAND_ADD entry for the same person wins.
ADDITIONS_FILE = os.path.join(MEDIA_DIR, "roster_additions.json")


def hand_added(node_ids):
    """HAND_ADD plus media/roster_additions.json (graph nodes only), one list per node."""
    merged = {}
    if os.path.exists(ADDITIONS_FILE):
        with open(ADDITIONS_FILE, encoding="utf-8") as f:
            for node, entries in json.load(f).items():
                if node.startswith("_"):
                    continue                            # "_about"
                if node not in node_ids:
                    print(f"roster_additions.json: {node!r} is not a graph node -- skipped")
                    continue
                merged[node] = list(entries)
    for node, entries in HAND_ADD.items():
        keys = {person_key(e["name"]) for e in entries}
        merged[node] = [e for e in merged.get(node, []) if person_key(e["name"]) not in keys] + list(entries)
    return merged


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)                       # never leave a half-written file behind


def build(show=None):
    graph = load_graph()
    node_ids = [n["id"] for n in graph["nodes"]]
    chosen, edges = selected_nodes(graph)
    matcher = OrgMatcher(node_ids)
    observations, n_files = collect(node_ids, matcher)
    # Every graph node is mined (the verification of 2026-10-17 found genuine interviews of companies outside the
    # top 200, e.g. Generac): the selected nodes are always listed, even with no official yet (the gap stays
    # visible), and every other node is listed when it has at least one official.
    companies, sightings, dropped = build_roster(observations, set(node_ids))
    extra = sorted((n for n in companies if n not in set(chosen) and companies[n]), key=lambda n: (-edges[n], n))
    ordered = {nid: companies.get(nid, []) for nid in chosen + extra}

    if show:
        if show not in ordered:
            print(f"{show!r} has no official on the roster")
            return 1
        for person in ordered[show]:
            print(f"{person['name']} -- {person['title']}   aliases={person['aliases']}")
            # one line per (date, kind, title, document); a call turn repeats on every answer, so count them
            lines = Counter((o.date or "----------", o.kind, o.title, o.source())
                            for o in sightings[(show, person["name"])])
            for (when, kind, title, src), n in sorted(lines.items(), reverse=True):
                times = f" x{n}" if n > 1 else ""
                print(f"      {when}  {kind:<17} {title!r}{times}  {src}")
            if not lines:
                print(f"      hand-checked (HAND_ADD): {person['source']}")
        return 0

    out = {
        "_about": "Officials of each graph company, for media_pull.py (user rule 2026-10-17: a news video counts "
                  "only when an official of the company speaks on camera, named in the video title or "
                  "description). Mined by media_roster.py, without any model, from documents under "
                  "transcripts/: titled speaker lines of earnings calls and conference talks, 10-K executive-"
                  "officer tables, and quote attributions in company press releases. Analysts, moderators, "
                  "hosts, interpreters and bank / broker lines are dropped, and so is anyone whose title names "
                  "none of the rule-2 roles (CEO, CFO, COO, CTO and other chief officers, president, founder, "
                  "chair, head or GM of a named division / business / group, IR head). title = the newest such "
                  "title; source = that document's source label | path. One person found at two companies is "
                  "kept at the company of the newer document; a CEO / CFO succeeded by a newer one is left out. "
                  "Companies: the "
                  f"{TOP_N} nodes with the most edges in graph/merged_graph.json plus every cloud_infra and "
                  "ai_models node (an empty list = no verified official yet), then every other node with at least "
                  "one official. Rebuild with `python -X utf8 media_roster.py`; never edit by hand (hand-checked "
                  "fixes live in media_roster.py HAND_ADD, HAND_ALIASES, SAME_PERSON, HAND_DROP, BOTH_CURRENT; "
                  "each HAND_ADD entry cites the company document that states the title).",
        "updated": date.today().isoformat(),
        "companies": ordered,
    }
    # The roster is rebuilt before every daily pull (2026-10-19). media_pull.py re-decides its stamped skips whenever
    # "updated" changes, so the date moves only when the roster itself changed.
    if os.path.exists(EXECUTIVES_FILE):
        with open(EXECUTIVES_FILE, encoding="utf-8") as f:
            before = json.load(f)
        if before.get("companies") == ordered:
            out["updated"] = before.get("updated", out["updated"])
    write_json(EXECUTIVES_FILE, out)

    covered = [n for n in ordered if ordered[n]]
    people = sum(len(v) for v in ordered.values())
    kinds = Counter(o.kind for o in observations)
    print(f"read {n_files} files; {len(observations)} sightings ({dict(kinds)})")
    print(f"wrote {os.path.relpath(EXECUTIVES_FILE, ROOT)}: {len(ordered)} companies ({len(chosen)} selected + "
          f"{len(extra)} more with an official), {people} people, {len(covered)} companies with >= 1 official")
    for reason, who in sorted(dropped.items()):
        print(f"  left out, {reason}: {len(who)}")
        if not reason.startswith("no rule-2 role"):
            for line in sorted(who):
                print(f"      {line}")
    top = chosen[:TOP_N]
    layers = {n["id"]: set(n.get("layers", [])) for n in graph["nodes"]}
    labs = [n for n in chosen if ALWAYS_LAYERS & layers[n]]
    print(f"  top {TOP_N} by edges: {sum(1 for n in top if ordered[n])}/{len(top)} covered")
    print(f"  cloud_infra + ai_models nodes: {sum(1 for n in labs if ordered[n])}/{len(labs)} covered")
    missing = [n for n in chosen if not ordered[n]]
    print(f"  no official found ({len(missing)}): {', '.join(missing)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Build media/executives.json and media/channels.json")
    ap.add_argument("what", nargs="?", default="executives", choices=["executives", "channels"])
    ap.add_argument("--show", metavar="NODE", help="print one company's roster with every sighting (no write)")
    args = ap.parse_args()
    os.chdir(ROOT)                              # verify_graph's helpers read paths relative to the repo root
    if args.what == "channels":
        return check_channels()
    return build(show=args.show)


if __name__ == "__main__":
    sys.exit(main())
