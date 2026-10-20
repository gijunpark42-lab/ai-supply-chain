"""The nightly worker pool's memory of who did what (user, 2026-10-19: "똑같은 에이전트한테 계속 시키면 안돼?
에이전트 갯수만 늘어나고 서로 어디까지 했는지 기억을 못해").

The nightly coordinator starts a FIXED pool of workers (as many as utils/agent_budget.py allows) and keeps
handing new work to the same workers. This file records every hand-out and every finish, so that
  - the coordinator still knows each worker's progress after its own context is compacted, and
  - the next night starts with whatever this night left unfinished ("carry over").

Items are short free-text names of one unit of work, e.g. "ir:Adobe 2026-10-15", "call:NVIDIA Q3 FY2027",
"gap:Foxconn/ir", "verify:TSMC Q3 FY2026 (10-15-2026)".

    python -X utf8 utils/work_ledger.py start                      new night: unfinished items -> carry_over
    python -X utf8 utils/work_ledger.py assign W1 "ir:Adobe 2026-10-15" "call:NVIDIA Q3 FY2027"
    python -X utf8 utils/work_ledger.py done W1 "ir:Adobe 2026-10-15"
    python -X utf8 utils/work_ledger.py show                       per worker: done / left; the carry-over list

The ledger lives in .claude/nightly/ledger.json (gitignored: it is working state of this computer's routine,
not data); the previous nights are kept in .claude/nightly/ledger_history.jsonl.
"""
import json
import os
import sys
from datetime import datetime

LEDGER = os.path.join(".claude", "nightly", "ledger.json")
HISTORY = os.path.join(".claude", "nightly", "ledger_history.jsonl")


def load():
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            return json.load(f)
    return {"night": None, "carry_over": [], "workers": {}}


def save(ledger):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=1)


def unfinished(ledger):
    """Items handed out (or carried over) but never finished, in hand-out order."""
    done = {item for w in ledger["workers"].values() for item in w["done"]}
    left = [item for item in ledger["carry_over"] if item not in done]
    for w in ledger["workers"].values():
        left += [item for item in w["assigned"] if item not in done and item not in left]
    return left


def main(argv):
    if not argv or argv[0] not in ("start", "assign", "done", "show"):
        print(__doc__)
        return 1
    ledger = load()
    cmd = argv[0]
    if cmd == "start":
        # Keep last night's ledger as history, then begin a new one with its unfinished items first.
        if ledger["night"]:
            os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
            with open(HISTORY, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger, ensure_ascii=False) + "\n")
        carry = unfinished(ledger)
        ledger = {"night": datetime.now().strftime("%Y-%m-%d %H:%M"), "carry_over": carry, "workers": {}}
        print("new night %s; %d unfinished item(s) carried over%s" % (
            ledger["night"], len(carry), ": " + "; ".join(carry[:20]) if carry else ""))
    elif cmd in ("assign", "done"):
        if len(argv) < 3:
            print("usage: work_ledger.py %s <worker> <item> [<item> ...]" % cmd)
            return 1
        worker = ledger["workers"].setdefault(argv[1], {"assigned": [], "done": []})
        key = "assigned" if cmd == "assign" else "done"
        for item in argv[2:]:
            if item not in worker[key]:
                worker[key].append(item)
        print("%s %s: %d item(s)" % (argv[1], key, len(argv) - 2))
    else:  # show
        print("night %s" % ledger["night"])
        for name, w in sorted(ledger["workers"].items()):
            left = [i for i in w["assigned"] if i not in w["done"]]
            print("  %s: %d done, %d left%s" % (name, len(w["done"]), len(left), " -> " + "; ".join(left) if left else ""))
        print("  unfinished overall (carry-over first): %d" % len(unfinished(ledger)))
        for item in unfinished(ledger)[:40]:
            print("    " + item)
        return 0
    save(ledger)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
