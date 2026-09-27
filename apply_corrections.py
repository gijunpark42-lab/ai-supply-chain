"""
apply_corrections.py -- apply REVIEWED CORRECTIONS to existing chain entries (accuracy pass).

Why a second applier
--------------------
apply_patches.py is deliberately ADD-only: it can append data but never change or remove it.
An accuracy review needs the opposite: "this figure does not match the source -> fix it",
"this entry is not supported by the document -> delete it", "this label has the wrong date
-> relabel it". Those are edits to EXISTING entries, so they get their own, equally serial,
single writer: this script. Review agents never touch chains/ -- they write proposal files,
and this script applies them one at a time.

Proposal file  (patches/corrections/<reviewer>_<n>.json)
------------------------------------------------------
{
  "reviewer": "acc-1",
  "items": [
    {
      "kind": "quarterly_data" | "contract",
      "company": "SK Hynix",              # node id; for a contract: the edge SOURCE company
      "target": null | "TSMC",            # contract only: the edge TARGET company
      "label": "SK Hynix Q2 FY2026 (08-14-2026)",   # qd.quarter  /  contract.source
      "signal_prefix": "first ~40+ characters of the signal, verbatim",
      "action": "keep" | "set" | "delete" | "relabel",
      "set": {"figure": "...", "units": "...", "value": "...", "signal": "..."},   # action=set: only listed keys change
                                          # ("slot": "guidance" moves a screener cell here; "slot": null removes it)
      "new_label": "SK Hynix Q2 FY2026 (08-13-2026)",                             # action=relabel
      "chains": ["components/nand_flash.json"],   # OPTIONAL: act only in these chain files (e.g. delete the extra
                                                  # copies of a company-wide fact, keeping it on one node)
      "reason": "one line: what the source actually says",
      "evidence": "verbatim snippet from the source (<= 200 chars)"
    }
  ]
}

Locating an entry: the (company, target, label, signal_prefix) tuple must match EXACTLY ONE
entry per chain file; the same entry may legitimately live in several chain files (a company
figure copied into two chains) -- then it is corrected in all of them, unless the item lists
`chains`: then only those files are touched, and each of them must hold the entry.

Usage
-----
    python apply_corrections.py --check          # validate every pending proposal, write nothing
    python apply_corrections.py                  # apply; each file moves to patches/corrections/applied/
    python apply_corrections.py --file <path>    # one proposal file

Nothing here touches graph/ -- run graph_build.py afterwards as usual.
"""

import argparse
import glob
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from taxonomy import iter_players                 # the shared 4-deep walker
from apply_patches import load_chain, save_chain  # keeps each file's newline style

CHAINS_DIR = os.path.join(ROOT, "chains")
CORR_DIR = os.path.join(ROOT, "patches", "corrections")
APPLIED_DIR = os.path.join(CORR_DIR, "applied")
ACTIONS = {"keep", "set", "delete", "relabel"}
SETTABLE = {"figure", "units", "value", "signal", "type", "date_signed", "slot"}
# `slot` moves a screener cell to the entry that carries the filed figure (found 2026-09-11: a CFO misspoke
# "$4.52" on the call, the 8-K prints $4.57). "slot": null removes the key; any other value must be a real slot.
SLOTS = {"revenue_growth", "guidance", "backlog_or_b2b", "supply_status", "next_catalyst"}


def chain_files():
    return sorted(glob.glob(os.path.join(CHAINS_DIR, "*", "*.json")))


def locate(chain, item):
    """Return a list of (container_list, index, entry) for every entry in `chain` that matches
    the item's locator. Empty list = not in this chain."""
    hits = []
    prefix = item["signal_prefix"]
    for player, *_rest in iter_players(chain):
        if player["company"] != item["company"]:
            continue
        if item["kind"] == "quarterly_data":
            for i, q in enumerate(player.get("quarterly_data", [])):
                if q.get("quarter") == item["label"] and (q.get("signal") or "").startswith(prefix):
                    hits.append((player["quarterly_data"], i, q))
        else:
            for edge in player.get("connects_to", []):
                if edge["company"] != item.get("target"):
                    continue
                for i, c in enumerate(edge.get("contracts", [])):
                    if c.get("source") == item["label"] and (c.get("signal") or "").startswith(prefix):
                        hits.append((edge["contracts"], i, c))
    return hits


def validate(item, path):
    problems = []
    for key in ("kind", "company", "label", "signal_prefix", "action", "reason"):
        if not item.get(key):
            problems.append(f"missing {key}")
    if item.get("kind") not in ("quarterly_data", "contract"):
        problems.append("kind must be quarterly_data or contract")
    if item.get("kind") == "contract" and not item.get("target"):
        problems.append("contract items need target")
    if item.get("action") not in ACTIONS:
        problems.append(f"unknown action {item.get('action')!r}")
    if item.get("action") == "set":
        bad = set(item.get("set", {})) - SETTABLE
        if not item.get("set") or bad:
            problems.append(f"set needs keys from {sorted(SETTABLE)} (got {sorted(item.get('set', {}))})")
        if "slot" in item.get("set", {}) and item["set"]["slot"] not in SLOTS | {None}:
            problems.append(f"slot must be one of {sorted(SLOTS)} or null (got {item['set']['slot']!r})")
    if item.get("action") == "relabel" and not item.get("new_label"):
        problems.append("relabel needs new_label")
    if len(item.get("signal_prefix", "")) < 20:
        problems.append("signal_prefix shorter than 20 chars (too ambiguous)")
    if "chains" in item and (not isinstance(item["chains"], list) or not item["chains"]):
        problems.append("chains must be a non-empty list of chain files (relative to chains/)")
    return problems


def chain_rel(path):
    """chains/components/nand_flash.json -> 'components/nand_flash.json' (the form items use)."""
    return os.path.relpath(path, CHAINS_DIR).replace("\\", "/")


def run(files, apply):
    os.makedirs(APPLIED_DIR, exist_ok=True)
    total = {"keep": 0, "set": 0, "delete": 0, "relabel": 0, "errors": 0}
    # Load every chain once; save only the ones we changed.
    chains = {}
    for f in chain_files():
        chains[f] = list(load_chain(f)) + [False]        # [chain, crlf, dirty]

    for path in files:
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except Exception as e:  # malformed JSON is a reviewer error, not a crash
            print(f"[error] {os.path.basename(path)}: cannot parse ({e})")
            total["errors"] += 1
            continue
        print(f"\n{os.path.basename(path)}  reviewer={doc.get('reviewer')}  items={len(doc.get('items', []))}")
        file_ok = True
        for n, item in enumerate(doc.get("items", []), 1):
            probs = validate(item, path)
            if probs:
                print(f"  [error] item {n} {item.get('company')!r}: {'; '.join(probs)}")
                total["errors"] += 1
                file_ok = False
                continue
            scope = set(item.get("chains") or [])
            where = [(f, locate(c[0], item)) for f, c in chains.items() if not scope or chain_rel(f) in scope]
            where = [(f, h) for f, h in where if h]
            missing = scope - {chain_rel(f) for f, _h in where}
            if missing:
                print(f"  [error] item {n} not in the listed chains {sorted(missing)}: {item['company']} | {item['signal_prefix'][:50]}")
                total["errors"] += 1
                file_ok = False
                continue
            if not where:
                print(f"  [error] item {n} not found: {item['kind']} {item['company']} -> {item.get('target')} | {item['label']} | {item['signal_prefix'][:50]}")
                total["errors"] += 1
                file_ok = False
                continue
            if any(len(h) > 1 for _f, h in where):
                print(f"  [error] item {n} ambiguous (matches several entries in one chain): {item['company']} | {item['signal_prefix'][:50]}")
                total["errors"] += 1
                file_ok = False
                continue
            act = item["action"]
            files_txt = ", ".join(os.path.relpath(f, CHAINS_DIR).replace("\\", "/") for f, _h in where)
            print(f"  [{act:7s}] {item['company']}{' -> ' + item['target'] if item.get('target') else ''} | {item['label']} | {files_txt}")
            if not apply or act == "keep":
                total[act] += 1
                continue
            for f, hits in where:
                lst, i, entry = hits[0]
                if act == "set":
                    for k, v in item["set"].items():
                        if k == "slot" and v is None:
                            entry.pop("slot", None)      # null = take the entry out of the screener cell
                        else:
                            entry[k] = v
                elif act == "delete":
                    del lst[i]
                elif act == "relabel":
                    key = "quarter" if item["kind"] == "quarterly_data" else "source"
                    entry[key] = item["new_label"]
                chains[f][2] = True
            total[act] += 1
        if apply and file_ok:
            shutil.move(path, os.path.join(APPLIED_DIR, os.path.basename(path)))
        elif apply:
            print(f"  -> {os.path.basename(path)} left in place (had errors); fix and re-run")

    if apply:
        for f, (chain, crlf, dirty) in chains.items():
            if dirty:
                save_chain(f, chain, crlf)
                print(f"saved {os.path.relpath(f, ROOT)}")
    print("\nsummary:", total, "(check mode)" if not apply else "")
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--file", help="one proposal file instead of every pending file")
    args = ap.parse_args()
    files = [args.file] if args.file else sorted(glob.glob(os.path.join(CORR_DIR, "*.json")))
    if not files:
        print("no proposal files in patches/corrections/")
        return
    run(files, apply=not args.check)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
