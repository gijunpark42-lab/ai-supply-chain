### Japanese timely disclosures from TSE TDnet (`tdnet.py`; part of `enrich japan`)

Built 2026-10-01 (user: a pipeline for the Japanese companies' TDnet disclosures). Every listed Japanese company
files its results (決算短信), forecast revisions, capex / plant decisions, mid-term plans, major agreements and M&A
on TDnet, the Tokyo Stock Exchange's timely-disclosure network, the day they happen. TSE shows the filings of ALL
companies on one public list, so `tdnet.py` covers every Japanese company in `company_metadata.json` that has a
TSE code (65 today; Asetek, `ASETEK.OL`, is an Oslo listing filed under exchange `OSE` and is not on TDnet).

**The 31-day limit.** TDnet keeps only about 31 days online (Japanese and English lists alike). A first sync can
reach back no further, whatever the company's latest call; a gap of more than ~4 weeks between syncs loses filings
for good (then only the company's own IR site has them — `ir_pull.py` / by hand). The status board asks for a sync
every 3 days.

**What is kept / skipped (by title, in `tdnet.py`; every skip is recorded with its reason in
`tdnet/sync_state.json` → `seen`, and counted per run in `runs[].skip_reasons`)**
- Kept: earnings releases (決算短信, quarterly shipment / sales flash figures), forecast revisions (業績予想の修正 —
  also when the title adds a dividend forecast), results / IR presentations (決算説明会資料, 補足資料), results-meeting
  Q&A records (質疑応答 / 書き起こし), mid-term / management plans (中期経営計画), capex / plant / capacity notices
  (設備投資, 工場, 生産能力, 固定資産の取得), supply / customer / alliance agreements (契約, 業務提携, 受注, MOU), M&A
  (買収, 子会社の異動, 合併, 会社分割, 事業譲渡, 公開買付, 出資, a completed spin-off).
- Skipped: corrections (訂正), results-date / delay notices, one-off gains / losses (投資有価証券売却益, 特別損益, 減損 —
  a forecast revision that names them is still kept), dividends, buybacks / treasury stock, stock compensation /
  stock options, officer changes, governance / internal control / audit, shareholder meetings, ESG / CSR, financing
  (bonds, loans, share issues, ratings), listing / share administration, monthly routine reports, and anything
  else ("other notice type" — investigation reports, litigation, shareholder changes, media-report responses).
  An alliance or acquisition title is never skipped for also naming treasury stock or a share issue.

**English first.** TSE's Company Announcements Service lists the English versions companies file (often a few
hours later the same day, under a different document id). A Japanese filing waits 2 days for an English version
of the same type from the same company (within 7 days); when one exists only the English one is saved, otherwise
the Japanese text is saved (its header says so). Pairs are one-to-one. An English version filed after its
Japanese one was already saved is skipped (`Japanese version … already saved`), so nothing is enriched twice.
Some English versions are summaries rather than full translations — the label still points to that file.

**Loop**
1. `python -X utf8 tdnet.py sync` — lists the days still online (from 3 days before the last sync; on a company's
   first sync from its latest earnings call in the graph, at most 120 days, else 30 days — capped by TDnet's 31),
   saves every new kept filing of our companies whole (pypdf) to
   `transcripts/tdnet/<slug>_<YYYY-MM-DD>_<doc id>[_qa].txt` and queues it in `tdnet/pending.json`. A document id is
   never saved twice; identical PDFs are caught by hash; an image-only PDF is skipped. `--company "<Company>"`
   (repeatable) syncs only those companies (it does not move the shared last-sync date); `--since YYYY-MM-DD` forces a start.
2. `python -X utf8 tdnet.py pending [--company "<Company>"]` — the queue (`kind`: `filing` or `qa`).
3. Enrich each file under the enrich skill's common rules (parallel `enricher` agents, split by company):
   - A filing is a company-issued document, NOT a transcript (header NOTE): facts (results, segment figures,
     capacity, capex amounts and timing, plant locations and start dates, named counterparties and deal terms
     that are operating facts) and the company's own forecasts and plan targets. Never the price of an acquisition
     or financing terms (§2).
   - A `_qa` file is a results-meeting Q&A record: management answers are management views (like a conference
     talk); the questions are analysts — context only.
   - Japanese text: every entry in English (§8); yen stays yen in English ("JPY 12.3 billion", "JPY 1,234
     million" — write the unit the filing uses, no conversion).
   - Depth rule (§6): the earnings call (Investing.com, `enrich intl`) is primary when there is one; a 決算短信 of the
     same quarter then adds only what the call did not state. For companies with no call the 決算短信 is the main
     source of the quarter.
   - Slots (skill slot table, "TDnet filing"): same as an IR release / deck — `guidance` (a forecast or plan
     target), `next_catalyst`, `backlog_or_b2b`, `supply_status`; never `revenue_growth`. A `_qa` record follows
     the call / conference row (`utils/check_patch.py` tells them apart by the `_qa.txt` file name).
   - Label: the file's `# source label:` line verbatim — `<Company> TDnet: <short English title> (MM-DD-YYYY)` for
     an English version, `<Company> TDnet: release <doc id> (MM-DD-YYYY)` for a Japanese one, dated the
     disclosure day (e.g. `MEC TDnet: Additional Capital Investment (09-30-2026)`,
     `Ferrotec TDnet: release 140120260915536876 (09-17-2026)`).
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 tdnet.py done --label "<label>"` for every handled filing (`--why "no material facts"` when it
   gave nothing); `status [--company …]` lists every filing seen for our companies, its state and title.
