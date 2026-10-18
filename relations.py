"""
relations.py — every company's NON-AI business relationships (user decision C, 2026-10-17).

Why this file exists
--------------------
The chain files (chains/) are AI supply-chain maps: every `connects_to` edge in them is an AI relationship
(scope "ai"), and the litmus test decides which companies belong to a chain. Since 2026-10-17 the user also
wants EVERY real relationship of a company on the map, even one that has nothing to do with AI — a turbine
maker's utility customers, a chipmaker's automotive customers, a cooling vendor's office-building contracts.
Those do not belong inside an AI chain, so they live in their own ADD-only files here:

    relations/<company file>.json          one file per graph company ("SK Hynix" -> relations/sk-hynix.json)
    {
      "company": "Caterpillar",            # the graph company whose relationships the file holds
      "relations": [
        {
          "from": "Caterpillar",           # always the file's company
          "to": "Rio Tinto",               # the counterparty: a graph node (exact node name) or any other company
          "relation": "supplies",          # seen from `from`: supplies | customer_of | partner
          "product": "Cat 798 AC electric-drive mining trucks",   # the SPECIFIC product / service, in English
          "scope": "other",                # always "other" here (AI relationships live in chains/)
          "source": "transcripts/edgar/caterpillar_10-K_2026-02-14.txt",   # a saved source file, OR a public
                                           #   https:// URL (10-K / 20-F customer or supplier note, company release)
          "quote": "verbatim snippet from that source",           # what proves it; grep-able in the saved file
          "label": "Caterpillar 10-K (02-14-2026)",              # canonical source label (enrich skill section 5)
          "date": "2026-02-14",            # the source document's date, YYYY-MM-DD
          "added": "2026-10-17",           # the day this row was written, YYYY-MM-DD
          "figure": "10% of 2025 sales"    # OPTIONAL: a number the quote states (customer share, order size, ...)
        }
      ]
    }

Rows are ADD-only: never edit or delete one (utils/check_relations.py compares every file with the committed
copy). A relationship seen again in a newer source is a NEW row with the new label.

How the rows reach the website
------------------------------
graph_build.py calls build_other_edges() and writes the result to graph/merged_graph.json under its OWN key,
"other_edges" — never into "edges". derive.py, evidence.py, enrich_status.py and verify_graph.py read only
"edges", so the Exposure / Screener / Timelines / Capex views and the audits stay exactly what they were; only
the web app reads "other_edges" (hidden by default, "Show non-AI relationships" draws them).

A merged other-edge always points supplier -> customer, like a chain edge:
    "A supplies B"     -> source A, target B
    "A customer_of B"  -> source B, target A   (flipped, so B is the supplier)
    "A partner B"      -> source A, target B   (no direction; relation "partner")
The same relationship written in both companies' files (A's 10-K: "we supply B", B's 10-K: "we buy from A")
becomes ONE other-edge whose `refs` list holds both sources. Rows are matched on the two companies and the
relation only, never on the `product` text: each filer words the product its own way ("diesel generator sets" /
"Cat C175 generator sets for data centers"), so the edge's `relationship` is the first row's product and every
ref keeps its own row's `product`.

A row whose counterparty is one of the semiconductor-fab contractors rule B keeps out (FAB_CONTRACTORS) is left
out of the graph with a warning even when utils/check_relations.py was not run, so the rule holds on every build.

The backfill queue (relations_backfill.json)
--------------------------------------------
New companies get their full relationships when they are added. The ~900 companies that were already on the
map get theirs a few per night: relations_backfill.json lists every graph company, most-connected first, with
status "pending" or "done" (and the day it was done). The nightly enrich takes the next ~5 pending ones.

    python -X utf8 relations.py queue                       create the queue / append graph companies it lacks
    python -X utf8 relations.py next [N]                    print the next N pending companies (default 5)
    python -X utf8 relations.py done "<Company>" [...]      mark companies done today (ADD-only)
"""

import datetime
import json
import os
import re
import sys

RELATIONS_DIR = "relations"
QUEUE_PATH = "relations_backfill.json"
PER_NIGHT = 5                                          # companies the nightly enrich backfills per run

# The three relation words a row may use, always read from the `from` company's side.
RELATION_TYPES = ("supplies", "customer_of", "partner")

# Rule B (user, 2026-10-17): data-center and power-grid contractors are allowed; these semiconductor-FAB
# contractors stay excluded — never a node, never a relations counterparty. utils/check_relations.py and
# utils/check_patch.py import this set, so the four names live in one place.
FAB_CONTRACTORS = {"United Integrated Services", "Acter", "Marketech", "Hanyang Eng"}


def squash(name):
    """'SK Hynix' -> 'skhynix': two spellings of one company squash to the same string."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


FAB_CONTRACTORS_SQUASHED = {squash(c) for c in FAB_CONTRACTORS}


# ---------------------------------------------------------------------------
# File names and loading
# ---------------------------------------------------------------------------

def relation_file_name(company):
    """'SK Hynix' -> 'sk-hynix.json' (lower case, every run of other characters becomes one '-').
    The same rule market/common.py uses for graph/financing/, so one company has one file name everywhere."""
    return re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-") + ".json"


def load_relation_files(relations_dir=RELATIONS_DIR):
    """Read every relations/*.json. Returns [(path, data), ...] sorted by file name (stable build output).

    A file that is not valid JSON is SKIPPED with a loud warning instead of stopping the build: the rows stay
    safe in the file, the nightly build still finishes, and the next build after the fix picks them up.
    (utils/check_relations.py refuses such a file before it is ever published.)"""
    if not os.path.isdir(relations_dir):
        return []
    out = []
    for fn in sorted(os.listdir(relations_dir)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(relations_dir, fn)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"  WARNING: {path} skipped ({exc}) - fix it: python -X utf8 utils/check_relations.py {path}")
            continue
        out.append((path, data))
    return out


# ---------------------------------------------------------------------------
# Merging the rows into graph edges (called by graph_build.py)
# ---------------------------------------------------------------------------

def edge_ends(entry):
    """(source, target, relation) of one row, pointed supplier -> customer (see the module docstring)."""
    if entry["relation"] == "customer_of":
        return entry["to"], entry["from"], "supplies"   # `from` buys from `to`, so `to` is the supplier
    return entry["from"], entry["to"], entry["relation"]


def build_other_edges(relation_files):
    """Turn the rows of every relations file into merged-graph edges with scope "other".

    One edge per (supplier, customer, relation): the product text is NOT part of the key, because the two
    companies of one relationship word it differently in their own documents. The edge's `relationship` is the
    first row's product; every row that describes the relationship adds one entry to the edge's `refs` (label,
    source, quote, date, product[, figure]), so each source keeps its own wording. Nothing is ever dropped from
    the files; a row the checker would refuse (unknown relation, scope other than "other", missing company, a
    rule-B fab contractor) is left out of the graph with a warning line, so a typo can never put a wrong edge
    on the map."""
    edges = []
    by_key = {}
    for path, data in relation_files:
        for i, entry in enumerate(data.get("relations", [])):
            if (not isinstance(entry, dict) or entry.get("relation") not in RELATION_TYPES
                    or entry.get("scope") != "other" or not entry.get("from") or not entry.get("to")
                    or entry["from"] == entry["to"]):
                print(f"  WARNING: {path} relations[{i}] left out of the graph - run utils/check_relations.py")
                continue
            # Rule B holds even when utils/check_relations.py was skipped: no fab contractor on the map.
            if squash(entry["to"]) in FAB_CONTRACTORS_SQUASHED or squash(entry["from"]) in FAB_CONTRACTORS_SQUASHED:
                print(f"  WARNING: {path} relations[{i}] left out of the graph - {entry['to']!r} is a "
                      f"semiconductor-fab contractor (rule B, 2026-10-17)")
                continue
            source, target, relation = edge_ends(entry)
            product = entry.get("product", "")
            # A partnership has no direction: A-B and B-A are the same relationship.
            pair = (source, target) if relation == "supplies" else tuple(sorted((source, target)))
            key = (pair, relation)
            edge = by_key.get(key)
            if edge is None:
                edge = {
                    "source": source,
                    "target": target,
                    "relationship": product,          # same key as a chain edge, so the web reads both alike
                    "relation": relation,
                    "scope": "other",
                    "refs": [],
                }
                by_key[key] = edge
                edges.append(edge)
            ref = {k: entry.get(k, "") for k in ("label", "source", "quote", "date", "product")}
            if entry.get("figure"):
                ref["figure"] = entry["figure"]
            if ref not in edge["refs"]:               # the same row copied twice is counted once
                edge["refs"].append(ref)
    return edges


# ---------------------------------------------------------------------------
# The backfill queue (relations_backfill.json)
# ---------------------------------------------------------------------------

QUEUE_ABOUT = (
    "Relations backfill queue (user decision C, 2026-10-17; enrich skill section 2). Every graph company that "
    "was on the map before 2026-10-17 gets ALL its business relationships recorded, AI or not, a few per night: "
    "the nightly enrich takes the next per_night pending rows from the top (most-connected first: degree = AI "
    "edges in graph/merged_graph.json when the row was queued), writes their non-AI relationships to "
    "relations/<company>.json and their AI ones as patches, then marks them done with `python -X utf8 "
    "relations.py done \"<Company>\"`. ADD-only: rows are never removed or reordered and a done row never goes "
    "back to pending; `relations.py queue` appends graph companies the file does not list yet."
)


def node_degrees(graph):
    """{company: number of AI edges touching it} from the merged graph's `edges`."""
    degree = {n["id"]: 0 for n in graph.get("nodes", [])}
    for e in graph.get("edges", []):
        for end in (e["source"], e["target"]):
            if end in degree:
                degree[end] += 1
    return degree


def build_queue(graph, queue=None, today=None):
    """Return the queue with every graph company in it. Existing rows keep their place and status; companies
    the queue does not list yet are appended, most-connected first (ties A->Z)."""
    today = today or datetime.date.today().isoformat()
    queue = queue or {"_about": QUEUE_ABOUT, "built": today, "per_night": PER_NIGHT, "rows": []}
    listed = {row["company"] for row in queue["rows"]}
    degree = node_degrees(graph)
    missing = sorted((c for c in degree if c not in listed), key=lambda c: (-degree[c], c))
    for company in missing:
        queue["rows"].append({"company": company, "degree": degree[company], "status": "pending",
                              "done_date": None})
    return queue


def next_pending(queue, n=PER_NIGHT):
    """The next n companies still pending, in queue order."""
    return [row["company"] for row in queue["rows"] if row["status"] == "pending"][:n]


def mark_done(queue, companies, today=None):
    """Mark companies done (ADD-only). A row already done keeps its first date; a company the queue does not
    list (a company added after the queue was built) is appended as done. Returns one message per company."""
    today = today or datetime.date.today().isoformat()
    rows = {row["company"]: row for row in queue["rows"]}
    messages = []
    for company in companies:
        row = rows.get(company)
        if row is None:
            row = {"company": company, "degree": None, "status": "done", "done_date": today}
            queue["rows"].append(row)
            rows[company] = row
            messages.append(f"{company}: not in the queue - appended as done {today}")
        elif row["status"] == "done":
            messages.append(f"{company}: already done {row['done_date']} (kept)")
        else:
            row["status"], row["done_date"] = "done", today
            messages.append(f"{company}: done {today}")
    return messages


def read_queue(path=QUEUE_PATH):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_queue(queue, path=QUEUE_PATH):
    """One row per line, so a night that marks five companies done changes five lines in the diff."""
    lines = ["{"]
    for key in ("_about", "built", "per_night"):
        lines.append(f" {json.dumps(key)}: {json.dumps(queue[key], ensure_ascii=False)},")
    lines.append(' "rows": [')
    rows = queue["rows"]
    for i, row in enumerate(rows):
        lines.append("  " + json.dumps(row, ensure_ascii=False) + ("," if i < len(rows) - 1 else ""))
    lines += [" ]", "}"]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)                              # atomic: the file is either the old queue or the new one


USAGE = """usage:
    python -X utf8 relations.py queue                       create the queue / append graph companies it lacks
    python -X utf8 relations.py next [N]                    print the next N pending companies (default 5)
    python -X utf8 relations.py done "<Company>" [...]      mark companies done today (ADD-only)"""


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    command = args[0] if args else ""
    if command == "queue":
        with open(os.path.join("graph", "merged_graph.json"), encoding="utf-8") as f:
            graph = json.load(f)
        queue = read_queue()
        before = len(queue["rows"]) if queue else 0
        queue = build_queue(graph, queue)
        write_queue(queue)
        print(f"{QUEUE_PATH}: {len(queue['rows'])} companies ({len(queue['rows']) - before} appended)")
    elif command == "next":
        queue = read_queue()
        if queue is None:
            sys.exit(f"{QUEUE_PATH} does not exist yet - run: python -X utf8 relations.py queue")
        n = int(args[1]) if len(args) > 1 else queue.get("per_night", PER_NIGHT)
        pending = next_pending(queue, n)
        left = sum(1 for row in queue["rows"] if row["status"] == "pending")
        print(f"next {len(pending)} of {left} pending:")
        for company in pending:
            print(f"  {company}  ->  {RELATIONS_DIR}/{relation_file_name(company)}")
    elif command == "done" and len(args) > 1:
        queue = read_queue()
        if queue is None:
            sys.exit(f"{QUEUE_PATH} does not exist yet - run: python -X utf8 relations.py queue")
        for message in mark_done(queue, args[1:]):
            print(message)
        write_queue(queue)
    else:
        print(USAGE)
        sys.exit(2)
