"""GPU rental prices (USD per GPU-hour) -> graph/gpu_prices.json.

The user asked on 2026-10-17 for free, script-only GPU $/hour data recorded every day by the nightly
routine (no model tokens) and shown on nodus42.com. This is market data, not a chain "signal":
it never touches quarterly_data, chains/, patches/ or derive.py.

Three sources, each one polite fetch a day:
  (a) shadeform     - Shadeform's public marketplace API (api.shadeform.ai/v1/instances/types).
                      Every listed instance type is one "offer". hourly_price is in CENTS for the whole
                      instance, so per-GPU-hour = hourly_price / 100 / num_gpus. We keep the daily median,
                      min, max, offer count and provider count per GPU model.
  (b) getdeploying  - GetDeploying's open weekly dataset (CC BY 4.0, credit required). Gives the
                      trailing ~53 weeks, so a --backfill run records the whole year at once.
  (c) provider_list_prices - on-demand list prices from the providers' own public pricing pages
                      (CoreWeave, Nebius, Lambda, Together AI, Crusoe). RunPod and vast.ai are NOT used
                      (their terms of service exclude this).

History (ADD-only JSONL in market/history/, see common.append_history):
  gpu_shadeform     key = date + gpu
  gpu_getdeploying  key = week + gpu + billing
  gpu_list          key = date + provider + gpu + config

CLI:  python -m market.gpu_prices [--backfill] [--build-only]
"""
import argparse
import csv
import datetime as dt
import io
import os
import re
import statistics
import sys
import time

from bs4 import BeautifulSoup

from market.common import (GRAPH, append_history, config, get, load_env, read_history, today,
                           write_json)

OUT_FILE = GRAPH / "gpu_prices.json"
UNIT = "USD per GPU-hour"

# History dataset names and their dedup keys (fixed by the data contract).
DS_SHADEFORM = "gpu_shadeform"
DS_GETDEPLOYING = "gpu_getdeploying"
DS_LIST = "gpu_list"
KEY_SHADEFORM = ("date", "gpu")
KEY_GETDEPLOYING = ("week", "gpu", "billing")
KEY_LIST = ("date", "provider", "gpu", "config")

SHADEFORM_URL = "https://api.shadeform.ai/v1/instances/types"
GETDEPLOYING_CSV = "https://getdeploying.com/dataset/gpu-prices/weekly.csv"
GETDEPLOYING_PAGE = "https://getdeploying.com/dataset/gpu-prices"
CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"

# The AI datacenter GPUs the website shows, in display order (newest first).
# key = a squashed lowercase name used for matching; label = what the website prints.
GPUS = [
    ("gb300", "GB300"),
    ("b300", "B300"),
    ("gb200", "GB200"),
    ("b200", "B200"),
    ("h200", "H200"),
    ("h100", "H100"),
    ("gh200", "GH200"),
    ("a100", "A100"),
    ("l40s", "L40S"),
    ("rtxpro6000", "RTX PRO 6000"),
    ("mi355x", "MI355X"),
    ("mi325x", "MI325X"),
    ("mi300x", "MI300X"),
]
GPU_LABEL = dict(GPUS)

# Name patterns for free-text names (Shadeform gpu_type, pricing pages). ORDER MATTERS:
# "gb300" must be tested before "b300", "h100nvl" before "h100", "l40s" before "l40".
GPU_PATTERNS = [
    ("gb300", "gb300"), ("gb200", "gb200"), ("gh200", "gh200"),
    ("b300", "b300"), ("b200", "b200"), ("h200", "h200"),
    ("h100nvl", "h100nvl"), ("h100", "h100"), ("a100", "a100"),
    ("l40s", "l40s"), ("rtxpro6000", "rtxpro6000"),
    ("mi355x", "mi355x"), ("mi325x", "mi325x"), ("mi300x", "mi300x"),
]
EXTRA_LABELS = {"h100nvl": "H100 NVL"}   # recorded in history, not charted

# GetDeploying slugs are exact, so they get an exact map (a pattern would wrongly turn
# "nvidia-rtx-pro-6000d", a different China-market card, into RTX PRO 6000).
GETDEPLOYING_SLUGS = {
    "nvidia-gb300": "gb300", "nvidia-b300": "b300", "nvidia-gb200": "gb200", "nvidia-b200": "b200",
    "nvidia-h200": "h200", "nvidia-h100": "h100", "nvidia-gh200": "gh200", "nvidia-a100": "a100",
    "nvidia-l40s": "l40s", "nvidia-rtx-pro-6000": "rtxpro6000",
    "amd-mi355x": "mi355x", "amd-mi325x": "mi325x", "amd-mi300x": "mi300x",
}

# A per-GPU-hour price outside this range is a parsing mistake (e.g. a monthly price), so it is dropped.
MIN_SANE, MAX_SANE = 0.05, 200.0


def log(msg):
    print(f"[gpu_prices] {msg}", flush=True)


def squash(name):
    """'NVIDIA HGX H100 SXM' -> 'nvidiahgxh100sxm' (lowercase, letters and digits only)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def gpu_key(name):
    """Map any GPU name to our canonical key: 'A100_80G' -> 'a100', 'NVIDIA HGX B300' -> 'b300'.
    Unknown names keep their own squashed form (so a new card is still recorded, just not charted)."""
    s = squash(name)
    for pattern, key in GPU_PATTERNS:
        if pattern in s:
            return key
    return s


def gpu_label(key, raw=""):
    return GPU_LABEL.get(key) or EXTRA_LABELS.get(key) or raw or key.upper()


def parse_money(text):
    """'$49.24' -> 49.24, 'from $1.55' -> 1.55, '$4.50/GPU-hr' -> 4.5, 'Contact sales' / '—' -> None."""
    m = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text or "")
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def sane(price):
    return price is not None and MIN_SANE <= price <= MAX_SANE


# --------------------------------------------------------------------------------------------
# (a) Shadeform: daily median / min / provider count per GPU model
# --------------------------------------------------------------------------------------------

def fetch_shadeform():
    """Return today's rows for gpu_shadeform (one row per GPU model)."""
    headers = {"Accept": "application/json"}
    key = os.getenv("SHADEFORM_API_KEY")
    if key:
        headers["X-API-KEY"] = key      # the value is never printed
    r = get(SHADEFORM_URL, headers=headers)
    if r.status_code in (401, 403):
        hint = "" if key else " (no SHADEFORM_API_KEY in .env; add one so the API accepts us)"
        raise RuntimeError(f"Shadeform refused the request: HTTP {r.status_code}{hint}")
    r.raise_for_status()
    instances = r.json().get("instance_types", [])

    # Group per-GPU-hour prices by canonical GPU key.
    groups = {}
    for it in instances:
        n_gpus = it.get("num_gpus") or 0
        cents = it.get("hourly_price")
        if n_gpus <= 0 or not cents:
            continue                     # CPU-only instance or no price
        on_demand = [a for a in it.get("availability", []) if a.get("rental_type") == "on_demand"]
        if not on_demand:
            continue                     # spot-only listing
        per_gpu = cents / 100.0 / n_gpus
        if not sane(per_gpu):
            continue
        key = gpu_key(it.get("gpu_type"))
        g = groups.setdefault(key, {"prices": [], "clouds": set(), "raw": set(), "available": 0, "by_cloud": {}})
        g["prices"].append(per_gpu)
        g["clouds"].add(it.get("cloud"))
        g["by_cloud"].setdefault(it.get("cloud") or "?", []).append(per_gpu)
        g["raw"].add(it.get("gpu_type"))
        if any(a.get("available") for a in on_demand):
            g["available"] += 1

    date = today()
    rows = []
    for key, g in sorted(groups.items()):
        rows.append({
            "date": date,
            "gpu": gpu_label(key, sorted(g["raw"])[0]),
            "gpu_key": key,
            "raw_types": sorted(g["raw"]),
            "median": round(statistics.median(g["prices"]), 4),
            # every instance size is one offer, so a provider listing 4 sizes at one price would set the plain
            # median; the median of the providers' own medians weighs each provider once (user, 2026-10-17)
            "provider_median": round(statistics.median(statistics.median(v) for v in g["by_cloud"].values()), 4),
            "min": round(min(g["prices"]), 4),
            "max": round(max(g["prices"]), 4),
            "offers": len(g["prices"]),
            "available_offers": g["available"],
            "providers": len(g["clouds"]),
            "source": "Shadeform",
            "url": SHADEFORM_URL,
        })
    return rows


# --------------------------------------------------------------------------------------------
# (b) GetDeploying: weekly medians (CC BY 4.0)
# --------------------------------------------------------------------------------------------

def fetch_getdeploying(backfill=False):
    """Return completed-week rows for gpu_getdeploying.
    The newest week in the file is partial and still changes, so a week is recorded only once it is
    over (Monday + 8 days <= today). Otherwise the ADD-only history would freeze a half-week value.
    backfill=True takes every week in the file (~53); a normal daily run only looks at the last 5 weeks."""
    r = get(GETDEPLOYING_CSV, headers={"Accept": "text/csv"})
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    now = dt.date.fromisoformat(today())
    oldest = dt.date.min if backfill else now - dt.timedelta(days=40)
    captured = today()

    def num(x):
        return float(x) if x not in (None, "") else None

    rows = []
    for rec in reader:
        key = GETDEPLOYING_SLUGS.get(rec.get("gpu_slug"))
        if not key:
            continue                     # consumer / old cards are not part of this chart
        week = dt.date.fromisoformat(rec["date"])
        if week + dt.timedelta(days=8) > now or week < oldest:
            continue
        billing = rec.get("billing_type") or "UNKNOWN"
        if rec.get("reservation_months"):
            billing = f"{billing}_{rec['reservation_months']}M"   # e.g. RESERVATION_12M
        rows.append({
            "week": rec["date"],
            "gpu": GPU_LABEL[key],
            "gpu_slug": rec["gpu_slug"],
            "billing": billing,
            "median": num(rec.get("median_price")),
            "provider_median": num(rec.get("provider_median_price")),
            "min": num(rec.get("min_price")),
            "max": num(rec.get("max_price")),
            "providers": int(rec["provider_count"]) if rec.get("provider_count") else None,
            "offers": int(rec["offering_count"]) if rec.get("offering_count") else None,
            "captured": captured,
            "source": "GetDeploying (CC BY 4.0)",
            "url": GETDEPLOYING_PAGE,
        })
    return rows


# --------------------------------------------------------------------------------------------
# (c) Provider list prices from public pricing pages
# --------------------------------------------------------------------------------------------

def list_row(provider, name, config_text, price_hr, price_gpu_hr, gpus, url):
    """One gpu_list row. price_hr = whole-instance $/hr when the page states the instance size, else None."""
    key = gpu_key(name)
    return {
        "date": today(),
        "provider": provider,
        "gpu": gpu_label(key, name),
        "gpu_key": key,
        "config": config_text,
        "gpus": gpus,
        "price_hr": round(price_hr, 4) if price_hr is not None else None,
        "price_gpu_hr": round(price_gpu_hr, 4),
        "source": f"{provider} pricing page",
        "url": url,
    }


def parse_coreweave(html, url):
    """CoreWeave: rows are div.table-row-v2 blocks; the on-demand price is for the whole instance."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for row in soup.select("div.table-row-v2"):
        if "gpu-pricing" not in " ".join(row.get("class", [])):
            continue                     # CPU, storage, networking rows
        name_el = row.select_one("h3.table-model-name")
        cells = row.select("div.table-grid > div.table-v2-cell")
        price_el = row.select_one("span.instance-price .item-value")
        if not (name_el and len(cells) > 1 and price_el):
            continue
        name = name_el.get_text(" ", strip=True)
        count = re.match(r"\d+", cells[1].get_text(strip=True))      # "8" or "4^1"
        price = parse_money(price_el.get_text())
        if not count or price is None:
            continue                     # "Contact sales"
        gpus = int(count.group())
        region_el = row.find_previous(lambda t: t.has_attr("class") and "eyebrow" in t["class"]
                                      and t.get_text(strip=True).upper().startswith("REGION"))
        region = region_el.get_text(strip=True).split(":", 1)[-1].strip().title() if region_el else ""
        cfg = f"{name}, {gpus} GPU{'s' if gpus > 1 else ''} per instance" + (f", {region}" if region else "")
        if sane(price / gpus):
            rows.append(list_row("CoreWeave", name, cfg, price, price / gpus, gpus, url))
    return rows


def parse_nebius(html, url):
    """Nebius: 'NVIDIA GPU Instances' block, last column is the on-demand price per GPU-hour."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for block in soup.select("div.pc-highlight-table-block__root"):
        title_el = block.select_one(".pc-highlight-table-block__title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if "GPU" not in title or "preemptible" in title.lower():
            continue                     # spot (preemptible), CPU and storage blocks
        table_rows = block.select(".pc-highlight-table-block__row")
        if not table_rows:
            continue
        header = [c.get_text(" ", strip=True) for c in table_rows[0].select(".pc-highlight-table-block__cell")]
        if not header or "gpu-hour" not in header[-1].lower() or "spot" in header[-1].lower():
            continue
        for tr in table_rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.select(".pc-highlight-table-block__cell")]
            if len(cells) < 4:
                continue
            price = parse_money(cells[-1])
            if not sane(price):
                continue                 # "Contact us"
            name = cells[0]
            cfg = f"{name}, per GPU ({cells[1]} vCPU, {cells[2]} GB RAM)"
            if cells[-1].lower().startswith("from"):
                cfg += ", starting price"
            rows.append(list_row("Nebius", name, cfg, None, price, 1, url))
    return rows


def parse_lambda(html, url):
    """Lambda: self-serve instance tables, one tab per instance size (8x, 4x, 2x, 1x), price per GPU/hr.
    The 1-Click Cluster tables (term contracts, 'DURATION' column) are skipped: on-demand only."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [c.get_text(" ", strip=True).upper() for c in trs[0].find_all(["th", "td"])]
        if "VRAM/GPU" not in header or not any("PRICE/GPU/HR" in h for h in header):
            continue
        price_idx = next(i for i, h in enumerate(header) if "PRICE/GPU/HR" in h)
        panel = table.find_parent(attrs={"aria-labelledby": True})
        tab = soup.find(id=panel["aria-labelledby"]) if panel else None
        size = re.match(r"(\d+)x", tab.get_text(strip=True)) if tab else None
        gpus = int(size.group(1)) if size else None
        for tr in trs[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) <= price_idx:
                continue
            price = parse_money(cells[price_idx])
            if not sane(price):
                continue
            name, vram = cells[0], cells[1]
            cfg = f"{name} {vram}, " + (f"{gpus}x instance" if gpus else "instance")
            rows.append(list_row("Lambda", name, cfg, price * gpus if gpus else None, price, gpus, url))
    return rows


def parse_together(html, url):
    """Together AI: 'On-demand hourly rates and reserved capacity' table, all prices per GPU per hour."""
    soup = BeautifulSoup(html, "html.parser")
    anchor = soup.find(string=lambda s: s and "on-demand hourly rates and reserved capacity" in s.lower())
    if not anchor:
        return []
    rows, od_idx, started = [], None, False
    for tr in anchor.find_all_next("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        if not cells:
            continue
        lower = [c.lower() for c in cells]
        if od_idx is None:
            if "on-demand" in lower:
                od_idx = lower.index("on-demand")     # header: Hardware | Preemptible | ON-Demand | Reserved
            continue
        if not re.match(r"(NVIDIA|AMD)\b", cells[0]):
            if started:
                break                    # past the GPU rows (vCPU / storage tables follow)
            continue                     # second header row (Pay as you go | 3-30 days ...)
        started = True
        if len(cells) <= od_idx:
            continue
        price = parse_money(cells[od_idx])
        if sane(price):
            rows.append(list_row("Together AI", cells[0], f"{cells[0]}, on-demand GPU cluster",
                                 None, price, None, url))
    return rows


def parse_crusoe(html, url):
    """Crusoe: cards under 'GPU instances pricing'; first price is on-demand per GPU-hour."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for item in soup.select("div.pricing_gpu-item"):
        section = item.find_previous(["h2", "h3"])
        if not section or section.get_text(" ", strip=True).lower() != "gpu instances pricing":
            continue                     # CPU, storage and managed-inference cards
        name_el = item.select_one("h4.pricing-item-heading")
        prices = item.select(".pricing-rich")
        if not name_el or not prices:
            continue
        price = parse_money(prices[0].get_text())
        if not sane(price):
            continue                     # "Contact sales"
        name = name_el.get_text(" ", strip=True)
        tags = " ".join(t.get_text(strip=True) for t in item.select(".pricing-tag") if t.get_text(strip=True))
        cfg = f"{name}" + (f" {tags}" if tags else "") + ", on-demand"
        rows.append(list_row("Crusoe", name, cfg, None, price, None, url))
    return rows


PROVIDER_PAGES = [
    ("CoreWeave", "https://www.coreweave.com/pricing", parse_coreweave),
    ("Nebius", "https://nebius.com/prices", parse_nebius),
    ("Lambda", "https://lambda.ai/pricing", parse_lambda),
    ("Together AI", "https://www.together.ai/pricing", parse_together),
    ("Crusoe", "https://www.crusoe.ai/cloud/pricing", parse_crusoe),
]


def fetch_list_prices():
    """Fetch each provider page once (with a pause between them). A broken page is skipped with a warning.
    Returns (rows, number_of_pages_that_worked)."""
    rows, ok = [], 0
    for i, (provider, url, parser) in enumerate(PROVIDER_PAGES):
        if i:
            time.sleep(2)                # be polite: one page at a time
        try:
            r = get(url)
            r.raise_for_status()
            got = parser(r.text, url)
            if not got:
                log(f"WARNING: {provider}: page fetched but no GPU prices parsed (layout may have changed)")
                continue
            rows.extend(got)
            ok += 1
            log(f"{provider}: {len(got)} list prices")
        except Exception as e:           # one dead page must not stop the others
            log(f"WARNING: {provider} list prices failed: {e}")
    return rows, ok


# --------------------------------------------------------------------------------------------
# Build graph/gpu_prices.json from history only
# --------------------------------------------------------------------------------------------

def make_series(sid, label, group, source, source_url, points):
    """Series object of data contract 1. points = [[date, value], ...] (sorted here)."""
    points = sorted(points)
    latest = None
    if points:
        date, value = points[-1]
        change = None
        if len(points) > 1 and points[-2][1]:
            change = round((value - points[-2][1]) / points[-2][1] * 100, 1)
        latest = {"date": date, "value": value, "change_pct": change}
    return {"id": sid, "label": label, "group": group, "unit": UNIT, "source": source,
            "source_url": source_url, "points": points, "latest": latest}


def build():
    """Rebuild graph/gpu_prices.json from market/history only (no network)."""
    show = config().get("show", {})
    shown = {s: show.get(s, True) for s in ("shadeform", "getdeploying", "provider_list_prices")}
    hidden = [s for s, on in shown.items() if not on]

    shadeform = read_history(DS_SHADEFORM)
    getdeploying = [r for r in read_history(DS_GETDEPLOYING) if r.get("billing") == "ON_DEMAND"]
    list_rows = read_history(DS_LIST)

    series, tables, notes = [], [], []

    # One chart group per GPU model: Shadeform daily median next to GetDeploying weekly median.
    for key, label in GPUS:
        if shown["shadeform"]:
            pts = [[r["date"], r["median"]] for r in shadeform if r.get("gpu_key") == key and r.get("median")]
            if pts:
                series.append(make_series(f"{key}_shadeform_median",
                                          f"{label} · Shadeform daily median (each instance type = one offer)",
                                          label, "Shadeform", SHADEFORM_URL, pts))
        if shown["getdeploying"]:
            pts = [[r["week"], r["median"]] for r in getdeploying if r.get("gpu") == label and r.get("median")]
            if pts:
                series.append(make_series(f"{key}_getdeploying_median",
                                          f"{label} · GetDeploying weekly on-demand median",
                                          label, "GetDeploying (CC BY 4.0)", GETDEPLOYING_PAGE, pts))

    order = {key: i for i, (key, _) in enumerate(GPUS)}

    if shown["shadeform"] and shadeform:
        last = max(r["date"] for r in shadeform)
        today_rows = sorted((r for r in shadeform if r["date"] == last and r.get("gpu_key") in order),
                            key=lambda r: order[r["gpu_key"]])
        tables.append({
            "id": "shadeform_today",
            "title": "Shadeform marketplace today (on-demand, per GPU-hour)",
            "columns": ["GPU", "Median $/GPU-hr (all offers)", "Provider median $/GPU-hr", "Min $/GPU-hr",
                        "Max $/GPU-hr", "Offers (instance types)", "Offers with capacity now", "Providers"],
            "rows": [[r["gpu"], r["median"], r.get("provider_median"), r["min"], r["max"], r["offers"],
                      r["available_offers"], r["providers"]] for r in today_rows],
            "source": "Shadeform", "source_url": SHADEFORM_URL, "asof": last,
        })

    if shown["getdeploying"] and getdeploying:
        last = max(r["week"] for r in getdeploying)
        week_rows = sorted((r for r in getdeploying if r["week"] == last),
                           key=lambda r: order.get(GETDEPLOYING_SLUGS.get(r["gpu_slug"]), 99))
        tables.append({
            "id": "getdeploying_latest_week",
            "title": f"GetDeploying on-demand, week of {last} (per GPU-hour)",
            "columns": ["GPU", "Median $/GPU-hr", "Provider median $/GPU-hr", "Min $/GPU-hr",
                        "Providers", "Listings"],
            "rows": [[r["gpu"], r["median"], r["provider_median"], r["min"], r["providers"], r["offers"]]
                     for r in week_rows],
            "source": "GetDeploying (CC BY 4.0)", "source_url": GETDEPLOYING_PAGE, "asof": last,
        })

    if shown["provider_list_prices"] and list_rows:
        # Each provider shows only its newest capture, so a price removed from a page drops off,
        # while a page that failed today keeps showing its last good capture (with its own date).
        newest = {}
        for r in list_rows:
            newest[r["provider"]] = max(newest.get(r["provider"], ""), r["date"])
        # Only the AI datacenter GPUs of GPUS are shown (older cards like V100 stay in history only).
        current = [r for r in list_rows if r["date"] == newest[r["provider"]] and r.get("gpu_key") in order]
        provider_order = {p: i for i, (p, _, _) in enumerate(PROVIDER_PAGES)}
        current.sort(key=lambda r: (order.get(r["gpu_key"], 99), provider_order.get(r["provider"], 99),
                                    r["price_gpu_hr"]))
        tables.append({
            "id": "provider_list_prices",
            "title": "Provider list prices",
            "columns": ["Provider", "GPU", "Config", "$/hr", "$/GPU-hr", "Date", "URL"],
            "rows": [[r["provider"], r["gpu"], r["config"], r["price_hr"], r["price_gpu_hr"], r["date"],
                      r["url"]] for r in current],
            "source": "Providers' public pricing pages (" + ", ".join(p for p, _, _ in PROVIDER_PAGES) + ")",
            "source_url": None,          # every row carries its own page URL
            "asof": max(newest.values()),
        })

    credits = []
    if shown["getdeploying"]:
        credits.append(f"Weekly medians: GetDeploying (CC BY 4.0), GPU rental price history, "
                       f"{GETDEPLOYING_PAGE}, license {CC_BY_URL}")
        notes.append("GetDeploying: a weekly value is the median of that week's daily captures of advertised "
                     "prices (not checked as rentable). A week is recorded here only after it has ended.")
    if shown["shadeform"]:
        credits.append(f"Daily medians: Shadeform marketplace API ({SHADEFORM_URL})")
        notes.append("Shadeform: every listed on-demand instance type is one offer; per-GPU price = instance "
                     "hourly price / GPU count. Offers without capacity right now are still counted. A provider "
                     "that lists several instance sizes at one per-GPU price counts several times in the plain "
                     "median; the provider median (recorded from 2026-10-18) counts each provider once.")
    if shown["provider_list_prices"]:
        credits.append("List prices: each provider's public pricing page (link on every row)")
        notes.append("Provider list prices are public on-demand rates; 'Contact sales' entries are left out. "
                     "$/hr is shown only when the page states the instance size.")
    notes.append("A100 combines the 40 GB and 80 GB versions.")

    data = {
        "updated": today(),
        "title": "GPU rental prices",
        "attribution": ". ".join(credits),
        "hidden_sources": hidden,
        "series": series,
        "tables": tables,
        "notes": notes,
    }
    write_json(OUT_FILE, data)
    log(f"wrote {OUT_FILE.relative_to(GRAPH.parent)}: {len(series)} series, {len(tables)} tables"
        + (f", hidden: {hidden}" if hidden else ""))
    return data


# --------------------------------------------------------------------------------------------
# Daily run
# --------------------------------------------------------------------------------------------

def run(backfill=False):
    """Fetch today's data from all three sources, append to history (ADD-only), rebuild the web file.
    Returns True if at least one source worked."""
    load_env()
    worked = 0

    try:
        rows = fetch_shadeform()
        added = append_history(DS_SHADEFORM, rows, KEY_SHADEFORM)
        log(f"Shadeform: {len(rows)} GPU models today, {added} new history rows")
        worked += 1 if rows else 0
    except Exception as e:
        log(f"WARNING: Shadeform failed: {e}")

    try:
        rows = fetch_getdeploying(backfill=backfill)
        added = append_history(DS_GETDEPLOYING, rows, KEY_GETDEPLOYING)
        log(f"GetDeploying: {len(rows)} completed-week rows read, {added} new history rows")
        worked += 1 if rows else 0
    except Exception as e:
        log(f"WARNING: GetDeploying failed: {e}")

    try:
        rows, pages_ok = fetch_list_prices()
        added = append_history(DS_LIST, rows, KEY_LIST)
        log(f"List prices: {pages_ok}/{len(PROVIDER_PAGES)} pages, {len(rows)} prices, {added} new history rows")
        worked += 1 if rows else 0
    except Exception as e:
        log(f"WARNING: list prices failed: {e}")

    build()                              # always rebuild, so earlier data stays on the site
    if not worked:
        log("ERROR: every GPU price source failed today")
    return worked > 0


def main():
    parser = argparse.ArgumentParser(description="Daily GPU rental prices -> graph/gpu_prices.json")
    parser.add_argument("--backfill", action="store_true", help="record every week GetDeploying still has")
    parser.add_argument("--build-only", action="store_true", help="rebuild the web file from history only")
    args = parser.parse_args()
    if args.build_only:
        build()
        return 0
    return 0 if run(backfill=args.backfill) else 1


if __name__ == "__main__":
    sys.exit(main())
