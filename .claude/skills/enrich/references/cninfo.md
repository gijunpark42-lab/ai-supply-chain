### China A-share IR activity records and investor Q&A (`cninfo.py`; part of `enrich china`)

Built 2026-10-01 (user: one pipeline for the Chinese A-share names' own disclosures). Our A-share companies rarely
publish an English earnings call, but management talks to investors in writing all the time. `cninfo.py` collects
two kinds of company documents for every SZSE / SSE company in `company_metadata.json` (market CN) — plus, since
2026-10-04, the statutory periodic reports (`cninfo.py reports`, last section of this file):

1. **IR activity records (投资者关系活动记录表)** — the company's own minutes of an institutional meeting (site visit,
   conference call, results briefing): prepared remarks plus management's answers. SZSE companies file them on
   cninfo's 调研活动 tab (titles vary: "投资者关系活动记录表20260823", "300502新易盛投资者关系管理信息20260911"); SSE
   companies post them on SSE e互动 (and a few file them as cninfo announcements). One file per record:
   `transcripts/cninfo/<slug>_<date>_record_<id>.txt`, PDF text page by page.
   Label: `<Company> IR activity record: <record no., else the date> (MM-DD-YYYY)`, dated the disclosure day —
   e.g. `Innolight IR activity record: 2026-008 (08-23-2026)`.
2. **Investor Q&A answers** — the company's written answers on SZSE 互动易 (irm.cninfo.com.cn) or SSE e互动
   (sns.sseinfo.com). One file per company per answer day: `transcripts/cninfo/<slug>_<date>_qa_<szse|sse>.txt`.
   Label: `<Company> investor Q&A: SZSE Interactive Easy (MM-DD-YYYY)` or `… SSE e-Interactive (MM-DD-YYYY)`.

**What is kept / skipped** (rules in `cninfo.py` FILTERS, copied into `cninfo/sync_state.json` → `filters`; every
skipped item id is recorded there with its reason):
- Records: everything on the 调研活动 tab except IR rules (制度 / 办法); elsewhere only titles that read as minutes
  (RECORD_RE). Event notices ("关于召开 / 参加…业绩说明会的公告"), results, buybacks and governance filings are skipped;
  so are image-only PDFs and a record already saved from the other site (same file hash).
- Q&A: only answers about products, customers, capacity, orders, shipments, demand, revenue / margin,
  sampling / qualification and guidance (KEEP_RE on question + answer). Skipped: stock-price / market-value /
  dividend / buyback / holdings / directors / pay / lawsuits / disclosure / rumour questions unless the answer
  still states an operating fact; non-answers ("不便透露", "商业秘密", "以公告为准", thanks only); answers under 25
  characters; answers of the current China-time day (taken on the next sync, so each day has one file).
- Out of scope: Hong Kong-only listings (ASMPT, Lenovo, Innoscience) — no A-share disclosure; IR releases and
  calls cover them.

**Loop**
1. `python -X utf8 cninfo.py sync` — per company from 7 days before its last sync (first sync: back to its latest
   earnings-call label in the graph, at most 120 days, else 30 days — same rule as `ir_pull.py`). `--company
   "<Company>"` / `--since YYYY-MM-DD` for one name or a backfill. Never re-saves an item id it has handled.
   **SSE limit:** the e互动 feeds show only about the last month, so the board asks for this sync weekly; a
   longer gap loses SSE answers for good (SZSE and cninfo records are searchable by date and can be backfilled).
2. `python -X utf8 cninfo.py pending` — the queue (`kind` = `record` or `qa`).
3. Enrich each file under the enrich skill's common rules (parallel `enricher` agents, all of one company's files
   to one agent):
   - Both kinds are **management Q&A — treat them like an investor-conference talk** (skill §2, slot table):
     the prepared remarks and ANSWERS are the company's statements, written as attributed management comments
     ("Management (IR record): …", "The company said on SZSE Interactive Easy: …") with the hedge kept.
   - The QUESTION is an investor's (records: a fund's; Q&A: anonymous) — context only. A number, customer or
     product that only the question states is not captured; when the answer confirms it, it is the company's.
   - The list of attending institutions in a record is not a fact. Boilerplate ("does not represent a forecast")
     is not a fact.
   - Depth rule: add only what the company's node does not already state for that period (a call, the periodic
     report, an earlier record of the same week often repeat the same remarks — `restates <label>` yields nothing).
   - Slots: like a conference talk — any slot, the ONE best entry per slot (`utils/check_patch.py` classes these
     labels as "call / conference / periodic report").
   - Everything in English (skill §8): translate as you go, RMB stays RMB ("RMB 13.69 billion"), Chinese company
     names map to the canonical English node.
   - Label: the file's `# source label:` line verbatim.
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 cninfo.py done --label "<label>"` per handled file (`--why "no material facts"` when it gave
   nothing); `status [--company …]` lists every saved file, its queue state and each company's last sync.

### China A-share periodic reports (`cninfo.py reports`; step 1d of `enrich china`)

Built 2026-10-04 (user-approved: the graph needs each A-share company's top-5 customers / suppliers, capacity,
construction in progress, R&D and MD&A, which only the statutory reports state). Every SZSE / SSE company files
them on cninfo (same universe as above; Hong Kong-only listings are out of scope):

| Report | When | What it gives |
|---|---|---|
| 年度报告 — **annual report** | by April 30 (often March / April) | 第二节 key financial data (revenue, net profit, YoY, the four quarters); 第三节 管理层讨论与分析 (MD&A): business and products, 营业收入构成 (segment / product revenue and margin), 产能 / 产量 / 销量 (capacity, output, sales volume), orders won by tender, **主要销售客户和主要供应商情况 (前五名客户 / 前五名供应商: % of sales / purchases, each customer's share, related-party share; named only when the company chooses to)**, 研发投入 (R&D), assets incl. 在建工程, investments and 募投 (raised-fund) projects, 未来发展的展望 / 经营计划 (outlook); the notes: top-5 receivables / prepayments, 重要在建工程项目 (major construction-in-progress projects: budget, progress, completion) |
| 半年度报告 — **half-year report** | by August 31 | the same outline for H1; usually NO top-5 customer table (the notes still give top-5 receivables) |
| 第一 / 第三季度报告 — **quarterly report** | by April 30 / October 31 | short (15–25 pages): the quarter's and year-to-date figures and the reasons for large changes |

**Files** — `transcripts/cninfo_reports/` (its own folder: the status board attributes files to a pipeline by folder):
- `<slug>_<date>_report_<announcement id>.txt` — the WHOLE report, page by page (pypdf; Wingdings tick boxes are
  turned back into `√`). This is what `verify_graph.py` checks numbers against.
- `<…>_extract.txt` (annual / half-year only) — what the enricher reads: 第二节 from 主要会计数据和财务指标, the whole
  第三节 管理层讨论与分析, and the pages elsewhere (before the parent-company notes, which repeat the group's) that hold
  top-5 customers / suppliers, top-5 receivables / prepayments, 重要在建工程项目, 募投项目, other major contracts or
  capacity. Its `# LOCATED:` header line lists the page of each of those items and what the extract does not contain
  (a half-year report: "Not in the extract: top-5 customers, …"). Roughly 30–85 of 180–330 pages.
- Both files declare the same `# source label:`; a quarterly report has no extract (the queue points at the whole file).

**Label:** `<Company> annual report: <YYYY> Annual Report (MM-DD-YYYY)`, `<Company> half-year report: <YYYY> Half-Year
Report (MM-DD-YYYY)`, `<Company> quarterly report: <YYYY> Q1|Q3 Report (MM-DD-YYYY)` — YYYY = the fiscal (calendar)
year, dated the disclosure day; the same shape as the reports saved by hand before 2026-10-04 (e.g. `Cambricon
half-year report: 2026 Half-Year Report (08-08-2026)`). `utils/check_patch.py` classes them as statutory statements.

**What is kept / skipped** (`cninfo.py` REPORT_FILTERS, copied into `cninfo/reports_state.json` → `filters`; every
skipped announcement id is recorded there with its reason):
- kept: the full Chinese report. One per company, kind and fiscal year: the original; a corrected re-issue
  (更正后 / 更新后 / 修订) only when the original is not listed; the English version only when it is the only full one.
- skipped: 摘要 summaries and notices about a report (更正公告, 业绩说明会 …); audit / internal-control / ESG reports;
  a report already saved — by this pipeline, or by hand before 2026-10-04 (any `transcripts/` file whose `# source
  label:` names the same company, kind and fiscal year: most 2026 half-year reports were saved and enriched that way);
  image-only or unreadable PDFs.

**Loop**
1. `python -X utf8 cninfo.py reports` — weekly, with `cninfo.py sync` (the board asks after 7 days: "China
   periodic-report sync"). A company's FIRST look takes only its newest annual and half-year report, plus the newest
   quarterly report when it is newer than both (on 2026-10-04: the 2025 annual + the 2026 half-year report); later
   runs take every report filed since the last run (from 7 days before it). `--company "<Company>"` for one name;
   `--since YYYY-MM-DD` takes every report filed since then (older history). About 30 s per annual report.
2. `python -X utf8 cninfo.py pending` — `report` rows: `file` = the `_extract` (or the whole quarterly report),
   `full` = the whole report.
3. Enrich — parallel `enricher` agents, one company's reports to one agent, at most 3 reports per agent (they are
   long). Read the extract to its last line; open the full file only to finish a table the extract cut, or a page
   the `# LOCATED:` line points at. Rules on top of the enrich skill's:
   - A **company statutory report, not management Q&A**: like a DART periodic report (skill slot table: statutory
     financial statements — any slot, the ONE best entry per slot). Facts, and the company's own outlook / 经营计划
     as attributed company guidance with its hedge. The MD&A's industry background (报告期内公司所处行业情况) describes
     the market, not the company — no entry unless it states a company fact.
   - Capture: revenue / net profit and their YoY, the quarterly split; segment / product revenue and gross margin;
     capacity, output and sales volume; orders won; the top-5 customers / suppliers; construction in progress and
     the major CIP / raised-fund capacity projects (budget, progress, expected completion → `next_catalyst` when
     dated); R&D spend and its share of revenue; new products and qualifications the report states.
   - **Top-5 customers** (the reason this pipeline exists):
     - a NAMED customer that is a node → a contract on the edge filer → customer, `type` `annual report customer
       share` (half-year report: `half-year report customer share` — the Exposure tab reads exactly these),
       `value` "<x>% of <year> sales (RMB …)", `units` "no specific figure", `date_signed` the fiscal year; on the
       existing edge, or a new edge when both are nodes (JOB 4: a filed customer relationship is explicit).
     - a named customer that is not a node → JOB 3 (independent verifier); rejected or asked → `quarterly_data` on
       the filer with `counterparty` / `counterparty_role: "customer"`.
     - UNNAMED customers (客户一 / 客户 A / 第一名) → `quarterly_data` on the filer only — one entry with the top-5
       total, each listed share and the related-party share, e.g. "Top five customers were 75.98% of 2025 sales; the
       largest 24.06%; names not disclosed; 8.10% of sales from a related party among them". **Never map an unnamed
       customer to a name** (not even when an IR record or the press suggests who it is), and no `counterparty` key.
     - Suppliers the same way, on the supplier → filer edge with `type` `annual report supplier share` /
       `half-year report supplier share` (not a customer-concentration fact, so Exposure does not list it);
       unnamed suppliers → the filer's `quarterly_data`.
     - Top-5 receivables (期末余额前五名的应收账款) are a share of RECEIVABLES, not of sales — say so, or leave them
       out when the sales table exists.
   - **Amounts in English, in a form `verify_graph.py` can check:** from a 元 table write the figure naturally
     ("RMB 38.24 billion", "RMB 29,055,570,800.33") — verify rescales; a figure printed in 万元 / 亿元 / 万只 keeps
     its printed digits ("RMB 955,022.58 ten-thousand", "RMB 66.91 hundred million", "2,806 ten-thousand units") —
     verify_graph.py does not convert 万 / 亿, so "RMB 9.55 billion" for 955,022.58万元 fails.
   - Same-day annual and Q1 report (common in late April): only one of the two labels may fill a given slot
     (`check_patch.py` refuses two same-slot entries on one date) — the Q1 report is the newer period.
   - Depth rule: add only what the node does not already state for that period (an IR record, a Q&A answer or the
     earlier quarterly report may have said it — `restates <label>`). English only (skill §8); 中际旭创 = Innolight,
     新易盛 = Eoptolink, 亨通光电 = Hengtong Optic-Electric — map every Chinese name to the canonical node.
   - Label: the file's `# source label:` line verbatim.
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 cninfo.py done --label "<label>"` per handled report (`--why "no material facts"` when it gave
   nothing); `cninfo.py status [--company …]` lists the saved reports and each company's last report run.
