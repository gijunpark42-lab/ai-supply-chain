### US Department of Defense contract awards (`dod_contracts.py`; part of `enrich us`)

Built 2026-10-21 (user: new official data sources for the nightly `enrich all`). Every business day the Department
of Defense publishes ONE page listing every contract it awarded that day worth $7.5 million or more, grouped by
service (Army, Navy, Air Force, Defense Logistics Agency, Missile Defense Agency, ...). Each award is one paragraph:
contractor name and location, amount, contract type and number, what it buys, place of performance, completion date,
contracting activity. defense.gov now redirects to war.gov ("Department of War", the secondary name in use since
September 2025); the pages are the Department's own official record, saved verbatim.

**What it is, for the enrich rules.** NOT a transcript and NOT a company document: it is the CUSTOMER's official
record of an order. It carries facts only — no management views, no guidance. It is enriched like a filing about the
company: the award is a fact on the winner's node, and the agency is a government customer (§2 "Government customers":
a `relations/` row with scope "other"; JOB 3 never makes an agency a node).

**Coverage.** `dod_contracts.py` matches contractor names to graph companies with its curated `ALIASES` table — legal
entity names ("Northrop Grumman Systems Corp.", "Space Exploration Technologies Corp." = SpaceX, "L3 Technologies Inc."
/ "Aerojet Rocketdyne Inc." = L3Harris, "United Launch Services LLC" = United Launch Alliance) and a few wholly owned
subsidiaries whose ownership is certain ("Constellation NewEnergy Inc." = Constellation Energy, "Direct Energy Business
LLC" = NRG Energy, utility subsidiaries such as "Virginia Electric and Power Co." = Dominion Energy). Groups covered:
defense / space / government services, cloud, software and AI labs (Microsoft, Amazon, Google, Oracle, IBM, OpenAI,
Anthropic), compute and networks, semiconductors and components, power equipment, EPC contractors,
energy suppliers and utilities (DLA Energy electricity / gas supply, utility privatization), pharma (DLA Troop Support).
The big primes that are NOT graph companies (Lockheed Martin, RTX / Raytheon, Boeing, General Dynamics, BAE Systems,
GE Aerospace, Leidos, Booz Allen ...) are never saved: `unmatched` lists them for the user to consider.
Never a guess: `NOT_NODES` keeps look-alikes out ("General Electric Co." = GE Aerospace, not GE Vernova; "Iron
Mountain Solutions" is a Huntsville engineering firm, not Iron Mountain; "Vertex Aerospace" is not Vertex; "Jacobs
Technology" went to Amentum in 2024), and a name that merely starts like a node ("Jacobs Government Services Co.",
"Quanta Government Solutions LLC") is listed as a near-miss by `unmatched`, never saved, until the coordinator has
checked who owns it.

**What is kept / skipped (in `dod_contracts.py`; every day page is recorded in `dod/sync_state.json` → `seen` with
its status, the companies matched and the entities skipped)**
- Kept: every award paragraph whose CONTRACTOR is a graph company — the name(s) before "is awarded / was awarded /
  have each been awarded" (each entry of a multi-award list, separated by ";"), or the contractor named in a
  `CORRECTION:` / `UPDATE:` paragraph. One file per company per announcement day, all its paragraphs in it.
- Never matched: a company named only in the description ("spares for the Boeing F/A-18"), a joint venture whose name
  contains a node ("Fluor-X JV" — recorded as skipped), a `NOT_NODES` name, a near-miss.
- Never saved twice: every saved paragraph's fingerprint is kept (`para_keys`), so a re-posted page (DoD posted the
  Sept. 29, 2026 awards twice, first under the title "Sept. 28") adds nothing it already saved. A second page of the
  same day with NEW paragraphs for a company gets its own file and a label with the article id before the date.

**Loop**
1. `python -X utf8 dod_contracts.py sync` — lists the announcement days from the contracts RSS feed (from 3 days before
   the last sync; the first sync reaches back 120 days), reads each new day page (war.gov answers 403 to scripts, so
   the page is read through Jina Reader), saves each graph company's award paragraph(s) verbatim to
   `transcripts/dod/<slug>_<YYYY-MM-DD>.txt` and queues the file in `dod/pending.json`. A day page is read once; a page
   that fails is retried on the next runs (`later:`), then given up after 3. `--company "<Company>"` (repeatable)
   re-reads the window's days for those companies only (after adding a node or an alias; it does not move the
   last-sync date); `--since YYYY-MM-DD` forces a start. A run stops after 45 minutes and the next one continues.
2. `python -X utf8 dod_contracts.py pending [--company "<Company>"]` — the queue (`kind`: `award`), with the largest
   amount stated for the company. `enrich us` works the WHOLE queue, whatever the company's home market (Rolls-Royce,
   Siemens and Thales win DoD awards too); the status board counts those rows under their own market.
3. Enrich each file under the enrich skill's common rules (parallel `enricher` agents, split by company):
   - **The award, on the company's node (JOB 1).** One `quarterly_data` entry per award paragraph, on the placement
     that holds the company's company-wide entries (§6 one fact, one node): `signal` = what was awarded and for what
     (the program / product / service as the paragraph words it), the contract type and number, modification or option
     wording, place of performance and the completion date, and the contracting activity — written in English, numbers
     as printed; `figure` = the amount with its qualifier ("$307,723,563 modification", "not-to-exceed $57,710,427
     undefinitized contract", "maximum $903,000,000 IDIQ"); `counterparty` = the agency as the page names it (the
     service heading or the contracting activity: "U.S. Army", "U.S. Navy", "U.S. Air Force", "U.S. Space Force",
     "Defense Logistics Agency", "Missile Defense Agency" ...), `counterparty_role` = "customer"; `topics` [] unless the
     award's subject is a timeline topic (electricity supply, generation, grid or cooling → `power_cooling`). **No
     screener slot** (one order among many; the screener's backlog comes from the company's own call / filing).
   - **The agency, as a government customer (relations/).** One row per file per agency in
     `relations/<company>.json`: `from` = the company, `to` = the agency as named above, `relation` "supplies",
     `product` = what the award buys (specific, English), `scope` "other", `source` = the saved file path, `quote` = a
     verbatim snippet of the paragraph that includes the amount, `label`, `date` = the announcement day, `figure` = the
     amount as the quote states it. For a Defense Logistics Agency buy name DLA as the customer and put "using customer
     is Navy" in `product`. For Foreign Military Sales the customer row is still the U.S. agency; the foreign
     government goes into the signal / product text, not a row. The agency is never a node.
   - **Multi-award contracts.** "One of N awardees" (the file's tag line) on a combined ceiling: the figure is the
     shared ceiling, worded as such ("one of 16 awardees on a $9,000,000,000 combined-maximum multiple-award
     construction contract") — never the whole as the company's, never divided. When the entry states its own amount
     ("(SPE604-27-D-8001, $38,136,143)"), that amount is the company's (the header says "this company's entry").
     Co-awardees on one paragraph are NOT a relationship between them.
   - **Two graph companies in one award (rare, JOB 4).** Only when the paragraph states that one node supplies or
     subcontracts to another (a prime naming a node as its subcontractor or source): an AI-chain supply → a chain
     edge through the patch under JOB 4; anything else → a `relations/` row; the saved file is the source.
   - **Corrections.** A tag line `correction / update of an earlier announcement` corrects or cancels an earlier day's
     award ("… was not released", a corrected amount or contract number). Read it with that day's file of the same
     company: a cancelled award yields no entry (close both files with `--why "award not released (correction
     MM-DD-YYYY)"`); a corrected amount is the figure to use (an entry already applied with the old number gets an
     `apply_corrections.py` fix). An `UPDATE:` that adds the company to an existing multiple-award contract is an award.
   - **Depth rule (§6).** The company's own call, 8-K or IR release about the same contract comes first; the DoD
     paragraph then adds only what it did not state (contract number, completion date, contracting activity, a
     different amount). A pure restatement yields no entry (`restates <label>`).
   - **Label:** the file's `# source label:` line verbatim — `[Company] DoD contract award (MM-DD-YYYY)`, dated the
     announcement day (e.g. `Northrop Grumman DoD contract award (09-30-2026)`, `L3Harris DoD contract award
     (10-14-2026)`). Several awards of one company on one day share the label (one file); a second page of the same
     day adds its article id (`… DoD contract award 4614322 (09-29-2026)`). The announcement day is the page's RSS
     publication day (US Eastern), not its title — the title was wrong once (above).
4. `python -X utf8 utils/check_patch.py <patches>` and `python -X utf8 utils/check_relations.py <files>` until clean →
   one `python graph_build.py --sync`.
5. `python -X utf8 dod_contracts.py done --label "<label>"` for every handled file (`--why "no material facts"` /
   `--why "restates <label>"` when it gave nothing). `status [--company …]` lists every file and its state;
   `unmatched` lists the big awardees that are not graph companies and the near-misses.

**Gotchas**
- **Blocked site.** war.gov's Akamai front answers 403 "Access Denied" to every script request for the day pages (the
  RSS feed is open). Jina Reader (`https://r.jina.ai/<URL>`, `X-Return-Format: html`) returns the rendered page;
  the header says "read via r.jina.ai". If Jina is blocked too, the pages stay `later:` and are retried; after 3 runs a
  day is given up (`skip:`) — read it in Chrome by hand if it matters.
- **Window.** The RSS feed holds the last 200 announcement days (~9 months); there is no 31-day cliff as on TDnet, but a
  longer gap falls back to the list page through Jina (automatic).
- **Only $7.5M+.** Smaller awards (most SBIR / STTR, small task orders) are never announced here.
- **Qualifiers are part of the number.** "maximum", "ceiling", "not-to-exceed", "estimated", "undefinitized",
  "cumulative face value" stay in the figure; a modification's amount is the modification, not the contract total.
- **Honeywell / Honeywell Aerospace.** The aerospace business has been its own node since the 06-29-2026 spin-off.
  The collector files an award under the name DoD prints ("Honeywell Aerospace Technologies" → Honeywell Aerospace,
  "Honeywell International Inc." → Honeywell). In August 2026 DoD still printed "Honeywell International Inc." for
  aerospace work (Phoenix propulsion, Clearwater inertial navigation units): the entry stays on Honeywell and names
  the entity exactly as printed ("awarded to Honeywell International Inc., Phoenix, Arizona"), with no claim about
  which business performs it — never re-filed under Honeywell Aerospace by guessing.
- **Subsidiary aliases** carry an `ALIAS NOTE:` line in the header (e.g. "Direct Energy has been a wholly owned NRG
  Energy subsidiary since January 2021"); the fact still goes on the parent node named in the label.
- **New aliases** are a code change in `dod_contracts.py` (`ALIASES`, `NOT_NODES`) by the coordinator, never by an
  enricher: only for an entity that is certainly the node (its own legal name or a wholly owned subsidiary); then
  `sync --company "<Company>" --since <date>` picks up the days already read.
- **A DoD award never adds a node.** A big awardee that is not on the map stays in `unmatched` (a pointer for the
  user / `enrich waitlist`); the award text alone is not a company document stating a supply-chain role.
