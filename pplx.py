"""
pplx.py -- earnings-call transcripts from Perplexity Finance, every market -> transcripts/perplexity/*.txt

The call source that comes AFTER each market's own collectors (user, 2026-10-20: "api 쓰는게 더 빠르면 ... 그거 써도
되고 없으면 그 퍼플렉시티 파이낸스 쓰면 된다 앞으로 enrich할 때도"; 2026-10-21: Perplexity for every market, and
"막혔으면 다른 방식 찾아내서라도 안 막히게"). Same shape as av.py / dart.py so the enrich loop is identical:

    python pplx.py sync                  # tonight's due companies -> their Perplexity call list -> every call that no
                                         #   other source has saved -> transcripts/perplexity/ + the queue
    python pplx.py targets               # who sync would look at tonight, and why (no browser, no requests)
    python pplx.py pending               # files saved by sync that are not enriched yet
    python pplx.py done [--label L]      # clear the queue (or one row) after enriching
    python pplx.py status                # coverage, last runs, blocks
    python pplx.py fetch "SK hynix"      # one company by hand (its newest call; --event <id> for another)

WHAT PERPLEXITY GIVES. Perplexity Finance shows a company's earnings calls with the full transcript: every paragraph
of the prepared remarks and the whole Q&A, with timestamps and chapters ("Prepared Remarks", "Q&A"). The transcripts
come from Quartr, a call-recording vendor (each transcript's audio link is files.quartr.com): the call as spoken,
not a summary and not a company document. Verified 2026-10-21 on SK hynix Q2 2026: 213 paragraphs, the whole call.

HOW IT GETS IN. Perplexity sits behind Cloudflare's bot check: curl / requests get a 403 "Just a moment..." page and
anonymous Jina Reader is refused too. A REAL Chrome passes the check, so this script drives the installed Chrome
through Playwright (channel="chrome") with its own persistent profile (PROFILE, outside the repo; Cloudflare's
clearance cookie stays in it between runs). Once the page is open, the page's own fetch() calls the same JSON
endpoints the website calls when a person opens the Earnings tab:
    /rest/finance/earnings/<SYMBOL>                      -> the company's calls (date, id, fiscal year / period)
    /rest/finance/earnings/<SYMBOL>/transcript/<id>      -> {date, status, paragraphs[{time, text, speakers}], chapters}
No login, no key, no model call. Headless works; when the check does not clear headless, the script retries with a
normal Chrome window parked off-screen.

STAYING UNBLOCKED (the user's ask). One browser, one page, one request at a time, a random 4-9 s pause between
requests, at most MAX_LISTS call lists and MAX_SAVES transcripts a night, a runtime budget, and nothing fetched
twice: every call id it ever decided is in the state file, each company is rechecked only when a new call is
plausible (weekly while due, monthly when Perplexity does not cover it). A 403 / 429 / challenge page mid-run ->
one cool-down and retry, then the run stops cleanly and the next night carries on.

ORDER OF SOURCES. A call is taken from Perplexity only when it is at least WAIT_DAYS old and no other source has it:
not in the graph (a call label within 5 days), not in another collector's queue (av / investing / tw / kind), and no
transcript file for the same label. So Alpha Vantage / defeatbeta (US) and the market's own collector get it first.

LABELS. `<Company> Q<N> FY<YYYY> (MM-DD-YYYY)` like every call. The quarter follows the company's own labels in the
graph: Perplexity's fiscal period is shifted by the offset found on a call both have (so a company we label by
calendar quarter stays that way); with no shared call, Perplexity's own fiscal year / period is used.
"""

import argparse
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
METADATA = ROOT / "company_metadata.json"
GRAPH = ROOT / "graph" / "merged_graph.json"
BOARD = ROOT / "graph" / "enrich_status.json"
OUT_DIR = ROOT / "transcripts" / "perplexity"
STATE = ROOT / "perplexity" / "sync_state.json"      # runs, symbols, per-company schedule, every call id decided
PENDING = ROOT / "perplexity" / "pending.json"       # files saved by sync, not enriched yet
# The Chrome profile lives outside the repo (and outside OneDrive): it holds cookies, never commit it.
PROFILE = Path.home() / "AppData" / "Local" / "nodus42-pplx-profile"

BASE = "https://www.perplexity.ai"
PAUSE = (4.0, 9.0)          # seconds between two requests, random in this range
MAX_LISTS = 150             # call lists (one per company) a night
MAX_SAVES = 30              # transcripts saved a night
BUDGET_MIN = 40             # minutes a sync may run
WAIT_DAYS = 2               # a call must be this old: Alpha Vantage / defeatbeta / the market's collector go first
DUE_DAYS = 75               # a company's next call is plausible this long after its last one
RECHECK_DUE = 7             # days between two looks at a company whose new call has not shown up yet
RECHECK_UNCOVERED = 30      # days before a company Perplexity does not cover is tried again
WAITING_MAX = 10            # days a call whose transcript is not final yet is retried
SAME_CALL_DAYS = 5          # two dates this close are the same call (time zones, a late file)
PER_COMPANY = 2             # calls saved per company per night (a company far behind catches up over nights)

# Exchange -> the suffix Perplexity uses for a bare local ticker. A ticker that already carries a suffix
# ("2330.TW", "6857.T", "000660.KS") is used as it is.
SUFFIX = {
    "KOSDAQ": [".KQ"], "KRX": [".KS", ".KQ"], "KOSPI": [".KS"],
    "SZSE": [".SZ"], "SSE": [".SS"],
    "XETRA": [".DE"], "Euronext Paris": [".PA"], "EPA": [".PA"], "Euronext Amsterdam": [".AS"], "AMS": [".AS"],
    "Euronext Brussels": [".BR"], "LSE": [".L"], "OMX Stockholm": [".ST"], "OMX Helsinki": [".HE"],
    "OMX Copenhagen": [".CO"], "VIE": [".VI"], "HOSE": [".VN"],
    # the exchanges whose tickers usually carry the suffix already, for the few that do not ('2383' on TWSE)
    "TWSE": [".TW"], "TPEx": [".TWO"], "TSE": [".T"], "HKEX": [".HK"], "SGX": [".SI"], "NSE": [".NS"], "SIX": [".SW"],
    "MIL": [".MI"], "STO": [".ST"], "TSX": [".TO"], "ASX": [".AX"], "IDX": [".JK"], "Bursa Malaysia": [".KL"],
    "Bursa": [".KL"], "B3": [".SA"], "Tadawul": [".SR"], "BIST": [".IS"],
}
US_EXCHANGES = {"NASDAQ", "NYSE", "NYSE American", "OTC"}
CALL_LABEL = re.compile(r"^(?P<name>.+) Q(?P<q>[1-4]) FY(?P<fy>20\d\d) \((?P<d>\d\d-\d\d-\d{4})\)$")
# Folders that hold company filings, not calls: a DART report or an 8-K for the same quarter is not the call.
NOT_CALL_DIRS = ("dart", "edgar", "ir", "kind", "mops", "tdnet", "edinet", "cninfo", "cninfo_reports", "conferences",
                 "media", "non_transcript_sources", "utility_filings", "hkex", "cnbrief", "dod")
# Other collectors' queues: a call already saved there (not enriched yet) is not fetched again here.
OTHER_QUEUES = ["av/pending.json", "investing/pending.json", "tw/pending.json", "kind/pending.json"]


class Blocked(Exception):
    """Cloudflare (or Perplexity) refused us: stop the run, the next night carries on."""


# ---------------------------------------------------------------- the map: who, which symbol, which calls we have

def read_json(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def slug(name):
    """'SK hynix' -> 'skhynix' (same rule as av.py / dart.py)."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def symbols_for(ticker, exchange):
    """Perplexity symbols to try for one company, best guess first ([] = no listed ticker)."""
    ticker = (ticker or "").strip()
    if not ticker:
        return []
    if exchange == "KONEX":
        return []                                   # Perplexity has no KONEX quotes
    if ticker.endswith("."):                        # 'RR.' (Rolls-Royce, LSE)
        ticker = ticker[:-1]
    if exchange in US_EXCHANGES:
        return [ticker]
    if "." in ticker:
        out = [ticker]
        if ticker.endswith(".HK") and ticker.startswith("0"):
            out.append(ticker.lstrip("0"))          # '0522.HK' -> also '522.HK'
        if ticker.endswith(".SS"):
            out.append(ticker[:-3] + ".SH")
        return out
    return [ticker + s for s in SUFFIX.get(exchange, [])] or [ticker]


def call_dates(graph):
    """company -> sorted call dates [(date, fy, q)] from its OWN call labels in the graph (contracts included)."""
    labels = {}
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            labels.setdefault(node["id"], set()).add(q.get("quarter", ""))
    for edge in graph["edges"]:
        for c in edge.get("contracts", []):
            for end in (edge.get("source"), edge.get("target")):
                labels.setdefault(end, set()).add(c.get("source", ""))
    out = {}
    for company, labs in labels.items():
        rows = set()
        for lab in labs:
            m = CALL_LABEL.match(lab)
            if m and m.group("name") == company:
                rows.add((datetime.strptime(m.group("d"), "%m-%d-%Y").date(), int(m.group("fy")), int(m.group("q"))))
        out[company] = sorted(rows)
    return out


def queued_calls():
    """company -> call dates already saved by another collector and waiting in its queue."""
    out = {}
    for rel in OTHER_QUEUES:
        for row in read_json(ROOT / rel, []):
            m = CALL_LABEL.match(row.get("label", ""))
            if m:
                out.setdefault(row.get("company") or m.group("name"), []).append(
                    datetime.strptime(m.group("d"), "%m-%d-%Y").date())
    return out


def board_call_gaps():
    """Companies the status board lists as never having had a call / overdue for one (first in line)."""
    board = read_json(BOARD, {}).get("board", {})
    out = []
    for m in board.get("markets", []):
        out += list(m.get("never", [])) + [r["company"] for r in m.get("overdue", [])]
    return out


def universe():
    """[(name, ticker, exchange)] for every graph node with a listed ticker."""
    meta = read_json(METADATA, {})
    nodes = {n["id"] for n in read_json(GRAPH, {"nodes": []})["nodes"]}
    return [(n, i.get("ticker"), i.get("exchange")) for n, i in meta.items()
            if n in nodes and symbols_for(i.get("ticker"), i.get("exchange"))]


def targets(state, today):
    """Tonight's companies, in order: the board's call gaps first, then the longest-waiting due calls.

    A company is due when it never had a call in the graph or its last call is DUE_DAYS old (a new quarter's call is
    plausible), and its own recheck date (state) has come."""
    graph = read_json(GRAPH, {"nodes": [], "edges": []})
    calls = call_dates(graph)
    gaps = set(board_call_gaps())
    rows = []
    for name, ticker, exchange in universe():
        info = state["companies"].get(name, {})
        if info.get("next_check") and info["next_check"] > today.isoformat():
            continue
        last = calls.get(name, [])[-1][0] if calls.get(name) else None
        if last is not None and (today - last).days < DUE_DAYS and name not in gaps:
            continue
        if exchange in US_EXCHANGES and name not in gaps:
            continue            # US calls come from Alpha Vantage / defeatbeta; Perplexity only for the board's gaps
        why = "board gap" if name in gaps else ("never had a call" if last is None else f"last call {last}")
        rank = (0 if name in gaps else 1, last or date.min)
        rows.append((rank, name, ticker, exchange, why))
    rows.sort(key=lambda r: r[0])
    return [(name, ticker, exchange, why) for _, name, ticker, exchange, why in rows]


# ---------------------------------------------------------------- the browser

class Perplexity:
    """One real Chrome with the persistent profile; get_json() fetches a /rest path from inside the page."""

    def __init__(self, headless=True):
        self.headless = headless
        self.last = 0.0

    def __enter__(self):
        from playwright.sync_api import sync_playwright      # imported here so `targets` / `pending` need no browser
        self.pw = sync_playwright().start()
        try:
            self._open(self.headless)
        except Blocked:
            if not self.headless:
                raise
            print("headless Chrome did not pass the check -- retrying with a window parked off-screen")
            self.ctx.close()
            self._open(False)
        return self

    def _open(self, headless):
        PROFILE.mkdir(parents=True, exist_ok=True)
        self.ctx = self.pw.chromium.launch_persistent_context(
            str(PROFILE), channel="chrome", headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--window-position=-2400,-2400"])
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.goto(BASE + "/finance", wait_until="domcontentloaded", timeout=60000)
        self._wait_for_check()

    def _wait_for_check(self, seconds=45):
        """Cloudflare's interstitial says 'Just a moment...' until the browser passes; wait it out."""
        end = time.time() + seconds
        while "just a moment" in (self.page.title() or "").lower():
            if time.time() > end:
                raise Blocked("Cloudflare check did not clear")
            self.page.wait_for_timeout(1500)

    def __exit__(self, *exc):
        try:
            self.ctx.close()
        finally:
            self.pw.stop()

    def get_json(self, path, retry=True):
        """GET one JSON path from inside the page. None = 404 (Perplexity has no such symbol / call)."""
        wait = random.uniform(*PAUSE) - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        res = self.page.evaluate("""async (p) => {
            const r = await fetch(p, {credentials: 'include', headers: {'accept': 'application/json'}});
            return {status: r.status, text: await r.text()};
        }""", path)
        status, text = res["status"], res["text"]
        if status in (403, 429, 503) or text.lstrip()[:200].lower().startswith("<!doctype"):
            if not retry:
                raise Blocked(f"{status} on {path}")
            print(f"  {status} on {path} -- cooling down 90 s, reopening the page, one retry")
            time.sleep(90)
            self.page.goto(BASE + "/finance", wait_until="domcontentloaded", timeout=60000)
            self._wait_for_check()
            return self.get_json(path, retry=False)
        if status in (400, 404):
            return None
        if status != 200:
            raise RuntimeError(f"HTTP {status} on {path}: {text[:120]}")
        return json.loads(text)


# ---------------------------------------------------------------- calls and labels

# Perplexity gives each call's start in UTC ('2026-07-28T23:00:00.000Z'). An 8 a.m. call in Seoul is still the day
# before in UTC, so the date in the label is taken in the exchange's own time (hours from UTC; DST ignored -- the calls
# are in daytime, so an hour never moves the date). Suffixes not listed are European exchanges (UTC+1).
UTC_OFFSET = {".KS": 9, ".KQ": 9, ".T": 9, ".TW": 8, ".TWO": 8, ".HK": 8, ".SS": 8, ".SH": 8, ".SZ": 8, ".SI": 8,
              ".KL": 8, ".JK": 7, ".VN": 7, ".NS": 5.5, ".AX": 10, ".SR": 3, ".IS": 3, ".TO": -5, ".SA": -3}


def event_date(ev, symbol=""):
    """The call's date in the exchange's own time ('2026-07-28T23:00:00.000Z' on .KS -> 2026-07-29)."""
    raw = str(ev.get("date", ""))
    try:
        start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return date.fromisoformat(raw[:10])
    suffix = symbol[symbol.rfind("."):] if "." in symbol else ""
    hours = UTC_OFFSET.get(suffix, 1 if suffix else -5)       # no suffix = a US listing (Eastern time)
    return (start + timedelta(hours=hours)).date()


def event_period(ev):
    """(fiscal year, quarter) as Perplexity files the call; quarter None when it is not Q1-Q4 (H1, FY...)."""
    fy = ev.get("fiscalYear")
    fp = str(ev.get("fiscalPeriod") or "").upper()
    m = re.search(r"([1-4])", fp)
    if fp.startswith("H"):                          # half-year results: H1 -> Q2, H2 -> Q4
        return (int(fy) if fy else None), (2 if m and m.group(1) == "1" else 4)
    return (int(fy) if fy else None), (int(m.group(1)) if m and fp.startswith("Q") else None)


def label_period(ev, events, ours, sym):
    """The (fy, q) for OUR label: Perplexity's period shifted by the offset seen on a call both sides have."""
    fy, q = event_period(ev)
    if fy is None or q is None:
        return None
    for other in events:
        ofy, oq = event_period(other)
        if ofy is None or oq is None:
            continue
        for d, lfy, lq in ours:
            if abs((event_date(other, sym) - d).days) <= SAME_CALL_DAYS:
                shift = (lfy * 4 + lq - 1) - (ofy * 4 + oq - 1)
                n = fy * 4 + q - 1 + shift
                return n // 4, n % 4 + 1
    return fy, q


def speaker_of(par):
    """'Name (Title)' from a paragraph's speakers list, '' when the transcript does not say."""
    names = []
    for s in par.get("speakers") or []:
        if isinstance(s, dict):
            name = (s.get("name") or s.get("speakerName") or "").strip()
            title = (s.get("title") or s.get("role") or s.get("company") or "").strip()
            if name:
                names.append(f"{name} ({title})" if title and title != name else name)
        elif isinstance(s, str) and s.strip():
            names.append(s.strip())
    return " / ".join(names)


def write_file(name, symbol, ev, data, fy, q):
    """Save one transcript with the header every call file carries; returns (path, label)."""
    day = event_date(ev, symbol)
    label = f"{name} Q{q} FY{fy} ({day.strftime('%m-%d-%Y')})"
    path = OUT_DIR / f"{slug(name)}_q{q}_{fy}.txt"
    pars = data.get("paragraphs") or []
    chapters = [c for c in (data.get("chapters") or []) if c.get("level") == 1]
    starts = {}
    for c in chapters:                              # a section heading before the first paragraph of each chapter
        first = next((i for i, p in enumerate(pars) if (p.get("time") or 0) >= (c.get("startTimestamp") or 0)), None)
        if first is not None:
            starts.setdefault(first, c.get("title"))
    url = f"{BASE}/finance/{symbol}/earnings"
    lines = [
        f"SOURCE: Perplexity Finance {url} (call {ev.get('id')}; transcript by Quartr) -- full call, as spoken",
        f"CALL DATE: {day.strftime('%m-%d-%Y')}",
        f"QUARTER: Q{q} FY{fy}",
        f"# source label: {label}",
        f"# paragraphs: {len(pars)}   characters: {sum(len(p.get('text') or '') for p in pars):,}   "
        f"status: {data.get('status')}   sections: {', '.join(c.get('title') or '' for c in chapters) or 'none'}",
        "", "---", "",
    ]
    previous = None
    for i, p in enumerate(pars):
        if i in starts:
            lines += [f"## {starts[i]}", ""]
            previous = None
        who = speaker_of(p)
        text = (p.get("text") or "").strip()
        lines += [f"{who}: {text}" if who and who != previous else text, ""]
        previous = who or previous
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, label


# ---------------------------------------------------------------- state and queue

def load_state():
    state = read_json(STATE, {})
    for key, empty in (("runs", []), ("symbols", {}), ("companies", {}), ("events", {})):
        state.setdefault(key, empty)
    return state


def save_state(state):
    STATE.parent.mkdir(exist_ok=True)
    state["runs"] = state["runs"][-60:]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def queue(rows):
    pending = read_json(PENDING, [])
    known = {(x["file"], x["label"]) for x in pending}
    for name, path, label in rows:
        row = {"kind": "transcript", "company": name,
               "file": str(path.relative_to(ROOT)).replace("\\", "/"), "label": label}
        if (row["file"], row["label"]) not in known:
            pending.append(row)
    PENDING.parent.mkdir(exist_ok=True)
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- sync

def calls_of(px, state, name, ticker, exchange):
    """The company's call list from Perplexity, trying its symbols until one answers. (symbol, events) or (None, [])."""
    known = state["symbols"].get(name)
    for sym in ([known] if known else symbols_for(ticker, exchange)):
        events = px.get_json(f"/rest/finance/earnings/{sym}")
        if isinstance(events, dict):                # tolerate {"earnings": [...]}-style wrappers
            events = next((v for v in events.values() if isinstance(v, list)), [])
        if events:
            state["symbols"][name] = sym
            return sym, [e for e in events if isinstance(e, dict) and e.get("id") and e.get("date")]
    return None, []


def have_call_file(name, fy, q, documents):
    """Is this company's call for (fy, q) already saved by any source? Exact company match only (the corpus's loose
    prefix match would let 'Nanya Technology' stand in for 'Nan Ya PCB'), and only call files: a full transcript
    (no suffix) outside the filings folders."""
    from agent.corpus import normalize_company
    token = normalize_company(name)
    for d in documents:
        folder = d.path.split("/")[1] if d.path.count("/") >= 2 else ""
        if (d.company_token == token and d.quarter == q and d.year == fy and d.is_full_transcript
                and folder not in NOT_CALL_DIRS):
            return True
    return (OUT_DIR / f"{slug(name)}_q{q}_{fy}.txt").exists()


def take_calls(px, state, name, sym, events, ours, queued, documents, today, max_saves):
    """Save the calls no other source has. Returns [(name, path, label)] and how the company's schedule moves on."""
    last_ours = ours[-1][0] if ours else None
    newer = [e for e in events if event_date(e, sym) <= today - timedelta(days=WAIT_DAYS)
             and (last_ours is None or event_date(e, sym) > last_ours + timedelta(days=SAME_CALL_DAYS))]
    newer.sort(key=lambda e: event_date(e, sym))
    if last_ours is None:
        newer = newer[-1:]                          # never enriched: the newest call only, no years of backfill
    saved = []
    for ev in newer:
        if len(saved) >= min(PER_COMPANY, max_saves):
            break
        key = str(ev["id"])
        seen = state["events"].get(key, "")
        if seen.startswith(("saved", "skip")):
            continue
        day = event_date(ev, sym)
        if any(abs((day - d).days) <= SAME_CALL_DAYS for d in queued.get(name, [])):
            state["events"][key] = "skip:queued by another collector"
            continue
        if ev.get("requiresLogin"):
            state["events"][key] = "skip:requires login"
            continue
        period = label_period(ev, events, ours, sym)
        if period is None:
            state["events"][key] = f"skip:no quarter ({ev.get('fiscalPeriod')})"
            continue
        fy, q = period
        label = f"{name} Q{q} FY{fy} ({day.strftime('%m-%d-%Y')})"
        if have_call_file(name, fy, q, documents):
            state["events"][key] = "skip:a transcript for this label is already saved"
            continue
        data = px.get_json(f"/rest/finance/earnings/{sym}/transcript/{key}")
        pars = (data or {}).get("paragraphs") or []
        first = seen.split(":", 1)[1] if seen.startswith("waiting:") else today.isoformat()
        not_final = (data or {}).get("status") not in ("final", None)
        if not pars or (not_final and (today - date.fromisoformat(first)).days < 3):
            if not pars and (today - day).days > WAITING_MAX:
                state["events"][key] = "skip:no transcript on Perplexity"
            elif (today - date.fromisoformat(first)).days > WAITING_MAX:
                state["events"][key] = "skip:no final transcript after %d days" % WAITING_MAX
            else:
                state["events"][key] = "waiting:" + first
                print(f"waiting  {label:48s} transcript not final yet ({(data or {}).get('status')})")
            continue
        path, label = write_file(name, sym, ev, data, fy, q)
        state["events"][key] = "saved:" + str(path.relative_to(ROOT)).replace("\\", "/")
        saved.append((name, path, label))
        print(f"saved    {label:48s} -> {path.relative_to(ROOT)}  ({len(pars)} paragraphs)")
    return saved


def next_check(events, today, sym, state):
    """When to look at this company again: tomorrow while a call waits for its transcript, else just after its next
    announced call, else in RECHECK_DUE days."""
    if any(state["events"].get(str(e["id"]), "").startswith("waiting") for e in events):
        return today + timedelta(days=1)
    upcoming = sorted(event_date(e, sym) for e in events if event_date(e, sym) > today)
    if upcoming:
        return max(upcoming[0] + timedelta(days=WAIT_DAYS), today + timedelta(days=1))
    return today + timedelta(days=RECHECK_DUE)


def sync(only=None, headed=False, force=False, limit=None):
    state = load_state()
    today = date.today()
    if not force and not only and any(r.get("date") == today.isoformat() and r.get("finished")
                                      and r.get("kind", "sync") == "sync" for r in state["runs"]):
        print(f"pplx sync already ran today ({today}); one run a day -- use --force to run again")
        return []
    if only:
        wanted = [u for u in universe() if u[0].lower() == only.lower()]
        todo = [(n, t, e, "by hand") for n, t, e in wanted]
        if not todo:
            sys.exit(f"{only!r} is not a graph node with a listed ticker")
    else:
        todo = targets(state, today)[:limit]
    graph = read_json(GRAPH, {"nodes": [], "edges": []})
    calls, queued = call_dates(graph), queued_calls()
    from agent.corpus import list_documents
    documents = list_documents()
    run = {"date": today.isoformat(), "kind": "fetch" if only else "sync", "started": datetime.now().strftime("%H:%M"),
           "due": len(todo),
           "looked": 0, "covered": 0, "saved": 0, "finished": False}
    print(f"{len(todo)} companies due tonight (lists <= {MAX_LISTS}, transcripts <= {MAX_SAVES}, {BUDGET_MIN} min)")
    stop_at = time.time() + BUDGET_MIN * 60
    saved = []
    try:
        with Perplexity(headless=not headed) as px:
            for name, ticker, exchange, why in todo:
                if run["looked"] >= MAX_LISTS or len(saved) >= MAX_SAVES or time.time() > stop_at:
                    print("nightly cap reached -- the rest waits for the next run")
                    break
                run["looked"] += 1
                info = state["companies"].setdefault(name, {})
                info["checked"] = today.isoformat()
                try:
                    sym, events = calls_of(px, state, name, ticker, exchange)
                except Blocked:
                    raise
                except Exception as exc:
                    print(f"FAIL     {name}: {exc}")
                    continue
                if not sym:
                    info.update(covered=False, next_check=(today + timedelta(days=RECHECK_UNCOVERED)).isoformat())
                    print(f"none     {name:32s} not on Perplexity ({', '.join(symbols_for(ticker, exchange))})")
                    continue
                run["covered"] += 1
                past = [e for e in events if event_date(e, sym) <= today]
                info.update(covered=True, symbol=sym,
                            last_event=max(event_date(e, sym) for e in past).isoformat() if past else None)
                got = take_calls(px, state, name, sym, events, calls.get(name, []), queued, documents, today,
                                 MAX_SAVES - len(saved))
                saved += got
                info["next_check"] = next_check(events, today, sym, state).isoformat()
                if not got:
                    print(f"nothing  {name:32s} ({why}; newest call on Perplexity {info['last_event']})")
                save_state(state)
        run["finished"] = True
    except Blocked as exc:
        run["blocked"] = str(exc)
        print(f"\nBLOCKED  {exc} -- stopped cleanly; the next run carries on")
    run["saved"] = len(saved)
    state["runs"].append(run)
    state["last_sync"] = today.isoformat()
    save_state(state)
    queue(saved)
    return saved


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="tonight's due companies -> their new calls")
    s.add_argument("--headed", action="store_true", help="a visible (off-screen) Chrome window instead of headless")
    s.add_argument("--force", action="store_true", help="run again although today's run already finished")
    s.add_argument("--limit", type=int, help="look at only the first N due companies (tests)")
    f = sub.add_parser("fetch", help="one company by hand")
    f.add_argument("company")
    f.add_argument("--headed", action="store_true")
    sub.add_parser("targets", help="who sync would look at tonight (no requests)")
    sub.add_parser("pending", help="files saved by sync that are not enriched yet")
    d = sub.add_parser("done", help="clear the queue after enriching (all rows, or one with --label)")
    d.add_argument("--label")
    sub.add_parser("status", help="coverage, runs and blocks")
    args = parser.parse_args()

    if args.cmd == "sync":
        rows = sync(headed=args.headed, force=args.force, limit=args.limit)
        print(f"\n{len(rows)} transcript(s) saved; `python pplx.py pending` shows the enrichment queue")
    elif args.cmd == "fetch":
        rows = sync(only=args.company, headed=args.headed, force=True)
        print(f"\n{len(rows)} transcript(s) saved")
    elif args.cmd == "targets":
        rows = targets(load_state(), date.today())
        for name, ticker, exchange, why in rows:
            print(f"{name:34s} {', '.join(symbols_for(ticker, exchange)):22s} {why}")
        print(f"{len(rows)} due (a sync looks at the first {MAX_LISTS})")
    elif args.cmd == "pending":
        rows = read_json(PENDING, [])
        for r in rows:
            print(f"{r['company']:32s} {r['label']:48s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = read_json(PENDING, [])
        keep = [r for r in rows if args.label and r["label"] != args.label]
        PENDING.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(rows) - len(keep)} row(s) cleared, {len(keep)} left")
    elif args.cmd == "status":
        st = load_state()
        cov = [c for c in st["companies"].values() if c.get("covered")]
        print(f"companies looked at: {len(st['companies'])}, on Perplexity: {len(cov)}, "
              f"calls decided: {len(st['events'])} "
              f"(saved {sum(1 for v in st['events'].values() if v.startswith('saved'))})")
        for r in st["runs"][-7:]:
            print(f"  {r['date']} {r.get('started', '')}  due {r['due']}  looked {r['looked']}  covered {r['covered']}  "
                  f"saved {r['saved']}" + (f"  BLOCKED {r['blocked']}" if r.get("blocked") else "")
                  + ("" if r.get("finished") or r.get("blocked") else "  (did not finish)"))
