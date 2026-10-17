"""Memory prices: DRAMeXchange spot prices + TrendForce memory price press releases (user, 2026-10-17).

What this collector does, once a day (run by the nightly routine, no model tokens):
  (a) Reads the public DRAMeXchange homepage (https://www.dramexchange.com/, no login) and records the KEY spot
      items only: DRAM chip spot (DDR5 / DDR4 / DDR3), GDDR spot, module spot (DDR5 RDIMM etc.) and NAND wafer
      spot (TLC). For each item it stores the high, low, session average and % change the page shows, plus the
      page's own "Last Update" time. The price date we store is the date the page states, not the fetch date.
      DRAMeXchange's terms bar republishing; the user chose to show it anyway, so the switch
      market/config.json -> show.dramexchange_spot must keep working (false = hidden on the site, still collected).
  (b) Reads the TrendForce press RSS (Semiconductors) and keeps memory-related releases (DRAM / NAND / HBM /
      contract price ...) as a table with any % figure found in the title or summary.

Files:
  market/history/memory_spot.jsonl   one row per (price date, item, page update time)  - ADD-only
  market/history/memory_press.jsonl  one row per press release URL                    - ADD-only
  graph/memory_prices.json           the web file (data contract 1), rebuilt from history every run

Note on the memory_spot key: the spec asked for key date+id. We key on date+id+asof ("asof" = the page's own
update time). On a normal night this is the same thing (one page update per date); it only matters if the page
is read twice on the same price date at different session times (e.g. a manual run after the evening session):
then the later session is kept too and build() shows the latest one for that date. Re-running with the page
unchanged still adds nothing.

CLI:
  python -m market.memory_prices              fetch today's data, append history, rebuild the web file
  python -m market.memory_prices --backfill   same, plus walk the TrendForce press list back 365 days
                                              (DRAMeXchange history charts are members-only, so spot has no backfill)
  python -m market.memory_prices --build-only rebuild graph/memory_prices.json from history only (no network)
"""
import argparse
import datetime as dt
import re
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from market.common import (GRAPH, append_history, config, get, read_history, today, write_json)

# ---------------------------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------------------------
DX_SOURCE_ID = "dramexchange_spot"
DX_NAME = "DRAMeXchange"
DX_URL = "https://www.dramexchange.com/"
DX_ATTRIBUTION = "Spot prices: DRAMeXchange (TrendForce)"

TF_SOURCE_ID = "trendforce_press"
TF_NAME = "TrendForce press center"
TF_RSS = "https://www.trendforce.com/feed/Semiconductors.html"
TF_LIST = "https://www.trendforce.com/presscenter/news/Semiconductors"   # used by --backfill only
TF_ATTRIBUTION = "Price releases: TrendForce press center"

SPOT_DATASET = "memory_spot"
PRESS_DATASET = "memory_press"
OUT_FILE = GRAPH / "memory_prices.json"

# Which DRAMeXchange homepage boxes we keep, by their title text. Every row inside these boxes is kept; every other
# box (flash SLC/MLC, memory cards, SSD street prices, eMMC ...) is ignored on purpose: show only the key series.
#   box title on the page -> (id prefix, series group, unit)
DX_SECTIONS = {
    "DRAM Spot Price": ("dram_spot", "DRAM spot", "USD per chip"),
    "GDDR Spot Price": ("gddr_spot", "DRAM spot", "USD per chip"),
    "Module Spot Price": ("module_spot", "Module spot", "USD per module"),
    # DRAMeXchange quotes NAND wafers per die-equivalent unit (a 512Gb TLC "wafer" at ~$9-19), not per whole wafer
    "Wafer Spot Price": ("nand_wafer", "NAND wafer spot", "USD per die-equivalent unit"),
}
# Order of the groups on the web page, and short box names for the notes.
GROUP_ORDER = ["DRAM spot", "Module spot", "NAND wafer spot"]
BOX_NAMES = {"DRAM Spot Price": "DRAM spot", "GDDR Spot Price": "GDDR spot",
             "Module Spot Price": "Module spot", "Wafer Spot Price": "NAND wafer spot"}

# A TrendForce release is "memory related" when its TITLE mentions one of these words. (Matching the summary too
# was tried and pulled in AI-rack and event releases that only mention HBM in passing, so the title decides.)
TF_TITLE_WORDS = re.compile(
    r"\b(DRAM|NAND|HBM\d*E?|memory|flash|SSDs?|DDR\d|LPDDR\d*X?|LPDRAM|GDDR\d*|eMMC|UFS|contract prices?)\b", re.I)
# A percentage figure, e.g. "121%", "10–15% QoQ", "-2.9% MoM".
PCT_RE = re.compile(r"[-+−]?\d+(?:\.\d+)?(?:\s*[–—-]\s*\d+(?:\.\d+)?)?\s?%(?:\s+(?:YoY|QoQ|MoM|HoH))?")

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

KEEP_DAYS = 365   # press table window


def log(msg):
    """Print a progress line (stderr, so it never mixes with JSON someone might pipe)."""
    print(f"[memory_prices] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------------------------------------------
def clean(text):
    """Collapse runs of whitespace (the page has '\\xa0' and double spaces, e.g. 'GDDR5  8Gb')."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def slug(text):
    """'DDR5 16Gb (2Gx8) 4800/5600' -> 'ddr5_16gb_2gx8_4800_5600' (stable series ids)."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def to_number(text):
    """'2,176.000' -> 2176.0 ; '0.28 %' -> 0.28 ; '--' or '' -> None."""
    t = clean(text).replace(",", "").replace("%", "").replace("−", "-").strip()
    try:
        return float(t)
    except ValueError:
        return None


def parse_last_update(text):
    """'Last Update: Oct.16 2026    18:10 (GMT+8)' -> ('2026-10-16', '2026-10-16 18:10 GMT+8').
    Returns (None, None) when the text has no recognisable date."""
    m = re.search(r"Last\s*Update\s*:\s*([A-Za-z]{3})[a-z]*\.?\s*(\d{1,2}),?\s+(\d{4}),?\s+(\d{1,2}):(\d{2})",
                  clean(text), re.I)
    if not m:
        return None, None
    mon = MONTHS.get(m.group(1).lower())
    if not mon:
        return None, None
    day = dt.date(int(m.group(3)), mon, int(m.group(2))).isoformat()
    return day, f"{day} {int(m.group(4)):02d}:{m.group(5)} GMT+8"


def pct_figures(*texts):
    """All distinct % figures in the given texts, joined with '; ' (None when there are none)."""
    found = []
    for t in texts:
        for f in PCT_RE.findall(clean(t)):
            f = f.replace("−", "-").strip()
            if f not in found:
                found.append(f)
    return "; ".join(found) or None


def is_memory_release(title):
    return bool(TF_TITLE_WORDS.search(title or ""))


def tf_url(href):
    """Normalise a TrendForce link to an absolute https URL (the history key)."""
    href = (href or "").strip()
    if href.startswith("/"):
        href = "https://www.trendforce.com" + href
    return href.replace("http://", "https://", 1)


# ---------------------------------------------------------------------------------------------------------------
# (a) DRAMeXchange spot prices
# ---------------------------------------------------------------------------------------------------------------
def parse_dramexchange(html, fetched):
    """Turn the homepage HTML into history rows (one per kept item). Pure function: easy to test offline.

    Each price box on the page is a <div class="left_tab"> holding:
      - a title cell (td.title_left, e.g. 'DRAM Spot Price') and its 'Last Update: ...' time (span.tab_time),
      - a header row (td.tab_title: Item | Daily High | Daily Low | Session High | Session Low | Session Average | ...)
      - one row per item (first cell td.tab_tr_gray2 = item name, then the numbers).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for box in soup.find_all("div", class_="left_tab"):
        title_cell = box.find("td", class_="title_left")
        if not title_cell:
            continue
        title = clean(title_cell.get_text(" "))
        if title not in DX_SECTIONS:
            continue                                   # not one of the key boxes
        prefix, group, unit = DX_SECTIONS[title]
        time_span = box.find("span", class_="tab_time")
        price_date, asof = parse_last_update(time_span.get_text(" ") if time_span else "")
        if not price_date:
            log(f"WARNING: no 'Last Update' date in box '{title}', skipped")
            continue
        header = [clean(td.get_text(" ")) for td in box.find_all("td", class_="tab_title")]
        cadence = "weekly" if any(h.lower().startswith("weekly") for h in header) else "daily"
        rank = 0
        for tr in box.find_all("tr"):
            name_cell = tr.find("td", class_="tab_tr_gray2")
            if not name_cell:
                continue
            label = clean(name_cell.get_text(" "))
            cells = [clean(td.get_text(" ")) for td in tr.find_all("td")][1:]   # numbers after the item name
            # Expected order: high, low, session high, session low, session average, change %, (history icon)
            nums = [to_number(c) for c in cells[:6]]
            if len(nums) < 6 or nums[4] is None:
                log(f"WARNING: could not read prices for '{label}' in '{title}', skipped")
                continue
            rank += 1
            rows.append({
                "date": price_date,                     # the price date the page states
                "id": f"{prefix}_{slug(label)}",
                "asof": asof,                           # the page's own update time (GMT+8)
                "label": label,
                "group": group,
                "section": title,
                "cadence": cadence,                     # 'daily' or 'weekly' (from the column headers)
                "unit": unit,
                "high": nums[0],
                "low": nums[1],
                "session_high": nums[2],
                "session_low": nums[3],
                "avg": nums[4],
                "change_pct": nums[5],
                "rank": rank,                           # position inside its box (keeps the page's order)
                "fetched": fetched,
                "source": DX_NAME,
                "source_url": DX_URL,
            })
    return rows


def collect_dramexchange():
    """Fetch the homepage once and append new rows. Returns True on success, False if the source is dead."""
    try:
        r = get(DX_URL)
        if r.status_code != 200:
            log(f"WARNING: DRAMeXchange returned HTTP {r.status_code}; keeping previous data")
            return False
        rows = parse_dramexchange(r.content, today())
    except Exception as e:                              # network error, layout change, ...
        log(f"WARNING: DRAMeXchange failed ({e.__class__.__name__}: {e}); keeping previous data")
        return False
    if not rows:
        log("WARNING: DRAMeXchange page had no spot rows (layout changed?); keeping previous data")
        return False
    added = append_history(SPOT_DATASET, rows, ("date", "id", "asof"))
    log(f"DRAMeXchange: {len(rows)} items read, {added} new history rows")
    return True


# ---------------------------------------------------------------------------------------------------------------
# (b) TrendForce memory price press releases
# ---------------------------------------------------------------------------------------------------------------
def parse_trendforce_rss(xml_bytes, fetched):
    """RSS items -> history rows for the memory-related ones."""
    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.iter("item"):
        title = clean(item.findtext("title"))
        url = tf_url(item.findtext("link") or item.findtext("guid"))
        summary = clean(BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" "))
        if not url or not is_memory_release(title):
            continue
        try:
            # pubDate is Taipei time (+0800); keep TrendForce's own calendar date (it matches the URL).
            date = parsedate_to_datetime(item.findtext("pubDate")).date().isoformat()
        except (TypeError, ValueError):
            m = re.search(r"/(\d{4})(\d{2})(\d{2})-", url)
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else fetched
        rows.append({"url": url, "date": date, "title": title, "summary": summary,
                     "figures": pct_figures(title, summary), "seen": fetched,
                     "source": TF_NAME, "source_url": url})
    return rows


def parse_trendforce_list(html, fetched):
    """One press-center list page -> (memory rows, oldest date on the page). Used by --backfill."""
    soup = BeautifulSoup(html, "html.parser")
    rows, oldest = [], None
    for link in soup.find_all("a", class_="title-link"):
        url = tf_url(link.get("href"))
        if "/presscenter/news/" not in url:
            continue
        box = link.find_parent("div")
        title = clean(link.get_text(" "))
        date_tag = box.find("h4") if box else None
        summary_tag = box.find("p") if box else None
        try:
            date = dt.datetime.strptime(clean(date_tag.get_text(" ")), "%d %B %Y").date().isoformat()
        except (AttributeError, ValueError):
            m = re.search(r"/(\d{4})(\d{2})(\d{2})-", url)
            if not m:
                continue
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        oldest = date if oldest is None or date < oldest else oldest
        summary = clean(summary_tag.get_text(" ")) if summary_tag else ""
        if is_memory_release(title):
            rows.append({"url": url, "date": date, "title": title, "summary": summary,
                         "figures": pct_figures(title, summary), "seen": fetched,
                         "source": TF_NAME, "source_url": url})
    return rows, oldest


def collect_trendforce(backfill=False):
    """Read the RSS once (and, with --backfill, the list pages back 365 days). True on success."""
    fetched = today()
    try:
        r = get(TF_RSS)
        if r.status_code != 200:
            log(f"WARNING: TrendForce RSS returned HTTP {r.status_code}; keeping previous data")
            return False
        rows = parse_trendforce_rss(r.content, fetched)
    except Exception as e:
        log(f"WARNING: TrendForce RSS failed ({e.__class__.__name__}: {e}); keeping previous data")
        return False
    if backfill:
        cutoff = (dt.date.fromisoformat(fetched) - dt.timedelta(days=KEEP_DAYS)).isoformat()
        for page in range(1, 80):                        # hard cap; ~8 releases per page
            time.sleep(2.0)                              # be polite: one list page every 2 seconds
            try:
                lr = get(TF_LIST, params={"page": page})
                if lr.status_code != 200:
                    log(f"WARNING: backfill page {page} returned HTTP {lr.status_code}; stopping backfill")
                    break
                page_rows, oldest = parse_trendforce_list(lr.content, fetched)
            except Exception as e:
                log(f"WARNING: backfill page {page} failed ({e.__class__.__name__}); stopping backfill")
                break
            rows += [x for x in page_rows if x["date"] >= cutoff]
            if oldest is None or oldest < cutoff:
                break
        log(f"TrendForce backfill: walked back to {cutoff}")
    added = append_history(PRESS_DATASET, rows, ("url",))
    log(f"TrendForce: {len(rows)} memory releases seen, {added} new history rows")
    return True


# ---------------------------------------------------------------------------------------------------------------
# Build the web file graph/memory_prices.json (data contract 1) from history only
# ---------------------------------------------------------------------------------------------------------------
def build_spot(history):
    """History rows -> (series list, snapshot table, notes) for DRAMeXchange."""
    # Keep one row per (item, price date): the one with the latest page update time.
    best = {}
    for r in history:
        k = (r["id"], r["date"])
        if k not in best or (r.get("asof") or "") > (best[k].get("asof") or ""):
            best[k] = r
    by_id = {}
    for (sid, _date), r in best.items():
        by_id.setdefault(sid, []).append(r)

    series, latest_rows = [], []
    for sid, rows in by_id.items():
        rows.sort(key=lambda x: x["date"])
        last = rows[-1]
        latest_rows.append(last)
        series.append({
            "id": sid,
            "label": last["label"],
            "group": last["group"],
            # the unit as defined now (rows recorded before 2026-10-17 say only "USD" for NAND wafers)
            "unit": DX_SECTIONS.get(last.get("section"), (None, None, last["unit"]))[2],
            "source": last["source"],
            "source_url": last["source_url"],
            "points": [[x["date"], x["avg"]] for x in rows],     # session average per price date
            "latest": {"date": last["date"], "value": last["avg"], "change_pct": last.get("change_pct")},
        })

    # Order like the page: group order, then box order (DRAM before GDDR inside "DRAM spot"), then row order.
    box_order = list(DX_SECTIONS)
    meta = {r["id"]: r for r in latest_rows}

    def order(s):
        r = meta[s["id"]]
        g = GROUP_ORDER.index(r["group"]) if r["group"] in GROUP_ORDER else 99
        b = box_order.index(r["section"]) if r["section"] in box_order else 99
        return (g, b, r.get("rank", 99), s["label"])
    series.sort(key=order)

    tables, notes = [], []
    if series:
        newest_asof = max(r.get("asof") or "" for r in latest_rows)
        table_rows = []
        for s in series:
            r = meta[s["id"]]
            table_rows.append([r["label"], r["group"], r["date"], r["high"], r["low"], r["avg"],
                               r.get("change_pct"), r["cadence"]])
        tables.append({
            "id": "dramexchange_spot_latest",
            "title": "DRAMeXchange spot: latest session",
            "columns": ["Item", "Group", "Price date", "High", "Low", "Session average", "Change %", "Cadence"],
            "rows": table_rows,
            "source": DX_NAME,
            "source_url": DX_URL,
            "asof": newest_asof,
        })
        # Notes: the page's own update time per box, and what the numbers are.
        stamps = {}
        for r in latest_rows:
            stamps.setdefault(r["section"], (r.get("asof"), r["cadence"]))
        parts = [f"{BOX_NAMES.get(sec, sec)} {a} ({c})" for sec, (a, c) in
                 sorted(stamps.items(), key=lambda kv: box_order.index(kv[0]) if kv[0] in box_order else 99)]
        notes.append("DRAMeXchange 'Last Update' per box: " + "; ".join(parts) + ".")
        notes.append("NAND wafer spot prices are quoted by DRAMeXchange per die-equivalent unit of the stated "
                     "density (e.g. one 512Gb TLC die), not per whole wafer.")
        notes.append("Spot series = session average in USD on the price date the page states (not the fetch date); "
                     "High/Low are the day's (daily boxes) or the week's (weekly boxes) range; Change % is the "
                     "change DRAMeXchange shows next to each item.")
        first_fetch = min(r.get("fetched") or r["date"] for r in history)
        notes.append(f"Spot prices recorded since {first_fetch}: DRAMeXchange's older history is members-only, "
                     "so each series grows by one point per page update.")
    return series, tables, notes


def build_press(history, today_str):
    """History rows -> the 'TrendForce memory price releases' table (last 365 days, newest first)."""
    cutoff = (dt.date.fromisoformat(today_str) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    # Re-apply the memory filter here too, so a tightened filter also cleans rows recorded earlier.
    rows = sorted((r for r in history if r.get("date", "") >= cutoff and is_memory_release(r.get("title"))),
                  key=lambda r: (r["date"], r["url"]), reverse=True)
    if not rows:
        return []
    return [{
        "id": "trendforce_memory_releases",
        "title": "TrendForce memory price releases",
        "columns": ["Date", "Title", "URL", "% figures"],
        "rows": [[r["date"], r["title"], r["url"], r.get("figures")] for r in rows],
        "source": TF_NAME,
        "source_url": "https://www.trendforce.com/presscenter/news",
        "asof": max(r.get("seen") or "" for r in history),
    }]


def build():
    """Rebuild graph/memory_prices.json from history + the show switches. No network."""
    show = (config().get("show") or {})
    hidden = [sid for sid in (DX_SOURCE_ID, TF_SOURCE_ID) if show.get(sid, True) is False]
    now = today()

    series, tables, notes, attribution = [], [], [], []
    if DX_SOURCE_ID not in hidden:
        s, t, n = build_spot(read_history(SPOT_DATASET))
        series += s
        tables += t
        notes += n
        if s:
            attribution.append(DX_ATTRIBUTION)
    if TF_SOURCE_ID not in hidden:
        t = build_press(read_history(PRESS_DATASET), now)
        tables += t
        if t:
            attribution.append(TF_ATTRIBUTION)
            notes.append("TrendForce releases are kept when the title mentions DRAM, NAND, HBM, SSD, flash, "
                         "memory or contract prices; % figures are copied from the title and summary.")

    data = {
        "updated": now,
        "title": "Memory prices",
        "attribution": "; ".join(attribution),
        "hidden_sources": hidden,
        "series": series,
        "tables": tables,
        "notes": notes,
    }
    write_json(OUT_FILE, data)
    log(f"wrote {OUT_FILE.relative_to(GRAPH.parent)}: {len(series)} series, {len(tables)} tables"
        + (f", hidden: {', '.join(hidden)}" if hidden else ""))
    return data


def run(backfill=False):
    """Fetch today's data from both sources, append history, rebuild the web file.
    Returns True when at least one source worked (the file is rebuilt either way, from whatever history exists)."""
    if backfill:
        log("note: DRAMeXchange spot history is members-only; --backfill only walks the TrendForce press list")
    ok_dx = collect_dramexchange()
    time.sleep(1.0)
    ok_tf = collect_trendforce(backfill=backfill)
    build()
    return ok_dx or ok_tf


def main():
    ap = argparse.ArgumentParser(description="Memory prices: DRAMeXchange spot + TrendForce memory releases")
    ap.add_argument("--backfill", action="store_true", help="also walk the TrendForce press list back 365 days")
    ap.add_argument("--build-only", action="store_true", help="rebuild graph/memory_prices.json from history only")
    args = ap.parse_args()
    if args.build_only:
        build()
        return 0
    return 0 if run(backfill=args.backfill) else 1


if __name__ == "__main__":
    sys.exit(main())
