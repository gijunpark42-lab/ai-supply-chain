"""
taxonomy.py — the single source of truth for the supply-chain vocabulary.

The project used to model each chain as flow[] -> tier -> players[] using a fixed
bottom-up 10-tier list. That has been replaced by the user's "AI Build Supply Chain"
taxonomy: a TOP-DOWN stack of LAYERS (Application at the top, Critical Minerals at the
bottom), where each layer holds SECTORS (and a few sectors hold SUB-SECTORS), plus four
cross-cutting DOMAINS (power, thermal, security, edge AI) that sit beside the stack.

Everything that needs to know "what are the layers / what color is each / what order do
they go in" imports from here, so the vocabulary lives in ONE place instead of being
copy-pasted across app.py, graph_build.py and main.py.

Data files store SLUGS (the short machine names below) for `layer` and `domain`, and
free strings for `sector` / `sub_sector`. Human-readable display names come from the
tables here.
"""

# ── The 13 layers, TOP -> BOTTOM (this ORDER is canonical: it drives column order) ──
# Each row is (slug, display name, hex color).
# "system_integration" is a deliberate addition by the project owner — it is NOT in the
# source taxonomy PDF (which has 12 layers). It is the home for server OEM/ODM
# integrators (Foxconn, Quanta, Wistron, Supermicro, Dell, Arista), which the 12-layer
# stack has no clean slot for. It sits between Cloud Infrastructure and Compute Hardware.
LAYERS = [
    ("application",        "Application",              "#a855f7"),
    ("ai_models",          "AI Models",                "#8b5cf6"),
    ("software_infra",     "Software Infrastructure",  "#6366f1"),
    ("cloud_infra",        "Cloud Infrastructure",     "#3b82f6"),
    ("system_integration", "System Integration",       "#16a34a"),  # owner-added (not in PDF)
    ("compute_hardware",   "Compute Hardware",         "#0ea5e9"),
    ("memory",             "Memory",                   "#06b6d4"),
    ("interconnect",       "Interconnect",             "#14b8a6"),
    ("advanced_packaging", "Advanced Packaging",       "#ec4899"),
    ("foundry",            "Semiconductor Foundry",    "#f97316"),
    ("equipment",          "Semiconductor Equipment",  "#f59e0b"),
    ("materials",          "Semiconductor Materials",  "#84cc16"),
    ("minerals",           "Critical Minerals",        "#a16207"),
]

# ── The 4 cross-cutting domains (drawn beside the stack, not inside it) ──────────────
DOMAINS = [
    ("power",    "Power Infrastructure", "#dc2626"),
    ("thermal",  "Thermal Management",   "#0891b2"),
    ("security", "Security",             "#7c3aed"),
    ("edge_ai",  "Edge & Physical AI",   "#db2777"),
]

# ── Derived lookups (built once, imported everywhere) ───────────────────────────────
LAYER_ORDER  = {slug: i for i, (slug, *_) in enumerate(LAYERS)}        # for sorting columns
LAYER_COLORS = {slug: color for slug, _name, color in LAYERS}
DOMAIN_COLORS = {slug: color for slug, _name, color in DOMAINS}
LAYER_NAMES  = {slug: name for slug, name, _color in LAYERS}           # display in headers/badges
DOMAIN_NAMES = {slug: name for slug, name, _color in DOMAINS}

# Convenience: one color map covering both layers and domains (layers win on overlap,
# but the slug sets are disjoint so order doesn't matter). Handy for node coloring where
# a node may be placed in either a layer or a domain.
GROUP_COLORS = {**LAYER_COLORS, **DOMAIN_COLORS}
GROUP_NAMES  = {**LAYER_NAMES, **DOMAIN_NAMES}

# Valid slug sets — used by graph_build.py / tools to catch typos in chain files.
LAYER_SLUGS  = set(LAYER_COLORS)
DOMAIN_SLUGS = set(DOMAIN_COLORS)

# ── Home markets (the enrichment status board and the `enrich <market>` commands) ────
# A company's market comes from its `exchange` in company_metadata.json. That file spells
# some exchanges two ways ("EPA" / "Euronext Paris", "STO" / "OMX Stockholm"), so every
# spelling seen there is listed. Order of MARKETS = display order on the status board.
MARKETS = [
    ("US",    "United States"),
    ("KR",    "Korea"),
    ("TW",    "Taiwan"),
    ("JP",    "Japan"),
    ("EU",    "Europe"),
    ("CN",    "China / Hong Kong"),
    ("other", "Other listed"),
]
MARKET_OF_EXCHANGE = {
    "NASDAQ": "US", "NYSE": "US", "NYSE American": "US", "AMEX": "US", "OTC": "US",
    "KOSPI": "KR", "KOSDAQ": "KR", "KRX": "KR",
    "TWSE": "TW", "TPEx": "TW",
    "TSE": "JP", "OSE": "JP",
    "SSE": "CN", "SZSE": "CN", "HKEX": "CN",
    "XETRA": "EU", "SIX": "EU", "Euronext Paris": "EU", "EPA": "EU", "MIL": "EU",
    "OMX Stockholm": "EU", "STO": "EU", "AMS": "EU", "Euronext Amsterdam": "EU",
    "Euronext Brussels": "EU", "VIE": "EU", "LSE": "EU",
    "SGX": "other", "IDX": "other", "TSX": "other", "ASX": "other",
}


def market_of(exchange):
    """'NASDAQ' -> 'US', 'KOSDAQ' -> 'KR'. No exchange (a private company) -> None.
    An exchange missing from the table -> 'other' (add it above when a new one appears)."""
    if not exchange:
        return None
    return MARKET_OF_EXCHANGE.get(exchange, "other")


def iter_players(chain):
    """Walk every player in a chain file, regardless of nesting depth.

    A chain has an optional `flow` (the layer stack) and an optional `domains` block.
    Both have the same shape:  group -> sectors[] -> (sub_sectors[]) -> players[].
    A sector holds EITHER `players` directly OR `sub_sectors` (each with `players`).

    Yields a 5-tuple for every player:
        (player_dict, group_slug, kind, sector, sub_sector)
    where:
        group_slug  is the layer slug (kind == "layer") or domain slug (kind == "domain")
        kind        is "layer" or "domain"
        sector      is the sector string (or None if the group has no sectors)
        sub_sector  is the sub-sector string, or None

    This is the ONE place the nested loop lives, so callers (graph_build.py, app.py)
    never re-implement the 4-deep walk.
    """
    groups = (
        (chain.get("flow", []),    "layer"),
        (chain.get("domains", []), "domain"),
    )
    for group_list, kind in groups:
        slug_key = "layer" if kind == "layer" else "domain"
        for group in group_list:
            group_slug = group.get(slug_key)
            for sector in group.get("sectors", []):
                sec_name = sector.get("sector")
                # sub-sectors first (e.g. Interconnect > Scale-up > CPO)
                for sub in sector.get("sub_sectors", []):
                    sub_name = sub.get("sub_sector")
                    for player in sub.get("players", []):
                        yield player, group_slug, kind, sec_name, sub_name
                # players attached directly to the sector
                for player in sector.get("players", []):
                    yield player, group_slug, kind, sec_name, None
