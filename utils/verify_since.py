"""Re-verify every label whose patch was applied since a given moment (2026-10-19).

graph_build.py re-verifies only the labels it applies itself. When a build is killed after its apply step (low
memory, 2026-10-14 / 10-17 / 10-18), the next build has nothing left to apply and so verifies nothing. This closes
that gap: routine/nightly.ps1 runs it after its own rebuild of such a night, and a coordinator can run it by hand.

    python -X utf8 utils/verify_since.py "2026-10-18 23:00"

It prints every [fail] / [warn] entry (verify_graph.verify_labels) and exits 1 when any entry fails, else 0.
The label of a patch is its "source" field; the receipts are in patches/applied/ (a patch keeps the time it was
written when apply_patches.py moves it there).
"""
import glob
import json
import os
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)                     # verify_graph reads chains/, graph/ and transcripts/ by relative path
sys.path.insert(0, REPO)
from verify_graph import verify_labels  # noqa: E402  (needs the repo on sys.path first)


def labels_since(moment):
    """Source labels of the receipts in patches/applied/ written at or after `moment`, oldest first."""
    labels = []
    for path in sorted(glob.glob(os.path.join("patches", "applied", "*.json")), key=os.path.getmtime):
        if datetime.fromtimestamp(os.path.getmtime(path)) < moment:
            continue
        with open(path, encoding="utf-8") as f:
            label = json.load(f).get("source")
        if label and label not in labels:
            labels.append(label)
    return labels


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    moment = datetime.strptime(argv[0], "%Y-%m-%d %H:%M")
    labels = labels_since(moment)
    if not labels:
        print("no patch applied since %s - nothing to verify" % argv[0])
        return 0
    fails = verify_labels(labels)
    print("verify_since %s: %d label(s), %d failing entr%s" % (argv[0], len(labels), fails, "y" if fails == 1 else "ies"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
