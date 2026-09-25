# HANDOFF — where the project stands and what to do next

Shared progress record for every agent working in this repo (Claude Code, Codex, ...).
Read `AGENTS.md` first for the load order and the hard rules. This file answers three questions:
**what is done, what is in flight, what comes next.** Append to the session log at the end of every
session; edit the "Current state" and "Next up" sections in place so they stay true.

Last full update: **2026-09-17** (Codex US missing-company enrichment; original Claude handoff history preserved below).

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
- **Graph:** 541 nodes, 1,619 edges after the two 2026-09-25 semiconductor coverage expansions (+133 and +29 skeleton nodes
  with `quarterly_data: []`, first `minerals` layer; see session log). Uncommitted.
- **Coverage by pipeline:** US 275 files / 276 labels in graph / 0 pending after this run; edgar 1,012/432;
  dart 48/48; intl 30/29; tw 17/17; conference 93/89 / 0 pending / 4 no-data; manual 244/245.
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
- **Standalone future-civilization Site:** `kardashev-scroll/` is a separate static Site, **The Power Age**, live
  publicly at `https://the-power-age.californiajune.chatgpt.site`. It is a scroll-only English cinematic from
  present-day power through embodied AI, recursive robot production, semiconductor cost compression, mass
  data-center scaling, planetary solar buildout, Solar System industry, Dyson-scale power and Type III civilization.
  Site project `appgprj_6ab1d0d4a8448191aca0b7492ea3cab7`; published version 2 from nested Site commit
  `69402bdae92a854dd1d12a5252b885e64ba0bd69`. This does not change the main earnings graph or Vercel app.
  User later created GitHub repo `gijunpark42-lab/the-power-age`; a fresh local nested repo now has commit
  `854a7f8`, pushed to its `main`. Vercel project `gijun42/kardashev-scroll` is connected to canonical GitHub
  repo `gijunpark42-lab/The-Power-Age` and live at `https://kardashev-scroll.vercel.app`.
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
1b. **US 2026 earnings-call backlog: done.** All 202 calls were enriched across runs 3–5 on 2026-09-16;
   `av/pending.json` is empty. Details: `docs/memory/us_backlog_2026.md`.
1c. **Missing-company audit:** the three US-listed direct candidates are now added and verified. Remaining list:
   `docs/MISSING_PUBLIC_COMPANIES_2026-09-17.md` (66 direct candidates: Korea 32, Japan 9, Taiwan 25;
   17 review candidates; 2 distributor exclusions). Korea is DART-only; Japan/Taiwan require an immediately
   available full transcript or approved pipeline before any add.
   UPDATE 2026-09-25: the user ordered a knowledge-built skeleton for 133 semiconductor names (session log);
   38 of the list above landed with it; the user then approved the rest ("yes do it all") and batch 2 added the
   remaining 17 semiconductor + 12 power/thermal A-list names. Not added: Doosan Tesna and the B-review names.
   Surfaced, not changed: GlobalWafers metadata should be 6488.TWO / TPEx; Toppan's product overlaps Tekscend.
1d. **Enrich the 162 skeleton nodes added 2026-09-25** (all `quarterly_data: []`): their tickers are in
   company_metadata.json, so `enrich us` / `enrich dart` / `enrich intl` / `enrich ir` pick them up on the next sync.
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
6. **The Power Age:** complete and live on both Sites and Vercel; source is in the separate GitHub repo
   `gijunpark42-lab/The-Power-Age` at commit `854a7f8`. Do not push the parent `reticulum-ai` repository.

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

- **2026-09-17 (Codex)** — Asked: read the repo, identify US/Korean/Japanese/Taiwanese listed companies missing
  from the graph, then enrich/add/logos; user narrowed the request mid-run because of token budget to **list only,
  no enrichment**. Done: wrote `docs/MISSING_PUBLIC_COMPANIES_2026-09-17.md`, comparing the 352-node graph with
  current official/thematic semiconductor and AI power/cooling baskets. Result: 69 direct (`A`) candidates, 17
  review (`B`) candidates, and 2 explicit distributor exclusions. No nodes, metadata, logos, transcripts, patches,
  queues, state files, generated graph files or external services changed. Decisions: enrichment/add/logo work is
  deferred; future Korea work uses only each candidate company's own DART filing, and Japan/Taiwan proceed only when
  a full transcript or approved pipeline is immediately available. Left open: validate sources company-by-company
  before any future addition, starting with the `A` list. Uncommitted: yes (`docs/` only).

- **2026-09-17 (Codex)** — Asked: continue with only the US-listed companies from the missing-company audit,
  enrich them from full transcripts into the appropriate chains, add logos, modify the repo and push. Done:
  added NXP Semiconductors (optical networking / Networking ASIC), Microchip Technology and Skyworks Solutions
  (optical Components + Power Semiconductors) through three applied patches and three saved full-call transcripts;
  added 21 quarterly-data entries and two transcript-named Microchip edges/contracts to Delta and Lite-On; added
  metadata and XML-valid, visually checked SVG logos. Build + web data sync completed at 355 nodes / 1,402 edges.
  Verification: NXP 6 pass / 0 fail; Microchip 8 pass + 2 unchecked / 0 fail; Skyworks 7 pass / 0 fail. The one
  queued Alpha Vantage row was marked done (`av/pending.json` 1 -> 0); manual fallback transcripts never entered
  that queue. Updated the audit to 66 remaining direct candidates. Decisions: this run covers only the US slice;
  Korea remains company-DART-only and Japan/Taiwan remain conditional on an available full transcript/approved
  pipeline. Left open: the remaining Korea/Japan/Taiwan audit candidates and pre-existing EDGAR round 3b. Uncommitted: no.

- **2026-09-18 (Claude, Opus 5 1M)** — Asked: does an AI-bio chain exist; if not build the skeleton, then
  multi-agent parallel enrich + logos + verify + push. Found `chains/applications/ai_bio.json` already on disk
  but UNTRACKED and half-built (28 players, 42 quarterly_data, 21 edges, 10 contracts; the 9 biopharma end
  customers, Tempus AI, Relay and Simulations Plus all at zero; Schrödinger carried 4 entries whose source
  transcript was not on disk at all). Took it over rather than rebuilding. Done:
  (1) **Transcripts** — `defeatbeta-api` was not installed; installed it, then pulled 13 calls with
  `utils/defeatbeta_fetch.py` (quota-free, parallel-safe): Schrödinger (label matched the existing one exactly,
  so the history did not split), Tempus AI, Simulations Plus, Eli Lilly, Bristol Myers Squibb, Vertex, Jazz,
  AstraZeneca, Novo Nordisk, Sanofi. Relay Therapeutics / Roche-Genentech / Bayer are on NEITHER defeatbeta nor
  Alpha Vantage (checked 2026Q1+2026Q2) — those three nodes stay at quarterly_data 0 until Europe runs through
  `investing.py`.
  (2) **Enrichment** — 5 parallel agents wrote 10 ADD-only patches; the coordinator added 2 more. Applied:
  **+66 quarterly_data, +10 contracts**. Chain is now 29 players / 108 quarterly_data / 27 edges / 20 contracts.
  (3) **Schrödinger audit** — a dedicated agent re-checked all 4 pre-existing no-source-on-disk entries against
  the newly fetched call: **4/4 CONFIRMED** verbatim (BMS Bunsen agreement, ACV $29.6M/+27%/$208M TTM, drug
  discovery rev $23M + $10M Ajax milestone, >$750M since 2020). Nothing had been fabricated.
  (4) **New edges from the calls** — NVIDIA→Bristol Myers Squibb and **Anthropic→Bristol Myers Squibb** (BMS CEO
  named both as AI partners; Anthropic was already a graph node, so this made it an 18-chain hub), AbCellera→Jazz
  (customer-side confirmation: preclinical, next-gen T-cell engagers, GI cancers), Schrödinger→Eli Lilly,
  Tempus AI→AstraZeneca / →BMS, plus contracts filling the empty NVIDIA→Schrödinger and Google→Schrödinger edges.
  New sector `ai_models / Frontier AI Models` for Anthropic. Kept the hedged Simulations Plus→Recursion edge
  (management-named + existing node) with the hedge preserved verbatim in the signal.
  (5) **Logos** — all 25 AI-bio nodes had none. Wikidata P154 with ticker proof (P249 qualifier on P414) got 12;
  companieslogo.com sitemap→ticker-keyed image got 12 more; Evaxion came off its own site. 23 SVG + 2 PNG, every
  SVG checked for drawable elements. manifest.json 352→377 by APPEND (no re-sort: +100 lines, 0 deletions).
  (6) **Verify** — `graph_build.py --sync` then `verify_graph.py` on all 10 new labels: **80 entries, 65 pass,
  15 unchecked (no numeric figure), 0 fail, 0 warn**. Graph 355→380 nodes, 1402→1429 edges. `av/pending.json`
  drained 13→0 (all were already in the graph from the earlier session).
  Decisions: proposed nodes NOT added (structure is the user's) — BioNTech, Merck, GSK, Daiichi Sankyo, Incyte,
  LevelSet Bio, Personalis, Simcere (2096.HK), IQVIA, Crinetics. Notable: Eli Lilly, Vertex, AstraZeneca, Novo
  and Sanofi Q2 calls contain **zero** AI/ML mentions — only BMS and Jazz do. Uncommitted: no (pushed).

- **2026-09-18 (Claude, Opus 5 1M) — follow-up** — User: "it's not on the website yet". The data WAS live
  (gijun42.com served 380 nodes / 1,429 edges / 21 chains and all 25 logos), but the UI hid the chain: the
  sidebar builds its list from `CHAIN_COLORS` in `web/src/lib/taxonomy.ts` (`CHAIN_SLUGS = Object.keys(...)`)
  and `page.tsx` seeds the default-checked filters from the same map, so with no `ai_bio` entry its 25
  exclusive nodes were filtered out — the header read "355 / 380 companies, 20 / 21 active chains". Fixed in
  3de46a2: added `ai_bio: "#d946ef"` plus a drug-discovery/genomics keyword rule to the Ask router in
  `retrieval.ts`. Verified in Chrome on the deployed site: 380/380 companies, 1,429 connections, 21/21 chains;
  Chain 2D renders the full AI Bio chain; Tempus AI shows "7 signals, downstream 2"; Recursion renders its
  logo badge and "last data 2026-08-05". The chain-skeleton skill now documents this as its last step.
  Uncommitted: no (pushed).

- **2026-09-18 (Claude, Opus 5 1M) — coverage pass on the AI-bio biopharma nodes** — User asked how much of each
  call was actually read, then set a clearer capture rule: **if MANAGEMENT said it and it is material to the
  company, capture it; ANALYST statements are not wanted.** Measured the gap first: the share of
  management-spoken figures present in the graph was Schrödinger 96% and Tempus 86% (fine), but the biopharma
  end customers were thin — AstraZeneca 40%, Novo 45%, BMS 59%, Vertex 62%, Sanofi 62%, Jazz 70%. Cause was my
  own earlier prompt, which told the agents to prioritise AI/ML content; these pharma calls contain almost none,
  so the agents captured only a few headline financials. Fix: 7 parallel agents (one per company, full-transcript
  read, analyst/management split derived from the Operator introductions) wrote 7 ADD-only patches — **+141
  quarterly_data**, 0 contracts, 0 new players, 0 new edges, 0 duplicates. Chain now **29 players / 249
  quarterly_data / 27 edges / 20 contracts**; graph unchanged at 380 nodes / 1,429 edges. Coverage after:
  Lilly 91%, BMS 98%, Vertex 100%, Jazz 89%, AstraZeneca 100%, Novo 95%, Sanofi 95%. `verify_graph.py` on all
  7 labels: 188 entries, 139 pass, 49 unchecked (no numeric figure), **0 fail, 0 warn**. A coordinator pre-flight
  (`preflight.py`, kept in the job tmp dir) independently re-checked every patch for leaked analyst figures,
  numeric support, collisions and forbidden slot re-tags before applying — 0 problems.
  Notes worth keeping: the agents corrected three errors in the speaker lists I gave them (substitute analysts
  on the Jazz call, Carsten Lønborg Madsen is a Danske analyst not Novo management, and AstraZeneca's analysts
  are introduced by Pascal Soriot rather than the Operator). The BMS transcript mislabels an Opdivo Qvantig
  figure as "Sotyktu" in the oncology section; the entry keeps the number verbatim and flags the naming rather
  than silently reassigning it. Uncommitted: no (pushed).

- **2026-09-18 (Claude, Opus 5 1M) — drained the "saved but never enriched" tail** — User asked to enrich whatever
  was left in the conference and pasted-earnings queues. **All five queue files were already at 0** (conference,
  us, dart, intl, tw, edgar), so instead I matched every transcript on disk against the graph's label set and found
  **7 files that had been saved, marked done, and produced no graph data at all**. Five agents handled them:
  **NVIDIA SIGGRAPH 2026** (+9: DLSS 5 pixel-space diffusion, AI physics surrogates ~1,000,000x checkpoint
  compression, Cosmos 3 family, the Cosmos Dreams 64 GB300 -> 16 Vera Rubin -> 1 RTX 6000 compute ladder),
  **NVIDIA The Six Five Summit** (+5: NeMo Switchyard model router — the word appears nowhere else in the graph —
  open-dataset-not-just-weights, DGX Station multi-tenancy, open-source token share call),
  **Seagate The Six Five Summit** (+5: 80% of the world's data on datacenter HDD, the 55% CIO deletion-regret
  survey, cold-tier obsolescence, object stores + metadata in memory),
  **Dell the Six Five Summit** (+1 only — see below),
  **IQE** (+13 qd, +2 contracts, +1 new edge) and **Naver Cloud** (+2).
  Applied in one build: **+35 quarterly_data, +2 contracts, +1 edge**; graph 380 nodes / 1,429 -> 1,430 edges.
  verify_graph on all 6 labels: 0 fail, 0 warn.
  **Three corrections worth remembering.**
  1. **IQE was mislabelled.** The file was `iqe_q2_2024.txt` with label `IQE Q2 FY2024`, because Investing.com's
     auto-generated title said "H1 2024". The transcript body header actually reads "Full transcript - IQE PLC
     (IQE) H1 2026", a question cites a 16-June-2025 RNS, and management speaks of 2026/2027 — it is the NEWEST
     IQE source, not a two-year-old republish. I renamed the file to `iqe_q2_2026.txt`, corrected its header
     (with a note explaining why), relabelled to `IQE Q2 FY2026 (09-07-2026)`, added the `revenue_growth` and
     `guidance` slots (the Screener was still showing FY2025 as current) and added the management-stated
     **IQE -> Tower Semiconductor** multi-year InP edge. **Never trust an Investing.com title's fiscal year —
     check the body header and what management dates itself to.**
  2. **Dell: 3 of 4 entries dropped.** They came from a speaker the transcript labels only "Matt, Infrastructure
     Expert" with NO company; the only company-labelled Dell speaker is CTO John Roese. Under the project rule
     (management speakers only) an unaffiliated "expert" on a vendor's conference track is not a company source.
     Kept the Roese entry alone. Cost: the GPU:CPU 8:1 -> 1:1 agentic ratio datapoint, which is real but not
     attributable to Dell.
  3. **Naver Cloud files two 잠정실적 the same day** — consolidated and separate (parent-only). The consolidated
     one is genuinely superseded by the 08-14 half-year report, but the SEPARATE set had no counterpart anywhere
     in the graph. A `_separate` sibling must not be judged by its consolidated twin. I also removed an unsourced
     "100%-owned" ownership claim the agent had added.
  **Not a queue:** a full recursive re-scan shows 336 EDGAR files with no graph data, but `edgar/done.json` holds
  all 1,012 as read — routine 8-Ks (dividends, officer changes) legitimately yield nothing under the completeness
  contract. Uncommitted: no (pushed).

- **2026-09-21 (Codex) — built and published “The Power Age” scroll story.** User asked for a public, game-like,
  scroll-only journey from present civilization to a galactic Kardashev civilization, then corrected the first
  version because it jumped to space too quickly. Done: created the separate static Site under
  `kardashev-scroll/`; generated and integrated six cinematic chapter assets; added the full causal bridge
  **AI gets a body → robots build robots → autonomous semiconductor fab → raw silicon (<$1 illustrative) vs
  fabricated logic die (~$300) vs accelerator module (~$3,000+) → data-center mass scaling → Earth-scale solar
  grid → robotic Solar System data centers → Dyson swarm → Type III galaxy**. Verified 14 sections, 9 image
  placements, JavaScript syntax, HTTP 200, and visually checked the opening, robot-factory, semiconductor-cost,
  Solar System and finale scenes in the in-app browser. Published Site version 2 successfully and changed access
  to public: `https://the-power-age.californiajune.chatgpt.site`; nested Site source commit
  `69402bdae92a854dd1d12a5252b885e64ba0bd69`. Main graph/build/queues untouched. Decisions: all visible Site
  text remains English per repo rule; Site is scroll-only with no buttons. Left open: none; further changes only
  if requested. Uncommitted: yes — main repo has this HANDOFF edit plus the untracked nested Site directory;
  no main-repo commit/push was authorized.

- **2026-09-21 (Codex) — prepared GitHub/Vercel handoff without touching the parent repo.** User clarified:
  “reticulum ai 푸시하면 안 돼지, 새로 만들어야지,” then created `gijunpark42-lab/the-power-age`. Done:
  initialized a fresh nested Git repo in `kardashev-scroll/`, committed the site as `854a7f8` (“Launch The
  Power Age”), set `origin` to the new repository, and added `vercel.json` plus `.gitignore` (no README).
  The push attempt was blocked by the environment proxy; GitHub auth is still invalid, and the escalation request
  for `gh auth refresh -h github.com -w` was rejected by the current usage-limit reviewer. No bytes were pushed
  to `reticulum-ai`, GitHub, or Vercel. Left open: user must refresh GitHub auth / restore outbound network, then
  run `git push -u origin main` in `C:\Users\calif\Desktop\earnings-ai\kardashev-scroll`; run `vercel --prod --yes`
  from the same directory afterward. Uncommitted: yes — main repo only has the HANDOFF edit and pre-existing
  `docs/research/` / `output/` items; nested site repo is clean.

- **2026-09-21 (Codex) — GitHub push completed.** User ran the prepared absolute-path commands after creating
  `gijunpark42-lab/the-power-age`; commit `854a7f8` is now on `main` and tracking `origin/main`. The remote
  reported a case-only repository move to `The-Power-Age.git`; local `origin` was updated to the canonical URL.
  Vercel deploy was attempted from the same checkout but the local Vercel CLI hit `spawn EPERM` and proxy
  refusal (`127.0.0.1:9`). Left open: run `vercel --prod --yes` from
  `C:\Users\calif\Desktop\earnings-ai\kardashev-scroll` in a network-enabled terminal. Parent `reticulum-ai`
  remains untouched.

- **2026-09-22 (Codex) — Vercel production deployment completed.** User said “걍 니가 알아서 다 해줘.”
  Disabled the Vercel CLI's automatic updater with `NO_UPDATE_NOTIFIER=1`, ran from the exact site checkout,
  created project `gijun42/kardashev-scroll`, connected GitHub repo
  `https://github.com/gijunpark42-lab/The-Power-Age`, uploaded 15.1 MB, and verified Vercel status `Ready`.
  Production alias: `https://kardashev-scroll.vercel.app`; immutable deployment:
  `https://kardashev-scroll-2n9h7050u-gijun42.vercel.app`. Parent `reticulum-ai` remained untouched.
  Left open: none. Uncommitted: parent HANDOFF documentation only; nested site repo remains clean because
  `.vercel/` is ignored.

- **2026-09-22 (Claude, Opus 5.5 1M) — ECOC 2026** — Asked: enrich the optical companies' ECOC 2026 conference
  appearances, full transcripts only, multi-agent parallel with verification. ECOC 2026 runs 09-20..24 in Malaga
  (exhibition 09-21..23); this run was on day 3. `investing.py conferences --since 2026-09-14` (needed
  `curl_cffi`, which is in requirements.txt but was not installed) found exactly **one** ECOC transcript:
  **Coherent's PhotonLink launch, 09-21** — a full verbatim transcript (CMO, CEO, EVP Semiconductor Devices, CTO;
  37K chars, ends on the closing thanks). Marvell's ECOC fireside chat was 09-22 with no transcript posted yet;
  Lumentum, Credo, Corning and Adtran had technical talks and booth demos only, which produce no transcript.
  Press releases and article summaries were deliberately not used.
  Two enrichers split the transcript by speaker lane (A: paras 1-28 CEO + semiconductor devices; B: paras 29-48
  CTO), each writing its own patch; B read A's patch and dropped the figures Julie Eng repeated from Jim Anderson.
  An independent verifier was started, then **stopped on the user's instruction** before it edited anything.
  Coordinator pre-flight instead: locator, label, figures in source, collisions, cross-patch duplicates,
  ASCII — 25 items, 0 problems. Thinned the `cpo` topic tags **21 -> 7** (derive.py never caps explicit tags,
  so Coherent's CPO timeline would have become ~21 ECOC rows); cpo now marks only entries whose subject IS
  co-packaged/near-packaged optics. Applied: **+24 quarterly_data, +1 contract** (Coherent -> NVIDIA: CTO named the
  CPO anchor LTA as "our NVIDIA agreement"). New substance includes the $30B integrated-optics opportunity by end
  of decade on top of ~$60B existing, up to ~$15,000 of content per 100T chip, >10 CPO / >10 NPO / >5 chip-to-chip
  engagements, NPO ramp 2H next calendar year, chip-to-chip 2029-2030, 300M+ InP lasers and 1B+ photodetectors
  shipped, the 6.4T silicon-photonics NPO module, 1.2 pJ/bit VCSEL NPO. verify_graph: 25 entries, 13 pass,
  12 unchecked, 0 fail, 0 warn. Graph unchanged at 380 nodes / 1,430 edges.
  **Queue:** removed ONLY the Coherent row from investing/pending.json — `investing.py done --kind conference`
  clears every conference row. 11 non-ECOC conference transcripts from the same pipeline run remain queued,
  including **Relay Therapeutics** (Morgan Stanley, 09-16), which would fill one of the three AI-bio nodes that
  had no free transcript. Left open: Marvell's ECOC transcript once posted; the 11 queued rows.
  Uncommitted: yes — no push instruction this turn.

- **2026-09-22 (Claude, Opus 5.5 1M) — ECOC 2026 part 2: official press releases** — User widened the source rule for
  this request: if only summaries exist, add conference content fact-based, from accurate sources; company IR releases
  are fine (recorded as an exception in docs/memory/feedback_transcript_only.md). Asked for Marvell, Lumentum, Sivers,
  Corning. Re-ran `investing.py conferences --since 2026-09-20`: no new ECOC transcripts. Fetched from OFFICIAL URLs
  and saved verbatim to `transcripts/non_transcript_sources/` with NOT-a-transcript notes and labels that name the
  document type: `marvell_ecoc_2026_press_release.txt` (09-21), `lumentum_ecoc_2026_elsfp_press_release.txt` (09-21),
  `lumentum_ecoc_2026_d2d_press_release.txt` (09-21, joint Lumentum/Qualcomm/Corning), `corning_ecoc_2026_press_release.txt`
  (09-17). Three parallel agents, split by COMPANY (the joint doc's Corning role went to the Corning agent), facts only,
  demos never written as shipping. Applied **+18 quarterly_data** (Marvell 7, Lumentum 4, Corning 7), no edges or
  contracts (joint demos are not supply contracts), Qualcomm deliberately not touched. Pre-flight 0 problems;
  verify_graph on all 4 labels: 18 entries, 12 pass, 6 unchecked, 0 fail. 4 `cpo` tags only — note they make these
  09-21/09-17 rows the latest CPO-timeline rows for Marvell/Lumentum/Corning (replace-with-latest), so e.g. Lumentum's
  five Citi 09-09 CPO rows drop out of that one view (they stay on the node). **Sivers: nothing added** — no ECOC 2026
  release on its newsroom or Cision; the ECOC exhibitor page (stand 2106) carries no Sivers content. Skipped
  schedule-only pages (Marvell event page, Lumentum speaker line-up), which do show that Marvell's Xi Wang and
  Lumentum's Rafik Ward held fireside chats 09-22 — transcripts may follow on Investing.com.
  Uncommitted: yes — no push instruction this turn.

- **2026-09-24 (Claude) — standing rules recorded** — Source hierarchy: transcripts read in full (management only); without a transcript only company-issued docs (IR releases, SEC/DART filings); articles are pointers, never data. Enrichment/verification agents: Opus effort high via the new pinned agent `.claude/agents/enricher.md` (`subagent_type: "enricher"`). Script checks every batch; the Opus verifier may be batched over ~5 jobs. Recorded in the enrich skill and docs/memory/feedback_source_hierarchy.md. Uncommitted: yes.

- **2026-09-25 (Claude, Opus 5.5 1M) — ir_pull.py + auto-verify** — (1) First automatic Opus batch verification
  (new rule: at 5+ labels in `verify_queue.json`, run without being asked) over the five ECOC labels: 43 entries,
  4 corrections applied via apply_corrections.py (a Coherent VCSEL production date that read as belonging to the
  wrong product; three Marvell "first" claims now attributed in the figure field), 0 deletes; queue cleared.
  (2) New `ir_pull.py` (`enrich ir`, references/ir.md): company IR RSS feeds -> `transcripts/ir/` verbatim with
  NOT-a-transcript headers and labels `<Company> press release: <short title> (MM-DD-YYYY)` -> `ir/pending.json`.
  Skips notices with a recorded reason, US results releases (edgar covers them) and anything already saved by
  hand (SOURCE-URL match). `discover` is strict (all distinctive name words or the ticker in the channel title) —
  the loose first version matched Applied Industrial's feed for Applied Optoelectronics. Test sync since 09-01 on
  6 feeds (Lumentum, Corning, Marvell, Coherent, Ciena, Fabrinet): 9 releases queued, incl. Ciena FY2029 targets
  (09-16 investor forum), Coherent PhotonLink/pluggable line systems, Marvell-Microsoft-Utimaco; 3 duplicates of the
  hand-saved ECOC releases removed. Coverage tab gets an "ir" card (enrich_status.py). Full `discover` over all public
  companies was started in the background. Credo and Applied Optoelectronics need feeds added by hand.
  Queue not yet enriched. Uncommitted: yes.
  Follow-up same day: the first (stopped) sequential discover survived TaskStop and overwrote ir/feeds.json; killed it and restored from the parallel run log -> **100 feeds**, all reachable, only 3M ticker-matched (correct). Bare `enrich` now includes `ir_pull.py sync`; `enrich ir <Company>` = one feed.
  Follow-up: `ir_pull.py status [--company]` + `done` now stamps enriched:<date> so a repeat `enrich <Company>` answers "already done"; first sync per company reaches back to its latest earnings call (capped 120 days). Feeds hold ~10 newest items (busy issuers ~3 weeks) -> run every 2-3 weeks.

- **2026-09-25 (Claude) — `enrich ir`, last week** — `ir_pull.py sync --since 2026-09-18` over 100 feeds: 23 releases from 18 companies (only 18 of the 100 published that week, so not 50). 18 enricher agents in parallel, one per company: 10 companies yielded 22 entries (Coherent 4, CoreWeave 4, Synopsys 4 + contract on Synopsys->TSMC, Microchip 2, Tempus 1 + NEW edge Recursion->Tempus AI for the TxFM model license, Digital Realty, Modine, Vertiv, Absci, Teradyne 1 each); 8 had no material facts (index inclusion, employer award, equity grants, community event, sponsorship, session notice, market survey, auto sample kits). Script checks + verify_graph on all 13 labels: 15 pass, 7 unchecked, 0 fail. Auto Opus verification (2 agents): 1 wording fix applied (Coherent component list), rest pass; verify_queue cleared. All 23 rows stamped enriched / no-new-facts; 7 older rows remain queued. Noise filter extended for those notice types. NOTE: node count 380->379 came from ANOTHER session merging Intel Foundry->Intel and Naver Cloud->Naver at 00:19 (uncommitted, not logged) — not from this run. Uncommitted: yes.

- **2026-09-25 (Claude) — IR feed coverage 100 -> 154, `enrich ir` for the new names** — User asked why only 100
  feeds when ~177 names are US-listed. Cause: `discover` only guesses investor./investors./ir.<name>.com. Added
  `ir_pull.py discover --company X --url <official IR news page>` (page <link rel=alternate>, RSS links on the page,
  common paths; same strict ownership check). Six agents searched the 78 missing US names with a read-only probe;
  coordinator registered 54 feeds once (44 strict-check passes + 10 `how: manual` with a `note` — official host whose
  channel title uses a brand/legal name or a generic title). US-listed coverage now **153/177**. The 24 without a
  usable feed are listed in memory feedback_source_hierarchy.md (email-alert-only, bot walls, dead feeds, results-only).
  ir_pull.py fixes: `get()` upgrades http:// to https:// (AEP); `save()` writes temp + os.replace with retries
  (Windows Errno 22 crashed a sync); shareholder-meeting pattern no longer catches medical congresses ("AANEM Annual
  Meeting"); RESULTS only matches financial results (Vertex Phase 2b "Positive Results" had been skipped); new
  noise pattern "Transaction in Own Shares" (Shell daily buyback notices).
  Sync since 09-18 over 154 feeds: 34 new releases (22 companies). Five `enricher` agents: 22 patches / 26 entries
  applied (AstraZeneca 6, Lilly 3, Vertex 2, Everpure FY28 preliminary outlook [guidance slot], Vicor raised Q3
  guidance [guidance slot], Supermicro shipping Vera Rubin NVL72 + 1.8MW CDUs, Semtech 50G CDR/TIA + XPO, Skyworks
  exchange offers for Qorvo notes, Fluence-EVE Power supply agreement, GE Vernova Egypt RLE + SMR MoU, Lumen, AOI
  concept demo, Apple M5-series Macs); 9 no-facts + 3 dropped as immaterial (ST MEMS sensor, Semtech-Palo Alto
  IoT, Viavi CMMC). Pre-flight 0 issues; verify_graph 24 pass / 2 unchecked / 0 fail. No new nodes or edges. Opus verification (2 agents, 26 entries): all pass, 0 corrections.
  NOTE: another session applied `patches/applied/skeleton_semis_expansion_2026-09-25.json` at 01:32 (144 players,
  graph 380 -> 512 nodes) — not this session's work. Uncommitted: yes.

- **2026-09-25 (Claude) — semiconductor coverage expansion (+133 skeleton nodes) + YJ Semi -> Yuanjie** — User asked for every
  missing semiconductor company (ambiguous ones for approval), approved the list (incl. POET, YMTC, Toray, all weak-AI
  semis, minerals Korea Zinc/Umicore/5N Plus/MP Materials/Lynas, Foosung) and ordered a skeleton "from your own knowledge",
  verified, multi-agent, with logos. Draft spec -> 5 enricher (Opus) verifiers on disjoint slices (16 unevidenced edges
  dropped, 55 evidenced edges added, 25 product fixes, Toray -> mlcc, renames UMS Integration / Nippon Sanso Holdings)
  -> ONE ADD-only patch `patches/applied/skeleton_semis_expansion_2026-09-25.json` (133 companies, 134 placements, 146 +
  16 incoming edges, contracts/quarterly_data empty) + 133 company_metadata.json rows. New sectors: Specialty /
  Mature-Node Foundry, Sub-fab Equipment (Scrubbers / Chillers), Solder & Bonding Materials, Lids & Thermal Interface
  (TIM), Server Mechanical Components, and the first `minerals` layer (Indium, Germanium, Rare Earths). Audit: every
  node/edge landed, 0 existing entries lost (pre/post counts). User then ordered `YJ Semi` merged into **Yuanjie**
  (688498.SS): player name + metadata key only; signal text keeps the note's "YJ Semi"; verify for the Goldman label
  unchanged (35 pass / 16 unchecked). Logos: 134 new (4 agents + 1 manual), light/dark contact-sheet checked; coverage
  508/512 (still none: ASADA, Fluidstack, KOACC, SK Trichem). Graph 512 nodes / 1,591 edges. Details + revert-by-name
  note: docs/memory/semis_expansion_2026_09_25.md. Uncommitted: yes.

- **2026-09-25 (Claude) — semiconductor coverage expansion, batch 2 (+29) + Yuanjie product** — User: "yes do it all" ->
  the 17 semiconductor + 12 power/thermal names left on docs/MISSING_PUBLIC_COMPANIES_2026-09-17.md, same recipe (draft
  spec -> 3 enricher verifiers -> one ADD-only patch `patches/applied/skeleton_semis_expansion2_2026-09-25.json`): 29
  companies, 20 + 8 incoming edges (DART / MOPS / EDINET-backed; Formosa Sumco->TSMC dropped as unevidenced), renamed
  JeRyong -> Cheryong Electric (DART English name), node `TSE Co.` (not TES / not the Tokyo exchange). Yuanjie product
  -> "InP laser chips (CW / DFB / EML)..." (direct one-line edit). Audit: all landed, 0 existing entries lost, batch 1
  intact. Graph 541 nodes / 1,619 edges. Logos: all 29 registered (contact-sheet checked); coverage 537/541. Uncommitted: yes.

- **2026-09-25 (Claude) — IR coverage to every listed company (rounds 2-3)** — User: "all listed companies,
  up to 40 agents, accuracy only". ir_pull.py grew list-page mode (HTML lists with a per-site link_re,
  title_from/date_from page, title_strip_re, insecure_tls, CJK headlines, PDF bodies via pypdf+cryptography),
  JSON mode (the GET endpoint a JS news page calls: Pronexus EIR, irpocket, AGC, Merck, Adobe, Novo, Roche),
  a prose_ok body gate (+ RSS content:encoded fallback), http-only fallback and parallel list reads in sync.
  ~40 finder agents (read-only probe) -> coordinator re-validation with today's code (date spot-check on the
  release) -> date gate ("beside" list dates vs the release's own date). Caught and fixed real list-date
  shifts (Infineon, Camtek, Socionext -> date_from=page), IQE crawl-time <time> tags, ADDA shared dates
  (rejected). Media-repost boards never registered. Feeds 154 -> 342; public names covered 342/465
  (US 182/191, TSE 58/64, Taiwan 46/75, Korea 20/84). Last-week enrichment of the newly covered names:
  60 releases -> 18 patches applied (AT&S->Marvell new edge with contract; GlobalWafers GDS, Zhen Ding CB,
  SoftBank notes for OpenAI tranche, GUC HBM4E IP, Accelink 12.8T XPO, LPKF glass-substrate LOI, ...),
  42 closed as no facts; verify_graph 0 fail; two Opus verifiers: 23 entries all pass. A third sync over the
  44 round-3 sources was running at commit time (its saves go into the next commit).
