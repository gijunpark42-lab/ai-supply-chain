---
name: enrich
description: Enrich the supply-chain graph from company sources — earnings calls, investor-conference talks, SEC/DART filings and important company IR press releases. Use for "enrich" (runs what ENRICH_STATUS.md recommends), the market commands "enrich us", "enrich korea", "enrich taiwan", "enrich japan", "enrich europe", "enrich china", the source commands "enrich us calls", "enrich edgar", "enrich dart", "enrich tdnet", "enrich intl", "enrich tw", "enrich conference", "enrich ir", "enrich waitlist", "Transcript:<company>", or a pasted/URL transcript or company release. Covers the status board, what to capture (facts, company guidance and management comments — never analyst opinion), the ADD-only patch format, JOB 1-5, labels, screener slots, checks and verification.
---

# Workflow 2 — Enrich

Common rules for EVERY source (consolidated 2026-09-26 at the user's request; where an older note in memory
or a reference file disagrees, this file wins). The source-specific steps live in `references/` (table at the end).

## 0. Start and finish every run with the status board

1. **Before anything, read `ENRICH_STATUS.md`** (repo root). It lists, per market, what is fetched and waiting,
   which companies are overdue for a call or were never enriched, where no source exists, and the ordered **Run next**
   list. Also run `python -X utf8 media_status.py` (seconds): it lists the news-interview transcripts not yet read (§11). If its "Generated" time is older than ~12 hours, or another session may have run since,
   refresh it first: `python -X utf8 enrich_status.py` (seconds, no model tokens). Do not re-scan pipelines,
   queues or the graph to find out what is done — the board already did.
2. **At the end**, `python graph_build.py --sync` rebuilds the board. If the run applied nothing (empty queues),
   run `python -X utf8 enrich_status.py` anyway. Paste the board's **Run next** block into your report.
3. **Record what no script can know** (the coordinator only — parallel agents put it in their report):
   - a source that does not exist: `python -X utf8 enrich_status.py mark "<Company>" ["<Company>" …] --source call|dart|ir|conference|edgar --why "<what was checked>" [--recheck YYYY-MM-DD]`
     (default recheck in 90 days; a marked company leaves the board's missing lists until then);
   - where a run stopped or what the next run must know: `python -X utf8 enrich_status.py note <US|KR|TW|JP|EU|CN|all> "<text>"`;
   - **a judgment these rules do not settle — Claude decides it in the same run, never waits for the user**
     (user, 2026-10-19: "질문은 니가 알아서 다 처리"; replaces the 2026-09-26 ask-the-user rule): a new company whose
     role is ambiguous, an unclear placement, whether a fact is material. An independent Opus judge (a pool verifier,
     §7.4) decides it from these rules and the user's earlier answers (`enrich_marks.json` → `answered` is the
     precedent), the run applies the decision, and the coordinator records it with
     `python -X utf8 enrich_status.py decide "<subject>" --question "<…>" --answer "<what was decided and done>" [--label "<source label>"] --no-board`
     (records never rebuild the board since 2026-10-21; the next build does). The board shows Claude's decisions
     for 7 days so the user can overrule one; list them at the top of the report. `ask` is no longer used.

## 1. Commands

| The user says | What runs |
|---|---|
| `enrich all` | **The nightly run** (user, 2026-10-19: every country, every source, every night at 23:00): every market command (`enrich us`, `korea`, `taiwan`, `japan`, `europe`, `china`, `intl`) with each of its collectors, `enrich edgar`, `enrich conference`, `enrich ir`, `enrich waitlist`, the Perplexity Finance call queue
(`pplx.py pending`, every market — references/pplx.md), the news interviews (§11), the relations backfill, the gap fill (§12) and Claude's decisions on any open judgment (§0.3) — whether or not the board calls them due. One fixed worker pool sized by free memory does all of it (§7.4). |
| `enrich` | The board's **Run next** list, top to bottom (refresh the board first). |
| `enrich us` | Every US gap except SEC filings — calls (+ defeatbeta fallback), overdue / never-enriched companies, conference talks, IR releases; also the utilities' own regulatory filings (`utility_filings.py`). Meant to run daily. |
| `enrich korea` | DART filings (+ backfill of Korean companies with no filing enriched), IR presentations and Samsung's official call script (`kind.py`: KRX KIND library + six large-cap IR sites), conference talks, IR releases. |
| `enrich taiwan` / `enrich japan` / `enrich europe` / `enrich china` | That market's calls (Investing.com; Taiwan Chinese-language calls via tw.py), conference talks, IR releases; Taiwan also its MOPS filings (`mops.py`: 法說會 decks, important 重大訊息, monthly revenue); China also the A-share IR activity records and investor Q&A answers (`cninfo.py`) and their periodic reports (`cninfo.py reports`: top-5 customers / suppliers, capacity, construction in progress, R&D, MD&A); Japan also its TDnet timely disclosures (`tdnet.py`: results, forecast revisions, capex, plans, agreements, M&A) and its EDINET annual / semi-annual securities reports (`edinet.py`: major customers, capex, R&D, MD&A). |
| `enrich edgar` | SEC 8-K / 10-K / 10-Q, foreign issuers' 6-K / 20-F / 40-F, recent listings' prospectus (not part of `enrich us`; `enrich all` runs it every night). |
| `enrich waitlist` / `enrich waitlist <market>` | Onboard the user-pre-approved new companies queued in `enrich_waitlist.json`, each market by its own rules (`references/waitlist.md`). |
| `enrich us calls` · `enrich dart` · `enrich kind` · `enrich tdnet` · `enrich intl` · `enrich tw` · `enrich conference` · `enrich ir` | One source, across every market it covers (reference table below). |
| a pasted transcript / URL / release, or `Transcript:<company>` | Save the source (§2), then enrich it under these rules. For `Transcript:<company>` fetch the latest full call yourself (US: `av.py` / `utils/defeatbeta_fetch.py` / Perplexity Finance, references/us.md; others: the market's source, then Perplexity Finance — `python -X utf8 pplx.py fetch "<Company>"`, references/pplx.md) and state the call date before enriching. |

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

**Every relationship, with a scope (decision C, user 2026-10-17: when a company is added, add everything related
to it, even if not AI-related)**
- Every real customer / supplier / partner-in-a-supply-role relationship a source states is recorded, AI or not,
  with a scope: `"ai"` = part of an AI chain → a `connects_to` edge through the patch (JOB 2 / JOB 4, unchanged);
  `"other"` = anything else → an ADD-only row in `relations/<company>.json` (shape: the `relations.py` docstring —
  from, to, relation `supplies` | `customer_of` | `partner`, product, scope "other", source, quote, label, date,
  added[, figure]). The litmus test decides chain MEMBERSHIP, never whether a relationship is recorded; the
  counterparty of an "other" row need not be a graph node and is not added as one for it.
- Same source rules: a saved file under `transcripts/` (its path + a verbatim, grep-able `quote`) or a public URL
  (10-K / 20-F customer or supplier note, company release, IR page). Never model memory, never third-party
  articles; lenders, banks and investors are financing, not relationships (below). A row with a `figure` must cite
  a saved file (save the page first); `check_relations.py` lists every URL row as a WARN for a human check.
- A capacity entitlement in, or wafer purchases from, a joint-venture fab that the filer's own document states is a
  supply relationship from the JV's operating majority owner (when it is a graph node) to the filer — a chain edge when
  that capacity feeds an AI chain, otherwise a relations/ row (`customer_of`); ownership shares and investment amounts
  stay out (Claude decision 2026-10-19, user delegated).
- **New companies get their full relationships now:** the run that adds a node (JOB 3, `enrich waitlist`, a new
  chain) also writes its `relations/<company>.json` from the same documents, then records it with
  `python -X utf8 relations.py done "<Company>"`.
- **Companies already on the map are backfilled, ~15 per night** (5 until 2026-10-19; raised with the daily gap fill, §12):
  every `enrich all` run (the nightly) takes `python -X utf8 relations.py next 15` (the next 15 pending in
  `relations_backfill.json`, most-connected first),
  reads each company's latest annual report (10-K / 20-F / 사업보고서 / 有価証券報告書 / 年度报告) customer and supplier
  notes and its own releases for named relationships, writes the AI ones as patch edges and the rest as
  `relations/` rows, and closes each with `relations.py done "<Company>"` — also when its documents name nobody
  (say so in the report). ADD-only: a done row never goes back to pending. Parallel agents write only the
  `relations/` files of the companies they were given; the coordinator alone runs `relations.py done`.
- Pre-flight every relations file with `python -X utf8 utils/check_relations.py <files>` until clean, before
  `graph_build.py --sync` (which merges them into `merged_graph.json` → `other_edges`; the website shows them only
  on demand).

**Contractors (rule B, user 2026-10-17):** data-center and power-grid contractors — construction / EPC /
electrical / mechanical builders of data centers, substations and transmission — ARE supply-chain participants and
may be added as nodes. Semiconductor-FAB contractors stay excluded: United Integrated Services, Acter, Marketech,
Hanyang Eng — never a node and never a `relations/` counterparty; their facility contracts stay on the client's
`quarterly_data` with counterparty keys, as before. Rule B excludes companies, not projects: the four named firms and
any other contractor whose business is semiconductor-fab facility / cleanroom construction. A general engineering /
EPC / construction firm that also designs or builds fabs (Bechtel, Jacobs Solutions, Gilbane, Fluor) is not a fab
contractor: its fab work is a relations/ row with scope "other" (Claude decision 2026-10-19, user delegated).
**Government customers and software users** (Claude decision 2026-10-19, user delegated): a government agency or public body named as a paying
customer of the company's product is a relations/ row (scope "other", the counterparty as the source names it); JOB 3
still never makes it a node, and grants or incentives the company receives are not customer relationships. Named
users of the company's product, paid or free (open-source software, SDKs, open models), are `supplies` rows when the
source says they use it, `partner` rows when it states joint development or integration; an illustrative "such as"
mention is not a row.
**Platform integrations** (Claude decision 2026-10-19, user delegated): app-integration ("connector") lists and content-availability lists on a
platform are not relations rows; a partnership in which the partner supplies a named part of the company's product or
service (payments, checkout, co-produced content, device design) is a `partner` row. A counterparty is written as the
source names it; a business unit is folded into its parent only when the naming rules map it (AWS -> Amazon).

**Do not capture**
- Analyst or moderator questions, estimates, opinions, ratings or price targets. When management confirms an
  analyst's number, the number is management's — attribute it to the executive who confirmed it.
- Third-party articles, research notes, newsletters, AI-summary sites, social posts. They are pointers only:
  find the company's own document and enrich from that, or leave the gap.
- Financing terms (offerings, notes, convertibles, credit lines, conversion prices, use of proceeds), governance,
  executive pay, personnel changes, awards and rankings, CSR, event / webcast / trade-show schedules.
  Not financing (user, 2026-10-13): a bitcoin miner's bitcoin production, holdings and sales (its inventory), bitcoin
  it lends out (2026-10-19: the BTC loaned and the interest income the company reports on it are part of its holdings),
  and a data-center developer's land / site purchases (capex) — keep them; a pledge of bitcoin as collateral for a credit
  facility stays out with the facility.
  A financing release can still carry operating facts ("12-inch capacity fully loaded", "the Texas fab passed
  Tier-1 customer qualification"): keep those, drop the deal terms. This includes the operating program a financing or
  government-funding commitment would pay for (new production lines, capacity build-outs, technology programs): keep it
  on the company's node as its stated plan, hedged as conditional when the commitment is; the loan / grant terms go to
  market/history/financing_manual.jsonl (§10c) (Claude decision 2026-10-19, user delegated).
  An award or ranking release is read the same way (Claude decision 2026-10-19, user delegated): the award, ranking, score and the awarding body's
  assessment yield nothing, but operating facts the company states about itself in it (a plant's delivery performance,
  backlog cleared, growth, revenue mix) are kept; a number already on the node for that period is a restatement (§6).
  **Where financing ends (Claude decision 2026-10-19, user delegated):**
  - Government money a company RECEIVES: a grant, subsidy, incentive, tax credit or R&D / program award (CHIPS Act, EU
    Chips Act, NSF, DOE, a national strategic fund) is a company fact — the amount, the program, what it funds and its
    status as the company states it (awarded, definitive agreement, letter of intent, preliminary terms, "in final
    discussions"), hedges kept, on the recipient's node; the agency never becomes a node. When the government takes
    equity or warrants in return, keep the award and say so, without the share count, price and stake terms. A
    government LOAN or loan guarantee is financing like any credit facility (§10c log): keep only the program it funds.
    A government agency that PAYS for a named contract is a customer (unchanged).
  - Cash: the company's stated cash, cash equivalents, investments or liquidity at a date — including a pro forma figure
    that counts money already raised — is a balance-sheet fact and is kept; how it was raised (offering size, price,
    coupon, conversion terms, use of proceeds) stays out.
  - Ownership between operating companies: when an operating company (not a bank, fund or other financial investor)
    buys or sells a stake of 20% or more, a stake that is or becomes a subsidiary, JV or equity-method affiliate, or
    control, record it on the node of the company whose document it is: the parties as named (with the affiliation
    stated), shares and stake before / after, the accounting status, the date and any operating cooperation the
    agreements state — never the price, proceeds, gain or loss, or security terms. Share trades by funds and banks,
    index changes, buybacks, insider dealings and IPO / listing filings (a subsidiary's draft registration too) stay out.
    A change in consolidation scope (a subsidiary becoming an equity-method affiliate or the reverse) is recorded once on
    the company-wide node with its effective date, because it changes the reported revenue base (SUMCO / FST).
  - Strategic equity investments: an operating company's investment in a customer, supplier or partner that the filing
    ties to a commercial relationship (NVIDIA -> Coherent / Marvell, Teradyne -> FormFactor) is a relationship fact —
    investor, amount and stake as stated and the commercial tie, on the existing edge (contract type `strategic equity
    investment`) or else on the filer's node with counterparty keys; security terms stay out. The same money from a
    bank or fund is financing.
  - Licences and disposals: a licence or collaboration deal is a contract, not an acquisition — its stated upfront
    payment, milestones ("up to"), royalties and fees are captured like a supply contract's value; only the purchase
    price of a company, business, shares, land or buildings is a deal price. A sale of assets, plants, capacity or a
    business is recorded like an acquisition: what was sold (MW, sites, products, the stake), the buyer as named, the
    dates — never the price, proceeds or gain.
  - Legal proceedings the company itself discloses (legal-proceedings / contingencies note, Item 3, a release or timely
    disclosure) are company facts: parties, court or forum, claim, filing date and stage, every amount the company
    states and its own position, attributed. Boilerplate yields nothing; a lawsuit known only from news is never
    captured. The fact goes on the filer's node; other parties are named in the signal, without keys or edges.
  - Government designations: a listing that names the company (DoD 1260H Chinese Military Companies list, the Entity
    List or another export-control listing, sanctions) or its removal, disclosed in the company's own filing or
    release — the designation, the stated effect and the company's response, on its node, no screener slot.

**Where the facts may come from**
1. Transcripts (earnings calls, investor-conference talks): read every line, prepared remarks and the full Q&A;
   take everything management says that is material to the company — never filter by chain theme. A call counts only
   as a full verbatim transcript (user, 2026-10-05). **Japan exception (user, 2026-10-13):** when a Japanese company's
   call has no full transcript, the Q&A summary of the results briefing that the company itself publishes (its own IR
   site / TDnet, never a third party's) is used instead — answers attributed as the summary words them; label it as
   the company document it is (e.g. `[Company] results briefing Q&A: <title> (MM-DD-YYYY)`). **logmi** (Claude decision 2026-10-19, user delegated): a
   full results-briefing transcript (presentation + Q&A) on logmi Finance (finance.logmi.jp) that the company itself
   provides (the article says 提供：<company>) or that its own IR page links counts as the company's record of the call:
   enrich it as the call (`[Company] Q[N] FY[YYYY] (MM-DD-YYYY)`, dated the briefing), saved verbatim with SOURCE = the
   logmi URL and the IR page that links it. It ranks above a Q&A summary; other logmi articles stay pointers.
2. No transcript: company-issued documents only — SEC / DART filings, IR press releases, company decks,
   fetched from the official source and saved verbatim (`transcripts/ir/` via `ir_pull.py`, or
   `transcripts/non_transcript_sources/` with a NOT-a-transcript NOTE and a `# source label:` header).
   **Blocked fetch (user, 2026-10-14):** when a company's own page or PDF answers 403 / a bot page (e.g. investor.asml.com),
   read the same URL through Jina Reader, `curl -s -m 60 "https://r.jina.ai/<full URL>"`. It is still the company document:
   save it verbatim with the original URL plus "via r.jina.ai" in the header. **Company video with no published transcript**
   (the company's own channel or IR site: results interview, investor day, webcast): `yt-dlp --js-runtimes node "<URL>"
   --skip-download --write-auto-subs --sub-langs "en.*" --sub-format vtt`, saved in `transcripts/non_transcript_sources/` with a
   NOT-a-transcript NOTE "(YouTube auto-captions, may mishear)"; a number enters only if the company's release or filing
   states it too. Never third-party channels' videos, except the news-outlet interviews of §11 (a named executive
   speaking on camera, saved by `media_pull.py`). **Exa search is fintweet-only and never used here** (user, 2026-10-14).
3. **IR press releases: only the important ones** — a named supply / customer agreement or design win, capacity /
   capex / production facts, company guidance or targets, a product launch or availability with specs and dates,
   the operating facts of an acquisition (never its price), a fab / facility start; for pharma / biotech / diagnostics nodes every clinical or regulatory fact that matters to the stock — trial authorisations, first patient dosed, interim / topline results and their numbers, designations (Fast Track, Breakthrough, priority review), filings and decision dates, approvals, the company's own validation-study results (user, 2026-10-06: "임상승인처럼 그 주식에 중요한것들은 당연히 넣어야함"; replaces the 2026-09-27 approvals-only rule). Facts from segments outside the node's chain ARE captured when material to the company (user, 2026-10-06: enrich covers the WHOLE company; replaces the 2026-09-27 out-of-chain-segment rule). **No AI-relevance check at all since 2026-10-12** (user: "관련있으면 추가시켜 ai뿐만아니라 … 목표가 공급망기반 블룸버그같은거임" — the goal is a supply-chain-based Bloomberg-style terminal): a real supply / customer relationship or material company fact is never held, rejected or deleted for being non-AI or outside the node's chain; the source rules, the analyst / financing exclusions and the JOB 3 rejection list still apply. Anything else yields no entry:
   close the row with `python ir_pull.py done --label "<label>" --why "no material facts"`. (`ir_pull.py` already
   skips the clear notices by headline: dividends, buybacks, event and results-date notices, personnel, awards,
   CSR, trade-show exhibit notices, columns and surveys.)
4. Product and event releases: "first" / "leading" are the company's claims (attribute them); a demo is a demo,
   never "shipping"; no edges or contracts from joint demonstrations. A company's own lab proof-of-concept or
   demonstration of a technology transition (Trane's 800 V DC chiller) IS one node entry on that company, worded as a
   demonstration with its stated results: no screener slot, no edge or contract, collaborators named in the signal only
   (Claude decision 2026-10-19, user delegated).

Add nothing the source does not state: no background knowledge, no inferred ownership, dates or customers, and no
arithmetic in `figure` / `units` / `value` (write the numbers as stated; verify flags derived ones).
A source that refers to counterparties without naming them ("all three major memory suppliers", "five hyperscalers")
puts the fact on the speaker's node only; it is never copied onto nodes picked from background knowledge (Claude decision 2026-10-19, user delegated).

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
A filed "customer X is n% of revenue" fact uses `type` `customer share` (DART), `10-K customer concentration` /
`10-Q customer concentration` / `20-F customer concentration` / `40-F customer concentration` / `prospectus customer
concentration` (EDGAR) or `annual securities report customer share` / `semi-annual report customer
share` (EDINET) or `annual report customer share` / `half-year report customer share` (China, `cninfo.py reports`)
— the Exposure tab reads exactly these.
A named deal recorded as an edge contract ALSO gets one node entry on the filer's company-wide placement when it
qualifies for a screener slot (contracts carry no slot); that pair is the only allowed repeat of a fact. When a
counterparty becomes a node, an unslotted counterparty entry that holds only that deal moves onto the new edge
(correction delete + patch add); a slotted one stays (Claude decision 2026-10-19, user delegated).

**JOB 3 — New companies: added with an independent Claude approval** (user decision 2026-09-26: Claude
approves, not the user). When a source names a company that is not in the chain and passes the litmus test
("does its stock directly benefit from this product being built and sold?" — any product of a universe company's
supply chain, AI or not, since 2026-10-12):
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
     are not needed): banks, lenders, insurers, investors / funds, governments and agencies, distributors,
     semiconductor-fab contractors (rule B, §2 — data-center and power-grid contractors are allowed), generic end
     customers, divisions, sub-brands, product names, and the do-not-add
     list (the 2026-09-05 cleanup removals, Core42, AES, Nanjing Casela).
   - **decide, never ask** (user, 2026-10-19: "질문은 니가 알아서 다 처리") when it is genuinely ambiguous — its role
     in this product is indirect or unclear, a borderline litmus case, a private company, an affiliate or JV, no sector
     fits: it settles it from these rules and the user's earlier answers (`enrich_marks.json` → `answered`) and writes
     `"approved": …` or its rejection reason, marked as a judgment call.
3. The coordinator adds each approved company's `company_metadata.json` entry (ticker, exchange, country,
   status), then applies. Rejected → the player comes out of the patch and the deal goes on the node of the
   company whose document it is, as `quarterly_data` with `counterparty` / `counterparty_role` keys
   ("Customer X: …" / "Supplier X: …"). Every judgment call is recorded —
   `python -X utf8 enrich_status.py decide "<Company>" --question "<…>" --answer "<the decision>" --label "<source label>" --no-board`
   — and shows on the status board for 7 days so the user can overrule it. When a counterparty becomes a node, the
   filer's existing counterparty entry stays where it is and the new edge gets its own contract worded for the
   relationship (Tempus AI -> Moderna / Merck & Co. precedent, 2026-10-12).
4. Every added node is named in the run report and the HANDOFF log — structure never changes silently.
   `utils/check_patch.py` refuses a new node without `approved`, without its metadata entry, or under a removed /
   duplicate name.
5. **Every new node gets its brand logo in the same run (user, 2026-10-01).** After applying, the coordinator fetches
   a logo for each added company that has no `static/logos/manifest.json` entry, following
   `docs/memory/logo_fetching.md` (ticker-proven identity; companieslogo search API → Wikidata P154 → official
   site; SVG preferred; render on both chip colours to check). Parallel agents write only
   `static/logos/<node id>.<ext>`; the coordinator alone appends `{"file","bg"}` to `static/logos/manifest.json`
   (append only, no key sorting) and then runs `graph_build.py --sync` (or `npm run sync`) so `web/public/logos`
   is refreshed. A node with no reliable logo is listed in the report instead of shipping a guessed one.
   **Browser cache (2026-10-13):** visitors' browsers keep logo files for 7 days (`web/next.config.mjs`). A
   new logo needs nothing extra (`manifest.json` itself is not cached), but NEVER fix a wrong logo by overwriting
   its file under the same name — returning visitors would keep the old image for up to a week. Save the
   corrected logo under a new file name (e.g. `<node id>-v2.<ext>`) and point that node's manifest `file` at it.

**JOB 4 — New edges:** only when the source explicitly states a supply or customer relationship, the speaker is
management (not an analyst), both companies are players in that chain, and it is not a joint demonstration.
A company's own customer list ("our customers include X, Y, Z", 主要客户包括…) DOES count as a stated customer
relationship (user decision 2026-10-05): edge filer -> each named customer that is a player in the same chain, one
contract per source ("X is named among the company's customers in its <source>"), units / value "no specific
figure". Names that are not players stay on the filer's quarterly_data with `counterparty` keys.
A customer or supplier the filing identifies by relationship ("Customer A, relation: Parent Company", a named affiliate in the related-party note) that is a company in the universe ALSO gets the edge, with the customer-share contract (user, 2026-10-06; e.g. Airoha Technology -> MediaTek, 16.14% of 2025 sales).
Existing edges may point outside the chain file (edges merge across chains by name).
A company named only as an example of a category ("leading labs such as X", "e.g.") is not a stated relationship:
no edge and no node proposal; it stays on the filer's node with counterparty keys. A list the company introduces as
its own customers ("workloads for customers, including A, B, C") is a customer list (rule above) (Claude decision 2026-10-19, user delegated).
One edge per supplier -> customer pair in a chain file: a new contract for another product of the same relationship
goes on the existing edge, and when the edge's `relationship` no longer covers it the coordinator widens the label
with an `apply_corrections.py` item of kind `edge` — never a second edge. A named pilot or trial deployment at a
customer's live site is a deployment (contract type `pilot deployment`; a new edge under the conditions above); a lab
demonstration or proof of concept stays a demo (Claude decision 2026-10-19, user delegated).
A relationship that runs opposite to an existing edge (Arm licenses Neoverse to Microsoft; Microsoft sells Cobalt VMs
to Arm; NVIDIA supplies GPUs to SharonAI) gets its own reverse-direction edge only when the source states a DIFFERENT
product flowing that way, named in its `relationship`; never the same relationship twice, and an existing edge in
that direction in another chain file is used first (Claude decision 2026-10-19, user delegated).

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
  fallback that covers untagged legacy entries. Tag a topic only where it is the entry's subject. `power_cooling`
  covers the whole power and thermal domain — generation, grid / transmission, storage, data-center power delivery
  and cooling — whether or not a data center is named (Claude decision 2026-10-19, user delegated).
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
| Earnings call, investor-conference talk (management speaking), DART periodic report, China IR activity record / investor Q&A (`cninfo.py`, management Q&A) | any — the ONE best entry per slot |
| Company's own statutory financial statements outside Korea (Taiwan quarterly / half-year / annual consolidated statements, China annual / half-year / quarterly reports from `cninfo.py reports` (2026-10-04), Japan annual securities reports / semi-annual reports from EDINET — `edinet.py`, 2026-10-04) | like a DART periodic report — any, the ONE best entry per slot (2026-10-01) |
| DART preliminary results (잠정실적) | `revenue_growth` only (the later periodic report supersedes it) |
| DART supply contract with an undisclosed customer | `backlog_or_b2b` only |
| 8-K | any, but only when newer than every same-slot entry of the company; otherwise none |
| 10-K / 10-Q | none |
| Foreign issuer's 6-K / 20-F / 40-F, recent listing's prospectus (`edgar_pull.py`, 2026-10-04) | 6-K = the 8-K row (a monthly revenue report: none, like MOPS monthly revenue); 20-F / 40-F / prospectus = none, like a 10-K |
| Taiwan MOPS monthly revenue (`mops.py`) | none — enriched without a slot, like the IR-release monthly revenue entries (user, 2026-10-01) |
| Company IR presentation (deck; `kind.py`, `mops.py`) or Taiwan MOPS material information (`mops.py`) | same as a company IR press release (row below); never `revenue_growth` — DART holds the quarter's numbers. A results deck may also fill `backlog_or_b2b` with the company's own stated total orders / order backlog (2026-10-01) |
| Japan TDnet filing (`tdnet.py`) | same as a company IR press release (row below), never `revenue_growth`; a results-meeting Q&A record (`_qa` file) = the call / conference row |
| US DoD contract award (`dod_contracts.py`) | none: the government's award record about the company, not the company's own words; the award is a fact entry without a slot |
| Utility regulatory filing (IRP, large-load report or tariff; `utility_filings.py`) | same as a company IR press release (the row below): the company's load / capacity plan → `guidance`, contracted large load → `backlog_or_b2b`; never `revenue_growth` |
| Company IR press release | `guidance` (company guidance / targets), `next_catalyst` (a new product launch, availability, production or shipment start with a date), `backlog_or_b2b` (a named order, contract or design win), `supply_status` (capacity, utilisation, sold-out) — only what the release itself states; never `revenue_growth`; a demo never fills a slot |
| News interview (`transcripts/media/`, `media_pull.py`, §11) | none — a remark on TV never replaces the call / filing entry the screener shows |

Never give a company a second entry with the same slot and the same date (the screener cannot choose), and leave
the key out when an entry fills no slot (never `"slot": null`). `utils/check_patch.py` enforces all of this.

## 5. Source labels — one canonical format per source (FIXED; use everywhere `quarter` / `source` appears)

| Source | Format | Example |
|---|---|---|
| Earnings call | `[Company] Q[N] FY[YYYY] (MM-DD-YYYY)` | `NVIDIA Q1 FY2027 (05-28-2026)` |
| DART periodic / preliminary report | same shape, dated the filing; the 사업보고서 is Q4 of the year it covers | `SK Hynix Q2 FY2026 (08-14-2026)` |
| DART supply contract | `[Company] DART supply contract (MM-DD-YYYY)` | `Sanil Electric DART supply contract (08-20-2026)` |
| SEC filing | `[Company] 8-K` / `10-K` / `10-Q` `(MM-DD-YYYY)` | `Lumentum 8-K (08-11-2026)` |
| SEC filing of a foreign issuer / a recent listing's prospectus (424B4, else S-1/A or F-1/A) | `[Company] 6-K` / `20-F` / `40-F` / `prospectus` `(MM-DD-YYYY)`, dated the filing | `TSMC 6-K (09-10-2026)`, `Cerebras prospectus (05-14-2026)` |
| Investor conference / company event | `[Company] [Event] [YYYY] (MM-DD-YYYY)` | `Credo Goldman Sachs conference 2026 (09-10-2026)` |
| Company IR press release (saved by `ir_pull.py` or by hand) | `[Company] press release: [headline, ≤ 60 chars] (MM-DD-YYYY)`; a non-English headline becomes `release <id from the URL>` | `Supermicro press release: Supermicro Now Shipping NVIDIA Vera Rubin NVL72 Racks (09-23-2026)` |
| Korean IR presentation from KRX KIND (`kind.py`) | `[Company] IR presentation: KIND <irSeq> (MM-DD-YYYY)`, dated the IR event | `Nepes IR presentation: KIND 19356 (09-18-2026)` |
| Korean large-cap results deck from its own IR site (`kind.py`) | `[Company] IR presentation: Q[N] [YYYY] results (MM-DD-YYYY)`, dated the DART earnings day | `SK Hynix IR presentation: Q2 2026 results (07-29-2026)` |
| Taiwan 法說會 deck from MOPS (`mops.py`) | `[Company] IR presentation: MOPS <file id> (MM-DD-YYYY)`, dated the conference | `Quanta IR presentation: MOPS 238220260813E001 (08-13-2026)` |
| Taiwan material information from MOPS (`mops.py`) | `[Company] MOPS material information: release <code>-<YYYYMMDD>-<serial> (MM-DD-YYYY)`, dated the filing | `Gold Circuit MOPS material information: release 2368-20260929-2 (09-29-2026)` |
| Taiwan monthly revenue from MOPS (`mops.py`) | `[Company] MOPS monthly revenue: <Month YYYY> (MM-DD-YYYY)` | `Auras Technology MOPS monthly revenue: August 2026 (09-10-2026)` |
| China A-share IR activity record (`cninfo.py`) | `[Company] IR activity record: [record no., else the date] (MM-DD-YYYY)`, dated the disclosure day | `Innolight IR activity record: 2026-008 (08-23-2026)` |
| China A-share investor Q&A answers (`cninfo.py`, one file per company per answer day) | `[Company] investor Q&A: [SZSE Interactive Easy \| SSE e-Interactive] (MM-DD-YYYY)` | `Eoptolink investor Q&A: SZSE Interactive Easy (09-23-2026)` |
| China A-share periodic report (`cninfo.py reports`; the shape of the reports saved by hand earlier) | `[Company] annual report: [YYYY] Annual Report (MM-DD-YYYY)` / `[Company] half-year report: [YYYY] Half-Year Report (…)` / `[Company] quarterly report: [YYYY] Q1\|Q3 Report (…)`; YYYY = the fiscal (calendar) year, dated the disclosure day | `Innolight annual report: 2025 Annual Report (03-31-2026)` |
| Hong Kong HKEXnews filing (`hkex.py`) | `[Company] HKEX announcement: [short English title, ≤ 60 chars] (MM-DD-YYYY)` / `[Company] HKEX circular: …` / `[Company] annual report: [YYYY/YY] Annual Report (…)` / `[Company] interim report: [YYYY] Interim Report (…)` / `[Company] prospectus (…)`, dated the HKEXnews release day (Hong Kong time) | `Lenovo HKEX announcement: Continuing Connected Transactions (09-12-2026)` |
| China A-share results briefing Q&A (`cnbrief.py`) | `[Company] results briefing Q&A: [period(s)][ collective] (MM-DD-YYYY)`, dated the briefing; a non-results briefing `[Company] investor briefing Q&A: [platform] [id] (MM-DD-YYYY)` | `JCET results briefing Q&A: H1 2026 (08-21-2026)` |
| Japan TDnet timely disclosure (`tdnet.py`) | `[Company] TDnet: [short English title, ≤ 60 chars] (MM-DD-YYYY)` for an English version; `[Company] TDnet: release <doc id> (MM-DD-YYYY)` for a Japanese-only filing; dated the disclosure day | `Taiyo Yuden TDnet: Conclusion of a Memorandum of Understanding Regarding (09-29-2026)` |
| Japan annual securities report / semi-annual report from EDINET (`edinet.py`) | `[Company] annual securities report: FY[YYYY] (MM-DD-YYYY)` / `[Company] semi-annual report: H1 FY[YYYY] (MM-DD-YYYY)`; an amended one adds `amended ` before the type; FY = the year the fiscal year ENDS in (a March year Apr 2025 – Mar 2026 = FY2026, as for the calls); dated the filing day | `SUMCO semi-annual report: H1 FY2026 (08-07-2026)` (December year); a March-year company's report filed in late June 2026 = `… annual securities report: FY2026 (06-dd-2026)` |
| US DoD contract announcement (`dod_contracts.py`) | `[Company] DoD contract award (MM-DD-YYYY)`, the announcement day; a second same-day page adds its article id before the date | `Northrop Grumman DoD contract award (09-30-2026)` |
| US utility regulatory filing (`utility_filings.py`) | `[Company] regulatory filing: [document short title] (MM-DD-YYYY)`, dated the filing; [Company] = the graph node (the parent of the filing subsidiary) | `Southern Company regulatory filing: Georgia Power Large Load Economic Development Report Q2 2026 (08-17-2026)` |
| News interview of a company executive (`media_pull.py`, `transcripts/media/`, §11) | `[Company] [Outlet] interview (MM-DD-YYYY)`, dated the day the video was published; [Company] = the graph node the speaking executive works for; [Outlet] = `CNBC`, `CNBC International`, `Bloomberg`, `Yahoo Finance` or `Fox Business`; a second video of the same company, outlet and day adds its YouTube video id before the date | `NVIDIA CNBC interview (10-16-2026)`, `Micron Bloomberg interview <video id> (10-16-2026)` |
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
(7) A call label's date is the call date the company's own documents give (results release "conference call today",
6-K / 8-K notice). A label found to carry a wrong or approximate date is relabelled everywhere in one session: every
entry through apply_corrections `relabel` items, the `# source label:` / CALL DATE header of every transcript file of
that call and any curated timelines/*.json source string (Claude decision 2026-10-19, user delegated).

## 6. Placement, duplicates and depth

- **One fact, one node.** Company-wide facts (total revenue, guidance, customer concentration) go on the placement
  that already holds the company's slot-tagged company-wide entries; a segment fact that maps to exactly one
  placement goes there; an ambiguous one goes on the company-wide placement. Never copy an entry into every chain
  the company appears in.
- **Edge meaning must match.** A contract goes on an edge only if it describes that edge's relationship in that
  direction; otherwise on the correct-direction edge (when both companies are players in the chain) or on the
  filer's `quarterly_data` naming the counterparty.
- **Cross-chain relationships and second placements** (Claude decision 2026-10-19, user delegated). When a company document states an AI-chain supply /
  customer relationship between two nodes that share no chain file, add ONE placement so they do: the missing party goes
  into a chain where the other already sits, at an existing sector that fits the role the document gives it (a buyer at
  cloud_infra / system_integration, a supplier at the matching supplier sector), choosing the chain of the product
  supplied when both ways fit and otherwise the fewest new placements; it goes through the patch's `new_nodes` block as
  an existing company new in this chain, with the verifier's approval, and then the edge is made. A relationship that is
  not AI, or whose AI part is unclear, is a `relations/` row and adds no placement. A second placement is never added
  only to hold facts: another business line's facts stay on the company-wide placement without a slot (user 2026-10-12).
- **AI chain or `relations/` (decision C, §2).** A relationship that belongs to an AI chain (the product feeds
  that chain's supply path) goes on the chain edge through the patch; any other goes in `relations/<filer>.json`
  with scope "other" — the filer's own document fills the filer's file (`from` = the filer; `customer_of` when the
  filer is the buyer). Never write one fact both ways. An "other" row between two companies that already share
  an AI edge must describe a DIFFERENT relationship (`utils/check_relations.py` warns). When it is unclear whether
  a relationship is AI, record it as "other" (shown only on demand, so the call is harmless) and say so in the
  report — but a clearly-AI relationship whose counterparty is not a graph node is never a relations/ row: it stays on
  the filer's quarterly_data with `counterparty` / `counterparty_role` keys and the counterparty is proposed under JOB 3
  when it passes the litmus test (Claude decision 2026-10-19, user delegated). The row records THAT the relationship exists; a non-AI deal's figures stay facts on the filer's
  `quarterly_data` with counterparty keys (a row's optional `figure` only repeats what its quote states).
  Between two Biopharma End Customers in ai_bio.json a chain edge is used only when its product is a program the
  chain's AI suppliers feed (Moderna -> Merck & Co. for intismeran); any other pharma collaboration is a relations/
  row. Chain edges created before decision C (2026-10-17) stay where they are (Claude decision 2026-10-19, user delegated).
- **The earnings call is the primary source.** Every later source — conference talk, IR release, 8-K, the DART
  periodic report after the preliminary results — adds only what the company's node does not already state for
  that period: new or changed numbers, newly named customers / partners, transitions and constraints the call did
  not mention. A restatement yields no entry (report it as `restates <label>`). So calls run first (§1 order).
- **Call figure vs filed figure** (Claude decision 2026-10-19, user delegated). When a call transcript's number differs from the company's own same-day
  release, deck or filing for the same metric and the gap looks like a transcription error (a dropped or misheard
  digit, comparison figures that match the filing, another speaker repeating the filed number), the call entry keeps
  its words but loses the number ("garbled in the call transcript; the filed figure is on the <filing label> entry")
  and the filed number is recorded under the filing's own label. A clear spoken misstatement stays as spoken, flagged
  ("as spoken on the call; the filed release prints a different figure"), and any screener slot moves to the filed
  entry (precedent: edgar_r3_call_figure_fixes, 2026-09-11).
- **Same-day release and 8-K:** `enrich us` takes the IR release first; `enrich edgar` (after it, in the same `enrich all` night) then skips
  facts the same-day release already put on the node (the 8-K exhibit is usually that release). A fact that only the
  same-day earnings release states goes under the release's own label (`[Company] 8-K (MM-DD-YYYY)` or its
  press-release label), never under the call label; an entry that mixes both is split (Claude decision 2026-10-19, user delegated).
- Exact duplicates inside one chain file may be removed (integrity rule); everything else is ADD-only. Two players of
  one company at the same locator with different products (die vs finished module, Trainium NPU vs UltraServer) are
  intentional flow stages, not duplicates: never merge them. An edge a correction leaves with no contracts is removed
  in the same pass (user 2026-10-05); skeleton edges with empty contracts are kept (Claude decision 2026-10-19, user delegated).
- **Corporate changes (2026-10-19).** A company taken private, delisted or turned into a wholly owned subsidiary stays a
  node with all its entries and edges; only its `company_metadata.json` row changes (ticker / exchange null, status
  `private` or `subsidiary`), which takes it off the market pipelines and the board. A completed merger adds no placement
  by itself (a placement needs a company document tying a product to a chain). A spun-off or separated business becomes
  its own node only once it is listed (its own registration statement or first filing), through JOB 3, placed where the
  parent's placement describes that business; the parent keeps every existing placement, entry and edge, and from the
  separation date each fact goes to the node of the company whose document states it.

## 7. Checks and verification — one model for every source

1. **Pre-flight every patch before it is applied:** `python -X utf8 utils/check_patch.py <patch> …`
   (`enrich edgar` uses `utils/check_edgar_patch.py`, which accepts only the SEC filing as the source).
   Fix until `RESULT: clean`. It checks numbers, the named counterparty, English only, the locator, new nodes
   (approved, in the metadata, not a removed / duplicate name) and edges, keys and tags, the slot rules, one fact
   one node, one source per patch.
2. **Apply once:** `python graph_build.py --sync` — the coordinator only; enrich agents never run it or
   `apply_patches.py`. It re-verifies the labels just applied (`verify_graph.py`): read every `[fail]` / `[warn]`.
   **In the nightly (and any long session) run it as `python -X utf8 utils/build_outside.py`** (2026-10-21): it
   starts `graph_build.py --sync` outside Claude Code's process tree — Claude Code's low-memory guard killed the
   in-session build on 10-18, 10-19 and 10-20 — waits up to 9 minutes and prints the build's fail / warn lines and
   its last output; `still running` (exit 3) → call it again with `--wait`. Exit 1 = the build itself failed: read
   the lines it printed (`.claude/build_outside.log` holds the whole output).
   A `number_not_in_source` on a figure you computed means the arithmetic must go; `source_not_found` means the
   source file was not saved under the label; anything else — fix the patch and re-run. One label by hand:
   `python -X utf8 verify_graph.py --label "<label>"`.
3. **Independent Opus check, without being asked:** append the applied labels to repo-root `verify_queue.json`;
   at 5+ pending (or at the end of a multi-job session) spawn an `enricher` verifier over them (batch labels of
   the same chain / company group). It re-reads every source and checks accuracy AND §2 (no analyst content, no
   financing terms, important releases only, attribution and hedges kept, English only) and, for a news interview
   (§11), that **the quoted words are the `# SPEAKER`'s at that timestamp — not the anchor's, a reporter's, another
   guest's or the title's** (re-read the lines around the `[mm:ss]`); it corrects or deletes
   entries (corrections go through a patch in `patches/corrections/`), lists facts it believes were missed in its
   report (the coordinator decides; it does not add them), and the verified rows move to `verified`.
4. **One fixed worker pool, sized by free memory, reused all run** (user, 2026-10-19: "메모리 로스안나게
   에이전트최대갯수 매일루프에서조정" and "똑같은 에이전트한테 계속 시키면 안돼? 에이전트 갯수만 늘어나고 서로 어디까지
   했는지 기억을 못해"; replaces the fixed "up to 20 at once"):
   - **Size:** run `python -X utf8 utils/agent_budget.py` first. Its `agents:` number (free RAM minus a 3 GB
     reserve, 0.75 GB per agent, 1–20) is the most agents alive at once — enrichers and verifiers together (about
     one verifier per three enrichers). Re-run it before graph_build.py and before adding a worker; never exceed it.
     **Before every graph_build.py stop all pool workers** (TaskStop): an idle worker still holds its process (~350 MB),
     and on 2026-10-20 the build was killed with 21 claude processes holding 4 GB. Restart from the ledger if work remains.
   - **Spawn once, then reuse:** start the pool's workers once (`enricher` agents named W1…Wn, verifiers V1…Vm)
     and give every next batch to an idle worker of the right kind with **SendMessage** — its context, including
     what it already did tonight, stays. Never spawn a new agent while a pool worker of that kind is idle; replace a
     worker only when it died or its context is full, and then brief the new one from the ledger.
   - **Ledger:** `python -X utf8 utils/work_ledger.py start` at the beginning of the night (it carries over what the
     last night left unfinished — hand that out first); `work_ledger.py assign <worker> <item…>` when you hand out
     work and `work_ledger.py done <worker> <item…>` when it comes back; `work_ledger.py show` after a context
     compaction or a restart tells you where every worker stands.
   - **Splitting:** about 2–5 sources per batch; all of one company's sources go to the same worker. Splitting
     never costs accuracy because: all of one company's sources go to the same agent (the depth
   rule stays consistent); each agent writes only its own patch files — never chains/, `company_metadata.json`,
   queues, `verify_queue.json`, `enrich_marks.json` or `media/enriched.jsonl`; the coordinator alone runs `utils/check_patch.py` over every
   patch, sends new-node proposals to a separate verifier, dedupes proposals two agents made for the same company,
   applies once, closes the queues and records marks. Verifiers run in parallel too (~5 labels each, grouped by
   chain / company). Collection and the number / locator / collision checks are scripts, not models.

## 8. English only in chains/

Every label, signal, figure, units, value, type, relationship and product written to chains/ is English.
Translate Korean / Chinese / Japanese sources as you go; romanise people and agencies; map company names to the
canonical English node (`SK하이닉스` → `SK Hynix`, never a Korean-named duplicate). Amounts keep their currency but
in English: "KRW 27.8 trillion", "US$1.43 billion (NT$45.4 billion)" — not "27조 8,000억원" or "14.32億美元".
`verify_graph.py` and `utils/check_patch.py` fail on any Hangul, kanji / hanzi or kana (since 2026-09-26).

## 9. Web language modes — translate what the run added (user, 2026-09-27)

The site has EN / 한국어 / 中文 (Simplified) / 日本語 modes. chains/ stays English (§8); translations live in
`i18n/translations/<ko|zh|ja>.json` (`{sha1(text)[:12]: text}`) and `graph_build.py --sync` rebuilds the overlays
(`i18n.py build`), printing how many displayed strings are still untranslated. At the END of every enrich run, after
the last `graph_build.py --sync` (and after the verifier's corrections, which change the text):
1. `python -X utf8 i18n.py pending` → chunk files in `i18n/pending/chunks/` (new / changed strings only).
2. Translate them with Sonnet (or better) agents following `i18n/BRIEF.md` — one agent per chunk, parallel, no
   sub-agents; numbers, money amounts, company / product names and source labels stay verbatim.
3. `python -X utf8 i18n.py validate i18n/pending` until clean → `python -X utf8 i18n.py merge i18n/pending` →
   `python -X utf8 i18n.py build`. Commit `i18n/translations/` and `web/public/data/i18n/` with the run.
A new company node gets its official local-script name in `i18n/company_names.json` only when the language matches
its home market (KR → ko from DART `corp_name`; JP → ja; CN / HK / TW → zh in Simplified characters); otherwise
the English name is shown.

## 10. Daily market data (2026-10-17)

`routine/nightly.ps1` runs `market/run_all.py` (prices, insider trades, financing, capex, AI-lab metrics; scripts
only) and `utils/transcript_quality.py` before the session starts. What they write is NOT a signal: never copy it
into `quarterly_data`, chains/ or patches/. Every enrich run (nightly or by hand) also does these three things:

a. **Transcript quality.** Read `graph/transcript_quality.json` (`flagged`: path, label, problem, suggestion). For
   each flagged file fetch a verbatim, speaker-labelled replacement (US: `utils/defeatbeta_fetch.py "<Name>" <TICKER>
   --fy <FY> --q <Q>`; otherwise the market's own transcript source), save it under the same source label, and
   re-enrich that label ADD-only. If no better copy exists yet, leave the file as it is and say so in the report.
   Once the verbatim replacement is saved and the label re-checked, move the old file out of transcripts/ to
   transcripts_superseded/<same sub-folder>/ with a `# SUPERSEDED <date>` first line naming the verbatim file; the
   label's same-day `_earnings_release` companion stays (Claude decision 2026-10-19, user delegated).
b. **AI-lab deals.** Newly reported AI-lab compute deals, GW commitments and contract terms in the day's sources
   (calls, filings, company releases) → append a row to `market/ai_lab_deals.json` `rows` (fields in its `_about`:
   date, lab, counterparty, what, gw, value_usd, source, url, url_or_path, quotes, added, added_by). `url` is the
   PUBLIC link the site shows (the SEC filing, or the company's investor-relations events page for a call), also
   when the quote is checked in a local transcript (`url_or_path`). ADD-only: never edit or delete a row; each quote
   must be verbatim in the cited URL or transcript path (`grep -F`). Keep the file valid JSON.
   Then `python -X utf8 market/run_all.py --only ai_labs` (same-day cache, no new download) before `graph_build.py --sync`.
c. **Financing the scripts miss.** Credit-rating actions and financing events (offerings, notes, loans, facilities)
   read in news or filings that `market/financing_*.py` did not record → append one JSON line per event to
   `market/history/financing_manual.jsonl`: `{"company": "<graph node id>", "date", "type"
   (debt|convertible|equity|credit_facility|abs|lease_financing|rating|other), "title", "amount", "currency",
   "amount_usd", "detail", "form", "market", "source", "url"}`. ADD-only, English, every row with its source URL.
   This file is the only place financing goes (§2 keeps it out of the map). Then rebuild the web file with
   `python -X utf8 market/run_all.py --only financing` (no network) before `graph_build.py --sync`.

## 11. News interviews (`transcripts/media/`, user 2026-10-17)

User: "찌라시면 시그널이면 안 돼. 무조건 뉴스여야 함. 회사 관계자가 직접 얘기한 거여야 해" — a rumor is never a signal; only
news, and only what a company official said directly. `media_pull.py` (daily in `routine/market_data.ps1`, the last 3
days — user, 2026-10-19; `media_roster.py` rebuilds the roster from that day's documents and
`media/roster_additions.json` right before it; details in
`docs/media_interviews.md`) saves the transcripts of interviews on the allowlisted news channels (`media/channels.json`:
CNBC, CNBC International, Bloomberg, Yahoo Finance, Fox Business) in which an executive on the company's roster
(`media/executives.json`) is named and speaks on camera: `transcripts/media/<node-slug>_<YYYY-MM-DD>_<video id>.txt`,
headers `# source label`, `# SOURCE` (the video URL), `# SPEAKER`, `# TRANSCRIPT`, then `[mm:ss]` timestamps.
**Who reads them:** `python -X utf8 media_status.py` lists the files whose label is not yet in `media/enriched.jsonl`
(a separate script, so `enrich_status.py` stays untouched). The **coordinator** of the run gives each one to the agent that handles
that company's sources (all of one company's sources go to one agent, §7.4) and, when the file is done, appends
its line to `media/enriched.jsonl`: `{"label", "date" (the run day), "entries" (how many were added), "why" (when
none)}` (ADD-only). Enrich agents never write that file, and `media_pull.py` never does either. Two parallel market
runs (`enrich us` and `enrich korea`) take only the files of their own market's companies.

a. **Only the named executive's own first-person words about their own company** — the person in the `# SPEAKER`
   header saying "we / our / I" about that company: facts, guidance and targets, attributed management views (the §2
   bar, nothing lower). A restatement of what the latest call or filing already states yields no entry (§6). JOB 1 on
   the speaker's node, JOB 2 only on an existing edge; never a new node or edge (JOB 3 / JOB 4 need a company
   document): a counterparty named only on TV goes on the speaker's node with `counterparty` keys.
b. **Never:** what the anchor, reporter, host, analyst, strategist or another guest says (analysts such as Dan Ives
   are out of this pipeline entirely); a number from the anchor's question, even when the executive agrees with it;
   the video title or description (the outlet's words); anything second-hand or rumoured ("reportedly", "sources
   say", "we've heard", "people familiar with") — also when the executive repeats it.
c. **Speaker unclear → skip.** Captions name no speakers (broadcast captions mark a new speaker with `>>`, Fox with
   an upper-case tag such as `LIZ:`; the file starts a new `[mm:ss]` line at both, but a turn without either marker
   runs on in the same line): use a line only when the lines around it show that the executive is the one
   speaking at that timestamp (answering the question just asked, in the first person).
d. **Verbatim, with the timestamp and the video URL.** `quarter` = the file's `# source label` (§5). Signal:
   `<job title> <name> on <outlet> [mm:ss] <caption mark>: '<verbatim words, one or two sentences>' (video: <the
   # SOURCE URL>)`, hedges kept; `figure` = the number as said (see e.), else 'no specific figure'; no screener slot
   (§4). `utils/check_patch.py` (and `verify_graph.py` after the apply) fails an entry whose quoted words are not
   word for word in the cited `[mm:ss]` paragraph of the transcript body (a quote may run on into the next one),
   or whose figure has a number that is not inside the quote.
e. **No caption kind is checked text, so every quote is treated as machine output.** `youtube manual captions` is
   the track the outlet uploaded: live broadcast captioning or a machine track, which mishears too (the CoreWeave
   file has "IN VIDEO SILICON ADVANTAGE" and "SIX AND 48 MILLION"; the NVIDIA file "reducing by 3040 times per
   year"). `youtube auto-captions` and `faster-whisper (machine)` are machine transcripts. For all three: nobody can
   re-listen, so use only a quote whose wording is unambiguous — skip a garbled phrase or a sentence that needs a
   guessed word — and write the mark right after the timestamp: "(broadcast captions)" for `youtube manual
   captions`, "(auto-captions)" for `youtube auto-captions`, "(machine transcript)" for `faster-whisper (machine)`.
   **A number** (in the quote or in `figure`) counts only when it is written clearly AND the company's own call,
   filing or release states the same number (as for company videos, §2.2); otherwise leave the number out of the
   entry ('no specific figure', and a quote without it) or skip the entry.
f. **Nothing of the video or the transcript goes on the site**: the file is an enrich input; the site shows only
   the short quote in the signal, with the video URL. `evidence.py` gives a news-interview entry no excerpt and no
   file path, and `enrich_status.py` lists the files by label only. The §7 checks apply as for every source.

## 12. Gap fill — every night (user, 2026-10-19: "부족한것들도 매일도는루프에서찾으면 채우는형식으로")

The board lists everything the map still lacks under **Gap fill — tonight's batch** (the whole list:
`graph/enrich_status.json` → `board` → `gaps`), most important first: companies with no data from their own
documents, nodes with no logo, companies with no executive on the news-interview roster, Korean companies with no
DART filing enriched, companies with no IR feed, companies
that never had a call enriched, calls overdue. `enrich all` hands the batch to the pool after the queues are done (at least the listed
batch; more if the night has time), and every gap ends in one of two ways — never left half done:
- **filled:** fetch the company's own source through its pipeline (`dart.py fetch`, `ir_pull.py discover` → a new
  entry in `ir/feeds.json`, `av.py` / `utils/defeatbeta_fetch.py` / Perplexity Finance (`pplx.py fetch "<Company>"`, references/pplx.md —
  every market) for a missed call, the market's IR site, the
  company's own deck or filing) and enrich it under every rule above; a missing logo is fetched as JOB 3 step 5 says;
  an empty news roster gets the company's CEO / CFO (and IR head) appended to `media/roster_additions.json` —
  `{"<node>": [{"name", "title", "aliases": [], "source": "<label | path or URL of the company document stating the
  title>"}]}`, only from the company's own IR leadership page, annual report or release (saved first) — and the next
  daily pull watches for them; a company that never had a call may also get its own channel's results video (§2.2);
- **marked:** nothing exists — `enrich_status.py mark "<Company>" --source <call|dart|ir|conference|edgar|logo|media> --why
  "<what was checked>" --no-board` (back on the list at its recheck date, 90 days by default).
So the list only shrinks, and the next night starts where this one stopped. The report gives filled / marked counts.

---

## Source-specific pipelines — read the matching reference file

These build ON TOP of everything above. When a command fires, read its reference file and follow it with this file.

| Trigger | Region / source | Read |
|---|---|---|
| `enrich us` / `korea` / `taiwan` / `japan` / `europe` / `china` | one home market, every source that serves it, in order | `references/markets.md` |
| `enrich dart` | Korean listed names — DART filings (정기보고서 / 잠정실적 / 공급계약) | `references/dart.md` |
| `enrich kind` | Korean listed names — IR presentations from the KRX KIND IR library (`kind.py`) | `references/kind.md` |
| `enrich tdnet` | Japanese listed names — TSE TDnet timely disclosures (決算短信, forecast revisions, capex, plans, agreements, M&A; English version preferred; only 31 days online) (`tdnet.py`) | `references/tdnet.md` |
| `enrich us calls` | US-listed names — Alpha Vantage full call transcripts (`av.py`), defeatbeta fallback, then Perplexity Finance | `references/us.md` |
| `enrich all` / every market command (calls step) | Every market — Perplexity Finance call transcripts (by Quartr) for the calls no market source has (`pplx.py`, nightly, real Chrome + the site's JSON) | `references/pplx.md` |
| `enrich intl` | Taiwan / Japan / Europe / HK / China — Investing.com (`investing.py`) | `references/intl.md` |
| `enrich tw` | Taiwan Chinese-language 法說會 — video + whisper (`tw.py`) | `references/tw.md` |
| `enrich taiwan` (MOPS step) | Taiwan listed names — 法說會 decks, important 重大訊息, monthly revenue from MOPS (`mops.py`) | `references/mops.md` |
| `enrich edgar` | US-listed names — SEC 8-Ks (every exhibit whole) + 10-K / 10-Q customer, supplier, backlog paragraphs + XBRL (`edgar_pull.py`); foreign issuers' 6-K / 20-F / 40-F and recent listings' prospectus the same way; completeness contract: read once, never reopen | `references/edgar.md` |
| `enrich conference` | Every listed name (US too) — investor-conference fireside chats via Investing.com (`investing.py conferences`); depth rule, multi-agent + verification loop, memory update | `references/conferences.md` |
| `enrich ir` | Company-issued IR press releases via each company's own feed (`ir_pull.py`); important releases only, facts only | `references/ir.md` |
| `enrich china` (step 1b) | China A-share names — IR activity records (投资者关系活动记录表) from cninfo / SSE e互动 and the company's answers on SZSE 互动易 / SSE e互动 (`cninfo.py`); management Q&A, answers only | `references/cninfo.md` |
| `enrich china` (step 1d) | China A-share names — 年度报告 / 半年度报告 / 季度报告 from cninfo (`cninfo.py reports`; full text + `_extract`): top-5 customers / suppliers, capacity, construction in progress, R&D, MD&A | `references/cninfo.md` ("China A-share periodic reports") |
| `enrich china` (step 1e) | Hong Kong-listed names — HKEXnews results, annual / interim reports (+ `_extract`), business updates, inside information, transactions (`hkex.py`); company filings | `references/hkex.md` |
| `enrich china` (step 1f) | China A-share names — 业绩说明会 full live text Q&A from the SSE Roadshow Center, 全景路演 (p5w) and SZSE 互动易 云访谈 (`cnbrief.py`); management Q&A, answers only; one event with cninfo's 召开情况 summary | `references/cnbrief.md` |
| `enrich us` (DoD step) | US Department of Defense daily contract announcements, awards of $7.5M+ naming a graph company (`dod_contracts.py`); the government's own award record | `references/dod.md` |
| `enrich us` (utility step) | US utilities' own IRPs, large-load reports and data-center tariffs (`utility_filings.py`; full text + `_load` extract) | `references/utility_filings.md` |
| `enrich japan` (step 1c) | Japanese listed names — FSA EDINET 有価証券報告書 / 半期報告書 (`edinet.py`; full text + `_extract`): major customers with % of sales, production / orders / sales, capex and new-facility plans, R&D, MD&A | `references/edinet.md` |
| `enrich waitlist` | New companies queued in `enrich_waitlist.json` (user pre-approved 2026-09-28) — metadata first, then each market's collectors, first patch adds the node | `references/waitlist.md` |

`enrich ir <Company>` runs only that company's feed (`ir_pull.py sync --company "<Company>"`).
Pasted text or a URL from the user overrides the pipelines — enrich that source directly under this file's rules.
