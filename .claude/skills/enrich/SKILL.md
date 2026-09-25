---
name: enrich
description: Enrich chains from an earnings call, filing, article or event transcript. Use for "enrich", "enrich dart", "enrich us", "enrich intl", "enrich tw", "enrich edgar", "enrich conference", "enrich ir", "Transcript:<company>", or any pasted/URL transcript. Covers the ADD-only patch format, JOB 1-5 (quarterly_data, contracts, new nodes, new edges, topics/slot/capex tags), the canonical source-label format and the graph_build.py --sync + verify step.
---

### Workflow 2 — Enrich a chain with a transcript or article

**Source hierarchy, agent standard and verification cadence (user rule, 2026-09-24 — read before any enrich):**
1. Transcripts: read every line; capture what MANAGEMENT said that is material to the company; exclude analyst
   statements unless management confirms them. Never filter by chain theme.
2. No transcript: company-issued documents only — IR press releases, SEC/DART filings, company decks. Fetch from the
   official URL, save verbatim to `transcripts/non_transcript_sources/` with a NOT-a-transcript NOTE and a
   `# source label:` header naming the doc type, e.g. `Marvell ECOC 2026 press release (09-21-2026)`.
3. Articles are pointers only — find the company's own release and enrich from that. No AI-summary sites,
   newsletters, social posts or exhibitor boilerplate. No company doc = leave the gap.
4. Product/event releases weigh less than filings: "first"/"leading" are claims, demos are not shipping,
   no screener slots, no edges/contracts from joint demos.
5. Spawn enrichment and verification agents with `subagent_type: "enricher"` (pinned Opus, effort high).
   Numeric/locator/collision checks are scripts.
6. Script checks (pre-flight + verify_graph) run on every batch before applying. The independent Opus verifier
   may be batched over ~5 jobs on the same chain/company group.
7. AUTO-VERIFY without being asked: after each apply, append the labels to repo-root `verify_queue.json`; at 5+
   pending (or at the end of a multi-job session) spawn an `enricher` verifier over them, then clear the verified rows.

**Trigger:** User gives a URL or paste of an earnings call, news article, or event transcript, plus a chain filename and a source label (e.g. "NVIDIA Q1 FY2027 (05-28-2026)" — see canonical format below).

**Output:** A PATCH file `patches/<company>_<quarter>.json` holding ONLY the additions (ADD-only) —
NOT a direct edit of `chains/`. Then `python graph_build.py --sync` is run — it first merges every
pending patch into the chains (`apply_patches.py`), rebuilds the graph, regenerates the Timelines /
Screener / Capex views from the tags added in JOB 5, and syncs `web/public/data`.
**Then it audits the additions:** `graph_build.py` passes the labels of the patches it just applied
to `verify_graph.py`, which re-checks every new entry against the source file (label resolves to a
file, numbers in `figure`/`units`/`value` appear in it, the counterparty is named, no Korean). Read
its `[fail]`/`[warn]` lines before reporting: a `number_not_in_source` on a figure you computed
(a sum, a QoQ delta) is fine — say so; a `source_not_found` means the transcript was not saved
under the expected name — fix the filename; anything else, fix the patch and re-run. To re-check
one label by hand: `python -X utf8 verify_graph.py --label "<label>"`.

**Why patches instead of editing chains/ directly (do not skip this):** several enrichment jobs
often run in parallel and many companies share one chain file (every power company → `power_cooling.json`,
every optical name → `optical_networking.json`). "Read chain → think for 10 minutes → write the whole
chain back" silently overwrites whatever another job added in those 10 minutes — no error, valid JSON,
data just gone (a *lost update*). A patch file has a unique name, so nothing collides, and
`apply_patches.py` is the single writer of `chains/`: it re-reads the live file, finds-or-creates each
player/edge by name, appends the new entries, and saves — all in milliseconds. It is idempotent
(re-applying skips duplicates) and moves each patch to `patches/applied/` as a receipt.

How to work: READ the chain (and the transcript) as before to decide what to add and where; then
WRITE those decisions as a patch. Patch shape (see the `apply_patches.py` docstring for the full spec):
```json
{ "source": "<label>",
  "chains": { "components/power_cooling.json": { "players": [
    { "company": "Vistra", "domain": "power", "sector": "Generation",       // locator: layer|domain + sector (+sub_sector); used only if the player must be CREATED
      "product": "…",                                                        // used only when created
      "quarterly_data": [ { "quarter": "<label>", "signal": "…", "figure": "…", "topics": [] } ],
      "connects_to": [ { "company": "Meta", "relationship": "…",             // relationship used only if the edge must be CREATED
                         "contracts": [ { "source": "<label>", "signal": "…", "topics": [] } ] } ] } ] } } }
```
Every player in a patch carries its locator even when it already exists — the merge ignores it if
the player is found, and the patch stays self-describing.

Four jobs — all ADD-only, never remove or overwrite existing data:

**JOB 1 — Node-level figures (quarterly_data):**
If the transcript mentions a company already in the chain (revenue, growth %, capacity, demand, shortages), add a `quarterly_data` entry to that player.
```json
{ "quarter": "<label>", "signal": "exact quote or paraphrase", "figure": "the number, or 'no specific figure'" }
```

**JOB 2 — Edge-level deal detail (contracts):**
If the transcript reveals a concrete deal, contract, or commitment on an existing edge (units shipped, $ value, delivery date, deal type), add a `contracts` entry to that edge.
```json
{
  "source": "<label>",
  "signal": "what was said",
  "units": "quantity or 'no specific figure'",
  "value": "$ amount or 'no specific figure'",
  "date_signed": "year/quarter or 'not stated'",
  "type": "supply agreement / deployment / partnership / etc."
}
```

**JOB 3 — New companies:**
If the transcript names a company not yet in the chain that passes the litmus test, add it to the correct layer→sector (or domain→sector) with empty `connects_to` and at least one `quarterly_data` entry from the transcript.

**JOB 4 — New edges:**
If the transcript explicitly states a supply or customer relationship between two companies already in the chain that isn't yet in `connects_to`, add it with any relevant `contracts` entries.

**JOB 5 — Tag every new entry for the derived views (Timelines / Screener / Capex):**
The Timelines, Screener and Capex tabs are GENERATED from the graph by `derive.py` (run by
`graph_build.py`). They are never hand-maintained any more. The generator only knows where an
entry belongs through these optional keys, so add them to EVERY `quarterly_data` entry you write
(and `topics` to every `contracts` entry):
```json
{ "quarter": "<label>", "signal": "...", "figure": "...",
  "topics": ["ocs", "cpo"],          // timeline ids this entry belongs to; [] = none (pure financials)
  "slot":   "guidance",              // OPTIONAL screener column this entry fills (one entry per slot)
  "capex":  { "field": "capex_year", "busd": 220, "display": "~$220B", "period": "2026 plan" } }
```
- `topics` ids = the filenames in `timelines/`: `cpo`, `cpu`, `foundry`, `hbm`, `nand_storage`, `ocs`,
  `optical_speed`, `packaging_substrate`, `power_cooling`, `product_launches`, `silicon_photonics`,
  `supply_tightness`, `transitions`. Always write the key — `[]` opts the entry out of the keyword
  fallback that covers untagged legacy entries.
- `slot` ∈ `revenue_growth` | `guidance` | `backlog_or_b2b` | `supply_status` | `next_catalyst`.
  Tag the ONE best entry per slot; the screener shows the latest-dated tagged entry per slot.
- `capex` (hyperscalers / neoclouds only): `field` ∈ `capex_q` | `capex_year` | `backlog` | `signal`.
  `busd` + `display` (+ `period` for capex_year, `metric`/`growth` for backlog) drive the bar charts.
- Rules the generator enforces: graph keeps full history; every derived view is REPLACE-WITH-LATEST
  per company; curated baseline files (`timelines/*.json`, `company_metrics.json`, `capex_backlog.json`)
  are inputs that are never auto-written and act as fallback; outputs land in `graph/` — never hand-edit those.

**Global enrichment rules:**
- Do NOT invent companies or deals. Only use what the transcript explicitly states.
- Do NOT add a company already in the chain — find it and update it instead.
- Use the same source label consistently across the entire chain (every node/edge touched by one transcript gets the identical label). The label identifies WHICH source document a data point came from. Use the canonical format below — never mix formats.
- Keep every existing node, edge, and data point intact. Only ADD.

**Canonical source-label format (FIXED — use everywhere `quarter`/`source` appears):**

| Source type | Format | Example |
|-------------|--------|---------|
| Earnings call | `[Company] Q[N] FY[YYYY] (MM-DD-YYYY)` | `NVIDIA Q1 FY2027 (05-28-2026)` |
| Event (keynote/conference) | `[Company] [Event] [YYYY] (MM-DD-YYYY)` | `NVIDIA GTC 2026 (03-18-2026)` |
| News / research note | `[Source] (MM-DD-YYYY)` | `Goldman Sachs optical note (04-15-2026)` |

Rules: (1) Always write `FY` for earnings — NVIDIA's fiscal year is offset from the calendar (NVDA Q1 FY2027 = the quarter ending ~April 2026); calendar-year filers (TSMC, SK Hynix) have FY = calendar year. (2) The date in parentheses is the SOURCE DOCUMENT date (earnings-call date / event date / article publish date), NOT the quarter-end date. (3) `[Company]` is the node's canonical name (`NVIDIA`, not `NVDA`).

---


---

## Source-specific pipelines — read the matching reference file

The six sub-workflows below build ON TOP of everything above. When the user triggers one,
read its reference file and follow it together with this file.

| Trigger | Region / source | Read |
|---|---|---|
| `enrich dart`  | Korean listed names — DART filings (정기보고서 / 잠정실적 / 공급계약) | `references/dart.md` |
| `enrich us`    | US-listed names — Alpha Vantage full call transcripts (`av.py`)      | `references/us.md`   |
| `enrich intl`  | Taiwan / Japan / Europe / HK / China — Investing.com (`investing.py`) | `references/intl.md` |
| `enrich tw`    | Taiwan Chinese-language 法說會 — video + whisper (`tw.py`)            | `references/tw.md`   |
| `enrich edgar` | US-listed names — SEC 8-Ks (every exhibit whole) + 10-K / 10-Q customer, supplier, backlog paragraphs + XBRL (`edgar_pull.py`); completeness contract: read once, never reopen | `references/edgar.md` |
| `enrich conference` | Every listed name (US too) — investor-conference fireside chats via Investing.com (`investing.py conferences`); depth rule, multi-agent + verification loop, memory update | `references/conferences.md` |
| `enrich ir` | Company-issued IR press releases via each company's own RSS feed (`ir_pull.py`); trade-show launches, partnerships, investor-day targets; facts only | `references/ir.md` |

A bare `enrich` with no region means: run the API pipelines automatically — including `ir_pull.py sync`
(company IR press releases), so one `enrich` covers calls, filings, conferences AND company releases.
`enrich ir <Company>` runs only that company's feed (`ir_pull.py sync --company "<Company>"`).
Pasted text or a URL from the user overrides the pipeline — enrich that source directly under this file's rules.
