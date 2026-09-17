# HANDOFF — where the project stands and what to do next

Shared progress record for every agent working in this repo (Claude Code, Codex, ...).
Read `AGENTS.md` first for the load order and the hard rules. This file answers three questions:
**what is done, what is in flight, what comes next.** Append to the session log at the end of every
session; edit the "Current state" and "Next up" sections in place so they stay true.

Last full update: **2026-09-12** (Codex UI session; original Claude handoff history preserved below).

---

## 1. What this project is (one paragraph)

A graph of the AI / semiconductor supply chain. 25 chain files under `chains/{accelerators,components,
manufacturing}/` (one per investment-significant product GENERATION, e.g. `nvidia_vera_rubin`, `nvda_b200`,
`tpu_v8t`), merged by exact company name into `graph/merged_graph.json` (352 nodes / 1,359 edges on
2026-09-12). Every node carries `quarterly_data` and every edge carries `contracts`, each entry sourced to a
transcript or filing saved under `transcripts/` with a canonical label like `NVIDIA Q2 FY2027 (08-27-2026)`.
The user curates the STRUCTURE (companies, layers, edges); agents do ADD-only ENRICHMENT from transcripts.
A Next.js app in `web/` (live on Vercel, project `reticulum-ai`, domain gijun42.com) renders it: Graph,
Chain 2D, Generations, Timelines, Screener, Capex, Coverage, Exposure, Ask, Semi Bot tabs.

## 2. The pipelines (how transcripts get in)

| Command | Script | Region / source | Queue file | Status 2026-09-12 |
|---|---|---|---|---|
| `enrich us` | `av.py sync / pending / done` | US calls via Alpha Vantage (25 req/day). Fallback: `utils/defeatbeta_fetch.py "<Name>" <TICKER>` (no quota) | `av/pending.json` | empty |
| `enrich dart` | `dart.py sync / pending / done` | Korean 정기보고서 / 잠정실적 / 공급계약 via DART | `dart/pending.json` | empty |
| `enrich intl` | `investing.py sync / pending / done` | Taiwan/Japan/Europe/HK English calls via Investing.com | `investing/pending.json` (kind=transcript) | empty |
| `enrich tw` | `tw.py sync / fetch / transcribe / done` | Taiwan Chinese-language 法說會 → yt-dlp → faster-whisper | `tw/pending.json` | empty |
| `enrich edgar` | `edgar_pull.py [--tickers A,B] [--force]` (pull) / `queue` / `done [--with-dropped]` | SEC 8-K / 10-K / 10-Q whole filings | `edgar/pending.json` | empty (round 3b pending, see §4) |
| `enrich conference` | `investing.py conferences / done --kind conference` | Investor-conference fireside chats, all listed names | `investing/pending.json` (kind=conference) | **84 rows waiting, none enriched** |
| `Transcript:<company>` / pasted text / URL | manual | user-supplied full transcript | — | — |

Each pipeline's procedure is in `.claude/skills/enrich/references/<pipeline>.md`. The shared patch format,
JOB 1–5, the label format and the build+verify step are in `.claude/skills/enrich/SKILL.md`.

Per-pipeline health (last sync, source date range, pending, files with no data) is regenerated into
`graph/enrich_status.json` by `enrich_status.py` on every build and shown on the Coverage tab. The
append-only history is `enrich_log.json` (commit it).

## 3. Current state (edit in place)

- **Git:** `main`, UI release `a26a812` committed and pushed on 2026-09-12, based on `0993d57`. User explicitly
  authorized immediate deployment in this session, including the necessary commit/push. Completion notes
  are recorded in a follow-up documentation commit. The standing no-auto-commit preference still applies
  to future sessions.
- **Graph:** 352 nodes, 1,377 edges (2026-09-16 evening: conference run 2 + SK Telecom node, onsemi→Lite-On removed).
- **Coverage by pipeline (from `enrich_log.json`, 2026-09-11):** edgar 1,012 files / 432 in graph;
  dart 48/48; intl 30/29; tw 17/17; conference 93 files / 89 in graph / 0 pending / 4 no-data (2026-09-16); manual 244/244.
- **Web app:** live; 2026-09-12 UI refresh in `web/src/app/{page.tsx,workspace.css}` and
  `web/src/components/{Sidebar.tsx,SearchBox.tsx}`: research-view headings, graph summary, scrollable
  keyboard-operated tab strip, mobile filter focus management, accessible sidebar sections/search clear,
  loading retry and empty-filter recovery. Connection count now reads immutable source edges instead of
  the force renderer's mutated links. Deploy = push to main, Vercel Root Dir = `web`.
  Verification artifacts: `C:\Users\calif\Documents\Codex\2026-09-12\earnings-ui-review\`.
  UI release `a26a812` is live on https://gijun42.com: Vercel deployment
  `dpl_7cgbLTAkTqPEXkSjfM2WehPDaur2` (`reticulum-kh7fd65v2-gijun42.vercel.app`), Ready.
  Live desktop/phone verification passed at 2026-09-12 14:39 PDT; the complete served graph matches the
  unchanged local JSON after parsing (Windows CRLF versus Linux LF is the only raw-byte difference).
- **Ask tab:** answered by a LOCAL Claude runner (`local-ask/`) behind a Cloudflare tunnel. `ask 실행` starts it
  (`node local-ask/up.mjs`), `ask 종료` stops it. No Gemini, no Anthropic API (removed in 3bfb0dc).
  If the runner is down the tab falls back after ~3 min. Codex cannot run this engine (it shells out to `claude -p`).
- **Memory snapshot:** `docs/memory/` = copy of Claude's memory dir taken 2026-09-12. `docs/memory/MEMORY.md`
  is the index. `project_state.md` there is an 86 KB enrichment history; open it only when you need a
  specific company's past enrichment.

## 4. Next up (ordered; edit in place)

1. **Conferences: done through 2026-09-15.** Investing.com has almost no tech-conference transcripts before late
   July 2026 (a 285-page walk back to 05-14 found only 9), so the only future work is NEW conferences:
   `C:/Users/calif/AppData/Local/Python/bin/python.exe -X utf8 investing.py conferences` (bare `python` lacks
   `curl_cffi`) → enrich → verify → one build → `investing.py done --kind conference`.
   Open structure questions for the USER: Terafab (KLA's new customer; not a node — fold into Tesla/SpaceX?),
   STMicro→SpaceX (Starlink ~90% share, satellite chips), Sanmina/Wiwynn as AMD Helios rack partners (list-named).
1b. **US 2026 earnings-call backlog — 202 calls downloaded, NOT enriched (user will trigger).**
   List: `docs/US_ENRICH_BACKLOG.md`; queue: `av/pending.json` (gitignored — rebuild from the list on another machine).
   `enrich us` processes them (no `slot` on entries older than the company's latest call). Details:
   `docs/memory/us_backlog_2026.md`.
2. **EDGAR round 3b — "read ALL recovered tables", user scheduled it for the week of 2026-09-14.**
   Prep is finished: `transcripts/edgar/` was re-pulled 137/137 tickers (2026-09-11 night), the 5 old
   verify fails pass again. Durable archive: `C:\Users\calif\edgar_round3b\` (ledger `R3_PROGRESS.md`,
   briefs `AGENT_BRIEF_R3B.md` + `VERIFIER_BRIEF.md`, `delta_rows_r3b.json` = 437 files / 9.7 MB of unread
   delta text, `r3b_image_pages.json`, `r3b_inscope_loss.json`).
   Resume: `python -X utf8 utils/edgar_batches.py 26 <archive>/delta_rows_r3b.json`
   → enricher + verifier per batch (patches named `edgar_<stem>_r3b.json`) → one `graph_build.py --sync`
   → full `verify_graph.py`. Option A was chosen: read every table, do NOT narrow to "in-scope" tables.
   Before batching, consider adding "bookings" / region words to `TABLE_KEEP_RE` in `edgar_pull.py` and a
   no-token re-pull (Kulicke & Soffa bookings table, TE Connectivity region×segment table were still dropped).
   Full context: `docs/memory/edgar_enrichment_2026_09_10.md` and `.claude/skills/enrich/references/edgar.md`.
3. **Routine syncs** whenever the user says `enrich` / `enrich us` / `enrich dart` / `enrich intl` / `enrich tw`:
   sync → pending → enrich → build → done. Bare `enrich` means "use the API pipelines"; do not ask which source.
4. **Open curation items for the USER (do not do these unprompted):** logos for the 38 US nodes added
   2026-09-10 (`docs/memory/logo_fetching.md`); Carrier could also sit in Heat Exchanger / CDU; GE Vernova has no
   gas-turbine node (Power-segment facts were dropped); pre-existing GE Vernova → AEP edge; Eaton / Eversource
   call-label dates differ from the real call dates.
5. **Rejected / do not re-propose:** news pipelines or knowledge-based edges (`feedback_transcript_only.md`),
   a Quant tab in the web app, turning off the Vercel plugin, adding Core42 / AES / Nanjing Casela as nodes,
   auto-committing, GitHub Actions scheduler (not until the core loop is declared solid by the user).

## 5. Standing decisions and gotchas (the ones that bite)

- **Lost-update race:** several agents enrich in parallel and many companies share one chain file. Never
  read-modify-write `chains/`. Patches only. A structural edit (move/rename/delete) that must touch `chains/`
  needs a HEAD-vs-worktree audit right after (`docs/memory/concurrent_job_race.md`).
- **Label prefix == node name.** `av.py` / `investing.py` decide "already enriched?" by matching the label's
  company prefix to the node name. A mismatch (`Arm` vs `Arm Holdings`) re-pulls the company every sync.
- **Alpha Vantage keys transcripts by FISCAL quarter** and its calendar returns only future dates. Never fall
  back to a calendar-quarter guess when the graph already has history for that company (Flex, Arm traps).
- **Call transcripts drop the zero in "$X.0Y"** (Vicor "$1.4" = filed $1.04). Cross-check per-share figures
  against the same company's 8-K when both exist.
- **Multi-node companies in one chain** (NVIDIA in two sectors of `foundry.json`): write a signal to ONE
  placement, not every player matching the name, or the merged node shows it twice.
- **Edge rule for new edges:** the counterparty must be NAMED by management (not an analyst) AND already be
  a node in that chain file. "Collaboration" partnerships are not edges.
- **Contract placement:** a contract goes on an existing edge only if the fact matches that edge's relationship
  AND direction. Company-wide facts go on the placement that holds the company's call entries.
- **verify_graph false alarms:** numbers spelled in words ("two and a half gigawatts"), sums/deltas you
  computed. Say so in the report instead of "fixing" them.
- **Renames** are an 8-step structural procedure (chains + labels + metadata + transcript headers + logos +
  edgar rows + rebuild + verify). `docs/memory/naming_rules.md` has the checklist and a worked example.
- **Skeleton builds** (new chain file) write `chains/` directly (new file, no collision) and must be checked
  against `docs/memory/common_fixes.md` (fake sub-brands, "AWS" → "Amazon", "Meta AI" → "Meta", ...).
- **The user's style:** Korean, short, casual; answers like "어", "어 그러자" mean yes. Report the call date
  before enriching. End reports with the commit command, never run it.

## 6. Useful commands

```powershell
# PowerShell (python is not on PATH)
cd "C:\Users\calif\Desktop\earnings-ai"
& "C:\Users\calif\AppData\Local\Python\bin\python.exe" graph_build.py --sync
& "C:\Users\calif\AppData\Local\Python\bin\python.exe" -X utf8 verify_graph.py --label "NVIDIA Q2 FY2027 (08-27-2026)"
& "C:\Users\calif\AppData\Local\Python\bin\python.exe" av.py sync          # then pending / done
& "C:\Users\calif\AppData\Local\Python\bin\python.exe" investing.py conferences
& "C:\Users\calif\AppData\Local\Python\bin\python.exe" -X utf8 utils/show_filing.py transcripts/edgar/<file> 1   # page number is positional
& "C:\Users\calif\AppData\Local\Python\bin\python.exe" -X utf8 utils/check_edgar_patch.py patches/<patch>.json
cat graph/hubs.txt        # full hub list (the build prints only what changed)
```

Suggested commit after an enrichment run (only when the user says commit):

```
git add chains patches graph web/public transcripts enrich_log.json <queue files> docs/HANDOFF.md
git commit -m "<what was enriched>"
```

---

## 7. Session log (append-only, newest at the bottom)

Every session ends with one entry here, whichever agent worked (Claude or Codex). Format and the
full recording rules are in `AGENTS.md` → "Recording your progress". Short version:
`- **YYYY-MM-DD (Agent)** — asked / done (counts, verify result) / decisions / left open (exact resume point) / uncommitted yes-no`.
Also refresh §3 and §4 above, and `docs/memory/` if a rule or preference changed.

- **2026-09-12 (Claude)** — Handoff created for Codex: `AGENTS.md`, this file, `docs/memory/` snapshot of
  Claude's memory dir. No data changed. Working tree otherwise clean at c504d27. Open work unchanged:
  conference queue (84), EDGAR round 3b (next week), routine syncs.

- **2026-09-12 (Codex, Astra xhigh)** — Asked: improve the Earnings AI website UI with a dedicated agent,
  then deploy immediately and record everything so Claude can resume. Done: refreshed research navigation,
  graph overview, native keyboard-accessible filter sections, mobile drawer focus trap/Escape/return focus,
  search shortcut and keyboard clear, load retry, and empty-filter recovery in the four frontend files above.
  Fixed the displayed connection count falling to zero after toggling filters: the 3D library mutates
  visual-link endpoints into objects, so the UI now counts the unchanged `graph.edges` source IDs.
  Validation: TypeScript `--noEmit --incremental false` passes; headless browser verification passes all
  12 check groups with 0 client exceptions, including all nine research views, 1440px desktop and 390px
  phone screenshots, count recovery, keyboard navigation and simulated load failure/retry. Scripts and
  screenshots are saved in the artifact folder above. No chains, graph, web/public data, transcripts,
  pipeline queues, analytics or external service settings were changed. Local builds invoke the Next.js
  binary directly to avoid `prebuild` data sync. Decisions: user required Astra + extra-high effort and
  explicitly authorized immediate deployment; preserve the standing no-auto-commit rule for later work.
  Left open at this checkpoint: finish production build, commit/push the UI release, verify live site,
  and append completion here. Uncommitted: yes (this release only; checkout was clean at start).

- **2026-09-12 (Codex, Astra xhigh — UI release complete)** — Done: optimized Next.js production build
  passed (compile, types, 5 static pages); the 12 browser check groups also passed against the compiled
  production bundle with 0 client exceptions. Committed/pushed release `a26a812` to `origin/main`;
  Vercel completed the production deployment in 34 seconds and aliased it to https://gijun42.com.
  Deployment: `dpl_7cgbLTAkTqPEXkSjfM2WehPDaur2`, URL
  `https://reticulum-kh7fd65v2-gijun42.vercel.app`, status Ready. Live verification at 14:39 PDT passed:
  HTTP 200, new UI, desktop graph, keyboard tabs, 390px phone without horizontal page overflow,
  mobile filter open/Escape, and 0 client exceptions. The complete served graph deep-equals the original
  local graph (352 companies / 1,359 connections); normalized SHA-256
  `11480cdf040a5150410c0c92e5e3003098d216bab08114bcfe656887ff7b1972`.
  Artifacts include `production-desktop.png`, `production-mobile.png`, `production-verification.json`,
  and repeatable verification scripts in the folder recorded in §3. Local verification servers stopped.
  No pipelines, analytics, generated snapshots, environment variables or trading controls changed.
  Git's automatic housekeeping reported permission warnings for old `.git/worktrees/*` registrations;
  the commit/push succeeded, and no manual cleanup was attempted. Left open: no UI release work;
  original conference/EDGAR/routine queues in §4 remain untouched. This completion record is included
  in a follow-up documentation commit/push so Claude and other checkouts receive it.

- **2026-09-12 (Claude)** — Asked: free API for basic valuation metrics (P/E, Fwd P/E, P/B ...) since the
  app only showed price. Done: `web/src/app/api/fundamentals/route.ts` (Yahoo quoteSummary via cookie+crumb
  handshake, module-level session cache, 60 s fetch revalidate, no key, zero LLM cost) + `Fundamentals.tsx`
  strip (P/E, Fwd P/E, PEG, P/B, P/S, EV/EBITDA, ROE, rev growth, GM, OPM, div, analyst target) mounted in
  `NodePanel` under the chart for every node with a ticker (US and non-US). Verified: tsc clean, `next build`
  ok, route returns data for NVDA / 000660.KS / 2330.TW / 6857.T. Decisions: Alpha Vantage OVERVIEW rejected
  (US-only, 25/day shared with transcript sync). Known gaps: some KR names return null trailing P/E and P/B;
  ADR P/B can be broken (ASML) — prefer the home-exchange ticker. Follow-up same day: user wants LIVE
  refresh → `Fundamentals` and `LiveQuote` now poll every 30 s while the panel is open; `/api/quote` and
  `/api/fundamentals` server cache cut to 30 s (was 10 min / 60 s). Then diversified by market
  (`web/src/lib/fundamentals.ts`): Korea → Naver Finance mobile JSON (PER, 추정PER=forward, PBR, EPS,
  target), Japan → Yahoo Finance Japan page JSON (PER 会社予想 = guidance-based forward, PBR, ROE), Taiwan →
  TWSE/TPEx official open-data tables (PER/PBR/yield), everything else + gap-fill → Yahoo Finance; strip
  shows `sources`. Taiwan OTC names stored as ".TW" (8299, 6488, 3105, 5274, 3529...) are ".TWO" on Yahoo —
  both `/api/quote` (price was silently empty for them before) and fundamentals now retry ".TWO".
  ALSO: user asked to merge Samsung Foundry into Samsung (same 005930.KS). New tool
  `utils/merge_company.py --from "Samsung Foundry" --into "Samsung"` (dry-run first): 2 chain files,
  2 players + 25 edge targets renamed, 1 duplicate edge collapsed, 1 self-loop kept in file (1 contract;
  graph_build skips self-loops), metadata entry dropped, screener baseline block folded. Graph 352→351 nodes,
  1,359→1,357 edges; verify_graph.py output byte-identical to before. naming_rules.md (docs + memory) updated.
  Uncommitted: yes (not deployed). Note: unrelated uncommitted edits by another session were present
  (CLAUDE.md, AGENTS.md, local-ask/*, ask-server skill) — not touched.

- **2026-09-16 (Claude)** — Asked: `enrich conference` on all 84 queued fireside chats, multi-agent in parallel,
  then a 20-agent verify pass. Done: 56 companies split into 20 batches (one company's conferences together);
  20 enrichers wrote 81 patches (Dell / Seagate / NVIDIA Six Five Summit had no supply-chain content → no patch);
  coordinator rewrote 25 flat chain keys to the nested `chains/<group>/<file>.json` paths (the batch briefs printed
  them flat — `apply_patches.py` aborts on a missing path); 20 adversarial verifiers then edited ~80 entries and
  deleted ~10 (cross-transcript contamination, moderator numbers credited to management, false "first disclosure"
  framing, invented strings, one `value` holding a market estimate). Dry-run clean, then ONE `graph_build.py --sync`:
  +387 quarterly_data, +37 contracts, +19 edges. `verify_graph` on the 424 conference entries: 294 pass /
  130 unchecked / 0 fail / 0 warn. User ruling mid-run: **xAI is under SpaceX** → `utils/merge_company.py --from xAI
  --into SpaceX` (graph 351 nodes / 1,376 edges). `investing.py done --kind conference` → queue 0 (needs the
  `AppData/Local/Python` interpreter). Memory: `conference_enrichment.md`, `naming_rules.md` (docs/memory copies
  updated). Left open: June conference backfill + the omissions list in §4.1. Uncommitted: yes (chains/, graph/,
  web/public, patches/applied, investing/pending.json, enrich_log.json, docs/).

- **2026-09-16 (Claude, run 2)** — Asked: supplement patches for the run-1 omissions, drop onsemi→Lite-On, pull the
  remaining conferences (newest first, reputable hosts only) and enrich + verify with 30 agents; then add SK Telecom
  as a node with its logo. Done: onsemi→Lite-On removed (chain + receipt). 26 supplement patches. `investing.py
  conferences --since 2026-05-15` → 9 new files (the site has almost nothing before late July); 7 enrichers → 8
  patches (NVIDIA SIGGRAPH had no supply-chain content). SK Telecom: node in neocloud.json (cloud_infra / Neocloud),
  edges Penguin Solutions→SK Telecom and NVIDIA→SK Telecom, metadata 017670.KS, logo `static/logos/SK Telecom.svg`
  (companieslogo SKM). **Incident:** a verifier ran `apply_patches.py --help`, which applied all 36 pending patches
  before verification finished → fixed apply_patches.py (any arg other than `--dry-run` now exits without applying);
  the 30 verifier rulings (20 concurrent max, launched in two waves) were then applied by the coordinator to chains
  and receipts (2 deletions, 14 edits). Also `investing.py get()` now retries connection resets / DNS blips.
  Result: graph 352 / 1,377; verify_graph on the 89 conference labels: 346 pass / 156 unchecked / 0 fail / 0 warn;
  conference queue 0. Memory: conference_enrichment.md, logo_fetching.md (docs/memory copies updated).
  Uncommitted: yes (chains/, graph/, web/public, patches/applied, transcripts/conferences, company_metadata.json,
  static/logos, apply_patches.py, investing.py, enrich_log.json, investing/, docs/).

- **2026-09-16 (Claude)** — Asked: download (not enrich) every 2026 earnings call of US-listed nodes that the graph
  has not enriched, full transcripts only, and record them for a later `enrich us`. Done: 150 US nodes / 445 calls
  checked → 202 queued (199 new `transcripts/av/` files from the defeatbeta parquet, now at `data/US/…`; AMAT Q1
  FY2026 from Motley Fool because both APIs hold a templated stub; Oracle Q3 FY2026 existing file; Intel Foundry Q4
  FY2025 shares Intel's file). Queue in `av/pending.json` + `av/sync_state.json` saved; tracked list
  `docs/US_ENRICH_BACKLOG.md`. Fixed `agent/corpus.py` label→file join to prefer an exact company file (it matched
  Applied Digital→Applied Materials, Lumentum→Lumen); full verify_graph unchanged before/after. No enrichment run.
  Uncommitted: yes (transcripts/av, agent/corpus.py, docs/).

- **2026-09-16 (Claude, run 3)** — Asked: enrich + verify 40 of the US backlog transcripts with 40 parallel agents
  (full transcripts only), plus Cerebras (newly listed as NASDAQ: CBRS). Done: the 40 newest backlog rows (38 companies)
  + Cerebras Q1/Q2 FY2026 (`transcripts/av/cerebras_q1_2026.txt`, `_q2_2026.txt`; metadata → CBRS / NASDAQ / public)
  → 42 patches, 40 enrichers + 40 verifiers (≤20 concurrent, waves). Verifiers edited wording/tags and removed 8-K
  restatements; ~0 deletions. New edges: Cerebras→Amazon, Sanmina→Cerebras, TSMC→Cerebras (on the N3/N2 foundry
  player — Cerebras is 5 nm; relationship text says so). One `apply_patches.py`, one `graph_build.py --sync`:
  graph 352 nodes / 1,384 edges; verify_graph on the 42 labels: 299 pass / 68 unchecked / 1 warn (Flex named as
  "Flextronics") / 0 fail. Removed only those 42 rows from `av/pending.json` (162 left; `docs/US_ENRICH_BACKLOG.md`
  Status column). Uncommitted: yes (chains/, graph/, web/public, patches/applied, transcripts/av, company_metadata.json,
  agent/corpus.py, enrich_log.json, docs/).

- **2026-09-16 (Claude, run 4)** — Asked: raise the subagent concurrency limit to 25, add the pending edge candidates, and
  enrich + verify the next 50 backlog transcripts. Done: `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=25` set in the user's
  `~/.claude/settings.json` env (takes effect on the next Claude Code start; this session stayed at 20, so waves).
  Next 50 newest backlog rows (49 companies) → 49 enrichers + 49 verifiers → 50 patches (~6 wording/tag edits per
  patch on average, deletions: Synopsys→Microsoft list-mention contract, Tesla→SpaceX Terafab work-split contract,
  Baker Hughes→Hitachi Energy off-chain grid edge). New edges kept by verifiers: Vistra→Microsoft (Pulaski PPA),
  Semtech→NVIDIA (1.6T DR4 TIAs/drivers), Siemens Energy→Oklo (power conversion system), NextEra Energy→Google
  (Duane Arnold). Coordinator edge patches (`patches/edge_*`): TSMC→SiTime (mature-node analog wafers, SiTime Q1),
  Cipher Digital→Google (Barber Lake, Cipher Q1), contracts Quanta→AEP (AEP Q1) and Bloom→AEP ($2.7B, AEP Q4);
  GE Vernova/MHI→AEP already had AEP Q2 contracts. One build: graph 352 / 1,390; verify_graph on 54 labels:
  425 pass / 90 unchecked / 0 warn / 0 fail. `av/pending.json` 162 → 112 (processed rows only). Uncommitted: yes.

- **2026-09-16 (Claude, run 5)** — Asked: finish the remaining 112 backlog transcripts the same way (parallel multi-agent
  enrich + verify, Opus xhigh). Done in one background Workflow (`us-backlog-enrich-112`: 111 enricher + 111 verifier
  agents, effort xhigh, pipeline so each brief was verified as soon as it was enriched) → 112 patches, ~1,003
  quarterly_data + 60 contracts kept, 249 verifier edits, 17 deletions (e.g. a Tesla entry naming xAI, reversed-direction
  Apple/Google/Lumen→Corning edges, collaboration/M&A edges from Cadence, ASE, Aehr, NextEra→Xcel). The coordinator also
  removed onsemi→Lite-On from the onsemi Q4 patch (user rule from run 2). New edges: Arm→SoftBank, Astera Labs→Amazon,
  Cadence→Samsung, Camtek→TSMC, Entergy→Hut 8, Flex→Amazon, GE Vernova→NextEra Energy, GE Vernova→Xcel Energy,
  Linde→TSMC, NVIDIA→Tesla. One build: graph 352 / 1,400; verify_graph on 112 labels: 848 pass / 214 unchecked /
  1 warn (Sandisk→Kioxia, transcript spells "Kyoccia") / 0 fail. `av/pending.json` → 0; the 2026 US backlog is done.
  Uncommitted: yes.
