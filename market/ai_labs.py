"""AI-lab business metrics and per-model benchmark scores -> graph/ai_labs.json (data contract 5).

Sources (all free, fetched by script once a day, no model tokens):
  (a) Epoch AI "Data on AI companies"  https://epoch.ai/data/ai_companies.zip  (CC BY 4.0)
      -> revenue reports (annualized revenue), funding rounds (amount, post-money), compute spend.
  (b) Epoch AI "Capabilities & benchmarking" https://epoch.ai/data/benchmark_data.zip  (CC BY 4.0)
      -> per-model scores (ECI, GPQA Diamond, SWE-bench Verified, FrontierMath, ...).
  (c) market/ai_lab_deals.json: a curated ADD-only log of lab deals (compute, chips, leases, power).
      Seeded from Nodus42 transcripts; the nightly enrich session appends to it. This module only READS it.

These are NOT supply-chain "signals": nothing here touches quarterly_data, chains/, patches/ or derive.py.

How a run works:
  1. Download each Epoch zip into market/cache/ (skipped when already fetched today, or when the server
     says the file is unchanged: ETag / Last-Modified -> HTTP 304).
  2. Read the CSV files straight out of the zip (nothing is extracted to disk).
  3. Append the rows to market/history/<dataset>.jsonl (ADD-only, deduplicated by key).
  4. build(): rebuild graph/ai_labs.json from the history files + the deals log.

CLI:  python -m market.ai_labs [--backfill] [--build-only]
  --backfill    force a fresh download (ignore the once-a-day guard and the ETag)
  --build-only  no network, just rebuild graph/ai_labs.json from history
"""
import argparse
import csv
import datetime as dt
import io
import os
import sys
import zipfile
from urllib.parse import urlparse

from market.common import (ROOT, GRAPH, load_env, today, get, read_json, write_json,
                           read_history, append_history, universe, config)

CACHE = ROOT / "market" / "cache"
DEALS_FILE = ROOT / "market" / "ai_lab_deals.json"
OUT_PATH = GRAPH / "ai_labs.json"

COMPANIES_ZIP = "https://epoch.ai/data/ai_companies.zip"
COMPANIES_PAGE = "https://epoch.ai/data/ai-companies"
BENCH_ZIP = "https://epoch.ai/data/benchmark_data.zip"
BENCH_PAGE = "https://epoch.ai/benchmarks"
SOURCE_ID = "epoch_ai"                  # the display switch in market/config.json ("show")
ATTRIBUTION = "Epoch AI (CC BY 4.0)"
MAX_ZIP_BYTES = 100 * 1024 * 1024       # refuse anything absurdly large

# History datasets (market/history/<name>.jsonl) and the fields that make a row unique.
# "seen" (the day we first saw that exact row) is NOT part of the key, so re-running on the same day,
# or on a day when Epoch changed nothing, adds no rows. When Epoch revises a value, the new version is
# a new key -> a new row, and build() keeps the most recently seen version.
DS_REVENUE = "ai_lab_revenue"
DS_FUNDING = "ai_lab_funding"
DS_COMPUTE = "ai_lab_compute"
DS_SCORES = "ai_model_scores"
KEY_REVENUE = ("lab", "epoch_id", "date", "annualized_usd", "type", "url")
KEY_FUNDING = ("lab", "epoch_id", "date", "round", "amount_usd", "post_money_usd", "url")
KEY_COMPUTE = ("lab", "epoch_id", "date", "amount_usd", "period", "category", "url")
KEY_SCORES = ("model", "benchmark", "score", "lab", "release_date")

# Models: keep "frontier" models released in the last ~24 months. A model counts as frontier when its
# Epoch Capabilities Index (ECI) is within FRONTIER_MARGIN points of the best ECI of any model released
# before it, or when it is one of its lab's TOP_PER_LAB best models in the window (for the labs in LAB_ORDER,
# so every tracked lab shows something).
MODEL_WINDOW_DAYS = 730
FRONTIER_MARGIN = 12.0
TOP_PER_LAB = 3
SCORE_HISTORY_DAYS = 1095   # store non-ECI scores for models up to ~3 years old (ECI is stored for all models)

# Epoch's company / organization names -> one lab id used everywhere in ai_labs.json and ai_lab_deals.json.
LAB_ALIASES = {
    "Google": "Google DeepMind", "Google DeepMind": "Google DeepMind",
    "Meta": "Meta", "Meta AI": "Meta",
    "Z.ai (Zhipu)": "Z.ai (Zhipu)", "Z.ai (Zhipu AI)": "Z.ai (Zhipu)", "Zhipu AI": "Z.ai (Zhipu)",
    "Moonshot": "Moonshot AI", "Moonshot AI": "Moonshot AI",
    "Nvidia": "NVIDIA", "NVIDIA": "NVIDIA",
    "Microsoft": "Microsoft", "Microsoft Research": "Microsoft", "Microsoft AI": "Microsoft",
    "Thinking Machines": "Thinking Machines", "Thinking Machines Lab": "Thinking Machines",
    "Mistral": "Mistral AI", "Mistral AI": "Mistral AI",
}

# Lab id -> graph node id. Checked against graph/merged_graph.json at build time (a missing node becomes null).
LAB_NODE = {
    "OpenAI": "OpenAI", "Anthropic": "Anthropic", "Google DeepMind": "Google", "Meta": "Meta",
    "xAI": "SpaceX",            # in the graph, xAI's Grok / Colossus work sits on the "SpaceX" node
    "Mistral AI": "Mistral", "Cohere": "Cohere", "Z.ai (Zhipu)": "Zhipu AI", "MiniMax": "MiniMax",
    "Alibaba": "Alibaba", "Amazon": "Amazon", "NVIDIA": "NVIDIA", "Microsoft": "Microsoft",
    "Thinking Machines": "Thinking Machines Lab", "DeepSeek": None, "Moonshot AI": None,
}

# Display order of the labs (others follow alphabetically).
LAB_ORDER = ["OpenAI", "Anthropic", "Google DeepMind", "xAI", "Meta", "Mistral AI", "Cohere",
             "DeepSeek", "Z.ai (Zhipu)", "MiniMax", "Moonshot AI"]

# Epoch's revenue "type" labels -> short English labels for the website.
REVENUE_TYPES = {
    "Annualized run rate": "run rate",
    "Annual recurring revenue (ARR)": "ARR",
    "Period interpolation": "annualized from period revenue",
}

# Benchmarks we publish: (id, label, file in benchmark_data.zip, score column, unit, higher_is_better, origin).
# unit "%" = the score is a fraction in the file (times the "scale" in benchmark_metadata.csv) shown as percent.
# origin = who runs the benchmark; "Epoch AI" for Epoch's own evaluations, else the external leaderboard
# whose results Epoch compiles into the same CC BY 4.0 download.
BENCHMARKS = [
    ("eci", "Epoch Capabilities Index", "epoch_capabilities_index/eci_scores.csv", "eci", "index", True, "Epoch AI"),
    ("gpqa_diamond", "GPQA Diamond", "gpqa_diamond.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("swe_bench_verified", "SWE-bench Verified", "swe_bench_verified.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("frontiermath", "FrontierMath Tiers 1-3", "frontiermath_tiers_1_3_v2.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("frontiermath_tier4", "FrontierMath Tier 4", "frontiermath_tier_4_v2.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("otis_mock_aime", "OTIS Mock AIME 2024-2025", "otis_mock_aime_2024_2025.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("math_level_5", "MATH Level 5", "math_level_5.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("simpleqa_verified", "SimpleQA Verified", "simpleqa_verified.csv", "Best score (across scorers)", "%", True, "Epoch AI"),
    ("hle", "Humanity's Last Exam", "hle_external.csv", "Accuracy", "%", True, "external leaderboard (HLE)"),
    ("arc_agi_2", "ARC-AGI-2", "arc_agi_2_external.csv", "Score", "%", True, "external leaderboard (ARC Prize)"),
    ("terminal_bench", "Terminal-Bench", "terminalbench_external.csv", "Accuracy mean", "%", True, "external leaderboard (Terminal-Bench)"),
    ("metr_time_horizon", "METR time horizon (50%)", "metr_time_horizons_external.csv", "Time horizon", "minutes", True, "external (METR)"),
    ("webdev_arena", "WebDev Arena", "webdev_arena_external.csv", "Arena Score", "Elo", True, "external leaderboard (LMArena)"),
]


def log(msg):
    print(f"[ai_labs] {msg}")


def warn(msg):
    print(f"[ai_labs] WARNING: {msg}")


# ---------------------------------------------------------------- small helpers

def lab_id(name):
    """Epoch company/organization text -> our lab id. 'Google DeepMind,Google' -> 'Google DeepMind'."""
    first = (name or "").split(",")[0].strip()
    return LAB_ALIASES.get(first, first) or None


def num(text):
    """'1.5e9' / '1,500' / '' -> float or None."""
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean_date(text):
    """Keep only real YYYY-MM-DD dates."""
    text = (text or "").strip()[:10]
    try:
        dt.date.fromisoformat(text)
        return text
    except ValueError:
        return None


def first_url(*texts):
    """The first http(s) link among Epoch's 'Source 1/2/3' cells (cells sometimes carry stray tabs/spaces)."""
    for t in texts:
        t = (t or "").strip().split()[0] if (t or "").strip() else ""
        if t.startswith("http://") or t.startswith("https://"):
            return t
    return None


def via(url, fallback):
    """'Epoch AI via ft.com' for a row whose original report is on ft.com."""
    if not url:
        return fallback
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"Epoch AI via {host}" if host else fallback


def as_int(x):
    return None if x is None else int(round(x))


def latest_by(rows, identity):
    """For each identity tuple keep the row seen last (history is append-only, so later lines are newer)."""
    best = {}
    for r in rows:
        k = tuple(r.get(f) for f in identity)
        old = best.get(k)
        if old is None or (r.get("seen") or "") >= (old.get("seen") or ""):
            best[k] = r
    return list(best.values())


# ---------------------------------------------------------------- download (polite, cached)

def fetch_zip(url, name, force=False):
    """Download an Epoch zip into market/cache/<name>. Returns the zip bytes, or None if nothing is usable.

    Politeness: at most one network request per file per day (unless force), and a conditional GET
    (If-None-Match / If-Modified-Since) so an unchanged file is not downloaded again (HTTP 304).
    If the source is down, the previously cached copy is used."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / name
    meta_path = CACHE / f"{name}.meta.json"
    meta = read_json(meta_path, {}) or {}
    cached = path.read_bytes() if path.exists() else None

    if cached and not force and meta.get("checked") == today():
        log(f"{name}: already checked today, using cache")
        return cached

    headers = {}
    if cached and not force:
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
    try:
        r = get(url, headers=headers, timeout=60)
    except Exception as e:                                    # network error after retries
        warn(f"{name}: download failed ({type(e).__name__}); {'using cached copy' if cached else 'no cached copy'}")
        return cached

    if r.status_code == 304 and cached:
        log(f"{name}: unchanged since last download (HTTP 304)")
        meta["checked"] = today()
        write_json(meta_path, meta)
        return cached
    if r.status_code != 200:
        warn(f"{name}: HTTP {r.status_code}; {'using cached copy' if cached else 'no cached copy'}")
        return cached
    data = r.content
    if len(data) > MAX_ZIP_BYTES or not zipfile.is_zipfile(io.BytesIO(data)):
        warn(f"{name}: response is not a usable zip; {'using cached copy' if cached else 'no cached copy'}")
        return cached

    tmp = path.with_suffix(path.suffix + ".tmp")              # atomic replace, like write_json
    tmp.write_bytes(data)
    os.replace(tmp, path)
    meta = {"url": url, "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified"),
            "downloaded": today(), "checked": today(), "bytes": len(data)}
    write_json(meta_path, meta)
    log(f"{name}: downloaded {len(data):,} bytes")
    return data


def read_csv(zf, member):
    """Rows of one CSV inside an open zip, as dicts (read in memory, never extracted)."""
    with zf.open(member) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")))


# ---------------------------------------------------------------- parse: AI companies

def parse_companies(data, seen):
    """ai_companies.zip -> (revenue rows, funding rows, compute rows) for the history files."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    revenue, funding, compute = [], [], []

    # Revenue reports: one row per reported figure. Only full-company figures (product-only figures such
    # as "ChatGPT revenue" would make the company line jump around).
    if "ai_companies_revenue_reports.csv" in names:
        for r in read_csv(zf, "ai_companies_revenue_reports.csv"):
            if (r.get("Scope") or "").strip() != "Full company":
                continue
            date = clean_date(r.get("Date"))
            lab = lab_id(r.get("Company"))
            if not date or not lab:
                continue
            value = num(r.get("Annualized revenue (USD)"))
            if value is None:
                value = num(r.get("Revenue amount (normalize to annual)"))
            period = (r.get("Period type") or "").strip()
            if value is None and period == "Year":
                value = num(r.get("Period revenue"))           # a full-year figure is already annual
            if value is None:
                continue
            kind = REVENUE_TYPES.get((r.get("Annualized revenue type") or "").strip())
            if kind is None:
                kind = "full-year revenue" if period == "Year" else "reported revenue"
            url = first_url(r.get("Source 1"), r.get("Source 2"), r.get("Source 3"))
            revenue.append({"lab": lab, "epoch_id": (r.get("Id") or "").strip(), "date": date,
                            "annualized_usd": as_int(value), "type": kind,
                            "source": via(url, "Epoch AI"), "url": url or COMPANIES_PAGE, "seen": seen})

    # Funding rounds: closed rounds only (talks and cancelled deals are skipped).
    if "ai_companies_funding_rounds.csv" in names:
        for r in read_csv(zf, "ai_companies_funding_rounds.csv"):
            if (r.get("Status") or "").strip() != "Closed":
                continue
            if (r.get("Exclude from graph view") or "").strip().lower() in ("true", "checked", "yes", "1"):
                continue
            date = clean_date(r.get("Close date")) or clean_date(r.get("Report date"))
            lab = lab_id(r.get("Company"))
            if not date or not lab:
                continue
            equity, debt = num(r.get("Funding (equity)")), num(r.get("Funding (debt)"))
            amount = None
            if equity is not None or debt is not None:
                amount = (equity or 0) + (debt or 0)
                if amount == 0:
                    amount = None                              # e.g. a secondary sale: no new money
            post = num(r.get("Valuation (post-money)"))
            if amount is None and post is None:
                continue
            kind = (r.get("Type") or "").strip()
            name = (r.get("Id") or "").strip() or "Funding round"
            if "Secondary" in kind:
                name += " (secondary sale)"
            elif "Debt" in kind:
                name += " (equity + debt)"
            elif kind == "Other":
                name += " (other)"
            url = first_url(r.get("Source 1"), r.get("Source 2"), r.get("Source 3"))
            funding.append({"lab": lab, "epoch_id": (r.get("Id") or "").strip(), "date": date, "round": name,
                            "amount_usd": as_int(amount), "post_money_usd": as_int(post),
                            "source": via(url, "Epoch AI"), "url": url or COMPANIES_PAGE, "seen": seen})

    # Compute spend (only a few labs report it).
    if "ai_companies_compute_spend.csv" in names:
        for r in read_csv(zf, "ai_companies_compute_spend.csv"):
            if (r.get("Exclude from graph view") or "").strip().lower() in ("true", "checked", "yes", "1"):
                continue
            date = clean_date(r.get("Date"))
            lab = lab_id(r.get("Company"))
            amount = num(r.get("Total compute spend"))
            if amount is None:
                amount = num(r.get("Amount"))
            if not date or not lab or amount is None:
                continue
            url = first_url(r.get("Source 1"), r.get("Source 2"), r.get("Source 3"))
            compute.append({"lab": lab, "epoch_id": (r.get("Id") or "").strip(), "date": date,
                            "amount_usd": as_int(amount), "period": (r.get("Period type") or "").strip() or None,
                            "category": (r.get("Category") or "").strip() or None,
                            "source": via(url, "Epoch AI"), "url": url or COMPANIES_PAGE, "seen": seen})
    return revenue, funding, compute


# ---------------------------------------------------------------- parse: benchmarks

def parse_benchmarks(data, seen):
    """benchmark_data.zip -> one history row per (model, benchmark) with the model's best score.

    Epoch lists every model VERSION (e.g. 'gpt-5-2025-08-07_high'); model_metadata.csv maps each version
    to its model group ('GPT-5'). We keep the best score across a group's versions (e.g. effort settings)."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    version_to_group = {}
    group_date = {}
    if "model_metadata.csv" in names:
        for r in read_csv(zf, "model_metadata.csv"):
            v, g = (r.get("model_version") or "").strip(), (r.get("model_group") or "").strip()
            if v and g:
                version_to_group[v] = g
            if g and clean_date(r.get("date")):
                group_date.setdefault(g, clean_date(r.get("date")))
    scale_by_file = {}
    if "benchmark_metadata.csv" in names:
        for r in read_csv(zf, "benchmark_metadata.csv"):
            if (r.get("source_file") or "").strip():
                scale_by_file[r["source_file"].strip()] = num(r.get("scale")) or 1.0

    cutoff = (dt.date.fromisoformat(seen) - dt.timedelta(days=SCORE_HISTORY_DAYS)).isoformat()
    best = {}        # (model, benchmark id) -> row
    for bid, _label, member, column, unit, higher, _origin in BENCHMARKS:
        if member not in names:
            warn(f"benchmark file missing from the zip: {member}")
            continue
        for r in read_csv(zf, member):
            if bid == "eci":
                model = (r.get("Model") or "").strip()
                org = r.get("Organization")
                release = clean_date(r.get("date"))
            else:
                model = version_to_group.get((r.get("Model version") or "").strip())
                org = r.get("Organization")
                release = clean_date(r.get("Release date"))
            if not model:
                continue
            release = release or group_date.get(model)
            value = num(r.get(column))
            if value is None or not release:
                continue
            if bid != "eci" and release < cutoff:
                continue
            if unit == "%":
                value = value * scale_by_file.get(member, 1.0) * 100.0
            value = round(value, 0 if unit == "Elo" else 1)
            row = {"model": model, "lab": lab_id(org), "org": (org or "").strip() or None,
                   "release_date": release, "benchmark": bid, "score": value, "seen": seen,
                   "source": "Epoch AI Benchmarking Hub", "url": BENCH_PAGE}
            key = (model, bid)
            old = best.get(key)
            if old is None or (value > old["score"] if higher else value < old["score"]):
                best[key] = row
    return list(best.values())


# ---------------------------------------------------------------- build the web file

def select_models(score_rows, today_str):
    """Pick frontier models from the latest score per (model, benchmark). Returns (models list, used ids)."""
    latest = latest_by(score_rows, ("model", "benchmark"))
    by_model = {}
    for r in latest:
        m = by_model.setdefault(r["model"], {"model": r["model"], "lab": r.get("lab"),
                                             "release_date": r.get("release_date"), "scores": {}})
        m["scores"][r["benchmark"]] = r["score"]
        if r["benchmark"] == "eci":                      # ECI rows carry Epoch's canonical lab and date
            m["lab"], m["release_date"] = r.get("lab"), r.get("release_date")

    window_start = (dt.date.fromisoformat(today_str) - dt.timedelta(days=MODEL_WINDOW_DAYS)).isoformat()
    with_eci = sorted((m for m in by_model.values() if "eci" in m["scores"] and m["release_date"]),
                      key=lambda m: m["release_date"])
    keep = set()
    best_before = None          # best ECI among models released on an EARLIER date
    best_today, day = None, None
    for m in with_eci:
        if m["release_date"] != day:                     # new release date: fold the previous day in
            if best_today is not None:
                best_before = best_today if best_before is None else max(best_before, best_today)
            day, best_today = m["release_date"], None
        e = m["scores"]["eci"]
        if m["release_date"] >= window_start and (best_before is None or e >= best_before - FRONTIER_MARGIN):
            keep.add(m["model"])
        best_today = e if best_today is None else max(best_today, e)

    per_lab = {}                # only for the AI labs we track (LAB_ORDER), not every small org Epoch lists
    for m in with_eci:
        if m["release_date"] >= window_start and m.get("lab") in LAB_ORDER:
            per_lab.setdefault(m["lab"], []).append(m)
    for lab_models in per_lab.values():
        for m in sorted(lab_models, key=lambda m: -m["scores"]["eci"])[:TOP_PER_LAB]:
            keep.add(m["model"])

    models = [by_model[name] for name in keep]
    models.sort(key=lambda m: (m["release_date"], m["scores"].get("eci", 0)), reverse=True)
    out = []
    for m in models:
        out.append({"model": m["model"], "lab": m["lab"], "release_date": m["release_date"],
                    "scores": dict(sorted(m["scores"].items(),
                                          key=lambda kv: [b[0] for b in BENCHMARKS].index(kv[0]))),
                    "source": "Epoch AI Benchmarking Hub", "url": BENCH_PAGE})
    used = {b for m in out for b in m["scores"]}
    return out, used


def load_deals():
    """Rows of the curated deals log (missing or broken file -> no deals, with a warning)."""
    try:
        doc = read_json(DEALS_FILE, {}) or {}
    except ValueError as e:
        warn(f"could not parse {DEALS_FILE.name}: {e}")
        return []
    return [r for r in doc.get("rows", []) if isinstance(r, dict) and r.get("lab")]


def build():
    """Rebuild graph/ai_labs.json from the history files and the deals log (no network)."""
    now = today()
    show = (config().get("show") or {}).get(SOURCE_ID, True)
    hidden = [] if show else [SOURCE_ID]

    revenue = latest_by(read_history(DS_REVENUE), ("lab", "epoch_id", "date")) if show else []
    funding = latest_by(read_history(DS_FUNDING), ("lab", "epoch_id", "date")) if show else []
    compute = latest_by(read_history(DS_COMPUTE), ("lab", "epoch_id", "date", "category")) if show else []
    if show:
        models, used = select_models(read_history(DS_SCORES), now)
    else:
        models, used = [], set()
    deals = load_deals()

    nodes = universe()
    labs = {}

    def lab_entry(lab):
        if lab not in labs:
            node = LAB_NODE.get(lab, lab)
            labs[lab] = {"id": lab, "node_id": node if node in nodes else None,
                         "revenue": [], "funding": [], "deals": [], "compute_spend": []}
        return labs[lab]

    for r in revenue:
        lab_entry(r["lab"])["revenue"].append(
            {"date": r["date"], "annualized_usd": r["annualized_usd"], "type": r["type"],
             "source": r["source"], "url": r["url"]})
    for r in funding:
        lab_entry(r["lab"])["funding"].append(
            {"date": r["date"], "round": r["round"], "amount_usd": r["amount_usd"],
             "post_money_usd": r["post_money_usd"], "source": r["source"], "url": r["url"]})
    for r in compute:
        lab_entry(r["lab"])["compute_spend"].append(
            {"date": r["date"], "amount_usd": r["amount_usd"], "period": r["period"],
             "category": r["category"], "source": r["source"], "url": r["url"]})
    for r in deals:
        # "url" = the public link shown on the site; url_or_path may be Nodus42's own transcript copy, which the
        # site cannot link to, so it is passed on as local_file (user, 2026-10-17 verification)
        path = r.get("url_or_path") or ""
        public = r.get("url") or (path if path.startswith("http") else None)
        if not public:
            warn(f"deal {r.get('date')} {r.get('lab')} / {r.get('counterparty')} has no public url")
        lab_entry(LAB_ALIASES.get(r["lab"], r["lab"]))["deals"].append(
            {"date": r.get("date"), "counterparty": r.get("counterparty"), "what": r.get("what"),
             "gw": r.get("gw"), "value_usd": r.get("value_usd"), "source": r.get("source"),
             "url": public, "local_file": path if path and not path.startswith("http") else None})
    for m in models:
        if m.get("lab"):
            lab_entry(m["lab"])

    for entry in labs.values():                         # newest first everywhere
        for field in ("revenue", "funding", "deals", "compute_spend"):
            entry[field].sort(key=lambda x: x.get("date") or "", reverse=True)

    order = {name: i for i, name in enumerate(LAB_ORDER)}
    lab_list = sorted(labs.values(), key=lambda e: (order.get(e["id"], len(order)), e["id"]))

    benchmarks = [{"id": bid, "label": label, "higher_is_better": higher, "unit": unit,
                   "source": f"Epoch AI Benchmarking Hub ({origin})" if origin != "Epoch AI" else "Epoch AI Benchmarking Hub",
                   "url": BENCH_PAGE}
                  for bid, label, _m, _c, unit, higher, origin in BENCHMARKS if bid in used]

    notes = [
        "Revenue and funding come from Epoch AI's 'Data on AI companies' (CC BY 4.0), which compiles company "
        "statements and media reports; each row links the original report.",
        "Revenue type: 'run rate' and 'ARR' are annualized snapshots; 'full-year revenue' is a calendar-year total; "
        "'annualized from period revenue' scales a quarter or half-year figure to a year.",
        f"Models: released in the last {MODEL_WINDOW_DAYS // 30} months, with an Epoch Capabilities Index (ECI) "
        f"within {FRONTIER_MARGIN:g} points of the best earlier model, plus each tracked lab's top {TOP_PER_LAB} by ECI. "
        "Scores are the best across a model's tested versions or settings.",
        "Benchmarks marked external are third-party leaderboards compiled by Epoch AI.",
        "Deals come from Nodus42's curated log (market/ai_lab_deals.json); the date is the date of the cited "
        "filing or call; the link is the SEC filing or, for an earnings call, the company's investor-relations "
        "events page. Deals can overlap (a site named in one deal can be part of a larger commitment), so their "
        "GW are not added up.",
    ]
    out = {"updated": now, "attribution": ATTRIBUTION, "hidden_sources": hidden,
           "labs": lab_list, "models": models, "benchmarks": benchmarks, "notes": notes}
    write_json(OUT_PATH, out)
    log(f"built {OUT_PATH.relative_to(ROOT)}: {len(lab_list)} labs, {len(models)} models, "
        f"{len(benchmarks)} benchmarks, {sum(len(e['deals']) for e in lab_list)} deals")
    return out


# ---------------------------------------------------------------- run

def run(backfill=False):
    """Fetch today's Epoch files, append history, rebuild graph/ai_labs.json. Returns True if any source worked."""
    load_env()                                           # no keys needed, but keeps every collector uniform
    seen = today()
    ok = 0

    data = fetch_zip(COMPANIES_ZIP, "epoch_ai_companies.zip", force=backfill)
    if data:
        try:
            revenue, funding, compute = parse_companies(data, seen)
            added = (append_history(DS_REVENUE, revenue, KEY_REVENUE),
                     append_history(DS_FUNDING, funding, KEY_FUNDING),
                     append_history(DS_COMPUTE, compute, KEY_COMPUTE))
            log(f"companies: {len(revenue)} revenue / {len(funding)} funding / {len(compute)} compute rows parsed; "
                f"new in history: {added[0]} / {added[1]} / {added[2]}")
            ok += 1
        except (zipfile.BadZipFile, KeyError, ValueError, csv.Error) as e:
            warn(f"could not read the AI-companies zip: {e}")

    data = fetch_zip(BENCH_ZIP, "epoch_benchmark_data.zip", force=backfill)
    if data:
        try:
            scores = parse_benchmarks(data, seen)
            added = append_history(DS_SCORES, scores, KEY_SCORES)
            log(f"benchmarks: {len(scores)} model scores parsed; new in history: {added}")
            ok += 1
        except (zipfile.BadZipFile, KeyError, ValueError, csv.Error) as e:
            warn(f"could not read the benchmark zip: {e}")

    build()                                              # always rebuild (keeps previous data if a source died)
    return ok > 0


def main(argv=None):
    p = argparse.ArgumentParser(description="AI-lab metrics + model benchmarks -> graph/ai_labs.json")
    p.add_argument("--backfill", action="store_true", help="force a fresh download (ignore cache / ETag)")
    p.add_argument("--build-only", action="store_true", help="rebuild graph/ai_labs.json from history, no network")
    args = p.parse_args(argv)
    if args.build_only:
        build()
        return 0
    return 0 if run(backfill=args.backfill) else 1


if __name__ == "__main__":
    sys.exit(main())
