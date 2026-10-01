### China A-share IR activity records and investor Q&A (`cninfo.py`; part of `enrich china`)

Built 2026-10-01 (user: one pipeline for the Chinese A-share names' own disclosures). Our A-share companies rarely
publish an English earnings call, but management talks to investors in writing all the time. `cninfo.py` collects
two kinds of company documents for every SZSE / SSE company in `company_metadata.json` (market CN):

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
