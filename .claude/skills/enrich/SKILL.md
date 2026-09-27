---
name: enrich
description: Enrich the supply-chain graph from company sources — earnings calls, investor-conference talks, SEC/DART filings and important company IR press releases. Use for "enrich" (runs what ENRICH_STATUS.md recommends), the market commands "enrich us", "enrich korea", "enrich taiwan", "enrich japan", "enrich europe", "enrich china", the source commands "enrich us calls", "enrich edgar", "enrich dart", "enrich intl", "enrich tw", "enrich conference", "enrich ir", "Transcript:<company>", or a pasted/URL transcript or company release. Covers the status board, what to capture (facts, company guidance and management comments — never analyst opinion), the ADD-only patch format, JOB 1-5, labels, screener slots, checks and verification.
---

# Workflow 2 — Enrich

Common rules for EVERY source (consolidated 2026-09-26 at the user's request; where an older note in memory
or a reference file disagrees, this file wins). The source-specific steps live in `references/` (table at the end).

## 0. Start and finish every run with the status board

1. **Before anything, read `ENRICH_STATUS.md`** (repo root). It lists, per market, what is fetched and waiting,
   which companies are overdue for a call or were never enriched, where no source exists, and the ordered
   **Run next** list. If its "Generated" time is older than ~12 hours, or another session may have run since,
   refresh it first: `python -X utf8 enrich_status.py` (seconds, no model tokens). Do not re-scan pipelines,
   queues or the graph to find out what is done — the board already did.
2. **At the end**, `python graph_build.py --sync` rebuilds the board. If the run applied nothing (empty queues),
   run `python -X utf8 enrich_status.py` anyway. Paste the board's **Run next** block into your report.
3. **Record what no script can know** (the coordinator only — parallel agents put it in their report):
   - a source that does not exist: `python -X utf8 enrich_status.py mark "<Company>" ["<Company>" …] --source call|dart|ir|conference|edgar --why "<what was checked>" [--recheck YYYY-MM-DD]`
     (default recheck in 90 days; a marked company leaves the board's missing lists until then);
   - where a run stopped or what the next run must know: `python -X utf8 enrich_status.py note <US|KR|TW|JP|EU|CN|all> "<text>"`;
   - **a judgment these rules do not settle — ask the user, do not guess** (user, 2026-09-26): a new company whose
     role is ambiguous, an unclear placement, whether a fact is material. Record it with
     `python -X utf8 enrich_status.py ask "<subject>" --question "<…>" [--label "<source label>"]`, keep the data
     safe meanwhile (ADD-only, on the filer's node), and list the open questions at the top of the report (a live
     session may also ask them directly). The user's answer closes it: `enrich_status.py resolve "<subject>" --answer "<…>"`.

## 1. Commands

| The user says | What runs |
|---|---|
| `enrich` | The board's **Run next** list, top to bottom (refresh the board first). |
| `enrich us` | Every US gap except SEC filings — calls (+ defeatbeta fallback), overdue / never-enriched companies, conference talks, IR releases. Meant to run daily. |
| `enrich korea` | DART filings (+ backfill of Korean companies with no filing enriched), conference talks, IR releases. Korean calls have no pipeline yet (board: "Needs a decision or setup"). |
| `enrich taiwan` / `enrich japan` / `enrich europe` / `enrich china` | That market's calls (Investing.com; Taiwan Chinese-language calls via tw.py), conference talks, IR releases. |
| `enrich edgar` | SEC 8-K / 10-K / 10-Q (weekly; not part of `enrich us`). |
| `enrich us calls` · `enrich dart` · `enrich intl` · `enrich tw` · `enrich conference` · `enrich ir` | One source, across every market it covers (reference table below). |
| a pasted transcript / URL / release, or `Transcript:<company>` | Save the source (§2), then enrich it under these rules. For `Transcript:<company>` fetch the latest full call yourself (US: `av.py` / `utils/defeatbeta_fetch.py`; others: the market's source) and state the call date before enriching. |

The step-by-step market procedures are in `references/markets.md`.

## 2. What to capture (user rule, 2026-09-26)

The map records **facts** and **what the company itself says**.

**Capture**
- Facts: revenue, growth, margins, capacity, utilisation, backlog / RPO, capex, units, prices; named customers,
  suppliers and partners; contracts and their terms; product generations; shipment / production / availability
  dates; specs.
- Company guidance and targets: quarter or year outlook, investor-day targets, guidance raised or cut.
- Management's own views — CEO, CFO and other executives on demand, supply, pricing, competition, technology
  transitions — written as attributed statements ("CEO: …", "management expects …") with the hedge kept, never
  rewritten as a fact.

**Do not capture**
- Analyst or moderator questions, estimates, opinions, ratings or price targets. When management confirms an
  analyst's number, the number is management's — attribute it to the executive who confirmed it.
- Third-party articles, research notes, newsletters, AI-summary sites, social posts. They are pointers only:
  find the company's own document and enrich from that, or leave the gap.
- Financing terms (offerings, notes, convertibles, credit lines, conversion prices, use of proceeds), governance,
  executive pay, personnel changes, awards and rankings, CSR, event / webcast / trade-show schedules.
  A financing release can still carry operating facts ("12-inch capacity fully loaded", "the Texas fab passed
  Tier-1 customer qualification"): keep those, drop the deal terms.

**Where the facts may come from**
1. Transcripts (earnings calls, investor-conference talks): read every line, prepared remarks and the full Q&A;
   take everything management says that is material to the company — never filter by chain theme.
2. No transcript: company-issued documents only — SEC / DART filings, IR press releases, company decks,
   fetched from the official source and saved verbatim (`transcripts/ir/` via `ir_pull.py`, or
   `transcripts/non_transcript_sources/` with a NOT-a-transcript NOTE and a `# source label:` header).
3. **IR press releases: only the important ones** — a named supply / customer agreement or design win, capacity /
   capex / production facts, company guidance or targets, a product launch or availability with specs and dates,
   the operating facts of an acquisition (never its price), a fab / facility start. Anything else yields no entry:
   close the row with `python ir_pull.py done --label "<label>" --why "no material facts"`. (`ir_pull.py` already
   skips the clear notices by headline: dividends, buybacks, event and results-date notices, personnel, awards,
   CSR, trade-show exhibit notices, columns and surveys.)
4. Product and event releases: "first" / "leading" are the company's claims (attribute them); a demo is a demo,
   never "shipping"; no edges or contracts from joint demonstrations.

Add nothing the source does not state: no background knowledge, no inferred ownership, dates or customers, and no
arithmetic in `figure` / `units` / `value` (write the numbers as stated; verify flags derived ones).

## 3. Patch format — ADD-only, never a direct edit of chains/

**Output:** a PATCH file holding ONLY the additions — `patches/<company>_<quarter>.json` (calls),
`patches/conf_<file stem>.json`, `patches/ir_<company>_<date>.json`, `patches/edgar_<file stem>.json`.
**One source per patch:** every entry carries the patch's `source` label — `graph_build.py` re-verifies only the
patch label, so an entry under another label would never be checked. Then `python graph_build.py --sync` is run —
it first merges every pending patch into the chains (`apply_patches.py`), rebuilds the graph, regenerates the
Timelines / Screener / Capex views from the tags added in JOB 5, rebuilds the status board and syncs
`web/public/data`.

**Why patches instead of editing chains/ directly (do not skip this):** several enrichment jobs
often run in parallel and many companies share one chain file (every power company → `power_cooling.json`,
every optical name → `optical_networking.json`). "Read chain → think for 10 minutes → write the whole
chain back" silently overwrites whatever another job added in those 10 minutes — no error, valid JSON,
data just gone (a *lost update*). A patch file has a unique name, so nothing collides, and
`apply_patches.py` is the single writer of `chains/`: it re-reads the live file, finds-or-creates each
player/edge by name, appends the new entries, and saves — all in milliseconds. It is idempotent
(re-applying skips duplicates) and moves each patch to `patches/applied/` as a receipt.

How to work: READ the chain (and the transcript) to decide what to add and where; then
WRITE those decisions as a patch. Patch shape (see the `apply_patches.py` docstring for the full spec):
```json
{ "source": "<label>",
  "chains": { "components/power_cooling.json": { "players": [
    { "company": "Vistra", "domain": "power", "sector": "Generation",       // locator: layer|domain + sector (+sub_sector)
      "product": "…",
      "quarterly_data": [ { "quarter": "<label>", "signal": "…", "figure": "…", "topics": [] } ],
      "connects_to": [ { "company": "Meta", "relationship": "…",             // relationship used only if the edge must be CREATED
                         "contracts": [ { "source": "<label>", "signal": "…", "topics": [] } ] } ] } ] } } }
```
Every player in a patch carries its locator even when it already exists — the merge ignores it if
the player is found, and the patch stays self-describing.

## 4. The five jobs — ADD-only, never remove or overwrite existing data

**JOB 1 — Node-level figures (`quarterly_data`):** facts about a company already in the chain (revenue, growth %,
capacity, demand, shortages, guidance, management views).
```json
{ "quarter": "<label>", "signal": "exact quote or close paraphrase, attributed", "figure": "the number, or 'no specific figure'" }
```

**JOB 2 — Edge-level deal detail (`contracts`):** a concrete deal, contract or commitment on an existing edge.
```json
{ "source": "<label>", "signal": "what was said", "units": "quantity or 'no specific figure'",
  "value": "$ amount or 'no specific figure'", "date_signed": "year/quarter or 'not stated'",
  "type": "supply agreement / purchase / customer share / deployment / capacity lease / licence / partnership / …" }
```
A filed "customer X is n% of revenue" fact uses `type` `customer share` (DART) or `10-K customer concentration` /
`10-Q customer concentration` (EDGAR) — the Exposure tab reads exactly these.

**JOB 3 — New companies: added with an independent Claude approval** (user decision 2026-09-26: Claude
approves, not the user). When a source names a company that is not in the chain and passes the litmus test
("does its stock directly benefit from this product being built and sold?"):
1. The enricher adds it to its patch as a player with a full locator (layer/domain + an existing sector +
   `product`) and describes it in the patch's top-level `new_nodes` block (apply_patches ignores this block):
   ```json
   "new_nodes": { "<Canonical Name>": { "ticker": "…", "exchange": "…", "country": "…",
       "why": "how its stock benefits from this product", "evidence": "the source line naming the relationship",
       "approved": "" } }
   ```
2. An independent `enricher` verifier — never the agent that proposed it — gives each proposal one of three answers:
   - **approve** when every point clearly holds: a real participant in that product (litmus), named by management
     in a stated supply / customer relationship, not an existing node under another spelling (naming rules),
     placed on the fixed slugs and an existing sector. It writes `"approved": "opus verifier <date>: <one line>"`.
   - **reject without asking** what is clearly not a supply-chain participant (user, 2026-09-26: banks and the like
     are not needed): banks, lenders, insurers, investors / funds, governments and agencies, distributors, EPC /
     construction contractors, generic end customers, divisions, sub-brands, product names, and the do-not-add
     list (the 2026-09-05 cleanup removals, Core42, AES, Nanjing Casela).
   - **ask the user** when it is genuinely ambiguous — its role in this product is indirect or unclear, a
     borderline litmus case, a private company, an affiliate or JV, no sector fits. It writes
     `"ask_user": "<the question>"`.
3. The coordinator adds each approved company's `company_metadata.json` entry (ticker, exchange, country,
   status), then applies. Rejected or asked → the player comes out of the patch and the deal goes on the node of
   the company whose document it is, as `quarterly_data` with `counterparty` / `counterparty_role` keys
   ("Customer X: …" / "Supplier X: …"), so no fact waits for the answer. An open question is recorded —
   `python -X utf8 enrich_status.py ask "<Company>" --question "<…>" --label "<source label>"` — and shows on the
   status board and the web Status tab under "Needs a decision" until the user answers; then the coordinator adds
   the node (or not) and closes it with `enrich_status.py resolve "<Company>" --answer "<the decision>"`.
4. Every added node is named in the run report and the HANDOFF log — structure never changes silently.
   `utils/check_patch.py` refuses a new node without `approved`, without its metadata entry, or under a removed /
   duplicate name.

**JOB 4 — New edges:** only when the source explicitly states a supply or customer relationship, the speaker is
management (not an analyst), both companies are players in that chain, and it is not a joint demonstration or a
list-only mention. Existing edges may point outside the chain file (edges merge across chains by name).

**JOB 5 — Tag every new entry for the derived views (Timelines / Screener / Capex):**
The Timelines, Screener and Capex tabs are GENERATED from the graph by `derive.py` (run by `graph_build.py`) and
never hand-maintained. The generator only knows where an entry belongs through these keys:
```json
{ "quarter": "<label>", "signal": "...", "figure": "...",
  "topics": ["ocs", "cpo"],          // timeline ids; [] = none (pure financials)
  "slot":   "guidance",              // OPTIONAL screener column (see the slot rules below)
  "capex":  { "field": "capex_year", "busd": 220, "display": "~$220B", "period": "2026 plan" } }
```
- `topics` ids = the filenames in `timelines/`: `cpo`, `cpu`, `foundry`, `hbm`, `nand_storage`, `ocs`,
  `optical_speed`, `packaging_substrate`, `power_cooling`, `product_launches`, `silicon_photonics`,
  `supply_tightness`, `transitions`. Always write the key (on contracts too) — `[]` opts out of the keyword
  fallback that covers untagged legacy entries. Tag a topic only where it is the entry's subject.
- `capex` (hyperscalers / neoclouds only): `field` ∈ `capex_q` | `capex_year` | `backlog` | `signal`;
  `busd` + `display` (+ `period` for capex_year, `metric`/`growth` for backlog) drive the bar charts.
- Rules the generator enforces: the graph keeps full history; every derived view is REPLACE-WITH-LATEST per
  company; curated baseline files (`timelines/*.json`, `company_metrics.json`, `capex_backlog.json`) are inputs
  that are never auto-written; outputs land in `graph/` — never hand-edit those.

**Screener slots** — `slot` ∈ `revenue_growth` | `guidance` | `backlog_or_b2b` | `supply_status` |
`next_catalyst`; the screener shows the latest-dated tagged entry per slot per company. Which source may fill
which slot:

| Source | Slots |
|---|---|
| Earnings call, investor-conference talk (management speaking), DART periodic report | any — the ONE best entry per slot |
| DART preliminary results (잠정실적) | `revenue_growth` only (the later periodic report supersedes it) |
| DART supply contract with an undisclosed customer | `backlog_or_b2b` only |
| 8-K | any, but only when newer than every same-slot entry of the company; otherwise none |
| 10-K / 10-Q | none |
| Company IR press release | `guidance` (company guidance / targets), `next_catalyst` (a new product launch, availability, production or shipment start with a date), `backlog_or_b2b` (a named order, contract or design win), `supply_status` (capacity, utilisation, sold-out) — only what the release itself states; never `revenue_growth`; a demo never fills a slot |

Never give a company a second entry with the same slot and the same date (the screener cannot choose), and leave
the key out when an entry fills no slot (never `"slot": null`). `utils/check_patch.py` enforces all of this.

## 5. Source labels — one canonical format per source (FIXED; use everywhere `quarter` / `source` appears)

| Source | Format | Example |
|---|---|---|
| Earnings call | `[Company] Q[N] FY[YYYY] (MM-DD-YYYY)` | `NVIDIA Q1 FY2027 (05-28-2026)` |
| DART periodic / preliminary report | same shape, dated the filing; the 사업보고서 is Q4 of the year it covers | `SK Hynix Q2 FY2026 (08-14-2026)` |
| DART supply contract | `[Company] DART supply contract (MM-DD-YYYY)` | `Sanil Electric DART supply contract (08-20-2026)` |
| SEC filing | `[Company] 8-K` / `10-K` / `10-Q` `(MM-DD-YYYY)` | `Lumentum 8-K (08-11-2026)` |
| Investor conference / company event | `[Company] [Event] [YYYY] (MM-DD-YYYY)` | `Credo Goldman Sachs conference 2026 (09-10-2026)` |
| Company IR press release (saved by `ir_pull.py` or by hand) | `[Company] press release: [headline, ≤ 60 chars] (MM-DD-YYYY)`; a non-English headline becomes `release <id from the URL>` | `Supermicro press release: Supermicro Now Shipping NVIDIA Vera Rubin NVL72 Racks (09-23-2026)` |
| Other company document (deck, investor-day material) | `[Company] [document type]: [title] (MM-DD-YYYY)` | — |
| Third-party note | legacy only — no new ones (articles are pointers, §2) | `Goldman Sachs optical note (04-17-2026)` |

Rules: (1) always `FY` for calls and periodic reports; fiscal years can be offset (NVIDIA Q1 FY2027 = the quarter
ending ~April 2026); calendar-year filers (TSMC, SK Hynix, Korean filers) have FY = calendar year. (2) The date is
the SOURCE DOCUMENT date (call, filing, event or release date), not the quarter end. (3) `[Company]` is the
canonical node name — the label prefix must equal the node name, or the pipelines treat the company as never
enriched and pull it again. (4) One source = one label on every node and edge it touches; never mix a call label
with a filing label of the same quarter. (5) Take the label from the saved file's `# source label:` header
verbatim; do not rename or merge events by hand (two spellings of one event are harmless, a wrong merge is not).
(6) A DART report shares the call label shape on purpose (history and the pipelines' "latest label + 1" quarter
logic depend on it); tools that must tell them apart use the source file's folder, as `enrich_status.py` does.

## 6. Placement, duplicates and depth

- **One fact, one node.** Company-wide facts (total revenue, guidance, customer concentration) go on the placement
  that already holds the company's slot-tagged company-wide entries; a segment fact that maps to exactly one
  placement goes there; an ambiguous one goes on the company-wide placement. Never copy an entry into every chain
  the company appears in.
- **Edge meaning must match.** A contract goes on an edge only if it describes that edge's relationship in that
  direction; otherwise on the correct-direction edge (when both companies are players in the chain) or on the
  filer's `quarterly_data` naming the counterparty.
- **The earnings call is the primary source.** Every later source — conference talk, IR release, 8-K, the DART
  periodic report after the preliminary results — adds only what the company's node does not already state for
  that period: new or changed numbers, newly named customers / partners, transitions and constraints the call did
  not mention. A restatement yields no entry (report it as `restates <label>`). So calls run first (§1 order).
- **Same-day release and 8-K:** the daily `enrich us` takes the IR release; the weekly `enrich edgar` then skips
  facts the same-day release already put on the node (the 8-K exhibit is usually that release).
- Exact duplicates inside one chain file may be removed (integrity rule); everything else is ADD-only.

## 7. Checks and verification — one model for every source

1. **Pre-flight every patch before it is applied:** `python -X utf8 utils/check_patch.py <patch> …`
   (`enrich edgar` uses `utils/check_edgar_patch.py`, which accepts only the SEC filing as the source).
   Fix until `RESULT: clean`. It checks numbers, the named counterparty, English only, the locator, new nodes
   (approved, in the metadata, not a removed / duplicate name) and edges, keys and tags, the slot rules, one fact
   one node, one source per patch.
2. **Apply once:** `python graph_build.py --sync` — the coordinator only; enrich agents never run it or
   `apply_patches.py`. It re-verifies the labels just applied (`verify_graph.py`): read every `[fail]` / `[warn]`.
   A `number_not_in_source` on a figure you computed means the arithmetic must go; `source_not_found` means the
   source file was not saved under the label; anything else — fix the patch and re-run. One label by hand:
   `python -X utf8 verify_graph.py --label "<label>"`.
3. **Independent Opus check, without being asked:** append the applied labels to repo-root `verify_queue.json`;
   at 5+ pending (or at the end of a multi-job session) spawn an `enricher` verifier over them (batch labels of
   the same chain / company group). It re-reads every source and checks accuracy AND §2 (no analyst content, no
   financing terms, important releases only, attribution and hedges kept, English only); it corrects or deletes
   entries (corrections go through a patch in `patches/corrections/`), lists facts it believes were missed in its
   report (the coordinator decides; it does not add them), and the verified rows move to `verified`.
4. **Parallel by default (user, 2026-09-26): up to 20 `enricher` agents at once** (`subagent_type: "enricher"`,
   pinned Opus, effort high), fewer when the work is small (about one agent per 2–5 sources; one source = one
   agent). Splitting never costs accuracy because: all of one company's sources go to the same agent (the depth
   rule stays consistent); each agent writes only its own patch files — never chains/, `company_metadata.json`,
   queues, `verify_queue.json` or `enrich_marks.json`; the coordinator alone runs `utils/check_patch.py` over every
   patch, sends new-node proposals to a separate verifier, dedupes proposals two agents made for the same company,
   applies once, closes the queues and records marks. Verifiers run in parallel too (~5 labels each, grouped by
   chain / company). Collection and the number / locator / collision checks are scripts, not models.

## 8. English only in chains/

Every label, signal, figure, units, value, type, relationship and product written to chains/ is English.
Translate Korean / Chinese / Japanese sources as you go; romanise people and agencies; map company names to the
canonical English node (`SK하이닉스` → `SK Hynix`, never a Korean-named duplicate). Amounts keep their currency but
in English: "KRW 27.8 trillion", "US$1.43 billion (NT$45.4 billion)" — not "27조 8,000억원" or "14.32億美元".
`verify_graph.py` and `utils/check_patch.py` fail on any Hangul, kanji / hanzi or kana (since 2026-09-26).

---

## Source-specific pipelines — read the matching reference file

These build ON TOP of everything above. When a command fires, read its reference file and follow it with this file.

| Trigger | Region / source | Read |
|---|---|---|
| `enrich us` / `korea` / `taiwan` / `japan` / `europe` / `china` | one home market, every source that serves it, in order | `references/markets.md` |
| `enrich dart` | Korean listed names — DART filings (정기보고서 / 잠정실적 / 공급계약) | `references/dart.md` |
| `enrich us calls` | US-listed names — Alpha Vantage full call transcripts (`av.py`), defeatbeta fallback | `references/us.md` |
| `enrich intl` | Taiwan / Japan / Europe / HK / China — Investing.com (`investing.py`) | `references/intl.md` |
| `enrich tw` | Taiwan Chinese-language 法說會 — video + whisper (`tw.py`) | `references/tw.md` |
| `enrich edgar` | US-listed names — SEC 8-Ks (every exhibit whole) + 10-K / 10-Q customer, supplier, backlog paragraphs + XBRL (`edgar_pull.py`); completeness contract: read once, never reopen | `references/edgar.md` |
| `enrich conference` | Every listed name (US too) — investor-conference fireside chats via Investing.com (`investing.py conferences`); depth rule, multi-agent + verification loop, memory update | `references/conferences.md` |
| `enrich ir` | Company-issued IR press releases via each company's own feed (`ir_pull.py`); important releases only, facts only | `references/ir.md` |

`enrich ir <Company>` runs only that company's feed (`ir_pull.py sync --company "<Company>"`).
Pasted text or a URL from the user overrides the pipelines — enrich that source directly under this file's rules.
