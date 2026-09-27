### Workflow 2b — Korean companies via DART (한국 회사)

Korean listed names (SK Hynix, Samsung, Samsung Electro-Mechanics, Hanmi Semiconductor, HD Hyundai
Electric, LS Electric, Simmtech, Daeduck, Soulbrain, Dongjin Semichem, Wonik IPS, Jusung, PSK,
Leeno, ISC, Techwing, EO Technics, Gaonchips, AD Technology, Doosan Enerbility, Hyosung Heavy,
Sanil Electric, Isu Petasys, Mirae Industry, Naver …) have no Motley Fool transcript. Their source
documents are DART filings. Three kinds matter, each on its own clock (verified on 산일전기 2Q26):

| DART filing | When | Goes to | What it gives |
|---|---|---|---|
| 영업(잠정)실적(공정공시) — **잠정실적** | earnings day itself (Sanil: 08-07) | `transcripts/dart/<slug>_prelim_<date>.txt` | revenue / OP / NI table, QoQ + YoY |
| 사업·반기·분기보고서 — **정기보고서** | ~1 week later, ≤45 days after quarter end (Sanil: 08-14) | `transcripts/dart/<slug>_q<N>_<year>_dart.txt` | the full report + full statements |
| 단일판매ㆍ공급계약체결 — **공급계약** | any day, unannounced (Sanil: 06-22, 08-20) | `supply_contracts/<slug>.txt` (one file per company, appended) | customer, amount, % of revenue, period |

So on earnings day only the 잠정실적 numbers can be enriched within the hour; the supply-chain
text (customers, suppliers, backlog) arrives with the 정기보고서 a week or so later. Not every
company files a 잠정실적 (KOSDAQ small caps often don't) — for those, earnings day == 정기보고서 day.

**Universe:** every company in `company_metadata.json` whose `exchange` is KRX/KOSPI/KOSDAQ and
whose ticker is a 6-digit stock code. `dart.py sync` scans the WHOLE DART feed (so 풍산 or any
other Korean filer technically passes by) but keeps ONLY these companies. To cover a new Korean
name (e.g. 풍산), add it to `company_metadata.json` with its stock code — nothing else to configure.
Samsung and Samsung Foundry share 005930 → one filing, fetched once.

**Trigger: the user says `enrich dart`** (no company name — there are dozens of Korean names and
the user will not list them). That one phrase means: run the whole loop below for EVERY new filing.
1. `python dart.py sync` — pulls everything filed on DART since the last sync (the user is on PST;
   DART runs on KST, so "today" simply means everything not yet pulled — `sync` handles the gap).
2. `python dart.py pending` — the queue of saved files that have NOT been enriched yet. Enrich
   every row in it (Step 2), one file at a time, all sections. Never re-enrich a file that is not
   in the queue — the queue is the duplicate guard; `dart/sync_state.json` is the download guard.
3. `python graph_build.py --sync` (this also runs `verify_graph.py` on the labels just applied —
   read its `[fail]`/`[warn]` lines, see Workflow 2), then `python dart.py done` to clear the queue.
4. Report per company: label, what was added (n quarterly_data, n contracts, new edges), and the
   verify result (n pass / n fail, with the reason for each fail).
If the queue is empty after `sync`, say so and stop — do not go looking for more.

**Step 1 — pull (what `enrich dart` runs; manual forms below):**
```
python dart.py corp                     # once; refresh yearly — builds dart/corp_codes.json
python dart.py sync                     # new 잠정실적 / 공급계약 / 정기보고서 for our companies since
                                        #   the last sync; dart/sync_state.json remembers what's saved,
                                        #   dart/pending.json queues what still needs enriching
python dart.py pending / done           # show the enrichment queue / clear it after enriching
python dart.py sync --since 20260801    # backfill from a date
python dart.py fetch --all 2026 2       # bulk-pull one quarter's 정기보고서 for every Korean company
python dart.py fetch "SK Hynix" 2026 2  # one company (quarter 1-4; 4 = 사업보고서)
```
A 정기보고서 file `transcripts/dart/<slug>_q<N>_<year>_dart.txt` holds, in order:
1. header — the exact **source label** to use, rcept_no, filing date, DART URL
2. `## FINANCIAL STATEMENTS` — full BS / IS / CF from `fnlttSinglAcntAll` (연결; 별도 if no consolidated).
   Columns: `account | this period | YTD | same period last year | two years ago`, **KRW (원)**.
   For Q1/Q3 the first amount is the quarter and YTD is cumulative; for H1 and annual read YTD.
3. `## REPORT TEXT` — the whole filing, tables flattened to `a | b | c` rows.

A 잠정실적 file `transcripts/dart/<slug>_prelim_<date>.txt` holds the header + the full text of the
공정공시 (the results table, plus any 첨부/comment the company added).

A 공급계약 file `supply_contracts/<slug>.txt` is one file per company; every 공급계약 공시 is appended
as a `====` block with its own header/label, oldest at the top. The full 공시 text is kept —
계약상대방 (customer, sometimes 비공개), 계약금액, 최근 매출액 대비 %, 계약기간, 판매·공급지역, 조건.

**Step 2 — enrich (Workflow 2, with these Korean-specific rules):**
- **ENGLISH ONLY in the chain.** Every `quarter` / `source` label, `signal`, `figure`, `units`,
  `value`, `type`, `relationship` and `product` you write must contain no Korean characters.
  Translate filing terms as you go: 잠정실적 → "preliminary results", 반기보고서 → "half-year
  report", 분기보고서 → "quarterly report", 사업보고서 → "annual report", 공급계약 → "supply
  contract", 수주잔고 → "order backlog", 신재생 → "renewables", 전력망 → "grid", 가동률 →
  "utilisation", 매출액 대비 → "% of prior-year revenue", 비공개 → "undisclosed". People and
  agencies get romanised names (Park Dong-seok, Korea National Railway). Korean is fine inside the
  source txt files and in this CLAUDE.md — never inside `chains/`. Before finishing, grep the
  entries you added for `[가-힣]` and fix any hit.
- **Never summarise, skim, or sample any DART file — read every line of every file** (정기보고서,
  잠정실적, and every block of a supply_contracts file) before touching the chain. The pipeline
  deliberately saves full text, not extracts; the reading is your job.
- **Source label** = the header's `# source label:` line, e.g. `SK Hynix Q2 FY2026 (08-14-2026)`.
  Korean filers are calendar-year, so FY = calendar year; the date is the FILING date (not quarter-end);
  the 사업보고서 is labelled Q4 of the year it covers (`Samsung Q4 FY2025 (03-15-2026)`).
  A 잠정실적 and the later 정기보고서 for the same quarter carry the same `Q2 FY2026` but different
  dates — both are valid entries; the 정기보고서 entry supersedes for `slot` purposes.
- **잠정실적 →** `quarterly_data` on the company's own node: `revenue_growth` slot (revenue, OP,
  YoY/QoQ % exactly as the table states), `topics: []` unless the company wrote a comment about a
  product. Nothing else — the file has no supplier/customer content.
- **공급계약 →** a `contracts` entry on the edge company → 계약상대방. If that edge doesn't exist
  and the counterparty is already a node, add the edge (JOB 4). If the counterparty is 비공개 /
  not a node, the deal goes on the company's own `quarterly_data` with `slot: backlog_or_b2b`
  and the amount — never invent the customer. Label format for contracts:
  `[Company] DART supply contract (MM-DD-YYYY)` (already written in each block's header). `type` =
  "supply agreement"; `units` = contract term + region; `value` = amount in KRW (and USD/EUR if
  stated) + % of prior-year revenue.
- **Read the ENTIRE filing, every section.** A DART filing is not a call transcript — the
  supply-chain facts are spread across the whole document (사업의 내용, 재무에 관한 사항, 주석,
  이사회/계약 내용, 계열회사, 기타 참고사항 …), and the 주석 (notes) often carry the concrete
  figures (segment revenue, major-customer concentration, purchase commitments, capex in
  progress) that the main sections summarise. Never skim or sample sections. Do not stop at
  `II. 사업의 내용`. If the file is too long for one pass, read it in consecutive chunks until
  the end, then enrich — the pass is complete only when the last line has been read.
  Sections and what they usually yield:
  - `II. 사업의 내용` — 주요 제품 (product mix, % of revenue), 원재료 및 생산설비 (raw-material
    SUPPLIERS by name + purchase amounts = incoming edges; capacity / 가동률 = supply_status),
    매출 및 수주상황 (수주잔고 = backlog_or_b2b, major CUSTOMERS = outgoing edges), 연구개발
    (next-gen products = product_launches / transitions), 기타 참고사항 (contracts, licences).
  - `III. 재무에 관한 사항` + 주석 — 부문별 매출, 주요 고객 매출 비중, 유형자산 취득 (capex),
    건설중인자산, 매입/판매 약정, 우발채무 (long-term supply agreements).
  - `IV~VI. 이사회, 주주, 임원` — usually nothing; still read, JV/투자 결의 can appear here.
  - `VII~IX. 계열회사, 이해관계자 거래, 기타` — related-party supply (e.g. 삼성전자 ↔ 삼성전기),
    material contracts signed after period end.
- Amounts are KRW: keep them in KRW but write them in English (`KRW 27.8 trillion`, `KRW 45,946M`) — do not
  convert to USD, and never paste the Korean (`27조 8,000억원` fails verify's English-only check).
- One fact, one node (enrich skill §6): a company-wide fact from a filing goes on the placement that holds the
  company's company-wide entries — never copy it into every chain the company appears in (one half-year report
  was once written into 14 chains).
- Company names inside the filing are Korean (`SK하이닉스`, `삼성전자`, `한미반도체`). Map to the
  canonical English node name already in the chain (`SK Hynix`, `Samsung`, `Hanmi Semiconductor`);
  never add a Korean-named duplicate.
- A DART filing is the single most reliable source for **who supplies whom in Korea** (원재료
  매입처, 주요 매출처) — it may name a supplier that an earnings call would never mention. Litmus
  test still applies before adding a node.
- Then `python graph_build.py --sync` as usual.

---

