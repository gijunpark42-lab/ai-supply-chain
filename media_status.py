"""News-interview transcripts waiting for enrich (enrich skill section 11).

media_pull.py saves interview transcripts to transcripts/media/*.txt. When the enrich coordinator has read one, it
appends a line to media/enriched.jsonl ({"label", "date", "entries", "why"}). This script lists the transcripts whose
source label is not in that file yet. It prints labels only, never paths or text (user rule 2026-10-17: nothing of
these transcripts may be shown on the website).

It lives in its own file, not in enrich_status.py, so the status board script stays untouched (2026-10-17).

CLI:  python -X utf8 media_status.py          one label per line, then a count
      python -X utf8 media_status.py --json   {"waiting": [labels]}
"""
import glob
import json
import os
import re
import sys

MEDIA_DIR = os.path.join("transcripts", "media")
MEDIA_ENRICHED = os.path.join("media", "enriched.jsonl")


def media_waiting():
    """Source labels of transcripts/media/*.txt that are not yet in media/enriched.jsonl."""
    done = set()
    try:
        with open(MEDIA_ENRICHED, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line).get("label"))
                except ValueError:
                    continue                      # a broken line never hides the rest
    except OSError:
        pass
    waiting = []
    for path in sorted(glob.glob(os.path.join(MEDIA_DIR, "*.txt"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            m = re.search(r"(?m)^# source label:\s*(.+?)\s*$", f.read(600))
        if m and m.group(1) not in done:
            waiting.append(m.group(1))
    return waiting


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))      # paths are relative to the repo root
    items = media_waiting()
    if "--json" in sys.argv:
        print(json.dumps({"waiting": items}, ensure_ascii=False))
    else:
        for label in items:
            print(label)
        print(f"{len(items)} news-interview transcript(s) waiting")
