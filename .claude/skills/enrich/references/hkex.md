### Hong Kong filings from HKEXnews (`hkex.py`; part of `enrich china`)

Built 2026-10-21 (user-approved new official source). Sixteen graph nodes are listed on the Stock Exchange of Hong
Kong (`company_metadata.json` exchange `HKEX`): ASMPT 00522, Lenovo 00992, Innoscience 02577, Foxconn Interconnect
Technology 06088 (listed as FIT HON TENG), Kingboard Laminates 01888, Biren Technology 06082, SMIC 00981, Hua Hong
Semiconductor 01347, MiniMax 00100, SUNeVision 01686, Tencent 00700, Zhipu AI 02513 (listed as Z.AI), Lightelligence
01879 (XIZHI TECH-P), Time Interconnect Technology 01729, Iluvatar CoreX 09903, Xiaomi 01810. `cninfo.py` covers only
the Shanghai / Shenzhen A-shares, so these names had no filing pipeline. Every company listed in Hong Kong must publish
its documents on **HKEXnews** (www1.hkexnews.hk), the exchange's official disclosure site, the day they are released —
each one is the company's OWN filing (a company document, never an article). A new node with exchange `HKEX` and a
`NNNN.HK` ticker is picked up automatically.

**What is kept / skipped** (decided first by the exchange's own headline categories, then by the title; every skip is
recorded with its reason in `hkex/sync_state.json` → `seen`, and counted per run in `runs[].skip_reasons`)
- Kept: results announcements (Final / Interim / Quarterly Results); annual, interim and quarterly reports; business
  and trading updates; inside information and profit alerts; discloseable / major / very substantial / connected and
  continuing connected transactions (also their completion and update notices); transaction circulars; voluntary
  announcements under "Other - Miscellaneous" whose title is about the business (launches, agreements, orders,
  capacity, customers); a listing prospectus (global offering).
- Skipped: monthly returns, next day disclosure returns, proxy forms, constitutional documents, documents on display,
  debt notices, pre-listing drafts (application proofs / PHIPs); **overseas regulatory announcements** (SMIC's and Hua
  Hong's copies of their Shanghai STAR filings — Chinese only, procedural or a duplicate of the HK report); dividends,
  board / personnel, governance, shareholder meetings and their notices (also when they name a transaction), share
  schemes, financing / share capital, buybacks, trading / listing admin, clarifications, litigation, board-meeting
  dates; procedural circulars (mandates, re-election, notification letters); ESG reports; and by title: treasury
  investments (wealth-management products), loans / guarantees / deposit services, H-share full circulation, share
  awards, index inclusion.

**English first.** HKEXnews keeps the English and Chinese versions as separate files (the Chinese one ends `_c.pdf`);
the collector reads the English list. A document published only in Chinese appears there as a one-line `.htm` stub;
then its Chinese file is saved (header `LANGUAGE: Chinese original …`). Almost every document of these sixteen names
has an English version.

**Loop**
1. `python -X utf8 hkex.py sync` — every run (cheap: one list request per company). From 3 days before each company's
   last sync; a company's FIRST sync takes 120 days plus its newest annual report from up to 400 days back (the annual
   report holds the major customers / suppliers disclosure). Saves every new kept document whole (pypdf, page by page,
   verbatim) to `transcripts/hkex/<slug>_<YYYY-MM-DD>_<file no>.txt` and queues it in `hkex/pending.json`. An annual /
   interim report or prospectus longer than 30 pages also gets `<…>_extract.txt` (what is queued; see step 3). A
   document already saved by hand or by `ir_pull.py` (the same HKEXnews file number in a `SOURCE:` line under
   `transcripts/`) or the same PDF bytes is not saved again. `--company "<Company>"` (repeatable) syncs only those
   companies; `--since YYYY-MM-DD` forces a start; `--budget MIN` (default 45) stops a long first sync politely —
   what is left is taken next run.
2. `python -X utf8 hkex.py pending [--company "<Company>"]` — the queue (`kind`: results / update / inside / transaction
   / circular / report / prospectus).
3. Enrich each file under the enrich skill's common rules (parallel `enricher` agents, all of one company's files to one
   agent; reports and circulars are long — at most 3 per agent):
   - Every file is a company-issued document, NOT a transcript (header NOTE): facts (results, segment figures, capacity,
     utilisation, shipments, capex amounts and timing, named customers / suppliers / partners and deal terms that are
     operating facts), the company's own outlook and targets, and management's commentary as attributed statements.
     Never financing terms, the price of an acquisition, governance, officer pay or ESG (§2).
   - **Reports (`report` rows):** read the `_extract` to its last line — financial highlights, the chairman's / CEO's
     statement, the management discussion and analysis whole (also when a company prints its business / financial
     review inside the Directors' report, as Hua Hong does), then the pages elsewhere with major customers /
     suppliers, segment information, capex / capital commitments, R&D, connected-transaction caps, related-party
     transactions, capacity, orders (its `# LOCATED:` line gives the pages). Open the full file (path in the header)
     only to read around a cut table or to check a number. The **major customers and suppliers** paragraph of the
     Directors' report ("the five largest customers accounted for 38% … the largest customer 12%"): a named customer
     that is a node → a `contracts` entry on the edge filer → customer with `type: "annual report customer share"`
     (`"half-year report customer share"` for an interim report — the Exposure tab reads these types); unnamed shares stay
     on the filer's own `quarterly_data`, never mapped to a name.
   - **Results announcements** are the quarter's main source for a company with no call; when an Investing.com call
     exists it comes first and the announcement adds only what the call did not state. The interim / annual report of
     the same period adds only what the results announcement did not state (depth rule §6; a restatement yields
     nothing: `restates <label>`).
   - **Continuing connected transactions** (`transaction` / `circular` rows) are often supply agreements with a parent or
     sister company (FIT ↔ Hon Hai / Foxconn, Kingboard Laminates ↔ Kingboard Holdings, MiniMax's API service agreement,
     SUNeVision ↔ Sun Hung Kai Properties): the counterparty, what is supplied, the annual caps and the historical
     amounts are relationship facts — an AI chain edge through the patch, otherwise a `relations/` row (scope "other",
     §2). Caps are the company's own ceilings, not sales: write them as caps ("annual cap HK$1,200 million for 2027").
   - **Inside information / profit alerts:** the company's own estimate with its hedge ("expects net profit of not less
     than HK$2.8 billion, up more than 200%").
   - **Prospectus:** the Business and Financial Information sections are company facts; the Industry Overview is a
     third-party consultant's report — context only, never an entry.
   - Every entry in English (§8); amounts in the filing's currency and unit (HK$, RMB, US$), no conversion; Chinese names
     mapped to the canonical node.
   - Slots: an `HKEX announcement` / `HKEX circular` is like a TDnet filing — `guidance`, `next_catalyst`,
     `backlog_or_b2b`, `supply_status`; never `revenue_growth`. An annual / interim / quarterly report is like a DART
     periodic report — any slot, the ONE best entry per slot. A prospectus fills no slot (like an SEC prospectus).
   - Label: the file's `# source label:` line verbatim — `<Company> HKEX announcement: <short English title> (MM-DD-YYYY)`
     / `<Company> HKEX circular: <short English title> (MM-DD-YYYY)` / `<Company> annual report: <YYYY or YYYY/YY> Annual
     Report (MM-DD-YYYY)` / `<Company> interim report: <YYYY or YYYY/YY> Interim Report (MM-DD-YYYY)` / `<Company>
     prospectus (MM-DD-YYYY)`, dated the HKEXnews release day (Hong Kong time), e.g. `Kingboard Laminates HKEX
     announcement: Positive Profit Alert (07-30-2026)`, `Tencent interim report: 2026 Interim Report (08-25-2026)`,
     `Lenovo annual report: 2025/26 Annual Report (06-26-2026)` (Lenovo's year ends in March: 2025/26 = Apr 2025 – Mar
     2026, as the report names it).
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 hkex.py done --label "<label>"` for every handled document (`--why "no material facts"` when it gave
   nothing); `status [--company …]` lists every document seen for our companies, its state and title, and each
   company's stock code / HKEXnews stockId / last sync.

**Gotchas**
- Some results announcements were saved earlier by hand or through `ir_pull.py` under other labels (`… press release:
  Interim Results Announcement …`, `… interim results announcement: …`); the collector skips them (`already saved by
  hand: <file>`) — they are enriched under their existing label.
- pypdf turns some Chinese company names in the English PDFs into stray glyphs (`ʮ̡`); the text is kept verbatim as
  extracted — read the English name beside it.
- Reports are long (Lenovo's annual report ~46 MB / 271 pages, Hua Hong's 434 pages with its ESG report bound in); the
  first sync of all sixteen names (2026-10-21) took about 5 minutes and saved 54 documents, 29 of them with an extract.
  The first look takes each company's 2025 annual report even though it is older than 120 days.
- HKEXnews answered directly in testing (2026-10-21). On a 403 / bot page the list and PDF text fall back to Jina
  Reader (`https://r.jina.ai/<url>`; PDF text then arrives without page breaks, noted in the header). Jina cannot read
  the JSONP stock-id answer, so the stockId is asked once per company and kept in the state file.
- A document listed under two of our companies is saved once, for the first one.
