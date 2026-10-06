### Japanese statutory reports from the FSA's EDINET (`edinet.py`; step 1c of `enrich japan`)

Built 2026-10-04 (user-approved: Japan's equivalent of `dart.py`). Every listed Japanese company files its statutory
reports with the Financial Services Agency on EDINET:

| EDINET document | docTypeCode | When (March-year company / December-year company) | What it gives |
|---|---|---|---|
| 有価証券報告書 — **annual securities report** | 120 (amended 訂正: 130) | late June / late March | the whole year: 事業の内容, 主要な相手先別の販売実績 (named customers with % of sales), 生産・受注・販売の実績, 設備投資 + 設備の新設・除却等の計画 (capex plans, plant by plant), 研究開発活動, 経営方針・対処すべき課題, management's analysis (MD&A), the statements and notes |
| 半期報告書 — **semi-annual report** | 160 (amended: 170) | mid-November / mid-August | the first half: management's analysis, material contracts, the half-year statements. Since April 2024 it replaces the Q2 quarterly report; Q1 / Q3 quarterly reports no longer exist (the TDnet 決算短信 carries those quarters) |

`edinet.py` covers every Japanese company in `company_metadata.json` with a TSE code (the same universe as `tdnet.py`).
EDINET keeps 10 years of filings, so — unlike TDnet — a late sync loses nothing.

**The API key.** Every EDINET API call needs a free key: register at
https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1 (the page opens a pop-up) and put `EDINET_API_KEY=<key>` in `.env`.
Without it every network command stops with those instructions, `enrich japan` skips this step, and the status board
lists it under "Needs a decision or setup". `codes`, `pending`, `done` and `status` work without a key.

**Loop**
1. `python -X utf8 edinet.py sync` — weekly is enough (the board asks after 7 days). It walks EDINET's daily lists from
   3 days before the last sync (a company's first sync: 120 days back — the last annual-report season) and saves every
   new annual / semi-annual report (and amendment) of our companies. Each report is saved twice in `transcripts/edinet/`:
   - `<slug>_<YYYY-MM-DD>_<docID>.txt` — the WHOLE report: every section of the filed inline-XBRL HTML in order (tables
     flattened to `a | b | c` rows; the PDF, page by page, when a report has no XBRL), kept for verification;
   - `<…>_extract.txt` — only the key sections: 事業の内容, 経営方針・経営環境及び対処すべき課題, 経営者による財政状態…の分析
     (with 生産・受注及び販売の実績 and 主要な相手先別の販売実績), 重要な契約 / 経営上の重要な契約等, 研究開発活動, the whole
     設備の状況 chapter, then every other passage that names major customers (e.g. 主要な顧客ごとの情報 in the segment
     notes, 特定の顧客への依存 in the risk factors). The extract is what is queued in `edinet/pending.json`.
   An amended report (訂正, `amended …` label) is short — it has no extract and the full file is queued.
   Skipped and recorded with the reason in `edinet/sync_state.json`: a withdrawn or undisclosed report, a report
   `ir_pull.py` already saved from the company's IR site (same EDINET document id in the URL), identical text.
   `--company "<Company>"` (repeatable) syncs only those companies; `--since YYYY-MM-DD` forces a start.
2. New Japanese node, or a backfill: `python -X utf8 edinet.py fetch "<Company>"` saves its newest annual AND newest
   semi-annual report (`--latest`: only the newest one; `--days N`: how far back to look, default 400).
3. `python -X utf8 edinet.py pending [--company "<Company>"]` — the queue (`kind`: annual / semi-annual / amended …).
4. Enrich each row under the enrich skill's common rules (parallel `enricher` agents, all of one company's reports to one
   agent; these files are long — at most 3 reports per agent):
   - Read the `_extract` to its last line. Open the full file (path in the header) only to read around a passage the
     extract cut, or to check a number. Never summarise or sample (the dart.md read-every-line rule, applied to the
     extract).
   - A statutory report is a company document, NOT a transcript (header NOTE): facts, the company's own plans and
     targets, and management's own analysis (attributed: "management states …"). Never financing terms, governance,
     officer pay or ESG (§2).
   - **主要な相手先別の販売実績 / 主要な顧客ごとの情報 (major customers):** each named customer with its share of sales →
     a `contracts` entry on the edge filer → customer when the customer is a node and that edge exists (add the edge only
     under JOB 4's rules), with `type: "annual securities report customer share"` (`"semi-annual report customer share"`
     for a semi-annual report) — the Exposure tab reads these types. `value` = the sales amount and the % exactly as the
     table states ("JPY 512,345 million; 21.1% of net sales"); `units` = the fiscal year; `date_signed`: "not stated".
     Customer not a node → `quarterly_data` on the filer's company-wide placement with `counterparty` and
     `counterparty_role: "customer"` keys ("Customer TSMC: 21.1% of FY2026 net sales"). Map the name to the canonical
     node (`台湾積体電路製造` / `Taiwan Semiconductor Manufacturing Company Ltd.` → `TSMC`); never add a Japanese-named
     duplicate; a new company only through JOB 3. Both years of the table are facts; the previous year usually restates the
     prior report — add it only when the node does not already hold it. The verifier finds the customer through the
     node name and its aliases (`verify_graph.KO_ALIASES`); a Japanese / katakana spelling it does not know gives a
     `counterparty_not_in_source` warn — put the spelling in the report so the coordinator adds the alias.
   - **生産・受注・販売の実績** (production, orders received, order backlog, sales by segment) → `quarterly_data`; order
     backlog = `backlog_or_b2b`. **設備投資 / 設備の新設計画** (capex of the year, each planned plant with its amount, start
     and completion) → `quarterly_data` (`supply_status` / `next_catalyst` where a dated capacity addition is stated).
     **研究開発活動** → new products / generations (topics `product_launches` / `transitions` where they fit).
     **経営方針・対処すべき課題** → company targets (`guidance`).
   - Japanese text: every entry in English (§8). Yen stays yen, in English, in the unit the report uses
     ("JPY 152,345 million", "JPY 3 trillion") — no conversion, never `百万円`. Company names → the canonical node.
   - Slots: a statutory report is like a DART periodic report (skill slot table) — any slot, the ONE best entry per slot.
     An amended report fills a slot only when it corrects that very figure.
   - Depth rule (§6): the earnings call (Investing.com) and the TDnet 決算短信 come first; the report adds only what the
     node does not already state for that period — named customers and their shares, capex plans by plant, order
     backlog, R&D, targets. A restatement yields no entry (`restates <label>`).
   - Label: the file's `# source label:` line verbatim — `<Company> annual securities report: FY<YYYY> (MM-DD-YYYY)` or
     `<Company> semi-annual report: H1 FY<YYYY> (MM-DD-YYYY)` (amended: `<Company> amended …`), dated the filing day; FY =
     the year the fiscal year ENDS in (a March year Apr 2025 – Mar 2026 = FY2026, the same convention as the calls).
5. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
6. `python -X utf8 edinet.py done --label "<label>"` for every handled report (`--why "no material facts"` when it gave
   nothing); `status [--company …]` lists every report seen for our companies, its state and title.
