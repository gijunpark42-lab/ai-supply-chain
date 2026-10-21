### China A-share results briefings — the live text Q&A (`cnbrief.py`; part of `enrich china`)

Built 2026-10-21 (user-approved new official source). After its annual report — and for many companies after the
half-year and Q3 reports too — an A-share company holds a results briefing (业绩说明会): an online event on an
exchange-linked roadshow platform where investors type questions and the company's executives / IR type the answers
live, under their own names. The platform keeps the whole exchange online afterwards. `cnbrief.py` saves it
**verbatim** (Chinese stays Chinese, nothing summarised or filtered inside a briefing) for every SZSE / SSE company in
`company_metadata.json` (market CN; Hong Kong-only listings are out of scope).

**Why it counts as a company document.** The answers are typed by the company's own people during the event, on the
platform the company names in its own cninfo notice (关于召开 / 举行…业绩说明会的公告). The platforms are run by the
exchanges' information companies (SSE Roadshow Center, SZSE 互动易) or are the long-standing roadshow platform SZSE
companies use (全景路演). Like a conference talk (enrich skill §2): the **answers and the company's statements are the
company's words**; the questions come from anonymous retail investors and only frame the answers.

**Same event as cninfo's summary.** `cninfo.py` saves the company's own announcement about the event
(业绩说明会召开情况 / 投资者关系活动记录表 of a 业绩说明会) — a SUMMARY written afterwards. A briefing and its summary
announcement are **one event: enrich it once, from the fuller cnbrief text**. If both are queued, enrich the cnbrief
file and close the cninfo row with `python -X utf8 cninfo.py done --label "<its label>" --why "same event as <cnbrief
label>"`; if the summary was enriched earlier, the briefing adds only what the summary did not state (`restates
<label>` yields nothing).

**Platforms** (public JSON behind the platforms' own pages, no login — endpoints in the `cnbrief.py` docstring)
| Platform | Who uses it | What is read |
|---|---|---|
| SSE Roadshow Center 上证路演中心 (roadshow.sseinfo.com) | most SSE companies, alone or in the SSE's collective briefings (科创板…集体业绩说明会) | every answer with its question and the answering guest (name, title), the company's own statements, the host's lines, and the pre-collected questions (预征集问答) the company answered; the guest panel |
| 全景路演 rs.p5w.net | many SZSE companies, alone or in a regional collective (…辖区投资者网上集体接待日暨业绩说明会) | every line: the questions with the company's replies (`speakUserName` = who answered, e.g. 董事会秘书王诚); in a collective, the company's own room only |
| SZSE 互动易 云访谈 (irm.cninfo.com.cn) | some SZSE companies | the company's postings and every answer with its question and the answerer |

**Coverage (first sync, 2026-10-21, back to 2026-04-01):** 153 events seen, 138 briefings saved (2,229 answered
questions) for 78 of the 103 A-share nodes — 42 of 47 SSE, 36 of 56 SZSE; 82 from the SSE Roadshow Center, 44 from
全景路演, 12 from 互动易; 52 from the H1 2026 season (Aug–Sep), 84 from the 2025 annual season (Apr–Jul), 2 in October.

**Not covered** — briefings on commercial IR platforms: 价值在线 (ir-online.cn / eseb.cn — the page needs an OAuth
login), 进门财经 (comein.cn, mostly audio), 约调研, 路演中 (roadshowchina.cn), roadshow.cnstock.com. Their cninfo notices
name the platform; the companies with no saved briefing for that reason include NAURA, TFC Optical, Dongshan Precision,
Kstar, Zhongheng Electric, Fastprint, Han's CNC, Hengtong (价值在线), Megmeet, Range, Shenzhen Honor, Focuslight (进门财经),
Envicool (约调研), Foxconn Industrial Internet (路演中), FiberHome's H1 (cnstock); others that held one there for a single
season (Inspur, Maxio, CIG) are covered for the other. No briefing found at all: Advanced Fiber Resources, Shennan
Circuits, Jiujiang Defu, Sunlord, ZTE, Woer, Feirongda, Jones Tech, YOFC, Enflame (listed 2026-09). For all of these,
cninfo.py's summary announcement stays the record.

**What is kept / skipped** (`cnbrief.py` FILTERS, copied into `cnbrief/sync_state.json` → `filters`; every event id is
recorded in `seen` with its status and title)
- Kept: results briefings (业绩说明会, 年度报告网上说明会, collective 集体业绩说明会 / 投资者网上集体接待日暨业绩说明会) and other
  investor briefings the company holds (重大事项 / 重大资产重组 / 投资者说明会, a 集体接待日 without a results title) — once
  the event is over. The whole text: answers + questions + who answered, company statements, pre-collected answers, the
  host's lines. In a collective only this company's lines.
- Skipped (reason recorded): IPO / bond / refinancing roadshows, listing ceremonies, lotteries, training, forums
  (financing marketing — the prospectus is the source, §2); an event with no answered question and no company statement;
  the same briefing already saved from another platform (same company, day and period); questions nobody answered
  (counted in the file header, not saved).
- `later:` — an event not held / not over yet, or a fetch that failed: retried by every sync until it is over.

**Loop**
1. `python -X utf8 cnbrief.py sync` — per company from 7 days before its last sync (first sync: 200 days back, so
   the whole annual season (April–June) and the H1 season (August–September) are in; the 2026-10-21 first sync ran with
   `--since 2026-04-01`). SSE companies: SSE Roadshow Center + 全景路演; SZSE companies: 互动易 + 全景路演. One request
   every 1.2 s (each takes 1–4 s; a nightly pass over the 103 companies took 7 min, the first sync 27 min), three tries,
   a 45-minute run-time budget (`--budget MIN`; companies not reached wait for the next sync). `--company "<Company>"`
   (repeatable) syncs only those names (the shared last-sync date does not move); `--since YYYY-MM-DD` forces a start.
   Every night is enough: a briefing is listed days before it happens and stays online.
2. `python -X utf8 cnbrief.py pending [--company "<Company>"]` — the queue (`kind` = `briefing`, with the answer count).
3. Enrich each file under the enrich skill's common rules (parallel `enricher` agents, all of one company's briefings
   and cninfo files to one agent):
   - **Management Q&A — treat it like an investor-conference talk** (skill §2, slot table): the ANSWER lines and
     COMPANY STATEMENT blocks are the company's statements, written as attributed management comments with the
     answering executive when the line names one ("CFO Lin Xiaofeng (results briefing): …", "The board secretary said
     at the H1 2026 results briefing: …") and the hedge kept.
   - The QUESTION is an anonymous investor's — context only. A number, customer or product only the question states is
     not captured; when the answer confirms it, it is the company's. HOST lines yield nothing.
   - Non-answers yield nothing: "请以公司公告为准", "涉及商业秘密", "感谢您的关注", generic strategy lines. Typical facts here:
     capacity / utilisation, order and delivery timing (e.g. NPO volume from 2027), product qualification stages,
     customer qualification, capex projects, pricing mechanisms, the period's figures with their YoY.
   - Depth rule (§6): add only what the node does not already state for that period — the periodic report, an IR
     activity record or the cninfo summary of the same briefing often say the same (`restates <label>`).
   - Everything in English (§8): translate as you go, RMB stays RMB, Chinese company names map to the canonical node
     (中际旭创 = Innolight, 新易盛 = Eoptolink, 长电科技 = JCET …). Traditional characters in an answer are still the answer.
   - Slots: like a conference talk — any slot, the ONE best entry per slot (`utils/check_patch.py` classes these labels
     as "call / conference / periodic report").
   - Label: the file's `# source label:` line verbatim.
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 cnbrief.py done --label "<label>"` per handled briefing (`--why "no material facts"` when it gave
   nothing); `cnbrief.py status [--company …]` lists every event seen, its state and title.

**Label** — `<Company> results briefing Q&A: <period(s)>[ collective] (MM-DD-YYYY)`, dated the briefing day (China
time); the period(s) come from the briefing title (`2025 annual`, `H1 2026`, `Q1 2026`, `Q3 2026`, joined with ` and `),
` collective` for a collective briefing. A non-results briefing: `<Company> investor briefing Q&A: <platform> <event
id> (MM-DD-YYYY)`. Examples: `JCET results briefing Q&A: H1 2026 (08-21-2026)`, `Montage Technology results briefing
Q&A: 2025 annual and Q1 2026 (05-14-2026)`, `Eoptolink results briefing Q&A: H1 2026 collective (09-11-2026)`,
`Shijia Photons investor briefing Q&A: SSE Roadshow 39779 (06-01-2026)`. (The same shape as the Japan results-briefing
exception, `[Company] results briefing Q&A: <title> (MM-DD-YYYY)`.)

**Gotchas**
- Answers are often posted after the event's scheduled end (late that evening): they are part of the record and kept.
- A collective event is read once per company: the SSE `companyId` filter, or the company's own room on 全景路演
  (`multCompanyList`); the label says `collective`.
- 全景路演's lists are 0-based (`page=0` is the newest page); the company search matches the stock code in the
  participant list, so regional collectives appear there too.
- SSE's pre-collected list refuses a page size above 50; its answer list carries `contentEn`, the platform's machine
  translation — never saved (not the company's words).
- 互动易 needs the company's cninfo orgId (`<orgId>_<code>`, from cninfo.py) to list its briefings.
- These are JSON endpoints: Jina Reader cannot replay them, so a blocked endpoint is recorded `later:` and retried.
