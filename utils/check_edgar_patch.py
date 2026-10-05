"""Pre-flight check for an `enrich edgar` patch, BEFORE graph_build.py applies it to chains/.

It runs the same per-entry checks verify_graph.py runs after a build (every number in figure/units/value is in the
filing, the counterparty is named, label format, no Korean) plus structural checks the build does not do:
  * the patch label equals the `# source label:` header of a transcripts/edgar file
  * every player already exists in that chain (no accidental NEW node) and its locator matches
  * every edge target is a node in that chain or an existing edge of that player; says whether the edge is new or
    exists only in the reverse direction (then use that one)
  * quarter/source == label, topics present and valid, slot/capex shape valid
  * the same (quarter, signal) / (source, signal) is not already in the chain

    python -X utf8 utils/check_edgar_patch.py patches/edgar_crdo_10-k_2026-06-15_customers.json [more ...]

Exit code 1 when any ERROR or verify FAIL is found. Fix until it prints `RESULT: clean`.
A patch that deliberately creates a new node (user-approved) shows ERROR lines for that node and its edges.
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import verify_graph as vg  # noqa: E402
from taxonomy import iter_players  # noqa: E402

vg.DOC_GLOBS = ["transcripts/edgar/*.txt"]          # stricter + faster: only the SEC filing itself counts
BY_LABEL, ALL_DOCS = vg.load_documents()
TOPICS = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob("timelines/*.json")}
SLOTS = {"revenue_growth", "guidance", "backlog_or_b2b", "supply_status", "next_catalyst"}
CAPEX_FIELDS = {"capex_q", "capex_year", "backlog", "signal"}
QD_KEYS = {"quarter", "signal", "figure", "topics"}
CT_KEYS = {"source", "signal", "units", "value", "date_signed", "type", "topics"}

problems = 0


def say(level, msg):
    global problems
    if level in ("ERROR", "FAIL"):
        problems += 1
    print(f"  [{level}] {msg}")


def filer_of(label):
    # 6-K / 20-F / 40-F = a foreign issuer's 8-K / 10-K; "prospectus" = a recent listing's 424B4 (or S-1/A, F-1/A)
    return re.split(r"\s+(8-K|6-K|10-K|10-Q|20-F|40-F|prospectus)\s+\(", label)[0]


def check_tags(where, entry):
    topics = entry.get("topics")
    if not isinstance(topics, list):
        say("ERROR", f"{where}: `topics` missing (write [] when none)")
    else:
        bad = [t for t in topics if t not in TOPICS]
        if bad:
            say("ERROR", f"{where}: unknown topics {bad}; valid: {sorted(TOPICS)}")
    if "slot" in entry and entry["slot"] not in SLOTS:
        say("ERROR", f"{where}: invalid slot {entry['slot']!r}")
    if "capex" in entry:
        cx = entry["capex"]
        if not isinstance(cx, dict) or cx.get("field") not in CAPEX_FIELDS:
            say("ERROR", f"{where}: invalid capex {cx!r}")


def verify(where, label, fields, counterparty=None):
    docs = vg.resolve_label_docs(label, BY_LABEL, ALL_DOCS)
    verdict, issues, detail = vg.check_entry(label, docs, fields, counterparty)
    level = {"fail": "FAIL", "warn": "WARN"}.get(verdict)
    if level:
        extra = {k: v for k, v in detail.items() if k.startswith("numbers_") or k == "counterparty"}
        say(level, f"{where}: verify {verdict} {issues} {extra}")


def check(patch_path):
    print(f"== {patch_path}")
    try:
        patch = json.load(open(patch_path, encoding="utf-8"))
    except Exception as exc:
        say("ERROR", f"invalid JSON: {exc}")
        return
    label = patch.get("source", "")
    if label not in BY_LABEL:
        say("ERROR", f"label {label!r} is not the `# source label:` of any transcripts/edgar file")
        return
    filer = filer_of(label)
    n_qd = n_ct = 0
    for chain_rel, body in (patch.get("chains") or {}).items():
        chain_path = os.path.join("chains", chain_rel)
        if not os.path.exists(chain_path):
            say("ERROR", f"chain file not found: {chain_rel}")
            continue
        chain = json.load(open(chain_path, encoding="utf-8"))
        placements = {}
        for player, group_slug, kind, sector, sub in iter_players(chain):
            placements.setdefault(player["company"], []).append((kind, group_slug, sector, sub, player))
        for p in body.get("players", []):
            company = p.get("company")
            where = f"{chain_rel} :: {company}"
            if company not in placements:
                say("ERROR", f"{where}: company is NOT a node in this chain (the patch would create a new node)")
                continue
            group = p["layer"] if "layer" in p else p.get("domain")
            spots = placements[company]
            match = [s for s in spots if s[1] == group and s[2] == p.get("sector") and s[3] == p.get("sub_sector")]
            if not match:
                say("WARN", f"{where}: locator {group}/{p.get('sector')}/{p.get('sub_sector')} matches none of "
                            f"{[(s[1], s[2], s[3]) for s in spots]} (merge will use the first placement)")
            # same rule as apply_patches.find_player: exact product, then an existing edge to a patch target, then first
            cands = match or spots
            targets = {e.get("company") for e in p.get("connects_to", [])}
            node = (next((s[4] for s in cands if s[4].get("product") == p.get("product")), None)
                    or next((s[4] for s in cands if any(x.get("company") in targets for x in s[4].get("connects_to", []))), None)
                    or cands[0][4])
            have_qd = {(q.get("quarter"), q.get("signal")) for q in node.get("quarterly_data", [])}
            for i, q in enumerate(p.get("quarterly_data", [])):
                n_qd += 1
                w = f"{where} qd[{i}]"
                if set(q) - QD_KEYS - {"slot", "capex"} or not QD_KEYS <= set(q):
                    say("ERROR", f"{w}: keys {sorted(q)} (need {sorted(QD_KEYS)} [+ slot/capex])")
                if q.get("quarter") != label:
                    say("ERROR", f"{w}: quarter {q.get('quarter')!r} != label")
                if (q.get("quarter"), q.get("signal")) in have_qd:
                    say("WARN", f"{w}: already in chain (would be skipped)")
                check_tags(w, q)
                verify(w, label, q)
            edges = {e.get("company"): e for e in node.get("connects_to", [])}
            for e in p.get("connects_to", []):
                target = e.get("company")
                w = f"{where} -> {target}"
                if target not in placements and target not in edges:
                    say("ERROR", f"{w}: target is neither a node in this chain nor an existing edge of this player")
                    continue
                if target not in edges:
                    reverse = any(x.get("company") == company for s in placements[target] for x in s[4].get("connects_to", []))
                    if reverse:
                        say("ERROR", f"{w}: NEW edge but the REVERSE edge already exists — check which one the fact describes")
                    else:
                        say("WARN", f"{w}: NEW edge (confirm the filing states the relationship explicitly)")
                have_ct = {(c.get("source"), c.get("signal")) for c in edges.get(target, {}).get("contracts", [])}
                counterparty = target if company == filer else company
                for i, c in enumerate(e.get("contracts", [])):
                    n_ct += 1
                    wc = f"{w} contract[{i}]"
                    if not CT_KEYS <= set(c):
                        say("ERROR", f"{wc}: missing keys {sorted(CT_KEYS - set(c))}")
                    if c.get("source") != label:
                        say("ERROR", f"{wc}: source {c.get('source')!r} != label")
                    if (c.get("source"), c.get("signal")) in have_ct:
                        say("WARN", f"{wc}: already in chain (would be skipped)")
                    check_tags(wc, c)
                    verify(wc, label, c, counterparty)
    print(f"  checked {n_qd} quarterly_data + {n_ct} contracts")


for path in sys.argv[1:]:
    check(path)
print("RESULT:", "PROBLEMS FOUND" if problems else "clean (no ERROR / FAIL)")
sys.exit(1 if problems else 0)
