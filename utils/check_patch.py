"""Pre-flight check for ANY enrichment patch, BEFORE graph_build.py applies it to chains/.

The general version of utils/check_edgar_patch.py (which stays the stricter check for `enrich edgar`:
it only accepts the SEC filing itself as the source). Written 2026-09-26 when the enrich skill's common
rules made a pre-flight check mandatory for every source. Once an entry is in chains/, removing it takes
a direct chains/ edit (patches are ADD-only), so catching a problem here is much cheaper.

Per entry it runs the verify_graph.py checks (every number in figure/units/value is in the source, the
counterparty is named, English only — any Korean/Chinese/Japanese character fails, label format), plus:
  * the label resolves to a saved source file (declared in its `# source label:` header)
  * every player already exists in that chain and the locator matches — or it is a NEW node that carries an
    independent Claude verifier's approval in the patch's top-level `new_nodes` block (enrich skill JOB 3), has
    its company_metadata.json entry, sits on valid slugs, and is neither an existing node under another spelling
    nor a company removed in the 2026-09-05 cleanup / ruled out by the user
  * every edge target is a node in the chain or an existing edge; a new edge / reverse edge is flagged
  * keys, quarter/source == label, `topics` present and valid, slot/capex shape valid
  * SLOT RULES (enrich SKILL.md, section "Tags and screener slots"): which source may fill which slot,
    one entry per slot per patch, and no second entry with the same slot and the same date on the company
  * ONE FACT, ONE NODE: the same (label, signal) must not be written to two players
  * the same (quarter, signal) / (source, signal) is not already in the chain

    python -X utf8 utils/check_patch.py patches/nvidia_q3_2027.json [more patches ...]

Exit code 1 when any ERROR or verify FAIL is found. Fix until it prints `RESULT: clean`.
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

import verify_graph as vg  # noqa: E402
from taxonomy import iter_players, LAYER_SLUGS, DOMAIN_SLUGS  # noqa: E402

BY_LABEL, ALL_DOCS = vg.load_documents()
TOPICS = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob("timelines/*.json")}
SLOTS = {"revenue_growth", "guidance", "backlog_or_b2b", "supply_status", "next_catalyst"}
CAPEX_FIELDS = {"capex_q", "capex_year", "backlog", "signal"}
QD_KEYS = {"quarter", "signal", "figure", "topics"}
QD_OPTIONAL = {"slot", "capex", "counterparty", "counterparty_role"}
CT_KEYS = {"source", "signal", "units", "value", "date_signed", "type", "topics"}
METADATA = json.load(open("company_metadata.json", encoding="utf-8"))
COMPANIES = sorted(METADATA, key=len, reverse=True)
MERGED = json.load(open(os.path.join("graph", "merged_graph.json"), encoding="utf-8"))
NODE_QD = {n["id"]: n.get("quarterly_data", []) for n in MERGED["nodes"]}


def squash(name):
    """'SK Hynix' -> 'skhynix' — two spellings of one company squash to the same string."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


NODE_BY_SQUASH = {squash(n["id"]): n["id"] for n in MERGED["nodes"]}
# Companies that must not come back as nodes: every counterparty folded away in the 2026-09-05 cleanup
# (banks, display makers, EPC contractors, ...; utils/graph_cleanup_2026_09_05.fold_log.tsv) and the
# user's own rulings (enrich edgar: Core42, AES, Nanjing Casela are NOT to be added).
DO_NOT_ADD = {"Core42", "AES", "Nanjing Casela"}
_fold_log = os.path.join("utils", "graph_cleanup_2026_09_05.fold_log.tsv")
if os.path.exists(_fold_log):
    with open(_fold_log, encoding="utf-8") as f:
        next(f, None)                                           # header: chain owner role counterparty label
        DO_NOT_ADD |= {line.split("\t")[3] for line in f if line.count("\t") >= 4}
DO_NOT_ADD_SQUASHED = {squash(n): n for n in DO_NOT_ADD}

problems = 0


def say(level, msg):
    global problems
    if level in ("ERROR", "FAIL"):
        problems += 1
    print(f"  [{level}] {msg}")


def owner_of(label):
    """The company whose document this is: the longest company name the label starts with."""
    return next((c for c in COMPANIES if label.startswith(c + " ")), None)


def source_kind(label, doc_path):
    """What kind of source the label names — decides which screener slots it may fill."""
    if re.search(r" (10-K|10-Q) \(", label):
        return "10-K/10-Q"
    if " 8-K (" in label:
        return "8-K"
    if "DART supply contract" in label:
        return "DART supply contract"
    if " press release" in label:
        return "press release"
    if " IR presentation" in label:
        return "IR presentation"
    if doc_path and "_prelim_" in doc_path:
        return "DART preliminary results"
    return "call / conference / periodic report"


# Which slots each kind of source may fill (enrich SKILL.md, "Tags and screener slots").
ALLOWED_SLOTS = {
    "10-K/10-Q": set(),                              # never
    "8-K": SLOTS,                                    # + only when newer than every same-slot entry (checked below)
    "DART supply contract": {"backlog_or_b2b"},
    # what the release itself states: guidance / a dated product launch / a named order / capacity — never revenue
    "press release": {"guidance", "next_catalyst", "backlog_or_b2b", "supply_status"},
    "IR presentation": {"guidance", "next_catalyst", "backlog_or_b2b", "supply_status"},   # a company deck (kind.py)
    "DART preliminary results": {"revenue_growth"},
    "call / conference / periodic report": SLOTS,
}


def _iso(label):
    """'X Q2 FY2026 (08-14-2026)' -> '2026-08-14' (ISO, so strings compare by date)."""
    m = re.search(r"\((\d\d)-(\d\d)-(\d{4})\)\s*$", label or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else ""


def check_tags(where, entry, label, kind, company, seen_slots):
    topics = entry.get("topics")
    if not isinstance(topics, list):
        say("ERROR", f"{where}: `topics` missing (write [] when none)")
    else:
        bad = [t for t in topics if t not in TOPICS]
        if bad:
            say("ERROR", f"{where}: unknown topics {bad}; valid: {sorted(TOPICS)}")
    if "capex" in entry:
        cx = entry["capex"]
        if not isinstance(cx, dict) or cx.get("field") not in CAPEX_FIELDS:
            say("ERROR", f"{where}: invalid capex {cx!r}")
    slot = entry.get("slot")
    if "slot" in entry and slot is None:
        say("ERROR", f"{where}: `slot: null` — leave the key out when the entry fills no slot")
        return
    if slot is None:
        return
    if slot not in SLOTS:
        say("ERROR", f"{where}: invalid slot {slot!r}")
        return
    if slot not in ALLOWED_SLOTS[kind]:
        say("ERROR", f"{where}: source kind '{kind}' may not fill slot {slot!r} (allowed: {sorted(ALLOWED_SLOTS[kind]) or 'none'})")
    if (company, slot) in seen_slots:
        say("ERROR", f"{where}: slot {slot!r} already used by another entry of this patch — tag the ONE best entry")
    seen_slots.add((company, slot))
    day = _iso(label)
    for q in NODE_QD.get(company, []):
        if q.get("slot") != slot or q.get("quarter") == label:
            continue
        other = _iso(q.get("quarter", ""))
        if other == day:
            say("ERROR", f"{where}: {company} already has slot {slot!r} on the same date from {q['quarter']!r} "
                         f"(two same-date entries make the screener ambiguous)")
        elif kind == "8-K" and other > day:
            say("ERROR", f"{where}: an 8-K fills a slot only when newer than every same-slot entry; "
                         f"{q['quarter']!r} is newer")


_DOCS = {}


def docs_for(label):
    """Saved source file(s) a label refers to (cached)."""
    if label not in _DOCS:
        _DOCS[label] = vg.resolve_label_docs(label, BY_LABEL, ALL_DOCS)
    return _DOCS[label]


def sectors_of(chain):
    """Every (layer-or-domain slug, sector) pair the chain defines, including sectors with no players yet."""
    out = set()
    for groups, key in ((chain.get("flow", []), "layer"), (chain.get("domains", []), "domain")):
        for g in groups:
            for s in g.get("sectors", []):
                out.add((g.get(key), s.get("sector")))
    return out


def check_new_node(where, company, p, group, chain, new_nodes):
    """A player this chain does not have yet (enrich skill JOB 3). True = it may be created (a WARN
    line keeps it visible in the report); False = refused (ERROR lines say why)."""
    info = new_nodes.get(company) or {}
    if str(info.get("ask_user") or "").strip():
        say("ERROR", f"{where}: held for the user's decision ({info['ask_user']}) — take the player out of the patch, "
                     f"keep the deal on the filer's node with counterparty keys, and record it with "
                     f"`enrich_status.py ask` (skill JOB 3)")
        return False
    if not str(info.get("approved") or "").strip():
        say("ERROR", f"{where}: NEW node without an independent Claude approval — describe it in the patch's "
                     f"`new_nodes` block (why, evidence) and have a separate verifier set `approved` (skill JOB 3)")
        return False
    ok = True
    if company not in METADATA:
        say("ERROR", f"{where}: NEW node has no company_metadata.json entry — the coordinator adds it before applying")
        ok = False
    same = NODE_BY_SQUASH.get(squash(company))
    if same and same != company:
        say("ERROR", f"{where}: {company!r} is the existing node {same!r} spelled differently — use the canonical name")
        ok = False
    ruled = DO_NOT_ADD_SQUASHED.get(squash(company))
    if ruled:
        say("ERROR", f"{where}: {ruled!r} was removed in the 2026-09-05 cleanup or ruled out by the user — put the deal "
                     f"on the filer's quarterly_data with counterparty keys instead")
        ok = False
    if group not in LAYER_SLUGS | DOMAIN_SLUGS or not p.get("sector"):
        say("ERROR", f"{where}: NEW node needs a valid layer/domain slug + sector (got {group!r} / {p.get('sector')!r})")
        ok = False
    elif (group, p.get("sector")) not in sectors_of(chain):
        say("WARN", f"{where}: NEW node opens sector {group}/{p.get('sector')!r}, which this chain does not have yet")
    if ok:
        kind = "an existing company, new in this chain" if same == company else "a new company"
        say("WARN", f"{where}: NEW placement ({kind}) — approved: {info['approved']}")
    return ok


def verify(where, label, fields, counterparty=None):
    """verify_graph's per-entry check, against the entry's OWN label (a patch that mixes
    several sources is already an ERROR, but each entry is still checked against its file)."""
    docs = docs_for(label)
    verdict, issues, detail = vg.check_entry(label, docs, fields, counterparty)
    level = {"fail": "FAIL", "warn": "WARN"}.get(verdict)
    if level:
        extra = {k: v for k, v in detail.items() if k.startswith("numbers_") or k == "counterparty"}
        say(level, f"{where}: verify {verdict} {issues} {extra}")


def check(patch_path):
    print(f"== {patch_path}")
    try:
        patch = json.load(open(patch_path, encoding="utf-8"))
    except Exception as exc:
        say("ERROR", f"invalid JSON: {exc}")
        return
    label = patch.get("source", "")
    docs = docs_for(label)
    if not docs:
        say("ERROR", f"label {label!r} resolves to no saved source file (save it with a `# source label:` header)")
        return
    if label not in BY_LABEL:
        say("WARN", f"label {label!r} is found only by file name — add a `# source label:` header to {docs[0].path}")
    owner = owner_of(label)
    if owner is None:
        say("WARN", f"label {label!r} does not start with a canonical company name from company_metadata.json")
    kind = source_kind(label, docs[0].path)
    new_nodes = patch.get("new_nodes") or {}
    created = set()
    seen_slots, facts = set(), {}
    n_qd = n_ct = 0
    for chain_rel, body in (patch.get("chains") or {}).items():
        chain_path = os.path.join("chains", chain_rel)
        if not os.path.exists(chain_path):
            say("ERROR", f"chain file not found: {chain_rel}")
            continue
        chain = json.load(open(chain_path, encoding="utf-8"))
        placements = {}
        for player, group_slug, gkind, sector, sub in iter_players(chain):
            placements.setdefault(player["company"], []).append((gkind, group_slug, sector, sub, player))
        for p in body.get("players", []):
            company = p.get("company")
            where = f"{chain_rel} :: {company}"
            group = p["layer"] if "layer" in p else p.get("domain")
            if company not in placements:
                created.add(company)                     # a player names it, approved or not
                if not check_new_node(where, company, p, group, chain, new_nodes):
                    continue
                node = {"company": company, "quarterly_data": [], "connects_to": []}   # apply_patches creates it
            else:
                spots = placements[company]
                match = [s for s in spots if s[1] == group and s[2] == p.get("sector") and s[3] == p.get("sub_sector")]
                if not match:
                    say("WARN", f"{where}: locator {group}/{p.get('sector')}/{p.get('sub_sector')} matches none of "
                                f"{[(s[1], s[2], s[3]) for s in spots]} (merge will use the first placement)")
                # same rule as apply_patches.find_player: exact product, then an existing edge to a patch target, then first
                cands = match or spots
                targets = {e.get("company") for e in p.get("connects_to", [])}
                node = (next((s[4] for s in cands if s[4].get("product") == p.get("product")), None)
                        or next((s[4] for s in cands if any(x.get("company") in targets for x in s[4].get("connects_to", []))), None)
                        or cands[0][4])
            have_qd = {(q.get("quarter"), q.get("signal")) for q in node.get("quarterly_data", [])}
            for i, q in enumerate(p.get("quarterly_data", [])):
                n_qd += 1
                w = f"{where} qd[{i}]"
                if set(q) - QD_KEYS - QD_OPTIONAL or not QD_KEYS <= set(q):
                    say("ERROR", f"{w}: keys {sorted(q)} (need {sorted(QD_KEYS)} [+ {sorted(QD_OPTIONAL)}])")
                if q.get("quarter") != label:
                    say("ERROR", f"{w}: quarter {q.get('quarter')!r} != patch label — one source per patch "
                                 f"(graph_build verifies only the patch label, so other labels would go unchecked)")
                if (q.get("quarter"), q.get("signal")) in have_qd:
                    say("WARN", f"{w}: already in chain (would be skipped)")
                fact = (q.get("quarter"), q.get("signal"))
                if fact in facts and facts[fact] != where:
                    say("ERROR", f"{w}: the same fact is also written to {facts[fact]} — one fact, one node")
                facts.setdefault(fact, where)
                own = q.get("quarter") or label
                check_tags(w, q, own, source_kind(own, (docs_for(own) or docs)[0].path), company, seen_slots)
                verify(w, own, q)
            edges = {e.get("company"): e for e in node.get("connects_to", [])}
            for e in p.get("connects_to", []):
                target = e.get("company")
                w = f"{where} -> {target}"
                if target not in placements and target not in edges:
                    say("ERROR", f"{w}: target is neither a node in this chain nor an existing edge of this player")
                    continue
                if target not in edges:
                    reverse = any(x.get("company") == company for s in placements[target] for x in s[4].get("connects_to", []))
                    if reverse:
                        say("ERROR", f"{w}: NEW edge but the REVERSE edge already exists — check which one the fact describes")
                    else:
                        say("WARN", f"{w}: NEW edge (confirm the source states the relationship explicitly)")
                have_ct = {(c.get("source"), c.get("signal")) for c in edges.get(target, {}).get("contracts", [])}
                counterparty = target if company == owner else company
                for i, c in enumerate(e.get("contracts", [])):
                    n_ct += 1
                    wc = f"{w} contract[{i}]"
                    if not CT_KEYS <= set(c):
                        say("ERROR", f"{wc}: missing keys {sorted(CT_KEYS - set(c))}")
                    if c.get("source") != label:
                        say("ERROR", f"{wc}: source {c.get('source')!r} != patch label — one source per patch")
                    if (c.get("source"), c.get("signal")) in have_ct:
                        say("WARN", f"{wc}: already in chain (would be skipped)")
                    if "slot" in c:
                        say("ERROR", f"{wc}: contracts carry no `slot` (only quarterly_data entries fill the screener)")
                    own = c.get("source") or label
                    check_tags(wc, {k: v for k, v in c.items() if k != "slot"}, own, kind, company, seen_slots)
                    verify(wc, own, c, counterparty)
    for company in sorted(set(new_nodes) - created):
        say("WARN", f"`new_nodes` lists {company!r}, but no player in the patch creates it")
    print(f"  checked {n_qd} quarterly_data + {n_ct} contracts  (source kind: {kind})")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        check(path)
    print("RESULT:", "PROBLEMS FOUND" if problems else "clean (no ERROR / FAIL)")
    sys.exit(1 if problems else 0)
