"""Shared helpers for the daily market-data collectors (market/*.py).

The user asked on 2026-10-17 for daily, free, script-only records next to the graph: memory prices, GPU $/hour,
insider trades, financing events, hyperscaler capex / cash flow and AI-lab metrics. Each collector:
  - fetches its source once a day (run by routine/nightly.ps1 through market/run_all.py, no model tokens),
  - appends what it saw to market/history/<dataset>.jsonl (ADD-only: a row whose key is already there is skipped),
  - rebuilds its web file graph/<dataset>.json from that history (generated, never hand-edited).
Re-running on the same day is safe: the history dedupes by key.
"""
import datetime as dt
import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent          # repo root (works in any worktree)
HISTORY = ROOT / "market" / "history"
GRAPH = ROOT / "graph"
PT = ZoneInfo("America/Los_Angeles")

# A normal browser User-Agent for public pages; SEC wants its own descriptive one (see sec_headers).
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def load_env():
    """Read the repo's .env (API keys) into os.environ. Never print the values."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def today():
    """Today's date in Pacific time (the laptop's clock), as YYYY-MM-DD."""
    return dt.datetime.now(PT).date().isoformat()


def sec_headers():
    """SEC requires a descriptive User-Agent with contact info (a bare request gets 403)."""
    ua = os.getenv("EDGAR_USER_AGENT") or "EarningsAI research contact@example.com"
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def get(url, headers=None, params=None, timeout=30, retries=3, pause=1.5, method="GET", json_body=None):
    """GET (or POST) with a few retries. Returns the requests.Response; raises after the last failure."""
    hdrs = {"User-Agent": BROWSER_UA}
    hdrs.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            if method == "POST":
                r = requests.post(url, headers=hdrs, params=params, json=json_body, timeout=timeout)
            else:
                r = requests.get(url, headers=hdrs, params=params, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code} for {url}")
                time.sleep(pause * (attempt + 1) * 2)
                continue
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(pause * (attempt + 1))
    raise last


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    """Write JSON atomically (temp file + rename) so a crash never leaves half a file for the website."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_history(dataset):
    """All rows ever recorded for a dataset (market/history/<dataset>.jsonl)."""
    path = HISTORY / f"{dataset}.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def append_history(dataset, rows, key_fields):
    """ADD-only append: rows whose key (tuple of key_fields) is already recorded are skipped.
    Returns how many new rows were written."""
    HISTORY.mkdir(parents=True, exist_ok=True)
    path = HISTORY / f"{dataset}.jsonl"
    seen = {tuple(r.get(k) for k in key_fields) for r in read_history(dataset)}
    new = []
    for r in rows:
        key = tuple(r.get(k) for k in key_fields)
        if key in seen:
            continue
        seen.add(key)
        new.append(r)
    if new:
        with path.open("a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(new)


def universe():
    """Graph nodes as {node_id: {ticker, exchange, country, status}} (node id = the name the website uses)."""
    graph = read_json(GRAPH / "merged_graph.json", {})
    nodes = graph.get("nodes", graph if isinstance(graph, list) else [])
    out = {}
    for n in nodes:
        if isinstance(n, dict) and n.get("id"):
            out[n["id"]] = {k: n.get(k) for k in ("ticker", "exchange", "country", "status")}
    return out


def config():
    """market/config.json switches, e.g. {"show": {"dramexchange_spot": true}}. Missing file = everything on."""
    return read_json(ROOT / "market" / "config.json", {}) or {}
