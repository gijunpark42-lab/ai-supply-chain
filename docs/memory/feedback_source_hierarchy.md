---
name: feedback-source-hierarchy
description: "User rule (2026-09-24) for enrichment sources and agents — transcripts read end to end; without one, only company-issued docs; articles are pointers, never data; enrich agents Opus effort high; verification batched"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 04e18dca-b3a7-48ad-9506-b4dab78c625f
  modified: 2026-09-25T11:03:19.257Z
---

**Source hierarchy (user decision 2026-09-24, after the ECOC 2026 run):**
1. **Earnings / conference transcripts** — read EVERY line, prepared remarks and full Q&A. Capture what
   MANAGEMENT said that is material to the company; analyst statements are excluded unless management
   confirms them (then attribute to the manager). Do not filter by chain theme.
2. **No transcript → company-issued documents only:** IR press releases (company site / Business Wire),
   SEC filings (10-K, 10-Q, 8-K), DART filings, company-posted decks. Fetch from the official URL, save the
   full text verbatim to `transcripts/non_transcript_sources/` with a NOT-a-transcript NOTE and a
   `# source label:` header whose label names the doc type ("Marvell ECOC 2026 press release (09-21-2026)").
   Read the whole document, never just the title.
3. **Articles are NOT a data source.** Use them only as pointers to find the company's own release, then enrich
   from that. AI summary sites (StockTitan summaries, Rallies, Intellectia), newsletters, social posts and
   exhibitor boilerplate are never sources. No company doc = leave the gap (e.g. Sivers at ECOC 2026).

**Weight differs by doc type** — a product/event press release is NOT a 10-Q: 10-K/10-Q (reviewed/audited,
certified) > 8-K / earnings release > product or event press release (marketing, forward-looking). In product
releases, "first"/"leading" are the company's CLAIMS; demos are demos, never "shipping". Screener slots are
filled only from transcripts and filings. No edges or contracts from joint demos.

**Why:** accuracy over volume — an empty cell beats a wrong one; secondary rewrites mis-copy numbers
(Investing.com's auto title gave IQE the wrong fiscal year) and add opinion.

**Agent standard** (user wants it "extremely accurate"): extraction and independent verification run on
**Opus, effort high** (xhigh-level care for long or judgment-heavy sources: conference depth rule, DART, hard
speaker splits). Collection and numeric/locator/collision checks are scripts, not models. Sonnet is fine for
fetching and formatting, not extraction. Spawn with `subagent_type: "enricher"` (pinned in
`.claude/agents/enricher.md`) so a low session effort (user set medium on 2026-09-22) does not leak in.

**Verification cadence (user asked 2026-09-24):** the cheap script checks (pre-flight + verify_graph) run on
EVERY batch before applying — they cost no model tokens and catch bad numbers before they enter chains/.
The expensive independent Opus verifier can be BATCHED: run it once over ~5 enrichment jobs instead of per job.
Batching saves the fixed per-agent overhead (reading CLAUDE.md, the skill, the chain) but NOT the per-source
reading. Keep batches to sources on the same chain/company group so one verifier's context stays manageable.

**AUTO-VERIFY (user, 2026-09-24): do not wait to be asked.** After every graph_build that applies patches,
append the new labels to repo-root `verify_queue.json` (label, chain, source file, date, script_checks). When 5 or
more are pending, or at the end of a multi-job session, spawn an `enricher` verifier over them on your own, then
remove the verified rows. Script checks still run before every apply.

**Free fetch routes (tested 2026-09-24, no key, no model training needed):** company IR sites on the Q4 platform
expose RSS at `<ir-host>/rss/pressrelease.aspx` (Lumentum, Corning, Marvell all returned 10 items); SEC EDGAR 8-K
atom feeds (`browse-edgar?action=getcompany&CIK=..&type=8-K&output=atom`, send a User-Agent with a contact email);
Business Wire and GlobeNewswire RSS. Transcripts: utils/defeatbeta_fetch.py (US), av.py, investing.py (intl +
conferences), dart.py.

**`ir_pull.py` built 2026-09-25 (`enrich ir`, Workflow 2h in references/ir.md):** reads each company's IR RSS
feed (ir/feeds.json), saves releases verbatim to transcripts/ir/, queues ir/pending.json, skips notices with a
recorded reason, skips US results releases (edgar covers them), and skips a release already saved by hand
(matched on SOURCE URL). `discover` is strict: every distinctive name word or the ticker must be in the feed's
channel title (loose matching once filed Applied Industrial's feed under Applied Optoelectronics). Shows as its
own card on the Coverage tab (enrich_status.py pipeline "ir").

100 IR feeds registered 2026-09-25 (94 by parallel discover, all reachable, only 3M matched by ticker —
correct). Bare `enrich` now includes `ir_pull.py sync`; `enrich ir <Company>` = one feed. **Gotcha:**
TaskStop on a backgrounded Bash job does NOT kill its Windows python child — the first (sequential) discover
kept running and overwrote ir/feeds.json with its stale 13-entry dict (restored from the second run's log).
After stopping a long background script, check `Get-CimInstance Win32_Process` for survivors and Stop-Process them.

**Feed expansion 2026-09-25 (user: "why only 100? US alone is ~170"):** host-guessing misses IR sites with other
names (intc.com, ir.aboutamazon.com, gcs-web.com hosts). Added `discover --company X --url <official IR news page>`
(page `<link rel=alternate>` + RSS links + common paths, same strict check), then 6 Sonnet agents searched the 78
missing US names with a READ-ONLY probe (job tmp probe.py; agents never write ir/feeds.json, coordinator registers
once). Result: 154 feeds, US-listed coverage 153/177. `how: "manual"` + `note` = official host whose channel title
fails the strict check (legal/brand name: Supermicro, PacBio, Fluence, MKS Inc., Lumen, Evaxion; generic title:
AAON, NuScale, AstraZeneca, Microsoft press-releases tag). NO usable feed (don't re-search): ASML, Google, Novo,
Linde (email alerts only); MPS, ASE, BMS (bot wall); Nokia (IR feed dead since 2011), Camtek (dead 2024), Hut 8
(dead 2025); Tesla (results/webcasts only), HPE (links all go to one landing page), Sanofi (US consumer newsroom
only), SPX/Nova (site/blog feeds), Adobe/Advanced Energy/EMCOR/Eaton/Nebius/Sterling/TSMC/Vistra/Ichor (none).
`get()` now upgrades http:// to https:// (AEP links are http, port 80 closed). Probe gotcha: release_body returns a
LIST of lines — count chars with sum(len), not len().

**Round 2+3 (2026-09-25, user: "all listed companies, up to 40 agents, accuracy only"):** 342 sources for 465
public names (US 182/191, TSE 58/64, TWSE+TPEx 46/75, Europe ~all, Korea only 20/84 -- most Korean small caps
have only admin-notice boards or repost media articles). ir_pull.py grew: list-page mode (link_re, title_from
page, title_strip_re, date_from page, insecure_tls, lang), JSON mode (EIR/irpocket/JSON APIs), PDF bodies, CJK
titles (label "release <url id>"), prose_ok body gate, parallel list reads in sync. Every config passed: finder
agent (Sonnet, read-only probe) -> coordinator re-validation with today's code (date spot-check on the release
itself) -> date gate ("beside" dates vs the page's own date; mismatch -> date_from=page or reject). Caught real
errors: Infineon/Camtek/Socionext list dates shifted by one entry; IQE pages stamp crawl-time <time> tags (page
date == today is ignored); ADDA 3 items same date (rejected). Media-repost boards ([Etnews], outlet credits) are
never sources. Enrichment rule held: consumer PCs / tiny non-AI parts / exhibits / CSR / personnel = NO FACTS.
Code-limited "none" left for later: HD Hyundai Electric, Taihan Cable, Isu Petasys (POST/onclick-only lists),
ISC/Pegatron/Vanguard/DB HiTek/Park Systems (POST-only APIs), Nidec/Toray/Ichor (header token), Siemens (fixed
window now 25 lines -- re-test), Asahi Kasei (site-wide JSON index; could use JSON link_re), bot walls (Eaton,
MPS, Quanta, Wistron, Gigabyte, CUPID-protected Korean sites).

**ir_pull "already done" + window (user asked 2026-09-25):** every handled URL is remembered (sync_state
`seen`: saved / skip:<why> / enriched:<date>); `done --label` stamps enriched; `status --company X` shows each
release's state. For `enrich <Company>` / `enrich ir <Company>`: run status first — if nothing pending and sync
adds nothing, answer "already done" and stop. First sync per company reaches back to its latest EARNINGS CALL in
the graph (not a later conference), capped 120 days. Feeds keep ~10 newest items (median ~140 days; busy issuers
~3 weeks) -> run every 2-3 weeks; it runs locally (computer on). Collection could later move to a GitHub Actions
cron (free, no API key; commits files), enrichment stays in Claude Code.

Supersedes the per-request exception in [[feedback-transcript-only-purism]]. See [[conference_enrichment]].
