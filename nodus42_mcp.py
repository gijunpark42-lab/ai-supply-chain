"""
nodus42_mcp.py -- the enriched supply-chain map as a read-only MCP server (user, 2026-10-19: "이미 enrich된 것들을
mcp로 ... 클로드 데스크탑에서도 바로 쓸 수 있게, 그거 바탕으로 답변을").

What it serves: only what the pipeline has already enriched and built -- graph/merged_graph.json (nodes with their
quarterly_data, AI chain edges with their contracts, non-AI relationships in other_edges), graph/company_metrics.json
(screener), graph/evidence.json (the verbatim source passage behind each entry) and graph/company_ko.json (Korean
names). Every entry carries the label of the company document it came from, so an answer can cite it. Nothing here
fetches from the internet or writes a file; the data is as fresh as the last nightly publish in this checkout.

Claude Desktop (claude_desktop_config.json -> "mcpServers"):
    "nodus42": {"command": "C:\\Users\\calif\\AppData\\Local\\Python\\bin\\python.exe",
                "args": ["-X", "utf8", "C:\\Users\\calif\\Desktop\\earnings-ai\\nodus42_mcp.py"]}
Needs the MCP Python SDK 2.x (`pip install mcp`). Test without a client:  python -X utf8 nodus42_mcp.py --selftest
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime

from mcp.server.mcpserver import MCPServer

ROOT = os.environ.get("NODUS42_DATA") or os.path.dirname(os.path.abspath(__file__))   # the repo checkout to read
GRAPH = os.path.join(ROOT, "graph")

server = MCPServer(
    name="nodus42",
    instructions=(
        "Nodus42 / earnings-ai: a supply-chain map of AI and adjacent companies built ONLY from company documents "
        "(earnings calls, SEC / DART / TDnet / EDINET / MOPS / cninfo filings, company IR releases, investor-conference "
        "talks, executives' own words in news interviews). Analyst opinion and news articles are never in it. "
        "Start with search_companies or company_profile; use search_entries for a topic; relationship / supply_chain "
        "for who supplies whom; source_excerpt for the verbatim passage. Cite the source label of every fact you use "
        "(e.g. 'NVIDIA Q2 FY2027 (08-26-2026)'). Edges with scope 'ai' are AI supply-chain relationships; "
        "'other_relationships' are the company's non-AI business ties. Say so when the map has nothing on a question."
    ),
)


# ---------------------------------------------------------------- loading (re-read when a file changes)

_cache = {}


def load(name):
    """graph/<name> as JSON, cached until the file changes on disk (a nightly publish rewrites it)."""
    path = os.path.join(GRAPH, name)
    stamp = os.path.getmtime(path)
    if _cache.get(name, (None,))[0] != stamp:
        with open(path, encoding="utf-8") as f:
            _cache[name] = (stamp, json.load(f))
    return _cache[name][1]


def graph():
    """merged_graph.json plus lookup tables built once per version of the file."""
    g = load("merged_graph.json")
    if _cache.get("_index", (None,))[0] is not g:
        nodes = {n["id"]: n for n in g["nodes"]}
        out_edges, in_edges = {}, {}
        for e in g["edges"]:
            out_edges.setdefault(e["source"], []).append(e)
            in_edges.setdefault(e["target"], []).append(e)
        other = {}
        for e in g.get("other_edges", []):
            other.setdefault(e["source"], []).append(e)
            other.setdefault(e["target"], []).append(e)
        _cache["_index"] = (g, {"nodes": nodes, "out": out_edges, "in": in_edges, "other": other})
    return g, _cache["_index"][1]


LABEL_DATE = re.compile(r"\((\d{2})-(\d{2})-(\d{4})\)\s*$")


def label_date(label):
    """'NVIDIA Q2 FY2027 (08-26-2026)' -> '2026-08-26' ('' when the label carries no date)."""
    m = LABEL_DATE.search(label or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else ""


def find_company(name):
    """A node id from a name, ticker or Korean name (case-insensitive). Returns (id, None) or (None, candidates)."""
    _, ix = graph()
    nodes = ix["nodes"]
    q = name.strip().lower()
    for nid in nodes:
        if nid.lower() == q:
            return nid, None
    for nid, n in nodes.items():
        if (n.get("ticker") or "").lower().split(".")[0] == q.split(".")[0] and q:
            return nid, None
    for nid, names in load("company_ko.json").items():
        if nid in nodes and any(k.lower() == q for k in names):
            return nid, None
    hits = [nid for nid in nodes if q in nid.lower()]
    if len(hits) == 1:
        return hits[0], None
    return None, sorted(hits, key=len)[:15]


def not_found(name, candidates):
    if candidates:
        return {"error": f"'{name}' matches several companies; ask again with one of them", "candidates": candidates}
    return {"error": f"'{name}' is not a company on the map (try search_companies)"}


def entry(q, company=None, target=None):
    """One quarterly_data entry or contract, in a compact, citable shape."""
    label = q.get("quarter") or q.get("source") or ""
    out = {"source": label, "date": label_date(label), "signal": q.get("signal")}
    for key in ("figure", "units", "value", "date_signed", "type", "chain"):
        if q.get(key) not in (None, "", "no specific figure", "not stated"):
            out[key] = q[key]
    if company:
        out["company"] = company
    if target:
        out["counterparty"] = target
    return out


def edge_summary(e, other_side):
    contracts = sorted(e.get("contracts", []), key=lambda c: label_date(c.get("source")), reverse=True)
    return {"company": e[other_side], "relationship": e.get("relationship"), "chain": e.get("chain"),
            "contracts": len(contracts), "latest": entry(contracts[0]) if contracts else None}


# ---------------------------------------------------------------- tools

@server.tool()
def search_companies(query: str, limit: int = 20) -> list:
    """Find companies on the map by name, ticker, Korean name, sector or product words (e.g. 'HBM', 'CoWoS',
    '하이닉스', 'transformer'). Returns name, ticker, exchange, country, layers, sectors and chains."""
    _, ix = graph()
    ko = load("company_ko.json")
    words = [w for w in query.lower().split() if w]
    found = []
    for nid, n in ix["nodes"].items():
        text = " ".join([nid, n.get("ticker") or "", " ".join(ko.get(nid, [])), " ".join(n.get("sectors", [])),
                         " ".join(p.get("product") or "" for p in n.get("products", []))]).lower()
        if all(w in text for w in words):
            score = (0 if query.lower() == nid.lower() else 1 if words[0] in nid.lower() else 2, -len(n.get("quarterly_data", [])))
            found.append((score, nid, n))
    found.sort(key=lambda x: x[0])
    return [{"name": nid, "ticker": n.get("ticker"), "exchange": n.get("exchange"), "country": n.get("country"),
             "status": n.get("status"), "layers": n.get("layers"), "sectors": n.get("sectors"), "chains": n.get("chains")}
            for _, nid, n in found[:limit]]


@server.tool()
def company_profile(company: str, entries: int = 25) -> dict:
    """Everything the map holds on one company: identity, where it sits in each chain (product), its AI-chain
    suppliers and customers (with the latest deal on each edge), its non-AI relationships, screener metrics, and
    its newest `entries` facts (newest first, each with its source label)."""
    nid, cands = find_company(company)
    if not nid:
        return not_found(company, cands)
    _, ix = graph()
    n = ix["nodes"][nid]
    facts = sorted(n.get("quarterly_data", []), key=lambda q: label_date(q.get("quarter")), reverse=True)
    metrics = load("company_metrics.json").get(nid)
    others = [{"source": e["source"], "target": e["target"], "relation": e.get("relation"),
               "relationship": e.get("relationship"), "source_label": (e.get("refs") or [{}])[0].get("label")}
              for e in ix["other"].get(nid, [])]
    return {
        "name": nid, "ticker": n.get("ticker"), "exchange": n.get("exchange"), "country": n.get("country"),
        "status": n.get("status"),
        "placements": [{k: p.get(k) for k in ("chain", "layer", "domain", "sector", "sub_sector", "product") if p.get(k)}
                       for p in n.get("products", [])],
        "suppliers": [edge_summary(e, "source") for e in ix["in"].get(nid, [])],
        "customers": [edge_summary(e, "target") for e in ix["out"].get(nid, [])],
        "other_relationships": others[:60],
        "screener": metrics,
        "facts_total": len(facts),
        "latest_facts": [entry(q) for q in facts[:entries]],
    }


@server.tool()
def company_entries(company: str, query: str = "", since: str = "", limit: int = 50) -> dict:
    """All facts on one company -- its own entries and the deals on its edges -- optionally filtered by words in
    the signal / figure (`query`) and by date (`since`, YYYY-MM-DD). Newest first."""
    nid, cands = find_company(company)
    if not nid:
        return not_found(company, cands)
    _, ix = graph()
    rows = [entry(q) for q in ix["nodes"][nid].get("quarterly_data", [])]
    for e in ix["out"].get(nid, []) + ix["in"].get(nid, []):
        rows += [entry(c, e["source"], e["target"]) for c in e.get("contracts", [])]
    words = [w for w in query.lower().split() if w]
    rows = [r for r in rows if all(w in json.dumps(r, ensure_ascii=False).lower() for w in words)
            and (not since or r["date"] >= since)]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"company": nid, "matches": len(rows), "entries": rows[:limit]}


@server.tool()
def search_entries(query: str, company: str = "", chain: str = "", since: str = "", limit: int = 40) -> dict:
    """Search every fact on the map (company entries and edge deals) for all the words in `query`
    (e.g. 'HBM4 qualification', 'gigawatt', 'backlog record'). Optional filters: a company, a chain file name
    (e.g. 'hbm_memory') and a date (`since`, YYYY-MM-DD). Newest first."""
    g, ix = graph()
    words = [w for w in query.lower().split() if w]
    only = None
    if company:
        only, cands = find_company(company)
        if not only:
            return not_found(company, cands)
    rows = []
    for nid, n in ix["nodes"].items():
        if only and nid != only:
            continue
        for q in n.get("quarterly_data", []):
            if chain and q.get("chain") != chain:
                continue
            rows.append(entry(q, nid))
    for e in g["edges"]:
        if (only and only not in (e["source"], e["target"])) or (chain and e.get("chain") != chain):
            continue
        rows += [entry(c, e["source"], e["target"]) for c in e.get("contracts", [])]
    rows = [r for r in rows if all(w in json.dumps(r, ensure_ascii=False).lower() for w in words)
            and (not since or r["date"] >= since)]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"matches": len(rows), "entries": rows[:limit]}


@server.tool()
def relationship(company_a: str, company_b: str) -> dict:
    """Every recorded tie between two companies, both directions: AI-chain edges with all their deals, and non-AI
    relationships with their quotes."""
    a, ca = find_company(company_a)
    b, cb = find_company(company_b)
    if not a:
        return not_found(company_a, ca)
    if not b:
        return not_found(company_b, cb)
    g, ix = graph()
    edges = [{"supplier": e["source"], "customer": e["target"], "relationship": e.get("relationship"),
              "chain": e.get("chain"),
              "deals": sorted((entry(c) for c in e.get("contracts", [])), key=lambda r: r["date"], reverse=True)}
             for e in g["edges"] if {e["source"], e["target"]} == {a, b}]
    other = [e for e in ix["other"].get(a, []) if {e["source"], e["target"]} == {a, b}]
    return {"companies": [a, b], "ai_edges": edges, "other_relationships": other}


@server.tool()
def supply_chain(company: str, direction: str = "both", depth: int = 1) -> dict:
    """Who supplies the company (`up`), whom it supplies (`down`) or both, through AI-chain edges, `depth` 1 or 2
    steps away. Each link gives the relationship text and how many deals it carries."""
    nid, cands = find_company(company)
    if not nid:
        return not_found(company, cands)
    _, ix = graph()
    depth = max(1, min(int(depth), 2))

    def walk(start, key, other_side):
        links, frontier, seen = [], [start], {start}
        for step in range(1, depth + 1):
            nxt = []
            for c in frontier:
                for e in ix[key].get(c, []):
                    links.append({"step": step, "supplier": e["source"], "customer": e["target"],
                                  "relationship": e.get("relationship"), "chain": e.get("chain"),
                                  "deals": len(e.get("contracts", []))})
                    if e[other_side] not in seen:
                        seen.add(e[other_side])
                        nxt.append(e[other_side])
            frontier = nxt
        return links[:200]

    out = {"company": nid}
    if direction in ("up", "both"):
        out["upstream"] = walk(nid, "in", "source")
    if direction in ("down", "both"):
        out["downstream"] = walk(nid, "out", "target")
    return out


@server.tool()
def chain_overview(chain: str = "") -> dict:
    """Without `chain`: every product chain on the map with its company and edge counts. With a chain file name
    (e.g. 'nvidia_vera_rubin', 'hbm_memory', 'power_cooling'): its companies by layer / sector with their products,
    and its edges."""
    g, ix = graph()
    if not chain:
        counts = {}
        for n in ix["nodes"].values():
            for c in n.get("chains", []):
                counts.setdefault(c, [0, 0])[0] += 1
        for e in g["edges"]:
            counts.setdefault(e.get("chain"), [0, 0])[1] += 1
        return {"chains": [{"chain": c, "companies": v[0], "edges": v[1]} for c, v in sorted(counts.items()) if c]}
    players = []
    for nid, n in ix["nodes"].items():
        for p in n.get("products", []):
            if p.get("chain") == chain:
                players.append({"company": nid, "layer": p.get("layer") or p.get("domain"), "sector": p.get("sector"),
                                "sub_sector": p.get("sub_sector"), "product": p.get("product")})
    if not players:
        return {"error": f"no chain named '{chain}' (call chain_overview with no argument for the list)"}
    players.sort(key=lambda p: (p["layer"] or "", p["sector"] or "", p["company"]))
    edges = [{"supplier": e["source"], "customer": e["target"], "relationship": e.get("relationship"),
              "deals": len(e.get("contracts", []))} for e in g["edges"] if e.get("chain") == chain]
    return {"chain": chain, "companies": players, "edges": edges}


@server.tool()
def source_excerpt(company: str, source_label: str, contains: str = "") -> dict:
    """The verbatim passage of the company document behind facts on the map: give the company and the entry's
    source label (as returned by the other tools), optionally words of the entry's signal to pick one entry.
    News-interview entries have no excerpt by design (only the quote in the signal and the video link)."""
    nid, cands = find_company(company)
    if not nid:
        return not_found(company, cands)
    g, ix = graph()
    ev = load("evidence.json")["entries"]
    words = [w for w in contains.lower().split() if w]
    found = []
    candidates = [("qd", nid, "", q) for q in ix["nodes"][nid].get("quarterly_data", [])]
    candidates += [("contract", e["source"], e["target"], c) for e in ix["out"].get(nid, []) + ix["in"].get(nid, [])
                   for c in e.get("contracts", [])]
    for kind, src, tgt, q in candidates:
        label = q.get("quarter") or q.get("source") or ""
        if label != source_label or not all(w in (q.get("signal") or "").lower() for w in words):
            continue
        # the same key evidence.py writes: sha1("kind|company|target|label|signal")[:16]
        key = hashlib.sha1("|".join([kind, src, tgt, label, q.get("signal") or ""]).encode("utf-8")).hexdigest()[:16]
        rec = ev.get(key) or {}
        found.append({"signal": q.get("signal"), "document": rec.get("doc"), "status": rec.get("status"),
                      "excerpt": rec.get("excerpt")})
    if not found:
        return {"error": f"no entry of {nid} under '{source_label}'" + (f" containing '{contains}'" if contains else "")}
    return {"company": nid, "source": source_label, "entries": found[:10]}


@server.tool()
def map_status() -> dict:
    """How big and how fresh the map is: companies, edges, facts, newest source date, when it was last built."""
    g, ix = graph()
    facts = sum(len(n.get("quarterly_data", [])) for n in g["nodes"])
    deals = sum(len(e.get("contracts", [])) for e in g["edges"])
    newest = max((label_date(q.get("quarter")) for n in g["nodes"] for q in n.get("quarterly_data", [])), default="")
    built = datetime.fromtimestamp(os.path.getmtime(os.path.join(GRAPH, "merged_graph.json"))).strftime("%Y-%m-%d %H:%M")
    return {"companies": len(g["nodes"]), "ai_edges": len(g["edges"]), "other_relationships": len(g.get("other_edges", [])),
            "company_facts": facts, "edge_deals": deals, "newest_source_date": newest, "graph_built": built,
            "data_folder": ROOT}


def selftest():
    """Call every tool once against the real data and print a short line each (no MCP client needed)."""
    print(json.dumps(map_status(), ensure_ascii=False))
    print("search HBM:", [c["name"] for c in search_companies("HBM", 5)])
    print("search 하이닉스:", [c["name"] for c in search_companies("하이닉스", 3)])
    p = company_profile("NVIDIA", 3)
    print("NVIDIA:", len(p["suppliers"]), "suppliers,", len(p["customers"]), "customers,", p["facts_total"], "facts")
    print("entries SK Hynix HBM4:", company_entries("SK Hynix", "HBM4", limit=2)["matches"])
    print("search gigawatt:", search_entries("gigawatt", limit=1)["matches"])
    print("relationship TSMC-NVIDIA:", len(relationship("TSMC", "NVIDIA")["ai_edges"]), "edges")
    print("supply_chain Micron up:", len(supply_chain("Micron", "up")["upstream"]), "links")
    print("chains:", len(chain_overview()["chains"]))
    first = p["latest_facts"][0]
    ex = source_excerpt("NVIDIA", first["source"], " ".join((first["signal"] or "").split()[:3]))
    print("excerpt:", (ex.get("entries") or [{}])[0].get("status"), str((ex.get("entries") or [{}])[0].get("excerpt"))[:120])
    print("unknown:", company_profile("No Such Company Inc"))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        server.run("stdio")
