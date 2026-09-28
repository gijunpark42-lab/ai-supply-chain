import os
import re
import sys
import ast
import json
import subprocess

from taxonomy import iter_players  # the one shared layer/sector/domain walker
from derive import derive_all      # graph → timelines / screener / capex projections
from apply_patches import apply_all  # patches/*.json → chains/ (safe merge, see apply_patches.py)

# Read all chain files in chains/ and merge by company name into one flat graph.
# Original chain files are never modified — this only writes to graph/merged_graph.json.
# To revert: delete graph/merged_graph.json and re-run.
#
# After the graph is written, derive.py projects it onto the three derived views
# (graph/timelines.bundle.json, graph/company_metrics.json, graph/capex_backlog.json).
# Pass --sync to also run `npm run sync` in web/ so web/public/data picks everything up.

METADATA_PATH = "company_metadata.json"

def load_metadata():
    """Load company_metadata.json if it exists, else return empty dict."""
    if not os.path.exists(METADATA_PATH):
        return {}
    with open(METADATA_PATH, encoding="utf-8") as f:
        return json.load(f)

HUBS_PATH = "graph/hubs.txt"


def read_previous_hubs(path=HUBS_PATH):
    """Parse the hubs.txt left by the PREVIOUS build into {company: [chain, ...]}.

    This script writes that file itself in a fixed format, so reading it back is
    exact: ast.literal_eval turns the "['a', 'b']" text into the real list again.
    Returns None when there is no previous build to compare against.
    """
    if not os.path.exists(path):
        return None
    previous = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                company, marker, chains = line.partition("chains: ")
                if not marker:
                    continue  # the header line, not a hub row
                previous[company.strip()] = ast.literal_eval(chains.strip())
    except (OSError, ValueError, SyntaxError):
        # A truncated or hand-edited file (e.g. a build killed mid-write) must never
        # abort the build - derive/evidence/verify still have to run after this step.
        # Treat it as "no baseline": the full list is printed, nothing is hidden.
        return None
    return previous


def report_hubs(hubs, path=HUBS_PATH):
    """Write the FULL hub list to disk; print only what changed since the last build.

    The list runs 100+ lines and is nearly identical build to build, so printing it
    every time buries the one row that actually moved. Nothing is lost - the complete
    list is always written to `path` (read it with `cat graph/hubs.txt`). What gets
    printed is the part worth noticing: a company that gained or lost a chain, which
    usually means an enrichment placed a node in a new chain.
    """
    current = {h["id"]: list(h["chains"]) for h in hubs}
    previous = read_previous_hubs(path)

    # Always write the complete record first - this file, not stdout, is the full list.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("Hub nodes (%d companies shared across 2+ chains):\n" % len(hubs))
        for h in hubs:
            f.write(f"  {h['id']:30s} chains: {h['chains']}\n")
    os.replace(tmp, path)  # atomic swap - the file is either the old list or the new one

    if previous is None:
        # No baseline yet - print everything, exactly as this script always did.
        print(f"\nHub nodes ({len(hubs)} companies shared across 2+ chains):")
        for h in hubs:
            print(f"  {h['id']:30s} chains: {h['chains']}")
        print(f"\n  (also saved to {path}; later builds print only what changed)")
        return

    added = [c for c in current if c not in previous]
    lost = [c for c in previous if c not in current]
    changed = [
        (c, previous[c], current[c])
        for c in current
        if c in previous and sorted(previous[c]) != sorted(current[c])
    ]

    print(f"\nHub nodes: {len(hubs)} companies shared across 2+ chains -> {path}")
    if not (added or lost or changed):
        print("  no change since the last build")
        return
    for c in added:
        print(f"  + NEW HUB   {c:28s} {current[c]}")
    for c in lost:
        print(f"  - LOST HUB  {c:28s} was {previous[c]}")
    for c, was, now in changed:
        gained = [x for x in now if x not in was]
        dropped = [x for x in was if x not in now]
        bits = []
        if gained:
            bits.append(f"+{gained}")
        if dropped:
            bits.append(f"-{dropped}")
        print(f"  ~ {c:30s} {' '.join(bits)}")


def build_graph(chains_dir="chains", output_path="graph/merged_graph.json"):
    metadata = load_metadata()
    nodes = {}  # key: company name → merged node data
    edges = []  # flat list of all directed edges across all chains

    # discover chain files recursively — chains/ may be organized into sub-folders
    # (e.g. chains/accelerators/, chains/components/). The chain id is still the
    # filename stem, so sub-foldering does not change node/edge data or colors.
    chain_files = []
    for _root, _dirs, _files in os.walk(chains_dir):
        for _fn in _files:
            if _fn.endswith(".json"):
                chain_files.append(os.path.join(_root, _fn))

    for filepath in sorted(chain_files):
        filename = os.path.basename(filepath)
        chain_name = filename.replace(".json", "")  # e.g. "nvidia_vera_rubin"

        with open(filepath, encoding="utf-8") as f:
            chain = json.load(f)

        print(f"  Reading: {filename}")

        # iter_players walks flow[] (layers) AND domains[] at any nesting depth, so
        # graph_build never re-implements the 4-deep loop. kind is "layer" or "domain".
        for player, slug, kind, sector, sub_sector in iter_players(chain):
                company = player["company"]

                # First time we see this company → create its node
                if company not in nodes:
                    meta = metadata.get(company, {})
                    nodes[company] = {
                        "id": company,
                        "layers": [],    # layer slugs this company plays in
                        "domains": [],   # cross-cutting domain slugs (power/thermal/…)
                        "sectors": [],   # sector strings across all its roles
                        "chains": [],
                        "products": [],
                        "quarterly_data": [],
                        # metadata fields (null if not in company_metadata.json)
                        "ticker":   meta.get("ticker"),
                        "exchange": meta.get("exchange"),
                        "country":  meta.get("country"),
                        "status":   meta.get("status", "public"),
                    }

                # Add layer/domain slug (a company can play different roles in different chains)
                group_field = "layers" if kind == "layer" else "domains"
                if slug not in nodes[company][group_field]:
                    nodes[company][group_field].append(slug)

                # Add sector (free string)
                if sector and sector not in nodes[company]["sectors"]:
                    nodes[company]["sectors"].append(sector)

                # Add chain source
                if chain_name not in nodes[company]["chains"]:
                    nodes[company]["chains"].append(chain_name)

                # Record this specific product role
                nodes[company]["products"].append({
                    "chain": chain_name,
                    "layer": slug if kind == "layer" else None,
                    "domain": slug if kind == "domain" else None,
                    "sector": sector,
                    "sub_sector": sub_sector,
                    "product": player["product"]
                })

                # Merge all quarterly_data entries (tag each with chain source).
                # Dedupe by (quarter, signal): a company that appears in several
                # chains often carries the same company-level figure in each, which
                # must not be double-counted in the merged node.
                _seen_qd = {(q.get("quarter"), q.get("signal"))
                            for q in nodes[company]["quarterly_data"]}
                for entry in player.get("quarterly_data", []):
                    key = (entry.get("quarter"), entry.get("signal"))
                    if key in _seen_qd:
                        continue
                    _seen_qd.add(key)
                    entry_with_chain = dict(entry)
                    entry_with_chain["chain"] = chain_name
                    nodes[company]["quarterly_data"].append(entry_with_chain)

                # Build edges — one edge object per connects_to entry
                for edge in player.get("connects_to", []):
                    # Skip self-loops (TSMC → TSMC from epiwafer → packaging)
                    if edge["company"] == company:
                        continue
                    edges.append({
                        "source": company,
                        "target": edge["company"],
                        "relationship": edge["relationship"],
                        "contracts": edge.get("contracts", []),
                        "chain": chain_name  # which chain this edge came from
                    })

    # Write merged graph
    graph = {
        "nodes": list(nodes.values()),
        "edges": edges
    }

    os.makedirs("graph", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\nSaved to {output_path}")
    print(f"Total nodes : {len(nodes)}")
    print(f"Total edges : {len(edges)}")

    # Hub nodes - companies that appear in 2+ chains.
    hubs = sorted(
        (n for n in nodes.values() if len(n["chains"]) >= 2),
        key=lambda x: len(x["chains"]),
        reverse=True,
    )
    report_hubs(hubs)

    return graph


def write_company_ko(graph, output_path="graph/company_ko.json"):
    """Write every company's Korean names for the web search box ("삼성전자" finds Samsung).

    - A listed Korean company gets DART's official name through its stock code
      (dart/corp_codes.json: "000660" -> "SK하이닉스").
    - Every Korean spelling in verify_graph.KO_ALIASES is added on top: short names
      ("하이닉스"), private companies, Korean spellings of foreign names ("키옥시아").
    Output: {"SK Hynix": ["SK하이닉스", "에스케이하이닉스", "하이닉스"], ...}, only companies that have one.
    """
    from verify_graph import KO_ALIASES
    hangul = re.compile(r"[가-힣]")
    corp_codes = {}
    if os.path.exists("dart/corp_codes.json"):
        with open("dart/corp_codes.json", encoding="utf-8") as f:
            corp_codes = json.load(f)

    names_by_company = {}
    for node in graph["nodes"]:
        names = []
        stock_code = (node.get("ticker") or "").split(".")[0]  # "000660.KS" -> "000660"
        if node.get("country") == "KR" and stock_code in corp_codes:
            names.append(corp_codes[stock_code]["corp_name"])
        for alias in KO_ALIASES.get(node["id"], []):
            if hangul.search(alias) and alias not in names:
                names.append(alias)
        if names:
            names_by_company[node["id"]] = names

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(names_by_company, f, indent=1, ensure_ascii=False, sort_keys=True)
    print(f"Korean search names: {len(names_by_company)} companies -> {output_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # chain text contains → and non-ASCII names

    # Step 0: fold any pending enrichment patches into chains/ first. Enrichment jobs
    # write to patches/ instead of chains/ so parallel jobs can never overwrite each
    # other; this single-process merge is the only writer of chains/ (see apply_patches.py).
    applied_labels = apply_all()
    if applied_labels:
        print()

    print("Building merged graph from all chain files...\n")
    graph = build_graph()

    # Derived views are rebuilt from the graph every time (see derive.py for the rules).
    derive_all(graph)

    # Source evidence: for every data point, the verbatim passage in its source document
    # (graph/evidence.json, shown by the "source" button in the web app). See evidence.py.
    from evidence import build_evidence
    build_evidence(graph)

    # Korean company names for the web search box (graph/company_ko.json).
    write_company_ko(graph)

    # Pipeline dashboard: which enrich pipeline ran when, what it covers, what is still
    # pending (graph/enrich_status.json for the Coverage tab + the enrich_log.json record).
    from enrich_status import build_enrich_status
    build_enrich_status(graph)

    # Audit what was just added: re-check every entry from the patches applied above
    # against its source file (verify_graph.py). Fails are printed, never auto-fixed —
    # the enrichment job (or the user) decides what to do with them.
    if applied_labels:
        from verify_graph import verify_labels
        verify_labels(applied_labels)

    # Optional: push everything into web/public/data so the Next.js app (and Vercel,
    # once committed) serves the fresh data. Kept behind a flag so plain builds stay fast.
    if "--sync" in sys.argv:
        print("\nRunning `npm run sync` in web/ ...")
        result = subprocess.run("npm run sync", cwd="web", shell=True)
        if result.returncode != 0:
            print("  WARNING: npm run sync failed (exit %d) — web/public/data NOT refreshed" % result.returncode)
