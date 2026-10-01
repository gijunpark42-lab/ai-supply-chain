"""
enrich_status.py — the enrichment PIPELINE dashboard behind the web app's Coverage tab.

The Coverage tab already answers "which COMPANY should I enrich next?". This module
answers the other half: "which PIPELINE ran when, what did it cover, what is still missing?"

For every pipeline (enrich us / dart / intl / tw / edgar / conference, plus the manual
`Transcript:<company>` pastes) it reads what is already on disk — no new bookkeeping:

  * the pipeline's state files   (av/sync_state.json, dart/sync_state.json, ...)  -> last sync, waiting list
  * the pipeline's pending queue (av/pending.json, investing/pending.json, ...)  -> what is NOT yet enriched
  * its transcript folder        (transcripts/av/*.txt, ...)                      -> what was fetched, and when
  * the merged graph             (graph/merged_graph.json)                        -> which source labels landed
  * the patch receipts           (patches/applied/*.json)                         -> when each label was enriched

On top of the pipeline cards it builds the MARKET BOARD (added 2026-09-26): per home market
(US, Korea, Taiwan, Japan, Europe, China) which companies are current / overdue / never enriched,
what is fetched and waiting, and the ordered "Run next" list of `enrich <market>` commands.

Outputs:
  graph/enrich_status.json   GENERATED every build (never hand-edit) — read by web/ via `npm run sync`;
                             the board sits under the "board" key.
  ENRICH_STATUS.md           GENERATED — the same board as a page: read it first before any enrich run.
  enrich_log.json            APPEND-ONLY record at the repo root, committed. One row per (day, pipeline)
                             whenever the counts change, so the run history survives a fresh clone
                             (file mtimes and patch receipts do not).
  enrich_marks.json          HAND-RECORDED by the coordinator through `mark` / `unmark` / `note` / `ask` /
                             `resolve` below (facts no script can infer: "no free transcript exists",
                             "stopped at ...", and open questions for the user).

Run by graph_build.py after the graph is built; can also be run alone:  python -X utf8 enrich_status.py
Record a fact:  python -X utf8 enrich_status.py mark "Bayer" --source call --why "no free transcript"
                python -X utf8 enrich_status.py note US "AV quota hit after 25 calls; 3 left"
"""

import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

# verify_graph.py already knows how to turn a source label into the file it came from
# (header "# source label:", filename join, event-name match). Reuse it instead of
# re-implementing the matching rules here.
from verify_graph import load_documents, resolve_label
from taxonomy import MARKETS, market_of

GRAPH_FILE = os.path.join("graph", "merged_graph.json")
STATUS_FILE = os.path.join("graph", "enrich_status.json")
LOG_FILE = "enrich_log.json"

# One entry per pipeline. `dirs` = the transcript folders the pipeline writes; a file's
# folder decides which pipeline it belongs to. Order = display order in the web app.
PIPELINES = [
    {"id": "us",         "name": "US earnings calls",          "command": "enrich us calls",
     "dirs": ["transcripts/av"],                 "state": "av/sync_state.json",       "pending": "av/pending.json",
     "source": "Alpha Vantage / defeatbeta (av.py)"},
    {"id": "edgar",      "name": "US SEC filings",             "command": "enrich edgar",
     "dirs": ["transcripts/edgar"],              "state": None,                       "pending": "edgar/pending.json",
     "source": "SEC EDGAR 8-K / 10-K / 10-Q (edgar_pull.py)"},
    {"id": "dart",       "name": "Korea DART filings",         "command": "enrich dart",
     "dirs": ["transcripts/dart", "supply_contracts"], "state": "dart/sync_state.json", "pending": "dart/pending.json",
     "source": "DART 정기보고서 / 잠정실적 / 공급계약 (dart.py)"},
    {"id": "intl",       "name": "Taiwan / Japan / Europe calls", "command": "enrich intl",
     "dirs": ["transcripts/investing"],          "state": "investing/sync_state.json", "pending": "investing/pending.json",
     "pending_kind": "transcript",
     "source": "Investing.com call transcripts (investing.py)"},
    {"id": "tw",         "name": "Taiwan Chinese 法說會",       "command": "enrich tw",
     "dirs": ["transcripts/tw"],                 "state": "tw/sync_state.json",       "pending": "tw/pending.json",
     "source": "法說會 video → whisper (tw.py)"},
    {"id": "conference", "name": "Investor conferences",       "command": "enrich conference",
     "dirs": ["transcripts/conferences"],        "state": "investing/conferences_state.json", "pending": "investing/pending.json",
     "pending_kind": "conference",
     "source": "Investing.com fireside chats (investing.py conferences)"},
    {"id": "ir",         "name": "Company IR press releases",  "command": "enrich ir",
     "dirs": ["transcripts/ir"],                 "state": "ir/sync_state.json",       "pending": "ir/pending.json",
     "source": "Company IR RSS feeds (ir_pull.py) — company-issued, not transcripts"},
    {"id": "kind",       "name": "Korea IR decks (KIND)",      "command": "enrich korea",
     "dirs": ["transcripts/kind"],               "state": "kind/sync_state.json",     "pending": "kind/pending.json",
     "pending_kind": "deck",
     "source": "KRX KIND IR library + large-cap IR sites (kind.py) — company IR presentations, not transcripts"},
    {"id": "utility",    "name": "US utility regulatory filings", "command": "enrich us",
     "dirs": ["transcripts/utility_filings"],    "state": "utility_filings/sync_state.json", "pending": "utility_filings/pending.json",
     "source": "Utilities' own IRPs / large-load reports and tariffs (utility_filings.py) — company filings, not transcripts"},
    {"id": "krcalls",    "name": "Korea earnings-call scripts", "command": "enrich korea",
     "dirs": ["transcripts/kr_calls"],           "state": "kind/sync_state.json",     "pending": "kind/pending.json",
     "pending_kind": "call",
     "source": "Samsung's official earnings-call script (kind.py)"},
    {"id": "cninfo",     "name": "China IR records + investor Q&A", "command": "enrich china",
     "dirs": ["transcripts/cninfo"],             "state": "cninfo/sync_state.json",   "pending": "cninfo/pending.json",
     "source": "cninfo 投资者关系活动记录表 + SZSE 互动易 / SSE e互动 answers (cninfo.py) — management Q&A, not calls"},
    {"id": "tdnet",      "name": "Japan TDnet disclosures",    "command": "enrich japan",
     "dirs": ["transcripts/tdnet"],              "state": "tdnet/sync_state.json",    "pending": "tdnet/pending.json",
     "source": "TSE TDnet timely disclosures (tdnet.py) — results, forecasts, capex, plans, deals; company filings, not transcripts"},
    {"id": "mops",       "name": "Taiwan MOPS filings",        "command": "enrich taiwan",
     "dirs": ["transcripts/mops"],               "state": "mops/sync_state.json",     "pending": "mops/pending.json",
     "source": "MOPS 法說會 decks, important 重大訊息 and monthly revenue (mops.py) — company filings, not transcripts"},
    {"id": "manual",     "name": "Pasted transcripts",         "command": "Transcript:<company>",
     "dirs": [],                                 "state": None,                       "pending": None,
     "source": "URL / pasted text enriched directly in Claude Code"},
]

LABEL_DATE = re.compile(r"\((\d\d)-(\d\d)-(\d{4})\)")


def label_date(label):
    """'Oracle Q1 FY2027 (09-10-2026)' -> '2026-09-10' (ISO, so strings sort by date)."""
    m = LABEL_DATE.search(label or "")
    return "%s-%s-%s" % (m.group(3), m.group(1), m.group(2)) if m else None


def read_json(path, default):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def mtime_day(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def pipeline_of(path):
    """Which pipeline wrote this file? Decided by its folder; anything else is a manual paste."""
    norm = path.replace("\\", "/")
    for p in PIPELINES:
        for d in p["dirs"]:
            if norm.startswith(d + "/"):
                return p["id"]
    return "manual"


def yyyymmdd_to_iso(s):
    """dart/av sync_state store '20260910' -> '2026-09-10'."""
    s = str(s or "")
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]) if len(s) == 8 and s.isdigit() else (s or None)


def graph_labels(graph):
    """Every source label in the graph -> how many entries carry it."""
    counts = Counter()
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            if q.get("quarter"):
                counts[q["quarter"]] += 1
    for edge in graph["edges"]:
        for c in edge.get("contracts", []):
            if c.get("source"):
                counts[c["source"]] += 1
    return counts


def applied_dates():
    """Patch receipts: source label -> the day the patch was applied (file mtime)."""
    out = {}
    for path in glob.glob(os.path.join("patches", "applied", "*.json")):
        try:
            label = read_json(path, {}).get("source")
        except Exception:
            continue
        if label:
            day = mtime_day(path)
            out[label] = max(out.get(label, ""), day)
    return out


# ---------------------------------------------------------------------------
# Market board — "which enrich should I run next?"
# ---------------------------------------------------------------------------
# The pipeline cards answer "when did each pipeline run". The board answers the user's
# question: per HOME MARKET (US, Korea, Taiwan, Japan, Europe, China), what is still missing
# and which `enrich <market>` command to run. It reads only what is already on disk (graph,
# queues, sync states) plus enrich_marks.json — the one file written by hand, through
# `python enrich_status.py mark / note`, for facts no script can infer ("Bayer has no free
# transcript"). Parallel enrich agents never write it: they report, one coordinator records.

MARKS_FILE = "enrich_marks.json"
BOARD_FILE = "ENRICH_STATUS.md"
EARNINGS_LABEL = re.compile(r" Q[1-4] FY20\d\d \(")
# The label shape "X Q2 FY2026 (…)" is shared by calls, DART periodic reports and a few results
# press releases, so the FILE decides: a call pipeline's folder, or a pasted call under a sector
# folder — but not a company document (non_transcript_sources/, *_press_release, *_tanshin,
# *_dart). A label whose file is not on disk is not counted as a call.
NOT_A_CALL_FILE = re.compile(r"non_transcript_sources/|press_release|tanshin|_dart\.txt$")
MARKET_COMMAND = {"US": "enrich us", "KR": "enrich korea", "TW": "enrich taiwan", "JP": "enrich japan",
                  "EU": "enrich europe", "CN": "enrich china", "other": "enrich intl"}
# The collectors that fetch each market's calls / filings. IR feeds and the conference listing
# serve every market at once, so they are reported once ("shared collectors"), not per market.
MARKET_COLLECTORS = {"US": ["us", "utility"], "KR": ["dart", "kind"], "TW": ["intl", "tw", "mops"], "JP": ["intl", "tdnet"],
                     "EU": ["intl"], "CN": ["intl", "cninfo"], "other": ["intl"]}
SYNC_EVERY = {"us": 1, "dart": 2, "intl": 7, "tw": 7, "edgar": 7, "ir": 3, "conference": 7, "kind": 3,
              "tdnet": 3,   # TDnet keeps only 31 days
              "cninfo": 7,  # days (SSE e互动 shows only about one month, so never let it slip past ~3 weeks)
              "utility": 30,   # days (utility_filings.py: monthly — IRPs and large-load reports change slowly)
              "mops": 3}
COLLECTOR_NAMES = {"us": "US call sync (av.py)", "dart": "DART sync (dart.py)", "kind": "KIND IR deck sync (kind.py)",
                   "tdnet": "TDnet disclosure sync (tdnet.py; TDnet keeps only 31 days)",
                   "cninfo": "China IR record / Q&A sync (cninfo.py)",
                   "utility": "utility regulatory-filing sync (utility_filings.py, monthly)",
                   "mops": "MOPS sync (mops.py)",
                   "intl": "Investing.com call sync (investing.py)", "tw": "Taiwan Chinese-call sync (tw.py)",
                   "edgar": "EDGAR pull (edgar_pull.py)", "ir": "IR feed sync (ir_pull.py)",
                   "conference": "conference listing (investing.py conferences)"}
WAITING_NAMES = {"us": "call", "intl": "call", "tw": "call", "dart": "DART filing", "kind": "IR deck", "krcalls": "call",
                 "tdnet": "TDnet filing", "cninfo": "IR record / investor Q&A",
                 "utility": "utility filing", "mops": "MOPS filing",
                 "conference": "conference", "ir": "IR release"}
LIST_MAX = 12        # names printed per list on ENRICH_STATUS.md (the JSON keeps every name)


def days_between(a, b):
    """Whole days from ISO date `a` to ISO date `b`."""
    return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days


def load_marks():
    """enrich_marks.json -> {"marks", "notes", "questions" (open, for the user), "answered"} lists
    (the file is created by the first mark / note / ask)."""
    data = read_json(MARKS_FILE, {})
    for key in ("marks", "notes", "questions", "answered"):
        data.setdefault(key, [])
    return data


def active_marks(marks, today):
    """(company, source) -> mark, for marks whose recheck date has not passed. An expired mark
    drops out on its own, so the company shows up as missing again and gets re-tried."""
    out = {}
    for m in marks["marks"]:
        if (m.get("recheck") or "9999-12-31") >= today:
            out[(m["company"], m["source"])] = m
    return out


def call_state(call_dates, today):
    """('current' | 'overdue' | 'never', last call date) for one company.
    The company's own rhythm decides: the median gap between its calls (quarterly ~91 days,
    half-yearly ~182). A call is overdue once that gap plus three weeks has passed."""
    if not call_dates:
        return "never", None
    gaps = sorted(days_between(a, b) for a, b in zip(call_dates, call_dates[1:]))
    gaps = [g for g in gaps if g >= 45]          # two labels for one quarter are not a rhythm
    cadence = gaps[len(gaps) // 2] if gaps else 91
    overdue = days_between(call_dates[-1], today) > cadence + 21
    return ("overdue" if overdue else "current"), call_dates[-1]


def is_call(label, pid, path):
    """True when this label is an earnings call (see NOT_A_CALL_FILE above)."""
    if not path or not EARNINGS_LABEL.search(label):
        return False
    if pid in ("us", "intl", "tw", "krcalls"):
        return True
    return pid == "manual" and not NOT_A_CALL_FILE.search(path)


def own_sources(graph, label_pipeline, label_file):
    """company -> {"calls": [ISO dates], "latest": {kind: ISO date}} from the company's OWN
    documents only (the label starts with its name). Another company's call that mentions it
    is not its own disclosure and does not count."""
    labels_of = defaultdict(set)
    for node in graph["nodes"]:
        for q in node.get("quarterly_data", []):
            labels_of[node["id"]].add(q.get("quarter", ""))
    for edge in graph["edges"]:
        for c in edge.get("contracts", []):
            for end in (edge.get("source"), edge.get("target")):
                labels_of[end].add(c.get("source", ""))
    out = {}
    for company, labels in labels_of.items():
        calls, latest = set(), {}
        for lab in labels:
            day = label_date(lab)
            if not day or not lab.startswith(company + " "):
                continue
            pid = label_pipeline.get(lab, "manual")
            if is_call(lab, pid, label_file.get(lab)):
                kind = "call"
                calls.add(day)
            else:
                kind = pid if pid in ("dart", "edgar", "conference", "ir", "kind", "tdnet", "cninfo", "utility", "mops") else "other"
            latest[kind] = max(latest.get(kind, ""), day)
        out[company] = {"calls": sorted(calls), "latest": latest}
    return out


def market_board(graph, label_pipeline, label_file, pipelines, today):
    """Per-market rollup + the ordered 'Run next' list + setup items (see ENRICH_STATUS.md)."""
    meta = read_json("company_metadata.json", {})
    marks = load_marks()
    marked = active_marks(marks, today)
    own = own_sources(graph, label_pipeline, label_file)
    by_id = {p["id"]: p for p in pipelines}
    feeds = read_json("ir/feeds.json", {})

    def market_of_company(name):
        return market_of((meta.get(name) or {}).get("exchange"))

    def age(pid):
        day = by_id.get(pid, {}).get("last_sync")
        return (days_between(day, today), day) if day else (None, None)

    # Fetched but not yet enriched, per market (EDGAR has its own weekly command, counted there).
    waiting = defaultdict(Counter)
    for p in pipelines:
        if p["id"] in ("edgar", "manual"):
            continue
        for r in p["pending"]:
            m = market_of_company(r.get("company"))
            if m:
                waiting[m][p["id"]] += 1

    companies = sorted(n["id"] for n in graph["nodes"])
    markets = []
    for mid, mname in MARKETS:
        names = [n for n in companies if market_of_company(n) == mid]
        row = {"id": mid, "name": mname, "command": MARKET_COMMAND[mid], "companies": len(names),
               "call_current": 0, "overdue": [], "never": [], "nothing": [], "dart_never": [],
               "marked": [], "feeds": sum(1 for n in names if n in feeds),
               "waiting": dict(waiting[mid]),
               "collectors": {pid: by_id.get(pid, {}).get("last_sync") for pid in MARKET_COLLECTORS[mid]}}
        for n in names:
            o = own.get(n, {"calls": [], "latest": {}})
            if not o["latest"]:
                row["nothing"].append(n)
            for (company, source), m in marked.items():
                if company == n:
                    row["marked"].append({"company": n, "source": source, "why": m.get("why"),
                                          "recheck": m.get("recheck")})
            if mid == "KR" and "dart" not in o["latest"] and (n, "dart") not in marked:
                row["dart_never"].append(n)
            if (n, "call") in marked:
                continue
            state, last = call_state(o["calls"], today)
            if state == "current":
                row["call_current"] += 1
            elif state == "overdue":
                row["overdue"].append({"company": n, "last_call": last})
            else:
                row["never"].append(n)
        row["overdue"].sort(key=lambda r: r["last_call"])
        markets.append(row)

    # ── Run next: the commands worth running now, with the reasons ──────────────────
    actions = []
    vq = read_json("verify_queue.json", {}).get("pending", [])
    if len(vq) >= 5:
        actions.append({"command": "Opus verifier over verify_queue.json",
                        "reasons": ["%d applied labels are waiting for the independent check (rule: at 5+)" % len(vq)]})
    by_market = {m["id"]: m for m in markets}
    intl_said = False            # the shared Investing.com sync is named once, on the first market that needs it
    for key in ["US", "KR", "edgar", "TW", "JP", "EU", "CN", "other"]:
        reasons = []
        if key == "edgar":
            days, day = age("edgar")
            queued = len(by_id.get("edgar", {}).get("pending", []))
            if days is None or days > SYNC_EVERY["edgar"]:
                reasons.append("last pulled %s (weekly)" % ("%d days ago, %s" % (days, day) if day else "never"))
            if queued:
                reasons.append("%d filings queued" % queued)
            if reasons:
                actions.append({"command": "enrich edgar", "reasons": reasons})
            continue
        m = by_market[key]
        if not m["companies"]:
            continue
        total = sum(m["waiting"].values())
        if total:
            parts = ", ".join("%d %s" % (n, WAITING_NAMES.get(pid, pid)) for pid, n in sorted(m["waiting"].items()))
            reasons.append("%d fetched file(s) waiting to be enriched (%s)" % (total, parts))
        # A stale collector is a reason only where it can find something: US and Korea have their own
        # collectors (daily/every other day); the shared Investing.com sync counts for a market only when
        # that market already has calls in the graph (otherwise it is its first-time setup, not routine).
        if key in ("US", "KR", "CN") or m["call_current"] or m["overdue"]:
            for pid in MARKET_COLLECTORS[key]:
                days, day = age(pid)
                if pid == "tdnet":
                    continue                     # checked below for every Japan board: TDnet forgets after 31 days
                if pid == "intl" and (intl_said or not (m["call_current"] or m["overdue"])):
                    continue                     # China's own collector (cninfo) counts; Investing.com as before
                if days is None or days > SYNC_EVERY[pid]:
                    reasons.append("%s last ran %s%s" % (
                        COLLECTOR_NAMES[pid], "%d days ago (%s)" % (days, day) if day else "never",
                        " — one sync serves Taiwan, Japan, Europe and China" if pid == "intl" else ""))
                    intl_said = intl_said or pid == "intl"
        if "tdnet" in MARKET_COLLECTORS[key]:
            days, day = age("tdnet")
            if days is None or days > SYNC_EVERY["tdnet"]:
                reasons.append("%s last ran %s" % (COLLECTOR_NAMES["tdnet"],
                                                   "%d days ago (%s)" % (days, day) if day else "never"))
        if m["overdue"] and key != "KR":        # Korea has no call pipeline yet — see the setup list
            reasons.append("%d overdue for a call: %s" % (len(m["overdue"]), short_list(
                ["%s (last %s)" % (r["company"], r["last_call"]) for r in m["overdue"]], 6)))
        if key == "US" and m["never"]:
            reasons.append("%d never had a call enriched (fetch with defeatbeta, mark the ones with none): %s"
                           % (len(m["never"]), short_list(m["never"], 6)))
        if key == "KR" and m["dart_never"]:
            reasons.append("%d have no DART filing enriched (backfill with `dart.py fetch`): %s"
                           % (len(m["dart_never"]), short_list(m["dart_never"], 6)))
        if reasons:
            actions.append({"command": m["command"], "reasons": reasons})

    # ── Setup / decisions no command can fix ────────────────────────────────────────
    setup = []
    kr = by_market["KR"]
    kr_calls = sorted(((n, own[n]["calls"][-1]) for n in companies
                       if market_of_company(n) == "KR" and own.get(n, {}).get("calls")), key=lambda x: x[1])
    if kr["companies"]:
        setup.append("Korean earnings calls: only Samsung publishes an official call script (kind.py fetches it). "
                     "SK Hynix's calls exist only at third-party transcript services, SEMCO / SK Telecom have an audio "
                     "replay, NAVER a gated replay, LG Innotek none; most KOSDAQ names hold no public call (their decks "
                     "come through kind.py). The last calls in the graph are %s; %d Korean companies never had one. A "
                     "call pasted by the user (Transcript:<company>) is enriched as usual."
                     % (short_list(["%s %s" % x for x in kr_calls], 8) or "none", kr["companies"] - len(kr_calls)))

    shared = {}
    for pid in ("ir", "conference"):
        days, day = age(pid)
        shared[pid] = {"last_sync": day, "days": days, "due": days is None or days > SYNC_EVERY[pid]}
    shared["ir"]["feeds"] = len(feeds)
    notes = sorted(marks["notes"], key=lambda r: r.get("at", ""), reverse=True)[:10]
    return {"today": today, "markets": markets, "next_actions": actions, "setup": setup,
            "questions": marks["questions"], "shared": shared, "verify_pending": len(vq), "notes": notes}


def short_list(items, n=LIST_MAX):
    items = list(items)
    return ", ".join(items[:n]) + (" … +%d more" % (len(items) - n) if len(items) > n else "")


def write_board(board, pipelines, generated):
    """ENRICH_STATUS.md — the page a person or a new agent reads to know what to run next."""
    L = ["# Enrichment status board", "",
         "Generated %s by `enrich_status.py`. Every `graph_build.py` run rebuilds it, and every enrich run "
         "ends by rebuilding it. Refresh by hand (seconds, no model tokens): `python -X utf8 enrich_status.py`" % generated,
         "",
         "Agents: read this first and trust it. Do not re-scan pipelines or the graph to find out what is done. "
         "Full name lists: `graph/enrich_status.json` → `board`. Record what no script can know with "
         "`python -X utf8 enrich_status.py mark …` / `note …` (coordinator only, see the end of this page).",
         "", "## Run next", ""]
    if board["next_actions"]:
        for i, a in enumerate(board["next_actions"], 1):
            L.append("%d. **`%s`** — %s" % (i, a["command"], "; ".join(a["reasons"])))
    else:
        L.append("Nothing is due. Every market is current and no queue holds work.")
    sh = board["shared"]
    L += ["", "Shared collectors (every market command runs them first when due): IR feeds synced %s (%d feeds)%s; "
          "conference listing walked %s%s." % (
              sh["ir"]["last_sync"] or "never", sh["ir"]["feeds"], " — due" if sh["ir"]["due"] else "",
              sh["conference"]["last_sync"] or "never", " — due" if sh["conference"]["due"] else ""),
          "Opus verification queue: %d label(s) waiting (runs at 5+)." % board["verify_pending"], ""]
    if board["questions"] or board["setup"]:
        L += ["## Needs a decision or setup", ""]
        L += ["- **Question for the user — %s:** %s%s (asked %s; answer, then `enrich_status.py resolve \"%s\" --answer \"…\"`)"
              % (q["subject"], q["question"], " — source: %s" % q["label"] if q.get("label") else "", q.get("at", ""),
                 q["subject"]) for q in board["questions"]]
        L += ["- " + s for s in board["setup"]] + [""]
    L += ["## Markets", "",
          "| Market | Companies | Call current | Overdue | Never had a call | No own data | Waiting | IR feeds | Collector last ran |",
          "|---|---|---|---|---|---|---|---|---|"]
    for m in board["markets"]:
        if not m["companies"]:
            continue
        coll = ", ".join("%s %s" % (pid, d or "never") for pid, d in m["collectors"].items())
        L.append("| %s — %s | %d | %d | %d | %d | %d | %d | %d | %s |" % (
            m["id"], m["name"], m["companies"], m["call_current"], len(m["overdue"]), len(m["never"]),
            len(m["nothing"]), sum(m["waiting"].values()), m["feeds"], coll))
    L += ["", "`Call current` = the latest own earnings call is within the company's usual gap + 3 weeks. "
          "`No own data` = not one entry from the company's own documents yet (new nodes land here). "
          "Marked companies (no source exists) are left out of Overdue / Never.", "", "## Details by market", ""]
    for m in board["markets"]:
        if not m["companies"]:
            continue
        L.append("### %s — %s (`%s`)" % (m["id"], m["name"], m["command"]))
        if m["overdue"]:
            L.append("- Overdue for a call: " + short_list("%s (last %s)" % (r["company"], r["last_call"]) for r in m["overdue"]))
        if m["never"] and m["id"] != "KR":          # Korea: no call pipeline yet (see the setup list)
            L.append("- Never had a call enriched: " + short_list(m["never"]))
        if m["dart_never"]:
            L.append("- No DART filing enriched: " + short_list(m["dart_never"]))
        if m["waiting"]:
            L.append("- Waiting to enrich: " + ", ".join("%d %s" % (n, WAITING_NAMES.get(p, p)) for p, n in sorted(m["waiting"].items())))
        if m["marked"]:
            L.append("- Known gaps, do not re-search: " + short_list(
                "%s (%s: %s; recheck %s)" % (x["company"], x["source"], x["why"], x["recheck"] or "never") for x in m["marked"]))
        L.append("")
    L += ["## Pipelines", "", "| Pipeline | Command | Last sync | Last enriched | Waiting | Files | In graph |", "|---|---|---|---|---|---|---|"]
    for p in pipelines:
        L.append("| %s | `%s` | %s | %s | %d | %d | %d |" % (p["name"], p["command"], p["last_sync"] or "-",
                                                         p["last_enriched"] or "-", len(p["pending"]), p["files"], p["in_graph"]))
    L += ["", "## Coordinator notes (newest first)", ""]
    L += ["- %s %s: %s" % (n.get("at", ""), n.get("market", ""), n.get("text", "")) for n in board["notes"]] or ["- none yet"]
    L += ["", "## Recording what no script can know (coordinator only)", "",
          "- A source that does not exist: `python -X utf8 enrich_status.py mark \"<Company>\" [\"<Company>\" …] --source call --why \"<reason>\" [--recheck YYYY-MM-DD]` "
          "(sources: call, dart, ir, conference, edgar; default recheck in 90 days).",
          "- Undo: `python -X utf8 enrich_status.py unmark \"<Company>\" --source call`",
          "- Where a run stopped: `python -X utf8 enrich_status.py note US \"AV quota hit after 25 calls; 3 left for tomorrow\"`",
          "- A judgment for the user (an ambiguous new company, an unclear placement): `python -X utf8 enrich_status.py ask \"<subject>\" --question \"…\" [--label \"<source label>\"]`; "
          "after the answer: `python -X utf8 enrich_status.py resolve \"<subject>\" --answer \"…\"`",
          "- Parallel enrich agents never write these; they put it in their report and the coordinator records it.", ""]
    with open(BOARD_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def build_enrich_status(graph=None):
    """Compute the per-pipeline status, write graph/enrich_status.json, append to enrich_log.json."""
    if graph is None:
        graph = read_json(GRAPH_FILE, {"nodes": [], "edges": []})
    labels = graph_labels(graph)
    by_label, all_docs = load_documents()
    cache = {}

    # 1) Attribute every graph label to a pipeline through the file it resolves to.
    label_pipeline, label_file = {}, {}
    for label in labels:
        doc = resolve_label(label, by_label, all_docs, None, cache)
        label_pipeline[label] = pipeline_of(doc.path) if doc else "manual"
        label_file[label] = doc.path.replace("\\", "/") if doc else None

    enriched_on = applied_dates()

    # 2) Every document on disk, grouped by pipeline (supply_contracts files hold several filings).
    docs_by_pipeline = defaultdict(list)
    for doc in all_docs:
        docs_by_pipeline[pipeline_of(doc.path)].append(doc)

    pipelines = []
    for p in PIPELINES:
        pid = p["id"]
        docs = docs_by_pipeline.get(pid, [])
        files = sorted({d.path.replace("\\", "/") for d in docs})
        doc_labels = {lab for d in docs for lab in (d.labels or [])}
        in_graph = sorted(lab for lab in labels if label_pipeline.get(lab) == pid)
        # Source-date range: what period of company reporting this pipeline covers.
        dates = sorted(x for x in (label_date(l) for l in (doc_labels | set(in_graph))) if x)

        # Pending queue = fetched but not yet enriched (the authoritative "what is missing").
        pending_rows = read_json(p["pending"], []) if p["pending"] else []
        if p.get("pending_kind"):
            pending_rows = [r for r in pending_rows if r.get("kind") == p["pending_kind"]]
        pending = [{"company": r.get("company"), "label": r.get("label"), "file": r.get("file")} for r in pending_rows]
        pending_files = {r.get("file", "").replace("\\", "/") for r in pending_rows}
        # utility_filings.py queues the `_load` extract; the full text beside it carries the same label
        pending_labels = {r.get("label") for r in pending_rows}

        # Saved, not queued, but no data landed under its label — worth a look (a call that
        # was read and yielded nothing, or a label spelled differently in the patch).
        # EDGAR is special: edgar/done.json records WHY a filing yielded nothing (earnings
        # release only, personnel item, ...). Those are intentional skips, not gaps.
        edgar_why = {}
        if pid == "edgar":
            for r in read_json("edgar/done.json", []):
                edgar_why[r.get("file", "").replace("\\", "/")] = r.get("why", "")
        skipped = 0
        no_data, seen_labels = [], set()
        for d in docs:
            path = d.path.replace("\\", "/")
            if path in pending_files or not d.labels or d.labels[0] in seen_labels or d.labels[0] in pending_labels:
                continue
            if not any(lab in labels for lab in d.labels):
                why = edgar_why.get(path, "")
                if why and not why.startswith("10-"):     # "10-K customer concentration" etc. = real content
                    skipped += 1                          # anything else = intentional skip
                    continue
                seen_labels.add(d.labels[0])
                no_data.append({"label": d.labels[0], "file": path, "why": why or None})
        no_data.sort(key=lambda r: r["label"])

        # When did enrichment actually happen? Patch receipts, grouped by day.
        days = Counter(enriched_on[l] for l in in_graph if l in enriched_on)
        enriched_days = [{"day": d, "labels": n} for d, n in sorted(days.items())]

        row = {
            "id": pid, "name": p["name"], "command": p["command"], "source": p["source"],
            "files": len(files),
            "labels_on_disk": len(doc_labels),
            "in_graph": len(in_graph),
            "entries": sum(labels[l] for l in in_graph),
            "pending": pending,
            "no_data": no_data,
            "skipped": skipped,
            "source_range": [dates[0], dates[-1]] if dates else None,
            "last_fetch": max((mtime_day(f) for f in files), default=None),
            "last_enriched": max((enriched_on[l] for l in in_graph if l in enriched_on), default=None),
            "enriched_days": enriched_days,
            "last_sync": None,
            "extra": {},
        }

        # Pipeline-specific state: last sync date, waiting list, media gaps, run log.
        state = read_json(p["state"], {}) if p["state"] else {}
        if pid == "us":
            row["last_sync"] = yyyymmdd_to_iso(state.get("last_sync"))
            # Calls Alpha Vantage had not posted yet — unless the call was enriched another
            # way in the meantime (a paste, defeatbeta): then a label dated on/after the
            # report date already sits in the graph and the row is no longer "waiting".
            def still_waiting(w):
                report = (w.get("report_date") or "")
                for lab in in_graph:
                    if lab.startswith(w.get("name", "") + " ") and (label_date(lab) or "") >= report:
                        return False
                return True
            row["extra"]["waiting"] = [w for w in state.get("waiting", []) if still_waiting(w)]
            row["extra"]["saved_pairs"] = len(state.get("saved", []))
        elif pid == "dart":
            row["last_sync"] = yyyymmdd_to_iso(state.get("last_sync"))
            row["extra"]["filings_seen"] = len(state.get("seen", []))
        elif pid == "intl":
            row["extra"]["articles_seen"] = len(state.get("saved", []))
        elif pid == "tw":
            seen = state.get("seen", {})
            row["extra"]["no_media"] = sorted(k for k, v in seen.items() if v == "no_media")
            row["extra"]["conferences_seen"] = len(seen)
        elif pid in ("kind", "krcalls", "tdnet", "cninfo", "utility", "mops"):
            row["last_sync"] = state.get("last_sync")
            row["extra"]["runs"] = state.get("runs", [])[-5:]
        elif pid == "ir":
            runs = state.get("runs", [])
            row["extra"]["runs"] = runs[-5:]
            row["extra"]["feeds"] = len(read_json("ir/feeds.json", {}))
            row["last_sync"] = runs[-1]["at"][:10] if runs else None
        elif pid == "conference":
            runs = state.get("runs", [])
            row["extra"]["runs"] = runs[-5:]
            row["last_sync"] = runs[-1]["at"][:10] if runs else None
        elif pid == "edgar":
            done = read_json("edgar/done.json", [])
            dropped = read_json("edgar/dropped.json", [])
            row["extra"]["done"] = len(done)
            row["extra"]["dropped"] = len(dropped)
            row["extra"]["why"] = Counter(r.get("why", "").split("(")[0].strip() for r in done).most_common(6)
            # STATUS.md's first lines record when the queue was last generated.
            try:
                with open(os.path.join("edgar", "STATUS.md"), encoding="utf-8") as f:
                    m = re.search(r"on (\d{4}-\d\d-\d\d)", f.read(600))
                row["last_sync"] = m.group(1) if m else None
            except OSError:
                pass
        if row["last_sync"] is None:
            row["last_sync"] = row["last_fetch"]
        pipelines.append(row)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    board = market_board(graph, label_pipeline, label_file, pipelines, generated[:10])
    status = {
        "generated": generated,
        "labels_total": len(labels),
        "pipelines": pipelines,
        "history": append_log(pipelines),
        "board": board,
    }
    os.makedirs("graph", exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    write_board(board, pipelines, generated)

    print("enrich_status — %d labels attributed; wrote %s and %s" % (len(labels), STATUS_FILE, BOARD_FILE))
    for r in pipelines:
        print("  %-11s files %4d  in graph %4d  pending %3d  no-data %3d  sync %s  enriched %s  range %s"
              % (r["id"], r["files"], r["in_graph"], len(r["pending"]), len(r["no_data"]),
                 r["last_sync"] or "-", r["last_enriched"] or "-",
                 "%s..%s" % tuple(r["source_range"]) if r["source_range"] else "-"))
    print("  Run next:" if board["next_actions"] else "  Run next: nothing due")
    for i, a in enumerate(board["next_actions"], 1):
        print("    %d. %s — %s" % (i, a["command"], "; ".join(a["reasons"])[:200]))
    return status


def append_log(pipelines):
    """Keep enrich_log.json as a durable run record: one row per (day, pipeline) when counts change."""
    log = read_json(LOG_FILE, {"runs": []})
    today = datetime.now().strftime("%Y-%m-%d")
    last_by_pipeline = {}
    for r in log["runs"]:
        last_by_pipeline[r["pipeline"]] = r
    for p in pipelines:
        row = {"day": today, "pipeline": p["id"], "files": p["files"], "in_graph": p["in_graph"],
               "pending": len(p["pending"]), "last_sync": p["last_sync"], "source_range": p["source_range"]}
        prev = last_by_pipeline.get(p["id"])
        same = prev and all(prev.get(k) == row[k] for k in ("files", "in_graph", "pending", "last_sync"))
        if same:
            continue
        if prev and prev["day"] == today:
            log["runs"].remove(prev)      # several builds a day -> keep the latest counts for that day
        log["runs"].append(row)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    return log["runs"]


def record(args):
    """`mark` / `unmark` / `note`: the coordinator's hand-written facts, kept in enrich_marks.json."""
    data = load_marks()
    data["_rule"] = ("Facts no script can infer, recorded ONLY by the coordinator of an enrich run through "
                     "`python enrich_status.py mark / unmark / note / ask / resolve` (parallel agents report, never "
                     "write). A mark keeps a company out of the board's missing lists until its recheck date; a "
                     "question waits under 'Needs a decision' until the user answers it.")
    now = datetime.now()
    if args.cmd == "mark":
        recheck = args.recheck or (now + timedelta(days=90)).strftime("%Y-%m-%d")
        known = read_json("company_metadata.json", {})
        unknown = [c for c in args.companies if c not in known]
        if unknown:                          # a typo would create a mark that matches nothing
            print("not a company in company_metadata.json (use the canonical node name): %s" % ", ".join(unknown))
            args.companies = [c for c in args.companies if c in known]
        for company in args.companies:
            data["marks"] = [m for m in data["marks"] if (m["company"], m["source"]) != (company, args.source)]
            data["marks"].append({"company": company, "source": args.source, "status": "no_source",
                                  "why": args.why, "at": now.strftime("%Y-%m-%d"), "recheck": recheck})
        print("marked %d compan%s: %s no_source until %s" % (len(args.companies), "y" if len(args.companies) == 1 else "ies",
                                                            args.source, recheck))
    elif args.cmd == "unmark":
        before = len(data["marks"])
        data["marks"] = [m for m in data["marks"] if not (m["company"] in args.companies and m["source"] == args.source)]
        print("removed %d mark(s)" % (before - len(data["marks"])))
    elif args.cmd == "note":
        data["notes"].append({"at": now.strftime("%Y-%m-%d %H:%M"), "market": args.market, "text": args.text})
        print("note recorded")
    elif args.cmd == "ask":
        data["questions"] = [q for q in data["questions"] if q["subject"] != args.subject]
        data["questions"].append({"subject": args.subject, "question": args.question, "label": args.label,
                                  "at": now.strftime("%Y-%m-%d")})
        print("question recorded for the user: %s" % args.subject)
    elif args.cmd == "resolve":
        hit = [q for q in data["questions"] if q["subject"] == args.subject]
        data["questions"] = [q for q in data["questions"] if q["subject"] != args.subject]
        for q in hit:                         # keep the decision as history
            data["answered"].append(dict(q, answer=args.answer, answered=now.strftime("%Y-%m-%d")))
        print("resolved %d question(s) for %s" % (len(hit), args.subject))
    data["marks"].sort(key=lambda m: (m["source"], m["company"]))
    with open(MARKS_FILE, "w", encoding="utf-8") as f:
        json.dump({"_rule": data["_rule"], "marks": data["marks"], "notes": data["notes"],
                   "questions": data["questions"], "answered": data["answered"]}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Rebuild the enrichment status (no arguments), or record a fact for the board.")
    sub = ap.add_subparsers(dest="cmd")
    SOURCES = ["call", "dart", "ir", "conference", "edgar"]
    mk = sub.add_parser("mark", help="record that a source does not exist for these companies (until --recheck)")
    mk.add_argument("companies", nargs="+")
    mk.add_argument("--source", required=True, choices=SOURCES)
    mk.add_argument("--why", required=True, help="what was checked, e.g. 'no free transcript (AV, defeatbeta, Investing.com)'")
    mk.add_argument("--recheck", help="YYYY-MM-DD; default = 90 days from today")
    um = sub.add_parser("unmark", help="remove a mark")
    um.add_argument("companies", nargs="+")
    um.add_argument("--source", required=True, choices=SOURCES)
    nt = sub.add_parser("note", help="record where a run stopped / what the next run should know")
    nt.add_argument("market", choices=[m for m, _ in MARKETS] + ["all"])
    nt.add_argument("text")
    ak = sub.add_parser("ask", help="record a judgment for the user (shown under 'Needs a decision' until resolved)")
    ak.add_argument("subject", help="a company name or a short topic")
    ak.add_argument("--question", required=True)
    ak.add_argument("--label", help="the source label the question comes from")
    rs = sub.add_parser("resolve", help="close a question with the user's answer (kept as history)")
    rs.add_argument("subject")
    rs.add_argument("--answer", required=True)
    args = ap.parse_args()
    if args.cmd:
        record(args)
    build_enrich_status()
