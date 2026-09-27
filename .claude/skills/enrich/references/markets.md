### Market commands — one command per home market (`enrich us`, `enrich korea`, …)

Added 2026-09-26 (user: one `enrich us` a day should fill everything missing in the US except 10-Q / 8-K, and
`enrich korea` should do Korea in one go; the status board says which one to run). A market command runs every
source that serves that market, in the order the depth rules need — calls first, then the sources that add only
what the call did not say — and rebuilds the graph and the board once. A company's market comes from its
`exchange` in `company_metadata.json` (`taxonomy.market_of`: US, KR, TW, JP, EU, CN, other).

**Frame shared by every market command**
0. Read `ENRICH_STATUS.md` (refresh it if stale). The market's **Run next** line and its **Details** section are
   the to-do list: waiting files, overdue calls, never-enriched companies, known gaps.
1. Collect (scripts, cheap): the market's own collectors below, plus the shared ones when the board calls them
   due — IR feeds (`python ir_pull.py sync`, every market at once) and the conference listing
   (`python investing.py conferences`). Shared collectors fetch for everyone; enrich only this market's rows and
   leave the others pending — the board then shows them under their own market.
2. Enrich in this order: calls → filings → conference talks → IR releases, each under the enrich skill's common
   rules. **Parallel by default: up to 20 `enricher` agents** (fewer for a small queue — about one agent per 2–5
   sources), split by company so one company never spans two agents; every patch passes
   `python -X utf8 utils/check_patch.py <patch>` before it is applied.
3. New companies the agents propose (skill JOB 3): the coordinator dedupes the proposals and sends them to a
   separate `enricher` verifier (approve / reject without asking / ask the user); adds the approved ones to
   `company_metadata.json`; records each ambiguous one with `enrich_status.py ask`; names all of them in the report.
4. Board gaps (overdue / never enriched): try the market's fetch; when nothing exists, the coordinator records it —
   `python -X utf8 enrich_status.py mark "<Company>" --source call --why "<what was checked>"`.
5. Apply once: `python graph_build.py --sync`; read the verify lines, fix, re-run until 0 fail.
6. Close ONLY this market's queue rows (commands below); append the applied labels to `verify_queue.json`
   (Opus verifier at 5+).
7. If anything is left, `python -X utf8 enrich_status.py note <market> "<where it stopped>"`; paste the board's
   Run next block into the report. Too much for one run (earnings season)? Newest first, stop cleanly, note it —
   the board carries the rest to the next run.

## `enrich us` — daily. SEC filings are NOT part of it: `enrich edgar`, weekly.
1. Calls: `python av.py sync` → `python av.py pending` → enrich every row (references/us.md). A call Alpha
   Vantage has not posted (`waiting`) or a `QUOTA` stop: `python utils/defeatbeta_fetch.py "<Canonical Name>" <TICKER>`
   (same file format and label, no quota).
2. Board gaps: every US company overdue for a call or never enriched → `utils/defeatbeta_fetch.py`; nothing there
   → mark it (`--why "not on Alpha Vantage or defeatbeta (checked <date>)"`).
3. Conference talks: `python investing.py pending --kind conference --market US` → references/conferences.md.
4. IR releases: `python ir_pull.py pending --market US` → references/ir.md (important releases only).
5. `python graph_build.py --sync`, then `python av.py done`, `python investing.py done --kind conference --market US`,
   and `python ir_pull.py done --label "<label>"` for every handled release (with `--why` when it gave nothing).

## `enrich korea`
1. DART: `python dart.py sync` → `python dart.py pending` → enrich every file (references/dart.md: read every line,
   English only).
2. Board gap "no DART filing enriched" (mostly new Korean nodes): fetch each one's latest periodic report —
   `python dart.py fetch "<Company>" <year> <quarter 1-4>` — and enrich it (≤ 10 reports per agent; they are long).
2b. IR presentations and calls: `python kind.py sync` (the KRX KIND library — 34 of our Korean companies post decks
   there — plus six large-cap IR sites: Samsung's official call script and the SK Hynix / SEMCO / LG Innotek / NAVER /
   SK Telecom results decks) → `python kind.py pending` → enrich every row (references/kind.md; a `call` row is a
   transcript, a `deck` row a company document) → `python kind.py done --label "<label>"` each.
3. Other Korean earnings calls: none is published as a transcript (only Samsung's script, taken in 2b); the board
   explains it under "Needs a decision or setup". A call the user pastes is enriched as usual — label = the call
   date; the DART report of the same quarter keeps its own filing date.
4. Conference talks: `python investing.py pending --kind conference --market KR`.
5. IR releases: `python ir_pull.py pending --market KR`. Korean results releases are KEPT (US ones are skipped):
   with no call pipeline they are often the only place the company's own outlook and commentary appear — add only
   what the DART preliminary results do not already state.
6. `python graph_build.py --sync`, then `python dart.py done`, `python investing.py done --kind conference --market KR`,
   `python ir_pull.py done --label "<label>"` per handled release.

## `enrich taiwan`
1. English-language calls: `python investing.py sync` → `python investing.py pending --kind transcript --market TW`
   (references/intl.md — at most the 2 most recent quarters per company).
2. Chinese-language calls (tw.py `COMPANIES`): `python tw.py sync` → `python tw.py transcribe` (slow: run it
   detached / overnight) → `python tw.py pending` (references/tw.md — the transcript has no speaker labels).
3. Board gaps: a company on neither Investing.com nor tw.py's list → mark it once checked.
4. Conference talks (`--kind conference --market TW`), IR releases (`ir_pull.py pending --market TW`; Chinese
   headlines are labelled `release <id>` — write the entries in English).
5. `python graph_build.py --sync`, then `python investing.py done --kind transcript --market TW`, `python tw.py done`,
   `python investing.py done --kind conference --market TW`, `ir_pull.py done --label …` per handled release.

## `enrich japan` / `enrich europe` / `enrich china`
1. Calls: `python investing.py sync` → `python investing.py pending --kind transcript --market JP|EU|CN`
   (references/intl.md). Calls held only in Japanese / Chinese are not on Investing.com: mark them once checked.
2. Conference talks (`--kind conference --market …`), IR releases (`ir_pull.py pending --market …`; non-English
   headlines → `release <id>` labels; entries in English).
3. `python graph_build.py --sync`, then `python investing.py done --kind transcript --market …`,
   `python investing.py done --kind conference --market …`, `ir_pull.py done --label …` per handled release.

`enrich intl` (source command) = the calls step for every non-US, non-Korean market at once, including the
few "other listed" names (SGX, TSX, ASX, IDX).
