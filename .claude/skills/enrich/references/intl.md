### Workflow 2d — Taiwan / Japan / Europe / HK / China via Investing.com (`enrich intl`)

The 88 names whose exchange is neither US nor Korean (Alchip, MediaTek, Nanya Technology,
ASMPT, Tokyo Electron, Advantest, SUMCO, Infineon, ASM International …) hold quarterly calls
but publish no written transcript, and no free API carries them. Investing.com transcribes the
ENGLISH-language calls as articles (full speaker turns + Q&A, ~15–20k words) within a day.
`investing.py` mirrors `dart.py`/`av.py`: `sync` → `pending` → enrich → `graph_build.py --sync` → `done`.
It reaches the site with a Chrome TLS fingerprint (`curl_cffi`) because plain requests get 403 —
public article pages only, one request per second. Fallback if that ever breaks: open the article
in Chrome and paste (Workflow 2) under the same label.

**Trigger: the user says `enrich intl`.**
1. `python investing.py sync` — one site search per company, downloads every transcript not yet
   saved. Prints `saved` / `FAIL`. Takes ~2–3 minutes.
2. `python investing.py pending --kind transcript` — the queue (a market command adds `--market TW|JP|EU|CN`
   and later closes only its rows with `done --kind transcript --market …`). Enrich every row (Workflow 2, JOB 1–5),
   but **at most the 2 most recent quarters per company** — anything older in the queue is marked
   done without enriching (history, not signal). Duplicates never reach the queue: `sync` skips a
   call the graph already carries under another source and same-call repeat articles.
3. `python graph_build.py --sync` (verify_graph runs on the labels just applied), then
   `python investing.py done --kind transcript` (a bare `done` would also clear the conference rows).
4. Report per company: label, what was added, verify result.

**Coverage reality (checked 2026-08-31):** Investing.com has Alchip, MediaTek, ASMPT, Nanya
Technology, Tokyo Electron, Advantest, SUMCO, Infineon, Sivers … It does NOT have the companies
whose calls are held in Chinese/Japanese — Quanta, Wiwynn, Wistron, Unimicron, Foxconn, GlobalWafers,
Yageo, Lasertec. Taiwan's Chinese-language calls are covered by `tw.py` (Workflow 2e, decided 2026-08-31);
MOPS decks and TWSE monthly revenue are not transcripts and are never enrichment sources. Japanese-only
calls have no source: once checked, mark them on the status board (`enrich_status.py mark … --source call`).

File format `transcripts/investing/<slug>_q<N>_<year>.txt`: `SOURCE:` (article URL) / `TITLE:` /
`CALL DATE:` (article publish date) / `QUARTER:` / `# source label:` header, then one paragraph per
speaker turn `Speaker, Title, Company: text`. The first few paragraphs are the article's own summary
("Key Takeaways") — the transcript proper starts after them; enrich from the transcript, not the summary.
A `# note: prepared remarks only` header line means Investing.com did not include the analyst Q&A
(happens for some Japanese calls, e.g. TDK, Advantest) — enrich what is there, don't go looking for more.
**Label FY for Japanese March-FY companies** is derived from the graph's latest label (+1 quarter) or,
with no history, from the article date (Q1/Q2 → FY = year+1; Q3/Q4 → FY = year), NOT from the title —
Investing.com's title years are inconsistent for Japan. Result matches what the graph already carries
(`Tokyo Electron Q4 FY2026 (04-30-2026)` → `Tokyo Electron Q1 FY2027 (07-31-2026)`). A call the graph
already has under another source (Motley Fool era) is skipped, not re-saved.
Manual pull: `python investing.py fetch <article url> [--company "Name"]`.

