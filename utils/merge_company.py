"""
merge_company.py -- fold one company node INTO another across every chain file.

    python utils/merge_company.py --from "Samsung Foundry" --into "Samsung" --dry-run
    python utils/merge_company.py --from "Samsung Foundry" --into "Samsung"

Why this exists
---------------
graph_build.py merges nodes by EXACT company name. When two names in chains/ are
really the same listed company (Samsung Foundry and Samsung are both 005930.KS),
the graph shows two hubs. This script renames the duplicate everywhere it appears
as a node identity -- player `company` fields and `connects_to` targets -- and then
deduplicates what the rename collided:

  * two players with the same name in the same sector  -> one player
    (quarterly_data concatenated, edges merged, products joined with " / ")
  * two edges from the same player to the same target  -> one edge
    (contracts concatenated, relationships joined with " / ")

It does NOT touch text: source labels like "Samsung Foundry Q2 FY2026 (08-14-2026)"
stay as they are (they name the DOCUMENT, and verify_graph.py already maps that
label to the shared Samsung filing). Signals, counterparty strings, etc. are data.

Outside chains/ it also:
  * drops the duplicate entry in company_metadata.json
  * folds the duplicate's block in company_metrics.json (hand-curated screener
    baseline) into the survivor's block, prefixing appended text with the old name

Nothing is deleted except the duplicate identity itself: every quarterly_data
entry and every contract survives on the merged node/edge. Self-loops created by
the merge (Samsung -> Samsung) are kept in the file; graph_build.py skips them
when drawing edges, and the script reports how many contracts sit on them.

After a real run: python graph_build.py --sync   (then commit chains/, graph/, web/public)
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAINS = ROOT / "chains"
METADATA = ROOT / "company_metadata.json"
METRICS = ROOT / "company_metrics.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    # Same formatting apply_patches.py uses, so diffs stay small.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def holders(chain):
    """Yield every list of players in a chain file (sector or sub_sector level)."""
    for group in chain.get("flow", []) + chain.get("domains", []):
        for sector in group.get("sectors", []):
            if "players" in sector:
                yield sector
            for sub in sector.get("sub_sectors", []):
                yield sub


def merge_edges(keep, other):
    """Fold edge `other` into edge `keep` (same target). Contracts dedupe on (source, signal)."""
    seen = {(c.get("source"), c.get("signal")) for c in keep.get("contracts", [])}
    for c in other.get("contracts", []):
        key = (c.get("source"), c.get("signal"))
        if key not in seen:
            keep.setdefault("contracts", []).append(c)
            seen.add(key)
    r1, r2 = keep.get("relationship", ""), other.get("relationship", "")
    if r2 and r2 != r1:
        keep["relationship"] = (r1 + " / " + r2) if r1 else r2
    return keep


def merge_players(keep, other):
    """Fold player `other` into player `keep` (same company, same sector)."""
    seen = {(q.get("quarter"), q.get("signal")) for q in keep.get("quarterly_data", [])}
    for q in other.get("quarterly_data", []):
        key = (q.get("quarter"), q.get("signal"))
        if key not in seen:
            keep.setdefault("quarterly_data", []).append(q)
            seen.add(key)
    by_target = {e["company"]: e for e in keep.get("connects_to", [])}
    for e in other.get("connects_to", []):
        if e["company"] in by_target:
            merge_edges(by_target[e["company"]], e)
        else:
            keep.setdefault("connects_to", []).append(e)
            by_target[e["company"]] = e
    p1, p2 = keep.get("product", ""), other.get("product", "")
    if p2 and p2 != p1:
        keep["product"] = (p1 + " / " + p2) if p1 else p2
    return keep


def merge_chain(chain, src, dst, report):
    """Rename src -> dst inside one chain dict. Returns True if anything changed."""
    changed = False
    for holder in holders(chain):
        players = holder.get("players", [])

        # 1. rename edge targets, then collapse duplicate targets per player
        for p in players:
            edges = p.get("connects_to", [])
            if any(e["company"] == src for e in edges):
                changed = True
                merged = []
                by_target = {}
                for e in edges:
                    if e["company"] == src:
                        e["company"] = dst
                        report["edges_renamed"] += 1
                    if e["company"] in by_target:
                        merge_edges(by_target[e["company"]], e)
                        report["edges_collapsed"] += 1
                    else:
                        by_target[e["company"]] = e
                        merged.append(e)
                p["connects_to"] = merged

        # 2. rename players, then collapse duplicate players in this holder
        if any(p["company"] == src for p in players):
            changed = True
            survivors = []
            by_name = {}
            for p in players:
                if p["company"] == src:
                    p["company"] = dst
                    report["players_renamed"] += 1
                if p["company"] == dst and dst in by_name:
                    merge_players(by_name[dst], p)
                    report["players_collapsed"] += 1
                    continue
                if p["company"] == dst:
                    by_name[dst] = p
                survivors.append(p)
            holder["players"] = survivors

        # 3. count self-loops the merge produced (kept in file, skipped by graph_build)
        for p in holder.get("players", []):
            if p["company"] == dst:
                for e in p.get("connects_to", []):
                    if e["company"] == dst:
                        report["self_loops"] += 1
                        report["self_loop_contracts"] += len(e.get("contracts", []))
    return changed


def blank(value):
    """Treat '', None and mojibake-only strings ('�') as empty baseline cells."""
    return not value or not any(ch.isalnum() for ch in str(value))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="name to remove, e.g. 'Samsung Foundry'")
    ap.add_argument("--into", dest="dst", required=True, help="surviving name, e.g. 'Samsung'")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()
    src, dst = args.src, args.dst

    report = {"files": [], "players_renamed": 0, "players_collapsed": 0,
              "edges_renamed": 0, "edges_collapsed": 0, "self_loops": 0, "self_loop_contracts": 0}

    for path in sorted(CHAINS.rglob("*.json")):
        chain = load(path)
        if merge_chain(chain, src, dst, report):
            report["files"].append(path.relative_to(ROOT).as_posix())
            if not args.dry_run:
                save(path, chain)

    # company_metadata.json: drop the duplicate identity
    meta = load(METADATA)
    meta_note = "no entry"
    if src in meta:
        if dst in meta:
            meta_note = "dropped %s (%s kept: %s)" % (src, dst, meta[dst].get("ticker"))
            del meta[src]
        else:
            meta_note = "renamed %s -> %s" % (src, dst)
            meta[dst] = meta.pop(src)
        if not args.dry_run:
            save(METADATA, meta)

    # company_metrics.json: fold the screener baseline block
    metrics = load(METRICS)
    metrics_note = "no block"
    if src in metrics:
        block = metrics.pop(src)
        target = metrics.setdefault(dst, {})
        appended = []
        for key, value in block.items():
            if key == "asof" or blank(value):
                continue
            if blank(target.get(key)):
                target[key] = value
            elif value != target[key]:
                target[key] = "%s; %s: %s" % (target[key], src, value)
            appended.append(key)
        metrics_note = "folded %s block into %s (%s)" % (src, dst, ", ".join(appended) or "nothing to add")
        if not args.dry_run:
            save(METRICS, metrics)

    mode = "DRY RUN — nothing written" if args.dry_run else "APPLIED"
    print("merge %r -> %r  [%s]" % (src, dst, mode))
    print("  chain files touched :", len(report["files"]))
    for f in report["files"]:
        print("     ", f)
    print("  players renamed     :", report["players_renamed"], " (collapsed into existing:", report["players_collapsed"], ")")
    print("  edge targets renamed:", report["edges_renamed"], " (collapsed into existing:", report["edges_collapsed"], ")")
    print("  self-loops kept     :", report["self_loops"], " carrying", report["self_loop_contracts"], "contracts (graph_build skips self-loops)")
    print("  company_metadata    :", meta_note)
    print("  company_metrics     :", metrics_note)
    if not args.dry_run:
        print("next: python graph_build.py --sync")


if __name__ == "__main__":
    main()
