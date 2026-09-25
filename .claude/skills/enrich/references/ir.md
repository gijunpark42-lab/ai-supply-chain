### Workflow 2h — Company IR press releases (`enrich ir`)

**What it is.** News a company issues itself that no call or transcript carries: trade-show launches
(ECOC, OFC, Computex), partnerships, design wins, investor-day targets. Source rule (user, 2026-09-24):
with no transcript, only company-issued documents count — never an article about them. `ir_pull.py`
reads each company's own IR RSS feed (free, no key) and saves the release verbatim.

**Trigger:** the user says `enrich ir` (or asks for a company's recent releases).

0. **Already done? Check first.** `python ir_pull.py status --company "<Company>"` lists every release of that
   company with its state (pending / enriched:<date>). If nothing is pending and a sync adds nothing new, tell
   the user it is already done and stop — do not re-read or re-enrich. `sync` never re-saves a URL it has
   handled (sync_state.json `seen`), and `done` stamps each row `enriched:<date>`.
1. `python ir_pull.py sync` — every registered feed (`--company X` for one). A company's FIRST sync reaches back
   to its latest earnings call in the graph (capped at 120 days; 30 days if it has none) — anything earlier was
   on that call. Later syncs only pick up URLs not yet handled. Feeds hold only their ~10 newest releases
   (median ~140 days, but CoreWeave / Equinix / Silicon Motion only ~3 weeks), so run it at least every 2-3 weeks
   or busy issuers drop items. It runs locally: the computer must be on when it runs.
   New releases land in `transcripts/ir/` with a NOT-a-transcript NOTE and a
   `# source label: <Company> press release: <short title> (MM-DD-YYYY)` header, and are queued in
   `ir/pending.json`. Notices are skipped with the reason recorded in `ir/sync_state.json`: dividends,
   event-participation notices, results-date / webcast notices, shareholder meetings, daily buyback notices
   ("Transaction in Own Shares"), and — for US-listed names — the quarterly FINANCIAL results release
   (edgar_pull.py + the call already cover it; clinical-trial "results" are news and are kept). A release already
   saved by hand elsewhere under transcripts/ (matched on its SOURCE URL) is skipped, never saved twice.
2. Missing feeds: `python ir_pull.py discover [--company X]` tries investor./investors./ir.<name>.com with
   the common RSS paths and accepts a feed only if EVERY distinctive word of the company name (or its ticker)
   is in the channel title — "Applied Optoelectronics" once matched Applied Industrial's feed. That host guess
   misses companies whose IR site has another name (intc.com, ir.aboutamazon.com, investor.ti.com). For those:
   find the OFFICIAL IR news page, then `python ir_pull.py discover --company "<Company>" --url <ir-news-page>` —
   it reads the page's `<link rel="alternate" type="application/rss+xml">`, any RSS link on the page, and the
   common paths on that host, under the same strict ownership check. Last resort:
   `python ir_pull.py add "<Company>" <feed-url>` after checking the feed by eye.
   **No RSS at all (most Japanese / Taiwanese / Korean / Chinese / many European sites): list-page mode.**
   `python ir_pull.py add "<Company>" <list-page-url> --page --link-re "<regex matching ONE release URL>"`
   reads the HTML list of releases. Options when needed: `--date-order mdy|dmy` (09/10/2026-style dates),
   `--title-from-page` (link text carries teasers/tags; use the release headline), `--title-strip-re` (cut
   category tags out of the link text). Extra feed-entry keys set by hand: `"date_from": "page"` (list dates
   drift onto the neighbouring entry -- Infineon; read each release's own date), `"insecure_tls": true` (the
   company's own site has a broken certificate chain -- Zhen Ding), `"lang"` (non-English releases: the label
   uses "release <url id>", the file keeps the original headline, entries are still written in English).
   PDF releases are read whole (pypdf + cryptography). Dates: URL > the date label inside the link > the text
   beside the link > the release page. A list config is registered only after a date spot-check (the assigned
   date must be printed on the release) -- "beside" dates that disagree with the page switch to date_from=page.
   **JS-rendered news page: JSON mode** -- `"kind": "json"` with the GET endpoint the page's own script calls
   (`items_key`, `title_key`, `date_key`, `link_key` or `link_tpl`, optional `link_re` filter); JSONP, a BOM and
   leading comments are handled (Pronexus EIR `eir-parts.net`, irpocket, AGC, Merck, Adobe, Novo, Roche,
   Mitsubishi Electric, Macronix). POST-only / token-gated endpoints are never used. A few feeds carry a year in
   the URL (Macronix `Year=2026`, Roche `year=2026`, Nanya `year=2026`, Kyocera `2026.html`, Sumitomo Bakelite
   `topics/2026`) -- bump them in January.
   **Body quality gate:** a saved release must have article prose (`prose_ok`: minimum length AND at least two
   sentence endings), else the RSS item's own full text (`content:encoded`) is tried, else the row fails. This
   stops JS-rendered pages (SK hynix newsroom) from saving menus / related-links lists as a "release".
3. Enrich with `subagent_type: "enricher"` agents, split by company. Facts only: specs, availability dates,
   counts, targets, named partners. "First"/"leading" are the company's claims; demos are not shipping;
   hedges stay. Depth rule: skip anything already on the node. No screener slots from product releases
   (investor-day targets from a company release may fill `guidance` only if no call/filing states them).
   Edges/contracts only when the release states a real supply or customer relationship — never from a joint
   demonstration.
4. Schedule-only releases (speaker line-ups, "to showcase at" booth lists with no facts) yield no entries —
   remove the row: `python ir_pull.py done --label "<label>" --why "no new facts"`. After enriching a row, the same
   `done --label` (it stamps `enriched:<date>`). Never `done --all` unless every row was handled.
5. `python graph_build.py --sync`, then the script checks; append the labels to `verify_queue.json`
   (the Opus verifier runs automatically at 5+ pending).
