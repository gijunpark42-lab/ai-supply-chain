"""i18n.py -- translations of the web site's data text (ko / zh = Simplified Chinese / ja).

Why this exists
---------------
The graph (chains/, graph/) is ENGLISH ONLY -- verify_graph.py and check_patch.py fail on any Korean / Chinese /
Japanese character, and English strings are used as keys all over the web app. So translations live beside the
data, never inside it: every displayed English string gets a short id = sha1(text)[:12], and each language keeps
one file  i18n/translations/<lang>.json  = {id: translated text}.  `build` then writes small per-bundle overlay
files into web/public/data/i18n/<lang>/<bundle>.json (+ company_names.json), and the web app shows the translation when the user picks that language (English when a string is not translated yet).

Commands
--------
    python i18n.py status                 # how many displayed strings are missing per language
    python i18n.py pending [--size 60000] # write the untranslated strings as chunk files to i18n/pending/
    python i18n.py merge <dir>            # merge translated chunk outputs (<dir>/out/<lang>/*.json) into translations
    python i18n.py build                  # write the web overlay files (run by graph_build.py --sync)
    python i18n.py validate <dir> [cNNN]  # check chunk outputs: ids, numbers, currencies, scripts

Translation itself is done by Claude agents (Sonnet or better) following i18n/BRIEF.md -- see the enrich skill,
"translate" step. Nothing here calls an API.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "web", "public", "data")      # the files the site displays (after sync-data.mjs)
I18N = os.path.join(ROOT, "i18n")
TRANS = os.path.join(I18N, "translations")
WEB_OUT = os.path.join(DATA, "i18n")                     # served as /data/i18n/<lang>/<bundle>.json
LANGS = ["ko", "zh", "ja"]

HAS_LETTER = re.compile(r"[A-Za-z]")
SKIP = re.compile(r"^(https?://|www\.)|^[A-Z0-9.\-]{1,8}$")      # URLs, tickers / short codes


def sid(text):
    """The id of a string: first 12 hex chars of SHA-1 over the UTF-8 text (the web app computes the same)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- extraction (what the site displays)
class Collector:
    def __init__(self):
        self.strings = {}          # id -> {"en": text, "bundles": set()}

    def add(self, text, bundle):
        if not isinstance(text, str):
            return
        t = text.strip()
        if not t or not HAS_LETTER.search(t) or SKIP.search(t):
            return
        rec = self.strings.setdefault(sid(text), {"en": text, "bundles": set()})
        rec["bundles"].add(bundle)

    def walk(self, obj, keys, bundle, list_keys=()):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys and isinstance(v, str):
                    self.add(v, bundle)
                elif k in list_keys and isinstance(v, list):
                    for x in v:
                        self.add(x, bundle)
                else:
                    self.walk(v, keys, bundle, list_keys)
        elif isinstance(obj, list):
            for v in obj:
                self.walk(v, keys, bundle, list_keys)


def load(name):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


GRAPH_KEYS = {"product", "sector", "sub_sector", "signal", "figure", "relationship",
              "units", "value", "type", "date_signed", "chain_focus"}
KEEP_EN_COLS = {"date", "company", "source", "sources", "ticker"}    # Timelines logic keys / resolver input
REPORT_SKIP_KEYS = {"company", "ticker", "source", "sources", "url", "urls", "as_of", "date",
                    "generated_at", "model", "label", "labels", "exchange"}


# Must match web/src/lib/signals.ts (DATE_RE and the split / length rules in buildTimeline()).
TIMELINE_DATE_RE = re.compile(
    r"\b(Q[1-4]\s*(?:FY\s*)?20\d\d|[12]H\s*20\d\d|H[12]\s*(?:FY\s*)?20\d\d|(?:early|mid|late|end of|exiting|through|by)"
    r"\s*(?:calendar |CY|fiscal |FY)?\s*20\d\d|CY20\d\d|FY20\d\d|20\d\d)\b", re.I)


def timeline_sentences(signal):
    """The sentences buildTimeline() can show: split after '.' or ';', 25-240 chars, containing a date."""
    out = []
    for part in re.split(r"(?<=[.;])\s+", signal):
        t = part.strip()
        if 25 <= len(t) <= 240 and TIMELINE_DATE_RE.search(t):
            out.append(t)
    return out


def extract():
    """Return {id: {"en", "bundles"}} for every displayed English string."""
    c = Collector()
    graph = load("merged_graph.json")
    c.walk(graph, GRAPH_KEYS, "graph", list_keys={"sectors"})
    # The company panel's "Product / Capacity Timeline" shows single SENTENCES cut out of signals
    # (web/src/lib/signals.ts buildTimeline) -- each sentence is looked up on its own, so add them too.
    for node in (graph or {}).get("nodes", []):
        for q in node.get("quarterly_data") or []:
            for sentence in timeline_sentences(q.get("signal") or ""):
                c.add(sentence, "graph")
    idx = load("chains/index.json")
    if idx:
        c.walk(idx, {"chain_focus", "title"}, "graph")
    chains_dir = os.path.join(DATA, "chains")
    if os.path.isdir(chains_dir):
        for f in sorted(os.listdir(chains_dir)):
            if f.endswith(".json") and f != "index.json":
                c.walk(load("chains/" + f), GRAPH_KEYS, "graph", list_keys={"sectors"})
    c.walk(load("company_metrics.json"),
           {"revenue_growth", "guidance", "backlog_or_b2b", "supply_status", "next_catalyst"}, "metrics")

    def walk_tl(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("name", "note", "title") and isinstance(v, str):
                    c.add(v, "timelines")
                elif k == "columns" and isinstance(v, list):
                    for col in v:
                        c.add(col, "timelines")
            if isinstance(o.get("columns"), list) and isinstance(o.get("rows"), list):
                cols = [str(x).strip().lower() for x in o["columns"]]
                for row in o["rows"]:
                    if isinstance(row, list):
                        for i, cell in enumerate(row):
                            if (cols[i] if i < len(cols) else "") not in KEEP_EN_COLS:
                                c.add(cell, "timelines")
            for k, v in o.items():
                if k != "rows":
                    walk_tl(v)
        elif isinstance(o, list):
            for v in o:
                walk_tl(v)

    walk_tl(load("timelines.bundle.json"))
    c.walk(load("capex_backlog.json"),
           {"label", "value", "delta", "detail", "title", "note", "display", "period", "metric", "growth",
            "signal", "footnote", "capex_q", "capex_year", "backlog"}, "capex")
    c.walk(load("exposure.json"), {"formula", "product", "sector", "text"}, "exposure")

    def walk_rep(o):
        if isinstance(o, dict):
            for k, v in o.items():
                c.add(k.replace("_", " "), "reportkeys")
                if k in REPORT_SKIP_KEYS:
                    continue
                if isinstance(v, str):
                    c.add(v, "reports")
                else:
                    walk_rep(v)
        elif isinstance(o, list):
            for v in o:
                if isinstance(v, str):
                    c.add(v, "reports")
                else:
                    walk_rep(v)

    rep = load("reports.bundle.json")
    if rep:
        walk_rep(rep)
    return {k: {"en": v["en"], "bundles": sorted(v["bundles"])} for k, v in c.strings.items()}


def load_trans(lang):
    p = os.path.join(TRANS, lang + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def save_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------- commands
def cmd_status(_):
    src = extract()
    print(f"displayed strings: {len(src)}")
    for lang in LANGS:
        tr = load_trans(lang)
        missing = [k for k in src if k not in tr]
        print(f"  {lang}: {len(src) - len(missing)} translated, {len(missing)} missing"
              f" ({sum(len(src[k]['en']) for k in missing)} chars)")


def cmd_pending(a):
    """Write every string missing in ANY language as chunks: i18n/pending/chunks/cNNN_p1.json {part-id: en}."""
    src = extract()
    have = {lang: load_trans(lang) for lang in LANGS}
    todo = [(k, v["en"]) for k, v in sorted(src.items(), key=lambda kv: kv[1]["en"])
            if any(k not in have[lang] for lang in LANGS)]
    pend = os.path.join(I18N, "pending")
    for f in glob.glob(os.path.join(pend, "chunks", "*.json")):
        os.remove(f)
    idmap, ci, part, cur = {}, 1, {}, 0

    def flush():
        nonlocal ci, part, cur
        if part:
            save_json(os.path.join(pend, "chunks", f"c{ci:03d}_p1.json"), part, indent=0)
            ci, part, cur = ci + 1, {}, 0

    for k, en in todo:
        pid = f"c{ci:03d}p1-{len(part) + 1:03d}"
        part[pid] = en
        idmap[pid] = k
        cur += len(en)
        if cur >= a.size:
            flush()
    flush()
    save_json(os.path.join(pend, "idmap.json"), idmap)
    print(f"{len(todo)} strings in {ci - 1} chunk(s) -> {pend}\\chunks (translate with i18n/BRIEF.md,"
          f" then `python i18n.py merge i18n/pending`)")


def cmd_merge(a):
    base = a.dir
    idmap = json.load(open(os.path.join(base, "idmap.json"), encoding="utf-8"))
    for lang in LANGS:
        tr = load_trans(lang)
        n = 0
        for f in sorted(glob.glob(os.path.join(base, "out", lang, "*.json"))):
            for pid, text in json.load(open(f, encoding="utf-8")).items():
                if pid in idmap and isinstance(text, str) and text.strip():
                    tr[idmap[pid]] = text
                    n += 1
        save_json(os.path.join(TRANS, lang + ".json"), tr, indent=0)
        print(f"{lang}: merged {n}, total {len(tr)}")


def cmd_build(_):
    """Per-bundle overlays {id: text} + company names, only for strings the site displays now."""
    src = extract()
    names_p = os.path.join(I18N, "company_names.json")
    for lang in LANGS:
        tr = load_trans(lang)
        bundles = {}
        for k, v in src.items():
            if k in tr:
                for b in v["bundles"]:
                    bundles.setdefault(b, {})[k] = tr[k]
        for f in glob.glob(os.path.join(WEB_OUT, lang, "*.json")):
            os.remove(f)
        for b, d in bundles.items():
            save_json(os.path.join(WEB_OUT, lang, b + ".json"), d)
    if os.path.exists(names_p):
        save_json(os.path.join(WEB_OUT, "company_names.json"), json.load(open(names_p, encoding="utf-8")))
    missing = {}
    for lang in LANGS:
        tr = load_trans(lang)                       # load each file ONCE (not once per string)
        missing[lang] = sum(1 for k in src if k not in tr)
    print("i18n overlay built; untranslated displayed strings: "
          + ", ".join(f"{l} {n}" for l, n in missing.items())
          + ("" if not any(missing.values()) else "  (run `python i18n.py pending` and translate)"))


NUM = re.compile(r"\d+(?:[.,]\d+)*")
CUR = re.compile(r"\b(?:KRW|USD|US\$|NT\$|JPY|EUR|CNY|RMB|HK\$|TWD|GBP|CHF|SGD|AUD|CAD)\b|[$€£¥₩]")
HANGUL = re.compile(r"[가-힣]")
KANA = re.compile(r"[぀-ヿ]")
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힣]")


def check_one(en, tr, lang):
    """Problems for one translated string (empty list = fine)."""
    probs = []
    if not isinstance(tr, str) or not tr.strip():
        return ["empty"]
    n_en, n_tr = NUM.findall(en), NUM.findall(tr)
    lost = [n for n in set(n_en) if n_tr.count(n) < n_en.count(n)]
    if lost:
        probs.append(f"numbers changed/lost {lost[:6]}")
    c_en, c_tr = CUR.findall(en), CUR.findall(tr)
    if any(c_tr.count(c) < c_en.count(c) for c in set(c_en)):
        probs.append("currency token changed")
    long_en = len(re.findall(r"[A-Za-z]{3,}", en)) >= 4
    if lang == "ko" and long_en and not HANGUL.search(tr):
        probs.append("not translated (no Hangul)")
    if lang in ("zh", "ja"):
        if HANGUL.search(tr):
            probs.append("contains Hangul")
        if long_en and not CJK.search(tr):
            probs.append("not translated (no CJK)")
    if lang == "zh" and KANA.search(tr):
        probs.append("contains Japanese kana")
    return probs


def cmd_validate(a):
    base = a.dir
    probs = 0
    pattern = (a.chunk + "_p*.json") if a.chunk else "*.json"     # one chunk (cNNN) or all of them
    files = sorted(glob.glob(os.path.join(base, "chunks", pattern)))
    if not files:
        # A wrong folder (e.g. Git Bash eating the backslash in i18n\pending -> "i18npending") used to report
        # "clean" because nothing was checked. Found 2026-10-06: 37 agents "validated" an empty folder.
        print(f"nothing checked: no chunk files match {os.path.join(base, 'chunks', pattern)} (wrong folder? use forward slashes)")
        probs += 1
    for f in files:
        part = os.path.basename(f)
        src = json.load(open(f, encoding="utf-8"))
        for lang in LANGS:
            p = os.path.join(base, "out", lang, part)
            if not os.path.exists(p):
                print(f"{part} {lang}: MISSING")
                probs += 1
                continue
            out = json.load(open(p, encoding="utf-8"))
            for k, en in src.items():
                for msg in (check_one(en, out.get(k), lang) if k in out else ["missing id"]):
                    print(f"{k} {lang}: {msg}")
                    probs += 1
    print("RESULT: clean" if not probs else f"RESULT: PROBLEMS ({probs})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("pending")
    p.add_argument("--size", type=int, default=60000, help="characters per chunk")
    p = sub.add_parser("merge")
    p.add_argument("dir")
    sub.add_parser("build")
    p = sub.add_parser("validate")
    p.add_argument("dir")
    p.add_argument("chunk", nargs="?", help="only this chunk, e.g. c007")
    a = ap.parse_args()
    {"status": cmd_status, "pending": cmd_pending, "merge": cmd_merge,
     "build": cmd_build, "validate": cmd_validate}[a.cmd](a)


if __name__ == "__main__":
    main()
