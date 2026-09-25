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

Two outputs:
  graph/enrich_status.json   GENERATED every build (never hand-edit) — read by web/ via `npm run sync`.
  enrich_log.json            APPEND-ONLY record at the repo root, committed. One row per (day, pipeline)
                             whenever the counts change, so the run history survives a fresh clone
                             (file mtimes and patch receipts do not).

Run by graph_build.py after the graph is built; can also be run alone:  python -X utf8 enrich_status.py
"""

import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

# verify_graph.py already knows how to turn a source label into the file it came from
# (header "# source label:", filename join, event-name match). Reuse it instead of
# re-implementing the matching rules here.
from verify_graph import load_documents, resolve_label

GRAPH_FILE = os.path.join("graph", "merged_graph.json")
STATUS_FILE = os.path.join("graph", "enrich_status.json")
LOG_FILE = "enrich_log.json"

# One entry per pipeline. `dirs` = the transcript folders the pipeline writes; a file's
# folder decides which pipeline it belongs to. Order = display order in the web app.
PIPELINES = [
    {"id": "us",         "name": "US earnings calls",          "command": "enrich us",
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


def build_enrich_status(graph=None):
    """Compute the per-pipeline status, write graph/enrich_status.json, append to enrich_log.json."""
    if graph is None:
        graph = read_json(GRAPH_FILE, {"nodes": [], "edges": []})
    labels = graph_labels(graph)
    by_label, all_docs = load_documents()
    cache = {}

    # 1) Attribute every graph label to a pipeline through the file it resolves to.
    label_pipeline = {}
    for label in labels:
        doc = resolve_label(label, by_label, all_docs, None, cache)
        label_pipeline[label] = pipeline_of(doc.path) if doc else "manual"

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
            if path in pending_files or not d.labels or d.labels[0] in seen_labels:
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

    status = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "labels_total": len(labels),
        "pipelines": pipelines,
        "history": append_log(pipelines),
    }
    os.makedirs("graph", exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=1)

    print("enrich_status — %d labels attributed; wrote %s" % (len(labels), STATUS_FILE))
    for r in pipelines:
        print("  %-11s files %4d  in graph %4d  pending %3d  no-data %3d  sync %s  enriched %s  range %s"
              % (r["id"], r["files"], r["in_graph"], len(r["pending"]), len(r["no_data"]),
                 r["last_sync"] or "-", r["last_enriched"] or "-",
                 "%s..%s" % tuple(r["source_range"]) if r["source_range"] else "-"))
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


if __name__ == "__main__":
    build_enrich_status()
