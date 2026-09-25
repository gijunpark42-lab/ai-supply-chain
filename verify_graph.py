"""
verify_graph.py — independent cross-verification of every data point in the merged graph.

What this is
------------
Enrichment (Workflow 2 / 2b) ADDS entries to the graph. Nothing, until now, ever went back
and asked: "is this entry actually supported by the document it claims to come from?"
This script does exactly that, from the outside:

  * it never touches chains/ or graph/merged_graph.json (read-only);
  * it does not trust the enrichment job — it re-opens the SOURCE FILE(S) the entry's label
    points at (transcripts/**, supply_contracts/*) and checks the entry against the text;
  * it writes one report: graph/verification.json (+ a console summary).

Think of it as an auditor that was not in the room when the data was written.

The four checks, per entry
--------------------------
Every quarterly_data entry (node) and every contracts entry (edge) gets:

  1. SOURCE   — does the label ("NVIDIA Q2 FY2027 (08-26-2026)") resolve to a file on disk?
                Resolution order: a "# source label:" header in the file (informal spellings
                such as "Source label for enrichment:" or a back-ticked label inside a NOTE
                line count too) → filename join ("<company>_q<N>_<year>.txt";
                "<company>_fy<year>[_briefing|_qa|_tanshin]" counts as Q4 FY<year>) → loose
                event-name match ("nvda_gtc_taipei_2026.txt" for "NVIDIA GTC Taipei 2026 (…)").
                One label may map to SEVERAL companion files (the call + its 8-K earnings
                release, a results deck + its Q&A): the checks below run against the UNION
                of their texts. A DART supply-contract label resolves ONLY to its
                supply_contracts/ block, never to the half-year report.
  2. NUMBERS  — every number written in `figure` / `units` / `value` (e.g. "$107M", "45%",
                "KRW 45,946M", "1.6T") must appear in that document. Numbers are the part
                of an entry that can be checked mechanically; a paraphrased `signal` cannot.
                The matcher understands rounding after a unit change ("45,946M" is the
                filing's "45,945,836,761" won; "$8.97B" is the release's "$8,965 million"),
                Korean units ("408.9억원" is 40,890M), numbers written in words ("6 thousand",
                "half a million") and speech-to-text decimal slips ("$3.7" for $3.07 → warn).
                Entries with no numbers ("no specific figure") are "unchecked", not "passed".
  3. PARTY    — for a contract on edge A → B, the source document must mention the OTHER
                company (the one the document is not about). A deal with Meta that never
                says "Meta" is suspicious. Korean/Japanese spellings, subsidiaries, brands
                and abbreviations (솔브레인, AWS, Atotech, STATS ChipPAC, ASE …) count.
  4. HYGIENE  — label follows the canonical format, and no Korean characters leaked into
                the chain (Workflow 2b rule).

Plus one check per EDGE (not per entry) — the real "cross" in cross-verification:

  5. CORROBORATION — how many INDEPENDENT sources back this edge?
        two_sided     : A's own documents mention B  AND  B's own documents mention A.
                        Two companies, on their own earnings calls / filings, each naming
                        the other. This is the strongest evidence the corpus can give.
        multi_source  : contracts from ≥2 different companies' documents.
        single_source : only one side has ever said it.
        no_contracts  : skeleton edge (curated structure, no deal data yet) — not judged.

Verdict per entry:  pass | warn | fail | unchecked
  fail      — source file missing, or a number is not in the document, or Korean chars.
  warn      — counterparty not found in the document, label format off, or every missing
              number is only a decimal-shift near miss ("3.7" in the transcript for "3.07")
              or transparent arithmetic on the field's other, verified numbers
              ("67.6 + 79.0 + 88.3 = 234.9"; "9.2 / 28.0 = 32.8%") — number_derived.
  unchecked — source resolved but the entry carries nothing checkable (no numbers).

How to run
----------
    python verify_graph.py                 # full report → graph/verification.json
    python verify_graph.py --company NVIDIA
    python verify_graph.py --label "Samsung Q2 FY2026 (08-14-2026)"
    python verify_graph.py --fails         # print every fail/warn: doc path + missing numbers

Exit code is 1 when any entry FAILS, so this can gate a build or a commit later.

evidence.py imports resolve_label, load_documents, numbers_in, NUMBER and KO_ALIASES from
here. Their names, signatures and return shapes are a contract: add helpers, don't change them.
"""

import argparse
import bisect
import glob
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

# We reuse two helpers the agent already has, rather than re-inventing them:
#   normalize()          — folds curly quotes / dashes / whitespace so quotes match
#   normalize_company()  — "SK Hynix" -> "skhynix", plus the filename aliases (nvidia -> nvda)
from agent.verify import normalize
from agent.corpus import list_documents, normalize_company

GRAPH_PATH = "graph/merged_graph.json"
REPORT_PATH = "graph/verification.json"
METADATA_PATH = "company_metadata.json"
DOC_GLOBS = ["transcripts/**/*.txt", "supply_contracts/*.txt"]

LABEL_EARNINGS = re.compile(r"^.+ Q[1-4] FY20\d\d \(\d\d-\d\d-\d{4}\)$")
LABEL_OTHER = re.compile(r"^.+ \(\d\d-\d\d-\d{4}\)$")   # events, notes, DART supply contracts
LABEL_DATE = re.compile(r"\((\d\d-\d\d-\d{4})\)\s*$")
LABEL_Q = re.compile(r"^(?P<company>.+?)\s+Q(?P<q>[1-4])\s+FY(?P<y>20\d\d)\b")
KOREAN = re.compile(r"[가-힣]")
CJK = re.compile(r"[가-힣一-鿿ぁ-ヿ]")                # Hangul, kanji/hanzi, kana


# ---------------------------------------------------------------------------
# 0. Alias tables — the other ways a document can name a graph node
# ---------------------------------------------------------------------------
# Korean filings write counterparties in Korean ("솔브레인"), Japanese briefings in Japanese
# ("日本化学工業"), English calls use brands, subsidiaries and abbreviations ("AWS", "Atotech",
# "STATS ChipPAC"). Every alias is matched exactly like the node name itself (Doc.mentions).
# evidence.py reads this table too, so the shape stays  node name -> [alias, alias, ...].
KO_ALIASES = {
    # --- Korean nodes -----------------------------------------------------------------
    "AD Technology": ["에이디테크놀로지", "AD테크놀로지"],
    "Daeduck Electronics": ["대덕전자", "Daeduck"],
    "Dongjin Semichem": ["동진쎄미켐", "동진세미켐", "Dongjin"],
    "Dongwoo Fine-Chem": ["동우화인켐", "동우파인켐", "Dongwoo"],
    "Doosan Corporation": ["두산전자", "주두산", "Doosan Electronic", "Doosan Corp"],
    "Doosan Enerbility": ["두산에너빌리티", "두산중공업"],
    "EO Technics": ["이오테크닉스", "EO테크닉스"],
    "Gaonchips": ["가온칩스"],
    "HD Hyundai Electric": ["HD현대일렉트릭", "현대일렉트릭", "에이치디현대일렉트릭", "Hyundai Electric"],
    "Hanmi Semiconductor": ["한미반도체", "Hanmi"],
    "Hanwha Semitech": ["한화세미텍", "한화정밀기계"],
    "Hyosung Heavy Industries": ["효성중공업", "Hyosung Heavy", "HICO"],
    "ISC": ["아이에스시"],
    "Isu Petasys": ["이수페타시스"],
    "Jusung Engineering": ["주성엔지니어링", "Jusung"],
    "Korea AI Computing Center (KOACC)": ["국가AI컴퓨팅센터", "국가 AI 컴퓨팅 센터"],
    "Korea Circuit": ["코리아써키트"],
    "LG Innotek": ["LG이노텍", "엘지이노텍"],
    "LS Electric": ["LS일렉트릭", "엘에스일렉트릭", "LS ELECTRIC", "LS산전"],
    "Leeno Industrial": ["리노공업", "Leeno"],
    "Mirae Industry": ["미래산업"],
    "Naver": ["네이버", "NAVER", "네이버클라우드", "NAVER Cloud", "Naver Cloud"],
    "POSCO": ["포스코"],
    "PSK Holdings": ["피에스케이홀딩스", "PSK홀딩스"],
    "PSK Inc.": ["피에스케이", "PSK Inc"],
    "SFA Semiconductor": ["SFA반도체", "에스에프에이반도체"],
    "SK Airplus": ["에스케이에어플러스", "SK에어플러스"],
    "SK Enpulse": ["에스케이엔펄스", "SK엔펄스"],
    "SK Hynix": ["SK하이닉스", "에스케이하이닉스", "하이닉스", "Hynix"],
    "SK Siltron": ["SK실트론", "에스케이실트론", "실트론"],
    "SK Specialty": ["SK스페셜티", "에스케이스페셜티"],
    "SK Trichem": ["에스케이트리켐", "SK트리켐"],
    "Samsung": ["삼성전자", "Samsung Electronics"],
    "Samsung Electro-Mechanics": ["삼성전기", "SEMCO", "Samsung Electro Mechanics"],
    "Samsung Foundry": ["삼성전자", "삼성파운드리", "Samsung Electronics", "Samsung"],
    "Sanil Electric": ["산일전기"],
    "Signetics": ["시그네틱스"],
    "Simmtech": ["심텍"], "Kinsus": ["킨서스", "景碩"],
    "Soulbrain": ["솔브레인"],
    "Taihan Cable": ["대한전선", "Taihan"],
    "Techwing": ["테크윙"],
    "Wonik IPS": ["원익IPS", "원익아이피에스"],
    "Wonik QnC": ["원익QnC", "원익큐엔씨"],
    # --- Japanese nodes (Japanese script + the Korean spelling a DART filing would use) ----
    "Advantest": ["어드반테스트", "アドバンテスト"],
    "Dai Nippon Printing": ["DNP", "大日本印刷"],
    "Disco Corporation": ["DISCO", "디스코", "ディスコ"],
    "Ibiden": ["이비덴", "イビデン"],
    "JX Advanced Metals": ["JX Metals", "JX Nippon Mining", "JX금속"],
    "Kioxia": ["키오시아", "キオクシア"],
    "Lasertec": ["레이저텍", "レーザーテック"],
    "Mitsubishi Gas Chemical": ["MGC", "三菱ガス化学", "미쓰비시가스화학", "미츠비시가스화학"],
    "Mitsubishi Heavy Industries": ["MHI", "三菱重工", "Mitsubishi Power", "Mitsubishi Hitachi Power Systems",
                                    "MHPS", "미쓰비시중공업", "미츠비시중공업"],
    "Mitsui Mining & Smelting": ["Mitsui Kinzoku", "Mitsui Mining", "三井金属"],
    "Murata": ["무라타", "村田製作所"],
    "Nippon Chemical Industrial": ["日本化学工業", "NCI"],
    "Nippon Steel": ["日本製鉄", "신일본제철"],
    "Renesas": ["르네사스", "ルネサス"],
    "SUMCO": ["섬코"],
    "Shin-Etsu Chemical": ["Shin-Etsu", "신에츠", "信越化学"],
    "Shinko Electric": ["Shinko", "新光電気"],
    "Sumitomo Metal Mining": ["SMM", "住友金属鉱山"],
    "TDK": ["TDK株式会社"],
    "Taiyo Holdings": ["Taiyo Ink", "다이요잉크", "다이요 잉크", "太陽ホールディングス"],
    "Taiyo Yuden": ["태양유전", "太陽誘電"],
    "Tokyo Electron": ["도쿄일렉트론", "東京エレクトロン"],
    "Tokyo Ohka Kogyo": ["TOK", "東京応化"],
    # --- everyone else: brands, subsidiaries, abbreviations, Korean spellings -----------
    "3M": ["쓰리엠"],
    "AMD": ["Advanced Micro Devices"],
    "ASE Group": ["ASE", "ASE Technology", "ASE Korea", "日月光"],
    "ASM International": ["ASMI", "ASM"],
    "ASML": ["에이에스엠엘"],
    "Absolics (SKC)": ["앱솔릭스"],
    "Alfa Laval": ["Alfa"],
    "Amazon": ["Amazon Web Services", "AWS", "Trainium", "Annapurna", "아마존"],
    "American Electric Power": ["AEP"],
    "Amkor Technology": ["Amkor", "앰코", "앰코테크놀로지", "앰코테크놀러지"],
    "Analog Devices": ["ADI"],
    "Anthropic": ["앤트로픽"],
    "Apple": ["애플"],
    "Applied Digital": ["APLD"],
    "Applied Materials": ["AMAT", "어플라이드 머티어리얼즈", "어플라이드머티리얼즈"],
    "Applied Optoelectronics": ["AAOI", "AOI", "Applied Opto"],
    "Arm Holdings": ["Arm", "ARM"],
    "BESI": ["BE Semiconductor"],
    "Bloom Energy": ["Bloom"],
    "Broadcom": ["브로드컴"],
    "Cadence": ["케이던스"],
    "Cisco": ["Cisco Systems", "시스코"],
    "Constellation Energy": ["Constellation"],
    "CoreWeave": ["코어위브"],
    "Delta Electronics": ["Delta", "델타전자"],
    "Dell": ["델"],
    "Dominion Energy": ["Dominion"],
    "Elite Material": ["EMC", "台光"],
    "Foxconn": ["Hon Hai", "홍하이", "폭스콘"],
    "GE Vernova": ["GE", "GE Vernova"],
    "GUC (Global Unichip)": ["Global Unichip"],
    "Google": ["Alphabet", "Google Cloud", "GCP", "구글"],
    "HPE": ["Hewlett Packard Enterprise"],
    "Intel": ["인텔", "Intel Foundry", "IFS", "Intel Foundry Services"],
    "Intersect Power": ["Intersect"],
    "JCET": ["STATS ChipPAC", "스태츠칩팩", "长电"],
    "Johnson Controls": ["JCI"],
    "KLA": ["KLA-Tencor", "케이엘에이"],
    "Kulicke & Soffa": ["K&S", "Kulicke and Soffa"],
    "Lam Research": ["Lam", "램리서치"],
    "Linde": ["린데"],
    "Lite-On": ["LITEON", "LiteOn", "라이트온"],
    "Lumen Technologies": ["Lumen"],
    "MKS Instruments": ["Atotech", "ATOTECH", "아토텍", "MKS"],
    "Marvell": ["마벨"],
    "Meta": ["Meta Platforms", "Facebook", "메타"],
    "Micron": ["마이크론", "Micron Technology"],
    "Microsoft": ["Azure", "Microsoft Azure", "마이크로소프트"],
    "Monolithic Power Systems": ["MPS"],
    "NVIDIA": ["엔비디아", "NVDIA"],
    "Nan Ya PCB": ["NYPCB", "Nanya PCB", "Nanya", "난야"],
    "Nanya Technology": ["Nanya"],
    "OpenAI": ["오픈AI", "오픈에이아이"],
    "Oracle": ["오라클"],
    "Powertech Technology": ["PTI", "Powertech"],
    "Puget Sound Energy": ["PSE"],
    "Qualcomm": ["퀄컴"],
    "Raytec Semiconductor": ["Raytek", "Raytec"],
    "Sandisk": ["SanDisk", "샌디스크", "サンディスク"],
    "SPIL": ["Siliconware"],
    "Silicon Motion": ["SIMO"],
    "SoftBank": ["소프트뱅크", "ソフトバンク"],
    "Southern Company": ["Southern Co"],
    "Sumitomo Bakelite": ["住友ベークライト"],
    "Sumitomo Electric": ["住友電気工業", "住友電工"],
    "Supermicro": ["Super Micro", "Super Micro Computer", "슈퍼마이크로"],
    "Synopsys": ["시높시스", "시놉시스"],
    "TE Connectivity": ["TE"],
    "TSMC": ["Taiwan Semiconductor", "台積電", "臺灣積體電路"],
    "Tesla": ["테슬라"],
    "Texas Instruments": ["TI"],
    "Trane Technologies": ["Trane"],
    "VAST Data": ["VAST"],
    "Vertiv": ["버티브"],
    "Western Digital": ["WDC"],
    "Xcel Energy": ["Xcel"],
    "Zhen Ding": ["ZDT"],
    "onsemi": ["ON Semiconductor", "온세미"],
    "SpaceX": ["xAI", "X.AI", "SpaceXAI", "Grok"],
}

# Node names (or first words) that are also ordinary English words, or that several nodes
# share. They never serve as a bare first-word fallback ("Together AI" must not be found by
# the word "together"), and as whole names they only count when written as a proper noun
# ("Coherent" / "COHERENT", never "a coherent strategy"; "Intel", never "intelligence").
COMMON_WORDS = set("""
american ampere analog apple applied black bloom celestial cisco coherent cohere constellation
core credo cursor dai delta disco dominion elite flex gold helix intel intersect johnson korea
lambda landmark linde lite meta micron mitsubishi monolithic nan nippon nova onto perplexity
power quanta reflection samsung screen shell shin siemens silicon southern sumitomo taiwan taiyo
texas thinking together tokyo tower via western world wonik doosan psk
""".split())


# ---------------------------------------------------------------------------
# 1. Small helpers: names, numbers, units
# ---------------------------------------------------------------------------

def compact(text):
    """Lowercase letters/digits/Hangul/CJK only: 'SK Hynix' -> 'skhynix'. Used for name matching."""
    return re.sub(r"[^a-z0-9가-힣一-鿿ぁ-ヿ]", "", unicodedata.normalize("NFKC", text).lower())


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Dates written inside a figure ("at 06-30-2026", "2026-01-01 to 2026-06-30", "to 12-2027")
# are not figures; their fragments ("06", "30") would match anything. Stripped before counting.
DATE_IN_FIELD = re.compile(r"\b\d{1,2}-\d{1,2}-\d{4}\b|\b\d{4}[-./]\d{2}[-./]\d{2}\b|\b\d{1,2}-20\d\d\b"
                           r"|\b(?:FY|CY)?'?\d{2}-\d{2}\b|\b20\d\d-\d{2}\b|'\d{2}\b")   # year ranges: "26-27", "CY27-29", "2026-28", "'23"

# Korean amount units, as they appear inside a DART filing: "408.9억원", "27조 8,000억원",
# "22 백만원". 십만/천만 are listed before 만/천 so the longer unit wins.
KO_UNITS = {"조": 1e12, "억": 1e8, "천만": 1e7, "백만": 1e6, "십만": 1e5, "만": 1e4, "천": 1e3}
KO_AMOUNT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(조|억|천만|백만|십만|만|천)"
                       r"(?:\s*(\d[\d,]*(?:\.\d+)?)\s*(억|천만|백만|십만|만|천))?")
# English amounts in words: "6 thousand", "1.3 billion", "half a million", "a billion".
WORD_UNITS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
WORD_AMOUNT = re.compile(r"\b(half a|half-a|a|\d[\d,]*(?:\.\d+)?)\s+(thousand|million|billion|trillion)")
# Scale suffix written right after a figure's number inside the chain: "45,946M", "$8.97B",
# "1.6T", "500K", "1.2kV", "2.5bn", "3 million". Also the ratio markers "%" and "x".
UNIT_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
              "b": 1e9, "bn": 1e9, "billion": 1e9, "t": 1e12, "trillion": 1e12, **KO_UNITS}
UNIT_SUFFIX = (r"\s?(%|x(?![a-z])|×|k(?=[A-Z]|[^A-Za-z]|$)|K(?![A-Za-z])|M(?![A-Za-z])|B(?![A-Za-z])"
               r"|T(?![A-Za-z])|bn(?![a-z])|mn(?![a-z])|thousand|million|billion|trillion"
               r"|조|억|천만|백만|십만|만|천)?")


def parse_number(text):
    """'45,946' -> 45946.0; None when the token is not a number."""
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def significant_digits(text):
    """The digits that carry information: '45,946' -> '45946', '0.96' -> '96',
    '6,000' -> '6', '20.9' -> '209', '62.0' -> '620' (a zero after the point is the
    writer's precision, so it counts). Their COUNT decides how loosely a figure may be
    matched — a 1-digit "500" proves nothing at any other scale."""
    bare = text.replace(",", "")
    if "." not in bare:
        bare = bare.rstrip("0")
    return bare.replace(".", "").lstrip("0")


def sig_exp(value):
    """A number as (significant digits, power of ten of its last digit):
    220000 -> ("22", 4), 0.45 -> ("45", -2), 40890000000 -> ("4089", 7), 4.9 -> ("49", -1).
    Two numbers with the same digits differ only by a power of ten — a unit change."""
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    digits = (whole + frac).lstrip("0")
    p = -len(frac)
    stripped = digits.rstrip("0")
    p += len(digits) - len(stripped)
    return stripped, p


ASIAN_CURRENCY = re.compile(r"KRW|₩|\bwon\b|JPY|¥|\byen\b|円|원|억|조", re.I)


def figure_unit(context, number):
    """What follows `number` inside its own field. Returns (scale, kind):
    kind = 'percent' ("45%"), 'multiple' ("12.9x"), 'amount' (a scale word/suffix was found:
    "$8.97B" -> 1e9, "1.2kV" -> 1e3, "408.9억원" -> 1e8) or None (bare number)."""
    if not context:
        return None, None
    m = re.search(r"(?<![\d.,])" + re.escape(number) + r"(?![\d,])" + UNIT_SUFFIX, context)
    if not m or not m.group(1):
        return None, None
    unit = m.group(1)
    if unit == "%":
        return None, "percent"
    if unit in ("x", "×"):
        return None, "multiple"
    return UNIT_SCALE[unit.lower()], "amount"


# ---------------------------------------------------------------------------
# 2. One source document
# ---------------------------------------------------------------------------

# Filename conventions (agent/corpus.py's plus the ones hand-saved files use):
#   <company>_q<N>_<year>[_suffix].txt      the call (bare) or a companion (_earnings_release, _call, _dart …)
#   <company>_q<N>_fy<year>[_suffix].txt    same, fiscal-year spelling
#   <company>_fy<year>[_suffix].txt         a full-year deck / tanshin / briefing = Q4 FY<year>
#   <slug>_prelim_<YYYY-MM-DD>[_separate]   a DART 잠정실적 (label comes from its header)
STEM_QUARTER = re.compile(r"^(?P<company>.+?)_q(?P<q>[1-4])_(?:fy)?(?P<y>20\d\d)(?P<suffix>.*)$")
STEM_FY = re.compile(r"^(?P<company>.+?)_fy(?P<y>20\d\d)(?P<suffix>.*)$")
STEM_PRELIM = re.compile(r"^(?P<company>.+?)_prelim_(?P<y>\d{4})-(?P<m>\d\d)-(?P<d>\d\d)(?P<suffix>.*)$")

# The label a file declares about itself. Machine-written files (av.py, dart.py, investing.py)
# use "# source label: X"; hand-saved files use a handful of informal spellings, and some
# NOTE lines carry the label in back-ticks ("… (same source label `Intel Q2 FY2026 (07-23-2026)`)").
HEADER_LABEL = re.compile(r"(?im)^\s*(?:#\s*)?(?:canonical\s+)?source label(?:\s+used)?"
                          r"(?:\s+(?:for|in)\s+(?:enrichment|chains))?\s*:\s*`?(.+?)`?\s*$")
INLINE_LABEL = re.compile(r"(?i)source label\s*`([^`]+)`")
# The date a file states about itself, from the machine-written fields only.
HEADER_DATE = re.compile(r"(?i)\b(?:CALL DATE|Filed|Earnings announced|Results announced)\s*:\s*"
                         r"(?:APPROXIMATE\s*-\s*)?(\d{4}-\d\d-\d\d|\d\d-\d\d-\d{4}|\d{8})")


def _mmddyyyy(text):
    """'2026-07-29' / '20260729' / '07-29-2026' -> '07-29-2026' (the label spelling)."""
    if re.fullmatch(r"\d{4}-\d\d-\d\d", text):
        return f"{text[5:7]}-{text[8:10]}-{text[:4]}"
    if re.fullmatch(r"\d{8}", text):
        return f"{text[4:6]}-{text[6:8]}-{text[:4]}"
    return text


def header_labels(block):
    """Every source label the head of a document declares, canonical spelling first.
    Older supply_contracts blocks said "DART 공급계약"; the chain says "DART supply contract"."""
    head = block[:3000]
    found = HEADER_LABEL.findall(head) + INLINE_LABEL.findall(head)
    labels = []
    for raw in found:
        lab = raw.strip().strip("`'\" ").rstrip(".").strip()
        lab = lab.replace("DART 공급계약", "DART supply contract")
        if LABEL_OTHER.match(lab) and lab not in labels:
            labels.append(lab)
    return labels


class Doc:
    """One source document (or one ==== block of a supply_contracts file)."""

    def __init__(self, path, text, label=None):
        self.path = path.replace("\\", "/")
        self.text = text
        self.label = label                    # from the "# source label:" header, if present
        self.labels = [label] if label else []
        self.norm = normalize(text)           # for number matching
        self.norm_nocomma = self.norm.replace(",", "")
        self.compact = compact(text)          # for company-name matching
        self._mention_cache = {}
        # Identity from the header (dates the file states about itself) and the filename.
        m = HEADER_DATE.search(text[:3000])
        self.date = _mmddyyyy(m.group(1)) if m else None
        self.stem = os.path.basename(self.path)[:-4]
        self.quarter = self.year = None
        self.suffix = ""
        if self.path.startswith("supply_contracts/"):
            self.company_token = normalize_company(self.stem)
        elif (m := STEM_QUARTER.match(self.stem)):
            self.company_token = normalize_company(m.group("company"))
            self.quarter, self.year, self.suffix = int(m.group("q")), int(m.group("y")), m.group("suffix")
        elif (m := STEM_FY.match(self.stem)):
            self.company_token = normalize_company(m.group("company"))
            self.quarter, self.year, self.suffix = 4, int(m.group("y")), m.group("suffix")
        elif (m := STEM_PRELIM.match(self.stem)):
            self.company_token = normalize_company(m.group("company"))
            self.date = self.date or f"{m.group('m')}-{m.group('d')}-{m.group('y')}"
        else:
            self.company_token = normalize_company(self.stem.split("_")[0])

    @property
    def is_full_transcript(self):
        """A bare <company>_q<N>_<year>.txt is the call itself; suffixed files are companions."""
        return self.quarter is not None and self.suffix == ""

    def declared_date(self):
        """The date this document says it is: its header label's date, else its CALL DATE / filed line."""
        for lab in self.labels:
            m = LABEL_DATE.search(lab)
            if m:
                return m.group(1)
        return self.date

    # -- PARTY -----------------------------------------------------------------------

    def mentions(self, company):
        """Does this document name `company` — its node name, an alias, a parenthesised
        acronym, a 4+ letter ticker, or (when distinctive) its first word alone?"""
        if company not in self._mention_cache:
            self._mention_cache[company] = any(self._has_name(n, explicit) for n, explicit in name_variants(company))
        return self._mention_cache[company]

    def _has_name(self, name, explicit=False):
        key = compact(name)
        if not key:
            return False
        if CJK.search(key):                       # Korean / Japanese spelling: the script is distinctive
            return len(key) >= 2 and key in self.compact
        compound = len(name.split()) >= 2 or not name.isalnum()      # "SK Hynix", "Lite-On", "K&S"
        if (compound or len(key) >= 7) and len(key) >= 5 and key not in COMMON_WORDS:
            return key in self.compact           # 'skhynix', 'liteon', 'broadcom' — spelling/spacing-proof
        if len(key) < (2 if explicit else 3):
            return False
        # Short or common-word names count only as whole words. ALL-CAPS names of up to
        # 4 letters (ASE, KLA, PSE) and common words (Intel, Coherent, Nova) are case-sensitive:
        # "ASE" must not hide in "phase", "Arm" must not match "arm's length".
        case_sensitive = key in COMMON_WORDS or len(key) <= 4
        return _word_pattern(name, case_sensitive).search(self.text) is not None

    # -- NUMBERS ---------------------------------------------------------------------

    def has_number(self, number, context=""):
        """Is this number in the document? `context` is the field it was written in (so the
        matcher can see "$8.97B" or "45%" around it). Ways to say yes, strictest first:

        1. exact text        "3.274" in the document (commas ignored on both sides)
        2. trailing zeros    "14.0" / "4.00"  ->  "14" / "4"        ("$14 billion")
        3. rounding          "88.9" matches a document value 88.86; "6,000" matches "6 thousand"
        4. unit rescale      the document's raw amount, divided by a power of ten and ROUNDED
                             to the figure's own precision: "45,946" (M) is 45,945,836,761 won;
                             "$8.97B" is "$8,965 million"; "422.5" (B) is a 백만원 table's
                             "422,483"; "0.7" (B) is "$700 million". Only the unit changes a
                             filing really makes are tried — the figure's own unit and the
                             천원 / 백만원 / 십억원 (thousands / millions / billions) tables —
                             because every extra power of ten is another chance for a wrong
                             number to collide with one of a filing's tens of thousands of
                             values. A 1-2 digit figure ("220B yen", "KRW 4.9B") is too round
                             for a window: it must appear with exactly the same digits at one
                             of those powers of ten ("220,000" million yen — not 4,912,345,678).
        Percentages and multiples ("45%", "12.9x") are never rescaled — the only other way
        to write 20.9% is 0.209.
        A number must stand on its own in the text: "38" inside "382" or "1,138" is not a match.
        """
        n = number.replace(",", "")
        if self._has_token(n):
            return True
        if "." in n and self._has_token(n.rstrip("0").rstrip(".")):
            return True
        value = parse_number(n)
        if value is None:
            return False
        decimals = len(n.split(".")[1]) if "." in n else 0
        half = 0.5 * 10 ** -decimals
        if self._has_value_between(value - half, value + half):
            return True
        precision = len(significant_digits(n))       # from the TEXT: "62.0" is 3 digits, "6,000" is 1
        sig, p_fig = sig_exp(value)                   # from the value: "62.0" -> ("62", 0), for the digit map
        scale, kind = figure_unit(context, number)
        if kind in ("percent", "multiple"):
            return precision >= 3 and self._has_value_between((value - half) / 100, (value + half) / 100)
        if scale:
            e = round(math.log10(scale))
            exponents = {e, e - 3, e - 6, e - 9}       # the figure's unit; 천원 / 백만원 / 십억원 tables
            if ASIAN_CURRENCY.search(context):
                exponents.add(e - 8)                   # 억원 / 億円 tables
        else:
            exponents = {-2, -1, 1, 2, 3, 6, 9}       # no unit stated: 억 <-> 십억, thousands, millions, billions
        exponents.discard(0)
        if precision >= 3:
            for k in sorted(exponents, reverse=True):
                f = 10.0 ** k
                if self._has_value_between((value - half) * f, (value + half) * f):
                    return True
            return False
        # A 1-2 digit figure ("220B yen", "KRW 2,500M", "500K") is too round for a window —
        # it would collide with something in any filing. It must appear with EXACTLY the same
        # digits at one of those powers of ten, printed with 4+ digits: "220,000" (million yen)
        # yes; "4,912,345,678" no (different digits); a bare "67" for "6.7B" no (too short).
        if not scale:
            return False
        return any(p - p_fig in exponents and p + len(sig) >= 4 for p in self._sig_map().get(sig, ()))

    def _has_token(self, n):
        """Is the comma-free number `n` in the text as a number of its own — not glued to
        other digits ("38" in "382"), not a fragment of a decimal ("38" in "1.38" / "38.5")?"""
        if n not in self.norm_nocomma:
            return False                                  # cheap check first; the regex is the slow one
        return re.search(r"(?<![\d.])" + re.escape(n) + r"(?!\d|\.\d)", self.norm_nocomma) is not None

    def near_miss(self, number, context=""):
        """A decimal-shift twin of the number that IS in the document — "3.7" for "3.07",
        the usual speech-to-text slip in a Motley Fool transcript. Only money-style figures
        qualify ("$3.07", "8.97B"): a percentage's twin ("10.06" for "10.6%") proves nothing.
        The twin must stand alone as a number (and keep the figure's "$" if it had one).
        Returns the twin or None."""
        n = number.replace(",", "")
        if "." not in n:
            return None
        dollar = bool(re.search(r"\$\s?" + re.escape(number) + r"(?![\d,])", context or ""))
        if not dollar and figure_unit(context, number)[1] != "amount":
            return None
        whole, frac = n.split(".", 1)
        twins = [whole + ".0" + frac]                       # 3.7  -> 3.07
        if frac.startswith("0") and len(frac) >= 2:
            twins.insert(0, whole + "." + frac[1:])         # 3.07 -> 3.7
        for twin in twins:
            pat = r"(?<![\d.])" + (r"\$\s?" if dollar else "") + re.escape(twin) + r"(?!\d|\.\d)"
            if re.search(pat, self.norm_nocomma):
                return twin
        return None

    def _values(self):
        """Every number in the document as a float — the raw tokens, plus Korean-unit
        amounts ("408.9억원" -> 40,890,000,000) and amounts in words ("6 thousand" -> 6000).
        Parsed once and cached."""
        if not hasattr(self, "_vals"):
            vals = set()
            for m in NUMBER.findall(self.norm):
                v = parse_number(m)
                if v is not None:
                    vals.add(v)
            for m in KO_AMOUNT.finditer(self.norm):
                v = parse_number(m.group(1))
                if v is None:
                    continue
                total = v * KO_UNITS[m.group(2)]
                vals.add(total)
                if m.group(3):                                   # "27조 8,000억" -> 27.8 trillion
                    v2 = parse_number(m.group(3))
                    if v2 is not None:
                        vals.add(total + v2 * KO_UNITS[m.group(4)])
            for m in WORD_AMOUNT.finditer(self.norm):
                head = m.group(1)
                v = 0.5 if head.startswith("half") else 1.0 if head == "a" else parse_number(head)
                if v is not None:
                    vals.add(v * WORD_UNITS[m.group(2)])
            self._vals = vals
            self._sorted = sorted(vals)
        return self._vals

    def _has_value_between(self, lo, hi):
        """Any document value in [lo, hi]? Sorted values + bisect make this O(log n)."""
        self._values()
        eps = 1e-9 * max(1.0, abs(hi))
        i = bisect.bisect_left(self._sorted, lo - eps)
        return i < len(self._sorted) and self._sorted[i] <= hi + eps

    def _sig_map(self):
        """significant digits -> the powers of ten they appear at: {"22": {4}} for "220,000"."""
        if not hasattr(self, "_sigs"):
            sigs = defaultdict(set)
            for v in self._values():
                s, p = sig_exp(v)
                if s:
                    sigs[s].add(p)
            self._sigs = sigs
        return self._sigs


_WORD_PATTERNS = {}


def _word_pattern(name, case_sensitive):
    """Compiled whole-word regex for a name (letters/digits may not touch it on either side).
    Case-sensitive patterns accept the name as written and in capitals ("Arm" / "ARM")."""
    key = (name, case_sensitive)
    if key not in _WORD_PATTERNS:
        forms = [name] + ([name.upper()] if case_sensitive and name.upper() != name else [])
        body = "|".join(re.escape(f) for f in forms)
        _WORD_PATTERNS[key] = re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % body,
                                         0 if case_sensitive else re.I)
    return _WORD_PATTERNS[key]


_METADATA = None
_KNOWN = None
_FIRST_WORDS = None
_VARIANTS = {}


def metadata():
    """company_metadata.json (the universe), read once; {} when it is missing."""
    global _METADATA
    if _METADATA is None:
        try:
            with open(METADATA_PATH, encoding="utf-8") as f:
                _METADATA = json.load(f)
        except (OSError, ValueError):
            _METADATA = {}
    return _METADATA


def _first_word(name):
    words = re.findall(r"[A-Za-z0-9]+", name)
    return words[0].lower() if words else ""


def known_companies():
    """normalised name -> its (normalised) first word, for every company in the universe.
    Used to tell a file about Samsung Electro-Mechanics from one about Samsung."""
    global _KNOWN, _FIRST_WORDS
    if _KNOWN is None:
        _KNOWN = {}
        for name in metadata():
            _KNOWN[normalize_company(name)] = _first_word(name)
            _KNOWN[re.sub(r"[^a-z0-9]", "", name.lower())] = _first_word(name)   # un-aliased spelling too
        counts = Counter(_first_word(n) for n in metadata())
        _FIRST_WORDS = {w for w, c in counts.items() if c >= 2}                    # shared first words
    return _KNOWN


def ambiguous_first_words():
    known_companies()
    return _FIRST_WORDS


def ticker_aliases(company):
    """A US company's 4-5 letter ticker (transcripts say "NVDA", "AVGO"). Shorter tickers and
    non-US ones collide with ordinary words / Asian stock codes, so they are left out."""
    info = metadata().get(company) or {}
    ticker = str(info.get("ticker") or "")
    if info.get("exchange") in ("NASDAQ", "NYSE") and re.fullmatch(r"[A-Z]{4,5}", ticker) and ticker != "FORM":
        return [ticker]
    return []


def name_variants(company):
    """Every spelling that counts as naming this node, as (text, explicit) pairs. `explicit`
    marks aliases listed by hand (they may be as short as 2 letters: "TI", "GE")."""
    if company not in _VARIANTS:
        variants = [(company, False)]
        m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", company)         # "Korea AI Computing Center (KOACC)"
        if m:
            variants += [(m.group(1), False), (m.group(2), True)]
        variants += [(a, True) for a in KO_ALIASES.get(company, ())]
        variants += [(t, True) for t in ticker_aliases(company)]
        words = company.split()
        if len(words) >= 2:                                        # "Vistra Corp" -> "Vistra"
            first = words[0].strip(",.")
            fk = compact(first)
            if len(fk) >= 3 and fk not in COMMON_WORDS and fk not in ambiguous_first_words():
                variants.append((first, False))
        seen, out = set(), []
        for text, explicit in variants:
            if text and text not in seen:
                seen.add(text)
                out.append((text, explicit))
        _VARIANTS[company] = out
    return _VARIANTS[company]


# ---------------------------------------------------------------------------
# 3. Load every source document once
# ---------------------------------------------------------------------------

def load_documents():
    """Read every txt under transcripts/ and supply_contracts/ into Doc objects.

    Returns (by_label, all_docs). by_label maps a source label -> the first Doc that
    declares it (a document may declare its label in several spellings; all are indexed).
    supply_contracts files hold several filings separated by ==== lines; each becomes
    its own Doc so a contract label points at exactly the filing it came from.
    """
    by_label = {}
    all_docs = []
    for pattern in DOC_GLOBS:
        for path in sorted(glob.glob(pattern, recursive=True)):
            with open(path, encoding="utf-8", errors="replace") as f:
                raw = f.read()
            blocks = re.split(r"^={20,}\s*$", raw, flags=re.M) if path.startswith("supply_contracts") else [raw]
            for block in blocks:
                if not block.strip():
                    continue
                labels = header_labels(block)
                doc = Doc(path, block, labels[0] if labels else None)
                doc.labels = labels
                all_docs.append(doc)
                for lab in labels:
                    by_label.setdefault(lab, doc)
    return by_label, all_docs


# ---------------------------------------------------------------------------
# 4. Label -> document(s)
# ---------------------------------------------------------------------------

# Filename tokens that mean the same company as the label's name (both directions).
# agent/corpus.py's alias table covers nvda / alphabet / amkor / ase / arm / onto / ttm / aaoi.
FILE_ALIASES = {
    "stmicroelectronics": {"stm"}, "mksinstruments": {"mks"}, "tokyoohkakogyo": {"tok"},
    "aehrtestsystems": {"aehr"}, "tokyoelectron": {"tel"}, "mitsubishigaschemical": {"mgc"},
    "goldmansachs": {"gs"}, "applieddigital": {"apld"}, "hanmisemiconductor": {"hanmisemi"},
    "samsungelectromechanics": {"semco", "samsungelectro"}, "shinetsuchemical": {"shinetsu"},
}
# Nodes whose source documents are their parent's filings.
SUBSIDIARY_OF = {"samsungfoundry": "samsung", "intelfoundry": "intel", "navercloud": "naver"}
MONTH_TOKEN = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*20\d\d$")


def company_rank(label_company, file_token):
    """How well a filename's company token names the label's company.
       3  the same token / a known alias         (samsung <-> samsung, tel <-> Tokyo Electron)
       2  the token is the leading part of the label's name  (hyosung_heavy -> Hyosung Heavy Industries)
       1  the label's name is the leading part of the token  (amazon_aws -> Amazon; a companion file)
       0  a different company — including the traps: 'samsung' is NOT Samsung Electro-Mechanics,
          'applied_digital' is NOT Applied Materials, 'lumen' is NOT Lumentum, 'nanya' is NOT Nan Ya PCB.
    """
    L = normalize_company(label_company)
    F = normalize_company(file_token)
    if not L or not F:
        return 0
    if F == L or F in FILE_ALIASES.get(L, ()):
        return 3
    if SUBSIDIARY_OF.get(L) == F:
        return 2
    known = known_companies()
    if len(F) >= 4 and L.startswith(F) and len(F) >= len(_first_word(label_company)):
        # 'samsung' also names Samsung itself, 'nanya' also names Nanya Technology: ambiguous.
        if any(K != L and (K == F or first == F) for K, first in known.items()):
            return 0
        return 2
    if len(L) >= 4 and F.startswith(L):
        # 'samsung_electro' belongs to Samsung Electro-Mechanics, not to Samsung.
        if any(K != L and (K.startswith(F) or (F.startswith(K) and len(K) > len(L))) for K in known):
            return 0
        return 1
    return 0


def label_company(label):
    """'Broadcom Q2 FY2026 (06-03-2026)' -> 'broadcom'; 'Goldman Sachs optical note (…)' -> 'goldmansachs…'."""
    head = re.split(r"\s+(Q[1-4]\s+FY|DART|GTC|Computex|\(|note)", label)[0]
    return normalize_company(head)


def _filename_matches(label, all_docs):
    """Documents whose FILENAME joins to an earnings label, best first: the call itself, then
    its companions (release, Q&A, deck) for the same company, quarter and date."""
    m = LABEL_Q.match(label)
    if not m:
        return []
    q, y, company = int(m.group("q")), int(m.group("y")), m.group("company")
    dm = LABEL_DATE.search(label)
    label_date = dm.group(1) if dm else None
    ranked = []
    for d in all_docs:
        if d.quarter != q or d.year != y:
            continue
        rank = company_rank(company, d.company_token)
        if rank == 0:
            continue
        # A file that states a different date is a different document: the 08-07 잠정실적
        # and the 08-14 half-year report share "Q2 FY2026" but are not companions.
        own = d.declared_date()
        if label_date and own and own != label_date:
            continue
        ranked.append((-rank, 0 if d.is_full_transcript else 1, d.path, d))
    return [d for *_, d in sorted(ranked, key=lambda t: t[:3])]


def _event_matches(label, all_docs):
    """Loose match for events / notes: every non-date token of the file stem must appear in
    the label, and the first token must name the label's company.
        nvda_gtc_taipei_2026.txt  <->  "NVIDIA GTC Taipei 2026 (06-01-2026)"
    Earnings-style files (with a q<N>/fy<year> token) never serve an event label."""
    head = re.split(r"\s+\(", label)[0]
    words = head.split()
    lab = compact(label)
    hits = []
    for d in all_docs:
        if d.quarter is not None or d.path.startswith("supply_contracts/"):
            continue
        tokens = d.stem.split("_")
        if not tokens:
            continue
        if not any(company_rank(" ".join(words[:k]), tokens[0]) >= 2 for k in range(len(words), 0, -1)):
            continue
        rest = [t for t in tokens[1:] if not re.fullmatch(r"(fy)?20\d\d|q[1-4]", t) and not MONTH_TOKEN.match(t)]
        if rest and all(t in lab for t in rest):
            hits.append(d)
    return hits


def resolve_label_docs(label, by_label, all_docs, filename_docs=None, cache=None):
    """Every document a source label refers to — the primary one first, then its companions.
    Empty list when nothing on disk matches. Strategies, in order:
      1. a document that DECLARES the label in its header (any spelling);
      2. filename join for earnings labels (company + quarter + year, same date);
      3. loose event-name match for events / notes.
    A DART supply-contract label only ever resolves through its block header (1).
    `filename_docs` (agent/corpus.py's index) is accepted for compatibility; the filename
    facts now live on each Doc."""
    key = ("docs", label)
    if cache is not None and key in cache:
        return cache[key]
    docs = [d for d in all_docs if label in d.labels]
    if "DART supply contract" not in label:
        for d in _filename_matches(label, all_docs) + _event_matches(label, all_docs):
            if d not in docs:
                docs.append(d)
    if cache is not None:
        cache[key] = docs
    return docs


def resolve_label(label, by_label, all_docs, filename_docs, cache):
    """Find the ONE best Doc a source label refers to, or None (the first of
    resolve_label_docs). Kept for evidence.py, which locates passages in a single file."""
    if label in cache:
        return cache[label]
    docs = resolve_label_docs(label, by_label, all_docs, filename_docs, cache)
    doc = docs[0] if docs else None
    cache[label] = doc
    return doc


# ---------------------------------------------------------------------------
# 5. Per-entry checks
# ---------------------------------------------------------------------------

FIELD_NUMBER = re.compile(r"(?<![A-Za-z\d.,])\d[\d,]*(?:\.\d+)?")   # not the "27" of "FY27" or "9680" of "XE9680"


def numbers_in(*fields):
    """Pull every number out of the free-text fields ('$107M', '45%', '27조 8,000억원').

    Years (2020-2039), single digits, the pieces of a date ("06-30-2026") and digits glued
    to a word ("FY27", "Q2", "XE9680") are skipped — they are labels, not figures.
    """
    found = []
    for field in fields:
        if not field or not isinstance(field, str):
            continue
        for n in FIELD_NUMBER.findall(DATE_IN_FIELD.sub(" ", field)):
            bare = n.replace(",", "")
            if re.fullmatch(r"20[2-3]\d", bare) or len(bare) < 2:
                continue
            found.append(n)
    return list(dict.fromkeys(found))   # dedupe, keep order


def derived_from(number, others):
    """Is `number` transparent arithmetic on the field's OTHER numbers (ones the document
    does contain)? A sum of 2-4 of them ("67.6 + 79.0 + 88.3 = 234.9"), a share in percent
    ("9.2 / 28.0 = 32.8%"), a growth rate, a difference, or a plain ratio ("12.9x").
    Returns the expression, or None. Such a figure is CONSISTENT with the source but not IN
    it, so the entry is reported as a warn (number_derived), never as a pass."""
    from itertools import combinations, permutations
    x = parse_number(number)
    if x is None or len(significant_digits(number)) < 2:
        return None
    n = number.replace(",", "")
    decimals = len(n.split(".")[1]) if "." in n else 0
    tol = 0.5 * 10 ** -decimals + 1e-9
    vals = [(o, parse_number(o)) for o in others if o != number]
    vals = [(o, v) for o, v in vals if v is not None and len(significant_digits(o)) >= 2]
    # Sums of any 2..n terms when the field is short ("13.03B + 14.52B + … + 19.4B = 151.9B"),
    # of at most 4 terms otherwise (keeps the subset count small).
    for size in range(2, (len(vals) if len(vals) <= 10 else 4) + 1):
        for combo in combinations(vals, size):
            if abs(sum(v for _, v in combo) - x) <= tol:
                return " + ".join(o for o, _ in combo)
    for (oa, a), (ob, b) in permutations(vals, 2):
        if b == 0:
            continue
        if abs(a / b * 100 - x) <= tol:
            return f"{oa} / {ob} x 100"
        if abs((a / b - 1) * 100 - x) <= tol:
            return f"({oa} / {ob} - 1) x 100"
        if x >= 1 and abs(a / b - x) <= tol:
            return f"{oa} / {ob}"
        if abs(a - b - x) <= tol:
            return f"{oa} - {ob}"
    return None


def check_entry(label, docs, fields, counterparty=None):
    """Run SOURCE / NUMBERS / PARTY / HYGIENE on one entry against its document(s);
    return (verdict, issues, detail). `docs` is the list from resolve_label_docs."""
    issues = []
    detail = {}

    # HYGIENE
    all_text = " ".join(v for v in fields.values() if isinstance(v, str)) + " " + label
    if KOREAN.search(all_text):
        issues.append("korean_characters")
    if not (LABEL_EARNINGS.match(label) or LABEL_OTHER.match(label)):
        issues.append("label_format")

    # SOURCE
    if not docs:
        issues.append("source_not_found")
        return "fail", issues, detail
    detail["doc"] = docs[0].path
    if len(docs) > 1:
        detail["docs"] = [d.path for d in docs]

    # NUMBERS — against the union of the companion documents
    context = " | ".join(str(fields.get(k) or "") for k in ("figure", "units", "value"))
    nums = numbers_in(fields.get("figure"), fields.get("units"), fields.get("value"))
    detail["numbers"] = nums
    missing = [n for n in nums if not any(d.has_number(n, context) for d in docs)]
    near, derived = {}, {}
    found = [n for n in nums if n not in missing]
    for n in missing:
        twin = next((t for t in (d.near_miss(n, context) for d in docs) if t), None)
        if twin:
            near[n] = twin
            continue
        expr = derived_from(n, found)
        if expr:
            derived[n] = expr
    if missing:
        still_missing = [n for n in missing if n not in near and n not in derived]
        if still_missing:
            issues.append("number_not_in_source")
            detail["numbers_missing"] = still_missing
        else:
            if near:
                issues.append("number_near_miss")
            if derived:
                issues.append("number_derived")
        if near:
            detail["numbers_near_miss"] = near
        if derived:
            detail["numbers_derived"] = derived

    # PARTY (edges only)
    if counterparty is not None:
        if any(d.mentions(counterparty) for d in docs):
            detail["counterparty"] = "mentioned"
        else:
            issues.append("counterparty_not_in_source")
            detail["counterparty"] = "not_found"

    if "korean_characters" in issues or "number_not_in_source" in issues:
        return "fail", issues, detail
    if issues:
        return "warn", issues, detail
    if not nums and counterparty is None:
        return "unchecked", issues, detail
    return "pass", issues, detail


# ---------------------------------------------------------------------------
# 6. Per-edge corroboration
# ---------------------------------------------------------------------------

def corroborate(edge, docs_by_company, resolved):
    """Classify an edge's evidence: two_sided / multi_source / single_source / no_contracts."""
    contracts = edge.get("contracts", [])
    if not contracts:
        return "no_contracts", {}
    a, b = edge["source"], edge["target"]
    a_docs = docs_by_company.get(normalize_company(a), [])
    b_docs = docs_by_company.get(normalize_company(b), [])
    a_says_b = any(d.mentions(b) for d in a_docs)
    b_says_a = any(d.mentions(a) for d in b_docs)
    source_companies = {label_company(c.get("source", "")) for c in contracts}
    detail = {"a_docs": len(a_docs), "b_docs": len(b_docs),
              "a_mentions_b": a_says_b, "b_mentions_a": b_says_a,
              "source_companies": sorted(source_companies)}
    if a_says_b and b_says_a:
        return "two_sided", detail
    if len(source_companies) >= 2:
        return "multi_source", detail
    return "single_source", detail


def index_docs_by_company(all_docs, node_names):
    """Map each graph node -> the documents that are ABOUT that company.

    A document is 'about' a company when its header label or filename names that company
    (company_rank >= 1). This is what makes the two_sided check independent: it only uses
    what a company said in its OWN filings, not what others said about it.
    """
    index = defaultdict(list)
    for doc in all_docs:
        token = label_company(doc.label) if doc.label else doc.company_token
        for name in node_names:
            if company_rank(name, token) >= 1:
                index[normalize_company(name)].append(doc)
    return index


# ---------------------------------------------------------------------------
# 7. Main
# ---------------------------------------------------------------------------

def _print_entry(e, indent="        "):
    """One fail/warn entry on the console: what is wrong, which file(s) were checked."""
    who = e["company"] + (" -> %s" % e["target"] if e.get("target") else "")
    extra = ""
    if e.get("numbers_missing"):
        extra += "  missing=%s" % e["numbers_missing"]
    if e.get("numbers_near_miss"):
        extra += "  near_miss=%s" % e["numbers_near_miss"]
    if e.get("numbers_derived"):
        extra += "  derived=%s" % e["numbers_derived"]
    print("[%s] %s | %s | %s%s" % (e["verdict"], who, e["label"], ", ".join(e["issues"]), extra))
    if e.get("doc"):
        more = "  (+%d companion%s)" % (len(e["docs"]) - 1, "s" if len(e["docs"]) > 2 else "") if e.get("docs") else ""
        print("%sdoc: %s%s" % (indent, e["doc"], more))
    print("%s%s" % (indent, e["signal"]))


def run(company_filter=None, label_filter=None, labels=None):
    """labels: optional list — check only entries whose source label is in it
    (graph_build.py passes the labels of the patches it just applied)."""
    with open(GRAPH_PATH, encoding="utf-8") as f:
        graph = json.load(f)

    by_label, all_docs = load_documents()
    filename_docs = list_documents()          # agent/corpus.py filename index (kept for evidence.py parity)
    node_names = [n["id"] for n in graph["nodes"]]
    docs_by_company = index_docs_by_company(all_docs, node_names)
    cache = {}

    def wanted(company, label):
        if company_filter and compact(company_filter) not in compact(company):
            return False
        if label_filter and label_filter != label:
            return False
        if labels is not None and label not in labels:
            return False
        return True

    entries = []
    # Node-level: quarterly_data
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            label = q.get("quarter", "")
            if not wanted(node["id"], label):
                continue
            docs = resolve_label_docs(label, by_label, all_docs, filename_docs, cache)
            verdict, issues, detail = check_entry(label, docs, q)
            entries.append({"kind": "quarterly_data", "company": node["id"], "label": label,
                            "signal": (q.get("signal") or "")[:140], "figure": q.get("figure"),
                            "verdict": verdict, "issues": issues, **detail})
    # Edge-level: contracts
    edge_reports = []
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        for c in edge.get("contracts", []):
            label = c.get("source", "")
            if not wanted(a, label) and not wanted(b, label):
                continue
            docs = resolve_label_docs(label, by_label, all_docs, filename_docs, cache)
            # Which side is the document about? The check looks for the OTHER one.
            doc_company = label_company(label)
            other = b if normalize_company(a)[:5] == doc_company[:5] else a
            verdict, issues, detail = check_entry(label, docs, c, counterparty=other)
            entries.append({"kind": "contract", "company": a, "target": b, "label": label,
                            "signal": (c.get("signal") or "")[:140], "value": c.get("value"),
                            "verdict": verdict, "issues": issues, **detail})
        if edge.get("contracts") and (wanted(a, "") or wanted(b, "")) and not label_filter and labels is None:
            tier, detail = corroborate(edge, docs_by_company, cache)
            edge_reports.append({"source": a, "target": b, "chain": edge.get("chain"),
                                 "relationship": edge.get("relationship"),
                                 "contracts": len(edge["contracts"]), "tier": tier, **detail})

    # Which labels never resolved — the single most actionable list
    unresolved = sorted({e["label"] for e in entries if "source_not_found" in e["issues"]})

    summary = {
        "entries_checked": len(entries),
        "verdicts": dict(Counter(e["verdict"] for e in entries)),
        "issues": dict(Counter(i for e in entries for i in e["issues"])),
        "edges_with_contracts": len(edge_reports),
        "edge_tiers": dict(Counter(r["tier"] for r in edge_reports)),
        "unresolved_labels": unresolved,
        "documents_indexed": len(all_docs),
        "labels_with_companions": len({e["label"] for e in entries if e.get("docs")}),
    }
    return summary, entries, edge_reports


def verify_labels(labels):
    """Post-enrichment gate, called by graph_build.py right after a build.

    Checks ONLY the entries that came from `labels` (the patches just applied) and
    prints every fail/warn so the enrichment job can fix its own patch while the
    transcript is still open. Returns the number of failing entries.
    """
    summary, entries, _ = run(labels=labels)
    print("\nverify_graph — %d new entr%s from %d label(s): %s" % (
        summary["entries_checked"], "y" if summary["entries_checked"] == 1 else "ies",
        len(labels), summary["verdicts"]))
    for e in entries:
        if e["verdict"] in ("fail", "warn"):
            _print_entry(e, indent="          ")
    return summary["verdicts"].get("fail", 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", help="only entries touching this company (substring)")
    ap.add_argument("--label", help="only entries with exactly this source label")
    ap.add_argument("--fails", action="store_true", help="print every fail/warn entry")
    args = ap.parse_args()

    summary, entries, edges = run(args.company, args.label)

    if not args.company and not args.label:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "entries": entries, "edges": edges}, f,
                      ensure_ascii=False, indent=1)

    print(f"documents indexed : {summary['documents_indexed']}")
    print(f"entries checked   : {summary['entries_checked']}   {summary['verdicts']}")
    print(f"issues            : {summary['issues']}")
    print(f"edges w/ contracts: {summary['edges_with_contracts']}   {summary['edge_tiers']}")
    print(f"labels w/ companions: {summary['labels_with_companions']}")
    if summary["unresolved_labels"]:
        print(f"\nunresolved labels ({len(summary['unresolved_labels'])}) — no source file on disk:")
        for lab in summary["unresolved_labels"]:
            print(f"  - {lab}")
    if args.fails or args.company or args.label:
        print()
        for e in entries:
            if e["verdict"] in ("fail", "warn"):
                _print_entry(e)
    if not args.company and not args.label:
        print(f"\nreport → {REPORT_PATH}")
    sys.exit(1 if summary["verdicts"].get("fail") else 0)


if __name__ == "__main__":
    main()
