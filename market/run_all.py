"""Run every daily market-data collector once, in a fixed order (user, 2026-10-17).

routine/nightly.ps1 calls this BEFORE the nightly enrich session starts:
    python -X utf8 market/run_all.py
It is script-only (no model tokens). Each collector fetches its free source once, appends what it saw to
market/history/<dataset>.jsonl (ADD-only, deduplicated by key) and rebuilds its web file in graph/.

Order (fixed): memory_prices, gpu_prices, insiders_us, insiders_asia, insiders (build), financing_asia,
hyperscaler_cash, ai_labs, financing_us, financing (build). financing_us runs late because it is the slowest
step when SEC is slow or blocking us (it stops itself after 5 filers fail in a row, see its circuit breaker), so
it cannot starve the other collectors of the nightly time box.

Before the first collector, every market/history/*.jsonl is checked for a cut-off last line (a run killed while
append_history was writing): such a line would make read_history() fail on every later night, so it is moved to
<dataset>.rejected.txt (kept, never deleted) with a warning, and a missing final newline is added back.

Each step runs inside try/except and is timed, so one dead source never stops the others. One JSON line per
collector per day goes to market/run_log.jsonl:
    {"date", "collector", "ok", "seconds", "new_rows", "runs", "error"?, "warning"?}
A second run on the same day updates that day's line (ok / seconds / error of the latest run, new_rows summed
over the day's runs, runs counted) instead of adding another one. new_rows = lines added to market/history/*.jsonl
by that step (counted before and after, so it works for every collector the same way).

Exit code: 0 unless every collector that ran failed.

The financing build also reads market/history/financing_manual.jsonl: rows the enrich session appends by hand
(credit-rating actions, financing news the scripts miss), same schema as every financing_*.jsonl. Lines that are
not valid JSON would stop the whole financing build, so they are moved to financing_manual.rejected.txt (kept,
never deleted) with a warning.

CLI:
    python -X utf8 market/run_all.py                       daily run
    python -X utf8 market/run_all.py --backfill            pass --backfill to every collector (slow: ~1-2 h)
    python -X utf8 market/run_all.py --only gpu_prices,ai_labs
"""
import argparse
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

# Running as a script puts market/ itself first on sys.path; use the repo root instead, so
# "from market.common import ..." works and no file in market/ can shadow a standard module.
_ROOT = Path(__file__).resolve().parent.parent
if sys.path and Path(sys.path[0] or ".").resolve() == _ROOT / "market":
    sys.path[0] = str(_ROOT)
elif str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from market.common import HISTORY, ROOT, today  # noqa: E402  (needs the sys.path fix above)

RUN_LOG = ROOT / "market" / "run_log.jsonl"
MANUAL_FINANCING = HISTORY / "financing_manual.jsonl"
MANUAL_REJECTS = HISTORY / "financing_manual.rejected.txt"
DEALS_FILE = ROOT / "market" / "ai_lab_deals.json"
MANUAL_REQUIRED = ("company", "date", "type", "title", "source", "url")


# ---------------------------------------------------------------- how to read each collector's result
# The collectors were written separately, so run() returns different things. Each judge turns the return
# value into (ok, warning).

def judge_bool(result):
    """memory_prices / gpu_prices / insiders_us / hyperscaler_cash / ai_labs: True when any source worked."""
    return bool(result), None


def judge_exit_code(result):
    """financing_us: returns a CLI exit code (0 = fine)."""
    return result == 0, None


def judge_markets_dict(result):
    """insiders_asia: {market: new rows, or None when that market failed}."""
    failed = sorted(m for m, v in (result or {}).items() if v is None)
    ok = bool(result) and len(failed) < len(result)
    return ok, (f"failed markets: {', '.join(failed)}" if failed and ok else None)


def judge_ok_failed(result):
    """financing_asia: (ok markets, failed markets)."""
    ok_markets, failed = result if result else ([], [])
    return bool(ok_markets), (f"failed markets: {', '.join(failed)}" if failed and ok_markets else None)


def judge_build(result):
    """insiders / financing builders: reaching the end without an exception is success."""
    return True, None


# (collector name, module, function, judge). "build" steps take no backfill flag.
COLLECTORS = [
    ("memory_prices", "market.memory_prices", "run", judge_bool),
    ("gpu_prices", "market.gpu_prices", "run", judge_bool),
    ("insiders_us", "market.insiders_us", "run", judge_bool),
    ("insiders_asia", "market.insiders_asia", "run", judge_markets_dict),
    ("insiders", "market.insiders", "build", judge_build),
    ("financing_asia", "market.financing_asia", "run", judge_ok_failed),
    ("hyperscaler_cash", "market.hyperscaler_cash", "run", judge_bool),
    ("ai_labs", "market.ai_labs", "run", judge_bool),
    ("financing_us", "market.financing_us", "run", judge_exit_code),     # slowest when SEC is down: late
    ("financing", "market.financing", "build", judge_build),
]
NAMES = [c[0] for c in COLLECTORS]


# ---------------------------------------------------------------- helpers

def history_line_counts():
    """{file name: number of lines} for every market/history/*.jsonl (fast byte count, no JSON parsing)."""
    counts = {}
    for path in HISTORY.glob("*.jsonl"):
        n = 0
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                n += chunk.count(b"\n")
        counts[path.name] = n
    return counts


def rows_added(before, after):
    return sum(max(0, n - before.get(name, 0)) for name, n in after.items())


def check_manual_financing():
    """Make market/history/financing_manual.jsonl safe for market/financing.py before the financing build.
    Returns a warning string, or None when everything is fine."""
    if not MANUAL_FINANCING.exists():
        return None
    good, bad, incomplete = [], [], 0
    for line in MANUAL_FINANCING.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not a JSON object")
        except ValueError:
            bad.append(line)
            continue
        good.append(line)
        if any(not row.get(k) for k in MANUAL_REQUIRED):
            incomplete += 1                # kept; financing.py skips a row without company / date / url
    notes = []
    if bad:
        # keep the broken lines (nothing is ever deleted), but out of the file the builder parses
        with MANUAL_REJECTS.open("a", encoding="utf-8") as f:
            f.write(f"# moved from financing_manual.jsonl on {today()} (not valid JSON)\n")
            for line in bad:
                f.write(line + "\n")
        tmp = MANUAL_FINANCING.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(l + "\n" for l in good), encoding="utf-8")
        os.replace(tmp, MANUAL_FINANCING)
        notes.append(f"{len(bad)} invalid line(s) in financing_manual.jsonl moved to {MANUAL_REJECTS.name}")
    if incomplete:
        notes.append(f"{incomplete} manual financing row(s) miss one of {', '.join(MANUAL_REQUIRED)}")
    print(f"[run_all] financing_manual.jsonl: {len(good)} rows" + (f" ({'; '.join(notes)})" if notes else ""))
    return "; ".join(notes) or None


def check_history_tails():
    """A run killed while append_history() was writing can leave a cut-off last line in a history file, and
    read_history() (json.loads on every line) would then fail on every later night. Move such a line to
    <dataset>.rejected.txt (kept, never deleted) and add back a missing final newline. Returns a warning or None."""
    notes = []
    for path in sorted(HISTORY.glob("*.jsonl")):
        size = path.stat().st_size
        if size == 0:
            continue
        with path.open("rb") as f:
            f.seek(max(0, size - (1 << 20)))             # the last MB holds the last line
            tail = f.read()
        ended = tail.endswith(b"\n")
        last = tail.rstrip(b"\n").rsplit(b"\n", 1)[-1] if ended else tail.rsplit(b"\n", 1)[-1]
        try:
            json.loads(last.decode("utf-8"))
            if not ended:                                # complete JSON, newline missing: the next append
                with path.open("ab") as f:               # would glue its row onto this line
                    f.write(b"\n")
                notes.append(f"{path.name}: final newline added")
            continue
        except ValueError:
            pass
        rejected = path.with_name(path.stem + ".rejected.txt")
        with rejected.open("a", encoding="utf-8") as f:
            f.write(f"# moved from {path.name} on {today()} (cut-off or invalid last line)\n")
            f.write(last.decode("utf-8", errors="replace") + "\n")
        with path.open("r+b") as f:                      # cut the broken line (and its newline) off the file
            f.truncate(size - len(last) - (1 if ended else 0))
        notes.append(f"{path.name}: broken last line moved to {rejected.name}")
    if notes:
        print("[run_all] history check: " + "; ".join(notes), flush=True)
    return "; ".join(notes) or None


def check_deals_file():
    """market/ai_lab_deals.json is edited by the enrich session; a broken file would silently drop every deal."""
    if not DEALS_FILE.exists():
        return None
    try:
        json.loads(DEALS_FILE.read_text(encoding="utf-8"))
        return None
    except ValueError as e:
        return f"market/ai_lab_deals.json is not valid JSON ({e}); deals left out of graph/ai_labs.json"


def update_run_log(entries):
    """One line per (date, collector): merge this run into today's line if there is one. Atomic rewrite."""
    lines = []
    if RUN_LOG.exists():
        for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    continue               # a damaged line is dropped rather than stopping the log
    index = {(e.get("date"), e.get("collector")): i for i, e in enumerate(lines)}
    for entry in entries:
        key = (entry["date"], entry["collector"])
        if key in index:
            old = lines[index[key]]
            entry["new_rows"] = (old.get("new_rows") or 0) + entry["new_rows"]
            entry["runs"] = (old.get("runs") or 1) + 1
            lines[index[key]] = entry
        else:
            index[key] = len(lines)
            lines.append(entry)
    tmp = RUN_LOG.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in lines), encoding="utf-8")
    os.replace(tmp, RUN_LOG)


# ---------------------------------------------------------------- the run

def run_one(name, module_name, func_name, judge, backfill):
    """Run one collector step. Returns its run_log entry (never raises)."""
    print(f"\n[run_all] ===== {name} =====", flush=True)
    entry = {"date": today(), "collector": name}
    warnings = []
    if name in ("financing_us", "financing_asia", "financing"):   # each of these rebuilds graph/financing/ (one file per company)
        try:
            warnings.append(check_manual_financing())
        except Exception as e:      # the check must never block the build itself
            warnings.append(f"financing_manual.jsonl check failed: {e}")
    if name == "ai_labs":
        warnings.append(check_deals_file())

    before = history_line_counts()
    start = time.monotonic()
    try:
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        result = func(backfill=backfill) if func_name == "run" else func()
        ok, warning = judge(result)
        warnings.append(warning)
        if not ok:
            entry["error"] = "every source failed (see the collector's warnings above)"
    except (Exception, SystemExit) as e:
        ok = False
        entry["error"] = f"{type(e).__name__}: {e}"[:300]
        traceback.print_exc()
    entry["seconds"] = round(time.monotonic() - start, 1)
    entry["new_rows"] = rows_added(before, history_line_counts())
    entry["ok"] = ok
    entry["runs"] = 1
    warnings = [w for w in warnings if w]
    if warnings:
        entry["warning"] = "; ".join(warnings)[:300]
    # fixed key order in the log line
    ordered = {k: entry[k] for k in ("date", "collector", "ok", "seconds", "new_rows", "runs") if k in entry}
    ordered.update({k: entry[k] for k in ("error", "warning") if k in entry})
    status = "ok" if ok else "FAILED"
    print(f"[run_all] {name}: {status} in {ordered['seconds']}s, {ordered['new_rows']} new history rows"
          + (f" ({ordered['error']})" if "error" in ordered else "")
          + (f" [warning: {ordered['warning']}]" if "warning" in ordered else ""), flush=True)
    return ordered


def run_all(backfill=False, only=None):
    """Run the collectors (all, or the names in `only`, still in the fixed order). Returns the log entries."""
    entries = []
    try:
        check_history_tails()
    except Exception as e:          # the check must never block the collectors
        print(f"[run_all] history check failed: {e}", flush=True)
    for name, module_name, func_name, judge in COLLECTORS:
        if only and name not in only:
            continue
        entry = run_one(name, module_name, func_name, judge, backfill)
        entries.append(entry)
        update_run_log([dict(entry)])      # written after every step, so a killed run still logs what finished
    return entries


def main(argv=None):
    try:
        sys.stdout.reconfigure(line_buffering=True)     # live progress in the nightly log
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Run every daily market-data collector (market/*.py).")
    parser.add_argument("--backfill", action="store_true", help="pass --backfill to every collector (slow)")
    parser.add_argument("--only", help="comma-separated collector names, e.g. gpu_prices,ai_labs. "
                                       "Known: " + ", ".join(NAMES))
    args = parser.parse_args(argv)
    only = None
    if args.only:
        only = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in only if n not in NAMES]
        if unknown:
            parser.error(f"unknown collector(s): {', '.join(unknown)} (known: {', '.join(NAMES)})")

    start = time.monotonic()
    entries = run_all(backfill=args.backfill, only=only)
    failed = [e["collector"] for e in entries if not e["ok"]]
    total_rows = sum(e["new_rows"] for e in entries)
    # The LAST line is what routine/nightly.ps1 copies into .claude/nightly.log.
    print(f"run_all {today()} {'backfill' if args.backfill else 'daily'}: "
          f"{len(entries) - len(failed)}/{len(entries)} collectors ok, {total_rows} new history rows, "
          f"{round(time.monotonic() - start)}s" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if entries and len(failed) == len(entries) else 0


if __name__ == "__main__":
    sys.exit(main())
