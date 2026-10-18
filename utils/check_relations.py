"""Pre-flight check for relations/*.json — the non-AI business relationships (relations.py, user decision C,
2026-10-17). Run it on every relations file a run wrote or changed, BEFORE graph_build.py; fix until it prints
`RESULT: clean`. The relations-file twin of utils/check_patch.py.

Per file:
  * valid JSON shaped {"company": "<graph company>", "relations": [...]}; the company is a graph node (or a new
    node that already has its company_metadata.json entry); the file name is relations.relation_file_name(company)
  * ADD-only: every row in the committed copy (git HEAD) is still there, unchanged
Per row:
  * exactly the known keys; `from` == the file's company; relation is supplies | customer_of | partner;
    scope is "other" (an AI relationship goes into a chain through a patch, never here)
  * `to`: not the file's own company; spelled exactly like the graph node when it is one (naming rules);
    not one of the four semiconductor-fab contractors rule B keeps out (United Integrated Services, Acter,
    Marketech, Hanyang Eng)
  * SOURCE RULE: `source` is a saved file under transcripts/ whose text contains `quote` verbatim (whitespace
    runs may differ), or a public http(s) URL. A URL row is listed as a WARN every time (its quote cannot be
    checked offline: open the URL), and a row with a `figure` must cite a saved file (AGENTS.md: every figure
    comes from a document saved under transcripts/; save the page first, e.g. ir_pull.py / edgar_pull.py)
  * label ends with (MM-DD-YYYY) and that date equals `date`; `date` / `added` are YYYY-MM-DD, not in the future
  * English only in to / product / label / figure (the quote stays in the source's language, verbatim)
  * every number in `figure` appears in `quote`
  * no duplicate row; a row that duplicates an AI edge between the same two companies is flagged (WARN)

    python -X utf8 utils/check_relations.py                       every file in relations/
    python -X utf8 utils/check_relations.py relations/caterpillar.json [more files ...]

Exit code 1 when any ERROR or FAIL is found.
"""
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# FAB_CONTRACTORS: rule B (user, 2026-10-17) — the semiconductor-FAB contractors that stay excluded (never a node,
# never a relations counterparty); data-center and power-grid contractors are allowed. Defined once in relations.py.
from relations import FAB_CONTRACTORS, RELATION_TYPES, relation_file_name  # noqa: E402  (repo root is on sys.path)

REQUIRED_KEYS = {"from", "to", "relation", "product", "scope", "source", "quote", "label", "date", "added"}
OPTIONAL_KEYS = {"figure"}
ISO_DATE = re.compile(r"^\d{4}-\d\d-\d\d$")
LABEL_DATE = re.compile(r"\((\d\d)-(\d\d)-(\d{4})\)\s*$")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
CJK = re.compile(r"[가-힣一-鿿ぁ-ヿ]")                   # Hangul, kanji / hanzi, kana (as verify_graph.py)


def squash(name):
    """'SK Hynix' -> 'skhynix' — two spellings of one company squash to the same string."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def collapse(text):
    return re.sub(r"\s+", " ", text or "").strip()


def check_row(where, row, company, ctx, today):
    """Problems of one relations row: a list of (level, message)."""
    out = []
    say = lambda level, msg: out.append((level, f"{where}: {msg}"))      # noqa: E731
    if not isinstance(row, dict):
        say("ERROR", "a row must be an object")
        return out
    missing, unknown = REQUIRED_KEYS - set(row), set(row) - REQUIRED_KEYS - OPTIONAL_KEYS
    if missing:
        say("ERROR", f"missing keys {sorted(missing)}")
    if unknown:
        say("ERROR", f"unknown keys {sorted(unknown)} (allowed: {sorted(REQUIRED_KEYS | OPTIONAL_KEYS)})")
    if row.get("from") != company:
        say("ERROR", f"`from` {row.get('from')!r} must be the file's company {company!r}")
    if row.get("relation") not in RELATION_TYPES:
        say("ERROR", f"relation {row.get('relation')!r} must be supplies | customer_of | partner")
    if row.get("scope") != "other":
        say("ERROR", f"scope {row.get('scope')!r} must be \"other\" — an AI relationship goes into its chain "
                     f"through a patch (connects_to), never into relations/")

    to = str(row.get("to") or "").strip()
    if not to:
        say("ERROR", "`to` is empty")
    elif to == company:
        say("ERROR", "`to` is the file's own company")
    else:
        same = ctx["node_by_squash"].get(squash(to))
        if same and same != to:
            say("ERROR", f"`to` {to!r} is the graph node {same!r} spelled differently — use the node name")
        if squash(to) in {squash(c) for c in FAB_CONTRACTORS}:
            say("ERROR", f"`to` {to!r} is a semiconductor-fab contractor, excluded by rule B (2026-10-17)")
        if to in ctx["ai_pairs"].get(company, set()):
            say("WARN", f"an AI edge already links {company} and {to} — record here only a DIFFERENT, non-AI "
                        f"relationship between them")
    if not str(row.get("product") or "").strip():
        say("ERROR", "`product` is empty — name the specific product / service")

    for key in ("to", "product", "label", "figure"):
        if CJK.search(str(row.get(key) or "")):
            say("ERROR", f"`{key}` must be English (only `quote` keeps the source's language)")

    # Dates: the label's (MM-DD-YYYY) is the source document date; `date` repeats it as YYYY-MM-DD.
    for key in ("date", "added"):
        value = str(row.get(key) or "")
        if not ISO_DATE.match(value):
            say("ERROR", f"`{key}` {value!r} must be YYYY-MM-DD")
        elif value > today:
            say("ERROR", f"`{key}` {value} is in the future")
    m = LABEL_DATE.search(str(row.get("label") or ""))
    if not m:
        say("ERROR", f"label {row.get('label')!r} must end with the source date (MM-DD-YYYY) — enrich skill section 5")
    elif f"{m.group(3)}-{m.group(1)}-{m.group(2)}" != row.get("date"):
        say("ERROR", f"label date ({m.group(0).strip()}) != `date` {row.get('date')!r}")

    # SOURCE RULE: a saved transcript / filing with the quote in it, or a public URL. Never model memory.
    source, quote = str(row.get("source") or ""), str(row.get("quote") or "")
    if not quote.strip():
        say("ERROR", "`quote` is empty — copy the verbatim line that states the relationship")
    if source.startswith(("https://", "http://")):
        # Nothing to read offline, so the row is listed for a human check every time it is checked.
        say("WARN", f"URL source, quote not verifiable offline — open {source} and confirm the quote")
        if str(row.get("figure") or "").strip():
            say("ERROR", "a row with a `figure` must cite a saved file under transcripts/ (every figure comes "
                         "from a saved document) — save the page first (ir_pull.py / edgar_pull.py / "
                         "transcripts/non_transcript_sources/) or drop the figure")
    elif source.replace("\\", "/").startswith("transcripts/"):
        path = ctx["root"] / source
        if not path.is_file():
            say("ERROR", f"source file {source} does not exist")
        elif quote.strip():
            text = path.read_text(encoding="utf-8", errors="replace")
            if quote not in text and collapse(quote) not in collapse(text):
                say("FAIL", f"quote not found verbatim in {source}")
    else:
        say("ERROR", f"source {source!r} must be a file under transcripts/ or a public https:// URL")

    for number in NUMBER.findall(str(row.get("figure") or "")):
        if number not in quote:
            say("FAIL", f"figure number {number!r} is not in the quote (write numbers as the source states them)")
    return out


def check_file(rel_path, data, baseline, ctx, today):
    """Problems of one relations file (a list of (level, message)). `baseline` = the committed copy or None."""
    out = []
    if not isinstance(data, dict) or not isinstance(data.get("relations"), list) or not data.get("company"):
        return [("ERROR", f"{rel_path}: must be {{\"company\": \"<graph company>\", \"relations\": [...]}}")]
    company = data["company"]
    extra = set(data) - {"company", "relations"}
    if extra:
        out.append(("ERROR", f"{rel_path}: unknown top-level keys {sorted(extra)}"))
    if company not in ctx["nodes"]:
        if company in ctx["metadata"]:
            out.append(("WARN", f"{rel_path}: {company!r} is not a graph node yet (it has its metadata entry — "
                                f"a new node being added this run)"))
        else:
            out.append(("ERROR", f"{rel_path}: {company!r} is neither a graph node nor in company_metadata.json"))
    if os.path.basename(rel_path) != relation_file_name(company):
        out.append(("WARN", f"{rel_path}: the file for {company!r} should be named {relation_file_name(company)}"))

    seen = set()
    for i, row in enumerate(data["relations"]):
        where = f"{rel_path} relations[{i}]"
        out += check_row(where, row, company, ctx, today)
        if isinstance(row, dict):
            key = (row.get("to"), row.get("relation"), row.get("product"), row.get("label"))
            if key in seen:
                out.append(("ERROR", f"{where}: duplicate of an earlier row (same to, relation, product, label)"))
            seen.add(key)

    # ADD-only: nothing that was committed may disappear or change.
    if baseline is not None:
        rows_now = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in data["relations"]]
        for j, row in enumerate(baseline.get("relations", [])):
            if json.dumps(row, sort_keys=True, ensure_ascii=False) not in rows_now:
                out.append(("ERROR", f"{rel_path}: committed row {j} (to {row.get('to')!r}, {row.get('label')!r}) "
                                     f"was removed or edited — relations rows are ADD-only"))
        if baseline.get("company") != company:
            out.append(("ERROR", f"{rel_path}: company changed from {baseline.get('company')!r} to {company!r}"))
    return out


def committed_copy(rel_path):
    """The file as committed at git HEAD (parsed), or None when it is new / git is unavailable."""
    try:
        result = subprocess.run(["git", "show", f"HEAD:{rel_path}"], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8")
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def repo_context():
    """Graph nodes, metadata names and the AI edges, read once from the repo."""
    graph = json.load(open(ROOT / "graph" / "merged_graph.json", encoding="utf-8"))
    nodes = {n["id"] for n in graph["nodes"]}
    ai_pairs = {}
    for e in graph["edges"]:
        ai_pairs.setdefault(e["source"], set()).add(e["target"])
        ai_pairs.setdefault(e["target"], set()).add(e["source"])
    metadata = json.load(open(ROOT / "company_metadata.json", encoding="utf-8"))
    return {"root": ROOT, "nodes": nodes, "metadata": set(metadata), "ai_pairs": ai_pairs,
            "node_by_squash": {squash(n): n for n in nodes}}


def main(paths):
    sys.stdout.reconfigure(encoding="utf-8")
    if not paths:
        folder = ROOT / "relations"
        paths = sorted(str(p.relative_to(ROOT)) for p in folder.glob("*.json")) if folder.is_dir() else []
        if not paths:
            print("no relations files (relations/*.json) to check")
    ctx = repo_context()
    today = datetime.date.today().isoformat()
    problems = 0
    for path in paths:
        rel_path = Path(path).resolve().relative_to(ROOT).as_posix()
        print(f"== {rel_path}")
        try:
            data = json.load(open(ROOT / rel_path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  [ERROR] invalid JSON: {exc}")
            problems += 1
            continue
        found = check_file(rel_path, data, committed_copy(rel_path), ctx, today)
        for level, message in found:
            print(f"  [{level}] {message}")
            if level in ("ERROR", "FAIL"):
                problems += 1
        print(f"  checked {len(data.get('relations', []))} rows")
    print("RESULT:", "PROBLEMS FOUND" if problems else "clean (no ERROR / FAIL)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
