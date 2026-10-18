"""Read the existing graph and public quote APIs; save a standalone research snapshot."""

import concurrent.futures
import datetime
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = "https://gijun42.com"


def fetch_fundamentals(symbol):
    """Keep failed requests explicit instead of replacing missing values with zero."""
    try:
        response = requests.get(
            BASE + "/api/fundamentals", params={"symbol": symbol}, timeout=35
        )
        response.raise_for_status()
        return symbol, response.json()
    except Exception as error:
        return symbol, {"error": str(error)}


def main():
    graph = json.loads((ROOT / "graph/merged_graph.json").read_text(encoding="utf-8"))
    metrics = json.loads((ROOT / "graph/company_metrics.json").read_text(encoding="utf-8"))
    universe = {}
    for node in graph["nodes"]:
        if node.get("exchange") in {"NASDAQ", "NYSE"}:
            universe.setdefault(node["ticker"], []).append(node["id"])

    # Home-exchange metadata omits these US ADR listings. Verify separately in the report.
    universe.update({"SKHY": ["SK Hynix"], "SKM": ["SK Telecom"], "PKX": ["POSCO"]})
    snapshot = {
        "retrieved_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": BASE,
        "universe": universe,
        "metrics": {name: metrics.get(name, {}) for names in universe.values() for name in names},
        "fundamentals": {},
        "quotes": {},
    }
    symbols = sorted(universe)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for index, (symbol, data) in enumerate(pool.map(fetch_fundamentals, symbols), 1):
            snapshot["fundamentals"][symbol] = data
            if index % 30 == 0:
                print(f"Fundamentals: {index}/{len(symbols)}", flush=True)

    for start in range(0, len(symbols), 30):
        response = requests.get(
            BASE + "/api/quotes",
            params={"symbols": ",".join(symbols[start:start + 30])},
            timeout=45,
        )
        response.raise_for_status()
        snapshot["quotes"].update(response.json().get("quotes", {}))

    (OUT / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(universe)} securities, {len(snapshot['quotes'])} quotes.")


if __name__ == "__main__":
    main()
