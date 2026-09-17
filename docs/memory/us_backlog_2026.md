---
name: us-backlog-2026
description: 2026-09-16 — DONE (runs 3-5 enriched all) 202 un-enriched 2026 US earnings calls downloaded (full transcripts) and queued in av/pending.json; enrich deferred until the user says so; defeatbeta dataset moved; corpus prefix-match fix
metadata:
  type: project
---

**User request 2026-09-16:** "미국주식들 올해 실적발표했는데 enrich 안한 거 전부 트랜스크립트만 다운로드 … full transcript …
enrich는 나중에 내가 시킬거야". Scope = US-listed graph nodes (NYSE/NASDAQ ticker in company_metadata, `av.universe()`),
every call REPORTED in calendar 2026 whose `<Company> Qn FYyyyy` label is not in the graph.

**Done:** 150 US nodes, 445 calls in 2026 → 242 already enriched, **202 queued** (199 new files in
`transcripts/av/`, Oracle Q3 FY2026 existing Motley Fool file, Intel Foundry Q4 FY2025 sharing Intel's file,
+ AMAT). Queue: `av/pending.json` (gitignored!) — tracked copy with the full list: `docs/US_ENRICH_BACKLOG.md`.
Also added to `av/sync_state.json` "saved" so `av.py sync` won't re-pull them. **Enrichment NOT started** —
wait for the user's `enrich us`.

**Progress 2026-09-16 run 3:** user asked "40개만 처리 + crbs enrich" → the 40 NEWEST rows (make_us_batches.py sorts
by call date desc) + Cerebras Q1/Q2 FY2026 enriched + verified (40+40 agents, ≤20 concurrent), one build, 0 fail.
**162 rows left** in av/pending.json (removed only the processed rows — never `av.py done` for a partial run, it
clears the whole queue). Next batch = the next-newest 40; the backlog doc has a Status column.
Cerebras = NASDAQ: CBRS (listed 2026), node in power_semiconductor.json.
**Run 4 (same day):** next 50 newest rows done the same way (tools: temp `make_us_batches3.py` = rest[:50],
`dequeue3.py`); **112 rows left** (mostly Q4-2025 calls → no `slot`). User raised the subagent cap to 25 via
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` in ~/.claude/settings.json env (needs a restart to apply).

**Gotchas found:**
- **defeatbeta moved its files** to `data/US/…` (old root path 404s, so `defeatbeta_api` 0.0.60 and
  `utils/defeatbeta_fetch.py` are broken). Direct DuckDB works:
  `read_parquet('https://huggingface.co/datasets/defeatbeta/yahoo-finance-data/resolve/main/data/US/stock_earning_call_transcripts.parquet')`
  (cols symbol, fiscal_year, fiscal_quarter, report_date, transcripts[] of {paragraph_number, speaker, content}).
  List-only queries take ~7 s; package 0.0.61 exists but was not installed. Use `py -X utf8` (3.14 has duckdb).
- **Templated stub transcripts exist**: AMAT 2026Q1 on BOTH defeatbeta and Alpha Vantage is a 10.7k-char fake
  ("latest reporting period, 2026Q1", 140-char turns). Full text came from Motley Fool
  (`/earnings/call-transcripts/2026/02/12/applied-materials-amat-q1-2026-earnings-transcript/`). Screen for
  `20\d\dQ[1-4]` / "latest reporting period" in the first turns + total chars < 20k.
- Many 2026-Q1-era defeatbeta transcripts are split into ≤1,000-char paragraphs — that is formatting, not truncation
  (totals 40–70k chars). Photronics calls are genuinely short (~19–20k).
- **agent/corpus.py `find_document_for_label`** matched by the first 7 letters, so "Applied Digital" resolved to the
  Applied Materials file and "Lumentum" to the Lumen file. Fixed: an exact company-token file now wins. Full
  verify_graph before/after: identical (4,936 entries, 0 verdict/file changes).
- Intel Foundry's Q1 FY2026 content sits under the Intel Q1 label — treat Intel Foundry calls as Intel's.

Related: [[feedback_transcript_sourcing]], [[conference_enrichment]], [[naming_rules]].

**Run 5 (same day) — backlog COMPLETE:** last 112 rows via ONE background Workflow (pipeline enrich→verify, 111+111 agents,
effort xhigh, ~40 min, ~23M subagent tokens) — far less coordinator context than hand-launching waves; prefer this
for big batches. av/pending.json is empty. Coordinator must still re-apply standing user rules the verifiers don't
know (e.g. onsemi→Lite-On edge unwanted — a verifier kept it on a fresh onsemi call).
