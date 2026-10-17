"""
utils/transcript_quality.py -- find saved call transcripts that are not what their header says.

Why (user, 2026-10-17): a few transcripts were saved as condensed notes even though their header says
"FULL transcript", and some verbatim pastes lost their speaker labels. An enricher reading such a file
cannot quote management verbatim or tell an analyst's question from a CFO's answer. This script finds
them so the nightly enrich run can re-fetch a proper copy (see .claude/skills/enrich/SKILL.md).

Two checks, script-only (no model tokens, no network):
  (a) "condensed"  the header claims a full / verbatim transcript, but the body is notes: bracketed
                   "[Speaker — role]" summaries, "Q&A highlights", "KEY FACTS" sections, mostly bullet
                   lines, and far smaller than the same company's other calls.
  (b) "no speaker labels"  a verbatim-sized call transcript whose body never says who is speaking
                   (no "Name:" lines, no name-on-its-own-line turns), or whose Q&A section has no labels
                   even though the prepared remarks do.
Files whose header already says "no speaker labels" (the Taiwan speech-to-text files) are skipped for (b),
and filings / press releases / slide decks are not call transcripts, so they are skipped too.

Output: graph/transcript_quality.json
  {"updated": "YYYY-MM-DD", "scanned": N,
   "flagged": [{"path", "label", "problem", "suggestion"}]}
and one summary line on stdout.

Usage (from the repo root):
    python -X utf8 utils/transcript_quality.py
"""

import datetime as dt
import json
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS = ROOT / "transcripts"
OUT_FILE = ROOT / "graph" / "transcript_quality.json"

# Folders that hold earnings calls and event transcripts. The others (edgar, dart, mops, ir, tdnet, ...)
# hold filings and press releases, which have no speakers by nature.
CALL_FOLDERS = {"accelerators", "av", "bigtech", "conferences", "equipment", "foundry", "investing",
                "kr_calls", "memory", "optical", "packaging", "power", "systems", "tw"}

# ---------------------------------------------------------------- patterns

# The header claims a complete call ("FULL transcript", "verbatim", "complete live Q&A", "transcript paste").
CLAIM = re.compile(
    r"\bfull\s+(?:earnings\s+|conference\s+)?(?:call\s+)?transcript\b"
    r"|\bverbatim\s+(?:call\s+)?transcript\b"
    r"|\bcomplete\s+(?:live\s+)?Q&A\b"
    r"|\btranscript\s+paste\b"
    r"|\bfull\s+transcript\b",
    re.I)
# ... unless the words are negated ("Motley Fool had not published the full transcript").
NEGATION = re.compile(r"(?:\bnot\b|\bno\b|n't\b|\bnon-|\bwithout\b)[^.\n]{0,30}$", re.I)

# Header says the document is something other than a call transcript (or has no speakers on purpose).
NOT_A_CALL = re.compile(
    r"earnings release|press release|Form \d+-K|Exhibit 99|presentation material"
    r"|keynote summary|shareholder letter|fact sheet|slide deck|\bslides\b",
    re.I)
# "Prepared remarks" alone is a call document without Q&A (Micron's official PDF) only when the title line says so
# or the header says the Q&A is missing; "prepared remarks + live Q&A" is a whole call.
PREPARED_ONLY = re.compile(r"Q&A (?:is )?not included|\bno (?:live )?Q&A\b", re.I)
NO_LABELS_DECLARED = re.compile(r"no speaker labels|speech-to-text|faster-whisper|machine transcription", re.I)

# Condensed-notes markers.
BRACKET_SPEAKER = re.compile(r"^\s*\[[^\]\n]{2,80}\s(?:—|–|--|-)\s[^\]\n]{1,60}\]\s*$", re.M)   # [Satya Nadella — CEO]
SECTION_MARKERS = re.compile(                                        # headings only notes have (upper case)
    r"^\s*\[?Q&A [Hh]ighlights\]?|^\s*(?:=+\s*)?KEY (?:CONTENT|FACTS|FINANCIALS|POINTS|TAKEAWAYS)\b"
    r"|^\s*={3}\s*(?:PREPARED REMARKS|Q&A|KEY)[^=\n]*={3}",
    re.M)
BULLET = re.compile(r"^\s*(?:[-•*–]|\d+[.)])\s+\S")

# Speaker labels.
NAME = r"[A-Z][\w.'’\-]*(?:\s+(?:[A-Z][\w.'’\-]*|de|van|von|da|del|der|la|le|bin|al|di|du))*"
INLINE_LABEL = re.compile(                                           # "Amy Hood:" / "Operator:" / "Jean Hu, CFO, AMD:"
    r"^\s*(?:\*\*)?(?P<name>(?:Unidentified|Unknown) (?:speaker|analyst|participant|company representative)|" + NAME + r")(?:\s*\([^)\n]{1,80}\))?(?:\s*,\s*[^:\n]{1,100})?(?:\*\*)?\s*:\s+\S")
STANDALONE_LABEL = re.compile(                                       # "Park Seong-Hwan" / "Jeff Su - TSMC - Director"
    r"^\s*(?P<name>" + NAME + r")(?:\s*(?:—|–|--|-|,|\()\s*[^.!?\n]{0,110})?\s*$")
QA_LABEL = re.compile(r"^\s*(?:Q|A)\s*(?:[-–—:]|\d+[:.])\s*\S")         # Bloomberg-style "Q - Name" / "A - Name"
BRACKET_ROLE = re.compile(r"^\s*\[(?:Operator|Moderator)\]\s*$")          # "[Operator]" (with "[Name - role]" lines)
# Where the Q&A starts: a heading line ("[Q&A]", "QUESTIONS AND ANSWERS", "Question-and-Answer Session").
QA_HEADING = re.compile(r"^\s*\[?(?:Q\s?&\s?A|Q&A Session|Questions? and Answers?|Question-and-Answer(?: Session)?)\]?:?\s*$",
                        re.I | re.M)
# Capitalised words that start header lines or headings, not speakers.
NOT_NAMES = {"source", "note", "notes", "speakers", "speaker", "participants", "title", "date", "event",
             "company", "quarter", "call", "results", "disclaimer", "agenda", "image", "page", "video",
             "label", "canonical", "operator instructions", "transcript", "prepared remarks", "presentation",
             "questions and answers", "question", "answer", "summary", "highlights", "overview", "outlook",
             "guidance", "copyright", "okay", "thanks", "thank you", "yes", "yeah", "sure", "great", "hi", "hello"}
HEADING_WORDS = re.compile(r"\b(?:Remarks|Questions?|Answers?|Presentation|Participants|Statements|Session|"
                           r"Highlights|Overview|Outlook|Results|Summary|Guidance|Section|Conference|Earnings|"
                           r"Quarter|Fiscal|Transcript|Call|Webcast|Disclaimer|Agenda)\b")

# The source label a file declares about itself (same spellings verify_graph.py reads, plus "Canonical label:").
HEADER_LABEL = re.compile(r"(?im)^\s*(?:#\s*)?(?:canonical\s+)?(?:source\s+)?label(?:\s+used)?"
                          r"(?:\s+(?:for|in)\s+(?:enrichment|chains))?\s*:\s*`?(.+?)`?\s*$")
INLINE_SOURCE_LABEL = re.compile(r"(?i)source label\s*`([^`]+)`")


# ---------------------------------------------------------------- helpers

def today():
    """Pacific date, the same clock the market collectors use."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except Exception:
        return dt.date.today().isoformat()


def call_files():
    """Every .txt in a call folder, plus loose .txt files directly under transcripts/."""
    files = [p for p in TRANSCRIPTS.glob("*.txt")]
    for folder in sorted(CALL_FOLDERS):
        files += sorted((TRANSCRIPTS / folder).rglob("*.txt"))
    return files


def split_header(text):
    """(header, body). Machine-written files end the header with a '---' line; hand-saved ones usually
    start the body after the first blank line. The header is never more than ~40 lines."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:40]):
        if line.strip() == "---":
            return "\n".join(lines[:i]), "\n".join(lines[i + 1:])
    for i, line in enumerate(lines[:15]):
        if i > 0 and not line.strip():
            return "\n".join(lines[:i]), "\n".join(lines[i + 1:])
    return "\n".join(lines[:3]), "\n".join(lines[3:])


def company_key(path):
    """'microsoft_q4_fy2026' -> 'microsoft' (the same company's other calls are compared by this key)."""
    stem = path.stem.lower()
    m = re.match(r"^(.+?)_(?:q[1-4]_|fy\d{4}|\d{4}-\d\d-\d\d)", stem)
    return m.group(1) if m else stem


def claims_full_transcript(header):
    for m in CLAIM.finditer(header):
        before = header[max(0, m.start() - 40):m.start()]
        if not NEGATION.search(before):
            return True
    return False


def is_name(name):
    """A plausible speaker name: has a lowercase letter (not an ALL-CAPS heading), not a header word."""
    n = name.strip()
    return (bool(re.search(r"[a-z]", n)) and n.lower() not in NOT_NAMES
            and n.split()[0].lower() not in {"source", "note", "call", "image", "page"}
            and not HEADING_WORDS.search(n))


def count_speaker_turns(body):
    """How many lines in the body say who is speaking."""
    lines = body.splitlines()
    turns = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        m = INLINE_LABEL.match(s)
        if m and is_name(m.group("name")):
            turns += 1
            continue
        if QA_LABEL.match(s) or BRACKET_SPEAKER.match(s) or BRACKET_ROLE.match(s):
            turns += 1
            continue
        # a name on its own line, followed by what that person said
        if len(s) <= 130 and s[-1] not in ".?!:;\"”" and STANDALONE_LABEL.match(s):
            name = STANDALONE_LABEL.match(s).group("name")
            words = name.split()
            nxt = next((l.strip() for l in lines[i + 1:i + 4] if l.strip()), "")
            if (len(words) >= 2 or name in ("Operator", "Moderator")) and is_name(name) and len(nxt) > 40:
                turns += 1
    return turns


def find_label(header):
    found = HEADER_LABEL.findall(header) + INLINE_SOURCE_LABEL.findall(header)
    for raw in found:
        label = raw.strip().strip("`'\" ").rstrip(".").strip()
        if label:
            return label
    return None


# ---------------------------------------------------------------- the scan

def inspect(path):
    """Read one file and return its measurements."""
    text = path.read_text(encoding="utf-8", errors="replace")
    header, body = split_header(text)
    nonblank = [l for l in body.splitlines() if l.strip()]
    head = header[:1500]                        # what the file says about itself
    claims_full = claims_full_transcript(head)
    first_line = (head.splitlines() or [""])[0].lower()
    qa = QA_HEADING.search(body)
    qa_text = body[qa.end():] if qa else ""
    return {
        "path": path,
        "rel": path.relative_to(ROOT).as_posix(),
        "key": company_key(path),
        "chars": len(body),
        "claims_full": claims_full,
        # a release / slide deck / prepared-remarks document, unless the header also says it is the full call
        "not_a_call": (not claims_full and (bool(NOT_A_CALL.search(head)) or bool(PREPARED_ONLY.search(head))
                                            or ("prepared remarks" in first_line and "q&a" not in first_line)))
                      or "earnings_release" in path.stem,
        "no_labels_declared": bool(NO_LABELS_DECLARED.search(head)),
        "bracket_speakers": len(BRACKET_SPEAKER.findall(body)),
        "section_markers": len(SECTION_MARKERS.findall(body)),
        "bullet_share": (sum(1 for l in nonblank if BULLET.match(l)) / len(nonblank)) if nonblank else 0.0,
        "turns": count_speaker_turns(body),
        "qa_chars": len(qa_text),
        "qa_turns": count_speaker_turns(qa_text) if qa else None,
        "label": find_label(text[:3000]),
    }


def peer_median(info, by_key):
    """Median body size of the same company's OTHER verbatim-looking calls (None when there are none)."""
    sizes = [o["chars"] for o in by_key.get(info["key"], [])
             if o is not info and not o["not_a_call"] and o["bracket_speakers"] < 2 and o["section_markers"] == 0]
    return statistics.median(sizes) if sizes else None


def refetch_hint(info):
    folder = info["rel"].split("/")[1] if info["rel"].count("/") >= 2 else ""
    if folder in ("av", "bigtech", "accelerators", "systems", "optical", "memory", "equipment", "foundry",
                  "packaging", "power"):
        return ("re-fetch a verbatim, speaker-labelled copy (US listings: "
                "`python -X utf8 utils/defeatbeta_fetch.py \"<Name>\" <TICKER> --fy <FY> --q <Q>`, "
                "else the Motley Fool or the company's IR transcript), save it under the same source label, "
                "then re-enrich that label")
    return ("re-fetch a verbatim, speaker-labelled copy (company IR transcript, Investing.com or LSEG), "
            "save it under the same source label, then re-enrich that label")


def scan():
    infos = [inspect(p) for p in call_files()]
    by_key = {}
    for info in infos:
        by_key.setdefault(info["key"], []).append(info)

    flagged = []
    for info in infos:
        median = peer_median(info, by_key)
        small = (info["chars"] < 0.4 * median) if median else info["chars"] < 15000
        notes_like = info["bracket_speakers"] >= 2 or info["section_markers"] >= 1 or info["bullet_share"] >= 0.25
        # an honest set of notes (header does not claim a transcript) is not judged for speaker labels
        mostly_notes = info["section_markers"] >= 2 or info["bullet_share"] >= 0.25

        # (a) header says FULL / verbatim, body is condensed notes
        if info["claims_full"] and notes_like and small:
            signs = []
            if info["bracket_speakers"] >= 2:
                signs.append(f'{info["bracket_speakers"]} bracketed "[Speaker — role]" summaries')
            if info["section_markers"]:
                signs.append("note sections (Q&A highlights / KEY FACTS / KEY CONTENT)")
            if info["bullet_share"] >= 0.25:
                signs.append(f'{info["bullet_share"]:.0%} bullet lines')
            size = (f'{info["chars"]:,} chars vs a median {median:,.0f} for its other calls' if median
                    else f'only {info["chars"]:,} chars')
            flagged.append({
                "path": info["rel"],
                "label": info["label"],
                "problem": "condensed: the header claims a full transcript but the body is notes ("
                           + "; ".join(signs) + f"; {size})",
                "suggestion": refetch_hint(info) + "; keep the condensed file's facts only where the new copy "
                              "confirms them",
            })
            continue

        # (b) a verbatim-sized call transcript that never says who is speaking (or labels only the prepared
        #     remarks and leaves the Q&A unlabelled)
        if info["not_a_call"] or info["no_labels_declared"] or mostly_notes:
            continue
        problem = None
        if info["chars"] >= 8000 and info["turns"] < max(2, info["chars"] / 25000):
            problem = (f'no speaker labels: {info["chars"]:,} chars of call text with {info["turns"]} speaker '
                       "turns marked, so management answers cannot be told apart from analyst questions")
        elif info["qa_chars"] >= 8000 and info["qa_turns"] < max(2, info["qa_chars"] / 25000):
            problem = (f'no speaker labels in the Q&A: {info["qa_chars"]:,} chars after the Q&A heading with '
                       f'{info["qa_turns"]} speaker turns marked (only the prepared remarks are labelled)')
        if problem:
            flagged.append({"path": info["rel"], "label": info["label"], "problem": problem,
                            "suggestion": refetch_hint(info)})
    return infos, flagged


def main():
    infos, flagged = scan()
    out = {"updated": today(), "scanned": len(infos), "flagged": flagged}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, OUT_FILE)                   # atomic: the site never sees half a file
    condensed = sum(1 for f in flagged if f["problem"].startswith("condensed"))
    print(f"transcript_quality: scanned {len(infos)} call transcripts, flagged {len(flagged)} "
          f"({condensed} condensed, {len(flagged) - condensed} missing speaker labels) "
          f"-> {OUT_FILE.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
