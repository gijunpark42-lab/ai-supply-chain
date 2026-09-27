---
name: enrich-rules-2026-09-26
description: "Enrich rules consolidated 2026-09-26 (user-ordered): capture = facts + company guidance + management views, never analyst opinion; IR releases important-only; market commands; ENRICH_STATUS.md board read first; SKILL.md §0-§8 wins over older notes"
metadata:
  node_type: memory
  type: feedback
---

On 2026-09-26 the user asked Claude to establish the enrich rules on its own: "팩트정보는 중요한데 누구 무슨
애널리스트의견이나 그건필요없고 회사의견 회사가이던스 CEO코멘트는중요함", update the status board in every enrich
cycle, and make the board say which enrich to run. Earlier the same day: articles / news articles are accepted
only when they are company IR press releases, and only the important ones.

**Where the rules live now:** `.claude/skills/enrich/SKILL.md` common rules §0-§8 (plus `references/markets.md`).
They win over older memory notes that disagree — e.g. the "screener slots only from transcripts and filings" line
in [[feedback-source-hierarchy]] (replaced by the slot table: 10-K/10-Q none, press release `guidance` only, 8-K only
when newest), the "News / research" label and "enrichment agent edits chain files" in [[feedback-integrity]], and
"Motley Fool first" in [[feedback_transcript_command]] (US calls: av.py, defeatbeta fallback).

**Why:** the rules had drifted apart across seven reference files (three verification models, three new-node
rules, a slot rule only in edgar.md), and the drift reached the data: financing terms and Chinese characters from IR
releases, same-date slot collisions, 10-K concentration facts that never reached the Exposure tab.

**How to apply:**
- Start every enrich run by reading `ENRICH_STATUS.md` (refresh: `python -X utf8 enrich_status.py`); bare `enrich`
  runs its Run next list; `enrich us` is daily and excludes SEC filings (`enrich edgar` weekly); `enrich korea` /
  `taiwan` / `japan` / `europe` / `china` exist.
- Only the coordinator records facts no script can infer: `enrich_status.py mark "<Co>" --source call --why …` /
  `note <market> "…"` → `enrich_marks.json`. Parallel agents report, never write it.
- Every patch passes `utils/check_patch.py` (edgar: `check_edgar_patch.py`) before `graph_build.py --sync`.
- New companies (user, same day: "승인은 내가 하는 게 아니라 클로드가 해야 함"): an enricher proposes one in its patch
  (`new_nodes` block: why + evidence); an independent Opus verifier approves with the JOB 3 checklist; the
  coordinator adds its metadata; every addition is reported. check_patch.py refuses unapproved / unregistered /
  removed-name / duplicate-name nodes. Moves, renames and deletions are still the user's.
- IR press releases may fill `guidance`, `next_catalyst` (new product / availability / production with a date),
  `backlog_or_b2b`, `supply_status` — never `revenue_growth` (user: "새제품같은거 뜰수도있는데 왜 가이던스만").
- Parallel by default: up to 20 enricher agents, fewer for small queues, split by company; only the coordinator
  writes chains/-adjacent shared state (metadata, queues, marks, verify_queue) and runs the build.
- The web app's Coverage tab became the "Status" tab: the same board, from graph/enrich_status.json → `board`.
- Ambiguity (user, same day: "애매한 거는 나한테 물어보게 하자 … 은행이나 이런 건 필요없으니깐"): the new-node verifier
  answers approve / reject-without-asking (banks, lenders, insurers, funds, governments, distributors, contractors,
  generic customers, divisions, products, do-not-add list) / ask the user (`"ask_user"`). Any judgment the rules do
  not settle → `enrich_status.py ask "<subject>" --question …` (board + web Status tab "Needs a decision"); the
  user's answer → `resolve … --answer …` (kept under `answered` in enrich_marks.json).
- Korean earnings calls still have no pipeline (decision pending with the user).
