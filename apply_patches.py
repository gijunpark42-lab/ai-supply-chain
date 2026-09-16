"""
apply_patches.py — merge enrichment PATCHES into the chain files, safely, one at a time.

Why this file exists (the concurrency problem it solves)
--------------------------------------------------------
Enrichment used to be:  read chain → think for 10 minutes → write the WHOLE chain back.
When two enrichment jobs run in parallel on the same chain file, the second writer's
copy is 10 minutes stale and silently overwrites everything the first writer added.
No error, valid JSON, a clean build — the data is just gone ("lost update").

The fix: an enrichment job never writes to chains/ directly. It writes its additions
to its OWN file under patches/ (file names never collide), and THIS script — a single
process — folds every pending patch into the chains. The read-modify-write window
shrinks from minutes to milliseconds, and because every patch is ADD-only the result
is the same no matter which order the patches land in.

Life cycle of a patch:
    patches/<slug>.json            written by an enrichment job
        → python apply_patches.py  (also run automatically by graph_build.py)
    patches/applied/<slug>.json    moved here after a successful merge = a receipt
                                   of exactly what that transcript added

Patch file shape
----------------
{
  "source": "Vistra Q2 FY2026 (08-06-2026)",          # the canonical label (for logging)
  "chains": {
    "components/power_cooling.json": {                 # path relative to chains/
      "players": [
        {
          "company": "Vistra",                         # canonical node name (see naming rules)
          "domain": "power",                           # WHERE to create it if it does not exist:
          "sector": "Generation",                      #   "layer": <slug>  or  "domain": <slug>
          "sub_sector": null,                          #   + sector (+ sub_sector). Ignored when found.
          "product": "...",                            # only used when the player is CREATED
          "quarterly_data": [ { "quarter": "...", "signal": "...", "figure": "...", "topics": [] } ],
          "connects_to": [
            { "company": "Meta", "relationship": "...",
              "contracts": [ { "source": "...", "signal": "...", "topics": [] } ] }
          ]
        }
      ]
    }
  }
}

Merge rules (ADD-only, idempotent — applying the same patch twice adds nothing twice):
  * player  : found by company name anywhere in the chain (preferring the patch's
              layer/sector when the company appears in several places); created at
              the patch's locator only if absent.
  * edge    : found by (player, target company); `contracts` are appended; created if absent.
  * entries : a quarterly_data entry is skipped when the same (quarter, signal) already
              exists; a contract is skipped when the same (source, signal) already exists.
  * nothing is ever removed or overwritten. Existing `product` / `relationship` text is kept.
"""

import json
import os
import shutil
import sys

from taxonomy import iter_players, LAYER_ORDER, LAYER_SLUGS, DOMAIN_SLUGS

CHAINS_DIR = "chains"
PATCHES_DIR = "patches"
APPLIED_DIR = os.path.join(PATCHES_DIR, "applied")


# ---------------------------------------------------------------------------
# File helpers — keep each chain file's own newline style so diffs stay clean
# ---------------------------------------------------------------------------

def load_chain(path):
    """Read a chain file and remember whether it uses Windows (CRLF) line endings."""
    with open(path, "rb") as f:
        raw = f.read()
    crlf = b"\r\n" in raw
    return json.loads(raw.decode("utf-8")), crlf


def save_chain(path, chain, crlf):
    """Write the chain back in the same style the repo already uses (2-space indent,
    UTF-8 without escaping, trailing newline, original line-ending flavour)."""
    text = json.dumps(chain, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:
        f.write(text)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Finding things inside a chain
# ---------------------------------------------------------------------------

def find_player(chain, company, want_group=None, want_sector=None, want_product=None, want_targets=()):
    """Return the player dict for `company`, or None.

    A company may legitimately appear in more than one layer (e.g. Corning in
    interconnect AND advanced_packaging). When that happens we prefer the one whose
    layer/domain and sector match the patch. A chain can even hold the SAME company twice
    at the same layer + sector for two products (e.g. two Amazon nodes in an AWS chain);
    then the one whose `product` equals the patch's product wins, then the one that already
    has an edge to a company the patch connects to, and only then the first match.
    """
    matches = []
    for player, group_slug, _kind, sector, _sub in iter_players(chain):
        if player.get("company") == company:
            matches.append((player, group_slug, sector))
    if not matches:
        return None

    def best(candidates):
        # among several candidates: exact product, then an existing edge to a patch target, then the first
        for player, _g, _s in candidates:
            if want_product and player.get("product") == want_product:
                return player
        for player, _g, _s in candidates:
            if any(find_edge(player, target) for target in want_targets):
                return player
        return candidates[0][0]

    exact = [m for m in matches if m[1] == want_group and m[2] == want_sector]
    if exact:
        return best(exact)
    same_group = [m for m in matches if m[1] == want_group]
    if same_group:
        return best(same_group)
    return best(matches)


def find_edge(player, target):
    for edge in player.get("connects_to", []):
        if edge.get("company") == target:
            return edge
    return None


def _players_list(chain, group_slug, sector_name, sub_sector_name):
    """Return the `players` list at layer/domain → sector (→ sub_sector), creating the
    containers when they do not exist yet. Layers are inserted in taxonomy order so a
    brand-new layer lands in the right place in the top→bottom stack."""
    if group_slug in LAYER_SLUGS:
        group_list, key = chain.setdefault("flow", []), "layer"
    elif group_slug in DOMAIN_SLUGS:
        group_list, key = chain.setdefault("domains", []), "domain"
    else:
        raise ValueError("unknown layer/domain slug %r" % group_slug)

    group = next((g for g in group_list if g.get(key) == group_slug), None)
    if group is None:
        group = {key: group_slug, "sectors": []}
        if key == "layer":
            # keep the fixed top→bottom order from taxonomy.py
            pos = sum(1 for g in group_list if LAYER_ORDER.get(g.get("layer"), 99) < LAYER_ORDER[group_slug])
            group_list.insert(pos, group)
        else:
            group_list.append(group)
        print("    created %s %r" % (key, group_slug))

    sector = next((s for s in group.get("sectors", []) if s.get("sector") == sector_name), None)
    if sector is None:
        sector = {"sector": sector_name, "players": []}
        group.setdefault("sectors", []).append(sector)
        print("    created sector %r under %s" % (sector_name, group_slug))

    if sub_sector_name:
        subs = sector.setdefault("sub_sectors", [])
        sub = next((s for s in subs if s.get("sub_sector") == sub_sector_name), None)
        if sub is None:
            sub = {"sub_sector": sub_sector_name, "players": []}
            subs.append(sub)
            print("    created sub_sector %r under %s/%s" % (sub_sector_name, group_slug, sector_name))
        return sub.setdefault("players", [])
    return sector.setdefault("players", [])


# ---------------------------------------------------------------------------
# Merging one patch player into a chain
# ---------------------------------------------------------------------------

def _same_entry(existing, new, key):
    """Two entries are 'the same' when their label AND signal text match."""
    return existing.get(key) == new.get(key) and existing.get("signal") == new.get("signal")


def merge_player(chain, pp, stats):
    """Fold one patch-player `pp` into `chain`. Mutates chain in place."""
    company = pp["company"]
    group_slug = pp.get("layer") or pp.get("domain")
    player = find_player(chain, company, group_slug, pp.get("sector"),
                         pp.get("product"), [e.get("company") for e in pp.get("connects_to", [])])

    if player is None:
        # JOB 3 — a genuinely new company. The locator tells us where it goes.
        if not group_slug or not pp.get("sector"):
            raise ValueError("player %r is not in the chain and the patch gives no layer/domain + sector to create it" % company)
        player = {
            "company": company,
            "product": pp.get("product", ""),
            "connects_to": [],
            "quarterly_data": [],
        }
        _players_list(chain, group_slug, pp["sector"], pp.get("sub_sector")).append(player)
        stats["players_created"] += 1
        print("    + new player %r in %s/%s" % (company, group_slug, pp["sector"]))

    # JOB 1 — node-level figures
    qd = player.setdefault("quarterly_data", [])
    for entry in pp.get("quarterly_data", []):
        if any(_same_entry(e, entry, "quarter") for e in qd):
            stats["skipped_duplicates"] += 1
            continue
        qd.append(entry)
        stats["quarterly_data"] += 1

    # JOB 2 / JOB 4 — edges and their contracts
    for pe in pp.get("connects_to", []):
        edge = find_edge(player, pe["company"])
        if edge is None:
            edge = {"company": pe["company"], "relationship": pe.get("relationship", ""), "contracts": []}
            player.setdefault("connects_to", []).append(edge)
            stats["edges_created"] += 1
            print("    + new edge %s -> %s" % (company, pe["company"]))
        contracts = edge.setdefault("contracts", [])
        for c in pe.get("contracts", []):
            if any(_same_entry(e, c, "source") for e in contracts):
                stats["skipped_duplicates"] += 1
                continue
            contracts.append(c)
            stats["contracts"] += 1


# ---------------------------------------------------------------------------
# Applying whole patch files
# ---------------------------------------------------------------------------

def apply_patch_file(patch_path, chains_dir=CHAINS_DIR, dry_run=False):
    """Apply one patch file to every chain it names. Returns the stats dict."""
    patch = load_json(patch_path)
    stats = {"players_created": 0, "edges_created": 0, "quarterly_data": 0,
             "contracts": 0, "skipped_duplicates": 0}
    print("Patch %s  [%s]" % (os.path.basename(patch_path), patch.get("source", "?")))

    for rel_path, body in patch.get("chains", {}).items():
        chain_path = os.path.join(chains_dir, rel_path)
        if not os.path.exists(chain_path):
            raise FileNotFoundError("patch %s targets missing chain %s" % (patch_path, chain_path))
        # The read → modify → write below is the ONLY place a chain file is touched,
        # and it takes milliseconds — that is the whole point of this script.
        chain, crlf = load_chain(chain_path)
        print("  -> %s" % rel_path)
        for pp in body.get("players", []):
            merge_player(chain, pp, stats)
        if not dry_run:
            save_chain(chain_path, chain, crlf)

    print("  added: %d quarterly_data, %d contracts, %d new players, %d new edges; %d duplicates skipped%s"
          % (stats["quarterly_data"], stats["contracts"], stats["players_created"],
             stats["edges_created"], stats["skipped_duplicates"], "  (DRY RUN)" if dry_run else ""))
    return stats


def apply_all(patches_dir=PATCHES_DIR, chains_dir=CHAINS_DIR, dry_run=False):
    """Apply every *.json directly under patches/ (oldest first), then move each to
    patches/applied/. Returns the list of source labels applied (empty when nothing was
    pending) — graph_build.py hands exactly those labels to verify_graph.py afterwards."""
    if not os.path.isdir(patches_dir):
        return []
    pending = sorted(
        (fn for fn in os.listdir(patches_dir) if fn.endswith(".json")),
        key=lambda fn: os.path.getmtime(os.path.join(patches_dir, fn)),
    )
    if not pending:
        return []

    labels = []
    applied_dir = os.path.join(patches_dir, "applied")
    os.makedirs(applied_dir, exist_ok=True)
    print("Applying %d pending patch(es) from %s/ ...\n" % (len(pending), patches_dir))
    for fn in pending:
        src = os.path.join(patches_dir, fn)
        with open(src, encoding="utf-8") as f:
            label = json.load(f).get("source")
        if label and label not in labels:
            labels.append(label)
        apply_patch_file(src, chains_dir, dry_run)
        if not dry_run:
            dest = os.path.join(applied_dir, fn)
            if os.path.exists(dest):
                # same slug applied before (e.g. a re-run) — keep both receipts
                base, ext = os.path.splitext(fn)
                n = 2
                while os.path.exists(os.path.join(applied_dir, "%s_%d%s" % (base, n, ext))):
                    n += 1
                dest = os.path.join(applied_dir, "%s_%d%s" % (base, n, ext))
            shutil.move(src, dest)
        print()
    return labels


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    # Any unknown flag (e.g. --help) used to fall through to a REAL apply of every pending
    # patch -- that happened twice on 2026-09-16. Only --dry-run is accepted; anything else stops.
    unknown = [a for a in sys.argv[1:] if a != "--dry-run"]
    if unknown:
        print("usage: python apply_patches.py [--dry-run]   (unknown argument(s): %s -- nothing applied)" % " ".join(unknown))
        sys.exit(2)
    dry = "--dry-run" in sys.argv
    n = len(apply_all(dry_run=dry))
    if n == 0:
        print("No pending patches in %s/." % PATCHES_DIR)
