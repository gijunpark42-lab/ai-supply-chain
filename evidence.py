"""
evidence.py — "show me where this number comes from".

Every quarterly_data entry and every contract in graph/merged_graph.json carries a
source label ("NVIDIA Q2 FY2027 (08-26-2026)"). verify_graph.py already checks, per
entry, whether that label resolves to a file on disk and whether the entry's numbers
appear in it. This script goes one step further, for the web app: it finds the actual
PASSAGE in the source text that backs each entry and saves a short excerpt of it, so a
reader can click a data point in the node panel and see the sentence it came from.

Nothing here is written by a model. It is plain text search, so it is deterministic:
the same graph + the same transcripts always give the same evidence.json.

What it writes
--------------
graph/evidence.json  (copied to web/public/data/ by `npm run sync`, fetched lazily by
web/src/components/Evidence.tsx):

    { "generated": "2026-09-05",
      "entries": {
        "<key>": { "doc":     "transcripts/av/nvidia_q3_2027.txt",   # null when no_source
                   "excerpt": "…context «$57 billion» context…",     # null when nothing found
                   "matched": "$57 billion",                          # the text inside «…»
                   "status":  "found" | "no_match" | "no_source",
                   "via":     "number" | "phrase" | "words" | "counterparty" | null,
                   "unmatched": ["45", "3.2"] }   # optional: figure numbers absent from the doc
      } }

key = first 16 hex characters of sha1("<kind>|<company>|<target>|<label>|<signal>"),
UTF-8 encoded, where
    kind    = "qd" for a node's quarterly_data entry, "contract" for an edge contract
    company = the node id (for a contract: the edge SOURCE company)
    target  = the edge TARGET company ("" for qd)
    label   = the entry's `quarter` (qd) / `source` (contract) label, exactly as stored
    signal  = the entry's `signal` text, exactly as stored
web/src/lib/evidence.ts builds the identical key in the browser, so the page can look
an entry up without shipping company names or signal text twice.

How the excerpt is chosen
-------------------------
1. SOURCE  — resolve the label to a file exactly the way verify_graph.py does (its
             resolver is imported, not copied). No file on disk -> status "no_source".
2. NUMBERS — take every number written in figure / units / value (verify_graph.numbers_in;
             years and single digits are ignored there, dates like "08-14-2026" here). Look
             each one up in the document: exact ("24.8"), trailing-zero ("14.0" ~ "14"),
             rounded ("88.9" ~ 88.86), and unit-rescaled ("1.898" B ~ "1,898" M; "150.3" KRW B
             ~ a filing's "150,323" 백만원) — the same four ways verify_graph's Doc.has_number
             accepts a number, but position-aware, so we know WHERE it is. Every occurrence is
             scored: distinctive words of the signal within ±220 characters ("distinctive" =
             rare across the whole transcript corpus, an IDF weight) + how specific the matched
             token is (a bare "48" proves little, "150,323" a lot). Best total wins. Numbers
             present but none found -> "no_match" (the nearest passage found through step 3
             is still attached as context).
3. WORDING — if the entry has no number, look for the signal's wording instead: the
             highest-scoring run of 4-6 consecutive signal words that occurs in the document
             (stopwords do not count towards the score), then 3- and 2-word phrases, then a
             single rare word that has another signal word within the same ±220 window,
             then the name of the counterparty (the other company on the edge, or the
             Korean alias of it inside a DART filing). Nothing -> "no_match".
4. EXCERPT — verbatim source text (only runs of whitespace are collapsed to one space),
             ±220 characters around the match, cut on word boundaries, the match wrapped
             in «…», "…" marking a cut edge.
             EXCEPT a news interview (transcripts/media/, media_pull.py; user rule 2026-10-17: nothing of
             the video or the transcript on the website): its record keeps the status but has
             doc / excerpt / matched = null (hide_media_source below).

How to run
----------
    python evidence.py                                   # full build -> graph/evidence.json
    python evidence.py --label "SK Hynix Q2 FY2026 (08-14-2026)"   # print those entries only
    python evidence.py --company Vistra                  # print entries touching a company
graph_build.py calls build_evidence(graph) right after derive_all(graph), so the file is
fresh on every build (and `--sync` copies it into web/public/data).
"""

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import sys
import time
from array import array
from collections import Counter, defaultdict
from datetime import date

# Reuse verify_graph's machinery instead of re-implementing it:
#   load_documents()  -> every transcript / supply-contract block as a Doc (path, text, label)
#   resolve_label()   -> label -> Doc (header label, then filename join, then loose event match)
#   numbers_in()      -> the checkable numbers inside figure / units / value
#   NUMBER            -> the regex that defines what a "number" is ("27,800", "24.8", "1.6")
#   KO_ALIASES        -> Korean spellings of the big counterparties ("SK Hynix" -> "SK하이닉스")
#   is_media_source() -> is this a news-interview transcript (transcripts/media/, media_pull.py)?
from verify_graph import load_documents, resolve_label, resolve_label_docs, numbers_in, NUMBER, KO_ALIASES, is_media_source
from agent.corpus import list_documents

GRAPH_PATH = "graph/merged_graph.json"
OUT_PATH = "graph/evidence.json"
CONTEXT = 220            # characters of context kept on each side of the match
SIZE_LIMIT = 2_000_000   # bytes; above this, no_match entries lose their excerpts
MAX_SPANS = 3000         # safety cap on the occurrences examined per number / phrase

WORD = re.compile(r"\w+")      # a "word" for phrase search: letters/digits, punctuation dropped
WS = re.compile(r"\s+")        # any run of whitespace (collapsed to one space in excerpts)

# Words that carry no meaning for "is this the right passage?" — they never count towards
# a phrase's distinctiveness score, but they may still sit INSIDE a matched phrase.
STOPWORDS = set("""
a about above across after again against all almost along already also although am among an and
another any are around as at back be became because become been before being below between both
but by came can cannot come could did do does doing done down during each either else even ever
every few first for from further get gets got had has have having he her here hers herself him
himself his how however i if in include including into is it its itself just last later least
let like made make makes many may me might more most much must my myself near need new no nor not
now of off often on once one only onto or other others our ours out over own per rather same
second she should since so some still such than that the their theirs them themselves then there
these they third this those though three through throughout to too toward two under until up upon
us use used very via vs was we well were what when where whether which while who whom whose why
will with within without would year years yes yet you your yours yourself
yoy qoq q1 q2 q3 q4 h1 h2 1h 2h fy cy
""".split())


# ---------------------------------------------------------------------------
# 1. The key — must match web/src/lib/evidence.ts byte for byte
# ---------------------------------------------------------------------------

def entry_key(kind, company, target, label, signal):
    """First 16 hex chars of sha1("kind|company|target|label|signal"), UTF-8 encoded.

    Everything is joined as-is: no trimming, no case folding. The TypeScript side does
    exactly the same, so both ends land on the same 16 characters for the same entry.
    """
    raw = "|".join([kind, company, target, label, signal])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 2. Word statistics across the corpus ("how rare is this word?")
# ---------------------------------------------------------------------------
#
# A signal like "Cloud revenue rose 82%" shares the words "cloud" and "revenue" with
# almost every earnings call, but "Anthropic" or "CoWoS" with very few. When a number
# occurs 20 times in a document we want the occurrence surrounded by the RARE words of
# the signal. IDF (inverse document frequency) is the classic weight for that:
#     idf = log((N + 1) / (df + 1))      N = documents, df = documents containing the word
# A word in every document weighs ~0; a word in one document weighs ~5. We store
# max(0, idf - 0.75), so words found in more than about half the corpus weigh nothing.
#
# Words are reduced to their first 6 letters ("shipments"/"shipment"/"shipped" -> "shipme"/
# "shippe") so light inflection still counts as the same word. That reduced form is a "stem"
# here; each stem gets a small integer id so per-token storage stays compact.

STEM_ID = {}        # stem string -> int id
DF = Counter()      # stem id -> number of documents containing it
IDF = {}            # stem id -> weight, filled once every document is indexed


def stem_of(word):
    """'shipments' -> 'shipme'. Korean words carry their particles attached ("수주잔고는"),
    so they are cut to their first two syllables instead ("수주")."""
    return word[:2] if "가" <= word[0] <= "힣" else word[:6]


def sid_of(word):
    """Integer id of a word's stem, creating it on first sight."""
    stem = stem_of(word)
    sid = STEM_ID.get(stem)
    if sid is None:
        sid = STEM_ID[stem] = len(STEM_ID)
    return sid


# English signal words -> the Korean stem a DART filing would use for the same idea
# (CLAUDE.md's Workflow 2b translation table, reversed). A Korean filing never contains the
# signal's English words, so without this the passage scoring is blind inside DART documents:
# "NEW ORDERS KRW 179.0B" must prefer the 수주 (orders) table over an 영업이익 line that
# happens to hold the same digits.
GLOSSARY = {
    "order": "수주", "orders": "수주", "backlog": "수주", "revenue": "매출", "revenues": "매출",
    "sales": "매출", "operating": "영업", "profit": "영업", "margin": "이익", "income": "이익",
    "capacity": "생산", "production": "생산", "output": "생산", "utilisation": "가동",
    "utilization": "가동", "capex": "투자", "investment": "투자", "customer": "매출처",
    "customers": "매출처", "client": "고객", "clients": "고객", "supplier": "매입", "suppliers": "매입",
    "purchase": "매입", "purchases": "매입", "export": "수출", "exports": "수출", "research": "연구",
    "development": "개발", "employees": "직원", "headcount": "직원", "dividend": "배당",
    "contract": "계약", "contracts": "계약", "agreement": "계약", "plant": "공장", "factory": "공장",
    "subsidiary": "종속", "subsidiaries": "종속", "shares": "주식", "debt": "차입", "borrowings": "차입",
    "inventory": "재고", "inventories": "재고", "equipment": "장비", "transformer": "변압",
    "transformers": "변압", "substrate": "기판", "substrates": "기판", "wafer": "웨이퍼",
    "wafers": "웨이퍼", "materials": "재료", "material": "재료", "semiconductor": "반도체",
    "memory": "메모리", "display": "디스플", "battery": "배터리", "renewable": "신재생",
    "renewables": "신재생", "grid": "전력", "power": "전력", "cash": "현금", "assets": "자산",
    "patent": "특허", "patents": "특허", "domestic": "국내", "overseas": "해외", "guidance": "전망",
    "outlook": "전망",
}


def is_content(word):
    """A word that can help identify a passage: 3+ chars, not a stopword, not a bare number."""
    return len(word) >= 3 and word not in STOPWORDS and not word.isdigit()


def weight(word):
    """IDF weight of a signal word; 0 when the word never occurs in the corpus."""
    sid = STEM_ID.get(stem_of(word))
    return IDF.get(sid, 0.0) if sid is not None else 0.0


def content_stems(texts):
    """Set of stem ids for the content words of the given texts (the entry's own words),
    plus the Korean stems the GLOSSARY maps them to."""
    wanted = set()
    for text in texts:
        for w in WORD.findall((text or "").lower()):
            if is_content(w):
                for stem in (stem_of(w), GLOSSARY.get(w)):
                    sid = STEM_ID.get(stem) if stem else None
                    if sid is not None:
                        wanted.add(sid)
    return wanted


# "Hanmi Semiconductor Q2 FY2026 (08-14-2026)" -> "Hanmi Semiconductor". Same split as
# verify_graph.label_company, but we keep the words rather than one squashed token.
LABEL_HEAD = re.compile(r"\s+(Q[1-4]\s+FY|DART|GTC|Computex|\(|note)")


def own_company_words(label):
    """Lowercase words of the company the document is ABOUT. Its own name is everywhere in
    its own filing ("HANMI Semiconductor Co., Ltd."), so it must never anchor or score a
    passage — it would look distinctive (rare across the corpus) while proving nothing."""
    head = LABEL_HEAD.split(label)[0]
    return set(WORD.findall(head.lower()))


# ---------------------------------------------------------------------------
# 3. One document, indexed for fast search
# ---------------------------------------------------------------------------

# The leading header lines of a saved source file (label, URL, dates, "Image source: The
# Motley Fool."). They are not the document's own words, and their dates would otherwise
# give false hits for numbers like "14" — so the body starts after them.
HEADER_LINE = re.compile(
    r"^(#(?!#)|SOURCE:|TITLE:|CALL DATE:|QUARTER:|NOTE:|Image source:|Need a quote|Call hosts:"
    r"|Earnings announced:|-{3,}\s*$|(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,)")


def body_of(text):
    """Drop the file's header block (at most the first 15 lines that look like a header)."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and i < 15 and (not lines[i].strip() or HEADER_LINE.match(lines[i])):
        i += 1
    return "\n".join(lines[i:])


class DocIndex:
    """Everything needed to search ONE document quickly, built once per document.

    self.disp   the document body with whitespace collapsed — excerpts are cut from it,
                so every excerpt is verbatim text.
    tokens      four parallel arrays (one entry per word): where the word starts/ends in
                self.disp, its stem id, and where it starts in self.search. Arrays of
                unsigned ints keep ~5 million corpus-wide tokens to a few dozen MB.
    self.search lowercase words joined by single spaces, punctuation gone. A phrase
                becomes "word word word" and str.find (C speed) does the searching.
    numbers     every number token, indexed by its comma-free text, by its digit runs,
                and as a float (for the rounding match).
    """

    def __init__(self, doc, count_df=True):
        self.path = doc.path
        self.disp = WS.sub(" ", body_of(doc.text)).strip()

        self.starts, self.ends = array("I"), array("I")
        self.sids, self.offs = array("I"), array("I")
        parts = []
        pos = 0
        for m in WORD.finditer(self.disp):
            w = sys.intern(m.group().lower())      # intern: one str object per distinct word
            self.starts.append(m.start())
            self.ends.append(m.end())
            self.sids.append(sid_of(w))
            self.offs.append(pos)
            parts.append(w)
            pos += len(w) + 1
        self.search = " ".join(parts)
        self.words = set(parts)                     # quick "could this phrase be here at all?"
        if count_df:                                # build_evidence counts DF in its own pass (count_stems)
            for sid in set(self.sids):
                DF[sid] += 1

        self.by_bare = defaultdict(list)   # "24.8" -> [(start, end), ...]  (commas removed)
        self.by_run = defaultdict(list)    # "1898" -> spans  (digit runs of 3+ digits)
        self.values = []                   # (float, start, end)  for the rounding match
        self._rounded = {}                 # decimals -> {rounded value: spans}, built lazily
        for m in NUMBER.finditer(self.disp):
            bare = m.group().replace(",", "")
            span = (m.start(), m.end())
            self.by_bare[bare].append(span)
            for run in bare.split("."):
                if len(run) >= 3:
                    self.by_run[run].append(span)
            try:
                self.values.append((float(bare), span[0], span[1]))
            except ValueError:
                pass

    # -- numbers -------------------------------------------------------------

    def rounded(self, decimals):
        """Document numbers rounded to `decimals` places -> their spans (cached per precision)."""
        if decimals not in self._rounded:
            table = defaultdict(list)
            for v, s, e in self.values:
                table[round(v, decimals)].append((s, e))
            self._rounded[decimals] = table
        return self._rounded[decimals]

    def scaled_matches(self, value, decimals):
        """Integer amounts in the document that ROUND to `value` once divided by a unit:
        figure "KRW 422.5B" vs a filing's "422,483" (백만원, /10^3), "422,483,117,900" (원,
        /10^9), "4,225" (억원, /10) or "422,483,118" (천원, /10^6). verify_graph's digit-run
        prefix rule catches truncation ("422,4…"); this also catches rounding up. Sorted
        integer values + bisect make each unit a range query."""
        if not hasattr(self, "_ints"):
            self._ints = sorted((v, s, e) for v, s, e in self.values if v >= 1000 and v == int(v))
            self._int_keys = [v for v, _s, _e in self._ints]
        spans = []
        half = 0.5 * 10 ** -decimals
        for unit in (10, 10 ** 3, 10 ** 6, 10 ** 9):
            lo = bisect.bisect_left(self._int_keys, (value - half) * unit)
            hi = bisect.bisect_left(self._int_keys, (value + half) * unit)
            spans.extend((s, e) for _v, s, e in self._ints[lo:hi])
        return spans

    def runs_with_prefix(self, digits):
        """Spans of every digit run (5+ digits) that STARTS with `digits` — "50.9" (KRW B)
        vs a filing's "50,912,345,678" (won). Sorted keys + bisect keep it O(log n)."""
        if not hasattr(self, "_runs_sorted"):
            self._runs_sorted = sorted(self.by_run)
        lo = bisect.bisect_left(self._runs_sorted, digits)
        hi = bisect.bisect_left(self._runs_sorted, digits + "￿")
        spans = []
        for run in self._runs_sorted[lo:hi]:
            if len(run) >= 5 and run != digits:
                spans.extend(self.by_run[run])
        return spans

    def number_candidates(self, number):
        """Every place this figure-number could be, as (start, end, how). `how` is 'exact',
        'rounded' or 'rescaled' — the four ways verify_graph.Doc.has_number accepts a number,
        kept position-aware. ALL rules contribute (not just the strictest that fires): a
        bare "179" matched exactly may be a page number, while the same figure rescaled to
        "179,012" (백만원) is the real one — find_by_numbers ranks them."""
        bare = number.replace(",", "")
        out = []
        seen = set()

        def add(spans, how):
            for span in spans[:MAX_SPANS]:
                if span not in seen:
                    seen.add(span)
                    out.append((span[0], span[1], how))

        add(self.by_bare.get(bare, []), "exact")
        if "." in bare:                                            # "14.0" -> "14", "4.00" -> "4"
            add(self.by_bare.get(bare.rstrip("0").rstrip("."), []), "exact")
        try:
            value = float(bare)
        except ValueError:
            return out
        decimals = len(bare.split(".")[1]) if "." in bare else 0
        add(self.rounded(decimals).get(value, []), "rounded")      # "88.9" ~ the document's 88.86
        digits = re.sub(r"\D", "", bare).lstrip("0")               # "1.898" (B) ~ "1,898" (M)
        if len(digits) >= 3:
            # A rescaled figure is a rounded amount against a RAW integer amount (won, 백만원,
            # millions). A document token with its own decimals ("1,503.1") is not that.
            add([sp for sp in self.by_run.get(digits, []) if "." not in self.disp[sp[0]:sp[1]]], "rescaled")
            add([sp for sp in self.runs_with_prefix(digits) if "." not in self.disp[sp[0]:sp[1]]], "rescaled")
            add(self.scaled_matches(value, decimals), "rescaled")
        return out

    # -- phrases -------------------------------------------------------------

    def phrase_spans(self, words):
        """Every whole-word occurrence of the word sequence, as (start, end) in self.disp."""
        needle = " ".join(words)
        n, total = len(needle), len(self.search)
        spans = []
        i = self.search.find(needle)
        while i != -1 and len(spans) < MAX_SPANS:
            j = i + n
            if (i == 0 or self.search[i - 1] == " ") and (j == total or self.search[j] == " "):
                ti = bisect.bisect_left(self.offs, i)             # token index at offset i
                spans.append((self.starts[ti], self.ends[ti + len(words) - 1]))
            i = self.search.find(needle, i + 1)
        return spans

    # -- scoring -------------------------------------------------------------

    def window_score(self, s, e, wanted):
        """How many of the entry's distinctive words sit within ±CONTEXT chars of [s, e)?
        Each distinct stem counts once, weighted by its IDF."""
        lo = bisect.bisect_left(self.starts, max(0, s - CONTEXT))
        hi = bisect.bisect_right(self.starts, e + CONTEXT)
        seen = set()
        for i in range(lo, hi):
            sid = self.sids[i]
            if sid in wanted:
                seen.add(sid)
        return sum(IDF[sid] for sid in seen)

    def best_span(self, spans, wanted):
        """Of several occurrences, the one whose neighbourhood best matches the entry.
        Returns (score, start, end); ties go to the earliest occurrence."""
        best = None
        for s, e in spans[:MAX_SPANS]:
            score = self.window_score(s, e, wanted)
            if best is None or score > best[0]:
                best = (score, s, e)
        return best

    def excerpt(self, s, e):
        """±CONTEXT characters around [s, e), cut on word boundaries, match wrapped in «…»."""
        disp = self.disp
        left, right = max(0, s - CONTEXT), min(len(disp), e + CONTEXT)
        if left > 0:
            sp = disp.find(" ", left, s)
            if sp != -1:
                left = sp + 1
        if right < len(disp):
            sp = disp.rfind(" ", e, right)
            if sp != -1:
                right = sp
        text = disp[left:s] + "«" + disp[s:e] + "»" + disp[e:right]
        return ("…" if left > 0 else "") + text + ("…" if right < len(disp) else "")


# ---------------------------------------------------------------------------
# 4. Locating one entry inside its document
# ---------------------------------------------------------------------------

STRICTNESS = {"exact": 0, "rounded": 1, "rescaled": 2}   # tie-break: stricter match first
LOOSE_PENALTY = {"exact": 0.0, "rounded": 0.5, "rescaled": 0.5}

# Dates written into a figure ("filed 08-14-2026", "as of 2026-06-30") are not figures;
# their fragments ("08", "14", "30") would match almost anything. Stripped before numbers_in.
DATE = re.compile(r"\b\d{1,2}-\d{1,2}-\d{4}\b|\b\d{4}[-./]\d{2}[-./]\d{2}\b")


def figure_numbers(*fields):
    """verify_graph.numbers_in, minus date fragments and leading-zero tokens ("06")."""
    cleaned = [DATE.sub(" ", f) if isinstance(f, str) else f for f in fields]
    return [n for n in numbers_in(*cleaned) if not (n.startswith("0") and not n.startswith("0."))]


def specificity(token):
    """How much a matched document token proves on its own: "48" could be anything (0),
    "3,145" is hard to hit by accident (2), "150,323" harder still (3)."""
    digits = sum(ch.isdigit() for ch in token)
    return 0.0 if digits <= 2 else 1.0 if digits == 3 else 2.0 if digits == 4 else 3.0


def find_by_numbers(index, numbers, wanted, min_score=0.0):
    """Best occurrence of any of the figure's numbers -> (start, end) or None.

    Each candidate scores  neighbourhood (IDF of the entry's words within ±CONTEXT)
                         + specificity of the matched token  - a small penalty for a
    rounded / rescaled match.  Highest total wins; ties go to the stricter match kind,
    then the number's order in the figure (the first is usually the headline one), then
    the earliest position. `min_score` > 0 demands at least one distinctive signal word
    nearby — used only for numbers taken from the signal text itself, which are weaker."""
    candidates = [index.number_candidates(n) for n in numbers]
    # Sorted start positions per number (exact matches and loose ones apart), so "does
    # another figure number sit in this window?" is a bisect. A passage holding several of
    # the figure's numbers ("$4.2B, up 21%") beats a lone "21%" somewhere else (a tax rate).
    exact_starts = [sorted(s for s, _e, how in cands if how == "exact") for cands in candidates]
    loose_starts = [sorted(s for s, _e, how in cands if how != "exact") for cands in candidates]

    def within(sorted_starts, s, e):
        k = bisect.bisect_left(sorted_starts, s - CONTEXT)
        return k < len(sorted_starts) and sorted_starts[k] <= e + CONTEXT

    def companions(i, s, e):
        """+1 per other figure number matched exactly inside the window, +0.5 if only loosely."""
        bonus = 0.0
        for j in range(len(candidates)):
            if j == i:
                continue
            if within(exact_starts[j], s, e):
                bonus += 1.0
            elif within(loose_starts[j], s, e):
                bonus += 0.5
        return bonus

    best = None
    for order, number in enumerate(numbers):
        for s, e, how in candidates[order]:
            nearby = index.window_score(s, e, wanted)
            if nearby < min_score:
                continue
            # An exact/rounded match is only as specific as the weaker of the two tokens
            # ("179.0" matched as the page number "179" is a 3-digit match); a rescaled
            # match is as specific as the raw amount it landed on ("150,323").
            token = index.disp[s:e]
            spec = specificity(token) if how == "rescaled" else min(specificity(number), specificity(token))
            total = nearby + spec + companions(order, s, e) - LOOSE_PENALTY[how]
            candidate = (-total, STRICTNESS[how], order, s, e)
            if best is None or candidate < best:
                best = candidate
    return (best[3], best[4]) if best else None


def phrase_candidates(tokens, sizes, min_content):
    """Every run of `sizes` consecutive signal words with at least `min_content` content
    words, most distinctive first (score = summed IDF of its distinct content words)."""
    candidates = []
    for size in sizes:
        for k in range(len(tokens) - size + 1):
            window = tokens[k:k + size]
            content = {w for w in window if is_content(w)}
            if len(content) < min_content:
                continue
            score = sum(weight(w) for w in content)
            candidates.append((-score, k, -size, window))
    candidates.sort()
    return candidates


def find_by_wording(index, tokens, wanted, skip=frozenset()):
    """Locate the signal's wording -> (start, end, via) or None.

    Ladder: 4-6 word phrases, then 2-3 word phrases (each needing 2+ content words and a
    weight of at least 1.0, i.e. one word found in under ~17% of documents or two in under
    ~30%), then a single rare word (weight >= 0.75, under ~22% of documents) with another
    signal word within the same ±CONTEXT window. The first rung that yields a hit wins.
    Words in `skip` (the filer's own name) never serve as the single-word anchor."""
    for sizes, min_content in (((6, 5, 4), 2), ((3, 2), 2)):
        for neg_score, _k, _neg_size, window in phrase_candidates(tokens, sizes, min_content):
            if -neg_score < 1.0:
                break                                    # sorted: nothing better follows
            if not all(w in index.words for w in window):
                continue                                 # cheap pre-check before str.find
            spans = index.phrase_spans(window)
            if spans:
                _score, s, e = index.best_span(spans, wanted)
                return s, e, "phrase"

    rare = sorted({w for w in tokens if is_content(w) and w not in skip}, key=lambda w: (-weight(w), w))
    for w in rare[:8]:
        if weight(w) < 0.75 or w not in index.words:
            continue
        others = wanted - {STEM_ID.get(stem_of(w))}
        best = None
        for s, e in index.phrase_spans([w]):
            score = index.window_score(s, e, others)
            if score > 0 and (best is None or score > best[0]):
                best = (score, s, e)
        if best:
            return best[1], best[2], "words"
    return None


def find_counterparty(index, names, own, wanted):
    """Last rung: the passage where the document names the OTHER company on the edge
    (or the node the entry is about, when that is not the filer itself). This is
    verify_graph's PARTY check made visible: a Korean filing that lists "Infineon" among
    its customers backs "lists Infineon among disclosed customers" — no English wording of
    the signal will ever appear in it. Returns (start, end, "counterparty") or None."""
    for name in names:
        if not name:
            continue
        words = WORD.findall(name.lower())
        if not words or set(words) <= own:
            continue                                     # that is the filer's own name
        candidates = [words] + [WORD.findall(alias.lower()) for alias in KO_ALIASES.get(name, [])]
        first = words[0]
        if len(words) > 1 and len(first) >= 6 and weight(first) >= 0.75:
            candidates.append([first])                   # "Vistra Corp" -> "vistra"
        for cand in candidates:
            if not cand or not all(w in index.words for w in cand):
                continue
            spans = index.phrase_spans(cand)
            if spans:
                _score, s, e = index.best_span(spans, wanted)
                return s, e, "counterparty"
    return None


def locate(index, label, fields, extra_texts=()):
    """Find the passage for one entry.

    Returns (status, (start, end) | None, via | None, unmatched) where `unmatched` lists the
    figure/units/value numbers that occur nowhere in the document (verify_graph's
    numbers_missing) — empty when every number was found or there was none to check.

    label       the entry's source label (tells us which company the document is about)
    fields      the quarterly_data / contract dict (signal, figure, units, value ...)
    extra_texts other words worth having near the match (the company names on the edge)."""
    signal = fields.get("signal") or ""
    own = own_company_words(label)
    wanted = content_stems([signal, fields.get("figure"), fields.get("units"),
                            fields.get("value"), *extra_texts])
    wanted -= {STEM_ID.get(stem_of(w)) for w in own}
    numbers = figure_numbers(fields.get("figure"), fields.get("units"), fields.get("value"))
    unmatched = [n for n in numbers if not index.number_candidates(n)]
    tokens = WORD.findall(signal.lower())
    # Names worth locating when the wording itself cannot be: the edge's companies, and the
    # `counterparty` a folded "Customer X: …" entry carries (see types.ts QuarterlyData).
    parties = [*extra_texts, fields.get("counterparty") or ""]

    if numbers:
        hit = find_by_numbers(index, numbers, wanted)
        if hit:
            return "found", hit, "number", unmatched
        near = (find_by_wording(index, tokens, wanted, own)          # context for the reviewer
                or find_counterparty(index, parties, own, wanted))
        return "no_match", (near[0], near[1]) if near else None, near[2] if near else None, unmatched

    near = find_by_wording(index, tokens, wanted, own)
    if near:
        return "found", (near[0], near[1]), near[2], unmatched
    hit = find_by_numbers(index, figure_numbers(signal), wanted, min_score=1.0)
    if hit:
        return "found", hit, "number", unmatched
    near = find_counterparty(index, parties, own, wanted)
    if near:
        return "found", (near[0], near[1]), near[2], unmatched
    return "no_match", None, None, unmatched


# ---------------------------------------------------------------------------
# 5. Walk the graph
# ---------------------------------------------------------------------------

def hide_media_source(record, label, doc_path):
    """User rule 5 (2026-10-17): nothing of a news-interview transcript reaches the website. The site shows this
    record (web/src/components/Evidence.tsx: the excerpt box and the file path), so for a source from
    transcripts/media/ (media_pull.py; label "[Company] CNBC interview (MM-DD-YYYY)") the excerpt, the matched text
    and the path are blanked. The status stays, and the entry's own signal already carries its short quote and the
    video URL. Returns the record."""
    if is_media_source(label, doc_path):
        record.update({"doc": None, "excerpt": None, "matched": None})
    return record


def iter_entries(graph):
    """Yield (kind, company, target, label, fields, extra_texts) for every data point."""
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            yield "qd", node["id"], "", q.get("quarter") or "", q, (node["id"],)
    for edge in graph["edges"]:
        for c in edge.get("contracts", []):
            yield ("contract", edge["source"], edge["target"], c.get("source") or "", c,
                   (edge["source"], edge["target"]))


OPEN_INDEXES = 64     # documents kept indexed at once; entries come label by label, so a few dozen is plenty


def count_stems(doc):
    """DocIndex's word pass alone: gives every word its stem id (in the same order as
    DocIndex does) and counts the document once per stem in DF, without keeping an index."""
    disp = WS.sub(" ", body_of(doc.text)).strip()
    DF.update({sid_of(m.group().lower()) for m in WORD.finditer(disp)})


class IndexCache:
    """indexes[doc] -> that document's DocIndex, built on first use. Only the `size` most
    recently used stay in memory; an evicted one is simply rebuilt when needed again (the
    same document always gives the same index, because DF and the stem ids are fixed by then)."""

    def __init__(self, size):
        self.size = size
        self.open = {}                     # dicts keep insertion order: oldest use first

    def __getitem__(self, doc):
        index = self.open.pop(doc, None)
        if index is None:
            index = DocIndex(doc, count_df=False)
        self.open[doc] = index             # (re)inserted last = most recently used
        if len(self.open) > self.size:
            del self.open[next(iter(self.open))]
        return index


def build_evidence(graph=None, out_path=OUT_PATH, company=None, label=None):
    """Build the evidence map. Writes `out_path` unless a company/label filter is given
    (then the matching records are printed instead). Returns the records dict."""
    started = time.time()
    if graph is None:
        with open(GRAPH_PATH, encoding="utf-8") as f:
            graph = json.load(f)

    # Corpus: every document is counted up front so IDF covers the whole corpus, but only the
    # OPEN_INDEXES most recently used ones stay indexed. Indexing all of them at once peaked at
    # ~6.8 GB (400 MB of transcripts) and the nightly build was killed for low memory.
    STEM_ID.clear(), DF.clear(), IDF.clear()
    by_label, all_docs = load_documents()
    filename_docs = list_documents()
    for doc in all_docs:
        count_stems(doc)
    indexes = IndexCache(OPEN_INDEXES)
    n_docs = len(all_docs)
    # Weight = IDF minus a floor of 0.75: a word must occur in fewer than ~half the documents
    # before it counts at all. Without the floor, a long signal full of ordinary finance words
    # ("core", "diluted", "margin", "cash", "flow") lights up every guidance paragraph.
    IDF.update({sid: max(0.0, math.log((n_docs + 1) / (df + 1)) - 0.75) for sid, df in DF.items()})

    records = {}
    stats, via_stats = Counter(), Counter()
    no_match_by_label, total_by_label = Counter(), Counter()
    resolve_cache = {}
    n_entries = 0

    for kind, company_id, target, lab, fields, extra in iter_entries(graph):
        if company and company.lower() not in (company_id + " " + target).lower():
            continue
        if label and label != lab:
            continue
        n_entries += 1
        key = entry_key(kind, company_id, target, lab, fields.get("signal") or "")
        if key in records:
            continue                     # same data point stored in two chain files
        # Older supply_contracts blocks still carry the Korean header label ("… DART 공급계약
        # (08-20-2026)") while the graph uses the English one. Exact header first, then
        # verify_graph's resolver (which would otherwise loosely land on the 정기보고서).
        doc = by_label.get(lab.replace("DART supply contract", "DART 공급계약")) \
            or resolve_label(lab, by_label, all_docs, filename_docs, resolve_cache)
        if doc is None:
            record = {"doc": None, "excerpt": None, "matched": None, "status": "no_source", "via": None}
        else:
            index = indexes[doc]
            status, span, via, unmatched = locate(index, lab, fields, extra)
            if status != "found":
                # A filing saved as companion files (edgar_pull's _customers / _supplychain pair) declares
                # the same label in each header: the first companion that holds the entry wins. Only files
                # that declare the label are tried, never a loose filename / event match.
                for other in resolve_label_docs(lab, by_label, all_docs, filename_docs, resolve_cache):
                    if other is doc or lab not in other.labels:
                        continue
                    result = locate(indexes[other], lab, fields, extra)
                    if result[0] == "found":
                        doc, index = other, indexes[other]
                        status, span, via, unmatched = result
                        break
            record = {"doc": index.path, "excerpt": None, "matched": None, "status": status, "via": via}
            if span:
                record["excerpt"] = index.excerpt(*span)
                record["matched"] = index.disp[span[0]:span[1]]
            if unmatched:
                record["unmatched"] = unmatched      # numbers the document does not contain
            hide_media_source(record, lab, index.path)   # a news interview: no excerpt, no path on the site
        records[key] = record
        stats[record["status"]] += 1
        via_stats[record["via"]] += 1
        total_by_label[lab] += 1
        if record["status"] == "no_match":
            no_match_by_label[lab] += 1
        if company or label:
            who = company_id + (" -> " + target if target else "")
            print(f"[{record['status']}] {who} | {lab} | via={record['via']}")
            print(f"    signal : {(fields.get('signal') or '')[:160]}")
            print(f"    figure : {fields.get('figure') or fields.get('value') or ''}")
            print(f"    doc    : {record['doc']}")
            if record.get("unmatched"):
                print(f"    numbers not in source: {record['unmatched']}")
            if record["excerpt"]:
                print(f"    excerpt: {record['excerpt']}")
            print()

    if company or label:
        print(f"{n_entries} entries, {len(records)} unique keys: {dict(stats)}")
        return records

    # Write compactly; if the file is too big, drop the (optional) context excerpts of
    # no_match entries — "found" excerpts are the product, no_match ones are a courtesy.
    out = {"generated": date.today().isoformat(), "entries": records}
    data = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    trimmed = False
    if len(data) > SIZE_LIMIT:
        for record in records.values():
            if record["status"] == "no_match":
                record["excerpt"] = None
        data = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        trimmed = True
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    print(f"\nevidence.py — {n_entries} entries ({len(records)} unique keys) from "
          f"{len(graph['nodes'])} nodes / {len(graph['edges'])} edges; {n_docs} documents "
          f"indexed; {time.time() - started:.1f}s")
    for status in ("found", "no_match", "no_source"):
        print(f"  {status:10s} {stats.get(status, 0):5d}")
    print(f"  found by   : number {via_stats.get('number', 0)}, phrase {via_stats.get('phrase', 0)}, "
          f"words {via_stats.get('words', 0)}, counterparty {via_stats.get('counterparty', 0)}")
    print(f"  wrote {out_path} ({len(data) / 1e6:.2f} MB)" + ("  [no_match excerpts dropped to fit]" if trimmed else ""))
    if no_match_by_label:
        print("  labels with the most no_match entries (no_match / entries):")
        for lab, n in no_match_by_label.most_common(10):
            print(f"    {n:3d} / {total_by_label[lab]:3d}  {lab}")
    return records


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # labels and excerpts are not ASCII
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", help="print entries touching this company (substring); no file written")
    ap.add_argument("--label", help="print entries with exactly this source label; no file written")
    args = ap.parse_args()
    build_evidence(company=args.company, label=args.label)


if __name__ == "__main__":
    main()
