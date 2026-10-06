"""
derive.py — build the DERIVED VIEWS (timelines / screener / capex) from the graph.

Why this file exists
--------------------
The graph (chains/ → graph/merged_graph.json) is the single source of truth: it keeps
the FULL multi-quarter history, every entry carries a dated source label, and it is
rebuilt on every enrichment. The Timelines, Screener and Capex tabs used to be
hand-maintained JSON files that went stale silently. This module PROJECTS the graph
onto those three views so one command (`python graph_build.py`) refreshes everything.

Rules (agreed 2026-08-27 — keep them):
  * The curated files at the repo root are INPUTS and are never written:
        timelines/*.json, company_metrics.json, capex_backlog.json
    They stay hand-editable and act as the frozen BASELINE / fallback.
  * Outputs are GENERATED files under graph/ (regenerated on every build):
        graph/timelines.bundle.json, graph/company_metrics.json, graph/capex_backlog.json
    `web/scripts/sync-data.mjs` prefers these over the root files when they exist.
  * The graph keeps history; every derived view is REPLACE-WITH-LATEST: for each
    company only the entries from its most recent source label are shown.
  * Curated timeline rows are never dropped — a generated table is APPENDED to each
    timeline. The build prints "supersede candidates" so a human can prune later.
  * Nothing here calls an LLM. It is deterministic Python over the tags below.

How enrichment feeds this (the tag vocabulary — see CLAUDE.md, Workflow 2, JOB 5)
-------------------------------------------------------------------------------
Optional keys on a `quarterly_data` entry (and `topics` also on a `contracts` entry):

    "topics": ["ocs", "cpo"]        which timeline(s) this entry belongs to.
                                     []  = explicitly none (opts out of keyword fallback)
    "slot":   "guidance"            which screener column this entry fills:
                                     revenue_growth | guidance | backlog_or_b2b |
                                     supply_status | next_catalyst
    "capex":  {"field": "capex_year", "busd": 220, "display": "~$220B",
               "period": "2026 plan"}          hyperscalers / neoclouds only.
              field = capex_q | capex_year | backlog | signal
              busd + display (+ period for capex_year, + metric/growth for backlog)
              are needed for the bar charts; the tables only need `field`.

Entries WITHOUT a "topics" key (all legacy entries) fall back to the keyword rules in
KEYWORD_RULES so past enrichment is connected too. Screener / capex have NO keyword
fallback (mis-slotting risk) — untagged companies keep their curated row until they
are re-enriched with tags.
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TIMELINES_DIR = "timelines"
METRICS_PATH = "company_metrics.json"
CAPEX_PATH = "capex_backlog.json"
OUT_DIR = "graph"

SCREENER_SLOTS = ["revenue_growth", "guidance", "backlog_or_b2b", "supply_status", "next_catalyst"]
CAPEX_FIELDS = ["capex_q", "capex_year", "backlog", "signal"]

GENERATED_TABLE_TITLE = "Latest graph signals (auto-derived)"
GENERATED_COLUMNS = ["Date", "Company", "Signal", "Figure", "Source"]

# Timeline tables whose first-ish column names a company — used only for the
# "supersede candidate" report (which curated rows now have newer graph data).
COMPANY_COLUMNS = {"Company", "Vendor", "Buyer", "Foundry", "Hyperscaler"}

# Values that mean "no real figure" — fall back to the signal text instead.
EMPTY_FIGURES = {"", "no specific figure", "not stated", "n/a", "-", "—", "�"}

# Keyword fallback for LEGACY entries (no "topics" key). Each rule = (timeline id,
# regex, flags). Patterns are deliberately specific — a false negative only means a
# row is missing from a timeline; a false positive puts noise in front of the user.
KEYWORD_RULES = [
    ("ocs", r"\bOCS\b|optical circuit switch", re.I),
    ("cpo", r"\bCPO\b|co-?packaged|\bNPO\b|near-?packaged|external light source|\bELS\b", re.I),
    ("silicon_photonics", r"silicon photonics|\bSiPho\b|\bSiPh\b|\bCW lasers?\b", re.I),
    ("optical_speed", r"(?<![\w.])(800G|1\.6T|3\.2T|400G)(?!\w)|[12]00G[- ]?(per[- ]lane|/lane)", re.I),
    ("hbm", r"\bHBM\d?E?\b|\bHBF\b|high[- ]bandwidth memory", re.I),
    ("nand_storage", r"\bNAND\b|\bSSDs?\b|\beSSD\b|\bQLC\b|\bTLC\b|\bNVMe\b", re.I),
    ("cpu", r"\bCPUs?\b|\bEPYC\b|\bXeon\b|\bGraviton\b|\bGrace\b|\bArm\b|Vera CPU", 0),
    ("foundry", r"\b(N2|N3|A16|A14|18A|14A|2nm|3nm|1\.4nm)\b|\bfoundry\b|\bEUV\b", re.I),
    ("packaging_substrate", r"\bCoWoS\b|\bSoIC\b|\bABF\b|glass[- ]core|advanced packaging|\bOSAT\b|\bFC-?BGA\b|\bT-?glass\b|interposer|\bHDI\b|\bPCBs?\b", re.I),
    # "transformer" alone would also match transformer MODELS — require the grid sense.
    ("power_cooling", r"800V|liquid[- ]cool|immersion|\bCDUs?\b|cold plate|direct-to-chip|\bcooling\b|busbar|(grid|power|large|dry-type) transformers?|substation|switchgear|\bSMRs?\b|nuclear|gas turbine|\bPPAs?\b|gigawatt", re.I),
    # case-sensitive: "mW" laser power and "speed-ups" must NOT match
    ("power_cooling", r"\bGW\b|\bMW\b|\bUPS\b|\bPDUs?\b", 0),
    # "allocation" alone would match CAPITAL allocation; "tight" alone matches "tight spec".
    ("supply_tightness", r"sold[- ]out|on allocation|allocat(ing|ed) (supply|capacity|output|wafers|lasers)|supply allocation|constrain|shortage|supply[- ]tight|tight (supply|market|capacity)|(remains?|very|extremely|incredibly) tight\b|\btightness\b|behind (customer )?demand|lead[- ]times?|fully (booked|covered)|take[- ]or[- ]pay", re.I),
    # only the four tracked transitions — a bare "transition to" matched power-plant maintenance
    ("transitions", r"HBM3E\s*(→|->|to)\s*HBM4|HBM4 (ramp|transition|cross-?over)|800G\s*(→|->|to)\s*1\.6T|1\.6T (transition|cross-?over|ramp)|air[- ]to[- ]liquid|liquid[- ]cooling transition|copper\s*(→|->|to)\s*optical|(54V|48V|415V)\s*(→|->|to)\s*800V|800V DC", re.I),
    ("product_launches", r"\b(Vera Rubin|Rubin Ultra|Blackwell Ultra|MI450|MI400|MI355|Trainium ?[23]|TPU ?v[78]|Ironwood|Helios|GB300|GB200|Feynman)\b", re.I),
]
_COMPILED_RULES = [(topic, re.compile(pat, flags)) for topic, pat, flags in KEYWORD_RULES]

_DATE_RE = re.compile(r"\((\d{2})-(\d{2})-(\d{4})\)")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def label_date(label):
    """'NVIDIA Q1 FY2027 (05-28-2026)' -> '2026-05-28'. '' when the label has no date."""
    m = _DATE_RE.search(label or "")
    if not m:
        return ""
    mm, dd, yyyy = m.groups()
    return "%s-%s-%s" % (yyyy, mm, dd)


def has_figure(text):
    """True when a figure string carries real content (not 'no specific figure' etc.)."""
    return (text or "").strip().lower() not in EMPTY_FIGURES


def best_text(entry):
    """Compact text for a table cell: the figure when it is real, else the signal."""
    fig = entry.get("figure", "")
    return fig if has_figure(fig) else entry.get("signal", "")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def latest_only(items):
    """Keep only the items whose date equals the newest date in the list.

    items = list of (date, thing). Undated items ('' date) only survive when
    nothing dated exists. This is the REPLACE-WITH-LATEST rule.
    """
    if not items:
        return []
    newest = max(d for d, _ in items)
    return [(d, t) for d, t in items if d == newest]


def topics_for(entry, known_topics, stats):
    """Timeline ids for one entry -> (topics, explicit).

    explicit=True when the enricher wrote a `topics` key (even an empty one);
    False when the keyword fallback decided.
    """
    if "topics" in entry:
        explicit = entry.get("topics") or []
        bad = [t for t in explicit if t not in known_topics]
        for t in bad:
            print("  WARNING: unknown topic %r on entry %r" % (t, (entry.get("quarter") or entry.get("source"))))
        good = [t for t in explicit if t in known_topics]
        stats["explicit"] += len(good)
        return good, True
    text = "%s %s" % (entry.get("signal", ""), entry.get("figure", ""))
    found = []
    for topic, rx in _COMPILED_RULES:
        if topic in known_topics and topic not in found and rx.search(text):
            found.append(topic)
    stats["keyword"] += len(found)
    return found, False


# Keyword-matched rows are capped per company per timeline so one long call does not
# flood a table; explicitly tagged rows are never capped (the enricher chose them).
KEYWORD_ROW_CAP = 6


# ---------------------------------------------------------------------------
# 1) TIMELINES — curated tables untouched + one generated table appended
# ---------------------------------------------------------------------------

def derive_timelines(graph):
    ids = sorted(fn[:-5] for fn in os.listdir(TIMELINES_DIR) if fn.endswith(".json"))
    curated = {tid: load_json(os.path.join(TIMELINES_DIR, tid + ".json")) for tid in ids}
    known = set(ids)
    stats = {"explicit": 0, "keyword": 0}

    # rows_by_topic[topic][company] = [(date, row_dict), ...]  (all history, trimmed below)
    rows_by_topic = {tid: {} for tid in ids}

    def collect(company, date, label, signal, figure, entry):
        topics, explicit = topics_for(entry, known, stats)
        for topic in topics:
            rows_by_topic[topic].setdefault(company, []).append(
                (date, {"company": company, "signal": signal, "figure": figure,
                        "source": label, "explicit": explicit})
            )

    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            label = q.get("quarter", "")
            fig = q.get("figure", "")
            collect(node["id"], label_date(label), label, q.get("signal", ""),
                    fig if has_figure(fig) else "", q)

    for edge in graph["edges"]:
        for c in edge.get("contracts", []):
            label = c.get("source", "")
            parts = []
            if has_figure(c.get("units")):
                parts.append("units: " + c["units"])
            if has_figure(c.get("value")):
                parts.append("value: " + c["value"])
            collect(edge["source"], label_date(label), label,
                    "→ %s: %s" % (edge["target"], c.get("signal", "")),
                    "; ".join(parts), c)

    node_ids = {n["id"] for n in graph["nodes"]}
    bundle = []
    supersede = []  # (timeline, table title, company, row label)
    trimmed = 0     # keyword-matched rows dropped by KEYWORD_ROW_CAP (reported, never silent)

    for tid in ids:
        tl = dict(curated[tid])
        tables = [dict(t) for t in tl.get("tables", [])]

        # Generated rows: latest source per company, newest first.
        rows = []
        latest_date_for = {}
        for company, items in rows_by_topic[tid].items():
            kept = latest_only(items)
            latest_date_for[company] = kept[0][0] if kept else ""
            explicit_rows = [(d, r) for d, r in kept if r["explicit"]]
            keyword_rows = [(d, r) for d, r in kept if not r["explicit"]]
            if len(keyword_rows) > KEYWORD_ROW_CAP:
                trimmed += len(keyword_rows) - KEYWORD_ROW_CAP
                keyword_rows = keyword_rows[:KEYWORD_ROW_CAP]
            for date, r in explicit_rows + keyword_rows:
                rows.append((date, company, r))
        rows.sort(key=lambda x: x[1])                 # company A→Z ...
        rows.sort(key=lambda x: x[0], reverse=True)   # ... within date, newest first (stable)
        gen_rows = [[d, c, r["signal"], r["figure"], r["source"]] for d, c, r in rows]

        # Supersede-candidate report: curated rows naming a company whose graph data
        # in THIS topic is newer than the row's own source label.
        for t in tables:
            cols = t.get("columns", [])
            ci = next((i for i, col in enumerate(cols) if col in COMPANY_COLUMNS), None)
            si = next((i for i, col in enumerate(cols) if col == "Source"), None)
            if ci is None or si is None:
                continue
            for row in t.get("rows", []):
                if len(row) <= max(ci, si):
                    continue
                company = re.sub(r"\s*\(.*?\)\s*$", "", row[ci]).strip()
                if company not in node_ids or company not in latest_date_for:
                    continue
                row_date = label_date(row[si])
                if row_date and latest_date_for[company] > row_date:
                    supersede.append((tid, t.get("title", ""), company, row[si]))

        if gen_rows:
            tables.append({
                "title": GENERATED_TABLE_TITLE,
                "columns": GENERATED_COLUMNS,
                "rows": gen_rows,
                "generated": True,
            })
        tl["tables"] = tables
        bundle.append(dict({"id": tid}, **tl))

    save_json(os.path.join(OUT_DIR, "timelines.bundle.json"), bundle)

    print("\nTimelines -> graph/timelines.bundle.json")
    print("  topic matches: %d explicit tags, %d keyword-fallback" % (stats["explicit"], stats["keyword"]))
    if trimmed:
        print("  %d keyword-matched rows trimmed by the per-company cap of %d (explicit tags are never capped)"
              % (trimmed, KEYWORD_ROW_CAP))
    for tl in bundle:
        gen = [t for t in tl["tables"] if t.get("generated")]
        n = len(gen[0]["rows"]) if gen else 0
        print("  %-22s %3d generated rows" % (tl["id"], n))
    if supersede:
        print("  supersede candidates (curated rows with newer graph data — prune by hand if wanted): %d" % len(supersede))
        for tid, title, company, src in supersede[:30]:
            print("    %s / %s: %s  [%s]" % (tid, title[:32], company, src))
        if len(supersede) > 30:
            print("    ... and %d more" % (len(supersede) - 30))
    return bundle


# ---------------------------------------------------------------------------
# 2) SCREENER — curated row as base, tagged slots override when newer
# ---------------------------------------------------------------------------

def derive_screener(graph):
    curated = load_json(METRICS_PATH) if os.path.exists(METRICS_PATH) else {}
    out = {}
    if "_schema" in curated:
        out["_schema"] = curated["_schema"]

    tagged_by_company = {}
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            slot = q.get("slot")
            if not slot:
                continue
            if slot not in SCREENER_SLOTS:
                print("  WARNING: unknown screener slot %r on %s %r" % (slot, node["id"], q.get("quarter")))
                continue
            tagged_by_company.setdefault(node["id"], []).append((label_date(q.get("quarter", "")), slot, q))

    # "Newest data" for the stale check counts only the company's OWN documents
    # ("Micron Q3 FY2026 (…)"), not a peer's call that mentions it ("NVIDIA Q2 FY2027"
    # on the Micron node) — otherwise every hyperscaler looked stale after each NVIDIA call.
    all_ids = [n["id"] for n in graph["nodes"]]

    def own_source(label, nid):
        if not label.startswith(nid + " "):
            return False
        # "Samsung Foundry Q2 …" is Samsung Foundry's label, not Samsung's.
        return not any(o != nid and o.startswith(nid + " ") and label.startswith(o + " ") for o in all_ids)

    latest_graph_date = {}
    for node in graph["nodes"]:
        dates = [label_date(q.get("quarter", "")) for q in node.get("quarterly_data", [])
                 if own_source(q.get("quarter", ""), node["id"])]
        latest_graph_date[node["id"]] = max(dates) if dates else ""

    updated, added, stale = [], [], []
    companies = [k for k in curated if k != "_schema"]
    companies += sorted(c for c in tagged_by_company if c not in curated)

    for company in companies:
        base = dict(curated.get(company, {}))
        base_asof = base.get("asof", "") or ""
        tagged = tagged_by_company.get(company, [])
        if not tagged:
            out[company] = base
            if base_asof and latest_graph_date.get(company, "") > base_asof:
                stale.append((company, base_asof, latest_graph_date[company]))
            continue
        row = dict(base)
        touched = False
        for slot in SCREENER_SLOTS:
            cands = [(d, q) for d, s, q in tagged if s == slot]
            kept = latest_only(cands)
            if not kept:
                continue
            date, q = kept[0]
            # REPLACE-WITH-LATEST: a tagged entry only overrides a curated slot when it
            # is at least as new as the curated snapshot.
            if base_asof and date and date < base_asof:
                continue
            row[slot] = best_text(q)
            touched = True
        newest = max(d for d, _, _ in tagged)
        if touched:
            row["asof"] = max(base_asof, newest)
            (updated if company in curated else added).append(company)
        out[company] = row

    save_json(os.path.join(OUT_DIR, "company_metrics.json"), out)
    print("\nScreener -> graph/company_metrics.json")
    print("  rows: %d (%d updated from graph tags, %d new from graph tags)" % (len(out) - ("_schema" in out), len(updated), len(added)))
    if stale:
        print("  stale curated rows (graph has newer data but no `slot` tags yet): %d" % len(stale))
        for company, asof, latest in sorted(stale, key=lambda x: x[2], reverse=True):
            print("    %-28s screener %s  <  graph %s" % (company, asof, latest))
    return out


# ---------------------------------------------------------------------------
# 3) CAPEX — curated file as base, capex-tagged entries override bars + rows
# ---------------------------------------------------------------------------

def _node_for_name(name, node_ids):
    """Map a capex display name ('Amazon (AWS)', 'Alphabet (Google)') to a graph node id."""
    cands = [name]
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", name or "")
    if m:
        cands += [m.group(1).strip(), m.group(2).strip()]
    for c in cands:
        if c in node_ids:
            return c
    return None


def derive_capex(graph):
    if not os.path.exists(CAPEX_PATH):
        print("\nCapex: no %s — skipped" % CAPEX_PATH)
        return None
    out = load_json(CAPEX_PATH)
    node_ids = {n["id"] for n in graph["nodes"]}

    # tagged[company][field] = [(date, entry, capex_tag), ...]
    tagged = {}
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            tag = q.get("capex")
            if not tag:
                continue
            field = tag.get("field")
            if field not in CAPEX_FIELDS:
                print("  WARNING: unknown capex field %r on %s %r" % (field, node["id"], q.get("quarter")))
                continue
            tagged.setdefault(node["id"], {}).setdefault(field, []).append((label_date(q.get("quarter", "")), q, tag))

    def newest(company, field):
        kept = latest_only([(d, (q, t)) for d, q, t in tagged.get(company, {}).get(field, [])])
        return kept[0] if kept else None  # (date, (entry, tag))

    changed = 0
    newest_date = ""

    # Tables (groups[].rows[]): each field independently, newest wins.
    for group in out.get("groups", []):
        for row in group.get("rows", []):
            company = _node_for_name(row.get("name"), node_ids)
            if not company or company not in tagged:
                continue
            row_date = label_date(row.get("source", ""))
            used_labels = []
            for field in CAPEX_FIELDS:
                hit = newest(company, field)
                if not hit:
                    continue
                date, (q, _tag) = hit
                if row_date and date and date < row_date:
                    continue
                row[field] = best_text(q)
                used_labels.append((date, q.get("quarter", "")))
                changed += 1
            if used_labels:
                d, lbl = max(used_labels)
                row["source"] = lbl
                newest_date = max(newest_date, d)

    # Bars: capex_bars from field=capex_year, backlog_bars from field=backlog (busd required).
    for key, field in (("capex_bars", "capex_year"), ("backlog_bars", "backlog")):
        block = out.get(key, {})
        bars = block.get("bars", [])
        seen = set()
        for bar in bars:
            company = _node_for_name(bar.get("name"), node_ids)
            if not company:
                continue
            seen.add(company)
            hit = newest(company, field)
            if not hit or hit[1][1].get("busd") is None:
                continue
            date, (q, tag) = hit
            if label_date(bar.get("source", "")) and date and date < label_date(bar.get("source", "")):
                continue
            bar["busd"] = tag["busd"]
            bar["display"] = tag.get("display", bar.get("display", ""))
            for k in ("period", "metric", "growth"):
                if tag.get(k):
                    bar[k] = tag[k]
            bar["detail"] = q.get("signal", bar.get("detail", ""))
            bar["source"] = q.get("quarter", "")
            newest_date = max(newest_date, date)
            changed += 1
        # Companies tagged for this field but not yet in the curated bars → append.
        for company in sorted(tagged):
            if company in seen:
                continue
            hit = newest(company, field)
            if not hit or hit[1][1].get("busd") is None:
                continue
            date, (q, tag) = hit
            bar = {"name": company, "busd": tag["busd"], "display": tag.get("display", ""),
                   "detail": q.get("signal", ""), "source": q.get("quarter", "")}
            for k in ("period", "metric", "growth"):
                if tag.get(k):
                    bar[k] = tag[k]
            bars.append(bar)
            newest_date = max(newest_date, date)
            changed += 1

    if newest_date and newest_date > (out.get("updated") or ""):
        out["updated"] = newest_date

    save_json(os.path.join(OUT_DIR, "capex_backlog.json"), out)
    print("\nCapex -> graph/capex_backlog.json")
    print("  %d bar/table fields refreshed from `capex` tags (%d companies tagged)" % (changed, len(tagged)))
    return out


# ---------------------------------------------------------------------------
# 4) EXPOSURE — "who benefits" ranking per chain / generation transition
# ---------------------------------------------------------------------------
#
# graph/exposure.json feeds the web app's Exposure tab (web/src/components/Exposure.tsx).
# For every company it carries the counts behind an EXPLAINABLE score per chain, the
# latest text per screener slot, the topic-tag counts, its status in each generation
# transition, and its customer / supplier concentration facts.
#
# The score is deliberately simple and stable — no learned weights, nothing hidden:
#
#   score(company, chain) = role weight                 what it makes in this chain
#                         + 0.5 x min(contracts, 10)    deal facts on its edges in this chain
#                         + 0.5 x min(edges, 8)         how wired-in it is in this chain
#                         + freshness bonus             +2 if its newest source document is
#                                                       <= 90 days old, +1 if <= 180, else 0
#
# rounded to one decimal. Role weight is the HEAVIEST role the company plays in that
# chain (a company can hold two roles in one chain, e.g. Meta = AI model + cloud):
#
#   3  compute_hardware, memory, interconnect, advanced_packaging, foundry   (the chip itself)
#   2  equipment, materials                                                  (one step removed)
#   2  cloud_infra, ai_models, application, system_integration, power, thermal (buyers / racks)
#   1  minerals, software_infra, security, edge_ai                           (far from the socket)
#
# "Edges in this chain" and "contracts in this chain" count BOTH directions — a deal on
# the edge SK Hynix -> NVIDIA is evidence for both companies. Freshness is company-level
# (newest label across its quarterly_data and the contracts on its edges): a company's
# most recent earnings call is what tells you whether its numbers are current.
#
# Only chains the company is a MEMBER of (node.chains) get a score. An edge can point at
# a company that is not a player in that chain file (Anthropic as a customer inside
# amd_mi450_helios); such edges still count in the company-level totals below.

EXPOSURE_PATH = os.path.join(OUT_DIR, "exposure.json")
CHAINS_DIR = "chains"
# Contract `type`s that state "customer X is n% of the supplier's revenue" (lower case): DART, EDGAR and EDINET
# (edinet.py: 主要な相手先別の販売実績 in a Japanese annual / semi-annual securities report), and China
# (cninfo.py reports: a named customer of the 前五名客户 table in an A-share annual / half-year report).
CONCENTRATION_TYPES = {"customer share", "10-k customer concentration", "10-q customer concentration",
                       "20-f customer concentration", "40-f customer concentration", "prospectus customer concentration",
                       "annual securities report customer share", "semi-annual report customer share",
                       "annual report customer share", "half-year report customer share"}

ROLE_WEIGHT = {
    "compute_hardware": 3, "memory": 3, "interconnect": 3, "advanced_packaging": 3, "foundry": 3,
    "equipment": 2, "materials": 2,
    "cloud_infra": 2, "ai_models": 2, "application": 2, "system_integration": 2,
    "power": 2, "thermal": 2,
    "minerals": 1, "software_infra": 1, "security": 1, "edge_ai": 1,
}
DEFAULT_ROLE_WEIGHT = 1     # an unknown slug (typo in a chain file) is scored like minerals
CONTRACT_STEP, CONTRACT_CAP = 0.5, 10   # +0.5 per contract, capped at 10 contracts (= +5.0)
EDGE_STEP, EDGE_CAP = 0.5, 8            # +0.5 per edge, capped at 8 edges (= +4.0)
FRESH_DAYS, FRESH_BONUS = 90, 2         # newest source <= 90 days old  -> +2
AGING_DAYS, AGING_BONUS = 180, 1        # newest source <= 180 days old -> +1

EXPOSURE_FORMULA = (
    "score(company, chain) = role weight (3 = compute/memory/interconnect/packaging/foundry, "
    "2 = equipment/materials/cloud/AI models/application/system integration/power/thermal, "
    "1 = minerals/software/security/edge) + 0.5 x min(contracts on its edges in the chain, 10) "
    "+ 0.5 x min(edges in the chain, 8) + freshness (+2 if the newest source is <= 90 days old, "
    "+1 if <= 180 days); rounded to 1 decimal"
)

# Mirror of TRANSITIONS in web/src/lib/transitions.ts: (key, current-gen chains, next-gen chains).
# Keep the two lists in sync when a new generation chain is added.
EXPOSURE_TRANSITIONS = [
    ("nvidia", ["nvda_b200"], ["nvidia_vera_rubin"]),
    ("amd", ["amd_mi355"], ["amd_mi450_helios"]),
    ("aws", ["aws_trainium2"], ["aws_trainium3"]),
    ("google", ["google_tpu_v7_ironwood"], ["tpu_v8t", "tpu_v8i"]),
]

# A share reads "5.0% of H1 2026 revenue" / "12% share" — try that shape first, so a
# price change earlier in the same sentence ("price +211% YoY") does not win.
_PCT_SHARE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:of\b|share\b|revenue\b)", re.I)
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _first_pct(*texts):
    """The revenue-share percentage in the given strings, as a float — or None.

    Pass 1 looks for a share-shaped percentage ('5.0% of ...', '12% share'); pass 2 takes
    the first percentage at all. Anything above 100 cannot be a share (it is a growth
    rate) and is ignored. Heuristic on purpose — the number can still be an aggregate
    ('top-5 customers ~25%'), so the raw text always travels next to it.
    """
    for rx in (_PCT_SHARE_RE, _PCT_RE):
        for text in texts:
            for m in rx.finditer(text or ""):
                pct = float(m.group(1))
                if pct <= 100:
                    return pct
    return None


def _chain_files():
    """chain slug -> (folder group, top-level 'company' field) for every chains/**/*.json.

    The folder name ('accelerators', 'components', 'manufacturing') groups the chain
    selector in the web app; the 'company' field says who the chain is about. A missing
    chains/ directory (running from elsewhere) simply yields {}.
    """
    found = {}
    if not os.path.isdir(CHAINS_DIR):
        return found
    for root, _dirs, files in os.walk(CHAINS_DIR):
        rel = os.path.relpath(root, CHAINS_DIR)
        group = "" if rel == "." else rel.replace(os.sep, "/").split("/")[0]
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                company = load_json(os.path.join(root, fn)).get("company")
            except (OSError, ValueError):
                company = None
            found[fn[:-5]] = (group, company)
    return found


def _days_between(today, iso_date):
    """Whole days from an ISO date ('2026-08-27') up to `today`; None when there is no date."""
    from datetime import date
    if not iso_date:
        return None
    y, m, d = (int(x) for x in iso_date.split("-"))
    return max(0, (today - date(y, m, d)).days)


def derive_exposure(graph, today=None):
    """Write graph/exposure.json — per-company, per-chain exposure scores and facts.

    `today` (a datetime.date) exists so a test can pin the freshness bonus; the build
    uses the real date. Everything else is a deterministic function of the graph.
    """
    from datetime import date
    today = today or date.today()

    nodes = graph["nodes"]
    edges = graph["edges"]
    node_ids = {n["id"] for n in nodes}
    member_chains = {n["id"]: list(n.get("chains") or []) for n in nodes}

    # ── Pass 1: walk the edges once and bucket what each company gets from them ──
    per_chain = {}            # company -> chain -> {"edges", "contracts", "partners": set}
    partners_all = {}         # company -> every distinct edge partner + folded counterparty
    in_degree, out_degree = {}, {}
    edges_with_contracts, contracts_total = {}, {}
    latest = {}               # company -> newest ISO date across all its sources
    topics = {}               # company -> {topic: count}
    concentration = {}        # company -> [fact, ...]
    chain_edges, chain_contracts = {}, {}

    def bucket(company, chain):
        return per_chain.setdefault(company, {}).setdefault(
            chain, {"edges": 0, "contracts": 0, "partners": set()})

    def bump_topics(company, entry):
        for t in entry.get("topics") or []:
            counts = topics.setdefault(company, {})
            counts[t] = counts.get(t, 0) + 1

    for e in edges:
        s, t, chain = e["source"], e["target"], e.get("chain")
        contracts = e.get("contracts") or []
        out_degree[s] = out_degree.get(s, 0) + 1
        in_degree[t] = in_degree.get(t, 0) + 1
        chain_edges[chain] = chain_edges.get(chain, 0) + 1
        chain_contracts[chain] = chain_contracts.get(chain, 0) + len(contracts)
        for company, other in ((s, t), (t, s)):
            b = bucket(company, chain)
            b["edges"] += 1
            b["contracts"] += len(contracts)
            b["partners"].add(other)
            partners_all.setdefault(company, set()).add(other)
            contracts_total[company] = contracts_total.get(company, 0) + len(contracts)
            if contracts:
                edges_with_contracts[company] = edges_with_contracts.get(company, 0) + 1
        for c in contracts:
            d = label_date(c.get("source", ""))
            for company in (s, t):
                latest[company] = max(latest.get(company, ""), d)
                bump_topics(company, c)
            # A "customer share" contract is a filed major-customer fact on an edge: the
            # target is x% of the source's revenue -> a concentration fact for the source.
            # `enrich edgar` writes the same fact as "10-K / 10-Q customer concentration";
            # before 2026-09-26 only "customer share" was read, so those never reached Exposure.
            if (c.get("type") or "").strip().lower() in CONCENTRATION_TYPES:
                text = c.get("signal", "")
                if has_figure(c.get("value")):
                    text = "%s — %s" % (text, c["value"])
                concentration.setdefault(s, []).append({
                    "counterparty": t,
                    "role": "customer",
                    "pct": _first_pct(c.get("value"), c.get("units"), c.get("signal")),
                    "text": text,
                    "label": c.get("source", ""),
                    "chain": chain,
                })

    # ── Pass 2: node-level entries (dates, topics, screener slots, folded counterparties) ──
    slot_cands = {}           # company -> slot -> [(date, entry)]
    for n in nodes:
        cid = n["id"]
        for q in n.get("quarterly_data") or []:
            d = label_date(q.get("quarter", ""))
            latest[cid] = max(latest.get(cid, ""), d)
            bump_topics(cid, q)
            slot = q.get("slot")
            if slot in SCREENER_SLOTS:
                slot_cands.setdefault(cid, {}).setdefault(slot, []).append((d, q))
            cp = q.get("counterparty")
            if cp:
                # A customer/supplier deal folded onto the company's own node because the
                # counterparty is not a chain member. It still names a real partner.
                partners_all.setdefault(cid, set()).add(cp)
                if q.get("chain") in member_chains[cid]:
                    bucket(cid, q["chain"])["partners"].add(cp)
                text = q.get("signal", "")
                if has_figure(q.get("figure")):
                    text = "%s — %s" % (text, q["figure"])
                concentration.setdefault(cid, []).append({
                    "counterparty": cp,
                    "role": q.get("counterparty_role") or "counterparty",
                    "pct": _first_pct(q.get("figure"), q.get("signal")),
                    "text": text,
                    "label": q.get("quarter", ""),
                    "chain": q.get("chain"),
                })

    # ── Pass 3: one record per company, scored per chain ──
    companies = {}
    for n in sorted(nodes, key=lambda x: x["id"]):
        cid = n["id"]
        chains = member_chains[cid]
        products = n.get("products") or []
        newest = latest.get(cid, "")
        days = _days_between(today, newest)
        if days is None:
            fresh_bonus = 0
        elif days <= FRESH_DAYS:
            fresh_bonus = FRESH_BONUS
        elif days <= AGING_DAYS:
            fresh_bonus = AGING_BONUS
        else:
            fresh_bonus = 0

        chain_stats, score_by_chain = {}, {}
        for chain in chains:
            weights = [ROLE_WEIGHT.get(p.get("layer") or p.get("domain"), DEFAULT_ROLE_WEIGHT)
                       for p in products if p.get("chain") == chain]
            role_w = max(weights) if weights else DEFAULT_ROLE_WEIGHT
            b = per_chain.get(cid, {}).get(chain, {})
            n_edges = b.get("edges", 0)
            n_contracts = b.get("contracts", 0)
            score = (role_w
                     + CONTRACT_STEP * min(n_contracts, CONTRACT_CAP)
                     + EDGE_STEP * min(n_edges, EDGE_CAP)
                     + fresh_bonus)
            score_by_chain[chain] = round(score, 1)
            chain_stats[chain] = {
                "role_weight": role_w,
                "edges": n_edges,
                "contracts": n_contracts,
                "counterparties": len(b.get("partners", ())),
            }

        # Screener slots: the latest-dated tagged entry per slot (same rule as derive_screener).
        slots, slot_sources = {}, {}
        for slot in SCREENER_SLOTS:
            kept = latest_only(slot_cands.get(cid, {}).get(slot, []))
            if kept:
                _d, q = kept[0]
                slots[slot] = best_text(q)
                slot_sources[slot] = q.get("quarter", "")

        # Generation status — the same rule as computeTransition() in transitions.ts.
        generations = {}
        for key, frm, to in EXPOSURE_TRANSITIONS:
            in_from = any(c in chains for c in frm)
            in_to = any(c in chains for c in to)
            if in_from or in_to:
                generations[key] = "retained" if (in_from and in_to) else ("gained" if in_to else "lost")

        facts = concentration.get(cid, [])
        # Largest share first; facts with no extractable % go last, then A→Z by partner.
        facts.sort(key=lambda f: (f["pct"] is None, -(f["pct"] or 0), f["counterparty"]))

        companies[cid] = {
            "ticker": n.get("ticker"),
            "exchange": n.get("exchange"),
            "country": n.get("country"),
            "status": n.get("status"),
            "chains": chains,
            "primary": (n.get("layers") or n.get("domains") or [None])[0],
            "roles": [{"chain": p.get("chain"), "layer": p.get("layer"), "domain": p.get("domain"),
                       "sector": p.get("sector"), "sub_sector": p.get("sub_sector"),
                       "product": p.get("product")} for p in products],
            "in_degree": in_degree.get(cid, 0),
            "out_degree": out_degree.get(cid, 0),
            "edges_with_contracts": edges_with_contracts.get(cid, 0),
            "contracts_total": contracts_total.get(cid, 0),
            "counterparties": len(partners_all.get(cid, ())),
            "signals": len(n.get("quarterly_data") or []),
            "latest": newest or None,
            "days_since": days,
            "freshness_bonus": fresh_bonus,
            "topics": dict(sorted(topics.get(cid, {}).items())),
            "slots": slots,
            "slot_sources": slot_sources,
            "generations": generations,
            "concentration": facts,
            "score_by_chain": score_by_chain,
            "chain_stats": chain_stats,
        }

    # ── Chains: members ranked by score, plus the anchor company and folder group ──
    files = _chain_files()
    chains_out = {}
    for chain in sorted({c for cs in member_chains.values() for c in cs}):
        members = [cid for cid, cs in member_chains.items() if chain in cs]
        members.sort(key=lambda cid: (-companies[cid]["score_by_chain"][chain], cid))
        group, company = files.get(chain, ("", None))
        chains_out[chain] = {
            "anchor": company if company in node_ids else None,
            "group": group,
            "members": members,
            "edges": chain_edges.get(chain, 0),
            "contracts": chain_contracts.get(chain, 0),
        }

    out = {
        "generated": today.isoformat(),
        "formula": EXPOSURE_FORMULA,
        "weights": {
            "role": ROLE_WEIGHT, "default_role": DEFAULT_ROLE_WEIGHT,
            "contract_step": CONTRACT_STEP, "contract_cap": CONTRACT_CAP,
            "edge_step": EDGE_STEP, "edge_cap": EDGE_CAP,
            "fresh_days": FRESH_DAYS, "fresh_bonus": FRESH_BONUS,
            "aging_days": AGING_DAYS, "aging_bonus": AGING_BONUS,
        },
        "transitions": [{"key": k, "from": f, "to": t} for k, f, t in EXPOSURE_TRANSITIONS],
        "companies": companies,
        "chains": chains_out,
    }
    # Compact JSON (no indent): the browser downloads this file, so size matters.
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(EXPOSURE_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    with_facts = sum(1 for c in companies.values() if c["concentration"])
    print("\nExposure -> %s" % EXPOSURE_PATH.replace(os.sep, "/"))
    print("  %d companies scored across %d chains · %d with concentration facts · %d KB"
          % (len(companies), len(chains_out), with_facts, os.path.getsize(EXPOSURE_PATH) // 1024))
    print("  formula: " + EXPOSURE_FORMULA)
    for chain, block in chains_out.items():
        top = ", ".join("%s %.1f" % (cid, companies[cid]["score_by_chain"][chain])
                        for cid in block["members"][:3])
        print("  %-22s %3d members  top: %s" % (chain, len(block["members"]), top))
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def derive_all(graph):
    """Run all three projections. `graph` is the dict graph_build.build_graph() returns."""
    derive_timelines(graph)
    derive_screener(graph)
    derive_capex(graph)
    derive_exposure(graph)


if __name__ == "__main__":
    # Standalone use: re-derive from the graph already on disk without rebuilding it.
    sys.stdout.reconfigure(encoding="utf-8")
    derive_all(load_json(os.path.join(OUT_DIR, "merged_graph.json")))
