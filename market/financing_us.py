"""US financing events from SEC EDGAR, for the graph's companies listed on US exchanges.

What counts as a financing event (user, 2026-10-17; these are NOT supply-chain signals, so nothing here
touches quarterly_data, chains/, patches/ or derive.py):
  - 8-K / 8-K/A with Item 2.03 (new direct financial obligation / off-balance-sheet obligation)
    or Item 3.02 (unregistered sale of equity securities),
  - 8-K with Item 1.01 only when that item is about a credit agreement, indenture, notes, loan or facility,
  - prospectus supplements 424B2 / 424B3 / 424B5 that offer notes, convertible notes or shares
    (preliminary "subject to completion" versions and resale prospectuses for selling holders are skipped),
  - 6-K (foreign private issuers such as Nebius file these instead of 8-K) when the report is about
    notes, a loan / credit facility or a share offering; the press-release exhibit is read for the numbers.

How it works:
  1. ticker -> CIK from https://www.sec.gov/files/company_tickers.json (cached weekly in market/cache/).
  2. For each CIK, the submissions JSON (https://data.sec.gov/submissions/CIK##########.json) lists the
     filings; we keep the last 365 days of the forms above.
  3. Each new filing's document is fetched once (SEC pacing: at most 4 requests per second, descriptive
     User-Agent from market.common.sec_headers()) and read with plain regular expressions (no model tokens):
     a short title, type, amount + currency, and coupon / maturity / conversion price into "detail".
  4. Rows go to market/history/financing_us.jsonl (ADD-only, key = accession + type + currency + company), and
     market/financing.py rebuilds graph/financing/ (one file per company) from every market/history/financing_*.jsonl.

Daily mode only looks at filings since the last run (a few days of overlap; already-processed accession
numbers are remembered in market/cache/financing_us_state.json, so nothing is fetched twice). A filing can give
two rows when it issues two instruments (e.g. CoreWeave's senior notes + convertible notes on one 8-K).
To re-read every filing with an improved parser: delete the state file and run --backfill (history is
ADD-only, so a row whose type changed is added next to the old one; clean the old one by hand if needed).

CLI:  python -m market.financing_us [--backfill] [--build-only]
"""
import argparse
import datetime as dt
import json
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from market import financing
from market.common import (ROOT, append_history, load_env, read_json, sec_headers, today, universe,
                           write_json)

DATASET = "financing_us"
SOURCE = "SEC EDGAR"
WINDOW_DAYS = 365
OVERLAP_DAYS = 7                      # daily mode re-checks this many days before the last run (late filings)
US_EXCHANGES = {"NASDAQ", "NYSE", "NYSE American", "NYSE Arca", "OTC"}

CACHE = ROOT / "market" / "cache"
TICKER_CACHE = CACHE / "sec_company_tickers.json"     # {"fetched": date, "map": {ticker: cik}}
STATE_FILE = CACHE / "financing_us_state.json"         # {"last_run": date, "seen": {accession: filing date}}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

FORMS_8K = {"8-K", "8-K/A"}
FORMS_424 = {"424B2", "424B3", "424B5"}
FORMS_6K = {"6-K", "6-K/A"}

# ---------------------------------------------------------------------------------------------------------
# Polite SEC access
# ---------------------------------------------------------------------------------------------------------
MIN_GAP = 0.25                        # seconds between SEC requests = at most 4 per second (SEC allows 10)
BREAKER = 5                           # this many filers failing one after another = SEC unreachable: stop
_last_request = [0.0]
_stats = {"requests": 0}


def sec_get(url, max_bytes=None, retries=3):
    """GET an SEC URL with pacing and retries. Returns the body as text (or None on 404).
    max_bytes stops reading a long prospectus early: the cover page is all we need."""
    last_error = None
    for attempt in range(retries):
        wait = MIN_GAP - (time.time() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.time()
        _stats["requests"] += 1
        try:
            r = requests.get(url, headers=sec_headers(), timeout=60, stream=True)
            if r.status_code == 404:
                r.close()
                return None
            if r.status_code in (403, 429, 500, 502, 503, 504):
                r.close()
                last_error = RuntimeError(f"HTTP {r.status_code} for {url}")
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if max_bytes and size >= max_bytes:
                    break
            r.close()
            body = b"".join(chunks)
            if r.encoding and r.encoding.lower() not in ("iso-8859-1", "latin-1"):
                return body.decode(r.encoding, errors="replace")
            try:                                     # no charset header: most EDGAR documents are UTF-8
                return body.decode("utf-8")
            except UnicodeDecodeError:
                return body.decode("cp1252", errors="replace")
        except requests.RequestException as e:
            last_error = e
            time.sleep(2 * (attempt + 1))
    raise last_error


def html_to_text(html):
    """Plain text of an HTML filing, whitespace collapsed (non-breaking spaces become normal spaces)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ")
    text = text.replace("\xa0", " ").replace("​", " ")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------------------------------------
# Universe: graph node -> SEC CIK
# ---------------------------------------------------------------------------------------------------------
def ticker_map():
    """{TICKER: cik} from SEC's company_tickers.json, refreshed when the cached copy is a week old."""
    cached = read_json(TICKER_CACHE, {}) or {}
    fetched = cached.get("fetched")
    if fetched and (dt.date.fromisoformat(today()) - dt.date.fromisoformat(fetched)).days < 7:
        return cached["map"]
    try:
        data = json.loads(sec_get(TICKERS_URL))
        mapping = {v["ticker"].upper(): int(v["cik_str"]) for v in data.values()}
        write_json(TICKER_CACHE, {"fetched": today(), "source": TICKERS_URL, "map": mapping})
        return mapping
    except Exception as e:                          # keep the stale copy if SEC is unreachable
        if cached.get("map"):
            print(f"  [warn] company_tickers.json refresh failed ({e}); using cached copy from {fetched}")
            return cached["map"]
        raise


def us_companies():
    """{cik: [node ids]} for public graph companies on US exchanges whose ticker SEC knows."""
    mapping = ticker_map()
    out, missing = {}, []
    for node_id, info in universe().items():
        if info.get("status") != "public" or info.get("exchange") not in US_EXCHANGES:
            continue
        ticker = (info.get("ticker") or "").upper().replace(".", "-")
        cik = mapping.get(ticker)
        if not cik:
            missing.append(f"{node_id} ({ticker or 'no ticker'})")
            continue
        out.setdefault(cik, []).append(node_id)
    if missing:
        print(f"  {len(missing)} US-listed nodes have no SEC CIK (e.g. unsponsored ADRs): "
              + ", ".join(missing[:12]) + (" ..." if len(missing) > 12 else ""))
    return out


# ---------------------------------------------------------------------------------------------------------
# Filing lists
# ---------------------------------------------------------------------------------------------------------
def _rows_from_block(block):
    """Turn the column-oriented 'filings' block of a submissions JSON into a list of dicts."""
    out = []
    for i in range(len(block.get("form", []))):
        out.append({
            "form": block["form"][i],
            "filed": block["filingDate"][i],
            "accession": block["accessionNumber"][i],
            "doc": block["primaryDocument"][i],
            "items": block.get("items", [""] * (i + 1))[i] or "",
        })
    return out


def list_filings(cik, since):
    """Filings of the forms we read, filed on or after `since` (YYYY-MM-DD), newest first."""
    sub = json.loads(sec_get(SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json")))
    filings = sub.get("filings", {})
    rows = _rows_from_block(filings.get("recent", {}))
    # Busy filers (hundreds of Form 4s) can push part of the year into older pages.
    oldest = min((r["filed"] for r in rows), default="9999")
    if oldest > since:
        for extra in filings.get("files", []):
            if extra.get("filingTo", "") >= since:
                rows += _rows_from_block(json.loads(sec_get(SUBMISSIONS_URL.format(name=extra["name"]))))
    keep = [r for r in rows if r["filed"] >= since and r["form"] in FORMS_8K | FORMS_424 | FORMS_6K]
    return sorted(keep, key=lambda r: r["filed"], reverse=True)


def doc_url(cik, accession, doc):
    return ARCHIVE_URL.format(cik=cik, acc=accession.replace("-", ""), doc=doc)


# ---------------------------------------------------------------------------------------------------------
# Reading a filing: which part to read, type, amount, detail, title
# ---------------------------------------------------------------------------------------------------------
# An 8-K item heading: "Item 2.03 Creation of ..." / "ITEM 2.03. CREATION OF ..." (a reference such as
# "under Item 2.03 of this report" is followed by a lowercase word, so it does not split the text).
ITEM_HEADING = re.compile(r"\bITEM\s*(\d\.\d{2})\s*[.:\-]?\s*", re.I)
REFERENCE_WORDS = {"this", "under", "in", "to", "of", "see", "and", "by", "into", "with", "per", "such", "above",
                   "below", "the", "pursuant", "or", "item", "items"}


def item_sections(text):
    """{item number: section text} of an 8-K. When a number appears twice (a table of contents lists the
    headings with page numbers), the longer section wins."""
    marks = []
    for m in ITEM_HEADING.finditer(text):
        previous = text[max(0, m.start() - 12):m.start()].lower().split()
        if previous and previous[-1] in REFERENCE_WORDS:
            continue                                 # "... incorporated by reference into this Item 1.01. The ..."
        if text[m.end():m.end() + 1].isupper():     # a heading's title starts with a capital letter
            marks.append((m.start(), m.end(), m.group(1)))
    sections = {}
    for i, (start, end, number) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[end:stop].strip()
        if len(body) > 40 and len(body) > len(sections.get(number, "")):
            sections[number] = body
    return sections


# Words that make an Item 1.01 (or a 6-K cover) about financing. Checked near the start only, so a customer
# contract that merely mentions "the Company's credit agreement" in passing is not picked up.
FINANCING_WORDS = re.compile(
    r"credit agreement|credit facilit|loan agreement|loan facilit|term loan|revolving|indenture|"
    r"senior (?:secured |unsecured )?notes|secured notes|convertible (?:senior )?notes|exchangeable notes|"
    r"notes due|note purchase agreement|delayed[- ]draw|financing agreement|bridge (?:loan|facilit)|"
    r"debentures|receivables (?:purchase|financing|securitization)|warehouse facilit|sale[- ]leaseback|"
    r"securitization|asset[- ]backed|loan and security agreement|commitment letter|private placement|"
    r"at[- ]the[- ]market|equity distribution agreement|sales agreement|underwriting agreement|debt (?:facilit|financing)|"
    r"offering of .{0,60}(?:notes|shares|stock)|pricing of .{0,60}(?:notes|shares|stock)|"
    r"(?:will )?invest \$[\d.,]+ (?:million|billion) in", re.I)

# A 6-K about results, meetings, buybacks or a not-yet-priced offering is not a financing event.
NOT_FINANCING_6K = re.compile(
    r"transaction in own shares|share (?:buy ?back|repurchase)|announcing the launch|announces? (?:the )?launch|"
    r"proposed (?:private |public )?offering|intention to offer|proposes to offer|financial results|"
    r"announces? (?:record |strong )?(?:\w+ )?(?:quarter|annual|full[- ]year|interim) (?:\w+ )?results", re.I)

# A prospectus supplement that only adds sales agents / restates an earlier supplement is not a new deal.
SUPPLEMENT_ONLY = re.compile(
    r"supersedes and replaces the prospectus supplement|supplements the prospectus and (?:the )?prospectus supplement|"
    r"amends and supplements (?:the|our) (?:prospectus supplement|information)|is being filed to (?:reflect|add|update|amend)",
    re.I)


def select_focus(text, form, items):
    """The part of the filing that describes the deal, or None when the filing is not a financing event."""
    if form in FORMS_8K:
        sections = item_sections(text)
        item_set = set(items.split(",")) if items else set()
        lead = sections.get("1.01", "")[:900]
        # Item 1.01 only: keep it only when the agreement itself is a financing agreement.
        if not ({"2.03", "3.02"} & item_set) and not FINANCING_WORDS.search(lead):
            return None
        # An underwriting / ATM sales agreement belongs to a registered offering whose 424B prospectus
        # supplement is read separately (it has the final numbers), so the 8-K would only repeat it.
        if re.search(r"underwriting agreement|equity distribution agreement|sales agreement|"
                     r"distribution agreement|at[- ]the[- ]market", lead, re.I):
            return None
        # A Rule 144A notes deal files a pricing 8-K (Item 1.01 purchase agreement with the initial purchasers)
        # and, about a week later, the closing 8-K with Item 2.03; the closing one is read.
        if not ({"2.03", "3.02"} & item_set) and re.search(r"\bpurchase agreement\b", lead, re.I) and \
                re.search(r"initial purchasers?", lead, re.I):
            return None
        # Money going OUT is not the company's financing: a share buyback, or the company investing in another
        # company (Sandisk buying Nanya shares is Nanya's financing, not Sandisk's).
        if re.search(r"share repurchase|stock repurchase|repurchase program|accelerated share|"
                     r"\b(?:company|we)\b[^.]{0,60}\b(?:make|made) an? (?:strategic )?(?:equity )?investment in\b|"
                     r"\b(?:company|we)\b[^.]{0,40}agreed to (?:purchase|acquire|subscribe for) (?:approximately )?"
                     r"[\d,.]+ (?:million |billion )?shares of", lead[:700], re.I):
            return None
        wanted = [n for n in ("1.01", "2.03", "3.02") if n in sections]
        if not wanted:
            return None                              # item headings not found: better nothing than a guess
        focus = " ".join(sections[n][:9000] for n in wanted)
        if not money_mentions(focus) and "8.01" in sections:   # numbers sometimes sit in the 8.01 summary
            focus += " " + sections["8.01"][:3000]
        return focus
    if form in FORMS_424:
        head = text[:4000]
        if re.search(r"subject to completion|preliminary prospectus supplement", head, re.I):
            return None                              # the final version follows a few days later
        if SUPPLEMENT_ONLY.search(head[:2500]):
            return None
        if re.search(r"selling (?:stock|share|security|unit|note)holders?|proxy statement|information statement|"
                     r"exchange offer|consent solicitation|dividend reinvestment|employee stock purchase|\bresale\b",
                     head, re.I):
            return None                              # not money raised by the company
        if form == "424B3" and re.search(r"\bmerger\b|business combination|stockholders?:|shareholders?:", head, re.I):
            return None                              # a merger prospectus
        return text[:12000]
    # 6-K: the cover's exhibit description must be about financing; the numbers come from the exhibit.
    cover, _, exhibit = text.partition(" @@EXHIBIT@@ ")
    if NOT_FINANCING_6K.search(cover[:6000]) or not FINANCING_WORDS.search(cover[:6000]):
        return None
    if exhibit and NOT_FINANCING_6K.search(exhibit[:600]):
        return None
    return (exhibit[:5000] if exhibit else cover[:6000])


# Type rules: the instrument named EARLIEST in the deal text wins ("Convertible Senior Notes" starts with
# "Convertible", so a convertible is not mistaken for plain notes).
TYPE_RULES = [
    ("convertible", r"mandatory convertible|convertible (?:senior |secured |unsecured |subordinated |exchangeable )*"
                    r"(?:notes?|debentures|bonds|preferred)|exchangeable (?:senior )*notes"),
    ("abs", r"asset[- ]backed (?:notes|securities|financing|facilit|loan)|securitization|"
            r"receivables (?:purchase|financing|securitization) (?:agreement|facilit|program)"),
    ("lease_financing", r"sale[- ](?:and[- ])?leaseback|finance lease|lease financing|equipment lease"),
    ("credit_facility", r"credit agreement|credit facilit|revolving (?:credit|loan|facilit)|term loan|loan agreement|"
                        r"loan facilit|delayed[- ]draw|bridge (?:loan|facilit)|loan and security agreement|"
                        r"financing agreements?|debt facilit|secured (?:debt )?facilit|commitment letter|"
                        r"warehouse facilit|letter of credit facilit"),
    ("debt", r"senior (?:secured |unsecured |subordinated )?notes|secured notes|subordinated notes|floating rate notes|"
             r"\d\s?% notes|notes due|debentures|\bbonds\b|commercial paper|note purchase agreement"),
    ("equity", r"common stock|ordinary shares|class [ab] (?:common|ordinary)|american depositary|depositary shares|"
               r"preferred stock|at[- ]the[- ]market|equity distribution agreement|sales agreement|pre-funded warrants|"
               r"registered direct|(?:will )?invest \$[\d.,]+ (?:million|billion) in|equity investment"),
]
FALLBACK_RULES = [("debt", r"\bnotes\b"), ("credit_facility", r"\bloans?\b|\bfacility\b"), ("equity", r"\bshares\b")]


def cover_title(focus, form):
    """The part of the deal text that names the securities being offered: a prospectus' title block (everything
    before its first sentence, "We are offering ..."), else the first 1,500 characters. Sentences about a
    concurrent offering ("Concurrently with this offering ... Mandatory Convertible Preferred Stock") are removed,
    because they describe a different deal (user, 2026-10-17 verification: Supermicro's common-stock prospectus
    d41737d424b5.htm was typed 'convertible')."""
    head = focus[:1500]
    if form in FORMS_424:
        prose = re.search(r"\b(?:we|it) (?:are|is|have|has|may)\b|\bis offering\b", head, re.I)
        head = head[:prose.start()] if prose else head[:400]
    return " ".join(x for x in split_sentences(head) if not CONCURRENT.search(x))


def classify(focus, form=None):
    if re.search(r"mandatory convertible", cover_title(focus, form), re.I):
        return "convertible"
    for rules in (TYPE_RULES, FALLBACK_RULES):
        best = None
        for kind, pattern in rules:
            m = re.search(pattern, focus, re.I)
            if m and (best is None or m.start() < best[1]):
                best = (kind, m.start())
        if best:
            return best[0]
    return "other"


# --- money -----------------------------------------------------------------------------------------------
CURRENCY = {"US$": "USD", "U.S.$": "USD", "USD": "USD", "$": "USD", "C$": "CAD", "CAD": "CAD", "A$": "AUD",
            "AUD": "AUD", "NT$": "TWD", "TWD": "TWD", "HK$": "HKD", "HKD": "HKD", "S$": "SGD", "SGD": "SGD",
            "RMB": "CNY", "CNY": "CNY", "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "¥": "JPY", "JPY": "JPY",
            "CHF": "CHF", "₩": "KRW", "KRW": "KRW"}
# Longer prefixes first, so "NT$" is not read as "$".
CUR_PREFIX = (r"(?:US\$|U\.S\.\s?\$|USD\s?|C\$|CAD\s?|A\$|AUD\s?|NT\$|TWD\s?|HK\$|HKD\s?|S\$|SGD\s?|RMB\s?|CNY\s?|"
              r"€|EUR\s?|£|GBP\s?|¥|JPY\s?|CHF\s?|₩|KRW\s?|\$)")
MONEY_CORE = (CUR_PREFIX + r"\s?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
              r"(?:\s*(?:billion|million|thousand|bn\b|mm\b|m\b|b\b))?")
MONEY = re.compile(
    r"(?P<cur>" + CUR_PREFIX + r")\s?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<unit>billion|million|thousand|bn\b|mm\b|m\b|b\b))?", re.I)
UNIT = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3}


def sentence_before(text, pos, span=300):
    """The part of the sentence that comes before `pos` (at most `span` characters back)."""
    return re.split(r"\.\s+(?=[A-Z(\"])", text[max(0, pos - span):pos])[-1]


# A sentence ends at ". " + capital letter, but not after an abbreviation inside a name ("Berkshire Hathaway
# Inc. (", "Co. LLC", "U.S. dollars", "No. 2").
SENTENCE_END = re.compile(r"(?<!\bInc)(?<!\bCo)(?<!\bCorp)(?<!\bLtd)(?<!\bNo)(?<!\bU\.S)(?<!\bN\.A)(?<!\bS\.A)"
                          r"\.\s+(?=[A-Z(\"])")
# A money amount in such a sentence belongs to another deal than the one this prospectus offers.
CONCURRENT = re.compile(r"concurrent|private placement|separate prospectus supplement|"
                        r"pursuant to a separate|depositary shares offering", re.I)


def split_sentences(text):
    return SENTENCE_END.split(text)


def own_deal(text):
    """`text` without its sentences about concurrent offerings (an ATM program or preferred offering launched
    the same day is a different deal from the one this filing offers)."""
    return " ".join(x for x in split_sentences(text) if not CONCURRENT.search(x))


def whole_sentence(text, pos, span=900):
    """The whole sentence around `pos` (at most `span` characters each way), abbreviation-aware."""
    start, end = max(0, pos - span), min(len(text), pos + span)
    before = split_sentences(text[start:pos])[-1]
    after = split_sentences(text[pos:end])[0]
    return before + after


def money_mentions(text):
    """Every money amount >= 1 million in the text: [(position, value, currency, matched text)]."""
    found = []
    for m in MONEY.finditer(text):
        value = float(m.group("num").replace(",", "")) * UNIT.get((m.group("unit") or "").lower(), 1)
        if value < 1e6:
            continue
        cur = CURRENCY.get(re.sub(r"\s", "", m.group("cur")).upper(), "USD")
        found.append((m.start(), value, cur, m.group(0)))
    return found


GOOD_CONTEXT = [                                     # (pattern, points); the best-matching pattern counts
    (r"total (?:aggregate )?(?:original )?principal amount", 12), (r"aggregate gross proceeds", 11),
    (r"aggregate (?:original )?principal amount", 10), (r"price to (?:the )?public", 9),
    (r"(?:public |registered direct |total )?offering price", 9), (r"principal amount", 7),
    (r"aggregate (?:commitments?|amount of up to|offering price|purchase price)|borrowing capacity|"
     r"maximum (?:principal|aggregate)|in an aggregate (?:principal )?amount|total commitments?|commitments? of|"
     r"gross proceeds|will invest", 7),
    (r"\bup to\b|offering|notes|shares|financing", 2),
]
AFTER_FACILITY = re.compile(r"^\W{0,3}(?:[a-z\-]+\s+){0,4}?(?:credit facilit|term loan|revolving|loan facilit|"
                            r"facility|delayed draw|bridge|debt facilit|financing)", re.I)
BAD_RIGHT_BEFORE = re.compile(r"conversion price|exercise price|purchase price|liquidation preference|par value|"
                              r"price per|underwriting discounts?|before expenses|net proceeds", re.I)   # last 40 chars
BAD_SENTENCE = [                                     # anywhere earlier in the same sentence
    (r"concurrent|separate (?:prospectus supplement|offering|private placement)", -6),
    (r"existing|outstanding|repurchase|redeem|redemption|repay|refinanc|retire|prepay|capped call|"
     r"market capitali[sz]ation|revenue|backlog|contract value", -5),
    (r"sublimit|letter of credit|swingline|capped at|availability|accordion|incremental|increase|increments?|"
     r"option to purchase|additional|over-?allotment|of which|allocated", -4),
]
BAD_AFTER = re.compile(r"^\W{0,3}(?:per (?:share|ads|depositary)|letter of credit|sublimit|swingline|"
                       r"of (?:the )?net proceeds|of (?:revenue|backlog))", re.I)


def best_amount(text, exclude=(), cover=False):
    """The most likely headline amount of the deal in `text`: (value, currency) or (None, None).
    `exclude` = positions already used (e.g. by note tranches found separately).
    `cover` = text starts with a prospectus cover, whose title block ("$2,999,999,890 Celestica Inc. Common
    Shares") comes before the first sentence ("We are offering ...") and names the deal size."""
    best, best_score = None, None
    prose = re.search(r"\b(?:we|it) (?:are|is|have|has|may)\b|\bis offering\b", text, re.I) if cover else None
    title_block_end = prose.start() if prose else 0
    for pos, value, cur, raw in money_mentions(text):
        if pos in exclude:
            continue
        before = text[max(0, pos - 90):pos]
        before_sentence = sentence_before(text, pos).lower()
        after = text[pos + len(raw):pos + len(raw) + 60].lower()
        score = 0
        for pattern, points in GOOD_CONTEXT:           # "... principal amount of $X" or "$X aggregate principal ..."
            if re.search(pattern, before[-80:], re.I) or re.match(r"\W{0,3}(?:in\s+)?(?:" + pattern + ")", after):
                score = points
                break
        if AFTER_FACILITY.search(after):
            score = max(score, 6)
        if BAD_RIGHT_BEFORE.search(before[-40:]):
            score -= 8
        for pattern, points in BAD_SENTENCE:
            if re.search(pattern, before_sentence):
                score += points
        if BAD_AFTER.search(after):
            score -= 6
        if re.search(r"\btotal\b", before[-50:], re.I):
            score += 1                               # "Total offering price $X" beats a partial amount
        if before_sentence.rstrip().endswith("including"):
            score -= 3
        if pos < title_block_end:
            score += 8
        if cover and CONCURRENT.search(whole_sentence(text, pos)):
            score -= 20                              # "concurrently ... Private Placement ... gross proceeds of $10B"
        score -= pos / 4000                          # earlier mentions are usually the headline
        if best_score is None or score > best_score:
            best, best_score = (value, cur), score
    if best is None or best_score < 0:
        return None, None
    return best


# --- note tranches ---------------------------------------------------------------------------------------
NOTE_CORE = (r"(?:\d{1,2}(?:\.\d{1,4})?\s?%|floating[- ]rate)\s+(?:[a-z\-]+\s+){0,6}?(?:notes?|debentures|bonds)"
             r"\s+due\s+(?:[a-z]+\s+(?:\d{1,2},\s+)?)?20\d\d")
OFFERED = re.compile(
    rf"(?P<money>{MONEY_CORE})\s+(?:in\s+)?(?:(?:aggregate|original|initial)\s+)*(?:principal\s+amount\s+of\s+|of\s+)?"
    rf"(?:(?:its|our|their|the|[\w.\-]+(?:\s[\w.\-]+){{0,3}}'s)\s+)?(?:(?:newly\s+issued|new|additional|[a-z]+-denominated)\s+)*"
    rf"(?P<name>{NOTE_CORE})", re.I)
# Same, when the 8-K names the tranche without its coupon: "$500,000,000 aggregate principal amount of senior
# notes due September 15, 2029" (the coupon is in the prospectus). "principal amount of" is required here.
OFFERED_PLAIN = re.compile(
    rf"(?P<money>{MONEY_CORE})\s+(?:in\s+)?(?:(?:aggregate|original|initial)\s+)*principal\s+amount\s+of\s+"
    rf"(?:(?:its|our|their|the|[\w.\-]+(?:\s[\w.\-]+){{0,3}}'s)\s+)?(?:(?:newly\s+issued|new|additional)\s+)*"
    rf"(?P<name>(?:(?:senior|secured|unsecured|subordinated|convertible|exchangeable)\s+){{1,4}}(?:notes?|debentures)"
    rf"\s+due\s+(?:[a-z]+\s+(?:\d{{1,2}},\s+)?)?20\d\d)", re.I)
# Name first: "3.850% notes due 2028 in the principal amount of $1,500.0 million" (Eaton's style).
NAME_FIRST = re.compile(
    rf"(?P<name>{NOTE_CORE})\s+(?:\([^)]{{0,60}}\)\s+)?in (?:the|an) (?:aggregate )?(?:original )?principal amount of\s+"
    rf"(?P<money>{MONEY_CORE})", re.I)
NOT_NEW = re.compile(r"existing|outstanding|redeem|repurchase|retire|in exchange for|exchange of|guarantee|"
                     r"maturity date of|refinanc|repay|concurrent|separate (?:offering|prospectus|private)|"
                     r"not part of this offering", re.I)


def offered_notes(text):
    """Note tranches the filing ISSUES: [{"pos","value","cur","name","convertible"}].
    A tranche named after "existing" / "outstanding" / "redeem" in the same sentence is somebody else's."""
    out, names = [], set()
    matches = list(OFFERED.finditer(text))
    for extra in (OFFERED_PLAIN, NAME_FIRST):
        taken = [(m.start(), m.end()) for m in matches]
        matches += [m for m in extra.finditer(text) if not any(a <= m.start() < b for a, b in taken)]
    for m in sorted(matches, key=lambda m: m.start()):
        sentence = sentence_before(text, m.start())
        if NOT_NEW.search(sentence):
            continue
        mention = money_mentions(m.group("money"))
        if not mention:
            continue
        name = tidy_name(m.group("name"))
        # One tranche = one coupon + maturity year (the cover says "Notes due 2029", the body "due May 1, 2029").
        coupon = re.match(r"(\d{1,2}(?:\.\d{1,4})?)\s?%", name)
        key = ((coupon.group(1).rstrip("0").rstrip(".") if coupon else "float" if "floating" in name.lower() else ""),
               name[-4:], bool(re.search(r"convertible|exchangeable", name, re.I)))
        if key in names:
            continue
        _, value, cur, _ = mention[0]
        # The same tranche written once with and once without its coupon ("$1B 5.300% Senior Notes due 2036" on
        # the cover, "$1B Senior Notes due 2036" in the text): keep one, preferring the name with the coupon.
        twin = next((t for t in out if t["key"][1:] == key[1:] and round(t["value"]) == round(value)
                     and "" in (t["key"][0], key[0])), None)
        if twin:
            if twin["key"][0] == "":
                twin.update(name=name, key=key)
            names.add(key)
            continue
        names.add(key)
        out.append({"pos": m.start("money"), "value": value, "cur": cur, "name": name, "key": key,
                    "convertible": key[2], "add_on": bool(re.search(r"\badditional\b", m.group(0), re.I))})
    return out


def tidy_name(name):
    """Collapse spaces; "5.200% NOTES DUE 2029" -> "5.200% Notes due 2029"."""
    name = re.sub(r"\s+", " ", name).strip()
    if name.isupper() or name == name.upper():
        name = " ".join(w if w[:1].isdigit() else ("due" if w == "DUE" else w.capitalize()) for w in name.split())
    return name


def short_money(value, cur="USD"):
    sign = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(cur, cur + " ")
    if value >= 999.5e6:
        return f"{sign}{value / 1e9:.2f}".rstrip("0").rstrip(".") + "B"
    return f"{sign}{value / 1e6:.1f}".rstrip("0").rstrip(".") + "M"


def extra_terms(focus, kind):
    """Interest margin, maturity, conversion terms, share count / price, when the deal text states them."""
    parts = []
    margin = re.search(r"\b(Term SOFR|Compounded SOFR|SOFR|EURIBOR|SONIA|LIBOR)\b(?:(?!\.\s)[^;]){0,90}?\bplus\s+"
                       r"(?:an?\s+(?:applicable\s+)?margin\s+(?:of|equal to)\s+|a spread of\s+)?(\d{1,2}(?:\.\d{1,3})?)\s?%",
                       focus, re.I) or re.search(r"\b(SOFR|EURIBOR|SONIA)\s?\+\s?(\d{1,2}(?:\.\d{1,3})?)\s?%", focus)
    if margin:
        parts.append(f"{margin.group(1)} + {margin.group(2)}%")
    if kind in ("credit_facility", "abs", "lease_financing", "other"):
        maturity = re.search(r"\bmatur(?:es|e|ity date (?:is|of [^.]{0,40}? is)|ing)\s+(?:on\s+)?"
                             r"((?:[A-Z][a-z]+ \d{1,2}, )?20\d\d)", focus)
        if maturity:
            parts.append(f"matures {maturity.group(1)}")
    conv = re.search(r"conversion price of approximately \$\s?([\d,]+(?:\.\d+)?)", focus, re.I)
    if conv and kind == "convertible":
        parts.append(f"conversion price ${conv.group(1)}/share")
    premium = re.search(r"premium of approximately (\d{1,3}(?:\.\d+)?)\s?%", focus, re.I)
    if premium and kind == "convertible":
        parts.append(f"{premium.group(1)}% conversion premium")
    if kind == "equity" and not re.search(r"at[- ]the[- ]market|equity distribution agreement|sales agreement",
                                          own_deal(focus[:3000]), re.I):
        shares = re.search(r"\b(\d{1,3}(?:,\d{3}){1,3})\s+(?:shares|ordinary shares|Class A|American Depositary|"
                           r"depositary shares)", focus, re.I)
        price = re.search(r"price (?:to the public )?of \$\s?(\d{1,4}(?:\.\d{1,4})?) per (?:share|ADS|depositary)",
                          focus, re.I)
        classes = offered_share_classes(focus)
        if classes:
            parts.append(f"{sum(n for n, _ in classes):,} shares (" +
                         " + ".join(f"{n:,} {name}" for n, name in classes) + ")")
        elif shares:
            parts.append(f"{shares.group(1)} shares")
        if price:
            parts.append(f"${price.group(1)}/share")
    return parts


FACILITY_KINDS = ["delayed draw term loan facility", "delayed draw term loan", "revolving credit facility",
                  "senior secured debt facility", "secured debt facility", "debt facility", "term loan facility",
                  "term loan", "bridge loan facility", "bridge facility", "bridge loan", "loan and security agreement",
                  "receivables purchase agreement", "letter of credit facility", "credit facility", "loan agreement",
                  "credit agreement", "financing agreements", "financing agreement", "loan facility"]


def facility_name(focus):
    head = focus[:4000].lower()
    for name in FACILITY_KINDS:
        if name in head:
            return name
    return "credit facility"


def is_amendment(focus):
    return bool(re.search(r"amendment no\.|amended and restated|(?:first|second|third|fourth|fifth|an) amendment|"
                          r"amendment to (?:the |that certain )?(?:credit|loan|financing)", focus[:700], re.I))


def notes_record(kind, notes, focus, date):
    """One debt or convertible record from the tranches it issues in ONE currency (summed)."""
    cur = notes[0]["cur"]
    amount = sum(n["value"] for n in notes)
    stated = ""
    if amount < 1e7:
        # A note issue under $10M is implausible here and is a typo in the filing (CoreWeave's 2026-04-14 8-K
        # says "$1,750,000" for its $1.75 billion notes). Show no number rather than a wrong one.
        stated = f"the filing text states {short_money(amount, cur)}; "
        amount = None
    amount_usd = to_usd(amount, cur, date)
    money = short_money(amount, cur) + " " if amount else ""
    word = "convertible notes" if kind == "convertible" else "notes"
    if len(notes) == 1:
        title = f"{money}{notes[0]['name']}" + (" (add-on)" if notes[0]["add_on"] else "")
    else:
        years = sorted({n["name"][-4:] for n in notes})
        span = years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"
        title = f"{money}{word} in {len(notes)} tranches due {span}"
    tranche_text = ", ".join(f"{short_money(n['value'], n['cur'])} {n['name']}" for n in notes[:8])
    terms = extra_terms(focus, kind)
    if not any("floating" in n["name"].lower() for n in notes):
        terms = [t for t in terms if "+" not in t]   # a SOFR margin belongs to a loan next to the notes
    if kind == "debt":
        terms = [t for t in terms if "conversion" not in t]   # those belong to a convertible in the same filing
    if stated:
        tranche_text = stated + ", ".join(n["name"] for n in notes[:8])
    detail = "; ".join([tranche_text] + terms)
    return {"type": kind, "title": title, "amount": amount, "currency": cur if amount else None,
            "amount_usd": amount_usd, "detail": detail}


def cover_totals(focus):
    """A prospectus offering two share classes at once (Alphabet's Class A + Class C) prints one "Total" row per
    class in its price table: their sum is the offering size. None when the table has fewer than two classes."""
    m = re.search(r"Price to (?:the )?Public", focus[:9000], re.I)
    if not m:
        return None
    table = focus[m.end():m.end() + 1500]
    if len(re.findall(r"\bPer Share of\b", table, re.I)) < 2:
        return None
    totals = re.findall(r"\bTotal\b\s*(?:\(\d\)\s*)?\$\s*(\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?)", table)
    return sum(float(t.replace(",", "")) for t in totals) if len(totals) >= 2 else None


def offered_share_classes(focus):
    """[(count, class name)] from the opening "We are offering 25,459,689 shares of our Class A Common Stock ...
    and 25,459,689 shares of our Class C Capital Stock" sentence, when it names more than one class."""
    m = re.search(r"\bWe are offering\b", focus[:6000])
    if not m:
        return []
    sentence = split_sentences(focus[m.start():m.start() + 900])[0]
    found = re.findall(r"(\d{1,3}(?:,\d{3}){1,3}) shares of our ((?:Class [A-C] )?[A-Za-z]+ (?:Stock|Shares))",
                       sentence)
    return [(int(n.replace(",", "")), name) for n, name in found] if len(found) >= 2 else []


def generic_record(kind, focus, form, items, date, exclude=()):
    """A credit facility, share sale, ABS, lease or other financing, read from the deal text."""
    amount, cur = best_amount(focus, exclude, cover=form in FORMS_424)
    if kind == "equity" and form in FORMS_424 and cover_totals(focus):
        amount, cur = cover_totals(focus), "USD"
    if kind == "equity" and amount is None:
        shares = re.search(r"\b(\d{1,3}(?:,\d{3}){1,3})\s+(?:shares|ordinary shares)", focus)
        price = re.search(r"price (?:to the public )?of \$\s?(\d{1,4}(?:\.\d{1,4})?) per share", focus, re.I)
        if shares and price:
            amount, cur = int(shares.group(1).replace(",", "")) * float(price.group(1)), "USD"
    money = short_money(amount, cur) if amount else ""
    amend = "Amendment: " if is_amendment(focus) else ""
    item_set = set(items.split(",")) if items else set()
    if kind == "credit_facility":
        title = f"{amend}{money} {facility_name(focus)}"
    elif kind == "convertible":
        pref = re.search(r"mandatory convertible preferred|convertible preferred", focus[:3000], re.I)
        # "Series A" / "Series B": two series offered on one day are two deals, so the title says which
        series = re.search(r"\b(Series [A-Z])\s+(?:Mandatory )?Convertible Preferred", cover_title(focus, form)) \
            if pref else None
        label = (series.group(1) + " " if series else "") + pref.group(0).lower() + " stock" if pref \
            else notes_label(focus, "convertible notes")
        title = f"{money} {label}"
    elif kind == "debt":
        title = f"{amend}{money} {notes_label(focus, 'notes')}"
    elif kind == "equity":
        if re.search(r"at[- ]the[- ]market|equity distribution agreement|sales agreement", own_deal(focus[:3000]), re.I):
            up_to = money
            if not up_to:                            # some programs are sized in shares, not dollars
                share_cap = re.search(r"up to ([\d,]{6,}) (?:shares|class a|ordinary)", focus[:3000], re.I)
                up_to = f"{share_cap.group(1)} shares" if share_cap else ""
            title = "At-the-market equity program" + (f", up to {up_to}" if up_to else "")
        elif form in FORMS_8K and "3.02" in item_set:
            title = f"{money} private placement of shares" if money else "Unregistered sale of equity securities"
        elif re.search(r"will invest|equity investment|strategic investment", own_deal(focus[:3000]), re.I):
            title = f"{money} equity investment"
        elif re.search(r"preferred stock|preferred shares", own_deal(focus[:1500]), re.I):
            title = f"{money} preferred stock offering"
        else:
            title = f"{money} share offering"
    elif kind == "abs":
        title = f"{amend}{money} asset-backed financing"
    elif kind == "lease_financing":
        title = f"{amend}{money} lease financing"
    else:
        title = f"{amend}{money} financial obligation ({form})"
    return {"type": kind, "title": re.sub(r"\s+", " ", title).strip(), "amount": round(amount, 2) if amount else None,
            "currency": cur if amount else None, "amount_usd": to_usd(amount, cur, date) if amount else None,
            "detail": "; ".join(extra_terms(focus, kind))}


def notes_label(focus, plain):
    """Name of the newly issued notes when the deal text names them without an amount next to the name:
    "7.125% Senior Secured Notes due 2030", or "convertible notes in 2 series due 2031-2033"; else `plain`."""
    names = []
    for m in re.finditer(NOTE_CORE, focus[:3000], re.I):
        sentence = sentence_before(focus, m.start())
        name = tidy_name(m.group(0))
        if not NOT_NEW.search(sentence) and name.lower() not in [n.lower() for n in names]:
            names.append(name)
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        years = sorted({n[-4:] for n in names})
        span = years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"
        return f"{plain} in {len(names)} series due {span}"
    return plain


def side_facility(lead):
    """A credit facility / ABS / lease deal named in the opening lines next to a notes issue
    (e.g. IREN's "$1.5 billion delayed draw term loan facility ... and $2.1 billion of senior notes")."""
    for kind, pattern in TYPE_RULES:
        if kind not in ("credit_facility", "abs", "lease_financing"):
            continue
        for m in re.finditer(pattern, lead, re.I):
            sentence = sentence_before(lead, m.start())
            if not NOT_NEW.search(sentence) and not re.search(r"indenture|guarant|covenant", sentence, re.I):
                return kind
    return None


def parse_financing(text, form, items, date):
    """Read one filing. Returns a list of records {type, title, amount, currency, amount_usd, detail};
    an empty list means it is not a financing event."""
    focus = select_focus(text, form, items)
    if not focus:
        return []
    item_set = set(items.split(",")) if items else set()
    notes = offered_notes(focus[:12000])
    records = []
    # One record per instrument kind and currency: CoreWeave's dollar and euro notes on one 8-K are two rows,
    # each matching its own prospectus when there is one.
    groups = {}
    for n in notes:
        groups.setdefault(("convertible" if n["convertible"] else "debt", n["cur"]), []).append(n)
    for (kind, _cur), group in groups.items():
        records.append(notes_record(kind, group, focus, date))
    if records:
        if form not in FORMS_424:
            extra = side_facility(focus[:900])
            if extra:
                records.append(generic_record(extra, focus, form, items, date, exclude={n["pos"] for n in notes}))
        return records
    kind = classify(focus, form)
    if form in FORMS_8K and "3.02" in item_set and "2.03" not in item_set:
        unregistered = item_sections(text).get("3.02", "")
        if re.search(r"\bwarrants?\b", unregistered[:600] + " " + focus[:400], re.I):
            record = generic_record("equity", focus, form, items, date)
            record.update(title="Unregistered warrant issuance", amount=None, currency=None, amount_usd=None)
            return [record]                          # e.g. a warrant given to a customer, no cash raised
        if re.search(r"\bmerger\b|\bacqui(?:re|sition)\b", unregistered[:600], re.I):
            record = generic_record("equity", unregistered, form, items, date)
            record.update(title="Unregistered shares issued as acquisition consideration", amount=None,
                          currency=None, amount_usd=None)
            return [record]
        if "1.01" not in item_set:
            # A 3.02-only filing is an equity issue whatever it mentions; shares handed to holders of
            # convertible notes or preferred stock (exchange / conversion, e.g. SpaceX's preferred converting
            # at its IPO) raise no new money, so no amount is shown.
            plain = re.sub(r"securities exchange act|stock exchange", " ", unregistered[:800], flags=re.I)
            if re.search(r"\bnotes\b|debentures", text[:30000], re.I):
                source_security = "notes"
            elif re.search(r"preferred stock", unregistered[:800], re.I):
                source_security = "preferred stock"
            else:
                source_security = None
            if source_security and re.search(r"\bexchang(?:e|es|ed)\b|\bconver(?:sion|ted|t)\b", plain, re.I):
                record = generic_record("equity", unregistered, form, items, date)
                record.update(title=f"Unregistered shares issued on exchange / conversion of {source_security}",
                              amount=None, currency=None, amount_usd=None)
                return [record]
            kind = "equity"
        elif kind == "other":
            kind = "equity"                          # Item 3.02 = an unregistered sale of equity securities
    if kind == "other" and form in FORMS_8K and "2.03" in item_set and re.search(r"guarant", focus, re.I):
        # An off-balance-sheet obligation under Item 2.03: a guarantee / credit support for someone else's
        # financing (NVIDIA's residual value guaranties to SB Energy, 8-K 2026-08-17, capped at $105B).
        record = generic_record("other", focus, form, items, date)
        cap = re.search(r"(?:capped at|not (?:to )?exceed|maximum (?:aggregate )?(?:amount|exposure|obligation)"
                        r"[^$]{0,40}?|up to)\s+(?:an aggregate of\s+)?(" + MONEY_CORE + ")", focus, re.I)
        if cap and money_mentions(cap.group(1)):
            _, value, cur_, _ = money_mentions(cap.group(1))[0]
            record.update(amount=round(value, 2), currency=cur_, amount_usd=to_usd(value, cur_, date))
        what = "Residual value guarantee" if re.search(r"residual value", focus, re.I) else "Guarantee"
        money = f" ({short_money(record['amount'], record['currency'])} cap)" if record["amount"] else ""
        record.update(title=f"{what} / credit support{money}", detail=record["detail"] or
                      "Item 2.03 off-balance-sheet obligation: a guarantee of another party's obligations")
        return [record]
    if kind == "other" and (form not in FORMS_8K or not FINANCING_WORDS.search(focus[:1500])):
        return []                                    # e.g. a factory lease or construction contract under 2.03
    record = generic_record(kind, focus, form, items, date)
    if form in FORMS_8K and "2.03" in item_set and kind == "equity" and record["amount"] is None:
        # Item 2.03 is a debt-type obligation; when the text only talks about shares (e.g. a spin-off 8-K),
        # say what the filing reports instead of guessing a share offering.
        record.update(type="other", title="New financial obligation (Item 2.03)", detail="")
    if record["amount"] is None:
        if form in FORMS_6K:
            return []                                # a 6-K with no number is not something to show
        if form in FORMS_424 and not record["title"].startswith("At-the-market"):
            return []
    return [record]


# ---------------------------------------------------------------------------------------------------------
# Currency (rare for US filers: euro / sterling notes). One small Yahoo Finance request per currency per run.
# ---------------------------------------------------------------------------------------------------------
FX_PAIRS = {"EUR": "EURUSD=X", "GBP": "GBPUSD=X", "JPY": "JPYUSD=X", "CHF": "CHFUSD=X", "CAD": "CADUSD=X",
            "AUD": "AUDUSD=X", "CNY": "CNYUSD=X", "TWD": "TWDUSD=X", "HKD": "HKDUSD=X", "SGD": "SGDUSD=X",
            "KRW": "KRWUSD=X"}
_fx_cache = {}


def to_usd(amount, currency, date):
    """Convert with the daily close on (or just before) `date`. None when the rate is unavailable."""
    if amount is None or not currency:
        return None
    if currency == "USD":
        return round(amount, 2)
    pair = FX_PAIRS.get(currency)
    if not pair:
        return None
    if currency not in _fx_cache:
        try:
            import yfinance as yf
            hist = yf.Ticker(pair).history(period="2y", interval="1d")
            _fx_cache[currency] = {d.date().isoformat(): float(c) for d, c in hist["Close"].items()}
        except Exception as e:
            print(f"  [warn] FX {pair} unavailable ({e})")
            _fx_cache[currency] = {}
    closes = _fx_cache[currency]
    days = sorted(d for d in closes if d <= date)
    return round(amount * closes[days[-1]], 2) if days else None


# ---------------------------------------------------------------------------------------------------------
# One filing -> rows
# ---------------------------------------------------------------------------------------------------------
def exhibit_text(cik, filing):
    """For a 6-K: the first press-release exhibit (EX-99.x) as (text, URL), or (None, None)."""
    body = sec_get(ARCHIVE_URL.format(cik=cik, acc=filing["accession"].replace("-", ""), doc="index.json"))
    if not body:
        return None, None
    names = [i["name"] for i in json.loads(body).get("directory", {}).get("item", [])]
    exhibits = sorted(n for n in names if re.search(r"ex[-_]?99", n, re.I)
                      and n.lower().endswith((".htm", ".html", ".txt")))
    if not exhibits:
        return None, None
    url = doc_url(cik, filing["accession"], exhibits[0])
    return html_to_text(sec_get(url, max_bytes=400_000) or ""), url


def read_filing(cik, filing):
    """Fetch and parse one filing. Returns (list of records, document URL)."""
    url = doc_url(cik, filing["accession"], filing["doc"])
    form = filing["form"]
    html = sec_get(url, max_bytes=700_000 if form in FORMS_424 else 3_000_000)
    if html is None:
        return [], url
    text = html_to_text(html)
    if form in FORMS_6K:
        # Cheap check on the short cover first; only a financing 6-K costs the two extra exhibit requests.
        if NOT_FINANCING_6K.search(text[:6000]) or not FINANCING_WORDS.search(text[:6000]):
            return [], url
        ex_text, ex_url = exhibit_text(cik, filing)
        if ex_text:
            text, url = text[:6000] + " @@EXHIBIT@@ " + ex_text, ex_url
    return parse_financing(text, form, filing["items"], filing["filed"]), url


def make_rows(node_ids, cik, filing, record, url):
    return [{
        "company": node_id,
        "date": filing["filed"],
        "type": record["type"],
        "title": record["title"][:160],
        "amount": round(record["amount"], 2) if record["amount"] else None,
        "currency": record["currency"],
        "amount_usd": record["amount_usd"],
        "detail": record["detail"][:500],
        "form": filing["form"],
        "market": "US",
        "source": SOURCE,
        "url": url,
        "accession": filing["accession"],
        "items": filing["items"],
        "cik": cik,
        "recorded": today(),
    } for node_id in node_ids]


# ---------------------------------------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------------------------------------
def build():
    """Rebuild graph/financing/ (one file per company) from all financing histories (market/financing.py does the work)."""
    return financing.build()


def run(backfill=False):
    load_env()
    state = read_json(STATE_FILE, {}) or {}
    window_start = (dt.date.fromisoformat(today()) - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    # Accession numbers already read (kept or not) -> never fetched again. Older than the window = forgotten.
    seen = {acc: filed for acc, filed in state.get("seen", {}).items() if filed >= window_start}
    if backfill or not state.get("last_run"):
        since = window_start
    else:
        since = max(window_start, (dt.date.fromisoformat(state["last_run"])
                                   - dt.timedelta(days=OVERLAP_DAYS)).isoformat())
    print(f"financing_us: filings since {since} ({'backfill' if backfill else 'daily'})")

    try:
        companies = us_companies()
    except Exception as e:
        print(f"  [warn] SEC ticker list unavailable ({e}); keeping previous data")
        build()
        return 1                                     # nothing could be checked at all
    print(f"  {len(companies)} SEC filers to check")

    key = ("accession", "type", "currency", "company")
    pending, checked, failed, kept, added = [], 0, 0, 0, 0
    in_a_row = 0                                     # filers failed one after another (circuit breaker)
    for n, (cik, node_ids) in enumerate(sorted(companies.items(), key=lambda kv: kv[1][0].lower()), 1):
        try:
            filings = list_filings(cik, since)
        except Exception as e:
            failed += 1
            in_a_row += 1
            print(f"  [warn] {node_ids[0]}: submissions unavailable ({e})")
            if in_a_row >= BREAKER:
                # SEC is down or blocking us: each further filer would cost ~20 s of retries for nothing, and
                # the nightly time box would kill the run before the other collectors (user, 2026-10-17).
                print(f"  [warn] SEC unreachable ({in_a_row} filers in a row failed); keeping previous data, "
                      f"skipping the other {len(companies) - n} filers")
                break
            continue
        in_a_row = 0
        checked += 1
        for f in filings:
            if f["accession"] in seen:
                continue
            if f["form"] in FORMS_8K and not ({"1.01", "2.03", "3.02"} & set(f["items"].split(","))):
                seen[f["accession"]] = f["filed"]    # results, votes, Reg FD ... decided from the item list alone
                continue
            try:
                records, url = read_filing(cik, f)
            except Exception as e:                   # not marked seen: retried on the next run
                print(f"  [warn] {node_ids[0]} {f['form']} {f['accession']}: {e}")
                continue
            seen[f["accession"]] = f["filed"]
            for record in records:
                pending += make_rows(node_ids, cik, f, record, url)
                kept += 1
                print(f"  + {node_ids[0]:<22} {f['filed']} {f['form']:<6} {record['type']:<15} {record['title']}")
        if n % 25 == 0:                              # save progress so an interrupted backfill resumes
            added += append_history(DATASET, pending, key)
            pending = []
            write_json(STATE_FILE, {"last_run": state.get("last_run"), "seen": seen})

    added += append_history(DATASET, pending, key)
    tripped = in_a_row >= BREAKER
    if checked:
        # a tripped breaker keeps last_run, so the next run looks back far enough to read the skipped filers
        write_json(STATE_FILE, {"last_run": state.get("last_run") if tripped else today(), "seen": seen})
    print(f"  checked {checked} filers ({failed} failed): {kept} financing records, {added} new history rows, "
          f"{_stats['requests']} SEC requests")
    build()
    if companies and checked == 0:
        print("  [warn] every SEC request failed")
        return 1
    if tripped:
        return 1                                     # logged as failed: most filers were not checked tonight
    return 0


def main():
    parser = argparse.ArgumentParser(description="US financing events from SEC EDGAR (8-K, 424B, 6-K).")
    parser.add_argument("--backfill", action="store_true", help="re-check the whole 365-day window")
    parser.add_argument("--build-only", action="store_true", help="rebuild graph/financing/ (one file per company) from history only")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)  # progress lines show up live in the nightly log
    except (AttributeError, ValueError):
        pass
    if args.build_only:
        build()
        return 0
    return run(backfill=args.backfill)


if __name__ == "__main__":
    sys.exit(main())
