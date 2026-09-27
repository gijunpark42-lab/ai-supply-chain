### Workflow 2g — Investor-conference fireside chats via Investing.com (`enrich conference`)

Between earnings calls, management speaks at bank conferences (Goldman Communacopia, Citi Global
TMT, Jefferies, UBS, Morgan Stanley TMT, JPM …). Investing.com posts a same-day article per
appearance — an editorial summary followed by the **verbatim fireside chat with speaker labels**
("Bill, CEO, Credo: …"). `investing.py conferences` walks the site's `/news/transcripts` listing
pages (newest first, 36 per page, publish date in the page JSON), keeps only articles whose title
is `<Company> at <Conference> [YYYY]: …` for a company in `company_metadata.json` (**US names
included** — nothing else carries conference talk), saves ONLY the transcript part (summary
dropped) to `transcripts/conferences/`, and queues it in `investing/pending.json` with
`kind: "conference"`. Verified 2026-09-10: Credo, Supermicro, Seagate, Arista, TE Connectivity,
Penguin Solutions, SpaceX, Uber at Goldman/Citi/Jefferies — 5,000–6,600 words each.
Same scraping caveat as `enrich intl` (Chrome TLS fingerprint, one request per second).

**Trigger: the user says `enrich conference` (or `enrich conferences`).** Run the whole loop:

1. `python investing.py conferences` — default window 180 days (`--since YYYY-MM-DD`, `--pages N`
   to walk further; ~1 s per page and per article). It prints how many listing pages it walked,
   the oldest article date reached, and `saved` / `skip` / `FAIL` per article. Every run is
   appended to `investing/conferences_state.json` → `runs[]` (`at`, `since`, `pages`,
   `oldest_seen`, `candidates`, `saved`); `seen{}` maps every conference URL to
   `saved` / `skip` / `fail` (`fail` is retried next run). **Read the last `runs[]` entry first** — it
   tells you how far back the site has already been walked, so you know whether the queue is
   complete for the window. The bot filter answers 403 after ~130 fast listing pages (first
   backfill 2026-09-10 stopped at `oldest_seen` 2026-08-06 with 84 files saved); `get()` now waits
   a minute and retries, but if a run still stops short, re-run later — it skips what it has and
   keeps walking back.
2. `python investing.py pending --kind conference` — this workflow's queue (rows marked `transcript`
   belong to `enrich intl` — leave them). A market command works only its own rows:
   `--kind conference --market US|KR|TW|JP|EU|CN`. Never enrich a file that is not in the queue.
3. **Enrich each file under the depth rule below** (Workflow 2, JOB 1–5, ADD-only, patches only);
   pre-flight every patch with `python -X utf8 utils/check_patch.py <patch>` until clean.
4. `python graph_build.py --sync` — ONE run by the coordinator after all patches are in. It applies
   the patches and runs `verify_graph.py` on the labels just applied.
5. **Verification loop:** read every `[fail]` / `[warn]` line. For each `[fail]`, re-open the
   transcript file, decide whether the entry is wrong (fix or drop it) or the locator is wrong
   (fix the `source_quote` / label), re-run `python -X utf8 verify_graph.py --label "<label>"`,
   and repeat until the labels from this run show 0 fail. Warnings that are explainable (e.g.
   a number the speaker rounds differently) are listed in the report, not silenced.
6. `python investing.py done --kind conference` (keeps the `enrich intl` rows; a market command adds
   `--market <its market>` so other markets' rows stay queued).
7. Report per company: label, what was added, what was skipped as a restatement, verify result.
   Then **update memory** (`conference_enrichment.md` in this project's memory dir): run date,
   window walked (`oldest_seen`), the companies + conferences enriched, the ones skipped as
   restatements, open problems. The user wants to be able to ask "where did we get to?" later —
   the status board (`ENRICH_STATUS.md`) now answers that too; keep the memory note short.
If the queue is empty after step 1, say so and stop.

**Depth rule — only what the earnings call did not already say.** A fireside chat two weeks after
a call restates most of the call. Before extracting, read the company's most recent earnings
entry in the graph (`quarterly_data` under its latest `[Company] Q[N] FY[YYYY] (…)` label —
`python -X utf8 verify_graph.py --label` prints it, or grep `graph/merged_graph.json`). ADD only:
- new or changed numbers (guidance raised/lowered, a quarter-to-date data point, backlog, capacity,
  ramp timing, pricing, mix) — not the call's numbers repeated;
- newly *named* customers, suppliers, partners, design wins, contracts → `contracts` on the existing
  edge (new edge only if the speaker states the relationship explicitly);
- product/generation transitions, supply constraints, share shifts the call did not mention.
If nothing survives the rule, write NO patch; list the file in the report as
`restates <earnings label>` and mark it done. Questions are context only — a moderator's number is
not management's unless management confirms it. Only management speakers are sources
(`Name, CEO/CFO/…, Company:` paragraphs); nothing from the article's own summary (it is not saved).

**Label:** the `# source label:` line verbatim — the enrich skill's Event format
`[Company] [Conference] [YYYY] (MM-DD-YYYY)`, e.g. `Credo Goldman Sachs conference 2026 (09-10-2026)`.
The date is the article publish date, which is the event day. `[Company]` is the canonical node name.

**Multi-agent (the default — up to 20 agents, fewer for a small queue) — the recipe that worked for `enrich edgar`:**
- Coordinator splits the `conference` rows by company into up to 20 batches (all of one company's
  conferences in one batch so the depth rule is applied consistently).
- One **enricher** agent per batch: reads each transcript in full, applies the depth rule, writes
  only `patches/conf_<file stem>.json` — never `chains/` (see `concurrent_job_race` memory).
- One **verifier** agent per batch, adversarial: re-reads every transcript, checks that every
  number, name and claim in the patch appears verbatim in a management paragraph and is not a
  restatement of the call entry; edits or deletes patch entries; never adds.
- Coordinator then runs step 4 once, does the verification loop (step 5), steps 6–7.

**File format** `transcripts/conferences/<company slug>_<conference slug>_<YYYY-MM-DD>.txt`:
`SOURCE:` (article URL) / `TITLE:` / `EVENT:` / `DATE:` / `# source label:` / `# speakers:` (the
management speakers found) / `# paragraphs:` header, then one paragraph per turn —
`Moderator: …` and `Name, Title, Company: …`. A `# note: no 'Full transcript' marker` header means
the article had no summary/transcript split and the whole body was saved; enrich the speaker
paragraphs only. Manual pull of one article: `python investing.py fetch <url>` (a non-earnings
transcripts URL is routed here automatically).

**Coverage reality:** titles name the company the way Investing.com writes it (`Supermicro`,
`Credo`, `Arista`); `match_company` uses the same spellings/aliases as `enrich intl`, so a company
that keeps being missed needs an `ALIASES` entry in `investing.py`, not a hand paste.
