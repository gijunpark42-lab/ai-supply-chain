### US utilities' own regulatory filings about data-center load (`utility_filings.py`; monthly step of `enrich us`)

Built 2026-10-01 (user: a pipeline for the utility / generation nodes of `chains/components/power_cooling.json`
that reads what the utilities themselves file about data-center load). Utilities state their data-center load
— contracted MW, the large-load pipeline, the load forecast, the generation and transmission they build for it,
the terms of their data-center tariffs — most fully in filings with their state commission, not on the call.
These are company-issued documents (the utility is the filer), public and free.

**What is read** (`utility_filings/sources.json`, curated; checked 2026-10-01):

| Node | Filer | Source |
|---|---|---|
| Dominion Energy | Dominion Energy Virginia / South Carolina | dominionenergy.com IRP page + the 2025 Virginia IRP Update (SCC PUR-2025-00184) |
| Southern Company | Georgia Power | Georgia PSC docket 55378 (quarterly Large Load Economic Development Report) and 56002 (2025 IRP, DCO-1 / LCOR-1 data-center tariffs), filer = Georgia Power only; georgiapower.com IRP page |
| American Electric Power | Indiana Michigan Power | indianamichiganpower.com IRP page |
| Entergy | Entergy Louisiana | entergylouisiana.com 2027 IRP page + regulatory filings page |
| NextEra Energy | FPL | FPL 2026-2035 Ten Year Power Plant Site Plan (Florida PSC, 04-01-2026), from NextEra's IR site |

Not covered (checked 2026-10-01): AEP Ohio's data-center tariff case (Ohio PUCO DIS sits behind a bot
challenge); Xcel Energy (its resource-plan pages now link Salesforce content-delivery pages that render
only through JavaScript — no direct PDF); Virginia SCC and Louisiana PSC dockets (script-driven search sites — the utilities' own pages carry
the main documents); Eversource, Exelon and the merchant generators (Vistra, Constellation, Talen, NRG) have no
IRP; their data-center contracts come through calls, 8-Ks and IR releases. To add a company or a source: follow
the `_how_to_add` block in sources.json, then `sync --company "<Company>"` and read the skip reasons.

**What is kept / skipped** (by title; every skip is recorded with its reason in `utility_filings/sync_state.json`):
- kept: integrated resource plans and updates, ten-year site plans, load forecasts / data assumptions, large-load
  economic-development reports, large-load / data-center tariffs and electric service agreements, generation /
  transmission certifications and applications, the utility's own IRP stakeholder decks;
- skipped: data requests and responses, errata, notices, motions, briefs, hearing transcripts, fees, access
  paperwork, testimony, and topics outside data-center load (environmental compliance, CCR, hydro, nuclear uprate
  reports, DSM / energy-efficiency potential studies, resilience, storms); anything filed by staff, intervenors
  or the commission (not company-issued); a document whose text never mentions data centers / large load
  ("no data-center / large-load content"); one dated before the window (below).

**Loop**
1. `python -X utf8 utility_filings.py sync` — monthly (the board flags it under `enrich us` after 30 days).
   Window = the ir_pull.py rule: a document dated before the company's latest earnings call in the graph (≤ 120
   days back; no call → 30 days) is skipped; `doc` entries in sources.json are taken once whatever their date.
   Each document is saved twice in `transcripts/utility_filings/`: `<slug>_<date>_<title>.txt` (the whole text,
   page by page) and `<…>_load.txt` (only the pages that mention data centers / large load, and on them only the
   paragraphs and tables about that load). The `_load` file is queued in `utility_filings/pending.json`.
2. `python -X utf8 utility_filings.py pending` — the queue.
3. Enrich each `_load` file (one company's filings to one `enricher` agent; these files are long — ≤ 3 per agent):
   - Read the `_load` file to its last line. Open the full file only to read around a passage the extract cut
     (a table continued on the next page).
   - Capture what the utility states about data-center / large load: contracted or committed MW / GW and the
     number of customers, the pipeline, the load forecast and peak, the generation / transmission additions and
     capital tied to that load, the large-load tariff terms (minimum bill, contract term, collateral, exit fees),
     named customers (only when the filing names them). Forecasts are the company's — attribute them
     ("Georgia Power projects …"); keep the hedge.
   - Never capture intervenor or staff positions quoted in the filing, rate-case revenue requirements, financing,
     or anything outside data-center load.
   - Placement: the utility's node in `components/power_cooling.json` (Utilities & Grid Operators / Generation);
     a named data-center customer that is a node (Meta, Microsoft, Amazon, Google …) → a contract on the
     utility → customer edge only when the filing states the supply relationship.
   - Slots (skill slot table, "Utility regulatory filing"): `guidance` (the company's load / capacity
     forecast or plan), `backlog_or_b2b` (contracted / committed large load, signed ESAs), `supply_status`
     (capacity position, queue), `next_catalyst` (a dated plant / line in service) — never `revenue_growth`.
   - Depth rule: add only what the node does not already state for that period (the call comes first).
   - Label: the file's `# source label:` line verbatim — `<Company> regulatory filing: <short title> (MM-DD-YYYY)`,
     dated the filing (e.g. `Southern Company regulatory filing: Georgia Power Large Load Economic Development
     Report Q2 2026 (08-17-2026)`).
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 utility_filings.py done --label "<label>"` for every handled filing (`--why "no material
   facts"` when it gave nothing); `status [--company …]` lists every saved filing and every skip with its reason.
